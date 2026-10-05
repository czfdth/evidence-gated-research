import json
import tempfile
import unittest
from pathlib import Path

from ccfa.run_ledger import check_ledger, sync_ledger


def _write_record(path: Path, run_id: str, *, status: str = "completed") -> None:
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": status,
                "command": ["python", "experiment.py"],
                "exit_code": 0 if status == "completed" else 1,
            }
        ),
        encoding="utf-8",
    )


class RunLedgerTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        self.log_dir = self.paper / "experiments" / "log"
        self.log_dir.mkdir(parents=True)
        _write_record(self.log_dir / "RUN1.json", "RUN1")
        _write_record(self.log_dir / "RUN2.json", "RUN2", status="failed")

    def test_sync_builds_chain_and_check_passes(self):
        result = sync_ledger(self.paper)

        problems, advisories = check_ledger(self.paper)

        self.assertEqual(result["appended"], 2)
        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_sync_is_idempotent(self):
        sync_ledger(self.paper)
        second = sync_ledger(self.paper)

        self.assertEqual(second["appended"], 0)

    def test_changed_record_appends_update_and_latest_wins(self):
        sync_ledger(self.paper)
        _write_record(self.log_dir / "RUN1.json", "RUN1", status="failed")

        stale, _advisories = check_ledger(self.paper)
        self.assertIn(
            "run-ledger-stale-record",
            [problem.code for problem in stale],
        )

        result = sync_ledger(self.paper)
        problems, _advisories = check_ledger(self.paper)

        self.assertEqual(result["appended"], 1)
        self.assertEqual(problems, [])

    def test_tampered_chain_is_detected(self):
        sync_ledger(self.paper)
        ledger = self.log_dir / "run-ledger.jsonl"
        lines = ledger.read_text(encoding="utf-8").splitlines()
        lines[0] = lines[0].replace('"kind": "tool_receipt"', '"kind": "tampered"')
        ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")

        problems, _advisories = check_ledger(self.paper)

        self.assertIn(
            "run-ledger-chain-mismatch",
            [problem.code for problem in problems],
        )

    def test_missing_record_is_detected(self):
        sync_ledger(self.paper)
        (self.log_dir / "RUN2.json").unlink()

        problems, _advisories = check_ledger(self.paper)

        self.assertIn(
            "run-ledger-orphan-record",
            [problem.code for problem in problems],
        )


if __name__ == "__main__":
    unittest.main()
