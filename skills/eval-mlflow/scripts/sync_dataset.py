#!/usr/bin/env python3
"""Sync evaluation cases to MLflow dataset.

Reads case directories from dataset.path in eval.yaml and syncs them
to an MLflow dataset using mlflow.genai.datasets API.

Usage:
    python3 ${CLAUDE_SKILL_DIR}/scripts/sync_dataset.py \\
        --config eval.yaml \\
        --dataset-name my-dataset
"""

import argparse
import sys
from pathlib import Path

import mlflow
from mlflow.genai.datasets import create_dataset, get_dataset

from agent_eval.config import EvalConfig
from agent_eval.mlflow.experiment import setup_experiment


def _resolve_under(root: Path, candidate: Path) -> Path:
    """Ensure a path resolves under root. Raises ValueError if it escapes."""
    resolved = candidate.resolve()
    root_resolved = root.resolve()
    if not resolved.is_relative_to(root_resolved):
        raise ValueError(f"Path escapes root directory: {candidate}")
    return resolved


def load_case(case_dir: Path, config: EvalConfig) -> dict:
    """Load a case directory into an MLflow dataset record.

    Classifies files by naming heuristic:
    - input*, prompt* → inputs
    - expected*, reference* → expectations
    - all others → inputs

    Returns:
        {"inputs": {...}, "expectations": {...}, "case_id": str}
    """
    case_dir = case_dir.resolve()
    project_root = Path.cwd().resolve()

    # Validate case directory is under project root
    _resolve_under(project_root, case_dir)

    inputs = {}
    expectations = {}

    # Read all files in the case directory
    for file_path in sorted(case_dir.rglob("*")):
        if not file_path.is_file() or file_path.is_symlink():
            continue

        # Validate each file is under case_dir
        _resolve_under(case_dir, file_path)

        rel_path = str(file_path.relative_to(case_dir))
        file_name = file_path.name.lower()

        # Read file content
        try:
            content = file_path.read_text()
        except UnicodeDecodeError:
            content = f"<binary: {file_path.name}>"

        # Classify by naming heuristic
        if file_name.startswith(("expected", "reference")):
            expectations[rel_path] = content
        else:
            # Default to inputs (includes input*, prompt*, and all others)
            inputs[rel_path] = content

    return {
        "inputs": inputs,
        "expectations": expectations,
        "case_id": case_dir.name,
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", default="eval.yaml",
                        help="Path to eval configuration file")
    parser.add_argument("--dataset-name", required=True,
                        help="Name for the MLflow dataset")
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
        print("Skipping dataset sync.", file=sys.stderr)
        sys.exit(0)

    # Get dataset path
    if not config.dataset_path:
        print("ERROR: dataset.path not configured in eval.yaml", file=sys.stderr)
        sys.exit(1)

    dataset_dir = Path(config.dataset_path)
    if not dataset_dir.exists():
        print(f"ERROR: Dataset directory not found: {dataset_dir}", file=sys.stderr)
        sys.exit(1)

    # Load all cases
    print(f"Loading cases from {dataset_dir}...", file=sys.stderr)
    records = []
    case_dirs = sorted(d for d in dataset_dir.iterdir() if d.is_dir())

    if not case_dirs:
        print(f"WARNING: No case directories found in {dataset_dir}", file=sys.stderr)
        sys.exit(0)

    for case_dir in case_dirs:
        try:
            record = load_case(case_dir, config)
            records.append(record)
            print(f"  Loaded: {case_dir.name}", file=sys.stderr)
        except Exception as e:
            print(f"  ERROR loading {case_dir.name}: {e}", file=sys.stderr)
            continue

    if not records:
        print("ERROR: No cases loaded successfully", file=sys.stderr)
        sys.exit(1)

    # Sync to MLflow dataset
    try:
        # Try to get existing dataset, or create new one
        try:
            dataset = get_dataset(name=args.dataset_name)
            print(f"Found existing dataset: {args.dataset_name}", file=sys.stderr)
        except Exception:
            dataset = create_dataset(name=args.dataset_name)
            print(f"Created new dataset: {args.dataset_name}", file=sys.stderr)

        # Merge records
        dataset.merge_records(records)
        print(f"\nSynced {len(records)} cases to MLflow dataset '{args.dataset_name}'")

    except Exception as e:
        print(f"ERROR: Failed to sync dataset: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
