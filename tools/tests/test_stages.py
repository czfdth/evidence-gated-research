import unittest

from ccfa.stages import (
    CONFERENCE_TAIL,
    JOURNAL_TAIL,
    SHARED_STAGES,
    all_gates,
    gate_for,
    stages_for,
)


class TestStages(unittest.TestCase):
    def test_shared_stages_are_identical_for_both_modes(self):
        shared = SHARED_STAGES
        self.assertEqual(stages_for("conference")[: len(shared)], shared)
        self.assertEqual(stages_for("journal")[: len(shared)], shared)

    def test_shared_stages_end_at_submitted(self):
        self.assertEqual(SHARED_STAGES[0], "idea")
        self.assertEqual(SHARED_STAGES[-1], "submitted")
        self.assertEqual(len(SHARED_STAGES), 10)

    def test_conference_tail_ends_archived(self):
        self.assertEqual(CONFERENCE_TAIL, ["rebuttal", "camera-ready", "archived"])

    def test_journal_tail_ends_archived(self):
        self.assertEqual(
            JOURNAL_TAIL,
            ["major-revision", "response-letter", "resubmitted", "accepted", "archived"],
        )

    def test_every_stage_has_a_gate(self):
        for mode in ("conference", "journal"):
            for stage in stages_for(mode):
                with self.subTest(mode=mode, stage=stage):
                    gate = gate_for(mode, stage)
                    self.assertTrue(gate.id)
                    self.assertTrue(gate.criterion)

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            stages_for("workshop")

    def test_unknown_stage_raises(self):
        with self.assertRaises(KeyError):
            gate_for("conference", "not-a-stage")

    def test_gate_ids_are_unique_within_a_mode(self):
        for mode in ("conference", "journal"):
            ids = [g.id for _, g in all_gates(mode)]
            self.assertEqual(len(ids), len(set(ids)), f"{mode} 模式存在重复 gate id")
