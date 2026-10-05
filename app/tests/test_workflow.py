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
    discover_root,
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

    def test_discover_root_takes_the_first_real_checkout(self):
        empty = self.root / "not-a-checkout"
        empty.mkdir()
        checkout = self.root / "research-workflow"
        (checkout / "tools" / "ccfa").mkdir(parents=True)

        found = discover_root([empty, checkout])

        self.assertEqual(found, checkout)

    def test_discover_root_falls_back_to_the_repository(self):
        empty = self.root / "not-a-checkout"
        empty.mkdir()

        self.assertEqual(discover_root([empty]), DEFAULT_ROOT)

    def test_bundled_runtime_layout_wins_over_guessing_an_interpreter(self):
        bundle = self.root / "workflow"
        (bundle / "python").mkdir(parents=True)
        (bundle / "python" / "python.exe").write_bytes(b"")
        (bundle / "tools" / "ccfa").mkdir(parents=True)

        client = WorkflowClient(root=bundle)

        self.assertEqual(client.python, bundle / "python" / "python.exe")

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

    def test_probe_tells_the_truth_about_the_resolved_workflow(self):
        # The verdict depends on the machine (a tools/.venv has the gate
        # dependencies, a bare interpreter may not), so assert the contract:
        # the probe reports exactly what the interpreter can actually do.
        ok, detail = self.client.probe()
        missing, _note = self.client.probe_interpreter()

        if missing:
            self.assertFalse(ok, detail)
            for module in missing:
                self.assertIn(module, detail)
        else:
            self.assertTrue(ok, detail)
            self.assertIn("个 stage", detail)

    def test_probe_reports_a_missing_interpreter(self):
        client = WorkflowClient(self.root, python=self.root / "nope.exe")

        ok, detail = client.probe()

        self.assertFalse(ok)
        self.assertIn("解释器", detail)

    def test_probe_reports_a_directory_that_is_not_a_workflow(self):
        client = WorkflowClient(self.root / "not-a-repo")

        ok, detail = client.probe()

        self.assertFalse(ok)
        self.assertTrue(detail)


    def test_probe_reports_an_interpreter_that_cannot_run_the_gates(self):
        with mock.patch.object(
            WorkflowClient,
            "probe_interpreter",
            return_value=(["z3", "pymupdf"], "依赖自检失败"),
        ):
            ok, detail = self.client.probe()

        self.assertFalse(ok)
        self.assertIn("z3", detail)
        self.assertIn("pymupdf", detail)
        self.assertIn("解释器", detail)

    def test_probe_interpreter_names_the_modules_a_failing_check_reports(self):
        payload = {"ok": False, "missing": [{"module": "z3"}, {"module": "cvc5"}]}

        with mock.patch.object(WorkflowClient, "json", return_value=payload):
            missing, note = self.client.probe_interpreter()

        self.assertEqual(missing, ["z3", "cvc5"])
        self.assertEqual(note, "依赖自检失败")

    def test_probe_interpreter_tolerates_a_workflow_without_the_flag(self):
        with mock.patch.object(
            WorkflowClient,
            "json",
            side_effect=WorkflowError("unrecognized arguments: --imports-only"),
        ):
            missing, note = self.client.probe_interpreter()

        self.assertEqual(missing, [])
        self.assertIn("不可用", note)

    def test_probe_interpreter_passes_when_the_check_is_green(self):
        with mock.patch.object(
            WorkflowClient,
            "json",
            return_value={"ok": True, "missing": [], "present": ["yaml"]},
        ):
            missing, note = self.client.probe_interpreter()

        self.assertEqual(missing, [])
        self.assertEqual(note, "依赖自检通过")


if __name__ == "__main__":
    unittest.main()
