"""Validation tests for the standard eval-analyze self-evaluation suite."""

from pathlib import Path
import shutil
import subprocess
import sys

import yaml

from agent_eval.config import EvalConfig
from workspace_files import _copy_input_files


REPO_ROOT = Path(__file__).parents[1]
SUITE_ROOT = REPO_ROOT / "eval" / "eval-analyze"
CONFIG_PATH = SUITE_ROOT / "eval.yaml"
CASE_NAMES = {"external-state", "local-only", "nested-skill"}


def _load_config():
    return yaml.safe_load(CONFIG_PATH.read_text())


def test_eval_analyze_suite_has_three_source_backed_cases():
    cases_root = SUITE_ROOT / "cases"

    assert {case.name for case in cases_root.iterdir() if case.is_dir()} == CASE_NAMES
    assert all((cases_root / name / "input.yaml").is_file() for name in CASE_NAMES)

    config = _load_config()
    assert config["dataset"]["path"] == "cases"
    assert "[EXTERNAL: Jira]" in config["dataset"]["schema"]

    inputs = {
        name: yaml.safe_load((cases_root / name / "input.yaml").read_text())
        for name in CASE_NAMES
    }
    assert all(input_data["prompt"] for input_data in inputs.values())
    assert all(input_data["source_files"] for input_data in inputs.values())


def test_eval_analyze_suite_passes_normal_validator():
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "skills/eval-analyze/scripts/validate_eval.py"),
            "config",
            str(CONFIG_PATH),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_eval_analyze_case_workspaces_materialize_only_their_declared_sources(tmp_path):
    config = EvalConfig.from_yaml(CONFIG_PATH)
    cases_root = SUITE_ROOT / "cases"
    expected_sources = {
        "external-state": {
            "target/external-state/fake-jira-skill/SKILL.md",
        },
        "local-only": {
            "eval-setup/SKILL.md",
            "eval-setup/scripts/check_env.py",
        },
        "nested-skill": {
            "eval-optimize/SKILL.md",
            "eval-run/SKILL.md",
        },
    }

    for case_name, expected in expected_sources.items():
        case_workspace = tmp_path / case_name
        case_workspace.mkdir()
        shutil.copy2(
            cases_root / case_name / "input.yaml",
            case_workspace / "input.yaml",
        )
        _copy_input_files(cases_root / case_name, case_workspace, config)

        materialized = {
            path.relative_to(case_workspace).as_posix()
            for path in case_workspace.rglob("*")
            if path.is_file()
        }
        assert materialized == expected | {"input.yaml"}


def test_eval_analyze_suite_uses_codex_and_one_mlflow_guidelines_judge():
    config = _load_config()

    assert config["execution"]["skill"] == "eval-analyze"
    assert config["runner"]["type"] == "codex"
    assert config["runner"]["plugin_dirs"] == ["."]

    judges = config["judges"]
    assert len(judges) == 1
    judge = judges[0]
    assert judge["name"] == "mlflow_guidelines"
    assert judge["mlflow_scorer"] == "Guidelines"
    assert judge["model"] == "gateway:/jeder-codex-endpoint"
    assert judge["feedback_type"] == "bool"
    guidelines = judge["arguments"]["guidelines"]
    assert "faithful to the analyzed skill" in guidelines
    assert "actually read" in guidelines
    assert "generic safety or fixture policies" in guidelines

    assert not any(
        key in judge
        for key in ("builtin", "check", "prompt", "prompt_file", "llm_rubric")
    )
