import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.ara_extract import extract


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


class AraExtractTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "manuscript" / "sections").mkdir(parents=True)
        (self.paper / "figures").mkdir()
        (self.paper / "tables").mkdir()
        (self.paper / "experiments" / "log").mkdir(parents=True)
        _write_yaml(
            self.paper / "ccfa.yaml",
            {"project": {"title": "Demo"}, "target_venue": {"name": "NeurIPS"}},
        )
        _write_yaml(
            self.paper / "data" / "claim-registry.yaml",
            {
                "version": 1,
                "claims": [{"id": "C1", "statement": "X improves Y", "experiments": ["RUN1"]}],
            },
        )
        _write_yaml(
            self.paper / "data" / "exploration-graph.yaml",
            {
                "version": 1,
                "entries": [
                    {
                        "id": "X1",
                        "kind": "dead-end",
                        "summary": "static rank failed",
                        "claim_ids": ["C1"],
                        "run_ids": ["RUN1"],
                        "rationale": "quality dropped",
                    }
                ],
            },
        )
        _write_yaml(
            self.paper / "figures" / "manifest.yaml",
            {"version": 1, "figures": [{"id": "F1", "path": "figures/plot.pdf"}]},
        )
        (self.paper / "manuscript" / "sections" / "main.tex").write_text(
            "\\section{Method}\n\\section{Results}\n",
            encoding="utf-8",
        )
        (self.paper / "manuscript" / "references.bib").write_text(
            "@article{a, title={A}, author={Doe}, year={2026}}\n",
            encoding="utf-8",
        )
        (self.paper / "experiments" / "log" / "RUN1.json").write_text(
            json.dumps({"run_id": "RUN1", "metrics": {"accuracy": 0.8}}),
            encoding="utf-8",
        )
        (self.paper / "tables" / "main.csv").write_text(
            "model,accuracy\nours,0.8\n",
            encoding="utf-8",
        )

    def test_extract_writes_semantic_inputs_and_report(self):
        report = extract(self.paper)
        out = self.paper / "ara-input"

        for name in (
            "problem.yaml",
            "concepts.yaml",
            "solution.yaml",
            "related_work.yaml",
            "experiments.yaml",
            "configs.yaml",
            "trace.yaml",
            "evidence.yaml",
            "EXTRACTION_REPORT.json",
        ):
            self.assertTrue((out / name).is_file(), name)
        self.assertEqual(report["claims"], 1)
        self.assertFalse(report["seal_level1_ready"])
        self.assertIn("concepts definitions", report["unresolved"])

    def test_extract_refuses_overwrite(self):
        extract(self.paper)

        with self.assertRaisesRegex(ValueError, "已存在"):
            extract(self.paper)


if __name__ == "__main__":
    unittest.main()
