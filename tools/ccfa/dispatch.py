"""Portable `ccfa <module> ...` console-script dispatcher."""

from __future__ import annotations

import importlib
import pkgutil
import sys


def _module_names() -> list[str]:
    import ccfa

    names = []
    for module in pkgutil.iter_modules(ccfa.__path__):
        if module.name.startswith("_") or module.name in {
            "dispatch",
        }:
            continue
        names.append(module.name)
    return sorted(names)


def run(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print("usage: ccfa <module> [args...]")
        print("       ccfa list")
        return 0
    if argv[0] in {"list", "modules"}:
        for name in _module_names():
            print(name)
        return 0
    if argv[0] in {"-V", "--version", "version"}:
        print("ccfa-research-workflow 0.1.0")
        return 0
    module_name = argv[0].replace("-", "_")
    try:
        module = importlib.import_module(f"ccfa.{module_name}")
    except ImportError:
        print(f"unknown ccfa module: {argv[0]}", file=sys.stderr)
        return 2
    entry = getattr(module, "main", None)
    if not callable(entry):
        print(f"module {module_name} has no main()", file=sys.stderr)
        return 2
    try:
        return int(entry([f"ccfa-{module_name}", *argv[1:]]) or 0)
    except SystemExit as exc:
        return int(exc.code or 0)


if __name__ == "__main__":
    raise SystemExit(run())
