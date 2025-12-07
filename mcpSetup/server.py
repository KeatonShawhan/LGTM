"""MCP server for calculator tools"""
from claude_agent_sdk import create_sdk_mcp_server
from tools.mathTools import add, multiply
from tools.gitTools import (
    get_diff,
    get_diff_stats,
    git_blame,
    git_log_file,
    get_changed_files,
    get_file_at_commit,
    search_commits
)

def create_calculator_server():
    """Create and return the calculator MCP server"""
    return create_sdk_mcp_server(
        name="calculator",
        version="2.0.0",
        tools=[
            get_diff,
            get_diff_stats,
            git_blame,
            git_log_file,
            get_changed_files,
            get_file_at_commit,
            search_commits
        ]
    )

__all__ = ['create_calculator_server']
