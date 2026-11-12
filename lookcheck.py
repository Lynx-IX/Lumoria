"""Checking look files before LumaTRX uses them.

A look (one of your own, one imported from a .lumatrx-look / .lumatrx-playlist file, or a look pack) is JSON. This
keeps only the fields LumaTRX understands, each with the right type and a sensible range, and drops anything
unknown or broken, so a damaged or hand-edited file can't crash LumaTRX when it's loaded. clean_look raises
ValueError only when nothing usable is left.
"""
import base64
import math

from timeline import clean_timeline

MAX_ITEMS = 200        # effects and groups in one look, all together
MAX_DEPTH = 4          # groups inside groups
MAX_LIST = 64          # options / sliders per effect
MAX_TEXT = 200         # any name or id
MAX_THUMB = 4_000_000  # bytes of a thumbnail picture
MAX_THUMB_SIDE = 2048  # pixels


def _num(v, default, lo=-1e6, hi=1e6):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(x):
        return default
    return min(hi, max(lo, x))


def _int(v, default, lo=-1_000_000, hi=1_000_000):
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, float) and math.isfinite(v):
        v = int(v)
    return min(hi, max(lo, v)) if isinstance(v, int) else default


def _bool(v, default):
    return v if isinstance(v, bool) else bool(v) if isinstance(v, (int, float)) else default


def _text(v, default=None):
    return v[:MAX_TEXT] if isinstance(v, str) else default


def _pair(v, default, lo=-1e6, hi=1e6):
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return [_num(v[0], default[0], lo, hi), _num(v[1], default[1], lo, hi)]
    return list(default)


# automation fields: name -> (kind, default)
_AUTO_FIELDS = dict(shape=("int", 0), rate=("num", 1.0), unit=("int", 2), lo=("num", 0.0), hi=("num", 1.0),
                    phase=("num", 0.0), band=("int", 0), dir=("int", 0), ease=("int", 0), then=("int", 0),
                    then_to=("num", 1.0), then_rate=("num", 1.0), then_unit=("int", 1), gain=("num", 1.0),
                    gate=("num", 0.0), curve=("num", 0.0), path=("int", 0), size=("num", 0.2),
                    paused=("int", 0))


def _auto(a):
    if not isinstance(a, dict):
        return None
    out = {}
    for k, (kind, d) in _AUTO_FIELDS.items():
        if k in a:
            out[k] = _int(a[k], d, 0, 1000) if kind == "int" else _num(a[k], d)
    for k in ("rate", "then_rate"):
        if k in out:
            out[k] = max(out[k], 0.01)
    if "base" in a:
        out["base"] = _pair(a["base"], [0.5, 0.5], 0.0, 1.0)
    if "rng" in a:
        out["rng"] = _pair(a["rng"], [80.0, 250.0], 1.0, 30000.0)
    if a.get("resp") is not None:
        out["resp"] = _pair(a["resp"], [0.03, 0.14], 0.0, 30.0)
    out.setdefault("shape", 0)
    out.setdefault("rate", 1.0)
    out.setdefault("unit", 2)
    out.setdefault("lo", 0.0)
    out.setdefault("hi", 1.0)
    out.setdefault("phase", 0.0)
    return out


def _effect(e):
    eid = _text(e.get("id"))
    if not eid:
        return None
    out = dict(id=eid, on=_bool(e.get("on"), True), amt=_num(e.get("amt"), 0.5, 0.0, 2.0),
               mod=_int(e.get("mod"), 0, 0, 2), opacity=_num(e.get("opacity"), 1.0, 0.0, 1.0),
               blend=_int(e.get("blend"), 0, 0, 100), centre=_pair(e.get("centre"), [0.5, 0.5], -2.0, 3.0),
               speed=_num(e.get("speed"), 1.0, -3.0, 3.0), target=_int(e.get("target"), 0, 0, 2),
               expanded=_bool(e.get("expanded"), False), keep_out=_bool(e.get("keep_out"), False),
               char=_int(e.get("char"), 0, 0, 3), mresp=_num(e.get("mresp"), 0.5, 0.0, 1.0),
               xs=_num(e.get("xs"), 1.0, 0.1, 8.0), xr=_num(e.get("xr"), 0.0, -360.0, 360.0),
               pick=_bool(e.get("pick"), False))
    if isinstance(e.get("opts"), list):
        out["opts"] = [_int(v, 0, 0, 10_000) for v in e["opts"][:MAX_LIST]]
    if isinstance(e.get("params"), list):
        out["params"] = [_num(v, 0.0) for v in e["params"][:MAX_LIST]]
    if isinstance(e.get("colours"), list):
        cols = [[_num(c[i], 1.0, 0.0, 1.0) for i in range(3)] for c in e["colours"][:8]
                if isinstance(c, (list, tuple)) and len(c) >= 3]
        if len(cols) >= 2:
            out["colours"] = cols
    if isinstance(e.get("autos"), dict):
        autos = {}
        for k, a in list(e["autos"].items())[:MAX_LIST]:
            k, a = _text(k), _auto(a)
            if k and a:
                autos[k] = a
        out["autos"] = autos
    if e.get("react"):
        out["react"] = True
    if "listen" in e:
        out["listen"] = _text(e.get("listen")) or None
    out["rng"] = _pair(e.get("rng"), [80.0, 250.0], 1.0, 30000.0)
    out["resp"] = _pair(e["resp"], [0.03, 0.14], 0.0, 30.0) if e.get("resp") is not None else None
    if isinstance(e.get("chosen"), list):
        out["chosen"] = [s for s in (_text(k) for k in e["chosen"][:MAX_LIST]) if s]
    return out


def _item(e, depth, budget):
    if not isinstance(e, dict) or budget[0] <= 0:
        return None
    budget[0] -= 1
    if not e.get("group"):
        return _effect(e)
    if depth >= MAX_DEPTH:
        return None
    g = dict(group=True, name=_text(e.get("name"), "Group"), on=_bool(e.get("on"), True),
             opacity=_num(e.get("opacity"), 1.0, 0.0, 1.0), blend=_int(e.get("blend"), 0, 0, 100),
             target=_int(e.get("target"), 0, 0, 2), expanded=_bool(e.get("expanded"), True),
             source=_int(e.get("source"), -1, -1, 16), size=_num(e.get("size"), 0.6, 0.01, 4.0),
             centre=_pair(e.get("centre"), [0.5, 0.5], -2.0, 3.0), fit=_int(e.get("fit"), 1, 0, 4),
             rotate=_num(e.get("rotate"), 0.0, -360.0, 360.0), rounded=_num(e.get("rounded"), 0.0, 0.0, 1.0),
             border=_num(e.get("border"), 0.0, 0.0, 1.0), cutout=_bool(e.get("cutout"), False))
    kids = e.get("children") if isinstance(e.get("children"), list) else []
    g["children"] = [c for c in (_item(k, depth + 1, budget) for k in kids) if c]
    return g


def clean_look(look):
    """A safe copy of a look: only known fields, right types, sensible ranges. ValueError if it isn't a look."""
    if not isinstance(look, dict) or not isinstance(look.get("effects"), list):
        raise ValueError("not a LumaTRX look")
    budget = [MAX_ITEMS]
    items = [c for c in (_item(e, 0, budget) for e in look["effects"]) if c]
    out = dict(version=_int(look.get("version"), 1, 0, 1000), effects=items)   # no version: the oldest format
    if "band" in look:
        out["band"] = look["band"] if isinstance(look["band"], (int, str)) and not isinstance(look["band"], bool) else 0
    if "gain" in look:
        out["gain"] = _num(look["gain"], 1.0, 0.0, 10.0)
    if "timeline" in look:   # lanes that move its sliders over time, in intro / loop / outro (timeline.py)
        tl = clean_timeline(look["timeline"], _num, _text)
        if tl:
            out["timeline"] = tl
    return out


def clean_meta(meta):
    """A look's own transition and timing, as stored with the playlist."""
    if not isinstance(meta, dict):
        return {}
    out = {}
    for k, (lo, hi) in dict(transition=(-1, 100), fade_unit=(0, 2), unit=(0, 2)).items():
        if k in meta:
            out[k] = _int(meta[k], 0, lo, hi)
    for k, (lo, hi) in dict(fade=(0.0, 600.0), hold=(0.0, 10_000.0)).items():
        if k in meta:
            out[k] = _num(meta[k], 0.0, lo, hi)
    return out


def _image_size(data):
    """(width, height) from a PNG or JPEG header, read before decoding (a tiny file can claim a huge picture)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    i = 2
    while i + 9 < len(data):   # JPEG: walk the markers to the frame header (SOF)
        if data[i] != 0xFF:
            return None
        marker, length = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + length
    return None


def clean_thumb(b64):
    """Thumbnail bytes from a look file if they really are a modest PNG or JPEG picture, else None."""
    if not isinstance(b64, str) or len(b64) > MAX_THUMB * 4 // 3 + 4:
        return None
    try:
        data = base64.b64decode(b64, validate=True)
    except ValueError:
        return None
    if len(data) > MAX_THUMB or not (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")):
        return None
    size = _image_size(data)
    if not size or not (0 < size[0] <= MAX_THUMB_SIDE and 0 < size[1] <= MAX_THUMB_SIDE):
        return None
    try:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    except Exception:
        return None
    if img is None or img.shape[0] > MAX_THUMB_SIDE or img.shape[1] > MAX_THUMB_SIDE:
        return None
    return data
