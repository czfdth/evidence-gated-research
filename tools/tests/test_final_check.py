import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from ccfa.final_check import check, main

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 8
CLEAN_TEXT = "Limitations and Data Availability are stated here."
MANIFEST = (
    "- name: plot\n"
    "  file: figures/plot.png\n"
    "  bytes_format: png\n"
    "  generator: src/plot.py\n"
    "  generator_hash: \"{hash}\"\n"
    "  source_run_ids: [\"20261003T142530-01\"]\n"
    "  source_data: experiments/results/main.csv\n"
    "  referenced_in: [\"manuscript/main.tex:1\"]\n"
)


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.manuscript = self.root / "manuscript"
        self.manuscript.mkdir()
        (self.manuscript / "main.tex").write_text("\\section{Intro}\n", encoding="utf-8")
        self.pdf = self.manuscript / "main.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\n")
        self.figures = self.root / "figures"
        self.figures.mkdir()
        self.log_dir = self.root / "experiments" / "log"
        self.log_dir.mkdir(parents=True)
        (self.log_dir / "20261003T142530-01.json").write_text(
            '{"run_id": "20261003T142530-01"}\n',
            encoding="utf-8",
        )
        self.source_data = self.root / "experiments" / "results" / "main.csv"
        self.source_data.parent.mkdir(parents=True)
        self.source_data.write_text("x,y\n1,2\n", encoding="utf-8")
        self.reader = lambda path: CLEAN_TEXT
        self.policy_path = self.root / "data" / "claims.yaml"
        self.write_policy()
        self.main = self.manuscript / "main.tex"
        self.main.write_text(
            "\\begin{abstract}\n"
            "\\end{abstract}\n"
            "\\section{Contributions}\n"
            "\\section{Results}\n",
            encoding="utf-8",
        )

    def run_check(self, **kwargs):
        kwargs.setdefault("reader", self.reader)
        return check(self.manuscript, pdf=self.pdf, **kwargs)

    def write_policy(self, **overrides):
        payload = {
            "version": 1,
            "protected_sections": ["abstract", "contributions", "results"],
            "waivers": [],
        }
        payload.update(overrides)
        self.policy_path.parent.mkdir(parents=True, exist_ok=True)
        self.policy_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def write_generator(self, body="print('x')\n"):
        path = self.root / "src" / "plot.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    def write_manifest(self, body):
        path = self.root / "manifest.yaml"
        path.write_text(body, encoding="utf-8")
        return path

    @staticmethod
    def codes(items):
        return sorted(item.code for item in items)


class TestCheck(BaseCase):
    def test_clean_paper_has_no_problems(self):
        problems, advisories = self.run_check()
        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_marker_in_pdf_text_is_a_problem(self):
        self.reader = lambda path: CLEAN_TEXT + " Figure ?? here"
        problems, _ = self.run_check()
        self.assertIn("unresolved-marker", self.codes(problems))

    def test_unreadable_pdf_is_skipped_not_passed(self):
        self.reader = lambda path: None
        problems, advisories = self.run_check()
        self.assertEqual(problems, [])
        self.assertIn("check-skipped", self.codes(advisories))

    def test_jpeg_bytes_named_png_is_a_problem(self):
        (self.figures / "a.png").write_bytes(JPEG)
        problems, _ = self.run_check()
        self.assertIn("figure-format", self.codes(problems))

    def test_manifest_hash_mismatch_is_a_problem(self):
        (self.figures / "plot.png").write_bytes(PNG)
        self.write_generator()
        manifest = self.write_manifest(MANIFEST.format(hash="sha256:deadbeef"))
        problems, _ = self.run_check(manifest=manifest)
        self.assertIn("figure-hash", self.codes(problems))

    def test_canonical_manifest_is_discovered_without_flag(self):
        (self.figures / "plot.png").write_bytes(JPEG)
        self.write_generator()
        (self.figures / "manifest.yaml").write_text(
            MANIFEST.format(hash="sha256:deadbeef"), encoding="utf-8"
        )
        problems, _ = self.run_check()
        self.assertIn("figure-hash", self.codes(problems))

    def test_cli_manifest_provenance_uses_paper_root(self):
        (self.figures / "plot.png").write_bytes(PNG)
        manifest = self.write_manifest(
            MANIFEST.format(hash=self.write_generator())
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("ccfa.final_check.extract_text", return_value=CLEAN_TEXT):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "final_check.py",
                        "--manuscript",
                        str(self.manuscript),
                        "--pdf",
                        str(self.pdf),
                        "--paper-root",
                        str(self.root),
                        "--manifest",
                        str(manifest),
                    ]
                )
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["problem_count"], 0)

    def test_malformed_manifest_raises_value_error(self):
        manifest = self.write_manifest("name: not-a-list\n")
        with self.assertRaises(ValueError):
            self.run_check(manifest=manifest)

    def test_untagged_number_is_an_advisory(self):
        self.main.write_text(
            "\\begin{abstract}\n"
            "\\end{abstract}\n"
            "\\section{Introduction}\n"
            "Accuracy was 92.5 percent.\n"
            "\\section{Contributions}\n"
            "\\section{Results}\n",
            encoding="utf-8",
        )
        _, advisories = self.run_check()
        self.assertIn("untagged-number", self.codes(advisories))

    def test_protected_untagged_number_is_a_problem(self):
        self.main.write_text(
            "\\begin{abstract}\n"
            "Coding 43 works.\n"
            "\\end{abstract}\n"
            "\\section{Contributions}\n"
            "\\section{Results}\n",
            encoding="utf-8",
        )
        problems, advisories = self.run_check()
        self.assertEqual(self.codes(problems), ["protected-untagged-number"])
        self.assertEqual(advisories, [])

    def test_waiver_is_listed_as_advisory(self):
        self.main.write_text(
            "\\begin{abstract}\n"
            "Coding 43 works.\n"
            "\\end{abstract}\n"
            "\\section{Contributions}\n"
            "\\section{Results}\n",
            encoding="utf-8",
        )
        self.write_policy(
            waivers=[
                {
                    "file": "manuscript/main.tex",
                    "line_text": "Coding 43 works.",
                    "reason": "protocol count",
                    "date": "2026-10-04",
                    "author": "Alice",
                }
            ]
        )
        problems, advisories = self.run_check()
        self.assertEqual(problems, [])
        self.assertEqual(self.codes(advisories), ["waived-number"])
        self.assertIn("protocol count", advisories[0].message)

    def test_missing_policy_is_an_advisory(self):
        self.policy_path.unlink()
        _, advisories = self.run_check()
        self.assertIn("claims-policy-missing", self.codes(advisories))
        message = next(
            item.message
            for item in advisories
            if item.code == "claims-policy-missing"
        )
        self.assertEqual(message, "未配置 claims policy，覆盖率未验证")

    def test_bad_waiver_is_a_problem(self):
        self.write_policy(
            waivers=[
                {
                    "file": "manuscript/main.tex",
                    "line_text": "Coding 43 works.",
                    "reason": "protocol count",
                    "date": "2026-10-04",
                    "author": 7,
                }
            ]
        )
        problems, _ = self.run_check()
        self.assertIn("claims-policy-invalid", self.codes(problems))

    def test_protected_unbound_cli_exits_one(self):
        self.main.write_text(
            "\\begin{abstract}\n"
            "Coding 43 works.\n"
            "\\end{abstract}\n"
            "\\section{Contributions}\n"
            "\\section{Results}\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("ccfa.final_check.extract_text", return_value=CLEAN_TEXT):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "final_check.py",
                        "--manuscript",
                        str(self.manuscript),
                        "--pdf",
                        str(self.pdf),
                        "--paper-root",
                        str(self.root),
                    ]
                )
        self.assertEqual(code, 1, stderr.getvalue())
        self.assertEqual(
            json.loads(stdout.getvalue())["problems"][0]["code"],
            "protected-untagged-number",
        )

    def test_all_protected_sections_matched_has_no_unknown_problem(self):
        problems, _ = self.run_check()

        self.assertEqual(problems, [])

    def test_unknown_protected_section_cli_exits_one(self):
        self.write_policy(protected_sections=["resultz"])
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("ccfa.final_check.extract_text", return_value=CLEAN_TEXT):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "final_check.py",
                        "--manuscript",
                        str(self.manuscript),
                        "--pdf",
                        str(self.pdf),
                        "--paper-root",
                        str(self.root),
                    ]
                )

        self.assertEqual(code, 1, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertIn(
            "claims-policy-unknown-section",
            [problem["code"] for problem in payload["problems"]],
        )
        self.assertIn("resultz", stderr.getvalue())

    def test_nonprotected_unbound_cli_exits_zero(self):
        self.main.write_text(
            "\\begin{abstract}\n"
            "\\end{abstract}\n"
            "\\section{Introduction}\n"
            "Coding 43 works.\n"
            "\\section{Contributions}\n"
            "\\section{Results}\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("ccfa.final_check.extract_text", return_value=CLEAN_TEXT):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "final_check.py",
                        "--manuscript",
                        str(self.manuscript),
                        "--pdf",
                        str(self.pdf),
                        "--paper-root",
                        str(self.root),
                    ]
                )
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["problem_count"], 0)

    def test_missing_policy_cli_still_exits_zero(self):
        self.policy_path.unlink()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("ccfa.final_check.extract_text", return_value=CLEAN_TEXT):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "final_check.py",
                        "--manuscript",
                        str(self.manuscript),
                        "--pdf",
                        str(self.pdf),
                        "--paper-root",
                        str(self.root),
                    ]
                )
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertIn(
            "claims-policy-missing",
            [
                advisory["code"]
                for advisory in json.loads(stdout.getvalue())["advisories"]
            ],
        )

    def test_missing_declaration_is_an_advisory(self):
        self.reader = lambda path: "nothing relevant here"
        problems, advisories = self.run_check()
        self.assertEqual(problems, [])
        self.assertIn("missing-declaration", self.codes(advisories))

    def test_missing_pdf_raises_value_error(self):
        with self.assertRaises(ValueError):
            check(self.manuscript, pdf=self.root / "gone.pdf", reader=self.reader)

    def test_one_bad_figure_can_report_both_codes(self):
        # Decision 4: the two codes answer different questions, so both fire.
        (self.figures / "plot.png").write_bytes(JPEG)
        manifest = self.write_manifest(
            MANIFEST.format(hash=self.write_generator())
        )
        problems, _ = self.run_check(manifest=manifest)
        codes = self.codes(problems)
        self.assertIn("figure-format", codes)
        self.assertIn("figure-manifest-format", codes)

    def test_skipped_check_forces_exit_two(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        patcher = patch("ccfa.final_check.extract_text", return_value=None)
        try:
            patcher.start()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "final_check.py",
                        "--manuscript",
                        str(self.manuscript),
                        "--pdf",
                        str(self.pdf),
                    ]
                )
        finally:
            patcher.stop()
        self.assertEqual(code, 2)
        payload = json.loads(stdout.getvalue())
        self.assertIn(
            "check-skipped",
            [advisory["code"] for advisory in payload["advisories"]],
        )

    def test_pdf_stat_error_exits_two_with_empty_stdout(self):
        real_stat = Path.stat
        stdout = io.StringIO()
        stderr = io.StringIO()

        def failing_stat(path, *args, **kwargs):
            if path.suffix.lower() == ".pdf":
                raise OSError("simulated stat failure")
            return real_stat(path, *args, **kwargs)

        with patch.object(Path, "stat", failing_stat):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "final_check.py",
                        "--manuscript",
                        str(self.manuscript),
                    ]
                )
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")

    def test_traversal_error_exits_two_with_empty_stdout(self):
        real_rglob = Path.rglob
        stdout = io.StringIO()
        stderr = io.StringIO()

        def failing_rglob(path, pattern, *args, **kwargs):
            if Path(path) == self.figures and pattern == "*":
                raise PermissionError("simulated traversal failure")
            return real_rglob(path, pattern, *args, **kwargs)

        patcher = patch.object(Path, "rglob", failing_rglob)
        try:
            patcher.start()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        "final_check.py",
                        "--manuscript",
                        str(self.manuscript),
                    ]
                )
        finally:
            patcher.stop()
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
