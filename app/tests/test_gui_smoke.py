import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit

from ccfa_core.checks import CheckResult
from ccfa_core.secrets import SecretStoreUnavailable
from ccfa_core.settings import ProviderSettings, Settings, save_settings
from ccfa_gui.settings_dialog import SettingsDialog
from ccfa_gui.window import MainWindow, image_non_background_ratio

from . import write_project

APP = QApplication.instance() or QApplication([])
FAKE_KEY = "sk-gui-FAKE-KEY-0987654321"
NEW_KEY = "sk-gui-NEW-KEY-1357924680"


class RecordingSecretStore:
    def __init__(self):
        self.values = {}

    def get(self, key_name):
        return self.values.get(key_name)

    def set(self, key_name, value):
        self.values[key_name] = value

    def delete(self, key_name):
        self.values.pop(key_name, None)


class UnavailableSecretStore(RecordingSecretStore):
    def get(self, key_name):
        raise SecretStoreUnavailable("no backend")

    def set(self, key_name, value):
        raise SecretStoreUnavailable("no backend")

    def delete(self, key_name):
        raise SecretStoreUnavailable("no backend")


class GuiSmokeTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.settings_path = self.root / "settings.json"
        write_project(self.root, "good", mode="conference", stage="idea")
        bad = self.root / "papers" / "bad"
        bad.mkdir(parents=True)
        (bad / "ccfa.yaml").write_text(": [unclosed\n", encoding="utf-8")
        self.secrets = RecordingSecretStore()
        self.window = self._window()

    def _window(self, secret_store=None):
        window = MainWindow(
            repo_root=self.root,
            secret_store=secret_store or self.secrets,
            settings_path=self.settings_path,
        )
        window.resize(1000, 700)
        window.show()
        APP.processEvents()
        return window

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def _select(self, slug):
        for row in range(self.window.project_list.count()):
            item = self.window.project_list.item(row)
            ref = item.data(Qt.ItemDataRole.UserRole)
            if ref.slug == slug:
                self.window.project_list.setCurrentRow(row)
                APP.processEvents()
                return item
        self.fail(f"project {slug} not found in list")

    def _screenshot(self, name="workbench.png"):
        image = self.window.grab().toImage()
        path = self.root / name
        self.assertTrue(image.save(str(path), "PNG"))
        return image, path

    def test_offscreen_render_is_non_blank_and_controls_are_visible(self):
        image, path = self._screenshot()

        self.assertGreater(image.width(), 600)
        self.assertGreater(image.height(), 400)
        ratio = image_non_background_ratio(image)
        self.assertGreater(
            ratio,
            0.02,
            f"non-background ratio too low: {ratio}",
        )
        print(f"SCREENSHOT_RATIO={ratio:.4f}")
        for widget in (
            self.window.project_list,
            self.window.stage_label,
            self.window.gate_label,
            self.window.deadline_label,
            self.window.results_table,
            self.window.refresh_button,
            self.window.validate_button,
            self.window.milestones_button,
            self.window.settings_button,
            self.window.checkpoints_button,
        ):
            with self.subTest(widget=type(widget).__name__):
                self.assertTrue(widget.isVisible())
                self.assertGreater(widget.width(), 0)
                self.assertGreater(widget.height(), 0)
        size = path.stat().st_size
        self.assertGreater(size, 0)
        print(f"SCREENSHOT_PATH={path}")
        print(f"SCREENSHOT_BYTES={size}")

    def test_bad_project_is_red_and_shows_error(self):
        item = self._select("bad")

        self.assertIn("bad", item.text())
        self.assertIn("解析失败", item.text())
        self.assertEqual(item.foreground().color(), QColor("red"))
        self.assertIn("bad", self.window.stage_label.text())

    def test_selecting_good_project_updates_stage_panel(self):
        self._select("good")

        self.assertIn("idea", self.window.stage_label.text())
        self.assertIn("scope_defined", self.window.gate_label.text())
        self.assertIn("无", self.window.deadline_label.text())

    def test_run_validate_populates_table(self):
        self._select("good")

        self.window.validate_button.click()
        APP.processEvents()

        self.assertGreater(self.window.results_table.rowCount(), 0)

    def test_run_milestones_populates_table(self):
        self._select("good")

        self.window.milestones_button.click()
        APP.processEvents()

        self.assertGreater(self.window.results_table.rowCount(), 0)

    def test_checkpoints_button_shows_the_human_queue(self):
        self._select("good")
        payload = {
            "human_review": {
                "status": "pending-human-review",
                "checkpoints": [
                    {
                        "id": "proof",
                        "type": "approve",
                        "question": "主证明逐行成立吗？",
                        "answer_with": "写 reviewer 与复核证据路径",
                        "ledger": "data/proof-audit.yaml",
                    }
                ],
            }
        }

        with mock.patch(
            "ccfa_gui.window.load_checkpoints",
            return_value=CheckResult(
                name="checkpoints",
                ok=False,
                problems=(),
                report=payload,
            ),
        ):
            self.window.checkpoints_button.click()
            APP.processEvents()

        self.assertEqual(self.window.checkpoint_card_count(), 1)
        self.assertEqual(self.window.detail_stack.currentIndex(), 1)
        card = self.window._checkpoint_cards[0]
        question = card.findChild(QLabel, "checkpointQuestion")
        self.assertIn("主证明逐行成立吗？", question.text())
        meta = card.findChild(QLabel, "checkpointMeta")
        self.assertIn("data/proof-audit.yaml", meta.text())
        self.assertIn("写 reviewer 与复核证据路径", meta.text())
        self.assertTrue(self.window.checkpoint_banner.isVisible())
        self.assertIn("待人工复核", self.window.checkpoint_banner.text())

        self.window.validate_button.click()
        APP.processEvents()
        self.assertEqual(self.window.detail_stack.currentIndex(), 0)
        self.assertFalse(self.window.checkpoint_banner.isVisible())

    def test_open_ledger_refuses_paths_outside_the_project(self):
        self._select("good")
        fake = mock.Mock()

        with mock.patch("ccfa_gui.window.QDesktopServices", fake):
            self.window._open_ledger("../../evil.yaml")
            fake.openUrl.assert_not_called()

            self.window._open_ledger("data/proof-audit.yaml")
            fake.openUrl.assert_called_once()

    def test_empty_project_list_shows_the_placeholder(self):
        empty_root = Path(self._temporary.name) / "empty"
        (empty_root / "papers").mkdir(parents=True)

        window = MainWindow(
            repo_root=empty_root,
            secret_store=self.secrets,
            settings_path=empty_root / "settings.json",
        )
        window.show()
        APP.processEvents()
        self.addCleanup(window.deleteLater)

        self.assertEqual(window.project_list.count(), 0)
        self.assertEqual(window.detail_stack.currentIndex(), 2)
        self.assertIn("还没有论文项目", window.placeholder_title.text())
        self.assertIn("new-paper.ps1", window.placeholder_hint.text())
        self.assertFalse(window.placeholder_icon.pixmap().isNull())
        window.close()

    def test_run_validate_on_bad_project_shows_error_row(self):
        self._select("bad")

        self.window.validate_button.click()
        APP.processEvents()

        self.assertGreater(self.window.results_table.rowCount(), 0)
        self.assertTrue(self.window.results_table.item(0, 2).text())

    def test_settings_save_puts_key_only_in_secret_store(self):
        dialog = SettingsDialog(self.settings_path, self.secrets)
        dialog.name_edit.setText("local")
        dialog.base_url_edit.setText("https://api.example.test/v1")
        dialog.model_edit.setText("gpt-test")
        dialog.timeout_spin.setValue(30)
        dialog.key_edit.setText(FAKE_KEY)

        self.assertTrue(dialog.save())

        self.assertEqual(self.secrets.values["local"], FAKE_KEY)
        raw = self.settings_path.read_bytes()
        self.assertNotIn(FAKE_KEY.encode("utf-8"), raw)
        payload = json.loads(raw.decode("utf-8"))
        self.assertEqual(payload["provider"]["name"], "local")
        self.assertEqual(dialog.key_status_label.text(), "已配置")
        dialog.deleteLater()

    def test_settings_dialog_never_echoes_existing_key(self):
        save_settings(
            self.settings_path,
            Settings(
                provider=ProviderSettings(
                    name="local",
                    base_url="https://api.example.test/v1",
                    model="gpt-test",
                    key_name="local",
                    timeout_s=30.0,
                )
            ),
        )
        self.secrets.set("local", FAKE_KEY)

        dialog = SettingsDialog(self.settings_path, self.secrets)

        self.assertEqual(dialog.key_edit.text(), "")
        self.assertIn("已配置", dialog.key_status_label.text())
        for line_edit in dialog.findChildren(QLineEdit):
            self.assertNotIn(FAKE_KEY, line_edit.text())
        dialog.deleteLater()

    def test_settings_dialog_rejects_empty_name(self):
        dialog = SettingsDialog(self.settings_path, self.secrets)
        dialog.name_edit.setText("")

        self.assertFalse(dialog.save())

        self.assertTrue(dialog.error_label.text())
        self.assertFalse(self.settings_path.exists())
        dialog.deleteLater()

    def test_settings_dialog_unavailable_keyring_does_not_fall_back(self):
        dialog = SettingsDialog(self.settings_path, UnavailableSecretStore())
        dialog.name_edit.setText("local")
        dialog.base_url_edit.setText("https://api.example.test/v1")
        dialog.model_edit.setText("gpt-test")
        dialog.key_edit.setText(FAKE_KEY)

        self.assertFalse(dialog.save())

        self.assertTrue(dialog.error_label.text())
        self.assertFalse(self.settings_path.exists())
        dialog.deleteLater()

    def test_settings_dialog_rename_without_new_key_keeps_old_key_name(self):
        save_settings(
            self.settings_path,
            Settings(
                provider=ProviderSettings(
                    name="old",
                    base_url="https://api.example.test/v1",
                    model="gpt-test",
                    key_name="old",
                    timeout_s=30.0,
                )
            ),
        )
        self.secrets.set("old", FAKE_KEY)

        dialog = SettingsDialog(self.settings_path, self.secrets)
        self.assertIn("已配置", dialog.key_status_label.text())
        dialog.name_edit.setText("renamed")

        self.assertTrue(dialog.save())

        payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["provider"]["name"], "renamed")
        self.assertEqual(payload["provider"]["key_name"], "old")
        self.assertEqual(self.secrets.get("old"), FAKE_KEY)
        self.assertIsNone(self.secrets.get("renamed"))
        self.assertEqual(dialog.key_status_label.text(), "已配置")
        dialog.deleteLater()

    def test_settings_dialog_rename_with_new_key_uses_new_name(self):
        save_settings(
            self.settings_path,
            Settings(
                provider=ProviderSettings(
                    name="old",
                    base_url="https://api.example.test/v1",
                    model="gpt-test",
                    key_name="old",
                    timeout_s=30.0,
                )
            ),
        )
        self.secrets.set("old", FAKE_KEY)

        dialog = SettingsDialog(self.settings_path, self.secrets)
        dialog.name_edit.setText("renamed")
        dialog.key_edit.setText(NEW_KEY)

        self.assertTrue(dialog.save())

        payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["provider"]["key_name"], "renamed")
        self.assertEqual(self.secrets.get("renamed"), NEW_KEY)
        self.assertNotIn(NEW_KEY.encode("utf-8"), self.settings_path.read_bytes())
        self.assertEqual(dialog.key_status_label.text(), "已配置")
        dialog.deleteLater()

    def test_credential_status_reports_available_and_unavailable(self):
        self.assertIn("可用", self.window.credential_label.text())

        unavailable = self._window(UnavailableSecretStore())
        try:
            self.assertIn("不可用", unavailable.credential_label.text())
        finally:
            unavailable.close()
            unavailable.deleteLater()
            APP.processEvents()

    def test_refresh_reloads_projects(self):
        before = self.window.project_list.count()
        write_project(self.root, "gamma")

        self.window.refresh_button.click()
        APP.processEvents()

        self.assertEqual(self.window.project_list.count(), before + 1)


if __name__ == "__main__":
    unittest.main()
