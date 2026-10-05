"""End-to-end smoke for the workbench chat: project -> engine -> tools.

The fake engine below mirrors the real OpenAI-compatible tool loop: it
"returns" tool_calls, executes them through the bridge configured by the
panel, and feeds the results back as if they were tool messages. Tool
execution happens on the engine worker thread, exactly like the production
engine; the panel is responsible for showing the confirmation dialog on the
GUI thread.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from ccfa_core.engines.base import EngineReply
from ccfa_core.settings import ProviderSettings, Settings, save_settings
from ccfa_gui.window import MainWindow, image_non_background_ratio
from . import create_project

APP = QApplication.instance() or QApplication([])
FAKE_KEY = "sk-e2e-chat-FAKE-KEY-9988776655"
BASE_URL = "https://api.example.test/v1"


class RecordingSecretStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key_name):
        return self.values.get(key_name)

    def set(self, key_name, value):
        self.values[key_name] = value

    def delete(self, key_name):
        self.values.pop(key_name, None)


def tool_call(call_id, name, arguments):
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        },
    }


class FakeToolEngine:
    """Minimal engine that replays scripted tool_calls through the bridge."""

    def __init__(self, plans=None, reply="fake reply"):
        self.plans = dict(plans or {})
        self.reply = reply
        self.tools = None
        self._handler = None
        self.sent_texts = []
        self.returned_tool_calls = []
        self.tool_results = []

    def configure_tools(self, handler, max_rounds=6):
        self._handler = handler

    def send(self, messages, *, tools=None, timeout_s=None, cancel=None):
        self.tools = tools
        text = messages[-1].content
        self.sent_texts.append(text)
        calls = []
        for keyword, planned in self.plans.items():
            if keyword in text:
                calls = planned
                break
        for index, call in enumerate(calls):
            self.returned_tool_calls.append(call)
            function = call["function"]
            arguments = json.loads(function["arguments"])
            try:
                result = self._handler(function["name"], arguments)
            except Exception as exc:
                result = {
                    "ok": False,
                    "error": {
                        "code": "tool-handler-error",
                        "message": str(exc),
                    },
                }
            self.tool_results.append(result)
        if calls:
            return EngineReply(text=f"{self.reply} (tools={len(calls)})")
        return EngineReply(text=self.reply)


class ChatEndToEnd(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.settings_path = self.root / "settings.json"
        self.project_dir = create_project(
            papers_root=self.root / "papers",
            slug="chat-e2e",
            venue="NeurIPS",
            year="2027",
            mode="conference",
            title="Chat E2E",
        )
        save_settings(
            self.settings_path,
            Settings(
                provider=ProviderSettings(
                    name="local",
                    base_url=BASE_URL,
                    model="gpt-test",
                    key_name="local",
                    timeout_s=30.0,
                )
            ),
        )
        self.secrets = RecordingSecretStore({"local": FAKE_KEY})
        self.window = MainWindow(
            repo_root=self.root,
            secret_store=self.secrets,
            settings_path=self.settings_path,
        )
        self.window.resize(1100, 780)
        self.window.show()
        APP.processEvents()
        self.panel = self.window.chat_panel
        self._select_project("chat-e2e")

    def tearDown(self):
        self.panel.stop()
        self._wait_until(lambda: self.panel._thread is None)
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def _select_project(self, slug):
        for row in range(self.window.project_list.count()):
            item = self.window.project_list.item(row)
            ref = item.data(Qt.ItemDataRole.UserRole)
            if ref.slug == slug:
                self.window.project_list.setCurrentRow(row)
                APP.processEvents()
                return
        self.fail(f"project {slug} not found")

    def _use_engine(self, engine):
        self.panel._engine_factory = lambda **kwargs: engine
        return engine

    def _send(self, text):
        self.panel.input_edit.setPlainText(text)
        APP.processEvents()
        self.panel.send_button.click()

    @staticmethod
    def _wait_until(predicate, timeout=20.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            APP.processEvents()
            if predicate():
                return True
            time.sleep(0.005)
        APP.processEvents()
        return predicate()

    def _messages(self):
        return [
            (
                self.panel.message_list.item(row).data(
                    Qt.ItemDataRole.UserRole
                ),
                self.panel.message_list.item(row).text(),
            )
            for row in range(self.panel.message_list.count())
        ]

    def _audit_path(self):
        return (
            self.project_dir / "ccfa-workfiles" / "agent-tools.jsonl"
        )

    def _audit_lines(self):
        return [
            json.loads(line)
            for line in self._audit_path().read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]

    def _arm_dialog_answer(self, button):
        """Click the given button as soon as the confirm dialog appears."""

        def click_when_shown():
            widget = QApplication.activeModalWidget()
            if isinstance(widget, QMessageBox):
                target = widget.button(button)
                if target is not None:
                    target.click()
                    return
            QTimer.singleShot(10, click_when_shown)

        QTimer.singleShot(0, click_when_shown)

    def _wait_for_reply(self):
        self.assertTrue(
            self._wait_until(
                lambda: self.panel._thread is None
                and len(self._messages()) >= 2
            )
        )

    # --- scenarios -----------------------------------------------------

    def test_real_neurips_project_is_selected_with_tools_attached(self):
        self.assertTrue(self.project_dir.is_dir())
        self.assertTrue((self.project_dir / "ccfa.yaml").is_file())
        self.assertIsNotNone(self.panel._tool_bridge)
        self.assertEqual(
            self.panel._tool_bridge.project_root,
            self.project_dir,
        )
        self.assertIn("chat-e2e", self.window.project_list.currentItem().text())

    def test_panel_uses_the_repository_level_library(self):
        from ccfa_gui import window as window_module

        expected = (
            Path(window_module.__file__).resolve().parents[2] / "library"
        )

        self.assertEqual(self.panel._tool_bridge.library_dir, expected)

    def test_chat_send_renders_user_and_assistant_messages(self):
        engine = self._use_engine(FakeToolEngine(reply="hello from fake"))

        self._send("plain question")
        self._wait_for_reply()

        roles = [role for role, _ in self._messages()]
        self.assertEqual(roles[:2], ["user", "assistant"])
        self.assertIn("hello from fake", self._messages()[1][1])
        self.assertEqual(engine.sent_texts, ["plain question"])

    def test_engine_receives_project_tools_and_no_run_log(self):
        engine = self._use_engine(FakeToolEngine())

        self._send("what tools do you have")
        self._wait_for_reply()

        names = {
            item["function"]["name"] for item in (engine.tools or [])
        }
        self.assertIn("milestones_due", names)
        self.assertIn("memory_add_idea", names)
        self.assertFalse(
            any("run" in name and "log" in name for name in names)
        )

    def test_milestones_due_tool_call_is_audited(self):
        engine = self._use_engine(
            FakeToolEngine(
                plans={
                    "milestone": [
                        tool_call("call_1", "milestones_due", {})
                    ]
                },
                reply="checked milestones",
            )
        )

        self._send("check the milestone plan")
        self._wait_for_reply()

        self.assertEqual(len(engine.returned_tool_calls), 1)
        self.assertEqual(len(engine.tool_results), 1)
        self.assertTrue(engine.tool_results[0]["ok"])
        tool_messages = [
            text for role, text in self._messages() if role == "tool"
        ]
        self.assertTrue(
            any("milestones_due" in text for text in tool_messages)
        )
        entries = self._audit_lines()
        self.assertEqual(entries[-1]["tool"], "milestones_due")
        self.assertEqual(entries[-1]["risk"], "read")
        self.assertEqual(entries[-1]["outcome"], "ok")
        self.assertTrue(
            any("checked milestones" in text for _, text in self._messages())
        )

    def test_declined_write_tool_returns_user_declined(self):
        engine = self._use_engine(
            FakeToolEngine(
                plans={
                    "remember": [
                        tool_call(
                            "call_2",
                            "memory_add_idea",
                            {
                                "idea": "declined idea",
                                "date": "2026-10-04",
                            },
                        )
                    ]
                },
                reply="write attempted",
            )
        )
        self._arm_dialog_answer(QMessageBox.StandardButton.No)

        self._send("remember this idea")
        self._wait_for_reply()

        result = engine.tool_results[0]
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "user-declined")
        self.assertEqual(result["error"]["message"], "user declined")
        ideas = (
            self.project_dir / "memory" / "ideas.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("declined idea", ideas)
        self.assertEqual(self._audit_lines()[-1]["outcome"], "declined")
        tool_messages = [
            text for role, text in self._messages() if role == "tool"
        ]
        self.assertTrue(any("declined" in text for text in tool_messages))

    def test_accepted_write_tool_persists_the_idea(self):
        engine = self._use_engine(
            FakeToolEngine(
                plans={
                    "remember": [
                        tool_call(
                            "call_3",
                            "memory_add_idea",
                            {
                                "idea": "accepted idea",
                                "date": "2026-10-04",
                            },
                        )
                    ]
                },
                reply="write approved",
            )
        )
        self._arm_dialog_answer(QMessageBox.StandardButton.Yes)

        self._send("remember this idea")
        self._wait_for_reply()

        result = engine.tool_results[0]
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["id"], "I1")
        ideas = (
            self.project_dir / "memory" / "ideas.md"
        ).read_text(encoding="utf-8")
        self.assertIn("accepted idea", ideas)
        self.assertEqual(self._audit_lines()[-1]["outcome"], "ok")

    def test_render_screenshot_is_non_blank(self):
        self._use_engine(FakeToolEngine(reply="render"))
        self._send("render please")
        self._wait_for_reply()

        image = self.window.grab().toImage()
        path = self.root / "chat-e2e.png"
        self.assertTrue(image.save(str(path), "PNG"))
        self.assertGreater(image.width(), 600)
        self.assertGreater(image.height(), 400)
        ratio = image_non_background_ratio(image)
        self.assertGreater(
            ratio,
            0.02,
            f"non-background ratio too low: {ratio}",
        )
        size = path.stat().st_size
        self.assertGreater(size, 0)
        print(f"CHAT_E2E_SCREENSHOT_RATIO={ratio:.4f}")
        print(f"CHAT_E2E_SCREENSHOT_PATH={path}")
        print(f"CHAT_E2E_SCREENSHOT_BYTES={size}")


if __name__ == "__main__":
    unittest.main()
