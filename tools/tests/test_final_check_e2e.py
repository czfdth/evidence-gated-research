import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pymupdf

TOOLS_ROOT = Path(__file__).resolve().parents[1]
CLI = TOOLS_ROOT / "ccfa" / "final_check.py"


class TestFinalCheckEndToEnd(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.manuscript = self.root / "manuscript"
        self.manuscript.mkdir()
        (self.root / "figures").mkdir()
        self.tex = self.manuscript / "main.tex"
        self.tex.write_text("\\section{Intro}\n", encoding="utf-8")
        self.pdf = self.manuscript / "main.pdf"

    def make_pdf(self, *lines):
        # One short line per insert_text call: a single long string can run past
        # the page and be clipped, which would make the fixture flaky.
        document = pymupdf.open()
        page = document.new_page()
        for index, line in enumerate(lines):
            page.insert_text((72, 72 + 14 * index), line)
        document.save(str(self.pdf))
        document.close()

    def _run(self, *extra):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(TOOLS_ROOT)
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--manuscript",
                str(self.manuscript),
                "--pdf",
                str(self.pdf),
                *extra,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def test_clean_paper_exits_zero_with_parseable_json(self):
        self.make_pdf("Limitations.", "Data Availability.")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["problem_count"], 0)

    def test_unresolved_marker_exits_one(self):
        self.make_pdf("Limitations.", "Data Availability.", "Figure ?? here")
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["problems"][0]["code"], "unresolved-marker")
        self.assertIn("main.pdf", result.stderr)

    def test_missing_pdf_exits_two_with_empty_stdout(self):
        result = self._run()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_advisory_only_run_exits_zero(self):
        self.make_pdf("Limitations.", "Data Availability.")
        self.tex.write_text("Accuracy was 92.5 percent.\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["problem_count"], 0)
        self.assertTrue(payload["advisories"])


if __name__ == "__main__":
    unittest.main()
