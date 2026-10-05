import contextlib
import io
import unittest
from pathlib import Path

from ccfa import dispatch


ROOT = Path(__file__).resolve().parents[2]


class PackagingTests(unittest.TestCase):
    def test_root_pyproject_exposes_ccfa_console_script(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('ccfa = "ccfa.dispatch:run"', text)
        self.assertIn('package-dir = {"" = "tools"}', text)
        self.assertIn("requires-python", text)

    def test_dispatch_lists_modules(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = dispatch.run(["list"])

        self.assertEqual(code, 0)
        self.assertIn("doctor", stdout.getvalue())

    def test_dispatch_rejects_unknown_module(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = dispatch.run(["not-a-module"])

        self.assertEqual(code, 2)
        self.assertIn("unknown ccfa module", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
