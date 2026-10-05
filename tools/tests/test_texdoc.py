import tempfile
import unittest
from pathlib import Path

from ccfa.texdoc import find_main_tex


def _write(dirpath: Path, name: str, body: str) -> Path:
    path = dirpath / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class TestFindMainTex(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_finds_single_documentclass_file(self):
        expected = _write(
            self.tmp, "neurips_2026.tex", r"\documentclass{article}\begin{document}\end{document}"
        )
        _write(self.tmp, "preamble.tex", r"\newcommand{\foo}{bar}")
        self.assertEqual(find_main_tex(self.tmp), expected)

    def test_prefers_conventional_main_name(self):
        _write(self.tmp, "aaa_template.tex", r"\documentclass{article}")
        expected = _write(self.tmp, "main.tex", r"\documentclass{article}")
        self.assertEqual(find_main_tex(self.tmp), expected)

    def test_searches_subdirectories(self):
        expected = _write(self.tmp / "src", "paper.tex", r"\documentclass{article}")
        self.assertEqual(find_main_tex(self.tmp), expected)

    def test_no_documentclass_raises(self):
        _write(self.tmp, "notes.tex", "just notes, no document class")
        with self.assertRaises(FileNotFoundError):
            find_main_tex(self.tmp)

    def test_empty_directory_raises(self):
        with self.assertRaises(FileNotFoundError):
            find_main_tex(self.tmp)
