import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from ccfa.change_log import add_entry
from ccfa.worktree_audit import audit, main


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class WorktreeAuditTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.repo = Path(self._temporary.name)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.name", "Audit Test")
        _git(self.repo, "config", "user.email", "audit@test.invalid")

    def test_audit_separates_covered_and_uncovered(self):
        covered = self.repo / "tools" / "ccfa" / "a.py"
        uncovered = self.repo / "tools" / "ccfa" / "b.py"
        covered.parent.mkdir(parents=True)
        covered.write_text("a = 1\n", encoding="utf-8")
        uncovered.write_text("b = 1\n", encoding="utf-8")
        add_entry(
            self.repo,
            summary="cover a",
            reason="test",
            files=["tools/ccfa/a.py"],
            tests=["tools.tests.test_worktree_audit"],
        )

        report = audit(self.repo)

        self.assertEqual(report["covered"], ["tools/ccfa/a.py"])
        self.assertEqual(report["uncovered"], ["tools/ccfa/b.py"])
        self.assertFalse(report["strict_pass"])

    def test_strict_exits_one_when_uncovered(self):
        uncovered = self.repo / "tools" / "ccfa" / "b.py"
        uncovered.parent.mkdir(parents=True)
        uncovered.write_text("b = 1\n", encoding="utf-8")

        with contextlib.redirect_stdout(io.StringIO()):
            code = main(
                ["worktree-audit", "--repo-root", str(self.repo), "--strict"]
            )

        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
