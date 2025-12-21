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


def verify_reference_exists(repo_url: str, reference: str) -> bool:
    """Check if a specific reference (branch, tag, or commit) exists."""
    
    # Check if it's a relative reference
    is_relative, base_ref = is_relative_reference(reference)
    
    if is_relative:
        # Verify the base reference exists
        try:
            result = subprocess.run(
                ['git', 'ls-remote', repo_url, base_ref],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0 and result.stdout.strip():
                return True
            else:
                raise ValueError(f"Base reference '{base_ref}' not found in repository")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            raise e
    
    # Check branches and tags
    try:
        result = subprocess.run(
            ['git', 'ls-remote', repo_url, reference],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0 and result.stdout.strip():
            return True
        
        # For commit SHAs, assume valid
        if re.match(r'^[0-9a-f]{7,40}$', reference):
            return True
        
        raise ValueError(f"Reference '{reference}' not found in repository")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise e

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
async def resolve_cloneable_repo(
    repo_url: str, 
    reference: Optional[str] = None,
    use_ssh: bool = False
):
    """Resolve a GitHub repository URL and reference to ensure it's cloneable."""
    try:
        normalized_url = normalize_github_url(repo_url, use_ssh=use_ssh)
        
        if not verify_remote_repo(normalized_url):
            raise ValueError(normalized_url, False, "Repository does not exist or is not accessible")
        
        if reference:
            if not verify_reference_exists(normalized_url, reference):
                raise ValueError(normalized_url, False, f"Reference '{reference}' not found")
        
        repo_id = generate_repo_id(repo_url)
        return normalized_url, repo_id, None
        
    except ValueError as e:
        raise e
    except Exception as e:
        raise e

