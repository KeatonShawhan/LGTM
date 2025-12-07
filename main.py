"""Main entry point for calculator agent"""
import asyncio
from agents.calculator import CalculatorAgent
from utils.repoManager import RepoManager

async def main():
    """Run calculator agent with sample task"""
    RepoManager.
    # Create and use calculator agent
    async with CalculatorAgent() as agent:
        # Example task: read file and perform calculation
        task = (
            "Multiply 6 and 7 and then return the result to me. Only return the number."
        )
        
        await agent.execute_task(task)


if __name__ == "__main__":
    # Run single task
    asyncio.run(main())
    
    # Or run interactive mode
    # asyncio.run(interactive_mode())