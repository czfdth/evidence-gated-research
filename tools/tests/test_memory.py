import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from ccfa.memory import (
    DEAD_ENDS_FILE,
    IDEAS_FILE,
    VALID_IDEA_STATUSES,
    add_dead_end,
    add_idea,
    check_memory,
    list_memory,
    load_memory,
    main,
    save_memory,
    search_memory,
)


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper_root = Path(self._temporary.name)

    def _ideas_path(self):
        return self.paper_root / IDEAS_FILE

    def _dead_ends_path(self):
        return self.paper_root / DEAD_ENDS_FILE

    def _write(self, relative, text):
        path = self.paper_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _add_idea(self, **overrides):
        values = {
            "idea": "使用对比学习替代多任务损失",
            "date": "2026-10-03",
        }
        values.update(overrides)
        return add_idea(self.paper_root, **values)

    def _add_dead_end(self, **overrides):
        values = {
            "idea": "使用对比学习替代多任务损失",
            "reason": "增益来自 batch size 变化",
            "evidence": "experiments/results/ablation.csv",
            "reopen_if": "出现新的负样本采样策略",
            "date": "2026-10-03",
        }
        values.update(overrides)
        return add_dead_end(self.paper_root, **values)


class TestAddIdea(MemoryTests):
    def test_first_add_creates_file_with_comment_header_and_fixed_fields(self):
        entry = self._add_idea(notes="initial note")
        path = self._ideas_path()

        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.splitlines()[0], "# 研究记忆（脚本读写，勿改字段名）")
        self.assertEqual(
            list(entry),
            ["id", "date", "idea", "status", "notes"],
        )
        self.assertEqual(
            entry,
            {
                "id": "I1",
                "date": "2026-10-03",
                "idea": "使用对比学习替代多任务损失",
                "status": "active",
                "notes": "initial note",
            },
        )

    def test_second_add_appends_without_overwriting_first_entry(self):
        first = self._add_idea(idea="first idea")
        second = self._add_idea(idea="second idea")

        self.assertEqual(first["id"], "I1")
        self.assertEqual(second["id"], "I2")
        self.assertEqual(
            [entry["idea"] for entry in load_memory(self._ideas_path())],
            ["first idea", "second idea"],
        )

    def test_next_id_uses_max_numeric_suffix_and_skips_used_numbers(self):
        save_memory(
            self._ideas_path(),
            [
                {
                    "id": "I1",
                    "date": "2026-10-01",
                    "idea": "first",
                    "status": "active",
                    "notes": None,
                },
                {
                    "id": "I3",
                    "date": "2026-10-02",
                    "idea": "third",
                    "status": "active",
                    "notes": None,
                },
            ],
        )

        entry = self._add_idea(idea="fourth")

        self.assertEqual(entry["id"], "I4")

    def test_invalid_date_status_and_idea_are_rejected(self):
        with self.assertRaises(ValueError):
            self._add_idea(date="2026-2-3")
        with self.assertRaises(ValueError):
            self._add_idea(status="whatever")
        for value in ("", "   ", None, 7):
            with self.subTest(idea=value):
                with self.assertRaises(ValueError):
                    self._add_idea(idea=value)

    def test_calendar_invalid_dates_are_rejected(self):
        for value in ("2026-13-01", "2026-02-30"):
            with self.subTest(date=value):
                with self.assertRaises(ValueError):
                    self._add_idea(date=value)

    def test_valid_status_enum_is_exposed(self):
        self.assertEqual(
            VALID_IDEA_STATUSES,
            ("active", "abandoned", "merged"),
        )


class TestAddDeadEnd(MemoryTests):
    def test_add_dead_end_has_six_fields_in_fixed_order(self):
        entry = self._add_dead_end()
        path = self._dead_ends_path()

        text = path.read_text(encoding="utf-8")
        self.assertEqual(
            text.splitlines()[0],
            "# 反重复记忆（脚本读写，勿改字段名）",
        )
        self.assertEqual(
            list(entry),
            ["id", "date", "idea", "reason", "evidence", "reopen_if"],
        )
        self.assertEqual(entry["id"], "DE1")
        self.assertEqual(entry["reopen_if"], "出现新的负样本采样策略")
        self.assertEqual(tuple(load_memory(path)[0]), tuple(entry))

    def test_reason_evidence_and_reopen_if_are_required(self):
        with self.assertRaises(ValueError):
            add_dead_end(
                self.paper_root,
                idea="missing reopen_if",
                reason="why",
                evidence="evidence.csv",
                date="2026-10-03",
            )

        for field in ("reason", "evidence", "reopen_if"):
            values = {
                "reason": "why",
                "evidence": "evidence.csv",
                "reopen_if": "when",
            }
            values[field] = ""
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self._add_dead_end(**values)

    def test_dead_end_ids_are_independent_from_idea_ids(self):
        self._add_idea()
        self._add_idea()

        first = self._add_dead_end()
        second = self._add_dead_end()

        self.assertEqual((first["id"], second["id"]), ("DE1", "DE2"))
        self.assertEqual(
            [entry["id"] for entry in load_memory(self._ideas_path())],
            ["I1", "I2"],
        )


class TestMemoryStore(MemoryTests):
    def test_load_memory_missing_file_returns_empty_list(self):
        self.assertEqual(load_memory(self._ideas_path()), [])

    def test_load_memory_rejects_broken_yaml(self):
        path = self._write(IDEAS_FILE, "- id: [unterminated\n")

        with self.assertRaises(ValueError):
            load_memory(path)

    def test_load_memory_rejects_mapping_top_level(self):
        path = self._write(IDEAS_FILE, "id: I1\nidea: wrong shape\n")

        with self.assertRaises(ValueError):
            load_memory(path)

    def test_save_memory_is_atomic_orders_fields_and_leaves_no_tmp(self):
        path = self._ideas_path()
        entries = [
            {
                "notes": None,
                "idea": "中文内容",
                "status": "active",
                "date": "2026-10-03",
                "id": "I1",
            }
        ]

        with patch("ccfa.cli.os.replace", wraps=os.replace) as replace:
            save_memory(path, entries)

        replace.assert_called_once()
        self.assertEqual(Path(replace.call_args.args[1]), path)
        text = path.read_text(encoding="utf-8")
        self.assertFalse(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertIn("中文内容", text)
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(list(load_memory(path)[0]), ["id", "date", "idea", "status", "notes"])
        self.assertEqual(list(path.parent.glob(f"{path.name}.tmp")), [])


class TestListMemory(MemoryTests):
    def test_list_memory_filters_kind_and_status(self):
        self._add_idea(idea="active idea", status="active")
        self._add_idea(idea="abandoned idea", status="abandoned")
        self._add_dead_end(idea="dead end")

        active = list_memory(self.paper_root, kind="ideas", status="active")
        dead_ends = list_memory(self.paper_root, kind="dead-ends")
        everything = list_memory(self.paper_root)

        self.assertEqual([entry["idea"] for entry in active["ideas"]], ["active idea"])
        self.assertEqual(active["dead_ends"], [])
        self.assertEqual(dead_ends["ideas"], [])
        self.assertEqual([entry["idea"] for entry in dead_ends["dead_ends"]], ["dead end"])
        self.assertEqual(len(everything["ideas"]), 2)
        self.assertEqual(len(everything["dead_ends"]), 1)

    def test_list_memory_rejects_invalid_kind_and_status(self):
        with self.assertRaises(ValueError):
            list_memory(self.paper_root, kind="unknown")
        with self.assertRaises(ValueError):
            list_memory(self.paper_root, status="unknown")


class TestMemoryCheck(MemoryTests):
    def _codes(self, problems):
        return [problem.code for problem in problems]

    def test_clean_memory_has_no_problems(self):
        self._add_idea()
        self._add_dead_end()

        self.assertEqual(check_memory(self.paper_root), [])

    def test_missing_required_fields_are_reported(self):
        self._write(
            IDEAS_FILE,
            "- date: \"2026-10-03\"\n"
            "  idea: missing id\n"
            "  status: active\n"
            "  notes: null\n"
            "- id: I2\n"
            "  idea: missing date\n"
            "  status: active\n"
            "  notes: null\n"
            "- id: I3\n"
            "  date: \"2026-10-03\"\n"
            "  status: active\n"
            "  notes: null\n",
        )

        codes = self._codes(check_memory(self.paper_root))

        self.assertEqual(codes.count("memory-missing-field"), 3)

    def test_invalid_date_and_id_are_reported(self):
        self._write(
            IDEAS_FILE,
            "- id: I0\n"
            "  date: \"2026-13-01\"\n"
            "  idea: invalid\n"
            "  status: active\n"
            "  notes: null\n",
        )

        codes = self._codes(check_memory(self.paper_root))

        self.assertIn("memory-invalid-date", codes)
        self.assertIn("memory-invalid-id", codes)

    def test_duplicate_ids_are_reported_for_both_entries(self):
        self._write(
            IDEAS_FILE,
            "- id: I1\n"
            "  date: \"2026-10-03\"\n"
            "  idea: first\n"
            "  status: active\n"
            "  notes: null\n"
            "- id: I1\n"
            "  date: \"2026-10-03\"\n"
            "  idea: second\n"
            "  status: active\n"
            "  notes: null\n",
        )

        duplicate = [
            problem
            for problem in check_memory(self.paper_root)
            if problem.code == "memory-duplicate-id"
        ]

        self.assertEqual(len(duplicate), 2)

    def test_invalid_status_is_revalidated_on_read(self):
        self._write(
            IDEAS_FILE,
            "- id: I1\n"
            "  date: \"2026-10-03\"\n"
            "  idea: manually edited\n"
            "  status: whatever\n"
            "  notes: null\n",
        )

        self.assertIn(
            "memory-invalid-status",
            self._codes(check_memory(self.paper_root)),
        )

    def test_dead_end_missing_reopen_if_is_reported(self):
        self._write(
            DEAD_ENDS_FILE,
            "- id: DE1\n"
            "  date: \"2026-10-03\"\n"
            "  idea: dead end\n"
            "  reason: failed\n"
            "  evidence: evidence.csv\n",
        )

        problems = check_memory(self.paper_root)
        missing = [
            problem
            for problem in problems
            if problem.code == "deadend-missing-reopen-if"
        ]
        self.assertEqual(len(missing), 1)
        self.assertTrue(missing[0].message.startswith("条目 DE1:"))

    def test_dead_end_reason_and_evidence_are_revalidated(self):
        cases = (
            (
                "reason",
                "- id: DE1\n"
                "  date: \"2026-10-03\"\n"
                "  idea: dead end\n"
                "  reason: \"\"\n"
                "  evidence: evidence.csv\n"
                "  reopen_if: reopen\n",
            ),
            (
                "evidence",
                "- id: DE1\n"
                "  date: \"2026-10-03\"\n"
                "  idea: dead end\n"
                "  reason: reason\n"
                "  reopen_if: reopen\n",
            ),
        )
        for field, text in cases:
            with self.subTest(field=field):
                self._write(DEAD_ENDS_FILE, text)
                problems = check_memory(self.paper_root)
                missing = [
                    problem
                    for problem in problems
                    if problem.code == "memory-missing-field"
                ]
                self.assertEqual(len(missing), 1)
                self.assertIn(field, missing[0].message)

    def test_non_mapping_does_not_stop_auditing_later_entries(self):
        self._write(
            IDEAS_FILE,
            "- not a mapping\n"
            "- id: I1\n"
            "  date: \"not-a-date\"\n"
            "  idea: later problem\n"
            "  status: active\n"
            "  notes: null\n",
        )

        problems = check_memory(self.paper_root)
        codes = self._codes(problems)

        self.assertIn("memory-entry-not-mapping", codes)
        self.assertIn("memory-invalid-date", codes)
        not_mapping = [
            problem
            for problem in problems
            if problem.code == "memory-entry-not-mapping"
        ]
        self.assertEqual(len(not_mapping), 1)
        self.assertTrue(not_mapping[0].message.startswith("第 1 条:"))

    def test_non_mapping_locator_uses_actual_position(self):
        self._write(
            IDEAS_FILE,
            "- id: I1\n"
            "  date: \"2026-10-03\"\n"
            "  idea: first entry\n"
            "  status: active\n"
            "  notes: null\n"
            "- not a mapping\n",
        )

        not_mapping = [
            problem
            for problem in check_memory(self.paper_root)
            if problem.code == "memory-entry-not-mapping"
        ]

        self.assertEqual(len(not_mapping), 1)
        self.assertTrue(not_mapping[0].message.startswith("第 2 条:"))

    def test_two_problems_in_one_pass_are_both_reported(self):
        self._write(
            IDEAS_FILE,
            "- id: I1\n"
            "  date: \"2026-10-03\"\n"
            "  idea: first\n"
            "  status: active\n"
            "  notes: null\n"
            "- id: I1\n"
            "  date: \"2026-10-03\"\n"
            "  idea: second\n"
            "  status: whatever\n"
            "  notes: null\n",
        )

        codes = self._codes(check_memory(self.paper_root))

        self.assertIn("memory-duplicate-id", codes)
        self.assertIn("memory-invalid-status", codes)

    def test_check_is_read_only(self):
        self._write(
            IDEAS_FILE,
            "- id: I0\n"
            "  date: \"bad\"\n"
            "  idea: invalid\n"
            "  status: whatever\n"
            "  notes: null\n",
        )
        self._add_dead_end()
        ideas = self.paper_root / IDEAS_FILE
        dead_ends = self.paper_root / DEAD_ENDS_FILE
        before = (ideas.read_bytes(), dead_ends.read_bytes())

        check_memory(self.paper_root)

        after = (ideas.read_bytes(), dead_ends.read_bytes())
        self.assertEqual(after, before)


class TestMemorySearch(MemoryTests):
    def test_search_finds_idea_text(self):
        self._add_idea(idea="Contrastive Learning for retrieval")

        result = search_memory(self.paper_root, "contrastive learning")

        self.assertEqual([entry["id"] for entry in result["ideas"]], ["I1"])
        self.assertEqual(result["dead_ends"], [])
        self.assertEqual(result["skipped_invalid"], 0)

    def test_search_finds_dead_end_reason_and_keeps_reopen_if(self):
        self._add_dead_end(
            reason="gain came from batch size",
            reopen_if="new negative sampling strategy",
        )

        result = search_memory(self.paper_root, "batch size")

        self.assertEqual(len(result["dead_ends"]), 1)
        self.assertEqual(
            result["dead_ends"][0]["reopen_if"],
            "new negative sampling strategy",
        )

    def test_search_is_case_insensitive(self):
        self._add_idea(idea="Retrieval Augmented Generation")

        result = search_memory(self.paper_root, "RETRIEVAL")

        self.assertEqual(len(result["ideas"]), 1)

    def test_search_counts_invalid_entries_and_returns_valid_hits(self):
        self._write(
            IDEAS_FILE,
            "- not a mapping\n"
            "- id: I1\n"
            "  date: \"2026-10-03\"\n"
            "  idea: valid searchable idea\n"
            "  status: active\n"
            "  notes: null\n",
        )

        result = search_memory(self.paper_root, "searchable")

        self.assertEqual(result["skipped_invalid"], 1)
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["file"], "memory/ideas.md")
        self.assertIsNone(result["skipped"][0]["id"])
        self.assertIn(
            "memory-entry-not-mapping",
            result["skipped"][0]["codes"],
        )
        self.assertEqual([entry["id"] for entry in result["ideas"]], ["I1"])

    def test_duplicate_matching_entries_are_both_skipped(self):
        self._write(
            IDEAS_FILE,
            "- id: I1\n"
            "  date: \"2026-10-03\"\n"
            "  idea: duplicate searchable idea\n"
            "  status: active\n"
            "  notes: null\n"
            "- id: I1\n"
            "  date: \"2026-10-03\"\n"
            "  idea: duplicate searchable idea\n"
            "  status: active\n"
            "  notes: null\n",
        )

        result = search_memory(self.paper_root, "duplicate")

        self.assertEqual(result["ideas"], [])
        self.assertEqual(result["skipped_invalid"], 2)
        self.assertEqual(len(result["skipped"]), 2)
        self.assertEqual(
            [(item["file"], item["id"]) for item in result["skipped"]],
            [
                ("memory/ideas.md", "I1"),
                ("memory/ideas.md", "I1"),
            ],
        )
        for item in result["skipped"]:
            self.assertIn("memory-duplicate-id", item["codes"])

    def test_invalid_dead_end_hit_is_reported_in_skipped(self):
        self._write(
            DEAD_ENDS_FILE,
            "- id: DE1\n"
            "  date: \"2026-10-03\"\n"
            "  idea: matching dead end\n"
            "  reason: matching reason\n"
            "  evidence: evidence.csv\n",
        )

        result = search_memory(self.paper_root, "matching")

        self.assertEqual(result["dead_ends"], [])
        self.assertEqual(result["skipped_invalid"], 1)
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["file"], "memory/dead-ends.md")
        self.assertEqual(result["skipped"][0]["id"], "DE1")
        self.assertIn(
            "deadend-missing-reopen-if",
            result["skipped"][0]["codes"],
        )

    def test_skipped_records_use_relative_paths_for_both_files(self):
        self._write(IDEAS_FILE, "- not a mapping\n")
        self._write(DEAD_ENDS_FILE, "- not a mapping\n")

        result = search_memory(self.paper_root, "anything")

        self.assertEqual(result["skipped_invalid"], 2)
        self.assertEqual(
            [item["file"] for item in result["skipped"]],
            ["memory/ideas.md", "memory/dead-ends.md"],
        )

    def test_search_rejects_empty_and_non_string_queries(self):
        for query in ("", "   ", None, 7):
            with self.subTest(query=query):
                with self.assertRaises(ValueError):
                    search_memory(self.paper_root, query)

    def test_search_no_match_is_an_empty_answer(self):
        self._add_idea(idea="one idea")

        result = search_memory(self.paper_root, "not present")

        self.assertEqual(result["ideas"], [])
        self.assertEqual(result["dead_ends"], [])
        self.assertEqual(result["skipped_invalid"], 0)

    def test_search_missing_files_is_an_empty_answer(self):
        result = search_memory(self.paper_root, "anything")

        self.assertEqual(result["ideas"], [])
        self.assertEqual(result["dead_ends"], [])
        self.assertEqual(result["skipped_invalid"], 0)


class TestMemoryReadFailures(MemoryTests):
    def test_load_memory_folds_directory_and_undecodable_bytes(self):
        ideas_dir = self.paper_root / IDEAS_FILE
        ideas_dir.mkdir(parents=True)
        with self.assertRaises(ValueError):
            load_memory(ideas_dir)

        ideas_dir.rmdir()
        ideas_dir.parent.mkdir(parents=True, exist_ok=True)
        ideas_dir.write_bytes(b"\xff\xfe")
        with self.assertRaises(ValueError):
            load_memory(ideas_dir)


class TestMain(MemoryTests):
    def test_add_and_list_commands_emit_json(self):
        add_stdout = StringIO()
        list_stdout = StringIO()

        with redirect_stdout(add_stdout), redirect_stderr(StringIO()):
            add_code = main(
                [
                    "memory",
                    "--paper-root",
                    str(self.paper_root),
                    "add-idea",
                    "--idea",
                    "cli idea",
                    "--date",
                    "2026-10-03",
                ]
            )
        with redirect_stdout(list_stdout), redirect_stderr(StringIO()):
            list_code = main(
                ["memory", "--paper-root", str(self.paper_root), "list"]
            )

        self.assertEqual(add_code, 0)
        self.assertEqual(list_code, 0)
        self.assertEqual(json.loads(add_stdout.getvalue())["id"], "I1")
        self.assertEqual(
            json.loads(list_stdout.getvalue())["ideas"][0]["idea"],
            "cli idea",
        )

    def test_add_dead_end_cli_happy_path(self):
        stdout = StringIO()

        with redirect_stdout(stdout), redirect_stderr(StringIO()):
            code = main(
                [
                    "memory",
                    "--paper-root",
                    str(self.paper_root),
                    "add-dead-end",
                    "--idea",
                    "cli dead end",
                    "--reason",
                    "reason",
                    "--evidence",
                    "evidence.csv",
                    "--reopen-if",
                    "reopen condition",
                    "--date",
                    "2026-10-03",
                ]
            )

        entry = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(entry["id"], "DE1")
        self.assertEqual(entry["reopen_if"], "reopen condition")
        self.assertEqual(
            set(entry),
            {"id", "date", "idea", "reason", "evidence", "reopen_if"},
        )

    def test_check_and_search_commands(self):
        self._add_idea(idea="CLI searchable idea")
        check_stdout = StringIO()
        search_stdout = StringIO()

        with redirect_stdout(check_stdout), redirect_stderr(StringIO()):
            check_code = main(
                ["memory", "--paper-root", str(self.paper_root), "check"]
            )
        with redirect_stdout(search_stdout), redirect_stderr(StringIO()):
            search_code = main(
                [
                    "memory",
                    "--paper-root",
                    str(self.paper_root),
                    "search",
                    "searchable",
                ]
            )

        self.assertEqual(check_code, 0)
        self.assertEqual(json.loads(check_stdout.getvalue())["problem_count"], 0)
        self.assertEqual(search_code, 0)
        self.assertEqual(
            json.loads(search_stdout.getvalue())["ideas"][0]["idea"],
            "CLI searchable idea",
        )

    def test_check_problem_and_bad_yaml_exit_codes(self):
        self._write(
            IDEAS_FILE,
            "- id: I0\n"
            "  date: \"bad\"\n"
            "  idea: invalid\n"
            "  status: whatever\n"
            "  notes: null\n",
        )
        problem_stdout = StringIO()
        with redirect_stdout(problem_stdout), redirect_stderr(StringIO()):
            problem_code = main(
                ["memory", "--paper-root", str(self.paper_root), "check"]
            )
        self.assertEqual(problem_code, 1)
        self.assertGreater(
            json.loads(problem_stdout.getvalue())["problem_count"],
            0,
        )

        self._write(IDEAS_FILE, "- id: [broken\n")
        stderr = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(stderr):
            broken_code = main(
                ["memory", "--paper-root", str(self.paper_root), "check"]
            )
        self.assertEqual(broken_code, 2)
        self.assertIn("工具错误", stderr.getvalue())

    def test_search_no_match_exits_zero_and_empty_query_exits_two(self):
        stdout = StringIO()
        with redirect_stdout(stdout), redirect_stderr(StringIO()):
            no_match_code = main(
                [
                    "memory",
                    "--paper-root",
                    str(self.paper_root),
                    "search",
                    "not present",
                ]
            )
        self.assertEqual(no_match_code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["ideas"], [])

        stderr = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(stderr):
            empty_code = main(
                ["memory", "--paper-root", str(self.paper_root), "search", ""]
            )
        self.assertEqual(empty_code, 2)
        self.assertIn("工具错误", stderr.getvalue())

    def test_invalid_add_is_a_tool_error(self):
        stderr = StringIO()

        with redirect_stderr(stderr):
            code = main(
                [
                    "memory",
                    "--paper-root",
                    str(self.paper_root),
                    "add-dead-end",
                    "--idea",
                    "dead end",
                    "--reason",
                    "reason",
                    "--evidence",
                    "evidence.csv",
                    "--reopen-if",
                    "",
                    "--date",
                    "2026-10-03",
                ]
            )

        self.assertEqual(code, 2)
        self.assertIn("工具错误", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
