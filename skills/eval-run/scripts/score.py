#!/usr/bin/env python3
"""Scoring CLI for eval runs.

Loads all files from each case's collected output directories into a
record dict. Passes the record to judges — they know what to do with
it via their description/check/prompt.

Usage:
    python3 ${CLAUDE_SKILL_DIR}/scripts/score.py judges --run-id <id> --config eval.yaml
    python3 ${CLAUDE_SKILL_DIR}/scripts/score.py pairwise --run-id <id> --baseline <id> --config eval.yaml
    python3 ${CLAUDE_SKILL_DIR}/scripts/score.py regression --run-id <id> --config eval.yaml
"""

import argparse
import importlib
import json
import os
import sys
import textwrap
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from agent_eval.config import EvalConfig


RUNS_DIR = Path("eval/runs")


def _resolve_under(root: Path, candidate: Path) -> Path:
    """Ensure a path resolves under root. Raises ValueError if it escapes."""
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes root directory: {candidate}")
    return resolved


# ---------------------------------------------------------------------------
# Case record loading — reads all files, no schema interpretation
# ---------------------------------------------------------------------------

def load_case_record(case_dir, config):
    """Load all files from a case's collected output directories.

    Returns:
        {
            "files": {"relative/path.md": "<content>", ...},
            "case_dir": str,
        }
    """
    case_dir = Path(case_dir).resolve()
    record = {"files": {}, "case_dir": str(case_dir)}

    # Load all files from each output directory
    for output in config.outputs:
        out_path = output.path or "."
        artifact_dir = case_dir / out_path
        if not artifact_dir.exists():
            continue
        _resolve_under(case_dir, artifact_dir)
        for f in sorted(artifact_dir.rglob("*")):
            if not f.is_file() or f.is_symlink():
                continue
            _resolve_under(case_dir, f)
            rel = str(f.relative_to(case_dir))
            try:
                record["files"][rel] = f.read_text()
            except UnicodeDecodeError:
                record["files"][rel] = f"<binary: {f.name}>"

    # Also provide convenience keys for the first file in each output dir
    for output in config.outputs:
        out_path = output.path or "."
        artifact_dir = case_dir / out_path
        if not artifact_dir.exists():
            continue
        for f in sorted(artifact_dir.iterdir()):
            if f.is_file() and not f.is_symlink():
                key = Path(out_path).name or "main"
                try:
                    record[f"{key}_content"] = f.read_text()
                    record[f"{key}_file"] = str(f)
                except UnicodeDecodeError:
                    pass
                break

    return record


# ---------------------------------------------------------------------------
# Judge loading and scoring
# ---------------------------------------------------------------------------

def load_judges(config, project_root=None):
    """Load all judges from config.

    Judge types determined by which fields are set:
    - check: inline Python snippet
    - prompt/prompt_file: LLM judge
    - module/function: external code judge
    """
    judges = []
    for jc in config.judges:
        if jc.check:
            scorer = _make_inline_check(jc)
        elif jc.prompt or jc.prompt_file:
            scorer = _load_llm_judge(jc, project_root)
        elif jc.module and jc.function:
            scorer = _load_code_judge(jc, project_root)
        else:
            print(f"  Warning: judge '{jc.name}' has no check, prompt, or module",
                  file=sys.stderr)
            continue
        if scorer:
            judges.append((jc.name, scorer))
    return judges


def score_cases(judges, case_dirs, config):
    """Score all cases with all judges in parallel."""
    if not case_dirs:
        return {"per_case": {}, "aggregated": {n: {"values": [], "mean": None, "pass_rate": None} for n, _ in judges}}
    per_case = {}
    aggregated = {name: {"values": []} for name, _ in judges}
    parallelism = min(len(case_dirs), os.cpu_count() or 4)
    lock = threading.Lock()
    completed = 0

    def _score_case(case_dir):
        case_id = case_dir.name
        record = load_case_record(case_dir, config)
        case_results = {}
        for name, scorer in judges:
            try:
                result = scorer(outputs=record)
                # Normalize — accepts (bool, str) tuples, Feedback, primitives
                if isinstance(result, tuple) and len(result) == 2:
                    case_results[name] = {
                        "value": result[0],
                        "rationale": result[1],
                    }
                elif hasattr(result, "value"):
                    case_results[name] = {
                        "value": result.value,
                        "rationale": getattr(result, "rationale", ""),
                    }
                elif isinstance(result, (bool, int, float, str)):
                    case_results[name] = {"value": result, "rationale": ""}
                else:
                    case_results[name] = {"value": result, "rationale": ""}
            except Exception as e:
                case_results[name] = {"value": None, "error": str(e)}
        return case_id, case_results

    with ThreadPoolExecutor(max_workers=parallelism) as pool:
        futures = {pool.submit(_score_case, d): d for d in case_dirs}
        for future in as_completed(futures):
            completed += 1
            case_id, case_results = future.result()
            per_case[case_id] = case_results
            with lock:
                for name, result in case_results.items():
                    if name in aggregated and result.get("value") is not None:
                        aggregated[name]["values"].append(result["value"])
                print(f"  [{completed}/{len(case_dirs)}] {case_id}", flush=True)

    # Compute aggregates
    for name in aggregated:
        values = aggregated[name]["values"]
        if not values:
            aggregated[name]["mean"] = None
            aggregated[name]["pass_rate"] = None
            continue
        if all(isinstance(v, bool) for v in values):
            aggregated[name]["pass_rate"] = sum(values) / len(values)
            aggregated[name]["mean"] = aggregated[name]["pass_rate"]
        elif all(isinstance(v, (int, float)) for v in values):
            aggregated[name]["mean"] = sum(values) / len(values)
            aggregated[name]["pass_rate"] = None
        else:
            aggregated[name]["mean"] = None
            aggregated[name]["pass_rate"] = None

    return {"per_case": per_case, "aggregated": aggregated}


def _make_inline_check(jc):
    """Create a scorer from an inline check script."""
    source = jc.check
    wrapped = f"def _check(outputs):\n{textwrap.indent(source, '    ')}"
    code = compile(wrapped, f"<check:{jc.name}>", "exec")
    ns = {"__builtins__": __builtins__}
    exec(code, ns)
    check_fn = ns["_check"]

    def scorer(outputs=None, **kwargs):
        return check_fn(outputs or {})

    return scorer


def _load_code_judge(jc, project_root=None):
    if project_root and str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    mod = importlib.import_module(jc.module)
    return getattr(mod, jc.function)


def _load_llm_judge(jc, project_root=None):
    try:
        from mlflow.genai.judges import make_judge
    except ImportError:
        raise ImportError("mlflow[genai] required for LLM judges")
    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    prompt = jc.prompt
    if not prompt and jc.prompt_file:
        prompt_path = Path(jc.prompt_file)
        if not prompt_path.is_absolute():
            prompt_path = root / prompt_path
        _resolve_under(root, prompt_path)
        if not prompt_path.exists():
            raise FileNotFoundError(f"Judge prompt not found: {prompt_path}")
        prompt = prompt_path.read_text()
    if not prompt:
        raise ValueError(f"LLM judge '{jc.name}' requires prompt or prompt_file")
    # Append context files to the prompt
    for ctx_path in jc.context:
        path = Path(ctx_path)
        if not path.is_absolute():
            path = root / path
        _resolve_under(root, path)
        if path.exists():
            prompt += f"\n\n## Context: {path.name}\n\n{path.read_text()}"
    kwargs = {"name": jc.name, "instructions": prompt}
    if jc.feedback_type:
        kwargs["feedback_value_type"] = _parse_feedback_type(jc.feedback_type)
    return make_judge(**kwargs)


def _parse_feedback_type(type_str):
    mapping = {"int": int, "float": float, "bool": bool, "str": str}
    if type_str in mapping:
        return mapping[type_str]
    if type_str.startswith("Literal"):
        from typing import Literal
        inner = type_str[len("Literal["):-1]
        values = tuple(v.strip().strip("'\"") for v in inner.split(","))
        return Literal[values]
    return str


# ---------------------------------------------------------------------------
# Pairwise comparison
# ---------------------------------------------------------------------------

BUILTIN_COMPARISON_PROMPT = (Path(__file__).parent.parent
                             / "prompts" / "comparison-judge.md")


@dataclass
class PairwiseResult:
    case_id: str
    pref_ab: Optional[str] = None
    pref_ba: Optional[str] = None
    error: Optional[str] = None

    @property
    def winner(self) -> str:
        if self.error or not self.pref_ab or not self.pref_ba:
            return "error"
        if self.pref_ab == "A" and self.pref_ba == "B":
            return "A"
        elif self.pref_ab == "B" and self.pref_ba == "A":
            return "B"
        return "tie"


def compare_runs(run_a_dir, run_b_dir, config, case_ids,
                 prompt=None, prompt_file=None, model="claude-sonnet-4-6"):
    """Compare two runs using position-swapped LLM judge."""
    comparison_prompt = prompt
    if not comparison_prompt and prompt_file:
        comparison_prompt = Path(prompt_file).read_text()
    if not comparison_prompt and BUILTIN_COMPARISON_PROMPT.exists():
        comparison_prompt = BUILTIN_COMPARISON_PROMPT.read_text()
    if not comparison_prompt:
        comparison_prompt = ("Compare outputs A and B. Return JSON: "
                             "{\"reasoning\": \"...\", \"preferred\": \"A\" or \"B\" or \"tie\"}")

    try:
        client = _get_anthropic_client()
    except Exception as e:
        return {"error": str(e)}

    def _compare_case(case_id):
        record_a = load_case_record(run_a_dir / "cases" / case_id, config)
        record_b = load_case_record(run_b_dir / "cases" / case_id, config)

        output_a = _first_content(record_a)
        output_b = _first_content(record_b)

        if not output_a or not output_b:
            return PairwiseResult(case_id=case_id,
                                  error=f"Missing output: a={bool(output_a)}, b={bool(output_b)}")
        result = PairwiseResult(case_id=case_id)

        msg_ab = f"## Output A\n\n{output_a}\n\n## Output B\n\n{output_b}"
        pref_ab, err = _call_judge(client, comparison_prompt, msg_ab, model)
        if pref_ab:
            result.pref_ab = pref_ab.get("preferred")
        else:
            result.error = f"AB failed: {err}"
            return result

        msg_ba = f"## Output A\n\n{output_b}\n\n## Output B\n\n{output_a}"
        pref_ba, err = _call_judge(client, comparison_prompt, msg_ba, model)
        if pref_ba:
            result.pref_ba = pref_ba.get("preferred")
        else:
            result.error = f"BA failed: {err}"
        return result

    parallelism = min(len(case_ids), os.cpu_count() or 4)
    results = []
    completed = 0
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=parallelism) as pool:
        futures = {pool.submit(_compare_case, cid): cid for cid in case_ids}
        for future in as_completed(futures):
            r = future.result()
            results.append(r)
            with lock:
                completed += 1
                status = r.winner if not r.error else f"error: {r.error}"
                print(f"    [{completed}/{len(case_ids)}] {r.case_id}... {status}",
                      flush=True)

    wins_a = sum(1 for r in results if r.winner == "A")
    wins_b = sum(1 for r in results if r.winner == "B")
    ties = sum(1 for r in results if r.winner == "tie")
    errors = sum(1 for r in results if r.winner == "error")

    return {
        "run_a": run_a_dir.name, "run_b": run_b_dir.name,
        "cases_compared": len(results),
        "wins_a": wins_a, "wins_b": wins_b,
        "ties": ties, "errors": errors,
        "per_case": [{"case_id": r.case_id, "winner": r.winner, "error": r.error}
                     for r in results],
    }


def _first_content(record):
    """Get the first *_content value from a record."""
    for k, v in record.items():
        if k.endswith("_content") and v:
            return v
    return None


def _get_anthropic_client():
    project_id = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID")
    region = os.environ.get("CLOUD_ML_REGION", "us-east5")
    if project_id:
        from anthropic import AnthropicVertex
        return AnthropicVertex(project_id=project_id, region=region)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        from anthropic import Anthropic
        return Anthropic(api_key=api_key)
    raise RuntimeError("Set ANTHROPIC_VERTEX_PROJECT_ID or ANTHROPIC_API_KEY")


def _call_judge(client, system_prompt, user_message, model):
    try:
        response = client.messages.create(
            model=model, max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        text = response.content[0].text
        json_text = text
        if "```json" in json_text:
            json_text = json_text.split("```json")[1].split("```")[0]
        elif "```" in json_text:
            json_text = json_text.split("```")[1].split("```")[0]
        return json.loads(json_text.strip()), None
    except Exception as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# Regression detection
# ---------------------------------------------------------------------------

@dataclass
class Regression:
    judge_name: str
    metric: str
    baseline_value: str
    current_value: str
    detail: str = ""


def detect_regressions(current_results, thresholds, baseline_results=None):
    regressions = []
    for judge_name, threshold in thresholds.items():
        current = current_results.get(judge_name)
        if current is None:
            continue
        if "min_pass_rate" in threshold:
            rate = current.get("pass_rate", 1.0)
            if rate < threshold["min_pass_rate"]:
                regressions.append(Regression(judge_name, "pass_rate",
                                              f">= {threshold['min_pass_rate']}", str(rate)))
        if "min_mean" in threshold:
            mean = current.get("mean", 0)
            if mean < threshold["min_mean"]:
                regressions.append(Regression(judge_name, "mean",
                                              f">= {threshold['min_mean']}", str(mean)))
        if "min_win_rate" in threshold:
            win_rate = current.get("win_rate", 0)
            if win_rate < threshold["min_win_rate"]:
                regressions.append(Regression(judge_name, "win_rate",
                                              f">= {threshold['min_win_rate']}", str(win_rate)))
        if baseline_results:
            baseline = baseline_results.get(judge_name)
            if baseline and current:
                for key in ("mean", "pass_rate"):
                    curr_val = current.get(key)
                    base_val = baseline.get(key)
                    if curr_val is not None and base_val is not None:
                        if curr_val < base_val - 0.5:
                            regressions.append(Regression(
                                judge_name, f"{key}_vs_baseline",
                                str(base_val), str(curr_val), "Degraded vs baseline"))
    return regressions


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _get_case_dirs(run_id):
    cases_dir = RUNS_DIR / run_id / "cases"
    if not cases_dir.exists():
        print(f"No cases directory: {cases_dir}", file=sys.stderr)
        sys.exit(1)
    return sorted(d for d in cases_dir.iterdir() if d.is_dir())


def _merge_summary(run_id, key, data):
    summary_path = RUNS_DIR / run_id / "summary.yaml"
    summary = {}
    if summary_path.exists():
        with open(summary_path) as f:
            summary = yaml.safe_load(f) or {}
    summary["run_id"] = run_id
    summary[key] = data
    with open(summary_path, "w") as f:
        yaml.dump(summary, f, default_flow_style=False, allow_unicode=True)


def cmd_judges(args):
    config = EvalConfig.from_yaml(args.config)
    case_dirs = _get_case_dirs(args.run_id)
    project_root = Path.cwd()

    judges = load_judges(config, project_root)
    print(f"Scoring {len(case_dirs)} cases with {len(judges)} judges: "
          f"{[n for n, _ in judges]}")

    judge_results = score_cases(judges, case_dirs, config)

    for name, agg in judge_results.get("aggregated", {}).items():
        mean = agg.get("mean")
        rate = agg.get("pass_rate")
        if rate is not None:
            print(f"  {name}: pass_rate={rate:.1%}")
        elif mean is not None:
            print(f"  {name}: mean={mean:.2f}")

    _merge_summary(args.run_id, "judges", {
        name: {k: v for k, v in agg.items() if k != "values"}
        for name, agg in judge_results.get("aggregated", {}).items()
    })
    _merge_summary(args.run_id, "per_case", judge_results.get("per_case", {}))

    # Regression detection
    if config.thresholds:
        current_agg = judge_results.get("aggregated", {})
        regressions = detect_regressions(current_agg, config.thresholds)
        if regressions:
            print(f"\n  REGRESSIONS: {len(regressions)} detected")
            for r in regressions:
                print(f"    [{r.judge_name}] {r.metric}: "
                      f"{r.baseline_value} -> {r.current_value}")
        else:
            print("\n  REGRESSIONS: 0")


def cmd_pairwise(args):
    config = EvalConfig.from_yaml(args.config)
    case_dirs = _get_case_dirs(args.run_id)
    case_ids = [d.name for d in case_dirs]

    run_dir = RUNS_DIR / args.run_id
    baseline_dir = RUNS_DIR / args.baseline

    if not baseline_dir.exists():
        print(f"Baseline not found: {baseline_dir}", file=sys.stderr)
        sys.exit(1)

    # Find pairwise judge config
    judge_name = args.judge
    pairwise_jc = None
    if judge_name:
        pairwise_jc = next((j for j in config.judges if j.name == judge_name), None)
    if not pairwise_jc:
        pairwise_jc = next((j for j in config.judges
                            if j.prompt or j.prompt_file), None)

    model = args.model or (pairwise_jc.model if pairwise_jc else "") or "claude-sonnet-4-6"
    prompt_file = args.prompt_file or (pairwise_jc.prompt_file if pairwise_jc else "")

    print(f"Pairwise comparison: {args.run_id} vs {args.baseline} "
          f"({len(case_ids)} cases, model={model})")

    result = compare_runs(
        run_dir, baseline_dir, config, case_ids,
        prompt=pairwise_jc.prompt if pairwise_jc else None,
        prompt_file=prompt_file,
        model=model,
    )

    if "error" in result:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        sys.exit(1)

    print(f"  A wins: {result['wins_a']}")
    print(f"  B wins: {result['wins_b']}")
    print(f"  Ties:   {result['ties']}")
    print(f"  Errors: {result['errors']}")

    _merge_summary(args.run_id, "pairwise", result)


def cmd_regression(args):
    config = EvalConfig.from_yaml(args.config)
    summary_path = RUNS_DIR / args.run_id / "summary.yaml"
    if not summary_path.exists():
        print(f"No summary found. Run judges first.", file=sys.stderr)
        sys.exit(1)

    with open(summary_path) as f:
        summary = yaml.safe_load(f) or {}

    current_agg = summary.get("judges", {})
    baseline_agg = None
    if args.baseline:
        baseline_path = RUNS_DIR / args.baseline / "summary.yaml"
        if baseline_path.exists():
            with open(baseline_path) as f:
                baseline_agg = (yaml.safe_load(f) or {}).get("judges", {})

    regressions = detect_regressions(current_agg, config.thresholds, baseline_agg)
    if regressions:
        print(f"REGRESSIONS: {len(regressions)} detected")
        for r in regressions:
            print(f"  [{r.judge_name}] {r.metric}: "
                  f"{r.baseline_value} -> {r.current_value}")
        sys.exit(1)
    else:
        print("REGRESSIONS: 0")


def main():
    parser = argparse.ArgumentParser(
        description="Scoring CLI for eval runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # judges
    jdg_p = subparsers.add_parser("judges", help="Run all judges")
    jdg_p.add_argument("--run-id", required=True)
    jdg_p.add_argument("--config", default="eval.yaml")

    # pairwise
    pw_p = subparsers.add_parser("pairwise", help="Pairwise comparison")
    pw_p.add_argument("--run-id", required=True)
    pw_p.add_argument("--baseline", required=True)
    pw_p.add_argument("--config", default="eval.yaml")
    pw_p.add_argument("--judge", default=None,
                      help="Name of judge from eval.yaml to use")
    pw_p.add_argument("--prompt-file", default=None,
                      help="Override comparison prompt file")
    pw_p.add_argument("--model", default=None,
                      help="Override judge model")

    # regression
    reg_p = subparsers.add_parser("regression", help="Threshold checks")
    reg_p.add_argument("--run-id", required=True)
    reg_p.add_argument("--config", default="eval.yaml")
    reg_p.add_argument("--baseline", default=None)

    args = parser.parse_args()
    {"judges": cmd_judges, "pairwise": cmd_pairwise,
     "regression": cmd_regression}[args.command](args)


if __name__ == "__main__":
    main()
