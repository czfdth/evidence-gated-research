import tempfile
import unittest
from pathlib import Path

from build.compile import CompileResult, compile_project

from . import request_latex_engine

PLAIN = r"""\documentclass{article}
\begin{document}
\section{Smoke}
Plain English path only.
\end{document}
"""

WITH_BIB = r"""\documentclass{article}
\begin{document}
See \cite{vaswani2017attention}.
\bibliographystyle{plain}
\bibliography{sample}
\end{document}
"""

SAMPLE_BIB = """\
@inproceedings{vaswani2017attention,
  title     = {Attention Is All You Need},
  author    = {Vaswani, Ashish},
  booktitle = {NeurIPS},
  year      = {2017}
}
"""


class TestCompileProject(unittest.TestCase):
    def setUp(self):
        if self._testMethodName != "test_missing_file_reports_tool_error":
            request_latex_engine(self)
        self.tmp = Path(tempfile.mkdtemp())
        self.tex = self.tmp / "main.tex"

    def test_plain_document_compiles(self):
        self.tex.write_text(PLAIN, encoding="utf-8")
        result = compile_project(self.tex, self.tmp / "build")
        self.assertIsInstance(result, CompileResult)
        self.assertTrue(result.ok, result.log_tail)
        self.assertIsNotNone(result.pdf)
        self.assertTrue(result.pdf.is_file())

    def test_bibliography_document_compiles_and_resolves_citation(self):
        self.tex.write_text(WITH_BIB, encoding="utf-8")
        (self.tmp / "sample.bib").write_text(SAMPLE_BIB, encoding="utf-8")
        result = compile_project(self.tex, self.tmp / "build2")
        self.assertTrue(result.ok, result.log_tail)
        names = [name for name, _ in result.steps]
        self.assertIn("bibtex", names, "含引用的文档必须触发 bibtex")
        aux = (self.tmp / "build2" / "main.aux").read_text(
            encoding="utf-8", errors="replace"
        )
        self.assertIn("bibcite", aux, "引用未被解析")

    def test_broken_document_fails_without_raising(self):
        self.tex.write_text(
            r"\documentclass{article}\begin{document}\undefinedcmd\end{document}",
            encoding="utf-8",
        )
        result = compile_project(self.tex, self.tmp / "build3")
        self.assertFalse(result.ok)
        self.assertIsNone(result.pdf)
        self.assertIn("undefinedcmd", result.log_tail)

    def test_missing_file_reports_tool_error(self):
        with self.assertRaises(FileNotFoundError):
            compile_project(self.tmp / "nope.tex", self.tmp / "build4")

    def test_never_invokes_latexmk(self):
        self.tex.write_text(PLAIN, encoding="utf-8")
        result = compile_project(self.tex, self.tmp / "build5")
        names = [name for name, _ in result.steps]
        self.assertNotIn("latexmk", names, "latexmk 本机缺 Perl，不得调用")

    def test_plain_document_skips_bibtex(self):
        self.tex.write_text(PLAIN, encoding="utf-8")
        result = compile_project(self.tex, self.tmp / "build6")
        names = [name for name, _ in result.steps]
        self.assertNotIn("bibtex", names, "无引用时不应调用 bibtex")

    def test_failed_bibtex_is_not_a_false_success(self):
        self.tex.write_text(
            r"""\documentclass{article}
\begin{document}
See \cite{vaswani2017attention}.
\bibliographystyle{plain}
\bibliography{ccfa_missing_refs}
\end{document}
""",
            encoding="utf-8",
        )
        result = compile_project(self.tex, self.tmp / "build7")
        self.assertFalse(result.ok)
        self.assertIsNone(result.pdf)
        self.assertEqual(result.steps[-1][0], "bibtex")
        self.assertNotEqual(result.steps[-1][1], 0)
        self.assertIn("ccfa_missing_refs", result.log_tail)
