"""AI person segmentation (Robust Video Matting) on a worker thread.

Feed it small RGB frames (top row first); it returns an alpha matte (1 = person) of the same size.
Runs on the GPU through DirectML when available, else on the CPU.
"""
import threading
import time

import numpy as np

MODEL = "rvm_mobilenetv3_fp32.onnx"
# AI Mask quality: (label, input long side in px, internal downsample ratio)
QUALITY = [("Fast", 512, 0.5), ("Balanced", 640, 0.5), ("High", 960, 0.5), ("Max", 1280, 0.375)]


class Segmenter:
    def __init__(self, model_path):
        self.model_path = model_path
        self.error = None
        self.loaded = False
        self.ms = 0.0                       # last inference time
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._frame = None                  # waiting to be processed
        self._mask = None                   # finished, not yet collected
        self._reset = False
        self._thread = None
        self.ratio = QUALITY[1][2]

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def wants_frame(self):
        with self._lock:
            return self.loaded and self._frame is None

    def submit(self, rgb):
        with self._lock:
            self._frame = rgb
        self._wake.set()

    def take_mask(self):
        with self._lock:
            mask, self._mask = self._mask, None
        return mask

    def reset(self):
        """Forget temporal memory (call when the source changes)."""
        self._reset = True

    def _run(self):
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            # the work is on the GPU; by default the CPU helper threads spin while they wait, burning a core
            opts.intra_op_num_threads = 2
            opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
            opts.add_session_config_entry("session.inter_op.allow_spinning", "0")
            session = ort.InferenceSession(self.model_path, sess_options=opts,
                                           providers=["DmlExecutionProvider", "CPUExecutionProvider"])
        except Exception as e:
            self.error = f"Background removal unavailable: {e}"
            return
        empty = [np.zeros((1, 1, 1, 1), np.float32)] * 4
        rec, size = empty, None
        self.loaded = True
        while True:
            self._wake.wait()
            self._wake.clear()
            with self._lock:
                frame = self._frame
            if frame is None:
                continue
            ratio = self.ratio
            if self._reset or (frame.shape, ratio) != size:   # recurrent state is tied to the frame size
                rec, size, self._reset = empty, (frame.shape, ratio), False
            t0 = time.perf_counter()
            src = (frame.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
            out = session.run(None, {"src": src, "r1i": rec[0], "r2i": rec[1], "r3i": rec[2],
                                     "r4i": rec[3], "downsample_ratio": np.array([ratio], np.float32)})
            rec = out[2:]
            mask = (np.clip(out[1][0, 0], 0, 1) * 255).astype(np.uint8)
            self.ms = (time.perf_counter() - t0) * 1000
            with self._lock:
                self._mask, self._frame = mask, None
