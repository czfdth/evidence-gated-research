"""Engine adapter around ``codex exec``.

The runner is injectable so tests never spawn a real codex process:

    runner(argv, cwd, timeout_s, prompt) -> (exit_code, stdout, stderr)

The default runner spawns codex with ``shell=False`` and writes the prompt to
stdin. Pass a cancellation token (boolean, callable, or ``threading.Event``)
to have the default runner kill the child process; the engine checks the same
token before and after the run.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .base import (
    ChatMessage,
    EngineError,
    EngineReply,
    is_cancelled,
    validate_timeout,
)

LOGGER = logging.getLogger(__name__)

STDERR_LIMIT = 500
TIMEOUT_EXIT_CODE = 124


class CodexExecEngine:
    """Send a prompt to the local ``codex exec`` CLI."""

    name = "codex-exec"

    def __init__(
        self,
        model: str = "",
        timeout_s: float = 600,
        runner: Callable[..., tuple[int, str, str]] | None = None,
        cwd: str | os.PathLike[str] | None = None,
    ):
        if model is None or not isinstance(model, str):
            raise ValueError("model 必须是字符串")
        if runner is not None and not callable(runner):
            raise ValueError("runner 必须可调用")
        self._model = model.strip()
        self._timeout_s = validate_timeout(timeout_s, "timeout_s")
        self._runner = runner
        self._cwd = str(Path.cwd() if cwd is None else Path(cwd).resolve())
        self._process: subprocess.Popen | None = None

    def send(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict] | None = None,
        timeout_s: float | None = None,
        cancel: Any = None,
    ) -> EngineReply:
        if tools is not None:
            raise EngineError("codex exec 不支持 tools 参数")
        if is_cancelled(cancel):
            raise EngineError("codex exec 已取消")
        effective_timeout = (
            self._timeout_s
            if timeout_s is None
            else validate_timeout(timeout_s, "timeout_s")
        )
        argv = self._build_argv()
        prompt = self._format_prompt(messages)
        LOGGER.debug("codex exec argv=%s cwd=%s", argv, self._cwd)
        try:
            if self._runner is None:
                result = self._default_runner(
                    argv,
                    self._cwd,
                    effective_timeout,
                    prompt,
                    cancel,
                )
            else:
                result = self._runner(
                    argv,
                    self._cwd,
                    effective_timeout,
                    prompt,
                )
        except EngineError:
            raise
        except subprocess.TimeoutExpired as exc:
            raise EngineError(
                f"codex exec 超时（{effective_timeout:g}s）"
            ) from exc
        except OSError as exc:
            raise EngineError(f"无法启动 codex: {exc}") from exc
        if is_cancelled(cancel):
            raise EngineError("codex exec 已取消")
        try:
            code, stdout, stderr = result
        except (TypeError, ValueError) as exc:
            raise EngineError(f"codex runner 返回非法结果: {exc!r}") from exc
        if code == TIMEOUT_EXIT_CODE:
            raise EngineError(
                f"codex exec 超时（{effective_timeout:g}s）: "
                f"{self._snippet(stderr)}"
            )
        if code != 0:
            raise EngineError(
                f"codex exec 失败（退出码 {code}）: {self._snippet(stderr)}"
            )
        return EngineReply(text=str(stdout).strip())

    def _build_argv(self) -> list[str]:
        argv = ["codex", "exec"]
        if self._model:
            argv.extend(["-m", self._model])
        argv.extend(["-C", self._cwd, "-"])
        return argv

    @staticmethod
    def _format_prompt(messages: list[ChatMessage]) -> str:
        return "\n\n".join(f"{message.role}: {message.content}" for message in messages)

    @staticmethod
    def _snippet(text: Any, limit: int = STDERR_LIMIT) -> str:
        value = "" if text is None else str(text)
        if len(value) <= limit:
            return value
        marker = "...[truncated]"
        keep = max(0, limit - len(marker))
        return value[:keep] + marker

    def _default_runner(
        self,
        argv: list[str],
        cwd: str,
        timeout_s: float,
        prompt: str,
        cancel: Any,
    ) -> tuple[int, str, str]:
        try:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )
        except OSError as exc:
            raise EngineError(f"无法启动 codex: {exc}") from exc
        self._process = process
        watcher = self._start_cancel_watcher(process, cancel)
        try:
            try:
                stdout, stderr = process.communicate(
                    input=prompt,
                    timeout=timeout_s,
                )
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                return (
                    TIMEOUT_EXIT_CODE,
                    stdout or "",
                    (stderr or "") + "\n[timeout]",
                )
        finally:
            self._process = None
            if watcher is not None:
                watcher.join(timeout=1.0)
        return process.returncode, stdout or "", stderr or ""

    @staticmethod
    def _start_cancel_watcher(
        process: subprocess.Popen,
        cancel: Any,
    ) -> threading.Thread | None:
        if cancel is None:
            return None
        if not callable(cancel) and not callable(getattr(cancel, "is_set", None)):
            return None

        def watch() -> None:
            while process.poll() is None:
                if is_cancelled(cancel):
                    try:
                        process.kill()
                    except OSError:
                        pass
                    return
                time.sleep(0.05)

        watcher = threading.Thread(
            target=watch,
            name="codex-exec-cancel",
            daemon=True,
        )
        watcher.start()
        return watcher
