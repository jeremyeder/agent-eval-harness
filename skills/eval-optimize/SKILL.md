---
name: eval-optimize
description: Automated skill refinement loop. Runs eval, identifies failures, feeds failing traces and judge rationale back to fix SKILL.md, re-runs until all judges pass. Use when you want to automatically improve a skill based on eval results.
user-invocable: true
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Skill
---

Automated refinement loop for skills based on evaluation feedback.

## Usage

```
/eval-optimize [config_file] --model <model> [--max-iterations <N>]
```

## How It Works

This skill implements the refinement loop from the MLflow skill evaluation methodology:

1. **Run eval** — execute the configured skill against all test cases
2. **Score** — run all configured judges (code-based and LLM)
3. **Identify failures** — find cases where judges failed
4. **Fix** — for each failure, read the trace + judge rationale, identify what went wrong, and edit the SKILL.md to fix it
5. **Re-run** — re-run eval on failing cases to verify the fix
6. **Regression check** — verify previously passing cases still pass
7. **Repeat** — until all judges pass or max iterations reached

## Steps

1. Parse `$ARGUMENTS`:
   - Config file path (positional, default: `eval.yaml`)
   - `--model <model>` (required)
   - `--max-iterations <N>` (default: 3)
   - `--run-id <id>` (optional)

2. Read the eval config to understand which skill is being tested and what judges to use.

3. **Iteration loop** (up to max-iterations):

   a. Run eval by invoking the eval-run skill:
   ```
   Use the Skill tool to invoke /eval-run --config <config> --model <model> --run-id <id>-iter-<N> --score
   ```

   b. Parse results from `eval/runs/<id>-iter-<N>/summary.yaml`

   c. If all judges pass: done! Report success.

   d. If judges fail:
      - Read the failing cases' traces (from `eval/runs/<id>-iter-<N>/stdout.log`)
      - Read the judge rationale for each failure
      - Identify the skill file that needs fixing (from config.skill → `.claude/skills/<skill>/SKILL.md`)
      - Read the current SKILL.md
      - Analyze the failure: what did the skill do wrong? What should it do instead?
      - Edit the SKILL.md with a targeted fix
      - **Important**: the fix must be specific and grounded in the trace evidence, not a generic instruction

   e. After fixing, re-run eval to verify:
   ```
   Use the Skill tool to invoke /eval-run --config <config> --model <model> --run-id <id>-iter-<N+1> --score --baseline <id>-iter-<N>
   ```

   f. Check for regressions: if previously passing cases now fail, the fix introduced a regression. Revert and try a different approach.

4. Report final state:
   - Which judges pass/fail
   - What changes were made to SKILL.md
   - How many iterations were needed
   - Any remaining failures

## Rules

- **Never make broad, generic changes** to SKILL.md. Every edit must be grounded in a specific failure trace.
- **Check for regressions** after every fix. A fix that breaks other cases is not a fix.
- **Stop after max iterations** even if failures remain. Report what could not be fixed.
- **Do not modify test cases or judges**. The eval harness is the ground truth.

$ARGUMENTS
