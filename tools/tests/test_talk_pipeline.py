import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.talk_pipeline import check, render_outline


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


class TalkPipelineTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "data").mkdir()
        (self.paper / "figures").mkdir()
        _write_yaml(
            self.paper / "data" / "claim-registry.yaml",
            {
                "version": 1,
                "claims": [
                    {"id": "C1", "statement": "claim", "type": "empirical"}
                ],
            },
        )
        _write_yaml(
            self.paper / "figures" / "manifest.yaml",
            {"version": 1, "figures": [{"id": "F1", "path": "figures/plot.pdf"}]},
        )

    def _write_plan(self, status: str = "conference-ready") -> None:
        _write_yaml(
            self.paper / "data" / "talk-plan.yaml",
            {
                "version": 1,
                "status": status,
                "slides": [
                    {
                        "id": "S1",
                        "title": "Main result",
                        "claim_ids": ["C1"],
                        "figure_ids": ["F1"],
                        "talking_points": ["state the result"],
                        "speaker_notes": "explain the result",
                    }
                ],
                "qa": [
                    {
                        "question": "What is the limitation?",
                        "answer": "Scope is bounded.",
                    }
                ],
            },
        )

    def test_conference_ready_plan_passes(self):
        self._write_plan()

        problems, advisories = check(self.paper)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_unknown_claim_and_figure_are_problems(self):
        self._write_plan()
        path = self.paper / "data" / "talk-plan.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        payload["slides"][0]["claim_ids"] = ["C404"]
        payload["slides"][0]["figure_ids"] = ["F404"]
        _write_yaml(path, payload)

        problems, _advisories = check(self.paper)

        codes = [problem.code for problem in problems]
        self.assertIn("talk-unknown-claim", codes)
        self.assertIn("talk-unknown-figure", codes)

    def test_conference_ready_requires_speaker_notes_and_qa(self):
        self._write_plan()
        path = self.paper / "data" / "talk-plan.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        payload["slides"][0]["speaker_notes"] = ""
        payload["qa"] = []
        _write_yaml(path, payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "talk-conference-ready-incomplete",
            [problem.code for problem in problems],
        )

    def test_render_outline_lists_slides_and_sources(self):
        self._write_plan()
        payload = yaml.safe_load(
            (self.paper / "data" / "talk-plan.yaml").read_text(
                encoding="utf-8"
            )
        )

        text = render_outline(payload)

        self.assertIn("Main result", text)
        self.assertIn("C1", text)
        self.assertIn("F1", text)


if __name__ == "__main__":
    unittest.main()
