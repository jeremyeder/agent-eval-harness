#!/usr/bin/env python3
"""Attach judge feedback to MLflow traces.

Searches for MLflow traces in an experiment and attaches judge scores
as feedback using the MLflow feedback API.

Note: This requires traces to be tagged with case_id during execution.
If no traces are found or traces lack case_id tags, the script will
warn and exit gracefully.

Usage:
    python3 ${CLAUDE_SKILL_DIR}/scripts/attach_feedback.py \\
        --config eval.yaml \\
        --run-id run-20260404-1234 \\
        --experiment my-experiment
"""

import argparse
import sys
from pathlib import Path

import mlflow
import yaml

from agent_eval.config import EvalConfig
from agent_eval.mlflow.experiment import log_feedback


RUNS_DIR = Path("eval/runs")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", default="eval.yaml",
                        help="Path to eval configuration file")
    parser.add_argument("--run-id", required=True,
                        help="Run ID to attach feedback for")
    parser.add_argument("--experiment", default=None,
                        help="Experiment name (default: from config)")
    args = parser.parse_args()

    # Load config
    try:
        config = EvalConfig.from_yaml(args.config)
    except FileNotFoundError:
        print(f"ERROR: Config not found: {args.config}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Failed to load config: {e}", file=sys.stderr)
        sys.exit(1)

    # Determine experiment name
    experiment_name = args.experiment or config.mlflow_experiment
    if not experiment_name:
        print("ERROR: No experiment name provided (use --experiment or set mlflow_experiment in config)",
              file=sys.stderr)
        sys.exit(1)

    # Check MLflow availability
    try:
        import mlflow
    except ImportError:
        print("WARNING: MLflow not available", file=sys.stderr)
        print("Skipping feedback attachment.", file=sys.stderr)
        sys.exit(0)

    # Get experiment
    try:
        experiment = mlflow.get_experiment_by_name(experiment_name)
        if not experiment:
            print(f"WARNING: Experiment '{experiment_name}' not found", file=sys.stderr)
            print("Skipping feedback attachment.", file=sys.stderr)
            sys.exit(0)
        experiment_id = experiment.experiment_id
    except Exception as e:
        print(f"WARNING: Failed to get experiment: {e}", file=sys.stderr)
        print("Skipping feedback attachment.", file=sys.stderr)
        sys.exit(0)

    # Load per_case results from summary
    run_dir = RUNS_DIR / args.run_id
    summary_path = run_dir / "summary.yaml"

    if not summary_path.exists():
        print(f"WARNING: summary.yaml not found: {summary_path}", file=sys.stderr)
        print("Skipping feedback attachment.", file=sys.stderr)
        sys.exit(0)

    try:
        with open(summary_path) as f:
            summary = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"ERROR: Failed to load summary.yaml: {e}", file=sys.stderr)
        sys.exit(1)

    per_case = summary.get("per_case", {})
    if not per_case:
        print("WARNING: No per_case results in summary.yaml", file=sys.stderr)
        print("Skipping feedback attachment.", file=sys.stderr)
        sys.exit(0)

    # Search for traces
    print(f"Searching for traces in experiment '{experiment_name}'...", file=sys.stderr)

    try:
        traces = mlflow.search_traces(experiment_ids=[experiment_id], max_results=1000)
    except Exception as e:
        print(f"WARNING: Failed to search traces: {e}", file=sys.stderr)
        print("Skipping feedback attachment.", file=sys.stderr)
        sys.exit(0)

    if not traces:
        print(f"WARNING: No traces found in experiment '{experiment_name}'", file=sys.stderr)
        print("Skipping feedback attachment.", file=sys.stderr)
        sys.exit(0)

    print(f"  Found {len(traces)} traces", file=sys.stderr)

    # Attach feedback
    attached_count = 0
    matched_cases = set()

    for trace in traces:
        # Try to extract case_id from trace tags
        case_id = None

        # Check trace tags
        if hasattr(trace, "tags") and trace.tags:
            case_id = trace.tags.get("case_id")

        # Check trace request_metadata if tags don't have it
        if not case_id and hasattr(trace, "request_metadata") and trace.request_metadata:
            case_id = trace.request_metadata.get("case_id")

        if not case_id:
            continue

        # Find matching per_case results
        case_results = per_case.get(case_id)
        if not case_results:
            continue

        matched_cases.add(case_id)

        # Attach feedback for each judge
        for judge_name, judge_result in case_results.items():
            try:
                value = judge_result.get("value")
                rationale = judge_result.get("rationale", "")

                if value is not None:
                    log_feedback(
                        trace_id=trace.request_id,
                        name=judge_name,
                        value=value,
                        rationale=rationale,
                    )
                    attached_count += 1
            except Exception as e:
                print(f"  WARNING: Failed to attach feedback for {case_id}/{judge_name}: {e}",
                      file=sys.stderr)
                continue

    # Print summary
    print(f"\nAttached feedback to {len(matched_cases)} traces ({attached_count} feedback items)")

    if len(matched_cases) == 0:
        print("\nWARNING: No traces matched case IDs from summary.yaml", file=sys.stderr)
        print("This is expected if traces were not tagged with case_id during execution.", file=sys.stderr)
        print("To enable trace feedback, ensure the runner tags traces with case_id.", file=sys.stderr)


if __name__ == "__main__":
    main()
