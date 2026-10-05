import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
CLI = TOOLS_ROOT / "ccfa" / "latex_check.py"


class TestLatexCheckEndToEnd(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.manuscript = self.root / "manuscript"
        self.manuscript.mkdir()
        self.tex = self.manuscript / "main.tex"
        self.tex.write_text("\\section{Intro}\n", encoding="utf-8")

    def _run(self, *extra):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(TOOLS_ROOT)
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--manuscript",
                str(self.manuscript),
                *extra,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def test_clean_run_exits_zero_with_parseable_json(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["problem_count"], 0)

    def test_structure_error_exits_one_with_location(self):
        self.tex.write_text("text\n\\section{Broken\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["problems"][0]["code"], "unbalanced-brace")
        self.assertIn("main.tex", result.stderr)

    def test_missing_manuscript_exits_two_with_empty_stdout(self):
        result = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--manuscript",
                str(self.root / "nope"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONPATH": str(TOOLS_ROOT)},
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_unknown_engine_with_compile_exits_two(self):
        result = self._run("--compile", "--engine", "definitely-not-a-real-engine")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_stray_percent_exits_zero_with_advisory_json(self):
        self.tex.write_text("50% faster than baseline\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["problem_count"], 0)
        self.assertEqual(payload["advisories"][0]["code"], "stray-percent")

    def test_missing_bib_file_exits_two_with_empty_stdout(self):
        result = self._run("--bib", str(self.root / "missing.bib"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_compile_without_main_tex_exits_two(self):
        # Needs --compile; a missing main.tex is only an error while compiling.
        self.tex.unlink()
        result = self._run("--compile")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
