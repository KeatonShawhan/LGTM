from temporalio import activity
from typing import Tuple, Optional, Dict
import tempfile
import subprocess
import re

def get_commit_sha(repo_path: str) -> str:
    """Get the current commit SHA from a cloned repository."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to get commit SHA: {e.stderr}")

def is_commit_sha(reference: str) -> bool:
    """Check if a reference looks like a commit SHA."""
    return bool(re.match(r'^[0-9a-f]{7,40}', reference))

@activity.defn(name="cloneRepo")
async def clone_repo(
    normalized_url: str, 
    reference: str,
    repo_id: str,
    commit_sha: Optional[str] = None,
    target_dir: Optional[str] = None,
    shallow: bool = True
):
    """
    Clone a repository at a specific reference.
    
    Args:
        normalized_url: GitHub repository URL (various formats accepted)
        reference: Branch name, tag, or commit SHA
        repo_id: hashed version of the repo_url
        commit_sha: Optional commit SHA for verification (if provided, will verify after clone)
        target_dir: Directory to clone into. If None, uses a temp directory
        shallow: Whether to do a shallow clone (--depth 1)
    
    Returns:
        String path to the cloned repository, String commit sha
    """
    import subprocess
    from pathlib import Path
    # Determine target directory
    if target_dir is None:
        # Create a temp directory that won't be auto-deleted
        temp_dir = tempfile.mkdtemp(prefix=f"repo_{repo_id}_")
        clone_path = temp_dir
        print(f"Cloning to temporary directory: {clone_path}")
    else:
        clone_path = target_dir
        Path(clone_path).mkdir(parents=True, exist_ok=True)


    try:
        # Build clone command
        clone_cmd = ['git', 'clone']
        if is_commit_sha(reference):
            # Clone without specifying branch, then checkout the specific commit
            if not shallow:
                clone_cmd.append('--no-single-branch')
            clone_cmd.extend([normalized_url, clone_path])
        else:
            # For branches and tags, use -b flag
            if shallow:
                clone_cmd.extend(['--depth', '1'])
            clone_cmd.extend(['-b', reference, normalized_url, clone_path])
        
        # Execute clone
        activity.heartbeat(f"Cloning {normalized_url} to {clone_path}")
        result = subprocess.run(
            clone_cmd,
            check=True,
            capture_output=True,
            text=True
        )
        
        # Get the commit SHA from the cloned repo
        actual_commit_sha = get_commit_sha(clone_path)
        
        # If commit_sha was provided, verify it matches
        if commit_sha and actual_commit_sha != commit_sha:
            # Try to resolve the provided commit_sha to full SHA
            try:
                resolved_result = subprocess.run(
                    ['git', 'rev-parse', commit_sha],
                    cwd=clone_path,
                    capture_output=True,
                    text=True,
                    check=True
                )
                resolved_sha = resolved_result.stdout.strip()
                if resolved_sha == actual_commit_sha:
                    commit_sha = resolved_sha
                else:
                    activity.heartbeat(f"Warning: Expected commit {commit_sha}, got {actual_commit_sha}")
            except subprocess.CalledProcessError:
                activity.heartbeat(f"Warning: Could not verify commit SHA {commit_sha}")
        
        # Use provided commit_sha if available, otherwise use actual
        final_commit_sha = commit_sha if commit_sha else actual_commit_sha
        
        activity.heartbeat(f"Clone complete: {clone_path} at {final_commit_sha}")
        return clone_path, final_commit_sha
        
    except subprocess.CalledProcessError as e:
        print(f"Clone failed: {e.stderr}")
        # Clean up the directory if clone failed and we created it
        if target_dir is None:
            import shutil
            shutil.rmtree(clone_path, ignore_errors=True)
        raise subprocess.CalledProcessError(e)
    except Exception as e:
        print(f"Unexpected error during clone: {str(e)}")
        if target_dir is None:
            import shutil
            shutil.rmtree(clone_path, ignore_errors=True)
        raise Exception(e)
