"""
Benchmark runner — orchestrates: load case → git diff → CodeContext → review → score.

Bypasses Temporal entirely; calls pipeline functions directly.

Usage:
    python -m benchmarks.runner                          # Run all cases
    python -m benchmarks.runner --case null_deref_001    # Run one case
    python -m benchmarks.runner --model haiku            # Use cheaper model
"""
import argparse
import asyncio
import concurrent.futures
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path so we can import LGTM modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env from project root (same one the main pipeline uses)
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env", override=True)

from activities.gitDiff import parse_diff_output
from activities.prioritizeFiles import compute_risk_score, should_ignore_file
from activities.agenticReview import run_review_core
from utils.dataclasses import (
    ChangeSet, ChangedFile, CodeContext, ContextOverview, Totals,
    FileTypeStats, FileContext, ContextMetadata, PrioritizedFile, FileSummary,
)
from benchmarks.dataclasses import BenchmarkCase, ExpectedFinding, ExpectedClean
from benchmarks.scorer import score_review
from benchmarks.trace_analyzer import analyze_trace, aggregate_trace_metrics

FIXTURE_REPO = Path(__file__).resolve().parent / "fixture_repo"
CASES_DIR = Path(__file__).resolve().parent / "cases"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

MODEL_ALIASES = {
    "sonnet": "claude-sonnet-4-20250514",
    "haiku": "claude-haiku-4-5-20251001",
    "opus": "claude-opus-4-20250514",
}


# ---------------------------------------------------------------------------
# Case loading
# ---------------------------------------------------------------------------

def load_case(case_path: Path) -> BenchmarkCase:
    """Load a BenchmarkCase from a JSON file."""
    with open(case_path, "r") as f:
        data = json.load(f)

    expected_findings = [
        ExpectedFinding(
            file_path=ef["file_path"],
            line_range=tuple(ef["line_range"]),
            severity_min=ef["severity_min"],
            category=ef["category"],
            description=ef["description"],
            keywords=ef["keywords"],
            required=ef.get("required", True),
        )
        for ef in data.get("expected_findings", [])
    ]

    expected_clean = [
        ExpectedClean(
            file_path=ec["file_path"],
            description=ec["description"],
            max_findings=ec.get("max_findings", 0),
        )
        for ec in data.get("expected_clean", [])
    ]

    return BenchmarkCase(
        case_id=data["case_id"],
        name=data["name"],
        description=data["description"],
        base_ref=data["base_ref"],
        head_ref=data["head_ref"],
        expected_findings=expected_findings,
        expected_clean=expected_clean,
        tags=data.get("tags", []),
    )


def discover_cases(case_id: str | None = None) -> list[BenchmarkCase]:
    """Discover and load benchmark cases from the cases directory."""
    if case_id:
        path = CASES_DIR / f"{case_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Benchmark case not found: {path}")
        return [load_case(path)]

    cases = []
    for path in sorted(CASES_DIR.glob("*.json")):
        cases.append(load_case(path))
    return cases


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def resolve_ref(ref: str, repo_path: Path = FIXTURE_REPO) -> str:
    """Resolve a git ref to a SHA in the given repo."""
    result = subprocess.run(
        ["git", "rev-parse", ref],
        cwd=repo_path, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def compute_changeset(base_sha: str, head_sha: str, repo_path: Path = FIXTURE_REPO) -> ChangeSet:
    """Compute ChangeSet between two commits in the fixture repo."""
    result = subprocess.run(
        ["git", "diff", "-U3", base_sha, head_sha],
        cwd=repo_path, capture_output=True, text=True, check=True,
    )
    files = parse_diff_output(result.stdout)
    return ChangeSet(base_commit=base_sha, head_commit=head_sha, files=files)


def clone_fixture_repo(dest: Path) -> None:
    """Clone fixture repo into dest using hardlinks (fast, minimal disk use)."""
    subprocess.run(
        ["git", "clone", "--local", str(FIXTURE_REPO), str(dest)],
        check=True, capture_output=True,
    )


# ---------------------------------------------------------------------------
# CodeContext builder (mirrors buildCodeContextWorkflow without Temporal)
# ---------------------------------------------------------------------------

def build_code_context(change_set: ChangeSet) -> CodeContext:
    """Build CodeContext directly, bypassing Temporal workflows."""

    # Layer 0: Overview
    total_lines_added = sum(f.added for f in change_set.files)
    total_lines_removed = sum(f.removed for f in change_set.files)
    total_hunks = sum(len(f.hunks) for f in change_set.files)
    files_added = sum(1 for f in change_set.files if f.added > 0 and f.removed == 0)
    files_deleted = sum(1 for f in change_set.files if f.removed > 0 and f.added == 0)

    # File type breakdown
    file_type_stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "lines_added": 0, "lines_removed": 0})
    for file in change_set.files:
        ext = f".{file.path.rsplit('.', 1)[-1].lower()}" if '.' in file.path else "no_extension"
        file_type_stats[ext]["count"] += 1
        file_type_stats[ext]["lines_added"] += file.added
        file_type_stats[ext]["lines_removed"] += file.removed

    file_breakdown = {
        ft: FileTypeStats(count=s["count"], lines_added=s["lines_added"], lines_removed=s["lines_removed"])
        for ft, s in file_type_stats.items()
    }

    flags = []
    if files_added > 0:
        flags.append("has_new_files")
    if files_deleted > 0:
        flags.append("has_deleted_files")
    if total_lines_added > 1000 or total_lines_removed > 1000:
        flags.append("large_change")

    overview = ContextOverview(
        totals=Totals(
            files_changed=len(change_set.files),
            files_added=files_added,
            files_deleted=files_deleted,
            lines_added=total_lines_added,
            lines_removed=total_lines_removed,
            total_hunks=total_hunks,
        ),
        file_breakdown=file_breakdown,
        flags=flags,
    )

    # Prioritize files
    file_stats_map = {f.path: (f.added, f.removed) for f in change_set.files}
    files_dict: dict[str, FileContext] = {}

    for file in change_set.files:
        if should_ignore_file(file.path):
            continue
        risk_score, reasons = compute_risk_score(file)
        added, removed = file_stats_map.get(file.path, (0, 0))

        files_dict[file.path] = FileContext(
            path=file.path,
            risk_score=risk_score,
            added=added,
            removed=removed,
            reasons=reasons,
            summary=None,  # Skip summarization for benchmarks (saves API calls)
        )

    return CodeContext(
        repo_id="benchmark_fixture",
        base_commit=change_set.base_commit,
        head_commit=change_set.head_commit,
        overview=overview,
        files=files_dict,
        metadata=ContextMetadata(),
    )


# ---------------------------------------------------------------------------
# Run a single benchmark case
# ---------------------------------------------------------------------------

async def run_case(case: BenchmarkCase, model: str, repo_path: Path) -> dict:
    """Run a single benchmark case end-to-end and return scored results."""
    print(f"\n{'='*60}")
    print(f"  Case: {case.case_id} — {case.name}")
    print(f"  Model: {model}")
    print(f"{'='*60}")

    start_time = time.time()

    # 1. Resolve refs
    base_sha = resolve_ref(case.base_ref, repo_path)
    head_sha = resolve_ref(case.head_ref, repo_path)
    print(f"  Base: {base_sha[:8]}  Head: {head_sha[:8]}")

    # 2. Compute changeset
    change_set = compute_changeset(base_sha, head_sha, repo_path)
    print(f"  Files changed: {len(change_set.files)}")
    for f in change_set.files:
        print(f"    {f.path}  (+{f.added} -{f.removed})")

    # 3. Build code context
    code_context = build_code_context(change_set)

    # 4. Checkout the head state so the review agent can read files
    subprocess.run(
        ["git", "checkout", head_sha, "--quiet"],
        cwd=repo_path, check=True, capture_output=True,
    )

    # 5. Run agentic review
    print(f"  Running review...")
    try:
        review_result = await run_review_core(
            code_context=asdict(code_context),
            change_set=asdict(change_set),
            repo_path=str(repo_path),
            heartbeat_fn=lambda msg: print(f"    [{msg}]"),
            model_override=model,
        )
    finally:
        # Restore HEAD to master so the repo isn't in detached state
        subprocess.run(
            ["git", "checkout", "master", "--quiet"],
            cwd=repo_path, check=False, capture_output=True,
        )

    wall_time = time.time() - start_time

    # 6. Score
    case_score = score_review(review_result, case)
    case_score.wall_time_seconds = wall_time
    case_score.token_usage = review_result.token_usage
    case_score.iterations = review_result.iterations

    # 7. Print summary
    print(f"\n  Results for {case.case_id}:")
    print(f"    Precision: {case_score.precision:.2f}  Recall: {case_score.recall:.2f}  F1: {case_score.f1:.2f}")
    print(f"    TP: {case_score.true_positives}  FN: {case_score.false_negatives}  FP: {case_score.false_positives}")
    print(f"    Clean violations: {case_score.clean_violations}/{case_score.clean_total}")
    print(f"    Tokens: {review_result.token_usage}  Iterations: {review_result.iterations}")
    print(f"    Wall time: {wall_time:.1f}s")

    return {
        "case_id": case.case_id,
        "case_name": case.name,
        "score": asdict(case_score),
        "review_result": {
            "summary": review_result.summary,
            "warnings": review_result.warnings,
            "overall_confidence": review_result.overall_confidence,
            "findings": [asdict(f) for f in review_result.findings],
            "stats": review_result.stats,
            "token_usage": review_result.token_usage,
            "iterations": review_result.iterations,
            "files_analyzed": review_result.files_analyzed,
            "trace_log": review_result.trace_log,
        },
    }


def run_case_isolated_sync(case: BenchmarkCase, model: str) -> dict:
    """Clone fixture repo into a temp dir, run the case in isolation, then clean up.

    Runs in its own thread with its own event loop so the blocking sync Anthropic
    client calls don't stall the main event loop and cases execute truly in parallel.
    """
    tmp = Path(tempfile.mkdtemp())
    try:
        clone_fixture_repo(tmp)
        return asyncio.run(run_case(case, model, tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LGTM Benchmark Runner")
    parser.add_argument("--case", type=str, default=None, help="Run a specific case by ID")
    parser.add_argument("--model", type=str, default="sonnet", help="Model to use (sonnet, haiku, opus, or full model ID)")
    parser.add_argument("--concurrency", type=int, default=3, help="Max cases to run concurrently (default: 3, use 1 for serial)")
    args = parser.parse_args()

    model = MODEL_ALIASES.get(args.model, args.model)
    cases = discover_cases(args.case)
    print(f"Discovered {len(cases)} benchmark case(s)")
    print(f"Using model: {model}")
    print(f"Concurrency: {args.concurrency}")

    RESULTS_DIR.mkdir(exist_ok=True)

    suite_start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(run_case_isolated_sync, case, model) for case in cases]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    suite_wall_time = time.time() - suite_start

    # Reorder results to match original case order (as_completed returns in completion order)
    case_id_to_result = {r["case_id"]: r for r in results}
    results = [case_id_to_result[case.case_id] for case in cases]

    # Compute trace metrics for each case
    case_trace_metrics = []
    for result, case in zip(results, cases):
        if result.get("review_result", {}).get("trace_log"):
            tm = analyze_trace(result, case)
            if tm:
                case_trace_metrics.append(tm)

    # Aggregate and save
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    model_short = args.model if args.model in MODEL_ALIASES else model[:20]
    output_path = RESULTS_DIR / f"run_{timestamp}_{model_short}.json"

    suite_output = {
        "timestamp": timestamp,
        "model": model,
        "concurrency": args.concurrency,
        "cases": results,
        "aggregate": _compute_aggregate(results, suite_wall_time),
        "trace_aggregate": aggregate_trace_metrics(case_trace_metrics),
    }

    with open(output_path, "w") as f:
        json.dump(suite_output, f, indent=2, default=str)

    print(f"\n{'='*60}")
    print(f"  Suite Complete")
    print(f"{'='*60}")
    agg = suite_output["aggregate"]
    print(f"  Avg Precision: {agg['avg_precision']:.2f}")
    print(f"  Avg Recall:    {agg['avg_recall']:.2f}")
    print(f"  Avg F1:        {agg['avg_f1']:.2f}")
    print(f"  Total Tokens:  {agg['total_tokens']}")
    print(f"  Suite Time:    {agg['suite_wall_time']:.1f}s  (compute: {agg['total_wall_time']:.1f}s)")
    print(f"  Results saved: {output_path}")


def _compute_aggregate(results: list[dict], suite_wall_time: float = 0.0) -> dict:
    """Compute aggregate metrics across all cases.

    total_wall_time: sum of per-case wall times (compute cost proxy).
    suite_wall_time: actual elapsed time for the full suite (reflects parallelism).
    """
    scores = [r["score"] for r in results]
    n = len(scores)
    if n == 0:
        return {}

    total_tp = sum(s["true_positives"] for s in scores)
    total_fn = sum(s["false_negatives"] for s in scores)
    total_fp = sum(s["false_positives"] for s in scores)

    # Micro-averaged precision/recall/F1
    micro_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    micro_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    micro_f1 = 2 * micro_precision * micro_recall / (micro_precision + micro_recall) if (micro_precision + micro_recall) > 0 else 0.0

    # Macro-averaged (average per-case)
    avg_precision = sum(s["precision"] for s in scores) / n
    avg_recall = sum(s["recall"] for s in scores) / n
    avg_f1 = sum(s["f1"] for s in scores) / n

    total_tokens = sum(
        (s.get("token_usage") or {}).get("total", 0)
        for s in scores
    )

    return {
        "cases_run": n,
        "avg_precision": round(avg_precision, 3),
        "avg_recall": round(avg_recall, 3),
        "avg_f1": round(avg_f1, 3),
        "micro_precision": round(micro_precision, 3),
        "micro_recall": round(micro_recall, 3),
        "micro_f1": round(micro_f1, 3),
        "total_true_positives": total_tp,
        "total_false_negatives": total_fn,
        "total_false_positives": total_fp,
        "total_tokens": total_tokens,
        "total_wall_time": round(sum(s["wall_time_seconds"] for s in scores), 1),
        "suite_wall_time": round(suite_wall_time, 1),
    }


if __name__ == "__main__":
    main()
