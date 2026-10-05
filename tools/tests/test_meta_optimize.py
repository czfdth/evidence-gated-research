import json
import tempfile
import unittest
from pathlib import Path

from ccfa.meta_optimize import analyze, render_markdown


def _write_store(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "entries": entries}, ensure_ascii=False),
        encoding="utf-8",
    )


class MetaOptimizeTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def test_repeated_friction_becomes_a_candidate(self):
        first = self.root / "one.json"
        second = self.root / "two.json"
        entry = {
            "id": 1,
            "created_at": "2026-10-05T00:00:00Z",
            "stage": "internal-review",
            "component": "cross_review",
            "category": "tool-bug",
            "severity": "high",
            "description": "同族 pass 被误判为 gate pass",
            "workaround": "手工检查 family_judgement",
        }
        _write_store(first, [entry])
        _write_store(second, [{**entry, "id": 2, "severity": "medium"}])

        report = analyze([(first, "paper-a"), (second, "paper-b")], min_count=2)

        self.assertEqual(report["candidate_count"], 1)
        candidate = report["candidates"][0]
        self.assertEqual(candidate["component"], "cross_review")
        self.assertEqual(candidate["count"], 2)
        self.assertEqual(candidate["severity"], "high")
        self.assertEqual(candidate["sources"], ["paper-a", "paper-b"])
        self.assertIn("回归测试", candidate["proposal"])
        self.assertEqual(candidate["status"], "proposed")

    def test_single_occurrence_is_retained_but_not_a_candidate(self):
        store = self.root / "one.json"
        _write_store(
            store,
            [
                {
                    "id": 1,
                    "created_at": "2026-10-05T00:00:00Z",
                    "stage": "writing",
                    "component": "latex_check",
                    "category": "environment",
                    "severity": "low",
                    "description": "缺少某个包",
                    "workaround": "手工安装",
                }
            ],
        )

        report = analyze([(store, "paper-a")], min_count=2)

        self.assertEqual(report["candidate_count"], 0)
        self.assertEqual(report["occurrence_count"], 1)

    def test_invalid_store_is_a_tool_error(self):
        invalid = self.root / "invalid.json"
        invalid.write_text('{"version": 2, "entries": []}', encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "version"):
            analyze([(invalid, "bad")])

    def test_readiness_gate_problem_codes_become_candidates(self):
        readiness = self.root / "readiness.json"
        readiness.write_text(
            json.dumps(
                {
                    "gate_results": [
                        {
                            "name": "rigor-rubric",
                            "problems": [
                                {"code": "rigor-model-cannot-acquit"}
                            ],
                        },
                        {
                            "name": "proof-orchestrator",
                            "problems": [
                                {"code": "proof-campaign-not-complete"}
                            ],
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        report = analyze(
            [],
            readiness_inputs=[(readiness, "paper-a")],
            min_count=1,
        )

        keys = {candidate["key"] for candidate in report["candidates"]}
        self.assertIn("rigor-rubric:rigor-model-cannot-acquit", keys)
        self.assertIn(
            "proof-orchestrator:proof-campaign-not-complete",
            keys,
        )

    def test_markdown_names_candidates_and_proposals(self):
        report = {
            "candidate_count": 1,
            "candidates": [
                {
                    "kind": "friction",
                    "key": "tool-bug:cross_review",
                    "component": "cross_review",
                    "category": "tool-bug",
                    "count": 2,
                    "severity": "high",
                    "sources": ["paper-a", "paper-b"],
                    "proposal": "补充回归测试",
                    "status": "proposed",
                }
            ],
        }

        text = render_markdown(report)

        self.assertIn("cross_review", text)
        self.assertIn("补充回归测试", text)


if __name__ == "__main__":
    unittest.main()
