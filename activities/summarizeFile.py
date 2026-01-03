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
    The agent should return a structured format, but we'll handle various formats.
    """
    # Try to extract structured information from the response
    # Look for common patterns like "Purpose:", "Behavior:", etc.
    
    purpose = ""
    behavior = ""
    key_functions = []
    dependencies = []
    notes = None
    
    # Try to find purpose
    purpose_match = re.search(r'(?:Purpose|purpose):\s*(.+?)(?:\n|$)', response_text, re.IGNORECASE | re.DOTALL)
    if purpose_match:
        purpose = purpose_match.group(1).strip()
    
    # Try to find behavior
    behavior_match = re.search(r'(?:Behavior|behavior|Functionality|functionality):\s*(.+?)(?:\n|$)', response_text, re.IGNORECASE | re.DOTALL)
    if behavior_match:
        behavior = behavior_match.group(1).strip()
    
    # Try to find key functions
    functions_match = re.search(r'(?:Key Functions|key functions|Functions|functions):\s*(.+?)(?:\n(?:Dependencies|Notes)|$)', response_text, re.IGNORECASE | re.DOTALL)
    if functions_match:
        functions_text = functions_match.group(1).strip()
        # Split by comma, newline, or bullet points
        key_functions = [f.strip() for f in re.split(r'[,•\-\n]', functions_text) if f.strip()]
    
    # Try to find dependencies
    deps_match = re.search(r'(?:Dependencies|dependencies|Imports|imports):\s*(.+?)(?:\n(?:Notes|$)|$)', response_text, re.IGNORECASE | re.DOTALL)
    if deps_match:
        deps_text = deps_match.group(1).strip()
        dependencies = [d.strip() for d in re.split(r'[,•\-\n]', deps_text) if d.strip()]
    
    # Try to find notes
    notes_match = re.search(r'(?:Notes|notes):\s*(.+?)$', response_text, re.IGNORECASE | re.DOTALL)
    if notes_match:
        notes = notes_match.group(1).strip()
    
    # If we couldn't parse structured format, use the whole response as purpose
    if not purpose and not behavior:
        # Try to extract first paragraph as purpose
        paragraphs = [p.strip() for p in response_text.split('\n\n') if p.strip()]
        if paragraphs:
            purpose = paragraphs[0]
        if len(paragraphs) > 1:
            behavior = paragraphs[1]
        if len(paragraphs) > 2:
            notes = '\n\n'.join(paragraphs[2:])
    
    return FileSummary(
        purpose=purpose or "Unable to determine purpose",
        behavior=behavior or "Unable to determine behavior",
        key_functions=key_functions,
        dependencies=dependencies,
        notes=notes
    )


@activity.defn(name="summarize_file")
async def summarize_file(
    repo_id: str,
    commit_sha: str,
    file_path: str,
    repo_path: str,
    summarizer_version: str = "v1"
) -> FileSummary:
    """
    Summarize a file using an agent, with caching support.
    
    Args:
        repo_id: Repository identifier
        commit_sha: Commit SHA
        file_path: Path to the file relative to repo root
        repo_path: Absolute path to the repository root
        summarizer_version: Version of the summarizer (for cache versioning)
        
    Returns:
        FileSummary object with structured summary
    """
    activity.heartbeat(f"Summarizing file: {file_path}")
    
    # Check cache first
    cache = get_file_summary_cache()
    cached_summary = cache.get(repo_id, commit_sha, file_path, summarizer_version)
    
    if cached_summary is not None:
        activity.heartbeat(f"Cache hit for {file_path}")
        # Convert dict back to FileSummary if needed (Temporal serialization)
        if isinstance(cached_summary, dict):
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
            dependencies=[],
            notes=f"File path: {file_path}"
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
            dependencies=[],
            notes=f"File path: {file_path}"
        )
    except Exception as e:
        activity.heartbeat(f"Error reading file {file_path}: {e}")
        return FileSummary(
            purpose="Error reading file",
            behavior=f"Unable to analyze - error: {str(e)}",
            key_functions=[],
            dependencies=[],
            notes=f"File path: {file_path}"
        )
    
    # Generate summary using Anthropic API
    try:
        # Create prompt for summarization
        prompt = f"""Please analyze the following code file and provide a structured summary.

File path: {file_path}

Code:
```{Path(file_path).suffix.lstrip('.') or 'text'}
{file_content}
```

Please provide a structured summary with the following sections:
1. Purpose: The high-level purpose of this file
2. Behavior: The main behavior and functionality
3. Key Functions: List the important functions, classes, or modules (comma-separated)
4. Dependencies: List key imports and dependencies (comma-separated)
5. Notes: Any additional important information

Format your response clearly with section headers."""
        
        system_prompt = """You are an expert code analyst specializing in file summarization.
Your task is to analyze code files and provide structured summaries that include:
1. Purpose: The high-level purpose of the file
2. Behavior: The main behavior and functionality
3. Key Functions: List of important functions, classes, or modules
4. Dependencies: Key imports and dependencies
5. Notes: Any additional important information

Provide clear, concise summaries that help understand the file's role in the codebase."""
        
        # Import Anthropic inside the function to avoid workflow sandbox restrictions
        from anthropic import Anthropic
        client = Anthropic()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            messages=[
                {"role": "user", "content": prompt}
            ],
            system=system_prompt
        )
        
        response_text = message.content[0].text
        
        # Parse response into FileSummary
        summary = _parse_summary_response(response_text)
        
        # Cache the result (convert to dict for serialization)
        summary_dict = {
            "purpose": summary.purpose,
            "behavior": summary.behavior,
            "key_functions": summary.key_functions,
            "dependencies": summary.dependencies,
            "notes": summary.notes
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
            dependencies=[],
            notes=f"File path: {file_path}"
        )

