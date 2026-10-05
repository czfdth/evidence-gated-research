import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from ccfa.provenance import (
    VALID_CLASSIFICATIONS,
    add_entry,
    check_store,
    load_store,
    main,
    render_markdown,
    save_store,
    sha256_of,
    write_markdown,
)


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.data = self.root / "data"
        self.data.mkdir()
        (self.data / "raw.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        self.store = self.root / "data" / "provenance.json"

    def add(self, **overrides):
        kwargs = dict(source="internal export", classification="real")
        kwargs.update(overrides)
        return add_entry(self.store, self.root, "data/raw.csv", **kwargs)


class TestSha256(BaseCase):
    def test_hash_is_prefixed_and_stable(self):
        first = sha256_of(self.data / "raw.csv")
        self.assertTrue(first.startswith("sha256:"))
        self.assertEqual(first, sha256_of(self.data / "raw.csv"))


class TestStoreRoundTrip(BaseCase):
    def test_missing_store_is_empty(self):
        self.assertEqual(load_store(self.store), {"version": 1, "files": {}})

    def test_save_then_load_round_trips(self):
        save_store(self.store, {"version": 1, "files": {"a": {"source": "x"}}})
        self.assertEqual(load_store(self.store)["files"]["a"]["source"], "x")

    def test_non_object_store_raises(self):
        self.store.write_text("[1, 2]\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_store(self.store)

    def test_malformed_json_raises(self):
        self.store.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_store(self.store)

    def test_missing_version_raises(self):
        self.store.write_text(json.dumps({"files": {}}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "store 缺少 version 字段"):
            load_store(self.store)

    def test_unsupported_version_raises(self):
        self.store.write_text(json.dumps({"version": 2, "files": {}}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "store version 不支持: 2"):
            load_store(self.store)

    def test_non_object_entry_is_tool_error(self):
        self.store.write_text(
            json.dumps({"version": 1, "files": {"data/a.csv": "oops"}}),
            encoding="utf-8",
        )
        stdout = StringIO()
        stderr = StringIO()
        args = [
            "provenance",
            "--store",
            str(self.store),
            "--paper-root",
            str(self.root),
            "check",
        ]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(args)
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("store 条目必须是对象", stderr.getvalue())

    def test_save_leaves_no_temporary_file_behind(self):
        save_store(self.store, {"version": 1, "files": {}})
        leftovers = [p.name for p in self.data.iterdir() if p.name != "provenance.json"]
        self.assertEqual([n for n in leftovers if n.startswith("provenance.")], [])


class TestAddEntry(BaseCase):
    def test_records_source_classification_and_checksum(self):
        entry = self.add(units="count", coverage="2020-2024", notes="exported 2026-10")
        self.assertEqual(entry["classification"], "real")
        self.assertEqual(entry["units"], "count")
        self.assertEqual(entry["sha256"], sha256_of(self.data / "raw.csv"))
        self.assertIn("recorded_at", entry)
        self.assertEqual(entry["size"], (self.data / "raw.csv").stat().st_size)

    def test_store_is_written_with_the_entry(self):
        self.add()
        self.assertIn("data/raw.csv", load_store(self.store)["files"])

    def test_invalid_classification_is_rejected(self):
        with self.assertRaises(ValueError):
            self.add(classification="made-up")

    def test_absolute_path_is_rejected(self):
        with self.assertRaises(ValueError):
            add_entry(
                self.store,
                self.root,
                str(self.data / "raw.csv"),
                source="x",
                classification="real",
            )

    def test_missing_source_file_is_rejected(self):
        with self.assertRaises(ValueError):
            add_entry(
                self.store, self.root, "data/gone.csv", source="x", classification="real"
            )

    def test_existing_entry_is_not_overwritten_without_force(self):
        self.add(notes="first")
        with self.assertRaises(ValueError):
            self.add(notes="second")
        self.assertEqual(load_store(self.store)["files"]["data/raw.csv"]["notes"], "first")

    def test_force_allows_rewriting(self):
        self.add(notes="first")
        self.add(notes="second", force=True)
        self.assertEqual(load_store(self.store)["files"]["data/raw.csv"]["notes"], "second")

    def test_classification_list_is_exposed(self):
        self.assertEqual(
            VALID_CLASSIFICATIONS, ("real", "rescaled-real", "documented-substitute")
        )

    def test_write_failure_returns_tool_error_without_stdout(self):
        args = [
            "provenance",
            "--store",
            str(self.store),
            "--paper-root",
            str(self.root),
            "add",
            "data/raw.csv",
            "--source",
            "internal export",
            "--classification",
            "real",
        ]
        stdout = StringIO()
        with mock.patch(
            "ccfa.cli.os.replace",
            side_effect=PermissionError("permission denied"),
        ):
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                exit_code = main(args)
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")


class TestCheckStore(BaseCase):
    def _codes(self, problems):
        return sorted(p.code for p in problems)

    def test_consistent_entry_is_clean(self):
        self.add()
        self.assertEqual(check_store(self.store, self.root), [])

    def test_modified_file_is_reported_as_drift(self):
        self.add()
        (self.data / "raw.csv").write_text("a,b\n9,9\n", encoding="utf-8")
        self.assertEqual(self._codes(check_store(self.store, self.root)), ["provenance-drift"])

    def test_removed_file_is_reported_as_missing(self):
        self.add()
        (self.data / "raw.csv").unlink()
        self.assertEqual(
            self._codes(check_store(self.store, self.root)), ["provenance-missing-file"]
        )

    def test_empty_source_is_reported(self):
        self.add()
        store = load_store(self.store)
        store["files"]["data/raw.csv"]["source"] = ""
        save_store(self.store, store)
        self.assertEqual(
            self._codes(check_store(self.store, self.root)), ["provenance-missing-source"]
        )

    def test_hand_edited_invalid_classification_is_reported(self):
        self.add()
        store = load_store(self.store)
        store["files"]["data/raw.csv"]["classification"] = "made-up"
        save_store(self.store, store)
        self.assertEqual(
            self._codes(check_store(self.store, self.root)),
            ["provenance-invalid-classification"],
        )

    def test_check_does_not_write(self):
        self.add()
        before = self.store.read_bytes()
        check_store(self.store, self.root)
        self.assertEqual(self.store.read_bytes(), before)

    def test_scan_reports_unrecorded_file(self):
        self.add()
        extra = self.data / "extra.csv"
        extra.write_text("x,y\n3,4\n", encoding="utf-8")

        stdout = StringIO()
        with redirect_stdout(stdout), redirect_stderr(StringIO()):
            exit_code = main(
                [
                    "provenance",
                    "--store",
                    str(self.store),
                    "--paper-root",
                    str(self.root),
                    "check",
                    "--scan",
                    "data",
                ]
            )

        self.assertEqual(exit_code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["problem_count"], 1)
        self.assertEqual(payload["problems"][0]["code"], "provenance-unrecorded")
        self.assertEqual(payload["problems"][0]["path"], str(extra))

    def test_unrecorded_file_is_invisible_without_scan(self):
        self.add()
        (self.data / "extra.csv").write_text("x,y\n3,4\n", encoding="utf-8")

        self.assertEqual(check_store(self.store, self.root), [])


class TestExport(BaseCase):
    def test_markdown_has_a_row_per_entry(self):
        self.add(notes="first")
        text = render_markdown(load_store(self.store))
        self.assertIn("data/raw.csv", text)
        self.assertIn("| 路径 |", text)
        # header row + separator row + the single data row
        self.assertEqual(text.count("\n| "), 3)

    def test_short_hash_is_shown(self):
        entry = self.add()
        text = render_markdown(load_store(self.store))
        self.assertIn(entry["sha256"][7:19], text)
        self.assertNotIn(entry["sha256"], text)

    def test_render_does_not_write(self):
        self.add()
        before = self.store.read_bytes()
        render_markdown(load_store(self.store))
        self.assertEqual(before, self.store.read_bytes())

    def test_write_markdown_creates_the_file(self):
        out = self.root / "data" / "provenance.md"
        write_markdown(out, "# doc\n")
        self.assertEqual(out.read_text(encoding="utf-8"), "# doc\n")

    def test_write_markdown_refuses_to_overwrite_without_force(self):
        out = self.root / "data" / "provenance.md"
        write_markdown(out, "first")
        with self.assertRaises(ValueError):
            write_markdown(out, "second")
        self.assertEqual(out.read_text(encoding="utf-8"), "first")

    def test_write_markdown_force_replaces(self):
        out = self.root / "data" / "provenance.md"
        write_markdown(out, "first")
        write_markdown(out, "second", force=True)
        self.assertEqual(out.read_text(encoding="utf-8"), "second")


if __name__ == "__main__":
    unittest.main()
