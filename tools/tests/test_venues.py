import os
import unittest
from pathlib import Path

from newpaper.venues import VenueNotFound, resolve_venue, templates_root


class TestVenueResolution(unittest.TestCase):
    def test_templates_root_honours_codex_home(self):
        original = os.environ.get("CODEX_HOME")
        try:
            os.environ["CODEX_HOME"] = "C:/fake/codex"
            self.assertEqual(
                templates_root(), Path("C:/fake/codex/skills/ccf-latex-templates")
            )
        finally:
            if original is None:
                os.environ.pop("CODEX_HOME", None)
            else:
                os.environ["CODEX_HOME"] = original

    def test_known_venue_resolves_to_existing_directory(self):
        path = resolve_venue("NeurIPS")
        self.assertTrue(path.is_dir(), path)

    def test_venue_lookup_is_case_insensitive(self):
        self.assertEqual(resolve_venue("neurips"), resolve_venue("NeurIPS"))

    def test_unknown_venue_raises_with_available_list(self):
        with self.assertRaises(VenueNotFound) as ctx:
            resolve_venue("NotAVenue2099")
        self.assertIn("NotAVenue2099", str(ctx.exception))
        self.assertIn("NeurIPS", str(ctx.exception))
