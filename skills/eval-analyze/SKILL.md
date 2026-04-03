---
name: eval-analyze
description: Analyze a skill and generate eval.yaml. Examines the target skill's structure, discovers test cases, and produces the evaluation configuration with dataset schema, output descriptions, and suggested judges.
user-invocable: true
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent, AskUserQuestion
---

You are an evaluation bootstrapper. Your job is to deeply analyze a target skill and produce `eval.yaml` — the configuration that `/eval-run` needs to execute evaluations. You examine the skill, find test cases, and generate everything.

## Step 0: Parse Arguments

Parse `$ARGUMENTS` for:
- `--skill <name>` (which skill to analyze — optional if only one skill exists)
- `--config <path>` (eval.yaml path, default: `eval.yaml`)
- `--update` (update existing eval.yaml rather than overwriting)

```bash
mkdir -p tmp
python3 -m agent_eval.state init tmp/analyze-config.yaml skill=<skill> config=<config> update=<true/false>
```

## Step 1: Discover Skills

If `--skill` was not provided, discover available skills:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/discover.py skills
```

If multiple skills found, ask the user which to analyze. If only one, use it.

## Step 2: Check Existing Config

Check if eval.yaml already exists:

```bash
test -f <config> && echo "CONFIG_EXISTS" || echo "NO_CONFIG"
```

**If exists and `--update` not set**: Validate it:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/discover.py config <config>
```

If valid, check eval.md freshness:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/discover.py check-eval-md eval.md
```

If eval.md is fresh and eval.yaml is complete (has `dataset`, `outputs`, `judges`), report that config is up to date and exit.

**If no config or `--update`**: Proceed to full analysis.

## Step 3: Analyze Target Skill

Launch an Explore agent to analyze the target skill. Read the prompt template at `${CLAUDE_SKILL_DIR}/prompts/analyze-skill.md` and use it as the agent's instructions, substituting the actual skill file path.

The agent should read:
- The SKILL.md file
- Any scripts or prompts the skill references
- Any existing test cases or dataset directories

The agent returns structured YAML + narrative describing the skill's inputs, outputs, pipeline, and quality criteria.

## Step 4: Explore Dataset

Look for existing test cases by searching the project:

```bash
find . -name "*.yaml" -path "*/cases/*" -o -name "*.json" -path "*/cases/*" | head -20
find . -type d -name "cases" | head -10
```

If test cases exist, read one sample case to understand its structure — what files it contains, what fields are in each file. This informs the `dataset.schema` description.

If no test cases exist, note this in the eval.yaml as a comment and suggest what the user should create based on the skill analysis.

## Step 5: Generate eval.yaml

Using the analysis from Step 3 and dataset exploration from Step 4, generate a complete `eval.yaml`:

```yaml
name: <project-name>
description: <what is being evaluated>
skill: <skill-name>
runner: claude-code

dataset:
  path: <discovered cases path, or suggested path>
  schema: |
    <natural language description of case structure — describe what
     you actually observed in the sample case, including file names,
     field names, and what each contains. Be specific.>

outputs:
  - path: <output directory from skill analysis>
    schema: |
      <natural language description of what the skill produces —
       describe file types, naming patterns, content structure.
       Include what to skip if relevant.>

judges:
  <generate judges based on the quality_criteria from the analysis:
   - inline check judges for deterministic criteria
   - LLM judges for quality criteria
   each judge should have a name and description>

thresholds:
  <suggested thresholds for each judge>
```

The `dataset.schema` and `outputs[*].schema` fields are critical — they must describe the actual structure you observed, not generic placeholders. These descriptions drive the entire pipeline.

If `--update`: Read existing eval.yaml first, preserve user customizations, only fill in missing sections.

## Step 6: Generate eval.md

Read the template at `${CLAUDE_SKILL_DIR}/prompts/generate-eval-md.md`. Write eval.md with:
- YAML frontmatter: skill name, analyzed_at timestamp, skill_hash (MD5 prefix of SKILL.md)
- Markdown body: skill analysis narrative

## Step 7: Report

Print a summary:
- eval.yaml: created/updated with N judges, dataset at <path>
- eval.md: skill analysis cached
- Next step: run `/eval-run --model <model>` to execute the evaluation

## Rules

- **Observe, don't assume** — describe what you actually find in the skill and dataset, not what you think should be there
- **Be specific in schemas** — reference actual field names, file names, and patterns you observed
- **Generate useful judges** — inline checks for structure/validity, LLM judges for quality
- **Preserve user work** — when updating, don't overwrite sections the user customized

$ARGUMENTS
