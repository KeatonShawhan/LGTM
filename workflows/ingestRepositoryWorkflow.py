from temporalio import workflow
from temporalio.common import RetryPolicy
from datetime import timedelta
from activities.resolveCloneable import resolve_cloneable_repo
from activities.cloneRepo import clone_repo
from activities.matchCommit import make_local_files_match_commit
from activities.cacheRepo import check_repo_cache, store_repo_cache

@workflow.defn(name="ingestRepositoryWorkflow")
class IngestRepositoryWorkflow:
    def __init__(self):
        self.complete = False

    @workflow.run
    async def run(self, repo_url: str, reference: str):

        normalized_url, repo_id, commit_sha = await workflow.execute_activity(
            resolve_cloneable_repo,
            args = [repo_url, reference],
            start_to_close_timeout=timedelta(minutes=1),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1)
        )

        if not repo_id or not commit_sha:
            raise ValueError("Failed to resolve repository: missing repo_id or commit_sha")
        
        # Check cache using the resolved commit SHA
        cached_path = await workflow.execute_activity(
            check_repo_cache,
            args=[repo_id, commit_sha],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1)
        )
        
        if cached_path:
            # Cache hit - use cached repository
            print("Cache hit!")
            clone_path = cached_path
        else:
            print("Cache miss!")
            # Cache miss - clone the repository
            clone_path, actual_commit_sha = await workflow.execute_activity(
                clone_repo,
                args = [normalized_url, reference, repo_id, commit_sha],
                start_to_close_timeout=timedelta(minutes=1),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=1)
            )
            
            if not clone_path or not actual_commit_sha:
                raise ValueError("failed to clone repo")
            
            # Verify commit SHA matches (should match, but double-check)
            if actual_commit_sha != commit_sha:
                # Use the actual commit SHA from the clone
                commit_sha = actual_commit_sha
            
            # Store in cache after successful clone
            await workflow.execute_activity(
                store_repo_cache,
                args=[repo_id, commit_sha, clone_path],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1)
            )

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

        