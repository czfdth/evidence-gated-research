import json
import tempfile
import unittest
from pathlib import Path

from ccfa.citation_calibration import build_dataset, calibrate, run_build


class CitationCalibrationTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.gold = self.root / "gold.jsonl"
        self.predictions = self.root / "predictions.jsonl"

    def _write(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n",
            encoding="utf-8",
        )

    def test_metrics_and_thresholds(self):
        self._write(
            self.gold,
            [
                {"id": "1", "label": "supported"},
                {"id": "2", "label": "unsupported"},
                {"id": "3", "label": "supported"},
                {"id": "4", "label": "unsupported"},
            ],
        )
        self._write(
            self.predictions,
            [
                {"id": "1", "prediction": "supported"},
                {"id": "2", "prediction": "supported"},
                {"id": "3", "prediction": "supported"},
                {"id": "4", "prediction": "unsupported"},
            ],
        )

        report = calibrate(self.gold, self.predictions)

        self.assertEqual(report["tp"], 2)
        self.assertEqual(report["fp"], 1)
        self.assertEqual(report["fn"], 0)
        self.assertEqual(report["tn"], 1)
        self.assertEqual(report["fpr"], 0.5)
        self.assertFalse(report["threshold_pass"])

    def test_missing_prediction_is_problem(self):
        self._write(self.gold, [{"id": "1", "label": "supported"}])
        self._write(self.predictions, [])

        report = calibrate(self.gold, self.predictions)

        self.assertEqual(report["missing"], ["1"])
        self.assertFalse(report["threshold_pass"])

    def test_empty_gold_set_fails_closed(self):
        self._write(self.gold, [])
        self._write(self.predictions, [])

        report = calibrate(self.gold, self.predictions)

        self.assertEqual(report["gold_count"], 0)
        self.assertEqual(report["error"], "gold-set-empty")
        self.assertFalse(report["threshold_pass"])

    def test_duplicate_id_is_rejected(self):
        self._write(
            self.gold,
            [
                {"id": "1", "label": "supported"},
                {"id": "1", "label": "unsupported"},
            ],
        )
        self._write(self.predictions, [])

        with self.assertRaisesRegex(ValueError, "重复 id"):
            calibrate(self.gold, self.predictions)


class CitationCalibrationBuildTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _paper(self, *, beta_doi: bool = True) -> Path:
        root = self.root / "paper"
        (root / "manuscript").mkdir(parents=True)
        (root / "data").mkdir(parents=True)
        (root / "manuscript" / "main.tex").write_text(
            "\\cite{alpha} and \\cite{beta}\n",
            encoding="utf-8",
        )
        beta_doi_field = "  doi = {10.1000/beta},\n" if beta_doi else ""
        (root / "manuscript" / "references.bib").write_text(
            "@article{alpha,\n"
            "  title = {Alpha Work},\n"
            "  doi = {10.1000/alpha},\n"
            "}\n"
            "@article{beta,\n"
            "  title = {Beta Work},\n"
            + beta_doi_field
            + "}\n",
            encoding="utf-8",
        )
        body = "sha256:" + "a" * 64
        entries = {}
        for key, doi, title in (
            ("alpha", "10.1000/alpha", "Alpha Work"),
            ("beta", "10.1000/beta", "Beta Work"),
        ):
            entries[key] = {
                "doi": doi,
                "status": "verified",
                "verified_at": "2026-01-01T00:00:00Z",
                "source": "crossref",
                "evidence": {
                    "body_sha256": body,
                    "retrieved_at": "2026-01-01T00:00:00Z",
                    "matched_title": title,
                    "source": "crossref",
                },
            }
        (root / "data" / "citation-ledger.json").write_text(
            json.dumps({"version": 1, "entries": entries}),
            encoding="utf-8",
        )
        return root

    def test_clean_entries_are_labelled_supported_and_accepted(self):
        dataset = build_dataset(self._paper())
        gold = {row["id"]: row["label"] for row in dataset["gold"]}
        predicted = {row["id"]: row["prediction"] for row in dataset["predictions"]}

        self.assertEqual(gold["clean:alpha"], "supported")
        self.assertEqual(predicted["clean:alpha"], "supported")
        self.assertEqual(gold["clean:beta"], "supported")
        self.assertEqual(predicted["clean:beta"], "supported")

    def test_constructed_defects_are_labelled_unsupported_and_caught(self):
        dataset = build_dataset(self._paper())
        gold = {row["id"]: row["label"] for row in dataset["gold"]}
        predicted = {row["id"]: row["prediction"] for row in dataset["predictions"]}

        for prefix in (
            "ledger-missing",
            "evidence-null",
            "duplicate-doi",
            "dangling-cite",
        ):
            case = f"{prefix}:alpha"
            self.assertEqual(gold[case], "unsupported", case)
            self.assertEqual(predicted[case], "unsupported", case)
        self.assertEqual(dataset["skipped"], [])

    def test_duplicate_doi_case_is_skipped_when_entry_has_no_doi(self):
        dataset = build_dataset(self._paper(beta_doi=False))
        skipped = [row["id"] for row in dataset["skipped"]]

        self.assertEqual(skipped, ["duplicate-doi:beta"])

    def test_run_build_writes_report_and_fails_closed_on_a_real_corpus(self):
        out = self.root / "out"
        report = run_build(self._paper(), out)

        self.assertTrue(report["threshold_pass"])
        self.assertEqual(report["fp"], 0)
        self.assertEqual(report["fn"], 0)
        self.assertEqual(report["generator"], "ccfa.citation_calibration/build")
        for name in ("gold.jsonl", "predictions.jsonl", "cases.json", "report.json"):
            self.assertTrue((out / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
