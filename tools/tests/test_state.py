import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import yaml

from ccfa.stages import gate_for
from ccfa.state import main, rollback, set_stage


def _write_state(
    root: Path,
    *,
    current: str = "idea",
    history: str = "  history: []\n",
    mode: str = "conference",
) -> Path:
    path = root / "ccfa.yaml"
    path.write_text(
        "version: \"0.4.0\"\n"
        "target_venue:\n"
        f"  mode: \"{mode}\"\n"
        "stage:\n"
        f"  current: \"{current}\"\n"
        "  gate: \"scope_defined\"\n"
        "  updated_at: \"2026-10-03\"\n"
        f"{history}"
        "artifacts:\n"
        "  manuscript: \"manuscript/main.tex\"\n",
        encoding="utf-8",
    )
    return path


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _run_main(*args):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(["state.py", *args])
    return code, stdout.getvalue(), stderr.getvalue()


class TestSetStage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = _write_state(self.root)

    def test_set_stage_requires_confirm_and_preserves_bytes(self):
        before = self.path.read_bytes()

        with self.assertRaisesRegex(ValueError, "--confirm"):
            set_stage(
                self.root,
                to="grounded",
                reason="scope is fixed",
                confirm=False,
            )

        self.assertEqual(self.path.read_bytes(), before)

    def test_set_stage_rejects_whitespace_reason(self):
        before = self.path.read_bytes()

        with self.assertRaisesRegex(ValueError, "reason"):
            set_stage(
                self.root,
                to="grounded",
                reason="   ",
                confirm=True,
            )

        self.assertEqual(self.path.read_bytes(), before)

    def test_set_stage_rejects_unknown_stage(self):
        with self.assertRaisesRegex(ValueError, "does-not-exist"):
            set_stage(
                self.root,
                to="does-not-exist",
                reason="try a bad stage",
                confirm=True,
            )

    def test_set_stage_rejects_current_stage(self):
        with self.assertRaisesRegex(ValueError, "相同"):
            set_stage(
                self.root,
                to="idea",
                reason="no-op",
                confirm=True,
            )

    def test_set_stage_rejects_backward_stage_and_preserves_bytes(self):
        self.path.write_text(
            _write_state(self.root, current="writing").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        before = self.path.read_bytes()

        with self.assertRaisesRegex(ValueError, "之后"):
            set_stage(
                self.root,
                to="results-ready",
                reason="must not disguise a rollback",
                confirm=True,
            )

        self.assertEqual(self.path.read_bytes(), before)

    def test_set_stage_updates_gate_and_appends_history(self):
        result = set_stage(
            self.root,
            to="grounded",
            reason="three nearest neighbors are listed",
            confirm=True,
        )
        data = _load(self.path)
        stage = data["stage"]
        entry = stage["history"][0]

        self.assertEqual(
            list(data),
            ["version", "target_venue", "stage", "artifacts"],
        )
        self.assertEqual(stage["current"], "grounded")
        self.assertEqual(stage["gate"], gate_for("conference", "grounded").id)
        self.assertEqual(entry["from"], "idea")
        self.assertEqual(entry["to"], "grounded")
        self.assertEqual(entry["reason"], "three nearest neighbors are listed")
        self.assertEqual(entry["kind"], "advance")
        self.assertEqual(result["kind"], "advance")
        self.assertFalse((self.root / "ccfa.yaml.tmp").exists())

    def test_history_order_is_append_only(self):
        set_stage(
            self.root,
            to="grounded",
            reason="grounding complete",
            confirm=True,
        )
        set_stage(
            self.root,
            to="data-ready",
            reason="sources are recorded",
            confirm=True,
        )

        history = _load(self.path)["stage"]["history"]
        self.assertEqual([entry["to"] for entry in history], ["grounded", "data-ready"])
        self.assertEqual([entry["from"] for entry in history], ["idea", "grounded"])

    def test_legacy_file_without_history_is_backfilled(self):
        self.path.write_text(
            self.path.read_text(encoding="utf-8").replace("  history: []\n", ""),
            encoding="utf-8",
        )

        set_stage(
            self.root,
            to="grounded",
            reason="legacy file",
            confirm=True,
        )

        self.assertEqual(len(_load(self.path)["stage"]["history"]), 1)

    def test_bad_history_is_rejected_without_rewrite(self):
        self.path.write_text(
            self.path.read_text(encoding="utf-8").replace(
                "  history: []\n",
                "  history:\n"
                "    - from: idea\n"
                "      to: grounded\n"
                "      at: \"2026-10-03\"\n"
                "      kind: advance\n",
            ),
            encoding="utf-8",
        )
        before = self.path.read_bytes()

        with self.assertRaisesRegex(ValueError, "history"):
            set_stage(
                self.root,
                to="data-ready",
                reason="bad history must block writes",
                confirm=True,
            )

        self.assertEqual(self.path.read_bytes(), before)


class TestRollback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = _write_state(self.root, current="writing")

    def test_rollback_requires_confirm_and_preserves_bytes(self):
        before = self.path.read_bytes()

        with self.assertRaisesRegex(ValueError, "--confirm"):
            rollback(
                self.root,
                to="results-ready",
                reason="claims need another check",
                confirm=False,
            )

        self.assertEqual(self.path.read_bytes(), before)

    def test_rollback_rejects_forward_or_same_stage(self):
        for target in ("writing", "submission-check"):
            with self.subTest(target=target):
                with self.assertRaisesRegex(ValueError, "之前"):
                    rollback(
                        self.root,
                        to=target,
                        reason="invalid direction",
                        confirm=True,
                    )

    def test_rollback_appends_void_artifacts(self):
        result = rollback(
            self.root,
            to="results-ready",
            reason="claim table was edited after the check",
            confirm=True,
            void_artifacts=["figures/main-results.pdf"],
        )
        entry = _load(self.path)["stage"]["history"][0]

        self.assertEqual(entry["kind"], "rollback")
        self.assertEqual(entry["void_artifacts"], ["figures/main-results.pdf"])
        self.assertEqual(result["kind"], "rollback")


class TestStateMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = _write_state(self.root)

    def test_main_set_stage_exits_zero_and_emits_json(self):
        code, stdout, stderr = _run_main(
            "--paper-root",
            str(self.root),
            "set-stage",
            "grounded",
            "--reason",
            "nearest neighbors recorded",
            "--confirm",
        )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["kind"], "advance")
        self.assertEqual(stderr, "")

    def test_main_missing_confirm_exits_two(self):
        code, stdout, stderr = _run_main(
            "--paper-root",
            str(self.root),
            "set-stage",
            "grounded",
            "--reason",
            "nearest neighbors recorded",
        )

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("--confirm", stderr)

    def test_main_backward_set_stage_exits_two_without_rewrite(self):
        self.path.write_text(
            _write_state(self.root, current="writing").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        before = self.path.read_bytes()

        code, stdout, stderr = _run_main(
            "--paper-root",
            str(self.root),
            "set-stage",
            "results-ready",
            "--reason",
            "must not disguise a rollback",
            "--confirm",
        )

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("之后", stderr)
        self.assertEqual(self.path.read_bytes(), before)

    def test_main_rollback_exits_zero(self):
        self.path.write_text(
            _write_state(self.root, current="writing").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        code, stdout, stderr = _run_main(
            "--paper-root",
            str(self.root),
            "rollback",
            "results-ready",
            "--reason",
            "claims need another check",
            "--void-artifacts",
            "figures/main-results.pdf",
            "--confirm",
        )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["kind"], "rollback")

    def test_main_bad_history_exits_two_without_rewrite(self):
        self.path.write_text(
            self.path.read_text(encoding="utf-8").replace(
                "  history: []\n",
                "  history: [{kind: rewind}]\n",
            ),
            encoding="utf-8",
        )
        before = self.path.read_bytes()

        code, stdout, stderr = _run_main(
            "--paper-root",
            str(self.root),
            "set-stage",
            "grounded",
            "--reason",
            "must not rewrite",
            "--confirm",
        )

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("history", stderr)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
