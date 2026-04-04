# Tasks: eval-mlflow Backend Implementation

**Plan**: PLAN-eval-mlflow-backend.md  
**Status**: Ready for implementation

## Task Breakdown

### Setup

- [X] Create spec document (SPEC-eval-mlflow-backend.md)
- [X] Create plan document (PLAN-eval-mlflow-backend.md)
- [ ] Create `skills/eval-mlflow/scripts/` directory

### Implementation: sync_dataset.py

- [ ] Create `skills/eval-mlflow/scripts/sync_dataset.py` file
- [ ] Add shebang and module docstring with usage
- [ ] Import dependencies (argparse, sys, Path, yaml, mlflow, EvalConfig)
- [ ] Add `_resolve_under()` helper for path safety (from score.py pattern)
- [ ] Implement `load_case(case_dir, config)` function
  - [ ] Validate case_dir with path safety check
  - [ ] Read all files in case directory (validate each path)
  - [ ] Classify files by naming heuristic:
    - [ ] `input*`, `prompt*` → inputs
    - [ ] `expected*`, `reference*` → expectations
    - [ ] All others → inputs
  - [ ] Return dict with `{"inputs": {...}, "expectations": {...}}`
- [ ] Implement `main()` function
  - [ ] Parse CLI arguments (--config, --dataset-name)
  - [ ] Load EvalConfig from YAML (validate path)
  - [ ] Call setup_experiment()
  - [ ] Browse dataset_path for case directories (validate paths)
  - [ ] Load each case with load_case()
  - [ ] Get or create MLflow dataset
  - [ ] Merge records into dataset
  - [ ] Print summary (N cases synced)
- [ ] Add error handling for missing config/paths
- [ ] Add `if __name__ == "__main__": main()`

### Implementation: log_results.py

- [ ] Create `skills/eval-mlflow/scripts/log_results.py` file
- [ ] Add shebang and module docstring with usage
- [ ] Import dependencies (argparse, sys, Path, json, yaml, mlflow, EvalConfig)
- [ ] Implement `main()` function
  - [ ] Parse CLI arguments (--config, --run-id)
  - [ ] Load EvalConfig from YAML
  - [ ] Call setup_experiment()
  - [ ] Validate and load summary.yaml from eval/runs/<run-id>/
  - [ ] Validate and load run_result.json from eval/runs/<run-id>/
  - [ ] Start MLflow run with mlflow.start_run(run_name=run_id)
  - [ ] Log parameters:
    - [ ] `skill` from config.skill (eval.yaml)
    - [ ] `agent` from run_result.json["agent"] (not "runner")
    - [ ] `model` from config
  - [ ] Log metrics (judge means/pass_rates, duration_s, cost_usd, tokens)
  - [ ] Set tags (regressions_detected from summary, exit_code from run_result)
  - [ ] Log artifact (summary.yaml)
  - [ ] Print summary with MLflow UI link
- [ ] Add error handling for missing files
- [ ] Handle missing/optional fields gracefully
- [ ] Add `if __name__ == "__main__": main()`

### Implementation: attach_feedback.py

- [ ] Create `skills/eval-mlflow/scripts/attach_feedback.py` file
- [ ] Add shebang and module docstring with usage
- [ ] Import dependencies (argparse, sys, Path, yaml, mlflow, log_feedback)
- [ ] Implement `main()` function
  - [ ] Parse CLI arguments (--config, --run-id, --experiment)
  - [ ] Load EvalConfig from YAML
  - [ ] Determine experiment name (from args or config.mlflow_experiment)
  - [ ] Get MLflow experiment by name
  - [ ] Validate and load summary.yaml per_case results
  - [ ] Try to search for traces with mlflow.search_traces()
  - [ ] For each trace found:
    - [ ] Try to extract case_id from trace tags (tags.case_id)
    - [ ] If match found in per_case results, call log_feedback() for each judge
  - [ ] Print summary (N traces found, N feedback attached)
  - [ ] If no traces: print warning, exit 0 (graceful)
  - [ ] If traces but no case_id tags: print warning, exit 0 (expected until tagging added)
- [ ] Add error handling for missing experiment/traces
- [ ] Graceful handling if no traces found (print warning, exit 0)
- [ ] Add `if __name__ == "__main__": main()`

### Update SKILL.md

- [ ] Read current SKILL.md
- [ ] Replace Step 3 inline python block with sync_dataset.py call
- [ ] Replace Step 4 inline python block with log_results.py call
- [ ] Replace Step 5 inline python block with attach_feedback.py call
- [ ] Verify variable interpolation (${CLAUDE_SKILL_DIR}, etc.)
- [ ] Maintain existing formatting and structure

### Quality Assurance

- [ ] Run `ruff check skills/eval-mlflow/scripts/` and fix issues
- [ ] Run `black skills/eval-mlflow/scripts/` for formatting
- [ ] Verify all imports are available
- [ ] Check for path traversal vulnerabilities
- [ ] Check for command injection vulnerabilities
- [ ] Check for hardcoded secrets
- [ ] Verify error messages are clear
- [ ] Verify CLI help text is accurate

### Testing

- [ ] Test sync_dataset.py with minimal eval.yaml
- [ ] Test log_results.py with sample run data
- [ ] Test attach_feedback.py (may skip if no traces available)
- [ ] Verify scripts exit with correct codes
- [ ] Verify output messages are clear and helpful

### Documentation

- [ ] Verify docstrings are complete
- [ ] Verify CLI help is accurate
- [ ] Check SKILL.md examples work

## Task Order

1. Setup (create directory)
2. Implement scripts in parallel (independent)
3. Update SKILL.md (depends on scripts)
4. Quality assurance (all scripts)
5. Testing (validation)

## Acceptance Criteria

- [ ] All scripts are executable (`chmod +x`)
- [ ] All scripts have proper shebang
- [ ] All scripts pass linters (ruff, black)
- [ ] No security issues detected
- [ ] SKILL.md updated correctly
- [ ] All tasks marked complete
- [ ] Changes committed

## Notes

- Scripts are independent and can be implemented in parallel
- Use existing patterns from `skills/eval-run/scripts/score.py`
- Graceful degradation if MLflow unavailable
- Clear error messages to stderr
- Success messages to stdout
