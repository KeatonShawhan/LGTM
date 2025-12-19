from temporalio import activity
import re
import subprocess
from urllib.parse import urlparse
from typing import Tuple, Optional
import hashlib

def normalize_github_url(url: str, use_ssh: bool = False) -> str:
    """Convert various GitHub URL formats to a cloneable Git URL."""
    url = url.rstrip('/').rstrip('.git')
    
    patterns = [
        r'github\.com[:/]([^/]+)/([^/]+)',
        r'^([^/]+)/([^/]+)$',
    ]
    
    match = None
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            owner, repo = match.groups()
            break
    
    if not match:
        raise ValueError(f"Could not parse GitHub URL: {url}")
    
    if use_ssh:
        return f"git@github.com:{owner}/{repo}.git"
    else:
        return f"https://github.com/{owner}/{repo}.git"


def verify_remote_repo(repo_url: str) -> bool:
    """Verify that a remote repository exists and is accessible."""
    try:
        result = subprocess.run(
            ['git', 'ls-remote', '--heads', repo_url],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def verify_reference_exists(repo_url: str, reference: str) -> bool:
    """Check if a specific reference (branch, tag, or commit) exists."""
    try:
        result = subprocess.run(
            ['git', 'ls-remote', repo_url, reference],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0 and result.stdout.strip():
            return True
        
        if re.match(r'^[0-9a-f]{7,40}$', reference):
            return True
        
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

def generate_repo_id(repo_url: str) -> str:
    """Generate a unique repo_id by hashing the normalized repo URL."""
    # Normalize URL to ensure consistent hashing
    try:
        normalized_url = normalize_github_url(repo_url)
    except ValueError:
        normalized_url = repo_url
    
    # Use SHA256 hash and take first 16 characters for reasonable length
    hash_obj = hashlib.sha256(normalized_url.encode('utf-8'))
    return hash_obj.hexdigest()[:16]

@activity.defn(name='resolveCloneableRepo')
def resolve_cloneable_repo(
    repo_url: str, 
    reference: Optional[str] = None,
    use_ssh: bool = False
) -> Tuple[str, str, str]:
    """Resolve a GitHub repository URL and reference to ensure it's cloneable."""
    try:
        normalized_url = normalize_github_url(repo_url, use_ssh=use_ssh)
        
        if not verify_remote_repo(normalized_url):
            return normalized_url, False, "Repository does not exist or is not accessible"
        
        if reference:
            if not verify_reference_exists(normalized_url, reference):
                return normalized_url, False, f"Reference '{reference}' not found"
        
        repo_id = generate_repo_id(repo_url)
        return normalized_url, repo_id, None
        
    except ValueError as e:
        return repo_url, False, str(e)
    except Exception as e:
        return repo_url, False, f"Unexpected error: {str(e)}"

