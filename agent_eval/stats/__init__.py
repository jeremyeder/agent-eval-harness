"""Statistical analysis for agent evaluations.

Optional dependency: install with `pip install agent-eval-harness[anova]`.
"""

try:
    from agent_eval.stats.anova import (
        mixed_effects_anova,
        one_way_anova,
        repeated_measures_anova,
    )
    from agent_eval.stats.pareto import pareto_frontier

    ANOVA_AVAILABLE = True
except ImportError:
    ANOVA_AVAILABLE = False
