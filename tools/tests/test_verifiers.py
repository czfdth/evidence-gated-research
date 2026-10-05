import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccfa import verifiers
from ccfa.verifiers import (
    FORMAL_ENGINES,
    TIER_CORE,
    Engine,
    collect_problems,
    inventory,
    main,
    probe_engine,
    status_lines,
    wired_engines,
)


class ProbeEngineTests(unittest.TestCase):
    def test_executable_on_path_is_available(self):
        engine = Engine(
            key="lean",
            kind="proof-assistant",
            capability="proofs",
            executables=("lean",),
        )

        status = probe_engine(
            engine,
            which=lambda name: "/opt/lean" if name == "lean" else None,
            module_probe=lambda name: None,
        )

        self.assertTrue(status.available)
        self.assertEqual(status.location, "/opt/lean")
        self.assertIn("lean", status.detail)

    def test_python_module_is_available(self):
        engine = Engine(
            key="z3",
            kind="SMT",
            capability="smt",
            python_module="z3",
            tier=TIER_CORE,
        )

        status = probe_engine(
            engine,
            which=lambda name: None,
            module_probe=lambda name: "5.1.0",
        )

        self.assertTrue(status.available)
        self.assertEqual(status.location, "python:z3")
        self.assertIn("5.1.0", status.detail)

    def test_missing_engine_is_reported(self):
        engine = Engine(key="coq", kind="proof-assistant", capability="proofs")

        status = probe_engine(
            engine,
            which=lambda name: None,
            module_probe=lambda name: None,
        )

        self.assertFalse(status.available)
        self.assertIsNone(status.location)

    def test_wsl_probe_is_used_when_native_tools_are_absent(self):
        engine = Engine(
            key="agda",
            kind="proof-assistant",
            capability="proofs",
            wsl_probe="agda --version",
        )
        seen = []

        def wsl(command):
            seen.append(command)
            return "Agda version 2.6.3 (WSL Ubuntu-24.04)"

        status = probe_engine(
            engine,
            which=lambda name: None,
            module_probe=lambda name: None,
            wsl_probe=wsl,
        )

        self.assertTrue(status.available)
        self.assertEqual(status.location, "wsl")
        self.assertIn("2.6.3", status.detail)
        self.assertEqual(seen, ["agda --version"])

    def test_wsl_probe_is_skipped_without_a_probe_callable(self):
        engine = Engine(
            key="agda",
            kind="proof-assistant",
            capability="proofs",
            wsl_probe="agda --version",
        )

        status = probe_engine(
            engine,
            which=lambda name: None,
            module_probe=lambda name: None,
        )

        self.assertFalse(status.available)

    def test_executable_is_preferred_over_module(self):
        engine = Engine(
            key="cvc5",
            kind="SMT",
            capability="smt",
            executables=("cvc5",),
            python_module="cvc5",
        )
        calls = []

        def module_probe(name):
            calls.append(name)
            return "1.3.1"

        status = probe_engine(
            engine,
            which=lambda name: "/usr/bin/cvc5",
            module_probe=module_probe,
        )

        self.assertTrue(status.available)
        self.assertEqual(status.location, "/usr/bin/cvc5")
        self.assertEqual(calls, [])

    def test_default_module_probe_reports_a_real_module(self):
        self.assertIsNotNone(verifiers._default_module_probe("yaml"))

    def test_default_module_probe_rejects_an_unknown_module(self):
        self.assertIsNone(
            verifiers._default_module_probe("no_such_module_zzz_123")
        )

    @unittest.skipUnless(
        verifiers.os.name == "nt",
        "extensionless launchers only need special handling on Windows",
    )
    def test_extensionless_launcher_is_found_on_path(self):
        with tempfile.TemporaryDirectory() as raw:
            bin_dir = Path(raw)
            launcher = bin_dir / "isabelle"
            launcher.write_text("#!/bin/sh\n", encoding="utf-8")
            with mock.patch.dict(
                os.environ, {"PATH": str(bin_dir)}, clear=False
            ), mock.patch.object(
                verifiers.shutil, "which", return_value=None
            ):
                resolved = verifiers._default_which("isabelle")

            self.assertEqual(resolved, str(launcher))


class InventoryTests(unittest.TestCase):
    def test_inventory_covers_every_registered_engine(self):
        statuses = inventory(
            which=lambda name: None,
            module_probe=lambda name: None,
        )

        self.assertEqual(len(statuses), len(FORMAL_ENGINES))
        self.assertTrue(all(not status.available for status in statuses))

    def test_registry_has_a_single_core_engine_and_unique_keys(self):
        keys = [engine.key for engine in FORMAL_ENGINES]
        self.assertEqual(len(keys), len(set(keys)))
        core = [engine.key for engine in FORMAL_ENGINES if engine.tier == TIER_CORE]
        self.assertEqual(core, ["z3"])

    def test_status_lines_mark_wired_engines(self):
        statuses = inventory(
            which=lambda name: None,
            module_probe=lambda name: None,
        )
        lines = status_lines(statuses, wired={"z3"})

        self.assertTrue(any("* z3" in line for line in lines))
        self.assertTrue(all("MISSING" in line for line in lines))


class CollectProblemsTests(unittest.TestCase):
    def _statuses(self):
        core = Engine(
            key="z3",
            kind="SMT",
            capability="smt",
            tier=TIER_CORE,
        )
        optional = Engine(
            key="lean",
            kind="proof-assistant",
            capability="proofs",
            install_hint="winget install Lean.Lean",
        )
        return [
            verifiers.EngineStatus(core, False, None, "missing"),
            verifiers.EngineStatus(optional, False, None, "missing"),
        ]

    def test_missing_core_is_a_problem_and_optional_is_an_advisory(self):
        problems, advisories = collect_problems(self._statuses())

        self.assertEqual([problem.path for problem in problems], ["z3"])
        self.assertEqual([advisory.path for advisory in advisories], ["lean"])
        self.assertIn("winget install Lean.Lean", advisories[0].message)

    def test_wired_optional_engine_becomes_a_problem(self):
        problems, advisories = collect_problems(
            self._statuses(),
            wired={"lean"},
        )

        self.assertEqual(
            sorted(problem.path for problem in problems),
            ["lean", "z3"],
        )
        self.assertEqual(advisories, [])

    def test_strict_promotes_every_missing_engine(self):
        problems, advisories = collect_problems(
            self._statuses(),
            strict=True,
        )

        self.assertEqual(len(problems), 2)
        self.assertEqual(advisories, [])

    def test_explicit_requirement_promotes_a_missing_engine(self):
        problems, _advisories = collect_problems(
            self._statuses(),
            required=("lean",),
        )

        self.assertIn("lean", [problem.path for problem in problems])

    def test_available_engine_is_never_reported(self):
        engine = Engine(
            key="julia",
            kind="language",
            capability="numerics",
        )
        statuses = [verifiers.EngineStatus(engine, True, "/bin/julia", "found")]

        problems, advisories = collect_problems(statuses)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_build_report_exposes_the_inventory(self):
        report = verifiers.build_report(
            self._statuses(),
            [],
            [],
            wired={"z3"},
        )

        self.assertEqual(report["problem_count"], 0)
        keys = [item["key"] for item in report["engines"]]
        self.assertEqual(keys, ["z3", "lean"])
        z3 = next(item for item in report["engines"] if item["key"] == "z3")
        self.assertTrue(z3["wired"])


class WiredEnginesTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _ledger(self, text: str) -> None:
        data = self.root / "data"
        data.mkdir(parents=True, exist_ok=True)
        (data / "formal-checks.yaml").write_text(text, encoding="utf-8")

    def test_reads_engine_names_from_the_ledger(self):
        self._ledger(
            "version: 1\n"
            "checks:\n"
            "  - id: a\n"
            "    engine: z3\n"
            "  - id: b\n"
            "    engine: cvc5\n"
        )

        self.assertEqual(wired_engines(self.root), {"z3", "cvc5"})

    def test_missing_ledger_yields_an_empty_set(self):
        self.assertEqual(wired_engines(self.root), set())

    def test_invalid_ledger_yields_an_empty_set(self):
        self._ledger("checks: [not, a, mapping]\n")

        self.assertEqual(wired_engines(self.root), set())


class MainTests(unittest.TestCase):
    def test_main_reports_a_missing_core_engine_as_a_problem(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = main(
                ["verifiers"],
                which=lambda name: None,
                module_probe=lambda name: None,
            )

        self.assertEqual(code, 1)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["problem_count"], 1)
        self.assertEqual(report["problems"][0]["path"], "z3")
        codes = {advisory["code"] for advisory in report["advisories"]}
        self.assertEqual(codes, {"verifier-missing"})

    def test_main_with_core_engine_present_reports_only_advisories(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = main(
                ["verifiers"],
                which=lambda name: None,
                module_probe=lambda name: "5.1.0" if name == "z3" else None,
            )

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["problem_count"], 0)
        z3 = next(item for item in report["engines"] if item["key"] == "z3")
        self.assertTrue(z3["available"])

    def test_main_strict_exits_one(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = main(
                ["verifiers", "--strict"],
                which=lambda name: None,
                module_probe=lambda name: None,
            )

        self.assertEqual(code, 1)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["problem_count"], len(FORMAL_ENGINES))

    def test_main_available_engine_is_reported_as_installed(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = main(
                ["verifiers"],
                which=lambda name: "/bin/" + name,
                module_probe=lambda name: "1.0",
            )

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertTrue(all(item["available"] for item in report["engines"]))


if __name__ == "__main__":
    unittest.main()
