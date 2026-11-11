"""Look files: good ones pass through, broken or hostile ones are cleaned up or refused, never crash."""
import base64
import struct
import unittest
import zlib

import cv2
import numpy as np

import tests  # noqa: F401
from lookcheck import MAX_ITEMS, clean_look, clean_meta, clean_thumb

GOOD = dict(version=2, band="bass", gain=1.2, effects=[
    dict(id="glow", on=True, amt=0.6, mod=1, opacity=1.0, blend=0, centre=[0.5, 0.5], opts=[1, 2],
         params=[0.3, 0.7], speed=1.0, target=0, expanded=True, colours=[[1, 0, 0], [0, 0, 1]], keep_out=False,
         autos={"amt": dict(shape=8, rate=2.0, unit=0, lo=0.0, hi=1.0, phase=0.0, dir=1)},
         listen=None, rng=[80, 250], resp=None, char=0, mresp=0.5, xs=1.0, xr=0.0, pick=False, chosen=[]),
    dict(group=True, name="G", on=True, children=[dict(id="kaleido", on=True, amt=0.4)]),
])


def png_bytes(w, h):
    ok, buf = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    return buf.tobytes()


def png_claiming(w, h):
    """A tiny PNG whose header claims a w x h picture (a 'decompression bomb' shape)."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"")) + chunk(b"IEND", b"")


class LookCheckTest(unittest.TestCase):
    def test_good_look_keeps_its_settings(self):
        out = clean_look(GOOD)
        e = out["effects"][0]
        self.assertEqual((e["id"], e["amt"], e["mod"], e["opts"], e["params"]), ("glow", 0.6, 1, [1, 2], [0.3, 0.7]))
        self.assertEqual(e["autos"]["amt"]["shape"], 8)
        self.assertEqual(out["effects"][1]["children"][0]["id"], "kaleido")
        self.assertEqual((out["band"], out["gain"]), ("bass", 1.2))

    def test_wrong_types_are_repaired(self):
        out = clean_look(dict(version=2, effects=[dict(id="glow", on="yes", amt="lots", opts="abc", params=[1, "x"],
                                                       centre=7, speed=float("nan"), autos={"amt": "bad", "p1": 5},
                                                       colours=[[1]], xs=1e9)]))
        e = out["effects"][0]
        self.assertEqual(e["amt"], 0.5)          # default, not a crash
        self.assertNotIn("opts", e)              # unusable: left out, the effect's own defaults apply
        self.assertEqual(e["params"], [1.0, 0.0])
        self.assertEqual(e["centre"], [0.5, 0.5])
        self.assertEqual(e["speed"], 1.0)
        self.assertEqual(e["autos"], {})         # bad automations dropped
        self.assertNotIn("colours", e)
        self.assertEqual(e["xs"], 8.0)           # clamped into range

    def test_entries_without_an_id_are_dropped(self):
        out = clean_look(dict(effects=[dict(amt=1), "nonsense", 42, None, dict(id="glow")]))
        self.assertEqual([e["id"] for e in out["effects"]], ["glow"])

    def test_not_a_look(self):
        for bad in (None, [], "text", 5, dict(), dict(effects="x")):
            with self.assertRaises(ValueError):
                clean_look(bad)

    def test_huge_and_deep_looks_are_capped(self):
        out = clean_look(dict(effects=[dict(id=f"e{i}") for i in range(MAX_ITEMS * 5)]))
        self.assertLessEqual(len(out["effects"]), MAX_ITEMS)
        deep = dict(id="leaf")
        for _ in range(50):
            deep = dict(group=True, children=[deep])
        out = clean_look(dict(effects=[deep]))   # no recursion blow-up

        def depth(item):
            return 1 + max((depth(c) for c in item.get("children", [])), default=0)
        self.assertLess(depth(out["effects"][0]), 10)

    def test_oldest_format_keeps_version_1(self):
        self.assertEqual(clean_look(dict(effects=[dict(id="glow", on=False)]))["version"], 1)

    def test_meta(self):
        self.assertEqual(clean_meta(dict(transition=2, fade="x", hold=5, evil=object())),
                         dict(transition=2, fade=0.0, hold=5.0))
        self.assertEqual(clean_meta("nope"), {})

    def test_thumbnails(self):
        good = png_bytes(64, 36)
        self.assertEqual(clean_thumb(base64.b64encode(good).decode()), good)
        self.assertIsNone(clean_thumb("not base64 !!!"))
        self.assertIsNone(clean_thumb(base64.b64encode(b"just some text, not a picture").decode()))
        self.assertIsNone(clean_thumb(base64.b64encode(png_claiming(100000, 100000)).decode()))   # bomb refused
        self.assertIsNone(clean_thumb(base64.b64encode(png_bytes(3000, 10)).decode()))           # too big
        self.assertIsNone(clean_thumb("A" * 20_000_000))                                          # oversized
        self.assertIsNone(clean_thumb(12345))


if __name__ == "__main__":
    unittest.main()
