"""Spout sender, written directly against Windows (no Spout package needed).

Spout shares a GPU texture between programs on the same machine: the sender makes a shared DirectX 11 texture,
lists its name in the "SpoutSenderNames" shared memory, and describes it (handle, size, format) in shared memory
named after itself. Receivers (OBS with the Spout2 plugin, Resolume, TouchDesigner, ...) open the texture by its
handle. Our frames are OpenGL, so the texture is also opened in OpenGL through WGL_NV_DX_interop (NVIDIA, AMD and
Intel drivers all have it) and each frame is copied in with a framebuffer blit: no CPU copy at all.
"""
import ctypes
from ctypes import wintypes

from OpenGL import GL

MAX_SENDERS, NAME_LEN = 64, 256          # the sender list Spout 2.007 uses: 64 names of 256 bytes
DXGI_FORMAT_B8G8R8A8_UNORM = 87
FILE_MAP_ALL_ACCESS, PAGE_READWRITE = 0xF001F, 0x04
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileMappingW.restype = wintypes.HANDLE
_k32.CreateFileMappingW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.LPCWSTR]
_k32.OpenFileMappingW.restype = wintypes.HANDLE
_k32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_k32.MapViewOfFile.restype = ctypes.c_void_p
_k32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
_k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
_k32.CreateMutexW.restype = wintypes.HANDLE
_k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.ReleaseMutex.argtypes = [wintypes.HANDLE]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]


class SharedTextureInfo(ctypes.Structure):
    """What a sender publishes about its texture (Spout's own layout, 280 bytes)."""
    _fields_ = [("shareHandle", ctypes.c_uint32), ("width", ctypes.c_uint32), ("height", ctypes.c_uint32),
                ("format", ctypes.c_uint32), ("usage", ctypes.c_uint32), ("description", ctypes.c_wchar * 128),
                ("partnerId", ctypes.c_uint32)]


class _MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD), ("PartitionId", wintypes.WORD),
                ("RegionSize", ctypes.c_size_t), ("State", wintypes.DWORD), ("Protect", wintypes.DWORD),
                ("Type", wintypes.DWORD)]


class SharedMemory:
    """A named shared-memory block with its "<name>_mutex" lock, as Spout makes them."""

    def __init__(self, name, size):
        self.handle = _k32.OpenFileMappingW(FILE_MAP_ALL_ACCESS, False, name) or \
            _k32.CreateFileMappingW(wintypes.HANDLE(-1), None, PAGE_READWRITE, 0, size, name)
        if not self.handle:
            raise OSError(f"couldn't open shared memory '{name}' ({ctypes.get_last_error()})")
        self.ptr = _k32.MapViewOfFile(self.handle, FILE_MAP_ALL_ACCESS, 0, 0, 0)   # the whole block
        mbi = _MBI()
        _k32.VirtualQuery(ctypes.c_void_p(self.ptr), ctypes.byref(mbi), ctypes.sizeof(mbi))
        self.size = min(mbi.RegionSize, max(size, mbi.RegionSize))
        self.mutex = _k32.CreateMutexW(None, False, name + "_mutex")

    def __enter__(self):
        _k32.WaitForSingleObject(self.mutex, 100)
        return self

    def __exit__(self, *exc):
        _k32.ReleaseMutex(self.mutex)

    def read(self, n=None):
        return ctypes.string_at(self.ptr, n or self.size)

    def write(self, data, offset=0):
        ctypes.memmove(self.ptr + offset, data, len(data))

    def close(self):
        _k32.UnmapViewOfFile(ctypes.c_void_p(self.ptr))
        _k32.CloseHandle(self.handle)
        _k32.CloseHandle(self.mutex)


def _names(mem):
    """The sender names listed in a SpoutSenderNames block."""
    raw, out = mem.read(), []
    for i in range(len(raw) // NAME_LEN):
        s = raw[i * NAME_LEN:(i + 1) * NAME_LEN].split(b"\0", 1)[0]
        if not s:
            break
        out.append(s.decode("latin-1"))
    return out


def _write_names(mem, names):
    block = b"".join(n.encode("latin-1")[:NAME_LEN - 1].ljust(NAME_LEN, b"\0") for n in names)
    mem.write(block.ljust(mem.size // NAME_LEN * NAME_LEN, b"\0")[:mem.size])


def senders():
    """Names of the Spout senders running right now (for tests and the UI)."""
    h = _k32.OpenFileMappingW(FILE_MAP_ALL_ACCESS, False, "SpoutSenderNames")
    if not h:
        return []
    _k32.CloseHandle(h)
    mem = SharedMemory("SpoutSenderNames", MAX_SENDERS * NAME_LEN)
    try:
        return _names(mem)
    finally:
        mem.close()


# ---- COM / Direct3D 11 through vtables
def _vcall(obj, index, restype, *args):
    """Call method `index` of COM object `obj` (a pointer), with ctypes-typed args."""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *[type(a) for a in args])(vtbl[index])
    return fn(obj, *args)


class _GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]

    def __init__(self, s):
        p = s.split("-")
        tail = bytes.fromhex(p[3] + p[4])
        super().__init__(int(p[0], 16), int(p[1], 16), int(p[2], 16), (ctypes.c_ubyte * 8)(*tail))


IID_IDXGIResource = _GUID("035f3ab4-482e-4e50-b41f-8a7f8bd8960b")


class _TEX2D_DESC(ctypes.Structure):
    _fields_ = [("Width", ctypes.c_uint), ("Height", ctypes.c_uint), ("MipLevels", ctypes.c_uint),
                ("ArraySize", ctypes.c_uint), ("Format", ctypes.c_uint), ("SampleCount", ctypes.c_uint),
                ("SampleQuality", ctypes.c_uint), ("Usage", ctypes.c_uint), ("BindFlags", ctypes.c_uint),
                ("CPUAccessFlags", ctypes.c_uint), ("MiscFlags", ctypes.c_uint)]


def _release(obj):
    if obj:
        _vcall(obj, 2, ctypes.c_ulong)


class SpoutSender:
    """Publishes our output texture as a Spout sender. Call send() each frame with the GL context current."""

    def __init__(self, name="LumaTRX"):
        self.name, self.size, self.error = name, None, None
        self.device = self.context = self.texture = None
        self.gl_dev = self.gl_obj = None
        self.gl_tex = self.fbo = 0
        self.names_mem = self.info_mem = None
        d3d = ctypes.WinDLL("d3d11")
        dev, ctx, lvl = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_uint()
        hr = d3d.D3D11CreateDevice(None, 1, None, 0x20, None, 0, 7, ctypes.byref(dev), ctypes.byref(lvl),
                                   ctypes.byref(ctx))   # hardware device, BGRA support
        if hr != 0:
            raise OSError(f"Direct3D 11 device failed ({hr & 0xFFFFFFFF:#x})")
        self.device, self.context = dev.value, ctx.value
        gpa = ctypes.WinDLL("opengl32").wglGetProcAddress
        gpa.restype, gpa.argtypes = ctypes.c_void_p, [ctypes.c_char_p]

        def wgl(name, restype, *argtypes):
            addr = gpa(name.encode())
            if not addr:
                raise OSError(f"the graphics driver has no {name} (GL/DirectX sharing)")
            return ctypes.WINFUNCTYPE(restype, *argtypes)(addr)
        H = ctypes.c_void_p
        self.wglDXOpenDeviceNV = wgl("wglDXOpenDeviceNV", H, ctypes.c_void_p)
        self.wglDXCloseDeviceNV = wgl("wglDXCloseDeviceNV", wintypes.BOOL, H)
        self.wglDXRegisterObjectNV = wgl("wglDXRegisterObjectNV", H, H, ctypes.c_void_p, ctypes.c_uint,
                                         ctypes.c_uint, ctypes.c_uint)
        self.wglDXUnregisterObjectNV = wgl("wglDXUnregisterObjectNV", wintypes.BOOL, H, H)
        self.wglDXLockObjectsNV = wgl("wglDXLockObjectsNV", wintypes.BOOL, H, ctypes.c_int, ctypes.POINTER(H))
        self.wglDXUnlockObjectsNV = wgl("wglDXUnlockObjectsNV", wintypes.BOOL, H, ctypes.c_int, ctypes.POINTER(H))
        self.gl_dev = self.wglDXOpenDeviceNV(ctypes.c_void_p(self.device))
        if not self.gl_dev:
            raise OSError("OpenGL couldn't open the Direct3D device")
        self.access_mutex = _k32.CreateMutexW(None, False, name + "_SpoutAccessMutex")

    def _make_texture(self, w, h):
        """A shared DirectX texture of w x h, opened in OpenGL too, and published under our name."""
        self._drop_texture()
        desc = _TEX2D_DESC(w, h, 1, 1, DXGI_FORMAT_B8G8R8A8_UNORM, 1, 0, 0, 0x8 | 0x20, 0, 0x2)
        tex = ctypes.c_void_p()
        hr = _vcall(self.device, 5, ctypes.c_long, ctypes.c_void_p(ctypes.addressof(desc)), ctypes.c_void_p(None),
                    ctypes.c_void_p(ctypes.addressof(tex)))   # ID3D11Device::CreateTexture2D
        if hr != 0:
            raise OSError(f"shared texture failed ({hr & 0xFFFFFFFF:#x})")
        self.texture = tex.value
        res, share = ctypes.c_void_p(), ctypes.c_void_p()
        _vcall(self.texture, 0, ctypes.c_long, ctypes.c_void_p(ctypes.addressof(IID_IDXGIResource)),
               ctypes.c_void_p(ctypes.addressof(res)))   # QueryInterface(IDXGIResource)
        _vcall(res.value, 8, ctypes.c_long, ctypes.c_void_p(ctypes.addressof(share)))   # GetSharedHandle
        _release(res.value)
        self.gl_tex = int(GL.glGenTextures(1))
        self.gl_obj = self.wglDXRegisterObjectNV(self.gl_dev, ctypes.c_void_p(self.texture), self.gl_tex,
                                                 GL.GL_TEXTURE_2D, 2)   # write-discard: we fill it whole
        if not self.gl_obj:
            raise OSError("OpenGL couldn't use the shared texture")
        self.fbo = int(GL.glGenFramebuffers(1))
        h_ = ctypes.c_void_p(self.gl_obj)
        self.wglDXLockObjectsNV(self.gl_dev, 1, ctypes.byref(h_))
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, self.gl_tex, 0)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
        self.wglDXUnlockObjectsNV(self.gl_dev, 1, ctypes.byref(h_))
        # publish: our description, and our name in the list of senders
        info = SharedTextureInfo((share.value or 0) & 0xFFFFFFFF, w, h, DXGI_FORMAT_B8G8R8A8_UNORM, 0,
                                 "LumaTRX Visual FX Engine", 0)
        self.info_mem = SharedMemory(self.name, ctypes.sizeof(SharedTextureInfo))
        with self.info_mem:
            self.info_mem.write(bytes(info))
        self.names_mem = SharedMemory("SpoutSenderNames", MAX_SENDERS * NAME_LEN)
        with self.names_mem:
            names = _names(self.names_mem)
            if self.name not in names:
                _write_names(self.names_mem, names + [self.name])
        active = SharedMemory("ActiveSenderName", NAME_LEN)
        with active:
            if not active.read(1).strip(b"\0"):
                active.write(self.name.encode().ljust(NAME_LEN, b"\0"))
        active.close()
        self.size = (w, h)

    def send(self, read_fbo, w, h):
        """Copy the frame in GL framebuffer `read_fbo` (w x h, top row first) into the shared texture."""
        if self.error:
            return
        try:
            if self.size != (w, h):
                self._make_texture(w, h)
            h_ = ctypes.c_void_p(self.gl_obj)
            _k32.WaitForSingleObject(self.access_mutex, 4)
            if self.wglDXLockObjectsNV(self.gl_dev, 1, ctypes.byref(h_)):
                GL.glBindFramebuffer(GL.GL_READ_FRAMEBUFFER, read_fbo)
                GL.glBindFramebuffer(GL.GL_DRAW_FRAMEBUFFER, self.fbo)
                GL.glBlitFramebuffer(0, 0, w, h, 0, 0, w, h, GL.GL_COLOR_BUFFER_BIT, GL.GL_NEAREST)
                GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
                self.wglDXUnlockObjectsNV(self.gl_dev, 1, ctypes.byref(h_))
            _k32.ReleaseMutex(self.access_mutex)
        except Exception as e:   # keep the show going: Spout just stops, with the reason in the UI
            self.error = str(e)

    def _drop_texture(self):
        if self.names_mem:
            with self.names_mem:
                _write_names(self.names_mem, [n for n in _names(self.names_mem) if n != self.name])
            self.names_mem.close()
            self.names_mem = None
        if self.info_mem:
            self.info_mem.close()
            self.info_mem = None
        if self.gl_obj:
            self.wglDXUnregisterObjectNV(self.gl_dev, ctypes.c_void_p(self.gl_obj))
            self.gl_obj = None
        if self.fbo:
            GL.glDeleteFramebuffers(1, [self.fbo])
            self.fbo = 0
        if self.gl_tex:
            GL.glDeleteTextures(1, [self.gl_tex])
            self.gl_tex = 0
        _release(self.texture)
        self.texture, self.size = None, None

    def close(self):
        """Stop sending: unlist our name and free everything (GL context must be current)."""
        try:
            self._drop_texture()
            if self.gl_dev:
                self.wglDXCloseDeviceNV(self.gl_dev)
                self.gl_dev = None
            _release(self.context)
            _release(self.device)
            self.context = self.device = None
            _k32.CloseHandle(self.access_mutex)
        except Exception:
            pass
