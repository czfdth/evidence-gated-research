import unittest

from ccfa.texcomment import is_escaped, strip_comment


class TestIsEscaped(unittest.TestCase):
    def test_single_backslash_escapes(self):
        self.assertTrue(is_escaped("\\%", 1))

    def test_two_backslashes_do_not_escape(self):
        self.assertFalse(is_escaped("\\\\%", 2))

    def test_character_at_the_start_is_not_escaped(self):
        self.assertFalse(is_escaped("a", 0))


class TestStripComment(unittest.TestCase):
    def test_plain_percent_starts_a_comment(self):
        self.assertEqual(strip_comment("\\cite{a} % \\cite{ghost}"), "\\cite{a} ")

    def test_escaped_percent_is_not_a_comment(self):
        self.assertEqual(strip_comment("100\\% of \\cite{a}"), "100\\% of \\cite{a}")

    def test_two_backslashes_then_percent_starts_a_comment(self):
        # A literal backslash followed by a percent: the percent is not escaped.
        self.assertEqual(strip_comment("line\\\\% \\cite{ghost}"), "line\\\\")

    def test_three_backslashes_then_percent_is_escaped(self):
        self.assertEqual(strip_comment("line\\\\\\% x"), "line\\\\\\% x")

    def test_no_percent_returns_line_unchanged(self):
        self.assertEqual(strip_comment("\\cite{a}"), "\\cite{a}")

    def test_percent_at_position_zero_yields_empty(self):
        self.assertEqual(strip_comment("% hidden"), "")

    def test_percent_at_end_of_line_yields_the_prefix(self):
        self.assertEqual(strip_comment("text %"), "text ")


if __name__ == "__main__":
    unittest.main()
