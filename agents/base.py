"""Base agent factory"""
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

class AgentFactory:
    """Factory for creating configured agents"""
    
    @staticmethod
    def create_calculator_agent(config: dict):
        """Create calculator agent with given configuration"""
        options = ClaudeAgentOptions(
            model=config["model"],
            mcp_servers=config["mcp_servers"],
            allowed_tools=config["allowed_tools"]
        )
        
        return ClaudeSDKClient(options=options)

__all__ = ['AgentFactory']