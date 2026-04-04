#!/usr/bin/env python3
"""ETL: Walk completed runs, produce records.json, pareto.csv, and optionally log to MLflow.

Usage:
    python3 eval/scripts/etl_loader.py [--runs-dir eval/runs] [--output eval/results]
    python3 eval/scripts/etl_loader.py --mlflow [--experiment rfe-speedrun-eval]
"""

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def load_run(run_dir: Path) -> dict | None:
    """Load a single run's data into a unified record."""
    run_result_path = run_dir / "run_result.json"
    summary_path = run_dir / "summary.yaml"

    if not run_result_path.exists():
        return None

    with open(run_result_path) as f:
        run_result = json.load(f)

    # Parse run_id: {model}-{case_id}-rep{N}
    run_id = run_dir.name
    parts = run_id.rsplit("-rep", 1)
    if len(parts) != 2:
        return None

    rep = int(parts[1])
    model_and_case = parts[0]
    # Model name is first token, case_id is the rest (e.g., "opus-RHAIRFE-1473")
    first_dash = model_and_case.find("-")
    if first_dash == -1:
        return None
    model = model_and_case[:first_dash]
    case_id = model_and_case[first_dash + 1:]

    # Validate parsed IDs
    if not _SAFE_ID.fullmatch(model) or not _SAFE_ID.fullmatch(case_id):
        return None

    record = {
        "run_id": run_id,
        "model": model,
        "case_id": case_id,
        "repetition": rep,
        "exit_code": run_result.get("exit_code"),
        "duration_s": run_result.get("duration_s"),
        "cost_usd": run_result.get("cost_usd"),
        "token_usage": run_result.get("token_usage"),
        "tokens_input": (run_result.get("token_usage") or {}).get("input", 0),
        "tokens_output": (run_result.get("token_usage") or {}).get("output", 0),
        "tokens_total": sum((run_result.get("token_usage") or {}).values()) if run_result.get("token_usage") else 0,
    }

    # Load judge scores from summary.yaml
    if summary_path.exists():
        with open(summary_path) as f:
            summary = yaml.safe_load(f) or {}

        judges = summary.get("judges", {})
        for judge_name, judge_data in judges.items():
            if isinstance(judge_data, dict):
                mean = judge_data.get("mean")
                pass_rate = judge_data.get("pass_rate")
                record[judge_name] = mean if mean is not None else pass_rate
            else:
                record[judge_name] = judge_data

    return record


def load_all_runs(runs_dir: Path) -> list[dict]:
    """Walk runs directory and load all run records."""
    records = []
    if not runs_dir.exists():
        return records

    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir() or run_dir.name.startswith("."):
            continue
        record = load_run(run_dir)
        if record:
            records.append(record)

    return records


def write_records_json(records: list[dict], output_path: Path):
    with open(output_path, "w") as f:
        json.dump(records, f, indent=2)
    print(f"  records.json: {len(records)} records -> {output_path}")


def write_pareto_csv(records: list[dict], output_path: Path):
    fieldnames = [
        "model", "case_id", "repetition", "rubric_score", "cost_usd",
        "duration_s", "tokens_total", "pass_fail", "feasibility",
        "recommendation", "score_what", "score_why", "score_open_to_how",
        "score_not_a_task", "score_right_sized",
    ]
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in records:
            writer.writerow(r)
    print(f"  pareto.csv: {len(records)} rows -> {output_path}")


def log_to_mlflow(records: list[dict], experiment_name: str):
    """Log each record as an MLflow run."""
    try:
        import mlflow
    except ImportError:
        print("  WARNING: mlflow not installed, skipping MLflow logging")
        return

    mlflow.set_experiment(experiment_name)

    for record in records:
        with mlflow.start_run(run_name=record["run_id"]):
            # Log params
            mlflow.log_param("model", record["model"])
            mlflow.log_param("case_id", record["case_id"])
            mlflow.log_param("repetition", record["repetition"])

            # Log metrics
            for metric_key in [
                "rubric_score", "cost_usd", "duration_s",
                "tokens_input", "tokens_output", "tokens_total",
                "score_what", "score_why", "score_open_to_how",
                "score_not_a_task", "score_right_sized",
            ]:
                value = record.get(metric_key)
                if value is not None and isinstance(value, (int, float)):
                    mlflow.log_metric(metric_key, value)

            # Log pass_fail as metric (bool -> 1/0)
            pf = record.get("pass_fail")
            if pf is not None:
                mlflow.log_metric("pass_fail", 1.0 if pf else 0.0)

            # Log categorical values as params
            for param_key in ["feasibility", "recommendation"]:
                value = record.get(param_key)
                if value is not None:
                    mlflow.log_param(param_key, str(value))

    print(f"  MLflow: {len(records)} runs logged to experiment '{experiment_name}'")


def export_mlflow(experiment_name: str, output_dir: Path):
    """Export MLflow experiment using mlflow-export-import."""
    try:
        from mlflow_export_import.experiment.export_experiment import ExperimentExporter
        import mlflow
    except ImportError:
        print("  WARNING: mlflow-export-import not installed, skipping export")
        return

    export_path = output_dir / "mlflow-export"
    export_path.mkdir(parents=True, exist_ok=True)

    try:
        client = mlflow.MlflowClient()
        exporter = ExperimentExporter(client)
        exporter.export_experiment(experiment_name, str(export_path))
        print(f"  MLflow export: {export_path}")
    except Exception as e:
        print(f"  WARNING: MLflow export failed: {e}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs-dir", default="eval/runs")
    parser.add_argument("--output", default="eval/results")
    parser.add_argument("--mlflow", action="store_true", help="Log to MLflow")
    parser.add_argument("--experiment", default="rfe-speedrun-eval")
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    records = load_all_runs(runs_dir)

    if not records:
        print("No run records found.", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(records)} run records from {runs_dir}")

    # Create timestamped output directory
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_dir = Path(args.output) / ts
    output_dir.mkdir(parents=True, exist_ok=True)

    write_records_json(records, output_dir / "records.json")
    write_pareto_csv(records, output_dir / "pareto.csv")

    if args.mlflow:
        log_to_mlflow(records, args.experiment)
        export_mlflow(args.experiment, output_dir)

    print(f"\nResults: {output_dir}")


if __name__ == "__main__":
    main()
