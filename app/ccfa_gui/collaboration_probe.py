"""Probe one paper's collaboration state without blocking the event loop.

The workflow answers in about half a second, which is far too slow to run for
every project while the user waits, so each probe runs on the shared thread
pool and posts its result back to the GUI thread through a signal.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from ccfa_core.collaboration import (
    CollaborationError,
    CollaborationState,
    run_collaboration,
)


class _ProbeSignals(QObject):
    done = Signal(int, str, object)


class CollaborationProbe(QRunnable):
    """Run one probe; ``done`` carries (generation, slug, state)."""

    def __init__(self, generation: int, slug: str, project_dir) -> None:
        super().__init__()
        self.signals = _ProbeSignals()
        self._generation = int(generation)
        self._slug = str(slug)
        self._dir = Path(project_dir)

    def run(self) -> None:  # noqa: D102 - QRunnable entry point
        try:
            state: CollaborationState = run_collaboration(self._dir)
        except CollaborationError as exc:
            state = CollaborationState.unavailable(str(exc))
        self.signals.done.emit(self._generation, self._slug, state)
