import os
import re
from temporalio import activity
import json
from agents.codeAnalysis import CodeAnalysisAgent
from utils.repoContexter import generate_repo_context

@activity.defn
async def summarize_repo_activity(repo_path: str) -> dict:
    # Pass summary to agent
    summary = generate_repo_context(repo_path)


    # async with CodeAnalysisAgent() as agent:
    #     task = f"""
    #     You are provided with a code repository located at: {repo_path}

    #     Your task is to return me 5 file names.
    #     """

    #     llm_response = await agent.execute_task(task)

    return {
        "llm_summary": summary
    }
