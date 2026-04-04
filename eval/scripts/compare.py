#!/usr/bin/env python3
"""Generate A:B comparison from records.json.

Reads unified records and produces comparison.json with quality, cost,
efficiency, variance, and per-RFE breakdowns.

Usage:
    python3 eval/scripts/compare.py --records eval/results/TIMESTAMP/records.json
    python3 eval/scripts/compare.py --records eval/results/TIMESTAMP/records.json --output comparison.json
"""

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path


def load_records(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def group_by_model(records: list[dict]) -> dict[str, list[dict]]:
    groups = defaultdict(list)
    for r in records:
        groups[r["model"]].append(r)
    return dict(groups)


def _stats(values: list[float]) -> dict:
    """Compute mean, std, min, max for a list of values."""
    if not values:
        return {"mean": None, "std": None, "min": None, "max": None, "n": 0}
    n = len(values)
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / n if n > 1 else 0
    return {
        "mean": round(mean, 4),
        "std": round(math.sqrt(variance), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "n": n,
    }


def _safe_values(records: list[dict], key: str) -> list[float]:
    """Extract numeric values, skipping None."""
    return [float(r[key]) for r in records if r.get(key) is not None]


def _pass_rate(records: list[dict]) -> float | None:
    vals = [r.get("pass_fail") for r in records if r.get("pass_fail") is not None]
    if not vals:
        return None
    return sum(1 for v in vals if v) / len(vals)


def model_summary(records: list[dict]) -> dict:
    """Compute summary stats for one model's records."""
    return {
        "quality": {
            "rubric_score": _stats(_safe_values(records, "rubric_score")),
            "pass_rate": _pass_rate(records),
            "score_what": _stats(_safe_values(records, "score_what")),
            "score_why": _stats(_safe_values(records, "score_why")),
            "score_open_to_how": _stats(_safe_values(records, "score_open_to_how")),
            "score_not_a_task": _stats(_safe_values(records, "score_not_a_task")),
            "score_right_sized": _stats(_safe_values(records, "score_right_sized")),
        },
        "cost": {
            "cost_usd": _stats(_safe_values(records, "cost_usd")),
            "duration_s": _stats(_safe_values(records, "duration_s")),
            "tokens_total": _stats(_safe_values(records, "tokens_total")),
            "tokens_input": _stats(_safe_values(records, "tokens_input")),
            "tokens_output": _stats(_safe_values(records, "tokens_output")),
        },
        "efficiency": _compute_efficiency(records),
    }


def _compute_efficiency(records: list[dict]) -> dict:
    scores = _safe_values(records, "rubric_score")
    costs = _safe_values(records, "cost_usd")
    if not scores or not costs:
        return {"score_per_dollar": None, "cost_per_point": None}
    mean_score = sum(scores) / len(scores)
    mean_cost = sum(costs) / len(costs)
    return {
        "score_per_dollar": round(mean_score / mean_cost, 4) if mean_cost > 0 else None,
        "cost_per_point": round(mean_cost / mean_score, 4) if mean_score > 0 else None,
    }


def per_rfe_breakdown(records: list[dict]) -> dict:
    """Group records by case_id and compute per-RFE stats."""
    by_case = defaultdict(list)
    for r in records:
        by_case[r["case_id"]].append(r)

    breakdown = {}
    for case_id, case_records in sorted(by_case.items()):
        breakdown[case_id] = {
            "rubric_score": _stats(_safe_values(case_records, "rubric_score")),
            "cost_usd": _stats(_safe_values(case_records, "cost_usd")),
            "pass_rate": _pass_rate(case_records),
            "n": len(case_records),
        }
    return breakdown


def compare_models(groups: dict[str, list[dict]]) -> dict:
    """Build the full A:B comparison."""
    model_names = sorted(groups.keys())

    comparison = {
        "models": model_names,
        "per_model": {},
        "per_rfe": {},
    }

    for model_name in model_names:
        records = groups[model_name]
        comparison["per_model"][model_name] = model_summary(records)
        comparison["per_rfe"][model_name] = per_rfe_breakdown(records)

    # Head-to-head deltas (if exactly 2 models)
    if len(model_names) == 2:
        a, b = model_names
        sa = comparison["per_model"][a]
        sb = comparison["per_model"][b]

        a_score = (sa["quality"]["rubric_score"] or {}).get("mean")
        b_score = (sb["quality"]["rubric_score"] or {}).get("mean")
        a_cost = (sa["cost"]["cost_usd"] or {}).get("mean")
        b_cost = (sb["cost"]["cost_usd"] or {}).get("mean")

        comparison["head_to_head"] = {
            "score_delta": round(a_score - b_score, 4) if a_score is not None and b_score is not None else None,
            "cost_delta": round(a_cost - b_cost, 4) if a_cost is not None and b_cost is not None else None,
            "score_ratio": round(a_score / b_score, 4) if b_score else None,
            "cost_ratio": round(a_cost / b_cost, 4) if b_cost else None,
            "interpretation": {
                f"{a}_vs_{b}_score": f"{a} scores {'higher' if (a_score or 0) > (b_score or 0) else 'lower'} by {abs((a_score or 0) - (b_score or 0)):.2f} points",
                f"{a}_vs_{b}_cost": f"{a} costs {'more' if (a_cost or 0) > (b_cost or 0) else 'less'} by ${abs((a_cost or 0) - (b_cost or 0)):.2f}",
            },
        }

    return comparison


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--records", required=True, help="Path to records.json")
    parser.add_argument("--output", default=None, help="Output path (default: same dir as records)")
    args = parser.parse_args()

    records = load_records(args.records)
    if not records:
        print("No records found.", file=sys.stderr)
        sys.exit(1)

    groups = group_by_model(records)
    print(f"Loaded {len(records)} records across {len(groups)} models: {list(groups.keys())}")

    comparison = compare_models(groups)

    output_path = Path(args.output) if args.output else Path(args.records).parent / "comparison.json"
    with open(output_path, "w") as f:
        json.dump(comparison, f, indent=2)

    print(f"\nComparison written to: {output_path}")

    # Print summary
    for model_name in comparison["models"]:
        ms = comparison["per_model"][model_name]
        score = (ms["quality"]["rubric_score"] or {}).get("mean", "N/A")
        cost = (ms["cost"]["cost_usd"] or {}).get("mean", "N/A")
        eff = ms["efficiency"].get("score_per_dollar", "N/A")
        print(f"  {model_name}: score={score}, cost=${cost}, efficiency={eff} score/$")

    if "head_to_head" in comparison:
        h2h = comparison["head_to_head"]
        for key, msg in h2h.get("interpretation", {}).items():
            print(f"  {msg}")


if __name__ == "__main__":
    main()
