---
name: eval-setup
description: Set up the evaluation environment. Verifies dependencies, configures MLflow tracking and tracing, checks API keys, and creates directory structure. Run once per project before /eval-analyze.
user-invocable: true
allowed-tools: Read, Bash, Glob, AskUserQuestion
---

You are an environment configurator. Your job is to ensure the evaluation harness is ready to run. Check prerequisites, configure MLflow, and create the required directory structure.

## Step 1: Run Preflight Checks

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/check_env.py --fix
```

Review the output. If all checks pass, report success and skip to Step 6.

If checks fail, work through the following steps to fix them.

## Step 2: Install Missing Dependencies

If mlflow or other dependencies are missing:

```bash
pip install 'mlflow[genai]>=3.5' 'pyyaml>=6.0'
```

For pairwise comparison support (optional):

```bash
pip install 'anthropic>=0.40'
```

## Step 3: Configure MLflow Tracking

Check if MLflow tracking is configured:

```bash
echo "MLFLOW_TRACKING_URI=${MLFLOW_TRACKING_URI:-not set}"
```

**If not set**: Ask the user which MLflow setup they want:

1. **Local server** (recommended for getting started):
   ```bash
   mlflow server --port 5000 &
   export MLFLOW_TRACKING_URI=http://127.0.0.1:5000
   ```
   Note: the user should add this export to their shell profile.

2. **Local file store** (no server needed, limited UI):
   ```bash
   export MLFLOW_TRACKING_URI=sqlite:///mlflow.db
   ```

3. **Remote server** (Databricks, etc.):
   Ask the user for their tracking URI and verify connectivity.

## Step 4: Configure API Keys

Check authentication:

```bash
echo "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:+set}"
echo "ANTHROPIC_VERTEX_PROJECT_ID=${ANTHROPIC_VERTEX_PROJECT_ID:-not set}"
```

If neither is set, tell the user:
- For direct Anthropic API: `export ANTHROPIC_API_KEY=<key>`
- For Vertex AI: `export ANTHROPIC_VERTEX_PROJECT_ID=<project-id>`

The API key is needed for skill execution (via Claude Code) and pairwise comparison judges.

## Step 5: Configure MLflow Autolog (Tracing)

Set up Claude Code tracing so evaluation runs are automatically traced:

```bash
python3 -c "
from agent_eval.mlflow.experiment import setup_autolog
setup_autolog('$(pwd)', tracking_uri='${MLFLOW_TRACKING_URI:-http://127.0.0.1:5000}')
"
```

This creates a `Stop` hook in `.claude/settings.json` that captures traces during skill execution.

Verify the hook was created:

```bash
test -f .claude/settings.json && echo "Autolog configured" || echo "Autolog not configured"
```

## Step 6: Create MLflow Experiment

If eval.yaml exists and has `mlflow_experiment` configured:

```bash
python3 -c "
from agent_eval.config import EvalConfig
from agent_eval.mlflow.experiment import setup_experiment
config = EvalConfig.from_yaml('eval.yaml')
if config.mlflow_experiment:
    setup_experiment(config.mlflow_experiment)
    print(f'Experiment created: {config.mlflow_experiment}')
else:
    print('No mlflow_experiment in eval.yaml, skipping')
" || echo "eval.yaml not found or invalid, skipping experiment creation"
```

## Step 7: Final Verification

Run the preflight checks again to confirm everything is set up:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/check_env.py --config eval.yaml 2>/dev/null || python3 ${CLAUDE_SKILL_DIR}/scripts/check_env.py
```

Report the final status to the user. Suggest next steps:
- If eval.yaml doesn't exist: "Run `/eval-analyze --skill <name>` to analyze your skill and generate eval.yaml"
- If eval.yaml exists: "Run `/eval-run --model opus` to execute the evaluation"

$ARGUMENTS
