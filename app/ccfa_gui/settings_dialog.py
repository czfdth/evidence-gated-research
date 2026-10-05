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
from ccfa_core.workflow import WorkflowClient

from . import theme


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
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        self.setMinimumWidth(560)

        title = QLabel("设置")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        note = QLabel("API key 只写入系统密钥环，settings.json 里只保存 key 名称。")
        note.setProperty("role", "hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        provider_title = QLabel("模型 provider")
        provider_title.setObjectName("sectionTitle")
        layout.addWidget(provider_title)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        self.name_edit = QLineEdit()
        self.base_url_edit = QLineEdit()
        self.model_edit = QLineEdit()
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(1.0, 3600.0)
        self.timeout_spin.setValue(60.0)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("留空则保留已有 key")
        form.addRow("Provider 名称", self.name_edit)
        form.addRow("Base URL", self.base_url_edit)
        form.addRow("模型", self.model_edit)
        form.addRow("超时（秒）", self.timeout_spin)
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
        form.addRow("HTTP 工具", registry_row)

        self.key_status_label = QLabel("未配置")
        self.key_status_label.setObjectName("key_status_label")
        self.key_status_label.setProperty("role", "hint")
        form.addRow("密钥状态", self.key_status_label)

        layout.addLayout(form)

        layout.addSpacing(6)
        workflow_title = QLabel("工作流")
        workflow_title.setObjectName("sectionTitle")
        layout.addWidget(workflow_title)
        workflow_form = QFormLayout()
        workflow_form.setContentsMargins(0, 0, 0, 0)
        workflow_form.setHorizontalSpacing(12)
        workflow_form.setVerticalSpacing(6)

        workflow_row = QHBoxLayout()
        self.workflow_root_edit = QLineEdit()
        self.workflow_root_edit.setObjectName("workflow_root_edit")
        self.workflow_root_edit.setPlaceholderText(
            "工作流仓库根目录（含 tools/），留空则用环境变量或默认"
        )
        workflow_row.addWidget(self.workflow_root_edit, stretch=1)
        self.workflow_root_browse_button = QPushButton("浏览")
        self.workflow_root_browse_button.setObjectName(
            "workflow_root_browse_button"
        )
        self.workflow_root_browse_button.clicked.connect(
            self._browse_workflow_root
        )
        workflow_row.addWidget(self.workflow_root_browse_button)
        workflow_form.addRow("工作流目录", workflow_row)

        python_row = QHBoxLayout()
        self.workflow_python_edit = QLineEdit()
        self.workflow_python_edit.setObjectName("workflow_python_edit")
        self.workflow_python_edit.setPlaceholderText(
            "可选；留空则用 <工作流目录>/tools/.venv 里的解释器"
        )
        python_row.addWidget(self.workflow_python_edit, stretch=1)
        self.workflow_python_browse_button = QPushButton("浏览")
        self.workflow_python_browse_button.setObjectName(
            "workflow_python_browse_button"
        )
        self.workflow_python_browse_button.clicked.connect(
            self._browse_workflow_python
        )
        python_row.addWidget(self.workflow_python_browse_button)
        workflow_form.addRow("Python 解释器", python_row)

        test_row = QHBoxLayout()
        self.workflow_test_button = QPushButton("测试工作流连接")
        self.workflow_test_button.setObjectName("workflow_test_button")
        self.workflow_test_button.clicked.connect(self._test_workflow)
        test_row.addWidget(self.workflow_test_button)
        self.workflow_status_label = QLabel("")
        self.workflow_status_label.setObjectName("workflow_status_label")
        self.workflow_status_label.setProperty("role", "hint")
        test_row.addWidget(self.workflow_status_label, stretch=1)
        workflow_form.addRow("", test_row)

        layout.addLayout(workflow_form)

        self.error_label = QLabel("")
        self.error_label.setObjectName("error_label")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"color: {theme.PROBLEM};")
        layout.addWidget(self.error_label)

        layout.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.save_button = QPushButton("保存")
        self.save_button.setObjectName("save_button")
        self.save_button.setProperty("role", "primary")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._on_save)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("cancel_button")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
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
        if settings.workflow_root is not None:
            self.workflow_root_edit.setText(settings.workflow_root)
        if settings.workflow_python is not None:
            self.workflow_python_edit.setText(settings.workflow_python)
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

    def _browse_workflow_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择工作流仓库根目录",
            self.workflow_root_edit.text().strip()
            or str(self._settings_path.parent),
        )
        if selected:
            self.workflow_root_edit.setText(selected)

    def _browse_workflow_python(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "选择工作流的 Python 解释器",
            self.workflow_python_edit.text().strip()
            or self.workflow_root_edit.text().strip()
            or str(self._settings_path.parent),
            "Python (python.exe);;所有文件 (*)",
        )
        if selected:
            self.workflow_python_edit.setText(selected)

    def _test_workflow(self) -> None:
        """Probe the workflow using the values currently in the dialog."""

        client = WorkflowClient(
            self.workflow_root_edit.text().strip() or None,
            python=self.workflow_python_edit.text().strip() or None,
        )
        ok, detail = client.probe()
        self.workflow_status_label.setText(detail)
        self.workflow_status_label.setStyleSheet(
            "color: #0b6b2f;" if ok else "color: #b00020;"
        )

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
                    workflow_root=(
                        self.workflow_root_edit.text().strip() or None
                    ),
                    workflow_python=(
                        self.workflow_python_edit.text().strip() or None
                    ),
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
