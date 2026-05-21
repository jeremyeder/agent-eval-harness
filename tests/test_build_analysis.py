"""Tests for build analysis command execution."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agent_eval.config import AnalysisCommand


def _run_build_analysis(workspace, analysis_commands, output_dir):
    """Extracted build analysis logic for testability."""
    metrics = {}
    for cmd in analysis_commands:
        try:
            result = subprocess.run(
                cmd.command, shell=True, cwd=str(workspace),
                capture_output=True, text=True, timeout=120,
            )
            metrics[cmd.name] = (
                result.stdout.strip().split("\n")[-1]
                if result.stdout.strip() else ""
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            metrics[cmd.name] = f"error: {e}"
    if metrics:
        with open(output_dir / "build_metrics.json", "w") as f:
            json.dump(metrics, f, indent=2)
            f.write("\n")
    return metrics


class TestRunBuildAnalysis:
    def test_runs_commands_in_workspace(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        (workspace / "main.py").write_text("print('hello')\n")
        (workspace / "utils.py").write_text("def helper():\n    pass\n")

        commands = [
            AnalysisCommand(name="file_count", command="ls *.py | wc -l"),
            AnalysisCommand(name="total_lines", command="wc -l *.py | tail -1"),
        ]

        metrics = _run_build_analysis(workspace, commands, output_dir)

        assert "file_count" in metrics
        assert "total_lines" in metrics

        bm_path = output_dir / "build_metrics.json"
        assert bm_path.exists()
        with open(bm_path) as f:
            saved = json.load(f)
        assert saved == metrics

    def test_handles_command_failure(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        commands = [
            AnalysisCommand(
                name="missing_tool",
                command="nonexistent_command_xyz 2>/dev/null",
            ),
        ]

        metrics = _run_build_analysis(workspace, commands, output_dir)
        assert "missing_tool" in metrics
        assert isinstance(metrics["missing_tool"], str)

    def test_empty_commands_no_file(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        metrics = _run_build_analysis(workspace, [], output_dir)
        assert metrics == {}
        assert not (output_dir / "build_metrics.json").exists()
