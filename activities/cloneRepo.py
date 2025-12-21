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

def is_relative_reference(reference: str) -> tuple[bool, str]:
    """
    Check if reference is relative and return (is_relative, base_ref).
    
    Examples:
    - main~3 -> (True, 'main')
    - HEAD^2~1 -> (True, 'HEAD')
    - v1.0.0 -> (False, 'v1.0.0')
    """
    # Pattern matches: base_name followed by any combination of ~N or ^N
    pattern = r'^([\w\-\/\.]+)([~^]\d*)+$'
    match = re.match(pattern, reference)
    
    if match:
        return True, match.group(1)
    return False, reference

@activity.defn(name="clone_repo")
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
        reference: Branch name, tag, commit SHA, or relative reference (e.g., main~3)
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
        # Check if it's a relative reference
        is_relative, base_ref = is_relative_reference(reference)
        
        # Build clone command
        clone_cmd = ['git', 'clone']
        needs_checkout = False
        checkout_ref = None
        
        if is_commit_sha(reference):
            # Clone without specifying branch, then checkout the specific commit
            if not shallow:
                clone_cmd.append('--no-single-branch')
            clone_cmd.extend([normalized_url, clone_path])
            needs_checkout = True
            checkout_ref = reference
            
        elif is_relative:
            # For relative references, clone the base ref then checkout the relative ref
            # Can't use shallow clone with relative refs (need history)
            clone_cmd.extend(['-b', base_ref, normalized_url, clone_path])
            needs_checkout = True
            checkout_ref = reference
            
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
        
        # If we need to checkout a specific commit or relative reference
        if needs_checkout:
            activity.heartbeat(f"Checking out {checkout_ref}")
            checkout_result = subprocess.run(
                ['git', 'checkout', checkout_ref],
                cwd=clone_path,
                check=True,
                capture_output=True,
                text=True
            )
        
        # Get the commit SHA
        commit_sha = get_commit_sha(clone_path)
        
        activity.heartbeat(f"Clone complete: {clone_path} at {commit_sha}")
        return clone_path, commit_sha
        
    except subprocess.CalledProcessError as e:
        print(f"Clone failed: {e.stderr}")
        # Clean up the directory if clone failed and we created it
        if target_dir is None:
            import shutil
            shutil.rmtree(clone_path, ignore_errors=True)
        raise subprocess.CalledProcessError(e.returncode, e.cmd, e.output, e.stderr)
    except Exception as e:
        print(f"Unexpected error during clone: {str(e)}")
        if target_dir is None:
            import shutil
            shutil.rmtree(clone_path, ignore_errors=True)
        raise e