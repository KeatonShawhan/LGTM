"""
Repository cache implementation with LRU and TTL eviction policies.
Uses (repo_id, commit_sha) as the cache key.
"""
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timedelta
from collections import OrderedDict
import threading
import json
from pathlib import Path


class LRUTTLCache:
    """
    A cache that evicts entries based on both LRU (Least Recently Used) 
    and TTL (Time To Live) policies.
    
    Args:
        max_size: Maximum number of entries in the cache (LRU eviction)
        ttl_seconds: Time to live in seconds (TTL eviction)
        cache_dir: Optional directory to persist cache metadata
    """
    
    def __init__(
        self, 
        max_size: int = 100, 
        ttl_seconds: int = 3600,
        cache_dir: Optional[str] = None
    ):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache_dir = Path(cache_dir) if cache_dir else None
        
        # OrderedDict maintains insertion order for LRU
        # Structure: {key: (value, timestamp)}
        self._cache: OrderedDict[Tuple[str, str], Tuple[Any, datetime]] = OrderedDict()
        self._lock = threading.RLock()
        
        # Metadata file path for persistence (set before loading)
        self._metadata_file = self.cache_dir / ".cache_metadata.json" if self.cache_dir else None
        
        # If cache_dir is provided, create it and load existing cache
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()
    
    def _make_key(self, repo_id: str, commit_sha: str) -> Tuple[str, str]:
        """Create a cache key from repo_id and commit_sha."""
        return (repo_id, commit_sha)
    
    def _is_expired(self, timestamp: datetime) -> bool:
        """Check if an entry has expired based on TTL."""
        age = datetime.now() - timestamp
        return age.total_seconds() > self.ttl_seconds
    
    def _evict_expired(self):
        """Remove all expired entries from the cache."""
        now = datetime.now()
        expired_keys = [
            key for key, (_, timestamp) in self._cache.items()
            if (now - timestamp).total_seconds() > self.ttl_seconds
        ]
        for key in expired_keys:
            del self._cache[key]
        
        # Persist evictions to disk if any occurred
        if expired_keys:
            self._save_to_disk()
    
    def _evict_lru(self):
        """Evict the least recently used entry if cache is full."""
        if len(self._cache) >= self.max_size:
            # Remove the oldest entry (first in OrderedDict)
            self._cache.popitem(last=False)
    
    def _save_to_disk(self):
        """Save cache metadata to disk for persistence across processes."""
        if not self._metadata_file:
            return
        
        try:
            # Convert cache to serializable format (copy data while holding lock)
            with self._lock:
                cache_data = {
                    "max_size": self.max_size,
                    "ttl_seconds": self.ttl_seconds,
                    "entries": [
                        {
                            "repo_id": key[0],
                            "commit_sha": key[1],
                            "value": value,
                            "timestamp": timestamp.isoformat()
                        }
                        for key, (value, timestamp) in self._cache.items()
                    ]
                }
            
            # Write to temporary file first, then rename (atomic operation)
            # Do this outside the lock to avoid blocking other operations
            temp_file = self._metadata_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            temp_file.replace(self._metadata_file)
        except Exception as e:
            # Don't fail if we can't save - cache will still work in-memory
            print(f"Warning: Failed to save cache to disk: {e}")
    
    def _load_from_disk(self):
        """Load cache metadata from disk."""
        if not self._metadata_file or not self._metadata_file.exists():
            return
        
        try:
            with open(self._metadata_file, 'r') as f:
                cache_data = json.load(f)
            
            # Restore cache entries
            with self._lock:
                self._cache.clear()
                for entry in cache_data.get("entries", []):
                    repo_id = entry["repo_id"]
                    commit_sha = entry["commit_sha"]
                    value = entry["value"]
                    timestamp = datetime.fromisoformat(entry["timestamp"])
                    
                    key = self._make_key(repo_id, commit_sha)
                    # Only load if not expired
                    if not self._is_expired(timestamp):
                        self._cache[key] = (value, timestamp)
        except Exception as e:
            # If loading fails, start with empty cache
            print(f"Warning: Failed to load cache from disk: {e}")
    
    def get(self, repo_id: str, commit_sha: str) -> Optional[Any]:
        """
        Retrieve a value from the cache.
        
        Args:
            repo_id: Repository identifier
            commit_sha: Commit SHA
            
        Returns:
            Cached value if found and not expired, None otherwise
        """
        with self._lock:
            self._evict_expired()
            
            key = self._make_key(repo_id, commit_sha)
            
            if key not in self._cache:
                return None
            
            value, timestamp = self._cache[key]
            
            # Check if expired
            if self._is_expired(timestamp):
                del self._cache[key]
                # Persist removal to disk
                self._save_to_disk()
                return None
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            
            return value
    
    def set(self, repo_id: str, commit_sha: str, value: Any):
        """
        Store a value in the cache.
        
        Args:
            repo_id: Repository identifier
            commit_sha: Commit SHA
            value: Value to cache
        """
        with self._lock:
            self._evict_expired()
            
            key = self._make_key(repo_id, commit_sha)
            
            # If key exists, remove it first (will be re-added at end)
            if key in self._cache:
                del self._cache[key]
            
            # Evict LRU if needed
            self._evict_lru()
            
            # Add new entry at end (most recently used)
            self._cache[key] = (value, datetime.now())
            
            # Persist to disk
            self._save_to_disk()
    
    def remove(self, repo_id: str, commit_sha: str) -> bool:
        """
        Remove an entry from the cache.
        
        Args:
            repo_id: Repository identifier
            commit_sha: Commit SHA
            
        Returns:
            True if entry was removed, False if it didn't exist
        """
        with self._lock:
            key = self._make_key(repo_id, commit_sha)
            if key in self._cache:
                del self._cache[key]
                # Persist to disk
                self._save_to_disk()
                return True
            return False
    
    def clear(self):
        """Clear all entries from the cache."""
        with self._lock:
            self._cache.clear()
    
    def size(self) -> int:
        """Get the current number of entries in the cache."""
        with self._lock:
            self._evict_expired()
            return len(self._cache)
    
    def get_cache_path(self, repo_id: str, commit_sha: str) -> Optional[Path]:
        """
        Get the file system path for a cached repository.
        Only works if cache_dir is set.
        
        Args:
            repo_id: Repository identifier
            commit_sha: Commit SHA
            
        Returns:
            Path to cached repository directory, or None if cache_dir not set
        """
        if not self.cache_dir:
            return None
        
        # Create a safe directory name from repo_id and commit_sha
        safe_repo_id = repo_id.replace('/', '_').replace('\\', '_')
        safe_commit = commit_sha[:8]  # Use short SHA
        cache_path = self.cache_dir / f"{safe_repo_id}_{safe_commit}"
        return cache_path


# Global cache instance
# Can be configured via environment variables or config
_cache_instance: Optional[LRUTTLCache] = None


def get_cache(
    max_size: int = 100,
    ttl_seconds: int = 3600,
    cache_dir: Optional[str] = None
) -> LRUTTLCache:
    """
    Get or create the global cache instance.
    
    Args:
        max_size: Maximum cache size (only used on first call)
        ttl_seconds: TTL in seconds (only used on first call)
        cache_dir: Cache directory (only used on first call)
        
    Returns:
        The global LRUTTLCache instance
    """
    global _cache_instance
    
    if _cache_instance is None:
        # Use cache_dir from parameter or default to project's cache directory
        if cache_dir is None:
            # Get the cache directory relative to this file's location
            # This file is at cache/repo_cache.py, so parent.parent is project root
            project_root = Path(__file__).parent.parent
            cache_dir = str(project_root / "cache" / "repos")
        
        _cache_instance = LRUTTLCache(
            max_size=max_size,
            ttl_seconds=ttl_seconds,
            cache_dir=cache_dir
        )
    
    return _cache_instance
