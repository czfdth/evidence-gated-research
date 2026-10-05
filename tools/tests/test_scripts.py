import ast
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
CCFA_DIR = REPO_ROOT / "tools" / "ccfa"

# This is the single explicit CLI inventory. The discovery test below compares
# it with the modules that actually define a top-level main().
CCFA_WRAPPERS = {
    "citation_guard": "citation-guard.ps1",
    "trace_claims": "trace-claims.ps1",
    "latex_check": "latex-check.ps1",
    "final_check": "final-check.ps1",
    "provenance": "provenance.ps1",
    "run_log": "run-log.ps1",
    "run_ledger": "run-ledger.ps1",
    "passport_ledger": "passport-ledger.ps1",
    "citation_calibration": "citation-calibration.ps1",
    "repro_package": "repro-package.ps1",
    "friction_log": "friction-log.ps1",
    "research_version": "research-version.ps1",
    "library": "library.ps1",
    "memory": "memory.ps1",
    "milestones": "milestones.ps1",
    "cross_review": "cross-review.ps1",
    "review_loop": "review-loop.ps1",
    "argument_audit": "argument-audit.ps1",
    "human_coding": "human-coding.ps1",
    "novelty": "novelty.ps1",
    "stats_plan": "statistics.ps1",
    "governance": "governance.ps1",
    "governance_map": "governance-map.ps1",
    "repro_env": "repro-env.ps1",
    "watch": "watch.ps1",
    "queue": "queue.ps1",
    "validate": "validate.ps1",
    "state": "state.ps1",
    "revision_ledger": "revision-ledger.ps1",
    "resubmit_pipeline": "resubmit-pipeline.ps1",
    "talk_pipeline": "talk-pipeline.ps1",
    "venue_fixtures": "venue-fixtures.ps1",
    "session_replay": "session-replay.ps1",
    "doctor": "doctor.ps1",
    "readiness": "readiness.ps1",
    "research_ledgers": "research-ledgers.ps1",
    "test_impact": "test-impact.ps1",
    "change_log": "change-log.ps1",
    "experiment_loop": "experiment-loop.ps1",
    "post_submission": "post-submission.ps1",
    "rigor": "rigor-rubric.ps1",
    "proof_orchestrator": "proof-orchestrator.ps1",
    "proof_run": "proof-run.ps1",
    "meta_optimize": "meta-optimize.ps1",
    "artifact_badge": "artifact-badge.ps1",
    "artifact_store": "artifact-store.ps1",
    "research_wiki": "research-wiki.ps1",
    "research_state": "research-state.ps1",
    "ara_compile": "ara-compile.ps1",
    "ara_extract": "ara-extract.ps1",
    "reference_audit": "reference-audit.ps1",
    "worktree_audit": "worktree-audit.ps1",
    "dashboard": "dashboard.ps1",
    "formal_check": "formal-check.ps1",
    "verifiers": "verifiers.ps1",
    "stages": "stages.ps1",
    "archive_client": "archive.ps1",
    "compute": "compute.ps1",
}
NEWPAPER_WRAPPER = "new-paper.ps1"
NEWPAPER_MODULE = "newpaper.create"

def _modules_with_main():
    modules = {}
    for module_path in sorted(CCFA_DIR.glob("*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "main"
            for node in tree.body
        ):
            modules[module_path.stem] = module_path
    return modules


def _powershell():
    executable = shutil.which("powershell")
    if executable is None:
        raise unittest.SkipTest("powershell is not available")
    return executable


def _run_wrapper(wrapper, *args, cwd=REPO_ROOT):
    return subprocess.run(
        [
            _powershell(),
            "-NoProfile",
            "-File",
            str(SCRIPTS_DIR / wrapper),
            *args,
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def _wrapper_test_name(prefix, wrapper):
    stem = re.sub(r"[^A-Za-z0-9_]", "_", Path(wrapper).stem)
    return f"test_{prefix}_{stem}"


class TestScriptInventory(unittest.TestCase):
    def test_ccfa_wrapper_manifest_matches_modules_with_main(self):
        modules = _modules_with_main()
        self.assertEqual(
            set(modules),
            set(CCFA_WRAPPERS),
            "CCFA_WRAPPERS must explicitly cover every ccfa module with main()",
        )
        for module, wrapper in CCFA_WRAPPERS.items():
            with self.subTest(module=module, wrapper=wrapper):
                self.assertTrue(
                    (SCRIPTS_DIR / wrapper).is_file(),
                    f"{module} has main() but {wrapper} is missing",
                )

    def test_newpaper_wrapper_matches_create_entrypoint(self):
        create_path = REPO_ROOT / "tools" / "newpaper" / "create.py"
        tree = ast.parse(create_path.read_text(encoding="utf-8"))
        self.assertTrue(
            any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "main"
                for node in tree.body
            )
        )
        self.assertTrue((SCRIPTS_DIR / NEWPAPER_WRAPPER).is_file())

    def test_every_wrapper_has_the_required_powershell_contract(self):
        mapping = dict(CCFA_WRAPPERS)
        mapping[NEWPAPER_MODULE] = NEWPAPER_WRAPPER
        for module, wrapper in mapping.items():
            with self.subTest(module=module, wrapper=wrapper):
                text = (SCRIPTS_DIR / wrapper).read_text(encoding="utf-8")
                invoked_module = (
                    NEWPAPER_MODULE if module == NEWPAPER_MODULE else f"ccfa.{module}"
                )
                required = [
                    "$ErrorActionPreference='Stop'",
                    '$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path',
                    '$env:PYTHONPATH="$root/tools"',
                    f'& "$root/tools/.venv/Scripts/python.exe" -m {invoked_module} @args',
                    "exit $LASTEXITCODE",
                ]
                for line in required:
                    self.assertIn(line, text)


def _make_help_test(wrapper):
    def test(self):
        result = _run_wrapper(wrapper, "--help")
        output = result.stdout + result.stderr
        self.assertEqual(
            result.returncode,
            0,
            f"{wrapper} --help output:\n{output}",
        )
        self.assertIn("usage", result.stdout.lower())

    return test


def _make_nonzero_test(wrapper):
    def test(self):
        result = _run_wrapper(wrapper, "--definitely-invalid")
        self.assertNotEqual(
            result.returncode,
            0,
            f"{wrapper} swallowed a nonzero exit code:\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )

    return test


for _wrapper in [*CCFA_WRAPPERS.values(), NEWPAPER_WRAPPER]:
    setattr(
        TestScriptInventory,
        _wrapper_test_name("help", _wrapper),
        _make_help_test(_wrapper),
    )
    setattr(
        TestScriptInventory,
        _wrapper_test_name("nonzero", _wrapper),
        _make_nonzero_test(_wrapper),
    )


class TestResearchVersionWrapperIntegration(unittest.TestCase):
    def test_lists_tags_in_a_real_git_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            (repo / "main.tex").write_text("draft\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "main.tex"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Script Test",
                    "-c",
                    "user.email=script@test.invalid",
                    "commit",
                    "-q",
                    "-m",
                    "draft",
                ],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "tag", "paper-v1"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )

            result = _run_wrapper(
                "research-version.ps1",
                "--repo",
                str(repo),
                "list",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("paper-v1", result.stdout.splitlines())


if __name__ == "__main__":
    unittest.main()
