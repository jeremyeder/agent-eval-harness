# Specification: eval-mlflow Backend Implementation

**Version**: 1.0  
**Date**: 2026-04-04  
**Status**: Draft

## Overview

Implement the backend scripts for the eval-mlflow skill to enable MLflow integration for the evaluation harness. The skill definition exists at `skills/eval-mlflow/SKILL.md` but currently uses inline `python3 -c "..."` blocks. Replace these with proper Python scripts.

## Goals

1. Create three Python scripts to handle MLflow operations
2. Update SKILL.md to call scripts instead of inline Python
3. Maintain consistency with existing harness code style and patterns
4. Enable idempotent, schema-driven MLflow integration

## Context

### Existing Infrastructure

- **Config**: `agent_eval.config.EvalConfig` parses eval.yaml
- **MLflow utils**: `agent_eval.mlflow.experiment` provides `setup_experiment()`, `ensure_server()`, `log_feedback()`
- **Dependencies**: `mlflow[genai]>=3.5` already installed
- **Run outputs**: 
  - `eval/runs/<run-id>/summary.yaml` (judge scores, aggregates)
  - `eval/runs/<run-id>/run_result.json` (metadata, cost, tokens, duration)

### Data Structures

**eval.yaml**:
```yaml
name: my-eval
mlflow_experiment: my-experiment
dataset:
  path: cases/
  schema: "Each case has input.yaml with {prompt, context} and expected.yaml with {output}"
outputs:
  - path: result
    schema: "Generated markdown document"
judges:
  - name: correctness
    check: ...
thresholds:
  correctness:
    min_pass_rate: 0.8
```

**summary.yaml**:
```yaml
run_id: run-20260404-1234
judges:
  correctness:
    values: [true, false, true, true]
    mean: 0.75
    pass_rate: 0.75
per_case:
  case-001:
    correctness:
      value: true
      rationale: "Output matches expected format"
```

**run_result.json**:
```json
{
  "exit_code": 0,
  "duration_s": 45.3,
  "token_usage": {"input": 1000, "output": 500},
  "cost_usd": 0.15,
  "agent": "claude-code"
}
```

## Requirements

### 1. sync_dataset.py

**Purpose**: Read case directories and sync to MLflow dataset

**Location**: `skills/eval-mlflow/scripts/sync_dataset.py`

**CLI Interface**:
```bash
python3 sync_dataset.py --config eval.yaml --dataset-name <name>
```

**Arguments**:
- `--config` (default: `eval.yaml`): Path to eval config
- `--dataset-name` (required): Name for MLflow dataset

**Behavior**:
1. Load `EvalConfig` from YAML
2. Read `dataset_schema` to understand case structure
3. Browse directories at `dataset_path`
4. For each case directory:
   - Read all files (with path validation)
   - Classify files as inputs vs expectations using naming heuristic:
     - Files matching `input*`, `prompt*` → inputs
     - Files matching `expected*`, `reference*` → expectations
     - All other files → inputs
   - Build MLflow record: `{"inputs": {...}, "expectations": {...}}`
5. Use `mlflow.genai.datasets.create_dataset()` or `get_dataset()` + `merge_records()`
6. Set experiment via `setup_experiment()`
7. Print: `"Synced N cases to MLflow dataset '<name>'"`

**Key Constraints**:
- Schema-driven interpretation (v1: naming heuristic, future: LLM-based)
- Path safety: validate all paths to prevent traversal attacks
- Idempotent (safe to run multiple times - datasets merge/deduplicate)
- ~80 lines

### 2. log_results.py

**Purpose**: Log run results and metrics to MLflow

**Location**: `skills/eval-mlflow/scripts/log_results.py`

**CLI Interface**:
```bash
python3 log_results.py --config eval.yaml --run-id <id>
```

**Arguments**:
- `--config` (default: `eval.yaml`): Path to eval config
- `--run-id` (required): Run ID to log

**Behavior**:
1. Load `EvalConfig` from YAML
2. Read `eval/runs/<run-id>/summary.yaml`
3. Read `eval/runs/<run-id>/run_result.json`
4. Call `setup_experiment(config.mlflow_experiment)`
5. Create MLflow run with `mlflow.start_run(run_name=run_id)`
6. Log parameters:
   - `skill`: from `config.skill` (eval.yaml)
   - `agent`: from `run_result.json["agent"]`
   - `model`: from config runtime overrides or eval.yaml
7. Log metrics:
   - For each judge: `{judge_name}_mean`, `{judge_name}_pass_rate`
   - `duration_s`, `cost_usd`, `total_tokens`
8. Set tags:
   - `regressions_detected`: "yes" or "no" (from summary.yaml)
   - `exit_code`: from run_result.json
9. Log artifacts:
   - `eval/runs/<run-id>/summary.yaml`
10. Print: MLflow UI link and summary

**Path Safety**: Use path validation to prevent directory traversal (similar to score.py's `_resolve_under()`)

**Key Constraints**:
- Use existing `setup_experiment()` helper
- Handle missing fields gracefully
- ~100 lines

### 3. attach_feedback.py

**Purpose**: Attach judge scores as feedback to MLflow traces

**Location**: `skills/eval-mlflow/scripts/attach_feedback.py`

**CLI Interface**:
```bash
python3 attach_feedback.py --config eval.yaml --run-id <id> --experiment <name>
```

**Arguments**:
- `--config` (default: `eval.yaml`): Path to eval config
- `--run-id` (required): Run ID
- `--experiment` (optional): Experiment name (default: from config)

**Behavior**:
1. Load `EvalConfig` from YAML
2. Read `eval/runs/<run-id>/summary.yaml` for per_case judge results
3. Use `mlflow.search_traces(experiment_ids=[...])` to find traces
4. For each trace:
   - Try to match case by trace tags (e.g., `tags.case_id`)
   - If match found, call `agent_eval.mlflow.experiment.log_feedback()` for each judge
5. Print: `"Attached feedback to N traces"`

**Key Constraints**:
- Use existing `log_feedback()` helper
- Graceful handling if no traces exist (print warning, exit 0)
- **Note**: Trace-to-case matching requires traces to be tagged with case_id during execution (future enhancement)
- ~70 lines

### 4. Update SKILL.md

**Changes**:
- **Step 3** (Sync Dataset): Replace inline python with:
  ```bash
  python3 ${CLAUDE_SKILL_DIR}/scripts/sync_dataset.py \\
      --config <config> \\
      --dataset-name <name>
  ```
- **Step 4** (Log Run Results): Replace inline python with:
  ```bash
  python3 ${CLAUDE_SKILL_DIR}/scripts/log_results.py \\
      --config <config> \\
      --run-id <run-id>
  ```
- **Step 5** (Attach Trace Feedback): Replace inline python with:
  ```bash
  python3 ${CLAUDE_SKILL_DIR}/scripts/attach_feedback.py \\
      --config <config> \\
      --run-id <run-id> \\
      --experiment <experiment>
  ```

## Non-Requirements

- ❌ No MLflow server management (already handled by existing utilities)
- ❌ No eval.yaml schema changes
- ❌ No new dependencies
- ❌ No GUI or interactive prompts
- ❌ No Docker/container integration

## Success Criteria

- [ ] All 3 scripts are executable and handle CLI args correctly
- [ ] Scripts use existing `agent_eval` modules (no duplication)
- [ ] SKILL.md calls scripts instead of inline Python
- [ ] Code style matches existing `skills/eval-run/scripts/` patterns
- [ ] No hardcoded field mappings - schema-driven
- [ ] Scripts are idempotent
- [ ] All linters pass (ruff, black)
- [ ] No security issues (no secrets, path traversal, injection)

## References

- Existing SKILL.md: `skills/eval-mlflow/SKILL.md`
- Config structure: `agent_eval/config.py`
- MLflow utilities: `agent_eval/mlflow/experiment.py`
- Scoring reference: `skills/eval-run/scripts/score.py`
- Execution reference: `skills/eval-run/scripts/execute.py`
