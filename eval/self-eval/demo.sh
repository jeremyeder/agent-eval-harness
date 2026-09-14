#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
PYTHON="$REPO_ROOT/.venv/bin/python"
CONFIG="$REPO_ROOT/eval/eval-analyze/eval.yaml"
TRACKING_URI="${MLFLOW_TRACKING_URI:-http://127.0.0.1:5000}"
EXPERIMENT="${AGENT_EVAL_DEMO_EXPERIMENT:-eval-analyze}"
MODEL="${AGENT_EVAL_DEMO_MODEL:-gpt-5.6-luna}"
RUN_ID="${AGENT_EVAL_DEMO_RUN_ID:-$(date +%Y%m%d-%H%M%S)-demo}"
OUTPUT="$REPO_ROOT/eval/runs/eval-analyze/$RUN_ID"
LOG_DIR=$(mktemp -d "${TMPDIR:-/tmp}/agent-eval-demo.XXXXXX")
WORKSPACE=""
RUN_URL=""

cleanup() {
    if [[ "${DEMO_FAILED:-0}" == "0" ]]; then
        rm -rf "$LOG_DIR"
    fi
}
trap cleanup EXIT

fail() {
    DEMO_FAILED=1
    printf '\nERROR: %s\n' "$1" >&2
    printf 'Logs: %s\n' "$LOG_DIR" >&2
    printf 'Run output: %s\n' "$OUTPUT" >&2
    exit 1
}

run_step() {
    local name=$1
    shift
    if ! "$@" >"$LOG_DIR/$name.log" 2>&1; then
        printf '      status: FAILED\n'
        fail "$name failed"
    fi
}

if [[ ! -x "$PYTHON" ]]; then
    fail "missing Python environment at $PYTHON"
fi
if [[ ! -f "$CONFIG" ]]; then
    fail "missing evaluation config at $CONFIG"
fi

export MLFLOW_TRACKING_URI="$TRACKING_URI"
unset MLFLOW_EXPERIMENT_ID MLFLOW_EXPERIMENT_NAME

printf '[1/7] Checking MLflow server\n'
MLFLOW_VERSION=$(curl -fsS "$TRACKING_URI/version" 2>"$LOG_DIR/mlflow-version-error" || true)
if [[ -z "$MLFLOW_VERSION" ]]; then
    fail "MLflow server is not reachable at $TRACKING_URI"
fi
printf '      using MLflow server at %s (version %s)\n' "$TRACKING_URI" "$MLFLOW_VERSION"
printf '      status: complete\n'

printf '[2/7] Preparing evaluation workspace\n'
run_step workspace \
    "$PYTHON" "$REPO_ROOT/skills/eval-run/scripts/workspace.py" \
    --config "$CONFIG" \
    --run-id "$RUN_ID"
WORKSPACE=$(awk '/^WORKSPACE: / {print $2}' "$LOG_DIR/workspace.log" | tail -1)
if [[ -z "$WORKSPACE" ]]; then
    fail "workspace path was not produced"
fi
printf '      workspace: %s\n' "$WORKSPACE"
printf '      status: complete\n'

printf '[3/7] Running three Codex cases\n'
printf '      cases: external-state, local-only, nested-skill\n'
run_step execute \
    "$PYTHON" "$REPO_ROOT/skills/eval-run/scripts/execute.py" \
    --config "$CONFIG" \
    --workspace "$WORKSPACE" \
    --skill eval-analyze \
    --model "$MODEL" \
    --agent codex \
    --mlflow-experiment "$EXPERIMENT" \
    --output "$OUTPUT" \
    --run-id "$RUN_ID"
if [[ -f "$OUTPUT/run_result.json" ]]; then
    "$PYTHON" - "$OUTPUT/run_result.json" <<'PY'
import json
import sys

data = json.loads(open(sys.argv[1], encoding="utf-8").read())
for case_id, result in data.get("per_case", {}).items():
    status = "OK" if result.get("exit_code") == 0 else "FAILED"
    print(f"      {case_id}: {status}")
PY
fi
printf '      status: complete\n'

printf '[4/7] Collecting generated eval.yaml files\n'
run_step collect \
    "$PYTHON" "$REPO_ROOT/skills/eval-run/scripts/collect.py" \
    --config "$CONFIG" \
    --workspace "$WORKSPACE" \
    --output "$OUTPUT"
while IFS= read -r generated; do
    printf '      %s\n' "${generated#"$OUTPUT/"}"
done < <(find "$OUTPUT/cases" -path '*/eval.yaml/eval.yaml' -type f -print | sort)
printf '      status: complete\n'

printf '[5/7] Scoring with MLflow Guidelines\n'
run_step score \
    "$PYTHON" "$REPO_ROOT/skills/eval-run/scripts/score.py" judges \
    --config "$CONFIG" \
    --run-id "$RUN_ID" \
    --workspace "$WORKSPACE" \
    --model "$MODEL"
if [[ -f "$OUTPUT/summary.yaml" ]]; then
    "$PYTHON" - "$OUTPUT/summary.yaml" <<'PY'
import sys
import yaml

data = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
for name, result in (data.get("judges") or {}).items():
    rate = result.get("pass_rate")
    scored = result.get("scored_cases")
    if isinstance(rate, (int, float)):
        print(f"      {name}: {rate:.1%} pass ({scored} cases)")
    else:
        print(f"      {name}: no aggregate score ({scored} cases)")
PY
fi
printf '      status: complete\n'

printf '[6/7] Publishing the MLflow evaluation run\n'
run_step log-results \
    "$PYTHON" "$REPO_ROOT/skills/eval-mlflow/scripts/log_results.py" \
    --config "$CONFIG" \
    --run-id "$RUN_ID"
RUN_URL=$(grep -Eo 'https?://[^[:space:]]+/#/experiments/[0-9]+/runs/[[:alnum:]-]+' \
    "$LOG_DIR/log-results.log" | tail -1 || true)
printf '      run: %s\n' "$RUN_ID"
printf '      status: complete\n'

printf '[7/7] Attaching judge assessments\n'
run_step attach-feedback \
    "$PYTHON" "$REPO_ROOT/skills/eval-mlflow/scripts/attach_feedback.py" \
    --config "$CONFIG" \
    --run-id "$RUN_ID" \
    --source judge
grep -E '^TRACES:|^FEEDBACK:' "$LOG_DIR/attach-feedback.log" |
    sed 's/^/      /' || true
printf '      status: complete\n'

if [[ -z "$RUN_URL" ]]; then
    fail "MLflow run URL was not produced"
fi

printf '\nComplete.\n'
printf 'MLflow run: %s\n' "$RUN_URL"
