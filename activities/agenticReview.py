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
import time


# ---------------------------------------------------------------------------
# Token Budget Management
# ---------------------------------------------------------------------------

@dataclass
class TokenBudget:
    """Tracks cumulative token usage across the agentic loop."""
    model_context_limit: int = 200_000
    budget_fraction: float = 0.40
    auto_route_threshold: float = 0.60   # 60% of budget -> auto-route via subagent
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
        lines.append(f"--- Hunk {i + 1} (new-file starts at line {hunk.start}) ---")
        line_no = hunk.start
        for diff_line in hunk.lines:
            if diff_line.startswith('-'):
                lines.append(f"     {diff_line}")
            else:
                lines.append(f"{line_no:4d} {diff_line}")
                line_no += 1
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

    if line_count > 200:
        for i, line in enumerate(file_lines[:200], start=1):
            result_lines.append(f"{i:>4} | {line}")
        result_lines.append(
            f"\n... [TRUNCATED: file has {line_count} lines, showing first 200. "
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
# Tool Result Capping
# ---------------------------------------------------------------------------

MAX_TOOL_RESULT_CHARS = 12_000  # ~3K tokens

def _cap_tool_result(result_text: str, tool_name: str) -> str:
    """Cap tool results at insertion time to prevent unbounded context growth."""
    if len(result_text) <= MAX_TOOL_RESULT_CHARS:
        return result_text

    # For diffs: keep first and last hunks, truncate middle
    if tool_name == "read_file_diff":
        lines = result_text.split("\n")
        if len(lines) > 80:
            kept = lines[:60] + [
                f"\n... [{len(lines) - 80} lines truncated] ...\n"
            ] + lines[-20:]
            return "\n".join(kept)

    # For file reads: keep first portion, note truncation
    return (
        result_text[:MAX_TOOL_RESULT_CHARS]
        + f"\n\n... [TRUNCATED: {len(result_text)} chars total. "
        f"Use read_file_snippet for specific sections.]"
    )


def _truncate_diff(diff_text: str, max_chars: int) -> str:
    """Truncate a diff to fit within a character budget, keeping start and end."""
    if len(diff_text) <= max_chars:
        return diff_text
    lines = diff_text.split("\n")
    first_count = max(1, int(len(lines) * 0.6))
    last_count = max(1, int(len(lines) * 0.2))
    kept = lines[:first_count]
    kept.append(f"\n... [{len(lines) - first_count - last_count} lines truncated] ...\n")
    kept.extend(lines[-last_count:])
    result = "\n".join(kept)
    # Hard character fallback
    if len(result) > max_chars:
        return (
            diff_text[: max_chars - 100]
            + f"\n\n... [TRUNCATED: {len(diff_text)} chars total. "
            f"Use read_file_diff for the full diff.]"
        )
    return result


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
    from observability.tracing import traced_anthropic_call

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
        message, _span = traced_anthropic_call(
            client,
            span_name=f"deep_analysis_{file_path}",
            metadata={
                "file_path": file_path,
                "focus_question": focus_question,
                "file_content_length": len(file_content),
            },
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

def _compact_conversation_history(
    messages: list[dict],
    preserve_count: int = 2,
) -> list[dict]:
    """
    Sliding window eviction of old tool results to prevent quadratic token growth.

    Preserves only the most recent `preserve_count` tool-result messages verbatim.
    Older tool results are replaced with a compact placeholder. Assistant reasoning
    text is always preserved (small and critical for continuity).
    """
    # Find indices of user messages that contain tool_results
    tool_result_indices = []
    for i, msg in enumerate(messages):
        if msg.get("role") == "user" and isinstance(msg.get("content"), list):
            has_tool_result = any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in msg["content"]
            )
            if has_tool_result:
                tool_result_indices.append(i)

    # Nothing to compact if we have few enough tool results
    if len(tool_result_indices) <= preserve_count:
        return messages

    # Indices to compact (all but the last `preserve_count`)
    indices_to_compact = set(tool_result_indices[:-preserve_count])

    compacted = []
    for i, msg in enumerate(messages):
        if i in indices_to_compact:
            new_content = []
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    raw = block.get("content", "")
                    new_content.append({
                        "type": "tool_result",
                        "tool_use_id": block.get("tool_use_id", ""),
                        "content": f"[Previously reviewed — {len(raw)} chars. See assistant analysis above.]",
                    })
                else:
                    new_content.append(block)
            compacted.append({"role": msg["role"], "content": new_content})
        else:
            compacted.append(msg)

    return compacted


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def _build_review_system_prompt() -> str:
    return """You are a senior code reviewer performing an in-depth review of a pull request.

ALL changed files have their diffs included inline in the initial message. Your approach should be:

1. ANALYZE: Read every inline diff carefully. Look for bugs, security issues, and logic errors in ALL files — not just high-risk ones. Subtle bugs often hide in small changes (operator swaps, off-by-one errors, dimension changes).
2. INVESTIGATE (optional): If you need more context:
   - Use read_file_snippet to inspect surrounding code
   - Use read_file_diff if an inline diff was truncated and you need the full version
   - Use read_full_file only for small files where full context matters
   - Use request_deep_analysis for complex files needing focused expert review
3. REPORT: Call submit_review with your findings. Do this BEFORE you run out of iterations.

Review categories (only report issues in these categories):
- bug: Logic errors, null references, race conditions, incorrect behavior — code that will malfunction
- security: Injection vulnerabilities, auth issues, data exposure — code that creates security risk
- performance: N+1 queries, memory leaks, inefficient algorithms — measurable runtime impact

Do NOT report:
- Naming conventions, variable naming preferences, or style opinions
- Import organization or code structure preferences
- Architectural preferences ("should use service layer", "inconsistent pattern")
- Any issue you would assign confidence below 0.7

Precision rules (strictly enforced):
- A false positive wastes developer time and erodes trust in the tool. Only report findings you are highly confident are genuine issues.
- When in doubt, omit. It is better to miss a minor issue than to report a false positive.
- Confidence calibration: 0.9+ = issue is directly visible in the diff and clearly harmful; 0.7–0.9 = strong evidence, likely real; below 0.7 = skip it.
- Do not report issues just because something "could" be a problem in theory. Report only what you can ground in the actual changed code.

Other rules:
- Analyze EVERY file's diff, even small changes. Subtle operator changes can be critical bugs.
- Be specific — evidence must be actual code you have seen via inline diffs or tools
- If the code looks good, say so. Don't invent issues.
- Call submit_review when you are done. Do not produce findings in plain text.
- You have a LIMITED number of iterations. Analyze all inline diffs first, then submit.
- You MUST call submit_review. If in doubt, submit early with what you have.

Line number rule:
- Each diff line is prefixed with its NEW-FILE line number (e.g. "  81 +    code here").
- Removed lines ('-') have no number (indented with spaces) — do not report findings on removed lines.
- When reporting a finding, use the new-file line number shown to the left of the relevant '+' or ' ' line.

Efficiency:
- All files have diffs inline — analyze them directly without tool calls
- Use read_file_snippet only for targeted investigation of specific line ranges
- After analyzing all inline diffs, call submit_review
- IMPORTANT: Analyze every diff before submitting. Don't skip files because of low risk scores."""


INLINE_DIFF_CHAR_BUDGET = 120_000  # ~30K tokens for all inline diffs combined


def _build_initial_message(
    code_context: CodeContext,
    change_set_files: dict[str, ChangedFile],
) -> tuple[str, dict]:
    """Build the initial user message from CodeContext summaries.

    Embeds diffs inline for ALL files using a token-aware character budget.
    If total diff size exceeds INLINE_DIFF_CHAR_BUDGET, per-file caps shrink
    proportionally so every file still gets its diff included.

    Returns:
        (message_text, context_metadata) — metadata captures what was provided
        for downstream trace analysis (truncation info, risk scores, etc.).
    """
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

    # Phase 1: Build raw diff text for every file
    raw_diffs: dict[str, str] = {}
    total_diff_chars = 0
    for fc in sorted_files:
        changed_file = change_set_files.get(fc.path)
        if changed_file and changed_file.hunks:
            diff_lines = []
            for i, hunk in enumerate(changed_file.hunks):
                diff_lines.append(
                    f"--- Hunk {i + 1} (new-file starts at line {hunk.start}) ---"
                )
                line_no = hunk.start
                for diff_line in hunk.lines:
                    if diff_line.startswith('-'):
                        diff_lines.append(f"     {diff_line}")
                    else:
                        diff_lines.append(f"{line_no:4d} {diff_line}")
                        line_no += 1
                diff_lines.append("")
            raw_diffs[fc.path] = "\n".join(diff_lines)
            total_diff_chars += len(raw_diffs[fc.path])

    # Phase 2: Determine per-file cap based on total diff size
    if total_diff_chars <= INLINE_DIFF_CHAR_BUDGET:
        per_file_cap = MAX_TOOL_RESULT_CHARS  # 12K — everything fits
    else:
        num_files = max(1, len(raw_diffs))
        per_file_cap = max(2_000, INLINE_DIFF_CHAR_BUDGET // num_files)

    # Phase 3: Build message with ALL diffs included
    truncated_files: list[str] = []
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

        # Embed diff for EVERY file
        if fc.path in raw_diffs:
            diff_text = raw_diffs[fc.path]
            if len(diff_text) > per_file_cap:
                diff_text = _truncate_diff(diff_text, per_file_cap)
                truncated_files.append(fc.path)
            lines.append("#### Diff")
            lines.append(diff_text)

        lines.append("")

    lines.append(
        "ALL changed files above include their diffs inline. "
        "Analyze every diff for issues, then call submit_review with your findings. "
        "Use read_file_diff only if a diff was truncated and you need the full version."
    )

    message_text = "\n".join(lines)

    context_meta = {
        "files_with_diffs": list(raw_diffs.keys()),
        "total_diff_chars": total_diff_chars,
        "per_file_cap": per_file_cap,
        "truncated_files": truncated_files,
        "file_risk_scores": {fc.path: fc.risk_score for fc in sorted_files},
    }

    return message_text, context_meta


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

MAX_ITERATIONS = 15


@activity.defn(name="agentic_review")
async def agentic_review(
    code_context: dict,
    change_set: dict,
    repo_path: str,
) -> ReviewResult:
    """
    Temporal activity wrapper. Delegates to run_review_core with activity.heartbeat.
    """
    return await run_review_core(
        code_context, change_set, repo_path,
        heartbeat_fn=activity.heartbeat,
    )


async def run_review_core(
    code_context: dict,
    change_set: dict,
    repo_path: str,
    heartbeat_fn=None,
    model_override: str = None,
) -> ReviewResult:
    """
    Core agentic review loop, decoupled from Temporal.

    Args:
        code_context: CodeContext as dict (or dataclass)
        change_set: ChangeSet as dict (or dataclass)
        repo_path: Absolute path to the repository root
        heartbeat_fn: Optional callback for progress reporting (e.g., activity.heartbeat)
        model_override: Optional model ID to use instead of default

    Returns:
        ReviewResult with validated findings
    """
    def heartbeat(msg: str):
        if heartbeat_fn:
            heartbeat_fn(msg)

    model = model_override or "claude-sonnet-4-20250514"

    heartbeat("Initializing agentic review...")

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
    initial_message, context_meta = _build_initial_message(ctx_obj, cs_files_map)
    messages: list[dict] = [{"role": "user", "content": initial_message}]

    # Pre-populate files_analyzed for ALL files with inline diffs
    sorted_files = sorted(
        ctx_obj.files.values(), key=lambda f: f.risk_score, reverse=True
    )
    for fc in sorted_files:
        if fc.path in cs_files_map and fc.path not in ctx.files_analyzed:
            ctx.files_analyzed.append(fc.path)

    # Import Anthropic inside activity to avoid Temporal sandbox restrictions
    from anthropic import Anthropic
    from observability.tracing import traced_anthropic_call, TraceSpan

    client = Anthropic()
    trace_spans: list[TraceSpan] = []

    # Record what the system provided to the agent (for trace analysis)
    now = time.time()
    trace_spans.append(TraceSpan(
        name="context_snapshot",
        span_type="context",
        start_time=now,
        end_time=now,
        metadata={
            "changed_files": list(cs_files_map.keys()),
            "context_files": list(ctx_obj.files.keys()),
            "file_risk_scores": context_meta["file_risk_scores"],
            "files_with_diffs": context_meta["files_with_diffs"],
            "truncated_files": context_meta["truncated_files"],
            "initial_message_chars": len(initial_message),
            "total_diff_chars": context_meta["total_diff_chars"],
            "per_file_cap": context_meta["per_file_cap"],
            "overview_totals": {
                "files_changed": ctx_obj.overview.totals.files_changed,
                "lines_added": ctx_obj.overview.totals.lines_added,
                "lines_removed": ctx_obj.overview.totals.lines_removed,
                "total_hunks": ctx_obj.overview.totals.total_hunks,
            },
        },
    ))

    review_result: Optional[ReviewResult] = None
    iteration = 0

    for iteration in range(1, MAX_ITERATIONS + 1):
        heartbeat(
            f"Review iteration {iteration}/{MAX_ITERATIONS} "
            f"(tokens: {budget.total_tokens_used}/{budget.budget_limit}, "
            f"usage: {budget.budget_usage_ratio:.0%})"
        )

        if budget.budget_exhausted:
            heartbeat("Token budget exhausted, forcing review submission")
            review_result = _build_budget_exhausted_result(ctx)
            break

        # Evict old tool results every iteration to prevent quadratic token growth
        if iteration > 2:
            messages = _compact_conversation_history(messages, preserve_count=2)

        # Call the model
        try:
            response, llm_span = traced_anthropic_call(
                client,
                span_name=f"review_iteration_{iteration}",
                metadata={
                    "iteration": iteration,
                    "budget_usage": round(budget.budget_usage_ratio, 2),
                    "files_analyzed": list(ctx.files_analyzed),
                },
                model=model,
                max_tokens=4096,
                temperature=0,
                system=system_prompt,
                messages=messages,
                tools=REVIEW_TOOLS,
            )
            trace_spans.append(llm_span)
        except Exception as e:
            heartbeat(f"API error: {e}")
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

            heartbeat(f"Executing tool: {tool_name}")

            # submit_review terminates the loop
            if tool_name == "submit_review":
                review_result = _parse_submit_review(tool_input)
                break

            # Auto-route through subagent if budget is tight
            tool_start = time.time()
            if (
                tool_name in ("read_file_snippet", "read_full_file", "read_file_diff")
                and budget.should_auto_route
            ):
                heartbeat(
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

            trace_spans.append(TraceSpan(
                name=f"tool_{tool_name}",
                span_type="tool",
                start_time=tool_start,
                end_time=time.time(),
                metadata={
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "result_length": len(result_text),
                    "iteration": iteration,
                    "auto_routed": budget.should_auto_route and tool_name in ("read_file_snippet", "read_full_file", "read_file_diff"),
                },
            ))

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": _cap_tool_result(result_text, tool_name),
            })

        # If submit_review was called, exit the loop
        if review_result is not None:
            break

        # Append tool results as user message
        messages.append({"role": "user", "content": tool_results})

    # If loop exhausted without a result, force a final submission
    if review_result is None:
        heartbeat("Max iterations reached — forcing final submission")
        messages.append({
            "role": "user",
            "content": (
                "You have reached the maximum iteration limit. "
                "Call submit_review NOW with your findings from the files "
                "you have already reviewed. If you found no issues, submit "
                "with an empty findings list and say the code looks clean."
            ),
        })

        try:
            response, llm_span = traced_anthropic_call(
                client,
                span_name="review_forced_submit",
                metadata={
                    "iteration": "forced_submit",
                    "files_analyzed": list(ctx.files_analyzed),
                },
                model=model,
                max_tokens=4096,
                temperature=0,
                system=system_prompt,
                messages=messages,
                tools=[t for t in REVIEW_TOOLS if t["name"] == "submit_review"],
            )
            trace_spans.append(llm_span)
            budget.update(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )

            for block in response.content:
                if block.type == "tool_use" and block.name == "submit_review":
                    review_result = _parse_submit_review(block.input)
                    review_result.warnings.append(
                        "Submitted via forced iteration limit"
                    )
                    break
        except Exception:
            pass  # Fall through to the static fallback below

    # Final fallback if forced submission also failed
    if review_result is None:
        review_result = ReviewResult(
            summary="Review did not complete within iteration limit",
            warnings=["Max iterations reached"],
            overall_confidence=0.0,
            findings=[],
            stats={"critical": 0, "high": 0, "medium": 0, "low": 0},
        )

    # Risk-adjusted evidence validation
    from activities.evidenceValidation import validate_findings_batch

    heartbeat(f"Validating {len(review_result.findings)} findings...")
    validated_findings, validation_span = validate_findings_batch(
        review_result.findings, repo_path, cs_files_map,
    )
    trace_spans.append(validation_span)

    validated_count = sum(1 for f in validated_findings if f.validated)
    heartbeat(f"Validated {validated_count}/{len(validated_findings)} findings")

    # Filter on adjusted confidence (uses post-validation confidence if available)
    CONFIDENCE_THRESHOLD = 0.7
    before_filter = len(validated_findings)
    validated_findings = [
        f for f in validated_findings
        if (f.confidence_adjusted if f.confidence_adjusted is not None else f.confidence) >= CONFIDENCE_THRESHOLD
    ]
    filtered_count = before_filter - len(validated_findings)
    if filtered_count > 0:
        heartbeat(f"Filtered {filtered_count} low-confidence findings (threshold={CONFIDENCE_THRESHOLD})")

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
        trace_log=[s.to_dict() for s in trace_spans],
    )
