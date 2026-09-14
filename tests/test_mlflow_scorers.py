"""Tests for the MLflow-native scorer adapter."""

from enum import Enum
from types import SimpleNamespace

import pytest

from agent_eval.config import EvalConfig, JudgeConfig
from agent_eval.mlflow.scorers import (
    normalize_feedback,
    resolve_scorer,
    score_with_mlflow_scorer,
)


def _config():
    return EvalConfig(name="test", skill="test")


def test_resolve_guidelines_passes_guidelines_and_model():
    judge = JudgeConfig(
        name="grounded",
        mlflow_scorer="Guidelines",
        model="gateway:/judge-model",
        arguments={"guidelines": "Stay grounded in the source."},
    )

    scorer = resolve_scorer(judge, _config())

    assert type(scorer).__name__ == "Guidelines"
    assert scorer.guidelines == "Stay grounded in the source."
    assert scorer.model == "gateway:/judge-model"


@pytest.mark.parametrize(
    ("value", "rationale", "metadata"),
    [
        (True, "The response follows the rule.", {"source": "native"}),
        (3.5, "The response is mostly complete.", {"scale": "1-5"}),
    ],
)
def test_normalize_feedback_preserves_value_rationale_and_metadata(
    value, rationale, metadata
):
    feedback = SimpleNamespace(
        value=value, rationale=rationale, metadata=metadata
    )

    assert normalize_feedback(feedback) == (value, rationale, metadata)


def test_normalize_feedback_converts_categorical_enum_to_yaml_safe_value():
    class CategoricalRating(str, Enum):
        YES = "yes"
        NO = "no"

    feedback = SimpleNamespace(
        value=CategoricalRating.YES, rationale="accepted", metadata={}
    )

    value, rationale, metadata = normalize_feedback(feedback)

    assert value == "yes"
    assert type(value) is str
    assert (rationale, metadata) == ("accepted", {})


def test_score_with_mlflow_scorer_converts_categorical_bool_feedback():
    class CategoricalRating(str, Enum):
        YES = "yes"
        NO = "no"

    class GuidelinesLikeScorer:
        def __call__(self, **kwargs):
            return SimpleNamespace(
                value=CategoricalRating.NO,
                rationale="rejected",
                metadata={},
            )

    value, rationale, metadata = score_with_mlflow_scorer(
        GuidelinesLikeScorer(), inputs={}, outputs={}, feedback_type="bool"
    )

    assert value is False
    assert (rationale, metadata) == ("rejected", {})


def test_score_with_mlflow_scorer_passes_available_case_data():
    calls = []

    class FakeScorer:
        def __call__(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                value=True, rationale="accepted", metadata={"kind": "fake"}
            )

    inputs = {"prompt": "hello"}
    outputs = {"answer": "world"}
    expectations = {"expected": "world"}
    trace = object()

    result = score_with_mlflow_scorer(
        FakeScorer(),
        inputs=inputs,
        outputs=outputs,
        expectations=expectations,
        trace=trace,
    )

    assert result == (True, "accepted", {"kind": "fake"})
    assert calls == [{
        "inputs": inputs,
        "outputs": outputs,
        "expectations": expectations,
        "trace": trace,
    }]


def test_score_with_mlflow_scorer_omits_unavailable_case_data():
    calls = []

    class FakeScorer:
        def __call__(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(value=2, rationale="ok", metadata=None)

    result = score_with_mlflow_scorer(
        FakeScorer(), inputs={"prompt": "hello"}, outputs={"answer": "world"}
    )

    assert result == (2, "ok", {})
    assert calls == [{
        "inputs": {"prompt": "hello"},
        "outputs": {"answer": "world"},
    }]


def test_score_with_mlflow_scorer_passes_only_required_output_columns():
    calls = []

    class OutputOnlyScorer:
        required_columns = {"inputs", "outputs"}

        def __call__(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(value=True, rationale="ok", metadata={})

    inputs = {"prompt": "hello"}
    outputs = {"answer.txt": "world"}

    score_with_mlflow_scorer(
        OutputOnlyScorer(),
        inputs=inputs,
        outputs=outputs,
        expectations={"expected": "world"},
        trace=object(),
    )

    assert calls == [{"inputs": inputs, "outputs": outputs}]


def test_score_with_mlflow_scorer_passes_declared_trace_without_expectations():
    calls = []

    class TraceAwareScorer:
        required_columns = {"inputs", "outputs", "trace"}

        def __call__(self, *, inputs, outputs, trace):
            calls.append({"inputs": inputs, "outputs": outputs, "trace": trace})
            return SimpleNamespace(value=True, rationale="ok", metadata={})

    inputs = {"prompt": "hello"}
    outputs = {"answer.txt": "world"}
    trace = object()

    score_with_mlflow_scorer(
        TraceAwareScorer(),
        inputs=inputs,
        outputs=outputs,
        expectations={"expected": "world"},
        trace=trace,
    )

    assert calls == [{"inputs": inputs, "outputs": outputs, "trace": trace}]


def test_score_with_mlflow_scorer_returns_structured_error():
    class FakeScorer:
        def __call__(self, **kwargs):
            raise RuntimeError("provider unavailable")

    value, rationale, metadata = score_with_mlflow_scorer(
        FakeScorer(), inputs={}, outputs={}
    )

    assert value is None
    assert "provider unavailable" in rationale
    assert metadata["error"] == "provider unavailable"
    assert metadata["exception_type"] == "RuntimeError"


def test_invalid_scorer_name_names_judge_and_required_package():
    judge = JudgeConfig(name="quality", mlflow_scorer="NotARealScorer")

    with pytest.raises(ValueError, match="Judge 'quality'.*mlflow"):
        resolve_scorer(judge, _config())
