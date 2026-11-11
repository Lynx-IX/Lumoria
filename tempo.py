"""The beat clock everything musical follows: beat effects, auto-play, look timing in beats/bars, launch quantize.

A steady clock counts beats (phase, a float: 0, 1, 2... are beats). Where its tempo comes from:
  Audio      - locks to the music's own tempo and beat (BeatTracker, below), pulling gently into phase so it keeps
               steady time, and runs on at the last tempo through quiet passages; x2 / x0.5 for double / half time
  Tap        - tap a key / button / MIDI pad on the beat; the average of the taps sets the tempo
  Manual     - a fixed BPM
  MIDI clock - 24 ticks per beat from a DAW (FL Studio, Ableton...) on any MIDI input; Start puts it on beat 1
"""
import math

import numpy as np

SOURCES = ["Audio", "Tap", "Manual", "MIDI clock"]
UNITS = ["sec", "beats", "bars"]
AUDIO, TAP, MANUAL, MIDI_CLOCK = range(4)
LAUNCH = ["now", "beat", "bar", "4 bars", "8 bars", "16 bars"]   # when a fired look starts (App.quantize)
PHRASE_BARS = {2: 1, 3: 4, 4: 8, 5: 16}


class Tempo:
    def __init__(self):
        self.bpm, self.source, self.beats_per_bar = 120.0, AUDIO, 4
        self.phase = 0.0           # beats since the clock started (whole numbers are beats)
        self.bar_origin = 0        # the beat that counts as beat 1 of a bar
        self.beat_now = False      # a new beat started this frame
        self.taps, self.last_onset = [], None
        self.clocks, self.clock_ms, self.clock_running, self.clock_seen = 0, [], False, -10.0
        self.mult = 1.0            # Audio: double (2) or half (0.5) the tempo the music is heard at
        self.lock = 0.0            # Audio: how sure the tracker is (0..1), for the interface
        self.locked_at = None      # Audio: when (perf_counter) the tracker last placed the beat
        self._est_n, self._beat_seen = None, 0

    @property
    def beat_len(self):
        return 60.0 / self.bpm

    def seconds(self, value, unit):
        """A time given in seconds, beats or bars (UNITS index), in seconds at the current tempo."""
        return value * (1.0, self.beat_len, self.beat_len * self.beats_per_bar)[unit]

    def beat_in_bar(self):
        return int(math.floor(self.phase) - self.bar_origin) % self.beats_per_bar

    def advance(self, dt, t, onset=False, est=None, now=None):
        """Move the clock on by one frame. onset: the audio beat detector fired this frame. est: the beat
        tracker's latest (bpm, confidence, seconds since its beat, perf_counter then, count); now: perf_counter."""
        before = self.phase
        if self.source == MIDI_CLOCK and self.clock_running:
            # between ticks, run on at the tempo, but never past the next tick (the DAW leads)
            self.phase = min(self.phase + dt * self.bpm / 60.0, (self.clocks + 1) / 24.0)
        else:
            self.phase += dt * self.bpm / 60.0
        if self.source == AUDIO and est is not None:
            self.follow(est, now)
        elif self.source == AUDIO and onset:   # until the tracker has heard enough: the kicks themselves
            self.audio_onset(t)
        # a beat fires once: a pull back across a beat doesn't fire it again (a big jump back starts afresh)
        cur = math.floor(self.phase)
        self.beat_now = cur > self._beat_seen
        if self.beat_now or cur < self._beat_seen - 1:
            self._beat_seen = cur

    def follow(self, est, now):
        """Audio: settle on the tracker's tempo and pull into phase with its beats, each time it has a new look."""
        bpm, conf, since, at, n = est
        if n == self._est_n:
            return
        self._est_n, self.lock, self.locked_at = n, conf, at
        target = min(300.0, max(20.0, bpm * self.mult))
        if abs(target / self.bpm - 1) > 0.08:   # a new tempo (or a fresh start): go straight there
            self.bpm = target
        else:
            self.bpm += (target - self.bpm) * 0.5
        frac = (since + max(0.0, now - at)) / (60.0 / target) % 1.0   # where the music's beat is now
        diff = (frac - self.phase % 1.0 + 0.5) % 1.0 - 0.5
        self.phase += diff * (0.35 + 0.4 * min(1.0, conf))

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
        """When a look fired now should start: quantize 1 = the next beat, 2 = the next bar, 3 / 4 / 5 = the next
        4 / 8 / 16-bar phrase (counted from beat 1 of the bar, see resync_bar). Just past a boundary (a few % of a
        beat) counts as on it, so auto-play and late taps aren't delayed."""
        grid = 1 if quantize == 1 else self.beats_per_bar * PHRASE_BARS[quantize]
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


class BeatTracker:
    """Finds the tempo and where the beats fall in the music itself (the Audio source), from an onset envelope:
    how much the sound just got louder, sampled each audio block. Every quarter second it looks at the last
    ~8 seconds: autocorrelation says how far apart the beats are (scored with their multiples, and leaning a
    little toward 120 BPM so it picks the felt beat over half or double), then a comb over the envelope says
    where they land. Pure numpy, run on the audio thread; the result is read by the main thread.
    """
    RATE = 100.0          # the envelope is resampled to this many points a second
    WINDOW = 8.0          # seconds of music each estimate looks at
    LO, HI = 70.0, 180.0  # the tempo range it reports (double / half buttons reach outside it)
    DELAY = 0.025         # how late a hit shows in the envelope (half the analysis window, roughly)

    def __init__(self):
        self.times, self.vals = [], []
        self.next_at = 0.0
        self.bpm, self.conf, self.since, self.at = None, 0.0, 0.0, 0.0   # since: seconds from the last beat to `at`
        self.count = 0           # estimates made (the reader notices a new one)
        self._rival, self._rival_n = None, 0
        self.mult = 1.0          # double / half time, set by the clock (the beats are placed on that grid)

    def push(self, t, value):
        """One envelope point at time t (seconds of audio). Returns True when a new estimate is ready."""
        self.times.append(t)
        self.vals.append(value)
        if len(self.times) > 2 and t - self.times[0] > self.WINDOW + 1.0:
            cut = len(self.times) // 8
            del self.times[:cut], self.vals[:cut]
        if t < self.next_at or t - self.times[0] < 4.0:
            return False
        self.next_at = t + 0.25
        return self.estimate(t)

    def estimate(self, t):
        fs = self.RATE
        grid = np.arange(max(self.times[0], t - self.WINDOW), t, 1.0 / fs)
        e = np.interp(grid, self.times, self.vals)
        k = int(fs * 0.25)   # take away the local average (sustained loudness isn't a beat), keep the rises
        local = np.convolve(e, np.ones(k) / k, mode="same")
        e = np.maximum(e - local, 0.0)
        if e.std() < 1e-6:
            self.conf *= 0.8
            return False
        e = (e - e.mean()) / e.std()
        n = len(e)
        spec = np.fft.rfft(e, 2 * n)
        ac = np.fft.irfft(spec * np.conj(spec))[:n] / n
        lags = np.arange(n)

        def at(lag):
            return np.interp(lag, lags, ac, right=0.0)

        bpms = np.arange(40.0, 240.0, 0.25)
        per = 60.0 * fs / bpms
        score = at(per) + 0.5 * at(2 * per) + 0.25 * at(4 * per) + 0.25 * at(per / 2)
        prior = np.exp(-0.5 * (np.log2(bpms / 120.0) / 0.9) ** 2)
        inside = (bpms >= self.LO) & (bpms <= self.HI)
        guess = bpms[int(np.argmax(np.where(inside, score * prior, -np.inf)))]
        # the lean picks which multiple; the peak itself is found without it (it would drag the tempo toward 120)
        near = np.where(np.abs(bpms / guess - 1) < 0.03, score, -np.inf)
        i = int(np.argmax(near))
        if 0 < i < len(bpms) - 1 and np.isfinite(near[i - 1]) and np.isfinite(near[i + 1]):
            a, b, c = near[i - 1], near[i], near[i + 1]
            d = a - 2 * b + c
            shift = 0.5 * (a - c) / d if d < 0 else 0.0
        else:
            shift = 0.0
        bpm = float(bpms[i] + 0.25 * shift)
        # finer: the autocorrelation peak a few beats out, fitted between samples (4 beats out is 4x as precise)
        for m in (4, 2):
            lag = m * 60.0 * fs / bpm
            j = int(round(lag))
            if j + 3 >= n * 0.7:
                continue
            j = j - 2 + int(np.argmax(ac[j - 2:j + 3]))
            a, b, c = ac[j - 1], ac[j], ac[j + 1]
            d = a - 2 * b + c
            if d < 0 and abs(j - lag) <= 2:
                fine = 60.0 * fs * m / (j + 0.5 * (a - c) / d)
                if abs(fine / bpm - 1) < 0.02:
                    bpm = float(fine)
            break
        conf = float(max(0.0, min(1.0, at(60.0 * fs / bpm) / max(ac[0], 1e-9))))
        # a different tempo has to show up a few times running before it replaces a settled one
        if self.bpm is None or abs(bpm / self.bpm - 1) < 0.04:
            self.bpm = bpm if self.bpm is None else self.bpm + (bpm - self.bpm) * 0.3
            self._rival_n = 0
        elif self._rival is not None and abs(bpm / self._rival - 1) < 0.04:
            self._rival_n += 1
            if self._rival_n >= 6:
                self.bpm, self._rival_n = bpm, 0
        else:
            self._rival, self._rival_n = bpm, 1
        # where the beats fall, on the grid actually in use (double / half time): the offset whose comb of beats
        # (recent ones counting more) catches the most rises
        p = 60.0 * fs / (self.bpm * self.mult)
        beats = np.arange(max(1, int((n - 1) // p)))
        offs = np.arange(0.0, p, 0.5)
        pos = (n - 1) - offs[:, None] - beats[None, :] * p
        since = float(offs[int(np.argmax(np.interp(pos, lags, e, left=0.0) @ 0.85 ** beats))]) / fs
        # a rise shows up in the envelope about 25 ms after the hit (the analysis window): count from the hit
        self.conf, self.since, self.at = conf, (since + self.DELAY) % (p / fs), t
        self.count += 1
        return True
