"""Discover and load paper projects under papers/*/ccfa.yaml.

The workbench never imports ``ccfa``: the stage table comes from the workflow's
own ``ccfa.stages`` CLI, so the state machine stays owned by the workflow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from ccfa_core.workflow import WorkflowClient, WorkflowError


# Mirrors ``ccfa.milestones.parse_deadline``: an optional YYYY-MM-DD string.
# The format is a data contract, so a local check avoids a subprocess per
# project without reimplementing workflow semantics.
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
_STAGE_CACHE: dict[str, tuple[str, ...]] = {}
_GATE_CACHE: dict[tuple[str, str], dict] = {}


class ProjectError(ValueError):
    """Raised when a project state file is missing or invalid."""


def parse_deadline(value: object) -> date | None:
    """Parse an optional YYYY-MM-DD deadline."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"deadline 必须是 YYYY-MM-DD 日期字符串: {value!r}")
    text = value.strip()
    if not text:
        return None
    if _DATE_PATTERN.fullmatch(text) is None:
        raise ValueError(f"deadline 非法: {value!r}，应为 YYYY-MM-DD")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"deadline 不是合法日期: {value!r}") from exc


def deadline_note(deadline: str | None, *, today: date | None = None) -> str:
    """Return the short countdown a badge can hold: ``剩 9 天`` / ``已逾期 6 天``.

    The header badge row is already tight at narrow widths, so the badge shows
    the countdown and the caller keeps the absolute date in the tooltip.
    """

    parsed = parse_deadline(deadline)
    if parsed is None:
        return "无"
    reference = today or date.today()
    days = (parsed - reference).days
    if days < 0:
        return f"已逾期 {abs(days)} 天"
    if days == 0:
        return "今天截止"
    return f"剩 {days} 天"


def stages_for(mode: str, *, client: WorkflowClient | None = None) -> tuple[str, ...]:
    """Return the workflow's stage list for *mode*, cached per mode."""

    cached = _STAGE_CACHE.get(mode)
    if cached is not None:
        return cached
    try:
        payload = (client or WorkflowClient()).json("stages", ("--mode", mode))
    except WorkflowError as exc:
        raise ValueError(f"无法从工作流读取 stage 表: {exc}") from exc
    stages = payload.get("stages")
    if not isinstance(stages, list) or not all(
        isinstance(item, str) for item in stages
    ):
        raise ValueError(f"工作流返回的 stage 表非法: {mode!r}")
    _STAGE_CACHE[mode] = tuple(stages)
    return _STAGE_CACHE[mode]


def gate_for(
    mode: str,
    stage: str,
    *,
    client: WorkflowClient | None = None,
) -> dict:
    """Return ``{"id", "criterion"}`` for one stage, cached per stage."""

    key = (mode, stage)
    cached = _GATE_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        payload = (client or WorkflowClient()).json(
            "stages",
            ("--mode", mode, "--stage", stage),
        )
    except WorkflowError as exc:
        raise ValueError(f"无法从工作流读取 gate: {exc}") from exc
    gate = payload.get("gate")
    if not isinstance(gate, dict) or not isinstance(gate.get("id"), str):
        raise ValueError(f"工作流返回的 gate 非法: {mode!r}/{stage!r}")
    _GATE_CACHE[key] = gate
    return gate


@dataclass(frozen=True)
class ProjectRef:
    slug: str
    dir: Path
    error: str | None = None


def _gate_criterion(mode: str, stage: str) -> str:
    """The workflow's own criterion text for this stage's gate.

    Decorative: a workflow that cannot answer must not stop the project from
    loading, so a failure here yields an empty string (the readiness view
    reports real connectivity problems).
    """

    try:
        gate = gate_for(mode, stage)
    except ValueError:
        return ""
    criterion = gate.get("criterion")
    return criterion.strip() if isinstance(criterion, str) else ""


@dataclass(frozen=True)
class ProjectState:
    slug: str
    dir: Path
    mode: str
    current_stage: str
    gate: str
    deadline: str | None
    updated_at: str
    gate_criterion: str = ""


def _yaml_path(path: Path) -> tuple[Path, Path]:
    path = Path(path)
    if path.is_dir():
        yaml_path = path / "ccfa.yaml"
    elif path.name == "ccfa.yaml":
        yaml_path = path
    else:
        yaml_path = path / "ccfa.yaml"
    return yaml_path.parent, yaml_path


def load_project(path: Path) -> ProjectState:
    """Load one project state, validating mode/stage against ccfa.stages."""
    project_dir, yaml_path = _yaml_path(path)
    try:
        raw = yaml_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ProjectError(f"无法读取项目状态 {yaml_path}: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ProjectError(f"项目状态解析失败 {yaml_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProjectError(f"{yaml_path} 顶层必须是映射")

    venue = data.get("target_venue")
    if not isinstance(venue, dict):
        raise ProjectError(f"{yaml_path} 缺少 target_venue 映射")
    stage = data.get("stage")
    if not isinstance(stage, dict):
        raise ProjectError(f"{yaml_path} 缺少 stage 映射")

    mode = venue.get("mode")
    if not isinstance(mode, str) or not mode.strip():
        raise ProjectError(f"{yaml_path} 缺少 target_venue.mode")
    try:
        valid_stages = stages_for(mode)
    except ValueError as exc:
        raise ProjectError(f"{yaml_path} 的 mode 非法: {mode!r}: {exc}") from exc

    current_stage = stage.get("current")
    if not isinstance(current_stage, str) or not current_stage.strip():
        raise ProjectError(f"{yaml_path} 缺少 stage.current")
    if current_stage not in valid_stages:
        raise ProjectError(
            f"{yaml_path} 的 stage.current 非法: {current_stage!r}"
        )

    gate = stage.get("gate")
    if not isinstance(gate, str) or not gate.strip():
        raise ProjectError(f"{yaml_path} 缺少 stage.gate")
    updated_at = stage.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at.strip():
        raise ProjectError(f"{yaml_path} 缺少 stage.updated_at")

    deadline = venue.get("deadline")
    try:
        parse_deadline(deadline)
    except ValueError as exc:
        raise ProjectError(
            f"{yaml_path} 的 target_venue.deadline 非法: {exc}"
        ) from exc

    return ProjectState(
        slug=project_dir.name,
        dir=project_dir,
        mode=mode,
        current_stage=current_stage,
        gate=gate,
        deadline=deadline,
        updated_at=updated_at,
        gate_criterion=_gate_criterion(mode, current_stage),
    )


def find_projects(repo_root: Path) -> list[ProjectRef]:
    """Return one ref per papers/*/ccfa.yaml; bad entries carry an error."""
    papers = Path(repo_root) / "papers"
    if not papers.is_dir():
        return []

    refs: list[ProjectRef] = []
    project_dirs = sorted(
        (path for path in papers.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    )
    for project_dir in project_dirs:
        yaml_path = project_dir / "ccfa.yaml"
        if not yaml_path.is_file():
            continue
        try:
            load_project(yaml_path)
        except (ProjectError, OSError, ValueError) as exc:
            refs.append(
                ProjectRef(
                    slug=project_dir.name,
                    dir=project_dir,
                    error=str(exc),
                )
            )
        else:
            refs.append(ProjectRef(slug=project_dir.name, dir=project_dir))
    return refs
