"""Provider settings dialog; the API key never enters settings.json."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ccfa_core.secrets import SecretStoreUnavailable
from ccfa_core.http_tools import load_registry
from ccfa_core.tools_bridge import openai_tools
from ccfa_core.settings import (
    ProviderSettings,
    Settings,
    load_settings,
    save_settings,
)


class SettingsDialog(QDialog):
    def __init__(self, settings_path: Path, secret_store, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API 设置")
        self._settings_path = Path(settings_path)
        self._secret_store = secret_store
        self._key_name = ""
        self._build_ui()
        self._load_current()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.base_url_edit = QLineEdit()
        self.model_edit = QLineEdit()
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(1.0, 3600.0)
        self.timeout_spin.setValue(60.0)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("留空则保留已有 key")
        form.addRow("Provider name", self.name_edit)
        form.addRow("Base URL", self.base_url_edit)
        form.addRow("Model", self.model_edit)
        form.addRow("Timeout (s)", self.timeout_spin)
        form.addRow("API key", self.key_edit)
        registry_row = QHBoxLayout()
        self.http_tools_path_edit = QLineEdit()
        self.http_tools_path_edit.setPlaceholderText("可选，例如 http-tools.yaml")
        registry_row.addWidget(self.http_tools_path_edit, stretch=1)
        self.http_tools_browse_button = QPushButton("浏览")
        self.http_tools_browse_button.setObjectName("http_tools_browse_button")
        self.http_tools_browse_button.clicked.connect(
            self._browse_http_tools
        )
        registry_row.addWidget(self.http_tools_browse_button)
        form.addRow("HTTP tools", registry_row)
        layout.addLayout(form)

        self.key_status_label = QLabel("未配置")
        self.key_status_label.setObjectName("key_status_label")
        layout.addWidget(self.key_status_label)
        self.error_label = QLabel("")
        self.error_label.setObjectName("error_label")
        self.error_label.setStyleSheet("color: #b00020;")
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        self.save_button = QPushButton("保存")
        self.save_button.setObjectName("save_button")
        self.save_button.clicked.connect(self._on_save)
        buttons.addWidget(self.save_button)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("cancel_button")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

    def _load_current(self) -> None:
        try:
            settings = load_settings(self._settings_path)
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        provider = settings.provider
        if settings.http_tools_path is not None:
            self.http_tools_path_edit.setText(settings.http_tools_path)
        if provider is None:
            return
        self.name_edit.setText(provider.name)
        self.base_url_edit.setText(provider.base_url)
        self.model_edit.setText(provider.model)
        self.timeout_spin.setValue(float(provider.timeout_s))
        self._key_name = provider.key_name
        self._refresh_key_status()

    def _refresh_key_status(self) -> None:
        if not self._key_name:
            self.key_status_label.setText("未配置")
            return
        try:
            value = self._secret_store.get(self._key_name)
        except SecretStoreUnavailable:
            self.key_status_label.setText("凭据后端不可用")
            return
        self.key_status_label.setText("已配置" if value else "未配置")

    def _browse_http_tools(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "选择 HTTP 工具注册表",
            str(self._settings_path.parent),
            "YAML (*.yaml *.yml);;所有文件 (*)",
        )
        if selected:
            self.http_tools_path_edit.setText(selected)

    def _registry_path(self, configured: str) -> Path:
        path = Path(configured)
        if not path.is_absolute():
            path = self._settings_path.parent / path
        return path

    def save(self) -> bool:
        name = self.name_edit.text().strip()
        base_url = self.base_url_edit.text().strip()
        model = self.model_edit.text().strip()
        if not name or not base_url or not model:
            self.error_label.setText(
                "provider name / base_url / model 不能为空"
            )
            return False
        http_tools_path = self.http_tools_path_edit.text().strip() or None
        if http_tools_path is not None:
            _specs, issues = load_registry(
                self._registry_path(http_tools_path),
                reserved_names=tuple(
                    item["function"]["name"] for item in openai_tools()
                ),
            )
            if issues:
                codes = ", ".join(sorted({issue.code for issue in issues}))
                self.error_label.setText(
                    f"HTTP 工具注册表不可用: {codes}"
                )
                return False
        key_name = name
        key_value = self.key_edit.text()
        if not key_value and self._key_name:
            # Keep the existing credential linked when the provider is
            # renamed without entering a new key.
            key_name = self._key_name
        if key_value:
            try:
                self._secret_store.set(key_name, key_value)
            except SecretStoreUnavailable as exc:
                self.error_label.setText(str(exc))
                return False
        try:
            save_settings(
                self._settings_path,
                Settings(
                    provider=ProviderSettings(
                        name=name,
                        base_url=base_url,
                        model=model,
                        key_name=key_name,
                        timeout_s=float(self.timeout_spin.value()),
                    ),
                    http_tools_path=http_tools_path,
                ),
            )
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return False
        self._key_name = key_name
        self.key_edit.clear()
        self.error_label.clear()
        self._refresh_key_status()
        return True

    def _on_save(self) -> None:
        if self.save():
            self.accept()
