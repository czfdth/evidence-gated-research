import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout

from ccfa.cli import Problem, emit, render_report, tool_error


class TestRenderReport(unittest.TestCase):
    def test_report_shape_with_no_problems(self):
        report = render_report([], [])
        self.assertEqual(report, {"problems": [], "advisories": [], "problem_count": 0})

    def test_problem_is_serialized_with_all_fields(self):
        problem = Problem("dangling-cite", "manuscript/main.tex", 42, "引用键不存在: foo")
        report = render_report([problem], [])
        self.assertEqual(
            report["problems"],
            [
                {
                    "code": "dangling-cite",
                    "path": "manuscript/main.tex",
                    "line": 42,
                    "message": "引用键不存在: foo",
                }
            ],
        )

    def test_advisories_do_not_count_as_problems(self):
        advisory = Problem("orphan-entry", "manuscript/references.bib", None, "条目从未被引用: bar")
        report = render_report([], [advisory])
        self.assertEqual(report["problem_count"], 0)
        self.assertEqual(len(report["advisories"]), 1)


class TestEmit(unittest.TestCase):
    def _emit(self, problems, advisories=()):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = emit(list(problems), list(advisories))
        return code, out.getvalue(), err.getvalue()

    def test_clean_run_exits_zero_and_emits_empty_json(self):
        code, out, _ = self._emit([])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["problem_count"], 0)

    def test_problem_run_exits_one(self):
        code, out, _ = self._emit([Problem("dangling-cite", "a.tex", 1, "x")])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["problem_count"], 1)

    def test_human_summary_goes_to_stderr_with_location(self):
        _, _, err = self._emit([Problem("dangling-cite", "a.tex", 7, "引用键不存在: foo")])
        self.assertIn("a.tex:7", err)

    def test_missing_line_does_not_emit_a_bare_colon(self):
        _, _, err = self._emit([Problem("orphan-entry", "a.bib", None, "从未被引用: bar")])
        self.assertIn("a.bib:", err)
        self.assertNotIn("a.bib:None", err)

    def test_stdout_stays_machine_readable(self):
        _, out, err = self._emit([Problem("dangling-cite", "a.tex", 1, "x")])
        json.loads(out)  # 抛异常即失败
        self.assertNotIn("a.tex:1", out)
        self.assertIn("a.tex", err)


class TestToolError(unittest.TestCase):
    def test_tool_error_exits_two_and_writes_stderr(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = tool_error("找不到 bib 文件")
        self.assertEqual(code, 2)
        self.assertIn("找不到 bib 文件", err.getvalue())
