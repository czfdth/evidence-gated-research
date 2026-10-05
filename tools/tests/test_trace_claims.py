import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from ccfa import datasource
from ccfa.trace_claims import check, main


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.doc = self.root / "main.tex"
        (self.root / "results.json").write_text(
            json.dumps({"summary": {"lcoe": 0.14285714285714285}}), encoding="utf-8"
        )

    def write_doc(self, body: str):
        self.doc.write_text(body, encoding="utf-8")

    def run_check(self):
        return check([self.doc], self.root)

    def run_main(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                [
                    "trace_claims.py",
                    "--doc",
                    str(self.doc),
                    "--base-dir",
                    str(self.root),
                ]
            )
        return code, out.getvalue(), err.getvalue()

    @staticmethod
    def codes(problems):
        return sorted(p.code for p in problems)


class TestCheck(BaseCase):
    def test_matching_rounding_passes(self):
        self.write_doc("\\dataval{results.json:summary.lcoe}{0.143}")
        problems, _ = self.run_check()
        self.assertEqual(problems, [])

    def test_mismatch_is_a_problem_with_location(self):
        self.write_doc("\\dataval{results.json:summary.lcoe}{0.5}")
        problems, _ = self.run_check()
        self.assertEqual(self.codes(problems), ["dataval-mismatch"])
        self.assertEqual(problems[0].line, 1)
        self.assertTrue(problems[0].path.endswith("main.tex"))

    def test_missing_key_is_a_problem_not_a_crash(self):
        self.write_doc("\\dataval{results.json:nope}{1}")
        problems, _ = self.run_check()
        self.assertEqual(self.codes(problems), ["dataval-error"])

    def test_missing_source_file_is_a_problem(self):
        self.write_doc("\\dataval{gone.json:x}{1}")
        problems, _ = self.run_check()
        self.assertEqual(self.codes(problems), ["dataval-error"])

    def test_path_escape_is_a_problem(self):
        self.write_doc("\\dataval{../outside.json:x}{1}")
        problems, _ = self.run_check()
        self.assertEqual(self.codes(problems), ["dataval-error"])

    def test_commented_tag_is_not_checked(self):
        self.write_doc("% \\dataval{results.json:nope}{1}")
        problems, _ = self.run_check()
        self.assertEqual(problems, [])

    def test_no_tags_is_clean(self):
        self.write_doc("No numbers here.")
        problems, _ = self.run_check()
        self.assertEqual(problems, [])


class TestMain(BaseCase):
    def test_clean_run_exits_zero(self):
        self.write_doc("\\dataval{results.json:summary.lcoe}{0.143}")
        code, _, _ = self.run_main()
        self.assertEqual(code, 0)

    def test_manuscript_flag_scans_all_tex_files(self):
        self.write_doc("\\dataval{results.json:summary.lcoe}{0.143}")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                [
                    "trace_claims.py",
                    "--manuscript",
                    str(self.root),
                    "--base-dir",
                    str(self.root),
                ]
            )

        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(json.loads(out.getvalue())["problem_count"], 0)

    def test_mismatch_exits_one(self):
        self.write_doc("\\dataval{results.json:summary.lcoe}{0.5}")
        code, _, _ = self.run_main()
        self.assertEqual(code, 1)

    def test_missing_document_exits_two(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                [
                    "trace_claims.py",
                    "--doc",
                    str(self.root / "nope.tex"),
                    "--base-dir",
                    str(self.root),
                ]
            )
        self.assertEqual(code, 2)

    def test_invalid_base_dir_exits_two(self):
        self.write_doc("No numbers here.")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                [
                    "trace_claims.py",
                    "--doc",
                    str(self.doc),
                    "--base-dir",
                    str(self.root / "missing"),
                ]
            )
        self.assertEqual(code, 2)

    def test_missing_yaml_dependency_exits_two(self):
        self.write_doc("\\dataval{results.yaml:summary.lcoe}{0.143}")
        out, err = io.StringIO(), io.StringIO()
        # Patch yaml to simulate a real venv without PyYAML.
        with mock.patch.object(datasource, "yaml", None):
            with redirect_stdout(out), redirect_stderr(err):
                code = main(
                    [
                        "trace_claims.py",
                        "--doc",
                        str(self.doc),
                        "--base-dir",
                        str(self.root),
                    ]
                )
        self.assertEqual(code, 2)

    def test_unreadable_document_exits_two(self):
        self.write_doc("No numbers here.")
        out, err = io.StringIO(), io.StringIO()
        # Use a mock because Windows does not reliably deny the owner read access.
        with mock.patch.object(Path, "open", side_effect=PermissionError("denied")):
            with redirect_stdout(out), redirect_stderr(err):
                code = main(
                    [
                        "trace_claims.py",
                        "--doc",
                        str(self.doc),
                        "--base-dir",
                        str(self.root),
                    ]
                )
        self.assertEqual(code, 2)


class TestUntaggedAdvisory(BaseCase):
    def test_untagged_flag_puts_candidates_in_advisories(self):
        self.write_doc("Accuracy was 92.5 percent.")
        problems, advisories = check([self.doc], self.root, untagged=True)
        self.assertEqual(problems, [])
        self.assertEqual(self.codes(advisories), ["untagged-number"])

    def test_untagged_candidates_do_not_change_the_exit_code(self):
        self.write_doc("Accuracy was 92.5 percent.")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                [
                    "trace_claims.py",
                    "--doc",
                    str(self.doc),
                    "--base-dir",
                    str(self.root),
                    "--untagged",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["problem_count"], 0)


if __name__ == "__main__":
    unittest.main()
