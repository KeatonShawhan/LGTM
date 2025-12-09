
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from activities.analysis import summarize_repo_activity
from datetime import timedelta

@workflow.defn(name="CodeAnalysisWorkflow")
class CodeAnalysisWorkflow:
    def __init__(self):
        self.complete = False
    @workflow.run
    async def run(self, repo_path: str, analysis_depth: str = "standard", filters: dict = None):

        # Summarize cloned repo
        summary = await workflow.execute_activity(
            summarize_repo_activity,
            args=[repo_path],
            start_to_close_timeout=timedelta(minutes=1),
            heartbeat_timeout=timedelta(minutes=2)
        )
        
        print(summary)

        return summary["llm_summary"]
            
