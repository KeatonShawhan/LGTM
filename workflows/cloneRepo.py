
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from activities.cloning import setup_repo_environment, setup_python_env
from datetime import timedelta

@workflow.defn(name="CloneRepoWorkflow")
class CloneRepoWorkflow:
    def __init__(self):
        self.complete = False
    @workflow.run
    async def run(self, repo_url: str, branch: str = "main"):
        
        # Setup environment
        environment = await workflow.execute_activity(
            setup_repo_environment,
            args=[repo_url, branch],
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=timedelta(minutes=2)
        )
        
        if (environment is None) or ("repo_path" not in environment):
            workflow.logger.error("❌ Failed to set up repo environment")
            return

        environment = await workflow.execute_activity(
            setup_python_env,
            args=[environment["repo_path"]],
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=timedelta(minutes=2)
        )
        
        if environment:
            self.complete = True
        return environment
            
