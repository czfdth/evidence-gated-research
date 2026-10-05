import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
CLI = TOOLS_ROOT / "ccfa" / "trace_claims.py"


class TestTraceClaimsEndToEnd(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.doc = self.root / "main.tex"
        self.doc.write_text("", encoding="utf-8")
        (self.root / "results.json").write_text(
            json.dumps({"summary": {"lcoe": 0.14285714285714285}}), encoding="utf-8"
        )

    def _run(self, *extra):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(TOOLS_ROOT)
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--doc",
                str(self.doc),
                "--base-dir",
                str(self.root),
                *extra,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def test_clean_run_exits_zero_with_parseable_json(self):
        self.doc.write_text(
            "\\dataval{results.json:summary.lcoe}{0.143}", encoding="utf-8"
        )
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["problem_count"], 0)

    def test_mismatch_exits_one_and_names_the_location(self):
        self.doc.write_text(
            "\\dataval{results.json:summary.lcoe}{0.5}", encoding="utf-8"
        )
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["problems"][0]["code"], "dataval-mismatch")
        self.assertIn("main.tex:1", result.stderr)

    def test_missing_document_exits_two_with_empty_stdout(self):
        self.doc.unlink()
        result = self._run()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_path_escape_is_a_problem_not_a_tool_error(self):
        self.doc.write_text("\\dataval{../outside.json:x}{1}", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["problems"][0]["code"], "dataval-error")

    def test_untagged_flag_exits_zero_with_advisory_json(self):
        self.doc.write_text("Accuracy was 92.5 percent.", encoding="utf-8")
        result = self._run("--untagged")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["problem_count"], 0)
        self.assertEqual(payload["advisories"][0]["code"], "untagged-number")


if __name__ == "__main__":
    unittest.main()
