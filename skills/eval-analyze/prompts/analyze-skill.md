You are analyzing a Claude Code skill to understand what it does, what inputs it expects, and what artifacts it produces. This analysis will be used to generate an eval.yaml configuration.

Read the skill file and any supporting files it references (prompts, templates, scripts). Also examine any existing test cases or dataset directories to understand the expected case structure.

Report your findings as structured YAML between ```yaml markers, followed by a narrative explanation.

## Analysis Structure

```yaml
purpose: "<one sentence describing what this skill does>"

inputs:
  description: |
    <natural language description of what the skill expects as input —
     how cases are structured, what files or fields they contain>
  invocation: "<how the skill is invoked: /skill-name args>"

outputs:
  - path: "<directory where the skill writes outputs>"
    description: |
      <natural language description of what the skill produces in
       this directory — file types, naming patterns, content structure>

flags:
  supported:
    - "--flag: what it does"
  headless: <true|false>   # can run without user interaction
  dry_run: <true|false>    # can skip external writes

pipeline:
  - step: "<what happens first>"
  - step: "<what happens next>"

quality_criteria:
  deterministic:
    - "<things that can be checked with code>"
  llm_judgment:
    - "<things that need LLM assessment>"

suggested_judges:
  - name: "<judge name>"
    type: "<check|llm>"
    description: |
      <what this judge evaluates and how>
    # For check type, include example inline script:
    check: |
      <python snippet example>
    # For llm type, include evaluation prompt sketch:
    prompt: |
      <evaluation instructions sketch>
```

## Narrative

After the YAML block, explain:
1. How the skill's pipeline flows (what happens in what order)
2. What a "good" output looks like vs a "bad" one
3. Any edge cases or failure modes you noticed
4. What evaluation criteria would be most valuable

Be thorough but concise. Focus on information that helps configure an evaluation harness. Reference actual file paths and field names you observed — don't invent generic examples.
