import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

"""MCP server for calculator tools"""
from claude_agent_sdk import create_sdk_mcp_server
from tools.mathTools import add, multiply

def create_calculator_server():
    """Create and return the calculator MCP server"""
    return create_sdk_mcp_server(
        name="calculator",
        version="2.0.0",
        tools=[add, multiply]
    )

__all__ = ['create_calculator_server']
