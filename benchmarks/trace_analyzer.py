"""
Trace analyzer — computes coverage, efficiency, and correctness metrics
from structured trace data captured during agentic review.

These metrics measure SYSTEM quality (context, tools, budget) rather than
prompt/reasoning quality. Use them to identify infrastructure improvements
before tuning prompts.

Usage:
    from benchmarks.trace_analyzer import analyze_trace, aggregate_trace_metrics
    metrics = analyze_trace(case_result, benchmark_case)
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from statistics import mean
from typing import Optional

from benchmarks.dataclasses import (
    BenchmarkCase,
    CoverageMetrics,
    CorrectnessMetrics,
    EfficiencyMetrics,
    EvidenceValidationMetrics,
    TraceMetrics,
)

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_trace(
    case_result: dict,
    benchmark_case: BenchmarkCase,
) -> Optional[TraceMetrics]:
    """Compute trace metrics for a single benchmark case.

    Args:
        case_result: A single entry from the ``cases`` array in results JSON.
                     Must contain ``review_result.trace_log``.
        benchmark_case: The corresponding ground-truth case definition.

    Returns:
        TraceMetrics if trace data is available, else None.
    """
    review = case_result.get("review_result", {})
    trace_log = review.get("trace_log")
    if not trace_log:
        return None

    score = case_result.get("score", {})
    match_details = score.get("match_details", [])

    coverage = _compute_coverage(trace_log, review, benchmark_case)
    efficiency = _compute_efficiency(trace_log, review, score, benchmark_case)
    correctness = _compute_correctness(review, match_details, benchmark_case)
    evidence_validation = _compute_evidence_validation(trace_log)

    return TraceMetrics(
        case_id=case_result.get("case_id", ""),
        coverage=coverage,
        efficiency=efficiency,
        correctness=correctness,
        evidence_validation=evidence_validation,
    )


def aggregate_trace_metrics(case_metrics: list[TraceMetrics]) -> dict:
    """Compute averages/sums across all cases for suite-level reporting."""
    if not case_metrics:
        return {}

    def _safe_mean(values: list[float]) -> float:
        return round(mean(values), 3) if values else 0.0

    return {
        # Coverage
        "avg_file_coverage": _safe_mean(
            [m.coverage.file_coverage for m in case_metrics]
        ),
        "avg_bug_file_coverage": _safe_mean(
            [m.coverage.bug_file_coverage for m in case_metrics]
        ),
        "avg_bug_line_coverage": _safe_mean(
            [m.coverage.bug_line_coverage for m in case_metrics]
        ),
        "avg_diff_truncation_rate": _safe_mean(
            [m.coverage.diff_truncation_rate for m in case_metrics]
        ),
        # Efficiency
        "avg_tokens_per_tp": _safe_mean(
            [m.efficiency.tokens_per_tp for m in case_metrics]
        ),
        "total_tool_calls": sum(
            m.efficiency.tool_calls_total for m in case_metrics
        ),
        "total_redundant_tool_calls": sum(
            m.efficiency.redundant_tool_calls for m in case_metrics
        ),
        "avg_auto_route_rate": _safe_mean(
            [m.efficiency.auto_route_rate for m in case_metrics]
        ),
        "avg_exploration_overhead": _safe_mean(
            [m.efficiency.exploration_overhead for m in case_metrics]
        ),
        # Correctness
        "avg_tool_call_hit_rate": _safe_mean(
            [m.correctness.tool_call_hit_rate for m in case_metrics]
        ),
        "avg_evidence_validation_rate": _safe_mean(
            [m.correctness.evidence_validation_rate for m in case_metrics]
        ),
        "avg_category_accuracy": _safe_mean(
            [m.correctness.category_accuracy for m in case_metrics]
        ),
        "avg_severity_accuracy": _safe_mean(
            [m.correctness.severity_accuracy for m in case_metrics]
        ),
        # Evidence Validation
        "avg_validation_rate": _safe_mean(
            [m.evidence_validation.validation_rate for m in case_metrics]
        ),
        "avg_confidence_delta": _safe_mean(
            [m.evidence_validation.avg_confidence_delta for m in case_metrics]
        ),
        "total_rejections": sum(
            m.evidence_validation.rejection_count for m in case_metrics
        ),
    }


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------

def _compute_coverage(
    trace_log: list[dict],
    review: dict,
    case: BenchmarkCase,
) -> CoverageMetrics:
    """Compute coverage metrics: did the agent see the right things?"""

    # Extract context snapshot (first span of type "context")
    context_snap = _find_context_snapshot(trace_log)
    changed_files = set(context_snap.get("changed_files", []))
    files_analyzed = set(review.get("files_analyzed") or [])
    context_files = set(context_snap.get("context_files", []))
    truncated_files = set(context_snap.get("truncated_files", []))

    files_changed_count = len(changed_files) or 1
    file_coverage = len(files_analyzed & changed_files) / files_changed_count

    # Bug file coverage: did the agent access files containing expected bugs?
    bug_files = {ef.file_path for ef in case.expected_findings if ef.required}
    if bug_files:
        accessed_bug_files = bug_files & files_analyzed
        bug_file_coverage = len(accessed_bug_files) / len(bug_files)
    else:
        bug_file_coverage = 1.0  # No bugs expected → perfect coverage

    # Bug line coverage: did tool calls target the specific line ranges?
    tool_spans = _get_tool_spans(trace_log)
    bug_line_coverage = _compute_bug_line_coverage(
        case.expected_findings, tool_spans, files_analyzed
    )

    # Truncated bug files: files with truncated diffs that contain expected bugs
    truncated_bug = sorted(bug_files & truncated_files)

    # Diff truncation rate
    diff_truncation_rate = (
        len(truncated_files) / len(context_files) if context_files else 0.0
    )

    return CoverageMetrics(
        file_coverage=round(file_coverage, 3),
        files_analyzed=len(files_analyzed),
        files_changed=len(changed_files),
        bug_file_coverage=round(bug_file_coverage, 3),
        bug_line_coverage=round(bug_line_coverage, 3),
        truncated_bug_files=truncated_bug,
        diff_truncation_rate=round(diff_truncation_rate, 3),
    )


def _compute_bug_line_coverage(
    expected_findings: list,
    tool_spans: list[dict],
    files_analyzed: set[str],
) -> float:
    """For each expected finding, check if any tool call covered its line range.

    - read_file_diff / read_full_file count as covering all lines in the file
    - read_file_snippet must have an overlapping line range
    - Inline diffs (file in files_analyzed) count as base coverage
    """
    required = [ef for ef in expected_findings if ef.required]
    if not required:
        return 1.0

    covered = 0
    for ef in required:
        # Inline diff counts as base coverage if the file was analyzed
        if ef.file_path in files_analyzed:
            covered += 1
            continue

        # Check explicit tool calls
        for span in tool_spans:
            meta = span.get("metadata", {})
            tool_input = meta.get("tool_input", {})
            file_path = tool_input.get("file_path", "")
            tool_name = meta.get("tool_name", "")

            if file_path != ef.file_path:
                continue

            # Full-file tools cover everything
            if tool_name in ("read_file_diff", "read_full_file", "request_deep_analysis"):
                covered += 1
                break

            # Snippet must overlap with expected line range
            if tool_name == "read_file_snippet":
                start = tool_input.get("start_line", 0)
                end = tool_input.get("end_line", 0)
                if _ranges_overlap(start, end, ef.line_range[0], ef.line_range[1]):
                    covered += 1
                    break

    return covered / len(required)


def _ranges_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Check if two inclusive line ranges overlap."""
    return a_start <= b_end and b_start <= a_end


# ---------------------------------------------------------------------------
# Efficiency
# ---------------------------------------------------------------------------

def _compute_efficiency(
    trace_log: list[dict],
    review: dict,
    score: dict,
    case: BenchmarkCase,
) -> EfficiencyMetrics:
    """Compute efficiency metrics: is the agent using resources well?"""

    tool_spans = _get_tool_spans(trace_log)
    token_usage = review.get("token_usage") or {}
    total_tokens = token_usage.get("total", 0)
    iterations = review.get("iterations") or 1
    tp_count = score.get("true_positives", 0)

    tokens_per_tp = total_tokens / max(1, tp_count)
    tool_calls_total = len(tool_spans)
    tool_calls_per_iter = tool_calls_total / max(1, iterations)

    # Redundant tool calls: same (file, tool) called more than once
    call_sigs = []
    for span in tool_spans:
        meta = span.get("metadata", {})
        file_path = meta.get("tool_input", {}).get("file_path", "")
        tool_name = meta.get("tool_name", "")
        if tool_name != "submit_review":
            call_sigs.append((file_path, tool_name))

    sig_counts = Counter(call_sigs)
    redundant = sum(v - 1 for v in sig_counts.values() if v > 1)

    # Auto-routing rate
    auto_routed = sum(
        1 for s in tool_spans
        if s.get("metadata", {}).get("auto_routed", False)
    )
    auto_route_rate = auto_routed / max(1, tool_calls_total)

    # Exploration overhead: tool calls to files with no expected findings
    bug_files = {ef.file_path for ef in case.expected_findings}
    non_submit_spans = [
        s for s in tool_spans
        if s.get("metadata", {}).get("tool_name") != "submit_review"
    ]
    if non_submit_spans:
        overhead_calls = sum(
            1 for s in non_submit_spans
            if s.get("metadata", {}).get("tool_input", {}).get("file_path", "") not in bug_files
        )
        exploration_overhead = overhead_calls / len(non_submit_spans)
    else:
        exploration_overhead = 0.0

    return EfficiencyMetrics(
        tokens_per_tp=round(tokens_per_tp, 0),
        tool_calls_total=tool_calls_total,
        tool_calls_per_iteration=round(tool_calls_per_iter, 2),
        redundant_tool_calls=redundant,
        auto_route_rate=round(auto_route_rate, 3),
        iterations_used=iterations,
        exploration_overhead=round(exploration_overhead, 3),
    )


# ---------------------------------------------------------------------------
# Correctness
# ---------------------------------------------------------------------------

def _compute_correctness(
    review: dict,
    match_details: list[dict],
    case: BenchmarkCase,
) -> CorrectnessMetrics:
    """Compute correctness metrics: are the agent's decisions accurate?"""

    findings = review.get("findings", [])
    tp_matches = [m for m in match_details if m.get("matched", False)]

    # Tool call hit rate (computed from match data, not trace spans)
    # What fraction of expected findings did the agent's findings actually match?
    bug_files = {ef.file_path for ef in case.expected_findings}
    if findings:
        hits = sum(1 for f in findings if f.get("file_path", "") in bug_files)
        tool_call_hit_rate = hits / len(findings)
    else:
        tool_call_hit_rate = 0.0

    # Confidence calibration: bucket findings by confidence and compute TP rate
    matched_titles = {
        m.get("actual_title") for m in match_details if m.get("matched")
    }
    buckets: dict[str, dict] = {
        "high": {"total": 0, "tp": 0},     # 0.9+
        "medium": {"total": 0, "tp": 0},   # 0.7 - 0.9
    }
    for f in findings:
        conf = f.get("confidence", 0)
        bucket = "high" if conf >= 0.9 else "medium" if conf >= 0.7 else None
        if bucket:
            buckets[bucket]["total"] += 1
            if f.get("title") in matched_titles:
                buckets[bucket]["tp"] += 1

    calibration = {}
    for k, v in buckets.items():
        if v["total"] > 0:
            calibration[k] = round(v["tp"] / v["total"], 3)

    # Evidence validation rate
    if findings:
        validated_count = sum(1 for f in findings if f.get("validated", False))
        evidence_validation_rate = validated_count / len(findings)
    else:
        evidence_validation_rate = 0.0

    # Category accuracy (among TPs only)
    if tp_matches:
        correct_cat = sum(
            1 for m in tp_matches
            if m.get("actual_category") == m.get("expected", {}).get("category")
        )
        category_accuracy = correct_cat / len(tp_matches)
    else:
        category_accuracy = 0.0

    # Severity accuracy (among TPs: actual severity >= expected minimum)
    if tp_matches:
        correct_sev = sum(
            1 for m in tp_matches
            if SEVERITY_RANK.get(m.get("actual_severity", ""), 0)
            >= SEVERITY_RANK.get(m.get("expected", {}).get("severity_min", ""), 0)
        )
        severity_accuracy = correct_sev / len(tp_matches)
    else:
        severity_accuracy = 0.0

    return CorrectnessMetrics(
        tool_call_hit_rate=round(tool_call_hit_rate, 3),
        confidence_calibration=calibration,
        evidence_validation_rate=round(evidence_validation_rate, 3),
        category_accuracy=round(category_accuracy, 3),
        severity_accuracy=round(severity_accuracy, 3),
    )


# ---------------------------------------------------------------------------
# Evidence Validation
# ---------------------------------------------------------------------------

def _compute_evidence_validation(trace_log: list[dict]) -> EvidenceValidationMetrics:
    """Extract evidence validation metrics from the validation span."""
    for span in trace_log:
        if span.get("name") == "evidence_validation" or span.get("span_type") == "validation":
            meta = span.get("metadata", {})
            return EvidenceValidationMetrics(
                validation_rate=round(meta.get("validation_rate", 0.0), 3),
                avg_confidence_delta=round(meta.get("avg_confidence_delta", 0.0), 4),
                rejection_count=meta.get("rejection_count", 0),
                signal_rates=meta.get("signals_summary", {}),
            )
    return EvidenceValidationMetrics()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_context_snapshot(trace_log: list[dict]) -> dict:
    """Find the context_snapshot span and return its metadata."""
    for span in trace_log:
        if span.get("span_type") == "context" or span.get("name") == "context_snapshot":
            return span.get("metadata", {})
    return {}


def _get_tool_spans(trace_log: list[dict]) -> list[dict]:
    """Extract tool-type spans from trace log."""
    return [s for s in trace_log if s.get("span_type") == "tool"]
