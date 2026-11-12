"""Video inputs. Each source runs a reader thread and keeps only the newest frame (BGR, top row first).

Sources are described by small dicts (saved with the session) and built with open_source():
  {"kind": "test"} | {"kind": "camera", "name"} | {"kind": "video", "path"} | {"kind": "image", "path"}
  | {"kind": "screen", "index"} | {"kind": "window", "title", "exe"}
Any of them can also carry "crop": [x0, y0, x1, y1], the part of the picture to keep (0..1, top-left origin).
"""
import ctypes
import os
import threading
import time
from ctypes import wintypes

import cv2
import numpy as np


def list_cameras():
    """[(name, [(backend, index), ...])] with Media Foundation tried first, DirectShow as fallback.

    Some drivers (DroidCam) crash OpenCV's DirectShow path but work via Media Foundation,
    while some cameras only exist in DirectShow. Indexes differ per backend, so match by name.
    """
    from cv2_enumerate_cameras import enumerate_cameras
    cams = {}
    for api in (cv2.CAP_MSMF, cv2.CAP_DSHOW):
        for c in enumerate_cameras(api):
            # never offer our own output as an input: that's an instant feedback loop
            if c.name != "OBS Virtual Camera":
                cams.setdefault(c.name, []).append((api, c.index))
    return list(cams.items())


class _ThreadedSource:
    def __init__(self):
        self._frame = None
        self._new = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.error = None
        self.fps = 0.0
        self.crop = None   # [x0, y0, x1, y1] (0..1) or None for the whole picture
        self.paused = False   # screens, windows and videos stop grabbing while nothing shows them
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_crop(self, crop):
        self.crop = clean_crop(crop)
        if getattr(self, "_still", None) is not None:   # a still picture only arrives once: send it again
            self._push(self._still)

    def _push(self, frame, cropped=False):
        if self.crop and not cropped:
            frame = crop_frame(frame, self.crop)
        with self._lock:
            self._frame, self._new = frame, True

    def latest(self):
        """Returns a frame only when a new one has arrived since the last call."""
        with self._lock:
            if not self._new:
                return None
            self._new = False
            return self._frame

    def resend(self):
        """Hand out the last frame again on the next latest() (after moving to another slot: a still image or a
        paused video has no new frame to give)."""
        with self._lock:
            self._new = self._frame is not None

    def close(self):
        self._stop.set()
        self._thread.join(timeout=2)


class CameraSource(_ThreadedSource):
    def __init__(self, name, backends, width=1920, height=1080, fps=60):
        self.name, self.backends, self._want = name, backends, (width, height, fps)
        super().__init__()

    def _open(self):
        w, h, fps = self._want
        for api, index in self.backends:
            cap = cv2.VideoCapture(index, api)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
                cap.set(cv2.CAP_PROP_FPS, fps)
                if cap.read()[0]:
                    return cap
            cap.release()
        return None

    def _run(self):
        cap = self._open()
        if cap is None:
            self.error = f"Couldn't open {self.name}. Is its app connected, or is another app using it?"
            return
        n, t0 = 0, time.perf_counter()
        while not self._stop.is_set():
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            self._push(frame)
            n += 1
            if time.perf_counter() - t0 >= 1:
                self.fps, n, t0 = n / (time.perf_counter() - t0), 0, time.perf_counter()
        cap.release()


class ImageSource(_ThreadedSource):
    """A still picture (png, jpg, ...): delivered once."""

    def __init__(self, path):
        self.path = path
        self.name = path.replace("\\", "/").rsplit("/", 1)[-1]
        super().__init__()

    def _run(self):
        frame = cv2.imread(self.path, cv2.IMREAD_COLOR)
        if frame is None:
            self.error = f"Couldn't open {self.name}"
            return
        self._still = frame
        self._push(frame)


def list_screens():
    """[(index, label)] for each monitor."""
    try:
        import mss
        with mss.MSS() as s:
            return [(i, f"Screen {i}  ({m['width']}x{m['height']})") for i, m in enumerate(s.monitors[1:], 1)]
    except Exception:
        return []


class ScreenSource(_ThreadedSource):
    """Live capture of a whole monitor (games, browsers, other apps' visuals)."""

    def __init__(self, index, max_width=2560, fps=30):   # up to 1440p goes up whole: the GPU scales it for free
        self.index, self.max_width, self.target_fps = index, max_width, fps
        self.name = f"Screen {index}"
        super().__init__()

    def _run(self):
        try:
            grabber = ScreenGrabber(self.target_fps)
            mon = grabber.monitors[self.index]
        except Exception as e:
            self.error = f"Screen capture failed: {e}"
            return
        period, n, t0 = 1 / self.target_fps, 0, time.perf_counter()
        while not self._stop.is_set():
            if self.paused:
                self.fps = 0.0
                grabber.idle()
                time.sleep(0.1)
                continue
            start = time.perf_counter()
            region = crop_region(mon, self.crop)   # grab only the part that's kept
            self._push(shrink(grabber.grab(region), self.max_width), cropped=True)
            n += 1
            if time.perf_counter() - t0 >= 1:
                self.fps, n, t0 = n / (time.perf_counter() - t0), 0, time.perf_counter()
            self._due = max(getattr(self, "_due", 0.0) + period, time.perf_counter())   # a steady beat, not "period after this one"
            time.sleep(max(0.0, self._due - time.perf_counter()))
        grabber.close()


class _Desktop:
    """One DXGI desktop duplication per monitor (the way OBS's Display Capture works: the GPU hands over each new
    frame, 60 fps and more for very little processor time). Windows allows one per monitor per program, so every
    screen and window source on that monitor shares it; it stops once nothing uses it."""
    _all, _lock = {}, threading.Lock()

    @classmethod
    def get(cls, index, user, fps):
        with cls._lock:
            d = cls._all.get(index)
            if d is None:
                d = cls._all[index] = cls(index)   # raises if this monitor can't be duplicated
            d.users[user] = fps
            return d

    def __init__(self, index):
        self.index, self.users, self.frame, self._error = index, {}, None, None   # users: {grabber: its fps}
        started = threading.Event()
        threading.Thread(target=self._run, args=(started,), daemon=True).start()
        started.wait(5)
        if self._error or not started.is_set():
            raise RuntimeError(self._error or "desktop duplication didn't start")

    def release(self, user):
        with _Desktop._lock:
            self.users.pop(user, None)

    def _run(self, started):
        try:   # the session only works on the thread that made it
            from windows_capture import DxgiDuplicationSession
            self._session = DxgiDuplicationSession(self.index)
        except Exception as e:
            self._error = str(e) or type(e).__name__
            started.set()
            return
        started.set()
        last = 0.0
        while True:
            with _Desktop._lock:
                if not self.users:
                    del _Desktop._all[self.index]
                    break
            rate = max(self.users.values(), default=30) + 1   # only as fast as the fastest source on it needs
            wait = last + 1 / rate - time.perf_counter()
            if wait > 0:   # not due yet: don't even fetch (fetching copies the whole screen off the GPU)
                time.sleep(min(wait, 0.05))
                continue
            try:
                # never wait inside it: the library holds Python's lock while waiting, stalling every other thread
                fr = self._session.acquire_frame(0)   # None: nothing changed on screen
            except Exception:   # resolution change, a fullscreen game taking over, the secure desktop...
                fr = None
                time.sleep(0.5)
                try:
                    self._session.recreate()
                except Exception:
                    pass
            if fr is not None:
                last = time.perf_counter()
                # BGR, our own copy (the system reuses its memory): converting the colours is the copy
                self.frame = cv2.cvtColor(fr.to_numpy(), cv2.COLOR_BGRA2BGR)
            else:
                time.sleep(0.004)
            del fr
        self._session = None


def fast_capture_ok():
    """Whether the fast desktop capture (DXGI duplication) works on this PC, for the self-test."""
    try:
        _Desktop.get(1, "check", 30).release("check")
        return True
    except Exception:
        return False


class ScreenGrabber:
    """grab(region) -> BGR for an area of the desktop (mss-style {"left", "top", "width", "height"}). Cuts it from
    the monitor's shared desktop duplication; falls back to mss (slower: about 30 fps for a 1440p screen) when that
    isn't available or the area spans two monitors."""

    def __init__(self, fps=30):
        import mss
        self.fps = fps
        self.mss = mss.MSS()
        self.monitors = self.mss.monitors   # [all, 1, 2, ...]
        self.desktops, self.dxgi = {}, True

    def grab(self, region):
        frame = self._dxgi(region) if self.dxgi else None
        if frame is None:
            frame = np.asarray(self.mss.grab(region))[:, :, :3]
        return np.ascontiguousarray(frame)

    def _dxgi(self, region):
        x, y, w, h = region["left"], region["top"], region["width"], region["height"]
        for i, m in enumerate(self.monitors[1:], 1):
            if m["left"] <= x and m["top"] <= y and x + w <= m["left"] + m["width"] and y + h <= m["top"] + m["height"]:
                break
        else:
            return None
        if i not in self.desktops:
            try:
                self.desktops[i] = _Desktop.get(i, self, self.fps)
            except Exception:
                self.dxgi = False   # not on this PC (remote desktop, very old drivers): mss from now on
                return None
        full = self.desktops[i].frame
        if full is None:
            return None
        x, y = x - m["left"], y - m["top"]
        return full[y:y + h, x:x + w]   # grab() copies it only if it's a part (the whole screen is shared as is)

    def idle(self):
        """Let go of the desktop captures while paused (they stop when nobody uses them)."""
        for d in self.desktops.values():
            d.release(self)
        self.desktops = {}

    def close(self):
        self.idle()
        self.mss.close()


def clean_crop(crop):
    """A crop as [x0, y0, x1, y1] inside 0..1 with x0 < x1 and y0 < y1 (at least 1% each way), or None for the
    whole picture when it's missing or unusable (a saved setup from elsewhere, a slip of the crop tool)."""
    try:
        x0, y0, x1, y1 = (float(v) for v in crop)
    except (TypeError, ValueError):
        return None
    if not all(v == v and abs(v) != float("inf") for v in (x0, y0, x1, y1)):
        return None
    x0, x1 = sorted((min(1.0, max(0.0, x0)), min(1.0, max(0.0, x1))))
    y0, y1 = sorted((min(1.0, max(0.0, y0)), min(1.0, max(0.0, y1))))
    if x1 - x0 < 0.01 or y1 - y0 < 0.01:
        return None
    if x0 <= 0.0 and y0 <= 0.0 and x1 >= 1.0 and y1 >= 1.0:
        return None   # the whole picture: no crop at all
    return [x0, y0, x1, y1]


def crop_frame(frame, crop):
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = crop
    a, b = int(x0 * w), int(y0 * h)
    return frame[b:max(b + 2, int(y1 * h)), a:max(a + 2, int(x1 * w))]


def crop_region(mon, crop):
    """An mss region (left, top, width, height) for the cropped part of a screen area."""
    if not crop:
        return mon
    x0, y0, x1, y1 = crop
    w, h = mon["width"], mon["height"]
    left, top = mon["left"] + int(x0 * w), mon["top"] + int(y0 * h)
    return {"left": left, "top": top, "width": max(2, int((x1 - x0) * w)), "height": max(2, int((y1 - y0) * h))}


def shrink(frame, max_width):
    """Keep uploads light: scale anything wider than max_width down."""
    if frame.shape[1] <= max_width:
        return frame
    k = max_width / frame.shape[1]
    return cv2.resize(frame, (max_width, round(frame.shape[0] * k)), interpolation=cv2.INTER_AREA)


# ---- single windows (Windows only). PrintWindow asks the window to draw itself into our bitmap, so it keeps
# working while the window is covered by others. Some GPU-drawn windows come back black that way; then we
# fall back to grabbing that spot of the screen (which needs the window to be visible).
if os.name == "nt":   # Windows sleeps in 15.6 ms steps by default, capping capture loops near 30 fps; ask for 1 ms
    ctypes.WinDLL("winmm").timeBeginPeriod(1)
_user32 = ctypes.WinDLL("user32", use_last_error=True) if os.name == "nt" else None
_gdi32 = ctypes.WinDLL("gdi32") if os.name == "nt" else None
_kernel32 = ctypes.WinDLL("kernel32") if os.name == "nt" else None
_ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GWL_EXSTYLE, WS_EX_TOOLWINDOW, PW_CLIENTONLY, PW_RENDERFULLCONTENT = -20, 0x80, 1, 2
if _user32:
    _user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetDC.restype = wintypes.HDC
    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    _gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ
    _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]
    _gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                 ctypes.c_void_p, wintypes.UINT]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                     ctypes.POINTER(wintypes.DWORD)]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _exe_of(hwnd):
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = _kernel32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return "", pid.value
    buf, n = ctypes.create_unicode_buffer(512), wintypes.DWORD(512)
    ok = _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
    _kernel32.CloseHandle(h)
    return (os.path.basename(buf.value) if ok else ""), pid.value


def _cloaked(hwnd):
    """Hidden-but-'visible' windows (suspended Store apps, other virtual desktops)."""
    v = ctypes.c_int(0)
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 14, ctypes.byref(v), ctypes.sizeof(v))
    except OSError:
        return False
    return v.value != 0


def list_windows():
    """[(hwnd, title, exe)] for open app windows, ours left out (capturing Lumoria into itself loops)."""
    if not _user32:
        return []
    out, me = [], os.getpid()

    def visit(hwnd, _):
        if not _user32.IsWindowVisible(hwnd) or _cloaked(hwnd):
            return True
        if _user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        n = _user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        exe, pid = _exe_of(hwnd)
        if pid != me and buf.value != "Program Manager":
            out.append((hwnd, buf.value, exe))
        return True
    _user32.EnumWindows(_ENUM_PROC(visit), 0)
    return out


def find_window(title, exe, hwnd=None):
    """The window a saved description means: the same window if it's still open, else the same title,
    else the first window of the same program (a browser's title changes with the tab)."""
    wins = list_windows()
    for h, t, e in wins:
        if h == hwnd and e == exe:
            return h
    for h, t, e in wins:
        if t == title and e == exe:
            return h
    for h, t, e in wins:
        if e == exe and exe:
            return h
    return None


def window_label(title, exe):
    app = exe.rsplit(".", 1)[0] if exe else ""
    title = title if len(title) <= 42 else title[:40] + "..."
    return f"{title}  ({app})" if app and app.lower() not in title.lower() else title


class WindowSource(_ThreadedSource):
    """Live capture of one window's inside (no title bar). Fast grabs it from the screen (the window must be visible);
    otherwise PrintWindow asks the window to draw itself, which works while covered but is slow for big windows."""

    def __init__(self, hwnd, title, max_width=2560, fps=30, fast=False):
        self.hwnd, self.title, self.max_width, self.target_fps = hwnd, title, max_width, fps
        self.name = title
        self.black_frames, self.fallback = 0, fast   # fast: grab it from the screen (it must be visible)
        super().__init__()

    def _client_rect(self):
        r = wintypes.RECT()
        _user32.GetClientRect(self.hwnd, ctypes.byref(r))
        pt = wintypes.POINT(0, 0)
        _user32.ClientToScreen(self.hwnd, ctypes.byref(pt))
        return pt.x, pt.y, r.right - r.left, r.bottom - r.top

    def _print(self, w, h):
        """The window's own drawing of itself, as BGR."""
        wdc = _user32.GetDC(self.hwnd)
        mdc = _gdi32.CreateCompatibleDC(wdc)
        bmp = _gdi32.CreateCompatibleBitmap(wdc, w, h)
        old = _gdi32.SelectObject(mdc, bmp)
        _user32.PrintWindow(self.hwnd, mdc, PW_CLIENTONLY | PW_RENDERFULLCONTENT)
        # BITMAPINFOHEADER: 32-bit, negative height = top row first
        bmi = (ctypes.c_int32 * 10)(40, w, -h, 1 | (32 << 16), 0, 0, 0, 0, 0, 0)
        buf = np.empty((h, w, 4), np.uint8)
        _gdi32.GetDIBits(mdc, bmp, 0, h, buf.ctypes.data, ctypes.byref(bmi), 0)
        _gdi32.SelectObject(mdc, old)
        _gdi32.DeleteObject(bmp)
        _gdi32.DeleteDC(mdc)
        _user32.ReleaseDC(self.hwnd, wdc)
        return buf[:, :, :3]

    def _run(self):
        grabber = ScreenGrabber(self.target_fps)
        period, n, t0 = 1 / self.target_fps, 0, time.perf_counter()
        while not self._stop.is_set():
            start = time.perf_counter()
            if self.paused:
                self.fps = 0.0
                grabber.idle()
                time.sleep(0.1)
                continue
            if not _user32.IsWindow(self.hwnd):
                self.error = f'The window "{self.title}" was closed'
                break
            x, y, w, h = self._client_rect()
            if _user32.IsIconic(self.hwnd) or w < 2 or h < 2:   # minimised: keep the last picture
                time.sleep(0.1)
                continue
            if not self.fallback:
                frame = self._print(w, h)
                if self.crop:
                    frame = crop_frame(frame, self.crop)
                # all black for a while: this window doesn't draw for PrintWindow; grab the screen instead
                self.black_frames = self.black_frames + 1 if frame.max() < 8 else 0
                self.fallback = self.black_frames > 15
            else:
                frame = grabber.grab(crop_region({"left": x, "top": y, "width": w, "height": h}, self.crop))
            self._push(np.ascontiguousarray(shrink(frame, self.max_width)), cropped=True)
            n += 1
            if time.perf_counter() - t0 >= 1:
                self.fps, n, t0 = n / (time.perf_counter() - t0), 0, time.perf_counter()
            self._due = max(getattr(self, "_due", 0.0) + period, time.perf_counter())   # a steady beat, not "period after this one"
            time.sleep(max(0.0, self._due - time.perf_counter()))
        grabber.close()


class _Missing:
    """Stands in for a source that couldn't be found; only carries the error."""

    def __init__(self, error):
        self.error, self.crop, self.fps = error, None, 0.0

    def latest(self):
        return None

    def set_crop(self, crop):
        pass

    def close(self):
        pass


class VideoFileSource(_ThreadedSource):
    def __init__(self, path):
        self.path = path
        self.name = path.replace("\\", "/").rsplit("/", 1)[-1]
        super().__init__()

    def _run(self):
        cap = cv2.VideoCapture(self.path)
        if not cap.isOpened():
            self.error = f"Couldn't open {self.name}"
            return
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30
        period = 1 / self.fps
        next_t = time.perf_counter()
        while not self._stop.is_set():
            if self.paused:
                time.sleep(0.1)
                next_t = time.perf_counter()
                continue
            ok, frame = cap.read()
            if not ok:  # loop
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            self._push(frame)
            next_t += period
            delay = next_t - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                next_t = time.perf_counter()
        cap.release()


def describe(desc):
    """A short label for a source description."""
    kind = desc.get("kind", "none")
    if kind == "camera":
        return desc["name"]
    if kind in ("video", "image"):
        return desc["path"].replace("\\", "/").rsplit("/", 1)[-1]
    if kind == "screen":
        return f"Screen {desc['index']}" + ("  (cropped)" if desc.get("crop") else "")
    if kind == "window":
        return window_label(desc["title"], desc.get("exe", "")) + ("  (cropped)" if desc.get("crop") else "")
    return {"test": "Test pattern"}.get(kind, "None")


def open_source(desc, cameras=None):
    """Build a running source from its description; None for the test pattern / nothing."""
    src = _open_source(desc, cameras)
    if src is not None and desc.get("crop"):
        src.set_crop(desc["crop"])
    return src


def _open_source(desc, cameras):
    kind = desc.get("kind")
    if kind == "camera":
        backends = dict(cameras if cameras is not None else list_cameras()).get(desc["name"])
        if backends is None:
            src = CameraSource(desc["name"], [])
            src.error = f"{desc['name']} isn't connected"
            return src
        return CameraSource(desc["name"], backends)
    if kind == "video":
        return VideoFileSource(desc["path"])
    if kind == "image":
        return ImageSource(desc["path"])
    if kind == "screen":
        return ScreenSource(desc["index"], fps=desc.get("fps", 30))
    if kind == "window":
        hwnd = find_window(desc["title"], desc.get("exe", ""), desc.get("hwnd"))
        if hwnd is None:
            return _Missing(f'The window "{desc["title"]}" isn\'t open')
        desc["hwnd"] = hwnd
        return WindowSource(hwnd, desc["title"], fps=desc.get("fps", 30), fast=desc.get("method") != "compatible")
    return None
