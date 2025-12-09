import os
import re
from temporalio import activity
import json
from agents.codeAnalysis import CodeAnalysisAgent


@activity.defn
async def summarize_repo_activity(repo_path: str) -> dict:
    summary = {"repo_path": repo_path}
    # Pass summary to agent
    async with CodeAnalysisAgent(
        directories=[repo_path] 
    ) as agent:
        task = f"""
        You are provided with a code repository located at: {repo_path}

        Your task is to return me 5 file names.
        """

        llm_response = await agent.execute_task(task)

    return {
        "llm_summary": llm_response
    }
