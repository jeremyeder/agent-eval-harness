"""Adapter for MLflow GenAI scorers used as harness judges."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from enum import Enum


def _load_native_scorers(judge_name: str):
    """Load MLflow's native scorer module without making MLflow mandatory."""
    try:
        from mlflow.genai import scorers
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            f"Judge '{judge_name}' requires the MLflow GenAI scorer package. "
            "Install it with `uv add 'mlflow[genai]'` (or install "
            "`mlflow[genai]`) before using MLflow scorers."
        ) from exc
    return scorers


def resolve_scorer(judge, config):
    """Return an MLflow scorer instance for a validated ``JudgeConfig``."""
    del config  # Reserved for registered scorer resolution in a later task.
    scorer_name = judge.mlflow_scorer.strip()
    scorers = _load_native_scorers(judge.name)

    # Guidelines is the first native scorer exposed by the harness contract.
    if scorer_name != "Guidelines":
        raise ValueError(
            f"Judge '{judge.name}' references unknown MLflow scorer "
            f"'{scorer_name}'. The required MLflow scorer package is "
            "`mlflow[genai]`; supported native scorers currently include "
            "'Guidelines'."
        )

    arguments = dict(judge.arguments or {})
    if "guidelines" not in arguments:
        raise ValueError(
            f"Judge '{judge.name}' using MLflow scorer 'Guidelines' must "
            "set arguments.guidelines."
        )
    if judge.model:
        arguments["model"] = judge.model

    try:
        return scorers.Guidelines(**arguments)
    except Exception as exc:
        raise ValueError(
            f"Judge '{judge.name}' could not construct MLflow scorer "
            f"'Guidelines': {exc}"
        ) from exc


def _yaml_safe_value(value):
    """Convert scalar-like scorer values to YAML/JSON-safe Python values."""
    if isinstance(value, Enum):
        return _yaml_safe_value(value.value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _yaml_safe_value(item())
        except (TypeError, ValueError):
            pass

    nested_value = getattr(value, "value", value)
    if nested_value is not value:
        return _yaml_safe_value(nested_value)
    return str(value)


def normalize_feedback(feedback) -> tuple[object, str, dict]:
    """Map an MLflow ``Feedback`` to value, rationale, and metadata."""
    required = ("value", "rationale", "metadata")
    missing = [name for name in required if not hasattr(feedback, name)]
    if missing:
        raise TypeError(
            "MLflow scorer must return mlflow.entities.Feedback with "
            f"{', '.join(required)}; missing {', '.join(missing)}."
        )

    metadata = feedback.metadata or {}
    if not isinstance(metadata, Mapping):
        raise TypeError(
            "MLflow Feedback.metadata must be a mapping when returned by "
            "an MLflow scorer."
        )
    return _yaml_safe_value(feedback.value), feedback.rationale or "", dict(metadata)


def _coerce_feedback_value(value, feedback_type):
    """Map MLflow categorical yes/no values to the harness bool contract."""
    if feedback_type != "bool" or isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"yes", "true"}:
            return True
        if normalized in {"no", "false"}:
            return False
    return value


def _available_kwargs(scorer, kwargs):
    """Avoid passing fields unsupported by a concrete native scorer."""
    try:
        parameters = inspect.signature(scorer).parameters
    except (TypeError, ValueError):
        return kwargs
    if any(p.kind == inspect.Parameter.VAR_KEYWORD
           for p in parameters.values()):
        return kwargs
    return {name: value for name, value in kwargs.items()
            if name in parameters}


def _required_kwargs(scorer, kwargs):
    """Select the case fields declared by an MLflow native scorer."""
    required_columns = getattr(scorer, "required_columns", None)
    if required_columns is None:
        return kwargs
    return {name: value for name, value in kwargs.items()
            if name in required_columns}


def score_with_mlflow_scorer(
    scorer,
    *,
    inputs: dict,
    outputs: dict,
    expectations: dict | None = None,
    trace=None,
    feedback_type: str | None = None,
) -> tuple[object, str, dict]:
    """Invoke a native scorer and normalize its MLflow ``Feedback`` result."""
    available = {
        name: value
        for name, value in {
            "inputs": inputs,
            "outputs": outputs,
            "expectations": expectations,
            "trace": trace,
        }.items()
        if value is not None
    }
    try:
        required = _required_kwargs(scorer, available)
        feedback = scorer(**_available_kwargs(scorer, required))
        value, rationale, metadata = normalize_feedback(feedback)
        return _coerce_feedback_value(value, feedback_type), rationale, metadata
    except Exception as exc:
        scorer_name = getattr(scorer, "name", type(scorer).__name__)
        message = f"MLflow scorer '{scorer_name}' failed: {exc}"
        return (
            None,
            message,
            {
                "error": str(exc),
                "exception_type": type(exc).__name__,
                "scorer": scorer_name,
            },
        )
