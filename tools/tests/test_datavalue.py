import unittest

from ccfa.datavalue import implied_rounding_tolerance, values_match


class TestImpliedRoundingTolerance(unittest.TestCase):
    def test_three_decimals_implies_half_unit(self):
        self.assertAlmostEqual(implied_rounding_tolerance("0.143"), 0.0005)

    def test_integer_has_no_implied_tolerance(self):
        self.assertEqual(implied_rounding_tolerance("42"), 0.0)


class TestValuesMatch(unittest.TestCase):
    def test_exact_number_matches(self):
        self.assertTrue(values_match("0.143", 0.143))

    def test_exact_string_matches(self):
        self.assertTrue(values_match("baseline", "baseline"))

    def test_rounded_claim_matches_full_precision_source(self):
        self.assertTrue(values_match("0.143", 0.14285714285714285))

    def test_rounded_claim_outside_half_unit_fails(self):
        self.assertFalse(values_match("0.5", 0.56))

    def test_integer_claim_has_no_implied_tolerance(self):
        self.assertFalse(values_match("42", 42.4))

    def test_thousands_separator_is_stripped(self):
        self.assertTrue(values_match("12,345.67", 12345.67))

    def test_json_style_boolean_matches_python_bool(self):
        self.assertTrue(values_match("false", False))
        self.assertTrue(values_match("True", True))

    def test_boolean_mismatch_fails(self):
        self.assertFalse(values_match("false", True))

    def test_relative_tolerance_accepts_small_relative_difference(self):
        self.assertTrue(
            values_match("1200000000", 1200000000.5, rel_tolerance=1e-6)
        )

    def test_relative_tolerance_is_off_by_default(self):
        self.assertFalse(values_match("1200000000", 1200000000.5))

    def test_non_numeric_mismatch_fails(self):
        self.assertFalse(values_match("baseline", "proposed"))

    def test_explicit_absolute_tolerance(self):
        # An integer claim implies no rounding tolerance; only an explicit one accepts the gap.
        self.assertTrue(values_match("10", 10.05, tolerance=0.1))
        self.assertFalse(values_match("10", 10.05))


if __name__ == "__main__":
    unittest.main()
