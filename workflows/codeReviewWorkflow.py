"""Workflow that orchestrates the code review activity"""
from temporalio import workflow
from temporalio.common import RetryPolicy
from datetime import timedelta
from utils.dataclasses import CodeContext, ReviewResult
from activities.reviewCode import review_code


@workflow.defn(name="codeReviewWorkflow")
class CodeReviewWorkflow:
    """
    Workflow that runs AI-powered code review on a CodeContext.
    Orchestrates the review_code activity with appropriate timeouts and retries.
    """

    @workflow.run
    async def run(self, code_context: CodeContext, repo_path: str) -> ReviewResult:
        """
        Run code review on the provided code context.

        Args:
            code_context: CodeContext with file summaries and risk scores
            repo_path: Absolute path to the repository root

        Returns:
            ReviewResult with validated findings
        """
        workflow.logger.info(f"Starting code review workflow for {len(code_context.files) if hasattr(code_context, 'files') else 'N/A'} files")

        review_result = await workflow.execute_activity(
            review_code,
            args=[code_context, repo_path],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
            heartbeat_timeout=timedelta(minutes=2)
        )

        # Log summary
        if hasattr(review_result, 'findings'):
            workflow.logger.info(f"Code review complete: {len(review_result.findings)} findings")
            validated_count = sum(1 for f in review_result.findings if f.validated)
            workflow.logger.info(f"Validated findings: {validated_count}/{len(review_result.findings)}")
        else:
            # Handle dict case (Temporal serialization)
            findings = review_result.get('findings', [])
            workflow.logger.info(f"Code review complete: {len(findings)} findings")

        return review_result
