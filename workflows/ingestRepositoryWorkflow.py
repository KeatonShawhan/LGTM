from temporalio import workflow

@workflow.defn(name="ingestRepositoryWorkflow")
class IngestRepositoryWorkflow:
    def __init__(self):
        self.complete = False

    @workflow.run
    async def run(self, repo_url: str, reference: str):
        from activities.resolveCloneable import resolve_cloneable_repo
        from activities.cloneRepo import clone_repo

        normalized_url, is_valid, error = await workflow.execute_activity(
            resolve_cloneable_repo,
            args = [repo_url, reference],
        )
        if error or not is_valid:
            raise ValueError(error, is_valid)
        
        clone_path, commit_sha = await workflow.execute_activity(
            clone_repo,
            args=[normalized_url, reference, is_valid]
        )

        if not clone_path or commit_sha:
            raise ValueError("failed to clone repo")

        