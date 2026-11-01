"""Audio analysis: bass / mid / high levels from any input device (mic, line in, loopback)."""
import threading

import numpy as np
import sounddevice as sd

BANDS = {"bass": (20, 160), "mid": (160, 2000), "high": (2000, 10000)}
SPEC_N = 128   # spectrum bands / waveform points handed to the shaders


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


class AudioAnalyzer:
    def __init__(self):
        self.stream = None
        self.device_name = None
        self.error = None
        self._raw = {k: 0.0 for k in BANDS}
        self._lock = threading.Lock()
        # smoothed, auto-ranged 0..1 levels read by the renderer
        self.level = {k: 0.0 for k in (*BANDS, "all")}
        self._range = {k: [1.0, 0.0] for k in self.level}
        # for visualizers: log-spaced spectrum (0..1) and the latest stretch of waveform (-1..1)
        self._spec_raw = np.zeros(SPEC_N, np.float32)
        self._wave_raw = np.zeros(SPEC_N, np.float32)
        self.spectrum = np.zeros(SPEC_N, np.float32)
        self._spec_peak = 0.3
        self.tap = None   # also hand each block of sound to this (the recorder), when set
        self.rate, self.channels = 0, 0

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
            n = 2048
            freqs = np.fft.rfftfreq(n, 1 / sr)
            masks = {k: (freqs >= lo) & (freqs < hi) for k, (lo, hi) in BANDS.items()}
            window = np.hanning(n).astype(np.float32)
            buf = np.zeros(n, np.float32)
            # spectrum bands 30 Hz .. 16 kHz, log spaced; each band is at least one FFT bin wide
            edges = np.geomspace(30, min(16000, sr / 2 - 1), SPEC_N + 1)
            lo_bin = np.searchsorted(freqs, edges[:-1])
            hi_bin = np.maximum(np.searchsorted(freqs, edges[1:]), lo_bin + 1)

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
                with self._lock:
                    self._raw = raw
                    self._spec_raw, self._wave_raw = spec, wave

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

    def update(self):
        """Call once per video frame: smooths and auto-ranges levels so quiet and loud sources both work."""
        if not self.stream:
            for k in self.level:
                self.level[k] *= 0.9
            return
        with self._lock:
            raw = dict(self._raw)
        raw["all"] = sum(raw.values()) / 3
        for k, v in raw.items():
            r = self._range[k]
            r[1] = max(v, r[1] * 0.997)   # slow-falling peak
            r[0] = min(v, r[0] + 0.0008)  # slow-rising floor
            target = max(0.0, (v - r[0]) / max(0.08, r[1] - r[0]))
            cur = self.level[k]
            self.level[k] = cur + (target - cur) * (0.7 if target > cur else 0.15)
