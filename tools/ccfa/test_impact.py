"""Select the smallest relevant test set for a code change.

The selector is intentionally conservative: a changed path is mapped to one
or more test modules only when that relationship is explicit. Anything
unknown, or any change to a shared contract module, falls back to the full
suite instead of silently skipping coverage.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

from ccfa.cli import tool_error


REPO_ROOT = Path(__file__).resolve().parents[2]


class Selection(NamedTuple):
    suite: str
    changed: tuple[str, ...]
    tests: tuple[str, ...]
    full: bool
    unknown: tuple[str, ...]
    reason: str

    def as_dict(self) -> dict:
        return {
            "suite": self.suite,
            "changed": list(self.changed),
            "tests": list(self.tests),
            "full": self.full,
            "unknown": list(self.unknown),
            "reason": self.reason,
        }


_TOOLS_FULL_PATHS = {
    "tools/ccfa/__init__.py",
    "tools/ccfa/cli.py",
    "tools/ccfa/stages.py",
    "tools/requirements.txt",
}

_TOOLS_EXACT = {
    "tools/ccfa/experiment_loop.py": (
        "tools.tests.test_docs_consistency",
        "tools.tests.test_experiment_loop",
        "tools.tests.test_readiness",
    ),
    "tools/ccfa/post_submission.py": (
        "tools.tests.test_docs_consistency",
        "tools.tests.test_post_submission",
        "tools.tests.test_readiness",
    ),
    "tools/ccfa/rigor.py": (
        "tools.tests.test_docs_consistency",
        "tools.tests.test_readiness",
        "tools.tests.test_rigor",
    ),
    "tools/ccfa/proof_orchestrator.py": (
        "tools.tests.test_docs_consistency",
        "tools.tests.test_proof_orchestrator",
        "tools.tests.test_readiness",
    ),
    "tools/ccfa/proof_run.py": (
        "tools.tests.test_docs_consistency",
        "tools.tests.test_proof_run",
    ),
    "tools/ccfa/meta_optimize.py": (
        "tools.tests.test_docs_consistency",
        "tools.tests.test_meta_optimize",
    ),
    "tools/ccfa/artifact_badge.py": (
        "tools.tests.test_artifact_badge",
        "tools.tests.test_docs_consistency",
        "tools.tests.test_readiness",
    ),
    "tools/ccfa/research_wiki.py": (
        "tools.tests.test_docs_consistency",
        "tools.tests.test_research_wiki",
    ),
    "tools/ccfa/research_state.py": (
        "tools.tests.test_docs_consistency",
        "tools.tests.test_research_state",
    ),
    "tools/ccfa/ara_compile.py": (
        "tools.tests.test_ara_compile",
        "tools.tests.test_docs_consistency",
    ),
    "tools/ccfa/run_ledger.py": (
        "tools.tests.test_docs_consistency",
        "tools.tests.test_run_ledger",
    ),
    "tools/ccfa/governance_map.py": (
        "tools.tests.test_docs_consistency",
        "tools.tests.test_governance_map",
    ),
    "tools/ccfa/artifact_store.py": (
        "tools.tests.test_artifact_store",
        "tools.tests.test_docs_consistency",
    ),
    "tools/ccfa/resubmit_pipeline.py": (
        "tools.tests.test_docs_consistency",
        "tools.tests.test_resubmit_pipeline",
    ),
    "tools/ccfa/talk_pipeline.py": (
        "tools.tests.test_docs_consistency",
        "tools.tests.test_talk_pipeline",
    ),
    "tools/ccfa/passport_ledger.py": (
        "tools.tests.test_docs_consistency",
        "tools.tests.test_passport_ledger",
    ),
    "tools/ccfa/citation_calibration.py": (
        "tools.tests.test_citation_calibration",
        "tools.tests.test_docs_consistency",
    ),
    "tools/ccfa/venue_fixtures.py": (
        "tools.tests.test_docs_consistency",
        "tools.tests.test_venue_fixtures",
    ),
    "tools/ccfa/session_replay.py": (
        "tools.tests.test_docs_consistency",
        "tools.tests.test_session_replay",
    ),
    "tools/ccfa/reference_audit.py": (
        "tools.tests.test_docs_consistency",
        "tools.tests.test_reference_audit",
    ),
    "tools/ccfa/dashboard.py": (
        "tools.tests.test_dashboard",
        "tools.tests.test_docs_consistency",
        "tools.tests.test_readiness",
    ),
    "tools/ccfa/cross_review.py": (
        "tools.tests.test_automation_e2e",
        "tools.tests.test_cross_review",
        "tools.tests.test_evidence_integrity_e2e",
        "tools.tests.test_readiness",
    ),
    "tools/ccfa/review_loop.py": (
        "tools.tests.test_docs_consistency",
        "tools.tests.test_review_loop",
    ),
    "tools/ccfa/test_impact.py": (
        "tools.tests.test_test_impact",
        "tools.tests.test_scripts",
        "tools.tests.test_github_workflows",
        "tools.tests.test_docs_consistency",
    ),
    "tools/newpaper/create.py": (
        "tools.tests.test_create",
        "tools.tests.test_docs_consistency",
        "tools.tests.test_scripts",
    ),
    "tools/newpaper/checklists.py": (
        "tools.tests.test_checklists",
        "tools.tests.test_docs_consistency",
    ),
    "ccfa.yaml.template": (
        "tools.tests.test_create",
        "tools.tests.test_state",
        "tools.tests.test_validate",
    ),
}


_APP_EXACT = {
    "app/ccfa_core/http_tools.py": (
        "app.tests.test_chat_panel",
        "app.tests.test_http_tools",
    ),
    "app/ccfa_core/settings.py": (
        "app.tests.test_chat_panel",
        "app.tests.test_settings",
    ),
    "app/ccfa_core/secrets.py": (
        "app.tests.test_secrets",
        "app.tests.test_settings",
    ),
    "app/ccfa_core/projects.py": (
        "app.tests.test_projects",
        "app.tests.test_workbench_e2e",
    ),
    "app/ccfa_core/checks.py": (
        "app.tests.test_checks",
        "app.tests.test_workbench_e2e",
    ),
    "app/ccfa_core/tools_bridge.py": (
        "app.tests.test_chat_panel",
        "app.tests.test_tools_bridge",
        "app.tests.test_workbench_e2e",
    ),
    "app/ccfa_core/engines/base.py": (
        "app.tests.test_engine_codex",
        "app.tests.test_engine_openai",
    ),
    "app/ccfa_core/engines/codex_exec.py": (
        "app.tests.test_chat_e2e",
        "app.tests.test_engine_codex",
    ),
    "app/ccfa_core/engines/openai_compat.py": (
        "app.tests.test_chat_e2e",
        "app.tests.test_engine_openai",
    ),
    "app/requirements.txt": (),
}


def _normalize_path(path: str) -> str:
    normalized = str(path).replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _module_from_test_path(path: str) -> str | None:
    name = Path(path).name
    if not path.endswith(".py") or not name.startswith("test_"):
        return None
    return path[:-3].replace("/", ".")


def _ccfa_module_tests(path: str) -> tuple[str, ...] | None:
    if not path.startswith("tools/ccfa/") or not path.endswith(".py"):
        return None
    if not (REPO_ROOT / path).is_file():
        return None
    stem = Path(path).stem
    if stem in {"__init__", "cli", "stages"}:
        return None
    candidate = REPO_ROOT / "tools" / "tests" / f"test_{stem}.py"
    if not candidate.is_file():
        return None
    return (f"tools.tests.test_{stem}",)


def _select_tools(path: str) -> tuple[str, ...] | None:
    if path.startswith("app/") or path.startswith("papers/"):
        return ()
    if path.startswith("tools/") and not (REPO_ROOT / path).is_file():
        return None
    if path in _TOOLS_FULL_PATHS:
        return None
    if path in _TOOLS_EXACT:
        return _TOOLS_EXACT[path]
    if path.startswith("tools/tests/"):
        if not (REPO_ROOT / path).is_file():
            return None
        module = _module_from_test_path(path)
        return (module,) if module else None
    if path.startswith("tools/ccfa/"):
        return _ccfa_module_tests(path)
    if path.startswith("tools/"):
        return None
    if path.startswith("scripts/"):
        return ("tools.tests.test_scripts",)
    if path.startswith(".github/"):
        return ("tools.tests.test_github_workflows",)
    if path == ".gitignore":
        return ("tools.tests.test_docs_consistency",)
    if path == "README.md" or path.startswith("docs/"):
        return ("tools.tests.test_docs_consistency",)
    if path.startswith("checklists/"):
        return (
            "tools.tests.test_checklists",
            "tools.tests.test_docs_consistency",
        )
    if path.startswith("automation/"):
        return ("tools.tests.test_automation_e2e",)
    if path.startswith("library/"):
        return ("tools.tests.test_library",)
    return None


def _select_app(path: str) -> tuple[str, ...] | None:
    if (
        path == "README.md"
        or path.startswith(
            (
                ".github/",
                "automation/",
                "checklists/",
                "docs/",
                "library/",
                "papers/",
                "scripts/",
                "tools/",
            )
        )
    ):
        return ()
    if path.startswith("app/") and not (REPO_ROOT / path).is_file():
        return None
    if path in _APP_EXACT:
        if path.endswith("requirements.txt"):
            return None
        return _APP_EXACT[path]
    if path.startswith("app/tests/"):
        if not (REPO_ROOT / path).is_file():
            return None
        module = _module_from_test_path(path)
        return (module,) if module else None
    if path.startswith("app/ccfa_gui/"):
        return (
            "app.tests.test_chat_panel",
            "app.tests.test_gui_smoke",
            "app.tests.test_workbench_e2e",
        )
    if path.startswith("app/"):
        return None
    return None


def select_tests(changed, *, suite: str) -> Selection:
    """Map changed repository-relative paths to test modules."""
    if suite not in {"tools", "app"}:
        raise ValueError(f"未知 test suite: {suite!r}")
    normalized = tuple(
        sorted(
            {
                _normalize_path(path)
                for path in changed
                if str(path).strip()
            }
        )
    )
    if not normalized:
        return Selection(suite, (), (), False, (), "no changes")

    selector = _select_tools if suite == "tools" else _select_app
    selected: set[str] = set()
    unknown: set[str] = set()
    for path in normalized:
        result = selector(path)
        if result is None:
            unknown.add(path)
        else:
            selected.update(result)
    if unknown:
        return Selection(
            suite,
            normalized,
            (),
            True,
            tuple(sorted(unknown)),
            "unknown paths require the full suite",
        )
    return Selection(
        suite,
        normalized,
        tuple(sorted(selected)),
        False,
        (),
        "impacted tests",
    )


def _git(repo_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-c", "core.quotePath=false", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise ValueError(f"无法运行 git: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ValueError(
            f"git {' '.join(args)} 失败 (exit {completed.returncode}): {detail}"
        )
    return completed.stdout


def collect_changed_paths(
    repo_root: Path,
    *,
    base: str | None = None,
    include_worktree: bool = True,
) -> tuple[str, ...]:
    """Collect committed diffs plus local tracked and untracked changes."""
    repo_root = Path(repo_root).resolve()
    paths: set[str] = set()
    if base:
        diff = _git(
            repo_root,
            "diff",
            "--name-only",
            "--diff-filter=ACMRTUXB",
            f"{base}...HEAD",
        )
        paths.update(line.strip() for line in diff.splitlines() if line.strip())
    if include_worktree:
        status = _git(
            repo_root,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        )
        for line in status.splitlines():
            if len(line) < 4:
                continue
            value = line[3:]
            if " -> " in value:
                old, new = value.split(" -> ", 1)
                paths.add(old.strip())
                paths.add(new.strip())
            else:
                paths.add(value.strip())
    return tuple(sorted(_normalize_path(path) for path in paths if path))


def build_run_command(
    repo_root: Path,
    selection: Selection,
) -> tuple[list[str], dict[str, str]]:
    """Build the unittest command and environment for a selection."""
    repo_root = Path(repo_root).resolve()
    if selection.suite == "tools":
        python = repo_root / "tools" / ".venv" / "Scripts" / "python.exe"
        python_path = str(repo_root / "tools")
        start_dir: Path | None = repo_root / "tools" / "tests"
        top_level: Path | None = repo_root / "tools"
    else:
        python = repo_root / "app" / ".venv" / "Scripts" / "python.exe"
        python_path = os.pathsep.join(
            (str(repo_root / "app"), str(repo_root / "tools"))
        )
        start_dir = repo_root / "app" / "tests"
        top_level = repo_root / "app"

    env = os.environ.copy()
    env["PYTHONPATH"] = python_path
    env["PYTHONUTF8"] = "1"
    if selection.suite == "app":
        env["QT_QPA_PLATFORM"] = "offscreen"

    if not selection.full and not selection.tests:
        return [], env
    if selection.full:
        command = [
            str(python),
            "-m",
            "unittest",
            "discover",
            "-s",
            str(start_dir.relative_to(repo_root)),
            "-t",
            str(top_level.relative_to(repo_root)),
        ]
    else:
        command = [str(python), "-m", "unittest", *selection.tests]
    return command, env


def run_selection(repo_root: Path, selection: Selection) -> int:
    command, env = build_run_command(repo_root, selection)
    if not command:
        print(
            json.dumps(selection.as_dict(), ensure_ascii=False),
            file=sys.stderr,
        )
        return 0
    print(json.dumps(selection.as_dict(), ensure_ascii=False), file=sys.stderr)
    completed = subprocess.run(
        command,
        cwd=str(Path(repo_root).resolve()),
        env=env,
        check=False,
    )
    return int(completed.returncode)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "按 git diff 选择最小相关测试集；未知路径或共享核心模块"
            "自动回退到全量测试。"
        )
    )
    parser.add_argument(
        "action",
        choices=("plan", "run"),
        default="plan",
        nargs="?",
    )
    parser.add_argument(
        "--suite",
        choices=("tools", "app"),
        default="tools",
    )
    parser.add_argument(
        "--base",
        help="git base ref（例如 origin/master）；本地工作树改动始终纳入",
    )
    parser.add_argument(
        "--no-worktree",
        action="store_true",
        help="只分析 base...HEAD，不包含当前未提交改动",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="跳过影响分析，强制全量测试",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    try:
        if args.full:
            selection = Selection(
                args.suite,
                (),
                (),
                True,
                (),
                "forced full suite",
            )
        else:
            changed = collect_changed_paths(
                repo_root,
                base=args.base,
                include_worktree=not args.no_worktree,
            )
            selection = select_tests(changed, suite=args.suite)
    except ValueError as exc:
        return tool_error(str(exc))

    if args.action == "plan":
        print(json.dumps(selection.as_dict(), ensure_ascii=False))
        return 0
    try:
        return run_selection(repo_root, selection)
    except OSError as exc:
        return tool_error(f"无法运行测试解释器: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
