"""MLflow experiment management utilities."""

import subprocess
import sys
from typing import Optional


def setup_experiment(experiment_name: str, tracking_uri: Optional[str] = None):
    """Create or set the MLflow experiment.

    Args:
        experiment_name: Name for the experiment.
        tracking_uri: MLflow tracking URI (default: from env or local).
    """
    try:
        import mlflow
    except ImportError:
        print("MLflow not installed. Install with: pip install 'mlflow[genai]'",
              file=sys.stderr)
        return

    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)


def ensure_server(port: int = 5000) -> bool:
    """Check if MLflow server is running, optionally start it.

    Returns:
        True if server is available.
    """
    import urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/2.0/mlflow/experiments/search",
                              timeout=2)
        return True
    except Exception:
        return False


def setup_autolog(project_dir: str, tracking_uri: str = "http://127.0.0.1:5000",
                  experiment_name: str = ""):
    """Configure MLflow autolog for Claude Code in a project directory.

    Runs `mlflow autolog claude` to set up the Stop hook in .claude/settings.json.
    """
    cmd = ["python3", "-m", "mlflow", "autolog", "claude", project_dir,
           "-u", tracking_uri]
    if experiment_name:
        cmd.extend(["-n", experiment_name])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Failed to setup MLflow autolog: {result.stderr}", file=sys.stderr)
    return result.returncode == 0


def log_feedback(trace_id: str, name: str, value, source_type: str = "CODE",
                 source_id: str = "agent-eval", rationale: str = ""):
    """Log feedback to a trace."""
    try:
        import mlflow
        from mlflow.entities.assessment import AssessmentSource

        mlflow.log_feedback(
            trace_id=trace_id,
            name=name,
            value=value,
            source=AssessmentSource(source_type=source_type, source_id=source_id),
            rationale=rationale if rationale else None,
        )
    except Exception:
        pass
