"""Main window: project list, stage panel, checks and settings entry."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QImage
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ccfa_core.checks import CheckError, run_milestones_due, run_validate
from ccfa_core.projects import ProjectError, find_projects, load_project
from ccfa_core.secrets import KeyringSecretStore, SecretStoreUnavailable
from ccfa_core.settings import default_settings_path

from .chat_panel import ChatPanel
from .settings_dialog import SettingsDialog

_SHARED_LIBRARY_DIR = Path(__file__).resolve().parents[2] / "library"


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
    ):
        super().__init__(parent)
        self._repo_root = Path(repo_root)
        self._secret_store = secret_store or KeyringSecretStore()
        self._settings_path = (
            Path(settings_path)
            if settings_path is not None
            else default_settings_path(self._repo_root)
        )
        self._build_ui()
        self.refresh_projects()
        self._update_credential_status()

    def _build_ui(self) -> None:
        self.setWindowTitle("论文工作台")
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)

        left = QVBoxLayout()
        left.addWidget(QLabel("项目"))
        self.project_list = QListWidget()
        self.project_list.setObjectName("project_list")
        self.project_list.currentItemChanged.connect(self._on_project_selected)
        left.addWidget(self.project_list, stretch=1)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setObjectName("refresh_button")
        self.refresh_button.clicked.connect(self.refresh_projects)
        left.addWidget(self.refresh_button)
        self.settings_button = QPushButton("设置")
        self.settings_button.setObjectName("settings_button")
        self.settings_button.clicked.connect(self.open_settings)
        left.addWidget(self.settings_button)

        right = QVBoxLayout()
        self.stage_label = QLabel("未选择项目")
        self.stage_label.setObjectName("stage_label")
        self.gate_label = QLabel("")
        self.gate_label.setObjectName("gate_label")
        self.deadline_label = QLabel("")
        self.deadline_label.setObjectName("deadline_label")
        right.addWidget(self.stage_label)
        right.addWidget(self.gate_label)
        right.addWidget(self.deadline_label)
        self.results_table = QTableWidget(0, 3)
        self.results_table.setObjectName("results_table")
        self.results_table.setHorizontalHeaderLabels(["来源", "代码", "消息"])
        right.addWidget(self.results_table, stretch=1)
        buttons = QHBoxLayout()
        self.validate_button = QPushButton("运行 validate")
        self.validate_button.setObjectName("validate_button")
        self.validate_button.clicked.connect(self.run_validate)
        buttons.addWidget(self.validate_button)
        self.milestones_button = QPushButton("运行 milestones")
        self.milestones_button.setObjectName("milestones_button")
        self.milestones_button.clicked.connect(self.run_milestones)
        buttons.addWidget(self.milestones_button)
        right.addLayout(buttons)
        self.chat_panel = ChatPanel(
            self._settings_path,
            secret_store=self._secret_store,
            library_dir=_SHARED_LIBRARY_DIR,
        )
        right.addWidget(self.chat_panel, stretch=2)

        outer.addLayout(left, stretch=1)
        outer.addLayout(right, stretch=3)

        self.credential_label = QLabel("")
        self.credential_label.setObjectName("credential_label")
        self.statusBar().addPermanentWidget(self.credential_label)

    def _selected_ref(self):
        item = self.project_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _set_results(self, rows) -> None:
        self.results_table.setRowCount(0)
        for source, code, message in rows:
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            for column, value in enumerate((source, code, message)):
                self.results_table.setItem(
                    row,
                    column,
                    QTableWidgetItem(str(value)),
                )

    def _clear_stage_panel(self, message: str = "未选择项目") -> None:
        self.stage_label.setText(message)
        self.gate_label.setText("")
        self.deadline_label.setText("")

    def refresh_projects(self) -> None:
        self.project_list.blockSignals(True)
        self.project_list.clear()
        refs = find_projects(self._repo_root)
        for ref in refs:
            text = ref.slug if ref.error is None else f"{ref.slug} — {ref.error}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, ref)
            if ref.error:
                item.setForeground(QBrush(QColor("red")))
                item.setToolTip(ref.error)
            self.project_list.addItem(item)
        self.project_list.blockSignals(False)
        if refs:
            self.project_list.setCurrentRow(0)
        else:
            self._clear_stage_panel()
            self._set_results([])
            self.chat_panel.set_project(None)

    def _on_project_selected(self, _current, _previous) -> None:
        ref = self._selected_ref()
        self._set_results([])
        if ref is None:
            self._clear_stage_panel()
            self.chat_panel.set_project(None)
            return
        if ref.error:
            self._clear_stage_panel(f"项目错误: {ref.error}")
            self.chat_panel.set_project(None)
            return
        try:
            state = load_project(ref.dir)
        except ProjectError as exc:
            self._clear_stage_panel(f"项目错误: {exc}")
            self.chat_panel.set_project(None)
            return
        self.stage_label.setText(f"阶段: {state.current_stage}")
        self.gate_label.setText(f"Gate: {state.gate}")
        self.deadline_label.setText(
            f"截止日期: {state.deadline if state.deadline else '无'}"
        )
        self.chat_panel.set_project(ref.dir)

    def _selected_project_error(self):
        ref = self._selected_ref()
        if ref is None:
            return "未选择项目"
        return ref.error

    def run_validate(self) -> None:
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

    def _update_credential_status(self) -> None:
        try:
            self._secret_store.get("__ccfa_status_probe__")
        except SecretStoreUnavailable:
            self.credential_label.setText("凭据后端不可用")
        else:
            self.credential_label.setText("凭据后端可用")

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self._settings_path,
            self._secret_store,
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._update_credential_status()
            self.chat_panel.reload_configuration()
