import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

from ccfa.pdftext import extract_text, find_unresolved_markers


class TestFindUnresolvedMarkers(unittest.TestCase):
    def test_bracketed_marker_is_reported(self):
        problems = find_unresolved_markers("see [?] here", "paper.pdf")
        self.assertEqual([p.code for p in problems], ["unresolved-marker"])

    def test_spaced_marker_is_reported_with_line(self):
        problems = find_unresolved_markers("a\nb ? c\n", "paper.pdf")
        self.assertEqual(problems[0].line, 2)

    def test_prose_question_mark_is_not_reported(self):
        self.assertEqual(find_unresolved_markers("Why? Because.", "paper.pdf"), [])

    def test_two_markers_yield_two_problems(self):
        self.assertEqual(len(find_unresolved_markers("[?] and [?]", "p")), 2)

    def test_no_text_is_clean(self):
        self.assertEqual(find_unresolved_markers("", "p"), [])

    def test_run_of_markers_is_reported_once(self):
        problems = find_unresolved_markers("Figure ?? here", "paper.pdf")
        self.assertEqual(len(problems), 1)

    def test_marker_run_at_start_is_reported(self):
        problems = find_unresolved_markers("??", "paper.pdf")
        self.assertEqual(len(problems), 1)


class TestExtractText(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_injected_reader_is_used(self):
        seen = []

        def reader(path):
            seen.append(path)
            return "hello"

        pdf = self.root / "p.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        self.assertEqual(extract_text(pdf, reader=reader), "hello")
        self.assertEqual(seen, [pdf])

    def test_missing_pymupdf_returns_none(self):
        pdf = self.root / "p.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        with patch.dict(sys.modules, {"pymupdf": None}):
            self.assertIsNone(extract_text(pdf))

    def test_unreadable_pdf_returns_none(self):
        self.assertIsNone(extract_text(self.root / "gone.pdf"))

    def test_real_pdf_text_is_extracted(self):
        pdf = self.root / "real.pdf"
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((72, 72), "HELLO WORLD")
        document.save(str(pdf))
        document.close()
        text = extract_text(pdf)
        self.assertIsNotNone(text)
        self.assertIn("HELLO", text.replace("\n", " "))


if __name__ == "__main__":
    unittest.main()
