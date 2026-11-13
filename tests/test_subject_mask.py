"""The Subject AI mask: the real model finds a clear object on a plain background, its masks are steadied from frame
to frame, a blank picture gives an empty mask, and a source's setting picks Person / Subject / Off."""
import os
import time
import unittest

import cv2
import numpy as np

import tests  # noqa: F401
import segment

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(HERE, "models", segment.SUBJECT_MODEL)


def picture(dx=0):
    """A warm round object (a 'ball') on a plain grey-blue wall, 320 x 180."""
    img = np.full((180, 320, 3), (70, 80, 95), np.uint8)
    cv2.circle(img, (160 + dx, 95), 48, (235, 150, 40), -1)
    cv2.circle(img, (145 + dx, 80), 14, (255, 220, 160), -1)   # a highlight
    return img


class SubjectModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seg = segment.Segmenter(MODEL, "subject")
        cls.seg.start()
        end = time.time() + 30
        while not cls.seg.loaded and not cls.seg.error and time.time() < end:
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.seg.stop()

    def mask_of(self, rgb):
        end = time.time() + 10
        while not self.seg.wants_frame() and time.time() < end:
            time.sleep(0.01)
        self.seg.submit(rgb)
        while time.time() < end:
            m = self.seg.take_mask()
            if m is not None:
                return m
            time.sleep(0.01)
        self.fail("no mask came back")

    def test_it_loads(self):
        self.assertIsNone(self.seg.error)
        self.assertTrue(self.seg.loaded)

    def test_finds_the_object_not_the_wall(self):
        self.seg.reset()
        m = self.mask_of(picture())
        self.assertEqual(m.shape, (180, 320))
        self.assertGreater(m[95, 160], 200)        # the middle of the ball
        for y, x in ((10, 10), (10, 310), (170, 10), (170, 310)):
            self.assertLess(m[y, x], 40)           # the wall in the corners

    def test_a_blank_picture_gives_an_empty_mask(self):
        self.seg.reset()
        m = self.mask_of(np.full((180, 320, 3), 128, np.uint8))
        self.assertLess(m.mean(), 10)

    def test_masks_are_steadied_between_frames(self):
        """When the object jumps, the next mask is part old, part new (not a hard flip)."""
        self.seg.reset()
        self.mask_of(picture(-90))
        m = self.mask_of(picture(90))
        old_spot, new_spot = m[95, 70], m[95, 250]
        self.assertGreater(old_spot, 40)   # a trace of where it was
        self.assertGreater(new_spot, old_spot)

    def test_timing_is_kept(self):
        self.mask_of(picture())
        self.assertGreater(self.seg.ms_avg, 0)


class Slow(unittest.TestCase):
    def test_slow_only_when_it_cannot_keep_up(self):
        s = segment.Segmenter("x.onnx", "subject")
        s.loaded = True
        s.ms_avg = 12
        self.assertFalse(s.slow())
        s.ms_avg = segment.SLOW_MS + 5
        self.assertTrue(s.slow())
        s.loaded = False
        self.assertFalse(s.slow())


class SourceSetting(unittest.TestCase):
    def test_mask_kind(self):
        import app
        self.assertEqual(app.mask_kind({}), "person")
        self.assertEqual(app.mask_kind({"mask": "subject"}), "subject")
        self.assertIsNone(app.mask_kind({"mask": "off"}))
        self.assertEqual(app.mask_kind({"mask": "something newer"}), "person")

    def test_every_kind_has_a_model_that_ships(self):
        for kind, name in segment.MODELS.items():
            self.assertTrue(os.path.exists(os.path.join(HERE, "models", name)), kind)


if __name__ == "__main__":
    unittest.main()
