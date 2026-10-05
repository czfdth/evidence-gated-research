import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.long_task import (
    checkpoint_task,
    check_task,
    resume_task,
    run_next_task,
    start_task,
)


class LongTaskTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "artifacts").mkdir()
        (self.root / "artifacts" / "a.txt").write_text("a\n", encoding="utf-8")
        self.spec = self.root / "task.yaml"
        self.spec.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "id": "T1",
                    "title": "Long task",
                    "steps": [
                        {"id": "S1", "description": "Do the first thing."},
                        {
                            "id": "S2",
                            "description": "Run the second thing.",
                            "command": ["{python}", "script.py"],
                            "budget_minutes": 5,
                        },
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def test_start_checkpoint_and_resume(self):
        state = start_task(self.root, self.spec)
        self.assertEqual(state["current_step"]["id"], "S1")

        state = checkpoint_task(
            self.root,
            "T1",
            step_id="S1",
            status="complete",
            evidence=["artifacts/a.txt"],
            next_action="Proceed to S2",
        )

        self.assertEqual(state["current_step"]["id"], "S2")
        self.assertEqual(state["next_action"], "Proceed to S2")
        self.assertEqual(check_task(self.root, "T1"), [])

    def test_resume_replays_from_disk(self):
        start_task(self.root, self.spec)
        checkpoint_task(
            self.root,
            "T1",
            step_id="S1",
            status="complete",
            evidence=["artifacts/a.txt"],
        )

        resumed = resume_task(self.root, "T1")

        self.assertEqual(resumed["event_count"], 2)
        self.assertEqual(resumed["current_step"]["id"], "S2")

    def test_unknown_step_is_rejected(self):
        start_task(self.root, self.spec)

        with self.assertRaisesRegex(ValueError, "step_id"):
            checkpoint_task(
                self.root,
                "T1",
                step_id="S404",
                status="complete",
                evidence=["artifacts/a.txt"],
            )

    def test_tampered_event_breaks_the_chain(self):
        start_task(self.root, self.spec)
        events_path = self.root / "ccfa-workfiles" / "tasks" / "T1" / "events.jsonl"
        event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[0])
        event["title"] = "Tampered"
        events_path.write_text(json.dumps(event) + "\n", encoding="utf-8")

        problems = check_task(self.root, "T1")

        self.assertIn(
            "long-task-event-tampered",
            [problem.code for problem in problems],
        )

    def test_run_next_previews_a_step_command(self):
        start_task(self.root, self.spec)
        checkpoint_task(
            self.root,
            "T1",
            step_id="S1",
            status="complete",
            evidence=["artifacts/a.txt"],
        )

        result = run_next_task(self.root, "T1")

        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(result["step_id"], "S2")
        self.assertIn("script.py", result["command"])


if __name__ == "__main__":
    unittest.main()
