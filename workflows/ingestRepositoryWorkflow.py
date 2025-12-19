from temporalio import workflow

@workflow.defn(name="ingestRepositoryWorkflow")
class IngestRepositoryWorkflow:
    def __init__(self):
        self.complete = False

    @workflow.run
    async def run(self, TODO_PARAMS):
        pass
        