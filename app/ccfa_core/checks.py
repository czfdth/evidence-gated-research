"""Run the workflow's deterministic checks through its CLI.

No tool logic is duplicated here: each check shells out to the workflow's own
console entry point and reads the JSON report it already promises.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ccfa_core.workflow import WorkflowClient, WorkflowError


class CheckError(RuntimeError):
    """Raised when a deterministic check cannot run."""


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    problems: tuple[object, ...] = ()
    report: dict | None = None


def _project_dir(project) -> Path:
    if isinstance(project, (str, Path)):
        path = Path(project)
        return path.parent if path.name == "ccfa.yaml" else path
    directory = getattr(project, "dir", None)
    if directory is None:
        raise CheckError("project 必须是 ProjectState、ProjectRef 或项目目录")
    return Path(directory)


def _run(client: WorkflowClient, module: str, args: tuple, label: str) -> dict:
    try:
        return client.json(module, args)
    except WorkflowError as exc:
        raise CheckError(f"{label} 失败：{exc}") from exc


def run_validate(project, *, client: WorkflowClient | None = None) -> CheckResult:
    """Run the workflow's ``ccfa.validate`` against the project state."""
    project_dir = _project_dir(project)
    yaml_path = project_dir / "ccfa.yaml"
    if not yaml_path.is_file():
        raise CheckError(f"validate 失败：找不到 {yaml_path}")
    report = _run(
        client or WorkflowClient(),
        "validate",
        (str(yaml_path),),
        "validate",
    )
    problems = tuple(
        str(item.get("message", ""))
        for item in report.get("problems", [])
        if isinstance(item, dict)
    )
    return CheckResult(
        name="validate",
        ok=not problems,
        problems=problems,
        report=report,
    )


def run_milestones_due(
    project,
    today=None,
    *,
    client: WorkflowClient | None = None,
) -> CheckResult:
    """Run the workflow's ``ccfa.milestones due`` and keep its report."""
    project_dir = _project_dir(project)
    if today is None:
        today = date.today()
    elif isinstance(today, str):
        try:
            today = date.fromisoformat(today)
        except ValueError as exc:
            raise CheckError(f"today 非法: {today!r}: {exc}") from exc
    if not isinstance(today, date):
        raise CheckError("today 必须是 datetime.date 或 ISO 日期字符串")
    report = _run(
        client or WorkflowClient(),
        "milestones",
        (
            "due",
            "--paper-root",
            str(project_dir),
            "--today",
            today.isoformat(),
        ),
        "milestones due",
    )
    problems = tuple(report.get("problems", []))
    return CheckResult(
        name="milestones-due",
        ok=not problems,
        problems=problems,
        report=report,
    )
