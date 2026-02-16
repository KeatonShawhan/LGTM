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


def show_results(result_path: Path):
    """Pretty-print a single benchmark run."""
    with open(result_path) as f:
        data = json.load(f)

    print(f"\n{'='*70}")
    print(f"  Benchmark Results: {result_path.name}")
    print(f"  Model: {data['model']}")
    print(f"  Timestamp: {data['timestamp']}")
    print(f"{'='*70}")

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


def main():
    parser = argparse.ArgumentParser(description="LGTM Benchmark Reporter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_parser = subparsers.add_parser("show", help="Show results from a single run")
    show_parser.add_argument("result_file", type=Path)

    compare_parser = subparsers.add_parser("compare", help="Compare two runs")
    compare_parser.add_argument("file_a", type=Path, help="First (baseline) run")
    compare_parser.add_argument("file_b", type=Path, help="Second (comparison) run")

    args = parser.parse_args()

    if args.command == "show":
        show_results(args.result_file)
    elif args.command == "compare":
        compare_results(args.file_a, args.file_b)


if __name__ == "__main__":
    main()
