import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from ccfa.validate import main, validate_yaml

VALID = """\
version: "0.4.0"
project:
  title: "Demo"
  short_name: "demo"
  root: "."
target_venue:
  name: "NeurIPS"
  year: "2027"
  mode: "conference"
stage:
  current: "idea"
  gate: "scope_defined"
  updated_at: "2026-10-03"
artifacts:
  manuscript: "manuscript/main.tex"
  bibliography: "manuscript/references.bib"
claims: []
experiments: []
reviews: []
revision_ledger:
  path: "reviews/revision-ledger.md"
  status: "not_started"
submission_checks:
  path: "submission/checks.md"
  status: "not_started"
"""


def _write(text: str) -> Path:
    tmp = Path(tempfile.mkdtemp()) / "ccfa.yaml"
    tmp.write_text(text, encoding="utf-8")
    return tmp


class TestValidateYaml(unittest.TestCase):
    def test_valid_file_has_no_problems(self):
        self.assertEqual(validate_yaml(_write(VALID)), [])

    def test_missing_required_top_level_field(self):
        broken = VALID.replace("claims: []\n", "")
        problems = validate_yaml(_write(broken))
        self.assertTrue(any("claims" in p for p in problems), problems)

    def test_invalid_mode_is_reported(self):
        broken = VALID.replace('mode: "conference"', 'mode: "workshop"')
        problems = validate_yaml(_write(broken))
        self.assertTrue(any("mode" in p for p in problems), problems)

    def test_invalid_stage_for_conference_mode(self):
        broken = VALID.replace('current: "idea"', 'current: "major-revision"')
        problems = validate_yaml(_write(broken))
        self.assertTrue(any("major-revision" in p for p in problems), problems)

    def test_unparsable_yaml_raises_not_returns(self):
        with self.assertRaises(ValueError):
            validate_yaml(_write("version: [unclosed\n"))

    def test_non_mapping_target_venue_reports_instead_of_crashing(self):
        broken = VALID.replace(
            'target_venue:\n  name: "NeurIPS"\n  year: "2027"\n  mode: "conference"\n',
            'target_venue: "not-a-mapping"\n',
        )
        problems = validate_yaml(_write(broken))
        self.assertIn("target_venue 必须是映射", problems)

    def test_missing_or_null_deadline_is_valid(self):
        without = VALID
        with_null = VALID.replace(
            '  mode: "conference"\n',
            '  mode: "conference"\n  deadline: null\n',
        )
        self.assertEqual(validate_yaml(_write(without)), [])
        self.assertEqual(validate_yaml(_write(with_null)), [])

    def test_invalid_deadline_format_and_calendar_are_reported(self):
        for value in ("2027-5-1", "2027-02-30"):
            with self.subTest(value=value):
                broken = VALID.replace(
                    '  mode: "conference"\n',
                    f'  mode: "conference"\n  deadline: "{value}"\n',
                )
                problems = validate_yaml(_write(broken))
                self.assertTrue(
                    any("deadline" in problem for problem in problems),
                    problems,
                )

    def test_datetime_deadline_is_reported_not_silently_accepted(self):
        broken = VALID.replace(
            '  mode: "conference"\n',
            '  mode: "conference"\n'
            "  deadline: 2027-05-01T00:00:00Z\n",
        )

        problems = validate_yaml(_write(broken))

        self.assertTrue(any("deadline" in problem for problem in problems), problems)

    def test_missing_history_is_valid(self):
        self.assertEqual(validate_yaml(_write(VALID)), [])

    def test_valid_history_is_accepted(self):
        with_history = VALID.replace(
            '  updated_at: "2026-10-03"\n',
            '  updated_at: "2026-10-03"\n'
            "  history:\n"
            "    - from: idea\n"
            "      to: grounded\n"
            '      at: "2026-10-03"\n'
            "      reason: nearest neighbors recorded\n"
            "      kind: advance\n",
        )
        self.assertEqual(validate_yaml(_write(with_history)), [])

    def test_history_missing_field_is_problem(self):
        broken = VALID.replace(
            '  updated_at: "2026-10-03"\n',
            '  updated_at: "2026-10-03"\n'
            "  history:\n"
            "    - from: idea\n"
            "      to: grounded\n"
            '      at: "2026-10-03"\n'
            "      kind: advance\n",
        )

        problems = validate_yaml(_write(broken))

        self.assertTrue(any("history" in problem and "reason" in problem for problem in problems), problems)

    def test_history_invalid_kind_is_problem(self):
        broken = VALID.replace(
            '  updated_at: "2026-10-03"\n',
            '  updated_at: "2026-10-03"\n'
            "  history:\n"
            "    - from: idea\n"
            "      to: grounded\n"
            '      at: "2026-10-03"\n'
            "      reason: nearest neighbors recorded\n"
            "      kind: rewind\n",
        )

        problems = validate_yaml(_write(broken))

        self.assertTrue(any("kind" in problem for problem in problems), problems)

    def test_history_advance_backwards_is_problem(self):
        broken = VALID.replace(
            '  updated_at: "2026-10-03"\n',
            '  updated_at: "2026-10-03"\n'
            "  history:\n"
            "    - from: writing\n"
            "      to: results-ready\n"
            '      at: "2026-10-03"\n'
            "      reason: bad direction\n"
            "      kind: advance\n",
        )

        problems = validate_yaml(_write(broken))

        self.assertTrue(
            any("state-history-direction" in problem for problem in problems),
            problems,
        )

    def test_history_rollback_forwards_is_problem(self):
        broken = VALID.replace(
            '  updated_at: "2026-10-03"\n',
            '  updated_at: "2026-10-03"\n'
            "  history:\n"
            "    - from: results-ready\n"
            "      to: writing\n"
            '      at: "2026-10-03"\n'
            "      reason: bad direction\n"
            "      kind: rollback\n"
            "      void_artifacts: []\n",
        )

        problems = validate_yaml(_write(broken))

        self.assertTrue(
            any("state-history-direction" in problem for problem in problems),
            problems,
        )

    def test_history_invalid_stage_is_problem(self):
        broken = VALID.replace(
            '  updated_at: "2026-10-03"\n',
            '  updated_at: "2026-10-03"\n'
            "  history:\n"
            "    - from: idea\n"
            "      to: no-such-stage\n"
            '      at: "2026-10-03"\n'
            "      reason: bad stage\n"
            "      kind: advance\n",
        )

        problems = validate_yaml(_write(broken))

        self.assertTrue(
            any("state-history-stage" in problem for problem in problems),
            problems,
        )

    def test_help_prints_usage_to_stdout_and_exits_zero(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["validate.py", "--help"])

        self.assertEqual(code, 0)
        self.assertIn("usage", stdout.getvalue().lower())
        self.assertEqual(stderr.getvalue(), "")
