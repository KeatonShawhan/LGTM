from temporalio import workflow
from activities.gitDiff import get_diff_from_main
from datetime import timedelta
from temporalio.common import RetryPolicy

@workflow.defn(name="computeChangeSetWorkflow")
class ComputeChangeSetWorkflow:
    @workflow.run
    async def run(self, repo_path: str, target_branch: str = "main"):
        
        changeSet = await workflow.execute_activity(
            get_diff_from_main,
            args = [repo_path, target_branch],
            start_to_close_timeout=timedelta(minutes=1),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1)
        )

        if not changeSet:
            raise ValueError("Failed to generate changeset.")

        return changeSet