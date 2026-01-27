from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Hunk:
    start: int
    lines: list[str]

@dataclass
class ChangedFile:
    path: str
    added: int
    removed: int
    hunks: list[Hunk]

@dataclass
class ChangeSet:
    base_commit: str 
    head_commit: str 
    files: list[ChangedFile]

@dataclass
class RepoHandle:
    repo_id: str
    repo_path: str
    commit_sha: str


@dataclass(frozen=True)
class PrioritizedFile:
    path: str
    risk_score: float
    priority: int  # 0 = highest priority
    reasons: list[str]


# Code Context dataclasses
@dataclass(frozen=True)
class Totals:
    files_changed: int
    files_added: int
    files_deleted: int
    lines_added: int
    lines_removed: int
    total_hunks: int


@dataclass(frozen=True)
class FileTypeStats:
    count: int
    lines_added: int
    lines_removed: int


@dataclass(frozen=True)
class ContextOverview:
    totals: Totals
    file_breakdown: dict[str, FileTypeStats]
    flags: list[str]


@dataclass(frozen=True)
class ContextMetadata:
    """Metadata for librarian bookkeeping"""
    pass  # Can be extended later


@dataclass(frozen=True)
class FileSummary:
    """Structured summary of a file's purpose and behavior"""
    purpose: str
    behavior: str
    key_functions: list[str]
    dependencies: list[str]


@dataclass(frozen=True)
class FileContext:
    """Context for individual files (Layer 1+)"""
    path: str
    risk_score: float
    added: int
    removed: int
    reasons: list[str]
    summary: Optional[FileSummary] = None
    # Can be extended with more file-specific context later


@dataclass(frozen=True)
class CodeContext:
    # Artifact identity
    repo_id: str
    base_commit: str
    head_commit: str

    # Context layers
    overview: ContextOverview          # Layer 0
    files: dict[str, FileContext]      # Layer 1+

    # Librarian bookkeeping
    metadata: ContextMetadata


# Code Review dataclasses
@dataclass(frozen=True)
class ReviewFinding:
    """Individual code review finding"""
    file_path: str
    line_number: int              # Primary line where issue occurs
    severity: str                 # "critical", "high", "medium", "low"
    category: str                 # "bug", "security", "performance", "style"
    title: str                    # Short description (1 line)
    evidence: str                 # Code snippet showing the issue
    suggestion: str               # Recommended fix or action
    confidence: float             # 0.0-1.0 confidence in this finding
    validated: bool = False       # Set by validation step


@dataclass(frozen=True)
class ReviewResult:
    """Complete code review result"""
    summary: str                  # Executive summary of the review
    warnings: list[str]           # High-level warnings/concerns
    overall_confidence: float     # 0.0-1.0 overall confidence
    findings: list[ReviewFinding] # Individual findings
    stats: dict[str, int]         # e.g., {"critical": 1, "high": 3, ...}