"""Look timelines: lanes of points that move a look's sliders over time, in sections.

A look can carry a timeline (see docs/timeline-plan.md). It's measured in bars on the tempo clock (or in seconds),
and two markers split it into three sections:

    intro   [0, intro_end)          plays once when the look comes on
    loop    [intro_end, loop_end)   repeats while the look stays on
    outro   [loop_end, length)      plays when the look is leaving (plan_outro: the handover to the next look)

With no markers set the whole timeline loops. Each lane moves one slider of one effect (by effect id and setting key,
the same keys the automate menu uses: "amt", "opacity", "speed", "xs", "xr", "p0".."pN") from point to point. A point
is [position, value, segment]: the segment says how it gets to the next point: "ramp" (a straight line), "ease"
(smooth in and out) or "hold" (stays, then jumps at the next point).

This module is plain arithmetic, no GPU or window, so it can be tested on its own. The App keeps one Playhead for
the look on air and applies its lanes once a frame.
"""
import math

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
    beats (bars unit), so it follows tempo changes, or in seconds. Once the look is told to leave, `outro_at` (in
    elapsed time, the timeline's unit) is when its outro starts: from then on it plays the outro, once."""

    def __init__(self, tl, beat, t, beats_per_bar=4):
        self.tl = tl
        self.start_beat, self.start_t = beat, t
        self.beats_per_bar = beats_per_bar
        self.outro_at = None

    def elapsed(self, beat, t):
        """Time since the start, in the timeline's unit."""
        if self.tl.get("unit") == "seconds":
            return max(0.0, t - self.start_t)
        return max(0.0, (beat - self.start_beat) / max(1, self.beats_per_bar))

    def has_outro(self):
        a, b, length = sections(self.tl)
        return length - b > 1e-6

    def where(self, beat, t):
        """(position on the timeline, section "intro" / "loop" / "outro" / "done", loop passes completed)."""
        e = self.elapsed(beat, t)
        a, b, length = sections(self.tl)
        if self.outro_at is not None and e >= self.outro_at - 1e-9:
            n = int(max(0.0, self.outro_at - a) // (b - a))
            pos = min(length, b + (e - self.outro_at))
            return pos, ("outro" if pos < length else "done"), n
        if e < a:
            return e, "intro", 0
        n, r = divmod(e - a, b - a)
        return a + r, "loop", int(n)

    def pass_end(self, e):
        """When the section playing at elapsed time e ends: the intro's end, or the end of this loop pass (now, if
        it's right on the end of one)."""
        a, b, _ = sections(self.tl)
        if e < a:
            return a
        k = (e - a) / (b - a)
        whole = math.floor(k + 1e-6)
        return e if abs(k - whole) < 1e-6 else a + math.ceil(k) * (b - a)

    def values(self, beat, t, mode="value", holds=None):
        """{(effect id, key): value} for every lane of that mode ("value": the slider's value, "depth": how far its
        wave swings, 0..1) at the current position. A lane in `holds` ({key: elapsed time}) lets go of its slider
        until then (someone took it over: see hold_until)."""
        pos, _, _ = self.where(beat, t)
        e = self.elapsed(beat, t) if holds else 0.0
        out = {}
        for lane in self.tl.get("lanes", []):
            key = (lane["effect"], lane["key"])
            if lane.get("mode", "value") != mode or lane.get("mute") or (holds and e < holds.get(key, -1.0)):
                continue
            v = value_at(lane["points"], pos)
            if v is not None:
                out[key] = v
        return out

    def hold_until(self, effect, key, beat, t):
        """Someone moved this slider by hand (MIDI or its card): when its lane takes it back - at the lane's next
        point, or where the section playing now ends (elapsed time; the outro keeps it until the look changes)."""
        e = self.elapsed(beat, t)
        pos, section, _ = self.where(beat, t)
        a, b, length = sections(self.tl)
        if section in ("outro", "done"):
            return float("inf")
        end = a if section == "intro" else b
        lane = next((ln for ln in self.tl.get("lanes", []) if ln["effect"] == effect and ln["key"] == key), None)
        ahead = [p[0] for p in (lane["points"] if lane else []) if pos + 1e-9 < p[0] <= end]
        return e + ((min(ahead) if ahead else end) - pos)


def simplify(points, tol=0.02):
    """A recorded lane, tidied (Douglas-Peucker): only the points needed to keep its shape within tol (a share of
    the lane's own range - a couple of MIDI steps) stay, so a take is easy to edit. Holds and eases always stay."""
    if len(points) < 3:
        return points
    vals = [p[1] for p in points]
    eps = tol * ((max(vals) - min(vals)) or 1.0)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        a, b = points[i], points[j]
        worst, k = -1.0, None
        for m in range(i + 1, j):
            p = points[m]
            if p[2] != "ramp":   # a shape someone chose: keep it
                keep[m] = True
            span = b[0] - a[0]
            guess = a[1] if span <= 0 else a[1] + (b[1] - a[1]) * (p[0] - a[0]) / span
            d = abs(p[1] - guess)
            if d > worst:
                worst, k = d, m
        if k is not None and worst > eps:
            keep[k] = True
            stack += [(i, k), (k, j)]
    return [p for p, kp in zip(points, keep) if kp]


def plan_outro(ph, beat, t, jump=False, grid=0.0, bar_origin=0.0, overlap=0.0):
    """When a look is told to leave: (when its outro starts, when the next look should start coming in), both in the
    playhead's elapsed time (the timeline's unit), or None if the timeline has no outro.

    jump: the outro starts now (else the loop pass playing now finishes first). grid: the launch grid in beats
    (0 = launch now) - a jump is then timed so the outro ENDS on a launch boundary (bars timelines only; counted
    from bar_origin like the tempo clock's phrases). overlap: the next look's transition, in the timeline's unit -
    it comes in that much before the outro ends, so the two overlap (never more than the outro itself)."""
    if not ph.has_outro():
        return None
    a, b, length = sections(ph.tl)
    outro = length - b
    now = ph.elapsed(beat, t)
    if not jump:
        start = ph.pass_end(now)
    elif grid > 0 and ph.tl.get("unit") != "seconds":
        bpb = max(1, ph.beats_per_bar)
        end_beat = ph.start_beat + (now + outro) * bpb            # the soonest it could end
        k = math.ceil((end_beat - bar_origin) / grid - 1e-6)      # ... on the next launch boundary
        start = (k * grid + bar_origin - ph.start_beat) / bpb - outro
    else:
        start = now
    end = start + outro
    return start, max(start, end - min(max(0.0, overlap), outro))


def loop_passes(tl, every_units):
    """How many loop passes auto-play stays for: the timeline's own `loops`, else as many as fit auto-play's
    "every" (given in the timeline's unit), at least one."""
    if tl.get("loops", 0) > 0:
        return int(tl["loops"])
    a, b, _ = sections(tl)
    return max(1, round(every_units / (b - a)))


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

