"""
Agentic code review activity using tool-use loop.

Replaces the single-shot review_code approach with an iterative agent that:
1. Starts with CodeContext summaries (triage)
2. Uses tools to read actual code and diffs on demand
3. Can escalate to subagents for deep file analysis
4. Manages a 40% context budget with automatic summarization
5. Terminates via submit_review tool call or budget exhaustion
"""
from temporalio import activity
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from utils.dataclasses import (
    CodeContext, ChangeSet, ChangedFile, Hunk,
    ReviewFinding, ReviewResult, FileContext, FileSummary,
    ContextOverview, Totals, FileTypeStats, ContextMetadata,
)
import json


# ---------------------------------------------------------------------------
# Token Budget Management
# ---------------------------------------------------------------------------

@dataclass
class TokenBudget:
    """Tracks cumulative token usage across the agentic loop."""
    model_context_limit: int = 200_000
    budget_fraction: float = 0.40
    auto_route_threshold: float = 0.60   # 60% of budget -> auto-route via subagent
    summarize_threshold: float = 0.80    # 80% of budget -> summarize old context
    input_tokens_used: int = 0
    output_tokens_used: int = 0

    @property
    def budget_limit(self) -> int:
        return int(self.model_context_limit * self.budget_fraction)

    @property
    def total_tokens_used(self) -> int:
        return self.input_tokens_used + self.output_tokens_used

    @property
    def budget_usage_ratio(self) -> float:
        return self.total_tokens_used / self.budget_limit if self.budget_limit > 0 else 0.0

    @property
    def should_auto_route(self) -> bool:
        return self.budget_usage_ratio >= self.auto_route_threshold

    @property
    def should_summarize(self) -> bool:
        return self.budget_usage_ratio >= self.summarize_threshold

    @property
    def budget_exhausted(self) -> bool:
        return self.total_tokens_used >= self.budget_limit

    def update(self, input_tokens: int, output_tokens: int):
        self.input_tokens_used += input_tokens
        self.output_tokens_used += output_tokens


# ---------------------------------------------------------------------------
# Tool Execution Context
# ---------------------------------------------------------------------------

@dataclass
class ToolContext:
    """All state needed by tool handlers."""
    repo_path: str
    change_set_files: dict[str, ChangedFile]  # path -> ChangedFile
    budget: TokenBudget
    files_analyzed: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tool Definitions (Anthropic tool_use format)
# ---------------------------------------------------------------------------

REVIEW_TOOLS = [
    {
        "name": "read_file_snippet",
        "description": (
            "Read a specific range of lines from a file in the repository. "
            "Use this when you need to inspect a particular section of code "
            "(e.g., around a function definition, a suspicious block). "
            "Returns numbered lines."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative path to the file from the repository root",
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to read (1-indexed, inclusive)",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to read (1-indexed, inclusive)",
                },
            },
            "required": ["file_path", "start_line", "end_line"],
        },
    },
    {
        "name": "read_file_diff",
        "description": (
            "Get the diff hunks for a specific changed file. Shows exactly what "
            "lines were added (+) and removed (-) with surrounding context. "
            "Use this as your primary tool when reviewing a file's changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative path to the changed file",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "read_full_file",
        "description": (
            "Read the entire contents of a file. Only use this for small files "
            "(under ~200 lines) where you need the full context. "
            "For larger files, prefer read_file_snippet."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative path to the file from the repository root",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "request_deep_analysis",
        "description": (
            "Request a focused deep analysis of a specific file by a specialist. "
            "Use this when a file is complex, large, or requires domain-specific "
            "analysis. You provide a specific question or focus area, and receive "
            "structured findings back. Especially useful for high-risk files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Relative path to the file to analyze",
                },
                "focus_question": {
                    "type": "string",
                    "description": (
                        "Specific question or focus area for the analysis. "
                        "E.g., 'Check for SQL injection in the query builder' "
                        "or 'Verify error handling covers all edge cases'"
                    ),
                },
            },
            "required": ["file_path", "focus_question"],
        },
    },
    {
        "name": "submit_review",
        "description": (
            "Submit the final code review. Call this when you have completed "
            "reviewing all files you intend to review. Provide a summary, any "
            "high-level warnings, and all individual findings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Executive summary of the review (2-3 sentences)",
                },
                "warnings": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "High-level warnings or concerns",
                },
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "line_number": {"type": "integer"},
                            "severity": {
                                "type": "string",
                                "enum": ["critical", "high", "medium", "low"],
                            },
                            "category": {
                                "type": "string",
                                "enum": ["bug", "security", "performance", "style"],
                            },
                            "title": {"type": "string"},
                            "evidence": {"type": "string"},
                            "suggestion": {"type": "string"},
                            "confidence": {"type": "number"},
                        },
                        "required": [
                            "file_path", "line_number", "severity",
                            "category", "title", "evidence",
                            "suggestion", "confidence",
                        ],
                    },
                    "description": "List of individual code review findings",
                },
            },
            "required": ["summary", "warnings", "findings"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool Handlers
# ---------------------------------------------------------------------------

def handle_read_file_snippet(tool_input: dict, ctx: ToolContext) -> str:
    file_path = tool_input["file_path"]
    start_line = max(1, tool_input["start_line"])
    end_line = tool_input["end_line"]

    full_path = Path(ctx.repo_path) / file_path
    if not full_path.exists():
        return f"Error: File not found: {file_path}"

    # Cap range at 300 lines
    if end_line - start_line > 300:
        end_line = start_line + 300

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
    except (UnicodeDecodeError, IOError) as e:
        return f"Error reading file: {e}"

    start_idx = start_line - 1
    end_idx = min(len(all_lines), end_line)

    numbered = []
    for i, line in enumerate(all_lines[start_idx:end_idx], start=start_line):
        numbered.append(f"{i:>4} | {line.rstrip()}")

    if file_path not in ctx.files_analyzed:
        ctx.files_analyzed.append(file_path)

    return "\n".join(numbered) if numbered else "No lines in the specified range."


def handle_read_file_diff(tool_input: dict, ctx: ToolContext) -> str:
    file_path = tool_input["file_path"]

    changed_file = ctx.change_set_files.get(file_path)
    if not changed_file:
        return f"Error: No diff found for file: {file_path}. It may not have been changed."

    lines = [
        f"Diff for: {file_path}",
        f"Lines added: +{changed_file.added}, removed: -{changed_file.removed}",
        "",
    ]

    for i, hunk in enumerate(changed_file.hunks):
        lines.append(f"--- Hunk {i + 1} (starting at line {hunk.start}) ---")
        for diff_line in hunk.lines:
            lines.append(diff_line)
        lines.append("")

    if file_path not in ctx.files_analyzed:
        ctx.files_analyzed.append(file_path)

    return "\n".join(lines)


def handle_read_full_file(tool_input: dict, ctx: ToolContext) -> str:
    file_path = tool_input["file_path"]

    full_path = Path(ctx.repo_path) / file_path
    if not full_path.exists():
        return f"Error: File not found: {file_path}"

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (UnicodeDecodeError, IOError) as e:
        return f"Error reading file: {e}"

    file_lines = content.split("\n")
    line_count = len(file_lines)
    result_lines = [f"File: {file_path} ({line_count} lines)", ""]

    if line_count > 500:
        for i, line in enumerate(file_lines[:500], start=1):
            result_lines.append(f"{i:>4} | {line}")
        result_lines.append(
            f"\n... [TRUNCATED: file has {line_count} lines, showing first 500. "
            f"Use read_file_snippet for specific sections.]"
        )
    else:
        for i, line in enumerate(file_lines, start=1):
            result_lines.append(f"{i:>4} | {line}")

    if file_path not in ctx.files_analyzed:
        ctx.files_analyzed.append(file_path)

    return "\n".join(result_lines)


def handle_request_deep_analysis(tool_input: dict, ctx: ToolContext) -> str:
    file_path = tool_input["file_path"]
    focus_question = tool_input["focus_question"]

    full_path = Path(ctx.repo_path) / file_path
    if not full_path.exists():
        return json.dumps({"error": f"File not found: {file_path}", "findings": []})

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            file_content = f.read()
    except (UnicodeDecodeError, IOError) as e:
        return json.dumps({"error": f"Cannot read file: {e}", "findings": []})

    # Build diff text from ChangeSet
    changed_file = ctx.change_set_files.get(file_path)
    diff_text = ""
    if changed_file:
        diff_lines = []
        for hunk in changed_file.hunks:
            diff_lines.append(f"@@ starting at line {hunk.start} @@")
            diff_lines.extend(hunk.lines)
        diff_text = "\n".join(diff_lines)

    findings = _run_deep_analysis_subagent(
        file_path=file_path,
        file_content=file_content,
        diff_text=diff_text,
        focus_question=focus_question,
    )

    if file_path not in ctx.files_analyzed:
        ctx.files_analyzed.append(file_path)

    return json.dumps(findings)


TOOL_HANDLERS = {
    "read_file_snippet": handle_read_file_snippet,
    "read_file_diff": handle_read_file_diff,
    "read_full_file": handle_read_full_file,
    "request_deep_analysis": handle_request_deep_analysis,
    # submit_review is handled specially in the loop
}


# ---------------------------------------------------------------------------
# Deep Analysis Subagent
# ---------------------------------------------------------------------------

_SUBAGENT_SYSTEM_PROMPT = """You are a specialist code reviewer performing deep analysis on a single file.

You will receive:
1. The full file content
2. The diff hunks showing what changed
3. A specific question or focus area

Your job is to deeply analyze this file with respect to the focus question.

Output ONLY valid JSON:
{
  "summary": "Brief summary of your analysis",
  "findings": [
    {
      "file_path": "exact/file/path.py",
      "line_number": 42,
      "severity": "high",
      "category": "bug",
      "title": "Short description",
      "evidence": "exact code snippet from the file",
      "suggestion": "specific fix recommendation",
      "confidence": 0.9
    }
  ]
}

Rules:
- Only report real issues with evidence from the actual code
- Focus specifically on the question asked
- If no issues found, return empty findings with a summary stating the code looks good
- Evidence must be actual code from the file"""


def _run_deep_analysis_subagent(
    file_path: str,
    file_content: str,
    diff_text: str,
    focus_question: str,
) -> dict:
    """
    Run a focused deep analysis on a single file using a fresh API call.
    Returns a dict with 'summary' and 'findings' keys.
    """
    from anthropic import Anthropic

    client = Anthropic()

    user_message = (
        f"## File: {file_path}\n\n"
        f"### Full File Content:\n```\n{file_content}\n```\n\n"
        f"### Diff Hunks (what changed):\n```\n"
        f"{diff_text if diff_text else 'No diff available - this may be a dependency file'}"
        f"\n```\n\n"
        f"### Focus Question:\n{focus_question}\n\n"
        f"Analyze this file with respect to the focus question above. "
        f"Return structured findings as JSON."
    )

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            temperature=0,
            system=_SUBAGENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        response_text = message.content[0].text
        json_text = _extract_json(response_text)
        return json.loads(json_text)

    except Exception as e:
        return {"summary": f"Deep analysis failed: {e}", "findings": []}


# ---------------------------------------------------------------------------
# Context Summarization
# ---------------------------------------------------------------------------

def _summarize_old_context(
    messages: list[dict],
    ctx: ToolContext,
) -> list[dict]:
    """
    Replace raw file/diff content in older tool results with a brief placeholder.
    Keeps the most recently analyzed file's content intact.
    """
    if len(ctx.files_analyzed) <= 1:
        return messages

    files_to_summarize = set(ctx.files_analyzed[:-1])

    summarized = []
    for msg in messages:
        if msg.get("role") == "user" and isinstance(msg.get("content"), list):
            new_content = []
            for block in msg["content"]:
                if block.get("type") == "tool_result":
                    content_text = block.get("content", "")
                    should_compress = False
                    for fp in files_to_summarize:
                        if fp in content_text and len(content_text) > 500:
                            should_compress = True
                            break
                    if should_compress:
                        new_content.append({
                            "type": "tool_result",
                            "tool_use_id": block.get("tool_use_id", ""),
                            "content": (
                                "[Context compressed to save budget. "
                                "The original content has been reviewed. "
                                "Refer to your earlier analysis of this file.]"
                            ),
                        })
                    else:
                        new_content.append(block)
                else:
                    new_content.append(block)
            summarized.append({"role": msg["role"], "content": new_content})
        else:
            summarized.append(msg)

    return summarized


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def _build_review_system_prompt() -> str:
    return """You are a senior code reviewer performing an in-depth review of a pull request.

You have access to tools that let you inspect the actual code and diffs. Your approach should be:

1. TRIAGE: Review the file summaries and risk scores provided. Decide which files to examine closely.
2. INVESTIGATE: For each file you want to review:
   - Start with read_file_diff to see what changed
   - Use read_file_snippet to inspect specific areas of interest
   - Use read_full_file only for small files where full context matters
   - Use request_deep_analysis for complex files needing focused expert review
3. REPORT: When you have reviewed all files of interest, call submit_review with your findings.

Review categories:
- bug: Logic errors, null references, race conditions, incorrect behavior
- security: Injection vulnerabilities, auth issues, data exposure
- performance: N+1 queries, memory leaks, inefficient algorithms
- style: Poor naming, high complexity, missing error handling

Rules:
- Start with the highest-risk files
- Be specific -- evidence must be actual code you have seen via tools
- Don't waste time on low-risk files unless you have budget remaining
- If the code looks good, say so. Don't invent issues.
- Call submit_review when you are done. Do not produce findings in plain text."""


def _build_initial_message(code_context: CodeContext) -> str:
    """Build the initial user message from CodeContext summaries."""
    lines = [
        "# Pull Request Code Review",
        "",
        f"Repository: {code_context.repo_id}",
        f"Comparing: {code_context.base_commit[:8]}..{code_context.head_commit[:8]}",
        "",
        "## Change Overview",
        f"- Files changed: {code_context.overview.totals.files_changed}",
        f"- Lines added: +{code_context.overview.totals.lines_added}",
        f"- Lines removed: -{code_context.overview.totals.lines_removed}",
        f"- Total hunks: {code_context.overview.totals.total_hunks}",
        "",
    ]

    if code_context.overview.flags:
        lines.append(f"Flags: {', '.join(code_context.overview.flags)}")
        lines.append("")

    lines.append("## Files to Review (sorted by risk score)")
    lines.append("")

    sorted_files = sorted(
        code_context.files.values(),
        key=lambda f: f.risk_score,
        reverse=True,
    )

    for fc in sorted_files:
        lines.append(f"### {fc.path}")
        lines.append(f"- Risk Score: {fc.risk_score:.1f}")
        lines.append(f"- Changes: +{fc.added}/-{fc.removed}")
        if fc.reasons:
            lines.append(f"- Risk Reasons: {', '.join(fc.reasons)}")
        if fc.summary:
            lines.append(f"- Purpose: {fc.summary.purpose}")
            lines.append(f"- Behavior: {fc.summary.behavior}")
            if fc.summary.key_functions:
                lines.append(f"- Key Functions: {', '.join(fc.summary.key_functions)}")
        lines.append("")

    lines.append(
        "Review these files using the available tools. "
        "Start with the highest-risk files. "
        "Call submit_review when you are done."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> str:
    """Extract JSON from text that may be wrapped in markdown code blocks."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        json_lines = []
        in_json = False
        for line in lines:
            if line.startswith("```") and not in_json:
                in_json = True
                continue
            elif line.startswith("```") and in_json:
                break
            elif in_json:
                json_lines.append(line)
        return "\n".join(json_lines)
    return text


def _reconstruct_code_context(data: dict) -> CodeContext:
    """Reconstruct CodeContext from Temporal-serialized dict."""
    if isinstance(data, CodeContext):
        return data

    totals = Totals(**data["overview"]["totals"])
    file_breakdown = {
        k: FileTypeStats(**v)
        for k, v in data["overview"]["file_breakdown"].items()
    }
    overview = ContextOverview(
        totals=totals,
        file_breakdown=file_breakdown,
        flags=data["overview"]["flags"],
    )

    files = {}
    for path, fc_data in data["files"].items():
        summary = None
        if fc_data.get("summary"):
            summary = FileSummary(**fc_data["summary"])
        files[path] = FileContext(
            path=fc_data["path"],
            risk_score=fc_data["risk_score"],
            added=fc_data["added"],
            removed=fc_data["removed"],
            reasons=fc_data["reasons"],
            summary=summary,
        )

    return CodeContext(
        repo_id=data["repo_id"],
        base_commit=data["base_commit"],
        head_commit=data["head_commit"],
        overview=overview,
        files=files,
        metadata=ContextMetadata(),
    )


def _reconstruct_change_set(data: dict) -> ChangeSet:
    """Reconstruct ChangeSet from Temporal-serialized dict."""
    if isinstance(data, ChangeSet):
        return data

    files = []
    for f_data in data.get("files", []):
        hunks = []
        for h_data in f_data.get("hunks", []):
            hunks.append(Hunk(start=h_data["start"], lines=h_data["lines"]))
        files.append(ChangedFile(
            path=f_data["path"],
            added=f_data["added"],
            removed=f_data["removed"],
            hunks=hunks,
        ))

    return ChangeSet(
        base_commit=data["base_commit"],
        head_commit=data["head_commit"],
        files=files,
    )


def _validate_finding(finding: ReviewFinding, repo_path: str) -> ReviewFinding:
    """Validate a finding by checking if evidence exists in the actual file."""
    file_full_path = Path(repo_path) / finding.file_path

    if not file_full_path.exists():
        return ReviewFinding(
            file_path=finding.file_path,
            line_number=finding.line_number,
            severity=finding.severity,
            category=finding.category,
            title=finding.title,
            evidence=finding.evidence,
            suggestion=finding.suggestion,
            confidence=finding.confidence,
            validated=False,
        )

    try:
        with open(file_full_path, "r", encoding="utf-8") as f:
            file_content = f.read()
    except (UnicodeDecodeError, IOError):
        return ReviewFinding(
            file_path=finding.file_path,
            line_number=finding.line_number,
            severity=finding.severity,
            category=finding.category,
            title=finding.title,
            evidence=finding.evidence,
            suggestion=finding.suggestion,
            confidence=finding.confidence,
            validated=False,
        )

    def normalize(text: str) -> str:
        return " ".join(text.split())

    normalized_content = normalize(file_content)
    normalized_evidence = normalize(finding.evidence)
    is_valid = normalized_evidence in normalized_content if normalized_evidence else False

    return ReviewFinding(
        file_path=finding.file_path,
        line_number=finding.line_number,
        severity=finding.severity,
        category=finding.category,
        title=finding.title,
        evidence=finding.evidence,
        suggestion=finding.suggestion,
        confidence=finding.confidence,
        validated=is_valid,
    )


def _parse_submit_review(tool_input: dict) -> ReviewResult:
    """Parse the submit_review tool call into a ReviewResult."""
    findings = []
    for f in tool_input.get("findings", []):
        try:
            findings.append(ReviewFinding(
                file_path=str(f.get("file_path", "")),
                line_number=int(f.get("line_number", 0)),
                severity=str(f.get("severity", "low")),
                category=str(f.get("category", "style")),
                title=str(f.get("title", "")),
                evidence=str(f.get("evidence", "")),
                suggestion=str(f.get("suggestion", "")),
                confidence=float(f.get("confidence", 0.5)),
                validated=False,
            ))
        except (ValueError, TypeError):
            continue

    stats = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for finding in findings:
        if finding.severity in stats:
            stats[finding.severity] += 1

    return ReviewResult(
        summary=str(tool_input.get("summary", "No summary provided")),
        warnings=list(tool_input.get("warnings", [])),
        overall_confidence=0.85,
        findings=findings,
        stats=stats,
    )


def _build_budget_exhausted_result(ctx: ToolContext) -> ReviewResult:
    return ReviewResult(
        summary=(
            f"Review completed under budget pressure. "
            f"Analyzed {len(ctx.files_analyzed)} files: "
            f"{', '.join(ctx.files_analyzed)}"
        ),
        warnings=["Token budget exhausted before review could be completed normally"],
        overall_confidence=0.5,
        findings=[],
        stats={"critical": 0, "high": 0, "medium": 0, "low": 0},
    )


# ---------------------------------------------------------------------------
# Main Agentic Loop
# ---------------------------------------------------------------------------

MAX_ITERATIONS = 25


@activity.defn(name="agentic_review")
async def agentic_review(
    code_context: dict,
    change_set: dict,
    repo_path: str,
) -> ReviewResult:
    """
    Run an agentic code review using a tool-use loop.

    Args:
        code_context: CodeContext as dict (Temporal serialization)
        change_set: ChangeSet as dict (Temporal serialization)
        repo_path: Absolute path to the repository root

    Returns:
        ReviewResult with validated findings
    """
    activity.heartbeat("Initializing agentic review...")

    # Reconstruct dataclasses from Temporal dicts
    ctx_obj = _reconstruct_code_context(code_context)
    cs_obj = _reconstruct_change_set(change_set)

    # Build lookup map for fast file access
    cs_files_map: dict[str, ChangedFile] = {f.path: f for f in cs_obj.files}

    budget = TokenBudget()
    ctx = ToolContext(
        repo_path=repo_path,
        change_set_files=cs_files_map,
        budget=budget,
    )

    # Build initial conversation
    system_prompt = _build_review_system_prompt()
    initial_message = _build_initial_message(ctx_obj)
    messages: list[dict] = [{"role": "user", "content": initial_message}]

    # Import Anthropic inside activity to avoid Temporal sandbox restrictions
    from anthropic import Anthropic

    client = Anthropic()

    review_result: Optional[ReviewResult] = None
    iteration = 0

    for iteration in range(1, MAX_ITERATIONS + 1):
        activity.heartbeat(
            f"Review iteration {iteration}/{MAX_ITERATIONS} "
            f"(tokens: {budget.total_tokens_used}/{budget.budget_limit}, "
            f"usage: {budget.budget_usage_ratio:.0%})"
        )

        if budget.budget_exhausted:
            activity.heartbeat("Token budget exhausted, forcing review submission")
            review_result = _build_budget_exhausted_result(ctx)
            break

        # Compress old context if budget is tight
        if budget.should_summarize:
            activity.heartbeat("Budget pressure: summarizing old context...")
            messages = _summarize_old_context(messages, ctx)

        # Call the model
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                temperature=0,
                system=system_prompt,
                messages=messages,
                tools=REVIEW_TOOLS,
            )
        except Exception as e:
            activity.heartbeat(f"API error: {e}")
            return ReviewResult(
                summary=f"Review failed due to API error: {e}",
                warnings=["Agentic review encountered an API error"],
                overall_confidence=0.0,
                findings=[],
                stats={"critical": 0, "high": 0, "medium": 0, "low": 0},
            )

        # Update token budget from response usage
        budget.update(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        # Append assistant response to conversation
        messages.append({"role": "assistant", "content": response.content})

        # Handle end_turn (model finished without tool call)
        if response.stop_reason == "end_turn":
            text_content = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text_content += block.text

            review_result = ReviewResult(
                summary=text_content[:500] if text_content else "Review completed without explicit submission",
                warnings=["Agent ended without calling submit_review"],
                overall_confidence=0.5,
                findings=[],
                stats={"critical": 0, "high": 0, "medium": 0, "low": 0},
            )
            break

        if response.stop_reason != "tool_use":
            review_result = ReviewResult(
                summary=f"Unexpected stop reason: {response.stop_reason}",
                warnings=["Agentic loop ended unexpectedly"],
                overall_confidence=0.0,
                findings=[],
                stats={"critical": 0, "high": 0, "medium": 0, "low": 0},
            )
            break

        # Execute tool calls
        tool_results = []

        for block in response.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input = block.input
            tool_use_id = block.id

            activity.heartbeat(f"Executing tool: {tool_name}")

            # submit_review terminates the loop
            if tool_name == "submit_review":
                review_result = _parse_submit_review(tool_input)
                break

            # Auto-route through subagent if budget is tight
            if (
                tool_name in ("read_file_snippet", "read_full_file", "read_file_diff")
                and budget.should_auto_route
            ):
                activity.heartbeat(
                    f"Budget pressure: auto-routing {tool_name} through subagent"
                )
                file_path = tool_input.get("file_path", "")
                result_text = handle_request_deep_analysis(
                    {"file_path": file_path, "focus_question": "General review of changes and potential issues"},
                    ctx,
                )
            else:
                handler = TOOL_HANDLERS.get(tool_name)
                if handler:
                    result_text = handler(tool_input, ctx)
                else:
                    result_text = f"Error: Unknown tool '{tool_name}'"

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": result_text,
            })

        # If submit_review was called, exit the loop
        if review_result is not None:
            break

        # Append tool results as user message
        messages.append({"role": "user", "content": tool_results})

    # If loop exhausted without a result
    if review_result is None:
        review_result = ReviewResult(
            summary="Review did not complete within iteration limit",
            warnings=["Max iterations reached"],
            overall_confidence=0.0,
            findings=[],
            stats={"critical": 0, "high": 0, "medium": 0, "low": 0},
        )

    # Validate all findings against actual files
    activity.heartbeat(f"Validating {len(review_result.findings)} findings...")
    validated_findings = []
    validated_count = 0
    for finding in review_result.findings:
        validated = _validate_finding(finding, repo_path)
        validated_findings.append(validated)
        if validated.validated:
            validated_count += 1

    activity.heartbeat(f"Validated {validated_count}/{len(validated_findings)} findings")

    # Recalculate stats with validated findings
    stats = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in validated_findings:
        if f.severity in stats:
            stats[f.severity] += 1

    return ReviewResult(
        summary=review_result.summary,
        warnings=review_result.warnings,
        overall_confidence=review_result.overall_confidence,
        findings=validated_findings,
        stats=stats,
        token_usage={
            "input": budget.input_tokens_used,
            "output": budget.output_tokens_used,
            "total": budget.total_tokens_used,
        },
        iterations=iteration,
        files_analyzed=list(ctx.files_analyzed),
    )
