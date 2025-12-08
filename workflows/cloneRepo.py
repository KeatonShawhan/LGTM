
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

@workflow.defn(name="CodeDevelopmentWorkflow")
class CodeDevelopmentWorkflow:
    def __init__(self):
        self.complete = False
    @workflow.run
    async def run(self, repo_url: str, branch: str = "main"):
        from activities.cloning import setup_repo_with_compose, setup_repo_environment, read_file_from_repo
        from datetime import timedelta
        
        # Setup environment
        environment = await workflow.execute_activity(
            setup_repo_environment,
            args=[repo_url, branch],
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=timedelta(minutes=2)
        )
        
        # Step 4: PROOF - Read a specific file (e.g., README)
        workflow.logger.info("Reading README.md...")
        readme = await workflow.execute_activity(
            read_file_from_repo,
            args=[environment, "README.md"],
            start_to_close_timeout=timedelta(minutes=2)
        )
        
        if readme['success']:
            workflow.logger.info(f"✅ Successfully read README.md")
            workflow.logger.info(f"   Size: {readme['file_size']} bytes")
            workflow.logger.info(f"   Lines: {readme['line_count']}")
            workflow.logger.info(f"   Preview: {readme['contents'][:100]}...")
        else:
            workflow.logger.warning(f"⚠️ Could not read README: {readme['error']}")
            
