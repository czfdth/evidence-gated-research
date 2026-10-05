import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.post_submission import check


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


class PostSubmissionTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "data").mkdir()
        (self.paper / "reviews").mkdir()
        (self.paper / "experiments" / "log").mkdir(parents=True)
        (self.paper / "figures").mkdir()
        (self.paper / "manuscript").mkdir()
        (self.paper / "experiments" / "log" / "RUN1.json").write_text(
            json.dumps({"run_id": "RUN1", "status": "completed"}),
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
        _write_yaml(
            self.paper / "figures" / "manifest.yaml",
            {
                "version": 1,
                "figures": [{"id": "F1", "path": "figures/plot.pdf"}],
            },
        )
        (self.paper / "reviews" / "revision-ledger.md").write_text(
            "# Revision ledger\n",
            encoding="utf-8",
        )

    def _write_tail(self, payload: dict) -> None:
        _write_yaml(
            self.paper / "data" / "post-submission.yaml",
            {"version": 1, **payload},
        )

    def _valid_tail(self) -> dict:
        return {
            "rebuttal": {
                "status": "complete",
                "response_ledger": "reviews/revision-ledger.md",
                "new_evidence_run_ids": ["RUN1"],
                "commitments": ["补充消融实验"],
            },
            "resubmit": {
                "status": "complete",
                "from_venue": "NeurIPS",
                "to_venue": "ICLR",
                "venue_diff": [
                    {
                        "id": "V1",
                        "requirement": "页数限制不同",
                        "current": "NeurIPS 9 页",
                        "action": "压缩到 8 页",
                        "sections": ["manuscript/sections/05-results.tex"],
                        "evidence": ["RUN1"],
                        "status": "complete",
                    }
                ],
                "sections_to_rewrite": ["manuscript/sections/05-results.tex"],
            },
            "talk": {
                "status": "complete",
                "slide_outline": [
                    {
                        "id": "S1",
                        "title": "核心结果",
                        "claim_ids": ["C1"],
                        "figure_ids": ["F1"],
                        "talking_points": ["解释主要发现"],
                    }
                ],
            },
        }

    def test_not_applicable_requires_reason(self):
        self._write_tail(
            {
                "rebuttal": {"status": "not-applicable", "reason": ""},
                "resubmit": {"status": "not-applicable", "reason": "已录用"},
                "talk": {"status": "not-applicable", "reason": "不做报告"},
            }
        )

        problems, _advisories = check(self.paper)

        self.assertIn(
            "post-submission-na-reason-missing",
            [problem.code for problem in problems],
        )

    def test_empty_tail_is_advisory(self):
        self._write_tail(
            {
                "rebuttal": {"status": "not-started"},
                "resubmit": {"status": "not-started"},
                "talk": {"status": "not-started"},
            }
        )

        problems, advisories = check(self.paper)

        self.assertEqual(problems, [])
        self.assertIn(
            "post-submission-empty",
            [advisory.code for advisory in advisories],
        )

    def test_valid_tail_passes(self):
        self._write_tail(self._valid_tail())

        problems, advisories = check(self.paper)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_unknown_run_id_is_a_problem(self):
        payload = self._valid_tail()
        payload["rebuttal"]["new_evidence_run_ids"] = ["RUN404"]
        self._write_tail(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "post-submission-unknown-run",
            [problem.code for problem in problems],
        )

    def test_unknown_claim_and_figure_ids_are_problems(self):
        payload = self._valid_tail()
        payload["talk"]["slide_outline"][0]["claim_ids"] = ["C404"]
        payload["talk"]["slide_outline"][0]["figure_ids"] = ["F404"]
        self._write_tail(payload)

        problems, _advisories = check(self.paper)

        codes = [problem.code for problem in problems]
        self.assertIn("post-submission-unknown-claim", codes)
        self.assertIn("post-submission-unknown-figure", codes)

    def test_complete_resubmit_needs_venue_diff_and_sections(self):
        payload = self._valid_tail()
        payload["resubmit"]["venue_diff"] = []
        payload["resubmit"]["sections_to_rewrite"] = []
        self._write_tail(payload)

        problems, _advisories = check(self.paper)

        codes = [problem.code for problem in problems]
        self.assertIn("post-submission-resubmit-incomplete", codes)

    def test_placeholder_is_a_problem(self):
        payload = self._valid_tail()
        payload["talk"]["slide_outline"][0]["title"] = "TODO"
        self._write_tail(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "post-submission-placeholder",
            [problem.code for problem in problems],
        )


if __name__ == "__main__":
    unittest.main()
