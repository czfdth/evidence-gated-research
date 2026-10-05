import tempfile
import unittest
from pathlib import Path

from ccfa.novelty import check


def _neighbor(identifier):
    return (
        f"  - id: {identifier}\n"
        f"    title: Related work {identifier}\n"
        "    venue: ExampleConf 2025\n"
        "    overlap: Shares the same threat model.\n"
        "    difference: Adds a new measurement on retrieval defenses.\n"
        "    claim_ids: [claim:main]\n"
    )


VALID = (
    "version: 1\n"
    "search:\n"
    "  databases: [semantic-scholar, arxiv, openreview]\n"
    "  queries: ['RAG security', 'retrieval attack']\n"
    "  searched_at: '2026-10-05'\n"
    "  cutoff: '2026-10-01'\n"
    "neighbors:\n"
    + _neighbor("a2025")
    + _neighbor("b2025")
    + _neighbor("c2025")
    + "claims: [claim:main]\n"
)


class NoveltyTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "data").mkdir()
        (self.root / "manuscript").mkdir()
        self.path = self.root / "data" / "novelty-audit.yaml"
        self.path.write_text(VALID, encoding="utf-8")
        (self.root / "manuscript" / "references.bib").write_text(
            "@misc{a2025, title={A}}\n"
            "@misc{b2025, title={B}}\n"
            "@misc{c2025, title={C}}\n",
            encoding="utf-8",
        )

    @staticmethod
    def _codes(problems):
        return {problem.code for problem in problems}

    def test_valid_audit_passes(self):
        problems, _advisories = check(self.root)
        self.assertEqual(problems, [])

    def test_thin_neighbor_list_is_a_problem(self):
        self.path.write_text(
            VALID.replace(_neighbor("c2025"), ""),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("novelty-thin-neighbors", self._codes(problems))

    def test_single_database_is_a_problem(self):
        self.path.write_text(
            VALID.replace(
                "[semantic-scholar, arxiv, openreview]",
                "[arxiv]",
            ),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("novelty-thin-search", self._codes(problems))

    def test_duplicate_database_is_a_problem(self):
        self.path.write_text(
            VALID.replace(
                "[semantic-scholar, arxiv, openreview]",
                "[arxiv, arxiv]",
            ),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("novelty-duplicate-database", self._codes(problems))

    def test_duplicate_claim_is_a_problem(self):
        self.path.write_text(
            VALID.replace(
                "claims: [claim:main]",
                "claims: [claim:main, claim:main]",
            ),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("novelty-duplicate-claim", self._codes(problems))

    def test_unknown_neighbor_is_a_problem(self):
        self.path.write_text(
            VALID.replace("id: a2025", "id: missing2025"),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("novelty-unknown-neighbor", self._codes(problems))

    def test_unknown_claim_id_is_a_problem(self):
        self.path.write_text(
            VALID.replace(
                "claim_ids: [claim:main]",
                "claim_ids: [claim:missing]",
            ),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("novelty-unknown-claim", self._codes(problems))

    def test_duplicate_neighbor_title_is_a_problem(self):
        self.path.write_text(
            VALID.replace(
                "    title: Related work a2025\n",
                "    title: Duplicate Title\n",
            )
            .replace(
                "    title: Related work b2025\n",
                "    title: Duplicate Title\n",
            ),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn(
            "novelty-duplicate-neighbor-title",
            self._codes(problems),
        )

    def test_unsupported_no_one_has_done_phrase_is_a_problem(self):
        self.path.write_text(
            VALID.replace(
                "Adds a new measurement on retrieval defenses.",
                "No one has done this before.",
            ),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("novelty-unsupported-claim", self._codes(problems))

    def test_uncovered_claim_is_a_problem(self):
        self.path.write_text(
            VALID.replace("claims: [claim:main]", "claims: [claim:main, claim:second]"),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("novelty-uncovered-claim", self._codes(problems))

    def test_cutoff_after_search_date_is_a_problem(self):
        self.path.write_text(
            VALID.replace("cutoff: '2026-10-01'", "cutoff: '2026-10-06'"),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("novelty-invalid", self._codes(problems))

    def test_compact_iso_date_is_invalid(self):
        self.path.write_text(
            VALID.replace("searched_at: '2026-10-05'", "searched_at: '20261005'"),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("novelty-invalid", self._codes(problems))


if __name__ == "__main__":
    unittest.main()
