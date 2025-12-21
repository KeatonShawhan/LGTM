from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ChangeSet:
    base_commit: str 
    head_commit: str 
    files: list[str]