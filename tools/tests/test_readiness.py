import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest import mock

from ccfa import readiness
from ccfa.cli import Problem
from ccfa.readiness import build_report, main, render_markdown


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paper_root = Path(self.tmp.name)
        self._write_state()

    def _write_state(self, extra=""):
        self.paper_root.joinpath("ccfa.yaml").write_text(
            "version: '0.4.0'\n"
            "project:\n"
            "  title: Demo\n"
            "  short_name: demo\n"
            "  root: .\n"
            "target_venue:\n"
            "  name: NeurIPS\n"
            "  year: 2026\n"
            "  mode: conference\n"
            "  deadline: null\n"
            "stage:\n"
            "  current: idea\n"
            "  gate: scope_defined\n"
            "  updated_at: '2026-10-04'\n"
            "  history: []\n"
            "artifacts:\n"
            "  manuscript: manuscript/main.tex\n"
            "  bibliography: manuscript/references.bib\n"
            "  figures: figures/\n"
            "  tables: tables/\n"
            "  experiments: experiments/\n"
            "  reviews: reviews/\n"
            "  submission: submission/\n"
            "claims: []\n"
            "experiments: []\n"
            "reviews: []\n"
            "revision_ledger:\n"
            "  path: reviews/revision-ledger.md\n"
            "  status: not_started\n"
            "submission_checks:\n"
            "  path: submission/checks.md\n"
            "  status: not_started\n"
            f"{extra}",
            encoding="utf-8",
        )

    def _set_deadline(self, value: str) -> None:
        """Give the fixture a real target date so the countdown has a subject."""

        path = self.paper_root / "ccfa.yaml"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace("  deadline: null", f"  deadline: {value}"),
            encoding="utf-8",
        )

    def _git_init(self):
        """Make the paper root a committed worktree with no remote yet."""

        for args in (
            ["git", "init"],
            ["git", "config", "user.email", "test@example.com"],
            ["git", "config", "user.name", "Test"],
            ["git", "add", "ccfa.yaml"],
            ["git", "commit", "-m", "init"],
        ):
            subprocess.run(
                args,
                cwd=self.paper_root,
                check=True,
                capture_output=True,
            )

    def _touch_ledgers(self, names):
        paths = {
            "proof": "data/proof-audit.yaml",
            "citation-support": "data/citation-support.yaml",
            "figure-support": "data/figure-support.yaml",
            "governance": "data/governance.yaml",
            "novelty": "data/novelty-audit.yaml",
            "statistics": "data/statistics-plan.yaml",
            "repro-environment": "data/repro-environment.yaml",
            "human-coding": "data/human-coding-report.json",
        }
        for name in names:
            path = self.paper_root / paths[name]
            path.parent.mkdir(parents=True, exist_ok=True)
            if name == "novelty":
                path.write_text(
                    "version: 1\n"
                    "search:\n"
                    "  databases: [arXiv, OpenAlex]\n"
                    "  queries: [readiness test]\n"
                    "  searched_at: '2026-10-04'\n"
                    "  cutoff: '2026-10-04'\n"
                    "claims: [claim-1]\n"
                    "neighbors:\n"
                    "  - id: a\n"
                    "    title: A\n"
                    "    venue: Test\n"
                    "    overlap: Overlap A\n"
                    "    difference: Difference A\n"
                    "    claim_ids: [claim-1]\n"
                    "  - id: b\n"
                    "    title: B\n"
                    "    venue: Test\n"
                    "    overlap: Overlap B\n"
                    "    difference: Difference B\n"
                    "    claim_ids: [claim-1]\n"
                    "  - id: c\n"
                    "    title: C\n"
                    "    venue: Test\n"
                    "    overlap: Overlap C\n"
                    "    difference: Difference C\n"
                    "    claim_ids: [claim-1]\n",
                    encoding="utf-8",
                )
                manuscript = self.paper_root / "manuscript"
                manuscript.mkdir(exist_ok=True)
                (manuscript / "references.bib").write_text(
                    "@misc{a, title={A}}\n"
                    "@misc{b, title={B}}\n"
                    "@misc{c, title={C}}\n",
                    encoding="utf-8",
                )
            else:
                path.write_text("{}\n", encoding="utf-8")

    def test_standard_profile_reports_missing_required_ledgers_and_no_science_claim(self):
        report = build_report(self.paper_root)

        self.assertFalse(report["ready"])
        self.assertEqual(report["profile"], "standard")
        self.assertEqual(report["dimensions"]["schema-valid"], "pass")
        self.assertEqual(report["dimensions"]["gate-verified"], "problem")
        self.assertEqual(report["dimensions"]["evidence-present"], "problem")
        self.assertEqual(
            report["dimensions"]["scientifically-accepted"],
            "not-claimed",
        )
        self.assertIn("citation-support", report["evidence"]["missing_required"])
        self.assertIn("claim-registry", report["evidence"]["missing_required"])
        self.assertIn("experiment-loop", report["evidence"]["missing_required"])
        self.assertIn("rigor-rubric", report["evidence"]["missing_required"])
        self.assertIn("proof-orchestrator", report["evidence"]["missing_required"])
        research = next(
            item
            for item in report["gate_results"]
            if item["name"] == "research-ledgers"
        )
        self.assertIn(
            "research-ledger-missing",
            [problem["code"] for problem in research["problems"]],
        )

    def test_lockfile_drift_makes_gate_verified_fail(self):
        self._touch_ledgers(
            [
                "citation-support",
                "figure-support",
                "novelty",
                "statistics",
                "repro-environment",
            ]
        )
        (self.paper_root / "requirements.txt").write_text(
            "# stdlib only\n",
            encoding="utf-8",
        )
        (self.paper_root / "requirements.lock").write_text(
            "python==3.12.14\n",
            encoding="utf-8",
        )
        (self.paper_root / "reviews").mkdir(exist_ok=True)
        (self.paper_root / "reviews" / "python-version.txt").write_text(
            "Python 3.12.14\n",
            encoding="utf-8",
        )
        (self.paper_root / "data" / "repro-environment.yaml").write_text(
            "version: 1\n"
            "python: '3.12.14'\n"
            "package_manager: pip\n"
            "requirements: requirements.txt\n"
            "lockfile: requirements.lock\n"
            "lockfile_sha256: sha256:"
            + "0" * 64
            + "\n"
            "system_tools:\n"
            "  - name: python\n"
            "    version: '3.12.14'\n"
            "    command: python --version\n"
            "    evidence: reviews/python-version.txt\n",
            encoding="utf-8",
        )

        report = build_report(self.paper_root, profile="standard")

        self.assertFalse(report["ready"])
        self.assertEqual(report["dimensions"]["gate-verified"], "problem")
        repro = next(
            item
            for item in report["gate_results"]
            if item["name"] == "repro-environment"
        )
        self.assertEqual(repro["status"], "problem")
        self.assertIn(
            "repro-env-lockfile-drift",
            [problem["code"] for problem in repro["problems"]],
        )

    def test_standard_pending_argument_audit_is_not_independent_review(self):
        self._touch_ledgers(
            [
                "citation-support",
                "figure-support",
                "novelty",
                "statistics",
                "repro-environment",
            ]
        )
        with mock.patch(
            "ccfa.readiness.argument_audit.check",
            return_value=([
                Problem(
                    "proof-review-not-verified",
                    "proof-audit.yaml",
                    None,
                    "pending",
                )
            ], []),
        ):
            report = build_report(self.paper_root, profile="standard")

        self.assertEqual(
            report["dimensions"]["independently-reviewed"],
            "pending-human-review",
        )
        self.assertEqual(report["dimensions"]["gate-verified"], "problem")

    def test_repro_bundle_verification_is_part_of_gate_verified(self):
        self._touch_ledgers(
            [
                "citation-support",
                "figure-support",
                "novelty",
                "statistics",
                "repro-environment",
            ]
        )
        bundle = self.paper_root / "submission" / "repro"
        bundle.mkdir(parents=True)
        (bundle / "MANIFEST.json").write_text(
            '{"version": 1}\n',
            encoding="utf-8",
        )

        report = build_report(self.paper_root, profile="standard")

        repro_bundle = next(
            item
            for item in report["gate_results"]
            if item["name"] == "repro-package"
        )
        self.assertEqual(repro_bundle["status"], "problem")
        self.assertEqual(report["dimensions"]["gate-verified"], "problem")

    def test_high_assurance_requires_all_ledgers(self):
        self._touch_ledgers(["novelty"])

        report = build_report(self.paper_root, profile="high-assurance")

        self.assertIn("proof", report["evidence"]["missing_required"])
        self.assertIn("artifact-badge", report["evidence"]["missing_required"])
        self.assertEqual(
            report["dimensions"]["independently-reviewed"],
            "missing-human-evidence",
        )

    def test_high_assurance_rejects_pending_human_ledgers(self):
        self._touch_ledgers(
            [
                "proof",
                "citation-support",
                "figure-support",
                "governance",
                "novelty",
                "statistics",
                "repro-environment",
            ]
        )
        report_path = self.paper_root / "data" / "human-coding-report.json"
        report_path.write_text(
            '{"version": 1, "status": "pending-human-dual-coding"}\n',
            encoding="utf-8",
        )
        (self.paper_root / "data" / "proof-audit.yaml").write_text(
            "version: 1\nstatus: pending-human-review\nreviews: []\n",
            encoding="utf-8",
        )
        (self.paper_root / "data" / "citation-support.yaml").write_text(
            "version: 1\nstatus: pending-human-review\nsupports: []\n",
            encoding="utf-8",
        )
        (self.paper_root / "data" / "figure-support.yaml").write_text(
            "version: 1\nstatus: pending-human-review\nfigures: []\n",
            encoding="utf-8",
        )

        report = build_report(self.paper_root, profile="high-assurance")

        self.assertFalse(report["ready"])
        self.assertEqual(
            report["dimensions"]["independently-reviewed"],
            "pending-human-review",
        )
        self.assertIn("required human review is incomplete", report["blocking"])

    def test_pending_human_ledgers_expand_into_answerable_checkpoints(self):
        self._touch_ledgers(
            [
                "proof",
                "citation-support",
                "figure-support",
                "governance",
                "novelty",
                "statistics",
                "repro-environment",
            ]
        )
        (self.paper_root / "data" / "proof-audit.yaml").write_text(
            "version: 1\nstatus: pending-human-review\nreviews: []\n",
            encoding="utf-8",
        )
        (self.paper_root / "data" / "human-coding-report.json").write_text(
            '{"version": 1, "status": "pending-human-dual-coding"}\n',
            encoding="utf-8",
        )

        report = build_report(self.paper_root, profile="high-assurance")

        human = report["human_review"]
        self.assertEqual(human["status"], "pending-human-review")
        self.assertEqual(
            sorted(human["pending"]),
            ["citation-support", "figure-support", "human-coding", "proof"],
        )
        by_id = {item["id"]: item for item in human["checkpoints"]}
        self.assertEqual(sorted(by_id), sorted(human["pending"]))
        for key, item in by_id.items():
            with self.subTest(checkpoint=key):
                self.assertEqual(item["status"], "pending")
                self.assertTrue(item["question"].strip())
                self.assertTrue(item["answer_with"].strip())
                self.assertTrue(str(item["ledger"]).startswith("data/"))
        self.assertEqual(by_id["proof"]["type"], "approve")
        self.assertEqual(by_id["proof"]["stage"], "internal-review")
        self.assertEqual(by_id["proof"]["ledger"], "data/proof-audit.yaml")
        self.assertEqual(by_id["human-coding"]["type"], "feedback")

        rendered = render_markdown(report)
        self.assertIn("## Human Checkpoints", rendered)
        self.assertIn(by_id["proof"]["question"], rendered)
        self.assertIn("data/proof-audit.yaml", rendered)

    def test_attested_human_review_has_no_checkpoints(self):
        self._touch_ledgers(
            [
                "proof",
                "citation-support",
                "figure-support",
                "governance",
                "novelty",
                "statistics",
                "repro-environment",
            ]
        )
        for name, status in (
            ("proof-audit.yaml", "human-attested"),
            ("citation-support.yaml", "human-attested"),
            ("figure-support.yaml", "human-attested"),
        ):
            (self.paper_root / "data" / name).write_text(
                f"version: 1\nstatus: {status}\n",
                encoding="utf-8",
            )
        (self.paper_root / "data" / "human-coding-report.json").write_text(
            '{"version": 1, "status": "human-attested"}\n',
            encoding="utf-8",
        )

        report = build_report(self.paper_root, profile="high-assurance")

        self.assertEqual(report["human_review"]["status"], "human-attested")
        self.assertEqual(report["human_review"]["checkpoints"], [])
        rendered = render_markdown(report)
        self.assertIn("## Human Checkpoints", rendered)
        self.assertIn("- none", rendered)

    def test_minimal_can_be_ready_without_scientific_acceptance(self):
        self._touch_ledgers(["novelty"])

        report = build_report(self.paper_root, profile="minimal")

        self.assertTrue(report["ready"])
        self.assertEqual(
            report["dimensions"]["scientifically-accepted"],
            "not-claimed",
        )

    def test_profile_can_come_from_ccfa_yaml(self):
        self._write_state("workflow:\n  profile: high-assurance\n")

        report = build_report(self.paper_root)

        self.assertEqual(report["profile"], "high-assurance")

    def test_assurance_submission_raises_the_audit_chain_without_more_effort(self):
        self._touch_ledgers(["novelty"])
        self._write_state(
            "workflow:\n  profile: minimal\n  assurance: submission\n"
        )

        report = build_report(self.paper_root)

        self.assertEqual(report["profile"], "minimal")
        self.assertEqual(report["assurance"], "submission")
        self.assertEqual(report["audit_profile"], "high-assurance")
        self.assertEqual(report["human_review"]["status"], "pending-human-review")
        self.assertIn("proof", report["evidence"]["missing_required"])
        self.assertEqual(
            report["dimensions"]["independently-reviewed"],
            "missing-human-evidence",
        )
        self.assertFalse(report["ready"])

    def test_assurance_draft_downgrades_the_audit_chain_only(self):
        self._touch_ledgers(["novelty"])
        self._write_state(
            "workflow:\n  profile: high-assurance\n  assurance: draft\n"
        )

        report = build_report(self.paper_root)

        self.assertEqual(report["profile"], "high-assurance")
        self.assertEqual(report["assurance"], "draft")
        self.assertEqual(report["audit_profile"], "standard")
        self.assertEqual(report["human_review"]["status"], "not-required")

    def test_standard_gate_failures_still_expose_human_checkpoints(self):
        human = readiness._human_review_status(
            self.paper_root,
            "standard",
            [
                {
                    "problems": [
                        {
                            "code": "review-contradiction: proof-review-not-verified",
                        }
                    ]
                }
            ],
        )

        self.assertEqual(human["status"], "pending-human-review")
        self.assertEqual(human["pending"], ["proof"])
        self.assertEqual(human["checkpoints"][0]["id"], "proof")

    def test_cross_review_failure_has_an_actionable_checkpoint(self):
        human = readiness._human_review_status(
            self.paper_root,
            "standard",
            [
                {
                    "name": "cross-review",
                    "problems": [
                        {"code": "review-provider-config-drift"},
                        {"code": "review-blocking"},
                    ]
                }
            ],
        )

        self.assertEqual(human["pending"], ["cross-review"])
        self.assertEqual(human["checkpoints"][0]["id"], "cross-review")
        self.assertIn("跨族", human["checkpoints"][0]["question"])

    def test_claim_candidates_have_a_promotion_checkpoint(self):
        (self.paper_root / "data").mkdir(exist_ok=True)
        (self.paper_root / "data" / "claim-candidates.yaml").write_text(
            "version: 1\n"
            "claims:\n"
            "  - id: CC-1\n"
            "    statement: Candidate claim\n"
            "    status: proposed\n",
            encoding="utf-8",
        )

        report = build_report(self.paper_root, profile="minimal")

        self.assertEqual(report["human_review"]["status"], "pending-human-review")
        checkpoint = report["human_review"]["checkpoints"][0]
        self.assertEqual(checkpoint["id"], "claim-candidates")
        self.assertEqual(checkpoint["ledger"], "data/claim-candidates.yaml")

    def test_optimization_proposals_have_a_review_checkpoint(self):
        (self.paper_root / "data").mkdir(exist_ok=True)
        (self.paper_root / "data" / "experiment-optimization-proposals.yaml").write_text(
            "version: 1\n"
            "proposals:\n"
            "  - optimization_id: TEST\n"
            "    status: proposed\n",
            encoding="utf-8",
        )

        report = build_report(self.paper_root, profile="minimal")

        self.assertEqual(report["human_review"]["status"], "pending-human-review")
        checkpoint = report["human_review"]["checkpoints"][0]
        self.assertEqual(checkpoint["id"], "optimization-proposals")
        self.assertEqual(
            checkpoint["ledger"],
            "data/experiment-optimization-proposals.yaml",
        )

    def test_generated_research_plans_have_a_review_checkpoint(self):
        (self.paper_root / "data").mkdir(exist_ok=True)
        (self.paper_root / "data" / "research-plan-candidates.yaml").write_text(
            "version: 1\nplans:\n  - id: RP-001\n    status: proposed\n",
            encoding="utf-8",
        )

        report = build_report(self.paper_root, profile="minimal")

        checkpoint = report["human_review"]["checkpoints"][0]
        self.assertEqual(checkpoint["id"], "research-plans")
        self.assertEqual(checkpoint["ledger"], "data/research-plan-candidates.yaml")

    def test_code_mutation_proposals_have_a_review_checkpoint(self):
        (self.paper_root / "data").mkdir(exist_ok=True)
        (self.paper_root / "data" / "code-mutation-proposals.yaml").write_text(
            "version: 1\nproposals:\n  - id: CM-1\n    status: proposed\n",
            encoding="utf-8",
        )

        report = build_report(self.paper_root, profile="minimal")

        checkpoint = report["human_review"]["checkpoints"][0]
        self.assertEqual(checkpoint["id"], "code-mutations")
        self.assertEqual(checkpoint["ledger"], "data/code-mutation-proposals.yaml")

    def test_high_assurance_defaults_to_submission_assurance(self):
        self._touch_ledgers(["novelty"])
        self._write_state("workflow:\n  profile: high-assurance\n")

        report = build_report(self.paper_root)

        self.assertEqual(report["assurance"], "submission")
        self.assertEqual(report["audit_profile"], "high-assurance")

    def test_unknown_assurance_is_rejected(self):
        self._write_state("workflow:\n  assurance: epic\n")

        with self.assertRaises(ValueError):
            build_report(self.paper_root)

    def test_gate_verdicts_mark_missing_inputs_as_blocked(self):
        report = build_report(self.paper_root)

        self.assertEqual(report["verdicts"]["argument-audit"], "blocked")
        self.assertIn("blocked", render_markdown(report))

    def test_a_gate_that_ran_and_rejected_is_a_fail_verdict(self):
        self._touch_ledgers(["novelty"])
        (self.paper_root / "data" / "novelty-audit.yaml").write_text(
            "version: 1\n"
            "search:\n"
            "  databases: [arXiv]\n"
            "  queries: [q]\n"
            "  searched_at: '2026-10-04'\n"
            "  cutoff: '2026-10-04'\n"
            "claims: [claim-1]\n"
            "neighbors: []\n",
            encoding="utf-8",
        )

        report = build_report(self.paper_root, profile="minimal")

        self.assertEqual(report["verdicts"]["novelty"], "fail")

    def test_checkpoints_only_returns_the_human_queue_without_running_gates(self):
        self._write_state("workflow:\n  profile: high-assurance\n")
        data = self.paper_root / "data"
        data.mkdir()
        (data / "proof-audit.yaml").write_text(
            "version: 1\nstatus: pending-human-review\nreviews: []\n",
            encoding="utf-8",
        )
        stream = StringIO()

        with redirect_stdout(stream):
            code = main(
                [
                    "readiness",
                    "--paper-root",
                    str(self.paper_root),
                    "--checkpoints-only",
                ]
            )

        payload = json.loads(stream.getvalue())
        self.assertEqual(code, 0)
        self.assertNotIn("gate_results", payload)
        self.assertEqual(payload["audit_profile"], "high-assurance")
        self.assertEqual(payload["human_review"]["status"], "pending-human-review")
        by_id = {item["id"]: item for item in payload["human_review"]["checkpoints"]}
        self.assertIn("proof", by_id)
        self.assertTrue(by_id["proof"]["question"])
        self.assertEqual(by_id["proof"]["ledger"], "data/proof-audit.yaml")

    def test_report_counts_down_to_the_submission_deadline(self):
        self._set_deadline("'2026-10-15'")

        report = build_report(
            self.paper_root,
            profile="minimal",
            today=date(2026, 10, 6),
        )

        self.assertEqual(report["deadline"]["mode"], "countdown")
        self.assertEqual(report["deadline"]["deadline"], "2026-10-15")
        self.assertEqual(report["deadline"]["days_left"], 9)
        self.assertFalse(report["deadline"]["overdue"])

    def test_an_overdue_deadline_counts_negative_days(self):
        self._set_deadline("'2026-09-30'")

        report = build_report(
            self.paper_root,
            profile="minimal",
            today=date(2026, 10, 6),
        )

        self.assertEqual(report["deadline"]["days_left"], -6)
        self.assertTrue(report["deadline"]["overdue"])

    def test_a_paper_without_a_deadline_has_no_countdown(self):
        report = build_report(
            self.paper_root,
            profile="minimal",
            today=date(2026, 10, 6),
        )

        self.assertIsNone(report["deadline"]["deadline"])
        self.assertIsNone(report["deadline"]["days_left"])
        self.assertFalse(report["deadline"]["overdue"])

    def test_markdown_leads_with_the_countdown_and_the_blocker_count(self):
        self._set_deadline("'2026-10-15'")
        report = build_report(
            self.paper_root,
            profile="minimal",
            today=date(2026, 10, 6),
        )

        markdown = render_markdown(report)

        self.assertIn("## Summary", markdown)
        self.assertIn("还有 9 天（2026-10-15）", markdown)
        self.assertIn(f"阻塞: {len(report['blocking'])} 条", markdown)
        self.assertIn("## Deadline", markdown)
        self.assertIn("## Blocking", markdown)

    def test_collaboration_only_agrees_with_the_full_report(self):
        self._git_init()
        stream = StringIO()

        with redirect_stdout(stream):
            code = main(
                [
                    "readiness",
                    "--paper-root",
                    str(self.paper_root),
                    "--profile",
                    "standard",
                    "--collaboration-only",
                ]
            )

        payload = json.loads(stream.getvalue())
        self.assertEqual(code, 0)
        self.assertNotIn("gate_results", payload)
        self.assertTrue(payload["git"]["present"])
        self.assertFalse(payload["git"]["dirty"])
        self.assertEqual(payload["git"]["remotes"], [])
        self.assertFalse(payload["collaboration_ready"])
        self.assertIn("paper git remote is missing", payload["blocking"])
        self.assertIn("GitHub Actions workflows are missing", payload["blocking"])

        # The slim report must not invent its own definition of "blocked":
        # every collaboration reason it lists is one the full report lists too.
        report = build_report(self.paper_root, profile="standard")
        self.assertEqual(
            payload["blocking"],
            [
                item
                for item in report["blocking"]
                if item in readiness.COLLABORATION_BLOCKERS
            ],
        )

        # An uncommitted file is the other half of the same contract.
        (self.paper_root / "notes.md").write_text("scratch\n", encoding="utf-8")
        stream = StringIO()
        with redirect_stdout(stream):
            main(
                [
                    "readiness",
                    "--paper-root",
                    str(self.paper_root),
                    "--profile",
                    "standard",
                    "--collaboration-only",
                ]
            )
        dirty = json.loads(stream.getvalue())
        self.assertTrue(dirty["git"]["dirty"])
        self.assertIn("paper git worktree is dirty", dirty["blocking"])

    def test_git_remote_and_workflow_status_are_reported(self):
        subprocess.run(["git", "init"], cwd=self.paper_root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.paper_root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.paper_root, check=True)
        subprocess.run(["git", "add", "ccfa.yaml"], cwd=self.paper_root, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.paper_root, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", "https://example.test/repo.git"], cwd=self.paper_root, check=True)
        (self.paper_root / ".github" / "workflows").mkdir(parents=True)

        report = build_report(self.paper_root, profile="minimal")

        self.assertTrue(report["git"]["present"])
        self.assertFalse(report["git"]["dirty"])
        self.assertEqual(report["git"]["remotes"], ["origin"])
        self.assertTrue(report["git"]["workflows_present"])

    def test_generated_readiness_reports_do_not_mark_tree_dirty(self):
        subprocess.run(["git", "init"], cwd=self.paper_root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.paper_root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.paper_root, check=True)
        reviews = self.paper_root / "reviews"
        reviews.mkdir()
        (reviews / ".gitkeep").write_text("", encoding="utf-8")
        subprocess.run(["git", "add", "ccfa.yaml", "reviews/.gitkeep"], cwd=self.paper_root, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.paper_root, check=True, capture_output=True)
        (reviews / "readiness.md").write_text("# report\n", encoding="utf-8")
        (reviews / "readiness.json").write_text("{}\n", encoding="utf-8")

        report = build_report(self.paper_root, profile="minimal")

        self.assertFalse(report["git"]["dirty"])

    def test_standard_requires_git_remote_and_workflows(self):
        self._touch_ledgers(
            [
                "citation-support",
                "figure-support",
                "novelty",
                "statistics",
                "repro-environment",
            ]
        )
        subprocess.run(["git", "init"], cwd=self.paper_root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.paper_root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.paper_root, check=True)
        subprocess.run(["git", "add", "."], cwd=self.paper_root, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.paper_root, check=True, capture_output=True)

        report = build_report(self.paper_root, profile="standard")

        self.assertFalse(report["ready"])
        self.assertEqual(report["dimensions"]["collaboration-ready"], "problem")
        self.assertIn("paper git remote is missing", report["blocking"])
        self.assertIn("GitHub Actions workflows are missing", report["blocking"])

    def test_render_markdown_names_scientific_boundary(self):
        report = build_report(self.paper_root, profile="minimal")
        markdown = render_markdown(report)

        self.assertIn("Scientific Boundary", markdown)
        self.assertIn("does not certify", markdown)

    def test_main_can_write_markdown_report(self):
        with redirect_stdout(StringIO()):
            code = main([
                "readiness",
                "--paper-root",
                str(self.paper_root),
                "--profile",
                "minimal",
                "--out",
                "reviews/readiness.md",
            ])

        self.assertEqual(code, 1)
        self.assertTrue((self.paper_root / "reviews" / "readiness.md").is_file())


class GateDrillTests(ReadinessTests):
    def _write_drills(self, text: str) -> None:
        path = self.paper_root / "data" / "gate-failure-drills.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _gate_drills(self, report: dict) -> dict:
        return next(
            result
            for result in report["gate_results"]
            if result["name"] == "gate-drills"
        )

    def test_gates_without_a_drill_are_marked_unproven(self):
        report = build_report(self.paper_root, profile="minimal")

        self.assertIn("schema-valid", report["unproven_guards"])
        drills = self._gate_drills(report)
        self.assertEqual(drills["status"], "pass")
        self.assertTrue(drills["advisories"])
        self.assertTrue(
            all(advisory["code"] == "unproven-guard" for advisory in drills["advisories"])
        )
        # Unproven guards are visible but never block by themselves.
        self.assertFalse(report["blocking"] and "gate-drills" in report["blocking"])

    def test_a_valid_drill_record_clears_the_gate(self):
        evidence = self.paper_root / "evidence"
        evidence.mkdir()
        (evidence / "schema.json").write_text(
            '{"triggered": true}',
            encoding="utf-8",
        )
        self._write_drills(
            "version: 1\n"
            "drills:\n"
            "  - gate: schema-valid\n"
            "    method: 把 ccfa.yaml 的 version 改成非法值\n"
            "    triggered: true\n"
            "    evidence: evidence/schema.json\n"
        )

        report = build_report(self.paper_root, profile="minimal")

        self.assertNotIn("schema-valid", report["unproven_guards"])
        self.assertEqual(self._gate_drills(report)["status"], "pass")

    def test_drill_without_existing_evidence_blocks(self):
        self._write_drills(
            "version: 1\n"
            "drills:\n"
            "  - gate: schema-valid\n"
            "    method: 破坏 ccfa.yaml\n"
            "    triggered: true\n"
            "    evidence: evidence/missing.json\n"
        )

        report = build_report(self.paper_root, profile="minimal")

        drills = self._gate_drills(report)
        self.assertEqual(drills["status"], "problem")
        self.assertEqual(
            drills["problems"][0]["code"],
            "gate-drill-evidence-missing",
        )
        self.assertFalse(report["ready"])

    def test_drill_that_never_triggered_blocks(self):
        self._write_drills(
            "version: 1\n"
            "drills:\n"
            "  - gate: schema-valid\n"
            "    method: 没有真的破坏任何输入\n"
            "    triggered: false\n"
            "    evidence: evidence/anything.json\n"
        )

        report = build_report(self.paper_root, profile="minimal")

        drills = self._gate_drills(report)
        self.assertEqual(drills["status"], "problem")
        self.assertEqual(
            drills["problems"][0]["code"],
            "gate-drill-not-triggered",
        )


    def test_evidence_that_did_not_trigger_blocks(self):
        evidence = self.paper_root / "evidence"
        evidence.mkdir()
        (evidence / "drill.json").write_text(
            '{"triggered": false}',
            encoding="utf-8",
        )
        self._write_drills(
            "version: 1\n"
            "drills:\n"
            "  - gate: schema-valid\n"
            "    method: 假装演练过，但证据显示没触发\n"
            "    triggered: true\n"
            "    evidence: evidence/drill.json\n"
        )

        report = build_report(self.paper_root, profile="minimal")

        drills = self._gate_drills(report)
        self.assertEqual(drills["status"], "problem")
        self.assertEqual(
            drills["problems"][0]["code"],
            "gate-drill-evidence-not-triggered",
        )


    def _set_stage(self, current: str, gate: str) -> None:
        path = self.paper_root / "ccfa.yaml"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace("  current: idea", f"  current: {current}").replace(
                "  gate: scope_defined",
                f"  gate: {gate}",
            ),
            encoding="utf-8",
        )

    def test_shared_stage_does_not_invent_tail_gates(self):
        report = build_report(self.paper_root, profile="standard")

        names = {result["name"] for result in report["gate_results"]}
        self.assertNotIn("post-submission", names)
        self.assertNotIn("talk-pipeline", names)

    def test_conference_tail_stage_requires_the_post_submission_ledger(self):
        self._set_stage("rebuttal", "rebuttal_submitted")

        report = build_report(self.paper_root, profile="standard")

        names = {result["name"] for result in report["gate_results"]}
        self.assertIn("post-submission", names)
        self.assertTrue(
            any(
                "post-submission gate failed" in reason
                for reason in report["blocking"]
            ),
            report["blocking"],
        )

    def test_tail_requirements_are_stage_driven(self):
        from ccfa.readiness import _tail_requirements

        self.assertEqual(_tail_requirements({"current": "internal-review"}), {})
        self.assertEqual(
            _tail_requirements({"current": "rebuttal"}),
            {"post-submission": True},
        )
        self.assertEqual(
            _tail_requirements({"current": "resubmitted"}),
            {"post-submission": True, "resubmit-pipeline": True},
        )
        self.assertEqual(
            _tail_requirements({"current": "camera-ready"}),
            {"post-submission": True, "talk-pipeline": True},
        )


    def test_tail_stage_blocks_until_its_section_is_complete(self):
        self._set_stage("rebuttal", "rebuttal_submitted")
        data = self.paper_root / "data"
        data.mkdir(exist_ok=True)
        (data / "post-submission.yaml").write_text(
            "version: 1\n"
            "rebuttal:\n"
            "  status: not-started\n"
            "resubmit:\n"
            "  status: not-applicable\n"
            "  reason: conference submission\n"
            "talk:\n"
            "  status: not-started\n",
            encoding="utf-8",
        )

        report = build_report(self.paper_root, profile="standard")

        self.assertTrue(
            any(
                "post-submission gate failed" in reason
                and "section-incomplete" in reason
                for reason in report["blocking"]
            ),
            report["blocking"],
        )


if __name__ == "__main__":
    unittest.main()
