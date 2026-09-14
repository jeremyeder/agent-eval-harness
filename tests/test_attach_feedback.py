"""Tests for attach_feedback.py trace availability handling."""

from types import SimpleNamespace

import pytest

try:
    from attach_feedback import _get_trace_with_retry, _push_feedback
    import attach_feedback
    _has_mlflow = True
except ModuleNotFoundError as exc:
    if exc.name != "mlflow":
        raise
    _has_mlflow = False
except SystemExit as exc:
    if exc.code not in (0, None):
        raise
    _has_mlflow = False


@pytest.mark.skipif(not _has_mlflow, reason="mlflow not installed")
def test_get_trace_with_retry_retries_until_trace_is_available(monkeypatch):
    calls = []
    responses = [RuntimeError("indexing"), SimpleNamespace(info="trace")]

    def get_trace(trace_id):
        calls.append(trace_id)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(attach_feedback.mlflow, "get_trace", get_trace)
    monkeypatch.setattr(attach_feedback.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(attach_feedback.time, "sleep", lambda _: None)

    assert _get_trace_with_retry("trace-1", retry_interval=0.01, timeout=1) \
        == SimpleNamespace(info="trace")
    assert calls == ["trace-1", "trace-1"]


@pytest.mark.skipif(not _has_mlflow, reason="mlflow not installed")
def test_get_trace_with_retry_returns_none_after_bounded_timeout(monkeypatch):
    calls = []
    now = iter((0.0, 0.0, 1.0))

    monkeypatch.setattr(
        attach_feedback.mlflow,
        "get_trace",
        lambda trace_id: (calls.append(trace_id),
                          (_ for _ in ()).throw(RuntimeError("missing")))[1],
    )
    monkeypatch.setattr(attach_feedback.time, "monotonic", lambda: next(now))
    monkeypatch.setattr(attach_feedback.time, "sleep", lambda _: None)

    assert _get_trace_with_retry("trace-2", retry_interval=0.01, timeout=0.5) is None
    assert calls == ["trace-2", "trace-2"]


@pytest.mark.skipif(not _has_mlflow, reason="mlflow not installed")
def test_push_feedback_skips_unavailable_trace_without_aborting(tmp_path, monkeypatch,
                                                                capsys):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "summary.yaml").write_text(
        "per_case:\n  case-1:\n    quality:\n      value: 1\n"
    )
    monkeypatch.setattr(attach_feedback, "find_run_traces",
                        lambda *_: [{"trace_id": "trace-1"}])
    monkeypatch.setattr(attach_feedback, "_get_trace_with_retry",
                        lambda *_: None)
    args = SimpleNamespace(trace_id=None, source="judge", run_id="run-1")

    _push_feedback(run_dir, "experiment", SimpleNamespace(), args)

    output = capsys.readouterr()
    assert "unavailable" in output.err
    assert "FEEDBACK: 0 entries" in output.out


@pytest.mark.skipif(not _has_mlflow, reason="mlflow not installed")
def test_push_feedback_routes_each_case_to_its_matching_trace(
    tmp_path, monkeypatch
):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "summary.yaml").write_text(
        "per_case:\n"
        "  case-1:\n"
        "    quality:\n"
        "      value: true\n"
        "  case-2:\n"
        "    quality:\n"
        "      value: false\n"
    )
    monkeypatch.setattr(
        attach_feedback,
        "find_run_traces",
        lambda *_: [
            {"trace_id": "trace-1", "case_id": "case-1"},
            {"trace_id": "trace-2", "case_id": "case-2"},
        ],
    )
    monkeypatch.setattr(
        attach_feedback, "_get_trace_with_retry", lambda trace_id: object()
    )
    feedback = []
    monkeypatch.setattr(
        attach_feedback,
        "log_feedback",
        lambda **kwargs: feedback.append(kwargs),
    )
    args = SimpleNamespace(trace_id=None, source="judge", run_id="run-1")

    _push_feedback(run_dir, "experiment", SimpleNamespace(), args)

    assert [(item["trace_id"], item["name"], item["value"])
            for item in feedback] == [
                ("trace-1", "case-1/quality", True),
                ("trace-2", "case-2/quality", False),
            ]
