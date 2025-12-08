
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

@workflow.defn(name="CodeDevelopmentWorkflow")
class CodeDevelopmentWorkflow:
    def __init__(self):
        self._cleanup_approved = False
    
    @workflow.run
    async def run(self, repo_url: str, branch: str = "main"):
        from activities.cloning import setup_repo_with_compose, run_command_in_sandbox, cleanup_sandbox
        from datetime import timedelta
        
        # Setup environment
        environment = await workflow.execute_activity(
            setup_repo_with_compose,
            args=[repo_url, branch],
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=timedelta(minutes=2)
        )
        
        try:
            # Run some command to verify it works
            test_result = await workflow.execute_activity(
                run_command_in_sandbox,
                args=[environment["container_id"], "ls -la /workspace"],
                start_to_close_timeout=timedelta(minutes=5)
            )
            
            workflow.logger.info(f"Container ready. ID: {environment['container_id']}")
            workflow.logger.info(f"Repo path: {environment['repo_path']}")
            
            # Wait for signal to cleanup
            workflow.logger.info("Waiting for cleanup approval signal...")
            await workflow.wait_condition(lambda: self._cleanup_approved)
            
            return {"status": "success", "environment": environment}
            
        finally:
            # Cleanup only after signal received
            await workflow.execute_activity(
                cleanup_sandbox,
                args=[environment],
                start_to_close_timeout=timedelta(minutes=5)
            )
    
    @workflow.signal
    async def approve_cleanup(self):
        """Call this signal when you're done examining the repo"""
        self._cleanup_approved = True
