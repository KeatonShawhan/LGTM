"""
Cache activities for repository cloning.
"""
from temporalio import activity
from typing import Optional, Tuple
from pathlib import Path
from cache.repo_cache import LRUTTLCache, get_cache
import os


@activity.defn(name="checkRepoCache")
async def check_repo_cache(repo_id: str, commit_sha: str) -> Optional[str]:
    """
    Check if a repository clone is cached.
    
    Args:
        repo_id: Repository identifier
        commit_sha: Commit SHA
        
    Returns:
        Path to cached repository if found and valid, None otherwise
    """
    cache = get_cache()
    
    # Get cached clone path
    cached_path = cache.get(repo_id, commit_sha)
    
    if cached_path is None:
        activity.heartbeat(f"Cache miss for {repo_id}@{commit_sha}")
        return None
    
    # Verify the cached path still exists and is a valid directory
    path = Path(cached_path)
    if not path.exists() or not path.is_dir():
        activity.heartbeat(f"Cached path no longer exists: {cached_path}")
        # Remove from cache if path is invalid
        cache.remove(repo_id, commit_sha)
        return None
    
    # Verify it's still a git repository
    git_dir = path / ".git"
    if not git_dir.exists():
        activity.heartbeat(f"Cached path is not a valid git repo: {cached_path}")
        # Remove from cache if path is invalid
        cache.remove(repo_id, commit_sha)
        return None
    
    activity.heartbeat(f"Cache hit for {repo_id}@{commit_sha}: {cached_path}")
    return str(cached_path)


@activity.defn(name="storeRepoCache")
async def store_repo_cache(repo_id: str, commit_sha: str, clone_path: str):
    """
    Store a repository clone in the cache.
    
    Args:
        repo_id: Repository identifier
        commit_sha: Commit SHA
        clone_path: Path to the cloned repository
    """
    cache = get_cache()
    
    # Verify the path exists before caching
    path = Path(clone_path)
    if not path.exists() or not path.is_dir():
        activity.heartbeat(f"Warning: Cannot cache invalid path: {clone_path}")
        return
    
    # Store in cache
    cache.set(repo_id, commit_sha, clone_path)
    activity.heartbeat(f"Cached {repo_id}@{commit_sha} at {clone_path}")
