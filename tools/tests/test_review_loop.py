import json
import tempfile
import unittest
from pathlib import Path

from ccfa.review_loop import (
    check_loop,
    drive_loop,
    init_loop,
    next_action,
    record_round,
)


class ReviewLoopTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "reviews").mkdir()

    def _record(
        self,
        *,
        verdict: str = "pass",
        family: str = "cross-family",
    ) -> Path:
        path = self.paper / "reviews" / "cross-review.json"
        path.write_text(
            json.dumps(
                {
                    "status": "complete",
                    "verdict": verdict,
                    "model_verdict": verdict,
                    "family_judgement": family,
                    "model": "gpt-5.6",
                    "provider": "openai-provider",
                    "execution_model": "deepseek-v4-flash",
                    "execution_provider": "deepseek-provider",
                    "input_hashes": {"manuscript/main.tex": "sha256:" + "a" * 64},
                    "prompt_sha256": "sha256:" + "b" * 64,
                    "blocking": [],
                    "summary": "ok",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_init_creates_state_and_memory(self):
        state = init_loop(
            self.paper,
            run_id="run_20261005_abcd1234",
            executor_model="deepseek-v4-flash",
            reviewer_backend="codex",
            reviewer_model="gpt-5.6",
            family_relation="cross-family",
            max_rounds=4,
        )

        self.assertEqual(state["round"], 0)
        self.assertTrue((self.paper / "reviews" / "review-loop-state.json").is_file())
        self.assertTrue((self.paper / "reviews" / "reviewer-memory.md").is_file())

    def test_cross_family_pass_records_acquittal(self):
        init_loop(
            self.paper,
            run_id="run_20261005_abcd1234",
            executor_model="deepseek-v4-flash",
            reviewer_backend="codex",
            reviewer_model="gpt-5.6",
            family_relation="cross-family",
        )
        record = self._record()

        state = record_round(self.paper, cross_review=record)

        self.assertEqual(state["round"], 1)
        self.assertEqual(state["status"], "completed")
        self.assertTrue((self.paper / "reviews" / "ACQUITTAL_LOG.jsonl").is_file())
        self.assertEqual(check_loop(self.paper), ([], []))

    def test_same_family_pass_cannot_complete(self):
        init_loop(
            self.paper,
            run_id="run_20261005_abcd1234",
            executor_model="deepseek-v4-flash",
            reviewer_backend="codex",
            reviewer_model="deepseek-v4-pro",
            family_relation="same-family",
        )
        record = self._record(family="same-family")

        state = record_round(self.paper, cross_review=record)

        self.assertEqual(state["status"], "blocked")
        self.assertTrue(state["requires_external_acquittal"])
        self.assertEqual(next_action(self.paper)["action"], "configure-cross-family-review")

    def test_changed_review_after_record_is_stale(self):
        init_loop(
            self.paper,
            run_id="run_20261005_abcd1234",
            executor_model="deepseek-v4-flash",
            reviewer_backend="codex",
            reviewer_model="gpt-5.6",
            family_relation="cross-family",
        )
        record = self._record()
        record_round(self.paper, cross_review=record)
        record.write_text(
            record.read_text(encoding="utf-8").replace('"verdict": "pass"', '"verdict": "blocking"'),
            encoding="utf-8",
        )

        problems, _advisories = check_loop(self.paper)

        self.assertIn(
            "review-loop-review-stale",
            [problem.code for problem in problems],
        )

    def test_drive_loop_fixes_reviews_and_stops_on_cross_family_pass(self):
        init_loop(
            self.paper,
            run_id="run_20261005_abcd1234",
            executor_model="deepseek-v4-flash",
            reviewer_backend="codex",
            reviewer_model="gpt-5.6",
            family_relation="cross-family",
        )
        calls = []

        def fix_runner(paper_root):
            calls.append("fix")

        def review_runner(paper_root, state):
            calls.append(f"review-{state['round'] + 1}")
            path = self._record(
                verdict="blocking" if state["round"] == 0 else "pass",
                family="cross-family",
            )
            return path

        state = drive_loop(
            self.paper,
            fix_runner=fix_runner,
            review_runner=review_runner,
        )

        self.assertEqual(state["status"], "completed")
        self.assertEqual(calls, ["fix", "review-1", "fix", "review-2"])

    def test_drive_loop_stops_when_external_acquittal_is_required(self):
        init_loop(
            self.paper,
            run_id="run_20261005_abcd1234",
            executor_model="deepseek-v4-flash",
            reviewer_backend="codex",
            reviewer_model="deepseek-v4-pro",
            family_relation="same-family",
        )

        state = drive_loop(
            self.paper,
            fix_runner=lambda paper_root: None,
            review_runner=lambda paper_root, state: self._record(
                verdict="pass",
                family="same-family",
            ),
        )

        self.assertEqual(state["status"], "blocked")
        self.assertTrue(state["requires_external_acquittal"])

    def test_drive_loop_stops_at_max_rounds(self):
        init_loop(
            self.paper,
            run_id="run_20261005_abcd1234",
            executor_model="deepseek-v4-flash",
            reviewer_backend="codex",
            reviewer_model="gpt-5.6",
            family_relation="cross-family",
            max_rounds=1,
        )

        state = drive_loop(
            self.paper,
            fix_runner=lambda paper_root: None,
            review_runner=lambda paper_root, state: self._record(
                verdict="blocking",
                family="cross-family",
            ),
        )

        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["round"], 1)


if __name__ == "__main__":
    unittest.main()
