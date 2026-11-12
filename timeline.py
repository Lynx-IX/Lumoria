"""Look timelines: lanes of points that move a look's sliders over time, in sections.

A look can carry a timeline (see docs/timeline-plan.md). It's measured in bars on the tempo clock (or in seconds),
and two markers split it into three sections:

    intro   [0, intro_end)          plays once when the look comes on
    loop    [intro_end, loop_end)   repeats while the look stays on
    outro   [loop_end, length)      plays when the look is leaving (plan_outro: the handover to the next look)

With no markers set the whole timeline loops. Each lane moves one slider of one effect (by effect id and setting key,
the same keys the automate menu uses: "amt", "opacity", "speed", "xs", "xr", "p0".."pN") from point to point. A point
is [position, value, segment]: the segment says how it gets to the next point: "ramp" (a straight line), "ease"
(smooth in and out), "ease_in" / "ease_out", "sharp_in" / "sharp_out" (exponential), "bounce", or "hold" (stays,
then jumps at the next point). See shape().

This module is plain arithmetic, no GPU or window, so it can be tested on its own. The App keeps one Playhead for
the look on air and applies its lanes once a frame.
"""
import math

SEGMENTS = ("ramp", "ease", "ease_in", "ease_out", "sharp_in", "sharp_out", "bounce", "hold")


def shape(seg, u):
    """How far (0..1) a segment of that shape has got at u (0..1) of the way to the next point. Every shape stays
    between the two points' values, so a lane never pushes a slider past them."""
    if seg == "ease":        # smooth in and out
        return u * u * (3 - 2 * u)
    if seg == "ease_in":     # starts slow, speeds up
        return u * u * u
    if seg == "ease_out":    # starts fast, slows down
        return 1 - (1 - u) ** 3
    if seg == "sharp_in":    # an exponential swell: hardly moves, then rushes in
        return (2 ** (10 * u) - 1) / 1023
    if seg == "sharp_out":   # a quick attack that settles
        return 1 - (2 ** (10 * (1 - u)) - 1) / 1023
    if seg == "bounce":      # lands and bounces a few times, smaller each time
        n, d = 7.5625, 2.75
        if u < 1 / d:
            return n * u * u
        if u < 2 / d:
            u -= 1.5 / d
            return n * u * u + .75
        if u < 2.5 / d:
            u -= 2.25 / d
            return n * u * u + .9375
        u -= 2.625 / d
        return n * u * u + .984375
    return 0.0 if seg == "hold" else u


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
            return v0 + (v1 - v0) * shape(seg, (pos - x0) / (x1 - x0))
    return points[-1][1]


def lane_sections(tl, lane=None):
    """(intro_end, loop_end, length) of one lane, in the timeline's unit. A lane can have its own length (at most the
    timeline's) and its own intro / loop / outro; a key it doesn't have comes from the timeline (so older timelines,
    with one set of markers, play as before). intro_end / loop_end set to None: the whole lane is the loop.
    lane=None: the timeline's own (its default for lanes, and the timing of a timeline with no lanes)."""
    own = lambda k: lane[k] if lane is not None and k in lane else tl.get(k)
    length = min(max(own("length") or tl["length"], 1 / 64), tl["length"])
    a, b = own("intro_end"), own("loop_end")
    a = 0.0 if a is None else min(max(0.0, a), length)
    b = length if b is None else min(max(a, b), length)
    if b - a < 1e-6:   # an empty loop can't repeat: treat the lane as one loop
        a, b = 0.0, length
    return a, b, length


def sections(tl):
    """The timeline's own (intro_end, loop_end, length): see lane_sections."""
    return lane_sections(tl, None)


def timing_lanes(tl):
    """The lanes that keep time: every lane, or - for a timeline with none - the timeline itself (as None)."""
    return tl.get("lanes") or [None]


def lead_lane(tl):
    """The lane the look's place is told by (the editor's status, the tile badge, auto-play's loop passes): the one
    with intro / loop / outro and the longest loop, else the longest lane."""
    best, key = None, None
    for lane in timing_lanes(tl):
        a, b, length = lane_sections(tl, lane)
        k = (b - a < length - 1e-6, b - a, length)   # has markers, loop length, length
        if key is None or k > key:
            best, key = lane, k
    return best


class Playhead:
    """Where the look on air is in its timeline. Started when the look comes on; time is counted on the tempo clock's
    beats (bars unit), so it follows tempo changes, or in seconds. Each lane runs its own sections on that clock.
    Once the look is told to leave, `outro_at` says when each lane's outro starts ({lane index: elapsed time}; a plain
    number: every lane at once): from then on that lane plays its outro, once."""

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

    @property
    def outro_start(self):
        """When the first outro starts (elapsed time), or None while the look isn't leaving."""
        o = self.outro_at
        if o is None or isinstance(o, (int, float)):
            return o
        return min(o.values()) if o else None

    def lane_outro_at(self, lane):
        o = self.outro_at
        if o is None or isinstance(o, (int, float)):
            return o
        lanes = timing_lanes(self.tl)
        i = next((k for k, ln in enumerate(lanes) if ln is lane), None)
        return o.get(i)

    def has_outro(self):
        return any(length - b > 1e-6 for a, b, length in (lane_sections(self.tl, ln) for ln in timing_lanes(self.tl)))

    def lane_where(self, lane, e):
        """(position in this lane, section "intro" / "loop" / "outro" / "done", loop passes completed) at elapsed e."""
        a, b, length = lane_sections(self.tl, lane)
        start = self.lane_outro_at(lane)
        if start is not None and length - b > 1e-6 and e >= start - 1e-9:
            n = int(max(0.0, start - a) // (b - a))
            pos = min(length, b + (e - start))
            return pos, ("outro" if pos < length else "done"), n
        if e < a:
            return e, "intro", 0
        n, r = divmod(e - a, b - a)
        return a + r, "loop", int(n)

    def where(self, beat, t):
        """The look's place, told by its lead lane (see lead_lane): (position, section, loop passes)."""
        return self.lane_where(lead_lane(self.tl), self.elapsed(beat, t))

    def pass_end(self, e, lane=None):
        """When the section a lane is playing at elapsed time e ends: the intro's end, or the end of this loop pass
        (now, if it's right on the end of one)."""
        a, b, _ = lane_sections(self.tl, lane)
        if e < a:
            return a
        k = (e - a) / (b - a)
        whole = math.floor(k + 1e-6)
        return e if abs(k - whole) < 1e-6 else a + math.ceil(k) * (b - a)

    def values(self, beat, t, mode="value", holds=None):
        """{(effect id, key): value} for every lane of that mode ("value": the slider's value, "depth": how far its
        wave swings, 0..1), each at its own place. A lane in `holds` ({key: elapsed time}) lets go of its slider
        until then (someone took it over: see hold_until)."""
        e = self.elapsed(beat, t)
        out = {}
        for lane in self.tl.get("lanes", []):
            key = (lane["effect"], lane["key"])
            if lane.get("mode", "value") != mode or lane.get("mute") or (holds and e < holds.get(key, -1.0)):
                continue
            v = value_at(lane["points"], self.lane_where(lane, e)[0])
            if v is not None:
                out[key] = v
        return out

    def hold_until(self, effect, key, beat, t):
        """Someone moved this slider by hand (MIDI or its card): when its lane takes it back - at the lane's next
        point, or where the section it's playing now ends (elapsed time; an outro keeps it until the look changes)."""
        e = self.elapsed(beat, t)
        lane = next((ln for ln in self.tl.get("lanes", []) if ln["effect"] == effect and ln["key"] == key), None)
        pos, section, _ = self.lane_where(lane, e)
        a, b, length = lane_sections(self.tl, lane)
        if section in ("outro", "done"):
            return float("inf")
        end = a if section == "intro" else b
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
    """When a look is told to leave: ({lane index: when its outro starts}, when the next look should start coming in),
    in the playhead's elapsed time (the timeline's unit), or None if no lane has an outro.

    Each lane with an outro starts it when its own loop pass finishes (jump: now); the next look comes in after the
    longest of them ends, its transition (`overlap`, in the timeline's unit) overlapping that end - never more than
    the longest outro. Lanes without an outro keep looping until then. grid: the launch grid in beats (0 = launch
    now): a jump is timed so every outro ENDS together on a launch boundary (bars timelines only; counted from
    bar_origin like the tempo clock's phrases)."""
    lanes = timing_lanes(ph.tl)
    outros = {}
    for i, lane in enumerate(lanes):
        a, b, length = lane_sections(ph.tl, lane)
        if length - b > 1e-6:
            outros[i] = length - b
    if not outros:
        return None
    now = ph.elapsed(beat, t)
    if jump and grid > 0 and ph.tl.get("unit") != "seconds":
        bpb = max(1, ph.beats_per_bar)
        end_beat = ph.start_beat + (now + max(outros.values())) * bpb   # the soonest the longest could end
        k = math.ceil((end_beat - bar_origin) / grid - 1e-6)            # ... on the next launch boundary
        end = (k * grid + bar_origin - ph.start_beat) / bpb
        starts = {i: end - o for i, o in outros.items()}
    elif jump:
        starts = {i: now for i in outros}
    else:
        starts = {i: ph.pass_end(now, lanes[i]) for i in outros}
    end = max(starts[i] + o for i, o in outros.items())
    longest = max(outros.values())
    return starts, max(min(starts.values()), end - min(max(0.0, overlap), longest))


def loop_passes(tl, every_units):
    """How many loop passes auto-play stays for: the timeline's own `loops`, else as many of its lead lane's loops
    as fit auto-play's "every" (given in the timeline's unit), at least one."""
    if tl.get("loops", 0) > 0:
        return int(tl["loops"])
    a, b, _ = lane_sections(tl, lead_lane(tl))
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
        out_lane = dict(effect=eff, key=key, mode="depth" if lane.get("mode") == "depth" else "value",
                        mute=bool(lane.get("mute", False)), points=pts)
        if lane.get("length") is not None:   # its own length and sections (else the timeline's)
            out_lane["length"] = num(lane["length"], length, 1 / 64, length)
        for k in ("intro_end", "loop_end"):
            if k in lane:
                out_lane[k] = None if lane[k] is None else num(lane[k], 0.0, 0.0, out_lane.get("length", length))
        if out_lane.get("intro_end") is not None and out_lane.get("loop_end") is not None                 and out_lane["loop_end"] < out_lane["intro_end"]:
            out_lane["loop_end"] = out_lane["intro_end"]
        lanes.append(out_lane)
    out["lanes"] = lanes
    return out

