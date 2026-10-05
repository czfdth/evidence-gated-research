import json
import os
import subprocess
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest import mock

import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit

from ccfa_core.checks import CheckResult
from ccfa_core.collaboration import CollaborationState
from ccfa_core.secrets import SecretStoreUnavailable
from ccfa_core.settings import ProviderSettings, Settings, save_settings
from ccfa_core.workflow import WorkflowClient
from ccfa_gui.settings_dialog import SettingsDialog
from ccfa_gui.stage_dialog import StageTransitionDialog
from ccfa_gui import theme
from ccfa_gui.main import main as gui_main
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

    def _window(self, secret_store=None, *, probes=False):
        # Collaboration probes shell out to the workflow once per project, so
        # only the tests that assert on them pay for them.
        window = MainWindow(
            repo_root=self.root,
            secret_store=secret_store or self.secrets,
            settings_path=self.settings_path,
            animations=False,
            collaboration_probes=probes,
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

    def _item(self, slug):
        for row in range(self.window.project_list.count()):
            item = self.window.project_list.item(row)
            ref = item.data(Qt.ItemDataRole.UserRole)
            if ref is not None and ref.slug == slug:
                return item
        self.fail(f"project {slug} not found in list")

    def _git_init(self, project_dir):
        """Make one paper directory a committed worktree with a remote."""

        for args in (
            ["git", "init"],
            ["git", "config", "user.email", "test@example.com"],
            ["git", "config", "user.name", "Test"],
            ["git", "add", "ccfa.yaml"],
            ["git", "commit", "-m", "init"],
            ["git", "remote", "add", "origin", "https://example.test/p.git"],
        ):
            subprocess.run(
                args,
                cwd=project_dir,
                check=True,
                capture_output=True,
            )
        (Path(project_dir) / ".github" / "workflows").mkdir(parents=True)

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
            self.window.readiness_button,
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

    def test_gate_criterion_is_shown_for_a_readable_project(self):
        self._select("good")

        label = self.window.gate_criterion_label
        self.assertTrue(label.isVisible())
        self.assertTrue(label.text().startswith("门禁判据："))
        self.assertTrue(label.toolTip())

        self._select("bad")
        self.assertFalse(label.isVisible())

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

    def test_readiness_button_renders_dimensions_verdicts_and_blocking(self):
        self._select("good")
        payload = {
            "ready": False,
            "profile": "standard",
            "assurance": "draft",
            "dimensions": {
                "schema-valid": "pass",
                "gate-verified": "problem",
            },
            "verdicts": {
                "novelty": "blocked",
                "research-ledgers": "fail",
            },
            "blocking": ["missing required standard ledger: novelty"],
        }
        problems = ("missing required standard ledger: novelty",)

        with mock.patch(
            "ccfa_gui.window.load_readiness",
            return_value=CheckResult(
                name="readiness",
                ok=False,
                problems=problems,
                report=payload,
            ),
        ):
            self.window.readiness_button.click()
            APP.processEvents()

        messages = [
            self.window.results_table.item(row, 2).text()
            for row in range(self.window.results_table.rowCount())
        ]
        self.assertIn("schema-valid", messages)
        self.assertIn("novelty", messages)
        self.assertIn("research-ledgers", messages)
        self.assertIn("missing required standard ledger: novelty", messages)
        self.assertIn("ready=false", self.window.results_summary.text())
        self.assertTrue(self.window.checkpoint_banner.isVisible())
        self.assertIn("ready=false", self.window.checkpoint_banner.text())
        self.assertIn("blocked=1", self.window.checkpoint_banner.text())

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
            animations=False,
            collaboration_probes=False,
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

    def test_chat_column_collapses_in_a_narrow_window(self):
        self.window.resize(1300, 800)
        APP.processEvents()
        self.assertTrue(self.window.chat_card.isVisible())

        self.window.resize(900, 700)
        APP.processEvents()
        self.assertFalse(self.window.chat_card.isVisible())
        self.assertFalse(self.window.chat_toggle.isChecked())

        self.window.chat_toggle.click()
        APP.processEvents()
        self.assertTrue(self.window.chat_card.isVisible())

        self.window.resize(1300, 800)
        APP.processEvents()
        self.assertTrue(self.window.chat_card.isVisible())
        self.assertTrue(self.window.chat_toggle.isChecked())

    def test_dark_mode_paints_the_window_with_the_dark_palette(self):
        with mock.patch.dict(os.environ, {"CCFA_THEME": "dark"}):
            window = self._window()
        try:
            self.assertEqual(window._mode, "dark")
            self.assertIn(theme.DARK["canvas"], window.styleSheet())
            self.assertIn(theme.DARK["panel"], window.styleSheet())
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_self_check_reports_the_workflow_it_found(self):
        stream = StringIO()

        with redirect_stdout(stream):
            code = gui_main(["--self-check", "--repo-root", str(self.root)])

        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["repo_root"], str(self.root))
        self.assertTrue(payload["workflow_root"])
        self.assertTrue(payload["workflow_python"])
        self.assertTrue(
            (Path(payload["workflow_root"]) / "tools" / "ccfa").is_dir()
        )
        # The verdict follows the dependency self-test: a checkout whose
        # interpreter cannot import the gates' deps must not report ready.
        expected_ok, _detail = WorkflowClient(
            payload["workflow_root"],
            python=payload["workflow_python"],
        ).probe()
        self.assertEqual(bool(payload["probe_ok"]), expected_ok)
        self.assertEqual(code, 0 if expected_ok else 1)

    def test_chat_column_slides_when_animations_are_enabled(self):
        window = MainWindow(
            repo_root=self.root,
            secret_store=self.secrets,
            settings_path=self.settings_path,
            animations=True,
            collaboration_probes=False,
        )
        self.addCleanup(window.deleteLater)
        window.resize(1300, 800)
        window.show()
        APP.processEvents()
        self.assertTrue(window.chat_card.isVisible())

        window.resize(900, 700)
        APP.processEvents()

        # Not an instant hide: the pane is mid-slide.
        self.assertTrue(window.chat_card.isVisible())
        self.assertIsNotNone(window._chat_animation)
        QTest.qWait(320)
        self.assertFalse(window.chat_card.isVisible())
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

    def test_stage_dialog_lists_targets_and_requires_a_reason(self):
        dialog = StageTransitionDialog(
            current="idea",
            targets={"advance": ("grounded", "data-ready"), "rollback": ()},
        )
        self.addCleanup(dialog.deleteLater)

        self.assertEqual(dialog.kind(), "advance")
        self.assertEqual(
            [
                dialog.target_combo.itemText(index)
                for index in range(dialog.target_combo.count())
            ],
            ["grounded", "data-ready"],
        )
        # The workflow refuses an empty reason, so the dialog never offers it.
        self.assertFalse(dialog.ok_button.isEnabled())
        dialog.reason_edit.setText("scope frozen")
        self.assertTrue(dialog.ok_button.isEnabled())
        self.assertEqual(dialog.reason(), "scope frozen")
        self.assertEqual(dialog.void_artifacts(), ())

    def test_stage_dialog_switches_to_rollback_and_collects_voided_artifacts(self):
        dialog = StageTransitionDialog(
            current="writing",
            targets={
                "advance": ("internal-review",),
                "rollback": ("idea", "grounded"),
            },
        )
        self.addCleanup(dialog.deleteLater)

        dialog.rollback_button.click()

        self.assertEqual(dialog.kind(), "rollback")
        self.assertEqual(dialog.target(), "idea")
        dialog.reason_edit.setText("the effect did not replicate")
        dialog.void_edit.setPlainText("results/table.csv\n\nmanuscript/fig1.pdf ")
        self.assertTrue(dialog.ok_button.isEnabled())
        self.assertEqual(
            dialog.void_artifacts(),
            ("results/table.csv", "manuscript/fig1.pdf"),
        )

    def test_stage_transition_writes_through_and_refreshes_the_header(self):
        self._select("good")

        self.window._apply_stage_transition("advance", "grounded", "scope frozen")
        APP.processEvents()

        self.assertIn("grounded", self.window.stage_label.text())
        self.assertIn("novelty_grounded", self.window.gate_label.text())
        self.assertIn("阶段已推进", self.window.checkpoint_banner.text())
        codes = [
            self.window.results_table.item(row, 1).text()
            for row in range(self.window.results_table.rowCount())
        ]
        self.assertIn("OK", codes)
        state = yaml.safe_load(
            (self.root / "papers" / "good" / "ccfa.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(state["stage"]["current"], "grounded")

    def test_stage_transition_reports_a_workflow_refusal(self):
        self._select("good")

        # "idea" is already the first stage: rolling back has nowhere to go.
        self.window._apply_stage_transition("rollback", "idea", "go back")
        APP.processEvents()

        codes = [
            self.window.results_table.item(row, 1).text()
            for row in range(self.window.results_table.rowCount())
        ]
        self.assertIn("错误", codes)
        state = yaml.safe_load(
            (self.root / "papers" / "good" / "ccfa.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(state["stage"]["current"], "idea")

    def test_deadline_badge_shows_the_countdown_and_keeps_the_date(self):
        write_project(self.root, "deadline", deadline="2030-01-01")
        self.window.refresh_button.click()
        APP.processEvents()

        self._select("deadline")

        self.assertTrue(
            self.window.deadline_label.text().startswith("截止 剩 "),
            self.window.deadline_label.text(),
        )
        self.assertIn("2030-01-01", self.window.deadline_label.toolTip())

    def test_export_button_writes_and_opens_the_readiness_report(self):
        self._select("good")
        fake = mock.Mock()

        with mock.patch("ccfa_gui.window.QDesktopServices", fake):
            self.window.export_button.click()
            APP.processEvents()

        expected = (
            self.root
            / "papers"
            / "good"
            / "reviews"
            / f"readiness-{date.today().isoformat()}.md"
        )
        self.assertTrue(expected.is_file(), expected)
        self.assertIn(
            "# Readiness Report",
            expected.read_text(encoding="utf-8"),
        )
        fake.openUrl.assert_called_once()
        messages = [
            self.window.results_table.item(row, 2).text()
            for row in range(self.window.results_table.rowCount())
        ]
        self.assertTrue(any("已导出" in text for text in messages), messages)

    def test_collaboration_state_marks_the_project_row(self):
        state = CollaborationState(
            present=True,
            dirty=True,
            commit="abc1234",
            remotes=(),
            workflows_present=False,
            ready=False,
            blocking=("paper git remote is missing",),
        )

        self.window._apply_collaboration(
            self.window._probe_generation,
            "good",
            state,
        )

        item = self._item("good")
        self.assertTrue(item.text().startswith("◆"), item.text())
        # The row stays one short token wide; the tooltip carries the detail.
        self.assertEqual(item.text(), "◆ good")
        tooltip = item.toolTip()
        self.assertIn("未提交改动：有", tooltip)
        self.assertIn("remote：无", tooltip)
        self.assertIn("CI workflows：无", tooltip)
        self.assertIn("paper git remote is missing", tooltip)
        self.assertIn("1 个有协作风险", self.window.summary_label.text())

    def test_clean_collaboration_state_leaves_the_row_plain(self):
        state = CollaborationState(
            present=True,
            dirty=False,
            commit="abc1234",
            remotes=("origin",),
            workflows_present=True,
            ready=True,
        )

        self.window._apply_collaboration(
            self.window._probe_generation,
            "good",
            state,
        )

        item = self._item("good")
        self.assertTrue(item.text().startswith("●"), item.text())
        self.assertEqual(item.text(), "● good")
        self.assertIn("未提交改动：无", item.toolTip())
        self.assertIn("remote：origin", item.toolTip())
        self.assertNotIn("协作风险", self.window.summary_label.text())

    def test_a_stale_collaboration_result_is_dropped(self):
        state = CollaborationState.unavailable("旧扫描的结果")

        self.window._apply_collaboration(
            self.window._probe_generation - 1,
            "good",
            state,
        )

        self.assertNotIn("good", self.window._git_states)

    def test_collaboration_probe_fills_the_row_from_the_workflow(self):
        self._git_init(self.root / "papers" / "good")
        window = self._window(probes=True)
        try:
            deadline = time.time() + 60
            while "good" not in window._git_states and time.time() < deadline:
                APP.processEvents()
                time.sleep(0.05)
            APP.processEvents()

            self.assertIn("good", window._git_states)
            state = window._git_states["good"]
            self.assertTrue(state.present)
            self.assertEqual(state.remotes, ("origin",))
            self.assertTrue(state.workflows_present)
            self.assertFalse(state.dirty)
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()

    def test_action_buttons_never_elide_at_the_collapse_width(self):
        # 1000px is the narrowest window that still shows the conversation
        # column, so the detail pane is at its tightest. Every action must
        # still render its full label: the row wraps instead of squeezing.
        window = self._window()
        try:
            window.resize(1000, 700)
            window.layout().activate()
            APP.processEvents()

            buttons = [
                window.validate_button,
                window.milestones_button,
                window.readiness_button,
                window.stages_button,
                window.checkpoints_button,
            ]
            for button in buttons:
                self.assertGreaterEqual(
                    button.width(),
                    button.sizeHint().width(),
                    f"{button.text()} 被压缩到 {button.width()}px",
                )
            # Two rows are expected at this width; one row is the wide case.
            rows = {button.y() for button in buttons}
            self.assertGreater(len(rows), 1)
        finally:
            window.close()
            window.deleteLater()
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()
