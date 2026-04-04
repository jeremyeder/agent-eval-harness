#!/usr/bin/env python3
"""Log evaluation run results to MLflow.

Reads summary.yaml and run_result.json from a completed eval run and logs
parameters, metrics, tags, and artifacts to MLflow.

Usage:
    python3 ${CLAUDE_SKILL_DIR}/scripts/log_results.py \\
        --config eval.yaml \\
        --run-id run-20260404-1234
"""

import argparse
import json
import os
import sys
from pathlib import Path

import mlflow
import yaml

from agent_eval.config import EvalConfig
from agent_eval.mlflow.experiment import setup_experiment


RUNS_DIR = Path("eval/runs")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", default="eval.yaml",
                        help="Path to eval configuration file")
    parser.add_argument("--run-id", required=True,
                        help="Run ID to log results for")
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

    # Setup MLflow experiment
    try:
        setup_experiment(config.mlflow_experiment)
    except Exception as e:
        print(f"WARNING: MLflow not available: {e}", file=sys.stderr)
        print("Skipping results logging.", file=sys.stderr)
        sys.exit(0)

    # Load run data
    run_dir = RUNS_DIR / args.run_id
    if not run_dir.exists():
        print(f"ERROR: Run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    summary_path = run_dir / "summary.yaml"
    if not summary_path.exists():
        print(f"ERROR: summary.yaml not found: {summary_path}", file=sys.stderr)
        sys.exit(1)

    run_result_path = run_dir / "run_result.json"
    if not run_result_path.exists():
        print(f"ERROR: run_result.json not found: {run_result_path}", file=sys.stderr)
        sys.exit(1)

    # Load summary
    try:
        with open(summary_path) as f:
            summary = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"ERROR: Failed to load summary.yaml: {e}", file=sys.stderr)
        sys.exit(1)

    # Load run_result
    try:
        with open(run_result_path) as f:
            run_result = json.load(f)
    except Exception as e:
        print(f"ERROR: Failed to load run_result.json: {e}", file=sys.stderr)
        sys.exit(1)

    # Start MLflow run
    print(f"Logging results for {args.run_id} to MLflow...", file=sys.stderr)

    try:
        with mlflow.start_run(run_name=args.run_id) as run:
            # Log parameters
            mlflow.log_param("skill", config.skill or "unknown")
            mlflow.log_param("agent", run_result.get("agent", "unknown"))

            # Model from config runtime overrides
            if config.model:
                mlflow.log_param("model", config.model)

            # Log metrics from judges
            judges_data = summary.get("judges", {})
            for judge_name, judge_metrics in judges_data.items():
                # Log mean if available
                if judge_metrics.get("mean") is not None:
                    mlflow.log_metric(f"{judge_name}_mean", judge_metrics["mean"])

                # Log pass_rate if available
                if judge_metrics.get("pass_rate") is not None:
                    mlflow.log_metric(f"{judge_name}_pass_rate", judge_metrics["pass_rate"])

            # Log run metadata metrics
            if run_result.get("duration_s") is not None:
                mlflow.log_metric("duration_s", run_result["duration_s"])

            if run_result.get("cost_usd") is not None:
                mlflow.log_metric("cost_usd", run_result["cost_usd"])

            # Log token usage if available
            token_usage = run_result.get("token_usage", {})
            if token_usage:
                total_tokens = (token_usage.get("input", 0) +
                                token_usage.get("output", 0))
                if total_tokens > 0:
                    mlflow.log_metric("total_tokens", total_tokens)
                if token_usage.get("input"):
                    mlflow.log_metric("input_tokens", token_usage["input"])
                if token_usage.get("output"):
                    mlflow.log_metric("output_tokens", token_usage["output"])

            # Set tags
            exit_code = run_result.get("exit_code", -1)
            mlflow.set_tag("exit_code", str(exit_code))

            # Check for regressions in summary
            regressions_detected = "no"
            if summary.get("regressions"):
                regressions_detected = "yes"
            # Also check pairwise results if present
            elif summary.get("pairwise", {}).get("wins_b", 0) > summary.get("pairwise", {}).get("wins_a", 0):
                regressions_detected = "yes"

            mlflow.set_tag("regressions_detected", regressions_detected)

            # Log artifact
            mlflow.log_artifact(str(summary_path))

            # Print summary
            tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
            print(f"\nLogged to experiment '{config.mlflow_experiment}', run '{args.run_id}'")
            print(f"  Run ID: {run.info.run_id}")
            print(f"  Judges: {len(judges_data)}")
            print(f"  Duration: {run_result.get('duration_s', 0):.1f}s")
            if run_result.get("cost_usd"):
                print(f"  Cost: ${run_result['cost_usd']:.2f}")
            print(f"  Regressions: {regressions_detected}")
            print(f"\nMLflow UI: {tracking_uri}")

    except Exception as e:
        print(f"ERROR: Failed to log results: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
