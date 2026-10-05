import tempfile
import unittest
from pathlib import Path

from ccfa.latex_structure import (
    check_braces,
    check_citations,
    check_environments,
    check_figures,
    find_stray_percent,
    scan_structure,
)


def _write(root: Path, body: str) -> Path:
    path = root / "main.tex"
    path.write_text(body, encoding="utf-8")
    return path


class TestBraces(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_balanced_braces_are_clean(self):
        self.assertEqual(check_braces(_write(self.root, r"\section{A} \textbf{b}")), [])

    def test_unclosed_brace_is_reported(self):
        problems = check_braces(_write(self.root, r"\section{A"))
        self.assertEqual([p.code for p in problems], ["unbalanced-brace"])

    def test_extra_closing_brace_is_reported_with_line(self):
        problems = check_braces(_write(self.root, "ok\n}\n"))
        self.assertEqual(problems[0].line, 2)

    def test_escaped_braces_do_not_count(self):
        self.assertEqual(check_braces(_write(self.root, r"a \{ b \}")), [])

    def test_brace_inside_a_comment_is_ignored(self):
        self.assertEqual(check_braces(_write(self.root, "% { unmatched")), [])

    def test_literal_backslash_then_comment_is_ignored(self):
        self.assertEqual(check_braces(_write(self.root, "line\\\\% { unmatched")), [])

    def test_double_backslash_before_brace_still_counts(self):
        # Two backslashes are a line-break command, so the brace is a real opener.
        problems = check_braces(_write(self.root, "a \\\\{ b"))
        self.assertEqual([p.code for p in problems], ["unbalanced-brace"])

    def test_triple_backslash_before_brace_is_escaped(self):
        self.assertEqual(check_braces(_write(self.root, "a \\\\\\{ b")), [])


class TestEnvironments(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_balanced_environments_are_clean(self):
        body = "\\begin{figure}\n\\end{figure}\n"
        self.assertEqual(check_environments(_write(self.root, body)), [])

    def test_mismatched_environment_names_are_reported(self):
        body = "\\begin{figure}\n\\end{table}\n"
        problems = check_environments(_write(self.root, body))
        self.assertEqual([p.code for p in problems], ["unmatched-environment"])
        self.assertIn("line 1", problems[0].message)

    def test_unclosed_environment_reports_its_open_line(self):
        problems = check_environments(_write(self.root, "text\n\\begin{table}\n"))
        self.assertEqual(problems[0].line, 2)

    def test_end_without_begin_is_reported(self):
        problems = check_environments(_write(self.root, "\\end{itemize}\n"))
        self.assertEqual(problems[0].line, 1)

    def test_environment_inside_a_comment_is_ignored(self):
        self.assertEqual(check_environments(_write(self.root, "% \\begin{figure}")), [])


class TestScanStructure(unittest.TestCase):
    def test_combines_both_checks(self):
        body = "\\begin{figure}\n{ unclosed\n"
        problems = scan_structure(_write(Path(tempfile.mkdtemp()), body))
        self.assertEqual(
            sorted(p.code for p in problems),
            ["unbalanced-brace", "unmatched-environment"],
        )


class TestCitations(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.bib = self.root / "references.bib"
        self.bib.write_text("@misc{known, title={T}}\n", encoding="utf-8")

    def test_known_key_is_clean(self):
        tex = _write(self.root, r"\cite{known}")
        self.assertEqual(check_citations([tex], self.bib), [])

    def test_unknown_key_is_reported_with_location(self):
        tex = _write(self.root, "text\n" + r"\citep{ghost}")
        problems = check_citations([tex], self.bib)
        self.assertEqual([p.code for p in problems], ["missing-cite-key"])
        self.assertEqual(problems[0].line, 2)
        self.assertIn("ghost", problems[0].message)

    def test_commented_citation_is_ignored(self):
        tex = _write(self.root, "% " + r"\cite{ghost}")
        self.assertEqual(check_citations([tex], self.bib), [])

    def test_duplicate_key_on_one_line_is_reported_once(self):
        tex = _write(self.root, r"\cite{ghost} and \cite{ghost}")
        problems = check_citations([tex], self.bib)
        self.assertEqual([p.code for p in problems], ["missing-cite-key"])


class TestFigures(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.figures = self.root / "figures"
        self.figures.mkdir()

    def test_existing_figure_is_clean(self):
        (self.figures / "plot.pdf").write_bytes(b"%PDF-1.4\n")
        tex = _write(self.root, r"\includegraphics{plot.pdf}")
        self.assertEqual(check_figures([tex], self.figures), [])

    def test_extensionless_reference_resolves(self):
        (self.figures / "plot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        tex = _write(self.root, r"\includegraphics[width=0.5\textwidth]{plot}")
        self.assertEqual(check_figures([tex], self.figures), [])

    def test_missing_figure_is_reported_with_line(self):
        tex = _write(self.root, "text\n" + r"\includegraphics{gone.png}")
        problems = check_figures([tex], self.figures)
        self.assertEqual([p.code for p in problems], ["missing-figure"])
        self.assertEqual(problems[0].line, 2)

    def test_commented_include_is_ignored(self):
        tex = _write(self.root, "% " + r"\includegraphics{gone.png}")
        self.assertEqual(check_figures([tex], self.figures), [])

    def test_spaced_include_with_missing_figure_is_reported(self):
        tex = _write(self.root, r"\includegraphics {gone.png}")
        problems = check_figures([tex], self.figures)
        self.assertEqual([p.code for p in problems], ["missing-figure"])


class TestStrayPercent(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_inline_percent_with_trailing_text_is_reported(self):
        problems = find_stray_percent(_write(self.root, "50% faster than baseline\n"))
        self.assertEqual([p.code for p in problems], ["stray-percent"])
        self.assertEqual(problems[0].line, 1)

    def test_trailing_percent_with_nothing_after_is_not_reported(self):
        self.assertEqual(find_stray_percent(_write(self.root, "text %\n")), [])

    def test_whole_line_comment_is_not_reported(self):
        self.assertEqual(find_stray_percent(_write(self.root, "% a note\n")), [])

    def test_escaped_percent_is_not_reported(self):
        self.assertEqual(find_stray_percent(_write(self.root, r"50\% faster")), [])

    def test_literal_backslash_then_comment_with_text_is_reported(self):
        self.assertEqual(
            [p.code for p in find_stray_percent(_write(self.root, "line\\\\% lost text\n"))],
            ["stray-percent"],
        )


if __name__ == "__main__":
    unittest.main()
