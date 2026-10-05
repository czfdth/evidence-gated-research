import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from ccfa_core.projects import find_projects
from ccfa_gui.settings_dialog import SettingsDialog
from ccfa_gui.window import MainWindow, image_non_background_ratio
from . import create_project

APP = QApplication.instance() or QApplication([])
FAKE_KEY = "sk-e2e-FAKE-KEY-1234567890"


class RecordingSecretStore:
    def __init__(self):
        self.values = {}

    def get(self, key_name):
        return self.values.get(key_name)

    def set(self, key_name, value):
        self.values[key_name] = value

    def delete(self, key_name):
        self.values.pop(key_name, None)


class WorkbenchEndToEnd(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.settings_path = self.root / "settings.json"
        self.codex_home = self.root / "codex-home"
        template = (
            self.codex_home
            / "skills"
            / "ccf-latex-templates"
            / "NeurIPS"
        )
        template.mkdir(parents=True)
        (template / "neurips_2026.tex").write_text(
            "\\documentclass{article}\n"
            "\\begin{document}Workbench E2E\\end{document}\n",
            encoding="utf-8",
        )
        (template / "neurips_2026.sty").write_text(
            "% minimal deterministic E2E fixture\n",
            encoding="utf-8",
        )
        environment = mock.patch.dict(
            os.environ,
            {"CODEX_HOME": str(self.codex_home)},
        )
        environment.start()
        self.addCleanup(environment.stop)

        self.project_dir = create_project(
            papers_root=self.root / "papers",
            slug="neurips-workbench",
            venue="NeurIPS",
            year="2027",
            mode="conference",
            title="Workbench E2E",
        )
        bad = self.root / "papers" / "bad"
        bad.mkdir(parents=True)
        (bad / "ccfa.yaml").write_text(": [unclosed\n", encoding="utf-8")

        self.secrets = RecordingSecretStore()
        self.window = MainWindow(
            repo_root=self.root,
            secret_store=self.secrets,
            settings_path=self.settings_path,
        )
        self.window.resize(1000, 700)
        self.window.show()
        APP.processEvents()

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
        self.fail(f"project {slug} not found in window list")

    def test_real_neurips_derivation_is_visible_to_find_projects(self):
        refs = {ref.slug: ref for ref in find_projects(self.root)}

        self.assertIn("neurips-workbench", refs)
        self.assertIsNone(refs["neurips-workbench"].error)
        self.assertTrue(
            os.path.samefile(
                refs["neurips-workbench"].dir,
                self.project_dir,
            )
        )
        self.assertTrue((self.project_dir / "ccfa.yaml").is_file())
        self.assertTrue(
            (self.project_dir / "manuscript" / "neurips_2026.tex").is_file()
        )
        self.assertTrue(
            (self.project_dir / "manuscript" / "neurips_2026.sty").is_file()
        )
        self.assertTrue(refs["bad"].error)

    def test_window_lists_derived_project_and_stage_panel(self):
        self._select("neurips-workbench")

        self.assertIn("idea", self.window.stage_label.text())
        self.assertIn("scope_defined", self.window.gate_label.text())
        self.assertIn("无", self.window.deadline_label.text())

    def test_window_renders_real_offscreen_image(self):
        image = self.window.grab().toImage()
        path = self.root / "workbench-e2e.png"
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
        print(f"SCREENSHOT_RATIO={ratio:.4f}")
        print(f"SCREENSHOT_PATH={path}")
        print(f"SCREENSHOT_BYTES={size}")

    def test_real_validate_populates_results_table(self):
        self._select("neurips-workbench")

        self.window.validate_button.click()
        APP.processEvents()

        self.assertGreater(self.window.results_table.rowCount(), 0)
        self.assertEqual(self.window.results_table.item(0, 0).text(), "validate")

    def test_real_milestones_populates_results_table(self):
        self._select("neurips-workbench")

        self.window.milestones_button.click()
        APP.processEvents()

        self.assertGreater(self.window.results_table.rowCount(), 0)
        self.assertIn(
            "sequential",
            self.window.results_table.item(0, 2).text(),
        )

    def test_bad_project_is_visible_and_marked(self):
        item = self._select("bad")

        self.assertIn("解析失败", item.text())
        self.assertEqual(item.foreground().color(), QColor("red"))
        self.assertIn("bad", self.window.stage_label.text())

    def test_settings_dialog_saves_provider_without_key_plaintext(self):
        registry = self.root / "http-tools.yaml"
        registry.write_text("version: 1\ntools: []\n", encoding="utf-8")
        dialog = SettingsDialog(self.settings_path, self.secrets)
        dialog.name_edit.setText("local")
        dialog.base_url_edit.setText("https://api.example.test/v1")
        dialog.model_edit.setText("gpt-test")
        dialog.timeout_spin.setValue(30)
        dialog.key_edit.setText(FAKE_KEY)
        dialog.http_tools_path_edit.setText(registry.name)

        self.assertTrue(dialog.save())

        self.assertEqual(self.secrets.values["local"], FAKE_KEY)
        raw = self.settings_path.read_bytes()
        self.assertNotIn(FAKE_KEY.encode("utf-8"), raw)
        payload = json.loads(raw.decode("utf-8"))
        self.assertEqual(payload["provider"]["name"], "local")
        self.assertEqual(payload["provider"]["model"], "gpt-test")
        self.assertEqual(payload["http_tools_path"], registry.name)
        self.assertEqual(dialog.key_status_label.text(), "已配置")
        dialog.deleteLater()

    def test_settings_dialog_rejects_invalid_http_tool_registry(self):
        registry = self.root / "invalid-tools.yaml"
        registry.write_text("version: 1\ntools: nope\n", encoding="utf-8")
        dialog = SettingsDialog(self.settings_path, self.secrets)
        dialog.name_edit.setText("local")
        dialog.base_url_edit.setText("https://api.example.test/v1")
        dialog.model_edit.setText("gpt-test")
        dialog.key_edit.setText(FAKE_KEY)
        dialog.http_tools_path_edit.setText(registry.name)

        self.assertFalse(dialog.save())

        self.assertIn("registry-invalid", dialog.error_label.text())
        self.assertFalse(self.settings_path.exists())
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
