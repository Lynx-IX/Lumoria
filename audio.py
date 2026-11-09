"""Audio analysis from any input device (mic, line in, loopback): bass / mid / high levels, a spectrum and
waveform for visualizers, drum hits (kick, snare / clap, hats, big kicks) and levels for any frequency range.

Levels come in two forms, both auto-ranged 0..1 so quiet and loud sources both work:
  target[k] - where the sound is right now (hits: 1 for a moment after each one)
  level[k]  - the same, smoothed like a meter (rise fast, fall slowly); hits fade out after each one
Effects that set their own attack / release follow target with their own smoothing instead.
"""
import math
import threading
from collections import deque

import numpy as np
import sounddevice as sd

BANDS = {"bass": (20, 160), "mid": (160, 2000), "high": (2000, 10000)}
SPEC_N = 128   # spectrum bands / waveform points handed to the shaders

# what an effect (or the main "React to") can listen to: key, name
SOURCES = [("bass", "Bass"), ("mid", "Mids"), ("high", "Highs"), ("all", "All"),
           ("kick", "Kick"), ("snare", "Snare / clap"), ("hat", "Hats"), ("accent", "Big kicks"),
           ("beat", "Beat (tempo clock)"), ("range", "Frequency range")]
SOURCE_KEYS = [k for k, _ in SOURCES]
SOURCE_NAMES = dict(SOURCES)
HITS = ("kick", "snare", "hat", "accent", "beat")   # hit-style sources: a pulse on each hit, not a level
HOLD = 0.05      # seconds a hit's target stays at 1
FADE = 0.22      # seconds for a hit's meter-style level to fade (time constant)

# where each drum is listened for (Hz). Snare / clap: the crack (2-5 kHz) with some of the body (150-350 Hz)
DETECT = {"kick": (40, 120), "snare_lo": (150, 350), "snare_hi": (1500, 5000), "hat": (7000, 14000)}
REFRACTORY = {"kick": 0.11, "snare": 0.09, "hat": 0.05}   # a drum can't hit again sooner than this


def list_inputs():
    """WASAPI input devices (falls back to every input if WASAPI isn't there), then every output device as
    ("loop", id): what it plays, captured through loopback (Windows' default output first)."""
    devs = sd.query_devices()
    apis = sd.query_hostapis()
    wasapi = [i for i, a in enumerate(apis) if a["name"] == "Windows WASAPI"]
    out = [(i, d["name"]) for i, d in enumerate(devs)
           if d["max_input_channels"] > 0 and (not wasapi or d["hostapi"] in wasapi)]
    try:
        import loopback
        out += [(("loop", dev_id), f"What you hear: {name}") for dev_id, name in loopback.list_outputs()]
    except Exception:
        pass
    return out


class Onset:
    """Finds hits in one band's spectral flux (how much it just got louder). The flux is scaled against its own
    recent peak, so quiet and loud music both work; a hit is flux clearly above the last ~0.1 s average, once
    per rise, and not too soon after the last one."""

    def __init__(self, refractory):
        self.refractory = refractory
        self.floor = 0.0                 # a hit must also reach this fraction of the band's recent peak
        self.peak = 0.0
        self.recent = deque(maxlen=10)   # about 0.1 s at 512-sample hops
        self.last, self.armed = -10.0, True

    def step(self, flux, now, delta):
        """Returns the hit's strength (scaled flux, 0..1) or 0 for no hit."""
        self.peak = max(flux, self.peak * 0.997)        # falls to half in about 2.5 s
        fn = flux / max(self.peak, 0.6)                 # the floor keeps near-silence from counting
        avg = sum(self.recent) / len(self.recent) if self.recent else 0.0
        self.recent.append(fn)
        if not self.armed:
            if fn < avg + delta * 0.5:
                self.armed = True
            return 0.0
        if fn > avg + delta and flux >= self.floor * self.peak and now - self.last >= self.refractory:
            self.last, self.armed = now, False
            return fn
        return 0.0


class AudioAnalyzer:
    def __init__(self):
        self.stream = None
        self.device_name = None
        self.error = None
        self._raw = {k: 0.0 for k in BANDS}
        self._lock = threading.Lock()
        keys = (*BANDS, "all")
        self.level = {k: 0.0 for k in (*keys, *HITS)}
        self.target = dict(self.level)
        self._range = {k: [1.0, 0.0] for k in keys}
        # for visualizers: log-spaced spectrum (0..1) and the latest stretch of waveform (-1..1)
        self._spec_raw = np.zeros(SPEC_N, np.float32)
        self._wave_raw = np.zeros(SPEC_N, np.float32)
        self._band_raw = np.zeros(SPEC_N, np.float32)   # the spectrum bands' plain magnitudes (frequency ranges)
        self.spectrum = np.zeros(SPEC_N, np.float32)
        self._spec_peak = 0.3
        self.tap = None   # also hand each block of sound to this (the recorder), when set
        self.rate, self.channels = 0, 0
        # spectrum band centres (Hz), set when a device opens; ranges an effect listens to, by (lo, hi)
        self.band_hz = np.geomspace(30, 16000, SPEC_N)
        self._ranges = {}
        # drum hits: counted in the audio thread, picked up once a frame by update()
        self.hit_sens = 0.5                  # 0 = only the clearest hits .. 1 = every little one
        self._hits = {k: 0 for k in HITS}
        self.hit_now = {k: False for k in HITS}   # hit this frame (meters, tempo)
        self.hit_t = {k: -10.0 for k in HITS}
        self.last_kick = -10.0
        self._t = None

    def open(self, device, name):
        self.close()
        try:
            loop = isinstance(device, tuple) and device[0] == "loop"
            if loop:   # an output device's sound: starts at once, so it calls through to the analyser set below
                import loopback
                target = []
                stream = loopback.LoopbackStream(device[1], lambda *a: target and target[0](*a))
                sr, ch = stream.samplerate, stream.channels
            else:
                info = sd.query_devices(device)
                sr = int(info["default_samplerate"])
                ch = min(2, info["max_input_channels"])
            callback = self._make_callback(sr)
            if loop:
                target.append(callback)
                self.stream = stream
            else:
                self.stream = sd.InputStream(device=device, channels=ch, samplerate=sr,
                                             blocksize=512, dtype="float32", callback=callback)
                self.stream.start()
            self.device_name, self.error, self.rate, self.channels = name, None, sr, ch
        except Exception as e:
            self.stream, self.error = None, str(e)

    def _make_callback(self, sr):
        """The audio thread's work for each block: FFT, levels, spectrum, waveform and drum hits."""
        n = 2048
        freqs = np.fft.rfftfreq(n, 1 / sr)
        masks = {k: (freqs >= lo) & (freqs < hi) for k, (lo, hi) in BANDS.items()}
        det = {k: np.flatnonzero((freqs >= lo) & (freqs < min(hi, sr / 2 - 1))) for k, (lo, hi) in DETECT.items()}
        window = np.hanning(n).astype(np.float32)
        buf = np.zeros(n, np.float32)
        # spectrum bands 30 Hz .. 16 kHz, log spaced; each band is at least one FFT bin wide
        edges = np.geomspace(30, min(16000, sr / 2 - 1), SPEC_N + 1)
        self.band_hz = np.sqrt(edges[:-1] * edges[1:])
        lo_bin = np.searchsorted(freqs, edges[:-1])
        hi_bin = np.maximum(np.searchsorted(freqs, edges[1:]), lo_bin + 1)
        onsets = {k: Onset(r) for k, r in REFRACTORY.items()}
        kicks = deque(maxlen=8)   # recent kick strengths, to tell the big ones
        state = dict(prev=None, samples=0, peak=0.0, peak_hops=0)

        def callback(indata, frames, _t, _status):
            nonlocal buf
            tap = self.tap
            if tap:
                tap(indata.copy())
            mono = indata.mean(axis=1)
            buf = np.concatenate((buf, mono))[-n:]
            mag = np.abs(np.fft.rfft(buf * window)) / (n / 4)
            raw = {}
            for k, m in masks.items():
                db = 20 * np.log10(mag[m].mean() + 1e-9)
                raw[k] = float(np.clip((db + 75) / 75, 0, 1))
            csum = np.concatenate(([0.0], np.cumsum(mag)))
            band = (csum[hi_bin] - csum[lo_bin]) / (hi_bin - lo_bin)
            spec = np.clip((20 * np.log10(band + 1e-9) + 70) / 70, 0, 1).astype(np.float32)
            wave = buf[-1024:][::1024 // SPEC_N].astype(np.float32)

            # drum hits from spectral flux on compressed magnitudes (loud parts count more than faint ones)
            state["samples"] += frames
            now = state["samples"] / sr
            comp = np.log1p(1000.0 * mag)
            prev, state["prev"] = state["prev"], comp
            hits = []
            if prev is not None:
                rise = np.maximum(comp - prev, 0.0)
                flux = {k: float(rise[idx].mean()) if len(idx) else 0.0 for k, idx in det.items()}
                sens = min(1.0, max(0.0, self.hit_sens))
                delta = 0.12 + 0.36 * (1.0 - sens)
                # a snare's band also jumps on every kick click and hat, a little less than on a real snare:
                # it only counts when it reaches nearly the band's recent peak (a quiet mix is judged the same)
                onsets["snare"].floor = 0.95 - 0.2 * sens
                lvl = float(comp[det["kick"]].mean())
                if onsets["kick"].step(flux["kick"], now, delta):
                    hits.append("kick")
                    state["peak"], state["peak_hops"] = lvl, 3   # watch how loud it gets over ~30 ms
                elif state["peak_hops"]:
                    state["peak"] = max(state["peak"], lvl)
                    state["peak_hops"] -= 1
                    if not state["peak_hops"]:   # a big kick: clearly louder than the last few
                        if len(kicks) >= 3 and state["peak"] > sorted(kicks)[len(kicks) // 2] + 0.35:
                            hits.append("accent")
                        kicks.append(state["peak"])
                # snare / clap: its crack. (Its body sits where a kick's pitch sweep does, so it can't tell them apart)
                if onsets["snare"].step(flux["snare_hi"], now, delta):
                    hits.append("snare")
                # hats: the top end jumping more than the snare's range does (a snare's noise reaches up there too)
                if onsets["hat"].step(max(0.0, flux["hat"] - 0.8 * flux["snare_hi"]), now, delta):
                    hits.append("hat")
            with self._lock:
                self._raw = raw
                self._spec_raw, self._wave_raw, self._band_raw = spec, wave, band.astype(np.float32)
                for h in hits:
                    self._hits[h] += 1

        return callback

    def close(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
        self.stream, self.device_name = None, None

    def shader_data(self, t):
        """128 x 2 floats for the GPU: spectrum, then waveform. With no input, a gentle idle ripple so
        visualizers still show where they are."""
        if not self.stream:
            x = np.linspace(0, 1, SPEC_N, dtype=np.float32)
            spec = 0.25 + 0.15 * np.sin(x * 9 + t * 2.0) * np.sin(x * 3.1 - t * 1.3)
            wave = 0.3 * np.sin(x * 25 + t * 3) * np.sin(x * 3.14)
            return np.stack([spec, wave]).astype(np.float32)
        with self._lock:
            spec, wave = self._spec_raw.copy(), self._wave_raw.copy()
        # auto-range against a slow-falling peak, then rise fast / fall slowly like a meter
        self._spec_peak = max(float(spec.max()), self._spec_peak * 0.995, 0.2)
        floor = 0.25
        target = np.clip((spec - floor) / max(self._spec_peak - floor, 0.05), 0, 1)
        self.spectrum += (target - self.spectrum) * np.where(target > self.spectrum, 0.6, 0.12)
        peak = max(float(np.abs(wave).max()), 1e-3)
        return np.stack([self.spectrum, wave / max(peak, 0.1)]).astype(np.float32)

    @staticmethod
    def _autorange(r, v):
        """Where v sits between a slow-falling peak and a slow-rising floor (updates r = [floor, peak])."""
        r[1] = max(v, r[1] * 0.997)   # slow-falling peak
        r[0] = min(v, r[0] + 0.0008)  # slow-rising floor
        return max(0.0, (v - r[0]) / max(0.08, r[1] - r[0]))

    def pulse(self, key, t):
        """A hit from outside the analyser (the tempo clock's beat), shown straight away."""
        self.hit_now[key], self.hit_t[key] = True, t
        self.target[key] = self.level[key] = 1.0

    def update(self, t=None):
        """Call once per video frame: smooths and auto-ranges levels, and picks up the drum hits."""
        dt = 1 / 60 if self._t is None or t is None else min(max(t - self._t, 0.0), 0.1)
        self._t = t if t is not None else (self._t or 0.0) + dt
        now = self._t
        fade = math.exp(-dt / FADE)
        with self._lock:
            raw = dict(self._raw)
            hits, self._hits = self._hits, {k: 0 for k in HITS}
            bands = self._band_raw.copy()
        live = self.stream is not None
        for k in HITS:
            self.hit_now[k] = live and hits[k] > 0
            if self.hit_now[k]:
                self.hit_t[k] = now
            self.target[k] = 1.0 if now - self.hit_t[k] < HOLD else 0.0
            self.level[k] = 1.0 if self.hit_now[k] else self.level[k] * fade
        if self.hit_now["kick"]:
            self.last_kick = now
        if not live:
            for k in (*BANDS, "all"):
                self.level[k] *= 0.9
                self.target[k] = 0.0
            for r in self._ranges.values():
                r["level"] *= 0.9
                r["target"] = 0.0
            return
        raw["all"] = sum(raw.values()) / 3
        for k, v in raw.items():
            target = self._autorange(self._range[k], v)
            cur = self.level[k]
            self.target[k] = target
            self.level[k] = cur + (target - cur) * (0.7 if target > cur else 0.15)
        # frequency ranges effects listen to (dropped once nothing has asked for them for a while)
        for key in [k for k, r in self._ranges.items() if now - r["used"] > 5.0]:
            del self._ranges[key]
        for (lo, hi), r in self._ranges.items():
            sel = (self.band_hz >= lo) & (self.band_hz <= hi)
            if not sel.any():   # narrower than one band: the nearest one
                sel = np.zeros(SPEC_N, bool)
                sel[int(np.argmin(np.abs(np.log(self.band_hz / math.sqrt(lo * hi)))))] = True
            db = 20 * math.log10(float(bands[sel].mean()) + 1e-9)
            target = self._autorange(r["range"], float(np.clip((db + 75) / 75, 0, 1)))
            r["target"] = target
            r["level"] += (target - r["level"]) * (0.7 if target > r["level"] else 0.15)

    def range_level(self, lo, hi):
        """(target, level) for a frequency range in Hz. The first ask starts measuring it (0 until then)."""
        lo, hi = sorted((max(20.0, float(lo)), max(20.0, float(hi))))
        key = (round(lo), round(hi))
        r = self._ranges.get(key)
        if r is None:
            r = self._ranges[key] = dict(range=[1.0, 0.0], level=0.0, target=0.0, used=self._t or 0.0)
        r["used"] = self._t or 0.0
        return r["target"], r["level"]

    def source(self, key, rng=None):
        """(target, level) for one of SOURCES."""
        if key == "range":
            return self.range_level(*(rng or (80.0, 250.0)))
        return self.target.get(key, 0.0), self.level.get(key, 0.0)
