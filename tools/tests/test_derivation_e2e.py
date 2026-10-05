"""Derive real venue projects and exercise their actual main files.

The venue root is intentionally not patched here: this file is the
end-to-end evidence that the real
``$CODEX_HOME/skills/ccf-latex-templates`` library produces projects whose
actual venue main files compile with the host MiKTeX engine.

The real NeurIPS guideline document references ``myfile.pdf`` without
shipping that placeholder image, so ``latex_check`` reports
``missing-figure`` and exits 1 even though the document itself compiles.
Compile-success evidence therefore uses ``compile_document`` on the resolved
main file, while ``latex_check --manuscript`` pins that known placeholder problem.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from ccfa.latex_check import main as latex_check_main
from ccfa.latex_compile import compile_document, find_engine
from ccfa.memory import main as memory_main
from ccfa.milestones import main as milestones_main
from ccfa.texdoc import find_main_tex
from ccfa.validate import main as validate_main
from newpaper.create import create_project
from newpaper.venues import resolve_venue

from . import request_latex_engine, request_venue_library


class DerivationEndToEnd(unittest.TestCase):
    def setUp(self):
        request_venue_library(self)
        request_latex_engine(self)
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.papers = Path(self._temporary.name) / "papers"

    def _derive(self, slug: str, venue: str) -> Path:
        return create_project(
            papers_root=self.papers,
            slug=slug,
            venue=venue,
            year="2027",
            mode="conference",
            title=f"{venue} smoke",
            deadline=None,
        )

    def _run(self, command, argv):
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = command(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def _assert_skeleton(self, root: Path) -> None:
        self.assertTrue((root / "ccfa.yaml").is_file())
        manuscript = root / "manuscript"
        main_tex = find_main_tex(manuscript)
        self.assertEqual(main_tex.suffix, ".tex")
        self.assertTrue(any(manuscript.glob("*.sty")))
        self.assertTrue((manuscript / "references.bib").is_file())
        self.assertEqual(
            json.loads(
                (root / "data" / "provenance.json").read_text(encoding="utf-8")
            ),
            {"version": 1, "files": {}},
        )
        for rel in (
            "experiments/log",
            "experiments/results",
            "memory/ideas.md",
            "memory/dead-ends.md",
            "reviews",
            "submission/repro",
        ):
            with self.subTest(rel=rel):
                self.assertTrue((root / rel).exists(), f"缺少 {rel}")

    def _assert_toolchain(self, root: Path) -> None:
        code, _, stderr = self._run(
            validate_main,
            ["validate.py", str(root / "ccfa.yaml")],
        )
        self.assertEqual(code, 0, stderr)

        code, stdout, stderr = self._run(
            milestones_main,
            ["milestones.py", "stage", "--paper-root", str(root)],
        )
        self.assertEqual(code, 0, stderr)
        stage = json.loads(stdout)
        self.assertEqual(stage["current"], "idea")
        self.assertEqual(set(stage), {"current", "gate", "updated_at"})

        code, stdout, stderr = self._run(
            milestones_main,
            [
                "milestones.py",
                "due",
                "--paper-root",
                str(root),
                "--today",
                "2026-10-03",
            ],
        )
        self.assertEqual(code, 0, stderr)
        due = json.loads(stdout)
        self.assertEqual(due["mode"], "sequential")
        self.assertIsNone(due["deadline"])
        self.assertEqual(due["due"], [])
        self.assertEqual(due["problems"], [])

        code, stdout, stderr = self._run(
            memory_main,
            ["memory.py", "--paper-root", str(root), "check"],
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["problem_count"], 0)

    def _compile_actual_main(self, root: Path):
        manuscript = root / "manuscript"
        main_tex = find_main_tex(manuscript)
        engine = find_engine()
        if engine is None:
            self.skipTest("本机找不到 pdflatex/xelatex，无法完成真编译证据")
        log: list[dict] = []

        def runner(argv, cwd):
            completed = subprocess.run(
                list(argv),
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            output = (completed.stdout or "") + (completed.stderr or "")
            log.append(
                {
                    "argv": list(argv),
                    "cwd": str(cwd),
                    "returncode": completed.returncode,
                    "output": output,
                }
            )
            return completed.returncode, output

        report = compile_document(main_tex, engine, runner=runner)
        return manuscript, main_tex, engine, report, log

    def _failure_diagnostic(self, main_tex: Path, report, log) -> str:
        lines = [
            f"main_tex={main_tex}",
            f"steps={list(report.steps)!r}",
        ]
        failed = next(
            (
                index
                for index, step in enumerate(report.steps)
                if step.status == "failed"
            ),
            None,
        )
        if failed is not None and failed < len(log):
            entry = log[failed]
            lines.append("failed_command=" + " ".join(entry["argv"]))
            lines.append(f"failed_returncode={entry['returncode']}")
            lines.extend(entry["output"].splitlines()[:30])
        return "\n".join(lines)

    def _assert_compiles(self, root: Path):
        manuscript, main_tex, engine, report, log = self._compile_actual_main(root)
        pdf = manuscript / f"{main_tex.stem}.pdf"
        diagnostic = self._failure_diagnostic(main_tex, report, log)
        self.assertTrue(
            report.steps and report.steps[-1].status == "ran",
            f"{engine} 编译序列未成功:\n{diagnostic}",
        )
        self.assertTrue(pdf.is_file(), f"缺少 PDF: {pdf}\n{diagnostic}")
        self.assertGreater(pdf.stat().st_size, 0)
        return main_tex, pdf, engine, report

    def test_derived_neurips_project_compiles_end_to_end(self):
        root = self._derive("neurips-smoke", "NeurIPS")

        self._assert_skeleton(root)
        self._assert_toolchain(root)
        main_tex, pdf, engine, report = self._assert_compiles(root)

        self.assertEqual(main_tex.name, "neurips_2026.tex")
        self.assertEqual(report.engine, engine)
        self.assertGreater(pdf.stat().st_size, 0)

        # Structural mode pins the upstream placeholder gap. Exit 1 is the
        # correct result: the real template references myfile.pdf but does not
        # ship that placeholder asset.
        code, stdout, stderr = self._run(
            latex_check_main,
            [
                "latex_check.py",
                "--manuscript",
                str(root / "manuscript"),
            ],
        )
        self.assertEqual(code, 1, stderr)
        problems = json.loads(stdout)["problems"]
        self.assertTrue(
            any(
                problem["code"] == "missing-figure"
                and "myfile.pdf" in problem["message"]
                for problem in problems
            ),
            f"NeurIPS 上游占位图问题未被报出: {problems!r}",
        )

    def test_neurips_latex_check_compile_with_main_produces_pdf(self):
        root = self._derive("neurips-check-smoke", "NeurIPS")
        manuscript = root / "manuscript"
        main_tex = find_main_tex(manuscript)
        self.assertEqual(main_tex.name, "neurips_2026.tex")

        code, stdout, stderr = self._run(
            latex_check_main,
            [
                "latex_check.py",
                "--manuscript",
                str(manuscript),
                "--main",
                main_tex.name,
                "--compile",
            ],
        )

        problems = json.loads(stdout)["problems"]
        pdf = manuscript / f"{main_tex.stem}.pdf"
        self.assertEqual(code, 1, stderr)
        self.assertTrue(pdf.is_file(), f"缺少 PDF: {pdf}\n{stderr}")
        self.assertGreater(pdf.stat().st_size, 0)
        self.assertTrue(
            any(
                problem["code"] == "missing-figure"
                and "myfile.pdf" in problem["message"]
                for problem in problems
            ),
            f"NeurIPS 上游占位图问题未被报出: {problems!r}",
        )

    def test_acl_upstream_template_is_missing_bibliography_assets(self):
        """ACL 模板当前缺少 bib 资产；上游补齐后本用例必须升级。

        The upstream ACL directory ships ``acl.sty`` and ``acl_latex.tex``
        but not ``acl_natbib.bst`` or ``custom.bib``. If a future template
        update adds those files, the missing-asset assertions below fail and
        this test must be replaced with a full compile-success assertion.
        """

        root = self._derive("acl-smoke", "ACL")

        self._assert_skeleton(root)
        self._assert_toolchain(root)

        template = resolve_venue("ACL")
        for asset in ("acl_natbib.bst", "custom.bib"):
            self.assertFalse(
                (template / asset).exists(),
                f"上游 ACL 模板已提供 {asset}；请升级为完整编译成功断言",
            )

        _, _, _, report, log = self._compile_actual_main(root)
        self.assertTrue(report.steps, "ACL 编译序列没有执行任何步骤")
        self.assertEqual(
            report.steps[-1].status,
            "failed",
            f"ACL 模板意外编译成功；请升级为成功断言: {list(report.steps)!r}",
        )
        failed = next(
            index
            for index, step in enumerate(report.steps)
            if step.status == "failed"
        )
        output = log[failed]["output"]
        self.assertIn("acl_natbib.bst", output)
        self.assertIn("custom.bib", output)

    def test_derived_cvpr_project_preserves_nested_template_tree(self):
        root = self._derive("cvpr-smoke", "CVPR")
        manuscript = root / "manuscript"

        self.assertTrue((manuscript / "main.tex").is_file())
        self.assertTrue((manuscript / "cvpr.sty").is_file())
        for rel in ("sec/1_intro.tex", "sec/3_finalcopy.tex"):
            nested = manuscript / rel
            self.assertTrue(
                nested.is_file(),
                f"递归复制缺失: {nested.relative_to(root).as_posix()}",
            )


if __name__ == "__main__":
    unittest.main()
