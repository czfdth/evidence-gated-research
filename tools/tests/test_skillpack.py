import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ccfa.skillpack import (
    MANIFEST_NAME,
    build_pack,
    describe,
    main,
    unpack_pack,
    verify_pack,
)

HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None


class SkillpackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "skills"
        (self.source / "ccf-demo" / "references").mkdir(parents=True)
        (self.source / "ccf-demo" / "SKILL.md").write_text(
            "# ccf-demo\n\nbody\n", encoding="utf-8"
        )
        (self.source / "ccf-demo" / "references" / "notes.md").write_text(
            "notes\n", encoding="utf-8"
        )
        self.pack = self.root / "ccf-demo.skillpack"

    def _build(self, **overrides):
        kwargs = {
            "pack_id": "ccf-demo",
            "version": "2026.10.06",
            "roles": ["executor"],
            "created_at": "2026-10-06T00:00:00Z",
        }
        kwargs.update(overrides)
        return build_pack(self.source, self.pack, **kwargs)

    def test_pack_then_verify_is_clean(self):
        manifest = self._build()

        self.assertEqual(manifest["file_count"], 2)
        self.assertEqual(verify_pack(self.pack), [])
        with zipfile.ZipFile(self.pack) as archive:
            stored = json.loads(archive.read(MANIFEST_NAME))
        self.assertEqual(
            sorted(item["path"] for item in stored["files"]),
            ["ccf-demo/SKILL.md", "ccf-demo/references/notes.md"],
        )
        for item in stored["files"]:
            with self.subTest(path=item["path"]):
                self.assertTrue(item["sha256"].startswith("sha256:"))
                self.assertEqual(item["stored_sha256"][:7], "sha256:")
                self.assertIsNone(item["nonce"])

    def test_verify_detects_a_tampered_member(self):
        self._build()
        with zipfile.ZipFile(self.pack) as archive:
            members = {
                info.filename: archive.read(info.filename)
                for info in archive.infolist()
            }
        members["payload/ccf-demo/SKILL.md"] = b"# injected\n"
        with zipfile.ZipFile(self.pack, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in members.items():
                archive.writestr(name, payload)

        codes = [problem.code for problem in verify_pack(self.pack)]

        self.assertIn("skillpack-member-tampered", codes)

    def test_verify_reports_unlisted_members(self):
        self._build()
        with zipfile.ZipFile(self.pack, "a", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("payload/extra.md", "extra\n")

        codes = [problem.code for problem in verify_pack(self.pack)]

        self.assertIn("skillpack-unlisted-member", codes)

    def test_verify_rejects_path_traversal_entries(self):
        self._build()
        with zipfile.ZipFile(self.pack) as archive:
            members = {
                info.filename: archive.read(info.filename)
                for info in archive.infolist()
            }
        manifest = json.loads(members[MANIFEST_NAME])
        manifest["files"][0]["path"] = "../escape.md"
        members[MANIFEST_NAME] = json.dumps(manifest).encode("utf-8")
        with zipfile.ZipFile(self.pack, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in members.items():
                archive.writestr(name, payload)

        codes = [problem.code for problem in verify_pack(self.pack)]

        self.assertIn("skillpack-bad-entry", codes)

    def test_pack_is_deterministic_for_the_same_tree(self):
        first = self._build()
        digest_one = Path(self.pack).read_bytes()
        self.pack.unlink()
        second = self._build()

        self.assertEqual(first["manifest_sha256"], second["manifest_sha256"])
        self.assertEqual(digest_one, Path(self.pack).read_bytes())

    def test_unpack_round_trips_the_tree(self):
        self._build()
        dest = self.root / "unpacked"

        unpack_pack(self.pack, dest)

        self.assertEqual(
            (dest / "ccf-demo" / "SKILL.md").read_text(encoding="utf-8"),
            "# ccf-demo\n\nbody\n",
        )
        self.assertEqual(
            (dest / "ccf-demo" / "references" / "notes.md").read_text(
                encoding="utf-8"
            ),
            "notes\n",
        )

    def test_unpack_refuses_to_overwrite_without_force(self):
        self._build()
        dest = self.root / "unpacked"

        unpack_pack(self.pack, dest)

        with self.assertRaises(ValueError):
            unpack_pack(self.pack, dest)

    def test_pack_refuses_to_overwrite_without_force(self):
        self._build()

        with self.assertRaises(ValueError):
            self._build()

    def test_list_reports_pack_metadata(self):
        self._build()

        summary = describe(self.pack)

        self.assertEqual(summary["pack_id"], "ccf-demo")
        self.assertEqual(summary["file_count"], 2)
        self.assertFalse(summary["encrypted"])

    def test_cli_pack_and_verify(self):
        out = self.root / "cli.skillpack"
        code = main(
            [
                "ccfa-skillpack",
                "pack",
                "--source",
                str(self.source),
                "--out",
                str(out),
                "--pack-id",
                "cli",
                "--version",
                "1",
                "--created-at",
                "2026-10-06T00:00:00Z",
            ]
        )
        self.assertEqual(code, 0)

        self.assertEqual(main(["ccfa-skillpack", "verify", str(out)]), 0)

    def test_encrypt_requires_a_passphrase(self):
        code = main(
            [
                "ccfa-skillpack",
                "pack",
                "--source",
                str(self.source),
                "--out",
                str(self.pack),
                "--pack-id",
                "x",
                "--version",
                "1",
                "--encrypt",
            ]
        )

        self.assertEqual(code, 2)
        self.assertFalse(self.pack.exists())

    @unittest.skipUnless(HAS_CRYPTO, "cryptography is not installed")
    def test_encrypted_pack_round_trip_and_wrong_passphrase(self):
        manifest = self._build(passphrase=b"correct horse")

        self.assertEqual(manifest["encryption"]["algorithm"], "AES-256-GCM")
        self.assertIn(
            "skillpack-locked",
            [problem.code for problem in verify_pack(self.pack)],
        )
        self.assertIn(
            "skillpack-bad-passphrase",
            [problem.code for problem in verify_pack(self.pack, b"wrong")],
        )
        self.assertEqual(verify_pack(self.pack, b"correct horse"), [])
        dest = self.root / "unpacked"
        unpack_pack(self.pack, dest, b"correct horse")
        self.assertEqual(
            (dest / "ccf-demo" / "SKILL.md").read_text(encoding="utf-8"),
            "# ccf-demo\n\nbody\n",
        )
        with self.assertRaises(ValueError):
            unpack_pack(self.pack, self.root / "other", b"wrong")


if __name__ == "__main__":
    unittest.main()
