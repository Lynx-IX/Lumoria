"""The OBS Virtual Camera, fed directly: frames go into the shared-memory queue that OBS's virtual camera device
(installed with OBS Studio) reads, the same queue OBS itself writes when you press "Start Virtual Camera".

Layout (OBS's shared-memory-queue): a header, then three frame slots, each a 64-bit timestamp padded to 32 bytes
followed by an NV12 picture (full-size luma, then half-size interleaved U/V). The writer bumps write_idx, fills
slot write_idx % 3, then publishes it through read_idx and marks the queue ready.
"""
import ctypes
import time
from ctypes import wintypes

import cv2
import numpy as np

NAME = "OBSVirtualCamVideo"
STARTING, READY, STOPPING = 1, 2, 3
FRAME_HEADER = 32


class _Header(ctypes.Structure):
    _fields_ = [("write_idx", ctypes.c_uint32), ("read_idx", ctypes.c_uint32), ("state", ctypes.c_uint32),
                ("offsets", ctypes.c_uint32 * 3), ("type", ctypes.c_uint32), ("cx", ctypes.c_uint32),
                ("cy", ctypes.c_uint32), ("interval", ctypes.c_uint64), ("reserved", ctypes.c_uint32 * 8)]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileMappingW.restype = wintypes.HANDLE
_k32.CreateFileMappingW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.DWORD, wintypes.LPCWSTR]
_k32.MapViewOfFile.restype = ctypes.c_void_p
_k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
_k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
ERROR_ALREADY_EXISTS, FILE_MAP_ALL_ACCESS, PAGE_READWRITE = 183, 0xF001F, 0x04


def _align(n):
    return (n + 31) & ~31


class VirtualCamera:
    def __init__(self, width, height, fps):
        if width % 2 or height % 2:
            raise ValueError("the virtual camera needs an even width and height")
        self.width, self.height = width, height
        frame = width * height * 3 // 2
        offsets, size = [], _align(ctypes.sizeof(_Header))
        for _ in range(3):
            offsets.append(size)
            size = _align(size + FRAME_HEADER + frame)
        self._handle = _k32.CreateFileMappingW(wintypes.HANDLE(-1), None, PAGE_READWRITE, 0, size, NAME)
        if not self._handle:
            raise OSError("couldn't create the virtual camera's shared memory")
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            _k32.CloseHandle(self._handle)
            raise RuntimeError("the OBS Virtual Camera is already in use (OBS's own 'Start Virtual Camera'?)")
        self._view = _k32.MapViewOfFile(self._handle, FILE_MAP_ALL_ACCESS, 0, 0, size)
        if not self._view:
            _k32.CloseHandle(self._handle)
            raise OSError("couldn't map the virtual camera's shared memory")
        self._header = _Header.from_address(self._view)
        h = self._header
        h.state, h.cx, h.cy, h.interval = STARTING, width, height, round(10_000_000 / fps)   # 100 ns units
        for i, off in enumerate(offsets):
            h.offsets[i] = off
        buf = (ctypes.c_uint8 * size).from_address(self._view)
        self._slots = [(np.frombuffer(buf, np.uint64, 1, off),
                        np.frombuffer(buf, np.uint8, frame, off + FRAME_HEADER)) for off in offsets]
        self._uv = np.empty((height // 2, width), np.uint8)

    def send(self, rgb):
        """One frame: RGB, top row first, the camera's size."""
        i420 = cv2.cvtColor(rgb, cv2.COLOR_RGB2YUV_I420)   # Y, then U, then V planes
        w, h = self.width, self.height
        y = i420[:h]
        u = i420[h:h + h // 4].reshape(h // 2, w // 2)
        v = i420[h + h // 4:].reshape(h // 2, w // 2)
        self._uv[:, 0::2], self._uv[:, 1::2] = u, v   # NV12: U and V interleaved
        hd = self._header
        idx = hd.write_idx + 1
        hd.write_idx = idx
        ts, pixels = self._slots[idx % 3]
        pixels[:w * h] = y.reshape(-1)
        pixels[w * h:] = self._uv.reshape(-1)
        ts[0] = time.perf_counter_ns() // 100
        hd.read_idx = idx
        hd.state = READY

    def close(self):
        if self._view:
            self._header.state = STOPPING
            self._slots = self._header = None
            _k32.UnmapViewOfFile(ctypes.c_void_p(self._view))
            _k32.CloseHandle(self._handle)
            self._view = None
