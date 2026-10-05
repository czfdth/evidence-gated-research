import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from ccfa.library import (
    SCHEMA_VERSION,
    build_index,
    check_library,
    main,
    search_index,
)
from ccfa.bib import load_entries, load_records

SAMPLE_BIB = r"""
@inproceedings{sample,
  title     = {Sample {GPU} Paper},
  author    = {Alice and Bob},
  year      = {2021},
  booktitle = {TestConf},
  abstract  = {An indexed abstract},
  doi       = {https://doi.org/10.1/AbC}
}

@article{chinese,
  title    = {注意力机制},
  author   = {Zhang and Li},
  journal  = {计算机学报},
  year     = {2024},
  abstract = {本文讨论推理模型与注意力机制}
}
"""


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _write_bib(self, text=SAMPLE_BIB):
        return self._write("refs.bib", text)

    def _build_sample(self, notes=None):
        self._write_bib()
        for stem, text in (notes or {}).items():
            self._write(Path("notes") / f"{stem}.md", text)
        return build_index(self.root)


class TestLoadRecords(LibraryTests):
    def test_load_records_reads_indexable_fields(self):
        path = self._write_bib()

        records = load_records(path).records

        record = records["sample"]
        self.assertEqual(record.title, "Sample GPU Paper")
        self.assertEqual(record.authors, "Alice and Bob")
        self.assertEqual(record.year, "2021")
        self.assertEqual(record.venue, "TestConf")
        self.assertEqual(record.abstract, "An indexed abstract")
        self.assertEqual(record.doi, "10.1/abc")

    def test_load_records_keeps_first_duplicate_and_records_key(self):
        path = self._write_bib(
            "@misc{dup, title={First}, year={2019}}\n"
            "@misc{dup, title={Second}, year={2020}}\n"
        )

        parsed = load_records(path)

        self.assertEqual(parsed.records["dup"].title, "First")
        self.assertEqual(parsed.duplicate_keys, ["dup"])

    def test_load_records_missing_file_raises_value_error(self):
        with self.assertRaises(ValueError):
            load_records(self.root / "missing.bib")

    def test_load_records_parse_failure_raises_value_error(self):
        path = self._write_bib("@article{broken, title={unterminated")

        with redirect_stderr(StringIO()), self.assertRaises(ValueError):
            load_records(path)


class TestLoadEntriesCompatibility(LibraryTests):
    def test_load_entries_keeps_existing_shape_and_values(self):
        entries = load_entries(self._write_bib())

        self.assertEqual(set(entries), {"sample", "chinese"})
        self.assertEqual(entries["sample"].title, "Sample GPU Paper")
        self.assertEqual(entries["sample"].doi, "10.1/abc")
        self.assertEqual(entries["sample"]._fields, ("key", "doi", "title"))

    def test_load_entries_still_rejects_duplicate_keys(self):
        path = self._write_bib(
            "@misc{dup, title={First}}\n@misc{dup, title={Second}}\n"
        )

        with self.assertRaises(ValueError):
            load_entries(path)


class TestBuildIndex(LibraryTests):
    def test_build_index_reports_entries_duplicates_and_stray_notes(self):
        self._write_bib(
            "@misc{kept, title={Kept}}\n"
            "@misc{kept, title={Duplicate}}\n"
            "@misc{other, title={Other}}\n"
        )
        self._write("notes/other.md", "note for other")
        self._write("notes/stray.md", "note with no bib key")
        stderr = StringIO()

        with redirect_stderr(stderr):
            summary = build_index(self.root)

        self.assertEqual(summary["entries"], 2)
        self.assertEqual(summary["duplicate_keys"], ["kept"])
        self.assertEqual(summary["stray_notes"], ["notes/stray.md"])
        self.assertIn("游离 note", stderr.getvalue())

    def test_build_index_meta_hashes_match_source_bytes(self):
        refs = self._write_bib()
        note = self._write("notes/chinese.md", "真实笔记内容")

        build_index(self.root)

        connection = sqlite3.connect(self.root / "index.db")
        try:
            meta = connection.execute(
                "SELECT schema_version, refs_sha256, notes_sha256, entry_count "
                "FROM meta"
            ).fetchone()
        finally:
            connection.close()
        expected_refs = hashlib.sha256(refs.read_bytes()).hexdigest()
        notes_digest = hashlib.sha256()
        relative = note.relative_to(self.root).as_posix()
        notes_digest.update(relative.encode("utf-8"))
        notes_digest.update(b"\0")
        notes_digest.update(note.read_bytes())
        notes_digest.update(b"\0")
        self.assertEqual(meta, (SCHEMA_VERSION, expected_refs, notes_digest.hexdigest(), 2))

    def test_index_schema_contains_meta_and_trigram_papers_table(self):
        self._build_sample()

        connection = sqlite3.connect(self.root / "index.db")
        try:
            meta_columns = [
                row[1] for row in connection.execute("PRAGMA table_info(meta)")
            ]
            sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'papers'"
            ).fetchone()[0]
        finally:
            connection.close()

        self.assertEqual(
            meta_columns,
            [
                "schema_version",
                "refs_sha256",
                "notes_sha256",
                "built_at",
                "entry_count",
            ],
        )
        self.assertIn("tokenize='trigram'", sql)
        self.assertIn("notes", sql)

    def test_notes_participate_in_search(self):
        self._build_sample({"sample": "retrievalaugmented generation note"})

        result = search_index(self.root, "retrievalaugmented")

        self.assertEqual([item["key"] for item in result["results"]], ["sample"])

    def test_search_path_is_empty_when_index_was_built_without_pdf(self):
        self._build_sample()

        result = search_index(self.root, "Sample")

        self.assertEqual(result["results"][0]["path"], "")

    def test_search_path_appears_after_pdf_is_added_without_rebuild(self):
        self._build_sample()
        self._write("papers/sample.pdf", "not a real pdf")

        result = search_index(self.root, "Sample")

        self.assertEqual(result["results"][0]["path"], "papers/sample.pdf")

    def test_search_path_disappears_after_pdf_is_deleted_without_rebuild(self):
        self._build_sample()
        pdf = self._write("papers/sample.pdf", "not a real pdf")
        self.assertEqual(
            search_index(self.root, "Sample")["results"][0]["path"],
            "papers/sample.pdf",
        )

        pdf.unlink()

        self.assertEqual(search_index(self.root, "Sample")["results"][0]["path"], "")

    def test_path_is_an_output_field_never_a_search_term(self):
        self._build_sample()
        self._write("papers/sample.pdf", "not a real pdf")

        hit = search_index(self.root, "Sample")["results"]

        self.assertEqual(hit[0]["path"], "papers/sample.pdf")
        self.assertEqual(search_index(self.root, "sample.pdf")["results"], [])
        self.assertEqual(search_index(self.root, "papers")["results"], [])

    def test_rebuild_replaces_the_index_atomically_without_temporary_file(self):
        self._build_sample()
        original = self.root / "index.db"
        self._write_bib(SAMPLE_BIB.replace("Sample {GPU} Paper", "Updated {GPU} Paper"))

        with patch("ccfa.library.os.replace", wraps=os.replace) as replace:
            build_index(self.root)

        replace.assert_called_once()
        self.assertEqual(Path(replace.call_args.args[0]), self.root / "index.db.tmp")
        self.assertEqual(Path(replace.call_args.args[1]), original)
        self.assertEqual(list(self.root.glob("index.db.tmp")), [])
        self.assertEqual(search_index(self.root, "Updated")["results"][0]["key"], "sample")

    def test_build_index_missing_refs_raises_value_error(self):
        with self.assertRaises(ValueError):
            build_index(self.root)


class TestSearchIndex(LibraryTests):
    def test_three_character_chinese_query_uses_fts_and_hits(self):
        self._build_sample()

        result = search_index(self.root, "注意力")

        self.assertEqual(result["mode"], "fts")
        self.assertEqual([item["key"] for item in result["results"]], ["chinese"])

    def test_two_character_chinese_query_uses_like_and_hits(self):
        self._build_sample()

        result = search_index(self.root, "推理")

        self.assertEqual(result["mode"], "like")
        self.assertEqual([item["key"] for item in result["results"]], ["chinese"])

    def test_quotes_dashes_and_boolean_words_are_literal_queries(self):
        self._write_bib(
            "@misc{literal, "
            "title={quote\"mark Alpha-Beta NOT this}, "
            "abstract={plain text}}\n"
        )
        build_index(self.root)

        cases = {
            'quote"mark': "literal",
            "Alpha-Beta": "literal",
            "NOT": "literal",
        }
        for query, expected_key in cases.items():
            with self.subTest(query=query):
                result = search_index(self.root, query)
                self.assertEqual(
                    [item["key"] for item in result["results"]],
                    [expected_key],
                )

    def test_short_query_escapes_percent_and_underscore_wildcards(self):
        self._write_bib(
            "@misc{percent, title={100% recall}}\n"
            "@misc{underscore, title={model_name}}\n"
            "@misc{plain, title={nothing special}}\n"
        )
        build_index(self.root)

        percent = search_index(self.root, "%")
        underscore = search_index(self.root, "_")

        self.assertEqual(percent["mode"], "like")
        self.assertEqual([item["key"] for item in percent["results"]], ["percent"])
        self.assertEqual(
            [item["key"] for item in underscore["results"]],
            ["underscore"],
        )

    def test_missing_index_names_the_bootstrap_command(self):
        self._write_bib()

        with self.assertRaisesRegex(ValueError, "先运行 library index"):
            search_index(self.root, "Sample")

    def test_stale_refs_are_rejected(self):
        self._build_sample()
        self._write_bib(SAMPLE_BIB.replace("2021", "2022"))

        with self.assertRaisesRegex(ValueError, "过期"):
            search_index(self.root, "Sample")

    def test_stale_notes_are_rejected(self):
        self._build_sample({"sample": "first note"})
        self._write("notes/sample.md", "changed note")

        with self.assertRaisesRegex(ValueError, "过期"):
            search_index(self.root, "Sample")

    def test_no_match_returns_empty_results(self):
        self._build_sample()

        result = search_index(self.root, "not-present-anywhere")

        self.assertEqual(result["mode"], "fts")
        self.assertEqual(result["results"], [])

    def test_limit_is_applied(self):
        self._write_bib(
            "@misc{one, title={shared token}}\n"
            "@misc{two, title={shared token}}\n"
            "@misc{three, title={shared token}}\n"
        )
        build_index(self.root)

        result = search_index(self.root, "shared", limit=2)

        self.assertEqual(len(result["results"]), 2)


class TestLibraryCheck(LibraryTests):
    def _codes(self, problems):
        return [problem.code for problem in problems]

    def test_clean_index_has_no_problems(self):
        self._build_sample({"sample": "a clean note"})

        self.assertEqual(check_library(self.root), [])

    def test_missing_index_reports_index_missing(self):
        self._write_bib()

        problems = check_library(self.root)

        self.assertIn("index-missing", self._codes(problems))

    def test_stale_refs_report_index_stale(self):
        self._build_sample()
        self._write_bib(SAMPLE_BIB.replace("2021", "2022"))

        problems = check_library(self.root)

        self.assertIn("index-stale", self._codes(problems))

    def test_stale_notes_report_index_stale(self):
        self._build_sample({"sample": "first note"})
        self._write("notes/sample.md", "changed note")

        problems = check_library(self.root)

        self.assertIn("index-stale", self._codes(problems))

    def test_refs_key_missing_from_index_is_reported(self):
        self._build_sample()
        connection = sqlite3.connect(self.root / "index.db")
        try:
            connection.execute("DELETE FROM papers WHERE key = 'sample'")
            connection.commit()
        finally:
            connection.close()

        problems = check_library(self.root)

        missing = [p for p in problems if p.code == "index-entry-missing"]
        self.assertEqual(len(missing), 1)
        self.assertIn("sample", missing[0].message)

    def test_index_key_missing_from_refs_is_reported(self):
        self._build_sample()
        connection = sqlite3.connect(self.root / "index.db")
        try:
            connection.execute(
                "INSERT INTO papers (key, title) VALUES (?, ?)",
                ("extra", "Extra entry"),
            )
            connection.commit()
        finally:
            connection.close()

        problems = check_library(self.root)

        extra = [p for p in problems if p.code == "index-entry-extra"]
        self.assertEqual(len(extra), 1)
        self.assertIn("extra", extra[0].message)

    def test_duplicate_bib_key_is_reported(self):
        self._write_bib(
            "@misc{dup, title={First}}\n"
            "@misc{dup, title={Second}}\n"
        )
        build_index(self.root)

        problems = check_library(self.root)

        duplicate = [p for p in problems if p.code == "duplicate-bib-key"]
        self.assertEqual(len(duplicate), 1)
        self.assertIn("dup", duplicate[0].message)

    def test_note_without_entry_is_reported(self):
        self._write_bib("@misc{sample, title={Sample}}\n")
        self._write("notes/stray.md", "note without a key")
        with redirect_stderr(StringIO()):
            build_index(self.root)

        problems = check_library(self.root)

        stray = [p for p in problems if p.code == "note-without-entry"]
        self.assertEqual(len(stray), 1)
        self.assertIn("stray", stray[0].message)

    def test_unsupported_index_schema_version_is_reported(self):
        self._build_sample()
        connection = sqlite3.connect(self.root / "index.db")
        try:
            connection.execute("UPDATE meta SET schema_version = 2")
            connection.commit()
        finally:
            connection.close()

        problems = check_library(self.root)

        self.assertIn("index-schema-version", self._codes(problems))

    def test_two_problems_are_both_reported_without_early_return(self):
        self._write_bib("@misc{sample, title={Sample}}\n")
        build_index(self.root)
        self._write_bib(
            "@misc{sample, title={Sample}}\n"
            "@misc{sample, title={Duplicate}}\n"
        )

        codes = self._codes(check_library(self.root))

        self.assertIn("index-stale", codes)
        self.assertIn("duplicate-bib-key", codes)

    def test_check_is_read_only(self):
        self._build_sample({"sample": "a note"})
        refs = self.root / "refs.bib"
        note = self.root / "notes" / "sample.md"
        index = self.root / "index.db"
        before = (refs.read_bytes(), note.read_bytes(), index.read_bytes())

        check_library(self.root)

        after = (refs.read_bytes(), note.read_bytes(), index.read_bytes())
        self.assertEqual(after, before)

    def test_missing_or_broken_refs_cannot_be_audited(self):
        missing_dir = self.root / "missing"
        with self.assertRaises(ValueError):
            check_library(missing_dir)

        broken_dir = self.root / "broken"
        broken_dir.mkdir()
        (broken_dir / "refs.bib").write_text(
            "@article{broken, title={unterminated",
            encoding="utf-8",
        )
        with redirect_stderr(StringIO()), self.assertRaises(ValueError):
            check_library(broken_dir)


class TestMain(LibraryTests):
    def test_index_and_search_commands_emit_json_and_exit_zero(self):
        self._write_bib()
        index_stdout = StringIO()
        search_stdout = StringIO()

        with redirect_stdout(index_stdout), redirect_stderr(StringIO()):
            index_code = main(["library", "--dir", str(self.root), "index"])
        with redirect_stdout(search_stdout), redirect_stderr(StringIO()):
            search_code = main(
                ["library", "--dir", str(self.root), "search", "注意力"]
            )

        self.assertEqual(index_code, 0)
        self.assertEqual(search_code, 0)
        self.assertEqual(json.loads(index_stdout.getvalue())["entries"], 2)
        self.assertEqual(
            json.loads(search_stdout.getvalue())["results"][0]["key"],
            "chinese",
        )

    def test_index_help_says_it_rebuilds_derived_data(self):
        stdout = StringIO()

        with redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            main(["library", "index", "--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("派生数据", stdout.getvalue())
        self.assertIn("可重建", stdout.getvalue())

    def test_search_help_lists_fields_and_explains_freshness_boundary(self):
        stdout = StringIO()

        with redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            main(["library", "search", "--help"])

        help_text = stdout.getvalue()
        normalized = " ".join(help_text.split())
        self.assertEqual(raised.exception.code, 0)
        for field in (
            "key",
            "title",
            "authors",
            "year",
            "venue",
            "abstract",
            "notes",
        ):
            with self.subTest(field=field):
                self.assertIn(field, help_text)
        self.assertIn("不含 PDF 全文", normalized)
        self.assertIn("新鲜度只对 refs.bib 与 notes 负责", normalized)
        self.assertIn("path 是结果字段、不参与检索", normalized)
        self.assertIn("key/title/authors/year/venue/abstract/notes；", normalized)
        self.assertNotIn("notes/path", normalized)


    def test_check_command_reports_problems_with_exit_one(self):
        self._write_bib()
        stdout = StringIO()

        with redirect_stdout(stdout), redirect_stderr(StringIO()):
            code = main(["library", "--dir", str(self.root), "check"])

        self.assertEqual(code, 1)
        self.assertEqual(
            json.loads(stdout.getvalue())["problems"][0]["code"],
            "index-missing",
        )

    def test_search_without_index_is_a_tool_error(self):
        self._write_bib()
        stderr = StringIO()

        with redirect_stderr(stderr):
            code = main(["library", "--dir", str(self.root), "search", "Sample"])

        self.assertEqual(code, 2)
        self.assertIn("工具错误", stderr.getvalue())
        self.assertIn("先运行 library index", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
