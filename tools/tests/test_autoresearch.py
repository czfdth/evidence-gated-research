import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.autoresearch import (
    check_mutation_proposals,
    check_plan_candidates,
    generate_plan_candidates,
    mutate_code,
)


class AutoResearchTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "data").mkdir()
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "data" / "claim-registry.yaml").write_text(
            "version: 1\n"
            "claims:\n"
            "  - id: C1\n"
            "    statement: The candidate improves accuracy.\n",
            encoding="utf-8",
        )
        (self.root / "src" / "model.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.root / "tests" / "check_value.py").write_text(
            "from pathlib import Path\n"
            "assert 'VALUE = 2' in Path('src/model.py').read_text()\n",
            encoding="utf-8",
        )

    def test_heuristic_plan_candidates_are_checked(self):
        report = generate_plan_candidates(self.root)

        self.assertEqual(report["status"], "candidates-found")
        self.assertEqual(len(report["plans"]), 1)
        problems = check_plan_candidates(self.root)
        self.assertEqual(problems, [])

    def test_model_plan_without_id_is_accepted_and_given_an_id(self):
        def generator(prompt, **kwargs):
            return {
                "plans": [
                    {
                        "claim_ids": ["C1"],
                        "problem": "p",
                        "gap": "g",
                        "hypothesis": "h",
                        "experiment": {
                            "design": "d",
                            "procedure": ["run"],
                            "budget_minutes": 10,
                            "success_metric": "accuracy",
                        },
                        "baselines": ["baseline"],
                        "metrics": ["accuracy"],
                        "risks": ["underpowered"],
                        "kill_criteria": ["no lift"],
                        "expected_evidence": "run-log",
                    }
                ]
            }

        report = generate_plan_candidates(
            self.root,
            model="fake",
            generator=generator,
        )

        self.assertEqual(report["plans"][0]["id"], "RP-001")

    def test_code_mutation_runs_in_sandbox_and_leaves_source_unchanged(self):
        def generator(prompt, **kwargs):
            return {
                "mutations": [
                    {
                        "file": "src/model.py",
                        "content": "VALUE = 2\n",
                        "hypothesis": "Doubling the value improves accuracy.",
                        "expected_effect": "The check passes.",
                    }
                ]
            }

        report = mutate_code(
            self.root,
            objective="Improve accuracy.",
            allow=["src/model.py"],
            model="fake",
            test_command="{python} tests/check_value.py",
            execute=True,
            generator=generator,
        )

        proposal = report["proposals"][0]
        self.assertEqual(proposal["status"], "proposed")
        self.assertEqual(proposal["sandbox_status"], "pass")
        self.assertIn("+VALUE = 2", proposal["diff"])
        self.assertEqual(
            (self.root / "src" / "model.py").read_text(encoding="utf-8"),
            "VALUE = 1\n",
        )
        self.assertEqual(check_mutation_proposals(self.root), [])

    def test_failed_sandbox_is_marked_rejected(self):
        def generator(prompt, **kwargs):
            return {
                "mutations": [
                    {
                        "file": "src/model.py",
                        "content": "VALUE = 3\n",
                        "hypothesis": "Wrong value.",
                        "expected_effect": "It will fail.",
                    }
                ]
            }

        report = mutate_code(
            self.root,
            objective="Improve accuracy.",
            allow=["src/model.py"],
            model="fake",
            test_command="{python} tests/check_value.py",
            execute=True,
            generator=generator,
        )

        self.assertEqual(report["proposals"][0]["status"], "rejected-sandbox")
        self.assertEqual(report["proposals"][0]["sandbox_status"], "fail")

    def test_check_mutations_detects_source_drift(self):
        def generator(prompt, **kwargs):
            return {
                "mutations": [
                    {
                        "file": "src/model.py",
                        "content": "VALUE = 2\n",
                        "hypothesis": "Doubling the value improves accuracy.",
                        "expected_effect": "The check passes.",
                    }
                ]
            }

        mutate_code(
            self.root,
            objective="Improve accuracy.",
            allow=["src/model.py"],
            model="fake",
            test_command="{python} tests/check_value.py",
            execute=True,
            generator=generator,
        )
        (self.root / "src" / "model.py").write_text("VALUE = 4\n", encoding="utf-8")

        problems = check_mutation_proposals(self.root)

        self.assertIn(
            "code-mutations-source-drift",
            [problem.code for problem in problems],
        )

    def test_check_plan_rejects_unknown_claim(self):
        output = self.root / "data" / "research-plan-candidates.yaml"
        output.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "status": "candidates-found",
                    "plans": [
                        {
                            "id": "RP-001",
                            "status": "proposed",
                            "human_review": "pending",
                            "claim_ids": ["C404"],
                            "problem": "p",
                            "gap": "g",
                            "hypothesis": "h",
                            "experiment": {
                                "design": "d",
                                "procedure": ["run"],
                                "budget_minutes": 10,
                                "success_metric": "accuracy",
                            },
                            "baselines": [],
                            "metrics": [],
                            "risks": [],
                            "kill_criteria": [],
                            "expected_evidence": "run-log",
                        }
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        problems = check_plan_candidates(self.root, output)

        self.assertIn(
            "research-plans-unknown-claim",
            [problem.code for problem in problems],
        )


if __name__ == "__main__":
    unittest.main()
