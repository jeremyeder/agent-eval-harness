"""MLflow trace search and extraction utilities."""

import sys
from collections.abc import Mapping
from typing import Optional

from agent_eval.mlflow.experiment import get_experiment_id


def _trace_field(trace, *names, default=None):
    """Read a trace field from either a DataFrame row or a trace object."""
    for name in names:
        if isinstance(trace, Mapping) and name in trace:
            return trace[name]
        if hasattr(trace, name):
            return getattr(trace, name)
    return default


def _trace_rows(traces):
    """Yield row-like values from MLflow's pandas and list result shapes."""
    try:
        import pandas as pd
    except ImportError:
        pd = None

    if pd is not None and isinstance(traces, pd.DataFrame):
        return traces.to_dict(orient="records")
    return traces


def _trace_scalar(value):
    """Unwrap MLflow enum-like metadata values for stable result dictionaries."""
    nested_value = getattr(value, "value", value)
    if nested_value is not value and isinstance(
        nested_value, (bool, int, float, str)
    ):
        return nested_value
    return value


def find_run_traces(experiment_name: str, run_id: str = "",
                    time_window_s: Optional[int] = None,
                    max_results: int = 100) -> list:
    """Find MLflow traces matching an eval run.

    Search strategy:
    1. Get experiment ID from name
    2. Search traces, optionally filtered by time window
    3. Return trace info dicts

    Args:
        experiment_name: MLflow experiment name.
        run_id: Eval run ID (for tag-based filtering).
        time_window_s: If set, only return traces from the last N seconds.
        max_results: Maximum traces to return.

    Returns:
        List of dicts with trace_id, timestamp, duration, status.
    """
    try:
        import mlflow
    except ImportError:
        return []

    exp_id = get_experiment_id(experiment_name)
    if not exp_id:
        return []

    try:
        traces = mlflow.search_traces(
            locations=[exp_id],
            max_results=max_results,
        )
    except Exception as e:
        print(f"Failed to search traces: {e}", file=sys.stderr)
        return []

    results = []
    for trace in _trace_rows(traces):
        info = trace.info if hasattr(trace, "info") else trace
        tags = _trace_field(info, "tags", default={})
        if run_id and isinstance(tags, Mapping):
            tagged_run_ids = {
                tags[name]
                for name in ("mlflow.runId", "agent_eval_run_id")
                if name in tags
            }
            if tagged_run_ids and run_id not in tagged_run_ids:
                continue
        trace_data = {
            "trace_id": _trace_field(info, "request_id", "trace_id", default=""),
            "timestamp": _trace_field(
                info, "timestamp_ms", "request_time", default=0
            ),
            "status": _trace_scalar(
                _trace_field(info, "status", "state", default="")
            ),
        }
        case_id = ""
        if isinstance(tags, Mapping):
            case_id = tags.get("case_id") or tags.get("eval_run_id", "")
            if case_id == run_id:
                case_id = ""
        if case_id:
            trace_data["case_id"] = case_id
        results.append(trace_data)

    return results


def extract_trace_inputs(traces, max_results: int = 10) -> list:
    """Extract root span inputs from traces for dataset generation.

    Args:
        traces: DataFrame or list of trace objects from mlflow.search_traces().
        max_results: Maximum inputs to extract.

    Returns:
        List of dicts with trace_id, eval_run_id, input_text, tool_interactions.
    """
    try:
        import pandas as pd
        is_df = isinstance(traces, pd.DataFrame)
    except ImportError:
        is_df = False

    if is_df:
        rows = [traces.iloc[i] for i in range(min(len(traces), max_results))]
    else:
        rows = traces[:max_results]

    results = []
    for trace in rows:
        try:
            input_text = ""
            tool_interactions = []
            eval_run_id = ""

            if is_df:
                trace_id = trace.get("trace_id", "")
                tags = trace.get("tags", {}) or {}
                eval_run_id = tags.get("eval_run_id", "") if isinstance(tags, dict) else ""
                request = trace.get("request", {})
                if isinstance(request, dict):
                    input_text = request.get("prompt", request.get("input", ""))
                spans = trace.get("spans", []) or []
                for span in spans:
                    name = span.get("name", "") if isinstance(span, dict) else getattr(span, "name", "")
                    if "AskUserQuestion" in name:
                        attrs = span.get("attributes", {}) if isinstance(span, dict) else {}
                        tool_interactions.append({
                            "tool": "AskUserQuestion",
                            "input": attrs,
                            "output": {},
                        })
            else:
                info = trace.info if hasattr(trace, "info") else trace
                trace_id = getattr(info, "request_id", getattr(info, "trace_id", ""))
                tags = getattr(info, "tags", {}) or {}
                eval_run_id = tags.get("eval_run_id", "") if isinstance(tags, dict) else ""
                data = trace.data if hasattr(trace, "data") else None
                if data and hasattr(data, "spans") and data.spans:
                    root = data.spans[0]
                    inputs = getattr(root, "inputs", {})
                    if isinstance(inputs, dict):
                        input_text = inputs.get("prompt", inputs.get("input", str(inputs)))
                    elif isinstance(inputs, str):
                        input_text = inputs
                    for span in data.spans[1:]:
                        span_name = getattr(span, "name", "")
                        if "AskUserQuestion" in span_name:
                            tool_interactions.append({
                                "tool": "AskUserQuestion",
                                "input": getattr(span, "inputs", {}),
                                "output": getattr(span, "outputs", {}),
                            })

            if input_text:
                entry = {
                    "trace_id": trace_id,
                    "input_text": input_text,
                    "tool_interactions": tool_interactions,
                }
                if eval_run_id:
                    entry["eval_run_id"] = eval_run_id
                results.append(entry)
        except Exception:
            continue

    return results
