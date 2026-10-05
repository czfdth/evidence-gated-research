import contextlib
import io
import re
import unittest
from pathlib import Path

from ccfa import dispatch


ROOT = Path(__file__).resolve().parents[2]

# CI installs the lock file, not requirements.txt. A direct dependency that is
# missing from the lock is therefore absent on a clean runner while it is
# present on a developer machine, which is how the doctor import gate failed.
REQUIREMENT_PAIRS = (
    ("tools/requirements.txt", "tools/requirements.lock"),
    ("app/requirements.txt", "app/requirements.lock"),
)
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s;\\]+)")


def _pins(relative: str) -> dict[str, str]:
    pinned: dict[str, str] = {}
    for line in (ROOT / relative).read_text(encoding="utf-8").splitlines():
        match = _PIN.match(line.split("#", 1)[0].strip())
        if match:
            pinned[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pinned


class PackagingTests(unittest.TestCase):
    def test_root_pyproject_exposes_ccfa_console_script(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn('ccfa = "ccfa.dispatch:run"', text)
        self.assertIn('package-dir = {"" = "tools"}', text)
        self.assertIn("requires-python", text)
        # install-toolchain is dispatched to install.fetch_toolchain, so the
        # package must ship that package too or the installed CLI loses a tool.
        self.assertIn('"install*"', text)

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
        self.assertIn("unknown ccfa command", stderr.getvalue())

    def test_locks_cover_every_direct_dependency(self):
        for direct, lock in REQUIREMENT_PAIRS:
            with self.subTest(lock=lock):
                locked = _pins(lock)
                for name, version in _pins(direct).items():
                    self.assertIn(
                        name,
                        locked,
                        f"{lock} 缺少直接依赖 {name}；"
                        "CI 只装 lock，干净机器上会缺这个包",
                    )
                    self.assertEqual(
                        locked[name],
                        version,
                        f"{lock} 里 {name} 的版本与 {direct} 不一致",
                    )


if __name__ == "__main__":
    unittest.main()
