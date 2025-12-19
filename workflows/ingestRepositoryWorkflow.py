from temporalio import workflow

@workflow.defn(name="ingestRepositoryWorkflow")
class IngestRepositoryWorkflow:
    def __init__(self):
        self.complete = False

    @workflow.run
    async def run(self, repo_url: str, reference: str):
        from activities.resolveCloneable import resolve_cloneable_repo

        normalized_url, is_valid, error = await resolve_cloneable_repo(
            repo_url=repo_url,
            reference=reference,
        )
        if error or not is_valid:
            raise ValueError(error, is_valid)
        