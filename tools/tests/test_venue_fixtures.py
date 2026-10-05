import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.venue_fixtures import check_fixture, list_fixtures, seed_checklist


class VenueFixtureTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.fixture = self.root / "fixture.yaml"
        self.fixture.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "venue": "NeurIPS",
                    "source": "official checklist",
                    "items": [
                        {
                            "id": "claims",
                            "category": "claims",
                            "requirement": "Claims match evidence.",
                            "required": True,
                        }
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def test_valid_fixture_passes(self):
        problems, advisories = check_fixture(self.fixture)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_missing_item_field_is_problem(self):
        payload = yaml.safe_load(self.fixture.read_text(encoding="utf-8"))
        payload["items"][0].pop("requirement")
        self.fixture.write_text(
            yaml.safe_dump(payload, sort_keys=False),
            encoding="utf-8",
        )

        problems, _advisories = check_fixture(self.fixture)

        self.assertIn(
            "venue-fixture-invalid",
            [problem.code for problem in problems],
        )

    def test_seed_checklist_writes_pending_items(self):
        paper = self.root / "paper"
        (paper / "data").mkdir(parents=True)

        result = seed_checklist(paper, self.fixture)

        seeded = yaml.safe_load(
            (paper / "data" / "venue-checklist.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(result["item_count"], 1)
        self.assertEqual(seeded["venue"], "NeurIPS")
        self.assertEqual(seeded["items"][0]["status"], "pending")
        self.assertEqual(seeded["items"][0]["owner"], "")

    def test_repository_fixtures_exist(self):
        names = {item["name"] for item in list_fixtures()}
        self.assertIn("neurips-paper-checklist", names)
        self.assertIn("arr-responsible-nlp", names)


if __name__ == "__main__":
    unittest.main()
