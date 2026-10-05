import hashlib
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import yaml

import ccfa.cross_review as cross_review_module
from ccfa.cli import Problem as CliProblem
from ccfa.cross_review import (
    REVIEW_SCHEMA,
    build_prompt,
    check_review,
    main,
    run_review,
)


class ModelFamilyTests(unittest.TestCase):
    def test_ollama_style_qwen_tags_are_the_qwen_family(self):
        # Ollama tags carry the version without a dash (qwen3:30b), unlike the
        # alias the workflow used to rely on (qwen-local).
        for name in ("qwen3:30b", "qwen3.8:27b-q4_K_M", "qwen2.5:3b", "qwen-local"):
            with self.subTest(model=name):
                self.assertEqual(
                    cross_review_module._model_family(name),
                    "qwen",
                )

    def test_deepseek_executor_and_qwen_reviewer_are_cross_family(self):
        self.assertEqual(
            cross_review_module._family_judgement("qwen3:30b", "deepseek-v4-flash"),
            "cross-family",
        )

    def test_same_family_is_detected_without_a_dash(self):
        self.assertEqual(
            cross_review_module._family_judgement("deepseek-v4-pro", "deepseek-v4-flash"),
            "same-family",
        )

    def test_unknown_models_stay_unknown(self):
        self.assertEqual(
            cross_review_module._family_judgement("some-unknown-model", "deepseek-v4-flash"),
            "unknown",
        )


class CrossReviewTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper_root = Path(self._temporary.name)
        (self.paper_root / "manuscript").mkdir()
        self.input_path = self.paper_root / "manuscript" / "main.tex"
        self.input_path.write_text("\\documentclass{article}\n", encoding="utf-8")
        state = {
            "target_venue": {"name": "NeurIPS", "mode": "conference"},
            "stage": {"current": "internal-review"},
        }
        (self.paper_root / "ccfa.yaml").write_text(
            yaml.safe_dump(state, sort_keys=False),
            encoding="utf-8",
        )
        self.codex_config = self.paper_root / "config.toml"
        self.codex_config.write_text(
            'model_provider = "deepseek-provider"\n'
            'model = "deepseek-v4-flash"\n'
            '[model_providers.deepseek-provider]\n'
            'base_url = "https://deepseek.example.test/v1"\n'
            '[model_providers.other-provider]\n'
            'base_url = "https://openai.example.test/v1"\n',
            encoding="utf-8",
        )

    def _payload(self, verdict="pass", blocking=None, summary="summary", checks=None):
        if checks is None:
            checks = [
                {
                    "gate": "citation",
                    "path": "manuscript/main.tex",
                    "evidence": "\\documentclass{article}",
                }
            ]
        return {
            "verdict": verdict,
            "blocking": blocking or [],
            "checks": checks,
            "summary": summary,
        }

    def _runner(
        self,
        *,
        payload=None,
        raw=None,
        code=0,
        stderr="",
        write_last=True,
    ):
        calls = []

        def runner(argv, cwd, timeout, prompt):
            calls.append(
                {
                    "argv": list(argv),
                    "cwd": Path(cwd),
                    "timeout": timeout,
                    "prompt": prompt,
                }
            )
            if write_last:
                output_path = Path(argv[argv.index("-o") + 1])
                text = raw if raw is not None else json.dumps(payload or self._payload())
                output_path.write_text(text, encoding="utf-8")
            return code, stderr

        runner.calls = calls
        return runner

    def _run(self, runner, **overrides):
        values = {
            "model": "gpt-5.6",
            "allow_same_family": False,
            "override_reason": None,
            "stage": "internal-review",
            "paths": [Path("manuscript/main.tex")],
            "codex_config": self.codex_config,
            # The deterministic-contradiction guard is exercised by its own
            # tests; these tests focus on the run/provenance mechanics.
            "contradiction_probe": lambda root: [],
        }
        values.update(overrides)
        return run_review(self.paper_root, runner=runner, **values)

    def _run_same_family(self, runner, **overrides):
        values = {
            "model": "deepseek-v4-pro",
            "allow_same_family": True,
            "override_reason": (
                "test migration: no second-family provider is configured"
            ),
        }
        values.update(overrides)
        return self._run(runner, **values)

    def _record_path(self):
        return self.paper_root / "reviews" / "cross-review.json"

    def _run_main(self, argv):
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()


class TestPromptAndArgv(CrossReviewTests):
    def test_build_prompt_contains_gate_criterion_file_list_and_no_write_rule(self):
        prompt = build_prompt(
            self.paper_root,
            "internal-review",
            [Path("manuscript/main.tex")],
        )

        self.assertIn("review_cleared", prompt)
        self.assertIn("跨模型评审报告无 blocking", prompt)
        self.assertIn("manuscript/main.tex", prompt)
        self.assertIn("禁止修改任何文件", prompt)
        self.assertIn("JSON", prompt)
        self.assertIn("本次运行就是在生成当前有效的跨模型评审报告", prompt)
        self.assertIn("不要因为 reviews/cross-review.json 尚不存在", prompt)
        self.assertIn("checks", prompt)
        self.assertIn("sha256", prompt)

    def test_argv_has_exact_required_flags_and_stdin_prompt(self):
        runner = self._runner(payload=self._payload())

        self._run(runner)

        argv = runner.calls[0]["argv"]
        self.assertEqual(argv[1], "exec")
        # The CLI is resolved to an absolute path when PATH lacks it.
        self.assertIn("codex", Path(argv[0]).name.casefold())
        self.assertIn("-m", argv)
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-5.6")
        self.assertIn("-s", argv)
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")
        self.assertIn("--ephemeral", argv)
        self.assertIn("--skip-git-repo-check", argv)
        self.assertIn("-C", argv)
        self.assertEqual(
            Path(argv[argv.index("-C") + 1]).resolve(),
            Path(self.paper_root).resolve(),
        )
        self.assertIn("--output-schema", argv)
        self.assertIn("-o", argv)
        self.assertEqual(argv[-1], "-")
        self.assertIn("禁止修改任何文件", runner.calls[0]["prompt"])

    def test_review_schema_is_strict(self):
        self.assertEqual(REVIEW_SCHEMA["properties"]["verdict"]["enum"], ["pass", "blocking"])
        self.assertEqual(
            REVIEW_SCHEMA["properties"]["blocking"]["items"]["required"],
            ["title", "evidence"],
        )


class TestRunReview(CrossReviewTests):
    def test_json_payload_in_markdown_fence_is_parsed(self):
        runner = self._runner(
            raw=(
                "```json\n"
                + json.dumps(self._payload("pass"), ensure_ascii=False)
                + "\n```"
            )
        )

        result = self._run(runner, model="gpt-5.6")

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["model_verdict"], "pass")

    def test_multiple_markdown_fences_are_rejected(self):
        fenced = (
            "```json\n"
            + json.dumps(self._payload("pass"), ensure_ascii=False)
            + "\n```\n```\n{}\n```"
        )
        runner = self._runner(raw=fenced)

        result = self._run(runner, model="gpt-5.6")

        self.assertEqual(result["status"], "malformed")
        self.assertEqual(result["verdict"], "malformed")

    def test_relative_paper_root_uses_absolute_codex_paths(self):
        runner = self._runner(payload=self._payload())
        original_cwd = Path.cwd()
        os.chdir(self.paper_root.parent)
        try:
            run_review(
                Path(self.paper_root.name),
                model="deepseek-v4-pro",
                allow_same_family=True,
                override_reason=(
                    "test migration: no second-family provider is configured"
                ),
                stage="internal-review",
                paths=[Path("manuscript/main.tex")],
                runner=runner,
                codex_config=self.codex_config,
            )
        finally:
            os.chdir(original_cwd)

        argv = runner.calls[0]["argv"]
        codex_cwd = Path(argv[argv.index("-C") + 1])
        self.assertTrue(codex_cwd.is_absolute())
        self.assertEqual(codex_cwd, self.paper_root.resolve())
        self.assertTrue(
            Path(argv[argv.index("--output-schema") + 1]).is_absolute()
        )
        self.assertTrue(Path(argv[argv.index("-o") + 1]).is_absolute())

    def test_review_model_must_be_explicit(self):
        runner = self._runner(payload=self._payload())

        with self.assertRaisesRegex(ValueError, "--model"):
            self._run(runner, model=None)

        self.assertEqual(runner.calls, [])
        self.assertFalse(self._record_path().exists())

    def test_pass_writes_json_and_markdown_records(self):
        runner = self._runner(payload=self._payload("pass"))

        result = self._run(
            runner,
            model="gpt-5.6",
            allow_same_family=False,
            override_reason=None,
        )

        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["family_judgement"], "cross-family")
        self.assertTrue(self._record_path().is_file())
        self.assertTrue((self.paper_root / "reviews" / "cross-review.md").is_file())
        self.assertEqual(result["model"], "gpt-5.6")
        self.assertEqual(result["execution_model"], "deepseek-v4-flash")
        self.assertEqual(result["execution_provider"], "deepseek-provider")
        self.assertRegex(result["provider_endpoint_sha256"], r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn("deepseek.example.test", json.dumps(result))

    def test_same_family_pass_is_downgraded_to_blocking(self):
        runner = self._runner(payload=self._payload("pass"))

        result = self._run_same_family(runner)

        self.assertEqual(result["model_verdict"], "pass")
        self.assertEqual(result["verdict"], "blocking")
        self.assertIn("never acquit", result["summary"])
        self.assertEqual(
            [problem.code for problem in check_review(self.paper_root, allow_same_family=True)],
            ["review-blocking"],
        )

    def test_missing_codex_config_fails_closed_before_running(self):
        runner = self._runner(payload=self._payload("pass"))

        with self.assertRaisesRegex(ValueError, "Codex 配置"):
            self._run(
                runner,
                codex_config=self.paper_root / "missing.toml",
            )

        self.assertEqual(runner.calls, [])

    def test_unknown_review_provider_fails_closed_before_running(self):
        runner = self._runner(payload=self._payload("pass"))

        with self.assertRaisesRegex(ValueError, "provider"):
            self._run(
                runner,
                provider="not-configured",
            )

        self.assertEqual(runner.calls, [])

    def test_same_family_requires_explicit_override(self):
        runner = self._runner(payload=self._payload("pass"))

        with self.assertRaisesRegex(ValueError, "allow-same-family"):
            self._run(
                runner,
                model="deepseek-v4-pro",
                allow_same_family=False,
            )

        self.assertEqual(runner.calls, [])
        self.assertFalse(self._record_path().exists())

    def test_same_family_override_requires_a_reason(self):
        runner = self._runner(payload=self._payload("pass"))

        with self.assertRaisesRegex(ValueError, "override-reason"):
            self._run(
                runner,
                model="deepseek-v4-pro",
                allow_same_family=True,
                override_reason=None,
            )

        self.assertEqual(runner.calls, [])
        self.assertFalse(self._record_path().exists())

    def test_same_family_override_reason_is_recorded(self):
        runner = self._runner(payload=self._payload("pass"))

        result = self._run(
            runner,
            model="deepseek-v4-pro",
            allow_same_family=True,
            override_reason=(
                "test migration: no second-family provider is configured"
            ),
        )

        self.assertTrue(result["family_override"])
        self.assertIn("no second-family provider", result["family_override_reason"])
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertEqual(
            record["family_override_reason"],
            result["family_override_reason"],
        )

    def test_cross_family_does_not_need_override_reason(self):
        runner = self._runner(payload=self._payload("pass"))

        result = self._run(
            runner,
            model="gpt-5.6",
            allow_same_family=False,
            override_reason=None,
        )

        self.assertEqual(result["family_judgement"], "cross-family")
        self.assertFalse(result["family_override"])
        self.assertIsNone(result["family_override_reason"])

    def test_cross_family_model_is_allowed_without_override(self):
        runner = self._runner(payload=self._payload("pass"))

        result = self._run(
            runner,
            model="gpt-5.6",
            allow_same_family=False,
        )

        self.assertEqual(result["family_judgement"], "cross-family")
        self.assertFalse(result["family_override"])

    def test_reasoning_effort_is_passed_and_recorded(self):
        runner = self._runner(payload=self._payload("pass"))

        result = self._run(
            runner,
            model="qwen-local",
            provider="other-provider",
            reasoning_effort="none",
        )

        argv = runner.calls[0]["argv"]
        self.assertIn("model_reasoning_effort=none", argv)
        self.assertEqual(result["reasoning_effort"], "none")

    def test_provider_is_passed_to_codex_and_recorded(self):
        runner = self._runner(payload=self._payload("pass"))

        result = self._run(
            runner,
            model="gpt-5.6",
            provider="other-provider",
            allow_same_family=False,
        )

        argv = runner.calls[0]["argv"]
        self.assertIn("-c", argv)
        self.assertIn("model_provider=other-provider", argv)
        self.assertEqual(result["provider"], "other-provider")

    def test_blocking_verdict_preserves_evidence_exactly(self):
        blocking = [
            {
                "title": "Missing ablation",
                "evidence": "Table 2 has no seed variance.",
            }
        ]
        runner = self._runner(payload=self._payload("blocking", blocking))

        result = self._run(runner)

        self.assertEqual(result["verdict"], "blocking")
        self.assertEqual(result["blocking"], blocking)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertEqual(record["blocking"], blocking)

    def test_missing_last_message_is_malformed_and_not_pass(self):
        runner = self._runner(write_last=False)

        result = self._run(runner)

        self.assertEqual(result["verdict"], "malformed")
        self.assertNotEqual(result["verdict"], "pass")
        self.assertTrue(self._record_path().is_file())

    def test_invalid_json_is_malformed(self):
        runner = self._runner(raw="{not json", write_last=True)

        result = self._run(runner)

        self.assertEqual(result["verdict"], "malformed")

    def test_nonzero_exit_writes_failure_record_and_raises(self):
        runner = self._runner(code=7, stderr="model unavailable", write_last=False)

        with self.assertRaisesRegex(ValueError, "codex exec"):
            self._run(runner)

        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["exit_code"], 7)
        self.assertIn("model unavailable", record["stderr"])

    def test_missing_codex_names_codex_exec(self):
        def runner(argv, cwd, timeout, prompt):
            raise FileNotFoundError("codex")

        with self.assertRaisesRegex(ValueError, "codex exec"):
            self._run(runner)

    def test_record_is_not_overwritten_without_force(self):
        first = self._runner(payload=self._payload("pass"))
        second = self._runner(payload=self._payload("blocking", [{"title": "x", "evidence": "y"}]))
        self._run(first)

        with self.assertRaises(ValueError):
            self._run(second)
        self.assertEqual(len(second.calls), 0)

        result = self._run(second, force=True)
        self.assertEqual(result["verdict"], "blocking")

    def test_input_hashes_normalize_text_line_endings(self):
        path = self.paper_root / "manuscript" / "crlf.tex"
        path.write_bytes(b"line one\r\nline two\r\n")

        result = self._run(
            self._runner(),
            paths=[Path("manuscript/crlf.tex")],
        )

        digest = hashlib.sha256(b"line one\nline two\n").hexdigest()
        self.assertEqual(
            result["input_hashes"]["manuscript/crlf.tex"],
            f"sha256:{digest}",
        )

    def test_input_hashes_keep_binary_bytes_exact(self):
        path = self.paper_root / "manuscript" / "blob.bin"
        path.write_bytes(b"line one\r\nline two\r\n")

        result = self._run(
            self._runner(),
            paths=[Path("manuscript/blob.bin")],
        )

        digest = hashlib.sha256(
            b"line one\r\nline two\r\n"
        ).hexdigest()
        self.assertEqual(
            result["input_hashes"]["manuscript/blob.bin"],
            f"sha256:{digest}",
        )

    def test_input_hashes_are_recorded(self):
        runner = self._runner(payload=self._payload())

        result = self._run(runner)

        self.assertEqual(
            set(result["input_hashes"]),
            {"manuscript/main.tex"},
        )
        self.assertTrue(result["input_hashes"]["manuscript/main.tex"].startswith("sha256:"))

    def test_prompt_hash_is_recorded_and_matches_the_prompt_sent(self):
        runner = self._runner(payload=self._payload())

        result = self._run(runner)

        digest = hashlib.sha256(
            runner.calls[0]["prompt"].encode("utf-8")
        ).hexdigest()
        self.assertEqual(result["prompt_sha256"], f"sha256:{digest}")

    def test_run_review_rejects_an_empty_input_list(self):
        runner = self._runner(payload=self._payload())

        with self.assertRaisesRegex(ValueError, "评审输入"):
            self._run(runner, paths=[])

    def test_long_stderr_is_bounded_in_complete_record(self):
        runner = self._runner(
            payload=self._payload(),
            stderr="x" * 100_000,
        )

        self._run(runner)

        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertLessEqual(
            len(record["stderr"]),
            4000 + len("...[truncated]"),
        )
        self.assertTrue(record["stderr"].endswith("...[truncated]"))

    def test_long_stderr_is_bounded_in_malformed_record(self):
        runner = self._runner(
            write_last=False,
            stderr="x" * 100_000,
        )

        self._run(runner)

        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "malformed")
        self.assertLessEqual(
            len(record["stderr"]),
            4000 + len("...[truncated]"),
        )
        self.assertTrue(record["stderr"].endswith("...[truncated]"))

    def test_long_stderr_is_bounded_in_failure_record(self):
        runner = self._runner(
            code=7,
            write_last=False,
            stderr="x" * 100_000,
        )

        with self.assertRaisesRegex(ValueError, "codex exec"):
            self._run(runner)

        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "failed")
        self.assertLessEqual(
            len(record["stderr"]),
            4000 + len("...[truncated]"),
        )
        self.assertTrue(record["stderr"].endswith("...[truncated]"))

    def test_short_stderr_is_not_marked_truncated(self):
        runner = self._runner(
            payload=self._payload(),
            stderr="short stderr",
        )

        self._run(runner)

        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertEqual(record["stderr"], "short stderr")
        self.assertNotIn("...[truncated]", record["stderr"])

    def test_long_raw_last_message_is_marked_truncated(self):
        runner = self._runner(raw="x" * 20_000)

        result = self._run(runner)

        self.assertEqual(result["verdict"], "malformed")
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertLessEqual(
            len(record["raw_last_message"]),
            10_000 + len("...[truncated]"),
        )
        self.assertTrue(record["raw_last_message"].endswith("...[truncated]"))

    def test_short_raw_last_message_is_not_marked_truncated(self):
        runner = self._runner(raw="{short malformed")

        self._run(runner)

        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertEqual(record["raw_last_message"], "{short malformed")
        self.assertNotIn("...[truncated]", record["raw_last_message"])


class TestDeterministicContradictionGuard(CrossReviewTests):
    def test_probe_turns_argument_problems_into_blocking_items(self):
        problem = CliProblem(
            "proof-review-not-verified",
            "data/proof-audit.yaml",
            None,
            "prop:noncomp: status='pending'，未通过人工复核",
        )
        with mock.patch.object(
            cross_review_module,
            "argument_audit_check",
            return_value=([problem], []),
        ):
            blockers = cross_review_module._deterministic_contradictions(
                self.paper_root
            )

        self.assertEqual(len(blockers), 1)
        self.assertIn("proof-review-not-verified", blockers[0]["title"])
        self.assertIn("data/proof-audit.yaml", blockers[0]["evidence"])

    def test_probe_failure_is_itself_blocking(self):
        with mock.patch.object(
            cross_review_module,
            "argument_audit_check",
            side_effect=RuntimeError("boom"),
        ):
            blockers = cross_review_module._deterministic_contradictions(
                self.paper_root
            )

        self.assertEqual(len(blockers), 1)
        self.assertIn("failed to run", blockers[0]["title"])

    def test_pass_is_downgraded_when_a_gate_disagrees(self):
        runner = self._runner(payload=self._payload())

        record = self._run(
            runner,
            contradiction_probe=lambda root: [
                {
                    "title": "review-contradiction: proof-review-not-verified",
                    "evidence": "data/proof-audit.yaml: pending",
                }
            ],
        )

        self.assertEqual(record["model_verdict"], "pass")
        self.assertEqual(record["verdict"], "blocking")
        self.assertTrue(record["deterministic_contradiction"])
        self.assertEqual(len(record["blocking"]), 1)
        self.assertIn("review-contradiction", record["summary"])

    def test_clean_gate_keeps_the_model_pass(self):
        runner = self._runner(payload=self._payload())

        record = self._run(runner)

        self.assertEqual(record["verdict"], "pass")
        self.assertFalse(record["deterministic_contradiction"])
        self.assertEqual(record["blocking"], [])

    def test_review_tier_flags_small_and_local_models(self):
        cases = {
            ("qwen3:30b", "local-qwen"): "advisory-only",
            ("qwen-local", "local-qwen"): "advisory-only",
            ("llama3.1:8b", "local-ollama"): "advisory-only",
            ("qwen3:72b", "local-qwen"): "gate-capable",
            ("gpt-5.6", None): "gate-capable",
            ("deepseek-v4-flash", "custom"): "gate-capable",
        }
        for (model, provider), expected in cases.items():
            with self.subTest(model=model, provider=provider):
                self.assertEqual(
                    cross_review_module._review_tier(model, provider),
                    expected,
                )

    def test_advisory_only_model_cannot_acquit(self):
        runner = self._runner(payload=self._payload())

        # The size heuristic alone marks this local model advisory-only.
        record = self._run(runner, model="qwen3:30b")

        self.assertEqual(record["model_verdict"], "pass")
        self.assertEqual(record["review_tier"], "advisory-only")
        self.assertEqual(record["verdict"], "blocking")
        self.assertTrue(
            any(
                item["title"].startswith("review-advisory-only:")
                for item in record["blocking"]
            )
        )

    def test_pass_without_checks_is_unevidenced(self):
        runner = self._runner(payload=self._payload(checks=[]))

        record = self._run(runner)

        self.assertEqual(record["verdict"], "blocking")
        self.assertTrue(
            any(
                item["title"].startswith("review-unevidenced-pass:")
                for item in record["blocking"]
            )
        )

    def test_pass_citing_a_file_outside_the_inputs_is_unevidenced(self):
        runner = self._runner(
            payload=self._payload(
                checks=[
                    {
                        "gate": "citation",
                        "path": "manuscript/not-an-input.tex",
                        "evidence": "\\documentclass{article}",
                    }
                ]
            )
        )

        record = self._run(runner)

        self.assertEqual(record["verdict"], "blocking")

    def test_pass_citing_the_file_hash_is_accepted(self):
        digest = cross_review_module._sha256(self.input_path)
        runner = self._runner(
            payload=self._payload(
                checks=[
                    {
                        "gate": "citation",
                        "path": "manuscript/main.tex",
                        "evidence": digest,
                    }
                ]
            )
        )

        record = self._run(runner)

        self.assertEqual(record["verdict"], "pass")


class TestCodexExecutableResolution(unittest.TestCase):
    def _clear_override(self):
        return mock.patch.dict(
            os.environ, {"CCFA_CODEX_EXECUTABLE": ""}, clear=False
        )

    def test_env_override_wins(self):
        with mock.patch.dict(
            os.environ, {"CCFA_CODEX_EXECUTABLE": r"C:\custom\codex.exe"}
        ):
            self.assertEqual(
                cross_review_module._resolve_codex_executable(),
                r"C:\custom\codex.exe",
            )

    def test_path_is_preferred_when_available(self):
        with self._clear_override(), mock.patch.object(
            cross_review_module.shutil, "which", return_value="/usr/bin/codex"
        ):
            self.assertEqual(
                cross_review_module._resolve_codex_executable(),
                "/usr/bin/codex",
            )

    def test_falls_back_to_the_newest_localappdata_binary(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            old = root / "OpenAI" / "Codex" / "bin" / "aaa"
            new = root / "OpenAI" / "Codex" / "bin" / "bbb"
            old.mkdir(parents=True)
            new.mkdir(parents=True)
            (old / "codex.exe").write_text("old", encoding="utf-8")
            (new / "codex.exe").write_text("new", encoding="utf-8")
            os.utime(old / "codex.exe", (1, 1))
            os.utime(new / "codex.exe", (2, 2))

            with self._clear_override(), mock.patch.dict(
                os.environ, {"LOCALAPPDATA": str(root)}, clear=False
            ), mock.patch.object(
                cross_review_module.shutil, "which", return_value=None
            ):
                resolved = cross_review_module._resolve_codex_executable()

            self.assertEqual(resolved, str(new / "codex.exe"))

    def test_falls_back_to_the_bare_name(self):
        with tempfile.TemporaryDirectory() as raw, self._clear_override(), (
            mock.patch.dict(os.environ, {"LOCALAPPDATA": raw}, clear=False)
        ), mock.patch.object(
            cross_review_module.shutil, "which", return_value=None
        ):
            self.assertEqual(
                cross_review_module._resolve_codex_executable(),
                "codex",
            )


class TestCheckReview(CrossReviewTests):
    def setUp(self):
        super().setUp()
        # These tests cover the audit mechanics; the deterministic-contradiction
        # guard has its own dedicated tests below.
        patcher = mock.patch.object(
            cross_review_module,
            "_deterministic_contradictions",
            return_value=[],
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_stored_pass_contradicting_a_gate_is_flagged(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)

        with mock.patch.object(
            cross_review_module,
            "_deterministic_contradictions",
            return_value=[{"title": "x", "evidence": "y"}],
        ):
            problems = check_review(self.paper_root)

        self.assertIn("review-contradiction", [p.code for p in problems])

    def test_advisory_only_pass_is_flagged(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        record_path = self._record_path()
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["review_tier"] = "advisory-only"
        record_path.write_text(json.dumps(record), encoding="utf-8")

        codes = [problem.code for problem in check_review(self.paper_root)]

        self.assertIn("review-advisory-only", codes)

    def test_contradiction_downgrade_is_accepted_by_the_auditor(self):
        runner = self._runner(payload=self._payload())
        self._run(
            runner,
            contradiction_probe=lambda root: [
                {
                    "title": "review-contradiction: proof-review-not-verified",
                    "evidence": "data/proof-audit.yaml: pending",
                }
            ],
        )

        codes = [problem.code for problem in check_review(self.paper_root)]

        # The pass->blocking downgrade is legitimate here, and the item comes
        # from the deterministic gate rather than from the model.
        self.assertNotIn("review-record-invalid", codes)
        self.assertNotIn("review-uncited-blocking", codes)
        self.assertIn("review-blocking", codes)

    def test_missing_record_is_review_missing(self):
        problems = check_review(self.paper_root)
        self.assertEqual([problem.code for problem in problems], ["review-missing"])

    def test_changed_input_is_review_stale(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        self.input_path.write_text("changed\n", encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual([problem.code for problem in problems], ["review-stale"])

    def test_same_family_record_is_a_problem_without_override(self):
        runner = self._runner(payload=self._payload())
        self._run_same_family(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["family_override"] = False
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-same-family", "review-blocking"],
        )
        self.assertEqual(
            [
                problem.code
                for problem in check_review(
                    self.paper_root,
                    allow_same_family=True,
                )
            ],
            ["review-blocking"],
        )

    def test_same_family_override_without_reason_is_a_problem(self):
        runner = self._runner(payload=self._payload())
        self._run_same_family(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record.pop("family_override_reason", None)
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(
            self.paper_root,
            allow_same_family=True,
        )

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-override-reason-missing", "review-blocking"],
        )

    def test_strict_cross_family_reports_override(self):
        runner = self._runner(payload=self._payload())
        self._run_same_family(runner)

        problems = check_review(
            self.paper_root,
            allow_same_family=True,
            strict_cross_family=True,
        )

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-family-override", "review-blocking"],
        )

    def test_edited_family_judgement_cannot_bypass_recomputation(self):
        runner = self._runner(payload=self._payload())
        self._run_same_family(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["family_override"] = False
        record["family_judgement"] = "cross-family"
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            [
                "review-family-mismatch",
                "review-same-family",
                "review-blocking",
            ],
        )
        self.assertEqual(
            [problem.code for problem in check_review(
                self.paper_root,
                allow_same_family=True,
            )],
            ["review-family-mismatch", "review-blocking"],
        )

    def test_legacy_record_without_family_fields_requires_explicit_migration(self):
        runner = self._runner(payload=self._payload())
        self._run_same_family(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record.pop("family_judgement", None)
        record.pop("family_override", None)
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            [
                "review-provenance-incomplete",
                "review-same-family",
                "review-blocking",
            ],
        )
        self.assertEqual(
            [
                problem.code
                for problem in check_review(
                    self.paper_root,
                    allow_same_family=True,
                )
            ],
            ["review-provenance-incomplete", "review-blocking"],
        )

    def test_legacy_record_with_family_but_no_execution_model_is_only_same_family(self):
        runner = self._runner(payload=self._payload())
        self._run_same_family(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record.pop("execution_model", None)
        record.pop("provider", None)
        record.pop("family_override", None)
        record["family_judgement"] = "same-family"
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            [
                "review-provenance-incomplete",
                "review-same-family",
                "review-blocking",
            ],
        )
        self.assertEqual(
            [
                problem.code
                for problem in check_review(
                    self.paper_root,
                    allow_same_family=True,
                )
            ],
            ["review-provenance-incomplete", "review-blocking"],
        )

    def test_missing_provenance_is_flagged_even_for_a_cross_family_looking_model(self):
        runner = self._runner(payload=self._payload())
        self._run(
            runner,
            model="gpt-5.6",
            allow_same_family=False,
        )
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record.pop("execution_model", None)
        record.pop("provider", None)
        record.pop("family_override", None)
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            [
                "review-provenance-incomplete",
                "review-same-family",
                "review-blocking",
            ],
        )
        self.assertEqual(
            [
                problem.code
                for problem in check_review(
                    self.paper_root,
                    allow_same_family=True,
                )
            ],
            ["review-provenance-incomplete", "review-blocking"],
        )

    def test_edited_execution_model_recomputes_family_and_detects_drift(self):
        runner = self._runner(payload=self._payload())
        self._run(
            runner,
            model="gpt-5.6",
            allow_same_family=False,
        )
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["execution_model"] = "gpt-5.6"
        record["family_judgement"] = "cross-family"
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            [
                "review-provider-config-drift",
                "review-family-mismatch",
                "review-same-family",
                "review-blocking",
            ],
        )
        self.assertEqual(
            [
                problem.code
                for problem in check_review(
                    self.paper_root,
                    allow_same_family=True,
                )
            ],
            [
                "review-provider-config-drift",
                "review-family-mismatch",
                "review-blocking",
            ],
        )

    def test_missing_endpoint_hash_makes_provenance_incomplete(self):
        runner = self._runner(payload=self._payload())
        self._run(
            runner,
            model="gpt-5.6",
            allow_same_family=False,
        )
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record.pop("provider_endpoint_sha256", None)
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-provenance-incomplete"],
        )
        self.assertEqual(
            [
                problem.code
                for problem in check_review(
                    self.paper_root,
                    allow_same_family=True,
                )
            ],
            ["review-provenance-incomplete"],
        )

    def test_missing_codex_config_path_is_provenance_incomplete(self):
        runner = self._runner(payload=self._payload())
        self._run(
            runner,
            model="gpt-5.6",
            allow_same_family=False,
        )
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record.pop("codex_config_path", None)
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-provenance-incomplete"],
        )

    def test_inconsistent_model_verdict_is_rejected(self):
        runner = self._runner(payload=self._payload())
        self._run(
            runner,
            model="gpt-5.6",
            allow_same_family=False,
        )
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["model_verdict"] = "blocking"
        record["verdict"] = "pass"
        record["blocking"] = []
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-record-invalid"],
        )

    def test_config_change_invalidates_complete_review(self):
        runner = self._runner(payload=self._payload())
        self._run(
            runner,
            model="gpt-5.6",
            allow_same_family=False,
        )
        self.codex_config.write_text(
            'model_provider = "deepseek-provider"\n'
            'model = "deepseek-v4-flash"\n'
            '[model_providers.deepseek-provider]\n'
            'base_url = "https://changed.example.test/v1"\n'
            '[model_providers.other-provider]\n'
            'base_url = "https://openai.example.test/v1"\n',
            encoding="utf-8",
        )

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-provider-config-drift"],
        )

    def test_mismatch_survives_incomplete_provenance_and_allow_flag(self):
        runner = self._runner(payload=self._payload())
        self._run_same_family(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["family_override"] = False
        record["family_judgement"] = "cross-family"
        record.pop("provider", None)
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            [
                "review-provenance-incomplete",
                "review-family-mismatch",
                "review-same-family",
                "review-blocking",
            ],
        )
        self.assertEqual(
            [
                problem.code
                for problem in check_review(
                    self.paper_root,
                    allow_same_family=True,
                )
            ],
            [
                "review-provenance-incomplete",
                "review-family-mismatch",
                "review-blocking",
            ],
        )

    def test_unknown_family_mismatch_survives_allow_flag(self):
        runner = self._runner(payload=self._payload())
        self._run_same_family(runner, model="mystery-v1")
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["family_override"] = False
        record["family_judgement"] = "same-family"
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            [
                "review-family-mismatch",
                "review-same-family",
                "review-blocking",
            ],
        )
        self.assertEqual(
            [
                problem.code
                for problem in check_review(
                    self.paper_root,
                    allow_same_family=True,
                )
            ],
            ["review-family-mismatch", "review-blocking"],
        )

    def test_same_family_record_with_pass_verdict_is_blocked(self):
        runner = self._runner(payload=self._payload())
        self._run_same_family(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["model_verdict"] = "pass"
        record["verdict"] = "pass"
        record.pop("blocking", None)
        record["blocking"] = []
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root, allow_same_family=True)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-blocking"],
        )

    def test_matching_prompt_hash_is_not_reported(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)

        problems = check_review(self.paper_root, allow_same_family=True)

        self.assertEqual(problems, [])

    def test_repeated_path_does_not_cause_prompt_drift(self):
        runner = self._runner(payload=self._payload())
        self._run(
            runner,
            paths=[
                Path("manuscript/main.tex"),
                Path("manuscript/main.tex"),
            ],
        )

        problems = check_review(self.paper_root, allow_same_family=True)

        self.assertEqual(problems, [])

    def test_empty_input_hashes_is_review_malformed(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["input_hashes"] = {}
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root, allow_same_family=True)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-malformed"],
        )

    def test_missing_stage_is_review_prompt_unknown(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record.pop("stage", None)
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root, allow_same_family=True)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-prompt-unknown"],
        )

    def test_blank_stage_is_review_prompt_unknown(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["stage"] = "   "
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root, allow_same_family=True)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-prompt-unknown"],
        )

    def test_record_without_prompt_hash_is_review_prompt_unknown(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record.pop("prompt_sha256", None)
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root, allow_same_family=True)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-prompt-unknown"],
        )

    def test_stale_prompt_hash_is_review_prompt_drift(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["prompt_sha256"] = "sha256:" + "0" * 64
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root, allow_same_family=True)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-prompt-drift"],
        )

    def test_changed_gate_criterion_is_review_prompt_drift(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        original = cross_review_module.gate_for

        def rewritten(mode, stage):
            gate = original(mode, stage)
            return gate._replace(criterion=gate.criterion + "（改写）")

        with mock.patch.object(cross_review_module, "gate_for", rewritten):
            problems = check_review(self.paper_root, allow_same_family=True)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-prompt-drift"],
        )

    def test_unbuildable_prompt_is_review_prompt_unknown(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        state = {
            "target_venue": {"name": "NeurIPS", "mode": "not-a-mode"},
            "stage": {"current": "internal-review"},
        }
        (self.paper_root / "ccfa.yaml").write_text(
            yaml.safe_dump(state, sort_keys=False), encoding="utf-8"
        )

        problems = check_review(self.paper_root, allow_same_family=True)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-prompt-unknown"],
        )

    def test_blocking_record_is_review_blocking(self):
        quote = (
            "The baseline comparison omits the strongest published method "
            "entirely."
        )
        self.input_path.write_text(
            "\\documentclass{article}\n"
            "The baseline comparison omits the strongest\n"
            "published method entirely.\n",
            encoding="utf-8",
        )
        blocking = [{"title": "gap", "evidence": f'main.tex: "{quote}"'}]
        runner = self._runner(payload=self._payload("blocking", blocking))
        self._run(runner)

        problems = check_review(self.paper_root)

        self.assertEqual([problem.code for problem in problems], ["review-blocking"])

    def test_fabricated_blocking_quote_is_uncited(self):
        self.input_path.write_text(
            "\\documentclass{article}\n"
            "The paper reports a small controlled study.\n",
            encoding="utf-8",
        )
        blocking = [
            {
                "title": "gap",
                "evidence": (
                    'main.tex: "The baseline comparison omits the strongest '
                    'published method entirely."'
                ),
            }
        ]
        runner = self._runner(payload=self._payload("blocking", blocking))
        self._run(runner)

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-blocking", "review-uncited-blocking"],
        )
        uncited = next(
            problem
            for problem in problems
            if problem.code == "review-uncited-blocking"
        )
        self.assertIn("gap", uncited.message)

    def test_quote_shorter_than_twenty_characters_is_uncited(self):
        self.input_path.write_text("short quote here\n", encoding="utf-8")
        blocking = [
            {"title": "short", "evidence": 'main.tex: "short quote here"'}
        ]
        runner = self._runner(payload=self._payload("blocking", blocking))
        self._run(runner)

        problems = check_review(self.paper_root)

        self.assertIn(
            "review-uncited-blocking",
            [problem.code for problem in problems],
        )

    def test_whole_evidence_substring_short_circuits_the_matcher(self):
        sentence = (
            "The baseline comparison omits the strongest published method "
            "entirely."
        )
        self.input_path.write_text(sentence + "\n", encoding="utf-8")
        blocking = [{"title": "gap", "evidence": sentence}]
        runner = self._runner(payload=self._payload("blocking", blocking))
        self._run(runner)
        calls = []
        real = cross_review_module._longest_quote_length

        def counting(evidence, corpus):
            calls.append((evidence, corpus))
            return real(evidence, corpus)

        with mock.patch(
            "ccfa.cross_review._longest_quote_length",
            side_effect=counting,
        ):
            problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-blocking"],
        )
        self.assertEqual(calls, [], "short path must not call the matcher")

    def test_cross_newline_quote_falls_back_to_the_substring_match(self):
        sentence = (
            "The baseline comparison omits the strongest published method "
            "entirely."
        )
        self.input_path.write_text(
            "The baseline comparison omits the strongest\n"
            "published method entirely.\n",
            encoding="utf-8",
        )
        blocking = [{"title": "gap", "evidence": f'main.tex: "{sentence}"'}]
        runner = self._runner(payload=self._payload("blocking", blocking))
        self._run(runner)
        calls = []
        real = cross_review_module._longest_quote_length

        def counting(evidence, corpus):
            calls.append((evidence, corpus))
            return real(evidence, corpus)

        with mock.patch(
            "ccfa.cross_review._longest_quote_length",
            side_effect=counting,
        ):
            problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-blocking"],
        )
        self.assertEqual(len(calls), 1)

    def test_uncited_blocking_check_exits_one(self):
        self.input_path.write_text(
            "\\documentclass{article}\n",
            encoding="utf-8",
        )
        blocking = [
            {
                "title": "gap",
                "evidence": (
                    'main.tex: "This sentence was never in the manuscript '
                    'at all, honestly."'
                ),
            }
        ]
        runner = self._runner(payload=self._payload("blocking", blocking))
        self._run(runner)

        code, stdout, stderr = self._run_main(
            [
                "cross-review",
                "check",
                "--paper-root",
                str(self.paper_root),
            ]
        )

        self.assertEqual(code, 1)
        payload = json.loads(stdout)
        self.assertIn(
            "review-uncited-blocking",
            [problem["code"] for problem in payload["problems"]],
        )
        self.assertIn("review-uncited-blocking", stderr)

    def test_malformed_record_is_review_malformed(self):
        path = self._record_path()
        path.parent.mkdir(parents=True)
        path.write_text("{bad json", encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual([problem.code for problem in problems], ["review-malformed"])

    def test_input_hash_path_escape_is_record_invalid(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        outside = self.paper_root.parent / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["input_hashes"] = {
            "../outside.txt": "sha256:"
            + hashlib.sha256(outside.read_bytes()).hexdigest()
        }
        self._record_path().write_text(
            json.dumps(record),
            encoding="utf-8",
        )

        problems = check_review(self.paper_root)

        self.assertEqual([problem.code for problem in problems], ["review-record-invalid"])

    def test_check_out_dir_reads_non_default_record(self):
        runner = self._runner(payload=self._payload())
        self._run(runner, out_dir=Path("custom-reviews"))

        code, stdout, stderr = self._run_main(
            [
                "cross-review",
                "check",
                "--paper-root",
                str(self.paper_root),
                "--out-dir",
                "custom-reviews",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["problem_count"], 0)
        self.assertEqual(stderr, "")

    def test_check_default_out_dir_behavior_is_unchanged(self):
        code, stdout, stderr = self._run_main(
            [
                "cross-review",
                "check",
                "--paper-root",
                str(self.paper_root),
            ]
        )

        report = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(report["problems"][0]["code"], "review-missing")
        self.assertIn("review-missing", stderr)


class TestMainAndHelp(CrossReviewTests):
    def test_help_states_config_based_provenance_and_no_execution_model_flag(self):
        stdout = StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            main(["cross-review", "--help"])

        self.assertEqual(raised.exception.code, 0)
        text = stdout.getvalue()
        self.assertIn("Codex", text)
        self.assertIn("provenance", text)
        self.assertNotIn("--execution-model", text)

    def test_run_and_check_help_expose_codex_config(self):
        for command in ("run", "check"):
            stdout = StringIO()
            with redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
                main(["cross-review", command, "--help"])

            self.assertEqual(raised.exception.code, 0)
            self.assertIn("--codex-config", stdout.getvalue())

    def test_main_run_pass_zero_blocking_one_and_oserror_two(self):
        with mock.patch("ccfa.cross_review.run_review", side_effect=lambda *a, **k: {"verdict": "pass"}):
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "cross-review",
                            "run",
                            "--paper-root",
                            str(self.paper_root),
                            "--stage",
                            "internal-review",
                        "--path",
                        "manuscript/main.tex",
                        "--model",
                        "deepseek-v4-pro",
                        ]
                    ),
                    0,
                )

        with mock.patch("ccfa.cross_review.run_review", side_effect=lambda *a, **k: {"verdict": "blocking"}):
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "cross-review",
                            "run",
                            "--paper-root",
                            str(self.paper_root),
                            "--stage",
                            "internal-review",
                        "--path",
                        "manuscript/main.tex",
                        "--model",
                        "deepseek-v4-pro",
                        ]
                    ),
                    1,
                )

        with mock.patch(
            "ccfa.cross_review.run_review",
            side_effect=ValueError("无法运行 codex exec"),
        ):
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "cross-review",
                            "run",
                            "--paper-root",
                            str(self.paper_root),
                            "--stage",
                            "internal-review",
                        "--path",
                        "manuscript/main.tex",
                        "--model",
                        "deepseek-v4-pro",
                        ]
                    ),
                    2,
                )


if __name__ == "__main__":
    unittest.main()
