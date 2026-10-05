"""Call the research workflow through its console entry points.

The workbench is a **consumer** of the workflow, not part of it: it never
imports ``ccfa``. Every deterministic operation shells out to the workflow's
own ``python -m ccfa.<tool>`` entry point, which already promises JSON on
stdout, a human summary on stderr, and exit codes 0 (clean) / 1 (findings) /
2 (tool error). The two sides can therefore be deployed and upgraded
independently: a workflow change only breaks the workbench if it changes that
CLI contract.

Where the workflow lives is explicit configuration, resolved in this order:

1. an explicit ``root`` passed by the caller,
2. ``CCFA_WORKFLOW_ROOT`` in the environment,
3. the repository this file sits in (the default when both live together).

The interpreter is the workflow's own venv when present, otherwise the current
interpreter with ``PYTHONPATH`` pointed at the workflow's ``tools/`` directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

WORKFLOW_ROOT_ENV = "CCFA_WORKFLOW_ROOT"
WORKFLOW_PYTHON_ENV = "CCFA_WORKFLOW_PYTHON"

DEFAULT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TIMEOUT_S = 120.0


class WorkflowError(RuntimeError):
    """A workflow call could not be made, or broke its output contract."""

    code = "workflow-error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


@dataclass(frozen=True)
class WorkflowResult:
    module: str
    exit_code: int
    payload: dict | None
    stdout: str
    stderr: str

    @property
    def findings(self) -> bool:
        """True when the tool ran and reported findings (exit 1)."""

        return self.exit_code == 1


class WorkflowClient:
    """Run ``ccfa`` tools in a child process and parse their JSON stdout."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        python: str | Path | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        env: dict | None = None,
    ) -> None:
        configured = os.environ.get(WORKFLOW_ROOT_ENV, "").strip()
        self.root = Path(root or configured or DEFAULT_ROOT)
        self.python = Path(python) if python else self._default_python()
        self.timeout = float(timeout)
        self._extra_env = dict(env or {})

    def _default_python(self) -> Path | None:
        override = os.environ.get(WORKFLOW_PYTHON_ENV, "").strip()
        if override:
            return Path(override)
        candidate = self.root / "tools" / ".venv" / "Scripts" / "python.exe"
        if candidate.is_file():
            return candidate
        # Inside a frozen build ``sys.executable`` is the app itself, not an
        # interpreter, so it can never run ``-m ccfa.<tool>``. Require the
        # workflow's own interpreter (or an explicit setting) instead.
        if getattr(sys, "frozen", False):
            return None
        return Path(sys.executable)

    def environment(self) -> dict:
        env = dict(os.environ)
        tools = str(self.root / "tools")
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{tools}{os.pathsep}{existing}" if existing else tools
        env["PYTHONIOENCODING"] = "utf-8"
        env.update(self._extra_env)
        return env

    def run(
        self,
        module: str,
        args: tuple | list = (),
        *,
        cwd: str | Path | None = None,
        timeout: float | None = None,
    ) -> WorkflowResult:
        # A bare name is a workflow tool (``ccfa.<name>``); a dotted name is
        # used verbatim, so non-ccfa entry points stay reachable.
        target = module if "." in module else f"ccfa.{module}"
        if self.python is None:
            raise WorkflowError(
                "找不到工作流解释器：请在设置里指定工作流目录"
                f"（应为包含 tools/.venv 的仓库根），或用 {WORKFLOW_PYTHON_ENV}"
                " 指定 Python",
                code="workflow-python-missing",
            )
        argv = [str(self.python), "-m", target]
        argv.extend(str(item) for item in args)
        try:
            completed = subprocess.run(
                argv,
                cwd=str(cwd) if cwd else None,
                env=self.environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.timeout,
                shell=False,
                check=False,
            )
        except FileNotFoundError as exc:
            raise WorkflowError(
                f"找不到工作流解释器 {self.python}：{exc}",
                code="workflow-python-missing",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise WorkflowError(
                f"工作流调用超时（{module}）：{exc}",
                code="workflow-timeout",
            ) from exc
        except OSError as exc:
            raise WorkflowError(
                f"无法运行工作流命令 ccfa.{module}：{exc}",
                code="workflow-unavailable",
            ) from exc
        return WorkflowResult(
            module=module,
            exit_code=completed.returncode,
            payload=self._parse(completed.stdout),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )

    def json(
        self,
        module: str,
        args: tuple | list = (),
        *,
        cwd: str | Path | None = None,
        timeout: float | None = None,
    ) -> dict:
        """Return the tool's JSON payload, raising if it broke the contract."""

        result = self.run(module, args, cwd=cwd, timeout=timeout)
        if result.payload:
            return result.payload
        detail = result.stderr.strip().splitlines()
        tail = detail[-1][:300] if detail else ""
        if result.exit_code == 2:
            # Exit 2 is the workflow's "the tool refused this input" signal:
            # surface its message under the workbench's own domain-error code.
            raise WorkflowError(
                tail or f"ccfa.{module} 以退出码 2 结束（工具错误）",
                code="tool-error",
            )
        raise WorkflowError(
            f"ccfa.{module} 未返回 JSON（exit {result.exit_code}）"
            + (f"：{tail}" if tail else ""),
            code="workflow-output-invalid",
        )

    @staticmethod
    def _parse(stdout: str) -> dict | None:
        text = (stdout or "").strip()
        if not text:
            return None
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    def probe(self) -> tuple[bool, str]:
        """Check that this client can actually reach the workflow.

        The installed app has no repository to fall back on, so the user needs
        a way to tell whether the configured workflow directory works before
        trusting the project list. Reads the stage table, which every workflow
        checkout can serve.
        """

        if self.python is None:
            return (
                False,
                "找不到工作流解释器：请选择包含 tools/.venv 的工作流目录",
            )
        try:
            payload = self.json("stages", ("--mode", "conference"))
        except WorkflowError as exc:
            return False, str(exc)
        # A call can still succeed through an inherited PYTHONPATH, so a
        # successful probe only counts when the configured root is a real
        # workflow checkout.
        if not (self.root / "tools" / "ccfa").is_dir():
            return (
                False,
                f"不是工作流目录：{self.root}（缺少 tools/ccfa）",
            )
        stages = payload.get("stages")
        count = len(stages) if isinstance(stages, list) else 0
        return (
            True,
            f"OK：{self.root}（{count} 个 stage，解释器 {self.python.name}）",
        )
