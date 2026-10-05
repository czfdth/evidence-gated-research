import unittest
from pathlib import Path

TEMPLATE_ROOT = Path(__file__).resolve().parents[2]


def root_anchored_dir_rule_matches(rule: str, repo_relative_path: str) -> bool:
    """Evaluate a gitignore rule shaped `/name/` against a repo-relative path."""
    pattern = rule.strip()
    if not pattern.startswith("/") or not pattern.endswith("/"):
        raise ValueError(f"仅支持形如 /name/ 的仓库根锚定目录规则: {rule!r}")
    prefix = pattern[1:-1]
    return repo_relative_path == prefix or repo_relative_path.startswith(prefix + "/")


class TestScaffoldContract(unittest.TestCase):
    def test_required_directories_exist(self):
        required = [
            "checklists",
            "library",
            "library/papers",
            "tools/ccfa",
            "tools/newpaper",
            "tools/build",
            "tools/tests",
        ]
        for rel in required:
            with self.subTest(rel=rel):
                self.assertTrue((TEMPLATE_ROOT / rel).is_dir(), f"缺少目录: {rel}")

    def test_gitignore_excludes_build_products(self):
        gitignore = (TEMPLATE_ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in ["tools/.venv/", "*.aux", "*.log", "*.pdf"]:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, gitignore)
        lines = [line.strip() for line in gitignore.splitlines()]
        with self.subTest(pattern="/papers/"):
            self.assertIn("/papers/", lines, "缺少整行忽略规则: /papers/")

    def test_derived_papers_rule_is_root_anchored(self):
        gitignore = (TEMPLATE_ROOT / ".gitignore").read_text(encoding="utf-8")
        patterns = [
            line.strip()
            for line in gitignore.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        derived = [p for p in patterns if p.lstrip("!").strip("/") == "papers"]
        self.assertEqual(
            derived, ["/papers/"], "派生论文目录规则必须是单行、锚定到仓库根的 /papers/"
        )
        rule = derived[0]
        self.assertFalse(
            root_anchored_dir_rule_matches(rule, "library/papers/.gitkeep"),
            "锚定规则 /papers/ 不得匹配 library/papers/.gitkeep",
        )
        self.assertTrue(
            root_anchored_dir_rule_matches(rule, "papers/demo-paper/ccfa.yaml"),
            "锚定规则 /papers/ 仍须匹配仓库根 papers/ 下的派生项目",
        )

    def test_papers_dir_kept_but_pdfs_ignored(self):
        gitignore = (TEMPLATE_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!library/papers/.gitkeep", gitignore)
        self.assertTrue((TEMPLATE_ROOT / "library" / "papers" / ".gitkeep").is_file())

    def test_contract_directories_are_non_empty(self):
        required = [
            "checklists",
            "library",
            "library/papers",
            "tools/ccfa",
            "tools/newpaper",
            "tools/build",
            "tools/tests",
        ]
        for rel in required:
            with self.subTest(rel=rel):
                self.assertTrue(
                    any((TEMPLATE_ROOT / rel).iterdir()),
                    f"目录为空,无法由 git 保留: {rel}",
                )
