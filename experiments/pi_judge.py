"""Pi CLI adapter for the Python benchmark's offline LLM judge.

The CLI uses Pi's ModelRuntime and pi-ai provider stack for model resolution and
credentials. It gives the Python runner a small process boundary instead of a
second, separately configured LLM client.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


class PiJudgeError(RuntimeError):
    """Raised when Pi cannot resolve or run the configured judge model."""


_SYSTEM_PROMPT = """You are a strict benchmark judge. Use only the graph data in the user prompt as evidence. Do not use outside knowledge or infer an unstated connection. A relationship passes only when the supplied graph shows a direct edge or a path of at most two edges. Return only the requested JSON array. Mark an assertion false when the graph data does not prove it."""


def _read_tier_file(path: Path) -> dict[str, str]:
    try:
        parsed = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        key: value
        for key, value in parsed.items()
        if key in {"cheap", "medium", "smart", "frontier"} and isinstance(value, str)
    }


def resolve_cheap_model(
    *, agent_dir: Path | str | None = None, project_dir: Path | str | None = None
) -> str:
    """Resolve the cheap tier with Pi's global-then-project precedence."""
    if agent_dir is None:
        agent_dir = Path(
            os.environ.get("PI_CODING_AGENT_DIR", "~/.pi/agent")
        ).expanduser()
    else:
        agent_dir = Path(agent_dir).expanduser()
    if project_dir is None:
        project_dir = Path(__file__).resolve().parent.parent
    else:
        project_dir = Path(project_dir)

    tiers = _read_tier_file(agent_dir / "model-tiers.json")
    tiers.update(_read_tier_file(project_dir / ".pi" / "model-tiers.json"))
    model_ref = tiers.get("cheap", "").strip()
    if not model_ref:
        raise PiJudgeError(
            "Pi model tier 'cheap' is not configured in the global or project "
            "model-tiers.json file"
        )
    return model_ref


def resolve_pi_cli() -> str:
    """Find the Pi CLI, honoring an explicit path for managed runner services."""
    configured = os.environ.get("PI_CLI_PATH")
    if configured:
        path = Path(configured).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        raise PiJudgeError(f"PI_CLI_PATH is not an executable file: {path}")

    executable = shutil.which("pi")
    if executable:
        return executable
    raise PiJudgeError(
        "Pi CLI was not found. Start the benchmark from a shell where 'pi' is on PATH."
    )


def run_pi_judge(
    prompt: str,
    *,
    model_ref: str,
    executable: str | None = None,
    timeout_seconds: int | None = None,
    cwd: Path | str | None = None,
) -> str:
    """Run one isolated, tool-free judge prompt through Pi's configured model."""
    pi = executable or resolve_pi_cli()
    timeout = timeout_seconds or int(os.environ.get("PI_JUDGE_TIMEOUT_SECONDS", "900"))
    command = [
        pi,
        "--model",
        model_ref,
        "--mode",
        "text",
        "--no-session",
        "--no-tools",
        "--no-extensions",
        "--no-context-files",
        "--no-skills",
        "--no-prompt-templates",
        "--no-mcp",
        "--system-prompt",
        _SYSTEM_PROMPT,
        "--print",
        prompt,
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd is not None else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise PiJudgeError(
            f"Pi judge timed out after {timeout} seconds using {model_ref}"
        ) from exc
    except OSError as exc:
        raise PiJudgeError(f"Could not start Pi judge: {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no CLI output"
        raise PiJudgeError(
            f"Pi judge exited with status {result.returncode} using {model_ref}: "
            f"{detail[-2000:]}"
        )
    answer = result.stdout.strip()
    if not answer:
        raise PiJudgeError(f"Pi judge returned empty output using {model_ref}")
    return answer
