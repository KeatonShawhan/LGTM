from temporalio import activity
from utils.dataclasses import ChangeSet, ChangedFile, PrioritizedFile
from typing import List
import re

# Patterns to ignore
IGNORE_PATTERNS = [
    "node_modules/",
    "vendor/",
    "dist/",
    "build/",
    ".lock",
    ".min.",
    ".generated.",
]


def should_ignore_file(file_path: str) -> bool:
    """
    Check if a file should be ignored based on ignore patterns.
    
    Args:
        file_path: Path to the file
        
    Returns:
        True if file should be ignored, False otherwise
    """
    for pattern in IGNORE_PATTERNS:
        if pattern in file_path:
            return True
    return False


def compute_risk_score(file: ChangedFile) -> tuple[float, List[str]]:
    """
    Compute a risk score for a changed file based on various factors.
    
    Risk factors:
    - Lines changed (more changes = higher risk)
    - File path keywords (sensitive paths like config, security, etc.)
    - File extension (code files vs docs vs tests)
    - Test vs non-test (production code changes are higher risk)
    - Renames (detected by path changes)
    - New files (new files are higher risk)
    
    Args:
        file: ChangedFile object
        
    Returns:
        Tuple of (risk score as float, list of reasons as strings)
        Higher score = more important/risky
    """
    score = 0.0
    reasons = []
    
    # Lines changed - base score
    total_changes = file.added + file.removed
    if total_changes > 0:
        score += total_changes * 0.1  # 0.1 points per line changed
        if total_changes > 100:
            reasons.append(f"large change: {total_changes} lines")
        elif total_changes > 50:
            reasons.append(f"moderate change: {total_changes} lines")
        else:
            reasons.append(f"{total_changes} lines changed")
    
    # File path keywords - important paths get higher scores
    sensitive_keywords = [
        "config", "settings", "security", "auth", "password", "secret",
        "api", "router", "handler", "controller", "middleware",
        "database", "db", "model", "schema", "migration",
        "util", "helper", "common", "core", "lib", "framework"
    ]
    file_path_lower = file.path.lower()
    for keyword in sensitive_keywords:
        if keyword in file_path_lower:
            score += 5.0
            reasons.append(f"sensitive path: {keyword}")
            break  # Only count once
    
    # File extension - prioritize code files
    code_extensions = {
        ".py": 10.0,
        ".js": 8.0,
        ".ts": 8.0,
        ".java": 8.0,
        ".go": 8.0,
        ".rs": 8.0,
        ".cpp": 8.0,
        ".c": 8.0,
        ".rb": 8.0,
        ".php": 8.0,
        ".swift": 8.0,
        ".kt": 8.0,
        ".scala": 8.0,
        ".tsx": 8.0,
        ".jsx": 8.0,
    }
    
    doc_extensions = {
        ".md": -5.0,
        ".txt": -5.0,
        ".rst": -5.0,
        ".adoc": -5.0,
    }
    
    found_ext = False
    for ext, points in code_extensions.items():
        if file.path.endswith(ext):
            score += points
            reasons.append(f"code file: {ext}")
            found_ext = True
            break
    
    if not found_ext:
        for ext, points in doc_extensions.items():
            if file.path.endswith(ext):
                score += points
                reasons.append(f"documentation file: {ext}")
                break
    
    # Test vs non-test - production code is higher risk
    test_patterns = ["test", "spec", "__tests__", "__test__", ".test.", ".spec."]
    is_test_file = any(pattern in file_path_lower for pattern in test_patterns)
    if not is_test_file:
        score += 15.0  # Production code gets bonus
        reasons.append("production code")
    else:
        score += 3.0   # Tests are still important but less critical
        reasons.append("test file")
    
    # New files - higher risk (all additions, no removals)
    if file.added > 0 and file.removed == 0:
        score += 20.0
        reasons.append("new file")
    
    # Large changes - exponential scaling for very large files
    if total_changes > 100:
        score += (total_changes - 100) * 0.5
    if total_changes > 500:
        score += 50.0  # Very large changes are risky
        reasons.append("very large change (>500 lines)")
    
    return (score, reasons)


@activity.defn(name="prioritize_files")
async def prioritize_files(change_set: dict) -> List[PrioritizedFile]:
    """
    Prioritize files in a changeset based on risk score.
    Filters out ignored files and returns sorted list by importance.
    
    Args:
        change_set: ChangeSet dictionary (Temporal serializes dataclasses to dicts)
        
    Returns:
        List of PrioritizedFile objects sorted by risk score (highest first)
    """
    # Convert dict to ChangeSet if needed (though it should come as dict from workflow)
    if isinstance(change_set, dict):
        files_data = change_set.get('files', [])
    else:
        # If it's already a ChangeSet object, convert to dict-like access
        files_data = change_set.files if hasattr(change_set, 'files') else []
    
    # Filter out ignored files and compute risk scores
    prioritized_files = []
    
    for file_data in files_data:
        # Handle both dict and ChangedFile object
        if isinstance(file_data, dict):
            file_path = file_data.get('path', '')
            file_added = file_data.get('added', 0)
            file_removed = file_data.get('removed', 0)
        else:
            file_path = file_data.path
            file_added = file_data.added
            file_removed = file_data.removed
        
        # Skip ignored files
        if should_ignore_file(file_path):
            continue
        
        # Create a ChangedFile-like object for scoring
        file_for_scoring = ChangedFile(
            path=file_path,
            added=file_added,
            removed=file_removed,
            hunks=[]  # We don't need hunks for scoring
        )
        
        # Compute risk score and reasons
        risk_score, reasons = compute_risk_score(file_for_scoring)
        
        # Create PrioritizedFile object (priority will be set after sorting)
        prioritized_file = PrioritizedFile(
            path=file_path,
            risk_score=risk_score,
            priority=0,  # Will be set after sorting
            reasons=reasons
        )
        
        prioritized_files.append(prioritized_file)
    
    # Sort by risk score (highest first)
    prioritized_files.sort(key=lambda x: x.risk_score, reverse=True)
    
    # Assign priority based on index (0 = highest priority)
    for index, prioritized_file in enumerate(prioritized_files):
        # Create a new PrioritizedFile with the correct priority
        # Since it's frozen, we need to create a new instance
        prioritized_files[index] = PrioritizedFile(
            path=prioritized_file.path,
            risk_score=prioritized_file.risk_score,
            priority=index,
            reasons=prioritized_file.reasons
        )
    
    return prioritized_files

