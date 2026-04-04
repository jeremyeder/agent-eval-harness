# Tasks: RFE-Creator Price-Performance Evaluation

**Input**: Design documents from `/specs/001-rfe-eval-pareto/`
**Prerequisites**: plan.md (required), spec.md (required)

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Merge eval harness code, extend env allowlist, add dependencies

- [X] T001 [US4] Merge pr-01 branch into working branch so eval harness code is on disk
- [X] T002 [US4] Extend `_SAFE_ENV_KEYS` in `agent_eval/agent/claude_code.py` to add JIRA_SERVER, JIRA_USER, JIRA_TOKEN, RFE_MODEL, RFE_MODEL_CONFIG, GITHUB_TOKEN
- [X] T003 [US4] Add mlflow-export-import to optional dependencies in `pyproject.toml`
- [X] T004 [US4] Install agent-eval-harness package: `pip install -e .[anthropic]`

**Checkpoint**: Eval harness code available and importable ✓

---

## Phase 2: Model Parameterization (US4)

**Goal**: Remove hardcoded model: opus so eval runner controls model selection

- [X] T005 [P] [US4] Remove `model: opus` from frontmatter in `/workspace/repos/rfe-creator/.claude/skills/rfe-feasibility-review/SKILL.md`
- [X] T006 [P] [US4] Remove `model: opus` from frontmatter in `/workspace/repos/rfe-creator/.claude/skills/architecture-review/SKILL.md`
- [X] T007 [P] [US4] Remove `model: opus` from frontmatter in `/workspace/repos/rfe-creator/.claude/skills/feasibility-review/SKILL.md`
- [X] T008 [P] [US4] Remove `model: opus` from frontmatter in `/workspace/repos/rfe-creator/.claude/skills/scope-review/SKILL.md`
- [X] T009 [P] [US4] Remove `model: opus` from frontmatter in `/workspace/repos/rfe-creator/.claude/skills/testability-review/SKILL.md`
- [X] T010 [US4] Remove `model: opus` from ~7 inline Agent launch instructions in `/workspace/repos/rfe-creator/.claude/skills/rfe.review/SKILL.md`
- [X] T011 [US4] Remove `model: opus` from inline Agent launch instruction in `/workspace/repos/rfe-creator/.claude/skills/rfe.split/SKILL.md`

**Checkpoint**: All model references removed, eval runner can control model uniformly ✓

---

## Phase 3: User Story 1 - Run Evaluation Matrix (Priority: P1)

**Goal**: Orchestrate 18 isolated runs with workspace creation, execution, collection, scoring

**Independent Test**: Run with 1 model, 1 RFE, 1 rep to validate end-to-end

- [X] T012 [P] [US1] Create eval dataset: `/workspace/repos/rfe-creator/eval/dataset/cases/RHAIRFE-1473/input.yaml`
- [X] T013 [P] [US1] Create eval dataset: `/workspace/repos/rfe-creator/eval/dataset/cases/RHAIRFE-1429/input.yaml`
- [X] T014 [P] [US1] Create eval dataset: `/workspace/repos/rfe-creator/eval/dataset/cases/RHAIRFE-1161/input.yaml`
- [X] T015 [US1] Create `/workspace/repos/rfe-creator/eval.yaml` with skill, outputs, judges config
- [X] T016 [US1] Create `/workspace/repos/rfe-creator/eval/judges/__init__.py`
- [X] T017 [US1] Create `/workspace/repos/rfe-creator/eval/judges/frontmatter_judges.py` with score extraction functions
- [X] T018 [US1] Create `/workspace/repos/rfe-creator/eval/test_plan.yaml` with models, cases, repetitions
- [X] T019 [US1] Create `/workspace/repos/rfe-creator/eval/scripts/run_matrix.py` — orchestrate workspace→execute→collect→score per run

**Checkpoint**: run_matrix.py can execute a single run and produce run_result.json + summary.yaml ✓

---

## Phase 4: User Story 2 - Generate A:B Comparison (Priority: P2)

**Goal**: ETL + comparison producing machine-parsable outputs

- [X] T020 [US2] Create `/workspace/repos/rfe-creator/eval/scripts/etl_loader.py` — walk runs, produce records.json and pareto.csv
- [X] T021 [US2] Create `/workspace/repos/rfe-creator/eval/scripts/compare.py` — read records.json, produce comparison.json

**Checkpoint**: Given completed runs, comparison.json has quality, cost, efficiency sections ✓

---

## Phase 5: User Story 3 - MLflow Integration (Priority: P2)

**Goal**: Log to MLflow and export for portability

- [X] T022 [US3] Add MLflow logging to etl_loader.py — log params, metrics, artifacts per run
- [X] T023 [US3] Add mlflow-export-import export step to etl_loader.py

**Checkpoint**: Results visible in MLflow UI and exportable ✓

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Model Param)**: Independent of Phase 1 (different repo), can run in parallel
- **Phase 3 (US1)**: Depends on Phase 1 (needs eval harness importable) and Phase 2 (needs model param for multi-model runs)
- **Phase 4 (US2)**: Depends on Phase 3 (needs run output structure defined)
- **Phase 5 (US3)**: Depends on Phase 4 (extends etl_loader.py)

### Within Phase 3

- T012-T014 (dataset) are parallel, no deps
- T015 (eval.yaml) after dataset exists
- T016-T017 (judges) after eval.yaml
- T018 (test_plan) parallel with T016-T017
- T019 (run_matrix) depends on all above
