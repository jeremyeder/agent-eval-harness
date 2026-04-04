#!/usr/bin/env python3
"""Orchestrate the full evaluation matrix.

Reads test_plan.yaml and eval.yaml. For each (model, case, rep) combination,
creates an isolated workspace, executes the speedrun skill, collects artifacts,
and runs scoring judges.

Usage:
    python3 eval/scripts/run_matrix.py [--plan eval/test_plan.yaml] [--config eval.yaml]

Single-run test:
    python3 eval/scripts/run_matrix.py --plan eval/test_plan.yaml --single
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import re

import yaml

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_id(value: str, label: str):
    """Validate that an ID contains only safe characters."""
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"Invalid {label}: {value!r} (must match [A-Za-z0-9._-]+)")


def load_test_plan(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def make_run_id(model_name: str, case_id: str, rep: int) -> str:
    _validate_id(model_name, "model name")
    _validate_id(case_id, "case ID")
    return f"{model_name}-{case_id}-rep{rep}"


def run_one(
    run_id: str,
    model_cfg: dict,
    case_id: str,
    config_path: str,
    execution: dict,
    project_root: Path,
    harness_scripts: Path,
) -> dict:
    """Execute one (model, case, rep) run. Returns run metadata."""
    print(f"\n{'='*60}")
    print(f"RUN: {run_id}")
    print(f"  Model: {model_cfg['model_id']} | Case: {case_id}")
    print(f"{'='*60}")

    output_dir = project_root / "eval" / "runs" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Create workspace
    print(f"  [1/4] Creating workspace...")
    ws_result = subprocess.run(
        [
            sys.executable,
            str(harness_scripts / "workspace.py"),
            "--config", config_path,
            "--run-id", run_id,
            "--case-filter", case_id,
        ],
        capture_output=True, text=True, cwd=str(project_root),
    )
    if ws_result.returncode != 0:
        print(f"  ERROR: workspace creation failed: {ws_result.stderr}")
        _save_error(output_dir, run_id, "workspace_failed", ws_result.stderr)
        return {"run_id": run_id, "status": "error", "phase": "workspace"}

    workspace = None
    for line in ws_result.stdout.splitlines():
        if line.startswith("WORKSPACE:"):
            workspace = line.split(":", 1)[1].strip()
    if not workspace:
        print(f"  ERROR: no workspace path in output")
        _save_error(output_dir, run_id, "workspace_missing", ws_result.stdout)
        return {"run_id": run_id, "status": "error", "phase": "workspace"}

    print(f"  Workspace: {workspace}")

    # Step 2: Execute skill
    print(f"  [2/4] Executing skill...")
    flags = "--headless --dry-run"
    skill_args = f"{case_id} {flags}"

    env = os.environ.copy()
    env["CLAUDE_CODE_SUBAGENT_MODEL"] = model_cfg.get("subagent_model", model_cfg["model_id"])

    exec_result = subprocess.run(
        [
            sys.executable,
            str(harness_scripts / "execute.py"),
            "--workspace", workspace,
            "--skill", "rfe.speedrun",
            "--skill-args", skill_args,
            "--model", model_cfg["model_id"],
            "--output", str(output_dir),
            "--config", config_path,
            "--subagent-model", model_cfg.get("subagent_model", model_cfg["model_id"]),
            "--max-budget", str(execution.get("max_budget_usd", 10.0)),
            "--timeout", str(execution.get("timeout_s", 1800)),
        ],
        capture_output=True, text=True, cwd=str(project_root), env=env,
    )

    # Log execution output regardless of exit code
    if exec_result.stdout:
        print(f"  Execute stdout (last 5 lines):")
        for line in exec_result.stdout.strip().splitlines()[-5:]:
            print(f"    {line}")
    if exec_result.returncode != 0:
        print(f"  WARNING: execution exited with code {exec_result.returncode}")

    # Step 3: Collect artifacts
    print(f"  [3/4] Collecting artifacts...")
    coll_result = subprocess.run(
        [
            sys.executable,
            str(harness_scripts / "collect.py"),
            "--config", config_path,
            "--workspace", workspace,
            "--output", str(output_dir),
        ],
        capture_output=True, text=True, cwd=str(project_root),
    )
    if coll_result.returncode != 0:
        print(f"  WARNING: collection failed: {coll_result.stderr}")

    # Step 4: Score
    print(f"  [4/4] Running judges...")
    score_result = subprocess.run(
        [
            sys.executable,
            str(harness_scripts / "score.py"),
            "judges",
            "--run-id", run_id,
            "--config", config_path,
        ],
        capture_output=True, text=True, cwd=str(project_root),
    )
    if score_result.stdout:
        for line in score_result.stdout.strip().splitlines():
            print(f"    {line}")
    if score_result.returncode != 0:
        print(f"  WARNING: scoring failed: {score_result.stderr}")

    # Load run_result.json for metadata
    run_result_path = output_dir / "run_result.json"
    run_meta = {"run_id": run_id, "status": "completed"}
    if run_result_path.exists():
        with open(run_result_path) as f:
            run_meta.update(json.load(f))

    run_meta["model"] = model_cfg["name"]
    run_meta["model_id"] = model_cfg["model_id"]
    run_meta["case_id"] = case_id

    print(f"  Status: {run_meta.get('status', 'unknown')} | "
          f"Exit: {run_meta.get('exit_code', '?')} | "
          f"Cost: ${run_meta.get('cost_usd', 0) or 0:.2f}")

    return run_meta


def _save_error(output_dir: Path, run_id: str, phase: str, detail: str):
    """Save an error result when a phase fails."""
    with open(output_dir / "run_result.json", "w") as f:
        json.dump({
            "run_id": run_id,
            "exit_code": -1,
            "duration_s": 0,
            "token_usage": None,
            "cost_usd": None,
            "error": f"{phase}: {detail[:500]}",
        }, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", default=None,
                        help="Path to test_plan.yaml (default: eval/test_plan.yaml in harness repo)")
    parser.add_argument("--config", default=None,
                        help="Path to eval.yaml (default: eval.yaml in harness repo)")
    parser.add_argument("--skill-project", default=None,
                        help="Path to the skill project (rfe-creator) to use as cwd for runs")
    parser.add_argument("--single", action="store_true",
                        help="Run only the first model, first case, 1 rep (for testing)")
    args = parser.parse_args()

    # Repo root is where this script lives (agent-eval-harness)
    repo_root = Path(__file__).resolve().parents[2]
    project_root = Path(args.skill_project).resolve() if args.skill_project else Path.cwd()

    # Default config paths relative to harness repo
    if not args.plan:
        args.plan = str(repo_root / "eval" / "test_plan.yaml")
    if not args.config:
        args.config = str(repo_root / "eval.yaml")

    # Harness scripts (same repo: skills/eval-run/scripts/)
    harness_scripts = (repo_root / "skills" / "eval-run" / "scripts").resolve()

    if not harness_scripts.exists():
        print(f"ERROR: eval harness scripts not found at {harness_scripts}", file=sys.stderr)
        sys.exit(1)

    print(f"Harness scripts: {harness_scripts}")

    plan = load_test_plan(args.plan)
    models = plan["models"]
    cases = plan["cases"]
    reps = plan.get("repetitions", 1)
    execution = plan.get("execution", {})

    if args.single:
        models = models[:1]
        cases = cases[:1]
        reps = 1

    total_runs = len(models) * len(cases) * reps
    print(f"\nTest Matrix: {len(models)} models x {len(cases)} cases x {reps} reps = {total_runs} runs")
    print(f"Models: {[m['name'] for m in models]}")
    print(f"Cases: {cases}")

    start_time = time.time()
    results = []

    for model_cfg in models:
        for case_id in cases:
            for rep in range(1, reps + 1):
                run_id = make_run_id(model_cfg["name"], case_id, rep)
                try:
                    result = run_one(
                        run_id=run_id,
                        model_cfg=model_cfg,
                        case_id=case_id,
                        config_path=args.config,
                        execution=execution,
                        project_root=project_root,
                        harness_scripts=harness_scripts,
                    )
                    results.append(result)
                except Exception as e:
                    print(f"  FATAL ERROR: {e}")
                    results.append({"run_id": run_id, "status": "error", "error": str(e)})

    elapsed = time.time() - start_time

    # Save matrix summary
    summary_path = project_root / "eval" / "runs" / "matrix_summary.json"
    summary = {
        "total_runs": total_runs,
        "completed": sum(1 for r in results if r.get("status") == "completed"),
        "errors": sum(1 for r in results if r.get("status") == "error"),
        "elapsed_s": round(elapsed, 1),
        "runs": results,
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print(f"MATRIX COMPLETE")
    print(f"  Runs: {summary['completed']}/{total_runs} completed, {summary['errors']} errors")
    print(f"  Elapsed: {elapsed:.0f}s")
    print(f"  Summary: {summary_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
