import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import ccfa.latex_check as latex_check
from ccfa.latex_check import check, main
from ccfa.latex_compile import CompileReport, CompileStep


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.manuscript = self.root / "manuscript"
        self.manuscript.mkdir()
        self.tex = self.manuscript / "main.tex"
        self.tex.write_text("\\section{Intro}\n", encoding="utf-8")

    def write(self, body: str):
        self.tex.write_text(body, encoding="utf-8")

    def fake_compile(self, seen):
        original_compile = latex_check.compile_document
        original_engine = latex_check.find_engine
        report = CompileReport("pdflatex", [CompileStep("pdflatex", "ran", 0)])

        def compile_without_latex(tex, engine):
            seen["tex"] = Path(tex)
            seen["engine"] = engine
            return report

        latex_check.compile_document = compile_without_latex
        latex_check.find_engine = lambda preferred=None: "pdflatex"
        return original_compile, original_engine

    @staticmethod
    def restore_compile(original_compile, original_engine):
        latex_check.compile_document = original_compile
        latex_check.find_engine = original_engine

    def run_main(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                ["latex_check.py", "--manuscript", str(self.manuscript), *extra]
            )
        return code, out.getvalue(), err.getvalue()


class TestCheck(BaseCase):
    def test_clean_manuscript_has_no_problems(self):
        problems, advisories = check(self.manuscript)
        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_compiles_non_default_main_file(self):
        alternative = self.manuscript / "venue-paper.tex"
        alternative.write_text("\\section{Intro}\n", encoding="utf-8")
        self.tex.unlink()
        seen = {}
        originals = self.fake_compile(seen)
        try:
            problems, _ = check(
                self.manuscript,
                compile=True,
                main="venue-paper.tex",
            )
        finally:
            self.restore_compile(*originals)

        self.assertEqual(problems, [])
        self.assertEqual(seen["tex"], alternative.resolve())

    def test_default_main_file_is_still_main_tex(self):
        seen = {}
        originals = self.fake_compile(seen)
        try:
            problems, _ = check(self.manuscript, compile=True)
        finally:
            self.restore_compile(*originals)

        self.assertEqual(problems, [])
        self.assertEqual(seen["tex"], self.tex.resolve())

    def test_unclosed_brace_is_a_problem(self):
        self.write("\\section{Intro\n")
        problems, _ = check(self.manuscript)
        self.assertIn("unbalanced-brace", [p.code for p in problems])

    def test_missing_figure_is_a_problem(self):
        self.write("\\includegraphics{gone.png}\n")
        problems, _ = check(self.manuscript)
        self.assertIn("missing-figure", [p.code for p in problems])

    def test_missing_cite_key_is_a_problem(self):
        bib = self.root / "references.bib"
        bib.write_text("@misc{known, title={T}}\n", encoding="utf-8")
        self.write("\\cite{ghost}\n")
        problems, _ = check(self.manuscript, bib=bib)
        self.assertIn("missing-cite-key", [p.code for p in problems])

    def test_stray_percent_is_only_an_advisory(self):
        self.write("50% faster\n")
        problems, advisories = check(self.manuscript)
        self.assertNotIn("stray-percent", [p.code for p in problems])
        self.assertIn("stray-percent", [p.code for p in advisories])

    def test_failed_compile_step_becomes_a_problem(self):
        report = CompileReport("pdflatex", [CompileStep("pdflatex", "failed", 1)])
        original_compile = latex_check.compile_document
        original_engine = latex_check.find_engine
        latex_check.compile_document = lambda tex, engine: report
        latex_check.find_engine = lambda preferred=None: "pdflatex"
        try:
            problems, _ = check(self.manuscript, compile=True)
        finally:
            latex_check.compile_document = original_compile
            latex_check.find_engine = original_engine
        self.assertIn("compile-failed", [p.code for p in problems])


class TestMain(BaseCase):
    def test_missing_manuscript_exits_two(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                ["latex_check.py", "--manuscript", str(self.root / "nope")]
            )
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")

    def test_compile_without_engine_exits_two(self):
        original = latex_check.find_engine
        latex_check.find_engine = lambda preferred=None: None
        try:
            code, _, _ = self.run_main("--compile")
        finally:
            latex_check.find_engine = original
        self.assertEqual(code, 2)

    def test_compile_tool_unavailable_exits_two(self):
        original_compile = latex_check.compile_document
        original_engine = latex_check.find_engine
        latex_check.find_engine = lambda preferred=None: "pdflatex"

        def _missing_tool(tex, engine):
            raise FileNotFoundError("bibtex")

        latex_check.compile_document = _missing_tool
        try:
            code, out, _ = self.run_main("--compile")
        finally:
            latex_check.compile_document = original_compile
            latex_check.find_engine = original_engine
        self.assertEqual(code, 2)
        self.assertEqual(out, "")

    def test_main_flag_targets_non_default_file(self):
        alternative = self.manuscript / "venue-paper.tex"
        alternative.write_text("\\section{Intro}\n", encoding="utf-8")
        self.tex.unlink()
        seen = {}
        originals = self.fake_compile(seen)
        try:
            code, stdout, stderr = self.run_main(
                "--compile",
                "--main",
                "venue-paper.tex",
            )
        finally:
            self.restore_compile(*originals)

        self.assertEqual(code, 0, stderr)
        self.assertEqual(seen["tex"], alternative.resolve())
        self.assertEqual(json.loads(stdout)["problem_count"], 0)

    def test_missing_or_escaping_main_exits_two(self):
        original = latex_check.find_engine
        latex_check.find_engine = lambda preferred=None: "pdflatex"
        try:
            for name, expected in (
                ("does-not-exist.tex", "找不到主文件"),
                ("../escape.tex", "逃出"),
            ):
                with self.subTest(name=name):
                    code, stdout, stderr = self.run_main(
                        "--compile",
                        "--main",
                        name,
                    )
                    self.assertEqual(code, 2)
                    self.assertEqual(stdout, "")
                    self.assertIn(expected, stderr)
        finally:
            latex_check.find_engine = original

    def test_main_without_compile_exits_two(self):
        code, stdout, stderr = self.run_main(
            "--main",
            "venue-paper.tex",
        )

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("--main 仅在 --compile 时生效", stderr)


if __name__ == "__main__":
    unittest.main()
