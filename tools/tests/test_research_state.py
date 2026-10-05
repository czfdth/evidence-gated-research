import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.research_state import check, next_actions


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


class ResearchStateTests(unittest.TestCase):
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
        (self.paper / "literature").mkdir()
        (self.paper / "src").mkdir()
        (self.paper / "to_human").mkdir()
        (self.paper / "paper").mkdir()
        (self.paper / "findings.md").write_text("# Findings\n", encoding="utf-8")
        (self.paper / "research-log.md").write_text("# Log\n", encoding="utf-8")

    def _write_state(self, payload: dict) -> None:
        _write_yaml(
            self.paper / "data" / "research-state.yaml",
            {"version": 1, **payload},
        )

    def _valid_state(self) -> dict:
        return {
            "project": {
                "title": "Test research",
                "question": "Does X improve Y?",
                "status": "active",
                "started": "2026-10-05",
                "domain": "computer science",
            },
            "literature": {
                "key_papers": ["gao2024ragsurvey"],
                "open_problems": ["gap A"],
                "evidence_gaps": ["missing benchmark"],
            },
            "hypotheses": [
                {
                    "id": "H1",
                    "statement": "X improves Y",
                    "status": "active",
                    "motivation": "prior work suggests it",
                    "parent": None,
                    "priority": "high",
                }
            ],
            "experiments": {
                "proxy_metric": "accuracy",
                "baseline_value": 0.7,
                "best_value": 0.8,
                "total_runs": 1,
                "trajectory": [
                    {
                        "run_id": "RUN1",
                        "hypothesis": "H1",
                        "metric_value": 0.8,
                        "delta": 0.1,
                        "wall_time_min": 5,
                        "change_summary": "add baseline",
                        "timestamp": "2026-10-05T00:00:00Z",
                    }
                ],
            },
            "outer_loop": {
                "cycle": 1,
                "last_direction": "deepen",
                "last_reflection": "effect is stable",
            },
            "workspace": {
                "findings": "findings.md",
                "log": "research-log.md",
                "literature_dir": "literature/",
                "experiments_dir": "experiments/",
                "to_human_dir": "to_human/",
                "paper_dir": "paper/",
            },
        }

    def test_not_started_is_advisory(self):
        self._write_state({"project": {"status": "paused"}})

        problems, advisories = check(self.paper)

        self.assertEqual(problems, [])
        self.assertIn(
            "research-state-empty",
            [advisory.code for advisory in advisories],
        )

    def test_valid_state_passes(self):
        self._write_state(self._valid_state())

        problems, advisories = check(self.paper)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_unknown_run_id_is_problem(self):
        payload = self._valid_state()
        payload["experiments"]["trajectory"][0]["run_id"] = "RUN404"
        self._write_state(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "research-state-unknown-run",
            [problem.code for problem in problems],
        )

    def test_unknown_parent_hypothesis_is_problem(self):
        payload = self._valid_state()
        payload["hypotheses"][0]["parent"] = "H404"
        self._write_state(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "research-state-unknown-hypothesis",
            [problem.code for problem in problems],
        )

    def test_trajectory_count_must_match_total_runs(self):
        payload = self._valid_state()
        payload["experiments"]["total_runs"] = 2
        self._write_state(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "research-state-run-count-mismatch",
            [problem.code for problem in problems],
        )

    def test_workspace_path_must_exist(self):
        payload = self._valid_state()
        payload["workspace"]["findings"] = "missing.md"
        self._write_state(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "research-state-missing-path",
            [problem.code for problem in problems],
        )

    def test_next_actions_reports_pending_hypothesis(self):
        payload = self._valid_state()
        payload["hypotheses"][0]["status"] = "pending"
        payload["experiments"]["trajectory"] = []
        payload["experiments"]["total_runs"] = 0
        self._write_state(payload)

        result = next_actions(self.paper)

        self.assertEqual(result["hypothesis"], "H1")
        self.assertIn("H1", result["action"])


if __name__ == "__main__":
    unittest.main()
