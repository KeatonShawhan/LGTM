from temporalio import activity
from typing import Tuple, Optional, Dict
import tempfile
import subprocess


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

@activity.defn(name="cloneRepo")
async def clone_repo(
    normalized_url: str, 
    reference: str,
    repo_id: str,
    target_dir: Optional[str] = None,
    shallow: bool = True
) -> Tuple[str, str]:
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
        
        if shallow:
            clone_cmd.extend(['--depth', '1'])
        
        clone_cmd.extend(['-b', reference, normalized_url, clone_path])
        
        # Execute clone
        result = subprocess.run(
            clone_cmd,
            check=True,
            capture_output=True,
            text=True
        )
        
        commit_sha = get_commit_sha(clone_path)
        return clone_path, commit_sha
        
    except subprocess.CalledProcessError as e:
        print(f"Clone failed: {e.stderr}")
        # Clean up the directory if clone failed and we created it
        if target_dir is None:
            import shutil
            shutil.rmtree(clone_path, ignore_errors=True)
        return None, None
    except Exception as e:
        print(f"Unexpected error during clone: {str(e)}")
        if target_dir is None:
            import shutil
            shutil.rmtree(clone_path, ignore_errors=True)
        return None, None
