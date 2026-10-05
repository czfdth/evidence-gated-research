import tempfile
import unittest
from pathlib import Path

from ccfa.latex_compile import compile_document, find_engine


class TestFindEngine(unittest.TestCase):
    def test_unknown_preferred_engine_returns_none(self):
        self.assertIsNone(find_engine("definitely-not-a-real-engine"))


class TestCompileDocument(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.tex = self.root / "main.tex"
        self.tex.write_text("\\documentclass{article}", encoding="utf-8")

    def _runner(self, behaviour, with_bibdata=True):
        calls: list[list[str]] = []

        def run(argv, cwd):
            calls.append(list(argv))
            if argv[0] == "pdflatex" and with_bibdata:
                (Path(cwd) / "main.aux").write_text("\\bibdata{refs}\n", encoding="utf-8")
            return behaviour(argv[0], len(calls))

        return run, calls

    @staticmethod
    def _ok(name, count):
        return 0, ""

    def test_runs_the_full_sequence_when_bibdata_is_present(self):
        run, calls = self._runner(self._ok)
        report = compile_document(self.tex, "pdflatex", runner=run)
        self.assertEqual([step.name for step in report.steps], ["pdflatex", "bibtex", "pdflatex", "pdflatex"])
        self.assertEqual([step.status for step in report.steps], ["ran", "ran", "ran", "ran"])
        self.assertEqual([call[0] for call in calls], ["pdflatex", "bibtex", "pdflatex", "pdflatex"])

    def test_skips_bibtex_when_aux_has_no_bibdata(self):
        run, calls = self._runner(self._ok, with_bibdata=False)
        report = compile_document(self.tex, "pdflatex", runner=run)
        self.assertEqual([step.status for step in report.steps], ["ran", "skipped", "ran", "ran"])
        self.assertNotIn("bibtex", [call[0] for call in calls])

    def test_stops_after_a_failed_first_pass(self):
        run, calls = self._runner(lambda name, count: (1, "boom"))
        report = compile_document(self.tex, "pdflatex", runner=run)
        self.assertEqual(len(report.steps), 1)
        self.assertEqual(report.steps[0].status, "failed")
        self.assertEqual(report.steps[0].returncode, 1)

    def test_stops_after_a_failed_bibtex(self):
        def behaviour(name, count):
            return (1, "bibtex failed") if name == "bibtex" else (0, "")

        run, _ = self._runner(behaviour)
        report = compile_document(self.tex, "pdflatex", runner=run)
        self.assertEqual([step.status for step in report.steps], ["ran", "failed"])

    def test_stops_after_a_failed_second_pass(self):
        states = {"pdflatex": 0}

        def behaviour(name, count):
            if name == "pdflatex":
                states["pdflatex"] += 1
                if states["pdflatex"] == 2:
                    return (1, "second pass failed")
            return (0, "")

        run, _ = self._runner(behaviour)
        report = compile_document(self.tex, "pdflatex", runner=run)
        self.assertEqual([step.status for step in report.steps], ["ran", "ran", "failed"])

    def test_report_names_the_engine(self):
        run, _ = self._runner(self._ok)
        self.assertEqual(compile_document(self.tex, "xelatex", runner=run).engine, "xelatex")

    def test_runner_receives_the_document_directory_as_cwd(self):
        seen = []

        def run(argv, cwd):
            seen.append(Path(cwd))
            (Path(cwd) / "main.aux").write_text("\\bibdata{refs}\n", encoding="utf-8")
            return 0, ""

        compile_document(self.tex, "pdflatex", runner=run)
        self.assertEqual(set(seen), {self.root})


if __name__ == "__main__":
    unittest.main()
