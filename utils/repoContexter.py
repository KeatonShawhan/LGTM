import os
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Optional
import re


def generate_repo_context(repo_path: str, max_file_size: int = 100000) -> str:
    """
    Generate a high-level tree of a GitHub codebase optimized for LLM context.
    
    Args:
        repo_path: path to the repo
        max_file_size: Maximum file size in bytes to include content (default 100KB)
    
    Returns:
        Formatted string representation of the repository structure
    """

    # Add file summaries
    context = "## File Summaries\n"
    context += generate_file_summaries(repo_path, max_file_size) + "\n\n"
    
    # Add key code elements
    context += "## Key Code Elements\n"
    context += extract_key_elements(repo_path) + "\n"
    
    return context

def generate_file_summaries(root_path: str, max_file_size: int) -> str:
    """Generate summaries of key files in the repository."""
    
    priority_files = {
        'README.md', 'README.rst', 'README.txt',
        'package.json', 'requirements.txt', 'Cargo.toml',
        'setup.py', 'pyproject.toml', 'go.mod',
        'Makefile', 'Dockerfile', '.gitignore'
    }
    
    code_extensions = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.go',
        '.rs', '.cpp', '.c', '.h', '.hpp', '.cs', '.rb',
        '.php', '.swift', '.kt', '.scala', '.sh'
    }
    
    summaries = []
    root = Path(root_path)
    
    # First, process priority files
    for priority_file in priority_files:
        file_path = root / priority_file
        if file_path.exists() and file_path.is_file():
            summaries.append(_summarize_file(file_path, max_file_size))
    
    # Then, process main code files (limit to avoid overwhelming context)
    code_files = []
    for file_path in root.rglob('*'):
        if (file_path.is_file() and 
            file_path.suffix in code_extensions and
            file_path.name not in priority_files and
            not any(part.startswith('.') for part in file_path.parts)):
            code_files.append(file_path)
    
    # Limit number of code files
    for file_path in code_files[:20]:
        summaries.append(_summarize_file(file_path, max_file_size))
    
    return "\n\n".join(summaries)


def _summarize_file(file_path: Path, max_size: int) -> str:
    """Create a summary of a single file."""
    
    try:
        file_size = file_path.stat().st_size
        if file_size > max_size:
            return f"### {file_path.name}\n**Path:** {file_path}\n**Size:** {file_size} bytes (too large to include)"
        
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Extract key information based on file type
        summary = f"### {file_path.name}\n**Path:** {file_path}\n"
        
        if file_path.suffix == '.py':
            summary += _extract_python_info(content)
        elif file_path.suffix in ['.js', '.ts', '.jsx', '.tsx']:
            summary += _extract_javascript_info(content)
        elif file_path.name in ['README.md', 'README.rst', 'README.txt']:
            summary += f"```\n{content[:1000]}\n```"
        else:
            # For other files, show first few lines
            lines = content.split('\n')[:10]
            summary += f"```\n{chr(10).join(lines)}\n```"
        
        return summary
    
    except Exception as e:
        return f"### {file_path.name}\n**Error reading file:** {str(e)}"


def _extract_python_info(content: str) -> str:
    """Extract key Python code elements."""
    
    info = []
    
    # Find imports
    imports = re.findall(r'^(?:from .+ )?import .+$', content, re.MULTILINE)
    if imports:
        info.append(f"**Imports:** {', '.join(imports[:5])}")
    
    # Find classes
    classes = re.findall(r'^class (\w+)', content, re.MULTILINE)
    if classes:
        info.append(f"**Classes:** {', '.join(classes)}")
    
    # Find functions
    functions = re.findall(r'^def (\w+)', content, re.MULTILINE)
    if functions:
        info.append(f"**Functions:** {', '.join(functions[:10])}")
    
    return '\n'.join(info) if info else "Python source file"


def _extract_javascript_info(content: str) -> str:
    """Extract key JavaScript/TypeScript code elements."""
    
    info = []
    
    # Find imports
    imports = re.findall(r'^import .+$', content, re.MULTILINE)
    if imports:
        info.append(f"**Imports:** {len(imports)} import statements")
    
    # Find exports
    exports = re.findall(r'^export (?:default |const |function |class )?(\w+)', content, re.MULTILINE)
    if exports:
        info.append(f"**Exports:** {', '.join(exports[:10])}")
    
    # Find functions/components
    functions = re.findall(r'(?:function|const) (\w+)', content)
    if functions:
        info.append(f"**Functions/Components:** {', '.join(set(functions[:10]))}")
    
    return '\n'.join(info) if info else "JavaScript/TypeScript source file"


def extract_key_elements(root_path: str) -> str:
    """Extract key architectural elements from the codebase."""
    
    elements = []
    root = Path(root_path)
    
    # Check for common project markers
    if (root / 'package.json').exists():
        elements.append("- **Type:** Node.js/JavaScript project")
    
    if (root / 'requirements.txt').exists() or (root / 'pyproject.toml').exists():
        elements.append("- **Type:** Python project")
    
    if (root / 'Cargo.toml').exists():
        elements.append("- **Type:** Rust project")
    
    if (root / 'go.mod').exists():
        elements.append("- **Type:** Go project")
    
    # Check for common frameworks
    if (root / 'package.json').exists():
        try:
            with open(root / 'package.json', 'r') as f:
                content = f.read()
                if 'react' in content.lower():
                    elements.append("- **Framework:** React detected")
                if 'vue' in content.lower():
                    elements.append("- **Framework:** Vue detected")
                if 'express' in content.lower():
                    elements.append("- **Framework:** Express detected")
        except:
            pass
    
    return '\n'.join(elements) if elements else "No specific framework markers detected"


# Example usage
if __name__ == "__main__":
    repo_url = "https://github.com/example/repo"
    context = generate_repo_context(repo_url)
    print(context)
    
    # Optionally save to file
    # with open("repo_context.txt", "w") as f:
    #     f.write(context)