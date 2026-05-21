"""Tests for multi-phase evaluation config parsing."""

import tempfile
from pathlib import Path

import yaml
import pytest

from agent_eval.config import (
    EvalConfig, PhaseConfig, VariantConfig, AnalysisCommand,
)


def _write_yaml(data):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    yaml.dump(data, f)
    f.close()
    return f.name


class TestPhaseParsing:
    def test_no_phases_backward_compat(self):
        path = _write_yaml({"name": "test", "skill": "my-skill"})
        c = EvalConfig.from_yaml(path)
        assert c.phases == []
        assert c.variants == []
        Path(path).unlink()

    def test_phases_parsed(self):
        path = _write_yaml({
            "name": "test",
            "phases": [
                {"name": "planning", "skill": "plan-skill", "arguments": "{prompt}",
                 "outputs": [{"path": "output", "schema": "plan"}],
                 "judges": [{"name": "quality", "check": "(True, 'ok')"}],
                 "build_analysis": [{"name": "loc", "command": "wc -l"}]},
                {"name": "building", "skill": "build-skill", "arguments": "{plan_content}",
                 "outputs": [{"path": "output", "schema": "code"}]},
            ],
        })
        c = EvalConfig.from_yaml(path)
        assert len(c.phases) == 2
        assert c.phases[0].name == "planning"
        assert c.phases[0].skill == "plan-skill"
        assert len(c.phases[0].outputs) == 1
        assert c.phases[0].outputs[0].path == "output"
        assert len(c.phases[0].judges) == 1
        assert c.phases[0].judges[0].name == "quality"
        assert len(c.phases[0].build_analysis) == 1
        assert c.phases[0].build_analysis[0].name == "loc"
        assert c.phases[1].name == "building"
        assert c.phases[1].build_analysis == []
        Path(path).unlink()

    def test_phase_with_runner_override(self):
        path = _write_yaml({
            "name": "test",
            "phases": [
                {"name": "planning", "skill": "",
                 "runner": {"system_prompt": "Plan only, no code"}},
            ],
        })
        c = EvalConfig.from_yaml(path)
        assert c.phases[0].runner is not None
        assert c.phases[0].runner.system_prompt == "Plan only, no code"
        Path(path).unlink()


class TestVariantParsing:
    def test_variants_parsed(self):
        path = _write_yaml({
            "name": "test",
            "phases": [{"name": "planning", "skill": ""}],
            "variants": [
                {"name": "ce-plan",
                 "phases": {"planning": {"skill": "ce-plan"}}},
                {"name": "speckit",
                 "phases": {"planning": {"skill": "writing-plans"}}},
            ],
        })
        c = EvalConfig.from_yaml(path)
        assert len(c.variants) == 2
        assert c.variants[0].name == "ce-plan"
        assert c.variants[0].phases["planning"]["skill"] == "ce-plan"
        Path(path).unlink()


class TestResolvePhase:
    def _make_config(self):
        return _write_yaml({
            "name": "test",
            "phases": [
                {"name": "planning", "skill": "default-planner",
                 "arguments": "{prompt}",
                 "judges": [{"name": "quality", "check": "(True, 'ok')"}],
                 "build_analysis": [{"name": "loc", "command": "wc -l"}]},
                {"name": "building", "skill": "default-builder",
                 "arguments": "{plan_content}"},
            ],
            "variants": [
                {"name": "ce-plan",
                 "phases": {
                     "planning": {"skill": "ce-plan"},
                     "building": {"skill": "ce-work"},
                 }},
                {"name": "plan-mode",
                 "phases": {
                     "planning": {"skill": "",
                                  "runner": {"system_prompt": "Plan only"}},
                 }},
            ],
        })

    def test_resolve_without_variant(self):
        path = self._make_config()
        c = EvalConfig.from_yaml(path)
        p = c.resolve_phase("planning")
        assert p.skill == "default-planner"
        assert p.arguments == "{prompt}"
        Path(path).unlink()

    def test_resolve_with_variant_overrides_skill(self):
        path = self._make_config()
        c = EvalConfig.from_yaml(path)
        p = c.resolve_phase("planning", "ce-plan")
        assert p.skill == "ce-plan"
        assert p.arguments == "{prompt}"  # Not overridden
        assert len(p.judges) == 1  # Inherited from base
        assert len(p.build_analysis) == 1  # Inherited from base
        Path(path).unlink()

    def test_resolve_with_runner_override(self):
        path = self._make_config()
        c = EvalConfig.from_yaml(path)
        p = c.resolve_phase("planning", "plan-mode")
        assert p.skill == ""
        assert p.runner is not None
        assert p.runner.system_prompt == "Plan only"
        Path(path).unlink()

    def test_resolve_nonexistent_phase(self):
        path = self._make_config()
        c = EvalConfig.from_yaml(path)
        assert c.resolve_phase("nonexistent") is None
        Path(path).unlink()

    def test_resolve_nonexistent_variant(self):
        path = self._make_config()
        c = EvalConfig.from_yaml(path)
        p = c.resolve_phase("planning", "nonexistent")
        assert p.skill == "default-planner"  # Falls back to base
        Path(path).unlink()


class TestAnalysisCommand:
    def test_dataclass_defaults(self):
        cmd = AnalysisCommand()
        assert cmd.name == ""
        assert cmd.command == ""

    def test_dataclass_values(self):
        cmd = AnalysisCommand(name="loc", command="wc -l *.py")
        assert cmd.name == "loc"
        assert cmd.command == "wc -l *.py"
