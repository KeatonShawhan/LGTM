from temporalio import activity
import re
import subprocess
from urllib.parse import urlparse
from typing import Tuple, Optional

def normalize_github_url(url: str, use_ssh: bool = False) -> str:
    """
    Convert various GitHub URL formats to a cloneable Git URL.
    
    Examples:
    - https://github.com/user/repo
    - github.com/user/repo
    - git@github.com:user/repo.git
    - https://github.com/user/repo.git
    """
    # Remove trailing slashes and .git if present
    url = url.rstrip('/').rstrip('.git')
    
    # Extract owner and repo name using regex
    patterns = [
        r'github\.com[:/]([^/]+)/([^/]+)',  # Matches most formats
        r'^([^/]+)/([^/]+)$',  # Matches "owner/repo" format
    ]
    
    match = None
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            owner, repo = match.groups()
            break
    
    if not match:
        raise ValueError(f"Could not parse GitHub URL: {url}")
    
    # Return appropriate format
    if use_ssh:
        return f"git@github.com:{owner}/{repo}.git"
    else:
        return f"https://github.com/{owner}/{repo}.git"


def verify_remote_repo(repo_url: str) -> bool:
    """
    Verify that a remote repository exists and is accessible.
    """
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
    """
    Check if a specific reference (branch, tag, or commit) exists in the repo.
    """
    try:
        # Check branches and tags
        result = subprocess.run(
            ['git', 'ls-remote', repo_url, reference],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0 and result.stdout.strip():
            return True
        
        # For commit SHAs, we can't verify without cloning
        # but we can check if it looks like a valid SHA
        if re.match(r'^[0-9a-f]{7,40}$', reference):
            return True  # Assume valid, will fail at clone if not
        
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

@activity.defn(name='resolve_cloneable')
async def resolve_cloneable_repo(
    repo_url: str, 
    reference: Optional[str] = None,
    use_ssh: bool = False
) -> Tuple[str, bool, Optional[str]]:
    """
    Resolve a GitHub repository URL and reference to ensure it's cloneable.
    
    Returns:
        Tuple of (normalized_url, is_valid, error_message)
    """
    try:
        # Normalize the URL
        normalized_url = normalize_github_url(repo_url, use_ssh=use_ssh)
        
        # Verify repository exists
        if not verify_remote_repo(normalized_url):
            return normalized_url, False, "Repository does not exist or is not accessible"
        
        # Verify reference if provided
        if reference:
            if not verify_reference_exists(normalized_url, reference):
                return normalized_url, False, f"Reference '{reference}' not found in repository"
        
        return normalized_url, True, None
        
    except ValueError as e:
        return repo_url, False, str(e)
    except Exception as e:
        return repo_url, False, f"Unexpected error: {str(e)}"
    
if __name__ == "__main__":
    # Test with various URL formats
    import asyncio
    test_cases = [
        ("https://github.com/psf/requests", "main"),
        ("github.com/psf/requests", "v2.28.0"),
        ("psf/requests", "main"),
    ]
    
    for url, ref in test_cases:
        normalized_url, is_valid, error = asyncio.run(resolve_cloneable_repo(url, ref))
        
        if is_valid:
            print(f"✓ {url} -> {normalized_url} (ref: {ref})")
            # Now you can safely clone:
            # subprocess.run(['git', 'clone', '-b', ref, normalized_url, 'local_dir'])
        else:
            print(f"✗ {url} -> Error: {error}")
