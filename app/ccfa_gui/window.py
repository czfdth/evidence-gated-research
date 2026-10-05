"""Main window: project list, stage panel, checks and settings entry."""

from __future__ import annotations

import re
import os
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QThreadPool, Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QImage
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ccfa_core.checks import (
    CheckError,
    run_milestones_due,
    run_validate,
)
from ccfa_core.checks import run_checkpoints as load_checkpoints
from ccfa_core.checks import run_readiness as load_readiness
from ccfa_core.checks import export_readiness as write_readiness_report
from ccfa_core.projects import (
    ProjectError,
    deadline_note,
    find_projects,
    load_project,
    stages_for,
)
from ccfa_core.secrets import KeyringSecretStore, SecretStoreUnavailable
from ccfa_core.settings import default_settings_path, load_settings
from ccfa_core.state import (
    StageTransitionError,
    rollback_stage,
    set_stage,
    transition_targets,
)

from .chat_panel import ChatPanel
from .collaboration_probe import CollaborationProbe
from .flow_layout import FlowLayout
from .stage_dialog import StageTransitionDialog
from .settings_dialog import SettingsDialog
from . import appearance, icons, theme

_SHARED_LIBRARY_DIR = Path(__file__).resolve().parents[2] / "library"

# Below this width the conversation column is worth more as horizontal room for
# the project detail pane; the toolbar toggle brings it back on demand.
CHAT_COLLAPSE_WIDTH = 1000

# Motion is short and only ever used to explain a layout change: 180ms for the
# conversation column, 140ms for swapping the detail page. Disable with
# animations=False (tests) or CCFA_NO_ANIM=1 (reduced-motion preference).
CHAT_ANIMATION_MS = 180
PAGE_ANIMATION_MS = 140
CHAT_PANE_MIN_WIDTH = 300

# Absolute path tokens inside a workflow error message ("C:\...\ccfa.yaml").
_PATH_TOKEN = re.compile(r"[A-Za-z]:[\\/][^\s]*|file://[^\s]*")
_REASON_LIMIT = 56

# Long workflow error clauses shortened for one-line list rows.
_REASON_ALIASES = {
    "项目状态解析失败": "解析失败",
    "无法读取项目状态": "无法读取",
}


def short_error_reason(
    error: str,
    *,
    limit: int = _REASON_LIMIT,
    terse: bool = False,
) -> str:
    """Fold a multi-line project error into one short, path-free reason.

    Sidebar rows and badges have to stay one line wide, so the absolute path is
    dropped here and preserved in the tooltip and in the results table. ``terse``
    also collapses the long leading clause, for rows with ~20 characters.
    """

    head = next(
        (line.strip() for line in (error or "").splitlines() if line.strip()),
        "",
    )
    if not head:
        return "无法读取"
    parts = _PATH_TOKEN.split(head, maxsplit=1)
    candidate = parts[0].strip(" \t:：-—") or parts[-1].strip(" \t:：-—")
    if not candidate:
        candidate = head
    if terse:
        candidate = _REASON_ALIASES.get(candidate, candidate)
    if len(candidate) > limit:
        candidate = candidate[: limit - 1].rstrip() + "…"
    return candidate


def image_non_background_ratio(image: QImage) -> float:
    """Return the fraction of sampled pixels differing from the top-left one."""
    if image.isNull() or image.width() == 0 or image.height() == 0:
        return 0.0
    background = image.pixelColor(0, 0)
    step = max(1, min(image.width(), image.height()) // 100)
    sampled = 0
    different = 0
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            sampled += 1
            if image.pixelColor(x, y) != background:
                different += 1
    return different / sampled if sampled else 0.0


class MainWindow(QMainWindow):
    def __init__(
        self,
        repo_root: Path,
        *,
        secret_store=None,
        settings_path: Path | None = None,
        parent=None,
        animations: bool | None = None,
        collaboration_probes: bool = True,
    ):
        super().__init__(parent)
        if animations is None:
            animations = os.environ.get("CCFA_NO_ANIM") != "1"
        self._animations = bool(animations)
        self._chat_animation: QPropertyAnimation | None = None
        self._page_animation: QPropertyAnimation | None = None
        self._repo_root = Path(repo_root)
        self._secret_store = secret_store or KeyringSecretStore()
        self._settings_path = (
            Path(settings_path)
            if settings_path is not None
            else default_settings_path(self._repo_root)
        )
        # Collaboration probes run off the GUI thread; each refresh bumps the
        # generation so a result from a stale scan is dropped instead of
        # painting an old answer onto a rebuilt list.
        self._refs: list = []
        self._git_states: dict = {}
        self._probe_generation = 0
        self._probe_tasks: list = []
        # One shared pool: probing a paper costs a workflow subprocess, so the
        # app must not start a fresh pool per window.
        self._probe_pool = QThreadPool.globalInstance()
        self._probe_pool.setMaxThreadCount(
            min(4, max(1, self._probe_pool.maxThreadCount()))
        )
        self._collaboration_probes = bool(collaboration_probes)
        self._build_ui()
        self.refresh_projects()
        self._update_credential_status()

    def _build_ui(self) -> None:
        self.setWindowTitle("论文工作台")
        self._mode = appearance.current_mode()
        self._palette = theme.palette(self._mode)
        self._chat_override: bool | None = None
        self._was_wide = True
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_toolbar())

        splitter = QSplitter(Qt.Orientation.Horizontal, central)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_detail())
        splitter.addWidget(self._build_conversation())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([220, 520, 380])
        outer.addWidget(splitter, stretch=1)

        self.credential_label = QLabel("")
        self.credential_label.setObjectName("credential_label")
        self.workflow_label = QLabel("")
        self.workflow_label.setObjectName("workflow_label")
        self.workflow_label.setProperty("role", "hint")
        self.status_separator = QLabel("·")
        self.status_separator.setObjectName("statusSeparator")
        self.statusBar().addPermanentWidget(self.workflow_label)
        self.statusBar().addPermanentWidget(self.status_separator)
        self.statusBar().addPermanentWidget(self.credential_label)
        self._apply_theme()
        appearance.watch(self._on_system_scheme_changed)

    def _apply_theme(self) -> None:
        """Paint the window with the current mode and recolour its icons."""

        self._palette = theme.palette(self._mode)
        self.setStyleSheet(theme.stylesheet(self._mode))
        self.chat_panel.set_theme_mode(self._mode)
        self._apply_icons()
        self._apply_responsive_layout(animate=False)

    def _apply_icons(self) -> None:
        ink = self._palette["ink"]
        muted = self._palette["muted"]
        self.app_mark.setPixmap(icons.app_mark(22, colour=self._palette["accent"]))
        self.refresh_button.setIcon(icons.icon("refresh", colour=ink))
        self.settings_button.setIcon(icons.icon("settings", colour=ink))
        self.chat_toggle.setIcon(icons.icon("chat", colour=ink))
        self.open_dir_button.setIcon(icons.icon("folder", colour=muted))
        self.export_button.setIcon(icons.icon("export", colour=muted))
        self.validate_button.setIcon(icons.icon("validate", colour="#ffffff"))
        self.milestones_button.setIcon(icons.icon("milestones", colour=ink))
        self.readiness_button.setIcon(icons.icon("readiness", colour=ink))
        self.stages_button.setIcon(icons.icon("stages", colour=ink))
        self.checkpoints_button.setIcon(icons.icon("checkpoints", colour=ink))
        self.chat_panel.send_button.setIcon(icons.icon("send", colour=ink))
        self.placeholder_icon.setPixmap(
            icons.pixmap("inbox", colour=self._palette["placeholder_icon"], size=44)
        )

    def _on_system_scheme_changed(self) -> None:
        mode = appearance.current_mode()
        if mode != self._mode:
            self._mode = mode
            self._apply_theme()

    def _on_chat_toggled(self, checked: bool) -> None:
        self._chat_override = bool(checked)
        self._set_chat_visible(bool(checked))

    def _set_chat_visible(self, visible: bool, *, animate: bool = True) -> None:
        """Show/hide the conversation column, sliding it when motion is on."""

        card = self.chat_card
        if self._chat_animation is not None:
            self._chat_animation.stop()
            self._chat_animation = None
        if not (animate and self._animations) or not self.isVisible():
            card.setMinimumWidth(CHAT_PANE_MIN_WIDTH if visible else 0)
            card.setMaximumWidth(16777215)
            card.setVisible(visible)
            return
        target = max(CHAT_PANE_MIN_WIDTH, card.width() or CHAT_PANE_MIN_WIDTH)
        if visible:
            card.setMinimumWidth(0)
            card.setMaximumWidth(0)
            card.setVisible(True)
        start, end = (0, target) if visible else (card.width(), 0)
        animation = QPropertyAnimation(card, b"maximumWidth", self)
        animation.setDuration(CHAT_ANIMATION_MS)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.finished.connect(lambda: self._finish_chat_motion(visible))
        self._chat_animation = animation
        animation.start()

    def _finish_chat_motion(self, visible: bool) -> None:
        self.chat_card.setMinimumWidth(
            CHAT_PANE_MIN_WIDTH if visible else 0
        )
        self.chat_card.setMaximumWidth(16777215)
        self.chat_card.setVisible(visible)
        self._chat_animation = None

    def _show_stack_page(self, index: int) -> None:
        """Switch the detail pane, fading the incoming page when motion is on."""

        if self.detail_stack.currentIndex() == index:
            return
        self.detail_stack.setCurrentIndex(index)
        if not self._animations or not self.isVisible():
            return
        page = self.detail_stack.currentWidget()
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(PAGE_ANIMATION_MS)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.finished.connect(lambda: page.setGraphicsEffect(None))
        self._page_animation = animation
        animation.start()

    def _apply_responsive_layout(self, *, animate: bool = True) -> None:
        wide = self.width() >= CHAT_COLLAPSE_WIDTH
        if wide != self._was_wide:
            # Crossing the breakpoint clears a manual choice, so the automatic
            # rule wins again next time the window changes size class.
            self._chat_override = None
            self._was_wide = wide
        visible = wide if self._chat_override is None else self._chat_override
        if self.chat_card.isVisible() != visible:
            self._set_chat_visible(visible, animate=animate)
        self.chat_toggle.blockSignals(True)
        self.chat_toggle.setChecked(visible)
        self.chat_toggle.blockSignals(False)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def _build_toolbar(self) -> QWidget:
        bar = QFrame(self)
        bar.setObjectName("toolbar")
        bar.setFixedHeight(40)
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(6)

        self.app_mark = QLabel()
        self.app_mark.setObjectName("appMark")
        self.app_mark.setPixmap(icons.app_mark(22))
        row.addWidget(self.app_mark)
        self.app_title = QLabel("论文工作台")
        self.app_title.setObjectName("appTitle")
        row.addWidget(self.app_title)
        row.addSpacing(10)

        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setObjectName("refresh_button")
        self.refresh_button.setIcon(icons.icon("refresh", colour=theme.INK))
        self.refresh_button.setToolTip("重新扫描 papers/ 下的项目")
        self.refresh_button.clicked.connect(self.refresh_projects)
        row.addWidget(self.refresh_button)

        self.settings_button = QPushButton("设置")
        self.settings_button.setObjectName("settings_button")
        self.settings_button.setIcon(icons.icon("settings", colour=theme.INK))
        self.settings_button.setToolTip("provider、密钥与工作流目录")
        self.settings_button.clicked.connect(self.open_settings)
        row.addWidget(self.settings_button)

        self.chat_toggle = QPushButton()
        self.chat_toggle.setObjectName("chat_toggle")
        self.chat_toggle.setCheckable(True)
        self.chat_toggle.setChecked(True)
        self.chat_toggle.setToolTip("显示或隐藏对话栏（窄窗口会自动收起）")
        self.chat_toggle.setFixedWidth(36)
        self.chat_toggle.clicked.connect(self._on_chat_toggled)
        row.addWidget(self.chat_toggle)

        row.addStretch(1)
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("summary_label")
        self.summary_label.setProperty("role", "hint")
        row.addWidget(self.summary_label)
        return bar

    def _build_sidebar(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("card")
        column = QVBoxLayout(panel)
        column.setContentsMargins(10, 10, 10, 10)
        column.setSpacing(6)
        title = QLabel("项目")
        title.setObjectName("sectionTitle")
        column.addWidget(title)
        self.project_list = QListWidget()
        self.project_list.setObjectName("project_list")
        self.project_list.currentItemChanged.connect(self._on_project_selected)
        self.project_list.itemDoubleClicked.connect(self._on_project_double_clicked)
        self.project_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        column.addWidget(self.project_list, stretch=1)
        panel.setMinimumWidth(180)
        return panel

    def _build_detail(self) -> QWidget:
        panel = QWidget(self)
        column = QVBoxLayout(panel)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)

        header = QFrame(panel)
        header.setObjectName("card")
        head = QVBoxLayout(header)
        head.setContentsMargins(12, 10, 12, 10)
        head.setSpacing(6)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self.project_title = QLabel("未选择项目")
        self.project_title.setObjectName("projectTitle")
        title_row.addWidget(self.project_title)
        title_row.addStretch(1)
        self.open_dir_button = QPushButton()
        self.open_dir_button.setObjectName("open_dir_button")
        self.open_dir_button.setIcon(icons.icon("folder", colour=theme.MUTED))
        self.open_dir_button.setToolTip("在文件管理器中打开项目目录")
        self.open_dir_button.setFixedSize(26, 26)
        self.open_dir_button.setEnabled(False)
        self.open_dir_button.clicked.connect(self._open_project_dir)
        title_row.addWidget(self.open_dir_button)
        self.export_button = QPushButton()
        self.export_button.setObjectName("export_button")
        self.export_button.setIcon(icons.icon("export", colour=theme.MUTED))
        self.export_button.setToolTip(
            "导出 readiness 一页式报告（写入 reviews/readiness-<日期>.md 并打开）"
        )
        self.export_button.setFixedSize(26, 26)
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_readiness_report)
        title_row.addWidget(self.export_button)
        head.addLayout(title_row)
        self.project_note = QLabel("从左侧选择一个项目")
        self.project_note.setObjectName("projectNote")
        self.project_note.setProperty("role", "hint")
        head.addWidget(self.project_note)
        badges = QHBoxLayout()
        badges.setSpacing(6)
        self.stage_label = QLabel("")
        self.stage_label.setObjectName("stage_label")
        self.gate_label = QLabel("")
        self.gate_label.setObjectName("gate_label")
        self.deadline_label = QLabel("")
        self.deadline_label.setObjectName("deadline_label")
        for widget in (self.stage_label, self.gate_label, self.deadline_label):
            widget.setProperty("role", "badge")
            widget.setVisible(False)
            badges.addWidget(widget)
        badges.addStretch(1)
        head.addLayout(badges)
        self.gate_criterion_label = QLabel("")
        self.gate_criterion_label.setObjectName("gateCriterion")
        self.gate_criterion_label.setProperty("role", "hint")
        self.gate_criterion_label.setWordWrap(True)
        self.gate_criterion_label.setVisible(False)
        head.addWidget(self.gate_criterion_label)
        column.addWidget(header)

        # A flow layout keeps every action readable: the pane is narrow whenever
        # the conversation column is open, and a box layout would elide the
        # button text instead of using a second line.
        actions_widget = QWidget(panel)
        actions = FlowLayout(actions_widget, h_spacing=6, v_spacing=6)
        self.validate_button = QPushButton("运行 validate")
        self.validate_button.setObjectName("validate_button")
        self.validate_button.setProperty("role", "primary")
        self.validate_button.setIcon(icons.icon("validate", colour="#ffffff"))
        self.validate_button.setToolTip("校验当前项目的 ccfa.yaml")
        self.validate_button.clicked.connect(self.run_validate)
        actions.addWidget(self.validate_button)
        self.milestones_button = QPushButton("运行 milestones")
        self.milestones_button.setObjectName("milestones_button")
        self.milestones_button.setIcon(icons.icon("milestones", colour=theme.INK))
        self.milestones_button.setToolTip("检查倒排里程碑与到期项")
        self.milestones_button.clicked.connect(self.run_milestones)
        actions.addWidget(self.milestones_button)
        self.readiness_button = QPushButton("运行 readiness")
        self.readiness_button.setObjectName("readiness_button")
        self.readiness_button.setIcon(icons.icon("readiness", colour=theme.INK))
        self.readiness_button.setToolTip(
            "跑一遍 readiness：六个维度、每个 gate 的结论、阻塞清单"
        )
        self.readiness_button.clicked.connect(self.run_readiness)
        actions.addWidget(self.readiness_button)
        self.stages_button = QPushButton("阶段流转")
        self.stages_button.setObjectName("stages_button")
        self.stages_button.setIcon(icons.icon("stages", colour=theme.INK))
        self.stages_button.setToolTip(
            "推进或回退 stage：写回 ccfa.yaml 并记入 stage.history"
        )
        self.stages_button.clicked.connect(self.open_stage_dialog)
        actions.addWidget(self.stages_button)
        self.checkpoints_button = QPushButton("待人工复核")
        self.checkpoints_button.setObjectName("checkpoints_button")
        self.checkpoints_button.setIcon(icons.icon("checkpoints", colour=theme.INK))
        self.checkpoints_button.setToolTip(
            "读出 readiness 的人工复核队列：要判断什么、写进哪个台账"
        )
        self.checkpoints_button.clicked.connect(self.run_checkpoints)
        actions.addWidget(self.checkpoints_button)
        policy = actions_widget.sizePolicy()
        policy.setHeightForWidth(True)
        actions_widget.setSizePolicy(policy)
        column.addWidget(actions_widget)
        # The summary keeps its own line: inside the wrapping row it would wrap
        # alone as soon as the buttons filled the width.
        self.results_summary = QLabel("尚未运行检查")
        self.results_summary.setObjectName("results_summary")
        self.results_summary.setProperty("role", "hint")
        column.addWidget(self.results_summary)

        self.checkpoint_banner = QLabel("")
        self.checkpoint_banner.setObjectName("checkpoint_banner")
        self.checkpoint_banner.setWordWrap(True)
        self.checkpoint_banner.setVisible(False)
        column.addWidget(self.checkpoint_banner)

        # Two ways to show the same pane: check results (table) and the human
        # decision queue (cards). A stack keeps each one's layout honest.
        self.detail_stack = QStackedWidget()

        self.results_table = QTableWidget(0, 3)
        self.results_table.setObjectName("results_table")
        self.results_table.setHorizontalHeaderLabels(["来源", "代码", "消息"])
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.results_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        header_view = self.results_table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.detail_stack.addWidget(self.results_table)

        self.checkpoint_scroll = QScrollArea()
        self.checkpoint_scroll.setObjectName("checkpoint_scroll")
        self.checkpoint_scroll.setWidgetResizable(True)
        self.checkpoint_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.checkpoint_container = QWidget()
        self.checkpoint_container.setObjectName("checkpoint_container")
        self.checkpoint_layout = QVBoxLayout(self.checkpoint_container)
        self.checkpoint_layout.setContentsMargins(0, 0, 0, 0)
        self.checkpoint_layout.setSpacing(8)
        self.checkpoint_layout.addStretch(1)
        self.checkpoint_scroll.setWidget(self.checkpoint_container)
        self.detail_stack.addWidget(self.checkpoint_scroll)

        self.placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self.placeholder)
        placeholder_layout.setContentsMargins(24, 24, 24, 24)
        placeholder_layout.setSpacing(8)
        placeholder_layout.addStretch(1)
        self.placeholder_icon = QLabel()
        self.placeholder_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_layout.addWidget(self.placeholder_icon)
        self.placeholder_title = QLabel("")
        self.placeholder_title.setObjectName("placeholderTitle")
        self.placeholder_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_layout.addWidget(self.placeholder_title)
        self.placeholder_hint = QLabel("")
        self.placeholder_hint.setObjectName("placeholderHint")
        self.placeholder_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_hint.setWordWrap(True)
        placeholder_layout.addWidget(self.placeholder_hint)
        placeholder_layout.addStretch(1)
        self.detail_stack.addWidget(self.placeholder)

        self.detail_stack.setCurrentIndex(0)
        self._checkpoint_cards: list[QFrame] = []
        column.addWidget(self.detail_stack, stretch=1)
        panel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        # Explicit minimums on all three panes keep the window able to shrink to
        # the breakpoint above; without this the detail pane's natural minimum
        # keeps the window wider than the collapse threshold.
        panel.setMinimumWidth(320)
        return panel

    def _build_conversation(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("card")
        self.chat_card = panel
        column = QVBoxLayout(panel)
        column.setContentsMargins(10, 10, 10, 10)
        column.setSpacing(6)
        title = QLabel("对话")
        title.setObjectName("sectionTitle")
        column.addWidget(title)
        self.chat_panel = ChatPanel(
            self._settings_path,
            secret_store=self._secret_store,
            library_dir=_SHARED_LIBRARY_DIR,
        )
        column.addWidget(self.chat_panel, stretch=1)
        panel.setMinimumWidth(300)
        return panel

    def _selected_ref(self):
        item = self.project_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _set_results(self, rows) -> None:
        self._show_stack_page(0)
        self.results_table.setRowCount(0)
        actionable = 0
        for source, code, message in rows:
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            for column, value in enumerate((source, code, message)):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                if column == 1:
                    font = QFont()
                    font.setFamilies(
                        ["JetBrains Mono", "Consolas", "Cascadia Mono"]
                    )
                    font.setPointSize(9)
                    item.setFont(font)
                    text = str(code)
                    if text not in {"OK", "无问题"}:
                        actionable += 1
                    item.setForeground(
                        QBrush(QColor(theme.severity_color(text, self._mode)))
                    )
                self.results_table.setItem(row, column, item)
        if not rows:
            self.results_summary.setText("尚未运行检查")
            self.results_summary.setStyleSheet(f"color: {self._palette['muted']};")
            return
        if actionable:
            self.results_summary.setText(
                f"{len(rows)} 条结果 · {actionable} 条需处理"
            )
            colour = self._palette["problem"]
        else:
            self.results_summary.setText(f"{len(rows)} 条结果 · 全部通过")
            colour = self._palette["ok"]
        self.results_summary.setStyleSheet(f"color: {colour};")

    def _set_badge(self, label: QLabel, text: str, *, state: str | None = None) -> None:
        """Set one header badge, re-polishing so ``[state]`` styling applies."""

        label.setText(text)
        label.setProperty("state", state)
        label.style().unpolish(label)
        label.style().polish(label)
        label.setVisible(bool(text))

    def _clear_stage_panel(self, message: str = "未选择项目") -> None:
        self.project_title.setText(message)
        self.project_title.setToolTip("")
        self.project_note.setText("从左侧选择一个项目")
        self.project_note.setToolTip("")
        self.open_dir_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.gate_criterion_label.setText("")
        self.gate_criterion_label.setVisible(False)
        self._set_badge(self.stage_label, "")
        self._set_badge(self.gate_label, "")
        self._set_badge(self.deadline_label, "")
        self.deadline_label.setToolTip("")

    def _show_placeholder(
        self,
        title: str,
        hint: str,
        *,
        icon_name: str = "inbox",
    ) -> None:
        """Empty state for the detail pane: icon, one line, then the hint."""

        self.placeholder_icon.setPixmap(
            icons.pixmap(icon_name, colour=self._palette["placeholder_icon"], size=44)
        )
        self.placeholder_title.setText(title)
        self.placeholder_hint.setText(hint)
        self._show_stack_page(2)

    def _show_project_error(self, slug: str, error: str) -> None:
        """Show a broken project without spilling a traceback across the header."""

        self.project_title.setText(slug)
        self.project_title.setToolTip(error)
        self.project_note.setText(short_error_reason(error))
        self.project_note.setToolTip(error)
        self._set_badge(self.stage_label, f"无法读取 {slug}", state="problem")
        self._set_badge(self.gate_label, "配置无效", state="problem")
        self._set_badge(self.deadline_label, "截止 未知")
        self.gate_criterion_label.setText("")
        self.gate_criterion_label.setVisible(False)

    def _open_project_dir(self) -> None:
        ref = self._selected_ref()
        if ref is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ref.dir)))

    def _on_project_double_clicked(self, item: QListWidgetItem) -> None:
        ref = item.data(Qt.ItemDataRole.UserRole) if item else None
        if ref is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(ref.dir)))

    def refresh_projects(self) -> None:
        self.project_list.blockSignals(True)
        self.project_list.clear()
        refs = find_projects(self._repo_root)
        self._refs = refs
        self._git_states = {}
        for ref in refs:
            if ref.error is None:
                text = f"● {ref.slug}"
            else:
                text = f"▲ {ref.slug} — {short_error_reason(ref.error, terse=True)}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, ref)
            if ref.error:
                item.setForeground(QBrush(QColor("red")))
                item.setToolTip(ref.error)
            else:
                item.setToolTip(f"papers/{ref.slug}")
            self.project_list.addItem(item)
        self._update_summary()
        self.project_list.blockSignals(False)
        if refs:
            self.project_list.setCurrentRow(0)
        else:
            self._clear_stage_panel()
            self._set_results([])
            self._show_placeholder(
                "还没有论文项目",
                "在仓库根运行 scripts/new-paper.ps1 my-paper --venue NeurIPS "
                "--year 2027 --mode conference 创建第一篇，然后点「刷新」。",
            )
            self.chat_panel.set_project(None)
        self._start_collaboration_probes()

    def _select_slug(self, slug: str) -> None:
        """Re-select one project by slug after the list has been rebuilt."""

        for row in range(self.project_list.count()):
            item = self.project_list.item(row)
            ref = item.data(Qt.ItemDataRole.UserRole) if item else None
            if ref is not None and ref.slug == slug:
                self.project_list.setCurrentRow(row)
                return

    def _start_collaboration_probes(self) -> None:
        """Ask the workflow about each readable project, off the GUI thread."""

        self._probe_generation += 1
        generation = self._probe_generation
        self._probe_pool.clear()
        self._probe_tasks = []
        if not self._collaboration_probes:
            return
        for ref in self._refs:
            if ref.error is not None:
                continue
            task = CollaborationProbe(generation, ref.slug, ref.dir)
            task.signals.done.connect(self._apply_collaboration)
            # The pool owns the C++ side; keeping the Python wrapper and its
            # signal object alive keeps the queued emission deliverable.
            self._probe_tasks.append(task)
            self._probe_pool.start(task)

    def _apply_collaboration(self, generation: int, slug: str, state) -> None:
        if generation != self._probe_generation:
            return
        self._git_states[slug] = state
        self._update_project_row(slug, state)
        self._update_summary()

    def _update_project_row(self, slug: str, state) -> None:
        for row in range(self.project_list.count()):
            item = self.project_list.item(row)
            ref = item.data(Qt.ItemDataRole.UserRole) if item else None
            if ref is None or ref.error is not None or ref.slug != slug:
                continue
            warnings = state.warnings
            # The glyph and the colour are the whole row signal: a long slug
            # would push any inline reason into "· 有未提", and the sidebar
            # tooltip already names each problem in full.
            marker = "◆" if warnings else "●"
            item.setText(f"{marker} {slug}")
            if warnings:
                item.setForeground(
                    QBrush(QColor(self._palette["advisory"]))
                )
            else:
                item.setForeground(QBrush(QColor(self._palette["ink"])))
            item.setToolTip(self._collaboration_tooltip(ref, state))
            return

    def _collaboration_tooltip(self, ref, state) -> str:
        lines = [f"papers/{ref.slug}"]
        if state.error:
            lines.append(state.error)
        elif not state.present:
            lines.append("不是 git 仓库：版本、快照与 run-log commit 都会落空")
        else:
            lines.append(f"提交 {state.commit or '未知'}")
            lines.append("remote：" + ("、".join(state.remotes) or "无"))
            lines.append(
                "CI workflows：有" if state.workflows_present else "CI workflows：无"
            )
            lines.append(
                "未提交改动：有" if state.dirty else "未提交改动：无"
            )
        for reason in state.blocking:
            lines.append(f"· {reason}")
        return "\n".join(lines)

    def _update_summary(self) -> None:
        refs = self._refs
        if not refs:
            self.summary_label.setText("papers/ 下没有项目")
            return
        broken = sum(1 for ref in refs if ref.error)
        risky = sum(
            1
            for ref in refs
            if ref.error is None
            and ref.slug in self._git_states
            and bool(self._git_states[ref.slug].warnings)
        )
        parts = [f"{len(refs)} 个项目"]
        if broken:
            parts.append(f"{broken} 个无法读取")
        if risky:
            parts.append(f"{risky} 个有协作风险")
        self.summary_label.setText(" · ".join(parts))

    def _on_project_selected(self, _current, _previous) -> None:
        ref = self._selected_ref()
        self._set_results([])
        self._hide_checkpoint_banner()
        self._clear_checkpoint_cards()
        if ref is None:
            self._clear_stage_panel()
            self._show_placeholder(
                "未选择项目",
                "从左侧选择一个项目查看阶段、门禁与检查结果。",
            )
            self.chat_panel.set_project(None)
            return
        self.open_dir_button.setEnabled(True)
        self.export_button.setEnabled(True)
        if ref.error:
            self._show_project_error(ref.slug, ref.error)
            self._set_results([("ccfa.yaml", "错误", ref.error)])
            self.chat_panel.set_project(None)
            return
        try:
            state = load_project(ref.dir)
        except ProjectError as exc:
            self._show_project_error(ref.slug, str(exc))
            self._set_results([("ccfa.yaml", "错误", str(exc))])
            self.chat_panel.set_project(None)
            return
        self.project_title.setText(ref.slug)
        self.project_title.setToolTip(str(ref.dir))
        self.project_note.setText(f"模式 {state.mode} · 更新于 {state.updated_at}")
        self.project_note.setToolTip(str(ref.dir))
        self._set_badge(self.stage_label, f"阶段 {state.current_stage}")
        self._set_badge(self.gate_label, f"门禁 {state.gate}")
        # The badge row is tight at narrow widths, so it carries the countdown
        # and the tooltip keeps the absolute date.
        self._set_badge(self.deadline_label, f"截止 {deadline_note(state.deadline)}")
        self.deadline_label.setToolTip(
            f"目标日 {state.deadline}" if state.deadline else "未设置投稿截止日"
        )
        criterion = state.gate_criterion
        self.gate_criterion_label.setText(
            f"门禁判据：{criterion}" if criterion else ""
        )
        self.gate_criterion_label.setToolTip(criterion)
        self.gate_criterion_label.setVisible(bool(criterion))
        self.chat_panel.set_project(ref.dir)

    def _selected_project_error(self):
        ref = self._selected_ref()
        if ref is None:
            return "未选择项目"
        return ref.error

    def run_validate(self) -> None:
        self._hide_checkpoint_banner()
        error = self._selected_project_error()
        if error:
            self._set_results([("validate", "错误", error)])
            return
        try:
            result = run_validate(self._selected_ref().dir)
        except CheckError as exc:
            self._set_results([("validate", "错误", str(exc))])
            return
        if result.problems:
            rows = [("validate", "问题", str(problem)) for problem in result.problems]
        else:
            rows = [("validate", "OK", "无问题")]
        self._set_results(rows)

    def run_milestones(self) -> None:
        self._hide_checkpoint_banner()
        error = self._selected_project_error()
        if error:
            self._set_results([("milestones", "错误", error)])
            return
        try:
            result = run_milestones_due(self._selected_ref().dir)
        except CheckError as exc:
            self._set_results([("milestones", "错误", str(exc))])
            return
        report = result.report or {}
        due = report.get("due", [])
        rows = [
            (
                "milestones",
                "OK" if result.ok else "问题",
                f"mode={report.get('mode')}, due={len(due)}",
            )
        ]
        for problem in result.problems:
            if isinstance(problem, dict):
                rows.append(
                    (
                        "milestones",
                        problem.get("code", "problem"),
                        problem.get("message", ""),
                    )
                )
            else:
                rows.append(("milestones", "problem", str(problem)))
        self._set_results(rows)

    def _hide_checkpoint_banner(self) -> None:
        self.checkpoint_banner.setVisible(False)

    def run_readiness(self) -> None:
        """Render the workflow's readiness report for the selected project."""

        ref = self._selected_ref()
        if ref is None or ref.error:
            self._hide_checkpoint_banner()
            self._clear_checkpoint_cards()
            self._set_results([("readiness", "错误", "先选择一个可读取的项目")])
            return
        try:
            result = load_readiness(ref.dir)
        except CheckError as exc:
            self._hide_checkpoint_banner()
            self._clear_checkpoint_cards()
            self._set_results([("readiness", "错误", str(exc))])
            return
        report = result.report or {}
        dimensions = report.get("dimensions")
        dimensions = dimensions if isinstance(dimensions, dict) else {}
        verdicts = report.get("verdicts")
        verdicts = verdicts if isinstance(verdicts, dict) else {}

        rows: list[tuple[str, str, str]] = [
            ("维度", str(status), str(name))
            for name, status in dimensions.items()
        ]
        rows.extend(
            ("gate", str(verdict), str(name))
            for name, verdict in sorted(verdicts.items())
            if verdict not in {"pass"}
        )
        rows.extend(("阻塞", "问题", str(item)) for item in result.problems)
        self._clear_checkpoint_cards()
        self._set_results(rows or [("readiness", "OK", "报告里没有维度信息")])

        counts: dict[str, int] = {}
        for verdict in verdicts.values():
            key = str(verdict)
            counts[key] = counts.get(key, 0) + 1
        self.results_summary.setText(
            f"ready={str(bool(report.get('ready'))).lower()} · "
            f"{len(result.problems)} 条阻塞"
        )
        self.results_summary.setStyleSheet(
            f"color: {self._palette['ok'] if result.ok else self._palette['problem']};"
        )
        profile = report.get("profile")
        assurance = report.get("assurance")
        if result.ok:
            self._show_banner(
                "ok",
                f"ready=true（profile {profile} / assurance {assurance}）",
            )
        else:
            first = result.problems[0] if result.problems else "见 gate 结论"
            gates = " ".join(f"{name}={count}" for name, count in sorted(counts.items()))
            self._show_banner(
                "pending",
                f"ready=false · 阻塞 {len(result.problems)} 条 · {first}"
                + (f" · gate {gates}" if gates else ""),
            )

    def export_readiness_report(self) -> None:
        """Write the workflow's one-page readiness report and open it."""

        ref = self._selected_ref()
        if ref is None or ref.error:
            self._hide_checkpoint_banner()
            self._set_results([("readiness", "错误", "先选择一个可读取的项目")])
            return
        try:
            path = write_readiness_report(ref.dir)
        except CheckError as exc:
            self._hide_checkpoint_banner()
            self._set_results([("readiness", "错误", str(exc))])
            return
        try:
            display = path.relative_to(Path(ref.dir)).as_posix()
        except ValueError:
            display = str(path)
        self._hide_checkpoint_banner()
        self._set_results([("readiness", "OK", f"已导出 {display}")])
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _show_banner(self, state: str, text: str) -> None:
        self.checkpoint_banner.setText(text)
        self.checkpoint_banner.setProperty("state", state)
        self.checkpoint_banner.style().unpolish(self.checkpoint_banner)
        self.checkpoint_banner.style().polish(self.checkpoint_banner)
        self.checkpoint_banner.setVisible(True)

    def _show_checkpoint_banner(self, status: str, count: int) -> None:
        if status == "pending-human-review":
            self._show_banner(
                "pending",
                f"待人工复核：{count} 项。脚本只能证明它还没被回答，不能替你回答。"
            )
        elif status == "human-attested":
            self._show_banner("ok", "人工复核账本已完成，没有待办。")
        else:
            self._show_banner(
                "muted",
                f"当前 profile 不要求人工复核（status={status}）。",
            )

    def run_checkpoints(self) -> None:
        ref = self._selected_ref()
        if ref is None or ref.error:
            self._hide_checkpoint_banner()
            self._clear_checkpoint_cards()
            self._set_results([("readiness", "错误", "先选择一个可读取的项目")])
            return
        try:
            result = load_checkpoints(ref.dir)
        except CheckError as exc:
            self._hide_checkpoint_banner()
            self._clear_checkpoint_cards()
            self._set_results([("readiness", "错误", str(exc))])
            return
        human = (result.report or {}).get("human_review")
        human = human if isinstance(human, dict) else {}
        checkpoints = [
            item
            for item in human.get("checkpoints", [])
            if isinstance(item, dict)
        ]
        self._clear_checkpoint_cards()
        if checkpoints:
            for item in checkpoints:
                self._add_checkpoint_card(item)
            self._show_stack_page(1)
            self.results_summary.setText(f"{len(checkpoints)} 项待人工")
            self.results_summary.setStyleSheet(f"color: {self._palette['problem']};")
        else:
            self._set_results(
                [("readiness", "OK", "当前没有待人工复核项")]
            )
        self._show_checkpoint_banner(
            str(human.get("status", "unknown")),
            len(checkpoints),
        )

    def checkpoint_card_count(self) -> int:
        return len(self._checkpoint_cards)

    def _clear_checkpoint_cards(self) -> None:
        while self.checkpoint_layout.count() > 1:
            item = self.checkpoint_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._checkpoint_cards = []

    def _add_checkpoint_card(self, checkpoint: dict) -> None:
        card = QFrame()
        card.setObjectName("checkpointCard")
        body = QVBoxLayout(card)
        body.setContentsMargins(12, 10, 12, 10)
        body.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        kind = str(checkpoint.get("type") or "review")
        chip = QLabel(kind)
        chip.setProperty("role", "badge")
        if kind == "feedback":
            chip.setProperty("state", "advisory")
        top.addWidget(chip)
        top.addStretch(1)
        ledger = str(checkpoint.get("ledger") or "")
        open_button = QPushButton("打开台账")
        open_button.setObjectName("open_ledger_button")
        open_button.setEnabled(bool(ledger))
        open_button.setToolTip(f"打开 {ledger}" if ledger else "该 checkpoint 没有指定台账")
        open_button.clicked.connect(
            lambda _checked=False, target=ledger: self._open_ledger(target)
        )
        top.addWidget(open_button)
        body.addLayout(top)

        question = QLabel(
            str(checkpoint.get("question") or checkpoint.get("id") or "待人工复核")
        )
        question.setObjectName("checkpointQuestion")
        question.setWordWrap(True)
        body.addWidget(question)

        meta_text = " — ".join(
            part
            for part in (ledger, str(checkpoint.get("answer_with") or ""))
            if part
        )
        meta = QLabel(meta_text)
        meta.setObjectName("checkpointMeta")
        meta.setWordWrap(True)
        body.addWidget(meta)

        self.checkpoint_layout.insertWidget(
            self.checkpoint_layout.count() - 1,
            card,
        )
        self._checkpoint_cards.append(card)

    def _open_ledger(self, relative: str) -> None:
        ref = self._selected_ref()
        if ref is None or not relative:
            return
        project_root = Path(ref.dir).resolve()
        target = (project_root / relative).resolve()
        # The ledger path comes from the workflow's JSON: never leave the
        # project directory because of it.
        if project_root not in target.parents and target != project_root:
            return
        if target.is_file() or target.is_dir():
            opened = target
        else:
            # The ledger does not exist yet: open the nearest existing ancestor
            # so the user can create it, never a path outside the project.
            opened = target.parent
            while not opened.exists() and project_root in opened.parents:
                opened = opened.parent
            if not opened.exists():
                opened = project_root
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(opened)))

    def open_stage_dialog(self) -> None:
        """Ask for one transition, then hand it to the workflow's own state tool."""

        ref = self._selected_ref()
        if ref is None or ref.error:
            self._set_results([("state", "错误", "先选择一个可读取的项目")])
            return
        try:
            state = load_project(ref.dir)
            stages = stages_for(state.mode)
        except (ProjectError, ValueError) as exc:
            self._set_results([("state", "错误", str(exc))])
            return
        targets = {
            kind: transition_targets(kind, state.current_stage, stages)
            for kind in ("advance", "rollback")
        }
        if not targets["advance"] and not targets["rollback"]:
            self._set_results([("state", "错误", "该项目没有可流转的阶段")])
            return
        dialog = StageTransitionDialog(
            current=state.current_stage,
            targets=targets,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply_stage_transition(
            dialog.kind(),
            dialog.target(),
            dialog.reason(),
            dialog.void_artifacts(),
        )

    def _apply_stage_transition(
        self,
        kind: str,
        to: str,
        reason: str,
        void_artifacts=(),
    ) -> None:
        """Perform one transition and show what the workflow wrote back."""

        ref = self._selected_ref()
        if ref is None or ref.error:
            self._set_results([("state", "错误", "先选择一个可读取的项目")])
            return
        slug = ref.slug
        label = "回退" if kind == "rollback" else "推进"
        try:
            if kind == "rollback":
                entry = rollback_stage(
                    ref.dir,
                    to=to,
                    reason=reason,
                    void_artifacts=void_artifacts,
                )
            else:
                entry = set_stage(ref.dir, to=to, reason=reason)
        except StageTransitionError as exc:
            self._set_results([("state", "错误", str(exc))])
            self._show_banner("pending", f"阶段流转失败：{exc}")
            return

        from_stage = str(entry.get("from", ""))
        gate = str(entry.get("gate", ""))
        rows = [
            ("state", "OK", f"{label} {from_stage} → {to}（门禁 {gate}）"),
        ]
        if kind == "rollback":
            voided = entry.get("void_artifacts") or []
            rows.append(
                (
                    "state",
                    "作废",
                    "、".join(str(item) for item in voided) or "无",
                )
            )
        # Rebuilding the list re-reads ccfa.yaml, so the header badges show the
        # workflow's new state rather than the app's assumption about it. It
        # also clears the results pane, so the outcome is written afterwards.
        self.refresh_projects()
        self._select_slug(slug)
        self._set_results(rows)
        self._show_banner("ok", f"阶段已{label}：{from_stage} → {to}")

    def _update_credential_status(self) -> None:
        try:
            self._secret_store.get("__ccfa_status_probe__")
        except SecretStoreUnavailable:
            self.credential_label.setText("● 凭据不可用")
            self.credential_label.setToolTip(
                "系统密钥环不可访问，API key 无法保存或读取"
            )
            self.credential_label.setStyleSheet(f"color: {self._palette['problem']};")
        else:
            self.credential_label.setText("● 凭据可用")
            self.credential_label.setToolTip("系统密钥环可读写")
            self.credential_label.setStyleSheet(f"color: {self._palette['ok']};")
        try:
            settings = load_settings(self._settings_path)
        except ValueError:
            self.workflow_label.setText("工作流：配置无效")
            self.workflow_label.setStyleSheet(f"color: {self._palette['problem']};")
            return
        root = settings.workflow_root
        if root:
            self.workflow_label.setText(f"工作流：{root}")
            self.workflow_label.setToolTip(
                "在设置里可测试连接；也可用 CCFA_WORKFLOW_ROOT 覆盖"
            )
        else:
            self.workflow_label.setText("工作流：默认（仓库根）")

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self._settings_path,
            self._secret_store,
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._update_credential_status()
            self.chat_panel.reload_configuration()
