import tempfile
import unittest
from pathlib import Path

from ccfa.dashboard import collect_reports, render_markdown, summarize


class DashboardTests(unittest.TestCase):
    def _report(
        self,
        root: Path,
        *,
        ready: bool,
        blocking: list[str] | None = None,
    ) -> dict:
        return {
            "paper_root": str(root),
            "profile": "standard",
            "stage": {"current": "internal-review", "gate": "review_cleared"},
            "dimensions": {
                "schema-valid": "pass",
                "evidence-present": "pass",
                "gate-verified": "pass" if ready else "problem",
                "independently-reviewed": "pending-human-review",
                "scientifically-accepted": "not-claimed",
                "collaboration-ready": "pass",
            },
            "git": {
                "present": True,
                "dirty": False,
                "commit": "abc1234",
                "remotes": ["origin"],
                "workflows_present": True,
            },
            "human_review": {
                "status": "pending-human-review",
                "pending": ["proof"],
            },
            "blocking": blocking or [],
            "ready": ready,
        }

    def test_summarize_counts_blocked_and_human_pending(self):
        first = Path("/tmp/paper-a")
        second = Path("/tmp/paper-b")
        reports = [
            self._report(first, ready=False, blocking=["proof missing"]),
            self._report(second, ready=True),
        ]

        summary = summarize(reports)

        self.assertEqual(summary["paper_count"], 2)
        self.assertEqual(summary["ready_count"], 1)
        self.assertEqual(summary["blocked_count"], 1)
        self.assertEqual(summary["human_pending_count"], 2)
        self.assertEqual(summary["papers"][0]["next_action"], "proof missing")

    def test_markdown_names_blockers_and_next_actions(self):
        summary = summarize(
            [self._report(Path("/tmp/paper-a"), ready=False, blocking=["proof missing"])]
        )

        text = render_markdown(summary)

        self.assertIn("paper-a", text)
        self.assertIn("proof missing", text)
        self.assertIn("pending-human-review", text)

    def test_collect_reports_skips_non_paper_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paper = root / "paper-a"
            paper.mkdir()
            (paper / "ccfa.yaml").write_text("version: 0.4.0\n", encoding="utf-8")
            (root / "not-a-paper").mkdir()

            calls = []

            def builder(path, *, profile=None, today=None):
                calls.append(path)
                return self._report(path, ready=True)

            reports = collect_reports(root, builder=builder)

            self.assertEqual(calls, [paper.resolve()])
            self.assertEqual(len(reports), 1)


if __name__ == "__main__":
    unittest.main()
