"""Main entry point for LGTM CLI"""
import asyncio
import argparse
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.common import RetryPolicy
from activities.cloning import setup_python_env, setup_repo_environment, remove_temp_repo
from activities.analysis import summarize_repo_activity
from workflows.cloneRepo import CloneRepoWorkflow
from workflows.codeAnalysis import CodeAnalysisWorkflow
from dotenv import load_dotenv
import os

load_dotenv()


async def review_command(repo: str, ref: str):
    """Execute the review workflow for a given repository and reference"""
    # Connect to Temporal server
    client = await Client.connect("localhost:7233")
    
    # Run worker and workflows
    async with Worker(
        client,
        task_queue="code-dev-queue",
        workflows=[CloneRepoWorkflow, CodeAnalysisWorkflow],
        activities=[setup_repo_environment, setup_python_env, summarize_repo_activity, remove_temp_repo]
    ):
        # Start workflow to clone repo
        print(f"Cloning repository: {repo} (ref: {ref})")
        clone_handle = await client.start_workflow(
            CloneRepoWorkflow.run,
            args=[repo, ref],
            id=f"code-dev-{asyncio.get_event_loop().time()}",
            task_queue="code-dev-queue",
        )
        
        print(f"Started workflow to clone repo: {clone_handle.id}")
        
        # Wait for clone to complete
        environment = await clone_handle.result()
        
        if not environment or "repo_path" not in environment:
            print("Failed to clone repository")
            return
        
        print(f"Repository cloned successfully to: {environment['repo_path']}")
        
        # Start code analysis workflow
        print(f"🔍 Starting code analysis...")
        analysis_handle = await client.start_workflow(
            CodeAnalysisWorkflow.run,
            args=[environment["repo_path"], "standard", None],
            id=f"code-analysis-{asyncio.get_event_loop().time()}",
            task_queue="code-dev-queue",
            retry_policy=RetryPolicy(maximum_attempts=2)
        )
        
        print(f"Started workflow to analyze code: {analysis_handle.id}")
        
        # Wait for analysis to complete
        result = await analysis_handle.result()
        
        print(f"\nReview Complete!")
        print(f"{'='*60}")
        print(result)
        print(f"{'='*60}")


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        prog="lgtm",
        description="LGTM - Claude Agent SDK for SWE-QA and PR Reviews"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Review command
    review_parser = subparsers.add_parser("review", help="Review a repository")
    review_parser.add_argument(
        "--repo",
        required=True,
        help="Repository URL (e.g., https://github.com/user/repo)"
    )
    review_parser.add_argument(
        "--ref",
        required=True,
        help="Git reference (branch, tag, or commit SHA)"
    )
    
    args = parser.parse_args()

    if args.command == "review":
        asyncio.run(review_command(args.repo, args.ref))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()