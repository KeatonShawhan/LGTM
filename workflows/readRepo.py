
from temporalio import workflow
from activities.repoReading import compose_directory

from datetime import timedelta

@workflow.defn(name="TranslateRepo")
class ReadRepoWorkflow:
    def __init__(self):
        self.complete = False

    @workflow.run
    async def run(self, repo_path: str):
        # Setup environment
        from agents.query import QueryAgent
        self.queryAgent = QueryAgent()
        composed = await workflow.execute_activity(
            compose_directory,
            args=[repo_path, self.queryAgent],
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=timedelta(minutes=2)
        )
        

        self.complete = True
        return composed
            
