"""MLflow dataset management utilities."""

import sys
import hashlib
import json
import os
import subprocess
from typing import Any


def _mlflow_api():
    """Load the native MLflow dataset APIs at the module boundary."""
    import mlflow
    from mlflow.genai.datasets import create_dataset, search_datasets

    return mlflow, create_dataset, search_datasets


def _repository_commit() -> str:
    """Return the commit identifying the source dataset, when available."""
    for name in ("GIT_COMMIT", "GITHUB_SHA", "CI_COMMIT_SHA"):
        if os.environ.get(name):
            return os.environ[name]
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def prepare_records(records: list[dict[str, Any]], source_commit: str | None = None):
    """Convert harness records to native MLflow evaluation records."""
    source = f"git:{source_commit or _repository_commit()}"
    prepared = []
    for record in records:
        inputs = record.get("inputs") or {}
        expectations = record.get("expectations")
        case_id = record.get("case_id") or _stable_case_id(inputs, expectations)
        tags = dict(record.get("tags") or {})
        tags.update({"case_id": str(case_id), "source": source})
        native = {"inputs": inputs, "tags": tags}
        if expectations:
            native["expectations"] = expectations
        if record.get("outputs") is not None:
            native["outputs"] = record["outputs"]
        prepared.append(native)
    return prepared


def _stable_case_id(inputs, expectations) -> str:
    payload = json.dumps(
        {"inputs": inputs, "expectations": expectations or {}},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return f"case-{hashlib.sha256(payload).hexdigest()[:16]}"


def get_or_create_dataset(
    name: str, experiment_name: str = "", source_commit: str | None = None
):
    """Get an existing MLflow dataset by name, or create a new one.

    Args:
        name: Dataset name.
        experiment_name: Optional experiment to link the dataset to.

    Returns:
        MLflow EvaluationDataset, or None if MLflow unavailable.
    """
    try:
        mlflow, create_dataset, search_datasets = _mlflow_api()
    except ImportError:
        print("MLflow not installed. Install with: pip install 'mlflow[genai]'",
              file=sys.stderr)
        return None

    if experiment_name:
        mlflow.set_experiment(experiment_name)

    experiment_id = None
    if experiment_name:
        experiment = mlflow.get_experiment_by_name(experiment_name)
        experiment_id = experiment.experiment_id if experiment else None

    # Search for existing dataset by name in the configured experiment.
    try:
        kwargs = {"experiment_ids": [experiment_id]} if experiment_id else {}
        results = search_datasets(**kwargs)
        for ds in results:
            if ds.name == name:
                return ds
    except Exception:
        pass

    # Create new dataset
    try:
        tags = {"source": f"git:{source_commit or _repository_commit()}"}
        kwargs = {"name": name, "tags": tags}
        if experiment_id:
            kwargs["experiment_id"] = experiment_id
        return create_dataset(**kwargs)
    except Exception as e:
        print(f"Failed to create dataset '{name}': {e}", file=sys.stderr)
        return None


def sync_records(
    dataset, records: list, source_commit: str | None = None
) -> int:
    """Merge records into an MLflow dataset.

    Args:
        dataset: MLflow EvaluationDataset.
        records: List of dicts with 'inputs' and optional 'expectations'.

    Returns:
        Number of records synced, or 0 on error.
    """
    if not dataset or not records:
        return 0
    native_records = prepare_records(records, source_commit)

    try:
        existing = dataset.to_df()
        by_case_id = {}
        if "tags" in existing.columns:
            for _, row in existing.iterrows():
                tags = row.get("tags") or {}
                case_id = tags.get("case_id") if isinstance(tags, dict) else None
                if case_id:
                    by_case_id[str(case_id)] = row

        to_merge = []
        delete_ids = []
        for record in native_records:
            case_id = record["tags"]["case_id"]
            current = by_case_id.get(case_id)
            if current is None:
                to_merge.append(record)
                continue
            def semantic_fields(value):
                return {
                    key: value.get(key)
                    for key in ("inputs", "expectations", "outputs")
                    if value.get(key) not in (None, {}, [])
                }

            current_tags = current.get("tags") or {}
            stable_tags = {
                key: current_tags.get(key) for key in ("case_id", "source")
            }
            record_stable_tags = {
                key: record["tags"].get(key) for key in ("case_id", "source")
            }
            if (semantic_fields(current) == semantic_fields(record)
                    and stable_tags == record_stable_tags):
                continue
            record_id = current.get("dataset_record_id")
            if record_id:
                delete_ids.append(record_id)
            to_merge.append(record)

        if delete_ids and hasattr(dataset, "delete_records"):
            dataset.delete_records(delete_ids)
        if to_merge:
            dataset.merge_records(to_merge)
        return len(to_merge)
    except Exception as e:
        print(f"Failed to sync records: {e}", file=sys.stderr)
        return 0
