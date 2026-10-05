"""Offscreen tests for the chat panel and its background engine thread."""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QTextBrowser

from ccfa_core.engines.base import EngineError, EngineReply
from ccfa_core.secrets import SecretStoreUnavailable
from ccfa_core.settings import ProviderSettings, Settings, save_settings
from ccfa_gui.chat_panel import ChatPanel, markdown_style
from ccfa_gui.window import MainWindow, image_non_background_ratio

from . import write_project

APP = QApplication.instance() or QApplication([])
FAKE_KEY = "sk-chat-FAKE-KEY-2468013579"
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


class UnavailableSecretStore(RecordingSecretStore):
    def get(self, key_name):
        raise SecretStoreUnavailable("no backend")


class FakeEngine:
    """Deterministic engine used to observe panel behavior."""

    def __init__(self, *, reply_text="pong", error=None, delay=0.0, name="fake"):
        self.name = name
        self.reply_text = reply_text
        self.error = error
        self.delay = delay
        self.calls = []
        self.started = threading.Event()
        self.cancelled = False

    def send(self, messages, *, tools=None, timeout_s=None, cancel=None):
        self.calls.append(
            {
                "messages": list(messages),
                "tools": tools,
                "timeout_s": timeout_s,
                "cancel": cancel,
            }
        )
        self.started.set()
        deadline = time.monotonic() + self.delay
        while time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                self.cancelled = True
                raise EngineError("请求已取消")
            time.sleep(0.005)
        if cancel is not None and cancel.is_set():
            self.cancelled = True
            raise EngineError("请求已取消")
        if self.error is not None:
            raise self.error
        return EngineReply(text=self.reply_text)


class ChatPanelTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.settings_path = self.root / "settings.json"
        self.secrets = RecordingSecretStore()
        self.factories = []
        self._panels = []

    def tearDown(self):
        for panel in self._panels:
            panel.stop()
            self._wait_until(lambda: panel._thread is None)
            panel.close()
            panel.deleteLater()
        APP.processEvents()

    def _configure_provider(self, key_name="local", key=FAKE_KEY):
        save_settings(
            self.settings_path,
            Settings(
                provider=ProviderSettings(
                    name="local",
                    base_url=BASE_URL,
                    model="gpt-test",
                    key_name=key_name,
                    timeout_s=30.0,
                )
            ),
        )
        if key is not None:
            self.secrets.set(key_name, key)

    def _configure_http_tool(self, *, risk="read"):
        registry = self.root / "http-tools.yaml"
        registry.write_text(
            "\n".join(
                [
                    "version: 1",
                    "tools:",
                    "  - name: paper_lookup",
                    "    description: Look up a paper",
                    f"    risk: {risk}",
                    "    method: GET",
                    "    url: https://api.example.test/papers/{paper_id}",
                    "    headers:",
                    "      Authorization: secret:paper-api",
                    "    parameters:",
                    "      type: object",
                    "      properties:",
                    "        paper_id:",
                    "          type: string",
                    "      required: [paper_id]",
                    "      additionalProperties: false",
                ]
            )
            + "\n",
            encoding="utf-8",
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
                ),
                http_tools_path=registry.name,
            ),
        )
        self.secrets.set("local", FAKE_KEY)
        self.secrets.set("paper-api", "paper-secret")
        return registry

    def _factory(self, engines=None):
        created = {}

        def factory(*, kind, model, settings, secret_store):
            created["kind"] = kind
            created["model"] = model
            created["settings"] = settings
            if engines is not None and kind in engines:
                return engines[kind]
            engine = FakeEngine(name=f"fake-{kind}")
            created.setdefault("engines", {})[kind] = engine
            return engine

        self.factories.append(factory)
        self.created = created
        return factory

    def _panel(self, *, factory=None, store=None, engines=None, kind="openai"):
        panel = ChatPanel(
            self.settings_path,
            secret_store=store or self.secrets,
            engine_factory=factory or self._factory(engines),
        )
        panel.resize(760, 620)
        panel.show()
        APP.processEvents()
        if kind != "openai":
            panel.engine_combo.setCurrentIndex(
                panel.engine_combo.findData(kind)
            )
            APP.processEvents()
        self._panels.append(panel)
        return panel

    @staticmethod
    def _wait_until(predicate, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            APP.processEvents()
            if predicate():
                return True
            time.sleep(0.005)
        APP.processEvents()
        return predicate()

    @staticmethod
    def _items(panel):
        return [
            (
                panel.message_list.item(row).data(Qt.ItemDataRole.UserRole),
                panel.message_list.item(row).text(),
                panel.message_list.item(row).foreground().color(),
            )
            for row in range(panel.message_list.count())
        ]

    def test_messages_render_as_role_bubbles(self):
        panel = self._panel()

        panel._append_message("user", "看一下主证明")
        panel._append_message("assistant", "第 3 步的假设没有被用到")
        panel._append_message("tool", "read_file [read] -> ok")
        panel._append_message("error", "引擎超时")
        APP.processEvents()

        roles = []
        for row in range(panel.message_list.count()):
            item = panel.message_list.item(row)
            widget = panel.message_list.itemWidget(item)
            with self.subTest(row=row):
                self.assertIsNotNone(widget, "每条消息都应有气泡部件")
                roles.append(widget.property("role"))
                # The plain text stays on the item for existing consumers.
                self.assertTrue(item.text())
                self.assertGreater(item.sizeHint().height(), 0)

        self.assertEqual(roles, ["user", "assistant", "tool", "error"])

    def test_tool_bubble_splits_name_risk_and_outcome(self):
        panel = self._panel()

        panel._append_message("tool", "write_file [write] -> denied")
        APP.processEvents()

        item = panel.message_list.item(0)
        widget = panel.message_list.itemWidget(item)
        labels = {
            child.objectName(): child.text()
            for child in widget.findChildren(QLabel)
        }

        self.assertEqual(labels.get("chatRole"), "write_file")
        self.assertEqual(labels.get("chatChip"), "write")
        body = widget.findChild(QTextBrowser, "chatBody")
        self.assertEqual(body.toPlainText().strip(), "denied")
        chip = next(
            child
            for child in widget.findChildren(QLabel)
            if child.objectName() == "chatChip"
        )
        self.assertEqual(chip.property("state"), "problem")

    def test_markdown_bodies_are_parsed_not_shown_raw(self):
        panel = self._panel()

        panel._append_message(
            "assistant",
            "结论：\n\n- 支持：污染可检索\n- 不支持：端到端\n\n"
            "```python\nassert claim.evidence == \"end-to-end\"\n```",
        )
        APP.processEvents()

        widget = panel.message_list.itemWidget(panel.message_list.item(0))
        body = widget.findChild(QTextBrowser, "chatBody")
        plain = body.toPlainText()

        self.assertNotIn("```", plain)
        self.assertNotIn("- 支持", plain)
        self.assertIn("支持：污染可检索", plain)
        self.assertIn("assert claim.evidence", plain)
        # The list and the code block are separate blocks, not one line.
        self.assertGreater(body.document().blockCount(), 3)

    def test_code_style_follows_the_theme_mode(self):
        panel = self._panel()

        panel._append_message("assistant", "回答：\n\n```python\nx = 1\n```")
        APP.processEvents()
        widget = panel.message_list.itemWidget(panel.message_list.item(0))
        body = widget.findChild(QTextBrowser, "chatBody")
        self.assertIn(
            markdown_style("light"),
            body.document().defaultStyleSheet(),
        )

        panel.set_theme_mode("dark")

        self.assertIn(
            markdown_style("dark"),
            body.document().defaultStyleSheet(),
        )
        self.assertNotEqual(
            markdown_style("light"),
            markdown_style("dark"),
        )
        # Re-rendering keeps the message text intact.
        self.assertIn("x = 1", body.toPlainText())

    def _send(self, panel, text):
        panel.input_edit.setPlainText(text)
        APP.processEvents()
        panel.send_button.click()

    def test_send_shows_user_and_assistant_messages(self):
        self._configure_provider()
        engine = FakeEngine(reply_text="pong")
        panel = self._panel(engines={"openai": engine})

        self._send(panel, "ping")
        self.assertTrue(
            self._wait_until(lambda: len(engine.calls) == 1 and panel._thread is None)
        )

        items = self._items(panel)
        self.assertEqual([role for role, _, _ in items], ["user", "assistant"])
        self.assertIn("ping", items[0][1])
        self.assertIn("pong", items[1][1])
        self.assertEqual(engine.calls[0]["messages"][0].content, "ping")
        self.assertEqual(panel.input_edit.toPlainText(), "")
        self.assertFalse(panel.send_button.isEnabled())
        self.assertTrue(panel.stop_button.isHidden())
        self.assertTrue(panel.input_edit.isEnabled())

    def test_registered_http_tool_is_advertised_from_the_project_bridge(self):
        self._configure_http_tool()
        engine = FakeEngine(reply_text="with registry")
        panel = self._panel(engines={"openai": engine})
        panel.set_project(write_project(self.root, "http-tools"))

        self._send(panel, "find a paper")
        self.assertTrue(self._wait_until(lambda: len(engine.calls) == 1))

        names = {
            item["function"]["name"] for item in engine.calls[0]["tools"]
        }
        self.assertIn("paper_lookup", names)
        self.assertIn("milestones_due", names)

    def test_reload_configuration_activates_a_new_registry_without_restart(self):
        self._configure_provider()
        panel = self._panel(engines={"openai": FakeEngine()})
        panel.set_project(write_project(self.root, "reload-http-tools"))
        before = {
            item["function"]["name"]
            for item in panel._tool_bridge.openai_tools()
        }
        self.assertNotIn("paper_lookup", before)

        self._configure_http_tool()
        panel.reload_configuration()

        after = {
            item["function"]["name"]
            for item in panel._tool_bridge.openai_tools()
        }
        self.assertIn("paper_lookup", after)
        self.assertIn("tools=11", panel.hint_label.text())

    def test_invalid_registry_fails_closed_without_leaking_file_content(self):
        self._configure_provider()
        leak = "sk-REGISTRY-PLAINTEXT-DO-NOT-SHOW"
        registry = self.root / "bad-tools.yaml"
        registry.write_text(
            "version: 1\ntools:\n  - name: leaked_tool\n"
            "    description: broken\n    method: GET\n    risk: read\n"
            "    url: https://example.test\n"
            f"    headers:\n      Authorization: {leak}\n"
            "    parameters:\n      type: object\n"
            "      properties: {value: {type: string}}\n"
            "      additionalProperties: false\n",
            encoding="utf-8",
        )
        loaded = Settings(
            provider=ProviderSettings(
                name="local",
                base_url=BASE_URL,
                model="gpt-test",
                key_name="local",
                timeout_s=30.0,
            ),
            http_tools_path=registry.name,
        )
        save_settings(self.settings_path, loaded)
        engine = FakeEngine()
        panel = self._panel(engines={"openai": engine})
        panel.set_project(write_project(self.root, "invalid-http-tools"))

        panel.refresh_status()

        self.assertIn("HTTP 工具注册表不可用", panel.hint_label.text())
        self.assertIn("registry-literal-secret", panel.hint_label.text())
        self.assertNotIn(leak, panel.hint_label.text())
        names = {
            item["function"]["name"]
            for item in panel._tool_bridge.openai_tools()
        }
        self.assertNotIn("leaked_tool", names)
        self.assertIn("milestones_due", names)

    def test_ctrl_enter_shortcut_sends_the_message(self):
        self._configure_provider()
        engine = FakeEngine(reply_text="shortcut")
        panel = self._panel(engines={"openai": engine})
        panel.input_edit.setPlainText("via keyboard")
        APP.processEvents()

        QTest.keyClick(
            panel.input_edit,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.ControlModifier,
        )

        self.assertTrue(self._wait_until(lambda: len(engine.calls) == 1))
        self.assertEqual(engine.calls[0]["messages"][0].content, "via keyboard")

    def test_running_state_disables_send_and_shows_stop(self):
        self._configure_provider()
        engine = FakeEngine(reply_text="slow", delay=5.0)
        panel = self._panel(engines={"openai": engine})

        self._send(panel, "long job")
        self.assertTrue(engine.started.wait(2.0))
        APP.processEvents()

        self.assertFalse(panel.send_button.isEnabled())
        self.assertFalse(panel.input_edit.isEnabled())
        self.assertFalse(panel.stop_button.isHidden())
        self.assertIn("停止", panel.stop_button.text())

    def test_stop_cancels_slow_engine_and_restores_ui(self):
        self._configure_provider()
        engine = FakeEngine(reply_text="slow", delay=5.0)
        panel = self._panel(engines={"openai": engine})

        self._send(panel, "long job")
        self.assertTrue(engine.started.wait(2.0))
        panel.stop_button.click()

        self.assertTrue(
            self._wait_until(lambda: engine.cancelled and panel._thread is None)
        )
        self.assertTrue(panel.stop_button.isHidden())
        self.assertTrue(panel.input_edit.isEnabled())
        panel.input_edit.setPlainText("next question")
        APP.processEvents()
        self.assertTrue(panel.send_button.isEnabled())
        self.assertTrue(
            any("已停止" in text for _, text, _ in self._items(panel))
        )

    def test_engine_error_shows_error_style_and_keeps_input(self):
        self._configure_provider()
        engine = FakeEngine(error=EngineError("backend exploded"))
        panel = self._panel(engines={"openai": engine})

        self._send(panel, "retry me")
        self.assertTrue(self._wait_until(lambda: panel._thread is None))

        items = self._items(panel)
        self.assertEqual([role for role, _, _ in items], ["user", "error"])
        self.assertIn("backend exploded", items[1][1])
        self.assertEqual(items[1][2], QColor("#b00020"))
        self.assertEqual(panel.input_edit.toPlainText(), "retry me")

    def test_write_confirmation_runs_on_the_gui_thread(self):
        panel = self._panel(engines={"openai": FakeEngine()})
        project_dir = write_project(self.root, "confirm-thread")
        panel.set_project(project_dir)
        gui_thread_id = threading.get_ident()
        observed = {}
        result = {}
        done = threading.Event()

        def fake_question(*args, **kwargs):
            observed["thread_id"] = threading.get_ident()
            observed["thread_name"] = threading.current_thread().name
            if QThread.currentThread() is not QApplication.instance().thread():
                observed["failure"] = "confirmation ran off the GUI thread"
                return QMessageBox.StandardButton.No
            observed["on_gui_thread"] = True
            return QMessageBox.StandardButton.No

        def worker():
            try:
                result["value"] = panel._tool_bridge.execute(
                    "memory_add_idea",
                    {"idea": "thread check", "date": "2026-10-04"},
                )
            finally:
                done.set()

        with mock.patch.object(
            QMessageBox,
            "question",
            side_effect=fake_question,
        ):
            worker_thread = threading.Thread(
                target=worker,
                name="confirm-worker",
            )
            worker_thread.start()
            self.assertTrue(self._wait_until(lambda: done.is_set()))
            worker_thread.join(timeout=5.0)

        print(
            "CONFIRM_THREAD_ID="
            f"{observed.get('thread_id')} GUI_THREAD_ID={gui_thread_id}"
        )
        print(f"CONFIRM_THREAD_NAME={observed.get('thread_name')}")
        self.assertIsNone(observed.get("failure"))
        self.assertTrue(observed.get("on_gui_thread"))
        self.assertEqual(observed.get("thread_id"), gui_thread_id)
        self.assertFalse(result["value"]["ok"])
        self.assertEqual(
            result["value"]["error"]["code"],
            "user-declined",
        )

    def test_pending_write_confirmation_aborts_when_stopped(self):
        panel = self._panel(engines={"openai": FakeEngine()})
        panel.set_project(write_project(self.root, "confirm-stop"))
        panel._cancel_event = threading.Event()
        panel.write_confirmation_requested.disconnect()
        panel.write_confirmation_requested.connect(
            lambda name, arguments, box: None,
            Qt.ConnectionType.DirectConnection,
        )
        result = {}
        done = threading.Event()

        def worker():
            result["value"] = panel._ask_write_confirmation(
                "memory_add_idea",
                {},
            )
            done.set()

        worker_thread = threading.Thread(
            target=worker,
            name="confirm-stop-worker",
        )
        started = time.monotonic()
        worker_thread.start()
        time.sleep(0.2)
        panel._cancel_event.set()
        self.assertTrue(done.wait(3.0))
        worker_thread.join(timeout=3.0)
        elapsed = time.monotonic() - started
        panel._cancel_event = None

        self.assertFalse(result["value"])
        self.assertLess(elapsed, 3.0)

    def test_engine_switch_uses_the_selected_engine(self):
        self._configure_provider()
        openai_engine = FakeEngine(reply_text="from openai")
        codex_engine = FakeEngine(reply_text="from codex")
        panel = self._panel(
            engines={"openai": openai_engine, "codex": codex_engine}
        )

        self._send(panel, "first")
        self.assertTrue(self._wait_until(lambda: len(openai_engine.calls) == 1))
        panel.engine_combo.setCurrentIndex(panel.engine_combo.findData("codex"))
        panel.model_edit.setText("gpt-5-codex")
        APP.processEvents()
        self._send(panel, "second")
        self.assertTrue(self._wait_until(lambda: len(codex_engine.calls) == 1))

        self.assertEqual(len(openai_engine.calls), 1)
        self.assertEqual(self.created["kind"], "codex")
        self.assertEqual(self.created["model"], "gpt-5-codex")
        self.assertIsNone(self.created["settings"])

    def test_unconfigured_provider_blocks_send_without_calling_engine(self):
        factory = self._factory()
        panel = self._panel(factory=factory)

        self._send(panel, "hello")
        APP.processEvents()

        self.assertIn("未配置 provider", panel.hint_label.text())
        self.assertNotIn("engines", self.created)

    def test_missing_key_blocks_send_without_calling_engine(self):
        self._configure_provider(key=None)
        factory = self._factory()
        panel = self._panel(factory=factory)

        self._send(panel, "hello")
        APP.processEvents()

        self.assertIn("未配置 API key", panel.hint_label.text())
        self.assertNotIn("engines", self.created)

    def test_unavailable_keyring_shows_hint_without_crashing(self):
        self._configure_provider()
        panel = self._panel(
            factory=self._factory(),
            store=UnavailableSecretStore(),
        )

        self._send(panel, "hello")
        APP.processEvents()

        self.assertIn("凭据后端不可用", panel.hint_label.text())
        self.assertNotIn("engines", self.created)

    def test_credential_errors_never_leak_secret_text(self):
        self._configure_provider()
        leak = "sk-CHAT-LEAK-9999"

        class ExplodingStore:
            def get(self, key_name):
                raise RuntimeError(leak)

        panel = self._panel(store=ExplodingStore())

        hint = panel.hint_label.text()
        self.assertNotIn(leak, hint)
        self.assertNotIn(leak.encode("utf-8"), hint.encode("utf-8"))
        self.assertIn("RuntimeError", hint)

        panel.refresh_status()
        hint = panel.hint_label.text()
        self.assertNotIn(leak, hint)
        self.assertNotIn(leak.encode("utf-8"), hint.encode("utf-8"))
        self.assertIn("RuntimeError", hint)

        self.assertIsNone(panel._prepare_engine())
        hint = panel.hint_label.text()
        self.assertNotIn(leak, hint)
        self.assertNotIn(leak.encode("utf-8"), hint.encode("utf-8"))
        self.assertIn("RuntimeError", hint)

    def test_unavailable_keyring_errors_never_leak_secret_text(self):
        self._configure_provider()
        leak = "sk-CHAT-BACKEND-LEAK-9999"

        class LeakyUnavailableStore:
            def get(self, key_name):
                raise SecretStoreUnavailable(leak)

        panel = self._panel(store=LeakyUnavailableStore())

        for name, action in (
            ("refresh_status", panel.refresh_status),
            ("prepare_engine", panel._prepare_engine),
        ):
            with self.subTest(path=name):
                action()
                hint = panel.hint_label.text()
                self.assertNotIn(leak, hint)
                self.assertNotIn(
                    leak.encode("utf-8"),
                    hint.encode("utf-8"),
                )
                self.assertIn("SecretStoreUnavailable", hint)

    def test_codex_engine_does_not_require_provider(self):
        engine = FakeEngine(reply_text="codex ok")
        factory = self._factory(engines={"codex": engine})
        panel = self._panel(factory=factory, kind="codex")
        panel.model_edit.setText("gpt-5-codex")

        self._send(panel, "hello")
        self.assertTrue(
            self._wait_until(
                lambda: len(engine.calls) == 1 and panel._thread is None
            )
        )

        self.assertEqual(self.created["kind"], "codex")
        self.assertIsNone(self.created["settings"])
        self.assertIn("codex ok", self._items(panel)[-1][1])

    def test_send_stays_disabled_while_input_is_empty(self):
        panel = self._panel(engines={"openai": FakeEngine()})

        self.assertFalse(panel.send_button.isEnabled())
        panel.input_edit.setPlainText("text")
        APP.processEvents()
        self.assertTrue(panel.send_button.isEnabled())

    def test_send_does_not_block_the_ui_thread(self):
        self._configure_provider()
        engine = FakeEngine(reply_text="slow", delay=0.6)
        panel = self._panel(engines={"openai": engine})
        panel.input_edit.setPlainText("responsiveness")
        APP.processEvents()

        started = time.monotonic()
        panel.send_button.click()
        elapsed = time.monotonic() - started
        APP.processEvents()

        self.assertLess(
            elapsed,
            0.1,
            f"send blocked the UI thread for {elapsed:.3f}s",
        )
        panel.stop_button.click()
        self.assertTrue(self._wait_until(lambda: panel._thread is None))

    def test_render_is_non_blank_with_visible_controls(self):
        panel = self._panel(engines={"openai": FakeEngine()})

        image = panel.grab().toImage()
        path = self.root / "chat-panel.png"
        self.assertTrue(image.save(str(path), "PNG"))

        self.assertGreater(image.width(), 500)
        self.assertGreater(image.height(), 400)
        ratio = image_non_background_ratio(image)
        self.assertGreater(
            ratio,
            0.02,
            f"non-background ratio too low: {ratio}",
        )
        for widget in (
            panel.engine_combo,
            panel.message_list,
            panel.input_edit,
            panel.send_button,
            panel.hint_label,
        ):
            with self.subTest(widget=type(widget).__name__):
                self.assertTrue(widget.isVisible())
                self.assertGreater(widget.width(), 0)
                self.assertGreater(widget.height(), 0)
        size = path.stat().st_size
        self.assertGreater(size, 0)
        print(f"CHAT_SCREENSHOT_RATIO={ratio:.4f}")
        print(f"CHAT_SCREENSHOT_PATH={path}")
        print(f"CHAT_SCREENSHOT_BYTES={size}")

    def test_window_mounts_the_chat_panel(self):
        write_project(self.root, "chat-demo", mode="conference", stage="idea")
        window = MainWindow(
            repo_root=self.root,
            secret_store=self.secrets,
            settings_path=self.settings_path,
            collaboration_probes=False,
        )
        window.resize(1100, 760)
        window.show()
        APP.processEvents()
        self.addCleanup(self._dispose_window, window)

        self.assertTrue(hasattr(window, "chat_panel"))
        self.assertEqual(window.chat_panel.engine_combo.count(), 2)
        self.assertTrue(window.chat_panel.isVisible())
        self.assertGreater(window.chat_panel.width(), 0)
        self.assertGreater(window.chat_panel.height(), 0)

    @staticmethod
    def _dispose_window(window):
        window.close()
        window.deleteLater()
        APP.processEvents()


if __name__ == "__main__":
    unittest.main()
