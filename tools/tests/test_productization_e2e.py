"""End-to-end regression for the productization workflow."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import yaml

from ccfa.figure_manifest import check_manifest, load_manifest
from ccfa.milestones import main as milestones_main
from ccfa.revision_ledger import main as revision_ledger_main
from ccfa.stages import gate_for
from ccfa.state import main as state_main
from ccfa.validate import main as validate_main
from newpaper.create import create_project

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
LEDGER_HEADER = "| Concern ID | 来源 | 类型 | 需要的新证据 | 处置 | 承诺风险 | 状态 |"
LEDGER_SEPARATOR = "| --- | --- | --- | --- | --- | --- | --- |"


class ProductizationEndToEnd(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.papers = Path(self._temporary.name) / "papers"

    def _derive(self, slug: str = "productization-smoke") -> Path:
        return create_project(
            papers_root=self.papers,
            slug=slug,
            venue="NeurIPS",
            year="2027",
            mode="conference",
            title="Productization smoke",
            deadline="2027-05-01",
        )

    def _run(self, command, argv):
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = command(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def _load_state(self, root: Path) -> dict:
        return yaml.safe_load(
            (root / "ccfa.yaml").read_text(encoding="utf-8")
        )

    def _set_stage(self, root: Path, to: str = "grounded"):
        return self._run(
            state_main,
            [
                "state.py",
                "--paper-root",
                str(root),
                "set-stage",
                to,
                "--reason",
                "state migration is ready",
                "--confirm",
            ],
        )

    def _rollback(self, root: Path):
        return self._run(
            state_main,
            [
                "state.py",
                "--paper-root",
                str(root),
                "rollback",
                "idea",
                "--reason",
                "grounding evidence is stale",
                "--void-artifacts",
                "figures/grounding.pdf",
                "--confirm",
            ],
        )

    def _manifest_item(self, root: Path) -> dict:
        run_id = "20261003T120000-01"
        figure = root / "figures" / "main-results.png"
        figure.write_bytes(PNG)
        generator = root / "ccfa-workfiles" / "figures" / "plot.py"
        generator.parent.mkdir(parents=True, exist_ok=True)
        generator.write_text("print('plot')\n", encoding="utf-8")
        source = root / "experiments" / "results" / "main.csv"
        source.write_text("x,y\n1,2\n", encoding="utf-8")
        log = root / "experiments" / "log" / f"{run_id}.json"
        log.write_text(
            json.dumps({"run_id": run_id, "started_at": "2026-10-03T12:00:00Z"}),
            encoding="utf-8",
        )
        return {
            "name": "main-results",
            "file": "figures/main-results.png",
            "bytes_format": "png",
            "generator": "ccfa-workfiles/figures/plot.py",
            "generator_hash": "sha256:"
            + hashlib.sha256(generator.read_bytes()).hexdigest(),
            "source_run_ids": [run_id],
            "source_data": "experiments/results/main.csv",
            "referenced_in": ["manuscript/main.tex:1"],
        }

    def _write_manifest(self, root: Path, items: list[dict]) -> Path:
        path = root / "figures" / "manifest.yaml"
        path.write_text(
            yaml.safe_dump(items, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return path

    def _write_ledger(self, root: Path, row: str) -> Path:
        path = root / "reviews" / "revision-ledger.md"
        path.write_text(
            "# 审稿意见矩阵\n" + LEDGER_HEADER + "\n" + LEDGER_SEPARATOR + "\n" + row + "\n",
            encoding="utf-8",
        )
        return path

    def test_full_productization_flow(self):
        root = self._derive()
        state = self._load_state(root)

        self.assertEqual(state["target_venue"]["name"], "NeurIPS")
        self.assertEqual(state["target_venue"]["mode"], "conference")
        self.assertEqual(state["target_venue"]["deadline"], "2027-05-01")
        self.assertEqual(state["stage"]["current"], "idea")
        self.assertTrue((root / "manuscript").is_dir())
        self.assertTrue(any((root / "manuscript").glob("*.tex")))
        self.assertTrue((root / "reviews" / "revision-ledger.md").is_file())

        code, stdout, stderr = self._set_stage(root)
        self.assertEqual(code, 0, stderr)
        state = self._load_state(root)
        self.assertEqual(len(state["stage"]["history"]), 1)
        self.assertEqual(state["stage"]["gate"], gate_for("conference", "grounded").id)
        self.assertEqual(json.loads(stdout)["gate"], state["stage"]["gate"])

        code, stdout, stderr = self._run(
            validate_main,
            ["validate.py", str(root / "ccfa.yaml")],
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["problem_count"], 0)

        code, stdout, stderr = self._rollback(root)
        self.assertEqual(code, 0, stderr)
        state = self._load_state(root)
        self.assertEqual(len(state["stage"]["history"]), 2)
        self.assertEqual(state["stage"]["current"], "idea")
        self.assertEqual(
            state["stage"]["history"][-1]["void_artifacts"],
            ["figures/grounding.pdf"],
        )
        self.assertEqual(json.loads(stdout)["kind"], "rollback")

        code, stdout, stderr = self._run(
            milestones_main,
            [
                "milestones.py",
                "due",
                "--paper-root",
                str(root),
                "--today",
                "2027-04-01",
            ],
        )
        self.assertEqual(code, 1, stderr)
        due = json.loads(stdout)["due"][0]
        self.assertEqual(due["checkpoint"], "T-30")
        self.assertEqual(due["stage"], "results-ready")
        self.assertEqual(due["gate"], "claims_supported")

        manifest_item = self._manifest_item(root)
        manifest = self._write_manifest(root, [manifest_item])
        problems, advisories = check_manifest(load_manifest(manifest), root)
        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

        del manifest_item["generator"]
        self._write_manifest(root, [manifest_item])
        problems, _ = check_manifest(load_manifest(manifest), root)
        self.assertIn(
            "figure-provenance-missing",
            {problem.code for problem in problems},
        )

        ledger = self._write_ledger(
            root,
            "| C1 | reviewer | 证据不足 | run-001 | 补充实验 | 是 | 待处理 |",
        )
        code, stdout, stderr = self._run(
            revision_ledger_main,
            ["revision_ledger.py", "--ledger", str(ledger)],
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["problem_count"], 0)

        self._write_ledger(
            root,
            "| C1 | reviewer | 证据不足 | 无 | 补充实验 | 是 | 待处理 |",
        )
        code, stdout, stderr = self._run(
            revision_ledger_main,
            ["revision_ledger.py", "--ledger", str(ledger)],
        )
        self.assertEqual(code, 1)
        self.assertIn(
            "ledger-risk-without-evidence",
            {problem["code"] for problem in json.loads(stdout)["problems"]},
        )

    def test_set_stage_appends_one_history_entry_and_aligns_gate(self):
        root = self._derive()
        code, stdout, stderr = self._set_stage(root)

        self.assertEqual(code, 0, stderr)
        result = json.loads(stdout)
        state = self._load_state(root)
        history = state["stage"]["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["from"], "idea")
        self.assertEqual(history[0]["to"], "grounded")
        self.assertEqual(history[0]["kind"], "advance")
        self.assertEqual(state["stage"]["gate"], gate_for("conference", "grounded").id)
        self.assertEqual(result["gate"], state["stage"]["gate"])

    def test_validate_accepts_scaffolded_state(self):
        root = self._derive()
        code, stdout, stderr = self._run(
            validate_main,
            ["validate.py", str(root / "ccfa.yaml")],
        )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["problem_count"], 0)

    def test_rollback_records_void_artifacts(self):
        root = self._derive()
        code, _, stderr = self._set_stage(root)
        self.assertEqual(code, 0, stderr)

        code, stdout, stderr = self._rollback(root)

        self.assertEqual(code, 0, stderr)
        result = json.loads(stdout)
        state = self._load_state(root)
        history = state["stage"]["history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(state["stage"]["current"], "idea")
        self.assertEqual(history[-1]["kind"], "rollback")
        self.assertEqual(history[-1]["from"], "grounded")
        self.assertEqual(history[-1]["to"], "idea")
        self.assertEqual(
            history[-1]["void_artifacts"],
            ["figures/grounding.pdf"],
        )
        self.assertEqual(result["void_artifacts"], ["figures/grounding.pdf"])

    def test_countdown_milestone_hits_one_full_node(self):
        root = self._derive()
        code, stdout, stderr = self._run(
            milestones_main,
            [
                "milestones.py",
                "due",
                "--paper-root",
                str(root),
                "--today",
                "2027-04-01",
            ],
        )

        self.assertEqual(code, 1, stderr)
        report = json.loads(stdout)
        self.assertEqual(report["due"][0]["checkpoint"], "T-30")
        self.assertEqual(report["due"][0]["stage"], "results-ready")
        self.assertEqual(report["due"][0]["gate"], "claims_supported")
        self.assertEqual(report["advisories"], [])

    def test_manifest_clean_entry_is_clean(self):
        root = self._derive()
        path = self._write_manifest(root, [self._manifest_item(root)])
        items = load_manifest(path)

        problems, advisories = check_manifest(items, root)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_manifest_missing_generator_is_reported(self):
        root = self._derive()
        item = self._manifest_item(root)
        del item["generator"]
        path = self._write_manifest(root, [item])
        items = load_manifest(path)

        problems, _ = check_manifest(items, root)

        self.assertIn(
            "figure-provenance-missing",
            {problem.code for problem in problems},
        )

    def test_revision_ledger_valid_file_exits_zero(self):
        root = self._derive()
        path = self._write_ledger(
            root,
            "| C1 | reviewer | 证据不足 | run-001 | 补充实验 | 是 | 待处理 |",
        )
        code, stdout, stderr = self._run(
            revision_ledger_main,
            ["revision_ledger.py", "--ledger", str(path)],
        )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["problem_count"], 0)

    def test_revision_ledger_bad_risk_exits_one(self):
        root = self._derive()
        path = self._write_ledger(
            root,
            "| C1 | reviewer | 证据不足 | 无 | 补充实验 | 是 | 待处理 |",
        )
        code, stdout, stderr = self._run(
            revision_ledger_main,
            ["revision_ledger.py", "--ledger", str(path)],
        )

        self.assertEqual(code, 1, stderr)
        self.assertIn(
            "ledger-risk-without-evidence",
            {problem["code"] for problem in json.loads(stdout)["problems"]},
        )

    def test_validate_rejects_forged_backward_advance(self):
        root = self._derive()
        state = self._load_state(root)
        state["stage"]["history"] = [
            {
                "from": "writing",
                "to": "grounded",
                "at": "2026-10-03",
                "reason": "forged regression fixture",
                "kind": "advance",
            }
        ]
        (root / "ccfa.yaml").write_text(
            yaml.safe_dump(state, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        code, stdout, stderr = self._run(
            validate_main,
            ["validate.py", str(root / "ccfa.yaml")],
        )

        self.assertEqual(code, 1)
        report = json.loads(stdout)
        self.assertEqual(report["problem_count"], 1)
        self.assertEqual(report["problems"][0]["code"], "schema-invalid")
        self.assertIn("state-history-direction", stderr)


if __name__ == "__main__":
    unittest.main()
