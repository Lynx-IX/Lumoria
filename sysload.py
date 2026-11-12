"""CPU and GPU load for the top bar's readout, read from Windows' performance counters (the same numbers Task Manager
shows) once a second on a background thread, so it never costs a frame. Elsewhere, or if the counters can't be read,
the values stay None and the readout leaves them out."""
import ctypes
import os
import threading
import time
from ctypes import wintypes

PDH_FMT_DOUBLE = 0x00000200
PDH_MORE_DATA = 0x800007D2 - (1 << 32)   # as a signed LONG
CPU_PATH = r"\Processor Information(_Total)\% Processor Utility"
GPU_PATH = r"\GPU Engine(*engtype_3D)\Utilization Percentage"


class _Value(ctypes.Structure):
    _fields_ = [("status", wintypes.DWORD), ("value", ctypes.c_double)]   # PDH_FMT_COUNTERVALUE (double)


class _Item(ctypes.Structure):
    _fields_ = [("name", ctypes.c_wchar_p), ("value", _Value)]            # PDH_FMT_COUNTERVALUE_ITEM_W


def gpu_by_engine(items, pid=None):
    """items: (instance name, % busy) for each process on each 3D engine. Task Manager's GPU figure: add up the
    processes on each engine and take the busiest engine (capped at 100). pid: just that process's share."""
    engines = {}
    for name, value in items:
        if pid is not None and not name.startswith(f"pid_{pid}_"):
            continue
        key = name[name.find("_luid_"):] if "_luid_" in name else name
        engines[key] = engines.get(key, 0.0) + value
    return min(100.0, max(engines.values(), default=0.0))


class SysLoad:
    def __init__(self, every=1.0):
        self.cpu = self.gpu = None         # whole machine, percent
        self.own_cpu = self.own_gpu = None   # Lumoria's own share
        self.every = every
        self._stop = threading.Event()
        if os.name == "nt":
            threading.Thread(target=self._run, name="sysload", daemon=True).start()

    def stop(self):
        self._stop.set()

    def _run(self):
        try:
            pdh = ctypes.windll.pdh
        except (AttributeError, OSError):
            return
        query = wintypes.HANDLE()
        if pdh.PdhOpenQueryW(None, None, ctypes.byref(query)):
            return
        cpu_c, gpu_c = wintypes.HANDLE(), wintypes.HANDLE()
        has_cpu = not pdh.PdhAddEnglishCounterW(query, CPU_PATH, None, ctypes.byref(cpu_c))
        has_gpu = not pdh.PdhAddEnglishCounterW(query, GPU_PATH, None, ctypes.byref(gpu_c))
        pid, ncpu = os.getpid(), os.cpu_count() or 1
        last = None
        try:
            pdh.PdhCollectQueryData(query)   # rates need two samples
            while not self._stop.wait(self.every):
                if pdh.PdhCollectQueryData(query):
                    continue
                if has_cpu:
                    v = _Value()
                    if not pdh.PdhGetFormattedCounterValue(cpu_c, PDH_FMT_DOUBLE, None, ctypes.byref(v)) \
                            and v.status in (0, 1):
                        self.cpu = min(100.0, max(0.0, v.value))
                if has_gpu:
                    items = self._array(pdh, gpu_c)
                    if items is not None:
                        self.gpu, self.own_gpu = gpu_by_engine(items), gpu_by_engine(items, pid)
                t = os.times()   # this process's CPU time, spread over every core
                now = (time.perf_counter(), t.user + t.system)
                if last:
                    self.own_cpu = min(100.0, max(0.0, (now[1] - last[1]) / max(now[0] - last[0], 1e-6) / ncpu * 100))
                last = now
        except Exception:   # the readout is a nicety: never let it take anything down
            pass
        finally:
            pdh.PdhCloseQuery(query)

    @staticmethod
    def _array(pdh, counter):
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        status = pdh.PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), None)
        if status != PDH_MORE_DATA or not size.value:
            return [] if status == 0 else None
        buf = (ctypes.c_byte * size.value)()
        if pdh.PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), buf):
            return None
        items = ctypes.cast(buf, ctypes.POINTER(_Item))
        return [(items[i].name or "", items[i].value.value) for i in range(count.value)
                if items[i].value.status in (0, 1)]
