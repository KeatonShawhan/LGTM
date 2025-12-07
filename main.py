"""Main entry point for calculator agent"""
import asyncio
from agents.calculator import CalculatorAgent
from utils.repoManager import RepoManager
from dotenv import load_dotenv
import os

load_dotenv()


async def main():
    """Run calculator agent with sample task"""
    repoManager = RepoManager(
        cache_dir="./repo_cache"
    )

    # Move this to clone in the sandbox for the agent to use, rather than have it look locally
    repoManager.ensure_repo_updated(os.getenv("REPO_URL"), "main", os.getenv("GITHUB_TOKEN"))

    # Create and use calculator agent
    async with CalculatorAgent() as agent:
        # Example task: read file and perform calculation
        task = (
            "Read me the files and folders in the sandbox. Dont look at any files on my local machine."
        )
        
        await agent.execute_task(task)


if __name__ == "__main__":
    # Run single task
    asyncio.run(main())
    
    # Or run interactive mode
    # asyncio.run(interactive_mode())