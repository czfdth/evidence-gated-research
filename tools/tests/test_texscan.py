import tempfile
import unittest
from pathlib import Path

from ccfa.texscan import find_cited_keys, iter_tex_files


def _write(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class TestIterTexFiles(unittest.TestCase):
    def test_collects_recursively_and_sorts(self):
        root = Path(tempfile.mkdtemp())
        _write(root, "b.tex", "")
        _write(root, "sub/a.tex", "")
        _write(root, "notes.txt", "not latex")
        names = [p.name for p in iter_tex_files(root)]
        self.assertEqual(names, ["b.tex", "a.tex"])

    def test_missing_directory_returns_empty(self):
        self.assertEqual(iter_tex_files(Path(tempfile.mkdtemp()) / "nope"), [])


class TestFindCitedKeys(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _scan(self, body: str):
        path = _write(self.root, "main.tex", body)
        return find_cited_keys([path]), path

    def test_plain_cite(self):
        keys, path = self._scan(r"See \cite{vaswani2017attention}.")
        self.assertEqual(list(keys), ["vaswani2017attention"])
        self.assertEqual(keys["vaswani2017attention"][0].line, 1)

    def test_multiple_keys_in_one_command(self):
        keys, _ = self._scan(r"\cite{alpha, beta ,gamma}")
        self.assertEqual(sorted(keys), ["alpha", "beta", "gamma"])

    def test_cite_variants(self):
        keys, _ = self._scan(r"\citep{a} \citet{b} \citeauthor{c} \cite[p.~3]{d}")
        self.assertEqual(sorted(keys), ["a", "b", "c", "d"])

    def test_optional_argument_with_braces_inside_is_handled(self):
        keys, _ = self._scan(r"\cite[see {Sec.} 3]{e}")
        self.assertEqual(list(keys), ["e"])

    def test_commented_line_is_ignored(self):
        keys, _ = self._scan("% \\cite{ghost}\n\\cite{real}")
        self.assertEqual(list(keys), ["real"])

    def test_escaped_percent_does_not_start_a_comment(self):
        keys, _ = self._scan("100\\% of \\cite{kept}")
        self.assertEqual(list(keys), ["kept"])

    def test_literal_backslash_then_comment_hides_the_citation(self):
        keys, _ = self._scan("line\\\\% \\cite{ghost}\n\\cite{real}")
        self.assertEqual(list(keys), ["real"])

    def test_repeated_key_records_every_location(self):
        keys, path = self._scan("\\cite{a}\ntext\n\\cite{a}")
        locations = keys["a"]
        self.assertEqual([loc.line for loc in locations], [1, 3])
        self.assertEqual([loc.path for loc in locations], [str(path)] * 2)

    def test_no_citations_yields_empty_mapping(self):
        keys, _ = self._scan("Plain text only.")
        self.assertEqual(keys, {})

    def test_multiple_files_are_merged(self):
        first = _write(self.root, "one.tex", r"\cite{a}")
        second = _write(self.root, "two.tex", r"\cite{b}")
        keys = find_cited_keys([first, second])
        self.assertEqual(sorted(keys), ["a", "b"])

    def test_unreadable_file_is_skipped_not_crashed(self):
        missing = self.root / "gone.tex"
        keys = find_cited_keys([missing])
        self.assertEqual(keys, {})
