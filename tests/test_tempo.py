"""The Audio tempo source locking to music: synthetic drum tracks at known tempos go through the real audio
analysis (no sound card), and the beat clock is stepped along in simulated time."""
import unittest

import numpy as np

import tests  # noqa: F401  (throwaway data folder)
import audio
import tempo
from tests.synth import SR, track

BLOCK = 512


class Recorder(tempo.BeatTracker):
    """The tracker, keeping each estimate with the audio time it was made at."""
    made = []

    def __init__(self):
        super().__init__()
        self.log = []
        Recorder.made.append(self)

    def estimate(self, t):
        ok = super().estimate(t)
        if ok and self.bpm:
            self.log.append((t, self.bpm, self.conf, self.since, self.count))
        return ok


def analyse(x, mult=1.0):
    """Run audio through the analyser's own block callback; returns its tracker."""
    real, tempo.BeatTracker = tempo.BeatTracker, Recorder
    try:
        a = audio.AudioAnalyzer()
        a.beat_mult = mult
        cb = a._make_callback(SR)
        for i in range(0, len(x) - BLOCK, BLOCK):
            cb(x[i:i + BLOCK], BLOCK, None, None)
    finally:
        tempo.BeatTracker = real
    return Recorder.made[-1]


def phase_error(tr, bpm, start, mult=1.0):
    """How far (in seconds) the tracker's last beat is from a real beat of the track."""
    grid = 60.0 / (bpm * mult) if mult >= 1 else 60.0 / bpm   # half time still lands on the track's beats
    t, _b, _c, since, _n = tr.log[-1]
    off = (t - since - start) % grid
    return min(off, grid - off)


class TrackerTest(unittest.TestCase):
    CASES = [(128, "four", 0.1), (120, "four", 0.3), (90, "broken", 0.05), (140, "broken", 0.4),
             (100, "sparse", 0.2), (75, "four", 0.15)]

    def test_tempo_and_beat_positions(self):
        for bpm, style, start in self.CASES:
            with self.subTest(bpm=bpm, style=style):
                tr = analyse(track(bpm, 14, style, start))
                self.assertAlmostEqual(tr.bpm, bpm, delta=bpm * 0.003)
                self.assertLess(phase_error(tr, bpm, start), 0.035)

    def test_drum_and_bass_reads_half_time_and_doubles_onto_the_beat(self):
        tr = analyse(track(174, 14, "dnb", 0.2))
        self.assertAlmostEqual(tr.bpm, 87, delta=1.0)   # the felt half-time pulse, as most listeners would tap
        tr = analyse(track(174, 14, "dnb", 0.2), mult=2.0)
        self.assertLess(phase_error(tr, 87, 0.2, mult=2.0), 0.035)   # doubled: on the 174 grid, not between

    def test_a_tempo_change_is_followed(self):
        x = np.concatenate([track(120, 12, "four", 0.1), track(128, 14, "four", 0.0, seed=2)])
        tr = analyse(x)
        self.assertAlmostEqual(tr.bpm, 128, delta=1.3)

    def test_silence_gives_no_tempo(self):
        tr = analyse(np.zeros((SR * 6, 2), np.float32))
        self.assertIsNone(tr.bpm)


class ClockTest(unittest.TestCase):
    def run_clock(self, tr, secs, fps=60.0, mult=1.0):
        """Step the beat clock along at fps, handing it each estimate as the audio thread would."""
        tp = tempo.Tempo()
        tp.bpm, tp.mult = 100.0, mult   # starts off the music's tempo, and out of phase
        beats, k, t = [], 0, 0.0
        while t < secs:
            while k < len(tr.log) and tr.log[k][0] <= t:
                k += 1
            est = None
            if k:
                at, bpm, conf, since, n = tr.log[k - 1]
                est = (bpm, conf, since, at, n)
            tp.advance(1.0 / fps, t, est=est, now=t)
            if tp.beat_now:
                beats.append(t)
            t += 1.0 / fps
        return tp, beats

    def test_clock_locks_on_and_fires_each_beat_once(self):
        bpm, start = 128, 0.1
        tr = analyse(track(bpm, 20, "four", start))
        tp, beats = self.run_clock(tr, 20)
        self.assertAlmostEqual(tp.bpm, bpm, delta=0.4)
        late = [b for b in beats if b > 10]
        grid = 60.0 / bpm
        errs = [min((b - start) % grid, grid - (b - start) % grid) for b in late]
        self.assertLess(max(errs), 0.03)   # every beat within 30 ms of the music's (a frame is 17 ms, beats are seen on frames)
        gaps = np.diff(late)
        self.assertTrue(np.all(gaps > grid * 0.6), gaps)   # never two beats where there's one

    def test_double_time_clock(self):
        tr = analyse(track(174, 16, "dnb", 0.2), mult=2.0)
        tp, _beats = self.run_clock(tr, 16, mult=2.0)
        self.assertAlmostEqual(tp.bpm, 174, delta=2.0)

    def test_quiet_music_keeps_the_last_tempo(self):
        tp = tempo.Tempo()
        tp.advance(0.1, 0.0, est=(124.0, 0.8, 0.0, 0.0, 1), now=0.0)
        settled, before = tp.bpm, tp.phase
        for i in range(600):   # ten seconds with no new estimate
            tp.advance(1 / 60, 0.1 + i / 60, est=(124.0, 0.8, 0.0, 0.0, 1), now=0.1 + i / 60)
        self.assertEqual(tp.bpm, settled)
        self.assertAlmostEqual(tp.phase - before, 10.0 * settled / 60.0, places=3)   # running on steadily


if __name__ == "__main__":
    unittest.main()
