"""Tests for log_results.py helpers."""

from types import SimpleNamespace

import pytest

try:
    from log_results import _is_within, _safe_trajectory_path
    from log_results import (
        _build_per_case_rows,
        _flush_trace_exports,
        _link_traces_to_run,
        _log_dataset_input,
        _load_case_input_text,
        _trace_has_complete_io,
    )
    _has_mlflow = True
except ModuleNotFoundError as exc:
    # Skip only when mlflow itself is missing; re-raise unrelated import errors
    # so path-safety regressions are never silently skipped.
    if exc.name != "mlflow":
        raise
    _has_mlflow = False
except SystemExit as exc:
    # log_results.py calls sys.exit(0) when mlflow is missing at import time.
    if exc.code not in (0, None):
        raise
    _has_mlflow = False


@pytest.mark.skipif(not _has_mlflow, reason="mlflow not installed")
class TestSafeTrajectoryPath:
    def test_accepts_real_file_under_job_root(self, tmp_path):
        """A regular trajectory.json alongside the transcript is accepted."""
        job_root = tmp_path / "job"
        step_dir = job_root / "case__abc" / "agent"
        step_dir.mkdir(parents=True)
        transcript = step_dir / "claude-code.txt"
        transcript.write_text("{}\n")
        traj = step_dir / "trajectory.json"
        traj.write_text("{}")

        result = _safe_trajectory_path(transcript, job_root)
        assert result == traj

    def test_missing_trajectory_returns_none(self, tmp_path):
        """No trajectory.json present -> None, no error."""
        job_root = tmp_path / "job"
        step_dir = job_root / "case__abc" / "agent"
        step_dir.mkdir(parents=True)
        transcript = step_dir / "claude-code.txt"
        transcript.write_text("{}\n")

        assert _safe_trajectory_path(transcript, job_root) is None

    def test_rejects_symlinked_trajectory(self, tmp_path):
        """A trajectory.json symlink pointing outside job_root is rejected."""
        job_root = tmp_path / "job"
        step_dir = job_root / "case__abc" / "agent"
        step_dir.mkdir(parents=True)
        transcript = step_dir / "claude-code.txt"
        transcript.write_text("{}\n")

        secret = tmp_path / "outside" / "secret.json"
        secret.parent.mkdir(parents=True)
        secret.write_text('{"leaked": true}')
        traj = step_dir / "trajectory.json"
        traj.symlink_to(secret)

        assert _safe_trajectory_path(transcript, job_root) is None

    def test_rejects_symlink_even_when_target_is_inside_root(self, tmp_path):
        """Symlinks are rejected outright, regardless of where they point."""
        job_root = tmp_path / "job"
        step_dir = job_root / "case__abc" / "agent"
        step_dir.mkdir(parents=True)
        transcript = step_dir / "claude-code.txt"
        transcript.write_text("{}\n")

        real = job_root / "real_trajectory.json"
        real.write_text("{}")
        traj = step_dir / "trajectory.json"
        traj.symlink_to(real)

        assert _safe_trajectory_path(transcript, job_root) is None


@pytest.mark.skipif(not _has_mlflow, reason="mlflow not installed")
class TestIsWithin:
    def test_descendant_path_is_within(self, tmp_path):
        root = tmp_path / "root"
        child = root / "a" / "b.txt"
        child.parent.mkdir(parents=True)
        child.write_text("x")
        assert _is_within(child, root) is True

    def test_escaping_path_is_not_within(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("x")
        assert _is_within(outside, root) is False

    def test_nonexistent_path_is_not_within(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        assert _is_within(root / "missing.txt", root) is False


@pytest.mark.skipif(not _has_mlflow, reason="mlflow not installed")
def test_build_per_case_rows_includes_judge_values_rationales_and_trace_links():
    rows = _build_per_case_rows(
        {
            "case-1": {
                "grounded": {"value": True, "rationale": "uses the source"},
                "quality": {"value": 0.75, "rationale": "mostly clear"},
            }
        },
        {"case-1": "trace-1"},
    )

    assert rows == [
        {
            "case_id": "case-1",
            "judge": "grounded",
            "value": True,
            "rationale": "uses the source",
            "trace_id": "trace-1",
        },
        {
            "case_id": "case-1",
            "judge": "quality",
            "value": 0.75,
            "rationale": "mostly clear",
            "trace_id": "trace-1",
        },
    ]


@pytest.mark.skipif(not _has_mlflow, reason="mlflow not installed")
def test_build_per_case_rows_uses_only_same_case_harbor_traces():
    rows = _build_per_case_rows(
        {
            "case-1": {"quality": {"value": 0.5}},
            "case-2": {"quality": {"value": 1.0}},
            "case-3": {"quality": {"value": 0.0}},
        },
        {"case-2": "direct-case-2"},
        main_trace_id="main-trace",
        harbor_step_traces={
            "case-1": {
                "second": "case-1-second",
                "first": "case-1-first",
            },
            "case-2": {"first": "case-2-first"},
        },
    )

    assert [row["trace_id"] for row in rows] == [
        "case-1-first",
        "direct-case-2",
        None,
    ]


@pytest.mark.skipif(not _has_mlflow, reason="mlflow not installed")
def test_log_dataset_input_passes_native_wrapper_to_mlflow(monkeypatch):
    calls = []
    monkeypatch.setattr(
        __import__("log_results").mlflow,
        "log_input",
        lambda dataset, context, tags=None: calls.append((dataset, context, tags)),
    )

    dataset = SimpleNamespace(_to_mlflow_entity=lambda: "dataset-entity")
    _log_dataset_input(dataset, "eval-dataset")

    assert len(calls) == 1
    logged_dataset, context, tags = calls[0]
    assert logged_dataset is dataset
    assert context == "evaluation"
    assert tags == {"dataset_name": "eval-dataset"}


@pytest.mark.skipif(not _has_mlflow, reason="mlflow not installed")
def test_log_dataset_input_passes_dataset_object_when_entity_converter_missing(
    monkeypatch,
):
    calls = []
    module = __import__("log_results")
    monkeypatch.setattr(
        module.mlflow,
        "log_input",
        lambda dataset, context, tags=None: calls.append((dataset, context, tags)),
    )
    dataset = SimpleNamespace(name="eval-dataset")

    module._log_dataset_input(dataset, "eval-dataset")

    assert calls == [(dataset, "evaluation", {"dataset_name": "eval-dataset"})]


@pytest.mark.skipif(not _has_mlflow, reason="mlflow not installed")
def test_link_traces_to_run_writes_mlflow_and_harness_run_tags():
    calls = []
    client = SimpleNamespace(
        link_traces_to_run=lambda **kwargs: calls.append(("link", kwargs)),
        set_trace_tag=lambda *args: calls.append(("tag", args)),
    )

    _link_traces_to_run(client, "mlflow-run", "harness-run", ["trace-1"])

    assert calls == [
        (
            "link",
            {"run_id": "mlflow-run", "trace_ids": ["trace-1"]},
        ),
        ("tag", ("trace-1", "mlflow.runId", "mlflow-run")),
        ("tag", ("trace-1", "agent_eval_run_id", "harness-run")),
    ]


@pytest.mark.skipif(not _has_mlflow, reason="mlflow not installed")
def test_flush_trace_exports_uses_public_mlflow_api(monkeypatch):
    calls = []
    module = __import__("log_results")
    monkeypatch.setattr(
        module.mlflow,
        "flush_trace_async_logging",
        lambda: calls.append("flushed"),
        raising=False,
    )

    _flush_trace_exports()

    assert calls == ["flushed"]


@pytest.mark.skipif(not _has_mlflow, reason="mlflow not installed")
def test_load_case_input_text_prefers_prompt(tmp_path):
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "input.yaml").write_text(
        "prompt: |\n  Analyze this skill.\ninput: ignored\n"
    )

    assert _load_case_input_text(case_dir) == "Analyze this skill."


@pytest.mark.skipif(not _has_mlflow, reason="mlflow not installed")
def test_trace_has_complete_io_rejects_empty_preview():
    complete = SimpleNamespace(
        info=SimpleNamespace(request_preview="prompt", response_preview="answer")
    )
    incomplete = SimpleNamespace(
        info=SimpleNamespace(request_preview="", response_preview="")
    )

    assert _trace_has_complete_io(complete) is True
    assert _trace_has_complete_io(incomplete) is False
