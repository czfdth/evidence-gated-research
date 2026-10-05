import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
CLI = TOOLS_ROOT / "ccfa" / "provenance.py"


class TestProvenanceEndToEnd(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.data = self.root / "data"
        self.data.mkdir()
        (self.data / "raw.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        self.store = self.data / "provenance.json"

    def _run(self, *extra):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(TOOLS_ROOT)
        # The store and paper root are top-level options: they must come before
        # the subcommand, or argparse rejects the call.
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--store",
                str(self.store),
                "--paper-root",
                str(self.root),
                *extra,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def _add(self):
        result = self._run(
            "add",
            "data/raw.csv",
            "--source",
            "internal export",
            "--classification",
            "real",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_add_then_check_is_clean(self):
        self._add()
        result = self._run("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["problem_count"], 0)

    def test_modified_file_exits_one_with_drift_and_names_path(self):
        self._add()
        (self.data / "raw.csv").write_text("a,b\n9,9\n", encoding="utf-8")

        result = self._run("check")
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["problems"][0]["code"], "provenance-drift")
        self.assertIn(str(self.data / "raw.csv"), result.stderr)

    def test_store_missing_version_exits_two_with_empty_stdout(self):
        self.store.write_text(json.dumps({"files": {}}), encoding="utf-8")

        result = self._run("check")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_export_without_out_prints_markdown_to_stdout(self):
        self._add()

        result = self._run("export")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("| 路径 |", result.stdout)
        self.assertIn("data/raw.csv", result.stdout)

    def test_export_out_refuses_existing_target_without_force(self):
        self._add()
        out = self.data / "provenance.md"
        out.write_text("existing\n", encoding="utf-8")

        result = self._run("export", "--out", str(out))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
