import subprocess
import tempfile
import unittest
from pathlib import Path

from ccfa.test_impact import (
    Selection,
    build_run_command,
    collect_changed_paths,
    select_tests,
)


ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class SelectTestsTests(unittest.TestCase):
    def test_ccfa_module_selects_its_matching_test_module(self):
        selection = select_tests(["tools/ccfa/cross_review.py"], suite="tools")

        self.assertIn("tools.tests.test_cross_review", selection.tests)
        self.assertIn("tools.tests.test_automation_e2e", selection.tests)
        self.assertIn("tools.tests.test_evidence_integrity_e2e", selection.tests)
        self.assertIn("tools.tests.test_readiness", selection.tests)
        self.assertFalse(selection.full)

    def test_review_loop_selects_its_focused_tests(self):
        selection = select_tests(
            ["tools/ccfa/review_loop.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_review_loop", selection.tests)
        self.assertFalse(selection.full)

    def test_experiment_loop_selects_readiness_integration_tests(self):
        selection = select_tests(
            ["tools/ccfa/experiment_loop.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_experiment_loop", selection.tests)
        self.assertIn("tools.tests.test_readiness", selection.tests)
        self.assertFalse(selection.full)

    def test_post_submission_selects_readiness_integration_tests(self):
        selection = select_tests(
            ["tools/ccfa/post_submission.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_post_submission", selection.tests)
        self.assertIn("tools.tests.test_readiness", selection.tests)
        self.assertFalse(selection.full)

    def test_rigor_selects_readiness_integration_tests(self):
        selection = select_tests(
            ["tools/ccfa/rigor.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_readiness", selection.tests)
        self.assertIn("tools.tests.test_rigor", selection.tests)
        self.assertFalse(selection.full)

    def test_proof_orchestrator_selects_readiness_integration_tests(self):
        selection = select_tests(
            ["tools/ccfa/proof_orchestrator.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_proof_orchestrator", selection.tests)
        self.assertIn("tools.tests.test_readiness", selection.tests)
        self.assertFalse(selection.full)

    def test_proof_run_selects_its_focused_tests(self):
        selection = select_tests(
            ["tools/ccfa/proof_run.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_proof_run", selection.tests)
        self.assertFalse(selection.full)

    def test_meta_optimize_selects_its_focused_tests(self):
        selection = select_tests(
            ["tools/ccfa/meta_optimize.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_meta_optimize", selection.tests)
        self.assertFalse(selection.full)

    def test_artifact_badge_selects_readiness_integration_tests(self):
        selection = select_tests(
            ["tools/ccfa/artifact_badge.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_artifact_badge", selection.tests)
        self.assertIn("tools.tests.test_readiness", selection.tests)
        self.assertFalse(selection.full)

    def test_research_wiki_selects_its_focused_tests(self):
        selection = select_tests(
            ["tools/ccfa/research_wiki.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_research_wiki", selection.tests)
        self.assertFalse(selection.full)

    def test_research_state_selects_its_focused_tests(self):
        selection = select_tests(
            ["tools/ccfa/research_state.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_research_state", selection.tests)
        self.assertFalse(selection.full)

    def test_ara_compile_selects_its_focused_tests(self):
        selection = select_tests(
            ["tools/ccfa/ara_compile.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_ara_compile", selection.tests)
        self.assertFalse(selection.full)

    def test_run_ledger_selects_its_focused_tests(self):
        selection = select_tests(
            ["tools/ccfa/run_ledger.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_run_ledger", selection.tests)
        self.assertFalse(selection.full)

    def test_governance_map_selects_its_focused_tests(self):
        selection = select_tests(
            ["tools/ccfa/governance_map.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_governance_map", selection.tests)
        self.assertFalse(selection.full)

    def test_artifact_store_selects_its_focused_tests(self):
        selection = select_tests(
            ["tools/ccfa/artifact_store.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_artifact_store", selection.tests)
        self.assertFalse(selection.full)

    def test_resubmit_pipeline_selects_its_focused_tests(self):
        selection = select_tests(
            ["tools/ccfa/resubmit_pipeline.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_resubmit_pipeline", selection.tests)
        self.assertFalse(selection.full)

    def test_talk_pipeline_selects_its_focused_tests(self):
        selection = select_tests(
            ["tools/ccfa/talk_pipeline.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_talk_pipeline", selection.tests)
        self.assertFalse(selection.full)

    def test_passport_and_calibration_select_their_focused_tests(self):
        passport = select_tests(
            ["tools/ccfa/passport_ledger.py"],
            suite="tools",
        )
        calibration = select_tests(
            ["tools/ccfa/citation_calibration.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_passport_ledger", passport.tests)
        self.assertIn(
            "tools.tests.test_citation_calibration",
            calibration.tests,
        )
        self.assertFalse(passport.full)
        self.assertFalse(calibration.full)

    def test_venue_fixtures_select_their_focused_tests(self):
        selection = select_tests(
            ["tools/ccfa/venue_fixtures.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_venue_fixtures", selection.tests)
        self.assertFalse(selection.full)

    def test_session_replay_selects_its_focused_tests(self):
        selection = select_tests(
            ["tools/ccfa/session_replay.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_session_replay", selection.tests)
        self.assertFalse(selection.full)

    def test_dashboard_selects_readiness_integration_tests(self):
        selection = select_tests(
            ["tools/ccfa/dashboard.py"],
            suite="tools",
        )

        self.assertIn("tools.tests.test_dashboard", selection.tests)
        self.assertIn("tools.tests.test_readiness", selection.tests)
        self.assertFalse(selection.full)

    def test_test_module_selects_itself(self):
        selection = select_tests(
            ["tools/tests/test_research_ledgers.py"],
            suite="tools",
        )

        self.assertEqual(selection.tests, ("tools.tests.test_research_ledgers",))
        self.assertFalse(selection.full)

    def test_docs_select_docs_consistency(self):
        selection = select_tests(
            ["README.md", "docs/workflow-guide.md"],
            suite="tools",
        )

        self.assertEqual(selection.tests, ("tools.tests.test_docs_consistency",))
        self.assertFalse(selection.full)

    def test_dot_prefixed_paths_keep_their_prefix(self):
        selection = select_tests(
            [".github/workflows/tests.yml"],
            suite="tools",
        )

        self.assertEqual(selection.tests, ("tools.tests.test_github_workflows",))
        self.assertFalse(selection.full)

    def test_dependency_locks_force_the_full_suite(self):
        # CI installs the lock, so a change to either the direct list or the
        # lock alters the environment for every test in the suite.
        for suite, path in (
            ("tools", "tools/requirements.txt"),
            ("tools", "tools/requirements.lock"),
            ("app", "app/requirements.txt"),
            ("app", "app/requirements.lock"),
        ):
            with self.subTest(suite=suite, path=path):
                selection = select_tests([path], suite=suite)

                self.assertTrue(selection.full, path)

    def test_unknown_path_fails_closed_to_full_suite(self):
        selection = select_tests(["new-component/data.json"], suite="tools")

        self.assertTrue(selection.full)
        self.assertEqual(selection.unknown, ("new-component/data.json",))

    def test_deleted_test_module_fails_closed_to_full_suite(self):
        selection = select_tests(
            ["tools/tests/test_deleted_module.py"],
            suite="tools",
        )

        self.assertTrue(selection.full)
        self.assertEqual(
            selection.unknown,
            ("tools/tests/test_deleted_module.py",),
        )

    def test_test_helper_is_not_imported_as_a_test_module(self):
        selection = select_tests(
            ["tools/tests/helpers.py"],
            suite="tools",
        )

        self.assertTrue(selection.full)
        self.assertEqual(selection.unknown, ("tools/tests/helpers.py",))

    def test_sensitive_core_change_fails_closed_to_full_suite(self):
        selection = select_tests(["tools/ccfa/cli.py"], suite="tools")

        self.assertTrue(selection.full)
        self.assertEqual(selection.tests, ())

    def test_app_changes_are_ignored_by_the_tools_suite(self):
        selection = select_tests(["app/ccfa_gui/window.py"], suite="tools")

        self.assertFalse(selection.full)
        self.assertEqual(selection.tests, ())

    def test_docs_and_ci_changes_are_ignored_by_the_app_suite(self):
        selection = select_tests(
            [
                ".github/workflows/tests.yml",
                "README.md",
                "docs/workflow-guide.md",
                "scripts/test-impact.ps1",
                "tools/ccfa/test_impact.py",
            ],
            suite="app",
        )

        self.assertFalse(selection.full)
        self.assertEqual(selection.tests, ())

    def test_app_module_selects_the_matching_app_tests(self):
        selection = select_tests(
            ["app/ccfa_core/http_tools.py"],
            suite="app",
        )

        self.assertEqual(
            selection.tests,
            (
                "app.tests.test_chat_panel",
                "app.tests.test_http_tools",
            ),
        )
        self.assertFalse(selection.full)

    def test_selection_is_sorted_and_deduplicated(self):
        selection = select_tests(
            [
                "tools/tests/test_cli.py",
                "tools/tests/test_cli.py",
                "tools/ccfa/datavalue.py",
            ],
            suite="tools",
        )

        self.assertEqual(
            selection.tests,
            (
                "tools.tests.test_cli",
                "tools.tests.test_datavalue",
            ),
        )

    def test_no_changes_runs_no_tests(self):
        selection = select_tests([], suite="tools")

        self.assertEqual(selection, Selection("tools", (), (), False, (), "no changes"))


class CollectChangedPathsTests(unittest.TestCase):
    def test_collects_committed_modified_and_untracked_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            _git(repo, "init", "-q")
            _git(repo, "config", "user.name", "Impact Test")
            _git(repo, "config", "user.email", "impact@test.invalid")
            (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
            _git(repo, "add", "tracked.txt")
            _git(repo, "commit", "-q", "-m", "base")
            (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
            (repo / "untracked.txt").write_text("new\n", encoding="utf-8")

            changed = collect_changed_paths(repo, base="HEAD")

            self.assertEqual(
                set(changed),
                {"tracked.txt", "untracked.txt"},
            )


class BuildRunCommandTests(unittest.TestCase):
    def test_tools_full_uses_discovery(self):
        selection = Selection(
            suite="tools",
            changed=("unknown.txt",),
            tests=(),
            full=True,
            unknown=("unknown.txt",),
            reason="unknown paths",
        )

        command, env = build_run_command(ROOT, selection)

        self.assertIn("unittest", command)
        self.assertIn("discover", command)
        self.assertEqual(env["PYTHONPATH"], str(ROOT / "tools"))

    def test_app_selection_uses_the_app_virtualenv(self):
        selection = Selection(
            suite="app",
            changed=("app/ccfa_core/http_tools.py",),
            tests=("app.tests.test_http_tools",),
            full=False,
            unknown=(),
            reason="impacted app tests",
        )

        command, env = build_run_command(ROOT, selection)

        self.assertTrue(
            Path(command[0]).as_posix().endswith("app/.venv/Scripts/python.exe")
        )
        self.assertIn("app.tests.test_http_tools", command)
        self.assertIn(str(ROOT / "app"), env["PYTHONPATH"])
        self.assertIn(str(ROOT / "tools"), env["PYTHONPATH"])
        self.assertEqual(env["QT_QPA_PLATFORM"], "offscreen")


if __name__ == "__main__":
    unittest.main()
