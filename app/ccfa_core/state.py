"""Write stage transitions back through the workflow's ``ccfa.state`` CLI.

The workbench never edits ``ccfa.yaml`` itself. A stage change is a workflow
operation with an audit trail (``stage.history``), so it goes through
``ccfa.state`` like every other command: the app only supplies the reason and
the explicit confirmation the workflow demands, and then re-reads the project
so the header shows what the workflow actually wrote.
"""

from __future__ import annotations

from pathlib import Path

from ccfa_core.workflow import WorkflowClient, WorkflowError


class StageTransitionError(RuntimeError):
    """Raised when a stage transition could not be performed."""


def _project_dir(project) -> Path:
    if isinstance(project, (str, Path)):
        path = Path(project)
        return path.parent if path.name == "ccfa.yaml" else path
    directory = getattr(project, "dir", None)
    if directory is None:
        raise StageTransitionError("project 必须是 ProjectState 或项目目录")
    return Path(directory)


def advance_targets(current: str, stages) -> tuple[str, ...]:
    """Return the stages strictly after *current*, in workflow order."""

    ordered = tuple(stages)
    if current not in ordered:
        return ()
    return ordered[ordered.index(current) + 1 :]


def rollback_targets(current: str, stages) -> tuple[str, ...]:
    """Return the stages strictly before *current*, in workflow order."""

    ordered = tuple(stages)
    if current not in ordered:
        return ()
    return ordered[: ordered.index(current)]


def transition_targets(kind: str, current: str, stages) -> tuple[str, ...]:
    """Return the legal targets for *kind* ("advance" or "rollback")."""

    if kind == "advance":
        return advance_targets(current, stages)
    if kind == "rollback":
        return rollback_targets(current, stages)
    raise StageTransitionError(f"未知的流转类型: {kind!r}")


def _transition(
    project,
    kind: str,
    to: str,
    reason: str,
    void_artifacts,
    client: WorkflowClient | None,
) -> dict:
    if kind not in {"advance", "rollback"}:
        raise StageTransitionError(f"未知的流转类型: {kind!r}")
    if not isinstance(reason, str) or not reason.strip():
        # The workflow refuses an empty reason too; failing here keeps the
        # workbench from ever reaching it with a reason it cannot audit.
        raise StageTransitionError("流转原因必填")
    project_dir = _project_dir(project)
    args = [
        "--paper-root",
        str(project_dir),
        "set-stage" if kind == "advance" else "rollback",
        to,
        "--reason",
        reason.strip(),
        "--confirm",
    ]
    if kind == "rollback":
        for artifact in void_artifacts or ():
            text = str(artifact).strip()
            if text:
                args += ["--void-artifacts", text]
    try:
        return (client or WorkflowClient()).json("state", args)
    except WorkflowError as exc:
        label = "推进阶段" if kind == "advance" else "回退阶段"
        raise StageTransitionError(f"{label}失败：{exc}") from exc


def set_stage(
    project,
    *,
    to: str,
    reason: str,
    client: WorkflowClient | None = None,
) -> dict:
    """Advance the project to a later stage and return the history entry."""

    return _transition(project, "advance", to, reason, (), client)


def rollback_stage(
    project,
    *,
    to: str,
    reason: str,
    void_artifacts=(),
    client: WorkflowClient | None = None,
) -> dict:
    """Roll the project back to an earlier stage, voiding named artifacts."""

    return _transition(
        project,
        "rollback",
        to,
        reason,
        void_artifacts,
        client,
    )
