"""
Tier 2: LLM-as-judge for fuzzy semantic matching.

Uses Haiku for cheap, fast grading of whether an actual finding
describes the same issue as an expected finding.
"""
import json
import os
from benchmarks.dataclasses import ExpectedFinding
from utils.dataclasses import ReviewFinding

GRADER_MODEL = "claude-haiku-4-5-20251001"

GRADER_PROMPT = """You are evaluating whether a code review finding matches an expected ground truth finding.

Expected finding (ground truth):
- File: {expected_file}
- Lines: {expected_lines}
- Category: {expected_category}
- Description: {expected_description}

Actual finding from the reviewer:
- File: {actual_file}
- Line: {actual_line}
- Severity: {actual_severity}
- Category: {actual_category}
- Title: {actual_title}
- Evidence: {actual_evidence}
- Suggestion: {actual_suggestion}

Does the actual finding identify the SAME issue as the expected finding?
The reviewer may use different wording, focus on different aspects, or categorize it differently — but the core issue must be the same.

Respond with ONLY valid JSON:
{{"match": true, "confidence": 0.9, "reasoning": "brief explanation"}}
or
{{"match": false, "confidence": 0.9, "reasoning": "brief explanation"}}"""


def llm_grade_match(
    expected: ExpectedFinding,
    actual: ReviewFinding,
) -> tuple[bool, float, str]:
    """
    Use LLM to determine if an actual finding matches an expected one.

    Returns:
        (is_match, confidence, reasoning)
    """
    try:
        from anthropic import Anthropic
        client = Anthropic()

        prompt = GRADER_PROMPT.format(
            expected_file=expected.file_path,
            expected_lines=f"{expected.line_range[0]}-{expected.line_range[1]}",
            expected_category=expected.category,
            expected_description=expected.description,
            actual_file=actual.file_path,
            actual_line=actual.line_number,
            actual_severity=actual.severity,
            actual_category=actual.category,
            actual_title=actual.title,
            actual_evidence=actual.evidence,
            actual_suggestion=actual.suggestion,
        )

        response = client.messages.create(
            model=GRADER_MODEL,
            max_tokens=256,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        # Parse JSON from response
        result = json.loads(text)
        return (
            bool(result.get("match", False)),
            float(result.get("confidence", 0.0)),
            str(result.get("reasoning", "")),
        )

    except Exception as e:
        # If LLM grading fails, return no match rather than crashing
        return (False, 0.0, f"LLM grading failed: {e}")
