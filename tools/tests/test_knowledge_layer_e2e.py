import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import yaml

from ccfa.library import main as library_main
from ccfa.memory import main as memory_main

REFS_BIB = r"""
@article{attention,
  title    = {注意力机制},
  author   = {Zhang, San},
  year     = {2024},
  journal  = {测试学报},
  abstract = {本文讨论推理模型与注意力机制}
}

@article{bert,
  title    = {BERT Pretraining},
  author   = {Devlin, Jacob},
  year     = {2019},
  journal  = {NAACL},
  abstract = {Bidirectional pretraining}
}

@article{gnn,
  title    = {Graph Neural Networks},
  author   = {Kipf, Thomas},
  year     = {2017},
  journal  = {ICLR},
  abstract = {Message passing on graphs}
}
"""

BRIDGE_ENTRY = r"""
@article{bridge,
  title    = {Bridge Networks},
  author   = {New, Author},
  year     = {2025},
  journal  = {TestConf},
  abstract = {A newly indexed entry}
}
"""


class KnowledgeLayerEndToEnd(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper_root = Path(self._temporary.name) / "paper"
        self.library_dir = self.paper_root / "library"
        self.notes_dir = self.library_dir / "notes"

    def _write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _run(self, command, argv):
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = command(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def _json(self, text):
        return json.loads(text)

    def _prepare_library(self):
        self._write(self.library_dir / "refs.bib", REFS_BIB)
        self._write(self.notes_dir / "attention.md", "注意力机制笔记")
        self._write(self.notes_dir / "bert.md", "BERT notes")
        self._write(self.notes_dir / "gnn.md", "GNN notes")

    def _library(self, *args):
        return self._run(
            library_main,
            ["library", "--dir", str(self.library_dir), *args],
        )

    def _memory(self, *args):
        return self._run(
            memory_main,
            ["memory", "--paper-root", str(self.paper_root), *args],
        )

    def test_library_builds_real_sqlite_and_searches_chinese_terms(self):
        self._prepare_library()

        code, stdout, stderr = self._library("index")

        self.assertEqual(code, 0)
        self.assertEqual(self._json(stdout)["entries"], 3)
        self.assertEqual(stderr, "")
        self.assertTrue((self.library_dir / "index.db").is_file())

        code, stdout, stderr = self._library("search", "注意力")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(self._json(stdout)["mode"], "fts")
        self.assertEqual(
            [entry["key"] for entry in self._json(stdout)["results"]],
            ["attention"],
        )

        code, stdout, stderr = self._library("search", "推理")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        result = self._json(stdout)
        self.assertEqual(result["mode"], "like")
        self.assertEqual([entry["key"] for entry in result["results"]], ["attention"])

        code, stdout, stderr = self._library("search", "not-present-anywhere")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(self._json(stdout)["results"], [])

    def test_library_check_accepts_a_clean_real_tree(self):
        self._prepare_library()
        self.assertEqual(self._library("index")[0], 0)

        code, stdout, stderr = self._library("check")

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(self._json(stdout)["problem_count"], 0)
        self.assertEqual(self._json(stdout)["problems"], [])

    def test_library_rejects_stale_index_and_recovers_after_rebuild(self):
        self._prepare_library()
        self.assertEqual(self._library("index")[0], 0)
        self._write(
            self.library_dir / "refs.bib",
            REFS_BIB + BRIDGE_ENTRY,
        )

        code, stdout, stderr = self._library("search", "Bridge")

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("过期", stderr)

        self.assertEqual(self._library("index")[0], 0)
        code, stdout, stderr = self._library("search", "Bridge")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            [entry["key"] for entry in self._json(stdout)["results"]],
            ["bridge"],
        )
        self.assertEqual(self._library("check")[0], 0)

    def test_library_check_reports_missing_and_stray_note_sources(self):
        self._prepare_library()
        self.assertEqual(self._library("index")[0], 0)
        (self.notes_dir / "gnn.md").unlink()
        self._write(self.notes_dir / "stray.md", "note without a bib key")

        code, stdout, stderr = self._library("check")

        self.assertEqual(code, 1)
        problems = self._json(stdout)["problems"]
        codes = {problem["code"] for problem in problems}
        self.assertIn("index-stale", codes)
        self.assertIn("note-without-entry", codes)
        self.assertIn("index-stale", stderr)
        self.assertIn("note-without-entry", stderr)

    def test_memory_check_and_search_use_real_files(self):
        self.assertEqual(
            self._memory(
                "add-idea",
                "--idea",
                "contrastive loss idea",
                "--date",
                "2026-10-03",
            )[0],
            0,
        )
        self.assertEqual(
            self._memory(
                "add-dead-end",
                "--idea",
                "contrastive replacement",
                "--reason",
                "gain came from batch size",
                "--evidence",
                "experiments/results/ablation.csv",
                "--reopen-if",
                "new negative sampling strategy",
                "--date",
                "2026-10-03",
            )[0],
            0,
        )

        code, stdout, stderr = self._memory("check")

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(self._json(stdout)["problem_count"], 0)

        code, stdout, stderr = self._memory("search", "batch size")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        result = self._json(stdout)
        self.assertEqual(result["skipped_invalid"], 0)
        self.assertEqual(result["skipped"], [])
        self.assertEqual(len(result["dead_ends"]), 1)
        self.assertEqual(
            result["dead_ends"][0]["reopen_if"],
            "new negative sampling strategy",
        )

    def test_memory_check_and_search_explain_missing_reopen_if(self):
        self.assertEqual(
            self._memory(
                "add-idea",
                "--idea",
                "kept idea",
                "--date",
                "2026-10-03",
            )[0],
            0,
        )
        self.assertEqual(
            self._memory(
                "add-dead-end",
                "--idea",
                "dead end idea",
                "--reason",
                "matching reason for search",
                "--evidence",
                "evidence.csv",
                "--reopen-if",
                "condition",
                "--date",
                "2026-10-03",
            )[0],
            0,
        )
        dead_ends_path = self.paper_root / "memory" / "dead-ends.md"
        entries = yaml.safe_load(dead_ends_path.read_text(encoding="utf-8"))
        del entries[0]["reopen_if"]
        dead_ends_path.write_text(
            yaml.safe_dump(entries, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        code, stdout, stderr = self._memory("check")

        self.assertEqual(code, 1)
        self.assertIn("DE1", stderr)
        self.assertIn("deadend-missing-reopen-if", stderr)
        self.assertIn(
            "deadend-missing-reopen-if",
            {problem["code"] for problem in self._json(stdout)["problems"]},
        )

        code, stdout, stderr = self._memory("search", "matching reason")
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        result = self._json(stdout)
        self.assertEqual(result["skipped_invalid"], 1)
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["file"], "memory/dead-ends.md")
        self.assertEqual(result["skipped"][0]["id"], "DE1")
        self.assertIn(
            "deadend-missing-reopen-if",
            result["skipped"][0]["codes"],
        )
        self.assertEqual(result["dead_ends"], [])


if __name__ == "__main__":
    unittest.main()
