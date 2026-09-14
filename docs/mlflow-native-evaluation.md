# MLflow-native evaluation backend

Agent Eval Harness keeps execution and evaluation as separate planes.

- The harness owns workspace preparation, agent execution, artifact collection,
  and orchestration.
- MLflow can own native evaluation datasets, runs, traces, scorer feedback,
  and human-review evidence.

This is an additive integration. Existing judge defaults and
`BuiltinJudgeRegistry` behavior remain unchanged. An evaluation opts into an
MLflow-native scorer only when its `eval.yaml` declares `mlflow_scorer`:

```yaml
judges:
  - name: mlflow_guidelines
    mlflow_scorer: Guidelines
    model: gateway:/jeder-codex-endpoint
    feedback_type: bool
    arguments:
      guidelines: |
        The generated contract must be grounded in the source files read.
```

## First consumer

The first consumer is the self-evaluation of `eval-analyze` in
[`eval/eval-analyze/eval.yaml`](../eval/eval-analyze/eval.yaml). That suite is
a demonstration of the integration, not the definition of the feature. Other
evaluations can adopt the same judge path independently and incrementally.

The current implementation demonstrates MLflow's built-in `Guidelines` judge.
The adapter is the extension seam for additional MLflow judges such as tool
call, retrieval/RAG, privacy, response-quality, and multi-turn judges. See
MLflow's [built-in judge catalog](https://mlflow.org/docs/latest/genai/eval-monitor/scorers/llm-judge/predefined/).

## MLflow evaluation plane

After an eval run, `/eval-mlflow` can publish:

1. a native MLflow evaluation dataset with stable case IDs;
2. an MLflow evaluation run with metrics and a per-case results table;
3. trace links and captured execution evidence;
4. automated scorer assessments attached to the matching traces.

This makes the result reviewable in MLflow. MLflow Review Queues can become a
later human-in-the-loop destination for trace-native review without requiring
the harness to replace its execution plane. See the [MLflow review queue
documentation](https://mlflow.org/docs/latest/genai/assessments/review-queues/).

## Compatibility contract

- Existing judges remain the default unless `mlflow_scorer` is present.
- Existing runner, workspace, collection, Harbor, and EvalHub paths remain
  harness-owned.
- The repository's MLflow integration remains the shared transport and
  trace-linking layer; this feature does not create a second MLflow backend.
- New MLflow judge support should be introduced as an explicit, tested opt-in.
