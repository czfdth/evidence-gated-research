import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import yaml

from ccfa.cross_review import check_review, run_review
from ccfa.milestones import main as milestones_main
from ccfa.queue import run_queue
from ccfa.watch import scan

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTOMATION_DIR = REPO_ROOT / "automation"


def _declared_fields(text: str) -> set[str]:
    """Field names the template's read-fields section promises, nothing else."""
    section = text.split("## 读取字段", 1)[1].split("##", 1)[0]
    return set(re.findall(r"^- `([a-z_]+)`", section, flags=re.MULTILINE))

ATOM_ONE = """\
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>urn:test:1</id>
    <title>First</title>
    <published>2026-10-01T00:00:00Z</published>
    <summary>First</summary>
  </entry>
</feed>
"""

ATOM_TWO = """\
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>urn:test:1</id>
    <title>First</title>
    <published>2026-10-01T00:00:00Z</published>
    <summary>First</summary>
  </entry>
  <entry>
    <id>urn:test:2</id>
    <title>Second</title>
    <published>2026-10-02T00:00:00Z</published>
    <summary>Second</summary>
  </entry>
</feed>
"""


class AutomationDocumentationTests(unittest.TestCase):
    def test_readme_covers_mounting_silence_and_user_confirmation(self):
        text = (AUTOMATION_DIR / "README.md").read_text(encoding="utf-8")

        self.assertIn("Codex automations", text)
        self.assertIn("本地项目", text)
        self.assertIn("实际创建 automations 需用户确认", text)
        self.assertIn("没有实质变化就不通知", text)
        self.assertIn("不得修改论文正文", text)
        self.assertIn("结论字段", text)

    def test_readme_names_all_four_prompt_templates(self):
        text = (AUTOMATION_DIR / "README.md").read_text(encoding="utf-8")

        for name in (
            "weekly-watch.md",
            "deadline-check.md",
            "stage-advance.md",
            "experiment-queue.md",
        ):
            with self.subTest(name=name):
                self.assertIn(name, text)

    def test_prompt_templates_contain_command_fields_quiet_rule_and_no_write_rule(self):
        expected = {
            "weekly-watch.md": (
                "tools/ccfa/watch.py",
                ("baseline", "new", "seen_total", "skipped"),
            ),
            "deadline-check.md": (
                "tools/ccfa/milestones.py",
                ("mode", "due", "missing_gates", "problems"),
            ),
            "stage-advance.md": (
                "tools/ccfa/milestones.py",
                ("current", "gate", "updated_at"),
            ),
            "experiment-queue.md": (
                "tools/ccfa/queue.py",
                ("runs", "runs[].name", "runs[].attempts", "runs[].status", "stopped"),
            ),
        }
        for name, (script, fields) in expected.items():
            with self.subTest(name=name):
                text = (AUTOMATION_DIR / name).read_text(encoding="utf-8")
                self.assertIn(script, text)
                self.assertIn("tools/.venv", text)
                self.assertIn("PYTHONPATH", text)
                self.assertIn("没有实质变化就不通知", text)
                self.assertIn("不得修改论文正文", text)
                self.assertIn("结论字段", text)
                for field in fields:
                    with self.subTest(field=field):
                        self.assertIn(f"`{field}`", text)

    def test_root_readme_lists_automation_directory(self):
        text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("| `automation/` |", text)

    def test_stage_template_is_manual_and_matches_stage_output_fields(self):
        text = (AUTOMATION_DIR / "stage-advance.md").read_text(encoding="utf-8")
        self.assertIn("仅手动触发", text)

        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "ccfa.yaml"
            state_path.write_text(
                yaml.safe_dump(
                    {
                        "stage": {
                            "current": "writing",
                            "gate": "draft_complete",
                            "updated_at": "2026-10-03",
                        }
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = milestones_main(
                    [
                        "milestones",
                        "stage",
                        "--paper-root",
                        str(state_path.parent),
                    ]
                )
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        real_fields = set(json.loads(stdout.getvalue()))
        for field in real_fields:
            self.assertIn(f"`{field}`", text)
        self.assertEqual(_declared_fields(text), real_fields)

    def test_deadline_template_fields_match_real_due_output(self):
        text = (AUTOMATION_DIR / "deadline-check.md").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "ccfa.yaml").write_text(
                yaml.safe_dump(
                    {
                        "target_venue": {
                            "name": "Smoke",
                            "mode": "conference",
                            "deadline": "2027-05-01",
                        },
                        "stage": {"current": "idea"},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = milestones_main(
                    [
                        "milestones",
                        "due",
                        "--paper-root",
                        str(root),
                        "--today",
                        "2027-04-05",
                    ]
                )
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        countdown_report = json.loads(stdout.getvalue())
        for field in ("due", "problems", "advisories"):
            self.assertIn(field, countdown_report)
            self.assertIn(f"`{field}`", text)
        self.assertEqual(_declared_fields(text), set(countdown_report))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "ccfa.yaml").write_text(
                yaml.safe_dump(
                    {
                        "target_venue": {
                            "name": "Smoke",
                            "mode": "conference",
                            "deadline": None,
                        },
                        "stage": {"current": "idea"},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = milestones_main(
                    [
                        "milestones",
                        "due",
                        "--paper-root",
                        str(root),
                        "--today",
                        "2027-04-10",
                    ]
                )
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        sequential_report = json.loads(stdout.getvalue())
        self.assertEqual(
            _declared_fields(text) - {"advisories"},
            set(sequential_report),
        )

    def test_weekly_watch_fields_match_real_scan_output(self):
        text = (AUTOMATION_DIR / "weekly-watch.md").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            result = scan(
                ["https://feed"],
                Path(temporary) / "watch-state.json",
                fetcher=lambda _url: ATOM_ONE,
            )

        self.assertEqual(_declared_fields(text), set(result))

    def test_experiment_queue_fields_match_real_output(self):
        text = (AUTOMATION_DIR / "experiment-queue.md").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue_path = root / "queue.json"
            queue_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "queue": [{"name": "ok", "command": ["python", "ok.py"]}],
                    }
                ),
                encoding="utf-8",
            )
            result = run_queue(
                queue_path,
                log_dir=root / "logs",
                runner=lambda argv, cwd, timeout_s: 0,
            )

        self.assertEqual(_declared_fields(text), set(result))


class AutomationEndToEndTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper_root = Path(self._temporary.name)

    def _write_state(self, *, stage="writing", deadline="2026-01-01"):
        state = {
            "target_venue": {
                "name": "NeurIPS",
                "year": "2027",
                "mode": "conference",
                "deadline": deadline,
            },
            "stage": {"current": stage, "gate": "draft_complete"},
        }
        (self.paper_root / "ccfa.yaml").write_text(
            yaml.safe_dump(state, sort_keys=False),
            encoding="utf-8",
        )

    def test_milestones_expired_exits_one(self):
        self._write_state()
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = milestones_main(
                [
                    "milestones",
                    "due",
                    "--paper-root",
                    str(self.paper_root),
                    "--today",
                    "2026-01-02",
                ]
            )

        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout.getvalue())["due"][0]["checkpoint"], "overdue")
        self.assertIn("deadline-passed", stderr.getvalue())

    def test_watch_baseline_then_incremental_new_id(self):
        state_path = self.paper_root / "watch-state.json"
        first = scan(
            ["https://feed"],
            state_path,
            fetcher=lambda _url: ATOM_ONE,
        )
        second = scan(
            ["https://feed"],
            state_path,
            fetcher=lambda _url: ATOM_TWO,
        )

        self.assertTrue(first["baseline"])
        self.assertEqual(first["new"], [])
        self.assertEqual([entry["id"] for entry in second["new"]], ["urn:test:2"])

    def test_queue_records_one_success_and_one_failure(self):
        queue_path = self.paper_root / "queue.json"
        queue_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "queue": [
                        {"name": "ok", "command": ["python", "ok.py"]},
                        {"name": "bad", "command": ["python", "bad.py"]},
                    ],
                }
            ),
            encoding="utf-8",
        )
        codes = iter([0, 3])

        def runner(argv, cwd, timeout_s):
            return next(codes)

        log_dir = self.paper_root / "logs"
        result = run_queue(queue_path, log_dir=log_dir, runner=runner)

        self.assertEqual(
            [run["status"] for run in result["runs"]],
            ["complete", "failed"],
        )
        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(log_dir.glob("*.json"))
        ]
        self.assertEqual([record["status"] for record in records], ["completed", "failed"])

    def test_cross_review_blocking_record_is_reported_by_check(self):
        self._write_state(stage="internal-review", deadline=None)
        input_path = self.paper_root / "main.tex"
        input_path.write_text(
            "\\documentclass{article}\n"
            "The baseline comparison omits the strongest published method "
            "entirely.\n",
            encoding="utf-8",
        )
        payload = {
            "verdict": "blocking",
            "blocking": [
                {
                    "title": "Missing evidence",
                    "evidence": (
                        'main.tex: "The baseline comparison omits the '
                        'strongest published method entirely."'
                    ),
                }
            ],
            "summary": "blocking",
        }

        def runner(argv, cwd, timeout, prompt):
            output = Path(argv[argv.index("-o") + 1])
            output.write_text(json.dumps(payload), encoding="utf-8")
            return 0, ""

        codex_config = self.paper_root / "config.toml"
        codex_config.write_text(
            'model_provider = "deepseek-provider"\n'
            'model = "deepseek-v4-flash"\n'
            '[model_providers.deepseek-provider]\n'
            'base_url = "https://deepseek.example.test/v1"\n',
            encoding="utf-8",
        )
        run_review(
            self.paper_root,
            stage="internal-review",
            paths=[Path("main.tex")],
            runner=runner,
            model="deepseek-v4-pro",
            codex_config=codex_config,
            allow_same_family=True,
            override_reason=(
                "test fixture: no second-family provider is configured"
            ),
        )

        self.assertEqual(
            [problem.code for problem in check_review(self.paper_root)],
            ["review-blocking"],
        )


if __name__ == "__main__":
    unittest.main()
