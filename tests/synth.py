"""Synthetic drum tracks for the tempo tests: kicks, snares, hats and a bassline at a known tempo and phase."""
import numpy as np

SR = 48000


def kick(sr=SR):
    t = np.arange(int(0.25 * sr)) / sr
    f = 50 + 90 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 12)


def noise(dur, decay, hp, rng, sr=SR):
    t = np.arange(int(dur * sr)) / sr
    x = rng.standard_normal(len(t))
    if hp:
        x = np.diff(np.concatenate(([0.0], x)))
    return x * np.exp(-t * decay)


def track(bpm, secs, style="four", start=0.0, seed=1, sr=SR):
    """Stereo float32. style: four (kick every beat, hats between), broken (syncopated kicks, like breaks),
    dnb (kick on 1 and the and-of-3, snares on 2 and 4), sparse (kick on 1 only, pads). The first beat is at
    `start` seconds."""
    rng = np.random.default_rng(seed)
    n = int(secs * sr)
    out = np.zeros(n)
    beat = 60.0 / bpm
    k, sn, hat = kick(), noise(0.2, 18, False, rng) * 0.5, noise(0.05, 60, True, rng) * 0.25

    def put(x, at, gain=1.0):
        i = int(at * sr)
        if 0 <= i < n:
            m = min(len(x), n - i)
            out[i:i + m] += gain * x[:m]

    b, i = start, 0
    while b < secs:
        pos = i % 4
        if style == "four":
            put(k, b)
            put(hat, b + beat / 2)
            if pos in (1, 3):
                put(sn, b)
        elif style == "broken":
            if pos == 0:
                put(k, b)
            if pos == 2:
                put(k, b + beat / 2)
            if pos in (1, 3):
                put(sn, b)
            for h in range(4):
                put(hat, b + h * beat / 4, 0.6 if h else 1.0)
        elif style == "dnb":
            if pos == 0:
                put(k, b)
            if pos == 2:
                put(k, b + beat / 2)
            if pos in (1, 3):
                put(sn, b)
            put(hat, b + beat / 2)
        elif style == "sparse":
            if pos == 0:
                put(k, b)
        b += beat
        i += 1
    tt = np.arange(n) / sr
    out += 0.08 * np.sin(2 * np.pi * 55 * tt)   # a held bass note under it all
    out /= max(1.0, np.abs(out).max())
    return np.stack([out, out], axis=1).astype(np.float32)
