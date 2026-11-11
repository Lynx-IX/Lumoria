"""Saving can't leave a cut-off file: the old file survives a save that fails part-way."""
import json
import os
import tempfile
import unittest
from unittest import mock

import tests  # noqa: F401  (throwaway data folder)
from shared import save_json, save_text


class SavingTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "playlist.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_round_trip(self):
        save_json(self.path, dict(order=["A", "B"], meta={}))
        with open(self.path) as fh:
            self.assertEqual(json.load(fh)["order"], ["A", "B"])
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_failed_swap_keeps_the_old_file(self):
        save_json(self.path, dict(order=["old"]))
        with mock.patch("shared.os.replace", side_effect=OSError("power cut")):
            with self.assertRaises(OSError):
                save_json(self.path, dict(order=["new"] * 1000))
        with open(self.path) as fh:
            self.assertEqual(json.load(fh), dict(order=["old"]))   # still whole, still the old one

    def test_failed_write_keeps_the_old_file(self):
        save_text(self.path, '{"order": ["old"]}')
        real_open = open

        def broken_open(path, *a, **k):
            fh = real_open(path, *a, **k)
            if str(path).endswith(".tmp"):
                fh.write = mock.Mock(side_effect=OSError("disk full"))
            return fh
        with mock.patch("builtins.open", broken_open):
            with self.assertRaises(OSError):
                save_text(self.path, '{"order": ["new"]}')
        with open(self.path) as fh:
            self.assertEqual(json.load(fh), dict(order=["old"]))


if __name__ == "__main__":
    unittest.main()
