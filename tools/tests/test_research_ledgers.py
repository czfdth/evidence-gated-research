import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.research_ledgers import check


class ResearchLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        (self.root / "manuscript").mkdir()
        (self.root / "figures").mkdir()
        (self.root / "experiments" / "log").mkdir(parents=True)
        (self.root / "manuscript" / "references.bib").write_text(
            "@misc{gao2024ragsurvey, title={Survey}}\n",
            encoding="utf-8",
        )
        (self.root / "manuscript" / "sections").mkdir()
        (self.root / "manuscript" / "sections" / "08-open-problems.tex").write_text(
            "Limitations are discussed here.\n",
            encoding="utf-8",
        )
        (self.root / "figures" / "manifest.yaml").write_text(
            "figures:\n"
            "  - name: threat-model-lattice\n"
            "    file: figures/threat-model-lattice.pdf\n",
            encoding="utf-8",
        )
        (self.root / "experiments" / "log" / "run-1.json").write_text(
            '{"run_id": "run-1", "status": "completed"}\n',
            encoding="utf-8",
        )
        self._write_valid_ledgers()

    def _write(self, relative, payload):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def _write_valid_ledgers(self):
        self._write(
            "data/claim-registry.yaml",
            {
                "version": 1,
                "claims": [
                    {
                        "id": "C1",
                        "statement": "A bounded claim.",
                        "type": "empirical",
                        "status": "supported",
                        "assumptions": ["A1"],
                        "limitations": ["L1"],
                        "proof": None,
                        "experiments": ["run-1"],
                        "figures": ["threat-model-lattice"],
                        "citations": ["gao2024ragsurvey"],
                    }
                ],
            },
        )
        self._write(
            "data/assumptions-limitations.yaml",
            {
                "version": 1,
                "assumptions": [
                    {
                        "id": "A1",
                        "claim_ids": ["C1"],
                        "statement": "The corpus is frozen.",
                        "violation_impact": "Counts become stale.",
                    }
                ],
                "limitations": [
                    {
                        "id": "L1",
                        "claim_ids": ["C1"],
                        "statement": "Only 43 works are coded.",
                        "discussed_in": "manuscript/sections/08-open-problems.tex",
                    }
                ],
            },
        )
        self._write(
            "data/venue-checklist.yaml",
            {
                "version": 1,
                "venue": "NeurIPS",
                "source": "NeurIPS Paper Checklist",
                "items": [
                    {
                        "id": "claims",
                        "requirement": "Claims are stated with evidence.",
                        "status": "complete",
                        "evidence": ["data/claim-registry.yaml"],
                        "owner": "author",
                    }
                ],
            },
        )
        self._write(
            "data/artifact-provenance.yaml",
            {
                "version": 1,
                "artifacts": [
                    {
                        "id": "matrix",
                        "path": "data/claim-registry.yaml",
                        "decided_by": "human",
                        "source": "author coding",
                        "model_family": None,
                    }
                ],
            },
        )
        self._write(
            "data/exploration-graph.yaml",
            {
                "version": 1,
                "entries": [
                    {
                        "id": "E1",
                        "kind": "active",
                        "summary": "The active claim line.",
                        "claim_ids": ["C1"],
                        "run_ids": ["run-1"],
                        "rationale": None,
                    }
                ],
            },
        )
        self._write(
            "data/cost-ledger.yaml",
            {
                "version": 1,
                "currency": "USD",
                "paper": "demo",
                "entries": [
                    {
                        "kind": "gpu",
                        "amount": 1.5,
                        "unit": "gpu-hours",
                    }
                ],
            },
        )
        self._write(
            "data/risk-register.yaml",
            {
                "version": 1,
                "risks": [
                    {
                        "id": "R1",
                        "description": "Model review can miss a proof flaw.",
                        "severity": "high",
                        "mitigation": "Require human proof review.",
                        "evidence": ["data/claim-registry.yaml"],
                        "status": "open",
                    }
                ],
            },
        )

    def _codes(self, problems):
        return {problem.code for problem in problems}

    def test_valid_research_ledgers_pass(self):
        problems, advisories = check(self.root, require_core=True)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_empty_seeded_ledgers_are_valid_but_advisory(self):
        empty = {
            "data/claim-registry.yaml": {"version": 1, "claims": []},
            "data/assumptions-limitations.yaml": {
                "version": 1,
                "assumptions": [],
                "limitations": [],
            },
            "data/venue-checklist.yaml": {
                "version": 1,
                "venue": "",
                "source": "",
                "items": [],
            },
            "data/artifact-provenance.yaml": {
                "version": 1,
                "artifacts": [],
            },
            "data/exploration-graph.yaml": {
                "version": 1,
                "entries": [],
            },
            "data/cost-ledger.yaml": {
                "version": 1,
                "currency": "",
                "paper": "",
                "entries": [],
            },
            "data/risk-register.yaml": {
                "version": 1,
                "risks": [],
            },
        }
        for relative, payload in empty.items():
            self._write(relative, payload)

        problems, advisories = check(self.root, require_core=True)

        self.assertEqual(problems, [])
        self.assertIn("research-ledger-empty", self._codes(advisories))

    def test_missing_core_ledger_is_a_problem(self):
        for relative in (
            "data/claim-registry.yaml",
            "data/assumptions-limitations.yaml",
            "data/venue-checklist.yaml",
            "data/artifact-provenance.yaml",
            "data/exploration-graph.yaml",
            "data/cost-ledger.yaml",
            "data/risk-register.yaml",
        ):
            (self.root / relative).unlink()

        problems, _advisories = check(self.root, require_core=True)

        self.assertEqual(
            len(
                [
                    problem
                    for problem in problems
                    if problem.code == "research-ledger-missing"
                ]
            ),
            7,
        )

    def test_malformed_values_are_problems_not_crashes(self):
        registry = yaml.safe_load(
            (self.root / "data" / "claim-registry.yaml").read_text(
                encoding="utf-8"
            )
        )
        registry["claims"][0]["assumptions"] = [{"bad": "type"}]
        self._write("data/claim-registry.yaml", registry)
        checklist = yaml.safe_load(
            (self.root / "data" / "venue-checklist.yaml").read_text(
                encoding="utf-8"
            )
        )
        checklist["items"][0]["status"] = ["complete"]
        self._write("data/venue-checklist.yaml", checklist)

        problems, _advisories = check(self.root, require_core=True)

        self.assertIn("claim-registry-invalid", self._codes(problems))
        self.assertIn("venue-checklist-invalid", self._codes(problems))

    def test_supported_claim_without_evidence_is_a_problem(self):
        registry = yaml.safe_load(
            (self.root / "data" / "claim-registry.yaml").read_text(
                encoding="utf-8"
            )
        )
        registry["claims"][0]["experiments"] = []
        registry["claims"][0]["figures"] = []
        registry["claims"][0]["citations"] = []
        self._write("data/claim-registry.yaml", registry)

        problems, _advisories = check(self.root, require_core=True)

        self.assertIn("claim-registry-unsupported", self._codes(problems))

    def test_supported_theoretical_claim_requires_proof(self):
        registry = yaml.safe_load(
            (self.root / "data" / "claim-registry.yaml").read_text(
                encoding="utf-8"
            )
        )
        registry["claims"][0]["type"] = "theoretical"
        registry["claims"][0]["proof"] = None
        self._write("data/claim-registry.yaml", registry)

        problems, _advisories = check(self.root, require_core=True)

        self.assertIn(
            "claim-registry-theoretical-proof-missing",
            self._codes(problems),
        )

    def test_supported_empirical_claim_requires_experiment(self):
        registry = yaml.safe_load(
            (self.root / "data" / "claim-registry.yaml").read_text(
                encoding="utf-8"
            )
        )
        registry["claims"][0]["type"] = "empirical"
        registry["claims"][0]["experiments"] = []
        self._write("data/claim-registry.yaml", registry)

        problems, _advisories = check(self.root, require_core=True)

        self.assertIn(
            "claim-registry-empirical-experiment-missing",
            self._codes(problems),
        )

    def test_dangling_claim_references_are_problems(self):
        registry = yaml.safe_load(
            (self.root / "data" / "claim-registry.yaml").read_text(
                encoding="utf-8"
            )
        )
        claim = registry["claims"][0]
        claim["assumptions"] = ["A-missing"]
        claim["limitations"] = ["L-missing"]
        claim["experiments"] = ["run-missing"]
        claim["figures"] = ["figure-missing"]
        claim["citations"] = ["citation-missing"]
        claim["proof"] = "proof-missing"
        self._write("data/claim-registry.yaml", registry)

        problems, _advisories = check(self.root, require_core=True)

        codes = self._codes(problems)
        self.assertIn("claim-registry-unknown-assumption", codes)
        self.assertIn("claim-registry-unknown-limitation", codes)
        self.assertIn("claim-registry-unknown-experiment", codes)
        self.assertIn("claim-registry-unknown-figure", codes)
        self.assertIn("claim-registry-unknown-citation", codes)
        self.assertIn("claim-registry-unknown-proof", codes)

    def test_venue_complete_item_requires_existing_evidence(self):
        checklist = yaml.safe_load(
            (self.root / "data" / "venue-checklist.yaml").read_text(
                encoding="utf-8"
            )
        )
        checklist["items"][0]["evidence"] = ["data/missing.yaml"]
        self._write("data/venue-checklist.yaml", checklist)

        problems, _advisories = check(self.root)

        self.assertIn("venue-checklist-evidence-missing", self._codes(problems))

    def test_model_artifact_requires_family_and_source(self):
        provenance = yaml.safe_load(
            (self.root / "data" / "artifact-provenance.yaml").read_text(
                encoding="utf-8"
            )
        )
        provenance["artifacts"][0]["decided_by"] = "model"
        provenance["artifacts"][0]["model_family"] = None
        provenance["artifacts"][0]["source"] = ""
        self._write("data/artifact-provenance.yaml", provenance)

        problems, _advisories = check(self.root)

        self.assertIn(
            "artifact-provenance-model-family-missing",
            self._codes(problems),
        )
        self.assertIn("artifact-provenance-source-missing", self._codes(problems))

    def test_model_artifact_requires_run_or_hash_binding(self):
        provenance = yaml.safe_load(
            (self.root / "data" / "artifact-provenance.yaml").read_text(
                encoding="utf-8"
            )
        )
        provenance["artifacts"][0]["decided_by"] = "model"
        provenance["artifacts"][0]["model_family"] = "deepseek"
        provenance["artifacts"][0]["source"] = "model output"
        self._write("data/artifact-provenance.yaml", provenance)

        problems, _advisories = check(self.root)

        self.assertIn(
            "artifact-provenance-binding-missing",
            self._codes(problems),
        )

    def test_dead_end_requires_rationale(self):
        graph = yaml.safe_load(
            (self.root / "data" / "exploration-graph.yaml").read_text(
                encoding="utf-8"
            )
        )
        graph["entries"][0]["kind"] = "dead-end"
        graph["entries"][0]["rationale"] = None
        self._write("data/exploration-graph.yaml", graph)

        problems, _advisories = check(self.root)

        self.assertIn("exploration-rationale-missing", self._codes(problems))

    def test_exploration_entry_requires_claim_and_run_bindings(self):
        graph = yaml.safe_load(
            (self.root / "data" / "exploration-graph.yaml").read_text(
                encoding="utf-8"
            )
        )
        graph["entries"][0]["claim_ids"] = []
        graph["entries"][0]["run_ids"] = []
        self._write("data/exploration-graph.yaml", graph)

        problems, _advisories = check(self.root)

        self.assertIn("exploration-graph-invalid", self._codes(problems))

    def test_cost_amount_must_be_finite_and_non_negative(self):
        ledger = yaml.safe_load(
            (self.root / "data" / "cost-ledger.yaml").read_text(
                encoding="utf-8"
            )
        )
        ledger["entries"][0]["amount"] = -1
        self._write("data/cost-ledger.yaml", ledger)

        problems, _advisories = check(self.root)

        self.assertIn("cost-ledger-invalid-amount", self._codes(problems))

    def test_risk_placeholder_mitigation_is_rejected(self):
        register = yaml.safe_load(
            (self.root / "data" / "risk-register.yaml").read_text(
                encoding="utf-8"
            )
        )
        register["risks"][0]["mitigation"] = "pending"
        self._write("data/risk-register.yaml", register)

        problems, _advisories = check(self.root)

        self.assertIn("risk-register-placeholder", self._codes(problems))

    def test_duplicate_and_asymmetric_assumption_links_are_problems(self):
        assumptions = yaml.safe_load(
            (self.root / "data" / "assumptions-limitations.yaml").read_text(
                encoding="utf-8"
            )
        )
        assumptions["assumptions"].append(
            dict(assumptions["assumptions"][0])
        )
        assumptions["limitations"].append(
            dict(assumptions["limitations"][0])
        )
        self._write("data/assumptions-limitations.yaml", assumptions)
        registry = yaml.safe_load(
            (self.root / "data" / "claim-registry.yaml").read_text(
                encoding="utf-8"
            )
        )
        registry["claims"][0]["assumptions"] = []
        registry["claims"][0]["limitations"] = []
        self._write("data/claim-registry.yaml", registry)

        problems, _advisories = check(self.root, require_core=True)

        self.assertIn(
            "assumptions-limitations-duplicate",
            self._codes(problems),
        )
        self.assertIn(
            "claim-registry-asymmetric-assumption",
            self._codes(problems),
        )
        self.assertIn(
            "claim-registry-asymmetric-limitation",
            self._codes(problems),
        )

    def test_fake_run_log_filename_is_not_a_run_id(self):
        (self.root / "experiments" / "log" / "fake-name.json").write_text(
            '{"run_id": "run-1", "status": "completed"}\n',
            encoding="utf-8",
        )
        registry = yaml.safe_load(
            (self.root / "data" / "claim-registry.yaml").read_text(
                encoding="utf-8"
            )
        )
        registry["claims"][0]["experiments"] = ["fake-name"]
        self._write("data/claim-registry.yaml", registry)

        problems, _advisories = check(self.root, require_core=True)

        self.assertIn(
            "claim-registry-unknown-experiment",
            self._codes(problems),
        )

    def test_claims_policy_claim_list_must_match_registry(self):
        self._write(
            "data/claims.yaml",
            {
                "version": 1,
                "claims": ["C2"],
                "protected_sections": ["abstract"],
                "waivers": [],
            },
        )

        problems, _advisories = check(self.root, require_core=True)

        self.assertIn(
            "claim-registry-policy-mismatch",
            self._codes(problems),
        )


if __name__ == "__main__":
    unittest.main()
