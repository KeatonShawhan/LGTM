"""Parent workflow that orchestrates the review process"""
from temporalio import workflow
from temporalio.common import RetryPolicy
from workflows.ingestRepositoryWorkflow import IngestRepositoryWorkflow
from workflows.computeChangeSetWorkflow import ComputeChangeSetWorkflow
from datetime import timedelta


@workflow.defn(name="ReviewWorkflow")
class ReviewWorkflow:
    """User-facing workflow that orchestrates internal workflows"""
    
    @workflow.run
    async def run(self, repo: str, ref: str):
        """
        Orchestrate the review process by calling internal workflows in succession
        
        Args:
            repo: Repository URL
            ref: Git reference (branch, tag, or commit SHA)
        """
        workflow.logger.info(f"Starting review workflow for {repo} (ref: {ref})")
        
        # Step 1: Ingest the repository
        workflow.logger.info("Step 1: Ingesting repository...")
        environment = await workflow.execute_child_workflow(
            IngestRepositoryWorkflow.run,
            args=[repo, ref],
            id=f"clone-{workflow.info().workflow_id}",
            task_queue="code-dev-queue",
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        
        if not environment or "repo_path" not in environment:
            workflow.logger.error("Failed to ingest repository")
            raise Exception("Failed to ingest repository")
        
        workflow.logger.info(f"Repository cloned to: {environment['repo_path']}")
        
        # Step 2: Compute the code change
        workflow.logger.info("Step 2: Computing git diff")
        diff = await workflow.execute_child_workflow(
            ComputeChangeSetWorkflow.run,
            args=[environment['repo_path']],
            id=f"clone-{workflow.info().workflow_id}",
            task_queue="code-dev-queue",
            retry_policy=RetryPolicy(maximum_attempts=2)
        )
        print(diff)
        # Step 3: Build the code context (Librarian)
        

        # Step 4: Generate the review


        workflow.logger.info("Review workflow completed successfully")
        
        return environment

