"""Workflow that orchestrates the agentic code review activity"""
from temporalio import workflow
from temporalio.common import RetryPolicy
from datetime import timedelta
from utils.dataclasses import CodeContext, ChangeSet, ReviewResult
from activities.agenticReview import agentic_review


@workflow.defn(name="codeReviewWorkflow")
class CodeReviewWorkflow:
    """
    Workflow that runs AI-powered agentic code review.
    Orchestrates the agentic_review activity with appropriate timeouts and retries.
    """

    @workflow.run
    async def run(self, code_context: CodeContext, change_set: ChangeSet, repo_path: str) -> ReviewResult:
        """
        Run agentic code review on the provided context.

        Args:
            code_context: CodeContext with file summaries and risk scores
            change_set: ChangeSet with diff hunks for all changed files
            repo_path: Absolute path to the repository root

        Returns:
            ReviewResult with validated findings
        """
        file_count = len(code_context.files) if hasattr(code_context, 'files') else 'N/A'
        workflow.logger.info(f"Starting agentic code review workflow for {file_count} files")

        review_result = await workflow.execute_activity(
            agentic_review,
            args=[code_context, change_set, repo_path],
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=RetryPolicy(maximum_attempts=2),
            heartbeat_timeout=timedelta(minutes=2),
        )

        # Log summary
        if hasattr(review_result, 'findings'):
            workflow.logger.info(f"Agentic review complete: {len(review_result.findings)} findings")
            validated_count = sum(1 for f in review_result.findings if f.validated)
            workflow.logger.info(f"Validated findings: {validated_count}/{len(review_result.findings)}")
            if hasattr(review_result, 'iterations') and review_result.iterations:
                workflow.logger.info(f"Iterations: {review_result.iterations}")
            if hasattr(review_result, 'files_analyzed') and review_result.files_analyzed:
                workflow.logger.info(f"Files analyzed: {review_result.files_analyzed}")
        else:
            findings = review_result.get('findings', [])
            workflow.logger.info(f"Agentic review complete: {len(findings)} findings")

        return review_result
