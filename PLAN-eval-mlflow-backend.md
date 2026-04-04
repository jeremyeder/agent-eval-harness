# Implementation Plan: eval-mlflow Backend

**Status**: Draft  
**Spec**: SPEC-eval-mlflow-backend.md  
**Branch**: 001-rfe-eval-pareto

## File Structure

```
skills/eval-mlflow/
├── SKILL.md                          # [UPDATE] Replace inline python
├── scripts/                          # [CREATE]
│   ├── sync_dataset.py              # [CREATE] ~80 lines
│   ├── log_results.py               # [CREATE] ~100 lines
│   └── attach_feedback.py           # [CREATE] ~70 lines
```

## Dependencies

### Imports

All scripts will use:
- `argparse` - CLI argument parsing
- `sys`, `os` - System utilities
- `pathlib.Path` - Path manipulation
- `yaml` - Config and summary parsing
- `json` - run_result.json parsing
- `agent_eval.config.EvalConfig` - Config loading
- `agent_eval.mlflow.experiment` - MLflow utilities

Script-specific:
- **sync_dataset.py**: `mlflow`, `mlflow.genai.datasets`
- **log_results.py**: `mlflow`
- **attach_feedback.py**: `mlflow`, `agent_eval.mlflow.experiment.log_feedback`

### External Dependencies

All already satisfied:
- `mlflow[genai]>=3.5` ✓
- `pyyaml` ✓
- `anthropic` (for client, if needed) ✓

## Implementation Order

1. **Create scripts directory**
2. **Implement sync_dataset.py** (independent)
3. **Implement log_results.py** (independent)
4. **Implement attach_feedback.py** (independent)
5. **Update SKILL.md** (depends on all scripts)

## Design Decisions

### 1. Schema Interpretation

**Decision**: Defer to LLM for schema interpretation (future enhancement)

**Rationale**: The spec says "no hardcoded field mappings" and "schema-driven." However, implementing full NL schema interpretation requires an LLM call. For this iteration, we'll use a simple heuristic:
- Files matching `input*` or `prompt*` → inputs
- Files matching `expected*` or `reference*` → expectations
- All other files → inputs

**Future**: Add LLM-based schema interpretation similar to how judges work.

### 2. Error Handling

**Strategy**: Fail fast with clear error messages

- Missing config file → print error, exit 1
- Missing run directory → print error, exit 1
- MLflow connection issues → print warning, exit 0 (graceful)
- Missing traces → print "0 traces found", exit 0

**Rationale**: Evaluation harness should continue even if MLflow is unavailable.

### 3. MLflow Experiment Setup

**Pattern**: Use existing `setup_experiment()` helper

```python
from agent_eval.mlflow.experiment import setup_experiment

setup_experiment(config.mlflow_experiment)
```

This handles both creating and setting the experiment.

### 4. Run Name vs Run ID

**Decision**: Use `run_name=<run-id>` in `mlflow.start_run()`

**Rationale**: Makes it easy to find runs in MLflow UI by run-id.

### 5. Trace Matching

**Strategy**: Match traces by case_id in trace tags/request_metadata

```python
traces = mlflow.search_traces(
    experiment_ids=[experiment_id],
    filter_string=f"tags.case_id = '{case_id}'",
)
```

**Fallback**: If no case_id tags, skip trace feedback (print warning).

## Implementation Details

### sync_dataset.py

```python
#!/usr/bin/env python3
"""Sync evaluation cases to MLflow dataset.

Usage:
    python3 sync_dataset.py --config eval.yaml --dataset-name my-dataset
"""

import argparse
import sys
from pathlib import Path

import mlflow
from mlflow.genai.datasets import create_dataset, get_dataset

from agent_eval.config import EvalConfig
from agent_eval.mlflow.experiment import setup_experiment


def load_case(case_dir: Path, config: EvalConfig) -> dict:
    """Load a case directory into an MLflow record.
    
    Returns:
        {"inputs": {...}, "expectations": {...}}
    """
    # Read all files
    # Classify by naming heuristic
    # Return structured record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="eval.yaml")
    parser.add_argument("--dataset-name", required=True)
    args = parser.parse_args()
    
    config = EvalConfig.from_yaml(args.config)
    setup_experiment(config.mlflow_experiment)
    
    # Browse dataset_path
    # Load each case
    # Sync to MLflow dataset
    # Print summary
```

**Size estimate**: 80 lines

### log_results.py

```python
#!/usr/bin/env python3
"""Log evaluation run results to MLflow.

Usage:
    python3 log_results.py --config eval.yaml --run-id run-20260404-1234
"""

import argparse
import json
import sys
from pathlib import Path

import mlflow
import yaml

from agent_eval.config import EvalConfig
from agent_eval.mlflow.experiment import setup_experiment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="eval.yaml")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    
    config = EvalConfig.from_yaml(args.config)
    setup_experiment(config.mlflow_experiment)
    
    # Load summary.yaml
    # Load run_result.json
    # Start MLflow run
    # Log params, metrics, tags, artifacts
    # Print summary with UI link
```

**Size estimate**: 100 lines

### attach_feedback.py

```python
#!/usr/bin/env python3
"""Attach judge feedback to MLflow traces.

Usage:
    python3 attach_feedback.py --config eval.yaml --run-id <id> --experiment <name>
"""

import argparse
import sys
from pathlib import Path

import mlflow
import yaml

from agent_eval.config import EvalConfig
from agent_eval.mlflow.experiment import log_feedback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="eval.yaml")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--experiment", default=None)
    args = parser.parse_args()
    
    config = EvalConfig.from_yaml(args.config)
    experiment = args.experiment or config.mlflow_experiment
    
    # Get experiment ID
    # Search traces
    # Load per_case results from summary
    # Match and attach feedback
    # Print summary
```

**Size estimate**: 70 lines

### SKILL.md Updates

Replace Step 3, 4, 5 inline python blocks with script calls:

**Step 3**:
```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/sync_dataset.py \
    --config eval.yaml \
    --dataset-name "${mlflow_experiment}-dataset"
```

**Step 4**:
```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/log_results.py \
    --config eval.yaml \
    --run-id <run_id>
```

**Step 5**:
```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/attach_feedback.py \
    --config eval.yaml \
    --run-id <run_id> \
    --experiment <experiment_name>
```

## Code Style Guidelines

Follow existing patterns from `skills/eval-run/scripts/score.py`:

1. **Shebang**: `#!/usr/bin/env python3`
2. **Docstring**: Module-level with usage example
3. **Imports**: Grouped (stdlib, third-party, local)
4. **Error handling**: Print to stderr, exit with codes
5. **Path safety**: Use `Path.resolve()`, check `is_relative_to()`
6. **Print style**: Descriptive messages to stdout, errors to stderr

## Testing Strategy

### Manual Testing

After implementation, test with:

```bash
# Setup test eval
cd /tmp/test-eval
# Create minimal eval.yaml

# Test sync_dataset
python3 skills/eval-mlflow/scripts/sync_dataset.py \
    --config eval.yaml \
    --dataset-name test-dataset

# Test log_results (requires a completed run)
python3 skills/eval-mlflow/scripts/log_results.py \
    --config eval.yaml \
    --run-id test-run-001

# Test attach_feedback
python3 skills/eval-mlflow/scripts/attach_feedback.py \
    --config eval.yaml \
    --run-id test-run-001
```

### Validation

- Run `ruff check` on all scripts
- Run `black --check` on all scripts
- Verify no security issues (path traversal, injection)
- Check imports are available

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| MLflow API changes | Use stable `mlflow[genai]>=3.5` API, minimal usage |
| Schema interpretation too simplistic | Document limitation, plan for LLM enhancement |
| Trace matching fails | Graceful degradation, clear error messages |
| Missing traces | Exit 0 with warning (expected in some cases) |
| Path traversal vulnerabilities | Use `Path.resolve()` and `is_relative_to()` checks |

## Out of Scope

- MLflow server lifecycle management (use existing `ensure_server()`)
- Dataset versioning (MLflow handles this)
- Complex schema interpretation (future enhancement)
- Web UI or interactive prompts
- Configuration validation beyond basic file existence

## Next Steps

1. Create `skills/eval-mlflow/scripts/` directory
2. Implement scripts in order (sync → log → attach)
3. Update SKILL.md
4. Run linters
5. Security review
6. Commit

## References

- Spec: SPEC-eval-mlflow-backend.md
- MLflow Datasets: https://mlflow.org/docs/latest/llms/genai-datasets/index.html
- MLflow Tracing: https://mlflow.org/docs/latest/llms/tracing/index.html
