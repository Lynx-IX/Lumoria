"""Drum hits (kick, snare, hats) on synthetic grooves with known hit times, through the real audio analysis (no
sound card): kicks aren't set off by the bassline, each drum's sensitivity is its own, and old settings load."""
import unittest

import tests  # noqa: F401  (throwaway data folder)
import audio
from tests.synth import SR, drum_mix

BLOCK = 512


def hits(x, **sens):
    """The analyser's hit times per drum for audio x, with these sensitivities (kick=, snare=, hat=)."""
    a = audio.AudioAnalyzer()
    a.sens.update(sens)
    cb = a._make_callback(SR)
    got = {"kick": [], "snare": [], "hat": []}
    for i in range(0, len(x) - BLOCK, BLOCK):
        before = dict(a._hits)
        cb(x[i:i + BLOCK], BLOCK, None, None)
        for k in got:
            if a._hits[k] > before[k]:
                got[k].append((i + BLOCK) / SR)
    return got


def score(truth, got, key):
    """(share of the real hits found, number of hits that weren't real) for one drum."""
    real, used, found = sorted(truth[key]), set(), 0
    for t in got[key]:
        j = next((j for j, y in enumerate(real) if j not in used and -0.01 <= t - y <= 0.06), None)
        if j is not None:
            used.add(j)
            found += 1
    return found / len(real), len(got[key]) - found


class DrumHits(unittest.TestCase):
    def test_bassline_does_not_set_off_the_kick(self):
        for style in ("punchy", "808"):
            for bass in (0.3, 0.6):
                x, truth = drum_mix(bass=bass, kick_style=style)
                for s in (0.5, 1.0):
                    found, false = score(truth, hits(x, kick=s), "kick")
                    self.assertGreaterEqual(found, 0.95, (style, bass, s))
                    self.assertLessEqual(false, 3, (style, bass, s))   # (the first half second, while it settles)

    def test_kick_click_does_not_set_off_the_snare(self):
        x, truth = drum_mix()
        found, false = score(truth, hits(x, snare=1.0), "snare")
        self.assertGreaterEqual(found, 0.95)
        self.assertLessEqual(false, 3)

    def test_each_drum_has_its_own_sensitivity(self):
        x, truth = drum_mix(hat_gain=0.05)
        low = hits(x, hat=0.3)
        high = hits(x, hat=0.9)
        self.assertGreater(score(truth, high, "hat")[0], score(truth, low, "hat")[0])   # quiet hats found
        self.assertGreaterEqual(score(truth, high, "hat")[0], 0.95)
        self.assertEqual(low["kick"], high["kick"])     # the kick and snare didn't move at all
        self.assertEqual(low["snare"], high["snare"])

    def test_old_single_sensitivity_loads(self):
        a = audio.AudioAnalyzer()
        a.set_sens(0.8)   # a session from before: one number for every drum
        self.assertEqual(a.sens, dict(kick=0.8, snare=0.8, hat=0.8))
        a.set_sens(dict(kick=0.2, hat="bad"))
        self.assertEqual(a.sens, dict(kick=0.2, snare=0.8, hat=0.8))


if __name__ == "__main__":
    unittest.main()
