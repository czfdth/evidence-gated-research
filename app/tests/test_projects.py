import tempfile
import unittest
from datetime import date
from pathlib import Path

import yaml

from ccfa_core.projects import (
    ProjectError,
    ProjectState,
    deadline_note,
    find_projects,
    gate_for,
    load_project,
)

from . import write_project


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def test_missing_papers_directory_is_empty(self):
        self.assertEqual(find_projects(self.root), [])

    def test_empty_papers_directory_is_empty(self):
        (self.root / "papers").mkdir()
        self.assertEqual(find_projects(self.root), [])

    def test_finds_valid_projects_sorted(self):
        write_project(self.root, "beta")
        write_project(self.root, "alpha")

        refs = find_projects(self.root)

        self.assertEqual([ref.slug for ref in refs], ["alpha", "beta"])
        self.assertTrue(all(ref.error is None for ref in refs))
        self.assertEqual(refs[0].dir, self.root / "papers" / "alpha")

    def test_bad_project_is_isolated_from_good_projects(self):
        write_project(self.root, "good")
        bad_dir = self.root / "papers" / "bad"
        bad_dir.mkdir(parents=True)
        (bad_dir / "ccfa.yaml").write_text(": [unclosed\n", encoding="utf-8")

        refs = find_projects(self.root)
        by_slug = {ref.slug: ref for ref in refs}

        self.assertIsNone(by_slug["good"].error)
        self.assertTrue(by_slug["bad"].error)
        self.assertIn("bad", by_slug["bad"].error)

    def test_directory_without_ccfa_yaml_is_ignored(self):
        (self.root / "papers" / "draft").mkdir(parents=True)
        self.assertEqual(find_projects(self.root), [])

    def test_load_project_reads_fields(self):
        project_dir = write_project(
            self.root,
            "demo",
            mode="journal",
            stage="major-revision",
            deadline="2027-05-01",
        )

        state = load_project(project_dir)

        self.assertIsInstance(state, ProjectState)
        self.assertEqual(state.slug, "demo")
        self.assertEqual(state.dir, project_dir)
        self.assertEqual(state.mode, "journal")
        self.assertEqual(state.current_stage, "major-revision")
        self.assertEqual(state.gate, "revision_planned")
        self.assertEqual(state.deadline, "2027-05-01")
        self.assertEqual(state.updated_at, "2026-10-04")

    def test_deadline_note_counts_down_to_the_target_date(self):
        self.assertEqual(
            deadline_note("2026-10-15", today=date(2026, 10, 6)),
            "剩 9 天",
        )
        self.assertEqual(
            deadline_note("2026-10-06", today=date(2026, 10, 6)),
            "今天截止",
        )

    def test_deadline_note_flags_an_overdue_target(self):
        self.assertEqual(
            deadline_note("2026-09-30", today=date(2026, 10, 6)),
            "已逾期 6 天",
        )

    def test_deadline_note_without_a_date_is_plain_none(self):
        self.assertEqual(deadline_note(None), "无")
        self.assertEqual(deadline_note(""), "无")

    def test_load_project_carries_the_gate_criterion(self):
        project_dir = write_project(
            self.root,
            "demo",
            mode="journal",
            stage="major-revision",
        )

        state = load_project(project_dir)

        expected = gate_for(state.mode, state.current_stage)["criterion"].strip()
        self.assertTrue(expected)
        self.assertEqual(state.gate_criterion, expected)

    def test_load_project_accepts_the_yaml_file_path(self):
        project_dir = write_project(self.root, "demo")

        state = load_project(project_dir / "ccfa.yaml")

        self.assertEqual(state.slug, "demo")
        self.assertEqual(state.dir, project_dir)

    def test_invalid_mode_raises_project_error_with_path_and_reason(self):
        project_dir = write_project(self.root, "demo", mode="bogus")

        with self.assertRaises(ProjectError) as caught:
            load_project(project_dir)

        message = str(caught.exception)
        self.assertIn(str(project_dir), message)
        self.assertIn("bogus", message)

    def test_invalid_stage_raises_project_error(self):
        project_dir = write_project(self.root, "demo")
        path = project_dir / "ccfa.yaml"
        state = yaml.safe_load(path.read_text(encoding="utf-8"))
        state["stage"]["current"] = "not-a-stage"
        path.write_text(
            yaml.safe_dump(state, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        with self.assertRaises(ProjectError) as caught:
            load_project(project_dir)

        self.assertIn("not-a-stage", str(caught.exception))

    def test_missing_gate_raises_project_error(self):
        project_dir = write_project(self.root, "demo")
        path = project_dir / "ccfa.yaml"
        state = yaml.safe_load(path.read_text(encoding="utf-8"))
        del state["stage"]["gate"]
        path.write_text(
            yaml.safe_dump(state, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        with self.assertRaises(ProjectError):
            load_project(project_dir)

    def test_non_mapping_yaml_raises_project_error(self):
        project_dir = self.root / "papers" / "demo"
        project_dir.mkdir(parents=True)
        (project_dir / "ccfa.yaml").write_text("- just\n- a list\n", encoding="utf-8")

        with self.assertRaises(ProjectError):
            load_project(project_dir)


if __name__ == "__main__":
    unittest.main()
