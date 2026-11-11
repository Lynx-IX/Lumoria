"""MIDI through Windows' own MIDI system (winmm), so no extra package is needed.

Every input port is opened; incoming messages are queued from Windows' callback thread and read once per frame
with MidiIn.poll() as (kind, channel, number, value): kind "cc" (value 0-127) or "note" (velocity, 0 = released),
or the MIDI clock ("clock" with value = Windows' timestamp in ms, "start", "stop").
MidiOut sends back to the output ports the user picked (button lights on a controller, see App.midi_feedback).
"""
import collections
import ctypes
import os
from ctypes import wintypes

_winmm = ctypes.WinDLL("winmm") if os.name == "nt" else None
CALLBACK_FUNCTION, MIM_DATA = 0x30000, 0x3C3
_MidiInProc = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.UINT, ctypes.c_size_t, ctypes.c_size_t,
                                 ctypes.c_size_t)


class _MIDIINCAPSW(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("vDriverVersion", wintypes.UINT),
                ("szPname", wintypes.WCHAR * 32), ("dwSupport", wintypes.DWORD)]


def list_ports():
    """Names of the MIDI input ports, in Windows' order."""
    if not _winmm:
        return []
    names = []
    for i in range(_winmm.midiInGetNumDevs()):
        caps = _MIDIINCAPSW()
        ok = _winmm.midiInGetDevCapsW(ctypes.c_size_t(i), ctypes.byref(caps), ctypes.sizeof(caps)) == 0
        names.append(caps.szPname if ok else f"MIDI input {i + 1}")
    return names


class MidiIn:
    def __init__(self):
        self.queue = collections.deque(maxlen=512)
        self.ports = []          # (name, handle or None, error)
        self.last_seen = 0.0     # when the last message arrived (for the activity light), set by poll's caller
        self._cb = _MidiInProc(self._callback)   # kept alive for as long as the ports are open

    def _callback(self, handle, msg, instance, p1, p2):
        if msg == MIM_DATA:
            self.queue.append((p1, p2))   # p2: when it arrived (ms since the port opened)

    def open_all(self):
        """(Re)open every input port. A port another program has open exclusively shows as busy."""
        self.close()
        for i, name in enumerate(list_ports()):
            h = wintypes.HANDLE()
            err = _winmm.midiInOpen(ctypes.byref(h), wintypes.UINT(i), ctypes.cast(self._cb, ctypes.c_void_p),
                                    ctypes.c_size_t(i), CALLBACK_FUNCTION)
            if err == 0:
                _winmm.midiInStart(h)
                self.ports.append((name, h, None))
            else:
                self.ports.append((name, None, "busy (in use by another program?)" if err == 4 else f"error {err}"))

    def close(self):
        for _name, h, _err in self.ports:
            if h:
                _winmm.midiInStop(h)
                _winmm.midiInReset(h)
                _winmm.midiInClose(h)
        self.ports = []

    def poll(self):
        """Messages received since the last call: [(kind, channel 1-16, number, value)]."""
        out = []
        while self.queue:
            p, ms = self.queue.popleft()
            status, d1, d2 = p & 0xFF, (p >> 8) & 0x7F, (p >> 16) & 0x7F
            if status == 0xF8:
                out.append(("clock", 0, 0, ms))
                continue
            if status in (0xFA, 0xFB):   # start, continue
                out.append(("start" if status == 0xFA else "continue", 0, 0, ms))
                continue
            if status == 0xFC:
                out.append(("stop", 0, 0, ms))
                continue
            kind, ch = status & 0xF0, (status & 0x0F) + 1
            if kind == 0xB0:
                out.append(("cc", ch, d1, d2))
            elif kind == 0x90:
                out.append(("note", ch, d1, d2))
            elif kind == 0x80:
                out.append(("note", ch, d1, 0))
        return out


class _MIDIOUTCAPSW(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("vDriverVersion", wintypes.UINT),
                ("szPname", wintypes.WCHAR * 32), ("wTechnology", wintypes.WORD), ("wVoices", wintypes.WORD),
                ("wNotes", wintypes.WORD), ("wChannelMask", wintypes.WORD), ("dwSupport", wintypes.DWORD)]


def list_out_ports():
    """Names of the MIDI output ports, in Windows' order."""
    if not _winmm:
        return []
    names = []
    for i in range(_winmm.midiOutGetNumDevs()):
        caps = _MIDIOUTCAPSW()
        ok = _winmm.midiOutGetDevCapsW(ctypes.c_size_t(i), ctypes.byref(caps), ctypes.sizeof(caps)) == 0
        names.append(caps.szPname if ok else f"MIDI output {i + 1}")
    return names


def short_msg(kind, ch, num, val):
    """A note-on or CC as one packed message (a note with value 0 is its light off)."""
    return (0x90 if kind == "note" else 0xB0) | ((ch - 1) & 0x0F) | ((num & 0x7F) << 8) | ((val & 0x7F) << 16)


class MidiOut:
    """The output ports the user picked, opened by name (only those: a synth on another port never hears us)."""
    def __init__(self):
        self.ports = []   # (name, handle or None, error)

    def open(self, names):
        self.close()
        if not _winmm:
            return
        for i, name in enumerate(list_out_ports()):
            if name not in names:
                continue
            h = wintypes.HANDLE()
            err = _winmm.midiOutOpen(ctypes.byref(h), wintypes.UINT(i), ctypes.c_size_t(0), ctypes.c_size_t(0), 0)
            if err == 0:
                self.ports.append((name, h, None))
            else:
                self.ports.append((name, None, "busy (in use by another program?)" if err == 4 else f"error {err}"))

    @property
    def active(self):
        return any(h for _n, h, _e in self.ports)

    def send(self, kind, ch, num, val):
        msg = short_msg(kind, ch, num, val)
        for _name, h, _err in self.ports:
            if h:
                _winmm.midiOutShortMsg(h, wintypes.DWORD(msg))

    def close(self):
        for _name, h, _err in self.ports:
            if h:
                _winmm.midiOutReset(h)
                _winmm.midiOutClose(h)
        self.ports = []
