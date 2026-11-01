"""Draws the Lumoria logo set as SVG (assets/svg/) and renders the Neon logo style's PNGs and .ico
(*_neon.*; the original artwork keeps the plain names and stays the default).

    python assets/make_logo.py

The symbol is three light trails forming an L: each stroke tapers from a sharp tip at the top, down to a rounded
corner, and out along a tail to the right. One left-to-right gradient (cyan -> violet -> magenta -> orange) runs
across all three. Variants: glow (large uses), flat (small sizes, docs), mono (one colour), the app icon tile,
a bolder small icon for 16-32 px, and the wordmark. PNGs are rendered with Edge in headless mode.
"""
import math
import os
import subprocess
import tempfile

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SVG = os.path.join(HERE, "svg")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

# (tip, corner, tail end, width at the corner) on a 512 canvas, outer stroke first
STROKES = [((250, 40), (56, 430), (476, 430), 34),
           ((296, 100), (142, 384), (478, 384), 30),
           ((334, 160), (232, 338), (452, 338), 26)]
GRADIENT = [(0, "#22d8ff"), (.22, "#3c8cff"), (.42, "#8a55ff"), (.58, "#d23cf0"), (.74, "#ff3fa0"),
            (.88, "#ff6a4a"), (1, "#ffb43c")]


def stroke_path(tip, corner, end, w, k=1.0, r=46):
    """A filled neon tube: even width along most of its length, tapering to a sharp tip at the top and a sharp
    streak at the end of the tail, around a rounded corner (radius r). k scales its width."""
    T, C, E = (np.array(v, float) for v in (tip, corner, end))
    d1 = (C - T) / np.linalg.norm(C - T)
    d2 = (E - C) / np.linalg.norm(E - C)
    turn = math.acos(max(-1.0, min(1.0, float(d1 @ d2))))   # how far the stroke turns at the corner
    cut = r * math.tan(turn / 2)   # the arc starts and ends this far from the corner
    a, b = C - d1 * cut, C + d2 * cut
    inside = d2 - d1   # the arc's centre sits on the inside of the turn
    side = np.array([-d1[1], d1[0]])
    centre = a + (side if side @ inside > 0 else -side) * r
    pts = list(T + np.outer(np.linspace(0, 1, 40), a - T))
    a0, a1 = math.atan2(*(a - centre)[::-1]), math.atan2(*(b - centre)[::-1])
    a1 = a0 + (a1 - a0 + math.pi) % (2 * math.pi) - math.pi   # the short way round
    pts += [centre + r * np.array([math.cos(t), math.sin(t)]) for t in np.linspace(a0, a1, 16)[1:-1]]
    pts += list(b + np.outer(np.linspace(0, 1, 40), E - b))
    pts = np.array(pts)
    seg = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
    s_ = seg / seg[-1]
    leg = np.linalg.norm(a - T) / seg[-1]
    tail0 = 1 - np.linalg.norm(E - b) / seg[-1]
    # full width from 45% down the first leg until 40% along the tail; smooth tapers either side
    up = np.clip(s_ / (leg * .45), 0, 1)
    down = np.clip((1 - s_) / ((1 - tail0) * .6), 0, 1)
    width = w * k / 2 * np.minimum(np.sin(up * math.pi / 2) ** .7, np.sin(down * math.pi / 2) ** .8)
    tang = np.gradient(pts, axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True)
    norm = np.c_[tang[:, 1], -tang[:, 0]]
    left, right = pts + norm * width[:, None], pts - norm * width[:, None]
    ring = np.r_[left, right[::-1]]
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in ring) + " Z"


def gradient(gid, x1=40, x2=470):
    stops = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in GRADIENT)
    return (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{x1}" y1="0" x2="{x2}" y2="0">'
            f'{stops}</linearGradient>')


def symbol_group(fill="url(#g)", k=1.0, core=True, glow=0.0):
    """The three strokes; core adds the white-hot centre of a neon tube, glow a soft bloom behind."""
    shapes = "".join(f'<path d="{stroke_path(*s[:3], s[3], k)}"/>' for s in STROKES)
    out = ""
    if glow:
        out += f'<g fill="{fill}" filter="url(#bloom)" opacity="{glow}">{shapes}</g>'
    out += f'<g fill="{fill}">{shapes}</g>'
    if core:
        cores = "".join(f'<path d="{stroke_path(*s[:3], s[3], k * .3)}"/>' for s in STROKES)
        out += f'<g fill="#ffffff" opacity=".62">{cores}</g>'
    return out


BLOOM = ('<filter id="bloom" x="-30%" y="-30%" width="160%" height="160%">'
         '<feGaussianBlur stdDeviation="14"/></filter>')


def svg(body, w=512, h=512, defs=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<defs>{defs}</defs>{body}</svg>\n')


def tile(inner, small=False):
    """The app icon: a flat dark rounded square with a faint edge, the symbol inside."""
    edge = 'stroke="#3a4152" stroke-width="6"' if small else 'stroke="#2c3240" stroke-width="4"'
    bg = ('<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
          '<stop offset="0" stop-color="#1a1e28"/><stop offset="1" stop-color="#0b0d12"/></linearGradient>')
    body = (f'<rect x="16" y="16" width="480" height="480" rx="{112 if small else 104}" fill="url(#bg)" {edge}/>'
            f'<g transform="translate(256 262) scale({.9 if small else .74}) translate(-266 -236)">{inner}</g>')
    return body, bg


# ---- wordmark: wide geometric capitals built from strokes (no font needed), 100 high
LETTERS = {
    "L": (100, "M8,0 V92 H100"),
    "U": (112, "M8,0 V70 Q8,92 30,92 H82 Q104,92 104,70 V0"),
    "M": (124, "M8,100 V8 L62,62 L116,8 V100"),
    "O": (120, "M30,8 H90 Q112,8 112,30 V70 Q112,92 90,92 H30 Q8,92 8,70 V30 Q8,8 30,8 Z"),
    "R": (112, "M8,100 V8 H82 Q104,8 104,30 V34 Q104,56 82,56 H8 M62,56 L106,100"),
    "I": (16, "M8,0 V100"),
    "A": (124, "M4,100 L62,4 L120,100 M30,66 H94"),
}


def shift_path(d, dx):
    """Moves a path made of absolute M/L/Q/H/V commands right by dx."""
    out, cmd = [], None
    for tok in d.replace(",", " ").replace("M", " M ").replace("L", " L ").replace("Q", " Q ").replace(
            "H", " H ").replace("V", " V ").replace("Z", " Z ").split():
        if tok.isalpha():
            cmd, i = tok, 0
            out.append(tok)
            continue
        v = float(tok)
        if cmd == "H" or (cmd in "MLQ" and i % 2 == 0):
            v += dx
        out.append(f"{v:g}")
        i += 1
    return " ".join(out)


def wordmark(fill, weight=12, gap=34):
    x, parts = 0, []
    for ch in "LUMORIA":
        w, d = LETTERS[ch]
        parts.append(f'<path d="{shift_path(d, x)}"/>')   # real coordinates, so one gradient spans the word
        x += w + gap
    width = x - gap
    body = (f'<g transform="translate(10 10)" fill="none" stroke="{fill}" stroke-width="{weight}" '
            f'stroke-linejoin="round" stroke-linecap="butt">{"".join(parts)}</g>')
    return body, width + 20, 120


def render(svg_path, png_path, w, h):
    """SVG -> PNG with transparency, through headless Edge."""
    html = os.path.join(tempfile.gettempdir(), "lumoria_logo_render.html")
    with open(html, "w", encoding="utf8") as fh:
        fh.write(f'<html><body style="margin:0;background:transparent">'
                 f'<img src="file:///{svg_path.replace(os.sep, "/")}" width="{w}" height="{h}"></body></html>')
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                    f"--window-size={w},{h}", "--default-background-color=00000000",
                    f"--screenshot={png_path}", "file:///" + html.replace(os.sep, "/")],
                   check=True, capture_output=True, timeout=60)


def main():
    os.makedirs(SVG, exist_ok=True)
    g = gradient("g")
    ice = ('<linearGradient id="ice" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="110">'
           '<stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#b9cdea"/></linearGradient>')
    files = {
        "lumoria_symbol_glow.svg": svg(symbol_group(glow=.75), defs=g + BLOOM),
        "lumoria_symbol.svg": svg(symbol_group(core=False), defs=g),
        "lumoria_symbol_mono.svg": svg(symbol_group(fill="currentColor", core=False)),
        "lumoria_icon.svg": svg(tile(symbol_group(glow=.55))[0], defs=g + BLOOM + tile("")[1]),
        "lumoria_icon_small.svg": svg(tile(symbol_group(k=1.7, core=False), small=True)[0], defs=g + tile("")[1]),
    }
    wb, ww, wh = wordmark("url(#ice)")
    files["lumoria_wordmark.svg"] = svg(wb, ww, wh, defs=ice)
    wb, ww, wh = wordmark("url(#gw)")
    files["lumoria_wordmark_gradient.svg"] = svg(wb, ww, wh, defs=gradient("gw", 0, ww - 20))
    for name, text in files.items():
        with open(os.path.join(SVG, name), "w", encoding="utf8") as fh:
            fh.write(text)

    def png(name, out, w, h):
        render(os.path.join(SVG, name), os.path.join(HERE, out), w, h)

    png("lumoria_symbol.svg", "lumoria_symbol_neon.png", 512, 512)          # top bar (small): crisp, no glow
    png("lumoria_symbol_glow.svg", "lumoria_symbol_neon_glow.png", 512, 512)  # welcome screen and other large uses
    png("lumoria_icon.svg", "lumoria_icon_neon.png", 512, 512)
    png("lumoria_icon_small.svg", "lumoria_icon_neon_small.png", 512, 512)
    ww, wh = wordmark("")[1:]
    png("lumoria_wordmark.svg", "lumoria_wordmark_neon.png", ww * 2, wh * 2)
    png("lumoria_wordmark_gradient.svg", "lumoria_wordmark_neon_gradient.png", ww * 2, wh * 2)

    # the .ico: the bold small tile for 16-32 px, the full tile from 48 up
    big = cv2.imread(os.path.join(HERE, "lumoria_icon_neon.png"), cv2.IMREAD_UNCHANGED)
    small = cv2.imread(os.path.join(HERE, "lumoria_icon_neon_small.png"), cv2.IMREAD_UNCHANGED)
    frames = [(s, cv2.resize(small if s <= 32 else big, (s, s), interpolation=cv2.INTER_AREA))
              for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)]
    write_ico(os.path.join(HERE, "lumoria_neon.ico"), frames)


def write_ico(path, frames):
    """A Windows .ico with PNG-compressed frames (supported since Vista)."""
    blobs = [cv2.imencode(".png", img)[1].tobytes() for _, img in frames]
    head = np.array([0, 1, len(frames)], "<u2").tobytes()
    offset, entries = 6 + 16 * len(frames), b""
    for (s, _), blob in zip(frames, blobs):
        entries += bytes([s % 256, s % 256, 0, 0]) + np.array([1, 32], "<u2").tobytes() \
                   + np.array([len(blob), offset], "<u4").tobytes()
        offset += len(blob)
    with open(path, "wb") as fh:
        fh.write(head + entries + b"".join(blobs))


if __name__ == "__main__":
    main()
