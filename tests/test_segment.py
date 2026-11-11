"""Background removal keeps going after errors, rebuilds itself if they keep coming, and stops cleanly."""
import sys
import time
import types
import unittest
from unittest import mock

import numpy as np

import tests  # noqa: F401
import segment


class FakeSession:
    """Stands in for the AI model: fails on the calls listed in FAIL, else returns a half-grey mask."""
    FAIL = set()
    calls = 0
    made = []

    def __init__(self, path, sess_options=None, providers=None):
        FakeSession.made.append(providers)

    def run(self, _names, inputs):
        FakeSession.calls += 1
        if FakeSession.calls in FakeSession.FAIL:
            raise RuntimeError("device removed")
        h, w = inputs["src"].shape[2:]
        rec = [np.zeros((1, 1, 1, 1), np.float32)] * 4
        return [None, np.full((1, 1, h, w), 0.5, np.float32)] + rec


def fake_ort():
    m = types.ModuleType("onnxruntime")
    m.InferenceSession = FakeSession
    m.SessionOptions = lambda: types.SimpleNamespace(intra_op_num_threads=0, add_session_config_entry=lambda *a: None)
    return m


class SegmenterTest(unittest.TestCase):
    def setUp(self):
        FakeSession.calls, FakeSession.made = 0, []
        self.patch = mock.patch.dict(sys.modules, {"onnxruntime": fake_ort()})
        self.patch.start()
        self.seg = segment.Segmenter("model.onnx")
        self.seg.start()
        self.wait(lambda: self.seg.loaded)

    def tearDown(self):
        self.seg.stop()
        self.patch.stop()

    def wait(self, cond, secs=3.0):
        end = time.time() + secs
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.01)
        return False

    def frame(self):
        """Hand it one frame and wait for the answer (a mask, or None after a failure)."""
        self.wait(self.seg.wants_frame)
        before = FakeSession.calls
        self.seg.submit(np.zeros((48, 64, 3), np.uint8))
        self.assertTrue(self.wait(lambda: FakeSession.calls > before and self.seg.wants_frame()))
        return self.seg.take_mask()

    def test_a_hiccup_is_survived(self):
        FakeSession.FAIL = {2}
        self.assertIsNotNone(self.frame())
        self.frame()                                   # this one fails
        self.assertEqual(self.seg.failures, 1)
        self.assertIn("hiccup", self.seg.take_notice())
        self.assertIsNotNone(self.frame())             # and it carries on
        self.assertIsNone(self.seg.error)

    def test_repeated_failures_rebuild_it_on_the_cpu(self):
        FakeSession.FAIL = {1, 2, 3}
        for _ in range(3):
            self.frame()
        self.assertEqual(len(FakeSession.made), 2)                     # built a second time...
        self.assertEqual(FakeSession.made[-1], ["CPUExecutionProvider"])   # ...on the CPU
        self.assertIn("restarted", self.seg.take_notice())
        self.assertIsNotNone(self.frame())

    def test_stop_ends_the_worker(self):
        FakeSession.FAIL = set()
        self.seg.stop()
        self.assertFalse(self.seg._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
