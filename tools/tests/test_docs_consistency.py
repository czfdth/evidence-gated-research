import ast
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from ccfa.milestones import checkpoints
from ccfa.stages import all_gates, stages_for
from newpaper.checklists import render_checklist


REPO_ROOT = Path(__file__).resolve().parents[2]
README_PATH = REPO_ROOT / "README.md"
WORKFLOW_GUIDE_PATH = REPO_ROOT / "docs" / "workflow-guide.md"
CCFA_DIR = REPO_ROOT / "tools" / "ccfa"

CLI_WRAPPERS = {
    "citation_guard": "scripts/citation-guard.ps1",
    "trace_claims": "scripts/trace-claims.ps1",
    "latex_check": "scripts/latex-check.ps1",
    "final_check": "scripts/final-check.ps1",
    "provenance": "scripts/provenance.ps1",
    "run_log": "scripts/run-log.ps1",
    "run_ledger": "scripts/run-ledger.ps1",
    "passport_ledger": "scripts/passport-ledger.ps1",
    "citation_calibration": "scripts/citation-calibration.ps1",
    "repro_package": "scripts/repro-package.ps1",
    "friction_log": "scripts/friction-log.ps1",
    "research_version": "scripts/research-version.ps1",
    "library": "scripts/library.ps1",
    "memory": "scripts/memory.ps1",
    "milestones": "scripts/milestones.ps1",
    "cross_review": "scripts/cross-review.ps1",
    "review_loop": "scripts/review-loop.ps1",
    "argument_audit": "scripts/argument-audit.ps1",
    "human_coding": "scripts/human-coding.ps1",
    "novelty": "scripts/novelty.ps1",
    "stats_plan": "scripts/statistics.ps1",
    "governance": "scripts/governance.ps1",
    "governance_map": "scripts/governance-map.ps1",
    "repro_env": "scripts/repro-env.ps1",
    "watch": "scripts/watch.ps1",
    "queue": "scripts/queue.ps1",
    "validate": "scripts/validate.ps1",
    "state": "scripts/state.ps1",
    "revision_ledger": "scripts/revision-ledger.ps1",
    "resubmit_pipeline": "scripts/resubmit-pipeline.ps1",
    "talk_pipeline": "scripts/talk-pipeline.ps1",
    "venue_fixtures": "scripts/venue-fixtures.ps1",
    "session_replay": "scripts/session-replay.ps1",
    "doctor": "scripts/doctor.ps1",
    "readiness": "scripts/readiness.ps1",
    "research_ledgers": "scripts/research-ledgers.ps1",
    "test_impact": "scripts/test-impact.ps1",
    "change_log": "scripts/change-log.ps1",
    "experiment_loop": "scripts/experiment-loop.ps1",
    "post_submission": "scripts/post-submission.ps1",
    "rigor": "scripts/rigor-rubric.ps1",
    "proof_orchestrator": "scripts/proof-orchestrator.ps1",
    "proof_run": "scripts/proof-run.ps1",
    "meta_optimize": "scripts/meta-optimize.ps1",
    "artifact_badge": "scripts/artifact-badge.ps1",
    "artifact_store": "scripts/artifact-store.ps1",
    "research_wiki": "scripts/research-wiki.ps1",
    "research_state": "scripts/research-state.ps1",
    "ara_compile": "scripts/ara-compile.ps1",
    "ara_extract": "scripts/ara-extract.ps1",
    "reference_audit": "scripts/reference-audit.ps1",
    "worktree_audit": "scripts/worktree-audit.ps1",
    "dashboard": "scripts/dashboard.ps1",
    "formal_check": "scripts/formal-check.ps1",
    "verifiers": "scripts/verifiers.ps1",
    "stages": "scripts/stages.ps1",
    "archive_client": "scripts/archive.ps1",
    "compute": "scripts/compute.ps1",
}
NEWPAPER_ENTRY = "tools/newpaper/create.py"
NEWPAPER_WRAPPER = "scripts/new-paper.ps1"

CHECKLISTS = {
    "conference": REPO_ROOT / "checklists" / "conference.md",
    "journal": REPO_ROOT / "checklists" / "journal.md",
}

REPO_PATH_PREFIXES = (
    "automation/",
    "checklists/",
    "library/",
    "scripts/",
    "tools/",
)
TOP_LEVEL_REPO_FILES = {
    "README.md",
    "ccfa.yaml.template",
}

# Generated paths that README may name as setup/runtime instructions but that
# intentionally do not exist in a fresh clone. Each prefix must be covered by
# .gitignore; the test below enforces that.
GENERATED_README_PATH_PREFIXES = (
    "tools/.venv",
    "app/.venv",
)


def _readme_text():
    return README_PATH.read_text(encoding="utf-8")


def _workflow_guide_text():
    return WORKFLOW_GUIDE_PATH.read_text(encoding="utf-8")


def _modules_with_main():
    modules = set()
    for module_path in CCFA_DIR.glob("*.py"):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "main"
            for node in tree.body
        ):
            modules.add(module_path.stem)
    return modules


def _repo_paths_from_readme(text):
    paths = []
    for token in re.findall(r"`([^`\n]+)`", text):
        raw = token.strip()
        if any(marker in raw for marker in "<>*{}"):
            continue
        if raw.startswith(("$", "~", "/", "..", "http://", "https://")):
            continue
        if re.match(r"^[A-Za-z]:[\\/]", raw):
            continue
        candidate = raw.rstrip("/")
        if "/" not in candidate and "\\" not in candidate:
            if candidate not in TOP_LEVEL_REPO_FILES:
                continue
        elif not candidate.startswith(REPO_PATH_PREFIXES):
            continue
        paths.append(candidate)
    return paths


def _is_generated_readme_path(path):
    return any(
        path == prefix or path.startswith(prefix + "/")
        for prefix in GENERATED_README_PATH_PREFIXES
    )


def _missing_readme_paths(paths):
    return [
        path
        for path in paths
        if not _is_generated_readme_path(path)
        and not (REPO_ROOT / path).exists()
    ]


def _assert_readme_paths_exist(paths):
    missing = _missing_readme_paths(paths)
    if missing:
        raise AssertionError(
            "README 路径不存在: " + ", ".join(missing)
        )


def _gitignore_patterns():
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    patterns = []
    for line in text.splitlines():
        pattern = line.strip()
        if not pattern or pattern.startswith("#") or pattern.startswith("!"):
            continue
        patterns.append(pattern.lstrip("/").rstrip("/"))
    return patterns


def _expected_checklist_bytes(mode, actual):
    # core.autocrlf=true may materialize repository LF blobs as CRLF. Compare
    # exact bytes under the checkout's newline convention.
    rendered = render_checklist(mode).encode("utf-8")
    if b"\r\n" in actual:
        return rendered.replace(b"\n", b"\r\n")
    return rendered


def _common_command_lines():
    match = re.search(
        r"常用命令：\s*```powershell\s*\n(.*?)```",
        _readme_text(),
        flags=re.DOTALL,
    )
    if match is None:
        return []
    return [
        line.strip()
        for line in match.group(1).splitlines()
        if line.strip().startswith("scripts/")
    ]


class TestReadmeInventory(unittest.TestCase):
    def test_every_ccfa_cli_module_is_named(self):
        readme = _readme_text()
        modules = _modules_with_main()
        self.assertEqual(modules, set(CLI_WRAPPERS))
        for module in modules:
            with self.subTest(module=module):
                self.assertIn(module, readme)

    def test_newpaper_entrypoint_is_named(self):
        readme = _readme_text()
        self.assertIn(NEWPAPER_ENTRY, readme)
        self.assertIn("newpaper.create", readme)

    def test_every_cli_has_a_documented_powershell_entry(self):
        readme = _readme_text()
        mapping = dict(CLI_WRAPPERS)
        mapping[NEWPAPER_ENTRY] = NEWPAPER_WRAPPER
        for module, wrapper in mapping.items():
            with self.subTest(module=module, wrapper=wrapper):
                self.assertIn(wrapper, readme)

    def test_repository_paths_named_in_readme_exist(self):
        paths = _repo_paths_from_readme(_readme_text())
        self.assertTrue(paths, "README 没有点名任何仓库内路径")
        for path in paths:
            if _is_generated_readme_path(path):
                continue
            with self.subTest(path=path):
                self.assertTrue((REPO_ROOT / path).exists(), f"README 路径不存在: {path}")

    def test_generated_readme_paths_are_gitignored(self):
        patterns = _gitignore_patterns()
        for prefix in GENERATED_README_PATH_PREFIXES:
            with self.subTest(prefix=prefix):
                self.assertTrue(
                    any(
                        prefix == pattern
                        or prefix.startswith(pattern + "/")
                        for pattern in patterns
                    ),
                    f"生成路径 {prefix} 未被 .gitignore 覆盖",
                )

    def test_generated_path_exemption_is_prefix_scoped(self):
        self.assertTrue(_is_generated_readme_path("tools/.venv"))
        self.assertTrue(
            _is_generated_readme_path("tools/.venv/Scripts/python.exe")
        )
        self.assertTrue(_is_generated_readme_path("app/.venv"))
        self.assertTrue(
            _is_generated_readme_path("app/.venv/Scripts/python.exe")
        )
        self.assertFalse(_is_generated_readme_path("tools/.venv-other"))
        self.assertFalse(_is_generated_readme_path("app/.venv-other"))
        self.assertFalse(
            _is_generated_readme_path("tools/ccfa/revision_ledger.py")
        )

    def test_nonexistent_committed_path_is_not_exempted(self):
        with self.assertRaises(AssertionError):
            _assert_readme_paths_exist(["tools/ccfa/does_not_exist.py"])


class TestReadmeWorkflowGuidance(unittest.TestCase):
    def test_readme_points_to_the_daily_workflow_guide(self):
        readme = _readme_text()
        self.assertIn("docs/workflow-guide.md", readme)
        self.assertIn(
            "读状态 -> 处理当前 gate -> 定向检查 -> 人工复核 -> 提交论文仓库 -> 推进阶段",
            readme,
        )

    def test_every_script_named_in_workflow_guide_exists(self):
        scripts = set(
            re.findall(
                r"scripts/[A-Za-z0-9-]+\.ps1",
                _workflow_guide_text(),
            )
        )
        self.assertTrue(scripts, "日常操作手册没有引用任何脚本")
        for script in scripts:
            with self.subTest(script=script):
                self.assertTrue(
                    (REPO_ROOT / script).is_file(),
                    f"日常操作手册引用了不存在的脚本: {script}",
                )

    def test_stage_to_command_quick_reference_is_present(self):
        readme = _readme_text()
        for command in (
            "milestones.ps1 due",
            "milestones.ps1 stage",
            "library.ps1",
            "memory.ps1",
            "run-log.ps1",
            "latex-check.ps1",
            "--main",
            "final-check.ps1",
        ):
            with self.subTest(command=command):
                self.assertIn(command, readme)

    def test_every_countdown_node_is_named_in_readme(self):
        readme = _readme_text()
        for node in checkpoints(date(2027, 1, 1)):
            with self.subTest(node=node):
                # A digit boundary keeps T-1 from matching inside T-14.
                self.assertRegex(readme, re.escape(node) + r"(?!\d)")

    def test_automation_pointer_and_silent_policy_are_present(self):
        readme = _readme_text()
        self.assertIn("automation/README.md", readme)
        for template in (
            "automation/weekly-watch.md",
            "automation/deadline-check.md",
            "automation/stage-advance.md",
            "automation/experiment-queue.md",
        ):
            with self.subTest(template=template):
                self.assertIn(template, readme)
        self.assertIn("没有实质变化就不通知", readme)
        self.assertIn("实际挂载需用户确认", readme)

    def test_venue_template_location_and_license_warning_are_present(self):
        readme = _readme_text()
        self.assertIn("$CODEX_HOME/skills/ccf-latex-templates", readme)
        self.assertIn("139", readme)
        self.assertIn("官方/社区下载", readme)
        self.assertIn("使用前自查许可与完整性", readme)
        self.assertIn("acl_natbib.bst", readme)
        self.assertIn("custom.bib", readme)


class TestReadmeCommonCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.paper_root = self.root / "paper"
        self.library_dir = self.root / "library"
        self.log_dir = self.root / "experiments" / "log"
        self.paper_root.mkdir()
        self.library_dir.mkdir()
        self.log_dir.mkdir(parents=True)

        (self.paper_root / "ccfa.yaml").write_text(
            "target_venue:\n"
            '  mode: "conference"\n'
            "  deadline: null\n"
            "stage:\n"
            '  current: "idea"\n'
            '  gate: "scope_defined"\n'
            '  updated_at: "2026-10-03"\n',
            encoding="utf-8",
        )
        (self.library_dir / "refs.bib").write_text(
            "@misc{demo, title={Demo}}\n",
            encoding="utf-8",
        )
        manuscript = self.paper_root / "manuscript"
        (manuscript / "sections").mkdir(parents=True)
        (manuscript / "sections" / "main.tex").write_text(
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "Demo\n"
            "\\end{document}\n",
            encoding="utf-8",
        )
        (manuscript / "references.bib").write_text("", encoding="utf-8")
        (self.paper_root / "submission").mkdir()
        (self.paper_root / "submission" / "final.pdf").write_bytes(b"%PDF-1.4\n")

    def _expand_tokens(self, tokens):
        replacements = {
            "<paper-root>": str(self.paper_root),
            "<library-dir>": str(self.library_dir),
            "<log-dir>": str(self.log_dir),
        }
        expanded = []
        for token in tokens:
            if token == "<command...>":
                expanded.extend([sys.executable, "-c", "print('ok')"])
                continue
            for placeholder, value in replacements.items():
                token = token.replace(placeholder, value)
            expanded.append(token)
        return expanded

    def test_common_commands_have_valid_argparse_shapes(self):
        lines = _common_command_lines()
        self.assertEqual(len(lines), 8, lines)
        wrapper_modules = {
            wrapper: module for module, wrapper in CLI_WRAPPERS.items()
        }
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT / "tools")

        for line in lines:
            with self.subTest(command=line):
                tokens = shlex.split(line)
                wrapper = tokens.pop(0)
                self.assertIn(wrapper, wrapper_modules)
                args = self._expand_tokens(tokens)
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        f"ccfa.{wrapper_modules[wrapper]}",
                        *args,
                    ],
                    cwd=str(REPO_ROOT),
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                )
                stderr = result.stderr.lower()
                self.assertIn(result.returncode, (0, 1, 2), result.stderr)
                self.assertNotIn("unrecognized arguments", stderr, result.stderr)
                self.assertNotIn(
                    "the following arguments are required",
                    stderr,
                    result.stderr,
                )


class TestChecklistRegeneration(unittest.TestCase):
    def test_conference_checklist_matches_fresh_render_byte_for_byte(self):
        path = CHECKLISTS["conference"]
        actual = path.read_bytes()
        self.assertEqual(
            actual,
            _expected_checklist_bytes("conference", actual),
            "conference.md 与 stages.py 的最新渲染不一致",
        )

    def test_journal_checklist_matches_fresh_render_byte_for_byte(self):
        path = CHECKLISTS["journal"]
        actual = path.read_bytes()
        self.assertEqual(
            actual,
            _expected_checklist_bytes("journal", actual),
            "journal.md 与 stages.py 的最新渲染不一致",
        )

    def test_checklist_stage_counts_and_gate_ids_match_stages(self):
        for mode in ("conference", "journal"):
            text = render_checklist(mode)
            pairs = all_gates(mode)
            with self.subTest(mode=mode, field="stage_count"):
                self.assertEqual(text.count("## "), len(stages_for(mode)))
            for index, (stage, gate) in enumerate(pairs, start=1):
                with self.subTest(mode=mode, stage=stage, gate=gate.id):
                    self.assertIn(f"## {index}. [{stage}]", text)
                    self.assertIn(f"- [ ] gate `{gate.id}`", text)


if __name__ == "__main__":
    unittest.main()
