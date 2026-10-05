"""Read one paper's git/GitHub collaboration state from the workflow.

The workbench does not decide what "dirty" or "collaboration-ready" means: it
asks ``ccfa.readiness --collaboration-only``, which reuses the full readiness
report's own git probe (including its rule that generated readiness reports do
not count as user changes).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ccfa_core.workflow import WorkflowClient, WorkflowError


class CollaborationError(RuntimeError):
    """Raised when the collaboration probe cannot run at all."""


@dataclass(frozen=True)
class CollaborationState:
    """The git facts the project list needs, plus the workflow's verdict."""

    present: bool
    dirty: bool | None
    commit: str | None
    remotes: tuple[str, ...]
    workflows_present: bool
    ready: bool
    blocking: tuple[str, ...] = ()
    error: str | None = None

    @property
    def warnings(self) -> tuple[str, ...]:
        """Short labels for the things worth putting in a one-line list row."""

        if not self.present:
            return ("非 git 仓库",)
        labels = []
        if self.dirty:
            labels.append("有未提交改动")
        if not self.remotes:
            labels.append("无 remote")
        if not self.workflows_present:
            labels.append("无 CI")
        return tuple(labels)

    @classmethod
    def unavailable(cls, message: str) -> "CollaborationState":
        """A probe that could not run at all, for the list's tooltip."""

        return cls(
            present=False,
            dirty=None,
            commit=None,
            remotes=(),
            workflows_present=False,
            ready=False,
            blocking=(),
            error=message,
        )


def _project_dir(project) -> Path:
    if isinstance(project, (str, Path)):
        path = Path(project)
        return path.parent if path.name == "ccfa.yaml" else path
    directory = getattr(project, "dir", None)
    if directory is None:
        raise CollaborationError("project 必须是 ProjectState 或项目目录")
    return Path(directory)


def _text(value) -> str | None:
    return value if isinstance(value, str) else None


def _flag(value) -> bool | None:
    return value if isinstance(value, bool) else None


def run_collaboration(
    project,
    *,
    client: WorkflowClient | None = None,
) -> CollaborationState:
    """Return the workflow's collaboration view of *project*."""

    project_dir = _project_dir(project)
    try:
        report = (client or WorkflowClient()).json(
            "readiness",
            ("--collaboration-only", "--paper-root", str(project_dir)),
        )
    except WorkflowError as exc:
        raise CollaborationError(f"协作状态检查失败：{exc}") from exc

    git = report.get("git")
    git = git if isinstance(git, dict) else {}
    remotes = git.get("remotes")
    return CollaborationState(
        present=bool(git.get("present")),
        dirty=_flag(git.get("dirty")),
        commit=_text(git.get("commit")),
        remotes=tuple(
            str(item) for item in remotes if isinstance(item, str)
        )
        if isinstance(remotes, list)
        else (),
        workflows_present=bool(git.get("workflows_present")),
        ready=bool(report.get("collaboration_ready")),
        blocking=tuple(
            str(item)
            for item in (
                report.get("blocking")
                if isinstance(report.get("blocking"), list)
                else []
            )
        ),
        error=_text(git.get("error")),
    )
