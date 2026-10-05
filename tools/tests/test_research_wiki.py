import tempfile
import unittest
from pathlib import Path

from ccfa.research_wiki import (
    add_edge,
    append_log,
    build_index,
    check_wiki,
    query_pack,
    rebuild_catalog,
    search_index,
    sync_bibliography,
)


ENTRY = """\
---
id: rw:001
kind: decision
title: Use a dedicated artifact badge ledger
status: active
tags: [artifact, reproducibility]
projects: [example-paper]
evidence: [run:RUN1, url:https://example.test/report]
related: []
updated_at: '2026-10-05'
---

# Decision

Keep artifact badge evidence machine readable.
"""


class ResearchWikiTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.wiki = Path(self._temporary.name)
        (self.wiki / "README.md").write_text("# Wiki\n", encoding="utf-8")

    def _write_entry(self, name: str, text: str = ENTRY) -> Path:
        path = self.wiki / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_valid_entry_passes(self):
        self._write_entry("decision.md")

        problems, advisories = check_wiki(self.wiki)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_duplicate_id_is_problem(self):
        self._write_entry("one.md")
        self._write_entry(
            "two.md",
            ENTRY.replace("title: Use a dedicated", "title: Duplicate"),
        )

        problems, _advisories = check_wiki(self.wiki)

        self.assertIn(
            "research-wiki-duplicate-id",
            [problem.code for problem in problems],
        )

    def test_invalid_enum_is_problem(self):
        self._write_entry(
            "bad.md",
            ENTRY.replace("kind: decision", "kind: mystery"),
        )

        problems, _advisories = check_wiki(self.wiki)

        self.assertIn(
            "research-wiki-invalid",
            [problem.code for problem in problems],
        )

    def test_missing_fields_is_problem(self):
        self._write_entry(
            "missing.md",
            ENTRY.replace("title: Use a dedicated artifact badge ledger\n", ""),
        )

        problems, _advisories = check_wiki(self.wiki)

        self.assertIn(
            "research-wiki-missing-field",
            [problem.code for problem in problems],
        )

    def test_unknown_related_link_is_problem(self):
        self._write_entry(
            "bad-link.md",
            ENTRY.replace("related: []", "related: [rw:404]"),
        )

        problems, _advisories = check_wiki(self.wiki)

        self.assertIn(
            "research-wiki-unknown-link",
            [problem.code for problem in problems],
        )

    def test_bad_evidence_is_problem(self):
        self._write_entry(
            "bad-evidence.md",
            ENTRY.replace("evidence: [run:RUN1, url:https://example.test/report]", "evidence: [doi:not-a-doi]"),
        )

        problems, _advisories = check_wiki(self.wiki)

        self.assertIn(
            "research-wiki-invalid-evidence",
            [problem.code for problem in problems],
        )

    def test_index_and_search(self):
        self._write_entry("decision.md")

        index = build_index(self.wiki)

        self.assertEqual(index["entry_count"], 1)
        self.assertEqual(index["entries"][0]["id"], "rw:001")
        self.assertEqual(
            search_index(index, "artifact badge")[0]["id"],
            "rw:001",
        )

    def test_missing_wiki_directory_is_problem(self):
        missing = self.wiki / "missing"

        problems, _advisories = check_wiki(missing)

        self.assertIn(
            "research-wiki-missing",
            [problem.code for problem in problems],
        )

    def test_typed_edge_resolves_and_is_indexed(self):
        self._write_entry("one.md")
        self._write_entry(
            "two.md",
            ENTRY.replace("id: rw:001", "id: rw:002")
            .replace("kind: decision", "kind: experiment")
            .replace("related: []", "related: [rw:001]"),
        )
        graph = self.wiki / "graph"
        graph.mkdir()
        (graph / "edges.jsonl").write_text(
            '{"from":"rw:002","to":"rw:001","type":"tested_by","evidence":"run:RUN1"}\n',
            encoding="utf-8",
        )

        problems, _advisories = check_wiki(self.wiki)
        index = build_index(self.wiki)

        self.assertEqual(problems, [])
        self.assertEqual(index["edge_count"], 1)
        self.assertEqual(index["edges"][0]["type"], "tested_by")

    def test_invalid_edge_type_and_endpoint_are_problems(self):
        self._write_entry("one.md")
        graph = self.wiki / "graph"
        graph.mkdir()
        (graph / "edges.jsonl").write_text(
            '{"from":"rw:001","to":"rw:404","type":"mystery","evidence":"run:RUN1"}\n',
            encoding="utf-8",
        )

        problems, _advisories = check_wiki(self.wiki)

        codes = [problem.code for problem in problems]
        self.assertIn("research-wiki-invalid-edge-type", codes)
        self.assertIn("research-wiki-unknown-edge-endpoint", codes)

    def test_add_edge_appends_and_query_pack_summarizes(self):
        self._write_entry("one.md")
        self._write_entry(
            "two.md",
            ENTRY.replace("id: rw:001", "id: rw:002")
            .replace("title: Use a dedicated artifact badge ledger", "title: New idea")
            .replace("kind: decision", "kind: idea"),
        )

        edge = add_edge(
            self.wiki,
            from_id="rw:002",
            to_id="rw:001",
            edge_type="inspired_by",
            evidence="file:notes.md",
        )
        pack = query_pack(self.wiki)

        self.assertEqual(edge["type"], "inspired_by")
        self.assertIn("inspired_by", pack)
        self.assertIn("rw:001", pack)

    def test_sync_bibliography_creates_paper_cards(self):
        bib = self.wiki / "refs.bib"
        bib.write_text(
            "@article{demo2026,\n"
            "  title={Demo Paper},\n"
            "  author={Doe, Jane},\n"
            "  year={2026},\n"
            "}\n",
            encoding="utf-8",
        )

        first = sync_bibliography(self.wiki, bib)
        second = sync_bibliography(self.wiki, bib)

        self.assertEqual(first["created"], ["paper:demo2026"])
        self.assertEqual(second["created"], [])
        self.assertTrue((self.wiki / "papers" / "demo2026.md").is_file())

    def test_rebuild_catalog_and_log(self):
        self._write_entry("one.md")
        self._write_entry(
            "gap.md",
            ENTRY.replace("id: rw:001", "id: gap:1")
            .replace("kind: decision", "kind: gap")
            .replace("title: Use a dedicated artifact badge ledger", "title: Missing evaluation"),
        )

        result = rebuild_catalog(self.wiki)
        append_log(self.wiki, "catalog rebuilt")

        self.assertIn("index.md", result["files"])
        self.assertIn("gap_map.md", result["files"])
        self.assertIn("Missing evaluation", (self.wiki / "gap_map.md").read_text(encoding="utf-8"))
        self.assertIn("catalog rebuilt", (self.wiki / "log.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
