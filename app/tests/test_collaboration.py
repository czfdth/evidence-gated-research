import tempfile
import unittest
from pathlib import Path

from ccfa_core.collaboration import (
    CollaborationError,
    CollaborationState,
    run_collaboration,
)

from . import write_project


class CollaborationWarningsTests(unittest.TestCase):
    """The list row is built from these labels, so they are pinned here."""

    def _state(self, **overrides):
        values = {
            "present": True,
            "dirty": False,
            "commit": "abc1234",
            "remotes": ("origin",),
            "workflows_present": True,
            "ready": True,
        }
        values.update(overrides)
        return CollaborationState(**values)

    def test_a_fully_wired_clean_paper_has_nothing_to_warn_about(self):
        self.assertEqual(self._state().warnings, ())

    def test_each_missing_piece_becomes_its_own_label(self):
        state = self._state(dirty=True, remotes=(), workflows_present=False)

        self.assertEqual(
            state.warnings,
            ("有未提交改动", "无 remote", "无 CI"),
        )

    def test_a_directory_outside_git_says_so_instead_of_listing_gaps(self):
        state = self._state(present=False, dirty=None, remotes=())

        self.assertEqual(state.warnings, ("非 git 仓库",))

    def test_unavailable_keeps_the_message_for_the_tooltip(self):
        state = CollaborationState.unavailable("找不到工作流解释器")

        self.assertFalse(state.present)
        self.assertEqual(state.error, "找不到工作流解释器")


class CollaborationProbeTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def test_a_plain_directory_is_reported_as_not_a_git_worktree(self):
        project_dir = write_project(self.root, "demo")

        state = run_collaboration(project_dir)

        self.assertFalse(state.present)
        self.assertIsNone(state.dirty)
        self.assertFalse(state.ready)
        self.assertEqual(state.warnings, ("非 git 仓库",))

    def test_a_missing_project_state_is_a_probe_error(self):
        empty = self.root / "papers" / "gone"
        empty.mkdir(parents=True)

        with self.assertRaises(CollaborationError):
            run_collaboration(empty)


if __name__ == "__main__":
    unittest.main()
