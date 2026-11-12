"""Look timelines (timeline.py): lane values between points, intro / loop sections on the tempo clock, cleaning a
look's timeline from a file, and the App setting sliders from the lanes. Time is simulated: no window or GPU."""
import json
import types
import unittest

import tests  # noqa: F401  (throwaway data folder)
import tempo
import timeline as T
from lookcheck import clean_look


def tl(**kw):
    base = dict(unit="bars", length=8.0, grid=0.25, on_leave="finish", loops=0, lanes=[])
    base.update(kw)
    return base


class LaneValues(unittest.TestCase):
    def test_segments(self):
        pts = [[0, 0.0, "ramp"], [2, 1.0, "ease"], [4, 0.0, "hold"], [6, 0.5, "ramp"]]
        self.assertAlmostEqual(T.value_at(pts, 1.0), 0.5)    # ramp: halfway
        self.assertAlmostEqual(T.value_at(pts, 2.5), 1.0 - 0.15625)   # ease: smoothstep(0.25) = 0.15625
        self.assertAlmostEqual(T.value_at(pts, 3.0), 0.5)    # ease is symmetric in the middle
        self.assertAlmostEqual(T.value_at(pts, 5.9), 0.0)    # hold: stays ...
        self.assertAlmostEqual(T.value_at(pts, 6.0), 0.5)    # ... then jumps at the next point
        self.assertAlmostEqual(T.value_at(pts, -1), 0.0)     # before the first point: its value
        self.assertAlmostEqual(T.value_at(pts, 99), 0.5)     # after the last: it holds
        self.assertIsNone(T.value_at([], 1.0))

    def test_points_at_the_same_place(self):
        self.assertAlmostEqual(T.value_at([[1, 0.2, "ramp"], [1, 0.8, "ramp"]], 1.0), 0.8)


class Sections(unittest.TestCase):
    def test_no_markers_loops_the_whole_timeline(self):
        ph = T.Playhead(tl(length=4.0), beat=10.0, t=0.0)
        self.assertEqual(ph.where(10.0, 0), (0.0, "loop", 0))
        pos, sec, n = ph.where(10.0 + 4 * 4 + 6, 0)   # one full pass (16 beats) and 6 beats more
        self.assertEqual((pos, sec, n), (1.5, "loop", 1))

    def test_intro_then_loop(self):
        ph = T.Playhead(tl(length=16.0, intro_end=4.0, loop_end=12.0), beat=0.0, t=0.0)
        self.assertEqual(ph.where(3 * 4, 0)[1], "intro")   # bar 3
        self.assertEqual(ph.where(4 * 4, 0), (4.0, "loop", 0))
        self.assertEqual(ph.where(12 * 4, 0), (4.0, "loop", 1))   # loop end wraps to loop start, never the outro
        pos, _, n = ph.where(27 * 4, 0)
        self.assertEqual((pos, n), (11.0, 2))   # 23 bars after the intro: 2 passes of 8, 7 in

    def test_markers_out_of_order_or_empty(self):
        self.assertEqual(T.sections(tl(length=8.0, intro_end=6.0, loop_end=2.0)), (0.0, 8.0, 8.0))
        self.assertEqual(T.sections(tl(length=8.0, intro_end=9.0)), (0.0, 8.0, 8.0))   # clamped: empty loop

    def test_follows_the_tempo_clock(self):
        """Bars are counted on the clock's beats, so a tempo change mid-loop keeps sections on the beat grid."""
        clock = tempo.Tempo()
        clock.source = tempo.MANUAL if hasattr(tempo, "MANUAL") else clock.source
        ph = T.Playhead(tl(length=2.0), beat=clock.phase, t=0.0)
        t = 0.0
        for bpm, secs in ((120.0, 2.0), (90.0, 4.0 / 3.0)):   # 4 beats at 120, then 2 beats at 90
            clock.bpm = bpm
            for _ in range(int(secs * 100)):
                clock.phase += 0.01 * bpm / 60.0
                t += 0.01
        pos, sec, n = ph.where(clock.phase, t)
        self.assertAlmostEqual(pos, 1.5, places=2)   # 6 beats = 1.5 bars into a 2-bar loop
        self.assertEqual((sec, n), ("loop", 0))

    def test_seconds_unit(self):
        ph = T.Playhead(tl(unit="seconds", length=10.0, intro_end=2.0, loop_end=6.0), beat=0.0, t=100.0)
        self.assertEqual(ph.where(999, 101.0)[1], "intro")
        self.assertEqual(ph.where(999, 107.0), (3.0, "loop", 1))

    def test_values_per_lane(self):
        lanes = [dict(effect="kaleido", key="amt", mode="value", mute=False, points=[[0, 0.0, "ramp"], [2, 1.0, "ramp"]]),
                 dict(effect="kaleido", key="p0", mode="value", mute=True, points=[[0, 0.3, "ramp"]]),
                 dict(effect="zoom", key="speed", mode="depth", mute=False, points=[[0, 0.3, "ramp"]])]
        ph = T.Playhead(tl(length=4.0, lanes=lanes), beat=0.0, t=0.0)
        self.assertEqual(ph.values(4.0, 0), {("kaleido", "amt"): 0.5})   # muted and depth lanes don't set values


class Cleaning(unittest.TestCase):
    def test_a_good_timeline_survives_a_round_trip(self):
        good = tl(length=16.0, intro_end=4.0, loop_end=12.0, on_leave="jump", loops=3,
                  lanes=[dict(effect="kaleido", key="amt", mode="value", mute=False,
                              points=[[0.0, 0.2, "ease"], [4.0, 0.8, "ramp"], [12.0, 0.8, "hold"], [16.0, 0.0, "ramp"]])])
        look = dict(version=2, effects=[dict(id="kaleido", on=True)], timeline=good)
        back = clean_look(json.loads(json.dumps(look)))
        self.assertEqual(back["timeline"], good)

    def test_damaged_timelines(self):
        look = dict(version=2, effects=[dict(id="kaleido")], timeline=dict(
            unit="weeks", length="lots", intro_end=99, loop_end=-5, on_leave=7, extra="x",
            lanes=[dict(effect="kaleido", key="amt", points=[[3, 0.5], [1, "nan"], [1, 0.2, "wobble"], "junk", [0.5]]),
                   dict(effect="kaleido", key="__import__"), dict(key="amt"), "junk"]))
        out = clean_look(look)["timeline"]
        self.assertEqual(out["unit"], "bars")
        self.assertEqual(out["length"], 8.0)
        self.assertEqual(out["on_leave"], "finish")
        self.assertNotIn("extra", out)
        self.assertLessEqual(out["loop_end"], out["length"])
        self.assertGreaterEqual(out["loop_end"], out["intro_end"])
        self.assertEqual(len(out["lanes"]), 1)
        self.assertEqual(out["lanes"][0]["points"], [[1.0, 0.2, "ramp"], [3.0, 0.5, "ramp"]])   # sorted, bad ones gone

    def test_not_a_timeline(self):
        self.assertNotIn("timeline", clean_look(dict(effects=[], timeline="nope")))
        self.assertNotIn("timeline", clean_look(dict(effects=[])))


class AppLanes(unittest.TestCase):
    def test_lanes_set_the_looks_sliders(self):
        import app
        fx = types.SimpleNamespace(id="kaleido", removing=False, amt=0.1, amt_smooth=0.1, opacity=1.0, speed=1.0,
                                   pvals=[0.0, 0.0])
        other = types.SimpleNamespace(id="zoom", removing=False, amt=0.4, amt_smooth=0.4, pvals=[0.0])
        fake = types.SimpleNamespace(tempo=types.SimpleNamespace(phase=0.0, beats_per_bar=4),
                                     pipe=types.SimpleNamespace(order=[fx, other]),
                                     set_auto_value=app.App.set_auto_value)
        lanes = [dict(effect="kaleido", key="amt", mode="value", mute=False, points=[[0, 0.0, "ramp"], [1, 1.0, "ramp"]]),
                 dict(effect="kaleido", key="p1", mode="value", mute=False, points=[[0, 0.7, "hold"]])]
        fake.playhead = T.Playhead(tl(length=4.0, lanes=lanes), beat=0.0, t=0.0)
        fake.tempo.phase = 2.0   # half a bar in
        app.App.timeline_step(fake, 0.0)
        self.assertAlmostEqual(fx.amt, 0.5)
        self.assertAlmostEqual(fx.amt_smooth, 0.5)
        self.assertAlmostEqual(fx.pvals[1], 0.7)
        self.assertAlmostEqual(other.amt, 0.4)   # an effect with no lane is left alone


if __name__ == "__main__":
    unittest.main()
