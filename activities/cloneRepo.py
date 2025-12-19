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
    target_dir: Optional[str] = None,
    shallow: bool = True
):
    """
    Clone a repository at a specific reference.
    
    Args:
        normalized_url: GitHub repository URL (various formats accepted)
        reference: Branch name, tag, or commit SHA
        repo_id: hashed version of the repo_url
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
        commit_sha = None
        if is_commit_sha(reference):
            # Clone without specifying branch, then checkout the specific commit
            if not shallow:
                clone_cmd.append('--no-single-branch')
            clone_cmd.extend([normalized_url, clone_path])
            commit_sha = reference
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
        
        # Get the commit SHA
        if not commit_sha:
            commit_sha = get_commit_sha(clone_path)
        
        activity.heartbeat(f"Clone complete: {clone_path} at {commit_sha}")
        return clone_path, commit_sha
        
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
