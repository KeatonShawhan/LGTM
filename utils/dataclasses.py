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
class FileContext:
    """Context for individual files (Layer 1+)"""
    path: str
    risk_score: float
    added: int
    removed: int
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