from temporalio import workflow
from temporalio.common import RetryPolicy
from datetime import timedelta
from activities.resolveCloneable import resolve_cloneable_repo
from activities.cloneRepo import clone_repo
from activities.matchCommit import make_local_files_match_commit

@workflow.defn(name="ingestRepositoryWorkflow")
class IngestRepositoryWorkflow:
    def __init__(self):
        self.complete = False

    @workflow.run
    async def run(self, repo_url: str, reference: str):

        normalized_url, repo_id, error = await workflow.execute_activity(
            resolve_cloneable_repo,
            args = [repo_url, reference],
            start_to_close_timeout=timedelta(minutes=1),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1)
        )

        if error or not repo_id:
            raise ValueError(error, repo_id)
        
        clone_path, commit_sha = await workflow.execute_activity(
            clone_repo,
            args = [normalized_url, reference, repo_id],
            start_to_close_timeout=timedelta(minutes=1),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1)
        )
        
        if not clone_path or not commit_sha:
            raise ValueError("failed to clone repo")

        match_result = await workflow.execute_activity(
            make_local_files_match_commit,
            args = [repo_id, clone_path, commit_sha],
            start_to_close_timeout=timedelta(minutes=1),
            heartbeat_timeout=timedelta(minutes=2),
         )
        
        if not match_result:
          raise ValueError("failed to match local files to commit")

        return {
            "repo_id": match_result["repo_id"],
            "repo_path": match_result["repo_path"],
            "commit_sha": match_result["commit_sha"],
        }

        