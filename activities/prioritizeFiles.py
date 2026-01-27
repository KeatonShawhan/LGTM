from temporalio import activity
from utils.dataclasses import ChangeSet, ChangedFile, PrioritizedFile
from typing import List
import re
import math

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

# Sensitive path patterns with word boundaries to prevent substring false positives
SENSITIVE_PATTERNS = [
    (r'\bconfig\b', "config"),
    (r'\bsettings?\b', "settings"),
    (r'\bsecur(e|ity)\b', "security"),
    (r'\bauth(entication|orization)?\b', "auth"),
    (r'\bpassw(ord|d)\b', "password"),
    (r'\bsecrets?\b', "secret"),
    (r'\bapi\b', "api"),
    (r'\broute[rs]?\b', "router"),
    (r'\bhandler\b', "handler"),
    (r'\bcontroller\b', "controller"),
    (r'\bmiddleware\b', "middleware"),
    (r'\bdatabase\b', "database"),
    (r'\bmodels?\b', "model"),
    (r'\bschema\b', "schema"),
    (r'\bmigrations?\b', "migration"),
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
    - Lines changed (logarithmic scaling with cap)
    - File path keywords (word-boundary matching, allows stacking)
    - File extension (code files vs docs vs tests)
    - Test vs non-test (production code changes are higher risk)
    - New files (new files are higher risk)

    Args:
        file: ChangedFile object

    Returns:
        Tuple of (risk score as float, list of reasons as strings)
        Higher score = more important/risky
    """
    score = 0.0
    reasons = []
    file_path_lower = file.path.lower()

    # Lines changed - logarithmic scaling with cap
    # log2(changes+1) gives ~3.3 for 10 lines, ~6.6 for 100, ~10 for 1000
    total_changes = file.added + file.removed
    if total_changes > 0:
        line_score = math.log2(total_changes + 1) * 2.0
        score += min(line_score, 25.0)  # Cap at 25 points

        if total_changes <= 20:
            reasons.append(f"{total_changes} lines changed")
        elif total_changes <= 100:
            reasons.append(f"moderate change: {total_changes} lines")
        else:
            reasons.append(f"large change: {total_changes} lines")

    # File path keywords - word boundary regex matching with stacking
    matched_keywords = []
    for pattern, label in SENSITIVE_PATTERNS:
        if re.search(pattern, file_path_lower):
            matched_keywords.append(label)

    if matched_keywords:
        # Base 3.0 + 1.0 per match, capped at reasonable level
        keyword_score = 3.0 + min(len(matched_keywords), 4) * 1.0
        score += keyword_score
        reasons.append(f"sensitive path: {', '.join(matched_keywords)}")

    # File extension - prioritize code files (reduced weights)
    code_extensions = {
        ".py": 5.0,
        ".js": 5.0,
        ".ts": 5.0,
        ".java": 5.0,
        ".go": 5.0,
        ".rs": 5.0,
        ".cpp": 5.0,
        ".c": 5.0,
        ".rb": 5.0,
        ".php": 5.0,
        ".swift": 5.0,
        ".kt": 5.0,
        ".scala": 5.0,
        ".tsx": 5.0,
        ".jsx": 5.0,
    }

    doc_extensions = {
        ".md": -3.0,
        ".txt": -3.0,
        ".rst": -3.0,
        ".adoc": -3.0,
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

    # Test vs non-test - production code is higher risk (reduced gap)
    test_patterns = ["test", "spec", "__tests__", "__test__", ".test.", ".spec."]
    is_test_file = any(pattern in file_path_lower for pattern in test_patterns)
    if not is_test_file:
        score += 10.0  # Production code gets bonus (reduced from 15)
        reasons.append("production code")
    else:
        score += 6.0   # Tests are important (increased from 3)
        reasons.append("test file")

    # New files - higher risk (all additions, no removals) - reduced weight
    if file.added > 0 and file.removed == 0:
        score += 12.0  # Reduced from 20
        reasons.append("new file")

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

