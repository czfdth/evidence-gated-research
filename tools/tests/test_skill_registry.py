import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.skill_registry import (
    install_skills,
    pack_skill,
    resolve,
    validate_registry,
)
from ccfa.skillpack import verify_pack


ROOT = Path(__file__).resolve().parents[2]


class SkillRegistryTests(unittest.TestCase):
    def test_repository_registry_is_valid(self):
        self.assertEqual(validate_registry(ROOT), [])

    def test_dependencies_resolve_before_dependents(self):
        order = resolve(ROOT, ["ccfa-autoresearch"])

        self.assertEqual(
            order,
            ["ccfa-core", "ccfa-experiments", "ccfa-autoresearch"],
        )

    def test_pack_and_install_are_verifiable_and_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            packed = pack_skill(ROOT, "ccfa-core", temp / "packs")
            self.assertEqual(verify_pack(Path(packed["pack"])), [])

            installed = install_skills(
                ROOT,
                temp / "installed",
                ["ccfa-autoresearch"],
            )

            self.assertEqual(
                [item["skill_id"] for item in installed],
                ["ccfa-core", "ccfa-experiments", "ccfa-autoresearch"],
            )
            self.assertTrue(
                (temp / "installed" / "ccfa-core" / "SKILL.md").is_file()
            )
            self.assertTrue(
                (
                    temp
                    / "installed"
                    / "ccfa-autoresearch"
                    / ".ccfa-skill-install.json"
                ).is_file()
            )

    def test_cycle_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for skill_id, dependency in (("a", "b"), ("b", "a")):
                source = root / "skills" / skill_id
                source.mkdir(parents=True)
                (source / "SKILL.md").write_text("# skill\n", encoding="utf-8")
                (source / "skill.yaml").write_text(
                    yaml.safe_dump(
                        {
                            "id": skill_id,
                            "version": "1",
                            "entrypoint": "ccfa",
                            "dependencies": [dependency],
                        },
                        sort_keys=False,
                    ),
                    encoding="utf-8",
                )
            (root / "skills" / "registry.yaml").write_text(
                yaml.safe_dump(
                    {
                        "version": 1,
                        "skills": [
                            {
                                "id": "a",
                                "version": "1",
                                "path": "skills/a",
                                "description": "a",
                                "dependencies": ["b"],
                            },
                            {
                                "id": "b",
                                "version": "1",
                                "path": "skills/b",
                                "description": "b",
                                "dependencies": ["a"],
                            },
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            problems = validate_registry(root)

            self.assertIn(
                "skill-registry-cycle",
                [problem.code for problem in problems],
            )

    def test_external_source_can_be_packed_without_copying_it_into_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            external = root / "external"
            skill = external / "demo"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("# demo\n", encoding="utf-8")
            (root / "skills").mkdir()
            (root / "skills" / "registry.yaml").write_text(
                yaml.safe_dump(
                    {
                        "version": 1,
                        "source_roots": {"external": "external"},
                        "skills": [
                            {
                                "id": "demo",
                                "source": {"root": "external", "path": "demo"},
                                "description": "demo skill",
                                "dependencies": [],
                            }
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            packed = pack_skill(root, "demo", root / "packs")

            self.assertTrue(Path(packed["pack"]).is_file())
            self.assertTrue(packed["version"].startswith("content-"))
            self.assertEqual(verify_pack(Path(packed["pack"])), [])

    def test_missing_external_source_is_advisory_unless_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "skills").mkdir()
            (root / "skills" / "registry.yaml").write_text(
                yaml.safe_dump(
                    {
                        "version": 1,
                        "source_roots": {"external": "missing"},
                        "skills": [
                            {
                                "id": "demo",
                                "source": {"root": "external", "path": "demo"},
                                "description": "demo skill",
                                "dependencies": [],
                            }
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            self.assertEqual(validate_registry(root), [])
            self.assertIn(
                "skill-registry-source-missing",
                [
                    problem.code
                    for problem in validate_registry(root, strict_external=True)
                ],
            )


if __name__ == "__main__":
    unittest.main()
