---
name: eval-anova
description: Run Design-of-Experiments (DoE) evaluations with ANOVA statistical analysis. Compares agent configurations across factorial experiment designs with repeated-measures statistics that account for case difficulty.
---

# eval-anova

Run a full-factorial experiment comparing agent configurations (models, effort levels, prompts) across shared test cases, then analyze results with repeated-measures ANOVA.

## Usage

```
/eval-anova                    # interactive: design → run → analyze
/eval-anova --dry-run          # validate config + estimate cost, no execution
/eval-anova --analyze-only     # re-analyze existing results
```

## Prerequisites

Install ANOVA dependencies:

```bash
pip install -e ".[anova]"
```

Set the results archival repo:

```bash
export RHAI_RESULTS_REPO=/path/to/rhai-results
```

## Workflow

1. **Design**: Define factors and levels in your eval YAML's `matrix:` section
2. **Preflight**: Validate archive repo, estimate cost
3. **Execute**: Run each condition × case × replication cell
4. **Score**: Composite scoring with bool/int separation and gate logic
5. **Analyze**: Repeated-measures ANOVA + Pareto frontier
6. **Archive**: Results saved to git-backed repo (or local fallback)

## Matrix Configuration

Add a `matrix:` key to your eval YAML:

```yaml
matrix:
  factors:
    model:
      - claude-sonnet-4-20250514
      - claude-haiku-4-5-20251001
    effort:
      - low
      - high
  replications: 3
```

See `references/matrix-schema.md` for the full schema.

## Statistical Methods

- **Repeated-measures ANOVA** (default): Accounts for case difficulty as a blocking factor. Correct when the same cases are evaluated under all conditions.
- **Mixed-effects model**: For multi-factor designs with crossed random effects.
- **One-way ANOVA**: Only for independent samples (cases NOT reused). Rarely appropriate.

See `prompts/interpret-anova.md` for guidance on interpreting results.
