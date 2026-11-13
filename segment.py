"""AI masks on a worker thread: the person (Robust Video Matting) or the main subject (U-2-Net small: a pet,
an object, a person - whatever the picture is about).

Feed it small RGB frames (top row first); it returns an alpha matte (1 = person / subject) of the same size.
Runs on the GPU through DirectML when available, else on the CPU.
"""
import threading
import time

import cv2
import numpy as np

MODEL = "rvm_mobilenetv3_fp32.onnx"
SUBJECT_MODEL = "u2netp.onnx"
MODELS = {"person": MODEL, "subject": SUBJECT_MODEL}
SUBJECT_SIZE = 320                  # the subject model only takes 320 x 320 pictures
SUBJECT_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
SUBJECT_STD = np.array([0.229, 0.224, 0.225], np.float32)
SUBJECT_KEEP = 0.45                 # how much of the last mask each new subject mask keeps (it has no video memory
#                                     of its own, so this steadies its edges from frame to frame)
SLOW_MS = 40                        # a mask that takes longer than this can't keep up with live video
# AI Mask quality: (label, input long side in px, internal downsample ratio)
QUALITY = [("Fast", 512, 0.5), ("Balanced", 640, 0.5), ("High", 960, 0.5), ("Max", 1280, 0.375)]
# Every segmenter (the main source's and one per Source 2-4) shares the graphics card through DirectML, and two
# of them building or running a model at the same moment from different threads crashes the whole program. So
# they take turns: one model call at a time (each takes a few ms, so several sources still keep up).
GPU_TURN = threading.Lock()


class Segmenter:
    def __init__(self, model_path, kind="person"):
        self.model_path = model_path
        self.kind = kind                    # "person" or "subject"
        self.error = None
        self.loaded = False
        self.ms = 0.0                       # last inference time
        self.ms_avg = 0.0                   # its running average (for the "too slow on this card" note)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._frame = None                  # waiting to be processed
        self._mask = None                   # finished, not yet collected
        self._reset = False
        self._thread = None
        self._stop = False
        self._notice = None                 # a one-off message for the user (a hiccup it recovered from)
        self.failures = 0                   # inference errors so far (for the self-test and tests)
        self.ratio = QUALITY[1][2]

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        """Let the worker finish (LumaTRX is closing)."""
        self._stop = True
        self._wake.set()
        if self._thread:
            self._thread.join(2)

    def take_notice(self):
        """A message about a problem it recovered from, once."""
        note, self._notice = self._notice, None
        return note

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

    def _session(self, gpu=True):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        # the work is on the GPU; by default the CPU helper threads spin while they wait, burning a core
        opts.intra_op_num_threads = 2
        opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
        opts.add_session_config_entry("session.inter_op.allow_spinning", "0")
        providers = (["DmlExecutionProvider"] if gpu else []) + ["CPUExecutionProvider"]
        with GPU_TURN:
            return ort.InferenceSession(self.model_path, sess_options=opts, providers=providers)

    def slow(self):
        """It can't keep up with live video on this computer (only the mask lags; the picture doesn't)."""
        return self.loaded and self.ms_avg > SLOW_MS

    def _subject(self, session, frame, last):
        h, w = frame.shape[:2]
        x = cv2.resize(frame, (SUBJECT_SIZE, SUBJECT_SIZE), interpolation=cv2.INTER_AREA).astype(np.float32)
        x = ((x / max(float(x.max()), 1.0) - SUBJECT_MEAN) / SUBJECT_STD).transpose(2, 0, 1)[None]
        with GPU_TURN:
            m = session.run(None, {session.get_inputs()[0].name: x})[0][0, 0]
        m = cv2.resize(np.clip(m, 0, 1), (w, h), interpolation=cv2.INTER_LINEAR)
        if last is not None and last.shape == m.shape:
            m = last * SUBJECT_KEEP + m * (1 - SUBJECT_KEEP)
        return m

    def _run(self):
        try:
            session = self._session()
        except Exception as e:
            self.error = f"Background removal unavailable: {e}"
            return
        empty = [np.zeros((1, 1, 1, 1), np.float32)] * 4
        rec, size, in_a_row, gpu = empty, None, 0, True
        last = None                         # the subject mask before (for smoothing)
        self.loaded = True
        while not self._stop:
            self._wake.wait()
            self._wake.clear()
            if self._stop:
                break
            with self._lock:
                frame = self._frame
            if frame is None:
                continue
            ratio = self.ratio
            if self._reset or (frame.shape, ratio) != size:   # recurrent state is tied to the frame size
                rec, size, self._reset, last = empty, (frame.shape, ratio), False, None
            t0 = time.perf_counter()
            try:
                if self.kind == "subject":
                    last = self._subject(session, frame, last)
                    mask = (last * 255).astype(np.uint8)
                else:
                    src = (frame.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
                    with GPU_TURN:
                        out = session.run(None, {"src": src, "r1i": rec[0], "r2i": rec[1], "r3i": rec[2],
                                                 "r4i": rec[3], "downsample_ratio": np.array([ratio], np.float32)})
                    rec = out[2:]
                    mask = (np.clip(out[1][0, 0], 0, 1) * 255).astype(np.uint8)
                in_a_row = 0
            except Exception as e:   # a hiccup (e.g. the graphics driver reset): start the memory over, carry on
                self.failures += 1
                in_a_row += 1
                rec, mask, last = empty, None, None
                if in_a_row >= 3:    # it keeps failing: build it again, on the CPU if the GPU is the trouble
                    try:
                        session, gpu = self._session(gpu=False), False
                        in_a_row = 0
                        self._notice = "Background removal had a problem and restarted (now on the CPU, a bit slower)"
                    except Exception as e2:
                        self.error, self.loaded = f"Background removal stopped: {e2}", False
                        return
                else:
                    self._notice = f"Background removal had a hiccup and carried on ({type(e).__name__})"
            self.ms = (time.perf_counter() - t0) * 1000
            self.ms_avg = self.ms if self.ms_avg == 0 else self.ms_avg * 0.9 + self.ms * 0.1
            with self._lock:
                self._mask, self._frame = mask, None
