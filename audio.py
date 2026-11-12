"""Audio analysis from any input device (mic, line in, loopback): bass / mid / high levels, a spectrum and
waveform for visualizers, drum hits (kick, snare / clap, hats, big kicks) and levels for any frequency range.

Levels come in two forms, both auto-ranged 0..1 so quiet and loud sources both work:
  target[k] - where the sound is right now (hits: 1 for a moment after each one)
  level[k]  - the same, smoothed like a meter (rise fast, fall slowly); hits fade out after each one
Effects that set their own attack / release follow target with their own smoothing instead.
"""
import math
import threading
import time
from collections import deque

import numpy as np
import sounddevice as sd

import tempo

BANDS = {"bass": (20, 160), "mid": (160, 2000), "high": (2000, 10000)}
SPEC_N = 128   # spectrum bands / waveform points handed to the shaders

# what an effect (or the main "React to") can listen to: key, name
SOURCES = [("bass", "Bass"), ("mid", "Mids"), ("high", "Highs"), ("all", "All"),
           ("kick", "Kick"), ("snare", "Snare / clap"), ("hat", "Hats"), ("accent", "Big kicks"),
           ("beat", "Beat (tempo clock)"), ("range", "Frequency range"),
           # slow and stereo measures (after "range", so saved looks keep their numbers)
           ("energy", "Energy (slow)"), ("bright", "Brightness"), ("busy", "Busyness"),
           ("pan", "Pan (left to right)"), ("width", "Width (stereo)")]
SOURCE_KEYS = [k for k, _ in SOURCES]
SOURCE_NAMES = dict(SOURCES)
SLOW = ("energy", "bright", "busy", "pan", "width")   # smooth measures of the whole sound, not drum hits
HITS = ("kick", "snare", "hat", "accent", "beat")   # hit-style sources: a pulse on each hit, not a level
HOLD = 0.05      # seconds a hit's target stays at 1
FADE = 0.22      # seconds for a hit's meter-style level to fade (time constant)

# where each drum is listened for (Hz). Snare / clap: the crack (2-5 kHz) with some of the body (150-350 Hz)
DETECT = {"kick": (40, 120), "kick_sweep": (120, 250), "snare_lo": (150, 350), "snare_hi": (1500, 5000), "hat": (7000, 14000)}
SNARE_ON_KICK = 0.92   # see the snare below: how big a crack right on a kick has to be
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

    def __init__(self, refractory, quiet=0.6):
        self.refractory = refractory
        self.quiet = quiet               # flux below this never counts as loud (near-silence stays quiet)
        self.floor = 0.0                 # a hit must also reach this fraction of the band's recent peak
        self.peak = 0.0
        self.recent = deque(maxlen=10)   # about 0.1 s at 512-sample hops
        self.last, self.armed = -10.0, True

    def step(self, flux, now, delta):
        """Returns the hit's strength (scaled flux, 0..1) or 0 for no hit."""
        self.peak = max(flux, self.peak * 0.997)        # falls to half in about 2.5 s
        fn = flux / max(self.peak, self.quiet)          # the floor keeps near-silence from counting
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
    @property
    def hit_sens(self):
        """All three drums' sensitivity as one number (their average); setting it sets all three."""
        return sum(self.sens.values()) / len(self.sens)

    @hit_sens.setter
    def hit_sens(self, v):
        self.sens = {k: float(v) for k in ("kick", "snare", "hat")}

    def set_sens(self, saved):
        """Sensitivity from a saved session: one number (older Lumoria: all drums) or {drum: value}."""
        if isinstance(saved, (int, float)):
            self.hit_sens = min(1.0, max(0.0, float(saved)))
        elif isinstance(saved, dict):
            for k in self.sens:
                try:
                    self.sens[k] = min(1.0, max(0.0, float(saved.get(k, self.sens[k]))))
                except (TypeError, ValueError):
                    pass

    def __init__(self):
        self.stream = None
        self.device_name = None
        self.error = None
        self._raw = {k: 0.0 for k in BANDS}
        self._lock = threading.Lock()
        keys = (*BANDS, "all")
        self.level = {k: 0.0 for k in (*keys, *HITS, *SLOW)}
        self.level["pan"] = 0.5
        self.target = dict(self.level)
        self._range = {k: [1.0, 0.0] for k in (*keys, "energy", "bright", "busy", "width")}
        self._feat = dict(bal=0.0, width=0.0, bright=0.0, busy=0.0)   # from the audio thread, already smoothed
        self._energy = 0.0
        self._wave_lr = (np.zeros(SPEC_N, np.float32), np.zeros(SPEC_N, np.float32))   # left / right, for scopes
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
        # how easily each drum counts as a hit, on its own: 0 = only the clearest hits .. 1 = every little one
        self.sens = dict(kick=0.5, snare=0.5, hat=0.5)
        self.swell = [0.0, 0.0, 0.0, 0.0]    # bass, mid, high, all: very slow envelopes (the "sustained" feel)
        self.flow = 0.0                      # a clock that runs faster when the music is busy and never jumps
        self.smooth = 0.3                    # how gradually levels rise and fall: 0 snappy (the old response) .. 1 slow
        self.fast = {k: 0.0 for k in (*BANDS, "all")}   # the old snappy levels, kept for the tempo detector
        self._hits = {k: 0 for k in HITS}
        self.hit_now = {k: False for k in HITS}   # hit this frame (meters, tempo)
        self.hit_t = {k: -10.0 for k in HITS}
        self.last_kick = -10.0
        self._t = None
        # the music's own tempo and beat (tempo.BeatTracker, on the audio thread): (bpm, confidence, seconds
        # since its last beat, time.perf_counter() then, estimate count), or None until it has heard enough
        self.beat_est = None
        self.beat_mult = 1.0   # double / half time (the tempo clock's choice): the tracker places beats on that grid

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
        onsets["kick"].quiet = 0.004   # the kick is measured on plain loudness (see below), a much smaller scale
        onsets["hat"].quiet = 0.35     # hats are quiet in most mixes: let fainter ones count
        tracker = tempo.BeatTracker()
        self.beat_est = None
        kicks = deque(maxlen=8)   # recent kick strengths, to tell the big ones
        state = dict(prev=None, prev_mag=None, samples=0, peak=0.0, peak_hops=0, kick_t=-10.0)
        feat = dict(bal=0.0, width=0.0, bright=0.0, busy=0.0)
        bl, br = np.zeros(1024, np.float32), np.zeros(1024, np.float32)   # the last 1024 samples of each side
        cen = np.flatnonzero((freqs >= 30) & (freqs < 16000))
        busy_bins = np.flatnonzero((freqs >= 60) & (freqs < 8000))
        log_lo, log_hi = math.log(150.0), math.log(5000.0)

        def callback(indata, frames, _t, _status):
            nonlocal buf, bl, br
            tap = self.tap
            if tap:
                tap(indata.copy())
            mono = indata.mean(axis=1)
            buf = np.concatenate((buf, mono))[-n:]
            left, right = indata[:, 0], indata[:, min(1, indata.shape[1] - 1)]
            bl, br = np.concatenate((bl, left))[-1024:], np.concatenate((br, right))[-1024:]
            ease = lambda tau: 1.0 - math.exp(-frames / sr / tau)   # how far to move this block toward a new value
            loud = float(np.sqrt(np.mean(mono * mono)))
            if loud > 1e-4:   # (below that it's silence: leave the stereo picture and brightness where they were)
                if indata.shape[1] >= 2:
                    l, r = indata[:, 0], indata[:, 1]
                    rl, rr = float(np.sqrt(np.mean(l * l))), float(np.sqrt(np.mean(r * r)))
                    side = float(np.sqrt(np.mean(((l - r) * 0.5) ** 2)))
                    mid = float(np.sqrt(np.mean(((l + r) * 0.5) ** 2)))
                    feat["bal"] += ((rr - rl) / (rr + rl + 1e-9) - feat["bal"]) * ease(0.12)
                    feat["width"] += (side / (side + mid + 1e-9) - feat["width"]) * ease(0.12)
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
            if loud > 1e-4:
                c = float((freqs[cen] * mag[cen]).sum() / (mag[cen].sum() + 1e-9))
                bright = (math.log(max(c, 1.0)) - log_lo) / (log_hi - log_lo)
                feat["bright"] += (min(1.0, max(0.0, bright)) - feat["bright"]) * ease(0.3)
            if prev is not None:
                rise = np.maximum(comp - prev, 0.0)
                feat["busy"] += (float(rise[busy_bins].mean()) - feat["busy"]) * ease(1.0)
                flux = {k: float(rise[idx].mean()) if len(idx) else 0.0 for k, idx in det.items()}
                # a kick: its low thump AND its pitch sweep coming down through 120-250 Hz, together, measured on
                # the plain (not compressed) loudness. A new bass note rises in the low band too, but hardly at all
                # in the sweep's range, and compressing would make a quiet bass note look as big as a kick
                lin = np.maximum(mag - state["prev_mag"], 0.0) if state["prev_mag"] is not None else mag * 0
                kick_hit = math.sqrt(float(lin[det["kick"]].mean()) * float(lin[det["kick_sweep"]].mean()))
                # each drum has its own sensitivity, so finding quiet hats never loosens the kick
                sens = {k: min(1.0, max(0.0, v)) for k, v in self.sens.items()}
                delta = {k: 0.12 + 0.36 * (1.0 - v) for k, v in sens.items()}
                # a snare's band also jumps on every kick click and hat, a little less than on a real snare:
                # it only counts when it reaches nearly the band's recent peak (a quiet mix is judged the same)
                onsets["snare"].floor = 0.95 - 0.2 * sens["snare"]
                # a kick has to be a good part as strong as the recent ones (a stray low thud isn't)
                onsets["kick"].floor = 0.5 - 0.2 * sens["kick"]
                lvl = float(comp[det["kick"]].mean())
                # the tempo tracker's envelope: rises across the mix, the kick's range counting double
                tracker.mult = self.beat_mult
                if tracker.push(now, float(rise[busy_bins].mean()) + 2.0 * flux["kick"]) and tracker.bpm:
                    with self._lock:
                        self.beat_est = (tracker.bpm, tracker.conf, tracker.since, time.perf_counter(), tracker.count)
                if onsets["kick"].step(kick_hit, now, delta["kick"]):
                    hits.append("kick")
                    state["kick_t"] = now
                    state["peak"], state["peak_hops"] = lvl, 3   # watch how loud it gets over ~30 ms
                elif state["peak_hops"]:
                    state["peak"] = max(state["peak"], lvl)
                    state["peak_hops"] -= 1
                    if not state["peak_hops"]:   # a big kick: clearly louder than the last few
                        if len(kicks) >= 3 and state["peak"] > sorted(kicks)[len(kicks) // 2] + 0.35:
                            hits.append("accent")
                        kicks.append(state["peak"])
                # snare / clap: its crack. (Its body sits where a kick's pitch sweep does, so it can't tell them apart)
                # A kick's click reaches up into the crack's range too: right on a kick, only a crack nearly as big
                # as the recent snares counts (a real snare on the same beat still is)
                if now - state["kick_t"] < 0.04:
                    onsets["snare"].floor = max(onsets["snare"].floor, SNARE_ON_KICK)
                if onsets["snare"].step(flux["snare_hi"], now, delta["snare"]):
                    hits.append("snare")
                # hats: the top end jumping more than the snare's range does (a snare's noise reaches up there too)
                if onsets["hat"].step(max(0.0, flux["hat"] - 0.8 * flux["snare_hi"]), now, delta["hat"]):
                    hits.append("hat")
            state["prev_mag"] = mag
            with self._lock:
                self._raw = raw
                self._spec_raw, self._wave_raw, self._band_raw = spec, wave, band.astype(np.float32)
                self._feat = dict(feat)
                self._wave_lr = (bl[:: 1024 // SPEC_N].copy(), br[:: 1024 // SPEC_N].copy())
                for h in hits:
                    self._hits[h] += 1

        return callback

    def close(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
        self.stream, self.device_name = None, None

    def shader_data(self, t):
        """128 x 4 floats for the GPU: spectrum, waveform, then the left and right waveforms (for scopes). With
        no input, a gentle idle ripple so visualizers still show where they are."""
        if not self.stream:
            x = np.linspace(0, 1, SPEC_N, dtype=np.float32)
            spec = 0.25 + 0.15 * np.sin(x * 9 + t * 2.0) * np.sin(x * 3.1 - t * 1.3)
            wave = 0.3 * np.sin(x * 25 + t * 3) * np.sin(x * 3.14)
            env = np.sin(x * 3.14)
            return np.stack([spec, wave, 0.4 * np.sin(x * 25 + t * 3) * env,
                             0.4 * np.sin(x * 37 - t * 2) * env]).astype(np.float32)
        with self._lock:
            spec, wave = self._spec_raw.copy(), self._wave_raw.copy()
            wl, wr = self._wave_lr
        # auto-range against a slow-falling peak, then rise fast / fall slowly like a meter
        self._spec_peak = max(float(spec.max()), self._spec_peak * 0.995, 0.2)
        floor = 0.25
        target = np.clip((spec - floor) / max(self._spec_peak - floor, 0.05), 0, 1)
        self.spectrum += (target - self.spectrum) * np.where(target > self.spectrum, 0.6, 0.12)
        peak = max(float(np.abs(wave).max()), 1e-3)
        side = max(float(np.abs(wl).max()), float(np.abs(wr).max()), 1e-3)   # one scale for both, so the shape holds
        return np.stack([self.spectrum, wave / max(peak, 0.1), wl / max(side, 0.1),
                         wr / max(side, 0.1)]).astype(np.float32)

    @staticmethod
    def _autorange(r, v, slow=False):
        """Where v sits between a slow-falling peak and a slow-rising floor (updates r = [floor, peak]). The slow
        measures (energy: builds and drops) use a much longer memory, so a whole section counts as high or low."""
        r[1] = max(v, r[1] * (0.9995 if slow else 0.997))    # slow-falling peak
        r[0] = min(v, r[0] + (0.0002 if slow else 0.0008))   # slow-rising floor
        return max(0.0, (v - r[0]) / max(0.08, r[1] - r[0]))

    def _ease(self, cur, target, dt):
        """A level moving toward its target at the Smoothness setting's speed: from the old snappy response (about
        14 ms up, 100 ms down) to a slow, flowing one (about 0.35 s up, 2 s down), whatever the frame rate."""
        s = min(1.0, max(0.0, self.smooth))
        tau = 0.014 * 25.0 ** s if target > cur else 0.103 * 19.4 ** s
        return cur + (target - cur) * (1.0 - math.exp(-dt / tau))

    def _slow_signals(self, dt):
        """Sustained signals for effects that should breathe with the music instead of twitching to it: slow
        envelopes of each band (about 0.6 s to rise, 2 s to fall) and a flow clock that speeds up with the energy."""
        lv = self.fast
        for i, k in enumerate(("bass", "mid", "high", "all")):
            cur, tgt = self.swell[i], lv[k]
            tau = 0.6 if tgt > cur else 2.0
            self.swell[i] = cur + (tgt - cur) * (1.0 - math.exp(-dt / tau))
        busy = 0.5 * self.swell[3] + 0.5 * self.level.get("energy", 0.0)
        self.flow += dt * (0.12 + 1.5 * busy)

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
            feat = dict(self._feat)
        live = self.stream is not None
        self._slow_signals(dt)
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
            for k in SLOW:
                rest = 0.5 if k == "pan" else 0.0
                self.target[k] = rest
                self.level[k] += (rest - self.level[k]) * 0.1
            self._energy *= 0.98
            return
        raw["all"] = sum(raw.values()) / 3
        for k, v in raw.items():
            target = self._autorange(self._range[k], v)
            cur = self.level[k]
            self.target[k] = target
            self.level[k] = self._ease(cur, target, dt)
            self.fast[k] += (target - self.fast[k]) * (0.7 if target > self.fast[k] else 0.15)
        # slow and stereo measures: smooth, and relative to this music's own range
        self._energy += (raw["all"] - self._energy) * (1 - math.exp(-dt / 1.5))
        slow = dict(energy=self._autorange(self._range["energy"], self._energy, slow=True),
                    bright=self._autorange(self._range["bright"], feat["bright"]),
                    busy=self._autorange(self._range["busy"], feat["busy"]),
                    width=self._autorange(self._range["width"], feat["width"]),
                    pan=0.5 + 0.5 * min(1.0, max(-1.0, feat["bal"] * 2.5)))   # a moderate pan reaches the edges
        for k, v in slow.items():
            self.target[k] = v
            self.level[k] += (v - self.level[k]) * 0.35
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
            r["level"] = self._ease(r["level"], target, dt)

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
