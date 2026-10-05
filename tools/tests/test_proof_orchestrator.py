import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.proof_orchestrator import check, next_actions


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


class ProofOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "data").mkdir()
        (self.paper / "experiments" / "log").mkdir(parents=True)
        (self.paper / "experiments" / "log" / "RUN1.json").write_text(
            json.dumps({"run_id": "RUN1", "status": "completed"}),
            encoding="utf-8",
        )
        _write_yaml(
            self.paper / "data" / "claim-registry.yaml",
            {
                "version": 1,
                "claims": [
                    {"id": "C1", "statement": "claim", "type": "theoretical"}
                ],
            },
        )
        _write_yaml(
            self.paper / "data" / "proof-audit.yaml",
            {
                "version": 1,
                "status": "human-attested",
                "reviews": [
                    {
                        "id": "prop:test",
                        "reviewer": "Ada Lovelace",
                        "reviewed_at": "2026-10-05",
                        "method": "line-by-line",
                        "status": "verified",
                    }
                ],
            },
        )

    def _write_campaign(self, payload: dict) -> None:
        _write_yaml(
            self.paper / "data" / "proof-campaign.yaml",
            {"version": 1, **payload},
        )

    def _valid_campaign(self) -> dict:
        return {
            "not_applicable": False,
            "not_applicable_reason": "",
            "campaigns": [
                {
                    "id": "PC1",
                    "claim_id": "C1",
                    "theorem_id": "prop:test",
                    "status": "proved",
                    "attempts": [
                        {
                            "id": "A1",
                            "strategy": "反证法",
                            "status": "succeeded",
                            "result": "完成证明",
                            "evidence": ["RUN1"],
                            "failure_reason": "",
                            "next_action": "归档证明",
                        }
                    ],
                    "proof_review": {
                        "review_id": "prop:test",
                        "reviewer": "Ada Lovelace",
                        "reviewed_at": "2026-10-05",
                        "method": "line-by-line",
                        "status": "verified",
                    },
                }
            ],
        }

    def test_not_applicable_requires_reason(self):
        self._write_campaign(
            {
                "not_applicable": True,
                "not_applicable_reason": "",
                "campaigns": [],
            }
        )

        problems, _advisories = check(self.paper)

        self.assertIn(
            "proof-campaign-na-reason-missing",
            [problem.code for problem in problems],
        )

    def test_empty_campaign_is_advisory(self):
        self._write_campaign(
            {
                "not_applicable": False,
                "not_applicable_reason": "",
                "campaigns": [],
            }
        )

        problems, advisories = check(self.paper)

        self.assertEqual(problems, [])
        self.assertIn(
            "proof-campaign-empty",
            [advisory.code for advisory in advisories],
        )

    def test_valid_campaign_passes(self):
        self._write_campaign(self._valid_campaign())

        problems, advisories = check(self.paper)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_proved_requires_verified_human_proof_review(self):
        payload = self._valid_campaign()
        payload["campaigns"][0]["proof_review"]["status"] = "pending"
        self._write_campaign(payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "proof-campaign-proof-not-verified",
            [problem.code for problem in problems],
        )

    def test_unknown_claim_theorem_and_run_are_problems(self):
        payload = self._valid_campaign()
        campaign = payload["campaigns"][0]
        campaign["claim_id"] = "C404"
        campaign["theorem_id"] = "prop:missing"
        campaign["attempts"][0]["evidence"] = ["RUN404"]
        self._write_campaign(payload)

        problems, _advisories = check(self.paper)

        codes = [problem.code for problem in problems]
        self.assertIn("proof-campaign-unknown-claim", codes)
        self.assertIn("proof-campaign-unknown-theorem", codes)
        self.assertIn("proof-campaign-unknown-run", codes)

    def test_failed_attempt_needs_failure_reason_and_next_action_when_open(self):
        payload = self._valid_campaign()
        campaign = payload["campaigns"][0]
        campaign["status"] = "blocked"
        campaign.pop("proof_review", None)
        campaign["attempts"][0].update(
            {
                "status": "failed",
                "result": "证明失败",
                "failure_reason": "",
                "next_action": "",
            }
        )
        self._write_campaign(payload)

        problems, _advisories = check(self.paper)

        codes = [problem.code for problem in problems]
        self.assertIn("proof-campaign-attempt-incomplete", codes)

    def test_next_actions_reports_open_and_blocked_campaigns(self):
        payload = self._valid_campaign()
        campaign = payload["campaigns"][0]
        campaign["status"] = "blocked"
        campaign.pop("proof_review", None)
        campaign["attempts"][0].update(
            {
                "status": "partial",
                "result": "卡在引理",
                "failure_reason": "",
                "next_action": "证明辅助引理",
            }
        )
        self._write_campaign(payload)

        result = next_actions(self.paper)

        self.assertEqual(result["campaigns"][0]["id"], "PC1")
        self.assertIn("辅助引理", result["campaigns"][0]["action"])


if __name__ == "__main__":
    unittest.main()
