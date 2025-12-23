import subprocess
from pathlib import Path
from typing import Optional, List
from utils.dataclasses import ChangeSet, Hunk, ChangedFile
from temporalio import activity
import re

def parse_diff_output(diff_output: str) -> list[ChangedFile]:
    """
    Parse git diff output into ChangedFile objects with hunks.
    
    Args:
        diff_output: Raw output from git diff command
    
    Returns:
        List of ChangedFile objects
    """
    changed_files = []
    current_file = None
    current_hunk = None
    
    lines = diff_output.split('\n')
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # New file diff starts with "diff --git"
        if line.startswith('diff --git'):
            # Save previous file if exists
            if current_file and current_hunk:
                current_file.hunks.append(current_hunk)
                changed_files.append(current_file)
            
            current_file = None
            current_hunk = None
            
        # File path line: "--- a/path" or "+++ b/path"
        elif line.startswith('+++ b/'):
            file_path = line[6:]  # Remove "+++ b/"
            if file_path == '/dev/null':
                # File was deleted
                file_path = lines[i-1][6:]  # Get from "--- a/" line
            
            current_file = ChangedFile(
                path=file_path,
                added=0,
                removed=0,
                hunks=[]
            )
            
        # Hunk header: "@@ -start,count +start,count @@"
        elif line.startswith('@@'):
            # Save previous hunk if exists
            if current_hunk and current_file:
                current_file.hunks.append(current_hunk)
            
            # Parse hunk header to get starting line
            match = re.match(r'@@ -(\d+),?\d* \+(\d+),?\d* @@', line)
            if match:
                start_line = int(match.group(2))  # Use the "+" side (new file)
                current_hunk = Hunk(start=start_line, lines=[])
            
        # Hunk content lines
        elif current_hunk is not None:
            if line.startswith('+') and not line.startswith('+++'):
                # Line added
                current_hunk.lines.append(line)
                if current_file:
                    current_file.added += 1
            elif line.startswith('-') and not line.startswith('---'):
                # Line removed
                current_hunk.lines.append(line)
                if current_file:
                    current_file.removed += 1
            elif line.startswith(' '):
                # Context line (unchanged)
                current_hunk.lines.append(line)
        
        i += 1
    
    # Don't forget the last file and hunk
    if current_file:
        if current_hunk:
            current_file.hunks.append(current_hunk)
        changed_files.append(current_file)
    
    return changed_files


@activity.defn(name='get_diff_from_main')
async def get_diff_from_main(repo_path: str, target_branch: str = "main") -> ChangeSet:
    """
    Compute the difference between the current state of a local repo and a target branch.
    
    Args:
        repo_path: Path to the local git repository
        target_branch: Branch to compare against (default: "main")
    
    Returns:
        ChangeSet with base_commit (target branch), head_commit (current HEAD), 
        and list of ChangedFile objects with hunks
    """
    try:
        # Ensure we're in a git repository
        repo_path = Path(repo_path).resolve()
        
        # Get the current HEAD commit
        head_result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        head_commit = head_result.stdout.strip()
        
        # Get the target branch commit (e.g., main)
        # First, try to get it from origin
        base_result = subprocess.run(
            ['git', 'rev-parse', f'origin/{target_branch}'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False  # Don't fail if origin doesn't exist
        )
        
        # If origin doesn't exist, try local branch
        if base_result.returncode != 0:
            base_result = subprocess.run(
                ['git', 'rev-parse', target_branch],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
            )
        
        base_commit = base_result.stdout.strip()
        
        # Get the unified diff with context
        diff_result = subprocess.run(
            ['git', 'diff', '-U3', base_commit, head_commit],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        
        # Parse the diff output into ChangedFile objects
        changed_files = parse_diff_output(diff_result.stdout)
        
        return ChangeSet(
            base_commit=base_commit,
            head_commit=head_commit,
            files=changed_files
        )
        
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Git command failed: {e.stderr}")


def get_diff_stats(repo_path: str, base_commit: str, head_commit: str) -> dict:
    """
    Get detailed statistics about the diff between two commits.
    
    Returns dict with insertions, deletions, and files changed.
    """
    try:
        # Get detailed diff stats
        result = subprocess.run(
            ['git', 'diff', '--shortstat', base_commit, head_commit],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        
        # Parse output like: "5 files changed, 123 insertions(+), 45 deletions(-)"
        output = result.stdout.strip()
        stats = {
            'files_changed': 0,
            'insertions': 0,
            'deletions': 0
        }
        
        if 'file' in output:
            files_match = re.search(r'(\d+) file', output)
            insertions_match = re.search(r'(\d+) insertion', output)
            deletions_match = re.search(r'(\d+) deletion', output)
            
            if files_match:
                stats['files_changed'] = int(files_match.group(1))
            if insertions_match:
                stats['insertions'] = int(insertions_match.group(1))
            if deletions_match:
                stats['deletions'] = int(deletions_match.group(1))
        
        return stats
        
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Git command failed: {e.stderr}")


def get_diff_content(repo_path: str, base_commit: str, head_commit: str, 
                     file_path: Optional[str] = None) -> str:
    """
    Get the actual diff content between two commits.
    
    Args:
        repo_path: Path to repository
        base_commit: Base commit SHA
        head_commit: Head commit SHA
        file_path: Optional specific file to diff (if None, diffs all files)
    
    Returns:
        The unified diff as a string
    """
    try:
        cmd = ['git', 'diff', base_commit, head_commit]
        if file_path:
            cmd.append('--')
            cmd.append(file_path)
        
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        
        return result.stdout
        
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Git command failed: {e.stderr}")


def get_changed_file_by_path(changeset: ChangeSet, file_path: str) -> Optional[ChangedFile]:
    """
    Helper function to get a specific ChangedFile by path.
    
    Args:
        changeset: The ChangeSet to search
        file_path: Path to the file
    
    Returns:
        ChangedFile if found, None otherwise
    """
    for changed_file in changeset.files:
        if changed_file.path == file_path:
            return changed_file
    return None


# Example usage
if __name__ == "__main__":
    repo_path = "/path/to/your/repo"
    
    # Get the diff from main
    diff = get_diff_from_main(repo_path)
    
    print(f"Comparing commits:")
    print(f"  Base (main): {diff.base_commit}")
    print(f"  Head (current): {diff.head_commit}")
    print(f"\nChanged files ({len(diff.files)}):")
    for file in diff.files:
        print(f"  - {file}")
    
    # Get detailed stats
    stats = get_diff_stats(repo_path, diff.base_commit, diff.head_commit)
    print(f"\nStats:")
    print(f"  Files changed: {stats['files_changed']}")
    print(f"  Insertions: +{stats['insertions']}")
    print(f"  Deletions: -{stats['deletions']}")
    
    # Get diff content for a specific file
    if diff.files:
        content = get_diff_content(repo_path, diff.base_commit, diff.head_commit, 
                                   file_path=diff.files[0])
        print(f"\nDiff for {diff.files[0]}:")
        print(content[:500])  # Print first 500 chars