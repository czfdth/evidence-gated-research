"""Shared helpers for the workbench app tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from ccfa_core.projects import gate_for

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = REPO_ROOT / "ccfa.yaml.template"


def project_state(
    slug: str,
    mode: str = "conference",
    stage: str = "idea",
    deadline: str | None = None,
) -> dict:
    state = yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8"))
    state["project"]["title"] = slug
    state["project"]["short_name"] = slug
    state["target_venue"]["name"] = "NeurIPS"
    state["target_venue"]["year"] = "2027"
    state["target_venue"]["mode"] = mode
    state["target_venue"]["deadline"] = deadline
    state["stage"]["current"] = stage
    try:
        state["stage"]["gate"] = gate_for(mode, stage)["id"]
    except ValueError:
        state["stage"]["gate"] = "scope_defined"
    state["stage"]["updated_at"] = "2026-10-04"
    return state


def write_project(root, slug: str, **kwargs) -> Path:
    project_dir = Path(root) / "papers" / slug
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "ccfa.yaml").write_text(
        yaml.safe_dump(
            project_state(slug, **kwargs),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return project_dir


def create_project(papers_root, slug: str, **kwargs) -> Path:
    """Scaffold a real project through the workflow's own CLI.

    Mirrors ``tools/newpaper/create.py`` without importing it: the workbench
    only ever talks to the workflow through its console entry points.
    """

    from ccfa_core.workflow import WorkflowClient, WorkflowError

    args = [
        slug,
        "--venue",
        str(kwargs.get("venue", "NeurIPS")),
        "--year",
        str(kwargs.get("year", "2027")),
        "--mode",
        str(kwargs.get("mode", "conference")),
        "--papers-root",
        str(papers_root),
    ]
    if kwargs.get("title"):
        args += ["--title", str(kwargs["title"])]
    if kwargs.get("deadline"):
        args += ["--deadline", str(kwargs["deadline"])]

    result = WorkflowClient().run("newpaper.create", args)
    if result.exit_code != 0:
        raise WorkflowError(
            "newpaper.create 失败"
            f"（exit {result.exit_code}）：{result.stderr.strip()[:200]}"
        )
    first_line = result.stdout.strip().splitlines()
    target = Path(first_line[0]) if first_line else Path()
    if not target.is_dir():
        raise WorkflowError(
            f"newpaper.create 未返回项目目录：{result.stdout[:120]!r}"
        )
    return target
