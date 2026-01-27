"""
Activity for running AI-powered code review on a CodeContext.
Generates structured review findings with validation against actual file content.
"""
from temporalio import activity
from pathlib import Path
from utils.dataclasses import CodeContext, ReviewFinding, ReviewResult, FileContext
import json
import re


def _build_review_prompt(code_context: CodeContext) -> str:
    """Build prompt with file summaries and priorities for code review."""
    lines = [
        "# Pull Request Code Review",
        "",
        f"Repository: {code_context.repo_id}",
        f"Base commit: {code_context.base_commit}",
        f"Head commit: {code_context.head_commit}",
        "",
        "## Change Overview",
        f"- Files changed: {code_context.overview.totals.files_changed}",
        f"- Lines added: {code_context.overview.totals.lines_added}",
        f"- Lines removed: {code_context.overview.totals.lines_removed}",
        "",
    ]

    if code_context.overview.flags:
        lines.append(f"Flags: {', '.join(code_context.overview.flags)}")
        lines.append("")

    lines.append("## Files to Review (sorted by risk)")
    lines.append("")

    # Sort files by risk score (highest first)
    sorted_files = sorted(
        code_context.files.values(),
        key=lambda f: f.risk_score,
        reverse=True
    )

    for file_ctx in sorted_files:
        lines.append(f"### {file_ctx.path}")
        lines.append(f"Risk Score: {file_ctx.risk_score:.2f}")
        lines.append(f"Changes: +{file_ctx.added}/-{file_ctx.removed}")

        if file_ctx.reasons:
            lines.append(f"Risk Reasons: {', '.join(file_ctx.reasons)}")

        if file_ctx.summary:
            lines.append(f"Purpose: {file_ctx.summary.purpose}")
            lines.append(f"Behavior: {file_ctx.summary.behavior}")
            if file_ctx.summary.key_functions:
                lines.append(f"Key Functions: {', '.join(file_ctx.summary.key_functions)}")

        lines.append("")

    return "\n".join(lines)


def _get_system_prompt() -> str:
    """Get the system prompt for code review."""
    return """You are a senior code reviewer analyzing a pull request.

Review the following files and identify issues in these categories:
- bug: Logic errors, null references, race conditions, incorrect behavior
- security: Injection vulnerabilities, auth issues, data exposure, OWASP risks
- performance: N+1 queries, memory leaks, inefficient algorithms, blocking calls
- style: Poor naming, high complexity, missing error handling, code smells

For each finding, you MUST provide ALL of these fields:
- file_path: exact path from the context (must match exactly)
- line_number: approximate line number where the issue occurs
- severity: one of "critical", "high", "medium", "low"
- category: one of "bug", "security", "performance", "style"
- title: one-line summary of the issue
- evidence: exact code snippet that shows the problem (copy from file content)
- suggestion: specific, actionable fix recommendation
- confidence: 0.0-1.0 indicating how confident you are in this finding

Rules:
- Only report real issues you can see evidence for in the code
- Be specific - vague findings are not helpful
- Focus on the most important issues first
- If the code looks good, say so in the summary with few or no findings
- Evidence must be actual code from the files, not made up

Output ONLY valid JSON in this exact format (no markdown, no explanation):
{
  "summary": "Executive summary of the review (2-3 sentences)",
  "warnings": ["High-level warning 1", "High-level warning 2"],
  "overall_confidence": 0.85,
  "findings": [
    {
      "file_path": "path/to/file.py",
      "line_number": 42,
      "severity": "high",
      "category": "bug",
      "title": "Null reference when user is not authenticated",
      "evidence": "user.name.lower()",
      "suggestion": "Add null check: if user and user.name: ...",
      "confidence": 0.9
    }
  ]
}"""


def _parse_review_response(response_text: str) -> ReviewResult:
    """Parse agent response into structured ReviewResult."""
    # Try to extract JSON from the response
    # Handle cases where the model might wrap it in markdown code blocks
    json_text = response_text.strip()

    # Remove markdown code blocks if present
    if json_text.startswith("```"):
        # Find the actual JSON content
        lines = json_text.split("\n")
        # Skip first line (```json) and last line (```)
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
        json_text = "\n".join(json_lines)

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        # Return a minimal result indicating parsing failure
        return ReviewResult(
            summary=f"Failed to parse review response: {e}",
            warnings=["Review parsing failed - raw response may need manual inspection"],
            overall_confidence=0.0,
            findings=[],
            stats={}
        )

    # Parse findings
    findings = []
    for f in data.get("findings", []):
        try:
            finding = ReviewFinding(
                file_path=str(f.get("file_path", "")),
                line_number=int(f.get("line_number", 0)),
                severity=str(f.get("severity", "low")),
                category=str(f.get("category", "style")),
                title=str(f.get("title", "")),
                evidence=str(f.get("evidence", "")),
                suggestion=str(f.get("suggestion", "")),
                confidence=float(f.get("confidence", 0.5)),
                validated=False
            )
            findings.append(finding)
        except (ValueError, TypeError) as e:
            # Skip malformed findings
            continue

    # Calculate stats
    stats = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for finding in findings:
        if finding.severity in stats:
            stats[finding.severity] += 1

    return ReviewResult(
        summary=str(data.get("summary", "No summary provided")),
        warnings=list(data.get("warnings", [])),
        overall_confidence=float(data.get("overall_confidence", 0.5)),
        findings=findings,
        stats=stats
    )


def _validate_finding(finding: ReviewFinding, repo_path: str) -> ReviewFinding:
    """
    Validate finding by checking if evidence exists in the actual file.
    Returns a new ReviewFinding with validated=True/False.
    """
    file_full_path = Path(repo_path) / finding.file_path

    if not file_full_path.exists():
        # File doesn't exist - invalid finding
        return ReviewFinding(
            file_path=finding.file_path,
            line_number=finding.line_number,
            severity=finding.severity,
            category=finding.category,
            title=finding.title,
            evidence=finding.evidence,
            suggestion=finding.suggestion,
            confidence=finding.confidence,
            validated=False
        )

    try:
        with open(file_full_path, 'r', encoding='utf-8') as f:
            file_content = f.read()
    except (UnicodeDecodeError, IOError):
        # Can't read file - mark as not validated
        return ReviewFinding(
            file_path=finding.file_path,
            line_number=finding.line_number,
            severity=finding.severity,
            category=finding.category,
            title=finding.title,
            evidence=finding.evidence,
            suggestion=finding.suggestion,
            confidence=finding.confidence,
            validated=False
        )

    # Normalize whitespace for comparison
    def normalize(text: str) -> str:
        return ' '.join(text.split())

    normalized_content = normalize(file_content)
    normalized_evidence = normalize(finding.evidence)

    # Check if evidence exists in file content
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
        validated=is_valid
    )


@activity.defn(name="review_code")
async def review_code(code_context: dict, repo_path: str) -> ReviewResult:
    """
    Run AI code review on the code context.

    Args:
        code_context: CodeContext as dict (Temporal serializes dataclasses)
        repo_path: Absolute path to the repository root

    Returns:
        ReviewResult with validated findings
    """
    activity.heartbeat("Starting code review...")

    # Reconstruct CodeContext from dict if needed
    # Temporal serializes dataclasses to dicts when passing between workflows/activities
    if isinstance(code_context, dict):
        from utils.dataclasses import (
            CodeContext, ContextOverview, Totals, FileTypeStats,
            FileContext, FileSummary, ContextMetadata
        )

        # Reconstruct Totals
        totals_data = code_context["overview"]["totals"]
        totals = Totals(**totals_data)

        # Reconstruct FileTypeStats
        file_breakdown = {
            k: FileTypeStats(**v)
            for k, v in code_context["overview"]["file_breakdown"].items()
        }

        # Reconstruct ContextOverview
        overview = ContextOverview(
            totals=totals,
            file_breakdown=file_breakdown,
            flags=code_context["overview"]["flags"]
        )

        # Reconstruct FileContext objects
        files = {}
        for path, fc_data in code_context["files"].items():
            summary = None
            if fc_data.get("summary"):
                summary = FileSummary(**fc_data["summary"])
            files[path] = FileContext(
                path=fc_data["path"],
                risk_score=fc_data["risk_score"],
                added=fc_data["added"],
                removed=fc_data["removed"],
                reasons=fc_data["reasons"],
                summary=summary
            )

        code_context = CodeContext(
            repo_id=code_context["repo_id"],
            base_commit=code_context["base_commit"],
            head_commit=code_context["head_commit"],
            overview=overview,
            files=files,
            metadata=ContextMetadata()
        )

    activity.heartbeat(f"Reviewing {len(code_context.files)} files...")

    # Build the review prompt
    prompt = _build_review_prompt(code_context)
    system_prompt = _get_system_prompt()

    activity.heartbeat("Calling AI for code review...")

    try:
        # Import Anthropic inside the function to avoid workflow sandbox restrictions
        from anthropic import Anthropic
        client = Anthropic()

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            temperature=0,
            messages=[
                {"role": "user", "content": prompt}
            ],
            system=system_prompt
        )

        response_text = message.content[0].text
        activity.heartbeat("Parsing review response...")

    except Exception as e:
        activity.heartbeat(f"Error calling AI: {e}")
        return ReviewResult(
            summary=f"Failed to generate review: {e}",
            warnings=["Review generation failed"],
            overall_confidence=0.0,
            findings=[],
            stats={}
        )

    # Parse the response
    review_result = _parse_review_response(response_text)

    activity.heartbeat(f"Validating {len(review_result.findings)} findings...")

    # Validate each finding
    validated_findings = []
    validated_count = 0
    for finding in review_result.findings:
        validated_finding = _validate_finding(finding, repo_path)
        validated_findings.append(validated_finding)
        if validated_finding.validated:
            validated_count += 1

    activity.heartbeat(f"Validated {validated_count}/{len(validated_findings)} findings")

    # Recalculate stats with validated findings
    stats = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for finding in validated_findings:
        if finding.severity in stats:
            stats[finding.severity] += 1

    # Return updated result with validated findings
    return ReviewResult(
        summary=review_result.summary,
        warnings=review_result.warnings,
        overall_confidence=review_result.overall_confidence,
        findings=validated_findings,
        stats=stats
    )
