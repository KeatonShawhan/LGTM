from temporalio import activity
import os
import subprocess
from pathlib import Path

@activity.defn(name="MakeLocalFilesMatchCommit")
async def make_local_files_match_commit(
    repo_id: str,
    repo_path: str,
    commit_sha: str,
) -> dict:
    """
    Perform a git checkout to the provided commit SHA for the given repository.
    
    Args:
        repo_path: Path to the local git repository
        commit_sha: The commit SHA to checkout (full or abbreviated)
        repo_id: Unique identifier for the repository
    
    Returns:
        Dictionary containing:
            - "repo_path": str path to the repository
            - "commit_sha": str the commit SHA that was checked out
            - "repo_id": str unique identifier for the repository
            - "metadata": empty for now
    
    """
    # Verify repo_path exists
    repo_path_obj = Path(repo_path)
    if not repo_path_obj.exists():
        raise ValueError(f"Repository path does not exist: {repo_path}")
    
    if not repo_path_obj.is_dir():
        raise ValueError(f"Repository path is not a directory: {repo_path}")
    
    # Verify commit exists
    try:
        result = subprocess.run(
            ["git", "cat-file", "-e", commit_sha],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
            timeout=30
        )
    except subprocess.CalledProcessError:
        raise ValueError(f"Commit SHA does not exist in repository: {commit_sha}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Git commit verification timed out")
    
    # Perform checkout (detached HEAD)
    try:
        result = subprocess.run(
            ["git", "checkout", "--detach", commit_sha],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
            timeout=60
        )
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr or e.stdout or "Unknown error"
        raise RuntimeError(
            f"Failed to checkout commit {commit_sha}: {error_msg}"
        ) from e
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Git checkout timed out")
    
    # Verify correct commit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
            timeout=30
        )
        actual_commit_sha = result.stdout.strip() # Gets the commit SHA of HEAD after checkout
        
        try:
            resolved_result = subprocess.run(
                ["git", "rev-parse", commit_sha],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
                timeout=30
            )
            requested_commit_sha = resolved_result.stdout.strip() # Gets the commit SHA of requested commit
            
            # Verify HEAD matches the requested commit
            if actual_commit_sha != requested_commit_sha:
                raise RuntimeError(
                    f"Checkout failed: HEAD points to {actual_commit_sha} "
                    f"but requested commit {commit_sha} resolves to {requested_commit_sha}"
                )
        except subprocess.CalledProcessError:
            raise RuntimeError(f"Failed to resolve requested commit SHA: {commit_sha}")
        
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to verify checkout: {e.stderr}") from e
    
    return {
        "repo_path": str(repo_path),
        "commit_sha": commit_sha,
        "repo_id": repo_id,
        "metadata": {}
    }
