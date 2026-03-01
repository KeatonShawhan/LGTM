# LGTM Benchmark Grading Rubric

This document describes how benchmark cases are scored and what constitutes a passing review.

---

## Scoring Overview

Each benchmark case is scored using a **two-tier matching system** that compares the review agent's actual findings against the case's `expected_findings` ground truth.

---

## Tier 1 — Deterministic Matching

Each actual finding is scored against each expected finding using a weighted rubric. If the score meets the threshold, the findings are considered a match.

### Hard Gate

| Criterion | Rule |
|-----------|------|
| **File path** | Must match exactly. If the file paths differ, score = 0.0 and matching stops. |

### Weighted Components (applied only when file matches)

| Component | Weight | Rule |
|-----------|--------|------|
| **Location** | 0.30 | Actual line is within `expected.line_range` → full score. Within ±10 lines of range → 0.15. Outside → 0.0. |
| **Category** | 0.20 | Actual category matches expected category string exactly. |
| **Severity** | 0.15 | Actual severity meets or exceeds `severity_min` (low < medium < high < critical). |
| **Keywords** | 0.35 | `matched_keywords / len(expected.keywords)` — fraction of expected keywords present in title + evidence + suggestion text. |

**Match threshold: ≥ 0.50**

A score ≥ 0.50 constitutes a Tier 1 match. A score < 0.50 proceeds to Tier 2 evaluation.

### Assignment

Matches are assigned greedily by descending score. Each expected finding and each actual finding is matched at most once (one-to-one assignment).

---

## Tier 2 — LLM-as-Judge

Applied to expected findings that were not matched in Tier 1.

- For each unmatched expected finding, the grader checks same-file actual findings using an LLM call.
- Returns: `(is_match: bool, confidence: float, reasoning: str)`
- A Tier 2 match counts as a true positive with the assigned confidence score.
- Model: Claude Haiku (fast, cheap, consistent).

---

## Metrics

| Metric | Formula | Notes |
|--------|---------|-------|
| **True Positive (TP)** | Expected finding was matched (Tier 1 or Tier 2) | |
| **False Negative (FN)** | Required expected finding was NOT matched | Only `required: true` findings count toward FN |
| **False Positive (FP)** | Actual finding has no expected match | Every unmatched actual finding is an FP |
| **Bonus Found** | Non-required expected finding was matched | Does not affect precision/recall |
| **Precision** | TP / (TP + FP) | 0.0 if denominator is 0 |
| **Recall** | TP / (TP + FN) | 0.0 if denominator is 0; 1.0 if no required findings |
| **F1** | 2 × P × R / (P + R) | Harmonic mean |

### Aggregate Metrics

| Type | Method |
|------|--------|
| **Macro** | Mean of per-case F1 / Precision / Recall |
| **Micro** | Global TP, FP, FN summed across all cases, then compute P/R/F1 |

---

## Clean Region Violations

Cases may define `expected_clean` regions — files or areas that should receive zero findings (or at most `max_findings`).

- A **clean violation** is counted when the agent produces a non-style finding in an `expected_clean` region beyond the allowed threshold.
- Style-category findings (`category: "style"`) do not count as violations.
- Tracked separately from FP; useful for measuring hallucination on obviously-clean code.

---

## Severity Scale

Severity levels are ordered: `low < medium < high < critical`

- `severity_min` in an expected finding defines the **minimum acceptable severity**.
- The agent's severity must meet or exceed `severity_min` for that component to score.
- A finding reported at `low` when `severity_min` is `high` scores 0 on the severity component.

---

## Category Values

| Value | When to use |
|-------|-------------|
| `bug` | Logic errors, null dereferences, off-by-ones, crashes |
| `security` | SQL injection, prototype pollution, auth bypass, injection vectors |
| `performance` | N+1 queries, algorithmic complexity, unnecessary I/O in loops |
| `style` | Naming, formatting, documentation (never penalised in clean regions) |

---

## What Makes a Good Benchmark Case

1. **Single, clear bug** — one primary expected finding per case; optional secondary findings marked `required: false`.
2. **Predictable line range** — the bug is isolated to a small function; `line_range` should be ≤ 15 lines.
3. **Distinctive keywords** — at least 5 keywords that uniquely identify the bug pattern without being too generic.
4. **Clean counterpart** — every bug case includes at least one `expected_clean` region in the same diff to test false-positive discipline.
5. **Language diversity** — cases span Python, JavaScript/TypeScript, and Go to avoid language-specific overfitting.

---

## Case Taxonomy

| Tag | Description |
|-----|-------------|
| `easy` | Bug is obvious from the diff with minimal context (e.g., missing None check) |
| `medium` | Bug requires understanding the function's contract or concurrency model |
| `hard` | Bug requires cross-file reasoning or subtle semantic knowledge |
| `clean` | No bugs; tests that the system does not hallucinate findings |
| `false-positive-test` | Alias for clean cases used specifically to measure FP rate |

---

## Suite Composition (v2)

| Language | Cases | Clean Cases | Total |
|----------|-------|-------------|-------|
| Python | 7 + 2 = 9 | 1 (clean_refactor_005) | 9 |
| JavaScript/TypeScript | 4 | 1 (js_clean_refactor_011) | 4 |
| Go | 4 | 0 | 4 |
| **Total** | **15 bug** | **2 clean** | **17** |

Bug category breakdown: 9 bugs, 4 security, 2 performance, 2 clean.
