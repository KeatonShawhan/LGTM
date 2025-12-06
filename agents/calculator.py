import json

from claude_agent_sdk import ResultMessage
"""Calculator agent implementation"""
from agents.base import AgentFactory
from config.agentConfig import get_calculator_agent_config
#from utils.logging import log_message, log_separator

class CalculatorAgent:
    """Agent for performing calculations and reading data"""
    
    def __init__(self):
        self.config = get_calculator_agent_config()
        self.client = None
    
    async def __aenter__(self):
        """Async context manager entry"""
        self.client = AgentFactory.create_calculator_agent(self.config)
        await self.client.__aenter__()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.client:
            await self.client.__aexit__(exc_type, exc_val, exc_tb)
    
    async def execute_task(self, task: str, log_responses: bool = True):
        """
        Execute a calculation task
        
        Args:
            task: The task description
            log_responses: Whether to log responses to file
        """
        if not self.client:
            raise RuntimeError("Agent not initialized. Use 'async with' context manager.")
        
        print(f"Task: {task}\n")
        print("=" * 60)
        
        # Send query
        await self.client.query(task)
        
        # Collect and process responses
        results = []
        async for message in self.client.receive_response():
            print(type(message), '\n')
            if isinstance(message, dict):
                print(json.dumps(message, indent=2))
            elif isinstance(message, str):
                try:
                    # Try to parse and pretty print if it's JSON string
                    parsed = json.loads(message)
                    print(json.dumps(parsed, indent=2))
                except:
                    # Not JSON, just print normally
                    print(message)
            else:
                # For other objects, convert to dict if possible
                try:
                    print(json.dumps(message.__dict__, indent=2, default=str))
                except:
                    print(message)
            if type(message) is ResultMessage:
                print(message.result, message.total_cost_usd)

        print("\n" + "=" * 60)
        return results

__all__ = ['CalculatorAgent']