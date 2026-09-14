"""Tests for native MLflow evaluation dataset synchronization."""

from types import SimpleNamespace
from pathlib import Path

import pandas as pd
import pytest

from agent_eval.mlflow import datasets

try:
    from sync_dataset import _extract_record
    _has_mlflow = True
except ModuleNotFoundError as exc:
    if exc.name != "mlflow":
        raise
    _has_mlflow = False
except SystemExit as exc:
    if exc.code not in (0, None):
        raise
    _has_mlflow = False


class FakeDataset:
    def __init__(self, records=None):
        self.records = list(records or [])
        self.merged = []
        self.deleted = []

    def to_df(self):
        return pd.DataFrame(self.records)

    def delete_records(self, record_ids):
        self.deleted.extend(record_ids)
        self.records = [
            record for record in self.records
            if record.get("dataset_record_id") not in record_ids
        ]
        return len(record_ids)

    def merge_records(self, records):
        self.merged.extend(records)
        self.records.extend(
            {**record, "dataset_record_id": f"record-{len(self.records)}"}
            for record in records
        )


def test_sync_records_preserves_inputs_expectations_and_stable_tags():
    dataset = FakeDataset()

    count = datasets.sync_records(
        dataset,
        [{
            "case_id": "local-only",
            "inputs": {"prompt": "inspect the skill"},
            "expectations": {"grounded": True},
        }],
        source_commit="abc123",
    )

    assert count == 1
    assert dataset.merged == [{
        "inputs": {"prompt": "inspect the skill"},
        "expectations": {"grounded": True},
        "tags": {"case_id": "local-only", "source": "git:abc123"},
    }]


def test_sync_records_is_idempotent_by_case_id():
    dataset = FakeDataset()
    record = {"case_id": "case-1", "inputs": {"prompt": "same"}}

    assert datasets.sync_records(dataset, [record], source_commit="abc123") == 1
    assert datasets.sync_records(dataset, [record], source_commit="abc123") == 0
    assert len(dataset.merged) == 1


def test_sync_records_replaces_changed_input_for_existing_case():
    dataset = FakeDataset()
    record = {"case_id": "case-1", "inputs": {"prompt": "old"}}
    datasets.sync_records(dataset, [record], source_commit="abc123")

    count = datasets.sync_records(
        dataset,
        [{"case_id": "case-1", "inputs": {"prompt": "new"}}],
        source_commit="def456",
    )

    assert count == 1
    assert dataset.deleted == ["record-0"]
    assert dataset.merged[-1]["tags"] == {
        "case_id": "case-1", "source": "git:def456"
    }


def test_sync_records_derives_stable_case_id_when_missing():
    first = datasets.prepare_records(
        [{"inputs": {"prompt": "same"}}], source_commit="abc123"
    )
    second = datasets.prepare_records(
        [{"inputs": {"prompt": "same"}}], source_commit="def456"
    )

    assert first[0]["tags"]["case_id"] == second[0]["tags"]["case_id"]


def test_get_or_create_dataset_attaches_new_dataset_to_experiment(monkeypatch):
    calls = []
    api = SimpleNamespace(
        set_experiment=lambda name: calls.append(("set_experiment", name)),
        get_experiment_by_name=lambda name: SimpleNamespace(experiment_id="7"),
    )
    create = lambda **kwargs: calls.append(("create", kwargs)) or "dataset"

    monkeypatch.setattr(datasets, "_mlflow_api", lambda: (api, create, lambda **_: []))

    assert datasets.get_or_create_dataset("eval", "experiment") == "dataset"
    assert ("create", {
        "name": "eval",
        "experiment_id": "7",
        "tags": {"source": "git:" + datasets._repository_commit()},
    }) in calls


@pytest.mark.skipif(not _has_mlflow, reason="mlflow not installed")
def test_extract_record_includes_case_directory_id(tmp_path: Path):
    case_dir = tmp_path / "case-from-directory"
    case_dir.mkdir()
    (case_dir / "input.yaml").write_text("prompt: inspect the skill\n")

    record = _extract_record(
        case_dir,
        {"prompt": "input.yaml:prompt"},
        {},
    )

    assert record == {
        "case_id": "case-from-directory",
        "inputs": {"prompt": "inspect the skill"},
        "expectations": {},
    }
