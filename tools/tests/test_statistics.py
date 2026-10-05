import tempfile
import unittest
from pathlib import Path

from ccfa.stats_plan import check

VALID = """\
version: 1
alpha: 0.05
multiple_comparison: holm-bonferroni
claims:
  - id: claim:main
    endpoint: accuracy
    test: paired t-test
    effect_size: 0.5
    target_power: 0.8
    sample_size: 30
    seeds: [0, 1, 2]
    stopping_rule: fixed horizon
    missing_data: complete case
"""

DESCRIPTIVE = """\
version: 1
analysis_type: descriptive
alpha: not-applicable
multiple_comparison: not-applicable
claims:
  - id: claim:matrix
    endpoint: descriptive counts in the coded matrix
    test: deterministic recount; no hypothesis test is claimed
    effect_size: not-applicable
    target_power: not-applicable
    sample_size: 43
    seeds: not-applicable
    stopping_rule: frozen corpus
    missing_data: explicit unknown coding; no imputation
"""


class StatisticsTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "data").mkdir()
        self.path = self.root / "data" / "statistics-plan.yaml"
        self.path.write_text(VALID, encoding="utf-8")

    @staticmethod
    def _codes(problems):
        return {problem.code for problem in problems}

    def test_valid_plan_passes(self):
        problems, _advisories = check(self.root)
        self.assertEqual(problems, [])

    def test_descriptive_plan_can_mark_inferential_fields_not_applicable(self):
        self.path.write_text(DESCRIPTIVE, encoding="utf-8")

        problems, _advisories = check(self.root)

        self.assertEqual(problems, [])

    def test_not_applicable_is_rejected_for_inferential_plan(self):
        self.path.write_text(
            VALID.replace("effect_size: 0.5", "effect_size: not-applicable"),
            encoding="utf-8",
        )

        problems, _advisories = check(self.root)

        self.assertIn("statistics-invalid", self._codes(problems))

    def test_unknown_analysis_type_is_a_problem(self):
        self.path.write_text(
            VALID.replace(
                "alpha: 0.05",
                "analysis_type: exploratory\nalpha: 0.05",
            ),
            encoding="utf-8",
        )

        problems, _advisories = check(self.root)

        self.assertIn("statistics-invalid", self._codes(problems))

    def test_multiple_claims_require_correction(self):
        self.path.write_text(
            VALID.replace("multiple_comparison: holm-bonferroni", "multiple_comparison: none")
            + "  - id: claim:second\n"
            "    endpoint: latency\n"
            "    test: paired t-test\n"
            "    effect_size: 0.4\n"
            "    target_power: 0.8\n"
            "    sample_size: 30\n"
            "    seeds: [0]\n"
            "    stopping_rule: fixed horizon\n"
            "    missing_data: complete case\n",
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("statistics-missing-correction", self._codes(problems))

    def test_invalid_alpha_is_a_problem(self):
        self.path.write_text(
            VALID.replace("alpha: 0.05", "alpha: 1.5"),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("statistics-invalid", self._codes(problems))

    def test_invalid_sample_size_is_a_problem(self):
        self.path.write_text(
            VALID.replace("sample_size: 30", "sample_size: 0"),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("statistics-invalid", self._codes(problems))

    def test_seeds_must_be_present(self):
        self.path.write_text(
            VALID.replace("    seeds: [0, 1, 2]\n", "    seeds: []\n"),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("statistics-invalid", self._codes(problems))

    def test_non_finite_effect_size_is_a_problem(self):
        for value in (".nan", ".inf"):
            with self.subTest(value=value):
                self.path.write_text(
                    VALID.replace("effect_size: 0.5", f"effect_size: {value}"),
                    encoding="utf-8",
                )
                problems, _advisories = check(self.root)
                self.assertIn("statistics-invalid", self._codes(problems))

    def test_huge_effect_size_is_a_problem_not_a_crash(self):
        huge = "1" + "0" * 400
        self.path.write_text(
            VALID.replace("effect_size: 0.5", f"effect_size: {huge}"),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("statistics-invalid", self._codes(problems))


if __name__ == "__main__":
    unittest.main()
