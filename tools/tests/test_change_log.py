import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from ccfa.change_log import add_entry, check, load_entries


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


class ChangeLogTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.repo = Path(self._temporary.name)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.name", "Change Log Test")
        _git(self.repo, "config", "user.email", "change@test.invalid")

    def test_add_and_check_covers_workflow_file(self):
        path = self.repo / "tools" / "ccfa" / "demo.py"
        path.parent.mkdir(parents=True)
        path.write_text("x = 1\n", encoding="utf-8")

        entry = add_entry(
            self.repo,
            summary="add demo",
            reason="test coverage",
            files=["tools/ccfa/demo.py"],
            tests=["tools.tests.test_demo"],
        )
        problems, advisories = check(
            self.repo,
            changed=["tools/ccfa/demo.py"],
        )

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])
        self.assertTrue(entry["id"].startswith("WC-"))
        self.assertTrue(
            (self.repo / "docs" / "workflow-change-log.md").is_file()
        )

    def test_missing_entry_is_problem(self):
        problems, _advisories = check(
            self.repo,
            changed=["tools/ccfa/unlogged.py"],
        )

        self.assertIn(
            "change-log-missing-entry",
            [problem.code for problem in problems],
        )

    def test_paper_and_library_changes_are_excluded(self):
        add_entry(
            self.repo,
            summary="only workflow",
            reason="scope test",
            files=["tools/ccfa/demo.py"],
            tests=["tools.tests.test_demo"],
        )

        problems, _advisories = check(
            self.repo,
            changed=[
                "papers/demo/manuscript/main.tex",
                "library/refs.bib",
            ],
        )

        self.assertEqual(problems, [])

    def test_append_only_entries_survive_render(self):
        add_entry(
            self.repo,
            summary="first",
            reason="one",
            files=["tools/ccfa/a.py"],
            tests=["tools.tests.test_change_log"],
        )
        add_entry(
            self.repo,
            summary="second",
            reason="two",
            files=["tools/ccfa/b.py"],
            tests=["tools.tests.test_change_log"],
        )

        entries, problems = load_entries(self.repo)

        self.assertEqual(problems, [])
        self.assertEqual([entry["summary"] for entry in entries], ["first", "second"])
        raw_lines = (
            self.repo / "docs" / "workflow-change-log.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(raw_lines), 2)
        self.assertEqual(
            json.loads(raw_lines[0])["summary"],
            "first",
        )

    def test_malformed_entry_is_problem(self):
        path = self.repo / "docs" / "workflow-change-log.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text('{"id": "bad"}\n', encoding="utf-8")

        problems, _advisories = check(self.repo, changed=[])

        self.assertIn(
            "change-log-malformed",
            [problem.code for problem in problems],
        )


if __name__ == "__main__":
    unittest.main()
