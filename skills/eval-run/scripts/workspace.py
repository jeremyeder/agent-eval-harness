#!/usr/bin/env python3
"""Prepare an isolated workspace for skill evaluation.

Reads eval.yaml for dataset path and output directories.
For each case, includes the full input file content in batch.yaml —
no field extraction or schema interpretation.

Usage:
    python3 ${CLAUDE_SKILL_DIR}/scripts/workspace.py \\
        --config eval.yaml \\
        --run-id test-001 \\
        [--case-filter case-001] \\
        [--symlinks scripts,.claude,CLAUDE.md]
"""

import argparse
import shutil
import sys
from pathlib import Path

import yaml

from agent_eval.config import EvalConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="eval.yaml")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case-filter", nargs="*", default=None)
    parser.add_argument("--symlinks", default=None,
                        help="Comma-separated dirs/files to symlink into workspace "
                             "(default: scripts,.claude,CLAUDE.md,.context,skills)")
    args = parser.parse_args()

    config = EvalConfig.from_yaml(args.config)

    cases_dir = Path(config.dataset_path)
    if not cases_dir.exists():
        print(f"ERROR: dataset path not found: {cases_dir}", file=sys.stderr)
        sys.exit(1)

    # Find cases (each subdirectory is a case)
    case_dirs = sorted(d for d in cases_dir.iterdir() if d.is_dir())
    if args.case_filter:
        case_dirs = [c for c in case_dirs
                     if any(f in c.name for f in args.case_filter)]

    if not case_dirs:
        print("ERROR: no cases found", file=sys.stderr)
        sys.exit(1)

    # Create workspace
    workspace = Path(f"/tmp/agent-eval/{args.run_id}")
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)

    # Create output directories from config
    for output in config.outputs:
        if output.path and output.path != ".":
            (workspace / output.path).mkdir(parents=True, exist_ok=True)

    # Build batch entries — include full input file content per case
    batch_entries = []
    case_order = []

    for case_dir in case_dirs:
        # Find the input file (first .yaml or .json in the case dir)
        input_content = _read_input(case_dir)
        if input_content is None:
            continue

        batch_entries.append(input_content)
        case_order.append({"case_id": case_dir.name})

    # Write batch.yaml
    with open(workspace / "batch.yaml", "w") as f:
        yaml.dump(batch_entries, f, default_flow_style=False,
                  allow_unicode=True, width=120)

    # Write case order
    with open(workspace / "case_order.yaml", "w") as f:
        yaml.dump(case_order, f, default_flow_style=False)

    # Symlink project resources into workspace
    project_root = Path.cwd()
    default_symlinks = ["scripts", ".claude", "CLAUDE.md", ".context", "skills"]
    symlink_names = (
        [s.strip() for s in args.symlinks.split(",") if s.strip()]
        if args.symlinks else default_symlinks
    )
    for name in symlink_names:
        target = project_root / name
        link = workspace / name
        if target.exists():
            link.symlink_to(target.resolve())

    print(f"WORKSPACE: {workspace}")
    print(f"CASES: {len(case_dirs)}")
    print(f"BATCH: {workspace / 'batch.yaml'}")


def _read_input(case_dir):
    """Read the input file from a case directory.

    Returns the parsed content (dict) or None if no input file found.
    Tries .yaml/.yml first, then .json.
    """
    for name in sorted(case_dir.iterdir()):
        if name.is_file() and name.suffix in (".yaml", ".yml"):
            with open(name) as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                return data
        elif name.is_file() and name.suffix == ".json":
            import json
            with open(name) as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    return None


if __name__ == "__main__":
    main()
