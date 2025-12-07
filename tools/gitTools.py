"""Git operation tools for code review"""
import subprocess
from pathlib import Path
from claude_agent_sdk import tool

@tool("get_diff", "Get git diff for a file against base branch", {
    "file_path": str,
    "base_branch": str
})
async def get_diff(args):
    """Get git diff for a file. Shows what changed in this PR."""
    file_path = args["file_path"]
    base_branch = args.get("base_branch", "main")
    
    try:
        result = subprocess.run(
            ['git', 'diff', base_branch, '--', file_path],
            capture_output=True,
            text=True,
            cwd=Path(file_path).parent
        )
        return {
            "content": [{
                "type": "text",
                "text": result.stdout if result.stdout else "No changes found"
            }]
        }
    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Error getting diff: {e}"
            }]
        }

@tool("get_diff_stats", "Get summary of all changes (files, insertions, deletions)", {
    "base_branch": str
})
async def get_diff_stats(args):
    """Get summary stats of changes."""
    base_branch = args.get("base_branch", "main")
    
    try:
        result = subprocess.run(
            ['git', 'diff', '--stat', base_branch],
            capture_output=True,
            text=True
        )
        return {
            "content": [{
                "type": "text",
                "text": result.stdout
            }]
        }
    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Error getting diff stats: {e}"
            }]
        }

@tool("git_blame", "Show who last modified specific lines of code", {
    "file_path": str,
    "line_start": int,
    "line_end": int
})
async def git_blame(args):
    """Get git blame for specific lines. Shows who wrote code and when."""
    file_path = args["file_path"]
    line_start = args["line_start"]
    line_end = args["line_end"]
    
    try:
        result = subprocess.run(
            ['git', 'blame', '-L', f'{line_start},{line_end}', file_path],
            capture_output=True,
            text=True
        )
        return {
            "content": [{
                "type": "text",
                "text": result.stdout
            }]
        }
    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Error running git blame: {e}"
            }]
        }

@tool("git_log_file", "Get commit history for a specific file", {
    "file_path": str,
    "max_count": int
})
async def git_log_file(args):
    """Get commit history for a file. Shows file evolution."""
    file_path = args["file_path"]
    max_count = args.get("max_count", 10)
    
    try:
        result = subprocess.run(
            ['git', 'log', f'--max-count={max_count}', '--oneline', '--', file_path],
            capture_output=True,
            text=True
        )
        return {
            "content": [{
                "type": "text",
                "text": result.stdout if result.stdout else f"No history found for {file_path}"
            }]
        }
    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Error getting file log: {e}"
            }]
        }

@tool("get_changed_files", "List all files changed in this PR", {
    "base_branch": str
})
async def get_changed_files(args):
    """List all files changed compared to base branch."""
    base_branch = args.get("base_branch", "main")
    
    try:
        result = subprocess.run(
            ['git', 'diff', '--name-only', base_branch],
            capture_output=True,
            text=True
        )
        return {
            "content": [{
                "type": "text",
                "text": result.stdout.strip() if result.stdout else "No changed files"
            }]
        }
    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Error getting changed files: {e}"
            }]
        }

@tool("get_file_at_commit", "Get file contents from a previous commit", {
    "file_path": str,
    "commit": str
})
async def get_file_at_commit(args):
    """Get file contents from a previous commit. Useful for before/after comparison."""
    file_path = args["file_path"]
    commit = args.get("commit", "HEAD~1")
    
    try:
        result = subprocess.run(
            ['git', 'show', f'{commit}:{file_path}'],
            capture_output=True,
            text=True
        )
        return {
            "content": [{
                "type": "text",
                "text": result.stdout
            }]
        }
    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Error getting file at commit: {e}"
            }]
        }

@tool("search_commits", "Search commit messages for keywords", {
    "query": str,
    "max_count": int
})
async def search_commits(args):
    """Search commit messages. Useful for finding related past changes."""
    query = args["query"]
    max_count = args.get("max_count", 20)
    
    try:
        result = subprocess.run(
            ['git', 'log', f'--max-count={max_count}', '--oneline', f'--grep={query}'],
            capture_output=True,
            text=True
        )
        return {
            "content": [{
                "type": "text",
                "text": result.stdout if result.stdout else f"No commits found matching '{query}'"
            }]
        }
    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Error searching commits: {e}"
            }]
        }

__all__ = [
    'get_diff',
    'get_diff_stats',
    'git_blame',
    'git_log_file',
    'get_changed_files',
    'get_file_at_commit',
    'search_commits'
]