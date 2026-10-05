import tempfile
import unittest
from pathlib import Path

from ccfa.figurebytes import check_figure_formats, sniff

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 8
GIF = b"GIF89a" + b"\x00" * 8


class TestSniff(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _write(self, name, body):
        path = self.root / name
        path.write_bytes(body)
        return path

    def test_detects_png_jpeg_gif_pdf(self):
        self.assertEqual(sniff(self._write("a", PNG)), ".png")
        self.assertEqual(sniff(self._write("b", JPEG)), ".jpg")
        self.assertEqual(sniff(self._write("c", GIF)), ".gif")
        self.assertEqual(sniff(self._write("d", b"%PDF-1.4\n")), ".pdf")

    def test_unknown_bytes_return_none(self):
        self.assertIsNone(sniff(self._write("e", b"not an image at all")))

    def test_unreadable_path_returns_none(self):
        self.assertIsNone(sniff(self.root / "gone.png"))


class TestCheckFigureFormats(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _write(self, name, body):
        path = self.root / name
        path.write_bytes(body)
        return path

    def test_matching_png_is_clean(self):
        self.assertEqual(check_figure_formats([self._write("a.png", PNG)]), [])

    def test_jpeg_bytes_named_png_is_reported(self):
        problems = check_figure_formats([self._write("a.png", JPEG)])
        self.assertEqual([p.code for p in problems], ["figure-format"])
        self.assertIn("jpg", problems[0].message)

    def test_jpeg_bytes_named_jpeg_is_clean(self):
        self.assertEqual(check_figure_formats([self._write("a.jpeg", JPEG)]), [])

    def test_unknown_bytes_are_not_convicted(self):
        self.assertEqual(check_figure_formats([self._write("a.png", b"???")]), [])

    def test_pdf_suffix_is_out_of_scope(self):
        self.assertEqual(check_figure_formats([self._write("a.pdf", JPEG)]), [])

    def test_missing_file_is_skipped_not_crashed(self):
        self.assertEqual(check_figure_formats([self.root / "gone.png"]), [])


if __name__ == "__main__":
    unittest.main()
