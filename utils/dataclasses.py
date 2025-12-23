from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ChangeSet:
    base_commit: str 
    head_commit: str 
    files: list[ChangedFile]

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

