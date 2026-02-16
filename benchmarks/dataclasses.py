from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Ground Truth Definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExpectedFinding:
    """A single expected finding in the benchmark ground truth."""
    file_path: str                          # Must match reviewer's file_path exactly
    line_range: tuple[int, int]             # (start, end) inclusive — allows fuzzy line matching
    severity_min: str                       # Minimum acceptable severity: "low" | "medium" | "high" | "critical"
    category: str                           # "bug" | "security" | "performance" | "style"
    description: str                        # Human-readable description of the expected issue
    keywords: list[str]                     # Key terms the finding should reference (for deterministic matching)
    required: bool = True                   # If True, missing this finding is a recall failure


@dataclass(frozen=True)
class ExpectedClean:
    """A file/region that should NOT produce findings (tests false positives)."""
    file_path: str
    description: str                        # Why this is intentionally clean
    max_findings: int = 0                   # How many findings are acceptable (0 = none)


@dataclass(frozen=True)
class BenchmarkCase:
    """A single benchmark case: one PR to review."""
    case_id: str                            # e.g., "null_deref_001"
    name: str                               # Human-readable name
    description: str                        # What this case tests
    base_ref: str                           # Git tag for the base commit
    head_ref: str                           # Git tag for the head commit
    expected_findings: list[ExpectedFinding]
    expected_clean: list[ExpectedClean] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Scoring Results
# ---------------------------------------------------------------------------

@dataclass
class FindingMatch:
    """Details about how an expected finding was matched (or not)."""
    expected: ExpectedFinding
    actual_file_path: Optional[str] = None
    actual_line: Optional[int] = None
    actual_title: Optional[str] = None
    actual_severity: Optional[str] = None
    actual_category: Optional[str] = None
    deterministic_score: float = 0.0        # Tier 1 match score (0.0 - 1.0)
    llm_match: Optional[bool] = None        # Tier 2 LLM verdict (None = not attempted)
    llm_confidence: Optional[float] = None
    llm_reasoning: Optional[str] = None
    matched: bool = False                   # Final verdict


@dataclass
class CaseScore:
    """Scoring result for a single benchmark case."""
    case_id: str
    # Finding-level metrics
    true_positives: int = 0                 # Expected findings that were matched
    false_negatives: int = 0                # Required expected findings NOT matched
    false_positives: int = 0                # Actual findings matching NO expected finding
    bonus_found: int = 0                    # Non-required expected findings that were matched

    # Derived metrics
    precision: float = 0.0                  # TP / (TP + FP)
    recall: float = 0.0                     # TP / (TP + FN)
    f1: float = 0.0                         # Harmonic mean of precision and recall

    # Clean region accuracy
    clean_violations: int = 0               # Findings in expected_clean regions
    clean_total: int = 0                    # Total expected_clean regions

    # Severity accuracy
    severity_exact_match: int = 0
    severity_adequate: int = 0              # Severity >= minimum

    # Per-finding match details (for debugging)
    match_details: list[FindingMatch] = field(default_factory=list)

    # Performance metadata
    token_usage: Optional[dict] = None
    iterations: Optional[int] = None
    wall_time_seconds: float = 0.0


@dataclass
class SuiteScore:
    """Aggregate scoring result for the full benchmark suite."""
    suite_id: str
    timestamp: str
    model: str
    cases: list[CaseScore] = field(default_factory=list)

    # Aggregate metrics
    avg_precision: float = 0.0
    avg_recall: float = 0.0
    avg_f1: float = 0.0
    total_true_positives: int = 0
    total_false_negatives: int = 0
    total_false_positives: int = 0

    # Cost
    total_token_usage: Optional[dict] = None
    total_wall_time_seconds: float = 0.0
