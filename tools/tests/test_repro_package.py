import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ccfa.cli import ToolEnvironmentError
from ccfa.repro_package import (
    MANIFEST_NAME,
    build_manifest,
    create_bundle,
    load_manifest,
    sha256_of,
    verify_bundle,
)


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "src").mkdir()
        (self.root / "src" / "train.py").write_text("print('train')\n", encoding="utf-8")
        (self.root / "configs").mkdir()
        (self.root / "configs" / "a.yaml").write_text("epochs: 5\n", encoding="utf-8")
        (self.root / "requirements.txt").write_text("numpy\n", encoding="utf-8")
        self.out = self.root / "bundles" / "result3"

    def manifest(self, **overrides):
        kwargs = dict(
            paper_root=self.root,
            files=["src/train.py", "configs/a.yaml"],
            command=["{python}", "src/train.py", "--config", "configs/a.yaml"],
            requirements="requirements.txt",
            notes="Table 3",
        )
        kwargs.update(overrides)
        return build_manifest(**kwargs)


class TestBuildManifest(BaseCase):
    def test_records_files_sorted_with_hashes_and_sizes(self):
        manifest = self.manifest()
        self.assertEqual([item["path"] for item in manifest["files"]], ["configs/a.yaml", "src/train.py"])
        first = manifest["files"][0]
        self.assertEqual(first["sha256"], sha256_of(self.root / "configs" / "a.yaml"))
        self.assertEqual(first["size"], (self.root / "configs" / "a.yaml").stat().st_size)

    def test_records_command_verbatim_as_argv(self):
        manifest = self.manifest()
        self.assertEqual(manifest["command"][0], "{python}")
        self.assertEqual(manifest["command"][2], "--config")

    def test_command_without_python_placeholder_is_rejected(self):
        with self.assertRaises(ValueError):
            self.manifest(command=["python", "src/train.py"])

    def test_records_requirements_hash(self):
        manifest = self.manifest()
        self.assertEqual(manifest["requirements"]["path"], "requirements.txt")
        self.assertTrue(manifest["requirements"]["sha256"].startswith("sha256:"))

    def test_requirements_is_null_when_absent(self):
        self.assertIsNone(self.manifest(requirements=None)["requirements"])

    def test_absolute_path_is_rejected(self):
        with self.assertRaises(ValueError):
            self.manifest(files=[str(self.root / "src" / "train.py")])

    def test_parent_escape_is_rejected(self):
        outside = self.root.parent / "outside.txt"
        outside.write_text("x\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.manifest(files=["../outside.txt"])

    def test_missing_file_is_rejected(self):
        with self.assertRaises(ValueError):
            self.manifest(files=["src/gone.py"])

    def test_version_is_one_and_platform_is_recorded(self):
        manifest = self.manifest()
        self.assertEqual(manifest["version"], 1)
        self.assertIn("python", manifest)
        self.assertIn("platform", manifest)
        self.assertIn("created_at", manifest)


class TestCreateBundle(BaseCase):
    def test_copies_files_preserving_structure(self):
        create_bundle(self.root, self.out, self.manifest())
        self.assertTrue((self.out / "files" / "src" / "train.py").is_file())
        self.assertTrue((self.out / "files" / "configs" / "a.yaml").is_file())

    def test_writes_a_readable_manifest(self):
        create_bundle(self.root, self.out, self.manifest())
        loaded = load_manifest(self.out)
        self.assertEqual(loaded["version"], 1)
        self.assertEqual(len(loaded["files"]), 2)

    def test_manifest_hashes_match_the_copied_bytes(self):
        create_bundle(self.root, self.out, self.manifest())
        loaded = load_manifest(self.out)
        for item in loaded["files"]:
            self.assertEqual(sha256_of(self.out / "files" / item["path"]), item["sha256"])

    def test_existing_bundle_is_not_overwritten_without_force(self):
        create_bundle(self.root, self.out, self.manifest())
        (self.out / "KEEP").write_text("keep\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            create_bundle(self.root, self.out, self.manifest())
        self.assertTrue((self.out / "KEEP").is_file())

    def test_precreated_empty_bundle_directory_is_accepted(self):
        self.out.mkdir(parents=True)

        create_bundle(self.root, self.out, self.manifest())

        self.assertTrue((self.out / MANIFEST_NAME).is_file())
        self.assertTrue((self.out / "files" / "src" / "train.py").is_file())

    def test_force_rebuilds_the_bundle(self):
        create_bundle(self.root, self.out, self.manifest())
        (self.out / "KEEP").write_text("keep\n", encoding="utf-8")
        create_bundle(self.root, self.out, self.manifest(), force=True)
        self.assertFalse((self.out / "KEEP").is_file())
        self.assertTrue((self.out / MANIFEST_NAME).is_file())

    def test_force_with_invalid_member_does_not_destroy_existing_bundle(self):
        create_bundle(self.root, self.out, self.manifest())
        keep = self.out / "KEEP"
        keep.write_text("keep\n", encoding="utf-8")
        bad = self.manifest()
        bad["files"][0]["path"] = "src/gone.py"
        with self.assertRaises(ValueError):
            create_bundle(self.root, self.out, bad, force=True)
        self.assertTrue(keep.is_file())

    def test_missing_manifest_version_is_rejected(self):
        bad = self.manifest()
        del bad["version"]
        with self.assertRaises(ValueError):
            create_bundle(self.root, self.out, bad)


class TestVerifyBundle(BaseCase):
    def _bundle(self):
        create_bundle(self.root, self.out, self.manifest())
        return self.out

    def _venv(self, path):
        path.mkdir(parents=True, exist_ok=True)
        return path / "python"

    def _codes(self, items):
        return sorted(i.code for i in items)

    def test_a_consistent_bundle_passes_and_reports_scope(self):
        bundle = self._bundle()
        problems, advisories = verify_bundle(
            bundle,
            venv_factory=self._venv,
            runner=lambda argv, cwd, timeout: (0, "ok\n"),
        )
        self.assertEqual(problems, [])
        self.assertEqual(self._codes(advisories), ["repro-output-tail", "repro-scope"])

    def test_successful_rerun_advisory_contains_output_tail(self):
        bundle = self._bundle()
        problems, advisories = verify_bundle(
            bundle,
            venv_factory=self._venv,
            runner=lambda argv, cwd, timeout: (0, "marker-output\n"),
        )
        self.assertEqual(problems, [])
        tail = next(item for item in advisories if item.code == "repro-output-tail")
        self.assertIn("marker-output", tail.message)

    def test_manifest_command_without_python_placeholder_is_rejected(self):
        bundle = self._bundle()
        manifest_path = bundle / MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["command"] = ["python", "src/train.py"]
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            verify_bundle(
                bundle,
                venv_factory=self._venv,
                runner=lambda argv, cwd, timeout: (0, ""),
            )

    def test_tampered_file_is_reported_as_incomplete(self):
        bundle = self._bundle()
        (bundle / "files" / "src" / "train.py").write_text("tampered\n", encoding="utf-8")
        problems, _ = verify_bundle(
            bundle, venv_factory=self._venv, runner=lambda a, c, t: (0, "")
        )
        self.assertEqual(self._codes(problems), ["repro-bundle-incomplete"])

    def test_nonzero_rerun_is_reported(self):
        bundle = self._bundle()

        def install_runner(argv, cwd, timeout):
            return 0, "installed\n"

        def run_runner(argv, cwd, timeout):
            return 3, "boom\n"

        problems, _ = verify_bundle(
            bundle,
            venv_factory=self._venv,
            install_runner=install_runner,
            runner=run_runner,
        )
        self.assertEqual(self._codes(problems), ["repro-rerun-failed"])

    def test_timeout_is_reported_as_rerun_failed(self):
        bundle = self._bundle()

        def runner(argv, cwd, timeout):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout)

        problems, _ = verify_bundle(
            bundle,
            venv_factory=self._venv,
            install_runner=lambda argv, cwd, timeout: (0, "installed\n"),
            runner=runner,
        )
        self.assertEqual(self._codes(problems), ["repro-rerun-failed"])
        self.assertIn("超时", problems[0].message)

    def test_install_failure_is_the_primary_finding(self):
        bundle = self._bundle()
        run_calls = []

        def run_runner(argv, cwd, timeout):
            run_calls.append(list(argv))
            return 0, "ran\n"

        problems, _ = verify_bundle(
            bundle,
            venv_factory=self._venv,
            install_runner=lambda argv, cwd, timeout: (7, "missing dependency\n"),
            runner=run_runner,
        )

        self.assertEqual(self._codes(problems), ["repro-install-failed"])
        self.assertIn("missing dependency", problems[0].message)
        self.assertIn("未尝试重跑", problems[0].message)
        self.assertEqual(run_calls, [])

    def test_venv_creation_failure_is_a_tool_error(self):
        bundle = self._bundle()

        def broken_venv(path):
            raise ToolEnvironmentError("找不到解释器")

        with self.assertRaises(ToolEnvironmentError):
            verify_bundle(bundle, venv_factory=broken_venv, runner=lambda a, c, t: (0, ""))

    def test_command_is_passed_as_argv_without_a_shell(self):
        bundle = self._bundle()
        seen = {}

        def runner(argv, cwd, timeout):
            seen["argv"] = list(argv)
            return 0, ""

        verify_bundle(bundle, venv_factory=self._venv, runner=runner)
        self.assertIsInstance(seen["argv"], list)
        self.assertTrue(seen["argv"][0].endswith("python"))
        self.assertNotIn("{python}", seen["argv"])

    def test_verify_does_not_modify_the_bundle(self):
        writer = self.root / "writer.py"
        writer.write_text(
            "from pathlib import Path\n"
            "Path('output.txt').write_text('written\\n', encoding='utf-8')\n"
            "print('writer-output')\n",
            encoding="utf-8",
        )
        manifest = build_manifest(
            self.root,
            ["writer.py"],
            ["{python}", "writer.py"],
            None,
            "writes relative output",
        )
        create_bundle(self.root, self.out, manifest)
        bundle = self.out
        before = self._snapshot(bundle)
        verify_bundle(bundle, venv_factory=lambda path: Path(sys.executable))
        after = self._snapshot(bundle)
        self.assertEqual(after, before)
        self.assertFalse(any(bundle.rglob("output.txt")))

    def _snapshot(self, root):
        return {
            path.relative_to(root).as_posix(): sha256_of(path)
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }


if __name__ == "__main__":
    unittest.main()
