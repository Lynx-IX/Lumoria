"""The beat clock everything musical follows: beat effects, auto-play, look timing in beats/bars, launch quantize.

A steady clock counts beats (phase, a float: 0, 1, 2... are beats). Where its tempo comes from:
  Audio      - follows the bass hits it's given, settling on a steady tempo and gently pulling into phase with them,
               so it keeps time through quiet passages
  Tap        - tap a key / button / MIDI pad on the beat; the average of the taps sets the tempo
  Manual     - a fixed BPM
  MIDI clock - 24 ticks per beat from a DAW (FL Studio, Ableton...) on any MIDI input; Start puts it on beat 1
"""
import math

SOURCES = ["Audio", "Tap", "Manual", "MIDI clock"]
UNITS = ["sec", "beats", "bars"]
AUDIO, TAP, MANUAL, MIDI_CLOCK = range(4)


class Tempo:
    def __init__(self):
        self.bpm, self.source, self.beats_per_bar = 120.0, AUDIO, 4
        self.phase = 0.0           # beats since the clock started (whole numbers are beats)
        self.bar_origin = 0        # the beat that counts as beat 1 of a bar
        self.beat_now = False      # a new beat started this frame
        self.taps, self.last_onset = [], None
        self.clocks, self.clock_ms, self.clock_running, self.clock_seen = 0, [], False, -10.0

    @property
    def beat_len(self):
        return 60.0 / self.bpm

    def seconds(self, value, unit):
        """A time given in seconds, beats or bars (UNITS index), in seconds at the current tempo."""
        return value * (1.0, self.beat_len, self.beat_len * self.beats_per_bar)[unit]

    def beat_in_bar(self):
        return int(math.floor(self.phase) - self.bar_origin) % self.beats_per_bar

    def advance(self, dt, t, onset=False):
        """Move the clock on by one frame. onset: the audio beat detector fired this frame."""
        before = self.phase
        if self.source == MIDI_CLOCK and self.clock_running:
            # between ticks, run on at the tempo, but never past the next tick (the DAW leads)
            self.phase = min(self.phase + dt * self.bpm / 60.0, (self.clocks + 1) / 24.0)
        else:
            self.phase += dt * self.bpm / 60.0
        if self.source == AUDIO and onset:
            self.audio_onset(t)
        self.beat_now = math.floor(self.phase) > math.floor(before)

    def audio_onset(self, t):
        if self.last_onset is not None:
            iv = t - self.last_onset
            if 0.2 < iv < 2.5:
                bpm = 60.0 / iv
                while bpm < 70:
                    bpm *= 2
                while bpm > 180:
                    bpm /= 2
                self.bpm += (bpm - self.bpm) * 0.12
        self.last_onset = t
        self.phase += (round(self.phase) - self.phase) * 0.35   # pull the beat toward the hit

    def tap(self, t):
        """A tap on the beat: sets the tempo from the last few taps, and puts this moment on a beat."""
        if self.taps and t - self.taps[-1] > 2.0:
            self.taps = []
        self.taps = (self.taps + [t])[-8:]
        if self.source != MIDI_CLOCK:
            self.source = TAP
        if len(self.taps) >= 2:
            gaps = sorted(b - a for a, b in zip(self.taps, self.taps[1:]))
            self.bpm = min(240.0, max(40.0, 60.0 / gaps[len(gaps) // 2]))
        self.phase = float(round(self.phase))

    def resync_bar(self):
        """Make the nearest beat beat 1 of the bar."""
        self.bar_origin = int(round(self.phase))

    def next_boundary(self, quantize):
        """When a look fired now should start: quantize 1 = the next beat, 2 = the next bar (in phase).
        Just past a boundary (a few % of a beat) counts as on it, so auto-play and late taps aren't delayed."""
        grid = 1 if quantize == 1 else self.beats_per_bar
        pos = (self.phase - self.bar_origin) / grid
        start = math.floor(pos) if pos - math.floor(pos) < 0.08 / grid else math.ceil(pos)
        return start * grid + self.bar_origin

    # MIDI clock (24 ticks a beat), with the tick times Windows stamps on them (ms)
    def midi_clock(self, ms, t):
        self.clock_seen = t
        self.clocks += 1
        self.clock_ms = (self.clock_ms + [ms])[-49:]
        if len(self.clock_ms) >= 13:
            per_tick = (self.clock_ms[-1] - self.clock_ms[0]) / (len(self.clock_ms) - 1)
            if per_tick > 0:
                self.bpm = min(300.0, max(20.0, 60000.0 / (per_tick * 24)))
        if self.source == MIDI_CLOCK:
            self.clock_running = True
            self.phase = self.clocks / 24.0

    def midi_start(self):
        self.clocks, self.clock_ms, self.clock_running = 0, [], True
        if self.source == MIDI_CLOCK:
            self.phase, self.bar_origin = 0.0, 0

    def midi_stop(self):
        self.clock_running = False
