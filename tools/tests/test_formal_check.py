import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.formal_check import run_checks


class FormalCheckTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "data").mkdir()
        self.script = self.root / "check.py"

    def _ledger(self, **overrides):
        check = {
            "id": "z3-test",
            "theorem_id": "prop:test",
            "engine": "z3",
            "command": ["{python}", "check.py"],
            "expected_status": "proved",
        }
        check.update(overrides)
        payload = {"version": 1, "checks": [check]}
        (self.root / "data" / "formal-checks.yaml").write_text(
            yaml.safe_dump(payload, sort_keys=False),
            encoding="utf-8",
        )

    def _script(self, payload):
        self.script.write_text(
            "import json\n"
            f"print(json.dumps({payload!r}))\n",
            encoding="utf-8",
        )

    def test_proved_check_passes(self):
        self._ledger()
        self._script(
            {
                "id": "z3-test",
                "theorem_id": "prop:test",
                "engine": "z3",
                "status": "proved",
                "summary": "unsat",
            }
        )

        problems, advisories, results = run_checks(self.root)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])
        self.assertEqual(results[0]["status"], "proved")

    def test_status_mismatch_is_a_problem(self):
        self._ledger()
        self._script(
            {
                "id": "z3-test",
                "theorem_id": "prop:test",
                "engine": "z3",
                "status": "unknown",
            }
        )

        problems, _, _ = run_checks(self.root)

        self.assertEqual([item.code for item in problems], ["formal-check-not-proved"])

    def test_malformed_output_is_a_problem(self):
        self._ledger()
        self.script.write_text("print('not json')\n", encoding="utf-8")

        problems, _, _ = run_checks(self.root)

        self.assertEqual(
            [item.code for item in problems],
            ["formal-check-output-invalid"],
        )

    def test_nonzero_exit_is_a_problem(self):
        self._ledger()
        self.script.write_text("raise SystemExit(3)\n", encoding="utf-8")

        problems, _, _ = run_checks(self.root)

        self.assertEqual(
            [item.code for item in problems],
            ["formal-check-execution-failed"],
        )


if __name__ == "__main__":
    unittest.main()
