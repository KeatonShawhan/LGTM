"""Risk-adjusted evidence validation for code review findings.

Replaces the old substring-match `_validate_finding()`. This module:
1. Fetches actual code from the repo proportional to finding severity
2. Validates the finding against fetched code using multi-signal checks
3. Adjusts confidence based on evidence quality signals
4. Returns enriched findings + a TraceSpan for observability

Zero LLM calls -- purely deterministic.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from observability.tracing import TraceSpan
from utils.dataclasses import ChangedFile, Hunk, ReviewFinding


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Context window (lines above/below finding.line_number) by severity
_CONTEXT_RADIUS = {
    "critical": 15,
    "high": 15,
    "medium": 5,
    "low": 0,   # hunk only for low-severity
}

# Words to exclude from symbol extraction (common English, not identifiers)
_STOP_WORDS = frozenset({
    "the", "this", "that", "with", "from", "into", "which", "when", "where",
    "what", "will", "would", "could", "should", "does", "have", "has", "had",
    "been", "being", "are", "was", "were", "not", "but", "and", "for", "nor",
    "can", "may", "might", "also", "then", "than", "each", "every", "all",
    "any", "both", "few", "more", "most", "some", "such", "only", "same",
    "other", "new", "old", "use", "used", "using", "return", "returns",
    "true", "false", "none", "null", "undefined", "function", "class", "def",
    "var", "let", "const", "import", "export", "str", "int", "float", "bool",
    "list", "dict", "set", "tuple", "self", "cls", "args", "kwargs",
})

_IDENT_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")

# Delimiters used to split evidence into code vs explanation fragments
_FRAGMENT_DELIMITERS = re.compile(r" - | -- |\n|\. (?=[A-Z])")

# Regex to extract inline code from backtick-delimited spans (e.g. `c.count++`)
_BACKTICK_RE = re.compile(r"`([^`]+)`")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FetchedEvidence:
    """Actual code fetched from the repository for validation."""
    file_exists: bool
    line_valid: bool
    line_in_diff: bool
    snippet: str           # fetched code lines (empty if file/line invalid)
    diff_hunk: str         # relevant diff hunk text (empty if none found)
    fetch_depth: str       # "hunk_only" | "line_snippet" | "function_context"


# ---------------------------------------------------------------------------
# Evidence fetching (risk-adjusted)
# ---------------------------------------------------------------------------

def fetch_evidence(
    finding: ReviewFinding,
    repo_path: str,
    cs_files_map: dict[str, ChangedFile],
) -> FetchedEvidence:
    """Fetch actual code from the repo for a single finding."""

    file_full_path = Path(repo_path) / finding.file_path

    # Gate 1: file exists?
    if not file_full_path.exists():
        return FetchedEvidence(
            file_exists=False, line_valid=False, line_in_diff=False,
            snippet="", diff_hunk="", fetch_depth="none",
        )

    # Read file
    try:
        file_lines = file_full_path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, IOError):
        return FetchedEvidence(
            file_exists=True, line_valid=False, line_in_diff=False,
            snippet="", diff_hunk="", fetch_depth="none",
        )

    # Gate 2: line_number valid?
    line_valid = 1 <= finding.line_number <= len(file_lines)

    # Determine fetch depth by severity
    radius = _CONTEXT_RADIUS.get(finding.severity, 5)
    if radius > 0:
        fetch_depth = "function_context" if radius >= 15 else "line_snippet"
    else:
        fetch_depth = "hunk_only"

    # Fetch code snippet (if line valid and radius > 0)
    snippet = ""
    if line_valid and radius > 0:
        start = max(0, finding.line_number - 1 - radius)
        end = min(len(file_lines), finding.line_number + radius)
        snippet = "\n".join(file_lines[start:end])

    # Find relevant diff hunk
    diff_hunk = ""
    line_in_diff = False
    changed_file = cs_files_map.get(finding.file_path)
    if changed_file:
        for hunk in changed_file.hunks:
            hunk_end = _hunk_end_line(hunk)
            if hunk.start <= finding.line_number <= hunk_end:
                diff_hunk = "\n".join(hunk.lines)
                line_in_diff = True
                break

    # For hunk_only depth, use the diff hunk as the snippet if we have one
    if fetch_depth == "hunk_only" and not snippet and diff_hunk:
        snippet = diff_hunk

    return FetchedEvidence(
        file_exists=True,
        line_valid=line_valid,
        line_in_diff=line_in_diff,
        snippet=snippet,
        diff_hunk=diff_hunk,
        fetch_depth=fetch_depth,
    )


def _hunk_end_line(hunk: Hunk) -> int:
    """Compute the last line number covered by a hunk.

    Hunk.start is the starting line in the new file. Hunk.lines contains
    diff-prefixed lines (+/-/space). Count non-removed lines to get the
    range in the new file.
    """
    new_lines = sum(1 for ln in hunk.lines if not ln.startswith("-"))
    return hunk.start + max(new_lines - 1, 0)


# ---------------------------------------------------------------------------
# Evidence validation (multi-signal)
# ---------------------------------------------------------------------------

def validate_evidence(
    finding: ReviewFinding,
    fetched: FetchedEvidence,
) -> tuple[bool, float, dict]:
    """Validate a finding against fetched evidence.

    Returns:
        (validated, confidence_delta, signals_dict)
    """
    signals: dict[str, bool] = {}

    # Hard gates
    if not fetched.file_exists:
        return False, -finding.confidence, {"file_exists": False}
    if not fetched.line_valid:
        return False, -finding.confidence, {"file_exists": True, "line_valid": False}

    signals["file_exists"] = True
    signals["line_valid"] = True

    # Combined text to search against
    search_text = fetched.snippet + "\n" + fetched.diff_hunk

    # Signal: line_in_diff
    signals["line_in_diff"] = fetched.line_in_diff

    # Signal: symbols_found -- do identifiers from the evidence appear in code?
    signals["symbols_found"] = _check_symbols(finding.evidence, search_text)

    # Signal: code_fragment_found -- does a code fragment from evidence appear?
    signals["code_fragment_found"] = _check_code_fragments(finding.evidence, search_text)

    # Compute confidence delta
    positive_signals = ["line_in_diff", "symbols_found", "code_fragment_found"]
    weights = {"line_in_diff": 0.05, "symbols_found": 0.05, "code_fragment_found": 0.10}

    # Content signals ground the finding in actual code text.
    # line_in_diff alone only confirms address (line is in the diff), not content.
    content_signals = ["symbols_found", "code_fragment_found"]
    has_content = any(signals.get(s, False) for s in content_signals)

    if not has_content:
        if not any(signals.get(s, False) for s in positive_signals):
            # File/line valid but nothing matches at all — small penalty
            return False, -0.15, signals
        # line_in_diff fired but no content grounding — stronger penalty to push
        # adjusted confidence below the 0.7 filter threshold
        return False, -0.25, signals

    delta = sum(weights[s] for s in positive_signals if signals.get(s, False))
    return True, delta, signals


def _check_symbols(evidence: str, code: str) -> bool:
    """Check if >= 50% of identifiers from evidence appear in the code."""
    evidence_idents = {
        m.group()
        for m in _IDENT_RE.finditer(evidence)
        if len(m.group()) >= 3 and m.group().lower() not in _STOP_WORDS
    }
    if not evidence_idents:
        return False

    code_lower = code.lower()
    found = sum(1 for ident in evidence_idents if ident.lower() in code_lower)
    return found / len(evidence_idents) >= 0.50


def _check_code_fragments(evidence: str, code: str) -> bool:
    """Check if at least one code fragment from evidence appears in the code."""

    def normalize(text: str) -> str:
        return " ".join(text.split())

    normalized_code = normalize(code)

    # First: extract inline code from backticks — highest-fidelity signal.
    # Evidence is typically structured as "[prose] `code` [prose]", so backtick
    # contents are verbatim code that should appear in the fetched snippet.
    for m in _BACKTICK_RE.finditer(evidence):
        frag = m.group(1).strip()
        if len(frag.replace(" ", "")) < 4:
            continue
        if normalize(frag) in normalized_code:
            return True

    # Fallback: delimiter-split fragments (catches evidence without backticks)
    fragments = _FRAGMENT_DELIMITERS.split(evidence)
    for frag in fragments:
        frag = frag.strip()
        # Skip very short fragments (likely not code)
        if len(frag.replace(" ", "")) < 8:
            continue
        # Skip fragments that look like pure English sentences
        if frag and frag[0].isupper() and not any(c in frag for c in "(){}[]=.<>"):
            continue
        if normalize(frag) in normalized_code:
            return True

    return False


# ---------------------------------------------------------------------------
# Batch orchestrator
# ---------------------------------------------------------------------------

def validate_findings_batch(
    findings: list[ReviewFinding],
    repo_path: str,
    cs_files_map: dict[str, ChangedFile],
) -> tuple[list[ReviewFinding], TraceSpan]:
    """Validate all findings and return enriched findings + a trace span.

    This is the main entry point called from run_review_core.
    """
    start_time = time.time()

    enriched: list[ReviewFinding] = []
    per_finding_data: list[dict] = []

    for finding in findings:
        fetched = fetch_evidence(finding, repo_path, cs_files_map)
        validated, confidence_delta, signals = validate_evidence(finding, fetched)

        adjusted = max(0.0, min(1.0, finding.confidence + confidence_delta))

        # Create new ReviewFinding with validation results (frozen dataclass)
        enriched_finding = ReviewFinding(
            file_path=finding.file_path,
            line_number=finding.line_number,
            severity=finding.severity,
            category=finding.category,
            title=finding.title,
            evidence=finding.evidence,
            suggestion=finding.suggestion,
            confidence=finding.confidence,
            validated=validated,
            evidence_context=fetched.snippet if fetched.snippet else None,
            confidence_adjusted=adjusted,
        )
        enriched.append(enriched_finding)

        per_finding_data.append({
            "file_path": finding.file_path,
            "line_number": finding.line_number,
            "severity": finding.severity,
            "original_confidence": finding.confidence,
            "adjusted_confidence": adjusted,
            "confidence_delta": confidence_delta,
            "validated": validated,
            "fetch_depth": fetched.fetch_depth,
            "signals": signals,
        })

    end_time = time.time()

    # Compute aggregates for the span
    total = len(findings)
    validated_count = sum(1 for d in per_finding_data if d["validated"])
    validation_rate = validated_count / total if total > 0 else 0.0
    avg_delta = (
        sum(d["confidence_delta"] for d in per_finding_data) / total
        if total > 0 else 0.0
    )
    rejection_count = sum(
        1 for d in per_finding_data
        if d["adjusted_confidence"] < 0.7
    )

    # Summarize signal rates
    signal_names = ["line_in_diff", "symbols_found", "code_fragment_found"]
    signals_summary = {}
    if total > 0:
        for sig in signal_names:
            count = sum(
                1 for d in per_finding_data
                if d["signals"].get(sig, False)
            )
            signals_summary[sig] = count / total

    span = TraceSpan(
        name="evidence_validation",
        span_type="validation",
        start_time=start_time,
        end_time=end_time,
        metadata={
            "findings_count": total,
            "validation_rate": validation_rate,
            "avg_confidence_delta": avg_delta,
            "rejection_count": rejection_count,
            "signals_summary": signals_summary,
            "per_finding": per_finding_data,
        },
    )

    return enriched, span
