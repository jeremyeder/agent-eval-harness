---
name: eval-mlflow
description: MLflow integration for evaluation — sync datasets, log run results, and attach judge feedback to traces. Reads eval.yaml schemas to understand case structure.
user-invocable: true
allowed-tools: Read, Bash, Glob, Grep, AskUserQuestion
---

You are an MLflow integration agent. Your job is to bridge the evaluation harness with MLflow — syncing datasets, logging results, and attaching feedback to traces. You read eval.yaml to understand the data structure.

## Step 0: Parse Arguments

Parse `$ARGUMENTS` for:
- `--action <sync-dataset|log-results|all>` (default: `all`)
- `--config <path>` (eval.yaml path, default: `eval.yaml`)
- `--run-id <id>` (required for `log-results`)

## Step 1: Verify MLflow

Check MLflow is configured:

```bash
python3 -c "
from agent_eval.mlflow.experiment import ensure_server
if ensure_server():
    print('MLflow server: OK')
else:
    print('MLflow server: not running')
import os
print(f'MLFLOW_TRACKING_URI={os.environ.get(\"MLFLOW_TRACKING_URI\", \"not set\")}')
"
```

If not configured, suggest running `/eval-setup` first.

## Step 2: Read Configuration

Read eval.yaml to understand:
- `mlflow_experiment` — the experiment name
- `dataset.path` and `dataset.schema` — where cases are and what they look like
- `outputs[*].schema` — what the skill produces
- `judges` — what was scored

## Step 3: Sync Dataset (if `--action sync-dataset` or `all`)

Sync evaluation cases to MLflow dataset:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/sync_dataset.py \
    --config eval.yaml \
    --dataset-name "${mlflow_experiment}-dataset"
```

The script reads `dataset.schema` from eval.yaml and browses case directories at `dataset.path`. For each case, it classifies files as inputs vs expectations using a naming heuristic (input*/prompt* → inputs, expected*/reference* → expectations) and syncs to MLflow.

## Step 4: Log Run Results (if `--action log-results` or `all`)

Log run results to MLflow:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/log_results.py \
    --config eval.yaml \
    --run-id <run_id>
```

The script reads `summary.yaml` and `run_result.json` from the run directory, then logs:
- **Parameters**: skill, agent (runner), model
- **Metrics**: judge scores (mean/pass_rate), duration, cost, tokens
- **Tags**: regressions_detected, exit_code
- **Artifacts**: summary.yaml

## Step 5: Attach Trace Feedback (if traces exist)

If MLflow tracing was enabled during the eval run, attach judge feedback to traces:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/attach_feedback.py \
    --config eval.yaml \
    --run-id <run_id> \
    --experiment <experiment_name>
```

The script searches for traces in the experiment and attempts to match them to cases by `case_id` tags. For matched traces, it attaches judge scores as feedback.

**Note**: This requires traces to be tagged with `case_id` during execution. If no traces are found or traces lack case_id tags, the script will warn and exit gracefully (this is expected until case_id tagging is added to the runner).

## Step 6: Report

Print summary:
- Dataset: synced N cases to MLflow dataset '<name>'
- Results: logged to experiment '<name>', run '<run_id>'
- Traces: attached feedback to N traces
- MLflow UI: <tracking_uri>

## Rules

- **Read the schema** — understand `dataset.schema` and `outputs[*].schema` to interpret case structure
- **No hardcoded fields** — determine what's an input vs reference by reading the schema descriptions
- **Graceful degradation** — if MLflow is not configured or unreachable, warn and skip (don't fail)
- **Idempotent** — safe to run multiple times

$ARGUMENTS
