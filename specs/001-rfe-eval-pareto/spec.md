# Feature Specification: RFE-Creator Price-Performance Evaluation

**Feature Branch**: `001-rfe-eval-pareto`  
**Created**: 2026-04-04  
**Status**: Draft  
**Input**: Evaluate rfe-creator agent across model configs to find the pareto curve on price-performance. Start with Opus 4.6 vs Sonnet 4.6, uniform model across all agents, 3 reps for variance. Matrix: 2 models x 3 RFEs x 3 reps = 18 isolated runs.

## User Scenarios & Testing

### User Story 1 - Run Evaluation Matrix (Priority: P1)

An evaluator runs the full 18-run test matrix to compare Opus 4.6 vs Sonnet 4.6 on the rfe-creator speedrun skill. Each run processes one Jira RFE in an isolated workspace with `--headless --dry-run`. The system captures quality scores (from existing rfe-creator rubric), cost (USD, tokens), and timing.

**Why this priority**: Core purpose of the system — without this, nothing else works.

**Independent Test**: Run `python3 eval/scripts/run_matrix.py` with a test plan containing 1 model, 1 RFE, 1 rep. Verify run_result.json, collected artifacts, and summary.yaml are produced.

**Acceptance Scenarios**:

1. **Given** a test_plan.yaml with 2 models and 3 RFEs, **When** run_matrix.py executes, **Then** 18 isolated runs complete with run_result.json containing duration_s, token_usage, and cost_usd for each
2. **Given** a completed run, **When** the frontmatter judges execute, **Then** summary.yaml contains rubric_score (0-10), pass_fail, feasibility, and 5 component scores extracted from rfe-review frontmatter
3. **Given** a run workspace, **When** the skill finishes, **Then** all artifacts (rfe-reviews, rfe-tasks, auto-fix-runs) are collected into eval/runs/{run_id}/cases/{rfe}/artifacts/

---

### User Story 2 - Generate A:B Comparison (Priority: P2)

After all runs complete, the evaluator generates a machine-parsable comparison of model A vs model B covering quality, cost, efficiency, variance, and per-RFE breakdowns.

**Why this priority**: The comparison output is the primary deliverable for decision-making.

**Independent Test**: Given a populated eval/runs/ directory with records from 2 models, run etl_loader.py then compare.py. Verify comparison.json has quality, cost, efficiency, and variance sections.

**Acceptance Scenarios**:

1. **Given** 18 completed runs, **When** etl_loader.py runs, **Then** records.json contains all 18 entries with model, rfe_id, repetition, cost, and quality fields
2. **Given** records.json, **When** compare.py runs, **Then** comparison.json contains mean_score, pass_rate, mean_cost_usd, score_per_dollar, and per-RFE breakdowns for each model
3. **Given** records.json, **When** etl_loader.py runs, **Then** pareto.csv is produced with columns: model, rfe_id, rep, score, cost_usd, duration_s, tokens_total

---

### User Story 3 - Load Results into MLflow (Priority: P2)

After ETL, results are logged to MLflow as experiment runs (params, metrics, artifacts) for interactive dashboards, and exported via mlflow-export-import for portability.

**Why this priority**: Enables interactive exploration and cross-instance portability.

**Independent Test**: Run etl_loader.py with --mlflow flag against a local MLflow instance. Verify experiment runs appear with correct params and metrics.

**Acceptance Scenarios**:

1. **Given** records.json, **When** etl_loader.py runs with MLflow enabled, **Then** each record is logged as an MLflow run with params (model, rfe_id, repetition) and metrics (rubric_score, cost_usd, duration_s, token counts, component scores)
2. **Given** a populated MLflow experiment, **When** the export step runs, **Then** eval/results/{ts}/mlflow-export/ contains the portable mlflow-export-import format

---

### User Story 4 - Model Parameterization (Priority: P1)

The rfe-creator skills must accept model selection from the eval runner instead of using hardcoded `model: opus`. The eval runner's `--model` and `CLAUDE_CODE_SUBAGENT_MODEL` control all agents uniformly.

**Why this priority**: Without this, we can only test one model config.

**Independent Test**: Remove `model: opus` from a SKILL.md file, run the skill with `--model claude-sonnet-4-6`, verify the skill uses sonnet.

**Acceptance Scenarios**:

1. **Given** all SKILL.md files have hardcoded `model: opus` removed, **When** the eval runner passes `--model claude-sonnet-4-6` and sets `CLAUDE_CODE_SUBAGENT_MODEL=claude-sonnet-4-6`, **Then** all agents (orchestrator + sub-agents) use sonnet
2. **Given** the eval runner's `_SAFE_ENV_KEYS`, **When** a run executes, **Then** JIRA_SERVER, JIRA_USER, JIRA_TOKEN, RFE_MODEL, RFE_MODEL_CONFIG, and GITHUB_TOKEN are forwarded to the subprocess

---

### Edge Cases

- What happens when a speedrun run fails (non-zero exit)? Run is recorded with exit_code and error, matrix continues.
- What happens when no review frontmatter is found? Judge returns default (0/false) with rationale "No review file found".
- What happens when MLflow is unavailable? ETL still produces records.json and pareto.csv; MLflow logging is skipped with a warning.
- What happens when a Jira issue is inaccessible? The speedrun skill handles this internally; the run captures the failure in exit_code.

## Requirements

### Functional Requirements

- **FR-001**: System MUST orchestrate N runs across a configurable test matrix (models x cases x repetitions)
- **FR-002**: System MUST create isolated workspaces per run via the eval harness workspace.py
- **FR-003**: System MUST capture duration_s, token_usage {input, output}, and cost_usd per run
- **FR-004**: System MUST extract existing rfe-creator quality scores from review frontmatter (rubric 0-10, 5 component scores, pass/fail, feasibility, recommendation)
- **FR-005**: System MUST produce records.json with unified per-run records
- **FR-006**: System MUST produce pareto.csv for spreadsheet/plotting use
- **FR-007**: System MUST produce comparison.json with A:B quality, cost, efficiency, variance, and per-RFE breakdowns
- **FR-008**: System MUST log results to MLflow as experiment runs with params, metrics, and artifacts
- **FR-009**: System MUST export MLflow experiment via mlflow-export-import for portability
- **FR-010**: System MUST preserve all raw run outputs in an organized directory tree
- **FR-011**: System MUST continue the matrix on individual run failures (no abort)
- **FR-012**: System MUST support uniform model selection (same model for orchestrator + all sub-agents)

### Key Entities

- **Run**: One execution of rfe.speedrun for one RFE with one model config. Identified by run_id = `{model_short}-{rfe_id}-rep{N}`
- **Record**: Unified data from a run: cost (duration, tokens, USD) + quality (scores, pass, feasibility, recommendation) + metadata (model, rfe_id, rep)
- **Test Plan**: YAML config defining models, cases, repetitions, and execution parameters

## Success Criteria

### Measurable Outcomes

- **SC-001**: All 18 runs in the initial matrix complete (with success or recorded failure) without manual intervention
- **SC-002**: comparison.json correctly reports mean scores, costs, and efficiency ratios for both models
- **SC-003**: Raw outputs for all 18 runs are preserved in eval/runs/ with all rfe-creator artifacts intact
- **SC-004**: Records can be loaded into MLflow and queried by model, rfe_id, and metrics
- **SC-005**: pareto.csv can be opened in a spreadsheet and used to plot score vs cost

## Assumptions

- The rfe-creator agent is invoked via Claude Code CLI (`claude --print`)
- Jira credentials (JIRA_SERVER, JIRA_USER, JIRA_TOKEN) are available in the environment
- The three test RFEs (RHAIRFE-1473, RHAIRFE-1429, RHAIRFE-1161) are accessible in Jira
- MLflow is available locally or the ETL gracefully degrades to file-only output
- `CLAUDE_CODE_SUBAGENT_MODEL` env var overrides explicit `model:` in Agent tool calls when the hardcoded values are removed from SKILL.md files
- The eval harness PR branch (pr-01) code is functional and tested
