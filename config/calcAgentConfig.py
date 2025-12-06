"""Agent configuration settings"""
from mcpSetup.server import create_calculator_server


def get_calculator_agent_config():
    """Get configuration for calculator agent"""
    return {
        "model": "claude-haiku-4-5-20251001",
        "mcp_servers": {
            "calc": create_calculator_server()
        },
        "allowed_tools": [
            "mcp__calc__add",
            "mcp__calc__multiply",
            "Read"
        ],
        "system_prompt": """You are a helpful calculator assistant.
        After performing calculations, explain your work clearly.""",
        "max_turns": 10,
    }

__all__ = ['get_calculator_agent_config']