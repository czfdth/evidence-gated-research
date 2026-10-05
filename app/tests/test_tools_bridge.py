"""Tests for the deterministic tools exposed to the chat engine."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import httpx
import yaml
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ccfa_core.engines.base import ChatMessage, EngineError
from ccfa_core.engines.openai_compat import OpenAICompatibleEngine
from ccfa_core.tools_bridge import TOOL_DEFINITIONS, ToolBridge, openai_tools
from ccfa_core.workflow import WorkflowClient
from ccfa_gui.chat_panel import ChatPanel
from . import create_project, write_project


def workflow_json(module: str, args) -> dict:
    """Fixtures drive the workflow through its CLI, never through imports."""

    return WorkflowClient().json(module, args)

APP = QApplication.instance() or QApplication([])
FAKE_KEY = "sk-bridge-FAKE-KEY-1122334455"
BASE_URL = "https://api.example.test/v1"

EXPECTED_TOOLS = {
    "milestones_stage",
    "milestones_due",
    "library_search",
    "memory_search",
    "memory_list",
    "memory_add_idea",
    "memory_add_dead_end",
    "state_set_stage",
    "state_rollback",
    "trace_claims_check",
}
WRITE_TOOLS = {
    "memory_add_idea",
    "memory_add_dead_end",
    "state_set_stage",
    "state_rollback",
}

SAMPLE_BIB = r"""
@inproceedings{sample,
  title     = {Sample {GPU} Paper},
  author    = {Alice and Bob},
  year      = {2021},
  booktitle = {TestConf},
  abstract  = {An indexed abstract}
}
"""


class FakeSecretStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key_name):
        return self.values.get(key_name)

    def set(self, key_name, value):
        self.values[key_name] = value

    def delete(self, key_name):
        self.values.pop(key_name, None)


class ToolBridgeTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.project_root = write_project(
            self.root,
            "demo",
            mode="conference",
            stage="idea",
        )
        self.bridge = ToolBridge(
            self.project_root,
            confirm_write=lambda name, arguments: True,
        )

    def audit_path(self):
        return (
            self.project_root
            / "ccfa-workfiles"
            / "agent-tools.jsonl"
        )

    def audit_lines(self):
        return [
            json.loads(line)
            for line in self.audit_path().read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    # --- specs ---------------------------------------------------------

    def test_specs_expose_expected_tools_and_risks(self):
        tools = {
            item["function"]["name"]: item for item in openai_tools()
        }

        self.assertEqual(set(tools), EXPECTED_TOOLS)
        for name, item in tools.items():
            self.assertEqual(item["type"], "function")
            self.assertEqual(
                item["function"]["parameters"]["type"],
                "object",
            )
            self.assertTrue(item["function"]["description"])
            expected_risk = "write" if name in WRITE_TOOLS else "read"
            self.assertEqual(self.bridge.risk(name), expected_risk)
        self.assertEqual(
            {tool.name for tool in TOOL_DEFINITIONS},
            EXPECTED_TOOLS,
        )
        description = tools["library_search"]["function"]["description"]
        self.assertIn("共享文献库", description)
        self.assertNotIn("project/library/index.db", description)

    def test_run_log_execution_is_not_exposed(self):
        names = {item["function"]["name"] for item in openai_tools()}

        self.assertNotIn("run_log_run", names)
        self.assertNotIn("run-log", names)
        self.assertFalse(
            any("run" in name and "log" in name for name in names)
        )

    # --- read tools ----------------------------------------------------

    def test_milestones_stage_happy_path(self):
        result = self.bridge.execute("milestones_stage", {})

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["current"], "idea")
        self.assertEqual(result["result"]["gate"], "scope_defined")

    def test_milestones_due_happy_path(self):
        due_root = write_project(
            self.root,
            "due",
            mode="conference",
            stage="idea",
            deadline="2026-10-20",
        )
        bridge = ToolBridge(due_root, confirm_write=lambda name, args: True)

        result = bridge.execute("milestones_due", {"today": "2026-10-06"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["mode"], "countdown")
        self.assertEqual(
            [item["checkpoint"] for item in result["result"]["due"]],
            ["T-14"],
        )

    def test_library_search_uses_the_explicit_shared_library(self):
        shared = self.root / "shared-library"
        shared.mkdir()
        (shared / "refs.bib").write_text(SAMPLE_BIB, encoding="utf-8")
        workflow_json("library", ("--dir", str(shared), "index"))
        self.assertFalse((self.project_root / "library").exists())
        bridge = ToolBridge(self.project_root, library_dir=shared)

        result = bridge.execute("library_search", {"query": "sample"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["results"][0]["key"], "sample")
        self.assertEqual(result["result"]["mode"], "fts")

    def test_library_search_without_shared_library_is_structured_error(self):
        result = self.bridge.execute("library_search", {"query": "sample"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "tool-error")
        self.assertIn("请先运行 library index", result["error"]["message"])

    def test_library_search_missing_index_names_the_index_command(self):
        shared = self.root / "empty-library"
        shared.mkdir()
        bridge = ToolBridge(self.project_root, library_dir=shared)

        result = bridge.execute("library_search", {"query": "sample"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "tool-error")
        self.assertIn("请先运行 library index", result["error"]["message"])

    def test_real_derived_project_uses_the_repository_level_library(self):
        project_dir = create_project(
            papers_root=self.root / "papers",
            slug="bridge-e2e",
            venue="NeurIPS",
            year="2027",
            mode="conference",
            title="Bridge E2E",
        )
        shared = self.root / "repo-library"
        shared.mkdir()
        (shared / "refs.bib").write_text(SAMPLE_BIB, encoding="utf-8")
        workflow_json("library", ("--dir", str(shared), "index"))
        self.assertFalse((project_dir / "library").exists())
        bridge = ToolBridge(project_dir, library_dir=shared)

        result = bridge.execute("library_search", {"query": "sample"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["results"][0]["key"], "sample")

    def test_memory_search_happy_path(self):
        workflow_json(
            "memory",
            (
                "--paper-root",
                str(self.project_root),
                "add-idea",
                "--idea",
                "use trigram fallback",
                "--date",
                "2026-10-04",
                "--notes",
                "two character queries",
            ),
        )

        result = self.bridge.execute("memory_search", {"query": "trigram"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["ideas"][0]["id"], "I1")

    def test_memory_list_happy_path(self):
        workflow_json(
            "memory",
            (
                "--paper-root",
                str(self.project_root),
                "add-idea",
                "--idea",
                "plain idea",
                "--date",
                "2026-10-04",
            ),
        )
        workflow_json(
            "memory",
            (
                "--paper-root",
                str(self.project_root),
                "add-dead-end",
                "--idea",
                "failed idea",
                "--date",
                "2026-10-04",
                "--reason",
                "it failed",
                "--evidence",
                "log 1",
                "--reopen-if",
                "new data arrives",
            ),
        )

        result = self.bridge.execute("memory_list", {"kind": "dead-ends"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["ideas"], [])
        self.assertEqual(result["result"]["dead_ends"][0]["id"], "DE1")

    def test_trace_claims_check_happy_path_uses_untagged_mode(self):
        (self.project_root / "results.json").write_text(
            json.dumps({"summary": {"lcoe": 0.14285714285714285}}),
            encoding="utf-8",
        )
        (self.project_root / "main.tex").write_text(
            "Accuracy was 92.5 percent.\n"
            "\\dataval{results.json:summary.lcoe}{0.143}\n",
            encoding="utf-8",
        )

        result = self.bridge.execute(
            "trace_claims_check",
            {"docs": ["main.tex"], "base_dir": "."},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["problem_count"], 0)
        self.assertIn(
            "untagged-number",
            [item["code"] for item in result["result"]["advisories"]],
        )

    # --- write tools ---------------------------------------------------

    def test_memory_add_idea_write_happy_path(self):
        result = self.bridge.execute(
            "memory_add_idea",
            {"idea": "new direction", "date": "2026-10-04"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["id"], "I1")
        self.assertTrue(
            (self.project_root / "memory" / "ideas.md").is_file()
        )

    def test_memory_add_dead_end_write_happy_path(self):
        result = self.bridge.execute(
            "memory_add_dead_end",
            {
                "idea": "dead direction",
                "date": "2026-10-04",
                "reason": "no signal",
                "evidence": "run 7",
                "reopen_if": "a larger corpus appears",
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["id"], "DE1")
        self.assertEqual(
            result["result"]["reopen_if"],
            "a larger corpus appears",
        )

    def test_state_set_stage_write_happy_path(self):
        result = self.bridge.execute(
            "state_set_stage",
            {"to": "grounded", "reason": "scope frozen"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["to"], "grounded")
        state = yaml.safe_load(
            (self.project_root / "ccfa.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(state["stage"]["current"], "grounded")

    def test_state_rollback_write_happy_path(self):
        rollback_root = write_project(
            self.root,
            "rollback",
            mode="conference",
            stage="experiments-running",
        )
        bridge = ToolBridge(
            rollback_root,
            confirm_write=lambda name, arguments: True,
        )

        result = bridge.execute(
            "state_rollback",
            {
                "to": "idea",
                "reason": "protocol flaw",
                "void_artifacts": ["experiments/log/run-1.json"],
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["kind"], "rollback")
        self.assertEqual(
            result["result"]["void_artifacts"],
            ["experiments/log/run-1.json"],
        )

    def test_write_tool_declined_returns_user_declined(self):
        bridge = ToolBridge(
            self.project_root,
            confirm_write=lambda name, arguments: False,
        )

        result = bridge.execute(
            "memory_add_idea",
            {"idea": "blocked", "date": "2026-10-04"},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "user-declined")
        self.assertEqual(result["error"]["message"], "user declined")
        self.assertFalse(
            (self.project_root / "memory" / "ideas.md").exists()
        )
        self.assertEqual(self.audit_lines()[-1]["outcome"], "declined")

    def test_write_tool_without_confirmer_is_declined(self):
        bridge = ToolBridge(self.project_root)

        result = bridge.execute(
            "state_set_stage",
            {"to": "grounded", "reason": "no confirmation path"},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "user-declined")
        state = yaml.safe_load(
            (self.project_root / "ccfa.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(state["stage"]["current"], "idea")

    # --- bad arguments -------------------------------------------------

    def test_unknown_tool_returns_structured_error(self):
        result = self.bridge.execute("does_not_exist", {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "unknown-tool")
        self.assertEqual(self.audit_lines()[-1]["outcome"], "unknown-tool")

    def test_non_mapping_arguments_return_structured_error(self):
        result = self.bridge.execute("milestones_stage", ["not", "a", "map"])

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid-arguments")

    def test_missing_required_argument_returns_structured_error(self):
        result = self.bridge.execute("memory_search", {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid-arguments")
        self.assertIn("query", result["error"]["message"])

    def test_unknown_argument_returns_structured_error(self):
        result = self.bridge.execute(
            "milestones_stage",
            {"surprise": 1},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid-arguments")
        self.assertIn("surprise", result["error"]["message"])

    def test_bad_argument_type_returns_structured_error(self):
        result = self.bridge.execute(
            "library_search",
            {"query": "sample", "limit": "many"},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid-arguments")
        self.assertIn("limit", result["error"]["message"])

    def test_domain_error_is_wrapped_without_crashing(self):
        result = self.bridge.execute("memory_search", {"query": "   "})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "tool-error")
        self.assertIn("不能为空", result["error"]["message"])

    def test_path_escape_in_trace_docs_is_rejected(self):
        result = self.bridge.execute(
            "trace_claims_check",
            {"docs": ["../outside.tex"]},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "tool-error")
        self.assertIn("越出论文根", result["error"]["message"])

    # --- audit ---------------------------------------------------------

    def test_audit_records_required_fields_and_digest(self):
        self.bridge.execute("milestones_stage", {})

        entry = self.audit_lines()[-1]
        self.assertEqual(
            set(entry),
            {"time", "tool", "args_digest", "risk", "outcome"},
        )
        self.assertEqual(entry["tool"], "milestones_stage")
        self.assertEqual(entry["risk"], "read")
        self.assertEqual(entry["outcome"], "ok")
        self.assertTrue(entry["time"].endswith("Z"))
        digest = entry["args_digest"]
        self.assertEqual(len(digest), 16)
        int(digest, 16)

    def test_audit_does_not_store_sensitive_arguments(self):
        self.bridge.execute(
            "memory_add_idea",
            {
                "idea": "key handling",
                "date": "2026-10-04",
                "notes": FAKE_KEY,
            },
        )

        raw = self.audit_path().read_bytes()
        self.assertNotIn(FAKE_KEY.encode("utf-8"), raw)
        entry = self.audit_lines()[-1]
        self.assertNotEqual(entry["args_digest"], FAKE_KEY)

    def test_malformed_jsonl_line_is_preserved_and_appended(self):
        path = self.audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not-json\n", encoding="utf-8")

        self.bridge.execute("milestones_stage", {})

        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "not-json")
        self.assertEqual(
            json.loads(lines[1])["tool"],
            "milestones_stage",
        )

    def test_audit_is_appended_not_overwritten(self):
        self.bridge.execute("milestones_stage", {})
        self.bridge.execute("memory_list", {"kind": "ideas"})

        tools = [entry["tool"] for entry in self.audit_lines()]
        self.assertEqual(tools, ["milestones_stage", "memory_list"])

    # --- engine tool loop ----------------------------------------------

    def _engine(self, handler, *, bridge=None, max_rounds=6):
        store = FakeSecretStore({"provider-key": FAKE_KEY})
        return OpenAICompatibleEngine(
            base_url=BASE_URL,
            model="test-model",
            secret_store=store,
            key_name="provider-key",
            timeout_s=5.0,
            transport=httpx.MockTransport(handler),
            tool_handler=None if bridge is None else bridge.execute,
            max_tool_rounds=max_rounds,
        )

    def test_engine_executes_tool_calls_and_returns_final_text(self):
        requests = []

        def handler(request):
            requests.append(json.loads(request.content.decode("utf-8")))
            if len(requests) == 1:
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": None,
                                    "tool_calls": [
                                        {
                                            "id": "call_1",
                                            "type": "function",
                                            "function": {
                                                "name": "memory_add_idea",
                                                "arguments": json.dumps(
                                                    {
                                                        "idea": "from model",
                                                        "date": "2026-10-04",
                                                    }
                                                ),
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "finished"}}]},
            )

        engine = self._engine(handler, bridge=self.bridge)
        reply = engine.send([ChatMessage("user", "record an idea")])

        self.assertEqual(reply.text, "finished")
        self.assertEqual(len(requests), 2)
        tool_messages = [
            message
            for message in requests[1]["messages"]
            if message.get("role") == "tool"
        ]
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(tool_messages[0]["tool_call_id"], "call_1")
        payload = json.loads(tool_messages[0]["content"])
        self.assertTrue(payload["ok"])
        self.assertTrue(
            (self.project_root / "memory" / "ideas.md").is_file()
        )
        self.assertEqual(self.audit_lines()[-1]["outcome"], "ok")

    def test_engine_tool_loop_stops_at_max_rounds(self):
        requests = {"count": 0}
        tool_calls = [
            {
                "id": "call_x",
                "type": "function",
                "function": {
                    "name": "milestones_stage",
                    "arguments": "{}",
                },
            }
        ]

        def handler(request):
            requests["count"] += 1
            if requests["count"] <= 10:
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": None,
                                    "tool_calls": tool_calls,
                                }
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "too late"}}]},
            )

        engine = self._engine(handler, bridge=self.bridge, max_rounds=2)

        with self.assertRaises(EngineError) as context:
            engine.send([ChatMessage("user", "loop forever")])

        self.assertIn("上限", str(context.exception))
        self.assertEqual(requests["count"], 3)
        self.assertEqual(len(self.audit_lines()), 2)

    def test_engine_without_handler_returns_tool_calls(self):
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "milestones_stage",
                    "arguments": "{}",
                },
            }
        ]

        def handler(request):
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": tool_calls,
                            }
                        }
                    ]
                },
            )

        engine = self._engine(handler)

        reply = engine.send([ChatMessage("user", "hello")])

        self.assertEqual(reply.tool_calls, tool_calls)
        self.assertEqual(reply.text, "")

    # --- chat panel wiring ---------------------------------------------

    def test_chat_panel_wires_bridge_and_shows_tool_outcome(self):
        settings_path = self.root / "settings.json"
        secrets = FakeSecretStore({"local": FAKE_KEY})
        panel = ChatPanel(
            settings_path,
            secret_store=secrets,
            engine_factory=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("engine must not be created")
            ),
        )
        self.addCleanup(self._dispose_panel, panel)
        panel.write_confirmer = lambda name, arguments: False
        panel.set_project(self.project_root)

        result = panel._tool_bridge.execute(
            "memory_add_idea",
            {"idea": "panel path", "date": "2026-10-04"},
        )
        APP.processEvents()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "user-declined")
        roles = [
            panel.message_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(panel.message_list.count())
        ]
        self.assertIn("tool", roles)
        texts = [
            panel.message_list.item(row).text()
            for row in range(panel.message_list.count())
        ]
        self.assertTrue(any("declined" in text for text in texts))

    @staticmethod
    def _dispose_panel(panel):
        panel.close()
        panel.deleteLater()
        APP.processEvents()


if __name__ == "__main__":
    unittest.main()
