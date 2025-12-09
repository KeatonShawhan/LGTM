"""Agent configuration settings"""
from mcpSetup.server import create_calculator_server


def get_code_analysis_agent_config():
    """Get configuration for calculator agent"""
    return {
        "model": "claude-haiku-4-5-20251001",
        "mcp_servers": {
        },
        "allowed_tools": [
            "Read",
        ],
        "system_prompt": """You are an expert software analyst.""",
        "max_turns": 10,
    }

__all__ = ['get_code_analysis_agent_config']