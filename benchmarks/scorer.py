"""
Two-tier scoring: deterministic keyword/location matching (Tier 1),
then LLM-as-judge for unresolved matches (Tier 2).

Uses the Hungarian algorithm for optimal expected→actual assignment.
"""
from utils.dataclasses import ReviewResult, ReviewFinding
from benchmarks.dataclasses import (
    BenchmarkCase, ExpectedFinding, ExpectedClean,
    CaseScore, FindingMatch,
)
from benchmarks.grader import llm_grade_match


SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
MATCH_THRESHOLD = 0.5  # Tier 1 deterministic match threshold


# ---------------------------------------------------------------------------
# Tier 1: Deterministic matching
# ---------------------------------------------------------------------------

def deterministic_match_score(expected: ExpectedFinding, actual: ReviewFinding) -> float:
    """
    Score how well an actual finding matches an expected one.
    Returns 0.0 - 1.0. File path must match (hard gate).
    """
    # Hard gate: file path must match exactly
    if actual.file_path != expected.file_path:
        return 0.0

    score = 0.0

    # Location: line_number within expected range
    if expected.line_range[0] <= actual.line_number <= expected.line_range[1]:
        score += 0.3
    elif abs(actual.line_number - expected.line_range[0]) <= 10:
        score += 0.15  # Close but not exact

    # Category match
    if actual.category == expected.category:
        score += 0.2

    # Severity: must meet minimum
    actual_rank = SEVERITY_RANK.get(actual.severity, 0)
    expected_rank = SEVERITY_RANK.get(expected.severity_min, 0)
    if actual_rank >= expected_rank:
        score += 0.15

    # Keyword matching: fraction of expected keywords in finding text
    combined_text = f"{actual.title} {actual.evidence} {actual.suggestion}".lower()
    if expected.keywords:
        matched_keywords = sum(1 for kw in expected.keywords if kw.lower() in combined_text)
        keyword_ratio = matched_keywords / len(expected.keywords)
        score += 0.35 * keyword_ratio

    return score


# ---------------------------------------------------------------------------
# Optimal assignment (greedy approximation — good enough for <20 findings)
# ---------------------------------------------------------------------------

def _greedy_assignment(
    expected: list[ExpectedFinding],
    actuals: list[ReviewFinding],
) -> list[tuple[int, int, float]]:
    """
    Greedy best-match assignment of expected → actual findings.
    Returns list of (expected_idx, actual_idx, score) tuples.
    """
    # Build score matrix
    scores = []
    for ei, exp in enumerate(expected):
        for ai, act in enumerate(actuals):
            s = deterministic_match_score(exp, act)
            if s > 0:
                scores.append((s, ei, ai))

    # Sort by score descending, greedily assign
    scores.sort(reverse=True)
    used_expected: set[int] = set()
    used_actual: set[int] = set()
    assignments: list[tuple[int, int, float]] = []

    for s, ei, ai in scores:
        if ei not in used_expected and ai not in used_actual:
            assignments.append((ei, ai, s))
            used_expected.add(ei)
            used_actual.add(ai)

    return assignments


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def score_review(
    review_result: ReviewResult,
    case: BenchmarkCase,
    use_llm_grading: bool = True,
) -> CaseScore:
    """
    Score a ReviewResult against a BenchmarkCase's ground truth.

    1. Tier 1: Deterministic matching with greedy assignment
    2. Tier 2: LLM grading for unmatched expected findings
    3. Compute precision, recall, F1
    4. Check clean regions for false positives
    """
    expected = case.expected_findings
    actuals = list(review_result.findings)

    # Tier 1: Deterministic assignment
    assignments = _greedy_assignment(expected, actuals)

    # Track which expected/actual findings are matched
    matched_expected: dict[int, tuple[int, float]] = {}  # ei -> (ai, score)
    matched_actual: set[int] = set()

    for ei, ai, score in assignments:
        if score >= MATCH_THRESHOLD:
            matched_expected[ei] = (ai, score)
            matched_actual.add(ai)

    # Build match details for all expected findings
    match_details: list[FindingMatch] = []

    for ei, exp in enumerate(expected):
        if ei in matched_expected:
            ai, det_score = matched_expected[ei]
            act = actuals[ai]
            match_details.append(FindingMatch(
                expected=exp,
                actual_file_path=act.file_path,
                actual_line=act.line_number,
                actual_title=act.title,
                actual_severity=act.severity,
                actual_category=act.category,
                deterministic_score=det_score,
                matched=True,
            ))
        else:
            # Tier 2: Try LLM grading for unmatched expected findings
            llm_matched = False
            if use_llm_grading:
                # Try each unmatched actual finding
                for ai, act in enumerate(actuals):
                    if ai in matched_actual:
                        continue
                    # Only try if same file
                    if act.file_path != exp.file_path:
                        continue

                    is_match, confidence, reasoning = llm_grade_match(exp, act)
                    if is_match:
                        matched_expected[ei] = (ai, 0.0)
                        matched_actual.add(ai)
                        match_details.append(FindingMatch(
                            expected=exp,
                            actual_file_path=act.file_path,
                            actual_line=act.line_number,
                            actual_title=act.title,
                            actual_severity=act.severity,
                            actual_category=act.category,
                            deterministic_score=0.0,
                            llm_match=True,
                            llm_confidence=confidence,
                            llm_reasoning=reasoning,
                            matched=True,
                        ))
                        llm_matched = True
                        break

            if not llm_matched:
                match_details.append(FindingMatch(
                    expected=exp,
                    matched=False,
                ))

    # Compute metrics
    true_positives = sum(1 for m in match_details if m.matched and m.expected.required)
    bonus_found = sum(1 for m in match_details if m.matched and not m.expected.required)
    false_negatives = sum(1 for m in match_details if not m.matched and m.expected.required)
    false_positives = len(actuals) - len(matched_actual)

    # For cases with NO expected findings (clean PRs), any finding is a FP
    if len(expected) == 0:
        false_positives = len(actuals)

    total_required = sum(1 for e in expected if e.required)
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else (1.0 if total_required == 0 else 0.0)
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else (1.0 if total_required == 0 else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # Severity accuracy
    severity_exact = 0
    severity_adequate = 0
    for m in match_details:
        if m.matched and m.actual_severity:
            actual_rank = SEVERITY_RANK.get(m.actual_severity, 0)
            expected_rank = SEVERITY_RANK.get(m.expected.severity_min, 0)
            if actual_rank == expected_rank:
                severity_exact += 1
            if actual_rank >= expected_rank:
                severity_adequate += 1

    # Clean region violations
    clean_violations = 0
    for ec in case.expected_clean:
        violations = sum(
            1 for f in actuals
            if f.file_path == ec.file_path and f.category in ("bug", "security", "performance")
        )
        if violations > ec.max_findings:
            clean_violations += 1

    return CaseScore(
        case_id=case.case_id,
        true_positives=true_positives,
        false_negatives=false_negatives,
        false_positives=false_positives,
        bonus_found=bonus_found,
        precision=round(precision, 3),
        recall=round(recall, 3),
        f1=round(f1, 3),
        clean_violations=clean_violations,
        clean_total=len(case.expected_clean),
        severity_exact_match=severity_exact,
        severity_adequate=severity_adequate,
        match_details=match_details,
    )
