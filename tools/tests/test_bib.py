import tempfile
import unittest
from pathlib import Path

from ccfa.bib import load_entries

SAMPLE = r"""
@inproceedings{vaswani2017attention,
  title     = {Attention Is All You Need},
  author    = {Vaswani, Ashish},
  doi       = {10.48550/arXiv.1706.03762},
  year      = {2017}
}

@article{noDOIentry,
  title = {An Entry Without a DOI},
  year = {2020}
}

@misc{weird-key,
  title = {Weird}
}
"""


def _bib(text: str) -> Path:
    path = Path(tempfile.mkdtemp()) / "references.bib"
    path.write_text(text, encoding="utf-8")
    return path


class TestLoadEntries(unittest.TestCase):
    def test_reads_key_doi_and_title(self):
        entries = load_entries(_bib(SAMPLE))
        self.assertIn("vaswani2017attention", entries)
        entry = entries["vaswani2017attention"]
        self.assertEqual(entry.doi, "10.48550/arxiv.1706.03762")
        self.assertEqual(entry.title, "Attention Is All You Need")

    def test_entry_without_doi_has_none(self):
        entries = load_entries(_bib(SAMPLE))
        self.assertIsNone(entries["noDOIentry"].doi)

    def test_title_braces_are_preserved_as_text(self):
        entries = load_entries(_bib('@misc{k, title = {The {GPU} Story}}'))
        self.assertIn("GPU", entries["k"].title)

    def test_empty_file_yields_no_entries(self):
        self.assertEqual(load_entries(_bib("")), {})

    def test_missing_file_raises_value_error(self):
        with self.assertRaises(ValueError):
            load_entries(Path(tempfile.mkdtemp()) / "nope.bib")

    def test_doi_is_normalized_to_lowercase_without_prefix(self):
        entries = load_entries(_bib('@misc{k, doi = {https://doi.org/10.1/AbC}}'))
        self.assertEqual(entries["k"].doi, "10.1/abc")

    def test_duplicate_key_raises_value_error(self):
        text = "@misc{dup, title={A}}\n@misc{dup, title={B}}\n"
        with self.assertRaises(ValueError):
            load_entries(_bib(text))
