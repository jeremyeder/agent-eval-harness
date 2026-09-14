"""Focused integration tests for score.py judge loading and execution."""

import score
from agent_eval.config import EvalConfig, JudgeConfig


def test_mlflow_judge_loads_and_scores_through_adapter(monkeypatch, tmp_path):
    config = EvalConfig(name="test", skill="test")
    config.judges = [
        JudgeConfig(
            name="guidelines",
            mlflow_scorer="Guidelines",
            arguments={"guidelines": "Stay grounded."},
        )
    ]
    case_dir = tmp_path / "case-001"
    case_dir.mkdir()
    record = {
        "inputs": {"prompt": "Evaluate this."},
        "files": {"output.txt": "grounded output"},
        "annotations": {"expected": "grounded"},
        "trace": {"trace_id": "trace-001"},
    }
    monkeypatch.setattr(score, "load_case_record", lambda *args, **kwargs: record)

    resolved = object()
    resolve_calls = []
    score_calls = []

    def fake_resolve(judge, received_config):
        resolve_calls.append((judge, received_config))
        return resolved

    def fake_score(scorer, **kwargs):
        score_calls.append((scorer, kwargs))
        return True, "grounded", {"source": "fake"}

    monkeypatch.setattr("agent_eval.mlflow.scorers.resolve_scorer", fake_resolve)
    monkeypatch.setattr(
        "agent_eval.mlflow.scorers.score_with_mlflow_scorer", fake_score
    )

    judges = score.load_judges(config)
    assert len(judges) == 1
    assert judges[0][0] == "guidelines"
    assert judges[0][3] == "mlflow"
    assert resolve_calls == [(config.judges[0], config)]

    result = score.score_cases(judges, [case_dir], config)

    assert result["per_case"]["case-001"]["guidelines"] == {
        "value": True,
        "rationale": "grounded",
        "judge_type": "mlflow",
    }
    assert result["aggregated"]["guidelines"]["pass_rate"] == 1.0
    assert score_calls == [
        (
            resolved,
            {
                "inputs": record["inputs"],
                "outputs": record["files"],
                "expectations": record["annotations"],
                "trace": record["trace"],
                "feedback_type": "",
            },
        )
    ]


def test_mlflow_judge_uses_conversation_when_case_has_no_artifacts(
    monkeypatch, tmp_path
):
    config = EvalConfig(name="test", skill="test")
    config.judges = [JudgeConfig(name="guidelines", mlflow_scorer="Guidelines")]
    case_dir = tmp_path / "case-001"
    case_dir.mkdir()
    record = {
        "inputs": {"prompt": "Evaluate this."},
        "files": {},
        "conversation": "grounded response",
    }
    monkeypatch.setattr(score, "load_case_record", lambda *args, **kwargs: record)

    resolved = object()
    score_calls = []

    monkeypatch.setattr(
        "agent_eval.mlflow.scorers.resolve_scorer",
        lambda judge, received_config: resolved,
    )

    def fake_score(scorer, **kwargs):
        score_calls.append((scorer, kwargs))
        return True, "grounded", {}

    monkeypatch.setattr(
        "agent_eval.mlflow.scorers.score_with_mlflow_scorer", fake_score
    )

    judges = score.load_judges(config)
    score.score_cases(judges, [case_dir], config)

    assert score_calls == [
        (
            resolved,
            {
                "inputs": record["inputs"],
                "outputs": {"conversation": record["conversation"]},
                "expectations": {},
                "trace": None,
                "feedback_type": "",
            },
        )
    ]
