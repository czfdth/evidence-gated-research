import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.governance_map import check, render_data_flows


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


class GovernanceMapTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "data").mkdir()

    def _write_all(self) -> None:
        _write_yaml(
            self.paper / "data" / "capability-matrix.yaml",
            {
                "version": 1,
                "capabilities": [
                    {
                        "id": "retrieval.citation_existence_gate",
                        "stage": "writing",
                        "control": "check DOI and title against indexes",
                        "status": "DESIGNED",
                        "evidence": ["file:data/citation-ledger.json"],
                    }
                ],
            },
        )
        _write_yaml(
            self.paper / "data" / "risk-register.yaml",
            {
                "version": 1,
                "risks": [
                    {
                        "id": "R1",
                        "description": "hallucinated citation",
                        "severity": "high",
                        "mitigation": "existence + claim support gate",
                        "controls": ["retrieval.citation_existence_gate"],
                        "evidence_status": "DESIGNED",
                        "residual_gap": "claim support still sampled",
                        "evidence": ["data/citation-ledger.json"],
                        "status": "open",
                    }
                ],
            },
        )
        _write_yaml(
            self.paper / "data" / "data-flows.yaml",
            {
                "version": 1,
                "network": [
                    {
                        "id": "crossref",
                        "endpoint": "https://api.crossref.org",
                        "purpose": "DOI verification",
                        "sends": "DOI and title query",
                        "credentials": "none",
                        "off_switch": "do not run citation verification",
                    }
                ],
                "stores": [
                    {
                        "id": "citation-cache",
                        "path": "data/citation-ledger.json",
                        "content": "resolver evidence",
                        "lifetime": "repository lifetime",
                        "delete": "delete with project",
                    }
                ],
            },
        )

    def test_valid_governance_map_passes(self):
        self._write_all()

        problems, advisories = check(self.paper)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_unknown_control_is_problem(self):
        self._write_all()
        risk_path = self.paper / "data" / "risk-register.yaml"
        payload = yaml.safe_load(risk_path.read_text(encoding="utf-8"))
        payload["risks"][0]["controls"] = ["missing.control"]
        _write_yaml(risk_path, payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "governance-map-unknown-control",
            [problem.code for problem in problems],
        )

    def test_invalid_capability_status_is_problem(self):
        self._write_all()
        path = self.paper / "data" / "capability-matrix.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        payload["capabilities"][0]["status"] = "DONE"
        _write_yaml(path, payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "governance-map-invalid",
            [problem.code for problem in problems],
        )

    def test_plaintext_secret_in_data_flow_is_problem(self):
        self._write_all()
        path = self.paper / "data" / "data-flows.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        payload["network"][0]["credentials"] = "sk-live-secret"
        _write_yaml(path, payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "governance-map-plaintext-credential",
            [problem.code for problem in problems],
        )

    def test_render_data_flows_lists_network_and_stores(self):
        self._write_all()
        payload = yaml.safe_load(
            (self.paper / "data" / "data-flows.yaml").read_text(
                encoding="utf-8"
            )
        )

        text = render_data_flows(payload)

        self.assertIn("crossref", text)
        self.assertIn("citation-cache", text)
        self.assertIn("do not run citation verification", text)


if __name__ == "__main__":
    unittest.main()
