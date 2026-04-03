#!/usr/bin/env python3
"""Discover skills and check eval.md freshness.

Usage:
    python3 ${CLAUDE_SKILL_DIR}/scripts/discover.py skills
    python3 ${CLAUDE_SKILL_DIR}/scripts/discover.py config [eval.yaml]
    python3 ${CLAUDE_SKILL_DIR}/scripts/discover.py check-eval-md [eval.md]
"""

import hashlib
import sys
from glob import glob
from pathlib import Path

import yaml


def discover_skills():
    """Find all skills in the project."""
    patterns = [
        ".claude/skills/*/SKILL.md",
        "skills/*/SKILL.md",
    ]
    skills = []
    for pattern in patterns:
        for path in sorted(glob(pattern)):
            name = Path(path).parent.name
            desc = ""
            try:
                with open(path) as f:
                    content = f.read()
                if content.startswith("---"):
                    fm = yaml.safe_load(content.split("---")[1])
                    desc = fm.get("description", "")[:80]
            except Exception:
                pass
            skills.append({"name": name, "path": path, "description": desc})

    if skills:
        for s in skills:
            print(f"SKILL: {s['name']:<30} {s['description']}")
    else:
        print("NONE: no skills found")
    return skills


def validate_config(path="eval.yaml"):
    """Validate an eval.yaml config file."""
    p = Path(path)
    if not p.exists():
        print(f"NOT_FOUND: {path}")
        sys.exit(1)

    with open(p) as f:
        config = yaml.safe_load(f) or {}

    errors = []
    if not config.get("skill"):
        errors.append("Missing 'skill' field")
    if not config.get("name"):
        errors.append("Missing 'name' field")

    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        sys.exit(1)

    dataset = config.get("dataset", {})
    outputs = config.get("outputs", [])
    judges = config.get("judges", [])

    print(f"VALID: {config.get('name')} (skill={config.get('skill')})")
    print(f"  dataset: {dataset.get('path', 'not set')}")
    print(f"  outputs: {len(outputs)} directories")
    print(f"  judges: {len(judges)}")


def check_eval_md(path="eval.md"):
    """Check if eval.md is fresh (skill hasn't changed)."""
    p = Path(path)
    if not p.exists():
        print("STALE: eval.md does not exist")
        sys.exit(1)

    content = p.read_text()
    if not content.startswith("---"):
        print("STALE: no frontmatter")
        sys.exit(1)

    parts = content.split("---", 2)
    if len(parts) < 3:
        print("STALE: invalid frontmatter")
        sys.exit(1)

    fm = yaml.safe_load(parts[1]) or {}
    skill_name = fm.get("skill", "")
    stored_hash = fm.get("skill_hash", "")

    if not skill_name or not stored_hash:
        print("STALE: missing skill or hash")
        sys.exit(1)

    for skills_dir in [Path(".claude/skills"), Path("skills")]:
        skill_path = skills_dir / skill_name / "SKILL.md"
        if skill_path.exists():
            current_hash = hashlib.md5(skill_path.read_bytes()).hexdigest()[:12]
            if current_hash == stored_hash:
                print(f"FRESH: {skill_name} (hash={stored_hash})")
                return
            else:
                print(f"STALE: hash mismatch ({stored_hash} != {current_hash})")
                sys.exit(1)

    print(f"STALE: skill {skill_name} not found")
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("Usage: discover.py <skills|config|check-eval-md> [args]",
              file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "skills":
        discover_skills()
    elif cmd == "config":
        path = sys.argv[2] if len(sys.argv) > 2 else "eval.yaml"
        validate_config(path)
    elif cmd == "check-eval-md":
        path = sys.argv[2] if len(sys.argv) > 2 else "eval.md"
        check_eval_md(path)
    else:
        print(f"Unknown: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
