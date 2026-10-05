"""Tests for the process boundary between the workbench and the workflow."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccfa_core.workflow import (
    DEFAULT_ROOT,
    WorkflowClient,
    WorkflowError,
)

from . import write_project


class WorkflowClientTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.client = WorkflowClient()

    def test_default_root_is_the_repository(self):
        self.assertEqual(self.client.root, DEFAULT_ROOT)
        self.assertTrue((self.client.root / "tools" / "ccfa").is_dir())

    def test_root_can_come_from_the_environment(self):
        with mock.patch.dict(
            os.environ, {"CCFA_WORKFLOW_ROOT": str(self.root)}, clear=False
        ):
            client = WorkflowClient()

        self.assertEqual(client.root, self.root)

    def test_environment_points_pythonpath_at_the_workflow_tools(self):
        env = self.client.environment()

        self.assertTrue(
            env["PYTHONPATH"].startswith(str(self.client.root / "tools"))
        )
        self.assertEqual(env["PYTHONIOENCODING"], "utf-8")

    def test_json_returns_the_tool_payload(self):
        project = write_project(self.root, "demo")

        payload = self.client.json(
            "milestones",
            ("stage", "--paper-root", str(project)),
        )

        self.assertEqual(payload["current"], "idea")
        self.assertEqual(payload["gate"], "scope_defined")

    def test_tool_error_exit_code_becomes_a_domain_error(self):
        missing = self.root / "nope.yaml"

        with self.assertRaises(WorkflowError) as caught:
            self.client.json("validate", (str(missing),))

        self.assertEqual(caught.exception.code, "tool-error")

    def test_missing_interpreter_is_reported_as_such(self):
        client = WorkflowClient(
            self.client.root,
            python=self.root / "no-such-python.exe",
        )

        with self.assertRaises(WorkflowError) as caught:
            client.run("stages", ("--mode", "conference"))

        self.assertEqual(caught.exception.code, "workflow-python-missing")

    def test_dotted_module_names_are_used_verbatim(self):
        result = self.client.run("ccfa.stages", ("--mode", "conference"))

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.payload["mode"], "conference")

    def test_findings_flag_marks_exit_one(self):
        broken = self.root / "ccfa.yaml"
        broken.write_text("version: '0.4.0'\n", encoding="utf-8")

        result = self.client.run("validate", (str(broken),))

        self.assertTrue(result.findings)
        self.assertTrue(result.payload["problems"])

    def test_parse_rejects_non_json_and_non_objects(self):
        self.assertIsNone(WorkflowClient._parse(""))
        self.assertIsNone(WorkflowClient._parse("not json"))
        self.assertIsNone(WorkflowClient._parse("[1, 2]"))
        self.assertEqual(WorkflowClient._parse('{"a": 1}'), {"a": 1})

    def test_frozen_build_never_falls_back_to_its_own_executable(self):
        with mock.patch.object(sys, "frozen", True, create=True):
            client = WorkflowClient(self.root)

            self.assertIsNone(client.python)
            with self.assertRaises(WorkflowError) as caught:
                client.run("stages", ("--mode", "conference"))

        self.assertEqual(caught.exception.code, "workflow-python-missing")
        self.assertIn("工作流目录", str(caught.exception))

    def test_frozen_build_uses_the_bundled_workflow_venv_when_present(self):
        venv = self.root / "tools" / ".venv" / "Scripts"
        venv.mkdir(parents=True)
        interpreter = venv / "python.exe"
        interpreter.write_text("", encoding="utf-8")

        with mock.patch.object(sys, "frozen", True, create=True):
            client = WorkflowClient(self.root)

        self.assertEqual(client.python, interpreter)


if __name__ == "__main__":
    unittest.main()
