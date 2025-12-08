# test_workflow.py
import asyncio
from temporalio.client import Client
from temporalio.worker import Worker
from activities.cloning import setup_repo_with_compose, run_command_in_sandbox, cleanup_sandbox
from workflows.cloneRepo import CodeDevelopmentWorkflow

async def main():
    # Connect to Temporal server
    client = await Client.connect("localhost:7233")
    
    # Option A: Run the workflow and wait for signal
    async with Worker(
        client,
        task_queue="code-dev-queue",
        workflows=[CodeDevelopmentWorkflow],
        activities=[setup_repo_with_compose, run_command_in_sandbox, cleanup_sandbox]
    ):
        # Start workflow
        handle = await client.start_workflow(
            CodeDevelopmentWorkflow.run,
            args=["https://github.com/KeatonShawhan/SharedSpoons", "main"],
            id=f"code-dev-{asyncio.get_event_loop().time()}",
            task_queue="code-dev-queue",
        )
        
        print(f"Started workflow: {handle.id}")
        print("Workflow is running... Check logs for container ID and repo path")
        print("\nWhen you're done examining:")
        print(f"  python send_cleanup_signal.py {handle.id}")
        
        # Keep worker running
        await asyncio.Event().wait()

asyncio.run(main())