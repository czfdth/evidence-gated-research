import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.resubmit_pipeline import check, render_report


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


class ResubmitPipelineTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        self.source = self.paper / "submission-source"
        self.target = self.paper / "submission-target"
        (self.source / "manuscript").mkdir(parents=True)
        (self.target / "manuscript").mkdir(parents=True)
        (self.source / "manuscript" / "refs.bib").write_text(
            "@misc{demo, title={Demo}}\n",
            encoding="utf-8",
        )
        (self.target / "manuscript" / "refs.bib").write_text(
            "@misc{demo, title={Demo}}\n",
            encoding="utf-8",
        )
        (self.source / "experiments" / "log").mkdir(parents=True)
        (self.target / "experiments" / "log").mkdir(parents=True)
        for name in ("RUN1.json", "RUN2.json"):
            (self.source / "experiments" / "log" / name).write_text(
                json.dumps({"run_id": name[:-5]}),
                encoding="utf-8",
            )
            (self.target / "experiments" / "log" / name).write_text(
                json.dumps({"run_id": name[:-5]}),
                encoding="utf-8",
            )

    def _write_plan(self) -> None:
        digest = hashlib.sha256(
            (self.source / "manuscript" / "refs.bib").read_bytes()
        ).hexdigest()
        _write_yaml(
            self.paper / "data" / "resubmit-plan.yaml",
            {
                "version": 1,
                "source": {
                    "venue": "NeurIPS",
                    "dir": "submission-source",
                    "bib": "manuscript/refs.bib",
                },
                "target": {
                    "venue": "ICLR",
                    "dir": "submission-target",
                    "allowed_paths": ["manuscript/"],
                    "forbidden_paths": ["experiments/log/"],
                },
                "frozen": {
                    "bib_sha256": digest,
                    "run_ids": ["RUN1", "RUN2"],
                },
                "anonymity_patterns": ["Author One", "author@example.test"],
            },
        )

    def test_valid_resubmit_plan_passes(self):
        self._write_plan()

        problems, advisories = check(self.paper)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_target_cannot_equal_source(self):
        self._write_plan()
        path = self.paper / "data" / "resubmit-plan.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        payload["target"]["dir"] = "submission-source"
        _write_yaml(path, payload)

        problems, _advisories = check(self.paper)

        self.assertIn(
            "resubmit-source-target-conflict",
            [problem.code for problem in problems],
        )

    def test_changed_bib_is_problem(self):
        self._write_plan()
        (self.target / "manuscript" / "refs.bib").write_text(
            "@misc{demo, title={Changed}}\n",
            encoding="utf-8",
        )

        problems, _advisories = check(self.paper)

        self.assertIn(
            "resubmit-frozen-bib-changed",
            [problem.code for problem in problems],
        )

    def test_new_experiment_run_is_problem(self):
        self._write_plan()
        (self.target / "experiments" / "log" / "RUN3.json").write_text(
            json.dumps({"run_id": "RUN3"}),
            encoding="utf-8",
        )

        problems, _advisories = check(self.paper)

        self.assertIn(
            "resubmit-new-experiment",
            [problem.code for problem in problems],
        )

    def test_anonymity_leak_is_problem_and_render_names_it(self):
        self._write_plan()
        (self.target / "manuscript" / "main.tex").write_text(
            "Author One\n",
            encoding="utf-8",
        )

        problems, _advisories = check(self.paper)
        report = render_report({"problems": [p._asdict() for p in problems]})

        self.assertIn(
            "resubmit-anonymity-leak",
            [problem.code for problem in problems],
        )
        self.assertIn("anonymity", report)


if __name__ == "__main__":
    unittest.main()
