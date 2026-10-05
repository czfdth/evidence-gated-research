"""End-to-end evidence-integrity regression on real file trees.

These tests use real temporary directories, real git repositories and the real
tool functions. Only the codex exec runner and the run-log command runner are
injected so the suite stays offline and fast.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
import pymupdf

from ccfa.cross_review import check_review, run_review
from ccfa.final_check import main as final_check_main
from ccfa.run_log import check_runs, git_state, run_command
from newpaper.create import create_project


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed: {completed.stdout}{completed.stderr}"
        )
    return completed.stdout


def _init_repo(path: Path, message: str = "parent commit") -> str:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Evidence Test"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "evidence@test.invalid"],
        cwd=path,
        check=True,
    )
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=path, check=True)
    return _git(path, "rev-parse", "HEAD").strip()


class EvidenceIntegrityEndToEnd(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _create(self, slug: str, papers_root: Path | None = None) -> Path:
        return create_project(
            papers_root=papers_root or self.root / "papers",
            slug=slug,
            venue="NeurIPS",
            year="2027",
            mode="conference",
            title=slug,
        )

    @staticmethod
    def _runner_ok(argv, cwd):
        return 0, "ok\n"

    def _write_claims_policy(self, paper: Path, payload: dict) -> None:
        (paper / "data").mkdir(parents=True, exist_ok=True)
        (paper / "data" / "claims.yaml").write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def _write_minimal_manuscript(self, paper: Path, body: str) -> None:
        """Drop venue instruction files so only the tested body is scanned."""
        main = paper / "manuscript" / "main.tex"
        for other in (paper / "manuscript").rglob("*.tex"):
            if other != main:
                other.unlink()
        main.write_text(body, encoding="utf-8")

    def _run_final_check(self, paper: Path) -> tuple[int, dict, str]:
        pdf_path = paper / "manuscript" / "main.pdf"
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((72, 72), "Limitations.")
        document.save(str(pdf_path))
        document.close()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            stderr
        ):
            code = final_check_main(
                [
                    "final_check.py",
                    "--manuscript",
                    str(paper / "manuscript"),
                    "--pdf",
                    str(pdf_path),
                    "--paper-root",
                    str(paper),
                ]
            )
        return code, json.loads(stdout.getvalue()), stderr.getvalue()

    # --- scenarios -----------------------------------------------------

    def test_derived_paper_is_its_own_repository(self):
        paper = self._create("repo-paper")

        self.assertTrue((paper / ".git").is_dir())
        self.assertTrue((paper / ".gitignore").is_file())
        commit = _git(paper, "rev-parse", "HEAD").strip()
        self.assertTrue(commit)
        tracked = _git(paper, "ls-tree", "-r", "--name-only", "HEAD").splitlines()
        self.assertIn("ccfa.yaml", tracked)
        self.assertIn("memory/ideas.md", tracked)
        state = git_state(paper)
        self.assertEqual(state.git_repo, "self")
        self.assertEqual(state.git_commit, commit)
        self.assertEqual(
            Path(_git(paper, "rev-parse", "--show-toplevel").strip()).resolve(),
            paper.resolve(),
        )

    def test_nested_derived_paper_records_a_self_run_log(self):
        parent = self.root / "template"
        parent_commit = _init_repo(parent)
        paper = self._create("nested-paper", papers_root=parent / "papers")
        paper_commit = _git(paper, "rev-parse", "HEAD").strip()

        _, record = run_command(
            ["python", "-c", "print('hi')"],
            paper / "experiments" / "log",
            paper,
            runner=self._runner_ok,
        )

        self.assertEqual(record["git_repo"], "self")
        self.assertEqual(record["git_commit"], paper_commit)
        self.assertNotEqual(record["git_commit"], parent_commit)

    def test_protected_unbound_number_exits_one(self):
        paper = self._create("unbound-paper")
        self._write_claims_policy(
            paper,
            {
                "version": 1,
                "protected_sections": ["abstract"],
                "waivers": [],
            },
        )
        self._write_minimal_manuscript(
            paper,
            "\\begin{abstract}\nCoding 43 works.\n\\end{abstract}\n",
        )

        code, report, _stderr = self._run_final_check(paper)

        self.assertEqual(code, 1, report)
        self.assertIn(
            "protected-untagged-number",
            [problem["code"] for problem in report["problems"]],
        )

    def test_waiver_hit_is_an_advisory(self):
        paper = self._create("waived-paper")
        self._write_claims_policy(
            paper,
            {
                "version": 1,
                "protected_sections": ["abstract"],
                "waivers": [
                    {
                        "file": "manuscript/main.tex",
                        "line_text": "Coding 43 works.",
                        "reason": "protocol count",
                        "date": "2026-10-04",
                        "author": "Alice",
                    }
                ],
            },
        )
        self._write_minimal_manuscript(
            paper,
            "\\begin{abstract}\nCoding 43 works.\n\\end{abstract}\n",
        )

        code, report, _stderr = self._run_final_check(paper)

        self.assertEqual(code, 0, report)
        self.assertEqual(report["problems"], [])
        self.assertIn(
            "waived-number",
            [advisory["code"] for advisory in report["advisories"]],
        )

    def test_fabricated_cross_review_quote_is_uncited(self):
        paper = self.root / "review-paper"
        (paper / "manuscript").mkdir(parents=True)
        (paper / "main.tex").write_text(
            "The baseline comparison omits the strongest published method "
            "entirely.\n",
            encoding="utf-8",
        )
        (paper / "ccfa.yaml").write_text(
            yaml.safe_dump(
                {
                    "target_venue": {"name": "NeurIPS", "mode": "conference"},
                    "stage": {"current": "internal-review"},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        payload = {
            "verdict": "blocking",
            "blocking": [
                {
                    "title": "invented gap",
                    "evidence": (
                        'main.tex: "This sentence was never written by any '
                        'author of this manuscript."'
                    ),
                }
            ],
            "summary": "blocking",
        }

        def runner(argv, cwd, timeout, prompt):
            output = Path(argv[argv.index("-o") + 1])
            output.write_text(json.dumps(payload), encoding="utf-8")
            return 0, ""

        codex_config = paper / "config.toml"
        codex_config.write_text(
            'model_provider = "deepseek-provider"\n'
            'model = "deepseek-v4-flash"\n'
            '[model_providers.deepseek-provider]\n'
            'base_url = "https://deepseek.example.test/v1"\n',
            encoding="utf-8",
        )
        run_review(
            paper,
            stage="internal-review",
            paths=[Path("main.tex")],
            runner=runner,
            model="deepseek-v4-pro",
            codex_config=codex_config,
            allow_same_family=True,
            override_reason=(
                "test fixture: no second-family provider is configured"
            ),
        )

        codes = [problem.code for problem in check_review(paper)]

        self.assertIn("review-uncited-blocking", codes)

    def test_run_log_foreign_and_none_repositories_are_problems(self):
        parent = self.root / "parent"
        _init_repo(parent)
        nested = parent / "nested"
        nested.mkdir()
        foreign_logs = self.root / "foreign-logs"

        _, foreign = run_command(
            ["true"],
            foreign_logs,
            nested,
            runner=self._runner_ok,
        )

        self.assertEqual(foreign["git_repo"], "foreign")
        self.assertIsNone(foreign["git_commit"])
        self.assertIn(
            "run-log-foreign-repo",
            [problem.code for problem in check_runs(foreign_logs)[0]],
        )

        plain = self.root / "plain"
        plain.mkdir()
        plain_logs = self.root / "plain-logs"

        _, none = run_command(
            ["true"],
            plain_logs,
            plain,
            runner=self._runner_ok,
        )

        self.assertEqual(none["git_repo"], "none")
        self.assertIn(
            "run-log-no-git-repo",
            [problem.code for problem in check_runs(plain_logs)[0]],
        )


if __name__ == "__main__":
    unittest.main()
