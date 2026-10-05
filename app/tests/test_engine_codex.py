"""Offline tests for the codex exec engine (injected runner only)."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ccfa_core.engines.codex_exec as codex_exec_module
from ccfa_core.engines.base import ChatMessage, Engine, EngineError
from ccfa_core.engines.codex_exec import CodexExecEngine


class RecordingRunner:
    def __init__(self, *, code=0, stdout="", stderr="", error=None):
        self.code = code
        self.stdout = stdout
        self.stderr = stderr
        self.error = error
        self.calls = []

    def __call__(self, argv, cwd, timeout_s, prompt):
        self.calls.append(
            {
                "argv": list(argv),
                "cwd": cwd,
                "timeout_s": timeout_s,
                "prompt": prompt,
            }
        )
        if self.error is not None:
            raise self.error
        return self.code, self.stdout, self.stderr


class FakeProcess:
    def __init__(self, *, stdout="done\n", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.received_input = None
        self.killed = False

    def communicate(self, input=None, timeout=None):
        self.received_input = input
        return self.stdout, self.stderr

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class TimeoutProcess(FakeProcess):
    def communicate(self, input=None, timeout=None):
        if timeout is not None:
            raise subprocess.TimeoutExpired(cmd=["codex"], timeout=timeout)
        self.received_input = input
        return "partial\n", "still running\n"


class CodexExecEngineTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = str(Path(self._temporary.name).resolve())

    def test_exact_argv_includes_model_cwd_and_dash(self):
        runner = RecordingRunner(stdout="reply\n")
        engine = CodexExecEngine(
            model="gpt-5-codex",
            timeout_s=42,
            runner=runner,
            cwd=self.root,
        )

        reply = engine.send([ChatMessage("user", "hello")])

        self.assertEqual(
            runner.calls[0]["argv"],
            ["codex", "exec", "-m", "gpt-5-codex", "-C", self.root, "-"],
        )
        self.assertEqual(runner.calls[0]["cwd"], self.root)
        self.assertEqual(runner.calls[0]["timeout_s"], 42)
        self.assertEqual(reply.text, "reply")

    def test_no_model_flag_when_model_is_empty(self):
        runner = RecordingRunner(stdout="ok")
        engine = CodexExecEngine(runner=runner, cwd=self.root)

        engine.send([ChatMessage("user", "hello")])

        self.assertEqual(
            runner.calls[0]["argv"],
            ["codex", "exec", "-C", self.root, "-"],
        )

    def test_prompt_carries_every_message_in_order(self):
        runner = RecordingRunner(stdout="ok")
        engine = CodexExecEngine(runner=runner, cwd=self.root)

        engine.send(
            [
                ChatMessage("system", "be careful"),
                ChatMessage("user", "第一问"),
                ChatMessage("assistant", "第一答"),
                ChatMessage("user", "第二问"),
            ]
        )

        prompt = runner.calls[0]["prompt"]
        self.assertLess(prompt.index("be careful"), prompt.index("第一问"))
        self.assertLess(prompt.index("第一问"), prompt.index("第一答"))
        self.assertLess(prompt.index("第一答"), prompt.index("第二问"))

    def test_default_cwd_is_the_process_cwd(self):
        runner = RecordingRunner(stdout="ok")
        engine = CodexExecEngine(runner=runner)

        engine.send([ChatMessage("user", "hello")])

        argv = runner.calls[0]["argv"]
        self.assertEqual(argv[-3], "-C")
        self.assertTrue(argv[-2])

    def test_success_reply_is_stripped_stdout(self):
        runner = RecordingRunner(stdout="  answer with space  \n")
        engine = CodexExecEngine(runner=runner, cwd=self.root)

        reply = engine.send([ChatMessage("user", "hello")])

        self.assertEqual(reply.text, "answer with space")
        self.assertEqual(reply.tool_calls, [])

    def test_nonzero_exit_raises_with_bounded_stderr_summary(self):
        runner = RecordingRunner(code=2, stderr="z" * 900)
        engine = CodexExecEngine(runner=runner, cwd=self.root)

        with self.assertRaises(EngineError) as context:
            engine.send([ChatMessage("user", "hello")])

        message = str(context.exception)
        self.assertIn("codex exec", message)
        self.assertIn("2", message)
        self.assertLessEqual(message.count("z"), 500)
        snippet = message.rsplit(": ", 1)[-1]
        self.assertLessEqual(len(snippet), 500)

    def test_runner_exit_code_124_is_a_timeout(self):
        runner = RecordingRunner(code=124)
        engine = CodexExecEngine(runner=runner, cwd=self.root)

        with self.assertRaises(EngineError) as context:
            engine.send([ChatMessage("user", "hello")])

        self.assertIn("超时", str(context.exception))

    def test_runner_timeout_expired_is_a_timeout(self):
        runner = RecordingRunner(
            error=subprocess.TimeoutExpired(cmd=["codex"], timeout=1)
        )
        engine = CodexExecEngine(runner=runner, cwd=self.root)

        with self.assertRaises(EngineError) as context:
            engine.send([ChatMessage("user", "hello")])

        self.assertIn("超时", str(context.exception))

    def test_missing_codex_binary_is_an_engine_error(self):
        runner = RecordingRunner(error=FileNotFoundError("codex"))
        engine = CodexExecEngine(runner=runner, cwd=self.root)

        with self.assertRaises(EngineError) as context:
            engine.send([ChatMessage("user", "hello")])

        self.assertIn("无法启动 codex", str(context.exception))

    def test_cancel_token_set_before_send_skips_the_runner(self):
        runner = RecordingRunner()
        engine = CodexExecEngine(runner=runner, cwd=self.root)

        with self.assertRaises(EngineError) as context:
            engine.send([ChatMessage("user", "hello")], cancel=lambda: True)

        self.assertIn("取消", str(context.exception))
        self.assertEqual(runner.calls, [])

    def test_default_runner_sends_prompt_on_stdin(self):
        process = FakeProcess(stdout="from stdin\n")
        created = {}

        def fake_popen(argv, **kwargs):
            created["argv"] = list(argv)
            created["kwargs"] = dict(kwargs)
            return process

        with mock.patch.object(
            codex_exec_module.subprocess,
            "Popen",
            side_effect=fake_popen,
        ):
            engine = CodexExecEngine(cwd=self.root, timeout_s=10)
            reply = engine.send([ChatMessage("user", "stdin-check")])

        self.assertEqual(created["argv"], ["codex", "exec", "-C", self.root, "-"])
        self.assertIs(created["kwargs"]["shell"], False)
        self.assertIs(created["kwargs"]["stdin"], subprocess.PIPE)
        self.assertIn("stdin-check", process.received_input)
        self.assertEqual(reply.text, "from stdin")

    def test_default_runner_kills_and_reports_timeout(self):
        process = TimeoutProcess()

        with mock.patch.object(
            codex_exec_module.subprocess,
            "Popen",
            return_value=process,
        ):
            engine = CodexExecEngine(cwd=self.root, timeout_s=1)
            with self.assertRaises(EngineError) as context:
                engine.send([ChatMessage("user", "slow")])

        self.assertIn("超时", str(context.exception))
        self.assertTrue(process.killed)

    def test_engine_satisfies_the_runtime_protocol(self):
        engine = CodexExecEngine(runner=RecordingRunner(), cwd=self.root)
        self.assertIsInstance(engine, Engine)


if __name__ == "__main__":
    unittest.main()
