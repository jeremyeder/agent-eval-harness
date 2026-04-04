"""Extract quality scores from rfe-review YAML frontmatter.

Each function is called by score.py with outputs=record where record is:
    {"files": {"relative/path.md": "<content>", ...}, "case_dir": str, ...}

Review files are in artifacts/rfe-reviews/ with names like RHAIRFE-1473-review.md.
"""

import re
from pathlib import Path
from typing import Any

import yaml


def _find_review_frontmatter(outputs: dict) -> dict:
    """Find and parse the first review file's YAML frontmatter from outputs."""
    files = outputs.get("files", {})
    for path, content in files.items():
        if "review" in Path(path).name and path.endswith(".md"):
            fm = _parse_frontmatter(content)
            if fm:
                return fm
    return {}


def _parse_frontmatter(content: str) -> dict | None:
    """Extract YAML frontmatter from markdown content."""
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None
    try:
        return yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None


def rubric_score(outputs: dict = None, **kwargs: Any) -> float:
    """Total rubric score (0-10)."""
    fm = _find_review_frontmatter(outputs or {})
    return float(fm.get("score", 0))


def pass_fail(outputs: dict = None, **kwargs: Any) -> bool:
    """Whether the RFE passed review."""
    fm = _find_review_frontmatter(outputs or {})
    return bool(fm.get("pass", False))


def feasibility(outputs: dict = None, **kwargs: Any) -> str:
    """Feasibility assessment: feasible/infeasible/indeterminate."""
    fm = _find_review_frontmatter(outputs or {})
    return fm.get("feasibility", "indeterminate")


def score_what(outputs: dict = None, **kwargs: Any) -> float:
    """Component score: what (0-2)."""
    fm = _find_review_frontmatter(outputs or {})
    return float(fm.get("scores", {}).get("what", 0))


def score_why(outputs: dict = None, **kwargs: Any) -> float:
    """Component score: why (0-2)."""
    fm = _find_review_frontmatter(outputs or {})
    return float(fm.get("scores", {}).get("why", 0))


def score_open_to_how(outputs: dict = None, **kwargs: Any) -> float:
    """Component score: open_to_how (0-2)."""
    fm = _find_review_frontmatter(outputs or {})
    return float(fm.get("scores", {}).get("open_to_how", 0))


def score_not_a_task(outputs: dict = None, **kwargs: Any) -> float:
    """Component score: not_a_task (0-2)."""
    fm = _find_review_frontmatter(outputs or {})
    return float(fm.get("scores", {}).get("not_a_task", 0))


def score_right_sized(outputs: dict = None, **kwargs: Any) -> float:
    """Component score: right_sized (0-2)."""
    fm = _find_review_frontmatter(outputs or {})
    return float(fm.get("scores", {}).get("right_sized", 0))


def recommendation(outputs: dict = None, **kwargs: Any) -> str:
    """Recommendation: submit/revise/split/reject."""
    fm = _find_review_frontmatter(outputs or {})
    return fm.get("recommendation", "reject")


def auto_revised(outputs: dict = None, **kwargs: Any) -> bool:
    """Whether the RFE was auto-revised."""
    fm = _find_review_frontmatter(outputs or {})
    return bool(fm.get("auto_revised", False))
