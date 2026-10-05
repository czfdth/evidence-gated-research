import tempfile
import unittest
from pathlib import Path

import pymupdf
import yaml

from ccfa.claim_extract import check_candidates, extract_candidates


class ClaimExtractTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "data").mkdir()
        (self.paper / "data" / "claim-registry.yaml").write_text(
            "version: 1\nclaims: []\n",
            encoding="utf-8",
        )
        self.pdf = self.paper / "paper.pdf"
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text(
            (72, 72),
            "We show that X improves Y by 10 percent in the benchmark.",
        )
        document.save(str(self.pdf))
        document.close()

    def test_extract_writes_candidates_and_does_not_touch_registry(self):
        registry_before = (
            self.paper / "data" / "claim-registry.yaml"
        ).read_text(encoding="utf-8")

        def generator(prompt, **kwargs):
            return {
                "claims": [
                    {
                        "statement": "X improves Y by 10 percent.",
                        "source_quote": "We show that X improves Y by 10 percent",
                        "claim_type": "empirical",
                        "confidence": "high",
                    }
                ]
            }

        report = extract_candidates(
            self.paper,
            ["paper.pdf"],
            model="fake-model",
            generator=generator,
        )
        out = self.paper / "data" / "claim-candidates.yaml"
        loaded = yaml.safe_load(out.read_text(encoding="utf-8"))

        self.assertEqual(report["claims"][0]["status"], "proposed")
        self.assertEqual(loaded["claims"][0]["source"]["page"], 1)
        self.assertEqual(
            (self.paper / "data" / "claim-registry.yaml").read_text(
                encoding="utf-8"
            ),
            registry_before,
        )

    def test_quote_not_in_source_is_rejected(self):
        def generator(prompt, **kwargs):
            return {
                "claims": [
                    {
                        "statement": "Unsupported claim.",
                        "source_quote": "This sentence is not in the source.",
                        "claim_type": "descriptive",
                        "confidence": "low",
                    }
                ]
            }

        report = extract_candidates(
            self.paper,
            ["paper.pdf"],
            model="fake-model",
            generator=generator,
        )

        self.assertEqual(report["claims"], [])
        self.assertEqual(report["rejections"][0]["reason"], "quote-not-in-source")

    def test_heuristic_extractor_works_without_a_model(self):
        report = extract_candidates(self.paper, ["paper.pdf"])

        self.assertEqual(len(report["claims"]), 1)
        self.assertEqual(report["generator"]["kind"], "heuristic")

    def test_check_detects_source_drift(self):
        report = extract_candidates(self.paper, ["paper.pdf"])
        self.assertTrue(report["claims"])

        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((72, 72), "Completely different text.")
        document.save(str(self.pdf))
        document.close()

        problems = check_candidates(
            self.paper,
            Path("data/claim-candidates.yaml"),
        )

        self.assertIn(
            "claim-candidates-source-drift",
            [problem.code for problem in problems],
        )

    def test_existing_candidate_ledger_is_not_overwritten(self):
        extract_candidates(self.paper, ["paper.pdf"])

        with self.assertRaisesRegex(ValueError, "拒绝覆盖"):
            extract_candidates(self.paper, ["paper.pdf"])


if __name__ == "__main__":
    unittest.main()
