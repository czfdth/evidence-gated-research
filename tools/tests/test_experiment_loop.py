import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.experiment_loop import check, next_actions, run_next


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


class ExperimentLoopTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "data").mkdir()
        (self.paper / "experiments" / "log").mkdir(parents=True)
        (self.paper / "experiments" / "log" / "RUN1.json").write_text(
            json.dumps({"run_id": "RUN1", "status": "completed"}),
            encoding="utf-8",
        )
        _write_yaml(
            self.paper / "data" / "claim-registry.yaml",
            {
                "version": 1,
                "claims": [
                    {
                        "id": "C1",
                        "statement": "测试 claim",
                        "type": "empirical",
                    }
                ],
            },
        )

    def _write_loop(self, payload: dict) -> None:
        payload = {"version": 1, **payload}
        _write_yaml(self.paper / "data" / "experiment-loop.yaml", payload)

    def _valid_loop(self) -> dict:
        return {
            "not_applicable": False,
            "not_applicable_reason": "",
            "ideas": [
                {
                    "id": "I1",
                    "statement": "候选方案 A",
                    "status": "promoted",
                    "pilot_budget_minutes": 30,
                    "pilot_metric": "AUC",
                    "kill_criterion": "AUC < 0.6",
                    "run_ids": ["RUN1"],
                    "decision": "promote",
                    "decision_rationale": "pilot 通过阈值",
                }
            ],
            "inner_loop": [
                {
                    "id": "L1",
                    "claim_id": "C1",
                    "run_id": "RUN1",
                    "change": "增加 baseline",
                    "hypothesis": "baseline 会降低误差",
                    "metric": "AUC",
                    "result": "improved",
                    "decision": "keep",
                    "next_action": "扩展到第二个数据集",
                }
            ],
            "outer_loop": [
                {
                    "id": "O1",
                    "claim_ids": ["C1"],
                    "evidence_run_ids": ["RUN1"],
                    "decision": "continue",
                    "rationale": "当前证据支持继续",
                    "next_action": "运行消融实验",
                }
            ],
        }

    def test_not_applicable_requires_reason(self):
        self._write_loop(
            {
                "not_applicable": True,
                "not_applicable_reason": "",
                "ideas": [],
                "inner_loop": [],
                "outer_loop": [],
            }
        )

        problems, _advisories = check(self.paper)

        self.assertIn(
            "experiment-loop-na-reason-missing",
            [problem.code for problem in problems],
        )

    def test_not_applicable_with_reason_passes(self):
        self._write_loop(
            {
                "not_applicable": True,
                "not_applicable_reason": "纯 SoK，没有实验 claim",
                "ideas": [],
                "inner_loop": [],
                "outer_loop": [],
            }
        )

        problems, advisories = check(self.paper)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_empty_loop_is_advisory(self):
        self._write_loop(
            {
                "not_applicable": False,
                "ideas": [],
                "inner_loop": [],
                "outer_loop": [],
            }
        )

        problems, advisories = check(self.paper)

        self.assertEqual(problems, [])
        self.assertIn(
            "experiment-loop-empty",
            [advisory.code for advisory in advisories],
        )

    def test_valid_loop_passes_cross_checks(self):
        self._write_loop(self._valid_loop())

        problems, advisories = check(self.paper)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_unknown_run_id_is_a_problem(self):
        payload = self._valid_loop()
        payload["inner_loop"][0]["run_id"] = "RUN404"
        self._write_loop(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "experiment-loop-unknown-run",
            [problem.code for problem in problems],
        )

    def test_unknown_claim_id_is_a_problem(self):
        payload = self._valid_loop()
        payload["outer_loop"][0]["claim_ids"] = ["C404"]
        self._write_loop(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "experiment-loop-unknown-claim",
            [problem.code for problem in problems],
        )

    def test_invalid_enums_are_problems(self):
        payload = self._valid_loop()
        payload["ideas"][0]["status"] = "maybe"
        payload["inner_loop"][0]["decision"] = "whatever"
        self._write_loop(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "experiment-loop-invalid",
            [problem.code for problem in problems],
        )

    def test_placeholder_is_a_problem(self):
        payload = self._valid_loop()
        payload["ideas"][0]["statement"] = "TODO"
        self._write_loop(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "experiment-loop-placeholder",
            [problem.code for problem in problems],
        )

    def test_next_actions_reports_pending_work(self):
        payload = self._valid_loop()
        payload["ideas"][0]["status"] = "pilot-planned"
        payload["ideas"][0]["pilot_command"] = ["python", "-c", "print('pilot')"]
        payload["inner_loop"][0].update({"result": "pending", "decision": "pending"})
        payload["outer_loop"][0].update({"decision": "pending"})
        self._write_loop(payload)

        result = next_actions(self.paper)

        self.assertEqual(result["pilot"][0]["id"], "I1")
        self.assertEqual(result["inner"][0]["id"], "L1")
        self.assertEqual(result["outer"][0]["id"], "O1")

    def test_next_actions_hands_the_pilot_budget_to_the_executor(self):
        payload = self._valid_loop()
        payload["ideas"][0]["status"] = "pilot-planned"
        payload["ideas"][0]["pilot_budget_minutes"] = 45
        payload["ideas"][0]["pilot_gpus"] = 1
        payload["ideas"][0]["pilot_command"] = ["python", "-c", "print('pilot')"]
        self._write_loop(payload)

        command = next_actions(self.paper)["pilot"][0]["suggested_command"]

        self.assertIn("compute.ps1 run", command)
        self.assertIn("--minutes 45", command)
        self.assertIn("--gpus 1", command)
        self.assertIn("print('pilot')", command)

    def test_pilot_planned_requires_command(self):
        payload = self._valid_loop()
        payload["ideas"][0]["status"] = "pilot-planned"
        self._write_loop(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "experiment-loop-invalid",
            [problem.code for problem in problems],
        )

    def test_run_next_dry_run_does_not_create_outputs(self):
        payload = self._valid_loop()
        payload["ideas"][0]["status"] = "pilot-planned"
        payload["ideas"][0]["pilot_command"] = ["python", "-c", "print('pilot')"]
        self._write_loop(payload)

        result = run_next(self.paper)

        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(result["idea_id"], "I1")
        self.assertFalse((self.paper / "experiments" / "log" / "compute-ledger.jsonl").exists())

    def test_run_next_executes_and_records_both_ledgers(self):
        payload = self._valid_loop()
        payload["ideas"][0]["status"] = "pilot-planned"
        payload["ideas"][0]["pilot_command"] = [
            sys.executable,
            "-c",
            "print('pilot')",
        ]
        self._write_loop(payload)

        result = run_next(self.paper, execute=True)

        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(
            (self.paper / "experiments" / "log" / f"{result['run_id']}.json").is_file()
        )
        self.assertTrue((self.paper / "experiments" / "log" / "compute-ledger.jsonl").is_file())

    def test_running_pilot_has_no_suggested_command(self):
        payload = self._valid_loop()
        payload["ideas"][0]["status"] = "pilot-running"
        self._write_loop(payload)

        entry = next_actions(self.paper)["pilot"][0]

        self.assertIsNone(entry["suggested_command"])

    def test_next_actions_rejects_an_invalid_ledger(self):
        payload = self._valid_loop()
        payload["inner_loop"][0]["run_id"] = "RUN404"
        self._write_loop(payload)

        with self.assertRaisesRegex(ValueError, "experiment-loop"):
            next_actions(self.paper)


if __name__ == "__main__":
    unittest.main()
