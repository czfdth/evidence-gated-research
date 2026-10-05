import os
import unittest
from unittest import mock

from ccfa_gui import appearance, theme


class ThemePaletteTests(unittest.TestCase):
    def test_light_and_dark_define_the_same_tokens(self):
        self.assertEqual(sorted(theme.LIGHT), sorted(theme.DARK))

    def test_palette_keys_are_all_hex_colours(self):
        for mode, values in theme.PALETTES.items():
            for key, value in values.items():
                with self.subTest(mode=mode, token=key):
                    self.assertRegex(value, r"^#[0-9a-f]{6}$")

    def test_normalise_mode_falls_back_to_light(self):
        for value in (None, "", "  ", "solarized", 12):
            with self.subTest(value=value):
                self.assertEqual(theme.normalise_mode(value), "light")
        self.assertEqual(theme.normalise_mode("Dark"), "dark")

    def test_stylesheets_differ_and_use_their_own_canvas(self):
        light = theme.stylesheet("light")
        dark = theme.stylesheet("dark")

        self.assertNotEqual(light, dark)
        self.assertIn(theme.LIGHT["canvas"], light)
        self.assertIn(theme.DARK["canvas"], dark)
        self.assertIn(theme.DARK["panel"], dark)
        self.assertNotIn(theme.DARK["canvas"], light)

    def test_severity_colours_track_the_mode(self):
        self.assertEqual(
            theme.severity_color("错误", "light"),
            theme.LIGHT["problem"],
        )
        self.assertEqual(
            theme.severity_color("错误", "dark"),
            theme.DARK["problem"],
        )
        self.assertEqual(
            theme.severity_color("OK", "dark"),
            theme.DARK["ok"],
        )
        self.assertEqual(
            theme.severity_color("something-else", "dark"),
            theme.DARK["ink"],
        )


class AppearanceTests(unittest.TestCase):
    def test_env_override_wins_over_the_system_scheme(self):
        with mock.patch.dict(os.environ, {appearance.MODE_ENV: "dark"}):
            self.assertEqual(appearance.current_mode(), "dark")
        with mock.patch.dict(os.environ, {appearance.MODE_ENV: "  LIGHT "}):
            self.assertEqual(appearance.current_mode(), "light")

    def test_unknown_override_falls_back_to_a_known_mode(self):
        with mock.patch.dict(os.environ, {appearance.MODE_ENV: "midnight"}):
            self.assertIn(appearance.current_mode(), {"light", "dark"})


if __name__ == "__main__":
    unittest.main()
