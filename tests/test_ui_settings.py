"""Interface settings and themes, without opening a window: every theme sets every colour, and a settings file
from an older LumaTRX (with options since removed, like the logo style and header tint) still loads."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ui  # noqa: E402


class Themes(unittest.TestCase):
    def test_every_theme_sets_every_colour(self):
        keys = set(ui.THEMES["Console"])
        for name, theme in ui.THEMES.items():
            self.assertEqual(set(theme), keys, name)
            for k, v in theme.items():
                self.assertRegex(v, r"^#[0-9a-fA-F]{6}$", f"{name}.{k}")

    def test_there_is_a_green_theme(self):
        def green(hex_):
            r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
            return g > r and g > b
        self.assertTrue(any(green(t["CYAN"]) and green(t["PANEL"]) for t in ui.THEMES.values()))


class OldSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved_file, self.saved = ui.SETTINGS_FILE, {k: getattr(ui.S, k) for k in ui.LAYOUT_DEFAULTS}
        ui.SETTINGS_FILE = os.path.join(self.tmp, "ui_settings.json")

    def tearDown(self):
        ui.SETTINGS_FILE = self.saved_file
        for k, v in self.saved.items():
            setattr(ui.S, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_removed_options_load_and_are_dropped(self):
        with open(ui.SETTINGS_FILE, "w") as fh:
            json.dump(dict(theme="Forest", header_tint=True, logo_look=2, layout=1, scale=1.2), fh)
        ui.load_layout()
        self.assertEqual((ui.S.theme, ui.S.layout, ui.S.scale), ("Forest", 1, 1.2))
        ui.save_layout()
        with open(ui.SETTINGS_FILE) as fh:
            saved = json.load(fh)
        self.assertNotIn("header_tint", saved)
        self.assertNotIn("logo_look", saved)
        self.assertEqual(saved["theme"], "Forest")


if __name__ == "__main__":
    unittest.main()
