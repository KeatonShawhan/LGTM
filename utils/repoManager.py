"""Repository management utilities"""
import subprocess
import os
from pathlib import Path
from typing import Tuple

class RepoManager:
    """Manages local repository clones and updates"""
    
    def __init__(self, cache_dir: str = "./repo_cache"):
        """
        Initialize repo manager.
        
        Args:
            cache_dir: Directory to store cloned repos
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
    
    def get_repo_path(self, repo_url: str) -> Path:
        """Get local path for a repo URL"""
        # Convert URL to safe directory name
        # https://github.com/user/repo.git -> user_repo
        repo_name = repo_url.rstrip('/').split('/')[-1].replace('.git', '')
        owner = repo_url.rstrip('/').split('/')[-2]
        return self.cache_dir / f"{owner}_{repo_name}"
    
    def ensure_repo_updated(
        self,
        repo_url: str,
        branch: str = "main",
        github_token: str = None
    ) -> Tuple[str, str]:
        """
        Ensure repo is cloned and up-to-date.
        
        Returns:
            (repo_path, current_commit_hash)
        """
        repo_path = self.get_repo_path(repo_url)
        
        # Add token to URL if provided
        clone_url = repo_url
        if github_token and repo_url.startswith("https://"):
            clone_url = repo_url.replace("https://", f"https://{github_token}@")
        
        # Clone if doesn't exist
        if not repo_path.exists():
            print(f"Cloning {repo_url}...")
            subprocess.run(
                ['git', 'clone', '--branch', branch, clone_url, str(repo_path)],
                check=True,
                capture_output=True
            )
            print(f"Cloned to {repo_path}")
        else:
            # Pull latest changes
            print(f"Updating {repo_path}...")
            subprocess.run(
                ['git', 'fetch', 'origin', branch],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            subprocess.run(
                ['git', 'reset', '--hard', f'origin/{branch}'],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            print(f"Updated to latest")
        
        # Get current commit hash
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        commit_hash = result.stdout.strip()
        
        # Get commit info
        result = subprocess.run(
            ['git', 'log', '-1', '--oneline'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        commit_info = result.stdout.strip()
        
        print(f"Current commit: {commit_info}")
        
        return str(repo_path), commit_hash

__all__ = ['RepoManager']