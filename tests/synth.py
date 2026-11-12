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


def drum_mix(bpm=124, secs=16, hat_gain=0.1, bass=0.4, kick_style="punchy", seed=3, sr=SR):
    """A house groove with known hit times, for the drum-hit tests: a kick every beat, snares on 2 and 4, 8th-note
    hats (`hat_gain` loud) and a moving bassline in the kick's own range (a new note every 8th, the classic false
    kick). kick_style: punchy (pitch sweep and click) or 808 (long, barely sweeping). Returns (stereo float32,
    {"kick" / "snare" / "hat": [times in s]})."""
    rng = np.random.default_rng(seed)
    n = int(secs * sr)
    out = np.zeros(n)
    beat = 60.0 / bpm
    t = np.arange(int(0.6 * sr)) / sr
    if kick_style == "808":
        f = 48 + 30 * np.exp(-t * 25)
        k = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.minimum(1, t / 0.002) * np.exp(-t * 4)
    else:
        f = 45 + 110 * np.exp(-t * 35)
        k = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 9) + rng.standard_normal(len(t)) * np.exp(-t * 400) * 0.15
    ts = np.arange(int(0.25 * sr)) / sr
    sn = np.sin(2 * np.pi * 190 * ts) * np.exp(-ts * 25) * 0.5 + noise(0.25, 16, True, rng) * 0.35
    hats = [np.diff(noise(0.06, 70, True, rng), prepend=0.0) for _ in range(4)]
    truth = {"kick": [], "snare": [], "hat": []}

    def put(x, at, gain, key):
        i = int(at * sr)
        if 0 <= i < n:
            m = min(len(x), n - i)
            out[i:i + m] += gain * x[:m]
            truth[key].append(at)

    b, i = 0.5, 0
    while b < secs - 1:
        put(k, b, 1.0, "kick")
        if i % 4 in (1, 3):
            put(sn, b, 0.8, "snare")
        for h in range(2):
            put(hats[(i + h) % 4], b + h * beat / 2, hat_gain * (1.0 if h == 0 else 0.7), "hat")
        b += beat
        i += 1
    tt = np.arange(n) / sr
    notes = [41.2, 55.0, 49.0, 61.7, 41.2, 73.4, 55.0, 46.2]
    step = beat / 2
    for j in range(int(secs / step)):   # each note: 8 ms attack, held, 15 ms release into the next
        a, z = int(j * step * sr), min(n, int(((j + 1) * step + 0.015) * sr))
        seg = tt[a:z] - tt[a]
        env = np.minimum(1, seg / 0.008) * np.exp(-seg * 3) * np.clip((step + 0.015 - seg) / 0.015, 0, 1)
        out[a:z] += bass * np.sin(2 * np.pi * notes[j % len(notes)] * seg) * env
    out /= max(1.0, np.abs(out).max())
    return np.stack([out, out], axis=1).astype(np.float32), truth
