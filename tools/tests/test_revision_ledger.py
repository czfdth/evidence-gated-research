import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from ccfa.revision_ledger import check_ledger, main

HEADER = "| Concern ID | 来源 | 类型 | 需要的新证据 | 处置 | 承诺风险 | 状态 |"
SEPARATOR = "| --- | --- | --- | --- | --- | --- | --- |"


class RevisionLedgerTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _write(self, content: str) -> Path:
        path = self.root / "reviews" / "revision-ledger.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _ledger(self, *rows: str) -> Path:
        content = "# 审稿意见矩阵\n" + HEADER + "\n" + SEPARATOR + "\n"
        content += "".join(row + "\n" for row in rows)
        return self._write(content)

    def _row(
        self,
        cid="C1",
        source="R1",
        type_="证据不足",
        evidence="run-001",
        disposition="补充实验",
        risk="否",
        status="已处理",
    ) -> str:
        return (
            f"| {cid} | {source} | {type_} | {evidence} | "
            f"{disposition} | {risk} | {status} |"
        )

    def _run_cli(self, path: Path):
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["revision_ledger.py", "--ledger", str(path)])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_empty_seed_file_is_legal(self):
        path = self._write("# 审稿意见矩阵\n")

        self.assertEqual(check_ledger(path), [])
        code, stdout, stderr = self._run_cli(path)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["problem_count"], 0)

    def test_header_missing_or_reordered_is_reported_with_line(self):
        headers = (
            "| Concern ID | 来源 | 类型 | 需要的新证据 | 处置 | 承诺风险 |",
            "| 来源 | Concern ID | 类型 | 需要的新证据 | 处置 | 承诺风险 | 状态 |",
        )
        for header in headers:
            with self.subTest(header=header):
                path = self._write(
                    "# 审稿意见矩阵\n"
                    + header
                    + "\n| --- | --- | --- | --- | --- | --- |\n"
                )

                problems = check_ledger(path)

                self.assertEqual([p.code for p in problems], ["ledger-header"])
                self.assertEqual(problems[0].line, 2)

    def test_row_with_missing_cells_is_reported_with_line(self):
        path = self._ledger("| C1 | R1 | 证据不足 |")

        problems = check_ledger(path)

        self.assertEqual([p.code for p in problems], ["ledger-row-shape"])
        self.assertEqual(problems[0].line, 4)

    def test_escaped_pipe_in_disposition_is_not_a_column_separator(self):
        path = self._ledger(
            "| C1 | R1 | 证据不足 | run-001 | cite A \\| B | 否 | 已处理 |"
        )

        self.assertEqual(check_ledger(path), [])

    def test_header_without_separator_is_reported_with_line(self):
        path = self._write("# 审稿意见矩阵\n" + HEADER + "\n")

        problems = check_ledger(path)

        self.assertEqual([p.code for p in problems], ["ledger-header"])
        self.assertEqual(problems[0].line, 2)

    def test_duplicate_concern_id_is_reported_with_line(self):
        path = self._ledger(self._row(cid="C1"), self._row(cid="C1"))

        problems = check_ledger(path)

        self.assertEqual([p.code for p in problems], ["ledger-duplicate-id"])
        self.assertEqual(problems[0].line, 5)

    def test_duplicate_concern_id_is_case_insensitive(self):
        path = self._ledger(self._row(cid="C1"), self._row(cid="c1"))

        problems = check_ledger(path)

        self.assertEqual([p.code for p in problems], ["ledger-duplicate-id"])
        self.assertEqual(problems[0].line, 5)

    def test_empty_concern_id_is_reported_with_line(self):
        path = self._ledger(self._row(cid=""))

        problems = check_ledger(path)

        self.assertEqual([p.code for p in problems], ["ledger-empty-id"])
        self.assertEqual(problems[0].line, 4)
        self.assertIn("4", problems[0].message)

    def test_invalid_type_and_status_are_reported_with_line(self):
        path = self._ledger(
            self._row(type_="待确认", status="进行中"),
        )

        problems = check_ledger(path)

        self.assertEqual(
            [p.code for p in problems],
            ["ledger-invalid-type", "ledger-invalid-status"],
        )
        self.assertEqual({p.line for p in problems}, {4})

    def test_rejected_concern_requires_reason(self):
        missing = self._ledger(
            self._row(status="不采纳", disposition="", risk="否", evidence="无"),
        )
        problems = check_ledger(missing)

        self.assertEqual([p.code for p in problems], ["ledger-missing-reason"])
        self.assertEqual(problems[0].line, 4)

        explained = self._ledger(
            self._row(
                status="不采纳",
                disposition="审稿人误解了设定，回复澄清",
                risk="否",
                evidence="无",
            ),
        )
        self.assertEqual(check_ledger(explained), [])

    def test_invalid_risk_is_reported_with_line(self):
        path = self._ledger(self._row(risk="可能"))

        problems = check_ledger(path)

        self.assertEqual([p.code for p in problems], ["ledger-invalid-risk"])
        self.assertEqual(problems[0].line, 4)

    def test_affirmed_risk_requires_new_evidence(self):
        for evidence in ("", "无"):
            with self.subTest(evidence=evidence):
                path = self._ledger(self._row(risk="是", evidence=evidence))

                problems = check_ledger(path)

                self.assertEqual(
                    [p.code for p in problems],
                    ["ledger-risk-without-evidence"],
                )
                self.assertEqual(problems[0].line, 4)

        with_evidence = self._ledger(self._row(risk="是", evidence="run-002"))
        self.assertEqual(check_ledger(with_evidence), [])

    def test_valid_ledger_is_clean(self):
        path = self._ledger(
            self._row(
                cid="C1",
                type_="证据不足",
                evidence="run-001",
                disposition="补充实验",
                risk="是",
                status="待处理",
            ),
            self._row(
                cid="C2",
                type_="误解",
                evidence="无",
                disposition="回复澄清",
                risk="否",
                status="不采纳",
            ),
        )

        self.assertEqual(check_ledger(path), [])
        code, stdout, stderr = self._run_cli(path)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["problem_count"], 0)

    def test_cli_reports_problem_line_and_missing_file(self):
        path = self._ledger(self._row(type_="未知"))

        code, stdout, stderr = self._run_cli(path)

        self.assertEqual(code, 1, stderr)
        problem = json.loads(stdout)["problems"][0]
        self.assertEqual(problem["code"], "ledger-invalid-type")
        self.assertEqual(problem["line"], 4)
        self.assertIn("ledger-invalid-type", stderr)

        missing = self.root / "reviews" / "missing.md"
        code, stdout, stderr = self._run_cli(missing)
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("工具错误", stderr)

    def test_check_is_read_only(self):
        path = self._ledger(self._row())
        before = path.read_bytes()

        check_ledger(path)

        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
