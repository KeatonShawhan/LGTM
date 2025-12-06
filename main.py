import anthropic
import os
from pathlib import Path

# Add Rich imports
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None

class CodeReviewAgent:
    def __init__(self, api_key=None):
        """Initialize the code review agent with Anthropic API key"""
        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = "claude-sonnet-4-20250514"
    
    def _print(self, message, style=None):
        """Print with Rich formatting if available"""
        if RICH_AVAILABLE and console:
            if style == "header":
                console.print(Panel(message, style="bold cyan"))
            elif style == "success":
                console.print(f"✅ [bold green]{message}[/bold green]")
            elif style == "error":
                console.print(f"❌ [bold red]{message}[/bold red]")
            elif style == "info":
                console.print(f"ℹ️  [cyan]{message}[/cyan]")
            else:
                console.print(message)
        else:
            print(message)
    
    def review_code(self, code: str, filename: str = "code.py", context: str = "") -> dict:
        """
        Review a piece of code and return findings
        
        Args:
            code: The code to review
            filename: Name of the file (helps Claude understand language/context)
            context: Optional context about what the code should do
            
        Returns:
            dict with 'summary', 'issues', and 'suggestions'
        """
        
        prompt = f"""Review this code file: {filename}

{f"Context: {context}" if context else ""}

Code:
```
{code}
```

Please provide a thorough code review covering:
1. Bugs or logical errors
2. Security vulnerabilities
3. Performance issues
4. Code style and best practices
5. Potential edge cases

Format your response as:

## Summary
[Brief overall assessment]

## Issues Found
[List each issue with severity: CRITICAL, HIGH, MEDIUM, LOW]

## Suggestions
[Specific improvements with code examples where helpful]"""

        try:
            self._print(f"🔍 Reviewing {filename}...", "info")
            
            message = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            response_text = message.content[0].text
            
            return {
                "success": True,
                "review": response_text,
                "usage": {
                    "input_tokens": message.usage.input_tokens,
                    "output_tokens": message.usage.output_tokens
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def review_file(self, filepath: str, context: str = "") -> dict:
        """Review a code file from disk"""
        try:
            path = Path(filepath)
            code = path.read_text()
            return self.review_code(code, path.name, context)
        except Exception as e:
            return {
                "success": False,
                "error": f"Error reading file: {str(e)}"
            }
    
    def review_multiple_files(self, filepaths: list, context: str = "") -> dict:
        """Review multiple files and return combined results"""
        results = {}
        
        if RICH_AVAILABLE and console:
            # Show progress bar when reviewing multiple files
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("[cyan]Reviewing files...", total=len(filepaths))
                
                for filepath in filepaths:
                    progress.update(task, description=f"[cyan]Reviewing {filepath}...")
                    results[filepath] = self.review_file(filepath, context)
                    progress.advance(task)
        else:
            for filepath in filepaths:
                print(f"Reviewing {filepath}...")
                results[filepath] = self.review_file(filepath, context)
        
        return results


# Example usage
if __name__ == "__main__":
    if not RICH_AVAILABLE:
        print("💡 Tip: Install 'rich' for better formatting: pip install rich\n")
    
    # Initialize agent (make sure ANTHROPIC_API_KEY is in your environment)
    agent = CodeReviewAgent()
    
    # Example: Review some sample buggy code
    sample_code = """
class Solution:
    def searchMatrix(self, matrix: List[List[int]], target: int) -> bool:
        l_row, r_row = 0, len(matrix) - 1
        while l_row <= r_row:
            mid_row = (l_row + r_row) // 2
            if matrix[mid_row][0] <= target and matrix[mid_row][len(matrix[0]) - 1]:
                #correct row found, now binary search through columns
                l_col, r_col = 0, len(matrix[0]) - 1
                while l_col <= r_col:
                    mid_col = (l_col + r_col) // 2
                    if matrix[mid_row][mid_col] == target:
                        return True
                    elif target < matrix[mid_row][mid_col]:
                        r_col = mid_col - 1
                    else:
                        l_col = mid_col + 1
                return False
            elif target < matrix[mid_row][0]:
                r_row = mid_row - 1
            else:
                l_row = mid_row + 1
        return False
"""
    
    if RICH_AVAILABLE and console:
        console.print(Panel.fit(
            "CODE REVIEW AGENT - Example Run",
            style="bold magenta"
        ))
    else:
        print("=" * 60)
        print("CODE REVIEW AGENT - Example Run")
        print("=" * 60)
    
    result = agent.review_code(
        code=sample_code,
        filename="sample.py",
        context="This is part of a web application that handles user data"
    )
    
    if result["success"]:
        # Print review with Rich markdown formatting
        if RICH_AVAILABLE and console:
            console.print("\n")
            console.print(Markdown(result["review"]))
            console.print("\n")
            console.rule("[bold green]Review Complete")
            console.print(f"[cyan]📊 Tokens used: {result['usage']['input_tokens']} in, {result['usage']['output_tokens']} out[/cyan]")
        else:
            print("\n" + result["review"])
            print("\n" + "=" * 60)
            print(f"Tokens used: {result['usage']['input_tokens']} in, {result['usage']['output_tokens']} out")
    else:
        agent._print(f"Error: {result['error']}", "error")
    
    # Example: Review a file from disk (uncomment to use)
    # result = agent.review_file("path/to/your/file.py")
    
    # Example: Review multiple files (uncomment to use)
    # results = agent.review_multiple_files([
    #     "src/app.py",
    #     "src/utils.py",
    #     "src/models.py"
    # ], context="This is a Flask web application")