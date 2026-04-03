"""Evaluation suite configuration loaded from eval.yaml files."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class OutputConfig:
    """One output artifact directory with a natural language schema."""
    path: str = ""
    schema: str = ""


@dataclass
class JudgeConfig:
    """Configuration for a single judge.

    Judge types (determined by which fields are set):
    - Inline check: `check` contains a Python snippet
    - LLM judge: `prompt` or `prompt_file` contains evaluation instructions
    - External code: `module` and `function` reference a Python callable
    """
    name: str = ""
    description: str = ""  # What this judge checks (context for LLM judges)
    # Inline code check (returns (bool, str))
    check: str = ""
    # LLM judge / pairwise
    prompt: str = ""
    prompt_file: str = ""
    context: list = field(default_factory=list)  # File paths loaded as supplementary context
    feedback_type: str = ""  # Optional: int, float, bool, str. Inferred if omitted.
    model: str = ""  # Override model for this judge (pairwise, LLM)
    # External code judge
    module: str = ""
    function: str = ""


@dataclass
class EvalConfig:
    """Complete evaluation suite configuration.

    Structure is schema-driven: dataset and output structures are described
    in natural language. The harness interprets these descriptions via LLM
    (once, cached) to drive prepare, collect, and score steps.
    """
    name: str = ""
    description: str = ""
    skill: str = ""
    runner: str = "claude-code"
    runner_options: dict = field(default_factory=dict)  # Runner-specific config
    permissions: dict = field(default_factory=dict)  # {"allow": [...], "deny": [...]}
    mlflow_experiment: str = ""

    # Dataset — natural language schema + path
    dataset_path: str = ""
    dataset_schema: str = ""

    # Outputs — list of artifact dirs with natural language schemas
    outputs: list = field(default_factory=list)

    # Judges (inline checks, LLM, pairwise, external code)
    judges: list = field(default_factory=list)

    # Regression thresholds
    thresholds: dict = field(default_factory=dict)

    # Runtime overrides (set by CLI or skill, not config file)
    model: str = ""
    subagent_model: str = ""
    run_id: str = ""
    baseline: str = ""

    @classmethod
    def from_yaml(cls, path: str | Path) -> "EvalConfig":
        """Load config from a YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {path}")

        with open(path) as f:
            raw = yaml.safe_load(f) or {}

        # Dataset
        dataset = raw.get("dataset", {})

        config = cls(
            name=raw.get("name", path.stem),
            description=raw.get("description", ""),
            skill=raw.get("skill", ""),
            runner=raw.get("runner", "claude-code"),
            runner_options=raw.get("runner_options", {}),
            permissions=raw.get("permissions", {}),
            mlflow_experiment=raw.get("mlflow_experiment", raw.get("name", "")),
            dataset_path=dataset.get("path", ""),
            dataset_schema=dataset.get("schema", ""),
        )

        # Outputs
        for o in raw.get("outputs", []):
            config.outputs.append(OutputConfig(
                path=o.get("path", ""),
                schema=o.get("schema", ""),
            ))

        # Judges
        for j in raw.get("judges", []):
            config.judges.append(JudgeConfig(
                name=j.get("name", ""),
                description=j.get("description", ""),
                check=j.get("check", ""),
                prompt=j.get("prompt", ""),
                prompt_file=j.get("prompt_file", ""),
                context=j.get("context", []),
                feedback_type=j.get("feedback_type", ""),
                model=j.get("model", ""),
                module=j.get("module", ""),
                function=j.get("function", ""),
            ))

        # Thresholds
        config.thresholds = raw.get("thresholds", {})

        return config

    @property
    def project_root(self) -> Path:
        """Project root (where eval.yaml lives)."""
        return Path.cwd()
