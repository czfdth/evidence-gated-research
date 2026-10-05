import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from ccfa.queue import (
    QueueLock,
    QueueLocked,
    QueueStalled,
    _docker_argv,
    _item_cwd,
    _load_queue_document,
    _sandbox_env,
    build_parser,
    load_queue,
    main,
    run_queue,
)
from ccfa.run_log import check_runs


class FakeClock:
    def __init__(self, now=0.0):
        self.now = float(now)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += float(seconds)


class RecordingRunner:
    def __init__(self, behaviors, *, clock=None, log_dir=None):
        self.behaviors = list(behaviors)
        self.calls = []
        self.clock = clock
        self.log_dir = Path(log_dir) if log_dir else None
        self.running_seen = []

    def __call__(self, argv, cwd, timeout_s):
        self.calls.append(
            {
                "argv": list(argv),
                "cwd": Path(cwd),
                "timeout_s": timeout_s,
            }
        )
        if self.log_dir is not None:
            records = sorted(self.log_dir.glob("*.json"))
            if records:
                self.running_seen.append(
                    json.loads(records[-1].read_text(encoding="utf-8")).get("status")
                )
        behavior = self.behaviors.pop(0)
        if isinstance(behavior, BaseException):
            raise behavior
        if callable(behavior):
            return behavior()
        return int(behavior)


class FakeProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = StringIO(stdout)
        self.stderr = StringIO(stderr)

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        raise AssertionError("kill should not be called")


class FakeGpuMeter:
    def __init__(self, readings):
        self.readings = list(readings)
        self.starts = 0
        self.stops = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1
        value = self.readings.pop(0)
        if isinstance(value, dict):
            return value
        return {"seconds": value, "samples": 1, "errors": 0}


class QueueTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.queue_path = self.root / "queue.json"
        self.log_dir = self.root / "log"

    def _write_queue(self, items, *, version=1, key="queue", **extra):
        payload = {"schema_version": version, key: items}
        payload.update(extra)
        self.queue_path.write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    def _item(self, name="run-1", command=None, **overrides):
        item = {
            "name": name,
            "command": command or ["python", "-c", "print('ok')"],
        }
        item.update(overrides)
        return item

    def _records(self):
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(self.log_dir.glob("*.json"))
        ]

    def _run(
        self,
        runner,
        *,
        budget_s=None,
        clock=None,
        gpu_budget_s=None,
        gpu_meter_factory=None,
        sandbox=None,
        allow_sandbox_downgrade=False,
        allow_injected_runner=False,
    ):
        return run_queue(
            self.queue_path,
            log_dir=self.log_dir,
            runner=runner,
            budget_s=budget_s,
            clock=clock,
            gpu_budget_s=gpu_budget_s,
            gpu_meter_factory=gpu_meter_factory,
            sandbox=sandbox,
            allow_sandbox_downgrade=allow_sandbox_downgrade,
            allow_injected_runner=allow_injected_runner,
        )


class TestLoadQueue(QueueTests):
    def test_load_queue_returns_items_with_defaults(self):
        self._write_queue(
            [
                {
                    "name": "one",
                    "command": ["python", "one.py"],
                }
            ]
        )

        items = load_queue(self.queue_path)

        self.assertEqual(items[0]["name"], "one")
        self.assertEqual(items[0]["command"], ["python", "one.py"])
        self.assertEqual(items[0]["retry_exit_codes"], [])
        self.assertIs(items[0]["retry_on_timeout"], False)
        self.assertIs(items[0]["retry_on_stall"], False)
        self.assertIsNone(items[0]["stall_timeout_s"])
        self.assertEqual(items[0]["max_attempts"], 1)

    def test_load_queue_rejects_invalid_safety_fields(self):
        cases = (
            {"schema_version": 1, "sandbox": "docker", "queue": []},
            {"schema_version": 1, "gpu_budget_s": -1, "queue": []},
            {
                "schema_version": 1,
                "queue": [
                    {
                        "name": "bad",
                        "command": ["python"],
                        "stall_timeout_s": 0,
                    }
                ],
            },
            {
                "schema_version": 1,
                "queue": [
                    {
                        "name": "bad",
                        "command": ["python"],
                        "retry_on_stall": "yes",
                    }
                ],
            },
        )
        for payload in cases:
            with self.subTest(payload=payload):
                self.queue_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_queue(self.queue_path)

    def test_load_queue_rejects_invalid_shape_and_version(self):
        cases = (
            {"schema_version": 2, "queue": []},
            {"schema_version": 1, "queue": {}},
            {"schema_version": 1, "queue": [{"name": "", "command": []}]},
            {
                "schema_version": 1,
                "queue": [
                    {
                        "name": "bad",
                        "command": ["python"],
                        "max_attempts": 0,
                    }
                ],
            },
            {
                "schema_version": 1,
                "queue": [
                    {
                        "name": "bad-timeout-retry",
                        "command": ["python"],
                        "retry_on_timeout": "yes",
                    }
                ],
            },
        )
        for payload in cases:
            with self.subTest(payload=payload):
                self.queue_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_queue(self.queue_path)

    def test_load_queue_rejects_invalid_docker_options(self):
        cases = (
            {"schema_version": 1, "sandbox": "docker", "queue": []},
            {
                "schema_version": 1,
                "sandbox": "docker",
                "docker_image": "python:3.12-slim",
                "docker_output": ".",
                "queue": [],
            },
            {
                "schema_version": 1,
                "sandbox": "docker",
                "docker_image": "python:3.12-slim",
                "docker_output": "..",
                "queue": [],
            },
            {
                "schema_version": 1,
                "sandbox": "docker",
                "docker_image": "python:3.12-slim",
                "docker_output": "/tmp/out",
                "queue": [],
            },
            {
                "schema_version": 1,
                "sandbox": "docker",
                "docker_image": "python:3.12-slim",
                "docker_network": "",
                "queue": [],
            },
            {
                "schema_version": 1,
                "sandbox": "docker",
                "docker_image": "python:3.12-slim",
                "docker_gpus": "0",
                "queue": [],
            },
        )
        for payload in cases:
            with self.subTest(payload=payload):
                self.queue_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_queue(self.queue_path)

    def test_load_queue_accepts_docker_options(self):
        self._write_queue(
            [],
            sandbox="docker",
            docker_image="python:3.12-slim",
            docker_network="none",
            docker_gpus="all",
            docker_output="artifacts",
        )

        items, options = _load_queue_document(self.queue_path)

        self.assertEqual(items, [])
        self.assertEqual(options["sandbox"], "docker")
        self.assertEqual(options["docker_image"], "python:3.12-slim")
        self.assertEqual(options["docker_network"], "none")
        self.assertEqual(options["docker_gpus"], "all")
        self.assertEqual(options["docker_output"], "artifacts")

    @unittest.skipUnless(os.name == "nt", "drive-relative paths are Windows-only")
    def test_load_queue_rejects_windows_drive_relative_docker_output(self):
        self._write_queue(
            [],
            sandbox="docker",
            docker_image="python:3.12-slim",
            docker_output="C:foo",
        )

        with self.assertRaisesRegex(ValueError, "docker_output"):
            load_queue(self.queue_path)


class TestRunQueue(QueueTests):
    def test_successful_command_exits_complete(self):
        self._write_queue([self._item()])
        runner = RecordingRunner([0], log_dir=self.log_dir)

        result = self._run(runner)

        self.assertEqual(
            result,
            {
                "runs": [{"name": "run-1", "attempts": 1, "status": "complete"}],
                "stopped": None,
            },
        )
        self.assertEqual(self._records()[0]["status"], "completed")

    def test_failure_outside_retry_codes_does_not_retry(self):
        self._write_queue([self._item(retry_exit_codes=[2], max_attempts=3)])
        runner = RecordingRunner([3, 3, 3])

        result = self._run(runner)

        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(result["runs"][0]["status"], "failed")
        self.assertIsNone(result["stopped"])

    def test_retry_code_retries_until_success(self):
        self._write_queue([self._item(retry_exit_codes=[2], max_attempts=3)])
        runner = RecordingRunner([2, 0], log_dir=self.log_dir)

        result = self._run(runner)

        self.assertEqual(result["runs"][0]["attempts"], 2)
        self.assertEqual(result["runs"][0]["status"], "complete")
        self.assertEqual([record["status"] for record in self._records()], ["failed", "completed"])

    def test_retry_exhaustion_stops_with_retries(self):
        self._write_queue([self._item(retry_exit_codes=[2], max_attempts=2)])
        runner = RecordingRunner([2, 2])

        result = self._run(runner)

        self.assertEqual(result["runs"][0]["attempts"], 2)
        self.assertEqual(result["runs"][0]["status"], "failed")
        self.assertEqual(result["stopped"], "retries")

    def test_timeout_counts_as_failure_and_retries(self):
        self._write_queue(
            [
                self._item(
                    timeout_s=5,
                    retry_exit_codes=[],
                    max_attempts=2,
                    retry_on_timeout=True,
                )
            ]
        )
        runner = RecordingRunner(
            [
                subprocess.TimeoutExpired(["python"], 5),
                subprocess.TimeoutExpired(["python"], 5),
            ],
            log_dir=self.log_dir,
        )

        result = self._run(runner)

        self.assertEqual(result["runs"][0]["attempts"], 2)
        self.assertEqual(result["runs"][0]["status"], "timeout")
        self.assertEqual(result["stopped"], "retries")
        self.assertTrue(self._records()[0]["metrics"]["timeout"])

    def test_timeout_without_explicit_flag_does_not_retry(self):
        self._write_queue(
            [
                self._item(
                    timeout_s=5,
                    max_attempts=2,
                )
            ]
        )
        runner = RecordingRunner(
            [
                subprocess.TimeoutExpired(["python"], 5),
                0,
            ],
            log_dir=self.log_dir,
        )

        result = self._run(runner)

        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(result["runs"][0]["attempts"], 1)
        self.assertEqual(result["runs"][0]["status"], "timeout")
        self.assertIsNone(result["stopped"])

    def test_timeout_with_default_attempt_limit_does_not_retry(self):
        self._write_queue([self._item(timeout_s=5)])
        runner = RecordingRunner(
            [subprocess.TimeoutExpired(["python"], 5)],
            log_dir=self.log_dir,
        )

        result = self._run(runner)

        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(result["runs"][0]["status"], "timeout")
        self.assertIsNone(result["stopped"])

    def test_retry_exhaustion_stops_before_later_items(self):
        self._write_queue(
            [
                self._item("first", retry_exit_codes=[2], max_attempts=2),
                self._item("second"),
            ]
        )
        runner = RecordingRunner([2, 2, 0])

        result = self._run(runner)

        self.assertEqual([run["name"] for run in result["runs"]], ["first"])
        self.assertEqual(result["stopped"], "retries")
        self.assertEqual(len(runner.calls), 2)

    def test_budget_stops_before_next_item(self):
        self._write_queue([self._item("first"), self._item("second")])
        clock = FakeClock()

        def first():
            clock.advance(20)
            return 0

        runner = RecordingRunner([first, 0])

        result = self._run(runner, budget_s=10, clock=clock)

        self.assertEqual([run["name"] for run in result["runs"]], ["first", "second"])
        self.assertEqual(
            [run["status"] for run in result["runs"]],
            ["complete", "skipped-budget"],
        )
        self.assertEqual(result["runs"][1]["attempts"], 0)
        self.assertEqual(result["stopped"], "budget")

    def test_every_attempt_is_running_before_terminal_record(self):
        self._write_queue([self._item(retry_exit_codes=[2], max_attempts=2)])
        runner = RecordingRunner([2, 0], log_dir=self.log_dir)

        self._run(runner)

        self.assertEqual(runner.running_seen, ["running", "running"])
        self.assertEqual(len(list(self.log_dir.glob("*.json"))), 2)

    def test_default_max_attempts_is_one_even_with_retry_code(self):
        self._write_queue([self._item(retry_exit_codes=[2])])
        runner = RecordingRunner([2])

        result = self._run(runner)

        self.assertEqual(len(runner.calls), 1)
        self.assertIsNone(result["stopped"])

    def test_empty_queue_is_clean(self):
        self._write_queue([])
        result = self._run(RecordingRunner([]))
        self.assertEqual(result, {"runs": [], "stopped": None})

    def test_negative_budget_is_rejected(self):
        self._write_queue([self._item()])
        with self.assertRaises(ValueError):
            self._run(RecordingRunner([]), budget_s=-1)

    def test_second_queue_is_refused_until_the_lock_is_released(self):
        self._write_queue([self._item()])
        self.log_dir.mkdir(parents=True, exist_ok=True)
        holder = QueueLock(self.log_dir)
        holder.__enter__()
        try:
            with self.assertRaises(QueueLocked):
                self._run(RecordingRunner([0]))
        finally:
            holder.__exit__(None, None, None)

    def test_unlocked_persisted_lock_file_is_reacquired(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.log_dir / ".queue.lock"
        lock_path.write_text(
            "\0" + json.dumps({"pid": 999999, "created_at": "old"}),
            encoding="utf-8",
        )

        lock = QueueLock(self.log_dir)
        with lock:
            self.assertTrue(lock_path.is_file())

    def test_malformed_metadata_does_not_block_a_free_os_lock(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.log_dir / ".queue.lock"
        lock_path.write_text("\0not-json", encoding="utf-8")

        lock = QueueLock(self.log_dir)
        with lock:
            self.assertTrue(lock_path.is_file())

    def test_held_os_lock_is_refused(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.log_dir / ".queue.lock"
        first = QueueLock(self.log_dir)
        second = QueueLock(self.log_dir)
        first.__enter__()
        try:
            with self.assertRaises(QueueLocked):
                second.__enter__()
        finally:
            first.__exit__(None, None, None)
        self.assertTrue(lock_path.is_file())

    def test_queue_lock_is_released_after_run(self):
        self._write_queue([self._item()])

        self._run(RecordingRunner([0]))
        self._run(RecordingRunner([0]))

        with QueueLock(self.log_dir):
            pass

    def test_gpu_budget_stops_before_next_item(self):
        self._write_queue([self._item("first"), self._item("second")])
        meter = FakeGpuMeter([6, 6])

        result = self._run(
            RecordingRunner([0, 0]),
            gpu_budget_s=5,
            gpu_meter_factory=lambda: meter,
        )

        self.assertEqual(
            [run["status"] for run in result["runs"]],
            ["complete", "skipped-gpu-budget"],
        )
        self.assertEqual(result["runs"][1]["attempts"], 0)
        self.assertEqual(result["stopped"], "gpu-budget")
        self.assertEqual(
            self._records()[0]["resource_usage"]["gpu_seconds"],
            6,
        )
        self.assertIsNone(self._records()[0]["metrics"])

    def test_gpu_budgeted_run_still_reports_metrics_pending(self):
        self._write_queue([self._item()])
        meter = FakeGpuMeter([2])

        self._run(
            RecordingRunner([0]),
            gpu_budget_s=10,
            gpu_meter_factory=lambda: meter,
        )

        problems, _advisories = check_runs(self.log_dir)
        self.assertIn(
            "run-log-metrics-pending",
            [problem.code for problem in problems],
        )

    def test_gpu_budget_requires_a_meter(self):
        self._write_queue([self._item()])

        class BrokenMeter:
            def start(self):
                raise ValueError("nvidia-smi unavailable")

            def stop(self):
                return {"seconds": 0, "samples": 0, "errors": 0}

        with self.assertRaisesRegex(ValueError, "nvidia-smi"):
            self._run(
                RecordingRunner([0]),
                gpu_budget_s=10,
                gpu_meter_factory=BrokenMeter,
            )

    def test_zero_gpu_budget_skips_without_starting_a_meter(self):
        self._write_queue([self._item("first"), self._item("second")])

        def fail_factory():
            raise AssertionError("meter should not start for a zero budget")

        result = self._run(
            RecordingRunner([]),
            gpu_budget_s=0,
            gpu_meter_factory=fail_factory,
        )

        self.assertEqual(
            [run["status"] for run in result["runs"]],
            ["skipped-gpu-budget", "skipped-gpu-budget"],
        )
        self.assertEqual(result["stopped"], "gpu-budget")

    def test_gpu_sampling_error_is_recorded_before_tool_error(self):
        self._write_queue([self._item()])
        meter = FakeGpuMeter(
            [{"seconds": 1.5, "samples": 1, "errors": 1}]
        )

        with self.assertRaisesRegex(ValueError, "GPU"):
            self._run(
                RecordingRunner([0]),
                gpu_budget_s=10,
                gpu_meter_factory=lambda: meter,
            )

        metrics = self._records()[0]["metrics"]
        self.assertIsNone(metrics)
        resource_usage = self._records()[0]["resource_usage"]
        self.assertEqual(resource_usage["gpu_seconds"], 1.5)
        self.assertEqual(resource_usage["gpu_sampling_errors"], 1)

    def test_stall_is_recorded_and_not_retried_by_default(self):
        self._write_queue(
            [
                self._item(
                    stall_timeout_s=1,
                    max_attempts=2,
                )
            ]
        )
        runner = RecordingRunner([QueueStalled("no output")])

        result = self._run(runner)

        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(result["runs"][0]["status"], "stalled")
        metrics = self._records()[0]["metrics"]
        self.assertTrue(metrics["stalled"])
        self.assertEqual(metrics["stall_timeout_s"], 1)

    def test_stall_retries_only_when_declared(self):
        self._write_queue(
            [
                self._item(
                    stall_timeout_s=1,
                    retry_on_stall=True,
                    max_attempts=2,
                )
            ]
        )
        runner = RecordingRunner([QueueStalled("no output"), 0])

        result = self._run(runner)

        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(result["runs"][0]["status"], "complete")
        self.assertEqual(
            [record["status"] for record in self._records()],
            ["failed", "completed"],
        )

    def test_sandbox_policy_rejects_cwd_escape(self):
        self._write_queue([self._item(cwd="..")])

        with self.assertRaisesRegex(ValueError, "沙箱策略"):
            self._run(None, sandbox="policy")

    def test_sandbox_policy_rejects_absolute_external_cwd(self):
        self._write_queue([self._item(cwd=str(self.root.parent))])

        with self.assertRaisesRegex(ValueError, "沙箱策略"):
            self._run(None, sandbox="policy")

    def test_sandbox_policy_accepts_no_cwd_with_relative_queue_root(self):
        resolved = _item_cwd(Path("."), self._item(), sandbox=True)

        self.assertTrue(resolved.is_absolute())

    def test_policy_sandbox_rejects_injected_runner(self):
        self._write_queue([self._item()])

        with self.assertRaisesRegex(ValueError, "默认 runner"):
            self._run(RecordingRunner([0]), sandbox="policy")

    def test_sandbox_policy_is_recorded_outside_metrics(self):
        self._write_queue(
            [
                self._item(
                    command=[sys.executable, "-c", "print('ok')"],
                )
            ]
        )

        self._run(None, sandbox="policy")

        record = self._records()[0]
        self.assertEqual(record["policy"]["sandbox"], "policy")
        self.assertIsNone(record["metrics"])

    def test_sandbox_env_drops_non_allowlisted_variables(self):
        env = _sandbox_env(
            {
                "PATH": "path",
                "SystemRoot": "root",
                "OPENAI_API_KEY": "secret",
                "HF_TOKEN": "secret2",
            }
        )

        self.assertEqual(env["PATH"], "path")
        self.assertEqual(env["SystemRoot"], "root")
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("HF_TOKEN", env)
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")


class TestDockerSandbox(QueueTests):
    def _docker_queue(self, items=None, **extra):
        self._write_queue(
            [self._item()] if items is None else items,
            sandbox="docker",
            docker_image="python:3.12-slim",
            **extra,
        )

    def test_docker_argv_exact_mounts_and_command_order(self):
        item = self._item(
            name="train",
            command=["python", "train.py"],
        )

        argv = _docker_argv(
            item,
            self.root,
            image="python:3.12-slim",
            network="none",
            gpus="all",
            output_relative="runs",
            env={},
            name="ccfa-test",
        )

        root = self.root.resolve()
        output_dir = (root / "runs").resolve()
        self.assertEqual(
            argv,
            [
                "docker",
                "run",
                "--rm",
                "--read-only",
                "--security-opt",
                "no-new-privileges",
                "--network",
                "none",
                "--tmpfs",
                "/tmp",
                "--name",
                "ccfa-test",
                "--mount",
                f"type=bind,source={root},target=/workspace,readonly",
                "--mount",
                f"type=bind,source={output_dir},target=/outputs",
                "--workdir",
                "/workspace",
                "--gpus",
                "all",
                "-e",
                "HOME=/tmp",
                "-e",
                "CCFA_WORKSPACE=/workspace",
                "-e",
                "CCFA_OUTPUT_DIR=/outputs",
                "python:3.12-slim",
                "python",
                "train.py",
            ],
        )

    def test_docker_argv_workdir_tracks_item_cwd(self):
        (self.root / "sub").mkdir()
        item = self._item(cwd="sub", command=["python", "train.py"])

        argv = _docker_argv(
            item,
            self.root,
            image="img",
            network="none",
            gpus=None,
            output_relative="runs",
            env={},
            name="ccfa-test",
        )

        self.assertEqual(argv[argv.index("--workdir") + 1], "/workspace/sub")
        self.assertNotIn("--gpus", argv)

    def test_docker_argv_rejects_output_escape(self):
        with self.assertRaisesRegex(ValueError, "逃出"):
            _docker_argv(
                self._item(),
                self.root,
                image="img",
                network="none",
                gpus=None,
                output_relative="../escape",
                env={},
                name="ccfa-test",
            )

    def test_docker_argv_rejects_root_output(self):
        with self.assertRaisesRegex(ValueError, "队列根"):
            _docker_argv(
                self._item(),
                self.root,
                image="img",
                network="none",
                gpus=None,
                output_relative=".",
                env={},
                name="ccfa-test",
            )

    def test_docker_argv_rejects_comma_in_mount_source(self):
        root = self.root / "has,comma"
        root.mkdir()

        with self.assertRaisesRegex(ValueError, "逗号"):
            _docker_argv(
                self._item(),
                root,
                image="img",
                network="none",
                gpus=None,
                output_relative="runs",
                env={},
                name="ccfa-test",
            )

    def test_docker_unavailable_fails_before_execution(self):
        self._docker_queue()
        runner = RecordingRunner([0])

        with mock.patch(
            "ccfa.queue._docker_available",
            side_effect=ValueError("Docker daemon 不可用"),
        ):
            with self.assertRaisesRegex(ValueError, "Docker daemon"):
                self._run(runner, sandbox="docker")

        self.assertEqual(runner.calls, [])

    def test_docker_available_maps_info_failure_to_tool_error(self):
        from ccfa.queue import _docker_available

        completed = mock.Mock(returncode=1, stdout="", stderr="daemon down")
        with mock.patch(
            "ccfa.queue.subprocess.run", return_value=completed
        ):
            with self.assertRaisesRegex(ValueError, "daemon down"):
                _docker_available()

    def test_docker_available_accepts_a_running_daemon(self):
        from ccfa.queue import _docker_available

        completed = mock.Mock(returncode=0, stdout="27.0.0", stderr="")
        with mock.patch(
            "ccfa.queue.subprocess.run", return_value=completed
        ) as run:
            _docker_available()

        self.assertEqual(run.call_args.args[0][:2], ["docker", "info"])

    def test_docker_mode_rejects_cwd_escape(self):
        self._docker_queue([self._item(cwd="..")])
        runner = RecordingRunner([0])

        with mock.patch("ccfa.queue._docker_available"):
            with self.assertRaisesRegex(ValueError, "沙箱策略"):
                self._run(
                    runner,
                    sandbox="docker",
                    allow_injected_runner=True,
                )

        self.assertEqual(runner.calls, [])

    def test_docker_mode_rejects_injected_runner_by_default(self):
        self._docker_queue()
        runner = RecordingRunner([0])

        with mock.patch("ccfa.queue._docker_available"):
            with self.assertRaisesRegex(ValueError, "注入 runner"):
                self._run(runner, sandbox="docker")

        self.assertEqual(runner.calls, [])

    def test_docker_manifest_downgrade_requires_explicit_flag(self):
        self._docker_queue()
        runner = RecordingRunner([0])

        with self.assertRaisesRegex(ValueError, "allow-sandbox-downgrade"):
            self._run(runner, sandbox="none")

        self.assertEqual(runner.calls, [])

    def test_docker_manifest_downgrade_runs_only_with_explicit_flag(self):
        self._docker_queue()
        runner = RecordingRunner([0])

        result = self._run(
            runner,
            sandbox="none",
            allow_sandbox_downgrade=True,
        )

        self.assertEqual(result["runs"][0]["status"], "complete")
        self.assertEqual(runner.calls[0]["argv"], ["python", "-c", "print('ok')"])
        self.assertIsNone(self._records()[0]["policy"])

    def test_docker_argv_symlink_escape_leaves_no_running_record(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        link = self.root / "runs"
        try:
            link.symlink_to(outside.name, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("当前平台不允许创建目录 symlink")
        self._docker_queue()

        with mock.patch("ccfa.queue._docker_available"):
            with self.assertRaisesRegex(ValueError, "逃出"):
                self._run(
                    RecordingRunner([0]),
                    sandbox="docker",
                    allow_injected_runner=True,
                )

        self.assertEqual(self._records(), [])

    def test_docker_argv_failure_does_not_start_the_gpu_meter(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        link = self.root / "runs"
        try:
            link.symlink_to(outside.name, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("当前平台不允许创建目录 symlink")
        self._docker_queue()
        meter = FakeGpuMeter([1])

        with mock.patch("ccfa.queue._docker_available"):
            with self.assertRaisesRegex(ValueError, "逃出"):
                self._run(
                    RecordingRunner([0]),
                    sandbox="docker",
                    gpu_budget_s=10,
                    gpu_meter_factory=lambda: meter,
                    allow_injected_runner=True,
                )

        self.assertEqual(meter.starts, 0)
        self.assertEqual(meter.stops, 0)

    def test_main_docker_unavailable_exits_two_without_a_record(self):
        self._docker_queue()
        stdout = StringIO()
        stderr = StringIO()

        with mock.patch(
            "ccfa.queue._docker_available",
            side_effect=ValueError("Docker daemon 不可用"),
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(
                    [
                        "queue",
                        "run",
                        "--queue",
                        str(self.queue_path),
                        "--log-dir",
                        str(self.log_dir),
                    ]
                )

        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Docker daemon", stderr.getvalue())
        self.assertEqual(
            list(self.log_dir.glob("*.json")) if self.log_dir.exists() else [],
            [],
        )

    def test_docker_mode_records_policy_and_original_command(self):
        self._docker_queue()
        runner = RecordingRunner([0])

        with mock.patch("ccfa.queue._docker_available"), mock.patch(
            "ccfa.queue._docker_remove"
        ):
            result = self._run(
                runner,
                sandbox="docker",
                allow_injected_runner=True,
            )

        self.assertEqual(result["runs"][0]["status"], "complete")
        self.assertEqual(len(runner.calls), 1)
        docker_argv = runner.calls[0]["argv"]
        self.assertEqual(docker_argv[:3], ["docker", "run", "--rm"])
        record = self._records()[0]
        self.assertEqual(record["command"], ["python", "-c", "print('ok')"])
        self.assertEqual(
            record["policy"],
            {
                "sandbox": "docker",
                "image": "python:3.12-slim",
                "network": "none",
                "gpus": None,
                "output": "runs",
                "workdir": "/workspace",
            },
        )
        self.assertIsNone(record["metrics"])

    def test_docker_mode_does_not_forward_host_env_into_the_container(self):
        self._docker_queue()
        runner = RecordingRunner([0])

        with mock.patch.dict(
            os.environ, {"QUEUE_TEST_SECRET": "SHOULD_NOT_LEAK"}
        ), mock.patch("ccfa.queue._docker_available"), mock.patch(
            "ccfa.queue._docker_remove"
        ):
            self._run(
                runner,
                sandbox="docker",
                allow_injected_runner=True,
            )

        docker_argv = runner.calls[0]["argv"]
        self.assertFalse(
            any(part.startswith("QUEUE_TEST_SECRET=") for part in docker_argv)
        )
        self.assertNotIn("SHOULD_NOT_LEAK", docker_argv)

    def test_docker_timeout_cleans_up_the_container(self):
        self._docker_queue([self._item(timeout_s=5)])
        runner = RecordingRunner([subprocess.TimeoutExpired(["python"], 5)])

        with mock.patch("ccfa.queue._docker_available"), mock.patch(
            "ccfa.queue._docker_remove"
        ) as remove:
            result = self._run(
                runner,
                sandbox="docker",
                allow_injected_runner=True,
            )

        self.assertEqual(result["runs"][0]["status"], "timeout")
        self.assertEqual(remove.call_count, 1)
        name = remove.call_args.args[0]
        self.assertTrue(name.startswith("ccfa-"))
        self.assertIn(name, runner.calls[0]["argv"])

    def test_cli_docker_override_requires_manifest_image(self):
        self._write_queue([self._item()])

        with self.assertRaisesRegex(ValueError, "docker_image"):
            self._run(RecordingRunner([0]), sandbox="docker")


class TestDefaultRunner(QueueTests):
    def test_default_runner_uses_shell_false(self):
        process = FakeProcess(returncode=0)
        with mock.patch("ccfa.queue.subprocess.Popen", return_value=process) as popen:
            from ccfa.queue import _default_runner

            code = _default_runner(["cmd"], self.root, None)

        self.assertEqual(code, 0)
        self.assertFalse(popen.call_args.kwargs["shell"])
        self.assertEqual(popen.call_args.kwargs["cwd"], str(self.root))

    def test_default_runner_streams_output_before_child_exits(self):
        from ccfa.queue import _default_runner

        ready = self.root / "first-flushed"
        go_ahead = self.root / "child-may-finish"
        script = (
            "import pathlib, time\n"
            "print('FIRST', flush=True)\n"
            f"pathlib.Path({str(ready)!r}).write_text('ready', encoding='utf-8')\n"
            "deadline = time.monotonic() + 30\n"
            f"while not pathlib.Path({str(go_ahead)!r}).exists() "
            "and time.monotonic() < deadline:\n"
            "    time.sleep(0.02)\n"
            "print('SECOND', flush=True)\n"
        )
        stderr = StringIO()
        result = {}

        def invoke():
            with redirect_stderr(stderr):
                result["code"] = _default_runner(
                    [sys.executable, "-c", script],
                    self.root,
                    None,
                )

        worker = threading.Thread(target=invoke)
        worker.start()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not ready.exists():
            time.sleep(0.02)

        self.assertTrue(ready.exists(), "child never signalled its first flush")
        # The child is still parked on go_ahead, so FIRST can only be here if
        # the runner forwarded it while the child was still running.
        self.assertTrue(worker.is_alive())
        self.assertIn("FIRST", stderr.getvalue())
        self.assertNotIn("SECOND", stderr.getvalue())
        go_ahead.write_text("go", encoding="utf-8")
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result["code"], 0)
        self.assertIn("SECOND", stderr.getvalue())

    def test_default_runner_forwards_partial_output_on_timeout(self):
        from ccfa.queue import _default_runner

        script = (
            "import sys, time\n"
            "print('PARTIAL_STDOUT', flush=True)\n"
            "print('PARTIAL_STDERR', file=sys.stderr, flush=True)\n"
            "time.sleep(5)\n"
        )
        stderr = StringIO()
        with redirect_stderr(stderr), self.assertRaises(subprocess.TimeoutExpired):
            _default_runner([sys.executable, "-c", script], self.root, 1.0)

        self.assertIn("PARTIAL_STDOUT", stderr.getvalue())
        self.assertIn("PARTIAL_STDERR", stderr.getvalue())

    def test_default_runner_stall_watchdog_kills_silent_child(self):
        from ccfa.queue import _default_runner

        script = (
            "import time\n"
            "print('READY', flush=True)\n"
            "time.sleep(5)\n"
        )
        stderr = StringIO()

        with redirect_stderr(stderr), self.assertRaises(QueueStalled):
            _default_runner(
                [sys.executable, "-c", script],
                self.root,
                10,
                stall_timeout_s=0.3,
            )

        self.assertIn("READY", stderr.getvalue())

    def test_default_runner_watchdog_does_not_kill_no_newline_progress(self):
        from ccfa.queue import _default_runner

        script = (
            "import sys, time\n"
            "for _ in range(12):\n"
            "    sys.stdout.write('PROGRESS')\n"
            "    sys.stdout.flush()\n"
            "    time.sleep(0.05)\n"
        )
        stderr = StringIO()

        with redirect_stderr(stderr):
            code = _default_runner(
                [sys.executable, "-c", script],
                self.root,
                10,
                stall_timeout_s=0.3,
            )

        self.assertEqual(code, 0)
        self.assertIn("PROGRESS", stderr.getvalue())

    def test_default_runner_env_does_not_leak_non_allowlisted_values(self):
        from ccfa.queue import _default_runner

        env = _sandbox_env(
            {
                **os.environ,
                "QUEUE_TEST_SECRET": "SHOULD_NOT_LEAK",
            }
        )
        script = (
            "import os\n"
            "print(os.environ.get('QUEUE_TEST_SECRET', 'MISSING'))\n"
        )
        stderr = StringIO()

        with redirect_stderr(stderr):
            code = _default_runner(
                [sys.executable, "-c", script],
                self.root,
                10,
                env=env,
            )

        self.assertEqual(code, 0)
        self.assertIn("MISSING", stderr.getvalue())
        self.assertNotIn("SHOULD_NOT_LEAK", stderr.getvalue())


class TestRunLogIntegration(QueueTests):
    def test_queue_records_resolved_cwd_in_run_log_field(self):
        sub = self.root / "sub"
        sub.mkdir()
        self._write_queue([self._item(cwd="sub")])

        self._run(RecordingRunner([0]))

        record = self._records()[0]
        self.assertEqual(record["cwd"], str(sub.resolve()))
        self.assertIsNone(record["metrics"])

    def test_completed_queue_run_still_reports_metrics_pending(self):
        self._write_queue([self._item()])

        self._run(RecordingRunner([0]))

        problems, _ = check_runs(self.log_dir)
        self.assertIn(
            "run-log-metrics-pending",
            [problem.code for problem in problems],
        )


class TestMain(QueueTests):
    def test_missing_cwd_still_records_failed_then_exits_two(self):
        self._write_queue([self._item(cwd="does-not-exist")])
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                [
                    "queue",
                    "run",
                    "--queue",
                    str(self.queue_path),
                    "--log-dir",
                    str(self.log_dir),
                ]
            )

        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("工具错误", stderr.getvalue())
        records = self._records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "failed")

    def test_real_child_stdout_is_forwarded_to_stderr_not_stdout(self):
        self._write_queue(
            [
                self._item(
                    command=[
                        sys.executable,
                        "-c",
                        "print('CHILD_STDOUT_MARKER')",
                    ]
                )
            ]
        )
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                [
                    "queue",
                    "run",
                    "--queue",
                    str(self.queue_path),
                    "--log-dir",
                    str(self.log_dir),
                ]
            )

        self.assertEqual(code, 0)
        parsed = json.loads(stdout.getvalue())
        self.assertEqual(parsed["runs"][0]["status"], "complete")
        self.assertIn("CHILD_STDOUT_MARKER", stderr.getvalue())
        self.assertNotIn("CHILD_STDOUT_MARKER", stdout.getvalue())

    def test_help_and_docstring_state_missing_cwd_behavior(self):
        import ccfa.queue as queue_module

        self.assertIn("cwd 不存在", queue_module.__doc__)
        self.assertIn("cwd 不存在", build_parser().format_help())
        self.assertIn("stdout 只输出 JSON", queue_module.__doc__)
        self.assertIn("子进程 stdout/stderr", queue_module.__doc__)
        self.assertIn("转发到 stderr", queue_module.__doc__)
        self.assertIn("--gpu-budget", build_parser().format_help())
        self.assertIn("stall_timeout_s", build_parser().format_help())
        self.assertIn("不是 OS 隔离", build_parser().format_help())
        self.assertIn("sandbox=docker", build_parser().format_help())
        self.assertIn("docker_output", build_parser().format_help())
        self.assertIn("Docker daemon", build_parser().format_help())
        self.assertIn("sandbox=docker", queue_module.__doc__)
        self.assertIn(
            "security boundary against a malicious image",
            queue_module.__doc__,
        )

    def test_main_passes_long_task_safety_options(self):
        self._write_queue([self._item()])
        with mock.patch(
            "ccfa.queue.run_queue",
            return_value={"runs": [], "stopped": None},
        ) as run:
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                code = main(
                    [
                        "queue",
                        "run",
                        "--queue",
                        str(self.queue_path),
                        "--log-dir",
                        str(self.log_dir),
                        "--gpu-budget-seconds",
                        "12",
                        "--sandbox",
                        "policy",
                        "--allow-sandbox-downgrade",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertEqual(run.call_args.kwargs["gpu_budget_s"], 12)
        self.assertEqual(run.call_args.kwargs["sandbox"], "policy")
        self.assertTrue(run.call_args.kwargs["allow_sandbox_downgrade"])

    def test_main_success_zero_failure_one_and_invalid_two(self):
        self._write_queue([self._item()])
        with mock.patch(
            "ccfa.queue.run_queue",
            return_value={"runs": [{"name": "run-1", "attempts": 1, "status": "complete"}], "stopped": None},
        ):
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "queue",
                            "run",
                            "--queue",
                            str(self.queue_path),
                            "--log-dir",
                            str(self.log_dir),
                        ]
                    ),
                    0,
                )

        with mock.patch(
            "ccfa.queue.run_queue",
            return_value={"runs": [{"name": "run-1", "attempts": 1, "status": "failed"}], "stopped": None},
        ):
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "queue",
                            "run",
                            "--queue",
                            str(self.queue_path),
                            "--log-dir",
                            str(self.log_dir),
                        ]
                    ),
                    1,
                )

        self.queue_path.write_text("{bad json", encoding="utf-8")
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(
                main(
                    [
                        "queue",
                        "run",
                        "--queue",
                        str(self.queue_path),
                        "--log-dir",
                        str(self.log_dir),
                    ]
                ),
                2,
            )


if __name__ == "__main__":
    unittest.main()
