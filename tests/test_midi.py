"""MIDI learn for the newer controls (Scale, Rotate, Centre x / y, the music switch, pausing an automation),
driven through a fake MIDI message queue: no controller needed. Links are saved to a throwaway folder."""
import json
import math
import os
import tempfile
import types
import unittest
from unittest import mock

import tests  # noqa: F401  (throwaway data folder)
import app as L
import midi
from shared import MOD_AUDIO, MOD_OFF


def cc(num, val, ch=1):
    """A raw Control Change packet, as Windows' MIDI callback hands it over."""
    return (0xB0 | (ch - 1)) | (num << 8) | (val << 16)


def note(num, vel, ch=1):
    return (0x90 | (ch - 1)) | (num << 8) | (vel << 16)


def effect(**kw):
    f = types.SimpleNamespace(
        id="kaleido", name="Kaleido", uid=7, on=True, removing=False, morph=0, amt=0.5, amt_smooth=0.5,
        opacity=1.0, speed=1.0, xs=1.0, xr=0.0, centre=[0.5, 0.5], mod=MOD_OFF, autos={}, amt_label=None,
        params=[("Segments", 6.0, 2.0, 16.0, "%.0f")], pvals=[6.0], options=[], opts=[],
        xform=True, has_centre=True, has_speed=True)
    f.__dict__.update(kw)
    return f


class FakeOut:
    """Stands in for midi.MidiOut: records what would go out to the controller."""
    def __init__(self):
        self.sent, self.opened = [], []

    def open(self, names):
        self.opened = list(names)

    @property
    def active(self):
        return bool(self.opened)

    def send(self, kind, ch, num, val):
        self.sent.append((kind, ch, num, val))


class FakeApp:
    """Just the App's MIDI and automation parts, over a fake MIDI input and a list of effects."""
    for _name in ("load_midi_map", "save_midi_map", "midi_binding", "midi_name", "midi_control", "automatable",
                  "handle_midi", "automate", "set_auto_value", "wave", "centre_path", "midi_lit", "midi_feedback",
                  "lights_off", "load_light_ports", "set_light_port"):
        locals()[_name] = L.App.__dict__[_name]   # as is: staticmethods stay static
    THEN_SHAPES = L.App.THEN_SHAPES

    def __init__(self, effects):
        self.pipe = types.SimpleNamespace(effects=effects, order=effects, trans_time=1.0, wave_rate=0.25)
        self.playlist, self.gain = [], 1.0
        self.tempo = types.SimpleNamespace(phase=0.0, beats_per_bar=4, tap=None, resync_bar=None)
        self.randomize = self.clear = self.toggle_record = self.playlist_step = None
        self.take = self.cue_step = self.set_xfader = None
        self.cued = self.xf_live = None
        self.xfader = 0.0
        self.midi = midi.MidiIn()   # never opened: messages are put on its queue by hand
        self.midi_map = self.load_midi_map()
        self.midi_learn, self.learn_target, self.midi_seen, self.midi_cc = False, None, 0.0, {}
        self.current_preset, self.auto_state, self.auto_live, self.flashed = "Look", {}, {}, []
        self.auto_mode, self.recorder = 0, types.SimpleNamespace(recording=False)
        self.midi_out, self.lights_sent = FakeOut(), {}
        self.light_ports = self.load_light_ports()

    def flash(self, msg, secs=5):
        self.flashed.append(msg)

    def send(self, *packets):
        for p in packets:
            self.midi.queue.append((p, 0))
        for msg in self.midi.poll():
            self.handle_midi(msg, 1.0)

    def learn(self, target, packet):
        """MIDI learn as the UI does it: learn mode on, click the control, move a knob, learn mode off."""
        self.midi_learn, self.learn_target = True, target
        self.send(packet)
        self.midi_learn = False


class MidiCase(unittest.TestCase):
    """A fake app with one effect; links and port choices are saved to a throwaway folder."""
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.patch = mock.patch.multiple(L, MIDI_FILE=os.path.join(self.dir.name, "midi_map.json"),
                                         MIDI_OUT_FILE=os.path.join(self.dir.name, "midi_out.json"))
        self.patch.start()
        self.f = effect()
        self.app = FakeApp([self.f])

    def tearDown(self):
        self.patch.stop()
        self.dir.cleanup()


class MidiLearnTest(MidiCase):
    def test_scale_follows_the_slider_log_scale(self):
        self.app.learn(("kaleido", "xs"), cc(20, 0))
        self.app.send(cc(20, 127))
        self.assertAlmostEqual(self.f.xs, 8.0, places=4)
        self.app.send(cc(20, 0))
        self.assertAlmostEqual(self.f.xs, 0.1, places=4)
        mid = round(127 * (math.log(1.0) - math.log(0.1)) / (math.log(8.0) - math.log(0.1)))
        self.app.send(cc(20, mid))
        self.assertAlmostEqual(self.f.xs, 1.0, delta=0.04)   # normal size sits near the knob's middle
        self.assertIsNone(self.app.current_preset)            # the look now differs from its saved copy

    def test_rotate_and_centre(self):
        self.app.learn(("kaleido", "xr"), cc(21, 0))
        self.app.learn(("kaleido", "cx"), cc(22, 0))
        self.app.learn(("kaleido", "cy"), cc(23, 0))
        self.app.send(cc(21, 127), cc(22, 0), cc(23, 127))
        self.assertAlmostEqual(self.f.xr, 360.0)
        self.assertEqual(self.f.centre, [0.0, 1.0])

    def test_centre_moves_the_point_a_floating_centre_circles(self):
        self.f.autos["centre"] = dict(path=0, rate=8.0, unit=0, size=0.2, base=[0.5, 0.5], phase=0.0, shape=0)
        self.app.learn(("kaleido", "cx"), cc(22, 0))
        self.app.send(cc(22, 127))
        self.assertEqual(self.f.autos["centre"]["base"], [1.0, 0.5])

    def test_music_switch(self):
        self.app.learn(("kaleido", "mod"), note(36, 100))
        self.app.send(note(36, 100), note(36, 0))   # a pad: press toggles, release does nothing
        self.assertEqual(self.f.mod, MOD_AUDIO)
        self.app.send(note(36, 100))
        self.assertEqual(self.f.mod, MOD_OFF)
        self.app.learn(("kaleido", "mod"), cc(40, 0))   # a knob or switch sending CC: upper half is on
        self.app.send(cc(40, 127))
        self.assertEqual(self.f.mod, MOD_AUDIO)

    def test_automation_pause_keeps_its_settings(self):
        a = dict(shape=0, rate=1.0, unit=0, lo=0.5, hi=2.0, phase=0.0, band=0)
        self.f.autos["xs"] = dict(a)
        self.app.learn(("kaleido", "auto_xs"), note(37, 100))
        self.app.automate(0.25)
        moving = self.f.xs
        self.app.send(note(37, 100))   # pause
        self.assertTrue(self.f.autos["xs"]["paused"])
        self.app.automate(0.6)
        self.assertEqual(self.f.xs, moving)   # held where it was
        self.assertEqual({k: v for k, v in self.f.autos["xs"].items() if k != "paused"}, a)   # settings kept
        self.app.send(note(37, 100))   # resume
        self.assertFalse(self.f.autos["xs"]["paused"])
        self.app.automate(0.6)
        self.assertNotEqual(self.f.xs, moving)

    def test_automation_toggle_without_an_automation_does_nothing(self):
        self.app.learn(("kaleido", "auto_p0"), note(38, 100))
        self.app.send(note(38, 100))
        self.assertEqual(self.f.autos, {})
        self.assertIn("Segments automation", self.app.midi_control(("kaleido", "auto_p0"))[5])

    def test_targets_an_effect_does_not_have(self):
        plain = effect(id="glow", xform=False, has_centre=False, has_speed=False, params=[])
        self.app.pipe.effects.append(plain)
        for key in ("xs", "xr", "cx", "cy", "auto_xs", "auto_centre", "auto_speed", "auto_p0", "auto_nope"):
            self.assertIsNone(self.app.midi_control(("glow", key)), key)
        self.assertIsNotNone(self.app.midi_control(("glow", "mod")))
        self.assertIsNotNone(self.app.midi_control(("glow", "auto_amt")))

    def test_links_are_saved_and_survive_a_restart_and_a_new_look(self):
        self.app.learn(("kaleido", "xs"), cc(20, 0))
        self.app.learn(("kaleido", "mod"), note(36, 100))
        self.app.learn(("kaleido", "auto_xr"), note(37, 100))
        with open(L.MIDI_FILE) as fh:
            self.assertEqual(len(json.load(fh)), 3)
        fresh = effect()   # another look's copy of the same effect, after a restart
        fresh.autos["xr"] = dict(shape=8, rate=4.0, unit=0, lo=-360.0, hi=360.0, phase=0.0, band=0)
        again = FakeApp([fresh])
        self.assertEqual(len(again.midi_map), 3)
        again.send(cc(20, 127), note(36, 90), note(37, 90))
        self.assertAlmostEqual(fresh.xs, 8.0, places=4)
        self.assertEqual(fresh.mod, MOD_AUDIO)
        self.assertTrue(fresh.autos["xr"]["paused"])

    def test_wave_speed_is_retired(self):
        self.assertIsNone(self.app.midi_control(("app", "wave")))
        with open(L.MIDI_FILE, "w") as fh:   # an old links file: its Wave speed link is dropped on loading
            json.dump([dict(src=["cc", 1, 9], target=["app", "wave"]),
                       dict(src=["cc", 1, 10], target=["app", "gain"])], fh)
        self.assertEqual([m["target"] for m in FakeApp([]).midi_map], [["app", "gain"]])

    def test_paused_survives_look_checking(self):
        from lookcheck import clean_look
        look = clean_look(dict(version=2, effects=[dict(id="kaleido", autos=dict(xs=dict(shape=0, paused=True)))]))
        self.assertTrue(look["effects"][0]["autos"]["xs"]["paused"])


class ButtonLightsTest(MidiCase):
    """Feedback to the controller: linked buttons light up to match what they switch."""
    def test_nothing_is_sent_until_a_port_is_ticked(self):
        self.app.learn(("kaleido", "mod"), note(36, 100))
        self.app.midi_feedback()
        self.assertEqual(self.app.midi_out.sent, [])

    def test_lights_follow_the_switches_and_only_change_when_they_do(self):
        self.app.set_light_port("MIDI Mix", True)
        self.app.learn(("kaleido", "mod"), note(1, 100))
        self.app.learn(("kaleido", "on"), cc(16, 127))
        self.app.learn(("kaleido", "xs"), cc(20, 0))   # a knob: no light
        out = self.app.midi_out
        self.app.midi_feedback()
        self.assertEqual(sorted(out.sent), [("cc", 1, 16, 127), ("note", 1, 1, 0)])
        out.sent.clear()
        self.app.midi_feedback()
        self.assertEqual(out.sent, [])   # nothing changed, nothing sent
        self.app.send(note(1, 100))      # music on, from the controller
        self.app.midi_feedback()
        self.assertEqual(out.sent, [("note", 1, 1, 127)])

    def test_paused_automation_play_and_look_lights(self):
        self.app.set_light_port("MIDI Mix", True)
        self.f.autos["xr"] = dict(shape=8, rate=4.0, unit=0, lo=-360.0, hi=360.0, phase=0.0, band=0)
        self.app.learn(("kaleido", "auto_xr"), note(3, 100))
        self.app.learn(("app", "play"), note(4, 100))
        self.app.playlist = ["Look", "Other"]
        self.app.learn(("look", "Look"), note(5, 100))
        self.app.midi_feedback()
        lit = {n: v for _k, _c, n, v in self.app.midi_out.sent}
        self.assertEqual(lit, {3: 127, 4: 0, 5: 127})   # running, stopped, the current look
        self.app.send(note(3, 100))   # pause (the look is now changed, so its light goes out too)
        self.app.midi_feedback()
        self.assertEqual(sorted(self.app.midi_out.sent[-2:]), [("note", 1, 3, 0), ("note", 1, 5, 0)])

    def test_unlinking_turns_the_light_off(self):
        self.app.set_light_port("MIDI Mix", True)
        self.app.learn(("kaleido", "on"), note(7, 100))
        self.app.midi_feedback()
        self.app.midi_map = []
        self.app.midi_feedback()
        self.assertEqual(self.app.midi_out.sent[-1], ("note", 1, 7, 0))
        self.app.midi_feedback()
        self.assertEqual(len(self.app.midi_out.sent), 2)   # and it's forgotten

    def test_ticked_ports_are_remembered(self):
        self.app.set_light_port("MIDI Mix", True)
        self.app.set_light_port("FL STUDIO FIRE", True)
        self.app.set_light_port("MIDI Mix", False)
        self.assertEqual(FakeApp([]).light_ports, ["FL STUDIO FIRE"])

    def test_packed_messages(self):
        self.assertEqual(midi.short_msg("note", 1, 1, 127), 0x7F0190)
        self.assertEqual(midi.short_msg("cc", 16, 20, 0), 0x0014BF)


if __name__ == "__main__":
    unittest.main()
