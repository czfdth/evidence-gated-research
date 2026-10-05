import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from ccfa.argument_audit import check, main


ATTRIBUTED = "Our method reduces the attack success rate by a wide margin."


class FigureSupportAuditTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.manuscript = self.root / "manuscript"
        self.manuscript.mkdir()
        (self.root / "data").mkdir()
        (self.root / "figures").mkdir()
        (self.root / "data" / "claims.yaml").write_text(
            "version: 1\nprotected_sections:\n  - results\nwaivers: []\n",
            encoding="utf-8",
        )
        (self.manuscript / "references.bib").write_text(
            "@article{smith2024,\n  title = {Test Paper}\n}\n",
            encoding="utf-8",
        )
        (self.manuscript / "main.tex").write_text(
            "\\section{Results}\n" + ATTRIBUTED + "\n",
            encoding="utf-8",
        )

    # -- helpers ---------------------------------------------------------

    def _write_manifest(self, text):
        (self.root / "figures" / "manifest.yaml").write_text(
            text, encoding="utf-8"
        )

    def _manifest_entry(self, name="main-results", referenced_in=None, extra=""):
        if referenced_in is None:
            referenced_in = '["manuscript/main.tex:2"]'
        return (
            f"- name: {name}\n"
            f"  file: figures/{name}.pdf\n"
            "  source_run_ids: [R1]\n"
            "  source_data: experiments/results/main.csv\n"
            "  generator: ccfa-workfiles/plot.py\n"
            '  generator_hash: "sha256:abc"\n'
            "  bytes_format: pdf\n"
            f"  referenced_in: {referenced_in}\n"
            f"{extra}"
        )

    def _write_valid_manifest(self):
        self._write_manifest(self._manifest_entry())

    def _write_ledger(self, text):
        (self.root / "data" / "figure-support.yaml").write_text(
            text, encoding="utf-8"
        )

    def _write_novelty(self, claims="  - C1\n"):
        (self.root / "data" / "novelty-audit.yaml").write_text(
            "version: 1\nclaims:\n" + claims,
            encoding="utf-8",
        )

    def _valid_ledger(
        self,
        *,
        figure_id="main-results",
        claim_ids="[C1]",
        verdict="supports",
        reviewer='"张三"',
        reviewed_at='"2026-10-04"',
        note=None,
    ):
        return "version: 1\nfigures:\n" + self._entry_block(
            figure_id=figure_id,
            claim_ids=claim_ids,
            verdict=verdict,
            reviewer=reviewer,
            reviewed_at=reviewed_at,
            note=note,
        )

    def _entry_block(
        self,
        *,
        figure_id="main-results",
        claim_ids="[C1]",
        verdict="supports",
        reviewer='"张三"',
        reviewed_at='"2026-10-04"',
        note=None,
    ):
        body = (
            f"  - id: {figure_id}\n"
            f"    claim_ids: {claim_ids}\n"
            f'    attributed_text: "{ATTRIBUTED}"\n'
            f"    verdict: {verdict}\n"
            f"    reviewer: {reviewer}\n"
            f"    reviewed_at: {reviewed_at}\n"
        )
        if note is not None:
            body += f'    note: "{note}"\n'
        return body

    @staticmethod
    def _codes(problems):
        return {problem.code for problem in problems}

    def _run(self):
        return check(self.root)

    # -- not applicable --------------------------------------------------

    def test_missing_manifest_is_not_applicable(self):
        problems, advisories = self._run()

        codes = self._codes(advisories)
        self.assertIn("figure-support-not-needed", codes)
        self.assertNotIn("figure-support-ledger-missing", self._codes(problems))

    def test_manifest_without_ledger_is_a_problem(self):
        self._write_valid_manifest()

        problems, _advisories = self._run()

        self.assertIn("figure-support-ledger-missing", self._codes(problems))

    def test_ledger_without_version_is_a_tool_problem(self):
        self._write_valid_manifest()
        self._write_ledger("figures: []\n")

        problems, _advisories = self._run()

        self.assertIn("argument-audit-invalid", self._codes(problems))
        self.assertNotIn("figure-support-ledger-missing", self._codes(problems))

    # -- happy path ------------------------------------------------------

    def test_valid_human_figure_review_passes(self):
        self._write_valid_manifest()
        self._write_novelty()
        self._write_ledger(self._valid_ledger())

        problems, advisories = self._run()

        self.assertEqual(problems, [])
        self.assertIn("figure-support-coverage", self._codes(advisories))

    def test_attributed_text_matches_across_wrapped_lines(self):
        (self.manuscript / "main.tex").write_text(
            "\\section{Results}\n"
            "Our method reduces the attack\n"
            "success rate by a wide margin.\n",
            encoding="utf-8",
        )
        self._write_valid_manifest()
        self._write_novelty()
        self._write_ledger(self._valid_ledger())

        problems, _advisories = self._run()

        self.assertNotIn(
            "figure-support-text-not-found", self._codes(problems)
        )

    # -- coverage --------------------------------------------------------

    def test_unreviewed_figure_is_a_problem(self):
        self._write_manifest(
            self._manifest_entry(name="main-results")
            + self._manifest_entry(name="ablation")
        )
        self._write_novelty()
        self._write_ledger(self._valid_ledger())

        problems, _advisories = self._run()

        self.assertIn("figure-support-missing", self._codes(problems))
        messages = " ".join(problem.message for problem in problems)
        self.assertIn("ablation", messages)

    def test_unknown_figure_in_ledger_is_a_problem(self):
        self._write_valid_manifest()
        self._write_novelty()
        self._write_ledger(self._valid_ledger(figure_id="not-in-manifest"))

        problems, _advisories = self._run()

        codes = self._codes(problems)
        self.assertIn("figure-support-figure-missing", codes)
        self.assertIn("figure-support-missing", codes)

    def test_duplicate_figure_entry_is_a_problem(self):
        self._write_valid_manifest()
        self._write_novelty()
        self._write_ledger(
            "version: 1\nfigures:\n"
            + self._entry_block()
            + self._entry_block()
        )

        problems, _advisories = self._run()

        self.assertIn("argument-audit-invalid", self._codes(problems))

    def test_invalid_figures_shape_is_a_problem(self):
        self._write_valid_manifest()
        self._write_ledger("version: 1\nfigures: {}\n")

        problems, _advisories = self._run()

        self.assertIn("argument-audit-invalid", self._codes(problems))

    # -- reviewer / verdict / date --------------------------------------

    def test_model_reviewer_is_a_problem(self):
        self._write_valid_manifest()
        self._write_novelty()
        self._write_ledger(self._valid_ledger(reviewer='"GPT-5"'))

        problems, _advisories = self._run()

        self.assertIn("figure-support-not-human", self._codes(problems))

    def test_invalid_date_is_a_problem(self):
        self._write_valid_manifest()
        self._write_novelty()
        self._write_ledger(self._valid_ledger(reviewed_at='"Oct 4, 2026"'))

        problems, _advisories = self._run()

        self.assertIn("figure-support-invalid-date", self._codes(problems))

    def test_invalid_verdict_is_a_problem(self):
        self._write_valid_manifest()
        self._write_novelty()
        self._write_ledger(self._valid_ledger(verdict="looks-good"))

        problems, _advisories = self._run()

        self.assertIn("figure-support-invalid-verdict", self._codes(problems))

    def test_contradicting_figure_is_a_problem(self):
        self._write_valid_manifest()
        self._write_novelty()
        self._write_ledger(
            self._valid_ledger(
                verdict="contradicts",
                note="The plotted gap is in the opposite direction.",
            )
        )

        problems, _advisories = self._run()

        self.assertIn("figure-support-not-supporting", self._codes(problems))

    def test_partial_figure_is_advisory(self):
        self._write_valid_manifest()
        self._write_novelty()
        self._write_ledger(
            self._valid_ledger(
                verdict="partial",
                note="Only two of three datasets are shown.",
            )
        )

        problems, advisories = self._run()

        self.assertNotIn("figure-support-not-supporting", self._codes(problems))
        self.assertIn("figure-support-partial", self._codes(advisories))

    def test_note_required_for_partial(self):
        self._write_valid_manifest()
        self._write_novelty()
        self._write_ledger(self._valid_ledger(verdict="partial"))

        problems, _advisories = self._run()

        self.assertIn("figure-support-note-missing", self._codes(problems))

    # -- not-applicable --------------------------------------------------

    def test_not_applicable_requires_reason_and_no_claims(self):
        self._write_valid_manifest()
        self._write_novelty()
        self._write_ledger(
            self._valid_ledger(verdict="not-applicable", claim_ids="[C1]")
        )

        problems, advisories = self._run()

        codes = self._codes(problems)
        self.assertIn("figure-support-invalid-claims", codes)
        self.assertIn("figure-support-note-missing", codes)
        self.assertNotIn("figure-support-missing", codes)

    def test_not_applicable_with_reason_passes(self):
        self._write_valid_manifest()
        self._write_novelty()
        self._write_ledger(
            self._valid_ledger(
                verdict="not-applicable",
                claim_ids="[]",
                note="Architecture schematic; it makes no empirical claim.",
            )
        )

        problems, _advisories = self._run()

        self.assertEqual(problems, [])

    def test_not_applicable_does_not_need_a_claim_registry(self):
        self._write_valid_manifest()
        self._write_ledger(
            self._valid_ledger(
                verdict="not-applicable",
                claim_ids="[]",
                note="Architecture schematic; it makes no empirical claim.",
            )
        )

        problems, _advisories = self._run()

        self.assertEqual(problems, [])

    # -- claim binding ---------------------------------------------------

    def test_undeclared_claim_is_a_problem(self):
        self._write_valid_manifest()
        self._write_novelty()
        self._write_ledger(self._valid_ledger(claim_ids="[C9]"))

        problems, _advisories = self._run()

        self.assertIn("figure-support-unknown-claim", self._codes(problems))

    def test_empty_claim_ids_is_a_problem(self):
        self._write_valid_manifest()
        self._write_novelty()
        self._write_ledger(self._valid_ledger(claim_ids="[]"))

        problems, _advisories = self._run()

        self.assertIn("figure-support-invalid-claims", self._codes(problems))

    def test_missing_novelty_ledger_is_a_problem(self):
        self._write_valid_manifest()
        self._write_ledger(self._valid_ledger())

        problems, advisories = self._run()

        self.assertIn(
            "figure-support-claims-unavailable", self._codes(problems)
        )
        self.assertNotIn(
            "figure-support-claims-unavailable", self._codes(advisories)
        )
        self.assertNotIn("figure-support-unknown-claim", self._codes(problems))

    def test_malformed_novelty_claims_is_a_problem(self):
        self._write_valid_manifest()
        (self.root / "data" / "novelty-audit.yaml").write_text(
            "version: 1\nclaims: C1\n", encoding="utf-8"
        )
        self._write_ledger(self._valid_ledger())

        problems, _advisories = self._run()

        self.assertIn(
            "figure-support-claims-unavailable", self._codes(problems)
        )

    def test_partially_malformed_claims_is_a_problem(self):
        self._write_valid_manifest()
        (self.root / "data" / "novelty-audit.yaml").write_text(
            "version: 1\nclaims:\n  - C1\n  - 123\n", encoding="utf-8"
        )
        self._write_ledger(self._valid_ledger())

        problems, _advisories = self._run()

        self.assertIn(
            "figure-support-claims-unavailable", self._codes(problems)
        )

    def test_wrong_novelty_version_is_a_problem(self):
        self._write_valid_manifest()
        (self.root / "data" / "novelty-audit.yaml").write_text(
            "version: 2\nclaims:\n  - C1\n", encoding="utf-8"
        )
        self._write_ledger(self._valid_ledger())

        problems, _advisories = self._run()

        self.assertIn(
            "figure-support-claims-unavailable", self._codes(problems)
        )

    def test_duplicate_claim_registry_is_a_problem(self):
        self._write_valid_manifest()
        (self.root / "data" / "novelty-audit.yaml").write_text(
            "version: 1\nclaims:\n  - C1\n  - C1\n", encoding="utf-8"
        )
        self._write_ledger(self._valid_ledger())

        problems, _advisories = self._run()

        self.assertIn(
            "figure-support-claims-unavailable", self._codes(problems)
        )

    def test_empty_claim_registry_cannot_bind_evidence(self):
        self._write_valid_manifest()
        (self.root / "data" / "novelty-audit.yaml").write_text(
            "version: 1\nclaims: []\n", encoding="utf-8"
        )
        self._write_ledger(self._valid_ledger())

        problems, _advisories = self._run()

        self.assertIn(
            "figure-support-claims-unavailable", self._codes(problems)
        )

    def test_claims_unavailable_is_reported_once(self):
        self._write_manifest(
            self._manifest_entry(name="main-results")
            + self._manifest_entry(name="ablation")
        )
        self._write_ledger(
            "version: 1\nfigures:\n"
            + self._entry_block(figure_id="main-results")
            + self._entry_block(figure_id="ablation")
        )

        problems, _advisories = self._run()

        reported = [
            problem
            for problem in problems
            if problem.code == "figure-support-claims-unavailable"
        ]
        self.assertEqual(len(reported), 1)

    # -- attributed text ------------------------------------------------

    def test_short_attributed_text_is_a_problem(self):
        self._write_valid_manifest()
        self._write_novelty()
        ledger = self._valid_ledger().replace(ATTRIBUTED, "good")
        self._write_ledger(ledger)

        problems, _advisories = self._run()

        self.assertIn("figure-support-text-too-short", self._codes(problems))

    def test_attributed_text_must_appear_in_referenced_file(self):
        self._write_valid_manifest()
        self._write_novelty()
        ledger = self._valid_ledger().replace(
            ATTRIBUTED, "A sentence that is nowhere in the manuscript."
        )
        self._write_ledger(ledger)

        problems, _advisories = self._run()

        self.assertIn("figure-support-text-not-found", self._codes(problems))

    # -- references ------------------------------------------------------

    def test_missing_referenced_in_is_a_problem(self):
        self._write_manifest(
            "- name: main-results\n  file: figures/main-results.pdf\n"
        )
        self._write_novelty()
        self._write_ledger(self._valid_ledger())

        problems, _advisories = self._run()

        self.assertIn(
            "figure-support-reference-missing", self._codes(problems)
        )

    def test_invalid_reference_line_is_a_problem(self):
        self._write_manifest(self._manifest_entry(referenced_in='["manuscript/main.tex:0"]'))
        self._write_novelty()
        self._write_ledger(self._valid_ledger())

        problems, _advisories = self._run()

        self.assertIn(
            "figure-support-reference-invalid", self._codes(problems)
        )

    def test_reference_escape_is_a_problem(self):
        self._write_manifest(
            self._manifest_entry(referenced_in='["../outside.tex:1"]')
        )
        self._write_novelty()
        self._write_ledger(self._valid_ledger())

        problems, _advisories = self._run()

        self.assertIn(
            "figure-support-reference-invalid", self._codes(problems)
        )

    def test_unknown_reference_file_is_a_problem(self):
        self._write_manifest(
            self._manifest_entry(referenced_in='["manuscript/missing.tex:1"]')
        )
        self._write_novelty()
        self._write_ledger(self._valid_ledger())

        problems, _advisories = self._run()

        self.assertIn(
            "figure-support-reference-invalid", self._codes(problems)
        )

    def test_out_of_range_reference_line_is_a_problem(self):
        self._write_manifest(
            self._manifest_entry(referenced_in='["manuscript/main.tex:999999"]')
        )
        self._write_novelty()
        self._write_ledger(self._valid_ledger())

        problems, _advisories = self._run()

        self.assertIn(
            "figure-support-reference-invalid", self._codes(problems)
        )

    def test_duplicate_manifest_name_is_a_problem(self):
        self._write_manifest(
            self._manifest_entry(name="dup") + self._manifest_entry(name="dup")
        )
        self._write_novelty()
        self._write_ledger(self._valid_ledger(figure_id="dup"))

        problems, _advisories = self._run()

        self.assertIn(
            "figure-support-manifest-invalid", self._codes(problems)
        )

    def test_unnamed_manifest_entry_is_a_problem(self):
        self._write_manifest("- file: figures/anonymous.pdf\n")
        self._write_novelty()
        self._write_ledger(self._valid_ledger())

        problems, advisories = self._run()

        self.assertIn(
            "figure-support-manifest-invalid", self._codes(problems)
        )
        self.assertNotIn("figure-support-not-needed", self._codes(advisories))

    def test_irrelevant_verdict_is_a_problem(self):
        self._write_valid_manifest()
        self._write_novelty()
        self._write_ledger(
            self._valid_ledger(
                verdict="irrelevant",
                note="The figure shows a different metric entirely.",
            )
        )

        problems, _advisories = self._run()

        self.assertIn("figure-support-not-supporting", self._codes(problems))

    def test_bool_ledger_version_is_a_problem(self):
        self._write_valid_manifest()
        self._write_novelty()
        self._write_ledger(
            self._valid_ledger().replace("version: 1", "version: true", 1)
        )

        problems, _advisories = self._run()

        self.assertIn("argument-audit-invalid", self._codes(problems))

    def test_float_ledger_version_is_a_problem(self):
        self._write_valid_manifest()
        self._write_novelty()
        self._write_ledger(
            self._valid_ledger().replace("version: 1", "version: 1.0", 1)
        )

        problems, _advisories = self._run()

        self.assertIn("argument-audit-invalid", self._codes(problems))

    # -- CLI -------------------------------------------------------------

    def test_main_returns_one_and_reports_missing_ledger(self):
        self._write_valid_manifest()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            stderr
        ):
            code = main(
                [
                    "argument-audit",
                    "--paper-root",
                    str(self.root),
                ]
            )

        self.assertEqual(code, 1)
        self.assertIn("figure-support-ledger-missing", stdout.getvalue())

    def test_main_accepts_explicit_ledger_paths(self):
        self._write_manifest(self._manifest_entry())
        self._write_novelty()
        ledger = self.root / "data" / "figure-support.yaml"
        self._write_ledger(self._valid_ledger())
        stdout = io.StringIO()
        stderr = io.StringIO()

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            stderr
        ):
            code = main(
                [
                    "argument-audit",
                    "--paper-root",
                    str(self.root),
                    "--figure-ledger",
                    str(ledger),
                    "--manifest",
                    str(self.root / "figures" / "manifest.yaml"),
                ]
            )

        self.assertEqual(code, 0, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
