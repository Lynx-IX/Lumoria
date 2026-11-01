"""Capturing what a Windows output device plays ("what you hear"), through WASAPI loopback, the same way OBS's
Desktop Audio works. PortAudio (sounddevice) can't do this, so it talks to Windows' audio system directly.

LoopbackStream looks enough like a sounddevice InputStream for AudioAnalyzer: it calls callback(block, frames,
None, None) with float32 blocks (frames x channels) from its own thread, and has start / stop / close.
"""
import ctypes
import threading
import time
from ctypes import HRESULT, POINTER, byref, c_float, c_int16, c_int32, c_uint32, c_uint64, c_void_p, c_wchar_p
from ctypes import wintypes

import comtypes
import numpy as np
from comtypes import CLSCTX_ALL, COMMETHOD, GUID, IUnknown

E_RENDER, DEVICE_ACTIVE, CONSOLE = 0, 1, 0
SHARED, LOOPBACK, SILENT = 0, 0x00020000, 0x2


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("val", c_void_p), ("pad", c_void_p)]


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD), ("nSamplesPerSec", wintypes.DWORD),
                ("nAvgBytesPerSec", wintypes.DWORD), ("nBlockAlign", wintypes.WORD),
                ("wBitsPerSample", wintypes.WORD), ("cbSize", wintypes.WORD)]


class WAVEFORMATEXTENSIBLE(ctypes.Structure):
    _fields_ = [("Format", WAVEFORMATEX), ("Samples", wintypes.WORD), ("dwChannelMask", wintypes.DWORD),
                ("SubFormat", GUID)]


FLOAT_FORMAT = GUID("{00000003-0000-0010-8000-00AA00389B71}")   # KSDATAFORMAT_SUBTYPE_IEEE_FLOAT
FRIENDLY_NAME = PROPERTYKEY(GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 14)


class IPropertyStore(IUnknown):
    _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    _methods_ = [COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(wintypes.DWORD))),
                 COMMETHOD([], HRESULT, "GetAt", (["in"], wintypes.DWORD), (["out"], POINTER(PROPERTYKEY))),
                 COMMETHOD([], HRESULT, "GetValue", (["in"], POINTER(PROPERTYKEY)), (["out"], POINTER(PROPVARIANT)))]


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [COMMETHOD([], HRESULT, "Activate", (["in"], POINTER(GUID)), (["in"], wintypes.DWORD),
                           (["in"], c_void_p), (["out"], POINTER(c_void_p))),
                 COMMETHOD([], HRESULT, "OpenPropertyStore", (["in"], wintypes.DWORD),
                           (["out"], POINTER(POINTER(IPropertyStore)))),
                 COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(c_wchar_p))),
                 COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(wintypes.DWORD)))]


class IMMDeviceCollection(IUnknown):
    _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
    _methods_ = [COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_uint32))),
                 COMMETHOD([], HRESULT, "Item", (["in"], c_uint32), (["out"], POINTER(POINTER(IMMDevice))))]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [COMMETHOD([], HRESULT, "EnumAudioEndpoints", (["in"], c_int32), (["in"], wintypes.DWORD),
                           (["out"], POINTER(POINTER(IMMDeviceCollection)))),
                 COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint", (["in"], c_int32), (["in"], c_int32),
                           (["out"], POINTER(POINTER(IMMDevice)))),
                 COMMETHOD([], HRESULT, "GetDevice", (["in"], c_wchar_p), (["out"], POINTER(POINTER(IMMDevice))))]


class IAudioClient(IUnknown):
    _iid_ = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
    _methods_ = [COMMETHOD([], HRESULT, "Initialize", (["in"], c_int32), (["in"], wintypes.DWORD),
                           (["in"], ctypes.c_longlong), (["in"], ctypes.c_longlong), (["in"], c_void_p),
                           (["in"], c_void_p)),
                 COMMETHOD([], HRESULT, "GetBufferSize", (["out"], POINTER(c_uint32))),
                 COMMETHOD([], HRESULT, "GetStreamLatency", (["out"], POINTER(ctypes.c_longlong))),
                 COMMETHOD([], HRESULT, "GetCurrentPadding", (["out"], POINTER(c_uint32))),
                 COMMETHOD([], HRESULT, "IsFormatSupported", (["in"], c_int32), (["in"], c_void_p),
                           (["out"], POINTER(c_void_p))),
                 COMMETHOD([], HRESULT, "GetMixFormat", (["out"], POINTER(c_void_p))),
                 COMMETHOD([], HRESULT, "GetDevicePeriod", (["out"], POINTER(ctypes.c_longlong)),
                           (["out"], POINTER(ctypes.c_longlong))),
                 COMMETHOD([], HRESULT, "Start"),
                 COMMETHOD([], HRESULT, "Stop"),
                 COMMETHOD([], HRESULT, "Reset"),
                 COMMETHOD([], HRESULT, "SetEventHandle", (["in"], wintypes.HANDLE)),
                 COMMETHOD([], HRESULT, "GetService", (["in"], POINTER(GUID)), (["out"], POINTER(c_void_p)))]


class IAudioCaptureClient(IUnknown):
    _iid_ = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
    _methods_ = [COMMETHOD([], HRESULT, "GetBuffer", (["out"], POINTER(c_void_p)), (["out"], POINTER(c_uint32)),
                           (["out"], POINTER(wintypes.DWORD)), (["out"], POINTER(c_uint64)),
                           (["out"], POINTER(c_uint64))),
                 COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32)),
                 COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32)))]


def _enumerator():
    return comtypes.CoCreateInstance(GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}"), IMMDeviceEnumerator,
                                     CLSCTX_ALL)


def _name(device):
    try:
        value = device.OpenPropertyStore(0).GetValue(byref(FRIENDLY_NAME))
        return ctypes.wstring_at(value.val) if value.vt == 31 else "Output"
    except Exception:
        return "Output"


def list_outputs():
    """[(device id, name)] for the active output devices, Windows' default first."""
    try:
        comtypes.CoInitialize()
    except OSError:
        pass
    try:
        en = _enumerator()
        default = en.GetDefaultAudioEndpoint(E_RENDER, CONSOLE).GetId()
        devices = en.EnumAudioEndpoints(E_RENDER, DEVICE_ACTIVE)
        out = []
        for i in range(devices.GetCount()):
            d = devices.Item(i)
            out.append((d.GetId(), _name(d)))
        out.sort(key=lambda o: o[0] != default)
        return out
    except Exception:
        return []


class LoopbackStream:
    """Captures what one output device plays. Silence still arrives (as zeros), so a recording's sound keeps
    pace with its picture even when nothing is playing (Windows sends nothing at all then)."""

    def __init__(self, device_id, callback):
        self.device_id, self.callback = device_id, callback
        self.samplerate, self.channels, self.error = 0, 0, None
        self._stop, self._thread = threading.Event(), None
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self._thread.start()
        ready.wait(5)
        if self.error or not self.samplerate:
            raise RuntimeError(self.error or "the output device didn't start")

    def start(self):
        pass   # already running: capture starts as soon as the device is open

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(2)

    def close(self):
        self.stop()

    def _run(self, ready):
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        try:
            device = _enumerator().GetDevice(self.device_id)
            client = ctypes.cast(device.Activate(byref(IAudioClient._iid_), CLSCTX_ALL, None),
                                 POINTER(IAudioClient))
            fmt_ptr = client.GetMixFormat()
            fmt = WAVEFORMATEX.from_address(fmt_ptr)
            rate, ch, bits = fmt.nSamplesPerSec, fmt.nChannels, fmt.wBitsPerSample
            is_float = fmt.wFormatTag == 3 or (fmt.wFormatTag == 0xFFFE and
                                               WAVEFORMATEXTENSIBLE.from_address(fmt_ptr).SubFormat == FLOAT_FORMAT)
            client.Initialize(SHARED, LOOPBACK, 2_000_000, 0, fmt_ptr, None)   # 200 ms buffer
            capture = ctypes.cast(client.GetService(byref(IAudioCaptureClient._iid_)), POINTER(IAudioCaptureClient))
            client.Start()
        except Exception as e:
            self.error = f"Couldn't listen to that output: {e}"
            ready.set()
            return
        self.samplerate, self.channels = rate, min(ch, 2)
        ready.set()
        sample = c_float if is_float and bits == 32 else (c_int16 if bits == 16 else c_int32)
        scale = 1.0 if sample is c_float else float(2 ** (bits - 1))
        t0, delivered = time.perf_counter(), 0
        try:
            while not self._stop.is_set():
                got = False
                while capture.GetNextPacketSize():
                    data, frames, flags, _, _ = capture.GetBuffer()
                    if flags & SILENT or not data:
                        block = np.zeros((frames, ch), np.float32)
                    else:
                        raw = np.ctypeslib.as_array(ctypes.cast(data, POINTER(sample)), (frames * ch,))
                        block = (raw.astype(np.float32) / scale).reshape(frames, ch)
                    capture.ReleaseBuffer(frames)
                    self._deliver(block[:, :2], frames)
                    delivered += frames
                    got = True
                # nothing playing: Windows sends nothing, so fill in silence to keep the clock honest
                behind = int((time.perf_counter() - t0) * rate) - delivered
                if not got and behind > rate // 20:
                    self._deliver(np.zeros((behind, min(ch, 2)), np.float32), behind)
                    delivered += behind
                elif got and behind < -rate // 5:   # we're ahead (silence filled, then sound came): re-sync
                    t0 = time.perf_counter() - delivered / rate
                time.sleep(0.005)
        finally:
            try:
                client.Stop()
            except Exception:
                pass
            ctypes.windll.ole32.CoTaskMemFree(c_void_p(fmt_ptr))

    def _deliver(self, block, frames):
        for i in range(0, frames, 512):   # the analyser works in blocks of about 512
            part = np.ascontiguousarray(block[i:i + 512])
            self.callback(part, len(part), None, None)
