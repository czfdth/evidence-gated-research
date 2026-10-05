import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa_core.state import (
    StageTransitionError,
    advance_targets,
    rollback_targets,
    rollback_stage,
    set_stage,
    transition_targets,
)

from . import write_project


class TransitionTargetTests(unittest.TestCase):
    """Pure ordering rules: the workflow owns the stage table, we slice it."""

    STAGES = ("idea", "grounded", "writing", "submitted", "archived")

    def test_advance_targets_are_everything_after_the_current_stage(self):
        self.assertEqual(
            advance_targets("grounded", self.STAGES),
            ("writing", "submitted", "archived"),
        )

    def test_rollback_targets_are_everything_before_the_current_stage(self):
        self.assertEqual(
            rollback_targets("writing", self.STAGES),
            ("idea", "grounded"),
        )

    def test_the_ends_of_the_line_have_no_targets(self):
        self.assertEqual(advance_targets("archived", self.STAGES), ())
        self.assertEqual(rollback_targets("idea", self.STAGES), ())

    def test_unknown_stage_yields_nothing_rather_than_guessing(self):
        self.assertEqual(advance_targets("nope", self.STAGES), ())
        self.assertEqual(rollback_targets("nope", self.STAGES), ())

    def test_transition_targets_dispatches_on_kind(self):
        self.assertEqual(
            transition_targets("advance", "idea", self.STAGES),
            advance_targets("idea", self.STAGES),
        )
        with self.assertRaises(StageTransitionError):
            transition_targets("sideways", "idea", self.STAGES)


class StageWriteTests(unittest.TestCase):
    """The writes really go through ``ccfa.state`` and land in ccfa.yaml."""

    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _state(self, project_dir: Path) -> dict:
        return yaml.safe_load(
            (project_dir / "ccfa.yaml").read_text(encoding="utf-8")
        )

    def test_set_stage_advances_and_records_the_gate(self):
        project_dir = write_project(self.root, "demo", stage="idea")

        entry = set_stage(project_dir, to="grounded", reason="scope frozen")

        self.assertEqual(entry["from"], "idea")
        self.assertEqual(entry["to"], "grounded")
        self.assertEqual(entry["kind"], "advance")
        self.assertEqual(entry["gate"], "novelty_grounded")

        state = self._state(project_dir)
        self.assertEqual(state["stage"]["current"], "grounded")
        self.assertEqual(state["stage"]["gate"], "novelty_grounded")
        history = state["stage"]["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["reason"], "scope frozen")
        self.assertEqual(history[0]["kind"], "advance")

    def test_set_stage_refuses_to_move_backwards(self):
        project_dir = write_project(self.root, "demo", stage="writing")

        with self.assertRaises(StageTransitionError):
            set_stage(project_dir, to="idea", reason="changed my mind")

        # A rejected transition must leave the file exactly as it was.
        self.assertEqual(self._state(project_dir)["stage"]["current"], "writing")

    def test_an_empty_reason_never_reaches_the_workflow(self):
        project_dir = write_project(self.root, "demo", stage="idea")

        with self.assertRaises(StageTransitionError):
            set_stage(project_dir, to="grounded", reason="   ")

        self.assertEqual(self._state(project_dir)["stage"]["current"], "idea")

    def test_rollback_records_the_voided_artifacts(self):
        project_dir = write_project(self.root, "demo", stage="writing")

        entry = rollback_stage(
            project_dir,
            to="results-ready",
            reason="the effect did not replicate",
            void_artifacts=["results/table.csv", "manuscript/fig1.pdf"],
        )

        self.assertEqual(entry["kind"], "rollback")
        self.assertEqual(
            entry["void_artifacts"],
            ["results/table.csv", "manuscript/fig1.pdf"],
        )
        state = self._state(project_dir)
        self.assertEqual(state["stage"]["current"], "results-ready")
        self.assertEqual(state["stage"]["history"][-1]["kind"], "rollback")

    def test_a_missing_reason_is_rejected_for_rollback_too(self):
        project_dir = write_project(self.root, "demo", stage="writing")

        with self.assertRaises(StageTransitionError):
            rollback_stage(project_dir, to="idea", reason="")

        self.assertEqual(self._state(project_dir)["stage"]["current"], "writing")


if __name__ == "__main__":
    unittest.main()
