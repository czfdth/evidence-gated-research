import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ccfa.doctor as doctor_module
from ccfa.doctor import (
    DEPENDENCIES,
    Dependency,
    Service,
    ServiceResult,
    Venv,
    check_environment,
    main,
)


def _locator(available):
    def which(name):
        return available.get(name)

    return which


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _all_available(self):
        found = {dep.key: f"/usr/bin/{dep.key}" for dep in DEPENDENCIES}
        for dep in DEPENDENCIES:
            found[dep.executables[0]] = f"/usr/bin/{dep.executables[0]}"
        return found

    def _check(self, available, *, strict=False, venvs=()):
        return check_environment(
            self.root,
            which=_locator(available),
            path_exists=lambda path: False,
            dependencies=DEPENDENCIES,
            venvs=venvs,
            strict=strict,
            run=lambda argv: 0,
        )

    @staticmethod
    def _codes(problems):
        return sorted(problem.code for problem in problems)

    def test_all_present_reports_nothing(self):
        problems, advisories, statuses = self._check(self._all_available())

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])
        self.assertTrue(any("git" in line for line in statuses))

    def test_missing_required_command_is_a_problem(self):
        available = self._all_available()
        del available["git"]

        problems, advisories, _statuses = self._check(available)

        self.assertEqual(self._codes(problems), ["doctor-missing-command"])
        messages = " ".join(problem.message for problem in problems)
        self.assertIn("git", messages)
        self.assertIn("版本", messages)
        self.assertEqual(advisories, [])

    def test_missing_optional_command_is_an_advisory(self):
        available = self._all_available()
        del available["docker"]

        problems, advisories, _statuses = self._check(available)

        self.assertEqual(problems, [])
        self.assertEqual(self._codes(advisories), ["doctor-missing-command"])
        messages = " ".join(advisory.message for advisory in advisories)
        self.assertIn("docker", messages)
        self.assertIn("沙箱", messages)

    def test_strict_promotes_optional_commands_to_problems(self):
        available = self._all_available()
        del available["docker"]

        problems, advisories, _statuses = self._check(available, strict=True)

        self.assertEqual(self._codes(problems), ["doctor-missing-command"])
        self.assertEqual(advisories, [])

    def test_command_aliases_are_tried_in_order(self):
        dependency = Dependency(
            key="tex",
            executables=("pdflatex", "latex"),
            required=False,
            capability="排版",
        )
        problems, advisories, _statuses = check_environment(
            self.root,
            which=_locator({"latex": "/usr/bin/latex"}),
            path_exists=lambda path: False,
            dependencies=(dependency,),
            venvs=(),
        )

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_missing_venv_is_reported(self):
        venv = Venv(key="tools", relative="tools/.venv", capability="包装器")

        problems, advisories, statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            path_exists=lambda path: False,
            dependencies=DEPENDENCIES,
            venvs=(venv,),
            run=lambda argv: 0,
        )

        self.assertEqual(problems, [])
        self.assertEqual(self._codes(advisories), ["doctor-missing-venv"])
        self.assertIn("tools/.venv", advisories[0].message)
        self.assertIn("tools/.venv", " ".join(statuses))

    def test_present_venv_is_not_reported(self):
        venv = Venv(key="tools", relative="tools/.venv", capability="包装器")
        marker = self.root / "tools" / ".venv" / "bin" / "python"

        problems, advisories, _statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            path_exists=lambda path: path == marker,
            dependencies=DEPENDENCIES,
            venvs=(venv,),
            run=lambda argv: 0,
        )

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_docker_daemon_down_is_an_advisory(self):
        calls = []

        def run(argv):
            calls.append(argv)
            return 1

        problems, advisories, statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            path_exists=lambda path: False,
            dependencies=DEPENDENCIES,
            venvs=(),
            run=run,
        )

        self.assertEqual(problems, [])
        self.assertEqual(self._codes(advisories), ["doctor-daemon-down"])
        self.assertTrue(any("docker" in call[0] for call in calls))
        self.assertIn("daemon", " ".join(statuses))

    def test_docker_daemon_up_is_not_reported(self):
        problems, advisories, _statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            path_exists=lambda path: False,
            dependencies=DEPENDENCIES,
            venvs=(),
            run=lambda argv: 0,
        )

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_docker_daemon_check_is_skipped_when_binary_is_missing(self):
        available = self._all_available()
        del available["docker"]

        def run(argv):  # pragma: no cover - must not be called
            raise AssertionError("daemon probe ran without a docker binary")

        _problems, advisories, _statuses = check_environment(
            self.root,
            which=_locator(available),
            path_exists=lambda path: False,
            dependencies=DEPENDENCIES,
            venvs=(),
            run=run,
        )

        self.assertEqual(self._codes(advisories), ["doctor-missing-command"])

    def test_strict_promotes_a_daemon_down_to_a_problem(self):
        problems, advisories, _statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            path_exists=lambda path: False,
            dependencies=DEPENDENCIES,
            venvs=(),
            run=lambda argv: 1,
            strict=True,
        )

        self.assertEqual(self._codes(problems), ["doctor-daemon-down"])
        self.assertEqual(advisories, [])

    def test_windows_venv_layout_is_recognised(self):
        venv = Venv(key="tools", relative="tools/.venv", capability="包装器")
        marker = self.root / "tools" / ".venv" / "Scripts" / "python.exe"

        problems, advisories, _statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            path_exists=lambda path: path == marker,
            dependencies=DEPENDENCIES,
            venvs=(venv,),
            run=lambda argv: 0,
        )

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_default_run_treats_a_timeout_as_failure(self):
        with mock.patch.object(
            doctor_module.subprocess,
            "run",
            side_effect=doctor_module.subprocess.TimeoutExpired(
                ["docker", "info"], 15
            ),
        ):
            self.assertEqual(
                doctor_module._default_run(["docker", "info"]),
                1,
            )

    def test_default_run_treats_a_missing_binary_as_failure(self):
        with mock.patch.object(
            doctor_module.subprocess,
            "run",
            side_effect=OSError("gone"),
        ):
            self.assertEqual(
                doctor_module._default_run(["docker", "info"]),
                1,
            )

    def test_injected_runner_exception_is_reported_not_raised(self):
        def run(argv):
            raise RuntimeError("boom")

        problems, advisories, _statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            path_exists=lambda path: False,
            dependencies=DEPENDENCIES,
            venvs=(),
            run=run,
        )

        self.assertEqual(problems, [])
        self.assertEqual(self._codes(advisories), ["doctor-daemon-down"])

    def test_plain_command_status_says_found_not_ok(self):
        _problems, _advisories, statuses = self._check(self._all_available())

        git_line = next(line for line in statuses if "git" in line)
        self.assertTrue(git_line.startswith("installed"))

    def test_reachable_service_without_functional_result_is_an_advisory(self):
        service = Service(
            key="provider",
            url="http://127.0.0.1:15721/v1/models",
            capability="模型调用",
            expected_model="gpt-5.6",
        )

        problems, advisories, statuses = check_environment(
            self.root,
            dependencies=(),
            venvs=(),
            services=(service,),
            service_probe=lambda item: ServiceResult(
                reachable=True,
                authenticated=True,
                functional=False,
                detail="configured model is absent",
            ),
        )

        self.assertEqual(problems, [])
        self.assertEqual(
            self._codes(advisories),
            ["doctor-service-not-functional"],
        )
        self.assertTrue(
            any(line.startswith("authenticated") for line in statuses)
        )

    def test_functional_service_reports_the_highest_verified_level(self):
        service = Service(
            key="zotero",
            url="http://127.0.0.1:23119/api/users/0/items?limit=1",
            capability="Zotero 本地文献接口",
        )

        problems, advisories, statuses = check_environment(
            self.root,
            dependencies=(),
            venvs=(),
            services=(service,),
            service_probe=lambda item: ServiceResult(
                reachable=True,
                authenticated=True,
                functional=True,
                detail="HTTP 200",
            ),
        )

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])
        self.assertTrue(any(line.startswith("functional") for line in statuses))

    def test_unreachable_service_is_promoted_by_strict_mode(self):
        service = Service(
            key="example-service",
            url="http://127.0.0.1:9/health",
            capability="Example local service",
        )

        problems, advisories, statuses = check_environment(
            self.root,
            dependencies=(),
            venvs=(),
            services=(service,),
            service_probe=lambda item: ServiceResult(
                reachable=False,
                authenticated=False,
                functional=False,
                detail="ConnectionRefusedError",
            ),
            strict=True,
        )

        self.assertEqual(
            self._codes(problems),
            ["doctor-service-unreachable"],
        )
        self.assertEqual(advisories, [])
        self.assertTrue(any("UNREACHABLE" in line for line in statuses))

    def test_provider_probe_requires_the_configured_model_in_models_list(self):
        service = Service(
            key="provider",
            url="http://127.0.0.1:15721/v1/models",
            capability="模型调用",
            expected_model="gpt-5.6",
        )

        result = doctor_module._probe_http_service(
            service,
            fetch=lambda url, timeout: (
                200,
                json.dumps({"data": [{"id": "another-model"}]}).encode(),
            ),
        )

        self.assertTrue(result.reachable)
        self.assertTrue(result.authenticated)
        self.assertFalse(result.functional)
        self.assertNotIn("another-model", result.detail)

    def test_provider_probe_accepts_models_slug_shape(self):
        service = Service(
            key="provider",
            url="http://127.0.0.1:15721/v1/models",
            capability="模型调用",
            expected_model="deepseek-v4-flash",
        )

        result = doctor_module._probe_http_service(
            service,
            fetch=lambda url, timeout: (
                200,
                json.dumps(
                    {
                        "models": [
                            {"slug": "deepseek-v4-flash"},
                            {"slug": "deepseek-v4-pro"},
                            {"slug": "deepseek-flash"},
                        ]
                    }
                ).encode(),
            ),
        )

        self.assertTrue(result.functional)
        self.assertEqual(result.detail, "配置模型可用")

    def test_discovers_provider_and_local_services_from_codex_config(self):
        config = self.root / "config.toml"
        config.write_text(
            'model_provider = "custom"\n'
            'model = "gpt-5.6"\n'
            '[model_providers.custom]\n'
            'base_url = "http://127.0.0.1:15721/v1"\n',
            encoding="utf-8",
        )

        services = doctor_module.discover_services(config)

        by_key = {service.key: service for service in services}
        self.assertEqual(
            by_key["provider"].url,
            "http://127.0.0.1:15721/v1/models",
        )
        self.assertEqual(by_key["provider"].expected_model, "gpt-5.6")
        self.assertEqual(set(by_key), {"provider", "zotero"})
        self.assertIn("zotero", by_key)

    def test_invalid_codex_config_still_discovers_fixed_local_services(self):
        config = self.root / "config.toml"
        config.write_text("not = [valid", encoding="utf-8")

        services = doctor_module.discover_services(config)

        self.assertEqual(
            {service.key for service in services},
            {"zotero"},
        )

    def test_default_path_check_rejects_an_empty_interpreter(self):
        venv = Venv(key="tools", relative="tools/.venv", capability="包装器")
        marker = self.root / "tools" / ".venv" / "bin" / "python"
        marker.parent.mkdir(parents=True)
        marker.write_bytes(b"")

        _problems, advisories, statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            dependencies=(),
            venvs=(venv,),
        )

        self.assertEqual(self._codes(advisories), ["doctor-missing-venv"])
        self.assertIn("MISSING", " ".join(statuses))

    def test_default_path_check_accepts_a_nonempty_interpreter(self):
        venv = Venv(key="tools", relative="tools/.venv", capability="包装器")
        marker = self.root / "tools" / ".venv" / "bin" / "python"
        marker.parent.mkdir(parents=True)
        marker.write_bytes(b"#!/bin/sh\n")

        problems, advisories, _statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            dependencies=(),
            venvs=(venv,),
        )

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_main_prints_json_and_exits_zero_when_only_optional_missing(self):
        available = self._all_available()
        del available["docker"]
        stdout = io.StringIO()
        stderr = io.StringIO()

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            stderr
        ):
            code = main(
                ["doctor", "--repo-root", str(self.root)],
                which=_locator(available),
                path_exists=lambda path: False,
                dependencies=DEPENDENCIES,
                venvs=(),
                run=lambda argv: 0,
                services=(),
            )

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["problem_count"], 0)
        self.assertEqual(
            [item["code"] for item in report["advisories"]],
            ["doctor-missing-command"],
        )

    def test_main_strict_exits_one_and_prints_missing_optional(self):
        available = self._all_available()
        del available["docker"]
        stdout = io.StringIO()
        stderr = io.StringIO()

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            stderr
        ):
            code = main(
                ["doctor", "--repo-root", str(self.root), "--strict"],
                which=_locator(available),
                path_exists=lambda path: False,
                dependencies=DEPENDENCIES,
                venvs=(),
                run=lambda argv: 0,
                services=(),
            )

        self.assertEqual(code, 1)
        self.assertIn("docker", stdout.getvalue())

    def test_main_advisory_summary_warns_about_strict_submission_gate(self):
        stderr = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            stderr
        ):
            code = main(
                ["doctor", "--repo-root", str(self.root)],
                which=_locator({}),
                path_exists=lambda path: False,
                dependencies=(
                    Dependency(
                        "docker",
                        ("docker",),
                        False,
                        "sandbox",
                    ),
                ),
                venvs=(),
                run=lambda argv: 0,
                services=(),
            )

        self.assertEqual(code, 0)
        self.assertIn("0 problems", stderr.getvalue())
        self.assertIn("1 advisory", stderr.getvalue())
        self.assertIn("--strict", stderr.getvalue())

    def _engine(self, key, tier):
        from ccfa.verifiers import Engine

        return Engine(key=key, kind="SMT", capability="proofs", tier=tier)

    def test_missing_optional_verifier_is_an_advisory(self):
        engine = self._engine("lean", "optional")

        problems, advisories, statuses = check_environment(
            self.root,
            dependencies=(),
            venvs=(),
            formal_engines=(engine,),
            engine_probe=lambda item: doctor_module.EngineStatus(
                item, False, None, "missing"
            ),
        )

        self.assertEqual(problems, [])
        self.assertEqual(
            self._codes(advisories),
            ["doctor-missing-verifier"],
        )
        self.assertIn("lean", " ".join(statuses))

    def test_missing_core_verifier_is_a_problem(self):
        engine = self._engine("z3", "core")

        problems, advisories, _statuses = check_environment(
            self.root,
            dependencies=(),
            venvs=(),
            formal_engines=(engine,),
            engine_probe=lambda item: doctor_module.EngineStatus(
                item, False, None, "missing"
            ),
        )

        self.assertEqual(
            self._codes(problems),
            ["doctor-missing-verifier"],
        )
        self.assertEqual(advisories, [])

    def test_present_verifier_is_not_reported(self):
        engine = self._engine("z3", "core")

        problems, advisories, statuses = check_environment(
            self.root,
            dependencies=(),
            venvs=(),
            formal_engines=(engine,),
            engine_probe=lambda item: doctor_module.EngineStatus(
                item, True, "python:z3", "module z3 5.1.0"
            ),
        )

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])
        self.assertTrue(any("z3" in line for line in statuses))

    def test_engine_probe_exception_is_reported_not_raised(self):
        engine = self._engine("z3", "core")

        def boom(item):  # pragma: no cover - only raised to simulate
            raise RuntimeError("probe exploded")

        problems, _advisories, _statuses = check_environment(
            self.root,
            dependencies=(),
            venvs=(),
            formal_engines=(engine,),
            engine_probe=boom,
        )

        self.assertEqual(
            self._codes(problems),
            ["doctor-missing-verifier"],
        )


    def test_check_imports_names_the_module_this_interpreter_cannot_import(self):
        missing, present = doctor_module.check_imports(
            (
                doctor_module.ImportCheck("yaml", "所有工具", "演示"),
                doctor_module.ImportCheck(
                    "ccfa_no_such_module_xyz",
                    "演示",
                    "演示",
                ),
            ),
            importer=__import__,
        )

        self.assertEqual(present, ["yaml"])
        self.assertEqual(
            [item["module"] for item in missing],
            ["ccfa_no_such_module_xyz"],
        )
        self.assertIn("ModuleNotFoundError", missing[0]["error"])

    def test_imports_only_is_green_in_a_fully_provisioned_venv(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(["doctor", "--imports-only"])

        payload = json.loads(out.getvalue())
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["missing"], [])
        self.assertIn("yaml", payload["present"])
        self.assertIn("python", payload)

    def test_imports_only_fails_closed_and_lists_what_is_missing(self):
        missing = [
            {
                "module": "z3",
                "capability": "formal-check",
                "message": "Z3 SMT 引擎",
                "error": "ModuleNotFoundError: No module named 'z3'",
            }
        ]
        out = io.StringIO()
        with mock.patch.object(
            doctor_module,
            "check_imports",
            return_value=(missing, ["yaml"]),
        ):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(
                io.StringIO()
            ):
                code = main(["doctor", "--imports-only"])

        payload = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["missing"], missing)


if __name__ == "__main__":
    unittest.main()
