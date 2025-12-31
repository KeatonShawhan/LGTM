"""Parent workflow that orchestrates the review process"""
from temporalio import workflow
from temporalio.common import RetryPolicy
from workflows.ingestRepositoryWorkflow import IngestRepositoryWorkflow
from workflows.computeChangeSetWorkflow import ComputeChangeSetWorkflow
from workflows.buildCodeContextWorkflow import BuildCodeContextWorkflow
from utils.dataclasses import RepoHandle
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
        repo_handle = await workflow.execute_child_workflow(
            IngestRepositoryWorkflow.run,
            args=[repo, ref],
            id=f"clone-{workflow.info().workflow_id}",
            task_queue="code-dev-queue",
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        
        if not repo_handle or not repo_handle.repo_path:
            workflow.logger.error("Failed to ingest repository")
            raise Exception("Failed to ingest repository")
        
        workflow.logger.info(f"Repository cloned to: {repo_handle.repo_path}")
        
        # Step 2: Compute the code change
        workflow.logger.info("Step 2: Computing git diff")
        change_set = await workflow.execute_child_workflow(
            ComputeChangeSetWorkflow.run,
            args=[repo_handle.repo_path],
            id=f"changeset-{workflow.info().workflow_id}",
            task_queue="code-dev-queue",
            retry_policy=RetryPolicy(maximum_attempts=2)
        )
        
        if not change_set:
            workflow.logger.error("Failed to compute changeset")
            raise Exception("Failed to compute changeset")
        
        # Workflow outputs are serialized to dicts by Temporal
        workflow.logger.info(f"Computed changeset with {len(change_set['files'])} changed files")
        
        # Step 3: Build the code context (Librarian)
        workflow.logger.info("Step 3: Building code context...")
        
        code_context = await workflow.execute_child_workflow(
            BuildCodeContextWorkflow.run,
            args=[repo_handle, change_set],
            id=f"build-context-{workflow.info().workflow_id}",
            task_queue="code-dev-queue",
            retry_policy=RetryPolicy(maximum_attempts=2)
        )
        
        if not code_context:
            workflow.logger.error("Failed to build code context")
            raise Exception("Failed to build code context")
        
        workflow.logger.info("Code context built successfully")

        # Step 4: Generate the review


        workflow.logger.info("Review workflow completed successfully")
        
        return code_context

