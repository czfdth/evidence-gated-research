"""Tests for the thin git-backed paper version wrapper.

Eleven cases inject a fake ``runner`` so no real git is touched; the twelfth
drives real git in a temporary repository to prove the default runner works.
"""

import io
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from ccfa.research_version import (
    diff_versions,
    git_output,
    list_versions,
    main,
    next_version,
    snapshot,
    working_tree_dirty,
)


class FakeGit:
    """Dispatch git argv to canned output, recording every call."""

    def __init__(
        self,
        tags=(),
        dirty=False,
        commit="abc123",
        diff="fake diff",
        toplevel=None,
    ):
        self.tags = list(tags)
        self.dirty = dirty
        self.commit = commit
        self.diff = diff
        self.toplevel = toplevel
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], repo: Path) -> tuple[int, str]:
        self.calls.append(list(args))
        if args == ["rev-parse", "--show-toplevel"]:
            if self.toplevel is None:
                return 0, str(repo)
            return 0, self.toplevel
        if args[:2] == ["tag", "-l"]:
            return 0, "\n".join(self.tags)
        if args == ["status", "--porcelain"]:
            return 0, " M main.tex" if self.dirty else ""
        if args == ["rev-parse", "HEAD"]:
            return 0, self.commit
        if args[0] == "diff":
            return 0, self.diff
        if args[0] == "tag":  # tag -a ...
            return 0, ""
        raise AssertionError(f"unexpected git argv: {args}")

    def tag_calls(self) -> list[list[str]]:
        return [call for call in self.calls if call[:1] == ["tag"]]


class TestListVersions(unittest.TestCase):
    def test_versions_sort_numerically_not_lexicographically(self):
        runner = FakeGit(tags=["paper-v10", "paper-v2"])
        repo = Path("repo")

        versions = list_versions(repo, runner=runner)

        self.assertEqual(versions, ["paper-v2", "paper-v10"])


class TestNextVersion(unittest.TestCase):
    def test_empty_tag_set_starts_at_one(self):
        runner = FakeGit(tags=[])
        self.assertEqual(next_version(Path("repo"), runner=runner), "paper-v1")

    def test_existing_three_advances_to_four(self):
        runner = FakeGit(tags=["paper-v3"])
        self.assertEqual(next_version(Path("repo"), runner=runner), "paper-v4")

    def test_malformed_tag_is_named_in_the_error(self):
        runner = FakeGit(tags=["paper-vX"])

        with self.assertRaises(ValueError) as caught:
            next_version(Path("repo"), runner=runner)

        self.assertIn("paper-vX", str(caught.exception))


class TestWorkingTreeDirty(unittest.TestCase):
    def test_clean_and_dirty_porcelain_output(self):
        clean = FakeGit(dirty=False)
        dirty = FakeGit(dirty=True)
        self.assertFalse(working_tree_dirty(Path("repo"), runner=clean))
        self.assertTrue(working_tree_dirty(Path("repo"), runner=dirty))


class TestSnapshot(unittest.TestCase):
    def test_clean_tree_tags_with_dirty_false_and_returns_pair(self):
        runner = FakeGit(tags=[], dirty=False, commit="cafe01")

        tag, commit = snapshot(Path("repo"), runner=runner)

        self.assertEqual((tag, commit), ("paper-v1", "cafe01"))
        self.assertEqual(self.tag_message(runner), "dirty=false")

    def test_dirty_tree_is_refused_without_touching_git_tag(self):
        runner = FakeGit(tags=[], dirty=True)

        with self.assertRaises(ValueError):
            snapshot(Path("repo"), runner=runner)

        self.assertEqual(runner.tag_calls(), [])

    def test_allow_dirty_records_dirty_true(self):
        runner = FakeGit(tags=[], dirty=True, commit="abc123")

        tag, _ = snapshot(Path("repo"), allow_dirty=True, runner=runner)

        self.assertEqual(tag, "paper-v1")
        message = self.tag_message(runner)
        self.assertIn("dirty=true", message)
        self.assertIn(
            "note=uncommitted changes are not captured; "
            "tag points at HEAD commit abc123",
            message,
        )

    def test_clean_tree_message_carries_no_uncaptured_content_note(self):
        runner = FakeGit(tags=[], dirty=False, commit="cafe01")

        snapshot(Path("repo"), runner=runner)

        self.assertNotIn("uncommitted changes are not captured", self.tag_message(runner))

    def test_label_goes_into_message_without_changing_the_name(self):
        runner = FakeGit(tags=["paper-v1"], dirty=False)

        tag, _ = snapshot(Path("repo"), label="camera-ready draft", runner=runner)

        self.assertEqual(tag, "paper-v2")
        self.assertIn("label=camera-ready draft", self.tag_message(runner))

    def tag_message(self, runner: FakeGit) -> str:
        for call in runner.calls:
            if call[:1] == ["tag"] and "-a" in call:
                return call[call.index("-m") + 1]
        self.fail("snapshot did not create an annotated tag")


class TestDiffVersions(unittest.TestCase):
    def test_paths_are_placed_after_double_dash(self):
        runner = FakeGit(diff="@@ -1 +1 @@\n-old\n+new\n")

        text = diff_versions(
            Path("repo"), "paper-v1", "paper-v2", ["main.tex", "refs.bib"], runner=runner
        )

        self.assertEqual(text, "@@ -1 +1 @@\n-old\n+new\n")
        self.assertEqual(
            runner.calls[-1],
            ["diff", "paper-v1", "paper-v2", "--", "main.tex", "refs.bib"],
        )

    def test_unknown_revision_exits_two_with_a_tool_message(self):
        def failing(args: list[str], repo: Path) -> tuple[int, str]:
            return 128, "fatal: bad revision 'paper-v9'"

        err = io.StringIO()
        with redirect_stderr(err):
            code = main(
                ["research_version.py", "--repo", "repo", "diff", "paper-v9", "paper-v1"],
                runner=failing,
            )

        self.assertEqual(code, 2)
        self.assertIn("paper-v9", err.getvalue())


class TestGitOutput(unittest.TestCase):
    def test_nonzero_exit_is_folded_into_value_error(self):
        def failing(args: list[str], repo: Path) -> tuple[int, str]:
            return 128, "fatal: not a git repository"

        with self.assertRaises(ValueError):
            git_output(["status", "--porcelain"], Path("repo"), runner=failing)

    def test_missing_git_oserror_is_folded_into_value_error(self):
        def missing_git(args: list[str], repo: Path) -> tuple[int, str]:
            raise OSError("git not found")

        with self.assertRaises(ValueError):
            git_output(["status", "--porcelain"], Path("repo"), runner=missing_git)


class TestOwnRepositoryGuard(unittest.TestCase):
    """Every version operation must resolve to the paper's own repository."""

    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name) / "papers" / "demo"
        self.paper.mkdir(parents=True)
        self.parent = self.paper.parent

    def test_list_refuses_a_parent_repository(self):
        runner = FakeGit(toplevel=str(self.parent))

        with self.assertRaises(ValueError) as caught:
            list_versions(self.paper, runner=runner)

        message = str(caught.exception)
        self.assertIn("论文目录不是独立 git 仓库", message)
        self.assertIn("拒绝在父仓库上打 tag", message)

    def test_snapshot_refuses_a_parent_repository_without_tagging(self):
        runner = FakeGit(toplevel=str(self.parent))

        with self.assertRaises(ValueError):
            snapshot(self.paper, runner=runner)

        self.assertEqual(runner.tag_calls(), [])

    def test_diff_refuses_a_parent_repository(self):
        runner = FakeGit(toplevel=str(self.parent))

        with self.assertRaises(ValueError):
            diff_versions(self.paper, "paper-v1", "paper-v2", runner=runner)

    def test_main_parent_repository_exits_two_with_tool_message(self):
        runner = FakeGit(toplevel=str(self.parent))
        err = io.StringIO()

        with redirect_stderr(err):
            code = main(
                [
                    "research_version.py",
                    "--repo",
                    str(self.paper),
                    "list",
                ],
                runner=runner,
            )

        self.assertEqual(code, 2)
        self.assertIn("论文目录不是独立 git 仓库", err.getvalue())

    def test_help_exits_zero_without_touching_git(self):
        runner = FakeGit()
        out = io.StringIO()

        with redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                main(["research_version.py", "--help"], runner=runner)

        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(runner.calls, [])

    def test_real_nested_directory_inside_parent_repo_is_refused(self):
        parent = Path(self._temporary.name) / "template-repo"
        nested = parent / "papers" / "demo"
        nested.mkdir(parents=True)
        _run_git(parent, "init", "-q")
        err = io.StringIO()

        with redirect_stderr(err):
            code = main(
                [
                    "research_version.py",
                    "--repo",
                    str(nested),
                    "list",
                ]
            )

        self.assertEqual(code, 2)
        self.assertIn("论文目录不是独立 git 仓库", err.getvalue())


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    )


def _tag_message(repo: Path, tag: str) -> str:
    return subprocess.run(
        ["git", "cat-file", "-p", tag],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout


class TestRealGitIntegration(unittest.TestCase):
    """The only case that proves the default runner really works."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        _run_git(self.repo, "init", "-q")
        # Annotated tags need a tagger identity; set it locally so the test
        # never depends on the machine's global git config.
        _run_git(self.repo, "config", "user.name", "Version Test")
        _run_git(self.repo, "config", "user.email", "version@test.invalid")
        (self.repo / "main.tex").write_text("first draft\n", encoding="utf-8")
        _run_git(self.repo, "add", "main.tex")
        _run_git(self.repo, "commit", "-q", "-m", "first draft")

    def test_snapshot_diff_end_to_end(self):
        tag, commit = snapshot(self.repo)
        self.assertEqual(tag, "paper-v1")
        self.assertTrue(commit)
        self.assertIn("dirty=false", _tag_message(self.repo, tag))
        self.assertEqual(commit, git_output(["rev-parse", "HEAD"], self.repo).strip())

        (self.repo / "main.tex").write_text("second draft\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            snapshot(self.repo)

        tag2, _ = snapshot(self.repo, allow_dirty=True)
        self.assertEqual(tag2, "paper-v2")
        message2 = _tag_message(self.repo, tag2)
        self.assertIn("dirty=true", message2)
        self.assertIn(
            "note=uncommitted changes are not captured; "
            f"tag points at HEAD commit {git_output(['rev-parse', 'HEAD'], self.repo).strip()}",
            message2,
        )

        # Once the edit is committed it gets its own commit and version, so a
        # diff between paper-v1 and the clean paper-v3 has real content.
        _run_git(self.repo, "add", "main.tex")
        _run_git(self.repo, "commit", "-q", "-m", "second draft")
        tag3, _ = snapshot(self.repo)
        self.assertEqual(tag3, "paper-v3")
        self.assertEqual(list_versions(self.repo), ["paper-v1", "paper-v2", "paper-v3"])

        difference = diff_versions(self.repo, "paper-v1", "paper-v3")
        self.assertIn("first draft", difference)
        self.assertIn("second draft", difference)

        # diff differences are the product, not a problem: the subcommand
        # exits 0 even though the two versions differ.
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(
                [
                    "research_version.py",
                    "--repo",
                    str(self.repo),
                    "diff",
                    "paper-v1",
                    "paper-v3",
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn("second draft", out.getvalue())


if __name__ == "__main__":
    unittest.main()
