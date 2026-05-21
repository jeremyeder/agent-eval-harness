#!/usr/bin/env python3
"""Sweep orchestrator for multi-variant planner evaluation.

Launches all planner × memory × repetition runs in parallel, tracks
state via an isolated beads database, and generates a comparison report.

Usage:
    python3 ${CLAUDE_SKILL_DIR}/scripts/sweep.py \\
        --config eval/planner-dataset/eval.yaml \\
        --case cli-tool \\
        --repetitions 3 \\
        --model sonnet \\
        [--max-parallel 12]

Resume after crash:
    python3 ${CLAUDE_SKILL_DIR}/scripts/sweep.py \\
        --config eval/planner-dataset/eval.yaml \\
        --case cli-tool \\
        --repetitions 3 \\
        --model sonnet
    (automatically skips completed runs via beads state)
"""

import agent_eval._bootstrap  # noqa: F401

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import yaml

from agent_eval.config import EvalConfig


def _get_runs_dir():
    return Path(os.environ.get("AGENT_EVAL_RUNS_DIR", "eval/runs"))


_SWEEP_PREFIX = "SWP"
_SWEEP_DB_DIR = ".beads-sweep"


def _bd(args_list, sweep_root):
    """Run a bd command against the sweep's isolated beads database.

    Uses -C to change to the sweep root directory, ensuring bd discovers
    only the sweep's .beads-sweep/ database — never the project's .beads/.
    The sweep DB uses prefix SWP- to make issues visually distinct.
    """
    cmd = ["bd", "-C", str(sweep_root), "--sandbox"] + args_list
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout.strip()


def _bd_create(title, task_type, sweep_root, description="", priority=2):
    """Create a beads issue and return its ID."""
    import re
    cmd = [
        "create",
        f"--title={title}",
        f"--type={task_type}",
        f"--priority={priority}",
    ]
    if description:
        cmd.append(f"--description={description}")
    output = _bd(cmd, sweep_root)
    m = re.search(r'\b(SWP-\w+)\b', output, re.IGNORECASE)
    return m.group(1) if m else ""


def _bd_close(issue_id, sweep_root, reason=""):
    """Close a beads issue."""
    cmd = ["close", issue_id]
    if reason:
        cmd.append(f"--reason={reason}")
    _bd(cmd, sweep_root)


def _bd_update(issue_id, sweep_root, **kwargs):
    """Update a beads issue."""
    cmd = ["update", issue_id]
    if kwargs.get("claim"):
        cmd.append("--claim")
    if kwargs.get("notes"):
        cmd.append(f"--notes={kwargs['notes']}")
    _bd(cmd, sweep_root)


def _bd_dep_add(issue_id, depends_on_id, sweep_root):
    """Add a dependency: issue_id depends on depends_on_id."""
    _bd(["dep", "add", issue_id, depends_on_id], sweep_root)


def _bd_ready(sweep_root):
    """Get list of ready (unblocked, open) issue IDs."""
    import re
    output = _bd(["ready"], sweep_root)
    if not output:
        return []
    ids = []
    for line in output.splitlines():
        m = re.search(r'\b(SWP-\w+)\b', line, re.IGNORECASE)
        if m:
            ids.append(m.group(1))
    return ids


def _bd_is_closed(issue_id, sweep_root):
    """Check if an issue is closed."""
    output = _bd(["show", issue_id], sweep_root)
    return "closed" in output.lower() or "✓" in output


def _run_name(variant, memory, rep):
    """Generate the run directory name."""
    return f"planner-{variant}-{memory}-r{rep}"


def _run_pipeline(run_name, config_path, case, variant, memory, phase,
                  model, runs_dir, prior_run=None, timeout=3600, max_budget=20):
    """Execute one phase of one run. Called as a subprocess-friendly function."""
    script_dir = Path(__file__).parent
    run_output = runs_dir / f"{run_name}-{phase}"

    # 1. Workspace setup
    ws_cmd = [
        sys.executable, str(script_dir / "workspace.py"),
        "--config", str(config_path),
        "--run-id", f"{run_name}-{phase}",
        "--phase", phase,
        "--variant", variant,
        "--case-filter", case,
        "--memory-variant", memory,
    ]
    if prior_run:
        ws_cmd.extend(["--prior-run", str(prior_run)])

    ws_result = subprocess.run(ws_cmd, capture_output=True, text=True, timeout=60)
    if ws_result.returncode != 0:
        return {"status": "failed", "phase": phase, "error": ws_result.stderr[-500:]}

    # Extract workspace path from output
    workspace = None
    for line in ws_result.stdout.splitlines():
        if line.startswith("WORKSPACE:"):
            workspace = line.split(":", 1)[1].strip()
            break
    if not workspace:
        return {"status": "failed", "phase": phase, "error": "No workspace path in output"}

    # 2. Execute
    exec_cmd = [
        sys.executable, str(script_dir / "execute.py"),
        "--workspace", workspace,
        "--skill", "",
        "--config", str(config_path),
        "--phase", phase,
        "--variant", variant,
        "--model", model,
        "--output", str(run_output),
        "--max-budget", str(max_budget),
        "--timeout", str(timeout),
    ]
    if prior_run:
        exec_cmd.extend(["--prior-run", str(prior_run)])

    stderr_path = run_output / "sweep-stderr.log"
    run_output.mkdir(parents=True, exist_ok=True)

    exec_result = subprocess.run(
        exec_cmd, capture_output=True, text=True,
        timeout=timeout + 60,
    )
    if exec_result.stderr:
        stderr_path.write_text(exec_result.stderr)

    # 3. Collect
    collect_cmd = [
        sys.executable, str(script_dir / "collect.py"),
        "--config", str(config_path),
        "--workspace", workspace,
        "--output", str(run_output),
        "--phase", phase,
        "--variant", variant,
    ]
    subprocess.run(collect_cmd, capture_output=True, text=True, timeout=120)

    # 4. Read results
    rr_path = run_output / "run_result.json"
    result_data = {"status": "done", "phase": phase, "run_output": str(run_output)}
    if rr_path.exists():
        with open(rr_path) as f:
            rr = json.load(f)
        result_data["cost_usd"] = rr.get("cost_usd", 0)
        result_data["duration_s"] = rr.get("duration_s", 0)
        result_data["tokens"] = rr.get("token_usage", {})
        result_data["exit_code"] = rr.get("exit_code", -1)
        if rr.get("exit_code", -1) != 0:
            result_data["status"] = "failed"
            result_data["error"] = f"exit {rr.get('exit_code')}"
    else:
        result_data["status"] = "failed"
        result_data["error"] = "No run_result.json"

    return result_data


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, help="Path to eval.yaml")
    parser.add_argument("--case", required=True, help="Case name to evaluate")
    parser.add_argument("--model", required=True, help="Model to use")
    parser.add_argument("--repetitions", type=int, default=3,
                        help="Number of repetitions per cell (default: 3)")
    parser.add_argument("--max-parallel", type=int, default=12,
                        help="Max parallel runs (default: 12)")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Per-phase timeout in seconds (default: 3600)")
    parser.add_argument("--max-budget", type=float, default=20.0,
                        help="Per-phase budget in USD (default: 20)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would run without executing")
    args = parser.parse_args()

    config = EvalConfig.from_yaml(args.config)
    runs_dir = _get_runs_dir()
    runs_dir.mkdir(parents=True, exist_ok=True)

    variants = [v.name for v in config.variants]
    memories = [mv.name for mv in config.memory_variants] or ["none"]
    reps = list(range(1, args.repetitions + 1))

    # Initialize sweep beads database in an isolated directory.
    # Uses .beads-sweep/ (not .beads/) so bd commands without -C never
    # discover it, and the project's .beads/ is never confused with it.
    sweep_root = runs_dir / _SWEEP_DB_DIR
    sweep_root.mkdir(parents=True, exist_ok=True)
    sweep_beads = sweep_root / ".beads"
    if not sweep_beads.exists():
        subprocess.run(
            ["bd", "init", f"--prefix={_SWEEP_PREFIX}", "-C", str(sweep_root)],
            capture_output=True, text=True, timeout=30,
        )
        print(f"Initialized sweep DB at {sweep_root}/", file=sys.stderr)

    # Build the run matrix and create beads issues
    plan_issues = {}  # (variant, memory, rep) → issue_id
    build_issues = {}  # (variant, memory, rep) → issue_id

    total_cells = len(variants) * len(memories) * len(reps)

    print(f"Sweep: {len(variants)} variants × {len(memories)} memories "
          f"× {len(reps)} reps = {total_cells} cells ({total_cells * 2} runs)")
    print(f"  Variants: {variants}")
    print(f"  Memories: {memories}")
    print(f"  Model: {args.model}")
    print(f"  Case: {args.case}")
    print(f"  Max parallel: {args.max_parallel}")

    if args.dry_run:
        print("\nDry run — would create these runs:")
        for v in variants:
            for m in memories:
                for r in reps:
                    name = _run_name(v, m, r)
                    print(f"  {name}-planning → {name}-building")
        return

    # Check for existing issues (resume support)
    existing_output = _bd(["list"], sweep_root)
    existing_titles = set()
    for v in variants:
        for m in memories:
            for r in reps:
                name = _run_name(v, m, r)
                if f"{name} planning" in existing_output:
                    existing_titles.add(f"{name} planning")
                if f"{name} building" in existing_output:
                    existing_titles.add(f"{name} building")

    # Create issues for each run
    for v in variants:
        for m in memories:
            for r in reps:
                name = _run_name(v, m, r)
                plan_title = f"{name} planning"
                build_title = f"{name} building"

                if plan_title not in existing_titles:
                    pid = _bd_create(plan_title, "task", sweep_root,
                                     description=f"variant={v} memory={m} rep={r} phase=planning")
                    plan_issues[(v, m, r)] = pid
                    bid = _bd_create(build_title, "task", sweep_root,
                                     description=f"variant={v} memory={m} rep={r} phase=building")
                    build_issues[(v, m, r)] = bid
                    if pid and bid:
                        _bd_dep_add(bid, pid, sweep_root)
                else:
                    print(f"  Resuming: {name} (issues exist)", file=sys.stderr)

    print(f"\nCreated {len(plan_issues)} planning + {len(build_issues)} building issues")
    print(f"Starting sweep...\n")

    # Main execution loop
    total_cost = 0.0
    completed = 0
    total_runs = total_cells * 2
    start_time = time.monotonic()
    active_futures = {}

    with ProcessPoolExecutor(max_workers=args.max_parallel) as pool:
        while True:
            # Find ready work from beads
            ready_ids = _bd_ready(sweep_root)
            if not ready_ids and not active_futures:
                break

            # Launch ready tasks (up to max_parallel - active)
            available_slots = args.max_parallel - len(active_futures)
            active_issue_ids = {v[0] for v in active_futures.values()}
            for issue_id in ready_ids[:available_slots]:
                if issue_id in active_issue_ids:
                    continue

                # Determine what this issue represents by matching against
                # the known run matrix. Avoids brittle title parsing.
                issue_output = _bd(["show", issue_id], sweep_root)
                matched = None
                for v in variants:
                    for m in memories:
                        for r in reps:
                            name = _run_name(v, m, r)
                            for phase_candidate in ("planning", "building"):
                                needle = f"{name} {phase_candidate}"
                                if needle in issue_output:
                                    matched = (v, m, r, phase_candidate, name)
                                    break
                            if matched:
                                break
                        if matched:
                            break
                    if matched:
                        break
                if not matched:
                    continue
                variant, memory, rep, phase, run_name = matched

                # For building phase, find the planning run output
                prior_run = None
                if phase == "building":
                    prior_run = str(runs_dir / f"{run_name}-planning")

                # Check if already completed
                run_output = runs_dir / f"{run_name}-{phase}"
                rr_path = run_output / "run_result.json"
                if rr_path.exists():
                    _bd_close(issue_id, sweep_root, reason="Already completed")
                    completed += 1
                    continue

                _bd_update(issue_id, sweep_root, claim=True)
                elapsed = time.monotonic() - start_time
                print(f"  [{completed}/{total_runs}] Launching {run_name}-{phase} "
                      f"({elapsed:.0f}s elapsed, ${total_cost:.2f} spent)",
                      flush=True)

                future = pool.submit(
                    _run_pipeline, run_name, args.config, args.case,
                    variant, memory, phase, args.model, runs_dir,
                    prior_run=prior_run, timeout=args.timeout,
                    max_budget=args.max_budget,
                )
                active_futures[future] = (issue_id, run_name, phase)

            # Wait for at least one completion if we have active work
            if active_futures:
                done_futures = []
                for future in list(active_futures):
                    if future.done():
                        done_futures.append(future)

                if not done_futures:
                    time.sleep(5)
                    continue

                for future in done_futures:
                    issue_id, run_name, phase = active_futures.pop(future)
                    try:
                        result = future.result(timeout=10)
                    except Exception as e:
                        result = {"status": "failed", "error": str(e)}

                    completed += 1
                    cost = result.get("cost_usd", 0) or 0
                    total_cost += cost
                    duration = result.get("duration_s", 0) or 0
                    tokens = result.get("tokens", {})
                    total_tokens = sum(v for v in tokens.values()
                                       if isinstance(v, (int, float)))

                    if result["status"] == "done":
                        notes = (f"cost=${cost:.2f} duration={duration:.0f}s "
                                 f"tokens={total_tokens}")
                        _bd_update(issue_id, sweep_root, notes=notes)
                        _bd_close(issue_id, sweep_root,
                                  reason=f"${cost:.2f}, {duration:.0f}s")
                        status_str = f"DONE ${cost:.2f} {duration:.0f}s"
                    else:
                        error = result.get("error", "unknown")[:200]
                        _bd_update(issue_id, sweep_root,
                                   notes=f"FAILED: {error}")
                        status_str = f"FAILED: {error[:80]}"

                    elapsed = time.monotonic() - start_time
                    print(f"  [{completed}/{total_runs}] {run_name}-{phase}: "
                          f"{status_str} | "
                          f"{completed} done, {len(active_futures)} running, "
                          f"${total_cost:.2f} total, {elapsed:.0f}s elapsed",
                          flush=True)
            elif not ready_ids:
                # Nothing ready and nothing active — check if truly done
                # or if everything is blocked/failed
                time.sleep(2)
                ready_ids = _bd_ready(sweep_root)
                if not ready_ids:
                    break

    elapsed = time.monotonic() - start_time
    print(f"\nSweep complete: {completed}/{total_runs} runs, "
          f"${total_cost:.2f} total, {elapsed:.0f}s elapsed")
    print(f"\nStatus:  bd -C {sweep_root} stats")
    print(f"Details: bd -C {sweep_root} list")

    # Generate comparison report
    print("\nTo generate comparison report:")
    variant_runs = []
    for v in variants:
        for m in memories:
            for r in reps:
                name = _run_name(v, m, r)
                variant_runs.append(f"{name}-building")
    print(f"  python3 {Path(__file__).parent}/report.py "
          f"--run-id {variant_runs[0]} "
          f"--config {args.config} "
          f"--variants {' '.join(variant_runs)}")


if __name__ == "__main__":
    main()
