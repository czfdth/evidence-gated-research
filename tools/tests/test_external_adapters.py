"""Adapter capability checks.

``probe_adapter`` reports ``installed`` from the skill's source tree, so these
tests build their own tree instead of asserting against whatever skills happen
to be installed on the machine running them. The shipped ``adapters.yaml`` is
copied in verbatim so the definitions under test stay the real ones.
"""

import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.external_adapters import (
    probe_adapter,
    validate_adapters,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SKILLS = ("exa-search", "pyzotero")


class ExternalAdapterTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self._write_fixture()

    def _write_fixture(self):
        skills = self.root / "skills"
        skills.mkdir(parents=True, exist_ok=True)
        (skills / "adapters.yaml").write_text(
            (ROOT / "skills" / "adapters.yaml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (skills / "registry.yaml").write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "skills": [
                        {"id": name, "path": f"skills/{name}"}
                        for name in FIXTURE_SKILLS
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        for name in FIXTURE_SKILLS:
            directory = skills / name
            directory.mkdir(exist_ok=True)
            (directory / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")

    def test_repository_adapters_are_valid(self):
        self.assertEqual(validate_adapters(ROOT), [])

    def test_env_adapter_is_configured_without_exposing_values(self):
        result = probe_adapter(
            self.root,
            "exa",
            environ={"EXA_API_KEY": "secret-value"},
        )

        self.assertTrue(result["installed"])
        self.assertEqual(result["configured"], "yes")
        self.assertEqual(result["functional"], "not-checked")
        self.assertFalse(result["ready"])
        self.assertNotIn("secret-value", str(result))

    def test_local_adapter_requires_a_functional_probe(self):
        result = probe_adapter(self.root, "zotero-local", environ={})

        self.assertTrue(result["installed"])
        self.assertEqual(result["configured"], "yes")
        self.assertEqual(result["functional"], "not-checked")
        self.assertFalse(result["ready"])

    def test_missing_required_env_is_not_configured(self):
        result = probe_adapter(self.root, "exa", environ={})

        self.assertEqual(result["configured"], "no")
        self.assertFalse(result["ready"])

    def test_missing_skill_source_is_reported_as_not_installed(self):
        (self.root / "skills" / "exa-search" / "SKILL.md").unlink()

        result = probe_adapter(
            self.root,
            "exa",
            environ={"EXA_API_KEY": "secret-value"},
        )

        self.assertFalse(result["installed"])
        self.assertFalse(result["ready"])

    def test_unknown_adapter_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知 adapter"):
            probe_adapter(self.root, "does-not-exist", environ={})


if __name__ == "__main__":
    unittest.main()
