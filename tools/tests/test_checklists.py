import unittest
from pathlib import Path

from ccfa.stages import stages_for
from newpaper.checklists import render_checklist

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKLISTS = {"conference": "conference.md", "journal": "journal.md"}


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


class TestChecklistRendering(unittest.TestCase):
    def test_every_stage_appears_for_both_modes(self):
        for mode in ("conference", "journal"):
            text = render_checklist(mode)
            for stage in stages_for(mode):
                with self.subTest(mode=mode, stage=stage):
                    self.assertIn(f"[{stage}]", text)

    def test_conference_text_mentions_rebuttal(self):
        self.assertIn("rebuttal", render_checklist("conference"))

    def test_journal_text_mentions_response_letter(self):
        self.assertIn("response-letter", render_checklist("journal"))

    def test_checkbox_count_covers_every_stage(self):
        for mode in ("conference", "journal"):
            text = render_checklist(mode)
            with self.subTest(mode=mode):
                self.assertGreaterEqual(text.count("- [ ]"), len(stages_for(mode)))

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            render_checklist("workshop")


class TestCommittedChecklists(unittest.TestCase):
    def test_committed_files_match_fresh_render(self):
        for mode, filename in CHECKLISTS.items():
            with self.subTest(mode=mode):
                path = REPO_ROOT / "checklists" / filename
                with path.open("r", encoding="utf-8", newline="") as handle:
                    committed = handle.read()
                self.assertEqual(
                    normalize_newlines(committed),
                    normalize_newlines(render_checklist(mode)),
                    f"{filename} 与最新渲染不一致；请重新运行 tools/newpaper/checklists.py",
                )
