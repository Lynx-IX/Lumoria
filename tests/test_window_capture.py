"""Window capture "Behind others" (Windows Graphics Capture): the whole-window picture the compositor hands over is cut
down to the window's inside, the same part "Fast" grabs from the screen."""
import unittest

import numpy as np

import tests  # noqa: F401  (throwaway data folder)
import sources


def window(frame_bounds, client):
    """A WindowSource with no capture running, at a made-up place on the screen."""
    w = sources.WindowSource.__new__(sources.WindowSource)
    w._frame_bounds = lambda: frame_bounds
    w._client_rect = lambda: client
    return w


class Inside(unittest.TestCase):
    def test_title_bar_and_frame_are_cut_off(self):
        # a window at (100, 50), 800 x 600 on screen; its inside starts 1 px in and 31 px down (the title bar)
        w = window((100, 50, 900, 650), (101, 81, 798, 568))
        img = np.zeros((600, 800, 4), np.uint8)
        img[31:31 + 568, 1:1 + 798] = 200   # the inside
        out = w._inside(img)
        self.assertEqual(out.shape[:2], (568, 798))
        self.assertTrue((out == 200).all())

    def test_a_scaled_picture_is_cut_in_proportion(self):
        # the same window, handed over at half size (a scaled display)
        w = window((100, 50, 900, 650), (100, 80, 800, 570))
        img = np.zeros((300, 400, 4), np.uint8)
        out = w._inside(img)
        self.assertEqual(out.shape[:2], (285, 400))

    def test_a_borderless_full_screen_window_stays_whole(self):
        w = window((0, 0, 1920, 1080), (0, 0, 1920, 1080))
        img = np.zeros((1080, 1920, 4), np.uint8)
        self.assertEqual(w._inside(img).shape[:2], (1080, 1920))

    def test_odd_numbers_never_break_it(self):
        img = np.zeros((10, 10, 4), np.uint8)
        self.assertEqual(window((0, 0, 0, 0), (0, 0, 10, 10))._inside(img).shape, img.shape)   # no window size
        self.assertEqual(window((0, 0, 10, 10), (50, 50, 10, 10))._inside(img).shape, img.shape)   # off the picture


if __name__ == "__main__":
    unittest.main()
