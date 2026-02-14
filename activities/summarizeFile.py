"""
Activity for summarizing files using an agent.
Caches summaries to reduce token usage on repeated files.
"""
from temporalio import activity
from pathlib import Path
from typing import Optional
from cache.file_summary_cache import get_file_summary_cache
from utils.dataclasses import FileSummary
import json
import re


def _parse_summary_response(response_text: str) -> FileSummary:
    """
    Parse the agent's response into a structured FileSummary.
    Uses simple regex extraction with validation.
    """
    def extract_field(label: str) -> str:
        """Extract a field by matching label prefix."""
        pattern = rf'^{label}:\s*(.+?)(?=\n(?:Purpose|Behavior|Key Functions|Dependencies):|$)'
        match = re.search(pattern, response_text, re.DOTALL | re.MULTILINE | re.IGNORECASE)
        return match.group(1).strip() if match else ""

    purpose = extract_field("Purpose")
    behavior = extract_field("Behavior")
    key_functions_raw = extract_field("Key Functions")
    dependencies_raw = extract_field("Dependencies")

    # Parse lists with validation
    key_functions = [f.strip() for f in key_functions_raw.split(',') if f.strip()][:5]
    dependencies = [d.strip() for d in dependencies_raw.split(',') if d.strip()]

    # Validate: at least purpose should be populated
    if not purpose:
        purpose = "Summary parsing failed - check raw response"

    return FileSummary(
        purpose=purpose[:200],      # Truncate overly long fields
        behavior=behavior[:200],
        key_functions=key_functions,
        dependencies=dependencies
    )


@activity.defn(name="summarize_file")
async def summarize_file(
    repo_id: str,
    commit_sha: str,
    file_path: str,
    repo_path: str,
    summarizer_version: str = "v1",
    use_cache: bool = False
) -> FileSummary:
    """
    Summarize a file using an agent, with caching support.
    
    Args:
        repo_id: Repository identifier
        commit_sha: Commit SHA
        file_path: Path to the file relative to repo root
        repo_path: Absolute path to the repository root
        summarizer_version: Version of the summarizer (for cache versioning)
        use_cache: If True, use cached summaries when available
        
    Returns:
        FileSummary object with structured summary
    """
    activity.heartbeat(f"Summarizing file: {file_path}")
    
    # Check cache first if caching is enabled
    cache = get_file_summary_cache()
    if use_cache:
        cached_summary = cache.get(repo_id, commit_sha, file_path, summarizer_version)
        
        if cached_summary is not None:
            activity.heartbeat(f"Cache hit for {file_path}")
            # Convert dict back to FileSummary if needed (Temporal serialization)
            if isinstance(cached_summary, dict):
                # Remove 'notes' if present (for backward compatibility with old cached summaries)
                cached_summary = {k: v for k, v in cached_summary.items() if k != 'notes'}
                return FileSummary(**cached_summary)
            return cached_summary
    
    activity.heartbeat(f"Cache miss for {file_path}, generating summary...")
    
    # Read file content
    full_file_path = Path(repo_path) / file_path
    if not full_file_path.exists():
        activity.heartbeat(f"File not found: {full_file_path}")
        return FileSummary(
            purpose="File not found",
            behavior="Unable to analyze - file does not exist",
            key_functions=[],
            dependencies=[]
        )
    
    try:
        with open(full_file_path, 'r', encoding='utf-8') as f:
            file_content = f.read()
    except UnicodeDecodeError:
        activity.heartbeat(f"Unable to read file (binary or encoding issue): {file_path}")
        return FileSummary(
            purpose="Binary or unsupported file",
            behavior="Unable to analyze - file is binary or has unsupported encoding",
            key_functions=[],
            dependencies=[]
        )
    except Exception as e:
        activity.heartbeat(f"Error reading file {file_path}: {e}")
        return FileSummary(
            purpose="Error reading file",
            behavior=f"Unable to analyze - error: {str(e)}",
            key_functions=[],
            dependencies=[]
        )
    
    # Generate summary using Anthropic API
    try:
        # Truncate large files to focus on first N lines
        MAX_FILE_LINES = 500
        lines = file_content.split('\n')
        if len(lines) > MAX_FILE_LINES:
            file_content = '\n'.join(lines[:MAX_FILE_LINES])
            file_content += f"\n\n... [truncated - {len(lines) - MAX_FILE_LINES} more lines]"

        # Create prompt for summarization
        prompt = f"""Analyze this code file and provide a structured summary.

File path: {file_path}

Code:
```{Path(file_path).suffix.lstrip('.') or 'text'}
{file_content}
```
"""

        system_prompt = """You are a code analyst creating concise file summaries for PR review.

Output format (use EXACTLY these labels):
Purpose: [1-2 sentences max - what this file is for]
Behavior: [1-2 sentences max - what it does at runtime]
Key Functions: [comma-separated list of 3-5 most important function/class names]
Dependencies: [comma-separated list of key external imports only]

Rules:
- Be extremely concise - reviewers scan these quickly
- Purpose/Behavior: Focus on WHAT, not HOW
- Key Functions: Only list the most important ones, not every function
- Dependencies: Only external packages, not standard library or relative imports
- No markdown, no bullet points, no extra formatting"""

        # Import Anthropic inside the function to avoid workflow sandbox restrictions
        from anthropic import Anthropic
        from observability.tracing import traced_anthropic_call

        client = Anthropic()
        message, _span = traced_anthropic_call(
            client,
            span_name=f"summarize_file_{file_path}",
            metadata={
                "repo_id": repo_id,
                "commit_sha": commit_sha[:8],
                "file_path": file_path,
                "file_lines": len(lines),
                "cache_hit": False,
            },
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            temperature=0,
            messages=[
                {"role": "user", "content": prompt}
            ],
            system=system_prompt,
        )

        response_text = message.content[0].text
        
        # Parse response into FileSummary
        summary = _parse_summary_response(response_text)
        
        # Cache the result (convert to dict for serialization)
        summary_dict = {
            "purpose": summary.purpose,
            "behavior": summary.behavior,
            "key_functions": summary.key_functions,
            "dependencies": summary.dependencies
        }
        cache.set(repo_id, commit_sha, file_path, summarizer_version, summary_dict)
        
        activity.heartbeat(f"Successfully summarized {file_path}")
        return summary
        
    except Exception as e:
        activity.heartbeat(f"Error generating summary for {file_path}: {e}")
        # Return a basic summary indicating error
        return FileSummary(
            purpose="Error during summarization",
            behavior=f"Unable to generate summary - error: {str(e)}",
            key_functions=[],
            dependencies=[]
        )

