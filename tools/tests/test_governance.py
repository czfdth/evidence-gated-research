import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from ccfa.governance import check, main
from ccfa.ledger import load_ledger

VALID = """\
version: 1
authors:
  - name: Alice Zhang
    affiliation: Example University
    roles: [conceptualization, writing]
    corresponding: true
  - name: Bob Li
    affiliation: Example Lab
    roles: [software, validation]
    corresponding: false
conflicts:
  - name: Alice Zhang
    declared: none
  - name: Bob Li
    declared: none
ethics:
  human_subjects: false
  data_license: CC-BY-4.0
ai_usage:
  disclosed: true
  policy: https://example.org/ai-policy
plagiarism:
  checked: true
  tool: iThenticate
  date: '2026-10-05'
responsible_disclosure:
  dual_use_reviewed: true
  disclosure_contact: security@example.org
  notes: Reviewed with the institution.
"""


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "data").mkdir()
        self.path = self.root / "data" / "governance.yaml"
        self.path.write_text(VALID, encoding="utf-8")

    @staticmethod
    def _codes(problems):
        return {problem.code for problem in problems}

    def test_valid_ledger_passes(self):
        problems, advisories = check(self.root)
        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_missing_author_conflict_is_a_problem(self):
        self.path.write_text(
            VALID.replace(
                "  - name: Bob Li\n    declared: none\n",
                "",
            ),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("governance-missing-conflict", self._codes(problems))

    def test_human_subjects_require_irb_and_consent(self):
        self.path.write_text(
            VALID.replace(
                "human_subjects: false",
                "human_subjects: true",
            ),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("governance-missing-ethics", self._codes(problems))

    def test_ai_disclosure_must_be_true(self):
        self.path.write_text(
            VALID.replace("disclosed: true", "disclosed: false"),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("governance-missing-ai-disclosure", self._codes(problems))

    def test_plagiarism_check_must_be_true(self):
        self.path.write_text(
            VALID.replace("checked: true", "checked: false"),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn(
            "governance-missing-plagiarism-check",
            self._codes(problems),
        )

    def test_dual_use_review_must_be_true(self):
        self.path.write_text(
            VALID.replace(
                "dual_use_reviewed: true",
                "dual_use_reviewed: false",
            ),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("governance-missing-dual-use", self._codes(problems))

    def test_missing_ledger_is_a_problem(self):
        self.path.unlink()
        problems, _advisories = check(self.root)
        self.assertIn("governance-ledger-missing", self._codes(problems))

    def test_main_emits_json(self):
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["governance", "--paper-root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["problem_count"], 0)

    def test_ledger_version_must_be_strict_int(self):
        for value in ("true", "1.0"):
            with self.subTest(value=value):
                self.path.write_text(
                    f"version: {value}\n",
                    encoding="utf-8",
                )
                payload, problems = load_ledger(self.path)
                self.assertIsNone(payload)
                self.assertIn(
                    "ledger-invalid",
                    {problem.code for problem in problems},
                )

    def test_pending_placeholder_text_is_a_problem(self):
        replacements = {
            "declared: none": (
                "declared: pending final author-specific COI disclosure"
            ),
            "tool: iThenticate": (
                "tool: manual self-check pending institutional similarity tool"
            ),
            "disclosure_contact: security@example.org": (
                "disclosure_contact: anonymous-submission-contact-pending"
            ),
        }
        for old, new in replacements.items():
            with self.subTest(field=old):
                self.path.write_text(
                    VALID.replace(old, new),
                    encoding="utf-8",
                )
                problems, _advisories = check(self.root)
                self.assertIn(
                    "governance-placeholder",
                    self._codes(problems),
                )


if __name__ == "__main__":
    unittest.main()
