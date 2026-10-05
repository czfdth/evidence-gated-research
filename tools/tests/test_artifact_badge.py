import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.artifact_badge import check


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


class ArtifactBadgeTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "data").mkdir()
        (self.paper / "data" / "evaluation-report.md").write_text(
            "third-party evaluation\n",
            encoding="utf-8",
        )
        (self.paper / "data" / "reuse-report.md").write_text(
            "reuse in a new setting\n",
            encoding="utf-8",
        )

    def _write_badge(self, payload: dict) -> None:
        _write_yaml(
            self.paper / "data" / "artifact-badge.yaml",
            {"version": 1, **payload},
        )

    def _valid_badge(self) -> dict:
        return {
            "status": "verified",
            "doi": "10.5281/zenodo.1234567",
            "archive_url": "https://zenodo.org/records/1234567",
            "license": {"code": "MIT", "data": "CC-BY-4.0"},
            "badges": {
                "available": {
                    "status": "verified",
                    "evidence": ["https://github.com/czfdth/evidence-gated-research"],
                    "rationale": "代码与材料可从私有仓库和 release 获取",
                },
                "evaluated": {
                    "status": "verified",
                    "evidence": ["data/evaluation-report.md"],
                    "independent_reviewer": "Ada Lovelace",
                    "reviewed_at": "2026-10-05",
                    "rationale": "第三方重跑了主结果",
                },
                "reusable": {
                    "status": "verified",
                    "evidence": ["data/reuse-report.md"],
                    "reuse_context": "在另一个 RAG 数据集上复用检测流程",
                    "rationale": "第三方在独立场景复用成功",
                },
            },
        }

    def test_not_started_is_advisory_without_require_verified(self):
        self._write_badge({"status": "not-started"})

        problems, advisories = check(self.paper)

        self.assertEqual(problems, [])
        self.assertIn(
            "artifact-badge-not-started",
            [advisory.code for advisory in advisories],
        )

    def test_not_started_with_require_verified_is_problem(self):
        self._write_badge({"status": "not-started"})

        problems, _advisories = check(self.paper, require_verified=True)

        self.assertIn(
            "artifact-badge-not-verified",
            [problem.code for problem in problems],
        )

    def test_valid_verified_badge_passes(self):
        self._write_badge(self._valid_badge())

        problems, advisories = check(self.paper, require_verified=True)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_model_reviewer_cannot_claim_evaluated(self):
        payload = self._valid_badge()
        payload["badges"]["evaluated"]["independent_reviewer"] = "GPT-5.6"
        self._write_badge(payload)

        problems, _advisories = check(self.paper, require_verified=True)

        self.assertIn(
            "artifact-badge-reviewer-not-human",
            [problem.code for problem in problems],
        )

    def test_reusable_requires_reuse_context(self):
        payload = self._valid_badge()
        payload["badges"]["reusable"].pop("reuse_context")
        self._write_badge(payload)

        problems, _advisories = check(self.paper, require_verified=True)

        self.assertIn(
            "artifact-badge-reusable-incomplete",
            [problem.code for problem in problems],
        )

    def test_bad_doi_is_invalid(self):
        payload = self._valid_badge()
        payload["doi"] = "not-a-doi"
        self._write_badge(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "artifact-badge-invalid",
            [problem.code for problem in problems],
        )


if __name__ == "__main__":
    unittest.main()
