"""Recording the output, with sound, to one video file.

The writing happens in a small helper process (started quietly with LumaTRX), so starting an encoder and
encoding frames never stall the show: LumaTRX copies each frame into shared memory and sends a note down a pipe.
Frames arrive whenever LumaTRX renders one; the file runs at a fixed rate (30 or 60 fps), so a frame is written
as many times as the clock says (repeated if the app is running slower, skipped if faster) and the video plays
back at real speed. Sound comes from LumaTRX's audio input (the one picked under Audio), counted by its samples.

Written with PyAV (FFmpeg's libraries). H.264 uses the graphics card's own encoder when there is one (NVIDIA
NVENC, AMD AMF, Intel Quick Sync), else Windows' Media Foundation, else the x264 software encoder.

Run as `python recorder.py <pipe>` (or `LumaTRX.exe --record-worker <pipe>`) it is that helper.
"""
import os
import subprocess
import sys
import threading
import time
from multiprocessing import shared_memory
from multiprocessing.connection import Client, Listener

import numpy as np

# (name, extension, video codec, bits per pixel per frame, sound codec)
FORMATS = [("MP4 (H.264)", ".mp4", "h264", 0.12, "aac"),
           ("MP4 small", ".mp4", "h264", 0.04, "aac"),
           ("MOV for editing (MJPEG)", ".mov", "mjpeg", 0.8, "pcm_s16le")]
H264 = [("h264_nvenc", "nv12"), ("h264_amf", "nv12"), ("h264_qsv", "nv12"), ("h264_mf", "nv12"),
        ("libx264", "yuv420p")]
SLOTS = 6   # frames that can wait in shared memory for the helper


class Recorder:
    """LumaTRX's side: starts the helper, hands it frames and sound, keeps the timer."""

    def __init__(self):
        self.path, self.error, self.encoder = None, None, ""
        self.found = None   # the H.264 encoder the helper picked on this PC ("" if none), once it knows
        self.ready = False   # the helper has the file open and takes frames
        self.fps, self.t0, self.dropped, self.sound = 30, None, 0, False
        self._conn, self._proc, self._shm, self._free = None, None, None, []
        self._send_lock, self._state = threading.Lock(), "idle"   # idle / starting / recording / stopping
        self._launch_lock, self._t0_wall, self._length = threading.Lock(), 0.0, 0.0
        self._done = threading.Event()
        threading.Thread(target=self._launch, daemon=True).start()   # warm up in the background

    @property
    def recording(self):
        return self._state in ("starting", "recording")

    def _launch(self):
        """Start the helper process and connect to it (once; again if it ever dies)."""
        with self._launch_lock:
            if not (self._proc and self._proc.poll() is None and self._conn):
                self._spawn()

    def _spawn(self):
        address = rf"\\.\pipe\lumatrx-rec-{os.getpid()}-{time.perf_counter_ns()}"
        listener = Listener(address, family="AF_PIPE")
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--record-worker", address]
        else:
            exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            cmd = [exe if os.path.exists(exe) else sys.executable, os.path.abspath(__file__), address]
        self._proc = subprocess.Popen(cmd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        conn = listener.accept()
        listener.close()
        self._conn = conn
        threading.Thread(target=self._listen, args=(conn,), daemon=True).start()

    def _listen(self, conn):
        """Replies from the helper: ready / a slot is free again / done / errors."""
        try:
            while True:
                msg = conn.recv()
                if msg[0] == "found":
                    self.found = msg[1]
                elif msg[0] == "ready":
                    self.encoder, self.ready, self._state = msg[1], True, "recording"
                elif msg[0] == "free":
                    self._free.append(msg[1])
                elif msg[0] == "error":
                    self.error, self.ready, self._state = msg[1], False, "idle"
                    self._release()
                elif msg[0] == "done":
                    if msg[1]:
                        self.error = msg[1]
                    self._done.set()
        except (EOFError, OSError):
            self._conn, self.ready = None, False
            if self._state != "idle":
                self.error, self._state = "The recording helper stopped unexpectedly", "idle"
            self._done.set()

    def _send(self, msg):
        with self._send_lock:
            self._conn.send(msg)

    def start(self, folder, size, fps, fmt, sound=None):
        """Begin a new file (named by date and time) in folder; returns its path. sound: (sample rate, channels)
        of the audio input, or None for video only. Problems end the recording with self.error set."""
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, time.strftime("LumaTRX %Y-%m-%d %H-%M-%S") + FORMATS[fmt][1])
        self.fps, self.error, self.ready, self.sound = fps, None, False, bool(sound)
        self.t0, self.dropped, self._state = None, 0, "starting"
        w, h = size
        self._frame_bytes = w * h * 3
        self._shm = shared_memory.SharedMemory(create=True, size=self._frame_bytes * SLOTS)
        self._free = list(range(SLOTS))
        self._done.clear()

        def go():
            try:
                self._launch()
                self._send(("start", self.path, fmt, size, fps, sound, self._shm.name))
            except Exception as e:
                self.error, self._state = f"Recording couldn't start: {e}", "idle"
                self._release()
        threading.Thread(target=go, daemon=True).start()
        return self.path

    def push(self, rgb, t):
        """A rendered frame (RGB, top row first) at time t; dropped if the helper has fallen behind."""
        if not self.ready:
            return
        if self.t0 is None:
            self.t0, self._t0_wall = t, time.perf_counter()   # sound is taken from here on too
        if not self._free:
            self.dropped += 1
            return
        slot = self._free.pop(0)
        np.ndarray(rgb.shape, np.uint8, self._shm.buf, slot * self._frame_bytes)[:] = rgb
        try:
            self._send(("v", slot, t - self.t0))
        except OSError:
            pass

    def push_sound(self, samples):
        """A block of sound from the audio input (frames x channels, float32), called from its thread."""
        if self.ready and self.sound and self.t0 is not None:
            try:
                self._send(("a", samples.astype(np.float32).tobytes(), samples.shape[1]))
            except OSError:
                pass

    def seconds(self):
        if self.t0 is None:
            return 0.0
        return time.perf_counter() - self._t0_wall if self.recording else self._length

    def failed(self):
        """The error, once, if the recording couldn't start or broke off (it has then stopped by itself)."""
        if self.error and self._state == "idle":
            err, self.error = self.error, None
            return err
        return None

    def stop(self):
        if not self.recording:
            return None
        self._length = self.seconds()
        was_ready, self.ready, self._state = self.ready, False, "stopping"
        if was_ready and self._conn:
            try:
                self._send(("stop",))
                self._done.wait(15)
            except OSError:
                pass
        self._state = "idle"
        self._release()
        return self.path

    def _release(self):
        if self._shm:
            try:
                self._shm.close()
                self._shm.unlink()
            except (OSError, FileNotFoundError):
                pass
            self._shm = None

    def close(self):
        """LumaTRX is quitting: finish any file and let the helper go."""
        self.stop()
        if self._conn:
            try:
                self._send(("quit",))
            except OSError:
                pass
        if self._proc:
            try:
                self._proc.wait(3)
            except subprocess.TimeoutExpired:
                self._proc.kill()


# ---------------------------------------------------------------- the helper process

def h264_encoder():
    """(codec name, pixel format) of the best H.264 encoder that opens on this PC: hardware first."""
    import av
    from fractions import Fraction
    for name, pix in H264:
        try:
            cc = av.CodecContext.create(name, "w")
            cc.width, cc.height, cc.pix_fmt, cc.time_base = 640, 360, pix, Fraction(1, 30)
            cc.bit_rate = 2_000_000
            cc.open()
            return name, pix
        except Exception:
            continue
    return "", ""


def worker_main(address):
    import av
    from fractions import Fraction
    conn = Client(address, family="AF_PIPE")
    h264 = h264_encoder()   # find it now, while nobody is waiting
    conn.send(("found", h264[0]))
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg[0] == "quit":
            return
        if msg[0] != "start":
            continue
        _, path, fmt, (w, h), fps, sound, shm_name = msg
        name, _, vcodec, bpp, acodec = FORMATS[fmt]
        shm = box = None
        try:
            shm = shared_memory.SharedMemory(name=shm_name)
            if vcodec == "h264":
                h264 = h264 or h264_encoder()
                vcodec, pix = h264
                if not vcodec:
                    raise RuntimeError("no H.264 encoder")
            else:
                pix = "yuvj420p"
            box = av.open(path, "w")
            video = box.add_stream(vcodec, rate=fps)
            video.width, video.height, video.pix_fmt = w, h, pix
            video.bit_rate = int(max(2e6, w * h * fps * bpp))
            video.time_base = Fraction(1, fps)
            audio, layout = None, "mono"
            if sound:
                rate, channels = sound
                layout = "stereo" if channels > 1 else "mono"
                audio = box.add_stream(acodec, rate=rate, layout=layout)
                if acodec == "aac":
                    audio.bit_rate = 192_000
            video.codec_context.open()   # start the encoder now (it can take a moment), not on the first frame
        except Exception as e:
            conn.send(("error", f"{name} recording isn't available on this PC ({e})"))
            if box:
                box.close()
            if shm:
                shm.close()
            continue
        conn.send(("ready", vcodec))
        written, samples, error, rgb = 0, 0, None, None
        frame_bytes = w * h * 3
        try:
            while True:
                msg = conn.recv()
                if msg[0] == "stop":
                    break
                if msg[0] == "a":
                    data = np.frombuffer(msg[1], np.float32).reshape(-1, msg[2])
                    frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(data.reshape(1, -1)), format="flt",
                                                       layout=layout)
                    frame.sample_rate, frame.pts = audio.rate, samples
                    frame.time_base = Fraction(1, audio.rate)
                    samples += data.shape[0]
                    box.mux(audio.encode(frame))
                    continue
                _, slot, t = msg
                start = slot * frame_bytes
                rgb = np.frombuffer(shm.buf[start:start + frame_bytes], np.uint8).reshape(h, w, 3)
                due = int(t * fps) + 1   # frames the file should have by now
                n = max(0, min(due - written, 10))
                frame = av.VideoFrame.from_ndarray(rgb, format="rgb24").reformat(format=pix) if n else None
                conn.send(("free", slot))
                for _ in range(n):
                    frame.pts = written
                    box.mux(video.encode(frame))
                    written += 1
            box.mux(video.encode())
            if audio:
                box.mux(audio.encode())
        except Exception as e:
            error = f"Recording stopped: {e}"
        finally:
            try:
                box.close()
            except Exception:
                pass
            rgb = None   # let go of the shared memory view before closing it
            shm.close()
        conn.send(("done", error))


if __name__ == "__main__":
    worker_main(sys.argv[1])
