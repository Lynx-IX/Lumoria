"""Importing look / playlist files end to end (into a throwaway folder), and crop cleaning."""
import base64
import json
import os
import tempfile
import types
import unittest
from unittest import mock

import cv2
import numpy as np

import tests  # noqa: F401
import app as L
from sources import clean_crop, crop_frame


def fake_app(folder):
    """Just enough of the App for import_looks: a playlist, look timing, thumbnails, saving."""
    a = types.SimpleNamespace(playlist=[], look_meta={})
    a.thumb_path = lambda name: os.path.join(folder, name + ".png")
    a.meta = lambda name: L.App.meta(a, name)
    a.save_playlist = lambda: None
    return a


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(L, "PRESET_DIR", self.dir.name)
        self.patch.start()
        self.app = fake_app(self.dir.name)

    def tearDown(self):
        self.patch.stop()
        self.dir.cleanup()

    def write(self, data, name="in.lumatrx-playlist"):
        path = os.path.join(self.dir.name, name)
        with open(path, "w") as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data))
        return path

    def test_good_playlist(self):
        ok, png = cv2.imencode(".png", np.zeros((36, 64, 3), np.uint8))
        path = self.write(dict(lumatrx="playlist", version=1, looks=[
            dict(name="Neon", look=dict(version=2, effects=[dict(id="glow", on=True, amt=0.5)]),
                 thumb=base64.b64encode(png.tobytes()).decode(), meta=dict(transition=1, hold=8))]))
        added = L.App.import_looks(self.app, path)
        self.assertEqual(added, ["Neon"])
        self.assertTrue(os.path.exists(os.path.join(self.dir.name, "Neon.json")))
        self.assertTrue(os.path.exists(os.path.join(self.dir.name, "Neon.png")))
        self.assertEqual(self.app.look_meta["Neon"]["hold"], 8.0)

    def test_hostile_and_broken_entries(self):
        path = self.write(dict(lumatrx="playlist", looks=[
            "nonsense",
            dict(name="../../evil", look=dict(effects=[dict(id="glow")]), thumb="!!notbase64",
                 meta=dict(transition="x")),
            dict(name="Empty", look=dict(effects=[])),
            dict(name="Broken", look="nope"),
        ]))
        added = L.App.import_looks(self.app, path)
        self.assertEqual(added, ["evil"])   # the name is cleaned: nothing written outside the looks folder
        self.assertTrue(os.path.exists(os.path.join(self.dir.name, "evil.json")))
        self.assertFalse(os.path.exists(os.path.join(self.dir.name, "evil.png")))   # bad thumbnail skipped

    def test_not_a_look_file(self):
        for data in ("[1, 2, 3]", '"text"', '{"hello": 1}', "{broken json"):
            with self.assertRaises(ValueError):
                L.App.import_looks(self.app, self.write(data, "x.lumatrx-look"))

    def test_names_never_overwrite(self):
        look = dict(lumatrx="look", name="Same", look=dict(effects=[dict(id="glow")]))
        L.App.import_looks(self.app, self.write(look, "a.lumatrx-look"))
        L.App.import_looks(self.app, self.write(look, "b.lumatrx-look"))
        self.assertEqual(self.app.playlist, ["Same", "Same (2)"])

    def test_files_from_before_the_rename_open(self):
        """LumaTRX was called Lumoria: its .lumoria-look / .lumoria-playlist files (marked "lumoria") still import."""
        look = dict(lumoria="look", name="Old look", look=dict(effects=[dict(id="glow")]))
        self.assertEqual(L.App.import_looks(self.app, self.write(look, "old.lumoria-look")), ["Old look"])
        pl = dict(lumoria="playlist", looks=[dict(name="Old list", look=dict(effects=[dict(id="glow")]))])
        self.assertEqual(L.App.import_looks(self.app, self.write(pl, "old.lumoria-playlist")), ["Old list"])


class DataFolder(unittest.TestCase):
    def test_the_old_data_folder_is_carried_over_once(self):
        import shared
        with tempfile.TemporaryDirectory() as root:
            old, new = os.path.join(root, "Lumoria"), os.path.join(root, "LumaTRX")
            os.makedirs(os.path.join(old, "presets"))
            with open(os.path.join(old, "presets", "Mine.json"), "w") as fh:
                fh.write("{}")
            self.assertTrue(shared.carry_over_data(new, old))
            self.assertTrue(os.path.exists(os.path.join(new, "presets", "Mine.json")))
            self.assertTrue(os.path.exists(os.path.join(old, "presets", "Mine.json")))   # a copy: the old one stays
            with open(os.path.join(new, "presets", "New.json"), "w") as fh:
                fh.write("{}")
            self.assertFalse(shared.carry_over_data(new, old))   # once only: never over the new folder
            self.assertTrue(os.path.exists(os.path.join(new, "presets", "New.json")))
            self.assertFalse(shared.carry_over_data(os.path.join(root, "x"), os.path.join(root, "none")))


class CropTest(unittest.TestCase):
    def test_clean_crop(self):
        self.assertEqual(clean_crop([0.1, 0.2, 0.6, 0.9]), [0.1, 0.2, 0.6, 0.9])
        self.assertEqual(clean_crop([0.6, 0.9, 0.1, 0.2]), [0.1, 0.2, 0.6, 0.9])   # backwards corners
        self.assertEqual(clean_crop([-1, -1, 0.5, 2]), [0.0, 0.0, 0.5, 1.0])        # outside the picture
        for bad in (None, [], [0.1, 0.2], "abc", [0.5, 0.5, 0.5, 0.9], [float("nan"), 0, 1, 1], [0, 0, 1, 1]):
            self.assertIsNone(clean_crop(bad))

    def test_crop_frame_is_never_empty(self):
        frame = np.zeros((720, 1280, 3), np.uint8)
        out = crop_frame(frame, clean_crop([0.2, 0.2, 0.22, 0.22]))
        self.assertGreater(out.size, 0)


if __name__ == "__main__":
    unittest.main()
