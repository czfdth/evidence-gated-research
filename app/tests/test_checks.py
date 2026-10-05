import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from datetime import date
from pathlib import Path

import yaml

from ccfa_core.checks import (
    CheckError,
    CheckResult,
    run_milestones_due,
    run_validate,
)
from ccfa_core.projects import load_project

from . import write_project


class CheckTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def test_run_validate_clean_project_returns_no_problems(self):
        project_dir = write_project(self.root, "demo")

        result = run_validate(load_project(project_dir))

        self.assertIsInstance(result, CheckResult)
        self.assertEqual(result.name, "validate")
        self.assertTrue(result.ok)
        self.assertEqual(result.problems, ())

    def test_run_validate_reports_schema_problems(self):
        project_dir = write_project(self.root, "demo")
        path = project_dir / "ccfa.yaml"
        state = yaml.safe_load(path.read_text(encoding="utf-8"))
        del state["project"]
        path.write_text(
            yaml.safe_dump(state, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        result = run_validate(project_dir)

        self.assertFalse(result.ok)
        self.assertTrue(result.problems)
        self.assertIn("project", " ".join(result.problems))

    def test_run_validate_malformed_yaml_raises_check_error(self):
        project_dir = self.root / "papers" / "broken"
        project_dir.mkdir(parents=True)
        (project_dir / "ccfa.yaml").write_text(": [unclosed\n", encoding="utf-8")

        with self.assertRaises(CheckError) as caught:
            run_validate(project_dir)

        self.assertIn("validate", str(caught.exception))

    def test_run_milestones_due_sequential_report(self):
        project_dir = write_project(self.root, "demo")

        result = run_milestones_due(project_dir, today=date(2026, 10, 4))

        self.assertEqual(result.name, "milestones-due")
        self.assertTrue(result.ok)
        self.assertEqual(result.problems, ())
        self.assertEqual(result.report["mode"], "sequential")
        self.assertEqual(result.report["due"], [])

    def test_run_milestones_due_countdown_report_is_structured(self):
        project_dir = write_project(
            self.root,
            "demo",
            deadline="2027-05-01",
        )

        result = run_milestones_due(project_dir, today=date(2027, 4, 17))

        self.assertEqual(result.report["mode"], "countdown")
        self.assertTrue(result.report["due"])
        self.assertFalse(result.ok)
        self.assertTrue(result.problems)

    def test_run_milestones_due_bad_project_raises_check_error(self):
        project_dir = write_project(self.root, "demo", mode="bogus")

        with self.assertRaises(CheckError) as caught:
            run_milestones_due(project_dir, today=date(2026, 10, 4))

        self.assertIn("milestones", str(caught.exception))

    def test_core_import_graph_does_not_block_on_pyside6(self):
        script = textwrap.dedent(
            """
            import sys
            import tempfile
            from pathlib import Path

            class BlockPySide6:
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == "PySide6" or fullname.startswith("PySide6."):
                        raise ImportError(f"blocked PySide6 import: {fullname}")
                    return None

            sys.meta_path.insert(0, BlockPySide6())

            import ccfa_core
            from ccfa_core import checks, projects, secrets, settings

            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                assert projects.find_projects(root) == []
                loaded = settings.load_settings(root / "settings.json")
                assert loaded.provider is None

            offending = [
                name
                for name in sys.modules
                if name == "PySide6" or name.startswith("PySide6.")
            ]
            assert not offending, offending
            print("CORE_IMPORT_OK")
            """
        )
        app_dir = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        # Only the app on the path: importing the core must never require the
        # workflow package, which is the whole point of the CLI boundary.
        env["PYTHONPATH"] = str(app_dir)

        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(app_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("CORE_IMPORT_OK", completed.stdout)


if __name__ == "__main__":
    unittest.main()
