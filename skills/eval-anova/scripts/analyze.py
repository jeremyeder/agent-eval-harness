"""Post-experiment analysis — ANOVA + Pareto + archival."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from agent_eval.archive import ResultsArchiver
from agent_eval.composite import aggregate_replications
from agent_eval.stats import ANOVA_AVAILABLE

logger = logging.getLogger(__name__)


def build_results_dataframe(
    run_results: list[Any],
) -> pd.DataFrame:
    """Convert RunResult list to a DataFrame for statistical analysis."""
    rows = []
    for r in run_results:
        row = {
            "case_id": r.case_id,
            "replication": r.replication,
            "composite": r.composite,
            "condition_id": r.condition.condition_id,
        }
        row.update(r.condition.levels)
        rows.append(row)
    return pd.DataFrame(rows)


def analyze_experiment(
    run_results: list[Any],
    factors: list[str],
    *,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Run statistical analysis on experiment results.

    Uses repeated-measures ANOVA for single-factor designs,
    mixed-effects model for multi-factor designs.
    """
    if not ANOVA_AVAILABLE:
        raise ImportError(
            "ANOVA dependencies not installed. "
            "Install with: pip install agent-eval-harness[anova]"
        )

    from agent_eval.stats.anova import mixed_effects_anova, repeated_measures_anova
    from agent_eval.stats.pareto import pareto_frontier

    df = build_results_dataframe(run_results)

    if len(factors) == 1:
        anova_result = repeated_measures_anova(df, factor=factors[0], alpha=alpha)
    else:
        anova_result = mixed_effects_anova(df, factors=factors, alpha=alpha)

    condition_summaries = []
    for cid, group in df.groupby("condition_id"):
        scores = group["composite"].tolist()
        agg = aggregate_replications(scores)
        levels = {f: group[f].iloc[0] for f in factors if f in group.columns}
        condition_summaries.append({
            "condition_id": cid,
            "levels": levels,
            **agg,
        })

    frontier = pareto_frontier(
        condition_summaries,
        cost_key="mean",
        quality_key="mean",
    )

    return {
        "anova": anova_result,
        "condition_summaries": condition_summaries,
        "pareto_frontier": frontier,
        "n_runs": len(run_results),
        "n_conditions": len(condition_summaries),
    }


def archive_results(
    experiment_id: str,
    analysis: dict[str, Any],
    run_results: list[Any],
    repo_path: Path,
) -> Path:
    """Archive experiment results to the results repo."""
    archiver = ResultsArchiver(repo_path=repo_path)

    data = {
        "experiment_id": experiment_id,
        "analysis": _make_serializable(analysis),
        "n_runs": len(run_results),
    }

    return archiver.archive_experiment(experiment_id, data, fallback=True)


def _make_serializable(obj: Any) -> Any:
    """Convert non-serializable types for JSON output."""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_serializable(i) for i in obj]
    if isinstance(obj, float) and (obj != obj):  # NaN check
        return None
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return obj
