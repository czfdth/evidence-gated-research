import ctypes
import json
import os
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.experiment_optimizer import check_spec, run_optimization


class ExperimentOptimizerTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "data").mkdir()
        (self.paper / "data" / "claim-registry.yaml").write_text(
            "version: 1\nclaims:\n  - id: C1\n    statement: Demo claim\n",
            encoding="utf-8",
        )
        self.spec = self.paper / "data" / "experiment-optimization.yaml"
        self.spec.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "id": "TEST",
                    "claim_id": "C1",
                    "objective": {
                        "name": "metrics.accuracy",
                        "direction": "maximize",
                        "baseline": 0.5,
                        "min_delta": 0.0,
                    },
                    "budget": {
                        "max_trials": 4,
                        "minutes_per_trial": 1,
                        "gpus_per_trial": 0,
                    },
                    "command": [
                        "{python}",
                        "--lr",
                        "{lr}",
                        "--metrics",
                        "{metrics_path}",
                    ],
                    "search_space": {"lr": [0.1, 0.2]},
                    "strategy": "grid",
                    "patience": 0,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def test_dry_run_lists_trials_without_writing_claims(self):
        result = run_optimization(self.paper, spec_path=self.spec)

        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(result["count"], 2)
        self.assertFalse(
            (self.paper / "data" / "experiment-optimization-proposals.yaml").exists()
        )

    def test_run_executes_grid_and_writes_a_proposal(self):
        def runner(argv, _cwd):
            metrics_path = Path(argv[argv.index("--metrics") + 1])
            lr = float(argv[argv.index("--lr") + 1])
            metrics_path.write_text(
                json.dumps({"metrics": {"accuracy": 0.5 + lr}}),
                encoding="utf-8",
            )
            return 0, ""

        result = run_optimization(
            self.paper,
            spec_path=self.spec,
            execute=True,
            runner=runner,
        )

        self.assertEqual(result["status"], "executed")
        self.assertAlmostEqual(result["best"]["value"], 0.7)
        proposals = yaml.safe_load(
            (self.paper / "data" / "experiment-optimization-proposals.yaml").read_text(
                encoding="utf-8"
            )
        )
        proposal = proposals["proposals"][0]
        self.assertEqual(proposal["status"], "proposed")
        self.assertEqual(proposal["proposed_inner_loop"]["decision"], "keep")
        self.assertEqual(proposal["human_review"], "pending")
        self.assertEqual(
            (self.paper / "data" / "claim-registry.yaml").read_text(
                encoding="utf-8"
            ),
            "version: 1\nclaims:\n  - id: C1\n    statement: Demo claim\n",
        )

    def _execute_with(self, spec_path):
        def runner(argv, _cwd):
            metrics_path = Path(argv[argv.index("--metrics") + 1])
            lr = float(argv[argv.index("--lr") + 1])
            metrics_path.write_text(
                json.dumps({"metrics": {"accuracy": 0.5 + lr}}),
                encoding="utf-8",
            )
            return 0, ""

        return run_optimization(
            self.paper,
            spec_path=spec_path,
            execute=True,
            runner=runner,
        )

    def _short_path(self, path: Path):
        """Return the Windows 8.3 form of *path*, or None when unavailable."""
        if os.name != "nt":
            return None
        buffer = ctypes.create_unicode_buffer(512)
        length = ctypes.windll.kernel32.GetShortPathNameW(
            str(path),
            buffer,
            512,
        )
        if not length:
            return None
        short = Path(buffer.value)
        return short if str(short) != str(path) else None

    def test_spec_reached_through_a_windows_short_path_is_still_inside(self):
        # The CI runner failed exactly here: paper_root resolved to the long
        # name while the spec kept the 8.3 short name (RUNNER~1), so
        # spec_file.relative_to(paper_root) raised on a file that is inside the
        # paper. Resolving the spec before the comparison is the fix.
        short_root = self._short_path(self.paper)
        if short_root is None:
            self.skipTest("8.3 短路径在此文件系统不可用")

        result = self._execute_with(
            short_root / "data" / "experiment-optimization.yaml"
        )

        self.assertEqual(result["status"], "executed")

    def test_check_rejects_a_command_without_metrics_path(self):
        payload = yaml.safe_load(self.spec.read_text(encoding="utf-8"))
        payload["command"] = ["{python}", "--lr", "{lr}"]
        self.spec.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

        problems = check_spec(self.paper, self.spec)

        self.assertIn(
            "experiment-optimization-invalid",
            [problem.code for problem in problems],
        )

    def test_check_rejects_unknown_claim(self):
        payload = yaml.safe_load(self.spec.read_text(encoding="utf-8"))
        payload["claim_id"] = "C404"
        self.spec.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

        problems = check_spec(self.paper, self.spec)

        self.assertIn(
            "experiment-optimization-unknown-claim",
            [problem.code for problem in problems],
        )


if __name__ == "__main__":
    unittest.main()
