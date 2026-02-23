"""
Results reporter — pretty-print benchmark results and compare two runs.

Usage:
    python -m benchmarks.reporter show results/run_2026-02-15_sonnet.json
    python -m benchmarks.reporter compare results/run_v1.json results/run_v2.json
"""
import argparse
import json
import sys
from pathlib import Path

from benchmarks.trace_analyzer import analyze_trace, aggregate_trace_metrics


# ---------------------------------------------------------------------------
# Case loading (shared with runner)
# ---------------------------------------------------------------------------

CASES_DIR = Path(__file__).parent / "cases"
RESULTS_DIR = Path(__file__).parent / "results"


def _resolve_latest() -> Path:
    """Return the most recent result JSON in the results directory."""
    results = sorted(RESULTS_DIR.glob("run_*.json"))
    if not results:
        print("No result files found in", RESULTS_DIR)
        sys.exit(1)
    return results[-1]


def _load_case_definitions() -> dict:
    """Load all benchmark case definitions, keyed by case_id."""
    from benchmarks.runner import load_case

    case_defs = {}
    for path in sorted(CASES_DIR.glob("*.json")):
        bc = load_case(path)
        case_defs[bc.case_id] = bc
    return case_defs


# ---------------------------------------------------------------------------
# Show
# ---------------------------------------------------------------------------

def show_results(result_path: Path):
    """Pretty-print a single benchmark run."""
    with open(result_path) as f:
        data = json.load(f)

    print(f"\n{'='*70}")
    print(f"  Benchmark Results: {result_path.name}")
    print(f"  Model: {data['model']}")
    print(f"  Timestamp: {data['timestamp']}")
    print(f"{'='*70}")

    # Load case definitions for trace analysis
    case_defs = _load_case_definitions()
    all_trace_metrics = []

    for case in data["cases"]:
        score = case["score"]
        print(f"\n  {case['case_id']}: {case['case_name']}")
        print(f"    Precision: {score['precision']:.2f}  Recall: {score['recall']:.2f}  F1: {score['f1']:.2f}")
        print(f"    TP: {score['true_positives']}  FN: {score['false_negatives']}  FP: {score['false_positives']}")
        print(f"    Clean violations: {score['clean_violations']}/{score['clean_total']}")

        # Show match details
        for md in score.get("match_details", []):
            exp = md["expected"]
            status = "MATCHED" if md["matched"] else "MISSED"
            icon = "+" if md["matched"] else "-"
            print(f"      [{icon}] {status}: {exp['description'][:60]}...")
            if md["matched"] and md.get("actual_title"):
                print(f"          Found: {md['actual_title']}")
            if md.get("llm_match"):
                print(f"          (LLM graded: confidence={md['llm_confidence']:.2f})")

        # Show false positives
        review = case.get("review_result", {})
        findings = review.get("findings", [])
        matched_titles = {
            md.get("actual_title") for md in score.get("match_details", []) if md["matched"]
        }
        fps = [f for f in findings if f.get("title") not in matched_titles]
        if fps:
            print(f"    False positives:")
            for fp in fps:
                print(f"      [!] {fp.get('file_path', '?')}:{fp.get('line_number', '?')} — {fp.get('title', '?')}")

        tokens = score.get("token_usage") or {}
        print(f"    Tokens: {tokens.get('total', 'N/A')}  Iterations: {score.get('iterations', 'N/A')}  Time: {score.get('wall_time_seconds', 0):.1f}s")

        # Trace metrics (if trace_log is available)
        bc = case_defs.get(case["case_id"])
        if bc and review.get("trace_log"):
            tm = analyze_trace(case, bc)
            if tm:
                all_trace_metrics.append(tm)
                _print_case_trace_metrics(tm)

    # Aggregate
    agg = data.get("aggregate", {})
    print(f"\n{'='*70}")
    print(f"  AGGREGATE ({agg.get('cases_run', 0)} cases)")
    print(f"{'='*70}")
    print(f"  Avg Precision: {agg.get('avg_precision', 0):.3f}")
    print(f"  Avg Recall:    {agg.get('avg_recall', 0):.3f}")
    print(f"  Avg F1:        {agg.get('avg_f1', 0):.3f}")
    print(f"  Micro P/R/F1:  {agg.get('micro_precision', 0):.3f} / {agg.get('micro_recall', 0):.3f} / {agg.get('micro_f1', 0):.3f}")
    print(f"  Total TP/FN/FP: {agg.get('total_true_positives', 0)} / {agg.get('total_false_negatives', 0)} / {agg.get('total_false_positives', 0)}")
    print(f"  Total Tokens:  {agg.get('total_tokens', 0)}")
    print(f"  Total Time:    {agg.get('total_wall_time', 0):.1f}s")

    # Trace aggregate
    if all_trace_metrics:
        _print_trace_aggregate(all_trace_metrics)


def _print_case_trace_metrics(tm):
    """Print trace metrics for a single case."""
    c = tm.coverage
    e = tm.efficiency
    r = tm.correctness

    print(f"    --- Trace Metrics ---")
    print(f"    Coverage:")
    print(f"      File coverage:      {c.file_coverage:.0%} ({c.files_analyzed}/{c.files_changed})")
    print(f"      Bug file coverage:  {c.bug_file_coverage:.0%}")
    print(f"      Bug line coverage:  {c.bug_line_coverage:.0%}")
    if c.truncated_bug_files:
        print(f"      Truncated bug files: {', '.join(c.truncated_bug_files)}")
    if c.diff_truncation_rate > 0:
        print(f"      Diff truncation:    {c.diff_truncation_rate:.0%}")
    print(f"    Efficiency:")
    print(f"      Tokens/TP:          {e.tokens_per_tp:.0f}")
    print(f"      Tool calls:         {e.tool_calls_total} ({e.tool_calls_per_iteration:.1f}/iter)")
    print(f"      Redundant calls:    {e.redundant_tool_calls}")
    if e.exploration_overhead > 0:
        print(f"      Exploration overhead: {e.exploration_overhead:.0%}")
    print(f"    Correctness:")
    print(f"      Finding hit rate:   {r.tool_call_hit_rate:.0%}")
    print(f"      Evidence validated: {r.evidence_validation_rate:.0%}")
    if r.confidence_calibration:
        cal_parts = [f"{k}={v:.0%}" for k, v in r.confidence_calibration.items()]
        print(f"      Confidence cal:     {', '.join(cal_parts)}")
    print(f"      Category accuracy:  {r.category_accuracy:.0%}")
    print(f"      Severity accuracy:  {r.severity_accuracy:.0%}")

    ev = tm.evidence_validation
    print(f"    Evidence Validation:")
    print(f"      Validation rate:    {ev.validation_rate:.0%}")
    print(f"      Avg conf delta:     {ev.avg_confidence_delta:+.4f}")
    print(f"      Rejections:         {ev.rejection_count}")
    if ev.signal_rates:
        sigs = ", ".join(f"{k}={v:.0%}" for k, v in ev.signal_rates.items())
        print(f"      Signals:            {sigs}")


def _print_trace_aggregate(all_trace_metrics):
    """Print suite-level trace metric aggregates."""
    agg = aggregate_trace_metrics(all_trace_metrics)

    print(f"\n  {'-'*50}")
    print(f"  TRACE AGGREGATE ({len(all_trace_metrics)} cases with traces)")
    print(f"  {'-'*50}")
    print(f"  Coverage:")
    print(f"    Avg file coverage:      {agg['avg_file_coverage']:.0%}")
    print(f"    Avg bug file coverage:  {agg['avg_bug_file_coverage']:.0%}")
    print(f"    Avg bug line coverage:  {agg['avg_bug_line_coverage']:.0%}")
    print(f"    Avg diff truncation:    {agg['avg_diff_truncation_rate']:.0%}")
    print(f"  Efficiency:")
    print(f"    Avg tokens/TP:          {agg['avg_tokens_per_tp']:.0f}")
    print(f"    Total tool calls:       {agg['total_tool_calls']}")
    print(f"    Total redundant calls:  {agg['total_redundant_tool_calls']}")
    print(f"    Avg auto-route rate:    {agg['avg_auto_route_rate']:.0%}")
    print(f"    Avg exploration overhead: {agg['avg_exploration_overhead']:.0%}")
    print(f"  Correctness:")
    print(f"    Avg finding hit rate:   {agg['avg_tool_call_hit_rate']:.0%}")
    print(f"    Avg evidence validated: {agg['avg_evidence_validation_rate']:.0%}")
    print(f"    Avg category accuracy:  {agg['avg_category_accuracy']:.0%}")
    print(f"    Avg severity accuracy:  {agg['avg_severity_accuracy']:.0%}")
    print(f"  Evidence Validation:")
    print(f"    Avg validation rate:    {agg.get('avg_validation_rate', 0):.0%}")
    print(f"    Avg confidence delta:   {agg.get('avg_confidence_delta', 0):+.4f}")
    print(f"    Total rejections:       {agg.get('total_rejections', 0)}")


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

def compare_results(path_a: Path, path_b: Path):
    """Compare two benchmark runs side-by-side."""
    with open(path_a) as f:
        data_a = json.load(f)
    with open(path_b) as f:
        data_b = json.load(f)

    print(f"\n{'='*70}")
    print(f"  Comparison")
    print(f"  A: {path_a.name}  (model: {data_a['model']})")
    print(f"  B: {path_b.name}  (model: {data_b['model']})")
    print(f"{'='*70}")

    # Index cases by ID
    cases_a = {c["case_id"]: c["score"] for c in data_a["cases"]}
    cases_b = {c["case_id"]: c["score"] for c in data_b["cases"]}

    all_case_ids = sorted(set(cases_a.keys()) | set(cases_b.keys()))

    print(f"\n  {'Case':<25} {'F1 (A)':>8} {'F1 (B)':>8} {'Delta':>8} {'Status':<12}")
    print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*8} {'-'*12}")

    for case_id in all_case_ids:
        sa = cases_a.get(case_id, {})
        sb = cases_b.get(case_id, {})
        f1_a = sa.get("f1", 0.0)
        f1_b = sb.get("f1", 0.0)
        delta = f1_b - f1_a

        if delta > 0.01:
            status = "IMPROVED"
        elif delta < -0.01:
            status = "REGRESSED"
        else:
            status = "stable"

        print(f"  {case_id:<25} {f1_a:>8.2f} {f1_b:>8.2f} {delta:>+8.2f} {status:<12}")

    # Aggregate comparison
    agg_a = data_a.get("aggregate", {})
    agg_b = data_b.get("aggregate", {})

    print(f"\n  {'Aggregate':<25} {'A':>8} {'B':>8} {'Delta':>8}")
    print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*8}")

    for metric in ["avg_f1", "avg_precision", "avg_recall", "micro_f1"]:
        va = agg_a.get(metric, 0.0)
        vb = agg_b.get(metric, 0.0)
        print(f"  {metric:<25} {va:>8.3f} {vb:>8.3f} {vb - va:>+8.3f}")

    tokens_a = agg_a.get("total_tokens", 0)
    tokens_b = agg_b.get("total_tokens", 0)
    pct = ((tokens_b - tokens_a) / tokens_a * 100) if tokens_a else 0
    print(f"  {'total_tokens':<25} {tokens_a:>8} {tokens_b:>8} {pct:>+7.1f}%")

    time_a = agg_a.get("total_wall_time", 0)
    time_b = agg_b.get("total_wall_time", 0)
    pct_t = ((time_b - time_a) / time_a * 100) if time_a else 0
    print(f"  {'total_wall_time':<25} {time_a:>7.1f}s {time_b:>7.1f}s {pct_t:>+7.1f}%")

    # Trace aggregate comparison
    case_defs = _load_case_definitions()
    full_cases_a = {c["case_id"]: c for c in data_a["cases"]}
    full_cases_b = {c["case_id"]: c for c in data_b["cases"]}

    trace_a = []
    trace_b = []
    for cid in all_case_ids:
        bc = case_defs.get(cid)
        if not bc:
            continue
        ca = full_cases_a.get(cid)
        cb = full_cases_b.get(cid)
        if ca and ca.get("review_result", {}).get("trace_log"):
            tm = analyze_trace(ca, bc)
            if tm:
                trace_a.append(tm)
        if cb and cb.get("review_result", {}).get("trace_log"):
            tm = analyze_trace(cb, bc)
            if tm:
                trace_b.append(tm)

    if trace_a or trace_b:
        agg_ta = aggregate_trace_metrics(trace_a) if trace_a else {}
        agg_tb = aggregate_trace_metrics(trace_b) if trace_b else {}

        trace_metrics = [
            "avg_file_coverage",
            "avg_bug_file_coverage",
            "avg_tokens_per_tp",
            "avg_tool_call_hit_rate",
            "avg_evidence_validation_rate",
            "avg_category_accuracy",
            "avg_severity_accuracy",
            "avg_validation_rate",
            "avg_confidence_delta",
        ]

        print(f"\n  {'Trace Metrics':<30} {'A':>8} {'B':>8} {'Delta':>8}")
        print(f"  {'-'*30} {'-'*8} {'-'*8} {'-'*8}")
        for metric in trace_metrics:
            va = agg_ta.get(metric, 0)
            vb = agg_tb.get(metric, 0)
            print(f"  {metric:<30} {va:>8.3f} {vb:>8.3f} {vb - va:>+8.3f}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LGTM Benchmark Reporter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_parser = subparsers.add_parser("show", help="Show results from a single run")
    show_parser.add_argument("result_file", nargs="?", default="latest",
                             help="Path to result JSON, or 'latest' (default)")

    compare_parser = subparsers.add_parser("compare", help="Compare two runs")
    compare_parser.add_argument("file_a", type=Path, help="First (baseline) run")
    compare_parser.add_argument("file_b", type=Path, help="Second (comparison) run")

    args = parser.parse_args()

    if args.command == "show":
        result_file = _resolve_latest() if args.result_file == "latest" else Path(args.result_file)
        show_results(result_file)
    elif args.command == "compare":
        compare_results(args.file_a, args.file_b)


if __name__ == "__main__":
    main()
