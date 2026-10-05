import json
import tempfile
import unittest
from pathlib import Path

from ccfa.citation_calibration import calibrate


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


if __name__ == "__main__":
    unittest.main()
