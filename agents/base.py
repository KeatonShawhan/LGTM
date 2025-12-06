"""Base agent factory"""
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
from typing import Dict, List, Optional

class AgentFactory:
    """Factory for creating configured agents"""
    
    @staticmethod
    def create_agent(
        model: str,
        mcp_servers: Optional[Dict] = None,
        allowed_tools: Optional[List[str]] = None,
        system_prompt: Optional[str] = None,
        max_turns: int = 25,
    ):
        """
        Create a generic agent with given configuration
        
        Args:
            model: Model name (e.g., "claude-sonnet-4-20250514")
            mcp_servers: Dict of MCP server name -> server instance
            allowed_tools: List of tool names the agent can use
            system_prompt: System prompt for the agent
            max_turns: Maximum number of agent turns/iterations (default: 25)
            temperature: Temperature for sampling
        """
        options = ClaudeAgentOptions(
            model=model,
            mcp_servers=mcp_servers or {},
            allowed_tools=allowed_tools or [],
            system_prompt=system_prompt,
            max_turns=max_turns
        )
        
        return ClaudeSDKClient(options=options)
    
    @staticmethod
    def create_from_config(config: dict):
        """Create agent from a configuration dictionary"""
        return AgentFactory.create_agent(**config)

__all__ = ['AgentFactory']