# test_workflow.py
import asyncio
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.common import RetryPolicy
from activities.cloning import setup_python_env, setup_repo_environment, remove_temp_repo
from activities.analysis import summarize_repo_activity
from workflows.cloneRepo import CloneRepoWorkflow
from workflows.codeAnalysis import CodeAnalysisWorkflow
import os

async def main():
    # Connect to Temporal server
    client = await Client.connect("localhost:7233")
    
    # Option A: Run the workflow and wait for signal
    async with Worker(
        client,
        task_queue="code-dev-queue",
        workflows=[CloneRepoWorkflow, CodeAnalysisWorkflow],
        activities=[setup_repo_environment, setup_python_env, summarize_repo_activity, remove_temp_repo]
    ):
        # Start workflow to clone repo
        environment = await client.start_workflow(
            CloneRepoWorkflow.run,
            args=["https://github.com/fatiando/boule", "main"],
            id=f"code-dev-{asyncio.get_event_loop().time()}",
            task_queue="code-dev-queue",
        )
        
        print(f"Started workflow to clone repo: {environment.id}")

        environment = await environment.result()

        print(f"Finished workflow to clone repo")
        print(environment)
        
        # analysis = await client.start_workflow(
        #     CodeAnalysisWorkflow.run,
        #     args=[environment["repo_path"], "standard", None],
        #     id=f"code-analysis-{asyncio.get_event_loop().time()}",
        #     task_queue="code-dev-queue",
        #     retry_policy=RetryPolicy(maximum_attempts=2)
        # )

        # print(f"Started workflow to analyze code: {analysis.id}")

        # Keep worker running
        await asyncio.Event().wait()

asyncio.run(main())