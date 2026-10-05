"""One-stop workflow regression on real derived paper projects.

Every tool invocation runs as a real subprocess from a neutral working
directory outside the repository, with explicit project paths. This proves
the toolchain does not depend on the repository root as its cwd.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from newpaper.checklists import render_checklist
from newpaper.create import create_project

from . import request_venue_library

TOOLS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TOOLS_ROOT.parent


class WorkflowEndToEnd(unittest.TestCase):
    def setUp(self):
        request_venue_library(self)
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.papers = self.root / "papers"
        self.neutral_cwd = self.root / "neutral-cwd"
        self.neutral_cwd.mkdir()
        self.env = dict(os.environ)
        self.env["PYTHONPATH"] = str(TOOLS_ROOT)
        self.conference = self._derive("workflow-conference", "conference")
        self.journal = self._derive("workflow-journal", "journal")

    def _derive(self, slug: str, mode: str, deadline: str | None = None) -> Path:
        return create_project(
            papers_root=self.papers,
            slug=slug,
            venue="NeurIPS",
            year="2027",
            mode=mode,
            title=f"{slug} workflow",
            deadline=deadline,
        )

    def _run(self, module: str, *args: str):
        return subprocess.run(
            [sys.executable, "-m", module, *args],
            cwd=str(self.neutral_cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self.env,
        )

    def _state(self, root: Path) -> dict:
        return yaml.safe_load(
            (root / "ccfa.yaml").read_text(encoding="utf-8")
        )

    def _assert_initial_state(self, root: Path, mode: str) -> dict:
        state = self._state(root)
        self.assertEqual(state["target_venue"]["mode"], mode)
        self.assertEqual(state["stage"]["current"], "idea")
        self.assertEqual(state["stage"]["gate"], "scope_defined")
        self.assertRegex(
            state["stage"]["updated_at"],
            r"^\d{4}-\d{2}-\d{2}$",
        )
        self.assertIsNone(state["target_venue"]["deadline"])
        return state

    def _memory_add_and_check(self, root: Path) -> dict:
        added = self._run(
            "ccfa.memory",
            "--paper-root",
            str(root),
            "add-idea",
            "--idea",
            "一站式工作流集成想法",
            "--date",
            "2026-10-03",
        )
        self.assertEqual(added.returncode, 0, added.stderr)
        entry = json.loads(added.stdout)
        self.assertEqual(entry["id"], "I1")

        checked = self._run(
            "ccfa.memory",
            "--paper-root",
            str(root),
            "check",
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout)["problem_count"], 0)
        return entry

    def _run_log_execute(self, root: Path) -> dict:
        log_dir = root / "experiments" / "log"
        executed = self._run(
            "ccfa.run_log",
            "--log-dir",
            str(log_dir),
            "--paper-root",
            str(root),
            "run",
            "--",
            sys.executable,
            "-c",
            "print('WORKFLOW_RUN_MARKER')",
        )
        self.assertEqual(executed.returncode, 0, executed.stderr)
        self.assertIn("WORKFLOW_RUN_MARKER", executed.stdout)

        records = sorted(log_dir.glob("*.json"))
        self.assertEqual(len(records), 1)
        record = json.loads(records[0].read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["exit_code"], 0)
        self.assertEqual(record["cwd"], ".")
        return record

    def _seed_provenance_input(self, root: Path) -> Path:
        csv = root / "data" / "raw.csv"
        csv.write_text("a,b\n1,2\n", encoding="utf-8")
        return csv

    def _provenance_add_and_check(self, root: Path) -> dict:
        store = root / "data" / "provenance.json"
        added = self._run(
            "ccfa.provenance",
            "--store",
            str(store),
            "--paper-root",
            str(root),
            "add",
            "data/raw.csv",
            "--source",
            "internal export",
            "--classification",
            "real",
        )
        self.assertEqual(added.returncode, 0, added.stderr)

        checked = self._run(
            "ccfa.provenance",
            "--store",
            str(store),
            "--paper-root",
            str(root),
            "check",
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout)["problem_count"], 0)
        payload = json.loads(store.read_text(encoding="utf-8"))
        self.assertIn("data/raw.csv", payload["files"])
        return payload

    def _seed_library(self, root: Path) -> Path:
        library_dir = root / "library"
        (library_dir / "notes").mkdir(parents=True, exist_ok=True)
        bibliography = root / "manuscript" / "references.bib"
        bibliography.write_text(
            "@article{attention,\n"
            "  title = {注意力机制的可复现研究},\n"
            "  author = {Zhang, San},\n"
            "  year = {2026},\n"
            "  journal = {TestConf},\n"
            "  abstract = {本文讨论推理模型的复现性}\n"
            "}\n",
            encoding="utf-8",
        )
        shutil.copy2(bibliography, library_dir / "refs.bib")
        (library_dir / "notes" / "attention.md").write_text(
            "注意力机制的实验笔记\n",
            encoding="utf-8",
        )
        return library_dir

    def _library_index_and_search(self, root: Path) -> dict:
        library_dir = root / "library"
        indexed = self._run(
            "ccfa.library",
            "--dir",
            str(library_dir),
            "index",
        )
        self.assertEqual(indexed.returncode, 0, indexed.stderr)
        self.assertEqual(json.loads(indexed.stdout)["entries"], 1)

        searched = self._run(
            "ccfa.library",
            "--dir",
            str(library_dir),
            "search",
            "注意",
        )
        self.assertEqual(searched.returncode, 0, searched.stderr)
        payload = json.loads(searched.stdout)
        self.assertEqual(payload["mode"], "like")
        self.assertEqual(
            [row["key"] for row in payload["results"]],
            ["attention"],
        )
        return payload

    def _full_chain(self, root: Path) -> None:
        self._seed_provenance_input(root)
        self._seed_library(root)
        self._memory_add_and_check(root)
        self._run_log_execute(root)
        self._provenance_add_and_check(root)
        self._library_index_and_search(root)

    def _snapshot(self, root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_conference_state_matches_template(self):
        self._assert_initial_state(self.conference, "conference")

    def test_journal_state_matches_template(self):
        self._assert_initial_state(self.journal, "journal")

    def test_deadline_round_trips_in_state(self):
        root = self._derive(
            "workflow-deadline",
            "conference",
            deadline="2027-05-01",
        )
        state = self._state(root)
        self.assertEqual(state["target_venue"]["deadline"], "2027-05-01")

    def test_checklists_cover_distinct_mode_tails(self):
        conference = render_checklist("conference")
        journal = render_checklist("journal")

        self.assertIn("[rebuttal]", conference)
        self.assertIn("[camera-ready]", conference)
        self.assertIn("[major-revision]", journal)
        self.assertIn("[response-letter]", journal)
        self.assertNotIn("[major-revision]", conference)
        self.assertNotIn("[camera-ready]", journal)
        self.assertNotEqual(conference, journal)

    def test_memory_add_idea_and_then_check(self):
        self._memory_add_and_check(self.conference)
        text = (self.conference / "memory" / "ideas.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("一站式工作流集成想法", text)

    def test_run_log_records_real_child_command(self):
        self._run_log_execute(self.conference)

    def test_provenance_add_and_then_check(self):
        self._seed_provenance_input(self.conference)
        self._provenance_add_and_check(self.conference)

    def test_library_two_character_chinese_query_uses_like(self):
        self._seed_library(self.conference)
        self._library_index_and_search(self.conference)

    def test_full_chain_runs_from_a_neutral_cwd(self):
        self.assertFalse(self.neutral_cwd.is_relative_to(REPO_ROOT))
        neutral_before = self._snapshot(self.neutral_cwd)

        self._full_chain(self.conference)

        neutral_after = self._snapshot(self.neutral_cwd)
        self.assertEqual(
            neutral_before,
            neutral_after,
            "工具在 cwd 中产生了文件，说明依赖了仓库根/相对路径",
        )
        self.assertIn(
            "一站式工作流集成想法",
            (self.conference / "memory" / "ideas.md").read_text(
                encoding="utf-8"
            ),
        )
        self.assertEqual(
            len(list((self.conference / "experiments" / "log").glob("*.json"))),
            1,
        )
        provenance = json.loads(
            (self.conference / "data" / "provenance.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("data/raw.csv", provenance["files"])
        self.assertTrue((self.conference / "library" / "index.db").is_file())

    def test_tool_chain_does_not_overwrite_other_outputs(self):
        self._seed_provenance_input(self.conference)
        self._seed_library(self.conference)
        before = self._snapshot(self.conference)

        self._full_chain(self.conference)

        after = self._snapshot(self.conference)
        changed = {
            relative
            for relative in set(before) | set(after)
            if before.get(relative) != after.get(relative)
        }
        run_log_entries = {
            relative
            for relative in changed
            if relative.startswith("experiments/log/")
        }
        self.assertEqual(len(run_log_entries), 1)
        self.assertEqual(
            changed - run_log_entries,
            {
                "memory/ideas.md",
                "data/provenance.json",
                "library/index.db",
            },
        )
        self.assertEqual(before["ccfa.yaml"], after["ccfa.yaml"])
        self.assertEqual(
            before["manuscript/references.bib"],
            after["manuscript/references.bib"],
        )


if __name__ == "__main__":
    unittest.main()
