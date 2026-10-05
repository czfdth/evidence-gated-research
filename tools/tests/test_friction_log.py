import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from ccfa.friction_log import (
    aggregate_stores,
    add_entry,
    check_store,
    filter_entries,
    load_store,
    main,
    render_markdown,
    save_store,
    write_text_output,
)


class FrictionLogTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.store_path = self.root / "friction_log.json"

    def _add(self, **overrides):
        values = {
            "stage": "writing",
            "component": "citation-manager",
            "category": "tool-bug",
            "severity": "high",
            "description": "The citation manager dropped a key.",
        }
        values.update(overrides)
        return add_entry(self.store_path, **values)

    def _write_store(self, store):
        self.store_path.write_text(
            json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def test_load_store_missing_file_returns_empty_store(self):
        self.assertEqual(load_store(self.store_path), {"version": 1, "entries": []})

    def test_add_entry_assigns_incrementing_ids_and_complete_fields(self):
        first = self._add(description="first")
        second = self._add(
            stage="revision",
            component="latex-check",
            category="environment",
            severity="medium",
            description="second",
            workaround="used a fallback",
        )

        self.assertEqual(first["id"], 1)
        self.assertEqual(second["id"], 2)
        self.assertEqual(
            set(first),
            {
                "id",
                "created_at",
                "stage",
                "component",
                "category",
                "severity",
                "description",
                "workaround",
            },
        )
        self.assertIsNone(first["workaround"])
        self.assertEqual(second["workaround"], "used a fallback")
        datetime.strptime(first["created_at"], "%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(load_store(self.store_path)["entries"], [first, second])

    def test_add_entry_rejects_invalid_category(self):
        with self.assertRaises(ValueError):
            self._add(category="not-a-category")

    def test_add_entry_rejects_invalid_severity(self):
        with self.assertRaises(ValueError):
            self._add(severity="urgent")

    def test_check_store_revalidates_hand_edited_enums_for_all_entries(self):
        self._add(description="first")
        self._add(description="second")
        store = load_store(self.store_path)
        store["entries"][0]["category"] = "whatever"
        store["entries"][1]["severity"] = "urgent"
        self._write_store(store)

        problems = check_store(self.store_path)

        invalid = [p for p in problems if p.code == "friction-invalid-enum"]
        self.assertEqual(len(invalid), 2)

    def test_check_store_reports_missing_description_and_required_fields(self):
        self._write_store(
            {
                "version": 1,
                "entries": [
                    {
                        "id": 1,
                        "stage": "writing",
                        "component": "citation-manager",
                        "category": "tool-bug",
                        "severity": "high",
                        "description": "",
                    },
                    {
                        "id": 2,
                        "stage": "writing",
                        "category": "tool-bug",
                        "severity": "high",
                        "description": "missing component",
                    },
                    {
                        "id": 3,
                        "component": "citation-manager",
                        "category": "tool-bug",
                        "severity": "high",
                        "description": "missing stage",
                    },
                ],
            }
        )

        problems = check_store(self.store_path)

        self.assertEqual(
            [p.code for p in problems].count("friction-missing-description"),
            1,
        )
        self.assertEqual(
            [p.code for p in problems].count("friction-missing-field"),
            2,
        )

    def test_load_store_rejects_invalid_version_and_shape(self):
        cases = [
            {"entries": []},
            {"version": 2, "entries": []},
            {"version": 1, "entries": {}},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                self._write_store(payload)
                with self.assertRaises(ValueError):
                    load_store(self.store_path)

    def test_save_store_replaces_atomically_and_leaves_no_temporary_file(self):
        store = {"version": 1, "entries": [{"id": 1, "description": "kept"}]}

        with patch("ccfa.cli.os.replace", wraps=os.replace) as replace:
            save_store(self.store_path, store)

        replace.assert_called_once()
        self.assertEqual(Path(replace.call_args.args[1]), self.store_path)
        self.assertEqual(load_store(self.store_path), store)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_filter_entries_by_category(self):
        store = {
            "version": 1,
            "entries": [
                {"id": 1, "category": "tool-bug"},
                {"id": 2, "category": "environment"},
            ],
        }
        self.assertEqual(
            filter_entries(store, category="environment"),
            [{"id": 2, "category": "environment"}],
        )

    def test_filter_entries_by_component(self):
        store = {
            "version": 1,
            "entries": [
                {"id": 1, "component": "citation-manager"},
                {"id": 2, "component": "latex-check"},
            ],
        }
        self.assertEqual(
            filter_entries(store, component="latex-check"),
            [{"id": 2, "component": "latex-check"}],
        )

    def test_filter_entries_by_severity(self):
        store = {
            "version": 1,
            "entries": [
                {"id": 1, "severity": "low"},
                {"id": 2, "severity": "high"},
            ],
        }
        self.assertEqual(
            filter_entries(store, severity="high"),
            [{"id": 2, "severity": "high"}],
        )

    def test_check_store_is_read_only(self):
        self._write_store(
            {
                "version": 1,
                "entries": [
                    {
                        "id": 1,
                        "stage": "writing",
                        "component": "citation-manager",
                        "category": "invalid",
                        "severity": "high",
                        "description": "invalid category",
                    }
                ],
            }
        )
        before = self.store_path.read_bytes()

        check_store(self.store_path)

        self.assertEqual(self.store_path.read_bytes(), before)

    def test_render_markdown_has_header_and_one_row_per_entry(self):
        self._add(
            stage="writing",
            component="citation-manager",
            category="tool-bug",
            severity="high",
            description="citation dropped",
            workaround="re-added by hand",
        )
        store = load_store(self.store_path)

        text = render_markdown(store)

        self.assertIn(
            "| id | date | stage | component | category | severity | description | workaround |",
            text,
        )
        self.assertIn(
            "| 1 | "
            + store["entries"][0]["created_at"][:10]
            + " | writing | citation-manager | tool-bug | high | citation dropped | re-added by hand |",
            text,
        )

    def test_export_without_out_prints_the_document_to_stdout(self):
        self._add(description="stdout only")
        markdown_stdout = StringIO()
        with redirect_stdout(markdown_stdout), redirect_stderr(StringIO()):
            markdown_code = main(["friction-log", "--store", str(self.store_path), "export"])
        json_stdout = StringIO()
        with redirect_stdout(json_stdout), redirect_stderr(StringIO()):
            json_code = main(
                [
                    "friction-log",
                    "--store",
                    str(self.store_path),
                    "export",
                    "--format",
                    "json",
                ]
            )

        self.assertEqual(markdown_code, 0)
        self.assertEqual(json_code, 0)
        self.assertIn("| id | date |", markdown_stdout.getvalue())
        self.assertEqual(json.loads(json_stdout.getvalue()), load_store(self.store_path))
        self.assertEqual(list(self.root.glob("*.md")), [])

    def test_export_with_out_writes_the_document_to_a_file(self):
        self._add(description="to file")
        out = self.root / "export.md"
        stdout = StringIO()
        with redirect_stdout(stdout), redirect_stderr(StringIO()):
            code = main(
                ["friction-log", "--store", str(self.store_path), "export", "--out", str(out)]
            )

        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("to file", out.read_text(encoding="utf-8"))

    def test_aggregate_merges_stores_and_labels_each_source(self):
        first = self.root / "first.json"
        second = self.root / "second.json"
        add_entry(
            first,
            stage="writing",
            component="citation-manager",
            category="tool-bug",
            severity="high",
            description="first paper friction",
        )
        add_entry(
            second,
            stage="revision",
            component="latex-check",
            category="environment",
            severity="low",
            description="second paper friction",
        )

        store = aggregate_stores([(first, "paper-a"), (second, "paper-b")])

        self.assertEqual(store["version"], 1)
        self.assertEqual([entry["id"] for entry in store["entries"]], [1, 2])
        self.assertEqual(
            [entry["source"] for entry in store["entries"]], ["paper-a", "paper-b"]
        )
        self.assertEqual(
            [entry["description"] for entry in store["entries"]],
            ["first paper friction", "second paper friction"],
        )

    def test_aggregate_with_missing_input_is_a_tool_error(self):
        source = self.root / "source.json"
        add_entry(
            source,
            stage="writing",
            component="citation-manager",
            category="tool-bug",
            severity="high",
            description="valid entry",
        )
        missing = self.root / "missing.json"
        out = self.root / "merged.json"
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                [
                    "friction-log",
                    "aggregate",
                    f"{source}=paper-a",
                    f"{missing}=paper-b",
                    "--out",
                    str(out),
                ]
            )

        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertFalse(out.exists())
        self.assertIn("聚合输入不存在", stderr.getvalue())

    def test_aggregate_out_existing_file_is_refused_without_force(self):
        source = self.root / "source.json"
        add_entry(
            source,
            stage="writing",
            component="citation-manager",
            category="tool-bug",
            severity="high",
            description="kept",
        )
        out = self.root / "merged.json"
        out.write_text("do not clobber", encoding="utf-8")
        stderr = StringIO()

        with redirect_stdout(StringIO()), redirect_stderr(stderr):
            code = main(
                [
                    "friction-log",
                    "aggregate",
                    f"{source}=paper-a",
                    "--out",
                    str(out),
                ]
            )

        self.assertEqual(code, 2)
        self.assertEqual(out.read_text(encoding="utf-8"), "do not clobber")
        self.assertIn("输出目标已存在", stderr.getvalue())

    def test_aggregate_force_overwrites_existing_output(self):
        source = self.root / "source.json"
        add_entry(
            source,
            stage="writing",
            component="citation-manager",
            category="tool-bug",
            severity="high",
            description="kept",
        )
        out = self.root / "merged.json"
        out.write_text("stale", encoding="utf-8")

        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            code = main(
                [
                    "friction-log",
                    "aggregate",
                    f"{source}=paper-a",
                    "--out",
                    str(out),
                    "--force",
                ]
            )

        self.assertEqual(code, 0)
        merged = load_store(out)
        self.assertEqual(merged["entries"][0]["description"], "kept")

    def test_aggregate_carries_invalid_entries_through_and_reports_problems(self):
        self._add(description="valid entry")
        self._write_store(
            {
                "version": 1,
                "entries": [
                    {
                        "id": 1,
                        "created_at": "2026-10-03T00:00:00Z",
                        "stage": "writing",
                        "component": "citation-manager",
                        "category": "invalid-category",
                        "severity": "high",
                        "description": "hand edited into an invalid enum",
                        "workaround": None,
                    }
                ],
            }
        )
        out = self.root / "merged.json"
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                [
                    "friction-log",
                    "aggregate",
                    f"{self.store_path}=paper-x",
                    "--out",
                    str(out),
                ]
            )

        self.assertEqual(code, 1)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["problem_count"], 1)
        self.assertEqual(report["problems"][0]["code"], "friction-invalid-enum")
        self.assertIn("invalid-category", stderr.getvalue())
        merged = load_store(out)
        self.assertEqual(len(merged["entries"]), 1)
        self.assertEqual(merged["entries"][0]["id"], 1)
        self.assertEqual(merged["entries"][0]["source"], "paper-x")
        self.assertEqual(merged["entries"][0]["category"], "invalid-category")

    def test_write_text_output_refuses_overwrite_without_force(self):
        out = self.root / "artifact.txt"
        write_text_output(out, "first")
        with self.assertRaises(ValueError):
            write_text_output(out, "second")
        self.assertEqual(out.read_text(encoding="utf-8"), "first")
        write_text_output(out, "third", force=True)
        self.assertEqual(out.read_text(encoding="utf-8"), "third")


if __name__ == "__main__":
    unittest.main()
