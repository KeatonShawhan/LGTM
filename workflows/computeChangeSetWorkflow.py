from temporalio import workflow


@workflow.defn(name="computeChangeSetWorkflow")
class ComputeChanegSetWorkflow:
    def __init__(self):
        self.complete = False
    
    @workflow.run
    async def run(self, repo_path: str, commit_sha: str):

        self.complete = True
        return ""