"""Cue, Take, the crossfader and phrase launch timing (the engine's logic; the picture is checked in the app)."""
import types
import unittest
from unittest import mock

import tests  # noqa: F401  (throwaway data folder)
import app as L
import tempo


def chain(name):
    """A one-effect chain standing in for a look's effects."""
    return [types.SimpleNamespace(name=name, on=True, mix=1.0, removing=False, xf_keep=False)]


class FakePipe:
    def __init__(self):
        self.outgoing, self.order, self.lib_i, self.trans_secs = None, chain("A"), 0, 1.0


class FakeApp:
    """The App's cue / crossfader methods over a stand-in pipeline: loading a look just records it."""
    for _name in ("cue", "cue_step", "take", "set_xfader", "fade_done", "cancel_fade", "crossfader_step",
                  "load_preset", "plan_leave"):
        locals()[_name] = L.App.__dict__[_name]

    def __init__(self):
        self.pipe, self.tempo = FakePipe(), tempo.Tempo()
        self.playlist, self.current_preset = ["A", "B", "C"], "A"
        self.band, self.gain, self.quantize, self.pending_look = "bass", 1.0, 0, None
        self.cued, self.xfader, self.xf_dir, self.xf_armed, self.xf_live = None, 0.0, 1, True, None
        self.auto_progress, self.fired, self.flashed = 0.0, [], []
        self.playhead = self.leaving = None   # no look timeline here (see test_timeline)

    def flash(self, msg, secs=5):
        self.flashed.append(msg)

    def _load_preset(self, name, manual=False):
        if self.xf_live and not manual:
            self.cancel_fade()
        if manual:
            self.xf_live = (self.current_preset, self.band, self.gain)
            self.pipe.outgoing = dict(order=self.pipe.order, manual=True, p=0.0, start=0.0, dur=1.0)
            self.pipe.order, self.pipe.lib_i = chain(name), self.pipe.lib_i ^ 1
        self.fired.append((name, manual))
        self.current_preset = name

    def fader(self, v):
        self.set_xfader(v)
        self.crossfader_step()


class CueTest(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.clock = mock.patch.object(L.glfw, "get_time", return_value=10.0)
        self.clock.start()

    def tearDown(self):
        self.clock.stop()

    def test_cue_then_take(self):
        a = self.app
        a.cue("B")
        self.assertEqual(a.fired, [])   # cueing doesn't fire
        a.take()
        self.assertEqual((a.fired, a.cued), ([("B", False)], None))

    def test_take_with_nothing_cued_says_so(self):
        self.app.take()
        self.assertEqual(self.app.fired, [])
        self.assertTrue(self.app.flashed)

    def test_cue_steps_through_the_playlist(self):
        a = self.app
        a.cue_step(1)
        self.assertEqual(a.cued, "B")
        a.cue_step(1)
        self.assertEqual(a.cued, "C")
        a.cue_step(1)
        self.assertEqual(a.cued, "A")   # wraps round
        a.cue_step(-1)
        self.assertEqual(a.cued, "C")

    def test_fader_brings_the_cued_look_in_and_swaps_ends(self):
        a = self.app
        a.cue("B")
        a.fader(0.5)
        self.assertEqual(a.fired, [("B", True)])
        self.assertEqual(a.pipe.outgoing["p"], 0.5)   # the picture is half way
        a.fader(1.0)
        self.assertEqual(a.pipe.outgoing["p"], 1.0)   # the pipeline sets A aside next frame
        self.assertEqual((a.current_preset, a.cued, a.xf_live, a.xf_dir), ("B", None, None, -1))
        a.pipe.outgoing = None
        a.cue("C")
        a.fader(0.6)   # coming back from the far end now brings C in
        self.assertEqual(a.fired[-1], ("C", True))
        self.assertAlmostEqual(a.pipe.outgoing["p"], 0.4)

    def test_fader_needs_a_cue_and_its_start_position(self):
        a = self.app
        a.fader(0.5)
        self.assertEqual(a.fired, [])   # nothing cued
        a.cue("B")
        a.xf_armed = False   # e.g. just after a Take, with the fader left part-way
        a.fader(0.6)
        self.assertEqual(a.fired, [])   # it waits until the fader goes back to its start
        a.fader(0.0)
        a.fader(0.3)
        self.assertEqual(a.fired, [("B", True)])

    def test_recueing_mid_fade_puts_the_old_look_back(self):
        a = self.app
        a.cue("B")
        a.fader(0.4)
        a.cue("C")
        self.assertEqual((a.current_preset, a.pipe.order[0].name, a.pipe.outgoing, a.xf_live), ("A", "A", None, None))
        self.assertEqual(a.pipe.lib_i, 0)   # back on the old look's effect set
        a.fader(0.5)
        self.assertEqual(len(a.fired), 1)   # not until the fader goes back to its start
        a.fader(0.0)
        a.fader(0.2)
        self.assertEqual(a.fired[-1], ("C", True))

    def test_firing_a_look_mid_fade_cancels_the_fade(self):
        a = self.app
        a.cue("B")
        a.fader(0.4)
        a.load_preset("C")
        self.assertEqual(a.fired[-1], ("C", False))
        self.assertIsNone(a.xf_live)

    def test_take_mid_fade_finishes_it_from_there(self):
        a = self.app
        a.cue("B")
        a.fader(0.25)
        a.take()
        og = a.pipe.outgoing
        self.assertFalse(og["manual"])
        self.assertAlmostEqual((10.0 - og["start"]) / og["dur"], 0.25)   # carries on from 25%
        self.assertEqual((a.current_preset, a.xf_live, a.xf_dir, a.xf_armed), ("B", None, 1, False))
        a.pipe.outgoing = None   # the timed fade has finished
        a.cue("C")
        a.fader(0.5)
        self.assertEqual(a.fired[-1], ("B", True))   # the fader has to go back to its start (0) first
        a.fader(0.0)
        a.fader(0.3)
        self.assertEqual(a.fired[-1], ("C", True))

    def test_take_waits_for_the_phrase(self):
        a = self.app
        a.quantize = 4   # 8 bars
        a.tempo.phase = 5.0
        a.cue("B")
        a.take()
        self.assertEqual(a.pending_look, ("B", 32))
        self.assertEqual(a.fired, [])


class PhraseTest(unittest.TestCase):
    def test_boundaries(self):
        tp = tempo.Tempo()
        tp.phase = 5.3
        self.assertEqual(tp.next_boundary(1), 6)
        self.assertEqual(tp.next_boundary(2), 8)
        self.assertEqual(tp.next_boundary(3), 16)
        self.assertEqual(tp.next_boundary(4), 32)
        self.assertEqual(tp.next_boundary(5), 64)
        tp.bar_origin = 2   # beat 1 moved (B): phrases count from it
        self.assertEqual(tp.next_boundary(3), 18)
        tp.phase = 18.02    # just past a boundary counts as on it
        self.assertEqual(tp.next_boundary(3), 18)
        self.assertEqual(tp.next_boundary(4), 34)


class MidiTargetsTest(unittest.TestCase):
    def test_fader_and_buttons_are_mappable(self):
        a = types.SimpleNamespace(pipe=types.SimpleNamespace(trans_time=1.0), playlist=[], gain=1.0,
                                  tempo=types.SimpleNamespace(), xfader=0.25)
        for k in ("randomize", "clear", "toggle_record", "playlist_step", "take", "cue_step", "set_xfader"):
            setattr(a, k, mock.Mock())
        a.tempo.resync_bar = mock.Mock()
        for key in ("xfade", "take", "cue_next", "cue_prev"):
            self.assertIsNotNone(L.App.midi_control(a, ("app", key)), key)
        c = L.App.midi_control(a, ("app", "xfade"))
        self.assertEqual((c[0], c[3]()), ("range", 0.25))


if __name__ == "__main__":
    unittest.main()
