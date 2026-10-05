import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.proof_run import check_run, materialize_run


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


class ProofRunTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "data").mkdir()
        _write_yaml(
            self.paper / "data" / "proof-campaign.yaml",
            {
                "version": 1,
                "not_applicable": False,
                "not_applicable_reason": "",
                "campaigns": [
                    {
                        "id": "PC1",
                        "claim_id": "C1",
                        "theorem_id": "prop:test",
                        "status": "blocked",
                        "attempts": [
                            {
                                "id": "A1",
                                "strategy": "反证法",
                                "status": "partial",
                                "result": "卡在辅助引理",
                                "evidence": ["RUN1"],
                                "failure_reason": "",
                                "next_action": "证明辅助引理",
                            }
                        ],
                    }
                ],
            },
        )

    def test_materialize_creates_aris_run_directory(self):
        run_dir = self.paper / "prompts" / "260101-01"

        report = materialize_run(self.paper, run_dir, campaign_id="PC1")

        for name in (
            "task.md",
            "materials.md",
            "local-proof.md",
            "source-manifest.md",
            "codex-ledger.md",
            "audit.md",
            "final.md",
            "next.md",
        ):
            self.assertTrue((run_dir / name).is_file(), name)
        self.assertTrue((run_dir / "sources").is_dir())
        self.assertEqual(report["status"], "LOCAL_ATTEMPT")
        self.assertIn("PC1", (run_dir / "task.md").read_text(encoding="utf-8"))

    def test_materialize_refuses_overwrite(self):
        run_dir = self.paper / "prompts" / "260101-01"
        materialize_run(self.paper, run_dir, campaign_id="PC1")

        with self.assertRaisesRegex(ValueError, "已存在"):
            materialize_run(self.paper, run_dir, campaign_id="PC1")

    def test_closed_run_requires_ready_status(self):
        run_dir = self.paper / "prompts" / "260101-01"
        materialize_run(self.paper, run_dir, campaign_id="PC1")

        problems, _advisories = check_run(run_dir, require_closed=True)

        self.assertIn(
            "proof-run-not-closed",
            [problem.code for problem in problems],
        )

    def test_notation_gate_rejects_undefined_or_colliding_symbols(self):
        run_dir = self.paper / "prompts" / "260101-01"
        materialize_run(self.paper, run_dir, campaign_id="PC1")
        (run_dir / "audit.md").write_text(
            "Core semantic objects retained: 4/5 (80%)\n"
            "Undefined symbols: 2\n"
            "Symbol collisions: 1\n"
            "Top-down derivation structure: FAIL\n",
            encoding="utf-8",
        )

        problems, _advisories = check_run(
            run_dir,
            notation_required=True,
            require_closed=True,
        )

        codes = [problem.code for problem in problems]
        self.assertIn("proof-run-notation-retention", codes)
        self.assertIn("proof-run-undefined-symbols", codes)
        self.assertIn("proof-run-symbol-collisions", codes)
        self.assertIn("proof-run-derivation-gate", codes)

    def test_ready_run_passes_closed_checks(self):
        run_dir = self.paper / "prompts" / "260101-01"
        materialize_run(self.paper, run_dir, campaign_id="PC1")
        (run_dir / "codex-ledger.md").write_text(
            "# Codex Ledger\n\n- status: READY_FOR_USER\n",
            encoding="utf-8",
        )
        (run_dir / "audit.md").write_text(
            "Core semantic objects retained: 5/5 (100%)\n"
            "Undefined symbols: 0\n"
            "Symbol collisions: 0\n"
            "Maximum parallel representations of one object: 1\n"
            "Maximum alias-chain depth: 1\n"
            "Maximum active nonstandard symbols in one proof step: 3\n"
            "Top-down derivation structure: PASS\n",
            encoding="utf-8",
        )
        (run_dir / "final.md").write_text(
            "# Final Proof\n\nCompleted proof.\n",
            encoding="utf-8",
        )

        problems, advisories = check_run(
            run_dir,
            notation_required=True,
            require_closed=True,
        )

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])


if __name__ == "__main__":
    unittest.main()
