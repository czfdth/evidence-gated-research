import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.ara_compile import compile_ara, validate_ara


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


class AraCompileTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "data").mkdir()
        (self.paper / "experiments" / "log").mkdir(parents=True)
        (self.paper / "figures").mkdir()
        (self.paper / "experiments" / "log" / "RUN1.json").write_text(
            json.dumps(
                {
                    "run_id": "RUN1",
                    "status": "completed",
                    "metrics": {"accuracy": 0.8},
                }
            ),
            encoding="utf-8",
        )
        _write_yaml(
            self.paper / "ccfa.yaml",
            {
                "project": {
                    "title": "Test Paper",
                    "short_name": "test",
                },
                "target_venue": {
                    "name": "NeurIPS",
                    "year": "2027",
                    "mode": "conference",
                },
                "stage": {"current": "internal-review"},
            },
        )
        _write_yaml(
            self.paper / "data" / "claim-registry.yaml",
            {
                "version": 1,
                "claims": [
                    {
                        "id": "claim-1",
                        "statement": "X improves Y",
                        "type": "empirical",
                        "status": "supported",
                        "assumptions": [],
                        "limitations": [],
                        "proof": None,
                        "experiments": ["RUN1"],
                        "figures": ["F1"],
                        "citations": [],
                    }
                ],
            },
        )
        _write_yaml(
            self.paper / "data" / "exploration-graph.yaml",
            {
                "version": 1,
                "entries": [
                    {
                        "id": "X1",
                        "kind": "active",
                        "summary": "Test X against baseline",
                        "claim_ids": ["claim-1"],
                        "run_ids": ["RUN1"],
                        "rationale": "baseline comparison",
                    },
                    {
                        "id": "X2",
                        "kind": "dead-end",
                        "summary": "Alternative without X",
                        "claim_ids": ["claim-1"],
                        "run_ids": ["RUN1"],
                        "rationale": "performance collapsed",
                    },
                ],
            },
        )
        _write_yaml(
            self.paper / "figures" / "manifest.yaml",
            {
                "version": 1,
                "figures": [
                    {
                        "id": "F1",
                        "path": "figures/plot.pdf",
                        "sha256": "sha256:" + "a" * 64,
                        "source": "RUN1",
                    }
                ],
            },
        )

    def test_compile_creates_mandatory_scaffold_and_report(self):
        out = self.paper / "ara"

        report = compile_ara(self.paper, out)

        for rel in (
            "PAPER.md",
            "logic/problem.md",
            "logic/claims.md",
            "logic/concepts.md",
            "logic/experiments.md",
            "logic/solution/architecture.md",
            "logic/solution/algorithm.md",
            "logic/solution/constraints.md",
            "logic/solution/heuristics.md",
            "logic/related_work.md",
            "src/configs/training.md",
            "src/configs/model.md",
            "src/environment.md",
            "trace/exploration_tree.yaml",
            "evidence/README.md",
        ):
            with self.subTest(rel=rel):
                self.assertTrue((out / rel).is_file(), rel)
        self.assertFalse(report["seal_level1_ready"])
        self.assertIn("concepts>=5", report["unmet_requirements"])

    def test_claims_and_trace_are_mapped_from_ledgers(self):
        out = self.paper / "ara"

        compile_ara(self.paper, out)

        claims = (out / "logic" / "claims.md").read_text(encoding="utf-8")
        tree = yaml.safe_load(
            (out / "trace" / "exploration_tree.yaml").read_text(encoding="utf-8")
        )
        self.assertIn("## C01: X improves Y", claims)
        self.assertIn("**Proof**: [E01]", claims)
        self.assertEqual(tree["tree"][0]["id"], "N01")
        self.assertTrue(tree["tree"][0]["children"])

    def test_compile_refuses_to_overwrite(self):
        out = self.paper / "ara"
        compile_ara(self.paper, out)

        with self.assertRaisesRegex(ValueError, "已存在"):
            compile_ara(self.paper, out)

    def test_validator_reports_missing_file(self):
        out = self.paper / "ara"
        compile_ara(self.paper, out)
        (out / "logic" / "concepts.md").unlink()

        problems, _advisories = validate_ara(out)

        self.assertIn(
            "ara-missing-file",
            [problem.code for problem in problems],
        )

    def _write_semantic_inputs(self) -> None:
        input_dir = self.paper / "ara-input"
        _write_yaml(
            input_dir / "problem.yaml",
            {
                "observations": [
                    {
                        "id": "O1",
                        "title": "Baseline is weak",
                        "statement": "Baseline accuracy is low.",
                        "evidence": "Table 1",
                        "implication": "Improvement is needed.",
                    }
                ],
                "gaps": [
                    {
                        "id": "G1",
                        "title": "No unified method",
                        "statement": "Existing methods do not combine both goals.",
                        "caused_by": ["O1"],
                        "existing_attempts": "Separate methods",
                        "why_they_fail": "They optimize only one goal.",
                    }
                ],
                "key_insight": {
                    "insight": "A shared adapter can solve both goals.",
                    "derived_from": ["O1", "G1"],
                    "enables": "Unified training",
                },
                "assumptions": ["A1: training data is fixed"],
            },
        )
        _write_yaml(
            input_dir / "concepts.yaml",
            {
                "concepts": [
                    {
                        "term": f"Concept {index}",
                        "notation": f"$x_{index}$",
                        "definition": f"Definition {index}",
                        "boundary_conditions": "finite data",
                        "related": [],
                    }
                    for index in range(1, 6)
                ]
            },
        )
        _write_yaml(
            input_dir / "solution.yaml",
            {
                "architecture": [
                    {
                        "name": "Shared adapter",
                        "purpose": "co-adapt pruning and tuning",
                        "inputs": ["x"],
                        "outputs": ["y"],
                        "interactions": "adapter",
                        "design_choices": "shared",
                    }
                ],
                "algorithm": {
                    "math": "$y=f(x)$",
                    "pseudocode": "return f(x)",
                    "complexity": "O(n)",
                },
                "constraints": ["finite compute"],
                "heuristics": [
                    {
                        "id": "H1",
                        "description": "dynamic rank",
                        "rationale": "adapt capacity",
                        "sensitivity": "medium",
                        "bounds": "1..64",
                        "code_ref": "src/execution/core.py",
                        "source": "Section 3",
                    }
                ],
            },
        )
        _write_yaml(
            input_dir / "related_work.yaml",
            {
                "entries": [
                    {
                        "id": "RW1",
                        "citation": "Doe et al., 2025",
                        "doi": "10.1000/example",
                        "type": "extends",
                        "delta": {"what_changed": "adds adapter", "why": "efficiency"},
                        "claims_affected": ["C01"],
                        "adopted_elements": ["baseline setup"],
                    }
                ]
            },
        )
        _write_yaml(
            input_dir / "experiments.yaml",
            {
                "experiments": [
                    {
                        "id": f"E{index:02d}",
                        "title": f"Experiment {index}",
                        "verifies": ["C01"],
                        "setup": {"Model": "test", "Hardware": "cpu", "Dataset": "data", "System": "test"},
                        "procedure": ["run", "measure"],
                        "metrics": "accuracy",
                        "expected_outcome": "method outperforms baseline",
                        "baselines": ["baseline"],
                        "dependencies": "none",
                    }
                    for index in range(1, 4)
                ]
            },
        )
        _write_yaml(
            input_dir / "configs.yaml",
            {
                "training": [
                    {
                        "name": "learning_rate",
                        "value": "3e-4",
                        "rationale": "standard",
                        "search_range": "1e-5..1e-3",
                        "sensitivity": "medium",
                        "source": "Section 4",
                    }
                ],
                "model": [
                    {
                        "name": "hidden_size",
                        "value": "256",
                        "rationale": "small model",
                        "search_range": "128..512",
                        "sensitivity": "low",
                        "source": "Section 3",
                    }
                ],
            },
        )
        _write_yaml(
            input_dir / "trace.yaml",
            {
                "tree": [
                    {
                        "id": "N01",
                        "type": "question",
                        "support_level": "explicit",
                        "source_refs": ["§1"],
                        "title": "Question",
                        "description": "Can one method solve both?",
                        "children": [
                            {
                                "id": f"N{index:02d}",
                                "type": "experiment",
                                "support_level": "explicit",
                                "source_refs": ["Table 1"],
                                "title": f"Experiment {index}",
                                "result": "result",
                                "evidence": ["C01"],
                                "children": [],
                            }
                            for index in range(2, 7)
                        ],
                    },
                    {
                        "id": "N07",
                        "type": "decision",
                        "support_level": "explicit",
                        "source_refs": ["§3"],
                        "title": "Use shared adapter",
                        "choice": "shared adapter",
                        "alternatives": ["separate adapters"],
                        "evidence": "ablation",
                        "children": [],
                    },
                    {
                        "id": "N08",
                        "type": "dead_end",
                        "support_level": "explicit",
                        "source_refs": ["§5"],
                        "title": "Static adapter failed",
                        "hypothesis": "static is enough",
                        "failure_mode": "quality loss",
                        "lesson": "dynamic ranks are needed",
                    },
                ]
            },
        )
        code_dir = input_dir / "src" / "execution"
        code_dir.mkdir(parents=True)
        (code_dir / "core.py").write_text(
            "def forward(x: float) -> float:\n    return x\n",
            encoding="utf-8",
        )
        _write_yaml(
            input_dir / "evidence.yaml",
            {
                "tables": [
                    {
                        "filename": "table1_main.md",
                        "source": "Table 1",
                        "caption": "Main results",
                        "extraction_type": "raw_table",
                        "rows": [["model", "accuracy"], ["ours", "0.8"]],
                    }
                ],
                "figures": [
                    {
                        "filename": "figure1_curve.md",
                        "source": "Figure 1",
                        "caption": "Curve",
                        "extraction_type": "raw_figure",
                        "rows": [["x", "y"], ["1", "0.8"]],
                    }
                ],
            },
        )

    def test_full_semantic_input_can_pass_seal_level_one(self):
        self._write_semantic_inputs()
        out = self.paper / "ara"

        report = compile_ara(self.paper, out)

        self.assertTrue(report["seal_level1_ready"], report["unmet_requirements"])
        problems, _advisories = validate_ara(out)
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
