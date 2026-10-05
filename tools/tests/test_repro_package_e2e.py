import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parents[1]
REPRO_PACKAGE = TOOLS_ROOT / "ccfa" / "repro_package.py"


class TestReproPackageEndToEnd(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "report.py").write_text("print('ok')\n", encoding="utf-8")
        self.out = self.root / "bundle"

    def _run(self, *args):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(TOOLS_ROOT)
        return subprocess.run(
            [sys.executable, str(REPRO_PACKAGE), *args],
            capture_output=True,
            encoding="utf-8",
            env=env,
        )

    def _bundle(self):
        result = self._run(
            "--paper-root",
            str(self.root),
            "bundle",
            "--files",
            "report.py",
            "--command",
            "{python} report.py",
            "--out",
            str(self.out),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.out

    def _codes(self, items):
        return [item["code"] for item in items]

    def test_consistent_bundle_verifies_and_reports_scope(self):
        bundle = self._bundle()

        result = self._run("verify", "--bundle", str(bundle))

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["problem_count"], 0)
        self.assertIn("repro-scope", self._codes(payload["advisories"]))
        tails = [
            item for item in payload["advisories"] if item["code"] == "repro-output-tail"
        ]
        self.assertEqual(len(tails), 1)
        self.assertIn("ok", tails[0]["message"])
        self.assertIn("repro-scope", result.stderr)
        self.assertIn("ok", result.stderr)

    def test_bundle_command_without_python_placeholder_exits_two(self):
        result = self._run(
            "--paper-root",
            str(self.root),
            "bundle",
            "--files",
            "report.py",
            "--command",
            "python report.py",
            "--out",
            str(self.out),
        )

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("{python}", result.stderr)

    def test_tampered_member_is_reported_as_incomplete(self):
        bundle = self._bundle()
        (bundle / "files" / "report.py").write_text(
            "print('tampered')\n", encoding="utf-8"
        )

        result = self._run("verify", "--bundle", str(bundle))

        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(self._codes(payload["problems"]), ["repro-bundle-incomplete"])
        self.assertIn("repro-scope", self._codes(payload["advisories"]))

    def test_nonexistent_bundle_exits_two_with_empty_stdout(self):
        missing = self.root / "no-such-bundle"

        result = self._run("verify", "--bundle", str(missing))

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_manifest_version_two_exits_two_with_empty_stdout(self):
        bundle = self._bundle()
        manifest_path = bundle / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = 2
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        result = self._run("verify", "--bundle", str(bundle))

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_manifest_command_without_python_placeholder_exits_two(self):
        bundle = self._bundle()
        manifest_path = bundle / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["command"] = ["python", "report.py"]
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        result = self._run("verify", "--bundle", str(bundle))

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("{python}", result.stderr)


if __name__ == "__main__":
    unittest.main()
