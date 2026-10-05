import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from ccfa.argument_audit import check, main


class ArgumentAuditTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.manuscript = self.root / "manuscript"
        self.manuscript.mkdir()
        (self.root / "data").mkdir()
        (self.root / "references").mkdir()
        (self.root / "data" / "claims.yaml").write_text(
            "version: 1\nprotected_sections:\n  - abstract\nwaivers: []\n",
            encoding="utf-8",
        )
        (self.manuscript / "references.bib").write_text(
            "@article{smith2024,\n"
            "  title = {Test Paper},\n"
            "  author = {Smith, Alice},\n"
            "  year = {2024}\n"
            "}\n",
            encoding="utf-8",
        )

    def _write_tex(self, text):
        (self.manuscript / "main.tex").write_text(text, encoding="utf-8")

    def _write_proof_ledger(self, text):
        (self.root / "data" / "proof-audit.yaml").write_text(
            text,
            encoding="utf-8",
        )

    def _write_support_ledger(self, text):
        (self.root / "data" / "citation-support.yaml").write_text(
            text,
            encoding="utf-8",
        )

    def _audited_main(self):
        """The audited_inputs block for the current manuscript bytes."""

        return self._audited("manuscript/main.tex")

    def _audited(self, *paths):
        """The audited_inputs block for the current bytes of *paths*."""

        lines = ["    audited_inputs:"]
        for raw in paths:
            digest = hashlib.sha256((self.root / raw).read_bytes()).hexdigest()
            lines.append(f"      {raw}: sha256:{digest}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _codes(problems):
        return {problem.code for problem in problems}

    def _run(self):
        return check(self.root)

    def test_missing_proof_ledger_is_a_problem(self):
        self._write_tex(
            "\\section{Method}\n"
            "\\begin{proposition}\\label{prop:main}\n"
            "A claim.\n"
            "\\end{proposition}\n"
        )

        problems, advisories = self._run()

        self.assertIn("proof-audit-missing", self._codes(problems))

    def test_valid_human_proof_review_passes(self):
        self._write_tex(
            "\\section{Method}\n"
            "\\begin{proposition}\\label{prop:main}\n"
            "A claim.\n"
            "\\end{proposition}\n"
        )
        self._write_proof_ledger(
            "version: 1\n"
            "reviews:\n"
            "  - id: prop:main\n"
            "    reviewer: Alice Zhang\n"
            "    reviewed_at: '2026-10-04'\n"
            "    method: line-by-line\n"
            "    status: verified\n" + self._audited_main()
        )

        problems, advisories = self._run()

        self.assertEqual(self._codes(problems), set())
        self.assertNotIn("proof-review-missing", self._codes(problems))
        self.assertNotIn("proof-review-not-human", self._codes(problems))
        self.assertIn("proof-audit-coverage", self._codes(advisories))

    def test_verified_review_without_audited_inputs_is_unbound(self):
        self._write_tex(
            "\\begin{proposition}\\label{prop:main}\n"
            "A claim.\n"
            "\\end{proposition}\n"
        )
        self._write_proof_ledger(
            "version: 1\n"
            "reviews:\n"
            "  - id: prop:main\n"
            "    reviewer: Alice Zhang\n"
            "    reviewed_at: '2026-10-04'\n"
            "    method: line-by-line\n"
            "    status: verified\n"
        )

        problems, _advisories = self._run()

        self.assertIn("proof-review-unbound", self._codes(problems))

    def test_editing_the_manuscript_afterwards_makes_the_review_stale(self):
        self._write_tex(
            "\\begin{proposition}\\label{prop:main}\n"
            "A claim.\n"
            "\\end{proposition}\n"
        )
        self._write_proof_ledger(
            "version: 1\n"
            "reviews:\n"
            "  - id: prop:main\n"
            "    reviewer: Alice Zhang\n"
            "    reviewed_at: '2026-10-04'\n"
            "    method: line-by-line\n"
            "    status: verified\n" + self._audited_main()
        )
        self.assertEqual(self._codes(self._run()[0]), set())

        self._write_tex(
            "\\begin{proposition}\\label{prop:main}\n"
            "A different claim.\n"
            "\\end{proposition}\n"
        )

        problems, _advisories = self._run()

        self.assertIn("proof-review-stale", self._codes(problems))

    def test_audited_inputs_cannot_escape_the_paper_root(self):
        self._write_tex(
            "\\begin{proposition}\\label{prop:main}\n"
            "A claim.\n"
            "\\end{proposition}\n"
        )
        self._write_proof_ledger(
            "version: 1\n"
            "reviews:\n"
            "  - id: prop:main\n"
            "    reviewer: Alice Zhang\n"
            "    reviewed_at: '2026-10-04'\n"
            "    method: line-by-line\n"
            "    status: verified\n"
            "    audited_inputs:\n"
            "      ../outside.tex: sha256:" + "0" * 64 + "\n"
        )

        problems, _advisories = self._run()

        self.assertIn("proof-review-unbound", self._codes(problems))

    def test_stamp_prints_the_current_digests(self):
        self._write_tex(
            "\\begin{proposition}\\label{prop:main}\n"
            "A claim.\n"
            "\\end{proposition}\n"
        )
        stream = StringIO()

        with redirect_stdout(stream):
            code = main(
                [
                    "argument-audit",
                    "--paper-root",
                    str(self.root),
                    "--stamp",
                    "manuscript/main.tex",
                ]
            )

        self.assertEqual(code, 0)
        self.assertIn("audited_inputs:", stream.getvalue())
        self.assertRegex(
            stream.getvalue(),
            r"manuscript/main\.tex: sha256:[0-9a-f]{64}",
        )

    def test_model_name_cannot_be_a_proof_reviewer(self):
        self._write_tex(
            "\\begin{proposition}\\label{prop:main}\n"
            "A claim.\n"
            "\\end{proposition}\n"
        )
        self._write_proof_ledger(
            "version: 1\n"
            "reviews:\n"
            "  - id: prop:main\n"
            "    reviewer: deepseek-v4-pro\n"
            "    reviewed_at: '2026-10-04'\n"
            "    method: line-by-line\n"
            "    status: verified\n"
        )

        problems, _advisories = self._run()

        self.assertIn("proof-review-not-human", self._codes(problems))

    def test_uncertain_proof_review_is_a_problem(self):
        self._write_tex(
            "\\begin{proposition}\\label{prop:main}\n"
            "A claim.\n"
            "\\end{proposition}\n"
        )
        self._write_proof_ledger(
            "version: 1\n"
            "reviews:\n"
            "  - id: prop:main\n"
            "    reviewer: Alice Zhang\n"
            "    reviewed_at: '2026-10-04'\n"
            "    method: line-by-line\n"
            "    status: uncertain\n"
        )

        problems, _advisories = self._run()

        self.assertIn("proof-review-not-verified", self._codes(problems))

    def test_pending_proof_placeholder_does_not_count_as_reviewed(self):
        self._write_tex(
            "\\begin{proposition}\\label{prop:main}\n"
            "A claim.\n"
            "\\end{proposition}\n"
        )
        self._write_proof_ledger(
            "version: 1\n"
            "status: pending-human-review\n"
            "reviews:\n"
            "  - id: prop:main\n"
            "    reviewer: Human reviewer pending\n"
            "    reviewed_at: '2026-10-04'\n"
            "    method: line-by-line\n"
            "    status: pending\n"
        )

        problems, advisories = self._run()

        self.assertIn("proof-review-not-verified", self._codes(problems))
        self.assertNotIn("proof-review-invalid-status", self._codes(problems))
        coverage = next(
            item for item in advisories if item.code == "proof-audit-coverage"
        )
        self.assertIn("0/1", coverage.message)

    def test_non_string_proof_fields_are_problems_not_crashes(self):
        self._write_tex(
            "\\begin{proposition}\\label{prop:main}\n"
            "A claim.\n"
            "\\end{proposition}\n"
        )
        self._write_proof_ledger(
            "version: 1\n"
            "reviews:\n"
            "  - id: prop:main\n"
            "    reviewer: Alice Zhang\n"
            "    reviewed_at: '2026-10-04'\n"
            "    method: [line-by-line]\n"
            "    status: {bad: true}\n"
        )

        problems, _advisories = self._run()

        self.assertIn("proof-review-invalid-method", self._codes(problems))
        self.assertIn("proof-review-invalid-status", self._codes(problems))

    def test_model_name_variants_cannot_be_reviewers(self):
        self._write_tex(
            "\\begin{proposition}\\label{prop:main}\n"
            "A claim.\n"
            "\\end{proposition}\n"
        )
        for reviewer in ("grok-3", "Sonnet 4.5", "amazon-nova-pro"):
            with self.subTest(reviewer=reviewer):
                self._write_proof_ledger(
                    "version: 1\n"
                    "reviews:\n"
                    "  - id: prop:main\n"
                    f"    reviewer: {reviewer}\n"
                    "    reviewed_at: '2026-10-04'\n"
                    "    method: line-by-line\n"
                    "    status: verified\n"
                )

                problems, _advisories = self._run()

                self.assertIn("proof-review-not-human", self._codes(problems))

    def test_protected_citation_requires_support_ledger(self):
        self._write_tex(
            "\\section{Abstract}\n"
            "Prior work \\cite{smith2024} shows this.\n"
        )

        problems, _advisories = self._run()

        self.assertIn("citation-support-ledger-missing", self._codes(problems))

    def test_abstract_environment_counts_as_a_protected_section(self):
        self._write_tex(
            "\\begin{abstract}\n"
            "Prior work \\cite{smith2024} shows this.\n"
            "\\end{abstract}\n"
        )

        problems, _advisories = self._run()

        self.assertIn("citation-support-ledger-missing", self._codes(problems))

    def test_optional_citation_argument_is_detected(self):
        self._write_tex(
            "\\section{Abstract}\n"
            "Prior work \\cite[p. 3]{smith2024} shows this.\n"
        )

        problems, _advisories = self._run()

        self.assertIn("citation-support-ledger-missing", self._codes(problems))

    def test_short_section_title_is_detected(self):
        self._write_tex(
            "\\section[short]{Abstract}\n"
            "Prior work \\cite{smith2024} shows this.\n"
        )

        problems, _advisories = self._run()

        self.assertIn("citation-support-ledger-missing", self._codes(problems))

    def test_protected_section_survives_non_protected_sibling_subsection(self):
        (self.root / "data" / "claims.yaml").write_text(
            "version: 1\n"
            "protected_sections:\n"
            "  - findings\n"
            "  - data\n"
            "waivers: []\n",
            encoding="utf-8",
        )
        self._write_tex(
            "\\section{Findings}\n"
            "\\subsection{Data}\n"
            "No citation here.\n"
            "\\subsection{Discussion}\n"
            "Prior work \\cite{smith2024} shows this.\n"
        )

        problems, _advisories = self._run()

        self.assertIn("citation-support-ledger-missing", self._codes(problems))

    def test_support_record_with_source_quote_passes(self):
        self._write_tex(
            "\\section{Abstract}\n"
            "Prior work shows this. \\cite{smith2024}\n"
        )
        quote = "Smith et al. show the exact semantic support for this claim."
        (self.root / "references" / "smith2024.md").write_text(
            f"# Notes\n\n{quote}\n",
            encoding="utf-8",
        )
        self._write_support_ledger(
            "version: 1\n"
            "supports:\n"
            "  - id: claim:abstract\n"
            "    claim_text: Prior work shows this.\n"
            "    citations: [smith2024]\n"
            "    reviewer: Alice Zhang\n"
            "    reviewed_at: '2026-10-04'\n"
            "    verdict: supports\n"
            f"    support_quote: \"{quote}\"\n"
            "    source_path: references/smith2024.md\n"
            + self._audited("references/smith2024.md")
        )

        problems, advisories = self._run()

        self.assertEqual(self._codes(problems), set())
        self.assertNotIn("citation-support-missing", self._codes(problems))
        self.assertNotIn("citation-support-quote-not-found", self._codes(problems))
        self.assertIn("citation-support-coverage", self._codes(advisories))

    def test_support_record_without_audited_inputs_is_unbound(self):
        quote = "Smith et al. show the exact semantic support for this claim."
        self._write_tex(
            "\\section{Abstract}\n"
            "Prior work shows this. \\cite{smith2024}\n"
        )
        (self.root / "references" / "smith2024.md").write_text(
            f"# Notes\n\n{quote}\n",
            encoding="utf-8",
        )
        self._write_support_ledger(
            "version: 1\n"
            "supports:\n"
            "  - id: claim:abstract\n"
            "    claim_text: Prior work shows this.\n"
            "    citations: [smith2024]\n"
            "    reviewer: Alice Zhang\n"
            "    reviewed_at: '2026-10-04'\n"
            "    verdict: supports\n"
            f"    support_quote: \"{quote}\"\n"
            "    source_path: references/smith2024.md\n"
        )

        problems, _advisories = self._run()

        self.assertIn("citation-support-unbound", self._codes(problems))

    def test_editing_the_source_afterwards_makes_support_stale(self):
        quote = "Smith et al. show the exact semantic support for this claim."
        self._write_tex(
            "\\section{Abstract}\n"
            "Prior work shows this. \\cite{smith2024}\n"
        )
        source = self.root / "references" / "smith2024.md"
        source.write_text(f"# Notes\n\n{quote}\n", encoding="utf-8")
        self._write_support_ledger(
            "version: 1\n"
            "supports:\n"
            "  - id: claim:abstract\n"
            "    claim_text: Prior work shows this.\n"
            "    citations: [smith2024]\n"
            "    reviewer: Alice Zhang\n"
            "    reviewed_at: '2026-10-04'\n"
            "    verdict: supports\n"
            f"    support_quote: \"{quote}\"\n"
            "    source_path: references/smith2024.md\n"
            + self._audited("references/smith2024.md")
        )
        self.assertEqual(self._codes(self._run()[0]), set())

        source.write_text(
            f"# Notes\n\n{quote}\n\nAn extra sentence after the review.\n",
            encoding="utf-8",
        )

        problems, _advisories = self._run()

        self.assertIn("citation-support-stale", self._codes(problems))

    def test_quote_not_in_source_is_a_problem(self):
        self._write_tex(
            "\\section{Abstract}\n"
            "Prior work \\cite{smith2024} shows this.\n"
        )
        (self.root / "references" / "smith2024.md").write_text(
            "This source does not contain the quoted sentence.",
            encoding="utf-8",
        )
        self._write_support_ledger(
            "version: 1\n"
            "supports:\n"
            "  - id: claim:abstract\n"
            "    claim_text: Prior work supports this.\n"
            "    citations: [smith2024]\n"
            "    reviewer: Alice Zhang\n"
            "    reviewed_at: '2026-10-04'\n"
            "    verdict: supports\n"
            "    support_quote: \"A quote that does not appear in the source.\"\n"
            "    source_path: references/smith2024.md\n"
        )

        problems, _advisories = self._run()

        self.assertIn("citation-support-quote-not-found", self._codes(problems))

    def test_support_record_requires_source_path(self):
        self._write_tex(
            "\\section{Abstract}\n"
            "Prior work shows this. \\cite{smith2024}\n"
        )
        self._write_support_ledger(
            "version: 1\n"
            "supports:\n"
            "  - id: claim:abstract\n"
            "    claim_text: Prior work shows this.\n"
            "    citations: [smith2024]\n"
            "    reviewer: Alice Zhang\n"
            "    reviewed_at: '2026-10-04'\n"
            "    verdict: supports\n"
            "    support_quote: \"A quote long enough to pass the length check.\"\n"
        )

        problems, _advisories = self._run()

        self.assertIn("citation-support-source-missing", self._codes(problems))

    def test_claim_text_must_appear_in_manuscript(self):
        self._write_tex(
            "\\section{Abstract}\n"
            "A different sentence. \\cite{smith2024}\n"
        )
        quote = "Smith et al. show the exact semantic support for this claim."
        (self.root / "references" / "smith2024.md").write_text(
            f"# Notes\n\n{quote}\n",
            encoding="utf-8",
        )
        self._write_support_ledger(
            "version: 1\n"
            "supports:\n"
            "  - id: claim:abstract\n"
            "    claim_text: This sentence is not in the manuscript.\n"
            "    citations: [smith2024]\n"
            "    reviewer: Alice Zhang\n"
            "    reviewed_at: '2026-10-04'\n"
            "    verdict: supports\n"
            f"    support_quote: \"{quote}\"\n"
            "    source_path: references/smith2024.md\n"
        )

        problems, _advisories = self._run()

        self.assertIn("citation-support-claim-not-found", self._codes(problems))

    def test_claim_text_in_non_protected_section_does_not_cover(self):
        (self.root / "data" / "claims.yaml").write_text(
            "version: 1\n"
            "protected_sections:\n"
            "  - findings\n"
            "waivers: []\n",
            encoding="utf-8",
        )
        self._write_tex(
            "\\section{Method}\n"
            "This sentence lives outside the protected section.\n"
            "\\section{Findings}\n"
            "Prior work \\cite{smith2024} shows this.\n"
        )
        quote = "Smith et al. show the exact semantic support for this claim."
        (self.root / "references" / "smith2024.md").write_text(
            f"# Notes\n\n{quote}\n",
            encoding="utf-8",
        )
        self._write_support_ledger(
            "version: 1\n"
            "supports:\n"
            "  - id: claim:findings\n"
            "    claim_text: This sentence lives outside the protected section.\n"
            "    citations: [smith2024]\n"
            "    reviewer: Alice Zhang\n"
            "    reviewed_at: '2026-10-04'\n"
            "    verdict: supports\n"
            f"    support_quote: \"{quote}\"\n"
            "    source_path: references/smith2024.md\n"
        )

        problems, _advisories = self._run()

        self.assertIn("citation-support-claim-not-found", self._codes(problems))

    def test_non_string_support_verdict_is_a_problem_not_a_crash(self):
        self._write_tex(
            "\\section{Abstract}\n"
            "Prior work \\cite{smith2024} shows this.\n"
        )
        self._write_support_ledger(
            "version: 1\n"
            "supports:\n"
            "  - id: claim:abstract\n"
            "    claim_text: Prior work shows this.\n"
            "    citations: [smith2024]\n"
            "    reviewer: Alice Zhang\n"
            "    reviewed_at: '2026-10-04'\n"
            "    verdict: [supports]\n"
            "    support_quote: \"A quote long enough to pass the length check.\"\n"
            "    source_path: references/smith2024.md\n"
        )

        problems, _advisories = self._run()

        self.assertIn("citation-support-invalid-verdict", self._codes(problems))

    def test_contradicting_support_verdict_is_a_problem(self):
        self._write_tex(
            "\\section{Abstract}\n"
            "Prior work \\cite{smith2024} shows this.\n"
        )
        self._write_support_ledger(
            "version: 1\n"
            "supports:\n"
            "  - id: claim:abstract\n"
            "    claim_text: Prior work supports this.\n"
            "    citations: [smith2024]\n"
            "    reviewer: Alice Zhang\n"
            "    reviewed_at: '2026-10-04'\n"
            "    verdict: contradicts\n"
            "    support_quote: \"A quote long enough to pass the length check.\"\n"
        )

        problems, _advisories = self._run()

        self.assertIn("citation-support-not-supporting", self._codes(problems))

    def test_unknown_bib_key_is_a_problem(self):
        self._write_tex(
            "\\section{Abstract}\n"
            "Prior work \\cite{missing2024} shows this.\n"
        )
        self._write_support_ledger(
            "version: 1\n"
            "supports:\n"
            "  - id: claim:abstract\n"
            "    claim_text: Prior work supports this.\n"
            "    citations: [missing2024]\n"
            "    reviewer: Alice Zhang\n"
            "    reviewed_at: '2026-10-04'\n"
            "    verdict: supports\n"
            "    support_quote: \"A quote long enough to pass the length check.\"\n"
        )

        problems, _advisories = self._run()

        self.assertIn("citation-support-unknown-bib", self._codes(problems))

    def test_main_emits_json_and_exit_code(self):
        self._write_tex("\\section{Method}\nNo theorem here.\n")
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["argument-audit", "--paper-root", str(self.root)])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["problem_count"], 0)
        self.assertIn("proof-audit-not-needed", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
