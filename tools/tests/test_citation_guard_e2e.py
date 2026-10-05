import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
GUARD = TOOLS_ROOT / "ccfa" / "citation_guard.py"


class TestCitationGuardEndToEnd(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "manuscript").mkdir()
        self.bib = self.root / "references.bib"
        self.ledger = self.root / "citation-ledger.json"

    def _run(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(TOOLS_ROOT)
        return subprocess.run(
            [
                sys.executable,
                str(GUARD),
                "--manuscript",
                str(self.root / "manuscript"),
                "--bib",
                str(self.bib),
                "--ledger",
                str(self.ledger),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def _write_clean_inputs(self):
        self.bib.write_text("@misc{good, doi = {10.1/ok}}\n", encoding="utf-8")
        self.ledger.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": {
                        "good": {
                            "status": "verified",
                            "evidence": {
                                "body_sha256": "sha256:" + "a" * 64,
                                "retrieved_at": "2026-10-04T00:00:00Z",
                                "matched_title": "Sample Title",
                                "source": "crossref",
                            },
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_clean_project_exits_zero_with_parseable_json(self):
        self._write_clean_inputs()
        (self.root / "manuscript" / "main.tex").write_text(r"\cite{good}", encoding="utf-8")

        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["problem_count"], 0)

    def test_unsupported_citation_exits_one_and_names_the_key(self):
        self._write_clean_inputs()
        (self.root / "manuscript" / "main.tex").write_text(
            r"\cite{good} \cite{invented2026}", encoding="utf-8"
        )

        result = self._run()
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["problem_count"], 1)
        self.assertEqual(payload["problems"][0]["code"], "dangling-cite")
        self.assertIn("invented2026", result.stderr)
        self.assertIn("main.tex:1", result.stderr)

    def test_bib_entry_without_a_ledger_record_exits_one(self):
        self.bib.write_text("@misc{good, doi = {10.1/ok}}\n", encoding="utf-8")
        self.ledger.write_text(
            json.dumps({"version": 1, "entries": {}}), encoding="utf-8"
        )
        (self.root / "manuscript" / "main.tex").write_text(r"\cite{good}", encoding="utf-8")

        result = self._run()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["problems"][0]["code"], "unverified-entry")

    def test_missing_ledger_exits_two_not_one(self):
        self._write_clean_inputs()
        self.ledger.unlink()
        (self.root / "manuscript" / "main.tex").write_text(r"\cite{good}", encoding="utf-8")

        result = self._run()
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_verified_without_evidence_exits_one(self):
        self.bib.write_text("@misc{good, doi = {10.1/ok}}\n", encoding="utf-8")
        self.ledger.write_text(
            json.dumps(
                {"version": 1, "entries": {"good": {"status": "verified"}}}
            ),
            encoding="utf-8",
        )
        (self.root / "manuscript" / "main.tex").write_text(
            r"\cite{good}",
            encoding="utf-8",
        )

        result = self._run()

        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn(
            "citation-self-asserted",
            [problem["code"] for problem in payload["problems"]],
        )

    def test_malformed_bib_exits_two_with_clean_stdout(self):
        # C8: a parse failure is a tool error (2). The parser's diagnostic must
        # not reach stdout, so the machine-readable channel stays empty/clean.
        self.bib.write_text("@misc{good, doi = {10.1/ok}\n", encoding="utf-8")
        self.ledger.write_text(
            json.dumps({"version": 1, "entries": {"good": {"status": "verified"}}}),
            encoding="utf-8",
        )
        (self.root / "manuscript" / "main.tex").write_text(r"\cite{good}", encoding="utf-8")

        result = self._run()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
