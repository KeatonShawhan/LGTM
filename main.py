"""Main entry point for LGTM CLI"""
import asyncio
import argparse
import json
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.common import RetryPolicy
from workflows.review import ReviewWorkflow
from workflows.ingestRepositoryWorkflow import IngestRepositoryWorkflow
from workflows.computeChangeSetWorkflow import ComputeChangeSetWorkflow
from workflows.buildCodeContextWorkflow import BuildCodeContextWorkflow
from dotenv import load_dotenv
from activities.resolveCloneable import resolve_cloneable_repo
from activities.cloneRepo import clone_repo
from activities.matchCommit import make_local_files_match_commit
from activities.cacheRepo import check_repo_cache, store_repo_cache
from activities.gitDiff import get_diff_from_main
from activities.prioritizeFiles import prioritize_files
from activities.summarizeFile import summarize_file
import os

load_dotenv()


async def review_command(repo: str, ref: str, use_cache: bool = False):
    """Execute the review workflow for a given repository and reference"""
    # Connect to Temporal server
    client = await Client.connect("localhost:7233")
    # Register ALL workflows (parent + children) and activities in the worker
    # The parent workflow will orchestrate the child workflows internally
    async with Worker(
        client,
        task_queue="code-dev-queue",
        workflows=[
            ReviewWorkflow,  # Parent workflow (user-facing)
            IngestRepositoryWorkflow,
            ComputeChangeSetWorkflow,
            BuildCodeContextWorkflow,
        ],
        activities=[
          resolve_cloneable_repo,
          clone_repo,
          make_local_files_match_commit,
          check_repo_cache,
          store_repo_cache,
          get_diff_from_main,
          prioritize_files,
          summarize_file,
        ]
    ):
        # Start the parent workflow - it will orchestrate child workflows internally
        print(f"Starting review for repository: {repo} (ref: {ref})")
        review_handle = await client.start_workflow(
            ReviewWorkflow.run,
            args=[repo, ref, use_cache],
            id=f"review-{asyncio.get_event_loop().time()}",
            task_queue="code-dev-queue",
            retry_policy=RetryPolicy(maximum_attempts=2)
        )
        
        print(f"Started review workflow: {review_handle.id}")
        
        # Wait for the entire review process to complete
        result = await review_handle.result()

        print(f"{'='*60}")
        print(f"Review Complete!")
        print(f"{'='*60}")

        print(f"Result: {json.dumps(result, indent=2)}")



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
    review_parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Use cached file summaries when available"
    )
    
    args = parser.parse_args()

    if args.command == "review":
        asyncio.run(review_command(args.repo, args.ref, args.use_cache))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()