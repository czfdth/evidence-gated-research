"""Locate executables installed by ``tools/install/fetch_toolchain.py``.

Portable tools land under a tools root with a single shim directory at
``<tools root>/bin``. Relying on the user PATH alone is fragile: a process
started before the PATH edit (the desktop app, a CI runner, a long-lived shell)
keeps the stale environment and reports installed tools as missing.
:func:`which` prefers ``PATH`` but falls back to the shim directory, so the
preflight reflects what is actually installed.

The root can be relocated because the system drive fills up. A one-line pointer
at ``%LOCALAPPDATA%\\codex-tools-location`` records the chosen root, so a
process that started before the ``CODEX_TOOLS_DIR`` change still resolves it.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


_POINTER_NAME = "codex-tools-location"


def _base_dir() -> Path | None:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    return Path(base) if base else None


def pointer_file() -> Path | None:
    base = _base_dir()
    return base / _POINTER_NAME if base else None


def write_pointer(root: Path) -> Path | None:
    """Record *root* so later processes find it without an environment edit."""
    pointer = pointer_file()
    if pointer is None:
        return None
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(str(Path(root)) + "\n", encoding="utf-8")
    return pointer


def tools_dir() -> Path:
    """Return the portable toolchain root, honouring a relocation pointer."""
    override = os.environ.get("CODEX_TOOLS_DIR")
    if override:
        return Path(override)
    base = _base_dir()
    candidate = (base / "codex-tools") if base else (Path.home() / ".codex-tools")
    pointer = pointer_file()
    if pointer is not None:
        try:
            if pointer.is_file():
                recorded = pointer.read_text(encoding="utf-8").strip()
                if recorded:
                    return Path(recorded)
        except OSError:
            pass
    return candidate


def shim_dir() -> Path:
    return tools_dir() / "bin"


def which(name: str) -> str | None:
    """Resolve *name*, falling back to the portable shim directory."""
    found = shutil.which(name)
    if found:
        return found
    shims = shim_dir()
    if not shims.is_dir():
        return None
    candidates = [shims / name]
    if sys.platform == "win32" and not Path(name).suffix:
        for suffix in (".cmd", ".bat", ".exe"):
            candidates.append(shims / f"{name}{suffix}")
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None
