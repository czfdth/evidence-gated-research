"""Chat panel: engine selection, message list and background execution.

The engine itself always runs on a worker thread; replies, failures and
stop notifications come back to the GUI thread through Qt signals.
"""

from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import (
    QBrush,
    QColor,
    QKeySequence,
    QShortcut,
    QTextCursor,
    QTextOption,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ccfa_core.engines.base import ChatMessage, EngineError

from . import icons, theme
from ccfa_core.engines.codex_exec import CodexExecEngine
from ccfa_core.engines.openai_compat import OpenAICompatibleEngine
from ccfa_core.http_tools import HttpToolRegistry, load_registry
from ccfa_core.secrets import KeyringSecretStore, SecretStoreUnavailable
from ccfa_core.settings import load_settings
from ccfa_core.tools_bridge import ToolBridge, openai_tools
from ccfa_core.workflow import WorkflowClient

ENGINE_OPENAI = "openai"
ENGINE_CODEX = "codex"

WRITE_CONFIRM_TIMEOUT_S = 300.0

# QTextDocument cannot resolve the workbench stylesheet, so the code style is
# built from the palette in code: monospace always, plus the mode's chip colour
# as the code background.
CODE_FONT = "'JetBrains Mono', Consolas, 'Cascadia Mono', monospace"


def markdown_style(mode: object = "light") -> str:
    background = theme.palette(mode)["code_bg"]
    return (
        f"code, pre {{ font-family: {CODE_FONT}; background-color: "
        f"{background}; }}"
    )

ROLE_PREFIXES = {
    "user": "你",
    "assistant": "助手",
    "error": "错误",
    "stopped": "已停止",
    "tool": "工具",
}
ROLE_COLORS = {
    "user": QColor("#1a4d8f"),
    "assistant": QColor("#1b5e20"),
    "error": QColor("#b00020"),
    "stopped": QColor("#8a6d00"),
    "tool": QColor("#5b2c86"),
}


def _split_tool(text: str) -> tuple[str, str, str]:
    """Split ``name [risk] -> outcome`` into its three parts."""

    name, separator, rest = text.partition(" [")
    if not separator:
        return text, "", ""
    risk, bracket, tail = rest.partition("]")
    if not bracket:
        return text, "", ""
    return name.strip(), risk.strip(), tail.lstrip(" ->").strip()


def _tool_state(outcome: str) -> str:
    lowered = outcome.casefold()
    if lowered.startswith(("ok", "allowed", "confirmed", "success")):
        return "ok"
    if lowered.startswith(("error", "denied", "refused", "fail")):
        return "problem"
    return "advisory"


def default_engine_factory(*, kind, model, settings, secret_store):
    """Build the engine selected in the combo box.

    ``settings`` is None for codex (no provider is required); OpenAI-compatible
    engines use the active provider and resolve the key from ``secret_store``.
    """
    if kind == ENGINE_CODEX:
        return CodexExecEngine(model=model)
    if settings is None or settings.provider is None:
        raise ValueError("未配置 provider")
    provider = settings.provider
    return OpenAICompatibleEngine(
        base_url=provider.base_url,
        model=provider.model,
        secret_store=secret_store,
        key_name=provider.key_name,
        timeout_s=provider.timeout_s,
    )


class ChatPanel(QWidget):
    """Chat UI with a background engine worker."""

    reply_ready = Signal(object)
    run_failed = Signal(str)
    run_stopped = Signal(str)
    run_finished = Signal()
    tool_called = Signal(object)
    write_confirmation_requested = Signal(str, object, object)

    def __init__(
        self,
        settings_path: Path,
        *,
        secret_store=None,
        engine_factory=None,
        library_dir=None,
        parent=None,
    ):
        super().__init__(parent)
        self._settings_path = Path(settings_path)
        self._secret_store = (
            secret_store if secret_store is not None else KeyringSecretStore()
        )
        self._engine_factory = engine_factory or default_engine_factory
        self._library_dir = (
            Path(library_dir) if library_dir is not None else None
        )
        self._history = []
        self._thread = None
        self._cancel_event = None
        self._running = False
        self._in_flight_text = ""
        self._mode = theme.DEFAULT_MODE
        self._tool_bridge = None
        self._project_root = None
        self._registry_issue_codes = ()
        self.write_confirmer = self._ask_write_confirmation
        self._build_ui()
        self.reply_ready.connect(self._on_reply)
        self.run_failed.connect(self._on_failed)
        self.run_stopped.connect(self._on_stopped)
        self.run_finished.connect(self._on_run_finished)
        self.tool_called.connect(self._on_tool_call)
        self.write_confirmation_requested.connect(
            self._show_write_confirmation
        )
        self._on_engine_changed()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("引擎"))
        self.engine_combo = QComboBox()
        self.engine_combo.setObjectName("engine_combo")
        self.engine_combo.addItem("OpenAI 兼容", ENGINE_OPENAI)
        self.engine_combo.addItem("codex exec", ENGINE_CODEX)
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        top.addWidget(self.engine_combo)
        self.model_label = QLabel("Codex 模型（可选）")
        self.model_edit = QLineEdit()
        self.model_edit.setObjectName("codex_model_edit")
        self.model_edit.setPlaceholderText("留空使用 codex 默认模型")
        top.addWidget(self.model_label)
        top.addWidget(self.model_edit, stretch=1)
        layout.addLayout(top)

        self.message_list = QListWidget()
        self.message_list.setObjectName("chat_messages")
        self.message_list.setWordWrap(True)
        layout.addWidget(self.message_list, stretch=1)

        self.hint_label = QLabel("")
        self.hint_label.setObjectName("chat_hint")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        self.input_edit = QPlainTextEdit()
        self.input_edit.setObjectName("chat_input")
        self.input_edit.setPlaceholderText("输入消息，Ctrl+Enter 发送")
        self.input_edit.setFixedHeight(90)
        self.input_edit.textChanged.connect(self._update_send_enabled)
        layout.addWidget(self.input_edit)

        buttons = QHBoxLayout()
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("chat_send_button")
        self.send_button.setIcon(icons.icon("send", colour=theme.INK))
        self.send_button.clicked.connect(self.send_message)
        buttons.addWidget(self.send_button)
        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("chat_stop_button")
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.hide()
        buttons.addWidget(self.stop_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.send_shortcuts = [
            QShortcut(
                QKeySequence("Ctrl+Return"),
                self,
                activated=self.send_message,
            ),
            QShortcut(
                QKeySequence("Ctrl+Enter"),
                self,
                activated=self.send_message,
            ),
        ]
        for shortcut in self.send_shortcuts:
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._update_send_enabled()

    def _kind(self) -> str:
        return self.engine_combo.currentData()

    def _on_engine_changed(self, *_args) -> None:
        is_codex = self._kind() == ENGINE_CODEX
        self.model_label.setVisible(is_codex)
        self.model_edit.setVisible(is_codex)
        self.refresh_status()

    def refresh_status(self) -> None:
        """Refresh the pre-send hint from the current settings and keyring."""
        if self._running:
            return
        if self._kind() == ENGINE_CODEX:
            self._set_hint("codex exec：使用本机 CLI，模型可留空")
            return
        try:
            settings = load_settings(self._settings_path)
        except ValueError as exc:
            self._set_hint(f"设置读取失败: {exc}")
            return
        registry_issue_codes = self._registry_codes(settings)
        provider = settings.provider
        if provider is None:
            self._set_hint("未配置 provider：请先在设置中填写 API 配置")
            return
        try:
            value = self._secret_store.get(provider.key_name)
        except SecretStoreUnavailable as exc:
            self._set_hint(f"凭据后端不可用（{type(exc).__name__}）")
            return
        except Exception as exc:
            self._set_hint(f"无法读取凭据（{type(exc).__name__}）")
            return
        if not isinstance(value, str) or not value.strip():
            self._set_hint("未配置 API key：请在设置中保存密钥")
            return
        if registry_issue_codes:
            self._set_hint(
                "HTTP 工具注册表不可用: "
                + ", ".join(registry_issue_codes)
            )
            return
        tool_count = 0
        if self._tool_bridge is not None:
            tool_count = len(self._tool_bridge.openai_tools())
        suffix = f" / tools={tool_count}" if tool_count else ""
        self._set_hint(f"Provider: {provider.name} / {provider.model}{suffix}")

    def send_message(self) -> None:
        """Send the input box content through the selected engine."""
        if self._running:
            return
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        prepared = self._prepare_engine()
        if prepared is None:
            return
        engine, timeout_s = prepared
        tools = None
        if self._kind() == ENGINE_OPENAI and self._tool_bridge is not None:
            if hasattr(engine, "configure_tools"):
                engine.configure_tools(self._tool_bridge.execute)
            tools = self._tool_bridge.openai_tools()
        self._append_message("user", text)
        self._history.append(ChatMessage("user", text))
        self._in_flight_text = text
        self.input_edit.clear()
        self._set_hint("")
        self._set_running(True, getattr(engine, "name", "engine"))
        self._start_worker(engine, list(self._history), timeout_s, tools)

    def stop(self) -> None:
        """Ask the running engine to stop; the worker finishes the UI state."""
        if self._cancel_event is not None:
            self._cancel_event.set()
            self._set_hint("正在停止...")

    def set_project(self, project_root, *, library_dir=None) -> None:
        """Attach the deterministic tools for one project (None clears them)."""
        self._project_root = (
            Path(project_root) if project_root is not None else None
        )
        if project_root is None:
            self._tool_bridge = None
            self._registry_issue_codes = ()
            return
        if library_dir is None:
            library_dir = self._library_dir
        http_tools = self._load_http_tools()
        self._tool_bridge = ToolBridge(
            project_root,
            library_dir=library_dir,
            workflow=self._workflow_client(),
            confirm_write=lambda name, arguments: self.write_confirmer(
                name,
                arguments,
            ),
            on_call=self.tool_called.emit,
            http_tools=http_tools,
        )
        self.refresh_status()

    def reload_configuration(self) -> None:
        """Reload settings and rebuild tools for the selected project."""
        if self._project_root is not None:
            self.set_project(self._project_root)
        else:
            self.refresh_status()

    def _registry_path(self, configured: str) -> Path:
        path = Path(configured)
        if not path.is_absolute():
            path = self._settings_path.parent / path
        return path

    def _registry_codes(self, settings) -> tuple[str, ...]:
        if settings.http_tools_path is None:
            self._registry_issue_codes = ()
            return ()
        _specs, issues = load_registry(
            self._registry_path(settings.http_tools_path),
            reserved_names=tuple(
                item["function"]["name"] for item in openai_tools()
            ),
        )
        codes = tuple(sorted({issue.code for issue in issues}))
        self._registry_issue_codes = codes
        return codes

    def _workflow_client(self) -> WorkflowClient | None:
        """Build the workflow client from settings, if the user configured it.

        Returns ``None`` to let :class:`ToolBridge` use the default discovery
        (environment variable, then the repository layout).
        """

        try:
            settings = load_settings(self._settings_path)
        except ValueError:
            return None
        if settings.workflow_root is None and settings.workflow_python is None:
            return None
        return WorkflowClient(
            settings.workflow_root,
            python=settings.workflow_python,
        )

    def _load_http_tools(self) -> HttpToolRegistry | None:
        try:
            settings = load_settings(self._settings_path)
        except ValueError:
            self._registry_issue_codes = ("settings-invalid",)
            return None
        if settings.http_tools_path is None:
            self._registry_issue_codes = ()
            return None
        specs, issues = load_registry(
            self._registry_path(settings.http_tools_path),
            reserved_names=tuple(
                item["function"]["name"] for item in openai_tools()
            ),
        )
        self._registry_issue_codes = tuple(
            sorted({issue.code for issue in issues})
        )
        if issues:
            return None
        return HttpToolRegistry(
            specs,
            resolve_secret=self._secret_store.get,
        )

    def _ask_write_confirmation(self, name: str, arguments: dict) -> bool:
        """Ask the user to approve a write tool call.

        Qt widgets must stay on the GUI thread: a worker thread emits a
        request and waits (bounded) for the answer, while a direct call from
        the GUI thread shows the dialog immediately.
        """
        if QThread.currentThread() is self.thread():
            return self._show_write_confirmation_now(name, arguments)
        box = {"event": threading.Event(), "allowed": False}
        self.write_confirmation_requested.emit(name, dict(arguments), box)
        deadline = time.monotonic() + WRITE_CONFIRM_TIMEOUT_S
        while not box["event"].wait(0.1):
            if self._cancel_event is not None and self._cancel_event.is_set():
                return False
            if time.monotonic() >= deadline:
                return False
        return bool(box.get("allowed"))

    @Slot(str, object, object)
    def _show_write_confirmation(self, name, arguments, box) -> None:
        try:
            box["allowed"] = self._show_write_confirmation_now(
                name,
                arguments,
            )
        except Exception:
            box["allowed"] = False
        finally:
            box["event"].set()

    def _show_write_confirmation_now(
        self,
        name: str,
        arguments: dict,
    ) -> bool:
        summary = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        if len(summary) > 500:
            summary = summary[:500] + "...[truncated]"
        answer = QMessageBox.question(
            self,
            "确认写操作",
            f"模型请求执行写操作：{name}\n参数：{summary}\n是否允许？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _prepare_engine(self):
        kind = self._kind()
        model = self.model_edit.text().strip()
        if kind == ENGINE_CODEX:
            try:
                engine = self._engine_factory(
                    kind=kind,
                    model=model,
                    settings=None,
                    secret_store=self._secret_store,
                )
            except Exception as exc:
                self._set_hint(f"无法创建引擎: {exc}")
                return None
            return engine, None
        try:
            settings = load_settings(self._settings_path)
        except ValueError as exc:
            self._set_hint(f"设置读取失败: {exc}")
            return None
        provider = settings.provider
        if provider is None:
            self._set_hint("未配置 provider：请先在设置中填写 API 配置")
            return None
        try:
            value = self._secret_store.get(provider.key_name)
        except SecretStoreUnavailable as exc:
            self._set_hint(f"凭据后端不可用（{type(exc).__name__}）")
            return None
        except Exception as exc:
            self._set_hint(f"无法读取凭据（{type(exc).__name__}）")
            return None
        if not isinstance(value, str) or not value.strip():
            self._set_hint("未配置 API key：请在设置中保存密钥")
            return None
        try:
            engine = self._engine_factory(
                kind=kind,
                model=model,
                settings=settings,
                secret_store=self._secret_store,
            )
        except Exception as exc:
            self._set_hint(f"无法创建引擎: {exc}")
            return None
        return engine, float(provider.timeout_s)

    def _start_worker(self, engine, messages, timeout_s, tools=None) -> None:
        self._cancel_event = threading.Event()
        thread = threading.Thread(
            target=self._run_engine,
            args=(engine, messages, timeout_s, self._cancel_event, tools),
            name="chat-engine",
            daemon=True,
        )
        self._thread = thread
        thread.start()

    def _run_engine(
        self,
        engine,
        messages,
        timeout_s,
        cancel_event,
        tools=None,
    ) -> None:
        try:
            reply = engine.send(
                messages,
                tools=tools,
                timeout_s=timeout_s,
                cancel=cancel_event,
            )
        except EngineError as exc:
            if cancel_event.is_set():
                self.run_stopped.emit("已停止")
            else:
                self.run_failed.emit(str(exc))
        except Exception as exc:  # adapter boundary: never kill the UI thread
            self.run_failed.emit(f"引擎异常: {exc}")
        else:
            if cancel_event.is_set():
                self.run_stopped.emit("已停止")
            else:
                self.reply_ready.emit(reply)
        finally:
            self.run_finished.emit()

    def _on_reply(self, reply) -> None:
        text = getattr(reply, "text", str(reply))
        self._append_message("assistant", text)
        self._history.append(ChatMessage("assistant", text))

    def _on_failed(self, message: str) -> None:
        self._append_message("error", message)
        if not self.input_edit.toPlainText().strip() and self._in_flight_text:
            self.input_edit.setPlainText(self._in_flight_text)
        self._in_flight_text = ""
        self._set_hint(f"引擎错误: {message}")

    def _on_stopped(self, message: str) -> None:
        self._append_message("stopped", message)
        self._set_hint(message)

    def _on_tool_call(self, record: dict) -> None:
        tool = record.get("tool", "tool")
        risk = record.get("risk", "?")
        outcome = record.get("outcome", "?")
        self._append_message("tool", f"{tool} [{risk}] -> {outcome}")

    def _on_run_finished(self) -> None:
        self._running = False
        self._thread = None
        self._cancel_event = None
        self._in_flight_text = ""
        self.input_edit.setEnabled(True)
        self.engine_combo.setEnabled(True)
        self.model_edit.setEnabled(True)
        self.stop_button.hide()
        self._update_send_enabled()

    def _set_running(self, running: bool, engine_name: str = "") -> None:
        self._running = running
        if running:
            self.send_button.setEnabled(False)
            self.stop_button.show()
            self.input_edit.setEnabled(False)
            self.engine_combo.setEnabled(False)
            self.model_edit.setEnabled(False)
            self._set_hint(f"运行中（{engine_name}）...")

    def _update_send_enabled(self) -> None:
        has_text = bool(self.input_edit.toPlainText().strip())
        self.send_button.setEnabled(has_text and not self._running)

    def _append_message(self, role: str, text: str) -> QListWidgetItem:
        item = QListWidgetItem(f"{ROLE_PREFIXES.get(role, role)}: {text}")
        item.setData(Qt.ItemDataRole.UserRole, role)
        item.setForeground(QBrush(ROLE_COLORS.get(role, QColor("#333333"))))
        item.setToolTip(str(text))
        self.message_list.addItem(item)
        # The item keeps its plain text (consumers read item.text()), while the
        # widget draws the bubble. Both carry the same content.
        bubble = self._bubble(role, str(text))
        item.setSizeHint(bubble.sizeHint())
        self.message_list.setItemWidget(item, bubble)
        # The first size hint is computed before the stylesheet is applied to
        # the new widget, which clips one-line bubbles; measure again now and
        # once more after the event loop has polished it.
        self._relayout_bubbles()
        QTimer.singleShot(0, self._relayout_bubbles)
        self.message_list.scrollToBottom()
        return item

    def _bubble(self, role: str, text: str) -> QWidget:
        """One message card: role line, optional chip, wrapped body."""

        bubble = QFrame()
        bubble.setObjectName("chatBubble")
        bubble.setProperty("role", role)
        column = QVBoxLayout(bubble)
        column.setContentsMargins(10, 8, 10, 8)
        column.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        title = QLabel(ROLE_PREFIXES.get(role, role))
        title.setObjectName("chatRole")
        head.addWidget(title)

        body_text = text
        if role == "tool":
            tool, risk, outcome = _split_tool(text)
            if risk:
                title.setText(tool)
                chip = QLabel(risk)
                chip.setObjectName("chatChip")
                chip.setProperty("state", _tool_state(outcome))
                head.addWidget(chip)
            body_text = outcome or text
        head.addStretch(1)
        column.addLayout(head)

        # A read-only text view renders the Markdown subset we care about
        # (lists, code fences, emphasis, links) with a document stylesheet, so
        # code is actually monospaced. The list item keeps the raw text.
        body = QTextBrowser()
        body.setObjectName("chatBody")
        body.setFrameShape(QFrame.Shape.NoFrame)
        body.setOpenExternalLinks(False)
        body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        body.document().setDocumentMargin(0)
        wrap = QTextOption()
        wrap.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        body.document().setDefaultTextOption(wrap)
        self._render_body(body, body_text)
        body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        column.addWidget(body)
        return bubble

    def _render_body(self, body: QTextBrowser, text: str) -> None:
        """Render Markdown into *body* using the current mode's code style."""

        body.setProperty("rawText", text)
        body.document().setDefaultStyleSheet(markdown_style(self._mode))
        body.setMarkdown(text)
        # Markdown code fences arrive as non-breakable lines, which would be
        # clipped inside a 400px bubble; let them wrap like the prose.
        cursor = QTextCursor(body.document())
        code_background = QBrush(QColor(theme.palette(self._mode)["code_bg"]))
        block = body.document().begin()
        while block.isValid():
            block_format = block.blockFormat()
            if block_format.nonBreakableLines():
                block_format.setNonBreakableLines(False)
                # Qt's markdown importer marks code fences as non-breakable
                # blocks; that flag is the reliable "this is code" marker, so
                # the background goes on here rather than through the
                # stylesheet (which the importer ignores for block backgrounds).
                block_format.setBackground(code_background)
                cursor.setPosition(block.position())
                cursor.setBlockFormat(block_format)
            block = block.next()

    def set_theme_mode(self, mode: object) -> None:
        """Re-render every bubble when the palette (and so code style) changes."""

        wanted = theme.normalise_mode(mode)
        if wanted == self._mode:
            return
        self._mode = wanted
        for row in range(self.message_list.count()):
            widget = self.message_list.itemWidget(self.message_list.item(row))
            body = (
                widget.findChild(QTextBrowser, "chatBody")
                if widget is not None
                else None
            )
            if body is None:
                continue
            raw = body.property("rawText")
            if isinstance(raw, str):
                self._render_body(body, raw)
        self._relayout_bubbles()

    def _relayout_bubbles(self) -> None:
        """Re-wrap bubbles after the list width changes."""

        available = max(160, self.message_list.viewport().width() - 24)
        for row in range(self.message_list.count()):
            item = self.message_list.item(row)
            widget = self.message_list.itemWidget(item)
            if widget is None:
                continue
            # A fixed width makes the body's viewport width deterministic, so
            # the document is laid out to exactly the space it gets drawn in.
            widget.setFixedWidth(available)
            body = widget.findChild(QTextBrowser, "chatBody")
            if body is not None:
                viewport = max(120, body.viewport().width())
                body.document().setTextWidth(viewport)
                body.setFixedHeight(
                    math.ceil(body.document().size().height()) + 2
                )
            widget.adjustSize()
            item.setSizeHint(widget.sizeHint())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._relayout_bubbles()

    def _set_hint(self, text: str) -> None:
        self.hint_label.setText(text)
