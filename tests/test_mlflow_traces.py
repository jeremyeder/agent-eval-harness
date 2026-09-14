"""Regression tests for MLflow trace search result compatibility."""

from enum import Enum
from types import SimpleNamespace

import pandas as pd

from agent_eval.mlflow import traces


def test_find_run_traces_normalizes_mlflow_dataframe_and_trace_list_shapes(
    monkeypatch,
):
    dataframe = pd.DataFrame(
        [
            {
                "trace_id": "trace-1",
                "request_time": 1_700_000_000_000,
                "state": "OK",
            }
        ]
    )
    trace_list = [
        SimpleNamespace(
            info=SimpleNamespace(
                trace_id="trace-1",
                request_time=1_700_000_000_000,
                state=TraceState.OK,
            )
        )
    ]

    monkeypatch.setattr(traces, "get_experiment_id", lambda _: "experiment-1")
    monkeypatch.setitem(
        __import__("sys").modules,
        "mlflow",
        SimpleNamespace(search_traces=lambda **_: dataframe),
    )
    dataframe_result = traces.find_run_traces("eval")

    monkeypatch.setitem(
        __import__("sys").modules,
        "mlflow",
        SimpleNamespace(search_traces=lambda **_: trace_list),
    )
    list_result = traces.find_run_traces("eval")

    assert dataframe_result == list_result == [
        {
            "trace_id": "trace-1",
            "timestamp": 1_700_000_000_000,
            "status": "OK",
        }
    ]


def test_find_run_traces_uses_locations_for_experiment_scope(monkeypatch):
    calls = []

    def search_traces(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(traces, "get_experiment_id", lambda _: "experiment-1")
    monkeypatch.setitem(
        __import__("sys").modules,
        "mlflow",
        SimpleNamespace(search_traces=search_traces),
    )

    assert traces.find_run_traces("eval") == []
    assert calls == [{"locations": ["experiment-1"], "max_results": 100}]


def test_find_run_traces_filters_mismatched_run_tags_but_keeps_untagged_rows(
    monkeypatch,
):
    dataframe = pd.DataFrame(
        [
            {
                "trace_id": "current",
                "request_time": 1,
                "state": "OK",
                "tags": {"mlflow.runId": "run-current"},
            },
            {
                "trace_id": "harness-tagged",
                "request_time": 4,
                "state": "OK",
                "tags": {"agent_eval_run_id": "run-current"},
            },
            {
                "trace_id": "historical",
                "request_time": 2,
                "state": "OK",
                "tags": {"mlflow.runId": "run-historical"},
            },
            {
                "trace_id": "mismatched-harness-tag",
                "request_time": 5,
                "state": "OK",
                "tags": {"agent_eval_run_id": "run-historical"},
            },
            {"trace_id": "legacy", "request_time": 3, "state": "OK"},
        ]
    )

    monkeypatch.setattr(traces, "get_experiment_id", lambda _: "experiment-1")
    monkeypatch.setitem(
        __import__("sys").modules,
        "mlflow",
        SimpleNamespace(search_traces=lambda **_: dataframe),
    )

    assert traces.find_run_traces("eval", run_id="run-current") == [
        {"trace_id": "current", "timestamp": 1, "status": "OK"},
        {"trace_id": "harness-tagged", "timestamp": 4, "status": "OK"},
        {"trace_id": "legacy", "timestamp": 3, "status": "OK"},
    ]


class TraceState(Enum):
    OK = "OK"
