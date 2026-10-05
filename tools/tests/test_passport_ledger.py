import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.passport_ledger import append_event, check_ledger, render_ledger


class PassportLedgerTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)

    def test_append_initial_and_checkpoint_and_check(self):
        append_event(
            self.paper,
            kind="initial_instructions",
            data={"user_words": "Write the paper"},
        )
        append_event(
            self.paper,
            kind="checkpoint_closed",
            data={
                "checkpoint_id": "CP1",
                "answer": "yes",
                "user_words": "yes, proceed",
            },
        )

        problems, advisories = check_ledger(self.paper)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_invalid_kind_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "kind"):
            append_event(self.paper, kind="mystery", data={})

    def test_tamper_is_detected(self):
        append_event(
            self.paper,
            kind="initial_instructions",
            data={"user_words": "Write the paper"},
        )
        path = self.paper / "ccfa-workfiles" / "passport" / "run-ledger.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        payload["entries"][0]["data"]["user_words"] = "tampered"
        path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

        problems, _advisories = check_ledger(self.paper)

        self.assertIn(
            "passport-chain-mismatch",
            [problem.code for problem in problems],
        )

    def test_render_names_events(self):
        append_event(
            self.paper,
            kind="tool_receipt",
            data={"step": "test", "command": "pytest", "status": "passed"},
        )

        text = render_ledger(self.paper)

        self.assertIn("tool_receipt", text)
        self.assertIn("pytest", text)


if __name__ == "__main__":
    unittest.main()
