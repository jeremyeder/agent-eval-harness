# Implementation Plan: RFE-Creator Price-Performance Evaluation

**Branch**: `001-rfe-eval-pareto` | **Date**: 2026-04-04 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-rfe-eval-pareto/spec.md`

## Summary

Build evaluation automation that runs the rfe-creator speedrun skill across model configurations (Opus 4.6 vs Sonnet 4.6), captures cost and quality metrics, and produces machine-parsable A:B comparisons. Uses the eval harness framework (PR pr-01) for workspace isolation, execution, and artifact collection. Adds frontmatter-based judges, an orchestration script, and ETL/comparison tooling.

## Technical Context

**Language/Version**: Python 3.11+  
**Primary Dependencies**: agent_eval (local package from PR pr-01), pyyaml, mlflow[genai], mlflow-export-import  
**Storage**: File-based (JSON, YAML, CSV) + optional MLflow  
**Testing**: Manual validation via single-run dry-run  
**Target Platform**: Linux (CI/local)  
**Project Type**: CLI automation scripts  
**Performance Goals**: N/A (batch job)  
**Constraints**: Each run costs $1-10 in API tokens; 18-run matrix ~$20-100 total  
**Scale/Scope**: 18 runs (2 models x 3 RFEs x 3 reps)

## Constitution Check

No constitution violations. The system uses existing eval harness patterns, adds no new abstractions beyond what's needed, and follows YAGNI.

## Project Structure

### Documentation (this feature)

```text
specs/001-rfe-eval-pareto/
├── plan.md              # This file
├── tasks.md             # Task breakdown
└── spec.md              # Feature specification
```

### Source Code (two repositories)

```text
# agent-eval-harness (primary repo)
agent_eval/agent/claude_code.py     # Extend _SAFE_ENV_KEYS (modify existing)
pyproject.toml                       # Add mlflow-export-import dep (modify existing)

# rfe-creator (secondary repo, at /workspace/repos/rfe-creator)
.claude/skills/                      # Remove hardcoded model: opus (modify existing)
eval/
├── dataset/cases/
│   ├── RHAIRFE-1473/input.yaml
│   ├── RHAIRFE-1429/input.yaml
│   └── RHAIRFE-1161/input.yaml
├── judges/
│   ├── __init__.py
│   └── frontmatter_judges.py       # Extract scores from rfe-review frontmatter
├── scripts/
│   ├── run_matrix.py                # Orchestrate 18 runs
│   ├── etl_loader.py                # Runs -> records.json + pareto.csv + MLflow
│   └── compare.py                   # A:B comparison -> comparison.json
├── test_plan.yaml                   # Model/case/rep configuration
└── eval.yaml                        # Eval harness configuration
```

**Structure Decision**: Two repos are involved. The eval harness gets infrastructure changes (env allowlist, deps). The rfe-creator gets the eval configuration, dataset, judges, and automation scripts under `eval/`.

## Data Flow

```
run_matrix.py (orchestrates 18 runs)
  for each (model, rfe, rep):
    workspace.py  -->  /tmp/agent-eval/{run_id}/       clean workspace
    execute.py    -->  eval/runs/{run_id}/run_result.json + logs
    collect.py    -->  eval/runs/{run_id}/cases/{rfe}/artifacts/...
    score.py      -->  eval/runs/{run_id}/summary.yaml

etl_loader.py (post-run)
  reads:  eval/runs/*/
  writes: eval/results/{ts}/records.json        unified records
          eval/results/{ts}/pareto.csv           for plotting
          MLflow experiment                      live (params + metrics + artifacts)
          eval/results/{ts}/mlflow-export/       portable (mlflow-export-import)

compare.py (post-run)
  reads:  records.json
  writes: eval/results/{ts}/comparison.json     A:B quality, cost, efficiency, variance
```
