"""Parity between scripts/*.ps1 and the portable `ccfa` dispatcher.

Portability is a contract, not a claim: every PowerShell wrapper must either
have a cross-platform command of the same name, or be declared platform-specific
with a reason. The check fails closed so a new wrapper cannot quietly land
without a portable path.
"""

import ast
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from ccfa import dispatch


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
TOOLS_DIR = REPO_ROOT / "tools"
# Only the workflow's own tool modules count. Platform-specific wrappers may
# legitimately run `python -m pip` or `python -m unittest`; those are not tools
# that need a portable command.
_MODULE_CALL = re.compile(
    r"-m\s+((?:ccfa|newpaper|install)\.[A-Za-z0-9_.]+)"
)


def _wrapper_module(path: Path) -> str | None:
    match = _MODULE_CALL.search(path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _module_path(module_name: str) -> Path:
    parts = module_name.split(".")
    return TOOLS_DIR.joinpath(*parts[:-1]) / f"{parts[-1]}.py"


def _defines_main(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "main"
        for node in tree.body
    )


class DispatchParityTests(unittest.TestCase):
    def test_every_wrapper_is_portable_or_declared_platform_specific(self):
        wrappers = {path.stem for path in SCRIPTS_DIR.glob("*.ps1")}
        covered = set(dispatch.COMMANDS) | set(dispatch.PLATFORM_SPECIFIC_COMMANDS)

        # Hard direction: a wrapper with neither a portable command nor an
        # explicit Windows-only declaration would quietly reintroduce the
        # PowerShell-only coupling this module exists to remove.
        self.assertEqual(
            sorted(wrappers - covered),
            [],
            "包装器既没有跨平台命令，也没有平台专用声明",
        )
        # A dispatched command must point at a wrapper that actually exists.
        self.assertEqual(
            sorted(set(dispatch.COMMANDS) - wrappers),
            [],
            "dispatcher 声明了不存在的包装器",
        )

    def test_wrapper_command_maps_to_the_same_module_it_runs(self):
        for path in sorted(SCRIPTS_DIR.glob("*.ps1")):
            with self.subTest(wrapper=path.name):
                if path.stem in dispatch.PLATFORM_SPECIFIC_COMMANDS:
                    self.assertIsNone(
                        _wrapper_module(path),
                        f"{path.name} 被声明为平台专用，却调用了 python -m",
                    )
                    continue
                module = _wrapper_module(path)
                self.assertIsNotNone(module, f"{path.name} 没有 python -m 调用")
                self.assertEqual(dispatch.COMMANDS[path.stem], module)

    def test_every_command_reaches_a_module_that_defines_main(self):
        for command, module_name in sorted(dispatch.COMMANDS.items()):
            with self.subTest(command=command):
                path = _module_path(module_name)
                self.assertTrue(path.is_file(), f"{module_name} 不存在: {path}")
                self.assertTrue(
                    _defines_main(path),
                    f"{module_name} 没有顶层 main()",
                )

    def test_resolve_accepts_dash_and_underscore_spelling(self):
        self.assertEqual(dispatch.resolve("post-submission"), "ccfa.post_submission")
        self.assertEqual(dispatch.resolve("post_submission"), "ccfa.post_submission")
        self.assertEqual(dispatch.resolve("statistics"), "ccfa.stats_plan")
        self.assertIsNone(dispatch.resolve("not-a-command"))


class DispatchRuntimeTests(unittest.TestCase):
    def _env(self) -> dict:
        existing = os.environ.get("PYTHONPATH", "")
        pythonpath = str(TOOLS_DIR) + (os.pathsep + existing if existing else "")
        return {**os.environ, "PYTHONPATH": pythonpath}

    def test_module_entry_point_lists_commands_without_powershell(self):
        completed = subprocess.run(
            [sys.executable, "-m", "ccfa", "list"],
            cwd=str(REPO_ROOT),
            env=self._env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        listed = completed.stdout.splitlines()
        self.assertIn("readiness", listed)
        self.assertIn("statistics", listed)
        self.assertEqual(len(listed), len(dispatch.COMMANDS))

    def test_module_entry_point_runs_a_real_tool(self):
        completed = subprocess.run(
            [sys.executable, "-m", "ccfa", "stages", "--help"],
            cwd=str(REPO_ROOT),
            env=self._env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_unknown_command_exits_two(self):
        completed = subprocess.run(
            [sys.executable, "-m", "ccfa", "definitely-not-a-tool"],
            cwd=str(REPO_ROOT),
            env=self._env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("unknown ccfa command", completed.stderr)


if __name__ == "__main__":
    unittest.main()
