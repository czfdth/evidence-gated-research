import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.rigor import check


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


class RigorRubricTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "data").mkdir()
        (self.paper / "experiments" / "log").mkdir(parents=True)
        (self.paper / "manuscript").mkdir()
        (self.paper / "experiments" / "log" / "RUN1.json").write_text(
            json.dumps({"run_id": "RUN1", "status": "completed"}),
            encoding="utf-8",
        )
        (self.paper / "manuscript" / "main.tex").write_text(
            "\\documentclass{article}\n",
            encoding="utf-8",
        )
        _write_yaml(
            self.paper / "data" / "claim-registry.yaml",
            {
                "version": 1,
                "claims": [
                    {"id": "C1", "statement": "claim", "type": "empirical"}
                ],
            },
        )

    def _write_rubric(self, payload: dict) -> None:
        _write_yaml(
            self.paper / "data" / "rigor-rubric.yaml",
            {"version": 1, **payload},
        )

    def _dimension(self, score: int = 3) -> dict:
        return {
            "score": score,
            "rationale": "有具体证据支持",
            "evidence": ["RUN1"],
        }

    def _valid_rubric(self) -> dict:
        return {
            "status": "complete",
            "reviewed_by": {
                "kind": "human",
                "identity": "张三",
                "reviewed_at": "2026-10-05",
            },
            "dimensions": {
                "evidence_relevance": self._dimension(),
                "falsifiability": self._dimension(),
                "scope": self._dimension(),
                "coherence": self._dimension(),
                "exploration_integrity": self._dimension(),
                "methodology": self._dimension(),
            },
        }

    def test_not_started_is_advisory_without_require_complete(self):
        self._write_rubric({"status": "not-started"})

        problems, advisories = check(self.paper)

        self.assertEqual(problems, [])
        self.assertIn(
            "rigor-rubric-not-started",
            [advisory.code for advisory in advisories],
        )

    def test_not_started_with_require_complete_is_problem(self):
        self._write_rubric({"status": "not-started"})

        problems, _advisories = check(self.paper, require_complete=True)

        self.assertIn(
            "rigor-rubric-not-complete",
            [problem.code for problem in problems],
        )

    def test_model_advisory_cannot_acquit(self):
        payload = self._valid_rubric()
        payload["status"] = "model-advisory"
        payload["reviewed_by"]["kind"] = "model"
        self._write_rubric(payload)

        problems, _advisories = check(self.paper, require_complete=True)

        self.assertIn(
            "rigor-model-cannot-acquit",
            [problem.code for problem in problems],
        )

    def test_model_advisory_is_allowed_as_advisory_in_standard_profile(self):
        payload = self._valid_rubric()
        payload["status"] = "model-advisory"
        payload["reviewed_by"]["kind"] = "model"
        self._write_rubric(payload)

        problems, advisories = check(self.paper)

        self.assertEqual(problems, [])
        self.assertIn(
            "rigor-model-advisory",
            [advisory.code for advisory in advisories],
        )

    def test_complete_with_model_reviewer_is_problem(self):
        payload = self._valid_rubric()
        payload["reviewed_by"]["kind"] = "model"
        self._write_rubric(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "rigor-model-cannot-acquit",
            [problem.code for problem in problems],
        )

    def test_complete_with_human_reviewer_passes(self):
        self._write_rubric(self._valid_rubric())

        problems, advisories = check(self.paper, require_complete=True)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_missing_dimension_is_problem(self):
        payload = self._valid_rubric()
        payload["dimensions"].pop("methodology")
        self._write_rubric(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "rigor-rubric-invalid",
            [problem.code for problem in problems],
        )

    def test_invalid_score_is_problem(self):
        payload = self._valid_rubric()
        payload["dimensions"]["scope"]["score"] = 9
        self._write_rubric(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "rigor-rubric-invalid",
            [problem.code for problem in problems],
        )

    def test_placeholder_rationale_is_problem(self):
        payload = self._valid_rubric()
        payload["dimensions"]["coherence"]["rationale"] = "TODO"
        self._write_rubric(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "rigor-rubric-placeholder",
            [problem.code for problem in problems],
        )

    def test_unknown_evidence_is_problem(self):
        payload = self._valid_rubric()
        payload["dimensions"]["evidence_relevance"]["evidence"] = ["missing.pdf"]
        self._write_rubric(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "rigor-rubric-unknown-evidence",
            [problem.code for problem in problems],
        )

    def test_missing_file_with_require_complete_is_problem(self):
        problems, _advisories = check(self.paper, require_complete=True)

        self.assertIn(
            "rigor-rubric-missing",
            [problem.code for problem in problems],
        )


if __name__ == "__main__":
    unittest.main()
