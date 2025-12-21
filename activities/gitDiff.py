import subprocess
from pathlib import Path
from typing import Optional, List
from utils.changeSet import ChangeSet
from temporalio import activity

@activity.defn(name='get_diff_from_main')
async def get_diff_from_main(repo_path: str, target_branch: str = "main") -> ChangeSet:
    """
    Compute the difference between the current state of a local repo and a target branch.
    
    Args:
        repo_path: Path to the local git repository
        target_branch: Branch to compare against (default: "main")
    
    Returns:
        CommitRange with base_commit (target branch), head_commit (current HEAD), 
        and list of changed files
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
        
        # Get the list of changed files between base and head
        diff_result = subprocess.run(
            ['git', 'diff', '--name-only', base_commit, head_commit],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        
        files = [f for f in diff_result.stdout.strip().split('\n') if f]
        
        return ChangeSet(
            base_commit=base_commit,
            head_commit=head_commit,
            files=files
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
            import re
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