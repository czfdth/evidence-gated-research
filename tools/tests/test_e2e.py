import tempfile
import unittest
from pathlib import Path

from build.compile import compile_project
from ccfa.texdoc import find_main_tex
from ccfa.validate import validate_yaml
from newpaper.create import create_project


class TestEndToEnd(unittest.TestCase):
    def test_scaffold_validate_and_compile(self):
        papers = Path(tempfile.mkdtemp()) / "papers"
        root = create_project(
            papers_root=papers,
            slug="e2e-demo",
            venue="NeurIPS",
            year="2027",
            mode="conference",
            title="E2E Demo",
        )

        self.assertEqual(validate_yaml(root / "ccfa.yaml"), [])

        main_tex = find_main_tex(root / "manuscript")
        result = compile_project(main_tex, root / "ccfa-workfiles" / "build")
        self.assertTrue(result.ok, f"编译失败:\n{result.log_tail}")
        self.assertTrue(result.pdf.is_file())

    def test_journal_mode_scaffold_validates(self):
        papers = Path(tempfile.mkdtemp()) / "papers"
        root = create_project(
            papers_root=papers,
            slug="journal-demo",
            venue="NeurIPS",
            year="2027",
            mode="journal",
            title="Journal Demo",
        )
        self.assertEqual(validate_yaml(root / "ccfa.yaml"), [])
        text = (root / "ccfa.yaml").read_text(encoding="utf-8")
        self.assertIn('mode: "journal"', text)
