"""
File summary cache implementation with LRU and TTL eviction policies.
Uses (repo_id, commit_sha, file_path, summarizer_version) as the cache key.
"""
from typing import Optional, Tuple, Any
from datetime import datetime
from collections import OrderedDict
import threading
import json
from pathlib import Path


class FileSummaryCache:
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
        ttl_seconds: int = 5184000, # 60 days in seconds
        cache_dir: Optional[str] = None
    ):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache_dir = Path(cache_dir) if cache_dir else None
        
        # OrderedDict maintains insertion order for LRU
        # Structure: {key: (value, timestamp)}
        self._cache: OrderedDict[Tuple[str, str, str, str], Tuple[Any, datetime]] = OrderedDict()
        self._lock = threading.RLock()
        
        # Metadata file path for persistence (set before loading)
        self._metadata_file = self.cache_dir / ".file_summary_cache_metadata.json" if self.cache_dir else None
        
        # If cache_dir is provided, create it and load existing cache
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()
    
    def _make_key(self, repo_id: str, commit_sha: str, file_path: str, summarizer_version: str) -> Tuple[str, str, str, str]:
        """Create a cache key from repo_id, commit_sha, file_path, and summarizer_version."""
        return (repo_id, commit_sha, file_path, summarizer_version)
    
    def _is_expired(self, timestamp: datetime) -> bool:
        """Check if an entry has expired based on TTL."""
        age = datetime.now() - timestamp
        return age.total_seconds() > self.ttl_seconds
    
    def _evict_expired(self):
        """Remove all expired entries from the cache."""
        now = datetime.now()
        expired_keys = []
        expired_files = []
        
        for key, (summary_file_path, timestamp) in self._cache.items():
            if (now - timestamp).total_seconds() > self.ttl_seconds:
                expired_keys.append(key)
                expired_files.append(summary_file_path)
        
        for key in expired_keys:
            del self._cache[key]
        
        # Remove expired summary files
        for summary_file_path in expired_files:
            summary_file = Path(summary_file_path)
            if summary_file.exists():
                try:
                    summary_file.unlink()
                except Exception:
                    pass  # Ignore errors deleting file
        
        # Persist evictions to disk if any occurred
        if expired_keys:
            self._save_to_disk()
    
    def _evict_lru(self):
        """Evict the least recently used entry if cache is full."""
        if len(self._cache) >= self.max_size:
            # Remove the oldest entry (first in OrderedDict)
            key, (summary_file_path, _) = self._cache.popitem(last=False)
            # Remove the summary file if it exists
            summary_file = Path(summary_file_path)
            if summary_file.exists():
                try:
                    summary_file.unlink()
                except Exception:
                    pass  # Ignore errors deleting file
    
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
                            "file_path": key[2],
                            "summarizer_version": key[3],
                            "timestamp": timestamp.isoformat()
                        }
                        for key, (_, timestamp) in self._cache.items()
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
            print(f"Warning: Failed to save file summary cache to disk: {e}")
    
    def _get_summary_file_path(self, repo_id: str, commit_sha: str, file_path: str, summarizer_version: str) -> Optional[Path]:
        """
        Get the file system path for a cached summary JSON file.
        Only works if cache_dir is set.
        
        Args:
            repo_id: Repository identifier
            commit_sha: Commit SHA
            file_path: Path to the file
            summarizer_version: Version of the summarizer
            
        Returns:
            Path to cached summary JSON file, or None if cache_dir not set
        """
        if not self.cache_dir:
            return None
        
        # Create a safe directory structure
        safe_repo_id = repo_id.replace('/', '_').replace('\\', '_').replace(':', '_')
        safe_commit = commit_sha[:8]  # Use short SHA
        safe_file_path = file_path.replace('/', '_').replace('\\', '_').replace(':', '_')
        safe_version = summarizer_version.replace('/', '_').replace('\\', '_').replace(':', '_')
        
        # Create directory structure: cache_dir/repo_id/commit_sha/
        summary_dir = self.cache_dir / safe_repo_id / safe_commit
        summary_file = summary_dir / f"{safe_file_path}_{safe_version}.json"
        return summary_file
    
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
                    file_path = entry["file_path"]
                    summarizer_version = entry["summarizer_version"]
                    timestamp = datetime.fromisoformat(entry["timestamp"])
                    
                    key = self._make_key(repo_id, commit_sha, file_path, summarizer_version)
                    # Only load if not expired and summary file exists
                    if not self._is_expired(timestamp):
                        summary_file = self._get_summary_file_path(repo_id, commit_sha, file_path, summarizer_version)
                        if summary_file and summary_file.exists():
                            # Store the file path as the value
                            self._cache[key] = (str(summary_file), timestamp)
                        else:
                            # File doesn't exist, skip this entry
                            continue
        except Exception as e:
            # If loading fails, start with empty cache
            print(f"Warning: Failed to load file summary cache from disk: {e}")
    
    def get(self, repo_id: str, commit_sha: str, file_path: str, summarizer_version: str) -> Optional[Any]:
        """
        Retrieve a value from the cache.
        
        Args:
            repo_id: Repository identifier
            commit_sha: Commit SHA
            file_path: Path to the file
            summarizer_version: Version of the summarizer
            
        Returns:
            Cached summary dict if found and not expired, None otherwise
        """
        with self._lock:
            self._evict_expired()
            
            key = self._make_key(repo_id, commit_sha, file_path, summarizer_version)
            
            if key not in self._cache:
                return None
            
            summary_file_path, timestamp = self._cache[key]
            
            # Check if expired
            if self._is_expired(timestamp):
                del self._cache[key]
                # Remove the summary file if it exists
                summary_file = Path(summary_file_path)
                if summary_file.exists():
                    try:
                        summary_file.unlink()
                    except Exception:
                        pass  # Ignore errors deleting file
                # Persist removal to disk
                self._save_to_disk()
                return None
            
            # Move to end (most recently used)
            self._cache.move_to_end(key)
        
        # Read the summary from the JSON file (outside the lock)
        summary_file = Path(summary_file_path)
        if not summary_file.exists():
            # File doesn't exist, remove from cache
            with self._lock:
                if key in self._cache:
                    del self._cache[key]
                    self._save_to_disk()
            return None
        
        try:
            with open(summary_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            # If we can't read the file, remove it from cache
            print(f"Warning: Failed to read summary file {summary_file_path}: {e}")
            with self._lock:
                if key in self._cache:
                    del self._cache[key]
                    self._save_to_disk()
            return None
    
    def set(self, repo_id: str, commit_sha: str, file_path: str, summarizer_version: str, value: Any):
        """
        Store a value in the cache.
        
        Args:
            repo_id: Repository identifier
            commit_sha: Commit SHA
            file_path: Path to the file
            summarizer_version: Version of the summarizer
            value: Summary dict to cache (will be saved as JSON)
        """
        # Get the file path for storing the summary
        summary_file = self._get_summary_file_path(repo_id, commit_sha, file_path, summarizer_version)
        if not summary_file:
            # Can't cache without cache_dir
            return
        
        # Write the summary to the JSON file
        try:
            # Create parent directory if it doesn't exist
            summary_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Write to temporary file first, then rename (atomic operation)
            temp_file = summary_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(value, f, indent=2)
            temp_file.replace(summary_file)
        except Exception as e:
            print(f"Warning: Failed to save summary to file {summary_file}: {e}")
            return
        
        # Update cache metadata
        with self._lock:
            self._evict_expired()
            
            key = self._make_key(repo_id, commit_sha, file_path, summarizer_version)
            
            # If key exists, remove it first (will be re-added at end)
            if key in self._cache:
                del self._cache[key]
            
            # Evict LRU if needed
            self._evict_lru()
            
            # Add new entry at end (most recently used) - store the file path
            self._cache[key] = (str(summary_file), datetime.now())
            
            # Persist metadata to disk
            self._save_to_disk()
    
    def remove(self, repo_id: str, commit_sha: str, file_path: str, summarizer_version: str) -> bool:
        """
        Remove an entry from the cache.
        
        Args:
            repo_id: Repository identifier
            commit_sha: Commit SHA
            file_path: Path to the file
            summarizer_version: Version of the summarizer
            
        Returns:
            True if entry was removed, False if it didn't exist
        """
        with self._lock:
            key = self._make_key(repo_id, commit_sha, file_path, summarizer_version)
            if key in self._cache:
                summary_file_path, _ = self._cache[key]
                del self._cache[key]
                # Remove the summary file if it exists
                summary_file = Path(summary_file_path)
                if summary_file.exists():
                    try:
                        summary_file.unlink()
                    except Exception:
                        pass  # Ignore errors deleting file
                # Persist to disk
                self._save_to_disk()
                return True
            return False
    
    def clear(self):
        """Clear all entries from the cache."""
        with self._lock:
            # Remove all summary files
            for summary_file_path, _ in self._cache.values():
                summary_file = Path(summary_file_path)
                if summary_file.exists():
                    try:
                        summary_file.unlink()
                    except Exception:
                        pass  # Ignore errors deleting file
            self._cache.clear()
            self._save_to_disk()
    
    def size(self) -> int:
        """Get the current number of entries in the cache."""
        with self._lock:
            self._evict_expired()
            return len(self._cache)


# Global cache instance
# Can be configured via environment variables or config
_file_summary_cache_instance: Optional[FileSummaryCache] = None


def get_file_summary_cache(
    max_size: int = 100,
    ttl_seconds: int = 5184000,  # 60 days in seconds
    cache_dir: Optional[str] = None
) -> FileSummaryCache:
    """
    Get or create the global file summary cache instance.
    
    Args:
        max_size: Maximum cache size (only used on first call)
        ttl_seconds: TTL in seconds (only used on first call)
        cache_dir: Cache directory (only used on first call)
        
    Returns:
        The global FileSummaryCache instance
    """
    global _file_summary_cache_instance
    
    if _file_summary_cache_instance is None:
        # Use cache_dir from parameter or default to project's cache directory
        if cache_dir is None:
            # Get the cache directory relative to this file's location
            # This file is at cache/file_summary_cache.py, so parent.parent is project root
            project_root = Path(__file__).parent.parent
            cache_dir = str(project_root / "cache" / "file_summaries")
        
        _file_summary_cache_instance = FileSummaryCache(
            max_size=max_size,
            ttl_seconds=ttl_seconds,
            cache_dir=cache_dir
        )
    
    return _file_summary_cache_instance

