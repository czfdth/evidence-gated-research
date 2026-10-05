import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from install import fetch_toolchain as ft


def _artifact(**overrides):
    base = {
        "key": "demo",
        "version": "1.0",
        "urls": ("https://example.test/demo.zip",),
        "archive": "zip",
        "bin_dir": "demo-1.0/bin",
        "executables": ("demo.exe",),
    }
    base.update(overrides)
    return ft.Artifact(**base)


class SourcePathTests(unittest.TestCase):
    def test_tools_token_is_expanded(self):
        artifact = _artifact(source_paths=("{tools}\\demo\\demo.exe",))

        paths = ft._source_paths(artifact, Path("F:/codex-tools"))

        self.assertEqual(paths, (Path("F:/codex-tools/demo/demo.exe"),))

    def test_glob_expands_versioned_install_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "qpdf 12.4.2" / "bin").mkdir(parents=True)
            (root / "qpdf 11.0.0" / "bin").mkdir(parents=True)
            (root / "qpdf 12.4.2" / "bin" / "qpdf.exe").write_bytes(b"x")
            (root / "qpdf 11.0.0" / "bin" / "qpdf.exe").write_bytes(b"y")
            artifact = _artifact(source_paths=(str(root / "qpdf*" / "bin" / "qpdf.exe"),))

            paths = ft._source_paths(artifact, root)

        self.assertEqual(len(paths), 2)
        self.assertTrue(all(path.name == "qpdf.exe" for path in paths))

    def test_missing_literal_path_is_kept_for_the_caller_to_filter(self):
        artifact = _artifact(source_paths=("{tools}\\nope.exe",))

        paths = ft._source_paths(artifact, Path("F:/codex-tools"))

        self.assertEqual(len(paths), 1)
        self.assertFalse(paths[0].exists())


class ExternalExecutableTests(unittest.TestCase):
    def test_path_hit_outside_the_shim_dir_is_external(self):
        with mock.patch.object(
            ft.shutil, "which", return_value=r"C:\Program Files\qpdf\bin\qpdf.exe"
        ):
            found = ft._external_executable(("qpdf.exe",), Path("F:/codex-tools/bin"))

        self.assertEqual(found, r"C:\Program Files\qpdf\bin\qpdf.exe")

    def test_own_shim_is_not_counted_as_external(self):
        with tempfile.TemporaryDirectory() as tmp:
            shim_dir = Path(tmp) / "bin"
            shim_dir.mkdir()
            shim = shim_dir / "qpdf.cmd"
            shim.write_text("@echo off\n", encoding="utf-8")
            with mock.patch.object(ft.shutil, "which", return_value=str(shim)):
                found = ft._external_executable(("qpdf.exe",), shim_dir)

        self.assertIsNone(found)

    def test_missing_executable_returns_none(self):
        with mock.patch.object(ft.shutil, "which", return_value=None):
            self.assertIsNone(ft._external_executable(("qpdf.exe",), Path("F:/codex-tools/bin")))

    def test_drop_shims_removes_only_named_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            shim_dir = Path(tmp)
            (shim_dir / "qpdf.cmd").write_text("x", encoding="utf-8")
            (shim_dir / "typst.cmd").write_text("x", encoding="utf-8")

            removed = ft._drop_shims(_artifact(executables=("qpdf.exe",)), shim_dir)

            self.assertEqual(len(removed), 1)
            self.assertFalse((shim_dir / "qpdf.cmd").exists())
            self.assertTrue((shim_dir / "typst.cmd").exists())


class ShimTests(unittest.TestCase):
    def test_shim_writes_cmd_and_removes_stale_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "demo"
            real = dest / "demo-1.0" / "bin" / "demo.exe"
            real.parent.mkdir(parents=True)
            real.write_bytes(b"MZ")
            shim_dir = Path(tmp) / "bin"
            shim_dir.mkdir()
            (shim_dir / "demo.exe").write_text("stale", encoding="utf-8")
            artifact = _artifact()

            written = ft._shim(artifact, dest, shim_dir)

            self.assertEqual(written, [str(real)])
            shim = shim_dir / "demo.cmd"
            self.assertTrue(shim.is_file())
            self.assertIn(str(real), shim.read_text(encoding="utf-8"))
            self.assertFalse((shim_dir / "demo.exe").exists())


class ExtractTests(unittest.TestCase):
    def test_zip_and_auto_archives_share_the_zip_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "demo.zip"
            with zipfile.ZipFile(bundle, "w") as archive:
                archive.writestr("demo-1.0/bin/demo.exe", "MZ")
            for archive_kind in ("zip", "auto"):
                target = root / f"out-{archive_kind}"
                ft._extract(_artifact(archive=archive_kind), bundle, target)
                self.assertTrue((target / "demo-1.0" / "bin" / "demo.exe").is_file())

    def test_unknown_archive_kind_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ft._extract(
                    _artifact(archive="rar"),
                    Path(tmp) / "x.rar",
                    Path(tmp) / "out",
                )


class InstallTests(unittest.TestCase):
    def test_external_install_short_circuits_without_downloading(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            with (
                mock.patch.object(
                    ft, "_external_executable", return_value=r"C:\Program Files\qpdf.exe"
                ),
                mock.patch.object(ft, "_download") as download,
            ):
                records = ft.install(
                    (_artifact(),),
                    dest=dest,
                    cache=dest / ".cache",
                    jobs=1,
                )

        self.assertEqual(records[0]["status"], "already-present")
        download.assert_not_called()

    def test_auto_artifact_prefers_system_path_over_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            real = dest / "system" / "qpdf.exe"
            real.parent.mkdir(parents=True)
            real.write_bytes(b"MZ")
            artifact = _artifact(
                archive="auto",
                source_paths=(str(real),),
                executables=("qpdf.exe",),
            )
            with (
                mock.patch.object(ft, "_external_executable", return_value=None),
                mock.patch.object(ft, "_download") as download,
            ):
                records = ft.install((artifact,), dest=dest, cache=dest / ".cache", jobs=1)

        self.assertEqual(records[0]["status"], "installed")
        self.assertEqual(records[0]["source"], str(real))
        download.assert_not_called()

    def test_auto_artifact_falls_back_to_download_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            artifact = _artifact(
                archive="auto",
                source_paths=(str(dest / "missing" / "qpdf.exe"),),
            )
            with (
                mock.patch.object(ft, "_external_executable", return_value=None),
                mock.patch.object(ft, "_download") as download,
            ):
                download.side_effect = RuntimeError("offline")
                records = ft.install((artifact,), dest=dest, cache=dest / ".cache", jobs=1)

        self.assertEqual(records[0]["status"], "failed")
        download.assert_called_once()

    def test_force_ignores_an_external_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            with (
                mock.patch.object(
                    ft, "_external_executable", return_value=r"C:\Program Files\qpdf.exe"
                ),
                mock.patch.object(ft, "_download", side_effect=RuntimeError("offline")),
            ):
                records = ft.install(
                    (_artifact(),),
                    dest=dest,
                    cache=dest / ".cache",
                    jobs=1,
                    force=True,
                )

        self.assertEqual(records[0]["status"], "failed")


class RegistryTests(unittest.TestCase):
    def test_mutool_points_at_the_slimmed_runtime(self):
        mutool = ft.BY_KEY["mutool"]

        self.assertEqual(mutool.archive, "existing")
        self.assertEqual(mutool.source_paths, ("{tools}\\mutool\\mutool.exe",))

    def test_qpdf_and_quarto_prefer_system_installs(self):
        for key in ("qpdf", "quarto"):
            with self.subTest(key=key):
                artifact = ft.BY_KEY[key]
                self.assertEqual(artifact.archive, "auto")
                self.assertTrue(any("Program Files" in item for item in artifact.source_paths))

    def test_every_artifact_declares_what_it_exposes(self):
        for artifact in ft.ARTIFACTS:
            with self.subTest(key=artifact.key):
                self.assertTrue(artifact.executables)


if __name__ == "__main__":
    unittest.main()
