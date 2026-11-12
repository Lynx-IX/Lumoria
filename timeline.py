"""Look timelines: lanes of points that move a look's sliders over time, in sections.

A look can carry a timeline (see docs/timeline-plan.md). It's measured in bars on the tempo clock (or in seconds),
and two markers split it into three sections:

    intro   [0, intro_end)          plays once when the look comes on
    loop    [intro_end, loop_end)   repeats while the look stays on
    outro   [loop_end, length)      plays when the look is leaving (the handover: a later step)

With no markers set the whole timeline loops. Each lane moves one slider of one effect (by effect id and setting key,
the same keys the automate menu uses: "amt", "opacity", "speed", "xs", "xr", "p0".."pN") from point to point. A point
is [position, value, segment]: the segment says how it gets to the next point: "ramp" (a straight line), "ease"
(smooth in and out) or "hold" (stays, then jumps at the next point).

This module is plain arithmetic, no GPU or window, so it can be tested on its own. The App keeps one Playhead for
the look on air and applies its lanes once a frame.
"""
SEGMENTS = ("ramp", "ease", "hold")
UNITS = ("bars", "seconds")
KEYS_FIXED = ("amt", "opacity", "speed", "xs", "xr")   # plus "p0", "p1"... (an effect's own sliders)
MAX_LANES = 64
MAX_POINTS = 512
MAX_LENGTH = 4096.0   # bars (or seconds)


def valid_key(key):
    return isinstance(key, str) and (key in KEYS_FIXED or (key[:1] == "p" and key[1:].isdigit() and len(key) <= 4))


def value_at(points, pos):
    """The lane's value at `pos` (points sorted by position). Before the first point: its value; after the last:
    the last one's (it holds)."""
    if not points:
        return None
    if pos < points[0][0]:
        return points[0][1]
    for (x0, v0, seg), (x1, v1, _) in zip(points, points[1:]):
        if pos < x1:
            if seg == "hold" or x1 <= x0:
                return v0
            u = (pos - x0) / (x1 - x0)
            if seg == "ease":
                u = u * u * (3 - 2 * u)
            return v0 + (v1 - v0) * u
    return points[-1][1]


def sections(tl):
    """(intro_end, loop_end, length) in the timeline's own unit. No markers: the whole timeline is the loop."""
    length = tl["length"]
    a = tl.get("intro_end")
    b = tl.get("loop_end")
    a = 0.0 if a is None else min(max(0.0, a), length)
    b = length if b is None else min(max(a, b), length)
    if b - a < 1e-6:   # an empty loop can't repeat: treat the timeline as one loop
        a, b = 0.0, length
    return a, b, length


class Playhead:
    """Where the look on air is in its timeline. Started when the look comes on; time is counted on the tempo clock's
    beats (bars unit), so it follows tempo changes, or in seconds."""

    def __init__(self, tl, beat, t, beats_per_bar=4):
        self.tl = tl
        self.start_beat, self.start_t = beat, t
        self.beats_per_bar = beats_per_bar

    def elapsed(self, beat, t):
        """Time since the start, in the timeline's unit."""
        if self.tl.get("unit") == "seconds":
            return max(0.0, t - self.start_t)
        return max(0.0, (beat - self.start_beat) / max(1, self.beats_per_bar))

    def where(self, beat, t):
        """(position on the timeline, section "intro" / "loop", loop passes completed)."""
        e = self.elapsed(beat, t)
        a, b, _ = sections(self.tl)
        if e < a:
            return e, "intro", 0
        n, r = divmod(e - a, b - a)
        return a + r, "loop", int(n)

    def values(self, beat, t):
        """{(effect id, key): value} for every lane, at the current position."""
        pos, _, _ = self.where(beat, t)
        out = {}
        for lane in self.tl.get("lanes", []):
            v = value_at(lane["points"], pos)
            if v is not None and lane.get("mode", "value") == "value" and not lane.get("mute"):
                out[(lane["effect"], lane["key"])] = v
        return out


def clean_timeline(tl, num, text):
    """A safe copy of a look's timeline (as read from a file), or None. num(v, default, lo, hi) and text(v) are
    lookcheck's checkers."""
    if not isinstance(tl, dict):
        return None
    unit = tl.get("unit") if tl.get("unit") in UNITS else "bars"
    length = num(tl.get("length"), 8.0, 0.25, MAX_LENGTH)
    out = dict(unit=unit, length=length, grid=num(tl.get("grid"), 0.25, 1 / 64, 64.0),
               on_leave="jump" if tl.get("on_leave") == "jump" else "finish",
               loops=int(num(tl.get("loops"), 0, 0, 1000)))
    for k in ("intro_end", "loop_end"):
        if tl.get(k) is not None:
            out[k] = num(tl[k], 0.0, 0.0, length)
    if "intro_end" in out and "loop_end" in out and out["loop_end"] < out["intro_end"]:
        out["loop_end"] = out["intro_end"]
    lanes = []
    for lane in tl.get("lanes", [])[:MAX_LANES] if isinstance(tl.get("lanes"), list) else []:
        if not isinstance(lane, dict):
            continue
        eff, key = text(lane.get("effect")), lane.get("key")
        if not eff or not valid_key(key):
            continue
        pts = []
        for p in lane.get("points", [])[:MAX_POINTS] if isinstance(lane.get("points"), list) else []:
            if not isinstance(p, (list, tuple)) or len(p) < 2:
                continue
            x, v = num(p[0], None, 0.0, length), num(p[1], None)
            if x is None or v is None:
                continue
            seg = p[2] if len(p) > 2 and p[2] in SEGMENTS else "ramp"
            pts.append([x, v, seg])
        pts.sort(key=lambda p: p[0])
        lanes.append(dict(effect=eff, key=key, mode="depth" if lane.get("mode") == "depth" else "value",
                          mute=bool(lane.get("mute", False)), points=pts))
    out["lanes"] = lanes
    return out

