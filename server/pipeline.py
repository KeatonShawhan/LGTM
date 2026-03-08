"""
Pipeline adapter — bridges a GitHub PR webhook payload to the LGTM review pipeline.

Mirrors benchmarks/runner.py: calls the pipeline activities directly, no Temporal.

Flow:
  1. Clone repo with installation token
  2. Compute ChangeSet from git diff (base_sha..head_sha)
  3. Build CodeContext (risk scores, summaries)
  4. Run agentic review via run_review_core()
  5. Return ReviewResult for the GitHub client to post
"""
import asyncio
import shutil
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from activities.agenticReview import run_review_core
from activities.gitDiff import parse_diff_output
from activities.prioritizeFiles import compute_risk_score, should_ignore_file
from utils.dataclasses import (
    ChangeSet, CodeContext, ContextMetadata, ContextOverview,
    FileContext, FileTypeStats, ReviewResult, Totals,
)
from server.github_client import clone_repo_with_token


def _compute_changeset(base_sha: str, head_sha: str, repo_path: Path) -> ChangeSet:
    """Run git diff and parse into a ChangeSet."""
    result = subprocess.run(
        ["git", "diff", "-U3", base_sha, head_sha],
        cwd=repo_path, capture_output=True, text=True, check=True,
    )
    files = parse_diff_output(result.stdout)
    return ChangeSet(base_commit=base_sha, head_commit=head_sha, files=files)


def _build_code_context(change_set: ChangeSet) -> CodeContext:
    """Build CodeContext without Temporal — mirrors benchmarks/runner.py."""
    total_added = sum(f.added for f in change_set.files)
    total_removed = sum(f.removed for f in change_set.files)
    total_hunks = sum(len(f.hunks) for f in change_set.files)
    files_added = sum(1 for f in change_set.files if f.added > 0 and f.removed == 0)
    files_deleted = sum(1 for f in change_set.files if f.removed > 0 and f.added == 0)

    file_type_stats: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "lines_added": 0, "lines_removed": 0}
    )
    for file in change_set.files:
        ext = f".{file.path.rsplit('.', 1)[-1].lower()}" if "." in file.path else "no_extension"
        file_type_stats[ext]["count"] += 1
        file_type_stats[ext]["lines_added"] += file.added
        file_type_stats[ext]["lines_removed"] += file.removed

    file_breakdown = {
        ft: FileTypeStats(count=s["count"], lines_added=s["lines_added"], lines_removed=s["lines_removed"])
        for ft, s in file_type_stats.items()
    }

    flags = []
    if files_added:
        flags.append("has_new_files")
    if files_deleted:
        flags.append("has_deleted_files")
    if total_added > 1000 or total_removed > 1000:
        flags.append("large_change")

    overview = ContextOverview(
        totals=Totals(
            files_changed=len(change_set.files),
            files_added=files_added,
            files_deleted=files_deleted,
            lines_added=total_added,
            lines_removed=total_removed,
            total_hunks=total_hunks,
        ),
        file_breakdown=file_breakdown,
        flags=flags,
    )

    files_dict: dict[str, FileContext] = {}
    for file in change_set.files:
        if should_ignore_file(file.path):
            continue
        risk_score, reasons = compute_risk_score(file)
        files_dict[file.path] = FileContext(
            path=file.path,
            risk_score=risk_score,
            added=file.added,
            removed=file.removed,
            reasons=reasons,
            summary=None,
        )

    return CodeContext(
        repo_id=f"github",
        base_commit=change_set.base_commit,
        head_commit=change_set.head_commit,
        overview=overview,
        files=files_dict,
        metadata=ContextMetadata(),
    )


async def run_pr_review(
    owner: str,
    repo: str,
    head_sha: str,
    base_sha: str,
    clone_url: str,
    installation_token: str,
    model: str,
) -> ReviewResult:
    """
    Clone the PR's head, run the LGTM pipeline, return ReviewResult.

    Runs in a thread executor so blocking git/subprocess calls don't stall the
    asyncio event loop.
    """
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        repo_path = tmp_dir / "repo"

        # Clone (blocking — run in executor so we don't block the event loop)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            clone_repo_with_token,
            clone_url,
            installation_token,
            repo_path,
        )

        # Checkout head_sha
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["git", "checkout", head_sha, "--quiet"],
                cwd=repo_path, check=True, capture_output=True,
            ),
        )

        # Compute diff and build context (blocking, run in executor)
        def _build():
            change_set = _compute_changeset(base_sha, head_sha, repo_path)
            code_context = _build_code_context(change_set)
            return change_set, code_context

        change_set, code_context = await loop.run_in_executor(None, _build)

        if not change_set.files:
            # No changed files — nothing to review
            from utils.dataclasses import ReviewResult
            return ReviewResult(
                summary="No reviewable changes found in this pull request.",
                warnings=[],
                overall_confidence=1.0,
                findings=[],
                stats={},
            )

        # Run agentic review (async, calls Anthropic API)
        review_result: ReviewResult = await run_review_core(
            code_context=asdict(code_context),
            change_set=asdict(change_set),
            repo_path=str(repo_path),
            heartbeat_fn=None,
            model_override=model,
        )

        return review_result

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
