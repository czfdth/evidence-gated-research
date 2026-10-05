import json
import sys
import tempfile
import unittest
from pathlib import Path

import ccfa.compute as compute
from ccfa.compute import (
    Attempt,
    LocalResources,
    RemoteBackend,
    append_attempt,
    load_backends,
    parse_nvidia_smi,
    plan,
    probe_local,
    run_local,
)


NVIDIA_CSV = (
    "0, NVIDIA GeForce RTX 5060 Laptop GPU, 8151 MiB, 12.0\n"
    "1, NVIDIA A100-SXM4-80GB, 81920 MiB, 8.0\n"
)


class ParseNvidiaSmiTests(unittest.TestCase):
    def test_parses_one_line_per_gpu(self):
        gpus = parse_nvidia_smi(NVIDIA_CSV)

        self.assertEqual(len(gpus), 2)
        self.assertEqual(gpus[0].name, "NVIDIA GeForce RTX 5060 Laptop GPU")
        self.assertEqual(gpus[0].memory_mib, 8151)
        self.assertEqual(gpus[0].compute_cap, "12.0")
        self.assertEqual(gpus[1].index, 1)

    def test_ignores_header_and_malformed_lines(self):
        raw = "index, name, memory.total, compute_cap\n" + NVIDIA_CSV + "garbage\n"

        gpus = parse_nvidia_smi(raw)

        self.assertEqual([gpu.index for gpu in gpus], [0, 1])

    def test_empty_output_yields_no_gpus(self):
        self.assertEqual(parse_nvidia_smi(""), [])


class ProbeLocalTests(unittest.TestCase):
    def test_reports_gpu_and_docker_nvidia_runtime(self):
        def run(argv):
            if argv[0] == "nvidia-smi":
                return 0, NVIDIA_CSV
            return 0, '{"runc":{}, "nvidia":{"path":"nvidia-container-runtime"}}'

        resources = probe_local(
            which=lambda name: f"/usr/bin/{name}",
            run=run,
            cpu_count=24,
            ram_gib=32.0,
        )

        self.assertEqual(resources.gpu_count, 2)
        self.assertTrue(resources.docker)
        self.assertTrue(resources.docker_gpu)
        self.assertEqual(resources.cpu_count, 24)

    def test_without_nvidia_smi_there_are_no_gpus(self):
        resources = probe_local(
            which=lambda name: "/usr/bin/docker" if name == "docker" else None,
            run=lambda argv: (0, '{"runc": {}}'),
            cpu_count=8,
            ram_gib=16.0,
        )

        self.assertEqual(resources.gpu_count, 0)
        self.assertFalse(resources.docker_gpu)

    def test_failing_nvidia_smi_does_not_raise(self):
        resources = probe_local(
            which=lambda name: "/usr/bin/nvidia-smi",
            run=lambda argv: (1, ""),
            cpu_count=4,
            ram_gib=8.0,
        )

        self.assertEqual(resources.gpu_count, 0)

    def test_docker_gpu_is_false_without_the_nvidia_runtime(self):
        resources = probe_local(
            which=lambda name: "/usr/bin/docker",
            run=lambda argv: (0, '{"runc": {}}'),
            cpu_count=4,
            ram_gib=8.0,
        )

        self.assertTrue(resources.docker)
        self.assertFalse(resources.docker_gpu)


class LoadBackendsTests(unittest.TestCase):
    def test_missing_config_means_no_remote(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_backends(Path(tmp)), [])

    def test_valid_backends_are_parsed_and_invalid_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data" / "compute.yaml").write_text(
                "backends:\n"
                "  - kind: slurm\n"
                "    host: hpc.example.edu\n"
                "    user: alice\n"
                "    partition: gpu\n"
                "    gpus: 4\n"
                "  - kind: kubernetes\n"
                "    host: ignored\n"
                "  - kind: pbs\n"
                "    host: legacy.example.edu\n",
                encoding="utf-8",
            )

            backends = load_backends(root)

        self.assertEqual(len(backends), 2)
        self.assertEqual(backends[0].target, "alice@hpc.example.edu")
        self.assertEqual(backends[0].gpus, 4)
        self.assertEqual(backends[1].kind, "pbs")

    def test_malformed_yaml_is_treated_as_unconfigured(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data" / "compute.yaml").write_text("backends: [", encoding="utf-8")
            self.assertEqual(load_backends(root), [])


class PlanTests(unittest.TestCase):
    def _resources(self, gpus=0, docker_gpu=False):
        return (
            LocalResources(cpu_count=8, ram_gib=16.0, gpus=[], docker=True, docker_gpu=docker_gpu)
            if gpus == 0
            else LocalResources(
                cpu_count=8,
                ram_gib=16.0,
                gpus=[compute.Gpu(0, "gpu", 8192, "12.0")],
                docker=True,
                docker_gpu=docker_gpu,
            )
        )

    def test_cpu_pilot_runs_locally(self):
        payload = plan(
            Path("."),
            budget_minutes=10,
            needs_gpu=False,
            resources=self._resources(),
            backends=[],
        )

        self.assertTrue(payload["local"]["usable"])
        self.assertEqual(payload["recommendation"], "local")

    def test_gpu_pilot_without_gpu_or_remote_is_blocked(self):
        payload = plan(
            Path("."),
            budget_minutes=10,
            needs_gpu=True,
            resources=self._resources(),
            backends=[],
        )

        self.assertFalse(payload["local"]["usable"])
        self.assertEqual(payload["recommendation"], "blocked")

    def test_gpu_pilot_uses_local_gpu_when_present(self):
        payload = plan(
            Path("."),
            budget_minutes=30,
            needs_gpu=True,
            resources=self._resources(gpus=1, docker_gpu=True),
            backends=[],
        )

        self.assertTrue(payload["local"]["usable"])
        self.assertTrue(payload["local"]["docker_gpu"])
        self.assertEqual(payload["recommendation"], "local")

    def test_configured_remote_is_recommended(self):
        payload = plan(
            Path("."),
            budget_minutes=30,
            needs_gpu=True,
            resources=self._resources(),
            backends=[RemoteBackend(kind="slurm", host="hpc", user="bob", gpus=8)],
        )

        self.assertTrue(payload["remote_configured"])
        self.assertEqual(payload["recommendation"], "remote")
        self.assertEqual(payload["remote"][0]["host"], "hpc")


class RunLocalTests(unittest.TestCase):
    def test_success_records_wall_time_and_gpu_minutes(self):
        attempt = run_local(
            [sys.executable, "-c", "print('ok')"],
            budget_minutes=1,
            gpus_used=2,
        )

        self.assertEqual(attempt.returncode, 0)
        self.assertFalse(attempt.timed_out)
        self.assertEqual(attempt.backend, "local")
        self.assertGreaterEqual(attempt.wall_seconds, 0.0)
        self.assertAlmostEqual(
            attempt.gpu_minutes,
            round(attempt.wall_seconds / 60.0 * 2, 3),
        )

    def test_command_over_budget_is_killed_and_flagged(self):
        attempt = run_local(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            budget_minutes=1 / 600,  # 0.1 s
        )

        self.assertTrue(attempt.timed_out)
        self.assertLess(attempt.wall_seconds, 15)

    def test_nonzero_exit_is_preserved(self):
        attempt = run_local(
            [sys.executable, "-c", "raise SystemExit(3)"],
            budget_minutes=1,
        )

        self.assertEqual(attempt.returncode, 3)
        self.assertFalse(attempt.timed_out)

    def test_nonpositive_budget_is_rejected(self):
        with self.assertRaises(ValueError):
            run_local([sys.executable, "-c", "pass"], budget_minutes=0)

    def test_attempt_is_appended_as_jsonl(self):
        attempt = Attempt(
            command="python train.py",
            backend="local",
            budget_minutes=5,
            wall_seconds=120.0,
            returncode=0,
            gpus_used=1,
            timed_out=False,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = append_attempt(Path(tmp), attempt)
            lines = path.read_text(encoding="utf-8").strip().splitlines()

        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["gpu_minutes"], 2.0)
        self.assertEqual(record["backend"], "local")
        self.assertRegex(
            record["recorded_at"],
            r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
        )


class CheckEnvironmentTests(unittest.TestCase):
    def test_no_gpu_and_no_remote_is_advisory_not_blocking(self):
        import unittest.mock as mock

        resources = LocalResources(cpu_count=4, ram_gib=8.0)
        with (
            mock.patch.object(compute, "probe_local", return_value=resources),
            mock.patch.object(compute, "load_backends", return_value=[]),
        ):
            problems, advisories = compute.check_environment(Path("."))

        self.assertEqual(problems, [])
        codes = {advisory.code for advisory in advisories}
        self.assertIn("compute-no-gpu-no-remote", codes)
        self.assertIn("compute-remote-unconfigured", codes)


if __name__ == "__main__":
    unittest.main()
