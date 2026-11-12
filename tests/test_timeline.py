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
                                     pipe=types.SimpleNamespace(order=[fx, other], outgoing=None),
                                     set_auto_value=app.App.set_auto_value, out_playhead=None)
        fake.apply_lanes = lambda ph, order, t, holds=None: app.App.apply_lanes(fake, ph, order, t, holds)
        fake.lane_hold = {}
        lanes = [dict(effect="kaleido", key="amt", mode="value", mute=False, points=[[0, 0.0, "ramp"], [1, 1.0, "ramp"]]),
                 dict(effect="kaleido", key="p1", mode="value", mute=False, points=[[0, 0.7, "hold"]])]
        fake.playhead = T.Playhead(tl(length=4.0, lanes=lanes), beat=0.0, t=0.0)
        fake.tempo.phase = 2.0   # half a bar in
        app.App.timeline_step(fake, 0.0)
        self.assertAlmostEqual(fx.amt, 0.5)
        self.assertAlmostEqual(fx.amt_smooth, 0.5)
        self.assertAlmostEqual(fx.pvals[1], 0.7)
        self.assertAlmostEqual(other.amt, 0.4)   # an effect with no lane is left alone



def song(**kw):
    """A 16-bar timeline: 4-bar intro, 8-bar loop (bars 4-12), 4-bar outro."""
    return tl(length=16.0, intro_end=4.0, loop_end=12.0, **kw)


class Outro(unittest.TestCase):
    def test_outro_plays_once_after_outro_at(self):
        ph = T.Playhead(song(), beat=0.0, t=0.0)
        ph.outro_at = 20.0   # 2 loop passes done
        self.assertEqual(ph.where(19 * 4, 0)[1], "loop")
        self.assertEqual(ph.where(21 * 4, 0), (13.0, "outro", 2))
        self.assertEqual(ph.where(30 * 4, 0)[1], "done")   # past its end: holds the last values

    def test_no_outro_no_plan(self):
        self.assertIsNone(T.plan_outro(T.Playhead(tl(length=8.0), 0.0, 0.0), 10.0, 0))
        self.assertIsNone(T.plan_outro(T.Playhead(tl(length=16.0, intro_end=4.0, loop_end=16.0), 0.0, 0.0), 10.0, 0))

    def test_finish_the_pass(self):
        ph = T.Playhead(song(), beat=0.0, t=0.0)
        self.assertEqual(T.plan_outro(ph, 6 * 4, 0), (12.0, 16.0))       # bar 6: the first pass ends at 12; the next look at 16
        self.assertEqual(T.plan_outro(ph, 13 * 4, 0), (20.0, 24.0))      # bar 13: the second pass ends at 20
        self.assertEqual(T.plan_outro(ph, 2 * 4, 0), (4.0, 8.0))         # in the intro: when the intro ends
        self.assertEqual(T.plan_outro(ph, 12 * 4, 0), (12.0, 16.0))      # right on a pass end: now
        self.assertEqual(T.plan_outro(ph, 6 * 4, 0, overlap=1.0), (12.0, 15.0))   # the next look overlaps its end
        self.assertEqual(T.plan_outro(ph, 6 * 4, 0, overlap=9.0), (12.0, 12.0))   # never more than the outro

    def test_jump(self):
        ph = T.Playhead(song(), beat=0.0, t=0.0)
        self.assertEqual(T.plan_outro(ph, 6 * 4 + 1, 0, jump=True), (6.25, 10.25))   # launch now: straight away
        # launch on the bar: the outro ENDS on a bar line (bar 11 here)
        self.assertEqual(T.plan_outro(ph, 6 * 4 + 1, 0, jump=True, grid=4), (7.0, 11.0))
        # an 8-bar phrase: ends on bar 16
        self.assertEqual(T.plan_outro(ph, 6 * 4 + 1, 0, jump=True, grid=32), (12.0, 16.0))
        # phrases are counted from where beat 1 was set (bar_origin); this look started on beat 2
        ph2 = T.Playhead(song(), beat=1.0, t=0.0)
        start, _ = T.plan_outro(ph2, 1.0 + 6 * 4, 0, jump=True, grid=32, bar_origin=0.0)
        self.assertAlmostEqual(1.0 + (start + 4.0) * 4, 64.0)   # ends on beat 64: the second phrase from the origin

    def test_seconds_jump_ignores_the_beat_grid(self):
        ph = T.Playhead(song(unit="seconds"), beat=0.0, t=100.0)
        self.assertEqual(T.plan_outro(ph, 999, 107.5, jump=True, grid=4), (7.5, 11.5))

    def test_loop_passes(self):
        self.assertEqual(T.loop_passes(song(loops=3), 64), 3)       # its own count wins
        self.assertEqual(T.loop_passes(song(), 16), 2)              # 16 bars of "every" = two 8-bar passes
        self.assertEqual(T.loop_passes(song(), 2), 1)               # at least one


class Handover(unittest.TestCase):
    """The App's side: Take / auto-play schedule the handover, the next look comes in at the planned moment, and the
    old look carries on with its outro while it fades out."""

    def make(self, quantize=0, on_leave="finish", transition=0, secs=0.0):
        import app
        fake = types.SimpleNamespace()
        for name in ("plan_leave", "leave_step", "load_preset", "look_style", "timeline_step", "apply_lanes",
                     "auto_timeline_step", "playlist_step", "auto_step"):
            setattr(fake, name, (lambda fn: (lambda *a, **k: fn(fake, *a, **k)))(app.App.__dict__[name]))
        fake.set_auto_value = app.App.set_auto_value
        clock = tempo.Tempo()
        clock.bpm = 120.0
        fx = types.SimpleNamespace(id="kaleido", removing=False, amt=0.0, amt_smooth=0.0, pvals=[])
        lanes = [dict(effect="kaleido", key="amt", mode="value", mute=False,
                      points=[[0, 0.0, "ramp"], [12, 0.5, "hold"], [12, 1.0, "ramp"], [16, 1.0, "ramp"]])]
        fake.tempo, fake.quantize, fake.pending_look, fake.leaving = clock, quantize, None, None
        fake.current_preset, fake.playlist, fake.fired = "A", ["A", "B", "C"], []
        fake.auto_mode, fake.auto_every, fake.auto_unit, fake.auto_progress = 0, 8, 2, 0.0
        fake.pipe = types.SimpleNamespace(order=[fx], outgoing=None, transition=transition, trans_secs=secs)
        fake.meta = lambda name: dict(transition=-1, fade=1.0, fade_unit=0, hold=0, unit=0)
        fake.hold_time = lambda: (fake.auto_every, fake.auto_unit)
        fake.out_playhead, fake.timeline_name, fake.lane_hold = None, "A", {}
        fake.playhead = T.Playhead(song(on_leave=on_leave, lanes=lanes), beat=0.0, t=0.0)
        fake.fx = fx

        def load(name, manual=False):   # the look comes in: a crossfade keeps the old chain as outgoing
            fake.leaving = None
            fake.fired.append((name, clock.phase))
            fake.pipe.outgoing = dict(order=fake.pipe.order) if transition != 2 else None
            fake.pipe.order = [types.SimpleNamespace(id="other", removing=False)]
            fake.current_preset, fake.playhead = name, None
        fake._load_preset = load
        return fake

    def run_to(self, fake, beat):
        while fake.tempo.phase < beat - 1e-9:
            fake.tempo.phase = min(beat, fake.tempo.phase + 0.25)
            fake.leave_step(0.0)
            if fake.auto_mode and fake.playhead is not None:
                fake.auto_timeline_step(0.0)
            fake.timeline_step(0.0)

    def test_take_finishes_the_pass_then_the_outro(self):
        f = self.make()
        self.run_to(f, 6 * 4)        # bar 6, in the first loop pass
        f.load_preset("B")           # Take
        self.assertEqual(f.fired, [])
        self.assertEqual(f.playhead.outro_at, 12.0)
        self.run_to(f, 13 * 4)       # into the outro
        self.assertEqual(f.playhead.where(f.tempo.phase, 0)[1], "outro")
        self.assertAlmostEqual(f.fx.amt, 1.0)        # the outro's lane value (it jumps at bar 12)
        self.run_to(f, 16 * 4)
        self.assertEqual(f.fired, [("B", 16 * 4)])   # no overlap: B comes in as the outro ends

    def test_the_next_look_overlaps_the_outro(self):
        f = self.make(secs=4.0)      # a 4 s transition at 120 BPM = 2 bars
        self.run_to(f, 6 * 4)
        f.load_preset("B")
        self.run_to(f, 14 * 4)
        self.assertEqual(f.fired, [("B", 14 * 4)])   # 2 bars before the outro ends
        self.assertIsNotNone(f.out_playhead)          # the old look keeps its outro going while it fades out
        old_fx = f.out_playhead[1][0]
        self.run_to(f, 15 * 4)
        self.assertAlmostEqual(old_fx.amt, 1.0)

    def test_a_cut_does_not_overlap(self):
        f = self.make(transition=2, secs=4.0)
        self.run_to(f, 6 * 4)
        f.load_preset("B")
        self.run_to(f, 17 * 4)
        self.assertEqual(f.fired, [("B", 16 * 4)])

    def test_jump_on_the_bar(self):
        f = self.make(quantize=2, on_leave="jump")
        self.run_to(f, 6 * 4 + 1)
        f.load_preset("B")
        self.assertEqual(f.playhead.outro_at, 7.0)   # so it ends on bar 11
        self.run_to(f, 12 * 4)
        self.assertEqual(f.fired, [("B", 11 * 4)])

    def test_firing_again_while_leaving_changes_the_destination(self):
        f = self.make()
        self.run_to(f, 6 * 4)
        f.load_preset("B")
        f.load_preset("C")
        self.run_to(f, 16 * 4)
        self.assertEqual(f.fired, [("C", 16 * 4)])

    def test_no_outro_loads_at_once(self):
        f = self.make()
        f.playhead = T.Playhead(tl(length=8.0), beat=0.0, t=0.0)
        f.load_preset("B")
        self.assertEqual(f.fired, [("B", 0.0)])

    def test_auto_play_stays_for_whole_passes_then_plays_the_outro(self):
        f = self.make()
        f.auto_mode, f.auto_every, f.auto_unit = 1, 16, 2   # every 16 bars = two 8-bar passes
        self.run_to(f, 40 * 4)
        self.assertEqual(f.fired[0], ("B", 24 * 4))   # intro 4 + 2 passes (16) = bar 20, + the 4-bar outro = bar 24


class DepthAndTakeover(unittest.TestCase):
    def lanes(self):
        return [dict(effect="kaleido", key="amt", mode="value", mute=False,
                     points=[[0, 0.0, "ramp"], [2, 1.0, "ramp"], [4, 0.0, "ramp"]]),
                dict(effect="kaleido", key="p0", mode="depth", mute=False, points=[[0, 1.0, "ramp"], [4, 0.0, "ramp"]])]

    def test_values_by_mode(self):
        ph = T.Playhead(song(lanes=self.lanes()), beat=0.0, t=0.0)
        self.assertEqual(ph.values(8.0, 0), {("kaleido", "amt"): 1.0})            # bar 2
        self.assertEqual(ph.values(8.0, 0, mode="depth"), {("kaleido", "p0"): 0.5})

    def test_hold_until_the_next_point_or_the_section_end(self):
        ph = T.Playhead(song(lanes=self.lanes()), beat=0.0, t=0.0)
        self.assertAlmostEqual(ph.hold_until("kaleido", "amt", 1 * 4, 0), 2.0)   # bar 1 (intro): the point at 2
        self.assertAlmostEqual(ph.hold_until("kaleido", "amt", 2.5 * 4, 0), 4.0) # past it: the intro's end (4)
        self.assertAlmostEqual(ph.hold_until("kaleido", "amt", 6 * 4, 0), 12.0)  # in the loop, no point ahead: its end
        ph.outro_at = 12.0
        self.assertEqual(ph.hold_until("kaleido", "amt", 13 * 4, 0), float("inf"))   # the outro: until the look changes
        held = {("kaleido", "amt"): 2.0}
        self.assertEqual(ph.values(1 * 4, 0, holds=held), {})                    # held: the lane lets go ...
        self.assertEqual(ph.values(2 * 4, 0, holds=held), {("kaleido", "amt"): 1.0})   # ... and takes it back

    def test_the_app_lets_go_when_taken_over(self):
        import app
        fx = types.SimpleNamespace(id="kaleido", removing=False, amt=0.3, amt_smooth=0.3, pvals=[0.0])
        fake = types.SimpleNamespace(tempo=types.SimpleNamespace(phase=4.0, beats_per_bar=4),
                                     pipe=types.SimpleNamespace(order=[fx], outgoing=None),
                                     set_auto_value=app.App.set_auto_value, out_playhead=None, lane_hold={},
                                     lane_keys={("kaleido", "amt")})
        fake.apply_lanes = lambda ph, order, t, holds=None: app.App.apply_lanes(fake, ph, order, t, holds)
        fake.playhead = T.Playhead(song(lanes=self.lanes()), beat=0.0, t=0.0)
        app.App.lane_takeover(fake, "kaleido", "amt", 0.0)   # at bar 1: yours until the point at bar 2
        fx.amt = 0.9                                          # (moved by hand)
        app.App.timeline_step(fake, 0.0)
        self.assertAlmostEqual(fx.amt, 0.9)
        self.assertTrue(app.App.lane_held(fake, "kaleido", "amt", 0.0))
        fake.tempo.phase = 2 * 4 + 2                          # bar 2.5: the lane has it again
        app.App.timeline_step(fake, 0.0)
        self.assertAlmostEqual(fx.amt, 0.75)
        app.App.lane_takeover(fake, "kaleido", "p0", 0.0)    # not a value lane: nothing to take over
        self.assertNotIn(("kaleido", "p0"), fake.lane_hold)

    def test_depth_lane_scales_the_wave(self):
        import app
        fx = types.SimpleNamespace(id="kaleido", uid=1, removing=False, on=True, morph=None, intro_reset=False,
                                   amt=0.0, amt_smooth=0.0, pvals=[0.0],
                                   autos={"p0": dict(shape=2, rate=1.0, unit=0, lo=0.0, hi=1.0)})   # ramp up, 1 s
        fake = types.SimpleNamespace(tempo=types.SimpleNamespace(phase=0.0, beats_per_bar=4), auto_state={},
                                     pipe=types.SimpleNamespace(order=[fx]), set_auto_value=app.App.set_auto_value,
                                     lane_keys=set(), audio_drive=None, centre_path=None)
        fake.wave = app.App.wave
        lanes = [dict(effect="kaleido", key="p0", mode="depth", mute=False, points=[[0, 0.5, "hold"]])]
        fake.playhead = T.Playhead(song(lanes=lanes), beat=0.0, t=0.0)
        app.App.automate(fake, 0.9)                     # the ramp is at 0.9 of its way
        self.assertAlmostEqual(fx.pvals[0], 0.5 + (0.9 - 0.5) * 0.5)   # half the swing, around the middle
        fake.playhead = None
        app.App.automate(fake, 0.9)
        self.assertAlmostEqual(fx.pvals[0], 0.9)        # no timeline: the full swing


class Polish(unittest.TestCase):
    def test_intro_wave_to_lane(self):
        import ui
        app_ = types.SimpleNamespace(tempo=tempo.Tempo())
        app_.tempo.bpm, app_.tempo.beats_per_bar = 120.0, 4
        intro = dict(shape=9, rate=2.0, unit=2, lo=0.1, hi=0.9, ease=3)    # 2 bars, linear
        lane = ui.intro_lane(app_, song(), "kaleido", "amt", intro)
        self.assertEqual(lane["points"], [[0.0, 0.1, "ramp"], [2.0, 0.9, "hold"]])
        intro = dict(shape=9, rate=6.0, unit=1, lo=0.0, hi=1.0, ease=0)    # 6 beats, smooth
        self.assertEqual(ui.intro_lane(app_, song(), "k", "p0", intro)["points"][1][:1], [1.5])
        intro = dict(shape=9, rate=4.0, unit=0, lo=0.0, hi=1.0)            # 4 s at 120 BPM = 2 bars
        self.assertAlmostEqual(ui.intro_lane(app_, song(), "k", "p0", intro)["points"][1][0], 2.0)
        intro = dict(shape=9, rate=99.0, unit=2, lo=0.0, hi=1.0)           # never longer than the timeline
        self.assertEqual(ui.intro_lane(app_, song(), "k", "p0", intro)["points"][1][0], 16.0)

    def test_editor_undo(self):
        import ui
        saved = []
        app_ = types.SimpleNamespace(edit_timeline=lambda name, tl_: saved.append(json.dumps(tl_)))
        ui.S.tl = dict(name="A", tl=song(), drag=None, sel=set(), hist=[], future=[], last=json.dumps(song()))
        try:
            ui.S.tl["tl"]["length"] = 8.0
            ui.tl_changed(app_)
            ui.S.tl["tl"]["grid"] = 1.0
            ui.tl_changed(app_)
            ui.tl_changed(app_)                       # nothing changed: no extra step
            self.assertEqual(len(ui.S.tl["hist"]), 2)
            ui.tl_undo(app_)
            self.assertEqual((ui.S.tl["tl"]["length"], ui.S.tl["tl"]["grid"]), (8.0, 0.25))
            ui.tl_undo(app_)
            self.assertEqual(ui.S.tl["tl"]["length"], 16.0)
            ui.tl_undo(app_)                          # nothing left: stays
            self.assertEqual(ui.S.tl["tl"]["length"], 16.0)
            ui.tl_undo(app_, redo=True)
            ui.tl_undo(app_, redo=True)
            self.assertEqual((ui.S.tl["tl"]["length"], ui.S.tl["tl"]["grid"]), (8.0, 1.0))
            self.assertEqual(json.loads(saved[-1])["grid"], 1.0)   # each step is saved (and played, if on air)
            ui.S.tl["tl"]["length"] = 4.0
            ui.tl_changed(app_)
            self.assertEqual(ui.S.tl["future"], [])   # a new edit forgets what could be redone
        finally:
            ui.S.tl = None


class OutroKey(Handover):
    def make(self, **kw):
        import app
        f = super().make(**kw)
        f.go_outro = (lambda fn: (lambda *a, **k: fn(f, *a, **k)))(app.App.__dict__["go_outro"])
        f.cued, f.flash = None, lambda *a, **k: None
        return f

    def test_outro_now_into_the_next_look(self):
        f = self.make()
        self.run_to(f, 6 * 4 + 1)
        f.go_outro()
        self.assertAlmostEqual(f.playhead.outro_at, 6.25)   # now, not at the end of the pass
        self.run_to(f, 12 * 4)
        self.assertEqual(f.fired, [("B", 10.25 * 4)])       # the 4-bar outro, then the next look

    def test_outro_into_the_cued_look_and_jumping_a_waiting_handover(self):
        f = self.make()
        self.run_to(f, 6 * 4)
        f.load_preset("C")             # waits for the end of the pass (bar 12) ...
        self.assertEqual(f.playhead.outro_at, 12.0)
        self.run_to(f, 7 * 4)
        f.go_outro()                   # ... until the Outro key: now, still into C
        self.assertEqual(f.playhead.outro_at, 7.0)
        self.run_to(f, 12 * 4)
        self.assertEqual(f.fired, [("C", 11 * 4)])


class Recording(unittest.TestCase):
    """Armed, a slider moved by hand writes its lane at the playhead; the take is tidied and kept when it stops."""

    def make(self, lanes=None):
        import app
        fake = types.SimpleNamespace()
        for name in ("record_value", "rec_step", "rec_end", "rec_end_all", "set_lane_keys", "set_tl_recording",
                     "resync_bar", "start_timeline"):
            setattr(fake, name, (lambda fn: (lambda *a, **k: fn(fake, *a, **k)))(app.App.__dict__[name]))
        clock = tempo.Tempo()
        clock.bpm = 120.0
        fake.tempo, fake.current_preset = clock, "A"
        fake.tl_recording, fake.rec_touch, fake.lane_hold, fake.tl_rev = True, {}, {}, 0
        fake.timeline = tl(length=4.0, lanes=lanes or [])
        fake.timeline_name = "A"
        fake.playhead = T.Playhead(fake.timeline, beat=0.0, t=0.0)
        fake.saved = []
        fake.edit_timeline = lambda name, tl_: fake.saved.append((name, json.loads(json.dumps(tl_))))
        fake.fx = types.SimpleNamespace(id="kaleido", removing=False)
        return fake

    def sweep(self, f, beats, values, key="amt"):
        """Move the slider through `values`, one per step across `beats` (16 steps a beat)."""
        for i, v in enumerate(values):
            f.tempo.phase = beats[0] + (beats[1] - beats[0]) * i / max(1, len(values) - 1)
            f.record_value(f.fx, key, v, f.tempo.phase / 2)   # (120 BPM: 2 beats a second)
            f.rec_step(f.tempo.phase / 2)

    def test_a_take_makes_a_lane(self):
        f = self.make()
        self.sweep(f, (0, 4), [i / 64 for i in range(65)])     # a straight ramp 0 -> 1 over bar 1
        self.assertEqual([ln["key"] for ln in f.timeline["lanes"]], ["amt"])
        self.assertIn(("kaleido", "amt"), f.lane_keys)
        f.rec_step(100.0)                                      # still for a while: the take ends
        pts = f.timeline["lanes"][0]["points"]
        self.assertLessEqual(len(pts), 3)                      # a straight line needs only its ends
        self.assertAlmostEqual(pts[0][1], 0.0)
        self.assertAlmostEqual(pts[-1][0], 1.0)
        self.assertAlmostEqual(pts[-1][1], 1.0)
        self.assertEqual(f.saved[-1][0], "A")                  # kept in the look
        self.assertEqual(f.tl_rev, 1)
        self.assertNotIn(("kaleido", "amt"), f.lane_hold)      # the lane plays again

    def test_a_take_replaces_what_it_passes_over(self):
        old = [[0.0, 0.5, "ramp"], [1.0, 0.5, "ramp"], [2.0, 0.5, "ramp"], [3.0, 0.5, "ramp"]]
        f = self.make([dict(effect="kaleido", key="amt", mode="value", mute=False, points=old)])
        f.set_lane_keys(f.timeline)
        self.sweep(f, (4, 8), [0.9] * 33)                      # hold it at 0.9 through bar 2 (pos 1..2)
        self.assertEqual(f.lane_hold[("kaleido", "amt")], float("inf"))   # the lane doesn't fight the hand
        f.rec_step(100.0)
        pts = f.timeline["lanes"][0]["points"]
        self.assertEqual([p[0] for p in pts if p[0] < 0.99], [0.0])        # before the take: untouched
        self.assertTrue(all(abs(p[1] - 0.9) < 1e-9 for p in pts if 0.99 < p[0] < 2.01))   # during: the take
        self.assertEqual([p for p in pts if p[0] > 2.5], [[3.0, 0.5, "ramp"]])   # after: untouched

    def test_disarmed_records_nothing(self):
        f = self.make()
        f.tl_recording = False
        self.sweep(f, (0, 4), [0.2, 0.4])
        self.assertEqual(f.timeline["lanes"], [])

    def test_simplify(self):
        line = [[i / 10, i / 10, "ramp"] for i in range(11)]
        self.assertEqual(T.simplify(line), [line[0], line[-1]])
        bend = [[0, 0.0, "ramp"], [1, 1.0, "ramp"], [2, 0.0, "ramp"]]
        self.assertEqual(T.simplify(bend), bend)


class BeatOne(unittest.TestCase):
    def test_timelines_start_on_beat_1_and_follow_a_resync(self):
        import app
        fake = types.SimpleNamespace(rec_touch={}, current_preset="A")
        for name in ("start_timeline", "set_lane_keys", "resync_bar"):
            setattr(fake, name, (lambda fn: (lambda *a, **k: fn(fake, *a, **k)))(app.App.__dict__[name]))
        fake.tempo = tempo.Tempo()
        fake.tempo.phase = 9.2            # beat 2 of bar 3 (bar 1 starts at beat 0)
        fake.start_timeline(song())
        self.assertEqual(fake.playhead.start_beat, 8)    # the nearest beat 1
        fake.tempo.phase = 12.9           # the music's downbeat is really here, a beat later: B on it
        fake.resync_bar()
        self.assertEqual(fake.tempo.bar_origin, 13)
        self.assertEqual(fake.playhead.start_beat, 9)   # the timeline's bars moved with it (by the nearest way)


class Shapes(unittest.TestCase):
    def test_every_shape_goes_from_one_point_to_the_next_and_stays_between(self):
        for seg in T.SEGMENTS:
            if seg == "hold":
                continue
            self.assertAlmostEqual(T.shape(seg, 0.0), 0.0, places=3, msg=seg)
            self.assertAlmostEqual(T.shape(seg, 1.0), 1.0, places=3, msg=seg)
            for k in range(101):
                self.assertTrue(-1e-9 <= T.shape(seg, k / 100) <= 1 + 1e-9, (seg, k))

    def test_the_shapes(self):
        pts = lambda seg: [[0, 0.0, seg], [1, 1.0, "ramp"]]
        self.assertAlmostEqual(T.value_at(pts("ease_in"), 0.5), 0.125)
        self.assertAlmostEqual(T.value_at(pts("ease_out"), 0.5), 0.875)
        self.assertLess(T.value_at(pts("sharp_in"), 0.5), 0.05)       # hardly moves at first
        self.assertGreater(T.value_at(pts("sharp_out"), 0.5), 0.95)   # most of the way at once
        self.assertEqual(T.value_at(pts("hold"), 0.99), 0.0)
        b = [T.value_at(pts("bounce"), k / 200) for k in range(201)]
        dips = sum(1 for i in range(1, 200) if b[i] < b[i - 1] and b[i] < b[i + 1])
        self.assertGreaterEqual(dips, 2)                               # it bounces
        self.assertAlmostEqual(T.value_at([[0, 1.0, "ease_in"], [2, 0.0, "ramp"]], 1.0), 0.875)   # downward too

    def test_new_shapes_survive_cleaning(self):
        look = dict(effects=[], timeline=tl(lanes=[dict(effect="k", key="amt", points=[[0, 0.2, s], [1, 0.4, "ramp"]])
                                                   for s in ("bounce", "sharp_out", "nonsense")]))
        segs = [ln["points"][0][2] for ln in clean_look(look)["timeline"]["lanes"]]
        self.assertEqual(segs, ["bounce", "sharp_out", "ramp"])


if __name__ == "__main__":
    unittest.main()
