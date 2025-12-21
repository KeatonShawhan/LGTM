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
        
        raise ValueError()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise e


def resolve_reference_to_commit_sha(repo_url: str, reference: str) -> str:
    """
    Resolve a reference (branch, tag, or commit SHA) to a full commit SHA.
    
    Args:
        repo_url: Repository URL
        reference: Branch name, tag, or commit SHA
        
    Returns:
        Full commit SHA (40 characters)
    """
    # If it's already a full commit SHA (40 chars), return it as-is
    if re.match(r'^[0-9a-f]{40}$', reference):
        return reference
    
    # If it's a short commit SHA (7-39 chars), we can't resolve it without cloning
    # For now, return it as-is - the clone will resolve it properly
    # Note: This means cache won't work for short SHAs until after first clone
    if re.match(r'^[0-9a-f]{7,39}$', reference):
        # Try to use ls-remote to see if we can find matching refs
        # This is a best-effort attempt
        try:
            result = subprocess.run(
                ['git', 'ls-remote', '--heads', '--tags', repo_url],
                capture_output=True,
                text=True,
                timeout=30,
                check=True
            )
            # Look for any SHA that starts with our reference
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    sha = line.split('\t')[0].strip()
                    if sha.startswith(reference) and re.match(r'^[0-9a-f]{40}$', sha):
                        return sha
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
        
        # If we can't resolve it, return as-is (will be resolved during clone)
        return reference
    
    # For branches and tags, use ls-remote to get the commit SHA
    try:
        result = subprocess.run(
            ['git', 'ls-remote', repo_url, reference],
            capture_output=True,
            text=True,
            timeout=30,
            check=True
        )
        
        if not result.stdout.strip():
            raise ValueError(f"Reference '{reference}' not found in repository")
        
        # Parse the commit SHA from ls-remote output
        # Format: <sha>\t<ref>
        lines = result.stdout.strip().split('\n')
        # Get the first line's SHA (for branches/tags, first line is usually what we want)
        sha = lines[0].split('\t')[0].strip()
        
        if not re.match(r'^[0-9a-f]{40}$', sha):
            raise ValueError(f"Invalid commit SHA format returned: {sha}")
        
        return sha
    except subprocess.CalledProcessError as e:
        raise ValueError(f"Failed to resolve reference '{reference}': {e.stderr}")
    except subprocess.TimeoutExpired:
        raise ValueError(f"Timeout while resolving reference '{reference}'")

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
    """
    Resolve a GitHub repository URL and reference to ensure it's cloneable.
    Also resolves the reference to a commit SHA.
    
    Args:
        repo_url: Repository URL to resolve
        reference: Optional branch, tag, or commit SHA
        use_ssh: Whether to use SSH URL format
    
    Returns:
        Tuple of (normalized_url, repo_id, commit_sha)
        - normalized_url: Normalized GitHub URL
        - repo_id: Unique repository identifier (hash)
        - commit_sha: Resolved commit SHA (None if no reference provided)
    
    Raises:
        ValueError: If repository is not accessible, reference not found, or other validation errors
    """
    normalized_url = normalize_github_url(repo_url, use_ssh=use_ssh)
    
    if not verify_remote_repo(normalized_url):
        raise ValueError("Repository does not exist or is not accessible")
    
    commit_sha = None
    if reference:
        if not verify_reference_exists(normalized_url, reference):
            raise ValueError(f"Reference '{reference}' not found")
        
        # Resolve reference to commit SHA
        commit_sha = resolve_reference_to_commit_sha(normalized_url, reference)
    
    repo_id = generate_repo_id(repo_url)
    return normalized_url, repo_id, commit_sha

