import tempfile
import unittest
import zipfile
from pathlib import Path

from ccfa.artifact_store import (
    package_science,
    put_artifact,
    replay_artifact,
    verify_store,
)


class ArtifactStoreTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "figures").mkdir()
        (self.paper / "figures" / "plot.txt").write_text(
            "plot-v1\n",
            encoding="utf-8",
        )

    def test_put_creates_content_addressed_version(self):
        result = put_artifact(
            self.paper,
            "figures/plot.txt",
            role="figure",
            run_id="RUN1",
        )

        self.assertEqual(result["version"], 1)
        self.assertTrue((self.paper / "ccfa-workfiles" / "artifact-store" / "manifest.json").is_file())
        self.assertEqual(verify_store(self.paper), ([], []))

    def test_put_same_content_is_idempotent(self):
        first = put_artifact(self.paper, "figures/plot.txt", role="figure")
        second = put_artifact(self.paper, "figures/plot.txt", role="figure")

        self.assertEqual(second["version"], first["version"])
        self.assertFalse(second["created"])

    def test_changed_content_creates_new_version(self):
        put_artifact(self.paper, "figures/plot.txt", role="figure")
        (self.paper / "figures" / "plot.txt").write_text(
            "plot-v2\n",
            encoding="utf-8",
        )

        result = put_artifact(self.paper, "figures/plot.txt", role="figure")

        self.assertEqual(result["version"], 2)
        self.assertTrue(result["created"])

    def test_verify_detects_tampered_blob(self):
        result = put_artifact(self.paper, "figures/plot.txt", role="figure")
        blob = (
            self.paper
            / "ccfa-workfiles"
            / "artifact-store"
            / "blobs"
            / result["sha256"]
        )
        blob.write_text("tampered\n", encoding="utf-8")

        problems, _advisories = verify_store(self.paper)

        self.assertIn(
            "artifact-store-integrity",
            [problem.code for problem in problems],
        )

    def test_package_science_contains_manifest_and_blob(self):
        put_artifact(self.paper, "figures/plot.txt", role="figure")
        out = self.paper / "submission" / "paper.science"

        report = package_science(self.paper, out)

        self.assertTrue(out.is_file())
        self.assertGreater(report["file_count"], 0)
        with zipfile.ZipFile(out) as archive:
            names = set(archive.namelist())
        self.assertIn("manifest.json", names)
        self.assertIn("README.md", names)

    def test_replay_returns_versions(self):
        put_artifact(
            self.paper,
            "figures/plot.txt",
            role="figure",
            run_id="RUN1",
        )

        result = replay_artifact(self.paper, "figures/plot.txt")

        self.assertEqual(result["artifact_id"], "figures/plot.txt")
        self.assertEqual(result["versions"][0]["run_id"], "RUN1")


if __name__ == "__main__":
    unittest.main()
