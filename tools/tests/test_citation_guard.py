import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from ccfa.citation_guard import check, main

BIB = r"""
@misc{good, doi = {10.1/ok}}
@misc{unverified, doi = {10.1/unverified}}
@misc{orphan, doi = {10.1/orphan}}
@misc{dupa, doi = {10.1/same}}
@misc{dupb, doi = {10.1/same}}
"""


def _evidence(sha=None):
    return {
        "body_sha256": "sha256:" + (sha or "a" * 64),
        "retrieved_at": "2026-10-04T00:00:00Z",
        "matched_title": "Sample Title",
        "source": "crossref",
    }


LEDGER = {
    "version": 1,
    "entries": {
        "good": {
            "status": "verified",
            "doi": "10.1/ok",
            "evidence": _evidence(),
        },
        "unverified": {"status": "unverified", "doi": "10.1/unverified"},
        "orphan": {
            "status": "verified",
            "doi": "10.1/orphan",
            "evidence": _evidence(),
        },
        "dupa": {
            "status": "verified",
            "doi": "10.1/same",
            "evidence": _evidence(),
        },
        "dupb": {
            "status": "verified",
            "doi": "10.1/same",
            "evidence": _evidence(),
        },
    },
}


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "manuscript").mkdir()
        self.bib = self.root / "references.bib"
        self.bib.write_text(BIB, encoding="utf-8")
        self.ledger = self.root / "citation-ledger.json"
        self.ledger.write_text(json.dumps(LEDGER), encoding="utf-8")

    def cite(self, body: str):
        (self.root / "manuscript" / "main.tex").write_text(body, encoding="utf-8")

    def run_check(self):
        return check(self.root / "manuscript", self.bib, self.ledger)

    @staticmethod
    def codes(problems):
        return sorted(p.code for p in problems)


class TestCheck(BaseCase):
    def test_clean_manuscript_has_no_problems(self):
        # 用一份全部已核验的最小语料。共享 fixture 里含有故意置为 unverified
        # 的条目，而守卫要求 bib 中每个条目都已核验——不论是否被引用。
        self.bib.write_text("@misc{good, doi = {10.1/ok}}\n", encoding="utf-8")
        self.ledger.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": {
                        "good": {
                            "status": "verified",
                            "evidence": _evidence(),
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        self.cite(r"\cite{good}")
        problems, advisories = self.run_check()
        self.assertEqual(problems, [], problems)
        self.assertEqual(advisories, [])

    def test_dangling_cite_is_a_problem_with_location(self):
        self.cite(r"\cite{ghost}")
        problems, _ = self.run_check()
        self.assertIn("dangling-cite", self.codes(problems))
        dangling = [p for p in problems if p.code == "dangling-cite"][0]
        self.assertIn("ghost", dangling.message)
        self.assertEqual(dangling.line, 1)
        self.assertTrue(dangling.path.endswith("main.tex"))

    def test_unverified_entry_is_a_problem(self):
        self.cite(r"\cite{good} \cite{unverified}")
        problems, _ = self.run_check()
        self.assertIn("unverified-entry", self.codes(problems))

    def test_entry_missing_from_ledger_is_a_problem(self):
        self.cite(r"\cite{good}")
        self.ledger.write_text(json.dumps({"version": 1, "entries": {}}), encoding="utf-8")
        problems, _ = self.run_check()
        self.assertIn("unverified-entry", self.codes(problems))

    def test_duplicate_doi_is_a_problem(self):
        self.cite(r"\cite{good} \cite{dupa} \cite{dupb}")
        problems, _ = self.run_check()
        self.assertIn("duplicate-doi", self.codes(problems))

    def test_orphan_entry_is_only_an_advisory(self):
        self.cite(r"\cite{good}")
        problems, advisories = self.run_check()
        self.assertNotIn("orphan-entry", self.codes(problems))
        self.assertIn("orphan-entry", self.codes(advisories))

    def test_entry_without_doi_is_not_a_duplicate(self):
        self.bib.write_text("@misc{a, title={A}}\n@misc{b, title={B}}\n", encoding="utf-8")
        self.ledger.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": {
                        "a": {"status": "verified", "evidence": _evidence()},
                        "b": {"status": "verified", "evidence": _evidence()},
                    },
                }
            ),
            encoding="utf-8",
        )
        self.cite(r"\cite{a} \cite{b}")
        problems, _ = self.run_check()
        self.assertNotIn("duplicate-doi", self.codes(problems))

    def test_verified_without_evidence_is_self_asserted(self):
        self.bib.write_text("@misc{good, doi = {10.1/ok}}\n", encoding="utf-8")
        self.ledger.write_text(
            json.dumps(
                {"version": 1, "entries": {"good": {"status": "verified"}}}
            ),
            encoding="utf-8",
        )
        self.cite(r"\cite{good}")

        problems, _ = self.run_check()

        self.assertIn("citation-self-asserted", self.codes(problems))
        self.assertNotIn("unverified-entry", self.codes(problems))

    def test_tampered_evidence_is_self_asserted(self):
        self.bib.write_text("@misc{good, doi = {10.1/ok}}\n", encoding="utf-8")
        self.ledger.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": {
                        "good": {
                            "status": "verified",
                            "evidence": _evidence(sha="not-a-valid-hash"),
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        self.cite(r"\cite{good}")

        problems, _ = self.run_check()

        self.assertIn("citation-self-asserted", self.codes(problems))


class TestMain(BaseCase):
    def test_clean_run_exits_zero(self):
        # 共享 fixture 含故意未核验与重复 DOI 的条目，无法干净退出；
        # 与 TestCheck.test_clean_manuscript_has_no_problems 用同一最小语料。
        self.bib.write_text("@misc{good, doi = {10.1/ok}}\n", encoding="utf-8")
        self.ledger.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": {
                        "good": {
                            "status": "verified",
                            "evidence": _evidence(),
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        self.cite(r"\cite{good}")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(
                [
                    "citation_guard.py",
                    "--manuscript",
                    str(self.root / "manuscript"),
                    "--bib",
                    str(self.bib),
                    "--ledger",
                    str(self.ledger),
                ]
            )
        self.assertEqual(code, 0)

    def test_problem_run_exits_one(self):
        self.cite(r"\cite{ghost}")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(
                [
                    "citation_guard.py",
                    "--manuscript",
                    str(self.root / "manuscript"),
                    "--bib",
                    str(self.bib),
                    "--ledger",
                    str(self.ledger),
                ]
            )
        self.assertEqual(code, 1)

    def test_missing_bib_exits_two(self):
        self.cite(r"\cite{good}")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(
                [
                    "citation_guard.py",
                    "--manuscript",
                    str(self.root / "manuscript"),
                    "--bib",
                    str(self.root / "nope.bib"),
                    "--ledger",
                    str(self.ledger),
                ]
            )
        self.assertEqual(code, 2)

    def test_missing_manuscript_exits_two(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(
                [
                    "citation_guard.py",
                    "--manuscript",
                    str(self.root / "nope"),
                    "--bib",
                    str(self.bib),
                    "--ledger",
                    str(self.ledger),
                ]
            )
        self.assertEqual(code, 2)

    def test_self_asserted_verified_exits_one(self):
        self.bib.write_text("@misc{good, doi = {10.1/ok}}\n", encoding="utf-8")
        self.ledger.write_text(
            json.dumps(
                {"version": 1, "entries": {"good": {"status": "verified"}}}
            ),
            encoding="utf-8",
        )
        self.cite(r"\cite{good}")

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(
                [
                    "citation_guard.py",
                    "--manuscript",
                    str(self.root / "manuscript"),
                    "--bib",
                    str(self.bib),
                    "--ledger",
                    str(self.ledger),
                ]
            )

        self.assertEqual(code, 1)


class TestVerifyOnline(BaseCase):
    def test_online_flag_is_off_by_default(self):
        self.cite(r"\cite{good}")
        problems, _ = check(self.root / "manuscript", self.bib, self.ledger)
        self.assertNotIn("doi-not-found", self.codes(problems))

    def test_online_flag_reports_a_dead_doi(self):
        self.cite(r"\cite{good}")
        import ccfa.citation_guard as guard
        from ccfa.doi_lookup import LookupResult

        def fake_lookup(
            doi,
            fetch=None,
            timeout=20.0,
            *,
            expected_title=None,
        ):
            return LookupResult(doi, False, None, "crossref: HTTP 404")

        original = guard.lookup
        guard.lookup = fake_lookup
        try:
            problems, _ = check(
                self.root / "manuscript", self.bib, self.ledger, verify_online=True
            )
        finally:
            guard.lookup = original
        self.assertIn("doi-not-found", self.codes(problems))

    def test_online_verification_writes_evidence_to_the_ledger(self):
        self.cite(r"\cite{good}")
        import ccfa.citation_guard as guard
        from ccfa.citation_ledger import load_ledger
        from ccfa.doi_lookup import LookupEvidence, LookupResult

        evidence = LookupEvidence(
            body_sha256="sha256:" + "c" * 64,
            retrieved_at="2026-10-04T01:02:03Z",
            matched_title="A Real Paper",
            source="crossref",
        )

        def fake_lookup(
            doi,
            fetch=None,
            timeout=20.0,
            *,
            expected_title=None,
        ):
            return LookupResult(
                doi,
                True,
                "crossref",
                "crossref 返回 200 且 DOI 匹配",
                evidence,
            )

        original = guard.lookup
        guard.lookup = fake_lookup
        try:
            problems, _ = check(
                self.root / "manuscript",
                self.bib,
                self.ledger,
                verify_online=True,
            )
        finally:
            guard.lookup = original

        self.assertNotIn("doi-not-found", self.codes(problems))
        self.assertNotIn("citation-self-asserted", self.codes(problems))
        record = load_ledger(self.ledger)["good"]
        self.assertEqual(record.status, "verified")
        self.assertEqual(
            record.evidence.body_sha256,
            "sha256:" + "c" * 64,
        )
        self.assertEqual(record.evidence.matched_title, "A Real Paper")

    def test_online_mismatch_marks_the_ledger_failed(self):
        self.cite(r"\cite{good}")
        import ccfa.citation_guard as guard
        from ccfa.citation_ledger import load_ledger
        from ccfa.doi_lookup import LookupResult

        def fake_lookup(
            doi,
            fetch=None,
            timeout=20.0,
            *,
            expected_title=None,
        ):
            return LookupResult(
                doi,
                False,
                "crossref",
                "doi mismatch",
                None,
                True,
            )

        original = guard.lookup
        guard.lookup = fake_lookup
        try:
            problems, _ = check(
                self.root / "manuscript",
                self.bib,
                self.ledger,
                verify_online=True,
            )
        finally:
            guard.lookup = original

        self.assertIn("doi-lookup-failed", self.codes(problems))
        record = load_ledger(self.ledger)["good"]
        self.assertEqual(record.status, "failed")
        self.assertIsNone(record.evidence)
        self.assertEqual(record.detail, "doi mismatch")

    def test_real_lookup_round_trips_through_the_ledger(self):
        body = json.dumps(
            {
                "message": {
                    "DOI": "10.1/ok",
                    "title": ["A Real Paper"],
                }
            }
        )
        self.bib.write_text(
            '@misc{good, doi = {10.1/ok}, title = {A Real Paper}}\n',
            encoding="utf-8",
        )
        self.ledger.write_text(
            json.dumps({"version": 1, "entries": {}}),
            encoding="utf-8",
        )
        self.cite(r"\cite{good}")
        from ccfa.citation_ledger import load_ledger

        def fetch(url, timeout):
            return 200, body

        problems, _ = check(
            self.root / "manuscript",
            self.bib,
            self.ledger,
            verify_online=True,
            fetch=fetch,
        )

        self.assertEqual(problems, [], problems)
        record = load_ledger(self.ledger)["good"]
        self.assertEqual(record.status, "verified")
        self.assertEqual(
            record.evidence.body_sha256,
            "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(record.evidence.matched_title, "A Real Paper")

        read_problems, _ = check(
            self.root / "manuscript",
            self.bib,
            self.ledger,
        )

        self.assertEqual(read_problems, [], read_problems)
        self.assertNotIn(
            "citation-self-asserted",
            self.codes(read_problems),
        )

    def test_missing_provider_title_never_writes_unreadable_evidence(self):
        body = json.dumps({"message": {"DOI": "10.1/ok", "title": []}})
        self.bib.write_text(
            "@misc{good, doi = {10.1/ok}}\n",
            encoding="utf-8",
        )
        self.ledger.write_text(
            json.dumps({"version": 1, "entries": {}}),
            encoding="utf-8",
        )
        self.cite(r"\cite{good}")
        from ccfa.citation_ledger import load_ledger

        def fetch(url, timeout):
            return 200, body

        problems, _ = check(
            self.root / "manuscript",
            self.bib,
            self.ledger,
            verify_online=True,
            fetch=fetch,
        )

        self.assertIn("doi-lookup-failed", self.codes(problems))
        record = load_ledger(self.ledger)["good"]
        self.assertEqual(record.status, "failed")
        self.assertIsNone(record.evidence)
        self.assertEqual(record.detail, "title missing")

        read_problems, _ = check(
            self.root / "manuscript",
            self.bib,
            self.ledger,
        )

        self.assertNotIn(
            "citation-self-asserted",
            self.codes(read_problems),
        )
        self.assertIn("unverified-entry", self.codes(read_problems))

    def test_both_sources_missing_is_doi_not_found(self):
        self.bib.write_text(
            "@misc{good, doi = {10.1/missing}}\n",
            encoding="utf-8",
        )
        self.ledger.write_text(
            json.dumps({"version": 1, "entries": {}}),
            encoding="utf-8",
        )
        self.cite(r"\cite{good}")
        from ccfa.citation_ledger import load_ledger

        def fetch(url, timeout):
            return 404, b""

        problems, _ = check(
            self.root / "manuscript",
            self.bib,
            self.ledger,
            verify_online=True,
            fetch=fetch,
        )

        self.assertIn("doi-not-found", self.codes(problems))
        self.assertNotIn("doi-lookup-failed", self.codes(problems))
        record = load_ledger(self.ledger)["good"]
        self.assertEqual(record.status, "failed")
        self.assertIn("HTTP 404", record.detail)

    def test_provider_doi_mismatch_is_doi_lookup_failed(self):
        body = json.dumps(
            {
                "message": {
                    "DOI": "10.1/other",
                    "title": ["A Real Paper"],
                }
            }
        )
        self.bib.write_text(
            '@misc{good, doi = {10.1/ok}, title = {A Real Paper}}\n',
            encoding="utf-8",
        )
        self.ledger.write_text(
            json.dumps({"version": 1, "entries": {}}),
            encoding="utf-8",
        )
        self.cite(r"\cite{good}")
        from ccfa.citation_ledger import load_ledger

        def fetch(url, timeout):
            return 200, body

        problems, _ = check(
            self.root / "manuscript",
            self.bib,
            self.ledger,
            verify_online=True,
            fetch=fetch,
        )

        self.assertIn("doi-lookup-failed", self.codes(problems))
        self.assertNotIn("doi-not-found", self.codes(problems))
        self.assertEqual(load_ledger(self.ledger)["good"].status, "failed")
        message = next(
            item.message
            for item in problems
            if item.code == "doi-lookup-failed"
        )
        self.assertIn("doi mismatch", message)
