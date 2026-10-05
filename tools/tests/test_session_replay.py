import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.session_replay import build_replay, check_replay, render_html


class SessionReplayTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "reviews").mkdir()
        (self.paper / "experiments" / "log").mkdir(parents=True)
        (self.paper / "ccfa-workfiles" / "artifact-store").mkdir(parents=True)
        (self.paper / "ccfa-workfiles" / "passport").mkdir(parents=True)
        (self.paper / "experiments" / "log" / "run-ledger.jsonl").write_text(
            json.dumps({"run_id": "RUN1", "status": "completed"}) + "\n",
            encoding="utf-8",
        )
        (self.paper / "ccfa-workfiles" / "artifact-store" / "manifest.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "artifacts": {
                        "figures/plot.pdf": [
                            {
                                "artifact_id": "figures/plot.pdf",
                                "version": 1,
                                "sha256": "a" * 64,
                                "run_id": "RUN1",
                                "role": "figure",
                            }
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        (self.paper / "ccfa-workfiles" / "passport" / "run-ledger.yaml").write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "entries": [
                        {
                            "seq": 1,
                            "kind": "initial_instructions",
                            "at": "2026-10-05T00:00:00Z",
                            "data": {"user_words": "write paper"},
                            "prev_hash": None,
                            "hash": "x",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (self.paper / "reviews" / "review-loop-state.json").write_text(
            json.dumps(
                {
                    "run_id": "run_1",
                    "round": 1,
                    "status": "completed",
                    "last_verdict": "pass",
                }
            ),
            encoding="utf-8",
        )

    def test_build_replay_links_runs_artifacts_and_reviews(self):
        replay = build_replay(self.paper)

        self.assertEqual(replay["run_count"], 1)
        self.assertEqual(replay["artifact_count"], 1)
        self.assertIn("RUN1", replay["run_ids"])
        self.assertEqual(check_replay(self.paper), ([], []))

    def test_dangling_artifact_run_is_problem(self):
        manifest = self.paper / "ccfa-workfiles" / "artifact-store" / "manifest.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["artifacts"]["figures/plot.pdf"][0]["run_id"] = "RUN404"
        manifest.write_text(json.dumps(payload), encoding="utf-8")

        problems, _advisories = check_replay(self.paper)

        self.assertIn(
            "session-replay-dangling-run",
            [problem.code for problem in problems],
        )

    def test_render_html_contains_timeline_entries(self):
        replay = build_replay(self.paper)

        html = render_html(replay)

        self.assertIn("RUN1", html)
        self.assertIn("figures/plot.pdf", html)
        self.assertIn("review-loop", html)


if __name__ == "__main__":
    unittest.main()
