import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.test_impact import select_tests


ROOT = Path(__file__).resolve().parents[2]
PAPER_ROOT = ROOT / "papers" / "example-paper"
PYTHON = sys.executable


def _workflow_run_commands(path):
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    commands = []
    for job in payload.get("jobs", {}).values():
        for step in job.get("steps", []):
            run = step.get("run")
            if not isinstance(run, str):
                continue
            current = None
            for raw in run.splitlines():
                line = raw.strip()
                continued = line.endswith("`")
                clean = line.rstrip("`").strip()
                if current is not None:
                    current = f"{current} {clean}"
                    if not continued:
                        commands.append(current)
                        current = None
                    continue
                if clean.startswith("python -m ccfa."):
                    if continued:
                        current = clean
                    else:
                        commands.append(clean)
    return commands


def _job_run_text(payload, job_name):
    job = payload["jobs"][job_name]
    return "\n".join(
        step.get("run", "")
        for step in job.get("steps", [])
        if isinstance(step.get("run"), str)
    )


def _informational_gate_steps(payload, job_name):
    return [
        step
        for step in payload["jobs"][job_name].get("steps", [])
        if step.get("continue-on-error") is True
    ]


def _run_workflow_command(command, *, cwd):
    command = command.replace(
        "${{ inputs.profile || 'standard' }}",
        "standard",
    ).replace(
        "${{ inputs.profile }}",
        "standard",
    )
    tokens = shlex.split(command, posix=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "tools")
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [PYTHON, *tokens[1:]],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        shell=False,
        check=False,
    )


def _assert_no_argparse_failure(testcase, result, command):
    stderr = result.stderr.casefold()
    with testcase.subTest(command=command):
        testcase.assertNotIn("unrecognized arguments", stderr)
        testcase.assertNotIn("the following arguments are required", stderr)
        testcase.assertNotIn("invalid choice", stderr)


class GitHubWorkflowTests(unittest.TestCase):
    def test_main_workflows_are_valid_yaml(self):
        workflow_dir = ROOT / ".github" / "workflows"
        expected = {
            "tests.yml",
            "paper-check.yml",
            "repro-smoke.yml",
            "reference-audit.yml",
            "release.yml",
        }

        self.assertEqual({path.name for path in workflow_dir.glob("*.yml")}, expected)
        for path in workflow_dir.glob("*.yml"):
            with self.subTest(path=path.name):
                payload = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIsInstance(payload, dict)
                self.assertIn("jobs", payload)

    def test_paper_workflows_are_valid_yaml(self):
        if not PAPER_ROOT.is_dir():
            self.skipTest("independent paper repository is not checked out")

        workflow_dir = PAPER_ROOT / ".github" / "workflows"
        expected = {"paper-check.yml", "repro-smoke.yml", "submission-gate.yml"}

        self.assertEqual({path.name for path in workflow_dir.glob("*.yml")}, expected)
        for path in workflow_dir.glob("*.yml"):
            with self.subTest(path=path.name):
                payload = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIsInstance(payload, dict)
                self.assertIn("jobs", payload)

    def test_main_cross_repository_token_is_not_embedded(self):
        main_check = (ROOT / ".github" / "workflows" / "paper-check.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("secrets.PAPER_REPOSITORY_TOKEN", main_check)
        self.assertNotRegex(main_check, r"github_pat_|ghp_[A-Za-z0-9]")

    def test_paper_cross_repository_token_is_not_embedded(self):
        if not PAPER_ROOT.is_dir():
            self.skipTest("independent paper repository is not checked out")

        paper_check = (
            PAPER_ROOT
            / ".github"
            / "workflows"
            / "paper-check.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("secrets.RESEARCH_WORKFLOW_TOKEN", paper_check)
        self.assertNotRegex(paper_check, r"github_pat_|ghp_[A-Za-z0-9]")

    def test_ci_recreates_the_product_virtualenv_layout(self):
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("python -m venv tools/.venv", workflow)
        self.assertIn("python -m venv app/.venv", workflow)
        self.assertIn(
            "scripts/test-impact.ps1 run --suite tools",
            workflow,
        )
        self.assertIn(
            "scripts/test-impact.ps1 run --suite app",
            workflow,
        )
        # Three Windows jobs build a virtualenv; the fourth is the Linux
        # portability job, which keeps the same UTF-8 contract for its output.
        self.assertEqual(workflow.count("PYTHONUTF8: '1'"), 4)

    def test_ci_installs_hash_locked_requirements(self):
        workflow_texts = [
            (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
            for name in ("tests.yml", "paper-check.yml", "repro-smoke.yml")
        ]
        if PAPER_ROOT.is_dir():
            workflow_texts.extend(
                (PAPER_ROOT / ".github" / "workflows" / name).read_text(
                    encoding="utf-8"
                )
                for name in ("paper-check.yml", "repro-smoke.yml")
            )

        for text in workflow_texts:
            with self.subTest(workflow=text.splitlines()[0]):
                self.assertNotIn("requirements.txt", text)
                self.assertIn("requirements.lock", text)

    def test_ci_runs_lint_and_dependency_audit(self):
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("ruff==0.16.10", workflow)
        self.assertIn("pip-audit==2.10.1", workflow)
        self.assertIn("ruff check tools app", workflow)
        self.assertIn(
            "pip-audit -r tools/requirements.lock --disable-pip",
            workflow,
        )
        self.assertIn(
            "pip-audit -r app/requirements.lock --disable-pip",
            workflow,
        )

    def test_ci_covers_cross_review_downstream_e2e_modules(self):
        selection = select_tests(
            ["tools/ccfa/cross_review.py"],
            suite="tools",
        )
        expected = (
            "tools.tests.test_automation_e2e",
            "tools.tests.test_evidence_integrity_e2e",
        )
        for module in expected:
            with self.subTest(module=module):
                self.assertIn(module, selection.tests)

    def test_ci_uses_impact_selection_and_scheduled_full_regression(self):
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("schedule:", workflow)
        self.assertIn("--base \"${{ github.event.pull_request.base.sha }}\"", workflow)
        self.assertIn("${{ github.event.before }}", workflow)
        self.assertIn("scripts/test-impact.ps1 run --suite tools --full", workflow)
        self.assertIn("scripts/test-impact.ps1 run --suite app --full", workflow)

    def test_ci_change_log_check_is_fail_closed(self):
        if (ROOT / ".public-mirror").is_file():
            self.skipTest(
                "the public mirror intentionally drops the private change-log gate"
            )

        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("Check workflow change log", workflow)
        self.assertIn("ccfa.change_log check", workflow)
        self.assertIn("github.event.pull_request.base.sha", workflow)
        self.assertIn("github.event.before", workflow)

    def test_ci_compile_list_has_valid_line_continuations(self):
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8"
        )
        payload = yaml.safe_load(workflow)
        step = next(
            item
            for item in payload["jobs"]["tools-impact"]["steps"]
            if item.get("name") == "Compile core modules"
        )
        lines = [
            line.strip()
            for line in step["run"].splitlines()
            if line.strip().startswith("tools/")
        ]
        self.assertTrue(lines)
        for line in lines[:-1]:
            self.assertTrue(
                line.endswith("`"),
                f"缺少 PowerShell 续行符: {line}",
            )
        self.assertFalse(lines[-1].endswith("`"))

    def test_ci_compile_list_paths_exist(self):
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8"
        )
        payload = yaml.safe_load(workflow)
        step = next(
            item
            for item in payload["jobs"]["tools-impact"]["steps"]
            if item.get("name") == "Compile core modules"
        )
        listed = [
            line.strip().rstrip("`").strip()
            for line in step["run"].splitlines()
            if line.strip().startswith("tools/")
            and line.strip().rstrip("`").strip().endswith(".py")
        ]
        self.assertTrue(listed)
        missing = [path for path in listed if not (ROOT / path).is_file()]
        self.assertEqual(
            missing,
            [],
            "tests.yml 的 py_compile 列表引用了不存在的模块；"
            "新增或改名模块时必须在同一个提交里更新列表与文件",
        )

    def test_actions_use_current_node24_compatible_majors(self):
        workflow_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                ROOT / ".github" / "workflows"
            ).glob("*.yml")
        )

        self.assertNotIn("actions/checkout@v4", workflow_text)
        self.assertNotIn("actions/setup-python@v5", workflow_text)
        self.assertNotIn("actions/upload-artifact@v4", workflow_text)

    def test_paper_workflows_separate_engineering_and_human_gates(self):
        workflows = [ROOT / ".github" / "workflows" / "paper-check.yml"]
        if PAPER_ROOT.is_dir():
            workflows.append(
                PAPER_ROOT / ".github" / "workflows" / "paper-check.yml"
            )

        for path in workflows:
            with self.subTest(path=path):
                payload = yaml.safe_load(path.read_text(encoding="utf-8"))
                deterministic = _job_run_text(
                    payload,
                    "deterministic-paper-checks",
                )
                human = _job_run_text(
                    payload,
                    "readiness-and-human-review",
                )

                self.assertIn("ccfa.citation_guard", deterministic)
                self.assertIn("ccfa.trace_claims", deterministic)
                self.assertIn("ccfa.final_check", deterministic)
                self.assertIn("ccfa.run_log", deterministic)
                self.assertIn("ccfa.formal_check", deterministic)
                self.assertNotIn("ccfa.readiness", deterministic)
                self.assertNotIn("ccfa.governance", deterministic)
                self.assertNotIn("ccfa.argument_audit", deterministic)
                self.assertNotIn("ccfa.cross_review", deterministic)

                self.assertIn("ccfa.readiness", human)
                self.assertIn("ccfa.governance", human)
                self.assertIn("ccfa.argument_audit", human)
                self.assertIn("ccfa.cross_review", human)
                self.assertGreaterEqual(
                    len(
                        _informational_gate_steps(
                            payload,
                            "readiness-and-human-review",
                        )
                    ),
                    4,
                )

    def test_paper_deterministic_gates_match_across_windows_and_linux(self):
        if not PAPER_ROOT.is_dir():
            self.skipTest("independent paper repository is not checked out")

        workflow_path = PAPER_ROOT / ".github" / "workflows" / "paper-check.yml"
        script_path = PAPER_ROOT / ".github" / "scripts" / "deterministic-gates.sh"
        self.assertTrue(
            script_path.is_file(),
            "paper CI 缺少跨平台 deterministic gate 脚本",
        )

        payload = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        self.assertIn("deterministic-paper-checks-linux", payload["jobs"])
        linux_job = _job_run_text(
            payload,
            "deterministic-paper-checks-linux",
        )
        self.assertIn("deterministic-gates.sh", linux_job)

        # The same tools must run on both runners; a tool added to only one side
        # would make the Linux job a weaker check than the Windows job.
        pattern = re.compile(r"ccfa\.[a-z_]+")
        windows_tools = set(
            pattern.findall(
                _job_run_text(payload, "deterministic-paper-checks")
            )
        )
        linux_tools = set(pattern.findall(script_path.read_text(encoding="utf-8")))

        self.assertEqual(
            windows_tools,
            linux_tools,
            "Windows 与 Linux 的确定性 gate 工具集必须完全一致",
        )
        self.assertIn("ccfa.citation_guard", windows_tools)
        self.assertIn("ccfa.formal_check", windows_tools)

    def test_submission_gate_is_fail_closed(self):
        if not PAPER_ROOT.is_dir():
            self.skipTest("independent paper repository is not checked out")

        workflow = (
            PAPER_ROOT / ".github" / "workflows" / "submission-gate.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("tags:", workflow)
        self.assertIn("--profile high-assurance", workflow)
        self.assertIn("ccfa.governance", workflow)
        self.assertIn("ccfa.argument_audit", workflow)
        self.assertIn("--strict-cross-family", workflow)
        self.assertIn("ccfa.repro_package", workflow)
        self.assertIn("ccfa.formal_check", workflow)
        self.assertNotIn("continue-on-error", workflow)

    def test_main_paper_commands_are_parseable(self):
        workflow = ROOT / ".github" / "workflows" / "paper-check.yml"
        commands = _workflow_run_commands(workflow)
        self.assertTrue(commands)

        with tempfile.TemporaryDirectory() as temporary:
            paper = Path(temporary) / "paper"
            paper.mkdir()
            (paper / "ccfa.yaml").write_text(
                "version: '0.4.0'\n",
                encoding="utf-8",
            )
            for command in commands:
                rendered = command.replace("_paper", str(paper))
                result = _run_workflow_command(rendered, cwd=ROOT)
                _assert_no_argparse_failure(self, result, command)

    def test_paper_repository_commands_are_parseable(self):
        if not PAPER_ROOT.is_dir():
            self.skipTest("independent paper repository is not checked out")

        workflow = PAPER_ROOT / ".github" / "workflows" / "paper-check.yml"
        commands = _workflow_run_commands(workflow)
        self.assertTrue(commands)

        with tempfile.TemporaryDirectory() as temporary:
            paper = Path(temporary)
            (paper / "ccfa.yaml").write_text(
                "version: '0.4.0'\n",
                encoding="utf-8",
            )
            for command in commands:
                result = _run_workflow_command(command, cwd=paper)
                _assert_no_argparse_failure(self, result, command)


if __name__ == "__main__":
    unittest.main()
