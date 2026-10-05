import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path

import yaml

from ccfa.milestones import (
    checkpoints,
    due_report,
    main,
    parse_deadline,
    stage_report,
)


class MilestoneTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper_root = Path(self._temporary.name)

    def _write_state(
        self,
        *,
        deadline="2027-05-01",
        stage="idea",
        mode="conference",
        include_deadline=True,
    ):
        venue = {
            "name": "NeurIPS",
            "year": "2027",
            "mode": mode,
        }
        if include_deadline:
            venue["deadline"] = deadline
        state = {
            "target_venue": venue,
            "stage": {"current": stage},
        }
        (self.paper_root / "ccfa.yaml").write_text(
            yaml.safe_dump(state, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def _run(self, argv):
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def _write_run(self, run_id, started_at, *, raw=None):
        log_dir = self.paper_root / "experiments" / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / f"{run_id}.json"
        if raw is None:
            raw = json.dumps(
                {"run_id": run_id, "started_at": started_at},
                ensure_ascii=False,
            )
        path.write_text(raw, encoding="utf-8")
        return path


class TestDeadlineAndCheckpoints(MilestoneTests):
    def test_parse_deadline_accepts_none_empty_and_valid_dates(self):
        self.assertIsNone(parse_deadline(None))
        self.assertIsNone(parse_deadline(""))
        self.assertIsNone(parse_deadline("   "))
        self.assertEqual(parse_deadline("2027-05-01"), date(2027, 5, 1))

    def test_parse_deadline_rejects_format_and_calendar_errors(self):
        for value in ("2027-5-1", "2027-13-01", "2027-02-30", 20270501):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_deadline(value)

    def test_parse_deadline_rejects_date_and_datetime_objects(self):
        for value in (date(2027, 5, 1), datetime(2027, 5, 1, 0, 0, 0)):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ValueError,
                    "必须是 YYYY-MM-DD 日期字符串",
                ):
                    parse_deadline(value)

    def test_checkpoints_are_relative_to_deadline(self):
        self.assertEqual(
            checkpoints(date(2027, 5, 1)),
            {
                "T-90": date(2027, 1, 31),
                "T-60": date(2027, 3, 2),
                "T-30": date(2027, 4, 1),
                "T-21": date(2027, 4, 10),
                "T-14": date(2027, 4, 17),
                "T-7": date(2027, 4, 24),
                "T-3": date(2027, 4, 28),
                "T-1": date(2027, 4, 30),
            },
        )


class TestDueReport(MilestoneTests):
    def test_t90_checkpoint_points_to_experiment_design(self):
        self._write_state(deadline="2027-05-01", stage="idea")

        report = due_report(self.paper_root, date(2027, 1, 31))

        self.assertEqual(report["due"][0]["checkpoint"], "T-90")
        self.assertEqual(report["due"][0]["stage"], "experiment-design")
        self.assertEqual(report["due"][0]["gate"], "design_frozen")

    def test_t60_checkpoint_points_to_experiments_running(self):
        self._write_state(deadline="2027-05-01", stage="experiment-design")

        report = due_report(self.paper_root, date(2027, 3, 2))

        self.assertEqual(report["due"][0]["checkpoint"], "T-60")
        self.assertEqual(report["due"][0]["stage"], "experiments-running")
        self.assertEqual(report["due"][0]["gate"], "results_recorded")

    def test_t30_checkpoint_points_to_results_ready(self):
        self._write_state(deadline="2027-05-01", stage="experiments-running")

        report = due_report(self.paper_root, date(2027, 4, 1))

        self.assertEqual(report["due"][0]["checkpoint"], "T-30")
        self.assertEqual(report["due"][0]["stage"], "results-ready")
        self.assertEqual(report["due"][0]["gate"], "claims_supported")

    def test_t21_checkpoint_points_to_writing(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")

        report = due_report(self.paper_root, date(2027, 4, 10))

        self.assertEqual(report["due"][0]["checkpoint"], "T-21")
        self.assertEqual(report["due"][0]["stage"], "writing")
        self.assertEqual(report["due"][0]["gate"], "draft_complete")

    def test_t1_checkpoint_points_to_submission_check(self):
        self._write_state(deadline="2027-05-01", stage="writing")

        report = due_report(self.paper_root, date(2027, 4, 30))

        self.assertEqual(report["due"][0]["checkpoint"], "T-1")
        self.assertEqual(report["due"][0]["stage"], "submission-check")
        self.assertEqual(report["due"][0]["gate"], "package_ready")

    def test_t30_new_run_is_a_problem_with_run_id_and_date(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")
        self._write_run("20270402T120000-01", "2027-04-02T12:00:00Z")

        report = due_report(self.paper_root, date(2027, 4, 2))

        problem = next(
            item
            for item in report["problems"]
            if item["code"] == "t30-new-experiment"
        )
        self.assertIn("20270402T120000-01", problem["message"])
        self.assertIn("2027-04-02", problem["message"])

    def test_t30_declared_build_run_is_visible_as_advisory(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")
        self._write_run(
            "20270402T120000-01",
            "2027-04-02T12:00:00Z",
            raw=json.dumps(
                {
                    "run_id": "20270402T120000-01",
                    "started_at": "2027-04-02T12:00:00Z",
                    "declared_purpose": "build",
                    "purpose_reason": "Re-render Figure 3 from frozen results.",
                }
            ),
        )

        report = due_report(self.paper_root, date(2027, 4, 2))

        self.assertNotIn(
            "t30-new-experiment",
            {problem["code"] for problem in report["problems"]},
        )
        advisory = next(
            item
            for item in report["advisories"]
            if item["code"] == "t30-declared-build-run"
        )
        self.assertIn("20270402T120000-01", advisory["message"])
        self.assertIn("2027-04-02", advisory["message"])
        self.assertIn("不构成证据", advisory["message"])

    def test_t30_legacy_purpose_build_still_qualifies_for_the_advisory(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")
        self._write_run(
            "20270402T120000-01",
            "2027-04-02T12:00:00Z",
            raw=json.dumps(
                {
                    "run_id": "20270402T120000-01",
                    "started_at": "2027-04-02T12:00:00Z",
                    "purpose": "build",
                    "purpose_reason": "Rebuild the camera-ready PDF after edits.",
                }
            ),
        )

        report = due_report(self.paper_root, date(2027, 4, 2))

        self.assertNotIn(
            "t30-new-experiment",
            {problem["code"] for problem in report["problems"]},
        )
        self.assertIn(
            "t30-declared-build-run",
            {advisory["code"] for advisory in report["advisories"]},
        )

    def test_t30_unjustified_build_run_is_a_problem(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")
        self._write_run(
            "20270402T120000-01",
            "2027-04-02T12:00:00Z",
            raw=json.dumps(
                {
                    "run_id": "20270402T120000-01",
                    "started_at": "2027-04-02T12:00:00Z",
                    "declared_purpose": "build",
                }
            ),
        )

        report = due_report(self.paper_root, date(2027, 4, 2))

        problem = next(
            item
            for item in report["problems"]
            if item["code"] == "t30-unjustified-build-run"
        )
        self.assertIn("20270402T120000-01", problem["message"])
        self.assertNotIn(
            "t30-declared-build-run",
            {item["code"] for item in report["advisories"]},
        )

    def test_t30_short_build_reason_is_a_problem(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")
        self._write_run(
            "20270402T120000-01",
            "2027-04-02T12:00:00Z",
            raw=json.dumps(
                {
                    "run_id": "20270402T120000-01",
                    "started_at": "2027-04-02T12:00:00Z",
                    "declared_purpose": "build",
                    "purpose_reason": "plot",
                }
            ),
        )

        report = due_report(self.paper_root, date(2027, 4, 2))

        self.assertIn(
            "t30-unjustified-build-run",
            {item["code"] for item in report["problems"]},
        )

    def test_t30_justified_build_run_is_an_advisory(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")
        self._write_run(
            "20270402T120000-01",
            "2027-04-02T12:00:00Z",
            raw=json.dumps(
                {
                    "run_id": "20270402T120000-01",
                    "started_at": "2027-04-02T12:00:00Z",
                    "declared_purpose": "build",
                    "purpose_reason": "Re-render Figure 3 from frozen results.",
                }
            ),
        )

        report = due_report(self.paper_root, date(2027, 4, 2))

        self.assertNotIn(
            "t30-new-experiment",
            {item["code"] for item in report["problems"]},
        )
        self.assertNotIn(
            "t30-unjustified-build-run",
            {item["code"] for item in report["problems"]},
        )
        self.assertIn(
            "t30-declared-build-run",
            {item["code"] for item in report["advisories"]},
        )

    def test_t30_build_reason_at_the_length_boundary_is_an_advisory(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")
        self._write_run(
            "20270402T120000-01",
            "2027-04-02T12:00:00Z",
            raw=json.dumps(
                {
                    "run_id": "20270402T120000-01",
                    "started_at": "2027-04-02T12:00:00Z",
                    "declared_purpose": "build",
                    "purpose_reason": "12345678901234567890",
                }
            ),
        )

        report = due_report(self.paper_root, date(2027, 4, 2))

        self.assertNotIn(
            "t30-unjustified-build-run",
            {item["code"] for item in report["problems"]},
        )
        self.assertIn(
            "t30-declared-build-run",
            {item["code"] for item in report["advisories"]},
        )

    def test_t30_whitespace_build_reason_is_a_problem(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")
        self._write_run(
            "20270402T120000-01",
            "2027-04-02T12:00:00Z",
            raw=json.dumps(
                {
                    "run_id": "20270402T120000-01",
                    "started_at": "2027-04-02T12:00:00Z",
                    "declared_purpose": "build",
                    "purpose_reason": "   ",
                }
            ),
        )

        report = due_report(self.paper_root, date(2027, 4, 2))

        self.assertIn(
            "t30-unjustified-build-run",
            {item["code"] for item in report["problems"]},
        )

    def test_t30_non_string_build_reason_is_a_problem(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")
        self._write_run(
            "20270402T120000-01",
            "2027-04-02T12:00:00Z",
            raw=json.dumps(
                {
                    "run_id": "20270402T120000-01",
                    "started_at": "2027-04-02T12:00:00Z",
                    "declared_purpose": "build",
                    "purpose_reason": 123,
                }
            ),
        )

        report = due_report(self.paper_root, date(2027, 4, 2))

        self.assertIn(
            "t30-unjustified-build-run",
            {item["code"] for item in report["problems"]},
        )

    def test_t30_experiment_run_with_a_reason_is_still_a_problem(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")
        self._write_run(
            "20270402T120000-01",
            "2027-04-02T12:00:00Z",
            raw=json.dumps(
                {
                    "run_id": "20270402T120000-01",
                    "started_at": "2027-04-02T12:00:00Z",
                    "declared_purpose": "experiment",
                    "purpose_reason": "A late ablation the reviewers asked for.",
                }
            ),
        )

        report = due_report(self.paper_root, date(2027, 4, 2))

        self.assertIn(
            "t30-new-experiment",
            {item["code"] for item in report["problems"]},
        )
        self.assertNotIn(
            "t30-declared-build-run",
            {item["code"] for item in report["advisories"]},
        )

    def test_t30_declared_experiment_run_is_a_problem(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")
        self._write_run(
            "20270402T120000-01",
            "2027-04-02T12:00:00Z",
            raw=json.dumps(
                {
                    "run_id": "20270402T120000-01",
                    "started_at": "2027-04-02T12:00:00Z",
                    "declared_purpose": "experiment",
                }
            ),
        )

        report = due_report(self.paper_root, date(2027, 4, 2))

        self.assertIn(
            "t30-new-experiment",
            {problem["code"] for problem in report["problems"]},
        )

    def test_t30_older_run_has_no_problem(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")
        self._write_run("20270331T120000-01", "2027-03-31T12:00:00Z")

        report = due_report(self.paper_root, date(2027, 4, 2))

        self.assertNotIn(
            "t30-new-experiment",
            {problem["code"] for problem in report["problems"]},
        )

    def test_t30_same_day_run_is_not_after_the_freeze(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")
        self._write_run("20270401T235900-01", "2027-04-01T23:59:00Z")

        report = due_report(self.paper_root, date(2027, 4, 2))

        self.assertNotIn(
            "t30-new-experiment",
            {problem["code"] for problem in report["problems"]},
        )

    def test_t30_scan_does_not_run_on_the_exact_checkpoint_day(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")
        self._write_run("20270402T120000-01", "2027-04-02T12:00:00Z")

        report = due_report(self.paper_root, date(2027, 4, 1))

        self.assertNotIn(
            "t30-new-experiment",
            {problem["code"] for problem in report["problems"]},
        )

    def test_bad_run_record_is_advisory_and_other_records_are_still_scanned(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")
        bad_path = self._write_run("bad", None, raw="{not-json")
        self._write_run("20270402T120000-01", "2027-04-02T12:00:00Z")

        report = due_report(self.paper_root, date(2027, 4, 3))

        self.assertIn(
            "t30-new-experiment",
            {problem["code"] for problem in report["problems"]},
        )
        self.assertEqual(
            [advisory["code"] for advisory in report["advisories"]],
            ["t30-scan-skipped"],
        )
        self.assertEqual(report["advisories"][0]["path"], str(bad_path))

    def test_t30_scan_is_not_run_in_sequential_mode(self):
        self._write_state(include_deadline=False, stage="results-ready")
        self._write_run("20270402T120000-01", "2027-04-02T12:00:00Z")

        report = due_report(self.paper_root, date(2027, 4, 3))

        self.assertEqual(report["mode"], "sequential")
        self.assertNotIn(
            "t30-new-experiment",
            {problem["code"] for problem in report["problems"]},
        )

    def test_t14_checkpoint_reports_gate_gaps(self):
        self._write_state(deadline="2027-05-01", stage="idea")
        today = date(2027, 5, 1) - timedelta(days=14)

        report = due_report(self.paper_root, today)

        self.assertEqual(report["mode"], "countdown")
        self.assertEqual(report["deadline"], "2027-05-01")
        self.assertEqual(report["due"][0]["checkpoint"], "T-14")
        self.assertEqual(report["due"][0]["date"], "2027-04-17")
        self.assertGreater(len(report["missing_gates"]), 0)
        self.assertTrue(
            all(
                problem["code"] == "milestone-gate-missing"
                for problem in report["missing_gates"]
            )
        )

    def test_t7_checkpoint_is_hit_on_exact_day(self):
        self._write_state(deadline="2027-05-01", stage="writing")

        report = due_report(self.paper_root, date(2027, 4, 24))

        self.assertEqual([item["checkpoint"] for item in report["due"]], ["T-7"])
        self.assertGreater(len(report["problems"]), 0)

    def test_t3_checkpoint_is_hit_on_exact_day(self):
        self._write_state(deadline="2027-05-01", stage="submission-check")

        report = due_report(self.paper_root, date(2027, 4, 28))

        self.assertEqual([item["checkpoint"] for item in report["due"]], ["T-3"])

    def test_non_checkpoint_day_has_empty_due(self):
        self._write_state(deadline="2027-05-01", stage="idea")

        report = due_report(self.paper_root, date(2027, 4, 20))

        self.assertEqual(report["due"], [])
        self.assertEqual(report["missing_gates"], [])
        self.assertEqual(report["problems"], [])

    def test_deadline_passed_reports_overdue(self):
        self._write_state(deadline="2027-05-01", stage="writing")

        report = due_report(self.paper_root, date(2027, 5, 2))

        self.assertEqual([item["checkpoint"] for item in report["due"]], ["overdue"])
        self.assertIn(
            "deadline-passed",
            {problem["code"] for problem in report["problems"]},
        )

    def test_sequential_mode_has_no_concrete_dates(self):
        self._write_state(include_deadline=False, stage="idea")

        report = due_report(self.paper_root, date(2027, 5, 1))

        self.assertEqual(report["mode"], "sequential")
        self.assertIsNone(report["deadline"])
        self.assertEqual(report["due"], [])
        self.assertIn("无投稿目标日", report["advisory"])
        self.assertIn("scope_defined", report["advisory"])
        self.assertIsNone(re.search(r"\d{4}-\d{2}-\d{2}", json.dumps(report)))

    def test_invalid_deadline_is_a_problem(self):
        self._write_state(deadline="2027-02-30", stage="idea")

        report = due_report(self.paper_root, date(2027, 1, 1))

        self.assertEqual(report["due"], [])
        self.assertIn(
            "deadline-invalid",
            {problem["code"] for problem in report["problems"]},
        )

    def test_unknown_stage_is_a_problem(self):
        self._write_state(deadline="2027-05-01", stage="not-a-stage")

        report = due_report(self.paper_root, date(2027, 4, 17))

        self.assertIn(
            "stage-unknown",
            {problem["code"] for problem in report["problems"]},
        )

    def test_passed_checkpoint_has_empty_due_and_no_gate_gap(self):
        self._write_state(deadline="2027-05-01", stage="submission-check")

        report = due_report(self.paper_root, date(2027, 4, 17))

        self.assertEqual(report["due"], [])
        self.assertEqual(report["missing_gates"], [])
        self.assertEqual(report["problems"], [])

    def test_t7_checkpoint_points_to_internal_review(self):
        self._write_state(deadline="2027-05-01", stage="writing")

        report = due_report(self.paper_root, date(2027, 4, 24))

        self.assertEqual(report["due"][0]["checkpoint"], "T-7")
        self.assertEqual(report["due"][0]["stage"], "internal-review")
        self.assertEqual(report["due"][0]["gate"], "review_cleared")
        self.assertTrue(
            any(
                "review_cleared" in problem["message"]
                for problem in report["problems"]
            )
        )


class TestMilestonesMain(MilestoneTests):
    def test_stage_command_outputs_current_gate_and_updated_at(self):
        self._write_state(stage="writing", deadline=None)
        data = yaml.safe_load(
            (self.paper_root / "ccfa.yaml").read_text(encoding="utf-8")
        )
        data["stage"]["gate"] = "draft_complete"
        data["stage"]["updated_at"] = "2026-10-03"
        (self.paper_root / "ccfa.yaml").write_text(
            yaml.safe_dump(data, sort_keys=False),
            encoding="utf-8",
        )

        code, stdout, stderr = self._run(
            [
                "milestones",
                "stage",
                "--paper-root",
                str(self.paper_root),
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            json.loads(stdout),
            {
                "current": "writing",
                "gate": "draft_complete",
                "updated_at": "2026-10-03",
            },
        )

    def test_stage_command_missing_file_or_fields_exits_two(self):
        code, stdout, stderr = self._run(
            [
                "milestones",
                "stage",
                "--paper-root",
                str(self.paper_root),
            ]
        )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("工具错误", stderr)

    def test_public_stage_report_matches_cli_output(self):
        self._write_state(stage="writing", deadline=None)
        data = yaml.safe_load(
            (self.paper_root / "ccfa.yaml").read_text(encoding="utf-8")
        )
        data["stage"]["gate"] = "draft_complete"
        data["stage"]["updated_at"] = "2026-10-03"
        (self.paper_root / "ccfa.yaml").write_text(
            yaml.safe_dump(data, sort_keys=False),
            encoding="utf-8",
        )

        report = stage_report(self.paper_root)
        code, stdout, stderr = self._run(
            [
                "milestones",
                "stage",
                "--paper-root",
                str(self.paper_root),
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout), report)
        self.assertEqual(
            report,
            {
                "current": "writing",
                "gate": "draft_complete",
                "updated_at": "2026-10-03",
            },
        )

        self._write_state(stage="writing", deadline=None)
        code, stdout, stderr = self._run(
            [
                "milestones",
                "stage",
                "--paper-root",
                str(self.paper_root),
            ]
        )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("工具错误", stderr)

    def test_due_non_checkpoint_exits_zero_with_json(self):
        self._write_state(deadline="2027-05-01", stage="idea")

        code, stdout, stderr = self._run(
            [
                "milestones",
                "due",
                "--paper-root",
                str(self.paper_root),
                "--today",
                "2027-04-20",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout)["due"], [])

    def test_due_checkpoint_with_gate_gap_exits_one(self):
        self._write_state(deadline="2027-05-01", stage="idea")

        code, stdout, stderr = self._run(
            [
                "milestones",
                "due",
                "--paper-root",
                str(self.paper_root),
                "--today",
                "2027-04-17",
            ]
        )

        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout)["due"][0]["checkpoint"], "T-14")
        self.assertIn("milestone-gate-missing", stderr)

    def test_due_t3_submission_check_exits_one_with_package_gap(self):
        self._write_state(deadline="2027-05-01", stage="submission-check")

        code, stdout, stderr = self._run(
            [
                "milestones",
                "due",
                "--paper-root",
                str(self.paper_root),
                "--today",
                "2027-04-28",
            ]
        )

        report = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(report["due"][0]["checkpoint"], "T-3")
        self.assertTrue(
            any("package_ready" in problem["message"] for problem in report["problems"])
        )
        self.assertIn("package_ready", stderr)

    def test_due_t30_new_run_exits_one(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")
        self._write_run("20270402T120000-01", "2027-04-02T12:00:00Z")

        code, stdout, stderr = self._run(
            [
                "milestones",
                "due",
                "--paper-root",
                str(self.paper_root),
                "--today",
                "2027-04-02",
            ]
        )

        self.assertEqual(code, 1)
        self.assertIn(
            "t30-new-experiment",
            {problem["code"] for problem in json.loads(stdout)["problems"]},
        )
        self.assertIn("t30-new-experiment", stderr)

    def test_due_t30_bad_record_advisory_exits_zero(self):
        self._write_state(deadline="2027-05-01", stage="results-ready")
        self._write_run("bad", None, raw="{not-json")

        code, stdout, stderr = self._run(
            [
                "milestones",
                "due",
                "--paper-root",
                str(self.paper_root),
                "--today",
                "2027-04-02",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["problems"], [])
        self.assertIn("t30-scan-skipped", stderr)

    def test_due_t14_internal_review_exits_one_with_review_gap(self):
        self._write_state(deadline="2027-05-01", stage="internal-review")

        code, stdout, stderr = self._run(
            [
                "milestones",
                "due",
                "--paper-root",
                str(self.paper_root),
                "--today",
                "2027-04-17",
            ]
        )

        report = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(report["due"][0]["checkpoint"], "T-14")
        self.assertTrue(
            any(
                "review_cleared" in problem["message"]
                for problem in report["missing_gates"]
            )
        )
        self.assertIn("review_cleared", stderr)

    def test_due_passed_t3_checkpoint_exits_zero_with_empty_due(self):
        self._write_state(deadline="2027-05-01", stage="submitted")

        code, stdout, stderr = self._run(
            [
                "milestones",
                "due",
                "--paper-root",
                str(self.paper_root),
                "--today",
                "2027-04-28",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["due"], [])
        self.assertEqual(stderr, "")

    def test_invalid_deadline_exits_one(self):
        self._write_state(deadline="bad-date", stage="idea")

        code, stdout, stderr = self._run(
            [
                "milestones",
                "due",
                "--paper-root",
                str(self.paper_root),
                "--today",
                "2027-04-17",
            ]
        )

        self.assertEqual(code, 1)
        self.assertIn("deadline-invalid", json.loads(stdout)["problems"][0]["code"])
        self.assertIn("deadline-invalid", stderr)

    def test_bad_today_or_yaml_exits_two(self):
        self._write_state(deadline="2027-05-01", stage="idea")

        code, stdout, stderr = self._run(
            [
                "milestones",
                "due",
                "--paper-root",
                str(self.paper_root),
                "--today",
                "2027-02-30",
            ]
        )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("工具错误", stderr)

    def test_datetime_deadline_is_a_tool_error_without_traceback(self):
        (self.paper_root / "ccfa.yaml").write_text(
            "target_venue:\n"
            "  name: Smoke\n"
            "  mode: conference\n"
            "  deadline: 2027-05-01T00:00:00Z\n"
            "stage:\n"
            "  current: writing\n",
            encoding="utf-8",
        )

        code, stdout, stderr = self._run(
            [
                "milestones",
                "due",
                "--paper-root",
                str(self.paper_root),
                "--today",
                "2027-05-02",
            ]
        )

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("工具错误", stderr)
        self.assertNotIn("Traceback", stderr)

        (self.paper_root / "ccfa.yaml").write_text(
            "target_venue: [broken\n",
            encoding="utf-8",
        )
        code, stdout, stderr = self._run(
            [
                "milestones",
                "due",
                "--paper-root",
                str(self.paper_root),
                "--today",
                "2027-04-17",
            ]
        )
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("工具错误", stderr)


if __name__ == "__main__":
    unittest.main()
