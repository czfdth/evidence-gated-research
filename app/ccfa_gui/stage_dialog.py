"""Collect one auditable stage transition: direction, target, reason.

The dialog owns no workflow logic. It only lists the targets the workflow's
own stage order allows and refuses to hand back an empty reason, so the window
can call ``ccfa.state`` with the confirmation it demands.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class StageTransitionDialog(QDialog):
    """Ask for the direction, target stage and reason of one transition."""

    def __init__(
        self,
        *,
        current: str,
        targets: dict[str, tuple[str, ...]],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("阶段流转")
        self.setMinimumWidth(420)
        self._current = current
        self._targets = {
            kind: tuple(items) for kind, items in targets.items()
        }
        self._kind = "advance" if self._targets.get("advance") else "rollback"
        self._build_ui()
        self._apply_kind()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel("阶段流转")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        note = QLabel(
            f"当前阶段 {self._current}。流转会写回 ccfa.yaml 的 stage.history，"
            "并同时更新门禁。"
        )
        note.setProperty("role", "hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        row = QHBoxLayout()
        row.setSpacing(0)
        self.advance_button = QPushButton("推进")
        self.advance_button.setObjectName("stage_advance_button")
        self.advance_button.setCheckable(True)
        self.advance_button.setEnabled(bool(self._targets.get("advance")))
        self.rollback_button = QPushButton("回退")
        self.rollback_button.setObjectName("stage_rollback_button")
        self.rollback_button.setCheckable(True)
        self.rollback_button.setEnabled(bool(self._targets.get("rollback")))
        self._kind_group = QButtonGroup(self)
        self._kind_group.setExclusive(True)
        for button in (self.advance_button, self.rollback_button):
            self._kind_group.addButton(button)
            row.addWidget(button)
        self.advance_button.clicked.connect(self._apply_kind)
        self.rollback_button.clicked.connect(self._apply_kind)
        layout.addLayout(row)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.target_combo = QComboBox()
        self.target_combo.setObjectName("stage_target_combo")
        form.addRow("目标阶段", self.target_combo)
        self.reason_edit = QLineEdit()
        self.reason_edit.setObjectName("stage_reason_edit")
        self.reason_edit.setPlaceholderText("为什么流转（必填，会写入 stage.history）")
        form.addRow("原因", self.reason_edit)
        self.void_edit = QPlainTextEdit()
        self.void_edit.setObjectName("stage_void_edit")
        self.void_edit.setPlaceholderText("每行一个作废产物路径（可留空）")
        self.void_edit.setFixedHeight(64)
        self.void_label = QLabel("作废产物")
        form.addRow(self.void_label, self.void_edit)
        layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setObjectName("stage_status_label")
        self.status_label.setProperty("role", "hint")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText("确认流转")
        self.ok_button.setProperty("role", "primary")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.reason_edit.textChanged.connect(self._refresh_ok_state)

    # -- state ---------------------------------------------------------------

    def kind(self) -> str:
        return self._kind

    def target(self) -> str:
        return self.target_combo.currentText()

    def reason(self) -> str:
        return self.reason_edit.text().strip()

    def void_artifacts(self) -> tuple[str, ...]:
        if self._kind != "rollback":
            return ()
        text = self.void_edit.toPlainText()
        return tuple(
            line.strip() for line in text.splitlines() if line.strip()
        )

    # -- widgets -------------------------------------------------------------

    def _apply_kind(self) -> None:
        if self.sender() is self.rollback_button:
            self._kind = "rollback"
        elif self.sender() is self.advance_button:
            self._kind = "advance"
        buttons = {
            "advance": self.advance_button,
            "rollback": self.rollback_button,
        }
        for kind, button in buttons.items():
            checked = kind == self._kind
            button.setChecked(checked)
            button.setProperty("role", "primary" if checked else "plain")
            button.style().unpolish(button)
            button.style().polish(button)

        rolling_back = self._kind == "rollback"
        self.void_label.setVisible(rolling_back)
        self.void_edit.setVisible(rolling_back)

        targets = self._targets.get(self._kind, ())
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        self.target_combo.addItems(targets)
        self.target_combo.blockSignals(False)

        label = "推进" if self._kind == "advance" else "回退"
        if targets:
            self.status_label.setText(f"可{label}到 {len(targets)} 个阶段。")
        else:
            self.status_label.setText(f"没有可{label}的阶段。")
        self._refresh_ok_state()

    def _refresh_ok_state(self) -> None:
        ready = bool(self.target_combo.count()) and bool(self.reason())
        self.ok_button.setEnabled(ready)
        self.ok_button.setToolTip(
            "" if ready else "选择目标阶段并填写原因后才能流转"
        )
