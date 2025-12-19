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
    print(f"Starting make_local_files_match_commit: repo_id={repo_id}, repo_path={repo_path}, commit_sha={commit_sha}")
    activity.heartbeat(f"Starting match commit for {repo_id} at {commit_sha}")
    
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
        print(f"Commit {commit_sha} verified to exist in repository")
    except subprocess.CalledProcessError:
        print(f"ERROR: Commit SHA {commit_sha} does not exist in repository")
        raise ValueError(f"Commit SHA does not exist in repository: {commit_sha}")
    except subprocess.TimeoutExpired:
        print(f"ERROR: Git commit verification timed out for {commit_sha}")
        raise RuntimeError("Git commit verification timed out")
    
    # Perform checkout (detached HEAD)
    print(f"Checking out commit {commit_sha} in detached HEAD mode...")
    activity.heartbeat(f"Checking out commit {commit_sha}")
    try:
        result = subprocess.run(
            ["git", "checkout", "--detach", commit_sha],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
            timeout=60
        )
        print(f"Checkout successful. stdout: {result.stdout}")
        if result.stderr:
            print(f"Checkout stderr: {result.stderr}")
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr or e.stdout or "Unknown error"
        print(f"ERROR: Failed to checkout commit {commit_sha}: {error_msg}")
        raise RuntimeError(
            f"Failed to checkout commit {commit_sha}: {error_msg}"
        ) from e
    except subprocess.TimeoutExpired:
        print(f"ERROR: Git checkout timed out for commit {commit_sha}")
        raise RuntimeError(f"Git checkout timed out")
    
    # Verify correct commit
    print(f"Verifying checkout was successful...")
    activity.heartbeat(f"Verifying checkout for {commit_sha}")
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
        print(f"HEAD is now at commit: {actual_commit_sha}")
        
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
            print(f"Requested commit {commit_sha} resolves to: {requested_commit_sha}")
            
            # Verify HEAD matches the requested commit
            if actual_commit_sha != requested_commit_sha:
                raise RuntimeError(
                    f"Checkout failed: HEAD points to {actual_commit_sha} "
                    f"but requested commit {commit_sha} resolves to {requested_commit_sha}"
                )
        except subprocess.CalledProcessError:
            print(f"ERROR: Failed to resolve requested commit SHA: {commit_sha}")
            raise RuntimeError(f"Failed to resolve requested commit SHA: {commit_sha}")
        
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to verify checkout: {e.stderr}")
        raise RuntimeError(f"Failed to verify checkout: {e.stderr}") from e
    
    print(f"Successfully matched local files to commit {commit_sha} for repo {repo_id}")
    activity.heartbeat(f"Successfully matched commit {commit_sha} for {repo_id}")
    
    return {
        "repo_path": str(repo_path),
        "commit_sha": commit_sha,
        "repo_id": repo_id,
        "metadata": {}
    }
