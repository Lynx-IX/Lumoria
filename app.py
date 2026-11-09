"""Lumoria Visual FX Engine: real-time GPU video effects for OBS and friends.

Control window (preview + settings) and a clean "Lumoria Output" window for OBS Window Capture.
Can also publish to the OBS Virtual Camera for Discord / Zoom / etc.
"""
import sys

if __name__ == "__main__" and "--record-worker" in sys.argv:   # Lumoria.exe as the recording helper (recorder.py)
    import recorder
    recorder.worker_main(sys.argv[sys.argv.index("--record-worker") + 1])
    raise SystemExit

import base64
import ctypes
import json
import math
import os
import queue
import random
import shutil
import subprocess
import threading
import time

import cv2
import glfw  # import before imgui_bundle so we use the standard glfw
import moderngl
import numpy as np
import OpenGL
OpenGL.ERROR_CHECKING = False  # else PyOpenGL raises on any stale GL error; we log them instead
import OpenGL.GL as GL
from imgui_bundle import imgui
from imgui_bundle import portable_file_dialogs as pfd
from imgui_bundle.python_backends.glfw_backend import GlfwRenderer

import effects as E
import ui
import audio as A
from audio import AudioAnalyzer, list_inputs
from shared import (AUTO_OFF, AUTO_PLAYLIST, AUTO_RANDOM, DATA, FROZEN, HERE, LOOK_MORPH, MOD_AUDIO, MOD_OFF, MOD_WAVE,
                    RESOLUTIONS, TRANSITIONS, VERSION)
from segment import MODEL as SEG_MODEL, QUALITY as SEG_QUALITY, Segmenter
import midi
import recorder
import sources
import tempo
from sources import (CameraSource, VideoFileSource, describe, list_cameras, list_screens, list_windows,
                     open_source)

PRESET_DIR = os.path.join(DATA, "presets")
PLAYLIST_FILE = os.path.join(PRESET_DIR, "_playlist.json")
MIDI_FILE = os.path.join(DATA, "midi_map.json")   # MIDI mappings (global, not per look)
RUNNING_FILE = os.path.join(DATA, ".running")   # exists while Lumoria runs (see App.unclean)
VCAM_FPS = 60
DEFAULT_COLOURS = [(1.0, 0.16, 0.6), (0.55, 0.2, 1.0), (0.0, 0.9, 1.0)]   # starting "Custom" palette


def set_u(prog, name, value):
    if name in prog:
        prog[name].value = value


# ---------------------------------------------------------------- GPU pipeline

class Target:
    def __init__(self, ctx, w, h, dtype="f1", clear_alpha=1.0):
        self.tex = ctx.texture((w, h), 4, dtype=dtype)
        self.tex.repeat_x = self.tex.repeat_y = False
        self.fbo = ctx.framebuffer(color_attachments=[self.tex])
        self.fbo.clear(0, 0, 0, clear_alpha)

    def release(self):
        self.fbo.release()
        self.tex.release()


def glide_target(f, dt, secs):
    """Move an item's Apply-to weights (everywhere, subject, background) toward its current choice over
    about secs, so switching All / Subject / Background crossfades. Returns them for u_tw."""
    goal = target_weights(0 if getattr(f, "needs_mask", False) else f.target)
    k = 1.0 if secs <= 0 else 1.0 - np.exp(-4.0 * dt / secs)
    f.tw = [g if abs(g - w) < 1e-3 else w + (g - w) * k for w, g in zip(f.tw, goal)]
    return tuple(f.tw)


def target_weights(target):
    return [1.0 if i == target else 0.0 for i in range(3)]


def ease(x):
    return x * x * (3 - 2 * x)


class Effect:
    def __init__(self, ctx, spec, copy_no=1):
        # copy_no > 1: an extra copy made with Duplicate, with its own settings ("edges#2", "Neon Edges 2")
        self.spec, self.kind, self.copy_no = spec, spec["id"], copy_no
        self.id = spec["id"] if copy_no == 1 else f"{spec['id']}#{copy_no}"
        self.name = spec["name"] if copy_no == 1 else f"{spec['name']} {copy_no}"
        self.cat = spec.get("cat", "Other")
        self.amt, self.on = spec["amt"], False
        self.expanded = False        # settings card open in the UI
        self.removing = False        # fading out, then leaves the chain
        self.xf_keep = False         # in both looks of a running look crossfade (not ramped by Grow)
        self.keep_out = False        # left out of Trails' "Final output" feedback, with everything after it
        self.autos = {}              # automation: setting key ("amt", "p2"...) -> its LFO (see App.automate)
        self.morph = None            # (from, to, start time, seconds) while a Morph transition slides it
        self.mod = MOD_AUDIO if spec.get("react") else MOD_OFF
        # what an Audio-driven effect follows: None = the main "React to" setting, else an audio.SOURCES key;
        # rng = its frequency range (Hz) for "range"; resp = None (the main smoothing) or [attack, release] in s
        self.listen, self.rng, self.resp = None, [80.0, 250.0], None
        self.follow, self.follow_t = 0.0, None   # its own smoothed level, when resp is set
        self.live = 0.0
        self.mix = 0.0               # 0..1 fade position, eases toward on/off
        self.opacity = 1.0           # how much of the effect shows over its input
        self.blend = 0               # index into effects.BLEND_MODES
        self.has_centre = spec.get("center", False)
        self.centre = [0.5, 0.5]     # image coords, (0,0) = top-left
        self.amt_smooth = self.amt   # glides toward amt so preset changes don't jump
        # dropdown options, passed to the shader as u_opt0, u_opt1, ...
        self.options = spec.get("options", [])
        self.opts = [default for _label, _choices, default in self.options]
        # extra sliders, passed as u_p0, u_p1, ...: (label, default, min, max, format)
        self.params = [(p[0], p[1], p[2] if len(p) > 2 else 0.0, p[3] if len(p) > 3 else 1.0,
                        p[4] if len(p) > 4 else "%.2f") for p in spec.get("params", [])]
        self.pvals = [p[1] for p in self.params]
        self.amt_label = spec.get("amt_label", "")
        # animated effects run on their own clock so Speed can slow, freeze or reverse them
        self.has_speed = spec.get("speed", False)
        self.speed, self.clock = 1.0, 0.0
        # wrap the effect so it can be faded against its input (u_mix)
        code = spec["code"].replace("void main()", "void fx_main()", 1) + E.BLEND_WRAPPER
        self.prog = ctx.program(vertex_shader=E.VERT, fragment_shader=E.HEAD + code)
        self.vao = ctx.vertex_array(self.prog, [])
        # effects with memory: each "state" pass updates its own float buffer every frame and can
        # read the others as u_s0, u_s1 (earlier passes already updated this frame)
        self.state_passes = []
        for state_code in spec.get("state", []):
            prog = ctx.program(vertex_shader=E.VERT, fragment_shader=E.HEAD + state_code)
            self.state_passes.append((prog, ctx.vertex_array(prog, [])))
        # per pass: (size multiple of the output, texture type); default same size, half-float
        self.state_size = spec.get("state_size", [(1, "f2")] * len(self.state_passes))
        self.state, self.parity = [], 0
        for prog in [self.prog] + [p for p, _ in self.state_passes]:
            for name, unit in (("u_tex", 0), ("u_prev", 1), ("u_clean", 2), ("u_mask", 3),
                               ("u_s0", 4), ("u_s1", 5), ("u_m0", 6), ("u_m1", 7), ("u_m2", 8),
                               ("u_audiotex", 9), ("u_plate", 11)):
                set_u(prog, name, unit)
        # the effect's own colours for the "Custom" palette (2 to effects.MAX_COLOURS)
        self.colours = [list(c) for c in DEFAULT_COLOURS]
        # person mask: some effects always need it; any effect can target subject/background with it
        self.needs_mask = spec.get("mask", False)
        self.mask_when = spec.get("mask_when")   # (option index, choices) that use the mask, e.g. person outline
        # point particles: real particles kept in a small float texture (one texel each), moved by an update
        # pass, then drawn as glowing points over the effect's picture (see effects.PARTICLES)
        self.points = None
        if "points" in spec:
            pts = spec["points"]
            n = pts["n"]
            upd = ctx.program(vertex_shader=E.VERT, fragment_shader=E.HEAD + pts["update"])
            drw = ctx.program(vertex_shader=pts["vert"], fragment_shader=E.HEAD + pts["frag"])
            self.points = dict(n=n, update=(upd, ctx.vertex_array(upd, [])), draw=(drw, ctx.vertex_array(drw, [])),
                               pos=[Target(ctx, n, n, "f4", 0.0) for _ in range(2)], cur=0)
            for prog in (upd, drw):
                for name, unit in (("u_tex", 0), ("u_prev", 1), ("u_clean", 2), ("u_mask", 3), ("u_s0", 4),
                                   ("u_s1", 5), ("u_audiotex", 9), ("u_pos", 10)):
                    set_u(prog, name, unit)
        self.target = 0              # 0 everything, 1 subject only, 2 background only
        self.tw = [1.0, 0.0, 0.0]    # the same as gliding weights, see glide_target
        self.place_first = spec.get("first", False)

    def release(self):
        """Free the GPU side of an extra copy that's no longer used."""
        objs = [self.prog, self.vao] + [o for pv in self.state_passes for o in pv]
        objs += [t for pair in self.state for t in pair]
        if self.points:
            objs += [o for k in ("update", "draw") for o in self.points[k]] + self.points["pos"]
        for o in objs:
            o.release()

    def copy_settings(self, f):
        """Take over another effect's settings (for Duplicate)."""
        self.amt = self.amt_smooth = f.amt
        self.mod, self.opacity, self.blend, self.speed = f.mod, f.opacity, f.blend, f.speed
        self.centre, self.opts, self.pvals = list(f.centre), list(f.opts), list(f.pvals)
        self.colours = [list(c) for c in f.colours]
        self.target, self.tw, self.expanded, self.keep_out = f.target, list(f.tw), f.expanded, f.keep_out
        self.autos = copy_autos(f.autos)
        self.listen, self.rng, self.resp = f.listen, list(f.rng), list(f.resp) if f.resp else None

    def apply_uniforms(self, prog, size, dt, level, beat):
        set_u(prog, "u_res", size)
        set_u(prog, "u_time", self.clock)
        set_u(prog, "u_dt", dt)
        set_u(prog, "u_speed", self.speed)
        set_u(prog, "u_amt", self.live)
        set_u(prog, "u_audio", level)
        set_u(prog, "u_centre", tuple(self.centre))
        for i, v in enumerate(self.opts):
            set_u(prog, f"u_opt{i}", v)
        for i, v in enumerate(self.pvals):
            set_u(prog, f"u_p{i}", v)
        cols = [tuple(c) for c in self.colours][:E.MAX_COLOURS]
        set_u(prog, "u_cols", cols + [cols[-1]] * (E.MAX_COLOURS - len(cols)))   # the array is always full
        set_u(prog, "u_ncols", len(cols))
        set_u(prog, "u_bands", beat["bands"])
        set_u(prog, "u_hits", beat["hits"])
        set_u(prog, "u_beats", beat["count"])
        set_u(prog, "u_since", beat["since"])
        set_u(prog, "u_beatlen", beat["len"])


class SourceMask:
    """The AI person mask for one of Sources 2-4 (for source groups): the raw mask from its own segmenter,
    refined and stabilised against that source's own picture like the main camera's, plus a small copy of the
    picture for the segmenter (read back a frame later so the GPU never stalls)."""

    def __init__(self, ctx, size, small_size):
        self.raw = ctx.texture((32, 32), 1, bytes(32 * 32))
        self.refs = [Target(ctx, *size) for _ in range(2)]
        self.i, self.fresh, self.tex = 0, True, None
        self.small = Target(ctx, *small_size)
        self.pbo, self.full, self.ready = [ctx.buffer(reserve=small_size[0] * small_size[1] * 3) for _ in range(2)], \
            [False, False], None
        self.active = False   # wanted this frame (the App decides)

    def upload(self, mask):
        h, w = mask.shape
        if self.raw.size != (w, h):
            ctx = self.raw.ctx
            self.raw.release()
            self.raw = ctx.texture((w, h), 1, alignment=1)
        self.raw.write(np.ascontiguousarray(mask), alignment=1)

    def release(self):
        for o in [self.raw, self.small] + self.refs + self.pbo:
            o.release()


class Group:
    """A layer: runs its own effects on a copy of the picture, then blends the result back
    (with opacity, blend mode, apply-to and fades, like a single effect). With `source` set (0-2 = Source 2-4)
    it starts from that video alone instead, so its effects touch nothing else, and places the result in the
    picture like a Media Layer (size, fit, position, rotation, rounded corners, border)."""
    _next = 1

    def __init__(self, name=None):
        self.uid = 10000 + Group._next          # effects use their library index as uid
        self.id = f"group{Group._next}"
        self.name = name or f"Group {Group._next}"
        Group._next += 1
        self.children = []
        self.on, self.mix, self.removing, self.expanded = True, 0.0, False, True
        self.keep_out = False
        self.opacity, self.blend, self.target = 1.0, 0, 0
        self.tw = [1.0, 0.0, 0.0]
        self.amt = self.amt_smooth = self.live = 1.0
        self.mod, self.needs_mask = MOD_OFF, False
        self.ping = []                           # its own ping-pong buffers, made by Pipeline
        self.src = None                          # the source copied to frame size (source groups)
        self.source = -1                         # -1: the picture so far; 0-2: Source 2-4 on its own
        self.cutout = False                      # source groups: place only the person (that source's AI mask)
        self.size, self.centre, self.fit = 0.6, [0.5, 0.5], 1
        self.rotate, self.rounded, self.border = 0.0, 0.0, 0.0


def walk(items):
    """Every effect and group in a chain, depth first."""
    for it in items:
        yield it
        if isinstance(it, Group):
            yield from walk(it.children)


class Pipeline:
    _next_uid = 5000   # extra copies' uids (originals use their library index)

    def __init__(self, ctx):
        self.ctx = ctx
        self.src_prog = ctx.program(vertex_shader=E.VERT, fragment_shader=E.HEAD + E.SOURCE)
        self.copy_prog = ctx.program(vertex_shader=E.VERT, fragment_shader=E.HEAD + E.COPY)
        self.src_vao = ctx.vertex_array(self.src_prog, [])
        self.copy_vao = ctx.vertex_array(self.copy_prog, [])
        # a group's finished picture (unit 4) blended over its input with the usual blend wrapper
        self.group_prog = ctx.program(vertex_shader=E.VERT, fragment_shader=E.HEAD
                                      + "void fx_main(){ o = texture(u_s0, v_uv); }" + E.BLEND_WRAPPER)
        for name, unit in (("u_tex", 0), ("u_mask", 3), ("u_s0", 4)):
            set_u(self.group_prog, name, unit)
        self.group_vao = ctx.vertex_array(self.group_prog, [])
        self.place_prog = ctx.program(vertex_shader=E.VERT, fragment_shader=E.HEAD + E.GROUP_PLACE + E.BLEND_WRAPPER)
        for name, unit in (("u_tex", 0), ("u_mask", 3), ("u_s0", 4)):
            set_u(self.place_prog, name, unit)
        self.place_vao = ctx.vertex_array(self.place_prog, [])
        set_u(self.place_prog, "u_cut", 12)
        self.alpha_prog = ctx.program(vertex_shader=E.VERT, fragment_shader=E.HEAD + E.ALPHA_OUT)
        for name, unit in (("u_tex", 0), ("u_mask", 3)):
            set_u(self.alpha_prog, name, unit)
        self.alpha_vao = ctx.vertex_array(self.alpha_prog, [])
        self.alpha_out = None              # (edge softness, matte middle) while an eraser makes the background transparent
        self.slot_masks = [None] * 3       # SourceMask per Source 2-4, made when a source group needs one
        self.main_mask = None              # the texture on unit 3 this frame (the main camera's refined mask)
        # two complete effect sets, so the outgoing look can keep running while the next one fades in
        # (extra copies made with Duplicate are appended to these, see new_copy)
        self.libs = [[Effect(ctx, s) for s in E.EFFECTS] for _ in range(2)]
        for lib in self.libs:
            for i, f in enumerate(lib):
                f.uid = i
        self.lib_i = 0
        self.order = []                                      # the chain: effects and groups, top to bottom
        self.outgoing = None   # the previous look while a look crossfade runs (see crossfade_to)
        self.mix_prog = ctx.program(vertex_shader=E.VERT, fragment_shader=E.HEAD + E.LOOK_MIX)
        set_u(self.mix_prog, "u_tex", 0)
        set_u(self.mix_prog, "u_s0", 4)
        self.mix_vao = ctx.vertex_array(self.mix_prog, [])
        self.ping_out = []
        self.src_tex = None
        self.ping, self.clean, self.out, self.size = [], None, None, None
        self.seg_small, self.mask_tex = None, None
        self.seg_pbo, self.seg_pbo_full = [], [False, False]   # see grab_small_async
        # extra sources (Source 2-4) for Media Layer effects; a black pixel stands in until one has a frame
        self.blank = ctx.texture((1, 1), 3, bytes(3))
        # AI mask refinement (full-res, edge-snapped, stabilised): a two-pass guided filter, see effects.GUIDED_A/B
        self.gf_progs = []
        for code in (E.GUIDED_A, E.GUIDED_B):
            prog = ctx.program(vertex_shader=E.VERT, fragment_shader=E.HEAD + code)
            for name, unit in (("u_tex", 0), ("u_clean", 2), ("u_s0", 4), ("u_s1", 5), ("u_plate", 11)):
                set_u(prog, name, unit)
            self.gf_progs.append((prog, ctx.vertex_array(prog, [])))
        self.gf_ab = None
        self.gf_rad, self.gf_eps = 0.0, 0.0012   # radius override (0 = from Edge refine), edge sensitivity
        self.mask_ref, self.ref_i, self.ref_fresh = [], 0, True
        self.mask_active, self.refine, self.stability = False, 0.9, 0.5
        # clean plate: the empty room, averaged over a second of frames. It sharpens the AI mask (anything
        # that changed near the person is the person) and lets the eraser make the person invisible.
        self.plate, self.plate_acc, self.plate_new, self.plate_left = None, [], [], 0
        self.plate_strength, self.plate_small = 0.7, None
        self.plate_prog = ctx.program(vertex_shader=E.VERT, fragment_shader=E.HEAD + E.PLATE_ACC)
        for name, unit in (("u_clean", 2), ("u_s0", 4)):
            set_u(self.plate_prog, name, unit)
        self.plate_vao = ctx.vertex_array(self.plate_prog, [])
        self.seg_long = 640          # segmenter input size (long side): the AI Mask quality
        self.media_tex, self.media_asp, self.media_live = [None] * 3, [16 / 9] * 3, [0.0] * 3
        # the texture units effects sample from: 0 input, 1 last output, 2 clean feed, 3 person mask,
        # 4-5 effect memory, 6-8 extra sources
        # audio for the shaders: a 128 x 2 float texture (row 0 spectrum, row 1 waveform) on unit 9, and
        # beat timing (bass, mid, high levels; beats counted; seconds since the last; seconds per beat)
        self.audio_tex = ctx.texture((128, 2), 1, dtype="f4")
        self.beat = dict(bands=(0.0, 0.0, 0.0), hits=(0.0, 0.0, 0.0, 0.0), count=0.0, since=10.0, len=0.5)
        self.level_of = None   # (effect, t) -> its audio level, for effects that listen to their own source
        self.transition, self.trans_time, self.wave_rate = 0, 1.0, 0.25
        self.trans_unit, self.trans_secs = 0, 1.0   # trans_time is in seconds / beats / bars; trans_secs = seconds
        self.override = None   # (style, seconds, until time) while a look with its own transition fades in
        self.resize(1280, 720)

    @property
    def effects(self):
        """The effect set the live chain uses (the library the UI shows)."""
        return self.libs[self.lib_i]

    def resize(self, w, h):
        for t in self.ping + self.ping_out + [t for t in (self.clean, self.out) if t]:   # seg_small: resize_seg
            t.release()
        self.ping = [Target(self.ctx, w, h) for _ in range(2)]
        self.ping_out = [Target(self.ctx, w, h) for _ in range(2)]   # for the outgoing look
        self.clean = Target(self.ctx, w, h)  # the untouched feed, available to every effect
        self.out = Target(self.ctx, w, h)
        # what feedback effects (u_prev) see of the last frame: the output, or, when an effect is marked
        # "keep out of trails", the picture just before it (written to one buffer while the other is read)
        for t in getattr(self, "fb", []):
            t.release()
        self.fb, self.fb_w, self.fb_ready = [Target(self.ctx, w, h) for _ in range(2)], 0, False
        self.size = (w, h)
        # small copy of the clean feed for the segmenter (~640 px on the long side, multiples of 32)
        self.resize_seg()
        for t in self.mask_ref + ([self.gf_ab] if self.gf_ab else []):
            t.release()
        self.mask_ref, self.ref_fresh = [Target(self.ctx, w, h) for _ in range(2)], True
        self.gf_ab = Target(self.ctx, w, h, "f2")
        if self.mask_tex is None:
            self.upload_mask(np.zeros((32, 32), np.uint8))
        self.clear_plate()   # a plate only fits the frame size it was captured at
        for i, sm in enumerate(getattr(self, "slot_masks", [])):   # per-source masks: remade at the new size
            if sm:
                sm.release()
                self.slot_masks[i] = None
        for f in self.libs[0] + self.libs[1]:  # memory buffers: half-float so slow fades don't stick at 8-bit
            for pair in f.state:
                for t in pair:
                    t.release()
            f.state = [[Target(self.ctx, w * k, h * k, dtype, 0.0) for _ in range(2)] for k, dtype in f.state_size]
        self.outgoing = None
        for g in walk(self.order):
            if isinstance(g, Group):
                self.alloc_group(g)

    def new_copy(self, lib, kind, copy_no=None):
        """Add an extra copy of effect `kind` to effect set `lib` (the next free number unless given)."""
        effects = self.libs[lib]
        taken = {f.copy_no for f in effects if f.kind == kind}
        copy_no = copy_no or next(n for n in range(2, 1000) if n not in taken)
        spec = next(f.spec for f in effects if f.kind == kind)
        f = Effect(self.ctx, spec, copy_no)
        Pipeline._next_uid += 1
        f.uid = Pipeline._next_uid
        w, h = self.size
        f.state = [[Target(self.ctx, w * k, h * k, dtype, 0.0) for _ in range(2)] for k, dtype in f.state_size]
        effects.append(f)
        return f

    def ensure_effects(self, lib, ids):
        """Make sure effect set `lib` has every effect a look names, creating copies like "edges#2"."""
        have = {f.id for f in self.libs[lib]}
        kinds = {f.kind for f in self.libs[lib]}
        for i in ids:
            kind, _, n = i.partition("#")
            if i not in have and kind in kinds and n.isdigit():
                self.new_copy(lib, kind, int(n))

    def drop_unused_copies(self, keep):
        """Free extra copies that are in neither chain (keep = items still in use)."""
        for lib in self.libs:
            for f in [f for f in lib if f.copy_no > 1 and f not in keep]:
                lib.remove(f)
                f.release()

    def alloc_group(self, g):
        for t in g.ping + ([g.src] if g.src else []):
            t.release()
        g.ping = [Target(self.ctx, *self.size) for _ in range(2)]
        g.src = Target(self.ctx, *self.size)

    # --- chain structure
    def container_of(self, item, items=None):
        """The list (top-level chain or a group's children) that holds item, or None."""
        items = self.order if items is None else items
        if item in items:
            return items
        for it in items:
            if isinstance(it, Group) and (found := self.container_of(item, it.children)) is not None:
                return found
        return None

    def find(self, uid):
        return next((it for it in walk(self.order) if it.uid == uid), None)

    def move_item(self, item, dest, index=None):
        """Move item into list dest (before index, or to the end). Refuses to put a group inside itself."""
        if isinstance(item, Group) and (dest is item.children or any(
                dest is g.children for g in walk(item.children) if isinstance(g, Group))):
            return
        src = self.container_of(item)
        if src is not None:
            if src is dest and index is not None and src.index(item) < index:
                index -= 1
            src.remove(item)
        dest.insert(len(dest) if index is None else index, item)

    def upload(self, frame):
        h, w = frame.shape[:2]
        if self.src_tex is None or self.src_tex.size != (w, h):
            if self.src_tex:
                self.src_tex.release()
            self.src_tex = self.ctx.texture((w, h), 3, alignment=1)
            self.src_tex.swizzle = "BGR1"  # OpenCV frames are BGR
            self.src_tex.repeat_x = self.src_tex.repeat_y = False
        self.src_tex.write(np.ascontiguousarray(frame), alignment=1)

    def upload_media(self, slot, frame):
        """New frame for an extra source (BGR, top row first); None clears the slot."""
        if frame is None:
            self.media_live[slot] = 0.0
            return
        h, w = frame.shape[:2]
        tex = self.media_tex[slot]
        if tex is None or tex.size != (w, h):
            if tex:
                tex.release()
            tex = self.media_tex[slot] = self.ctx.texture((w, h), 3, alignment=1)
            tex.swizzle = "BGR1"
            tex.repeat_x = tex.repeat_y = False
        tex.write(np.ascontiguousarray(frame), alignment=1)
        self.media_asp[slot], self.media_live[slot] = w / h, 1.0

    def upload_mask(self, mask):
        h, w = mask.shape
        if self.mask_tex is None or self.mask_tex.size != (w, h):
            if self.mask_tex:
                self.mask_tex.release()
            self.mask_tex = self.ctx.texture((w, h), 1, alignment=1)
            self.mask_tex.repeat_x = self.mask_tex.repeat_y = False
        self.mask_tex.write(np.ascontiguousarray(mask), alignment=1)

    PLATE_FRAMES = 30

    def capture_plate(self):
        """Start averaging the next PLATE_FRAMES clean frames into a new plate. A plate already captured stays
        in use (and in memory) until the new one is finished."""
        for t in self.plate_new:
            t.release()
        self.plate_new = [Target(self.ctx, *self.size, "f2") for _ in range(2)]
        self.plate_left = self.PLATE_FRAMES

    def clear_plate(self):
        for t in self.plate_acc + self.plate_new:
            t.release()
        self.plate, self.plate_acc, self.plate_new, self.plate_left, self.plate_small = None, [], [], 0, None

    def _plate_step(self):
        """One frame of plate capture (after the clean feed is drawn)."""
        n = self.PLATE_FRAMES - self.plate_left
        src, dst = self.plate_new[n % 2], self.plate_new[1 - n % 2]
        dst.fbo.use()
        src.tex.use(4)
        set_u(self.plate_prog, "u_k", 1.0 / (n + 1))
        self.plate_vao.render(vertices=3)
        self.plate_left -= 1
        if self.plate_left == 0:   # done: swap it in, then let the old plate go
            for t in self.plate_acc:
                t.release()
            self.plate_acc, self.plate_new, self.plate = self.plate_new, [], dst
            self.plate_small = self.grab_small(dst.tex).astype(np.int16)

    def plate_drift(self, mask):
        """How far the background has moved away from the plate (0 = same; ~0.1+ = camera moved or the
        lighting/exposure changed), judged on pixels the AI mask calls background."""
        cur = self.grab_small().astype(np.int16)
        h, w = cur.shape[:2]
        if self.plate_small.shape != cur.shape:   # AI Mask quality changed since the capture
            self.plate_small = cv2.resize(self.plate_small, (w, h))
        bg = cv2.resize(mask, (w, h)) < 40
        if bg.sum() < w * h * 0.1:
            return 0.0
        return float(np.median(np.abs(cur - self.plate_small).mean(axis=2)[bg])) / 255

    def resize_seg(self):
        """Small copy of the clean feed for the segmenter: seg_long px on the long side, multiples of 32."""
        if self.seg_small:
            self.seg_small.release()
        w, h = self.size
        k = self.seg_long / max(w, h)
        self.seg_small = Target(self.ctx, max(32, round(w * k / 32) * 32), max(32, round(h * k / 32) * 32))

    def refine_mask(self):
        """Low-res AI mask -> full-res edge-snapped, stabilised mask; returns the texture effects should read."""
        tex, self.ref_i, self.ref_fresh = self.refine_into(self.mask_tex, self.mask_ref, self.ref_i, self.ref_fresh)
        return tex

    def refine_into(self, raw, refs, i, fresh, guide=None):
        """The refinement for any mask: raw (low res) -> refs[1 - i], guided by the picture `guide` (default the
        clean feed, on unit 2). Returns (texture, new i, new fresh)."""
        if guide is not None:
            guide.use(2)
        W, H = self.size
        # Edge refine sets how far the filter reaches to fix the AI's edge (window radius, px at 720p)
        rad = (self.gf_rad or 8.0 + 16.0 * self.refine) * H / 720
        raw.use(0)
        (pa, va), (pb, vb) = self.gf_progs
        self.gf_ab.fbo.use()
        set_u(pa, "u_res", (W, H))
        set_u(pa, "u_rad", rad)
        set_u(pa, "u_eps", self.gf_eps)
        va.render(vertices=3)
        dst = refs[1 - i]
        dst.fbo.use()
        self.gf_ab.tex.use(5)
        refs[i].tex.use(4)
        set_u(pb, "u_res", (W, H))
        set_u(pb, "u_rad", rad)
        set_u(pb, "u_refine", min(1.0, self.refine * 1.5))
        set_u(pb, "u_stable", self.stability)
        set_u(pb, "u_first", 1.0 if fresh else 0.0)
        vb.render(vertices=3)
        if guide is not None:
            self.clean.tex.use(2)
        return dst.tex, 1 - i, False

    def grab_small(self, tex=None):
        """The current clean frame (or tex), shrunk for the segmenter, as RGB uint8 (top row first)."""
        self.seg_small.fbo.use()
        (tex or self.clean.tex).use(0)
        set_u(self.copy_prog, "u_tex", 0)
        self.copy_vao.render(vertices=3)
        w, h = self.seg_small.tex.size
        return np.frombuffer(self.seg_small.fbo.read(components=3, alignment=1), np.uint8).reshape(h, w, 3)

    def grab_slot_small(self, sm, tex):
        """Copy a source's frame into its small buffer and start reading it back (ready next frame)."""
        w, h = sm.small.tex.size
        if sm.full[1]:
            sm.ready = np.frombuffer(sm.pbo[1].read(), np.uint8).reshape(h, w, 3)
        sm.small.fbo.use()
        tex.use(0)
        set_u(self.copy_prog, "u_tex", 0)
        self.copy_vao.render(vertices=3)
        sm.small.fbo.read_into(sm.pbo[0], components=3, alignment=1)
        sm.pbo.reverse()
        sm.full = [sm.full[1], True]

    def read_out_async(self):
        """The output frame (RGB, top row first) via a two-buffer read-back: starts copying this frame and returns
        the previous one, so recording never stalls the GPU."""
        W, H = self.size
        if not getattr(self, "out_pbo", None) or self.out_pbo[0].size != W * H * 3:
            self.out_pbo, self.out_full = [self.ctx.buffer(reserve=W * H * 3) for _ in range(2)], [False, False]
        ready = np.frombuffer(self.out_pbo[1].read(), np.uint8).reshape(H, W, 3) if self.out_full[1] else None
        self.out.fbo.read_into(self.out_pbo[0], components=3, alignment=1)
        self.out_pbo.reverse()
        self.out_full = [self.out_full[1], True]
        return ready

    def grab_small_async(self):
        """Like grab_small, but without waiting for the GPU: starts copying this frame into a buffer and
        returns the copy started on the previous call (None the first time). Reading straight back stalls
        the CPU until the GPU catches up, which cost about half of every frame."""
        w, h = self.seg_small.tex.size
        size = w * h * 3
        if not self.seg_pbo or self.seg_pbo[0].size != size:
            for b in self.seg_pbo:
                b.release()
            self.seg_pbo, self.seg_pbo_full = [self.ctx.buffer(reserve=size) for _ in range(2)], [False, False]
        ready = None
        if self.seg_pbo_full[1]:
            ready = np.frombuffer(self.seg_pbo[1].read(), np.uint8).reshape(h, w, 3)
        self.seg_small.fbo.use()
        self.clean.tex.use(0)
        set_u(self.copy_prog, "u_tex", 0)
        self.copy_vao.render(vertices=3)
        self.seg_small.fbo.read_into(self.seg_pbo[0], components=3, alignment=1)
        self.seg_pbo.reverse()
        self.seg_pbo_full = [self.seg_pbo_full[1], True]
        return ready

    def render(self, t, dt, level, test_pattern):
        ctx = self.ctx
        GL.glDisable(GL.GL_SCISSOR_TEST)  # left on by the imgui renderer
        ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        W, H = self.size

        # source -> clean, cover-fitted to the output frame
        p = self.src_prog
        self.clean.fbo.use()
        use_tex = self.src_tex is not None and not test_pattern
        if use_tex:
            self.src_tex.use(0)
            sw, sh = self.src_tex.size
            sa, oa = sw / sh, W / H
            set_u(p, "u_scale", (oa / sa, 1.0) if sa > oa else (1.0, sa / oa))
        set_u(p, "u_mode", 0 if use_tex else 1)
        set_u(p, "u_res", (W, H))
        set_u(p, "u_time", t)
        self.src_vao.render(vertices=3)

        # effect chain; u_prev is last frame's output for feedback effects
        self.clean.tex.use(2)
        if self.plate_left:
            self._plate_step()
        (self.plate.tex if self.plate else self.blank).use(11)
        plate_on = 1.0 if self.plate else 0.0
        for prog, _ in self.gf_progs:
            set_u(prog, "u_plate_on", plate_on)
            set_u(prog, "u_plate_k", self.plate_strength)
        if self.mask_active:
            self.main_mask = self.refine_mask()
        else:
            self.main_mask = self.mask_tex
            self.ref_fresh = True
        self.main_mask.use(3)
        (self.fb[1 - self.fb_w].tex if self.fb_ready else self.out.tex).use(1)
        self.fb_taken = False
        for i, tex in enumerate(self.media_tex):
            (tex if tex and self.media_live[i] else self.blank).use(6 + i)
        self.audio_tex.use(9)
        # a look can bring its own transition, used only while it fades in
        style, ttime = self.transition, self.trans_secs
        if self.override and t < self.override[2]:
            style, ttime = self.override[0], self.override[1]
        cut = style == 2
        self._frame = dict(t=t, dt=dt, level=level, style=style, step=1.0 if cut else dt / max(ttime, 0.01),
                           glide=1.0 if cut else min(1.0, dt * 3 / max(ttime, 0.01)))
        og = self.outgoing
        p = min(1.0, (t - og["start"]) / max(og["dur"], 0.01)) if og else 1.0
        if og and p >= 1.0:   # crossfade finished: the old look's effects go idle
            for f in walk(og["order"]):
                f.on, f.mix, f.removing = False, 0.0, False
            for f in walk(self.order):
                f.xf_keep = False
            self.outgoing = og = None
        grow = og is not None and og["style"] == 1
        inp = self.run_chain(self.order, self.clean.tex, self.ping, ease(p) if grow else 1.0)
        self.fb_ready = self.fb_taken
        if self.fb_taken:
            self.fb_w = 1 - self.fb_w

        if og:   # look crossfade: the outgoing look still runs, and the two pictures are mixed
            old = self.run_chain(og["order"], self.clean.tex, self.ping_out, 1 - ease(p) if grow else 1.0)
            self.out.fbo.use()
            inp.use(0)
            old.use(4)
            set_u(self.mix_prog, "u_p", p)
            set_u(self.mix_prog, "u_style", og["style"])
            self.mix_vao.render(vertices=3)
            return
        self.out.fbo.use()
        inp.use(0)
        if self.alpha_out:   # Background Eraser > Transparent: the alpha travels out (Spout)
            set_u(self.alpha_prog, "u_soft", self.alpha_out[0])
            set_u(self.alpha_prog, "u_mid", self.alpha_out[1])
            self.alpha_vao.render(vertices=3)
            return
        set_u(self.copy_prog, "u_tex", 0)
        self.copy_vao.render(vertices=3)

    def crossfade_to(self, new_order, style, seconds, t):
        """Swap in a look built from the other effect set, while the current one keeps running and fades out.
        If a crossfade was still running, its outgoing look is simply dropped: its effect set is the one
        new_order was just built on, so those effects must not be touched here."""
        self.outgoing = dict(order=[f for f in self.order if not f.removing], start=t, dur=seconds, style=style)
        self.order = new_order

    def run_chain(self, items, inp, ping, scale=1.0):
        """Run a list of effects/groups over inp, ping-ponging between the two targets; returns the result.
        scale multiplies every effect's amount (look crossfades use it for Grow)."""
        W, H = self.size
        fr = self._frame
        t, dt, level = fr["t"], fr["dt"], fr["level"]
        pi = 0
        for idx, f in enumerate(list(items)):
            f.mix = min(1.0, f.mix + fr["step"]) if f.on else max(0.0, f.mix - fr["step"])
            f.amt_smooth += (f.amt - f.amt_smooth) * fr["glide"]
            if f.mix <= 0:
                f.live = 0.0
                if f.removing:  # finished fading out
                    f.removing = False
                    items.remove(f)
                continue
            fade = ease(f.mix)
            if f.keep_out and items is self.order and not self.fb_taken:
                # feedback (Trails "Final output") gets the picture as it is before this effect
                self.fb[self.fb_w].fbo.use()
                inp.use(0)
                set_u(self.copy_prog, "u_tex", 0)
                self.copy_vao.render(vertices=3)
                self.fb_taken = True
            if isinstance(f, Group):
                if not f.ping:
                    self.alloc_group(f)
                f.live = fade
                if f.source >= 0:   # start from that source alone, stretched to the frame
                    slot = f.source
                    live = self.media_live[slot] and self.media_tex[slot] is not None
                    f.src.fbo.use()
                    (self.media_tex[slot] if live else self.blank).use(0)
                    set_u(self.copy_prog, "u_tex", 0)
                    self.copy_vao.render(vertices=3)
                    sm = self.slot_masks[slot]
                    if sm and sm.active:   # this source's own person mask, for its group's effects and Cut out
                        sm.tex, sm.i, sm.fresh = self.refine_into(sm.raw, sm.refs, sm.i, sm.fresh, f.src.tex)
                        self.grab_slot_small(sm, f.src.tex)
                        sm.tex.use(3)
                    res = self.run_chain(f.children, f.src.tex, f.ping, scale)
                    self.main_mask.use(3)
                    prog, vao = self.place_prog, self.place_vao
                    cut = bool(f.cutout and sm and sm.active and sm.tex)
                    (sm.tex if cut else self.blank).use(12)
                    set_u(prog, "u_cut_on", 1.0 if cut else 0.0)
                    set_u(prog, "u_res", (W, H))
                    set_u(prog, "u_amt", f.size)
                    set_u(prog, "u_centre", tuple(f.centre))
                    set_u(prog, "u_p0", f.rotate)
                    set_u(prog, "u_p1", f.rounded)
                    set_u(prog, "u_p2", f.border)
                    set_u(prog, "u_opt1", f.fit)
                    set_u(prog, "u_masp", (self.media_asp[slot],) * 3)
                    set_u(prog, "u_mlive", (1.0 if live else 0.0,) * 3)
                else:
                    res = self.run_chain(f.children, inp, f.ping, scale)
                    prog, vao = self.group_prog, self.group_vao
                ping[pi].fbo.use()
                inp.use(0)
                res.use(4)
                set_u(prog, "u_mix", fade * f.opacity)
                set_u(prog, "u_blend", f.blend)
                set_u(prog, "u_tw", glide_target(f, dt, self.trans_secs))
                vao.render(vertices=3)
                inp, pi = ping[pi].tex, pi ^ 1
                continue
            lv = self.level_of(f, t) if self.level_of and f.mod == MOD_AUDIO else level
            if f.mod == MOD_AUDIO:
                k = min(1.6, 0.1 + lv * 1.2)
            elif f.mod == MOD_WAVE:  # phase offset per slot so waves don't all move together
                k = 0.1 + 0.9 * (0.5 + 0.5 * np.sin(2 * np.pi * self.wave_rate * t + idx * 1.7))
            else:
                k = 1.0
            # Grow ramps effects between looks, but one both looks share stays at full strength in each,
            # else the plain feed shows through the middle of the transition
            f.live = f.amt_smooth * k * (fade if fr["style"] == 1 else 1.0) * (1.0 if f.xf_keep else scale)
            f.clock += dt * f.speed
            inp.use(0)
            if f.state_passes:
                new = 1 - f.parity
                for s, (sprog, svao) in enumerate(f.state_passes):
                    for j, pair in enumerate(f.state):
                        pair[new if j < s else f.parity].tex.use(4 + j)
                    f.state[s][new].fbo.use()
                    f.apply_uniforms(sprog, (W, H), dt, lv, self.beat)
                    svao.render(vertices=3)
                f.parity = new
                for j, pair in enumerate(f.state):
                    pair[f.parity].tex.use(4 + j)
            ping[pi].fbo.use()
            f.apply_uniforms(f.prog, (W, H), dt, lv, self.beat)
            set_u(f.prog, "u_masp", tuple(self.media_asp))
            set_u(f.prog, "u_mlive", tuple(self.media_live))
            set_u(f.prog, "u_plate_on", 1.0 if self.plate else 0.0)
            set_u(f.prog, "u_mix", fade * f.opacity)
            set_u(f.prog, "u_blend", f.blend)
            # eraser/tracers work from the mask themselves; limiting them to subject/background would hide them
            set_u(f.prog, "u_tw", glide_target(f, dt, self.trans_secs))
            f.vao.render(vertices=3)
            if f.points:
                self.run_points(f, ping[pi].fbo, (W, H), dt, level, fade * f.opacity)
            inp, pi = ping[pi].tex, pi ^ 1
        return inp

    def run_points(self, f, target, size, dt, level, mix):
        """Move an effect's point particles (its state 0 is the velocity field), then add them as glowing
        points onto target, which already holds the effect's picture."""
        pts = f.points
        old, new = pts["pos"][pts["cur"]], pts["pos"][1 - pts["cur"]]
        prog, vao = pts["update"]
        old.tex.use(10)
        new.fbo.use()
        f.apply_uniforms(prog, size, dt, level, self.beat)
        vao.render(vertices=3)
        pts["cur"] = 1 - pts["cur"]
        target.use()
        new.tex.use(10)
        prog, vao = pts["draw"]
        f.apply_uniforms(prog, size, dt, level, self.beat)
        set_u(prog, "u_mix", mix)
        set_u(prog, "u_tw", tuple(f.tw))
        self.ctx.enable(moderngl.BLEND | moderngl.PROGRAM_POINT_SIZE)
        self.ctx.blend_func = moderngl.ONE, moderngl.ONE
        vao.render(mode=moderngl.POINTS, vertices=pts["n"] * pts["n"])
        self.ctx.disable(moderngl.BLEND | moderngl.PROGRAM_POINT_SIZE)

    def read_rgb(self):
        W, H = self.size
        data = self.out.fbo.read(components=3, alignment=1)
        return np.frombuffer(data, np.uint8).reshape(H, W, 3)


# ---------------------------------------------------------------- outputs

class OutputWindow:
    """Borderless-capable window showing only the processed video. OBS: Window Capture -> 'Lumoria Output'."""

    def __init__(self, share):
        glfw.window_hint(glfw.AUTO_ICONIFY, False)  # stay up when fullscreen loses focus
        self.win = glfw.create_window(960, 540, "Lumoria Output", None, share)
        glfw.make_context_current(self.win)
        glfw.swap_interval(0)  # the control window already syncs to vblank
        self.ctx = moderngl.create_context()
        self.prog = self.ctx.program(vertex_shader=E.VERT, fragment_shader=E.HEAD + E.BLIT)
        set_u(self.prog, "u_tex", 0)
        self.vao = self.ctx.vertex_array(self.prog, [])
        self.tex, self.tex_key = None, None
        self.visible, self.saved = True, None
        self._last_click = 0.0
        glfw.set_window_close_callback(self.win, self._on_close)
        glfw.set_key_callback(self.win, self._on_key)
        glfw.set_mouse_button_callback(self.win, self._on_click)

    def _on_close(self, win):
        glfw.set_window_should_close(win, False)
        self.set_visible(False)

    def _on_key(self, win, key, _sc, action, _mods):
        if action == glfw.PRESS and key in (glfw.KEY_F11, glfw.KEY_F, glfw.KEY_ENTER):
            self.toggle_fullscreen()
        elif action == glfw.PRESS and key == glfw.KEY_ESCAPE and glfw.get_window_monitor(win):
            self.toggle_fullscreen()

    def _on_click(self, win, button, action, _mods):
        if button == glfw.MOUSE_BUTTON_LEFT and action == glfw.PRESS:
            now = glfw.get_time()
            if now - self._last_click < 0.35:
                self.toggle_fullscreen()
            self._last_click = now

    def set_visible(self, v):
        self.visible = v
        (glfw.show_window if v else glfw.hide_window)(self.win)

    def _monitor_under_window(self):
        x, y = glfw.get_window_pos(self.win)
        w, h = glfw.get_window_size(self.win)
        cx, cy = x + w // 2, y + h // 2
        for m in glfw.get_monitors():
            mx, my = glfw.get_monitor_pos(m)
            mode = glfw.get_video_mode(m)
            if mx <= cx < mx + mode.size.width and my <= cy < my + mode.size.height:
                return m
        return glfw.get_primary_monitor()

    def toggle_fullscreen(self):
        if glfw.get_window_monitor(self.win):
            glfw.set_window_monitor(self.win, None, *self.saved, 0)
        else:
            self.saved = (*glfw.get_window_pos(self.win), *glfw.get_window_size(self.win))
            m = self._monitor_under_window()
            mode = glfw.get_video_mode(m)
            glfw.set_window_monitor(self.win, m, 0, 0, mode.size.width, mode.size.height, mode.refresh_rate)

    def draw(self, tex):
        if not self.visible:
            return
        glfw.make_context_current(self.win)
        key = (tex.glo, tex.size)
        if key != self.tex_key:
            self.tex = self.ctx.external_texture(tex.glo, tex.size, 4, 0, "f1")
            self.tex_key = key
        fw, fh = glfw.get_framebuffer_size(self.win)
        if fw and fh:
            self.ctx.screen.use()
            self.ctx.clear(0, 0, 0, 1)
            tw, th = tex.size
            k = min(fw / tw, fh / th)
            vw, vh = int(tw * k), int(th * k)
            self.ctx.viewport = ((fw - vw) // 2, (fh - vh) // 2, vw, vh)
            self.tex.use(0)
            self.vao.render(vertices=3)
            glfw.swap_buffers(self.win)


class VirtualCam:
    """Publishes frames to the OBS Virtual Camera device (vcam.py) from a worker thread."""

    def __init__(self, w, h):
        import vcam
        self.cam = vcam.VirtualCamera(w, h, VCAM_FPS)
        self.q = queue.Queue(maxsize=1)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while (frame := self.q.get()) is not None:
            self.cam.send(frame)

    def send(self, frame):
        try:
            self.q.get_nowait()  # drop a stale frame rather than lag
        except queue.Empty:
            pass
        self.q.put(frame)

    def close(self):
        self.send(None)
        self.thread.join(timeout=2)
        self.cam.close()


# ---------------------------------------------------------------- app + UI

def copy_autos(autos):
    """A copy of an effect's automations that shares no lists (the frequency range, the response times)."""
    return {k: {kk: (list(v) if isinstance(v, list) else v) for kk, v in a.items()} for k, a in autos.items()}


class App:
    def __init__(self, ctx, out_win):
        self.pipe = Pipeline(ctx)
        self.pipe.level_of = self.effect_level
        self.auto_state = {}   # (effect uid, setting) -> [smoothed level, last time]: audio-driven sliders' own meters
        self.auto_live = {}    # (effect uid, setting) -> (what it hears, what it drives 0..1), for the menu's meters
        self.out_win = out_win
        self.audio = AudioAnalyzer()
        self.cameras = list_cameras()
        self.audio_devs = list_inputs()
        self.source, self.source_label = None, "Test pattern"
        self.source_desc = {"kind": "test"}
        # Sources 2-4, shown by Media Layer effects
        self.extra, self.extra_desc = [None] * 3, [{"kind": "none"} for _ in range(3)]
        self.screens = list_screens()
        self.windows, self.windows_t = [], 0.0   # open windows, refreshed while the source menu is open
        self.cropping = None   # while choosing a crop: dict(target, rect, before, drag)
        self.flip_preview, self.band, self.gain = False, "bass", 1.0
        self.res_idx = 0
        self.vcam, self.vcam_last = None, 0.0
        self.recorder = recorder.Recorder()
        self.rec_folder = os.path.join(os.path.expanduser("~"), "Videos", "Lumoria")
        self.rec_format, self.rec_fps, self.rec_sound = 0, 60, True
        self.spout = None   # Spout sender while on (spout.SpoutSender)
        self.file_dialog = None   # (target: "main" or slot 0-2, kind "video"/"image", dialog)
        self.share_dialog = None  # ("export"/"import", dialog, details) while a look/playlist file dialog is open
        self.thumb_tried, self.preset_t = set(), 0.0   # looks thumbnailed this run; when the current look was fired
        self.msg, self.msg_until = "", 0.0
        self.playlist = self.load_playlist()   # saved looks, in show order
        self.current_preset = None
        self.frames, self.fps, self.fps_t = 0, 0, 0.0
        self.last_t = None
        # auto-play: change the look every N seconds or N beats
        self.auto_mode, self.auto_every, self.auto_unit = AUTO_OFF, 8, 0   # unit: 0 = seconds, 1 = beats
        self.auto_kind_last = AUTO_PLAYLIST   # what MIDI play/pause starts (the UI keeps it up to date)
        self.auto_progress = 0.0
        self.beat_armed, self.beat_until = True, 0.0
        self.tempo = tempo.Tempo()   # the beat clock (tempo.py): beat effects, auto-play, look timing in beats/bars
        self.quantize = 0            # launching a look: 0 at once, 1 on the next beat, 2 on the next bar
        self.pending_look = None     # (name, beat it starts on) while a quantized launch waits
        self.picking, self.pick_dragging = None, False   # effect whose centre is being placed on the preview
        self.segmenter, self.seg_error_shown = None, False  # AI person mask, started on first use
        self.mask_quality = 1   # index into segment.QUALITY
        # Capture background: a countdown so you can step out, then the plate is averaged (see Pipeline)
        self.plate_at, self.plate_busy, self.plate_delay = None, False, 5.0
        self.plate_drift, self.plate_check_t, self.last_mask = 0.0, 0.0, None
        self.slot_segs = [None] * 3   # AI segmenters for Sources 2-4 (see update_source_masks)
        # MIDI: every input port is opened; mappings link a knob/fader/pad to a control (see midi_control)
        self.midi = midi.MidiIn()
        try:
            self.midi.open_all()
        except Exception as e:   # no MIDI system: the rest of the app doesn't need it
            print(f"[Lumoria] MIDI unavailable: {e}", flush=True)
        self.midi_map = self.load_midi_map()   # [{"src": [kind, channel, number], "target": [scope, key]}]
        self.midi_learn, self.learn_target, self.midi_seen, self.midi_cc = False, None, 0.0, {}
        # notice when Lumoria's own code changes on disk, so a stale copy doesn't keep running
        self.code_stamp, self.code_check_t = code_stamp(), 0.0
        self.update_ready, self.restart_requested = False, False
        self.session_text, self.session_t = "", 0.0
        # a marker file that exists only while Lumoria runs: still there at start = it didn't close properly
        self.unclean = os.path.exists(RUNNING_FILE)
        self.crash_note = self.last_crash() if self.unclean else ""
        self.held_session = None   # the last setup, waiting for "Restore?" after an unexpected close
        try:
            with open(RUNNING_FILE, "w") as fh:
                fh.write(str(os.getpid()))
        except OSError:
            pass
        self.restore_session()
        # undo: snapshots of the effect chain (see track_undo)
        self.undo_stack, self.redo_stack = [], []
        self.undo_committed = self.undo_pending = self.chain_state()
        self.undo_t = self.undo_pending_t = 0.0

    # --- actions
    def flash(self, msg, secs=5):
        self.msg, self.msg_until = msg, glfw.get_time() + secs

    def choose_source(self, target, desc):
        """Switch the main source (target "main") or Source 2-4 (target 0-2) to a description."""
        if self.cropping and self.cropping["target"] == target:
            self.cropping = None
        if target == "main":
            self.source_desc = desc
            self.set_source(open_source(desc, self.cameras), describe(desc))
            self.flip_preview = desc.get("kind") == "camera"
        else:
            if self.extra[target]:
                self.extra[target].close()
            self.extra_desc[target] = desc
            self.extra[target] = open_source(desc, self.cameras) if desc.get("kind") != "test" else None
            self.pipe.upload_media(target, None)

    def source_of(self, target):
        return (self.source, self.source_desc) if target == "main" else (self.extra[target], self.extra_desc[target])

    def media_slots_used(self):
        """Which of Sources 2-4 a Media Layer in the chain is showing."""
        return ({f.opts[0] for f in walk(self.pipe.order)
                 if not isinstance(f, Group) and f.id.startswith("media_") and not f.removing and f.on}
                | {g.source for g in walk(self.pipe.order)
                   if isinstance(g, Group) and g.source >= 0 and not g.removing and g.on})

    def refresh_windows(self, t):
        if t - self.windows_t > 1.0:
            self.windows, self.windows_t = list_windows(), t

    # --- crop: the source shows uncropped on the preview while a box is dragged over it
    def start_crop(self, target):
        src, desc = self.source_of(target)
        if src is None:
            return
        before = desc.get("crop")
        self.cropping = dict(target=target, rect=list(before or (0.0, 0.0, 1.0, 1.0)), before=before, drag=None)
        src.set_crop(None)

    def finish_crop(self, apply):
        c, self.cropping = self.cropping, None
        src, desc = self.source_of(c["target"])
        if apply:
            x0, y0, x1, y1 = c["rect"]
            full = x1 - x0 > 0.99 and y1 - y0 > 0.99
            desc.pop("crop", None) if full else desc.update(crop=[round(v, 4) for v in c["rect"]])
        if src is not None:
            src.set_crop(desc.get("crop"))
        if c["target"] == "main":
            self.source_label = describe(desc)

    # --- sharing: looks and whole playlists as files (each look with its transition and timing)
    LOOK_EXT, PLAYLIST_EXT = ".lumoria-look", ".lumoria-playlist"

    def look_package(self, name):
        with open(os.path.join(PRESET_DIR, name + ".json")) as fh:
            pkg = dict(name=name, look=json.load(fh), meta=self.look_meta.get(name, {}))
        try:
            with open(self.thumb_path(name), "rb") as fh:
                pkg["thumb"] = base64.b64encode(fh.read()).decode("ascii")
        except OSError:
            pass
        return pkg

    def export_looks(self, path, names=None):
        """Write one look (names = [one]) or the whole playlist (names None) to a file; returns how many."""
        names = list(self.playlist) if names is None else names
        looks = [self.look_package(n) for n in names
                 if os.path.exists(os.path.join(PRESET_DIR, n + ".json"))]
        if names is not None and len(names) == 1 and looks:
            data = dict(lumoria="look", version=1, **looks[0])
        else:
            data = dict(lumoria="playlist", version=1, looks=looks)
        with open(path, "w", encoding="utf8") as fh:
            json.dump(data, fh, indent=1)
        return len(looks)

    def import_looks(self, path):
        """Add the look(s) in a .lumoria-look / .lumoria-playlist file to the end of the playlist. Names that are
        already taken get a number, so nothing of yours is overwritten. Returns the names added."""
        with open(path, encoding="utf8") as fh:
            data = json.load(fh)
        if data.get("lumoria") == "look":
            looks = [data]
        elif data.get("lumoria") == "playlist":
            looks = data.get("looks", [])
        elif "effects" in data:   # a bare look file from a presets folder
            looks = [dict(name=os.path.splitext(os.path.basename(path))[0], look=data, meta={})]
        else:
            raise ValueError("not a Lumoria look or playlist file")
        added = []
        for pkg in looks:
            look = pkg.get("look")
            if not isinstance(look, dict) or "effects" not in look:
                continue
            base = "".join(c for c in str(pkg.get("name", "Look")) if c.isalnum() or c in " -_").strip() or "Look"
            name, k = base, 2
            while os.path.exists(os.path.join(PRESET_DIR, name + ".json")) or name in added:
                name, k = f"{base} ({k})", k + 1
            with open(os.path.join(PRESET_DIR, name + ".json"), "w") as fh:
                json.dump(look, fh, indent=1)
            if pkg.get("thumb"):
                try:
                    with open(self.thumb_path(name), "wb") as fh:
                        fh.write(base64.b64decode(pkg["thumb"]))
                except (OSError, ValueError):
                    pass
            self.playlist.append(name)
            if pkg.get("meta"):
                self.look_meta[name] = {**self.meta(name), **pkg["meta"]}
            added.append(name)
        self.save_playlist()
        return added

    # sample looks shipped with Lumoria (samples/: look + thumbnail), in the order they're offered
    SAMPLES = ["Neon Lines", "Kaleido Dream", "Warp Speed", "Comic Book", "Matrix", "Old Film", "Ember Storm",
               "Glitch VHS"]

    def samples_missing(self):
        return [n for n in self.SAMPLES if n not in self.playlist
                and os.path.exists(os.path.join(HERE, "samples", n + ".json"))]

    def add_samples(self):
        """Add the sample looks that aren't in the playlist yet (with their thumbnails); returns how many."""
        added = self.samples_missing()
        for name in added:
            for ext in (".json", ".png"):
                src = os.path.join(HERE, "samples", name + ext)
                if os.path.exists(src):
                    shutil.copyfile(src, os.path.join(PRESET_DIR, name + ext))
            self.playlist.append(name)
        if added:
            self.save_playlist()
        return len(added)

    def ask_export(self, names=None):
        """Save dialog for one look (names = [it]) or the playlist (None); the answer is handled in process."""
        one = names is not None and len(names) == 1
        ext = self.LOOK_EXT if one else self.PLAYLIST_EXT
        default = os.path.join(os.path.expanduser("~"), "Documents", (names[0] if one else "Lumoria playlist") + ext)
        kind = "Lumoria look" if one else "Lumoria playlist"
        self.share_dialog = ("export", pfd.save_file(f"Export {'look' if one else 'playlist'}", default,
                                                     [kind, "*" + ext]), (names, ext))

    def ask_import(self):
        self.share_dialog = ("import", pfd.open_file(
            "Import looks or a playlist", os.path.join(os.path.expanduser("~"), "Documents"),
            ["Lumoria looks and playlists", f"*{self.LOOK_EXT} *{self.PLAYLIST_EXT}", "All files", "*"],
            pfd.opt.multiselect), None)

    def finish_share_dialog(self):
        if not (self.share_dialog and self.share_dialog[1].ready()):
            return
        (action, dialog, extra), self.share_dialog = self.share_dialog, None
        result = dialog.result()
        try:
            if action == "export" and result:
                names, ext = extra
                path = result if result.lower().endswith(ext) else result + ext
                n = self.export_looks(path, names)
                self.flash(f"Exported {n} look{'s' if n != 1 else ''} to {os.path.basename(path)}", 4)
            elif action == "import" and result:
                added = [n for path in result for n in self.import_looks(path)]
                self.flash(f"Imported {len(added)} look{'s' if len(added) != 1 else ''}" +
                           (f": {', '.join(added[:4])}{'...' if len(added) > 4 else ''}" if added else ""), 5)
        except (OSError, ValueError) as e:
            self.flash(f"{'Export' if action == 'export' else 'Import'} failed: {e}", 6)

    def pick_file(self, target, kind):
        filters = (["Video", "*.mp4 *.mov *.mkv *.avi *.webm *.wmv *.m4v", "All files", "*"] if kind == "video"
                   else ["Image", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff", "All files", "*"])
        self.file_dialog = (target, kind, pfd.open_file(f"Choose {'a video' if kind == 'video' else 'an image'}",
                                                        os.path.expanduser("~") if FROZEN else HERE, filters))

    def set_source(self, src, label):
        if self.source:
            self.source.close()
        self.source, self.source_label = src, label
        if self.segmenter:
            self.segmenter.reset()

    def set_resolution(self, idx):
        self.res_idx = idx
        _, w, h = RESOLUTIONS[idx]
        self.pipe.resize(w, h)
        if self.vcam:  # virtual camera size is fixed at start, so restart it
            self.toggle_vcam()
            self.toggle_vcam()

    def toggle_spout(self, on=None):
        """Start or stop the Spout sender "Lumoria" (OBS with the Spout2 plugin, Resolume, TouchDesigner...)."""
        on = self.spout is None if on is None else on
        if not on and self.spout:
            self.spout.close()
            self.spout = None
        elif on and self.spout is None:
            try:
                import spout
                self.spout = spout.SpoutSender("Lumoria")
            except Exception as e:
                self.flash(f"Spout failed: {e}", 8)

    def toggle_record(self):
        """Start or stop recording the output to a video file (Settings > Output: folder, format, rate)."""
        rec = self.recorder
        if rec.recording:
            self.audio.tap = None
            path = rec.stop()
            self.flash(f"Saved {os.path.basename(path)} ({rec.seconds():.0f} s)"
                       + (f", {rec.dropped} frames skipped" if rec.dropped > 10 else ""), 5)
            return
        self.pipe.out_full = [False, False]   # nothing left over from the last recording
        sound = (self.audio.rate, self.audio.channels) if self.rec_sound and self.audio.stream else None
        rec.start(self.rec_folder, self.pipe.size, self.rec_fps, self.rec_format, sound)
        self.audio.tap = rec.push_sound if sound else None
        note = "" if sound or not self.rec_sound else " (no sound: pick an audio input under Audio)"
        self.flash(f"Recording to {os.path.basename(rec.path)}{note}", 4 if note else 2)

    def toggle_vcam(self):
        if self.vcam:
            self.vcam.close()
            self.vcam = None
            return
        try:
            self.vcam = VirtualCam(*self.pipe.size)
        except Exception as e:
            self.flash(f"Virtual camera failed: {e}\n(Stop OBS's own 'Start Virtual Camera' first.)", 8)

    # --- effect chain
    def add_effect(self, f, into=None):
        """Add (or re-enable) an effect at the end of a chain: the top level, or a group's children."""
        dest = self.pipe.order if into is None else into
        if self.pipe.container_of(f) is not dest:
            if self.pipe.container_of(f) is None:
                f.mix = 0.0
            # the eraser sets the stage (new background), so everything else should run after it
            self.pipe.move_item(f, dest, 0 if f.place_first else None)
        f.on, f.removing = True, False

    # --- unexpected closes
    def last_crash(self):
        """The last error in crash.log, if it was written during the run that didn't close properly."""
        path = os.path.join(DATA, "crash.log")
        try:
            if os.path.getmtime(path) < os.path.getmtime(RUNNING_FILE):
                return ""
            with open(path, encoding="utf8") as fh:
                lines = [l.strip() for l in fh if l.strip()]
            return lines[-1][:160] if lines else ""
        except OSError:
            return ""

    def answer_restore(self, restore):
        """The user's answer to "restore the last setup?" after an unexpected close."""
        data, self.held_session = self.held_session, None
        if restore and data:
            self.apply_look(data)
        self.unclean = False

    def clean_exit(self):
        try:
            os.remove(RUNNING_FILE)
        except OSError:
            pass

    # --- undo / redo: the effect chain (effects, groups, every setting), snapshotted once a change settles
    UNDO_STEPS = 100

    def chain_state(self):
        def strip(e):   # opening/closing a card isn't worth an undo step
            e = {k: v for k, v in e.items() if k != "expanded"}
            if "children" in e:
                e["children"] = [strip(c) for c in e["children"]]
            return e
        return json.dumps([strip(self.item_to_dict(f)) for f in self.pipe.order if not f.removing], sort_keys=True)

    def track_undo(self, t, force=False):
        """Record a step once the chain has stopped changing for half a second (a knob turned, a slider dragged
        or a look loaded is one step, not hundreds). force: record any change right now."""
        if not force and t - self.undo_t < 0.25:
            return
        self.undo_t = t
        cur = self.chain_state()
        if cur != self.undo_pending:
            self.undo_pending, self.undo_pending_t = cur, t
            if not force:
                return
        if cur != self.undo_committed and (force or t - self.undo_pending_t >= 0.5):
            self.undo_stack = (self.undo_stack + [self.undo_committed])[-self.UNDO_STEPS:]
            self.redo_stack.clear()
            self.undo_committed = cur

    def undo(self, redo=False):
        self.track_undo(glfw.get_time(), force=True)
        src, dst = (self.redo_stack, self.undo_stack) if redo else (self.undo_stack, self.redo_stack)
        if not src:
            self.flash("Nothing to redo" if redo else "Nothing to undo", 1.5)
            return
        dst.append(self.undo_committed)
        state = src.pop()
        self.apply_look(dict(version=2, effects=json.loads(state)))
        for g in walk(self.pipe.order):   # rebuilt groups shouldn't fade in again
            if isinstance(g, Group) and g.on:
                g.mix = 1.0
        self.undo_committed = self.undo_pending = state
        self.current_preset = None
        self.flash(("Redo" if redo else "Undo") + f"  ({len(self.undo_stack)} back, {len(self.redo_stack)} forward)", 1.2)

    # --- MIDI
    def load_midi_map(self):
        try:
            with open(MIDI_FILE) as fh:
                return [m for m in json.load(fh) if len(m.get("src", [])) == 3 and len(m.get("target", [])) == 2]
        except (OSError, ValueError, AttributeError):
            return []

    def save_midi_map(self):
        try:
            with open(MIDI_FILE, "w") as fh:
                json.dump(self.midi_map, fh, indent=1)
        except OSError:
            pass

    def midi_binding(self, target):
        """The MIDI source linked to a control, or None."""
        return next((m["src"] for m in self.midi_map if m["target"] == list(target)), None)

    @staticmethod
    def midi_name(src):
        kind, ch, num = src
        return f"{'CC' if kind == 'cc' else 'Note'} {num}" + (f" ch{ch}" if ch != 1 else "")

    def midi_control(self, target):
        """What a mappable control is: (kind, lo, hi, get, set or fire, label), or None if it doesn't exist.
        target = (scope, key): an effect id ("edges", "edges#2") with amt / opacity / speed / p<i> / opt<i> /
        on; "app" with gain / ttime / wave / prev / next / play / random / clear; or "look" with a look's name."""
        scope, key = target
        p = self.pipe
        if scope == "look":
            return ("trigger", 0, 1, None, lambda: self.load_preset(key), f"Look '{key}'") \
                if key in self.playlist else None
        if scope == "app":
            def play():
                self.auto_progress = 0.0
                self.auto_mode = AUTO_OFF if self.auto_mode else (self.auto_kind_last or AUTO_PLAYLIST)
            return {
                "gain": ("range", 0.2, 3.0, lambda: self.gain, lambda v: setattr(self, "gain", v), "Audio sensitivity"),
                "ttime": ("range", 0.1, 5.0, lambda: p.trans_time, lambda v: setattr(p, "trans_time", v),
                          "Transition time"),
                "wave": ("range", 0.02, 2.0, lambda: p.wave_rate, lambda v: setattr(p, "wave_rate", v), "Wave speed"),
                "prev": ("trigger", 0, 1, None, lambda: self.playlist_step(-1), "Previous look"),
                "next": ("trigger", 0, 1, None, lambda: self.playlist_step(1), "Next look"),
                "play": ("trigger", 0, 1, None, play, "Play / pause"),
                "random": ("trigger", 0, 1, None, self.randomize, "Random look"),
                "clear": ("trigger", 0, 1, None, self.clear, "Clear all effects"),
                "tap": ("trigger", 0, 1, None, lambda: self.tempo.tap(glfw.get_time()), "Tap tempo"),
                "record": ("trigger", 0, 1, None, self.toggle_record, "Record on / off"),
                "resync": ("trigger", 0, 1, None, self.tempo.resync_bar, "Beat 1 (re-sync bar)"),
            }.get(key)
        f = next((f for f in p.effects if f.id == scope), None)
        if f is None:
            return None
        def attr(name, lo, hi, label):
            return ("range", lo, hi, lambda: getattr(f, name), lambda v: setattr(f, name, v), f"{f.name} · {label}")
        if key == "amt":
            return attr("amt", 0.0, 1.0, f.amt_label or "Amount")
        if key == "opacity":
            return attr("opacity", 0.0, 1.0, "Opacity")
        if key == "speed":
            return attr("speed", -3.0, 3.0, "Speed")
        if key == "on":
            return ("toggle", 0, 1, lambda: f.on, lambda v: setattr(f, "on", v), f"{f.name} · On/off")
        if key[:1] == "p" and key[1:].isdigit() and int(key[1:]) < len(f.params):
            j = int(key[1:])
            name, _d, lo, hi, _fmt = f.params[j]
            return ("range", lo, hi, lambda: f.pvals[j], lambda v: f.pvals.__setitem__(j, v), f"{f.name} · {name}")
        if key[:3] == "opt" and key[3:].isdigit() and int(key[3:]) < len(f.options):
            j = int(key[3:])
            name, choices, _d = f.options[j]
            return ("index", 0, len(choices) - 1, lambda: f.opts[j], lambda v: f.opts.__setitem__(j, v),
                    f"{f.name} · {name}")
        return None

    def handle_midi(self, msg, t):
        kind, ch, num, val = msg
        if kind in ("clock", "start", "continue", "stop"):   # a DAW's tempo (see tempo.py)
            if kind == "clock":
                self.tempo.midi_clock(val, t)
            elif kind == "start":
                self.tempo.midi_start()
            elif kind == "continue":
                self.tempo.clock_running = True
            else:
                self.tempo.midi_stop()
            return
        src = [kind, ch, num]
        self.midi_seen = t
        prev = self.midi_cc.get(tuple(src), 0)
        self.midi_cc[tuple(src)] = val
        if self.midi_learn:
            if self.learn_target is not None and (kind == "cc" or val > 0):
                target = list(self.learn_target)
                self.midi_map = [m for m in self.midi_map if m["src"] != src and m["target"] != target]
                self.midi_map.append(dict(src=src, target=target))
                self.save_midi_map()
                c = self.midi_control(self.learn_target)
                self.flash(f"MIDI: {self.midi_name(src)}  ->  {c[5] if c else target}", 3)
                self.learn_target = None
            return
        for m in self.midi_map:
            if m["src"] != src or (c := self.midi_control(tuple(m["target"]))) is None:
                continue
            ctl, lo, hi, get, put, _label = c
            pressed = val > 0 if kind == "note" else (prev < 64 <= val)
            if ctl == "range":
                if kind == "cc":
                    put(lo + (hi - lo) * val / 127)
                elif val > 0:
                    put(lo + (hi - lo) * val / 127)   # pads: velocity sets the value
            elif ctl == "index":
                if kind == "cc":
                    put(min(hi, val * (hi + 1) // 128))
                elif val > 0:
                    put((get() + 1) % (hi + 1))      # pads step through the choices
            elif ctl == "toggle":
                if kind == "cc":
                    put(val >= 64)
                elif val > 0:
                    put(not get())
            elif ctl == "trigger" and pressed:
                put()
            if m["target"][0] not in ("app", "look"):
                self.current_preset = None

    def covers(self, f):
        """How f hides the picture coming into it: "redraws" (see effects.REDRAWS), "covers" (a full-frame
        Media Layer), "smears" (strong Trails: mostly its own memory, so brief things fade into it) or None."""
        if isinstance(f, Group) or not f.on or f.removing:
            return None
        if f.kind == "trails" and f.opts[0] == 0 and f.amt >= 0.8 and f.opacity >= 0.95:
            return "smears"
        if f.opacity < 0.95 or f.blend or f.target or f.mod:   # partial, blended or limited: others still show
            return None
        r = E.REDRAWS.get(f.kind)
        if r and f.opts[r[0]] in r[1] and (not r[2] or f.amt >= 0.9):
            return "redraws"
        if f.kind.startswith("media_") and f.opts[1] == 0 and f.amt >= 0.99:
            return "covers"
        return None

    def covered_by(self, item, container):
        """The first effect after item in its list that hides it (see covers), or None."""
        for later in container[container.index(item) + 1:]:
            if self.covers(later):
                return later
        return None

    def duplicate_effect(self, f):
        """An independent copy of f, with the same settings, placed right after it."""
        c = self.pipe.new_copy(self.pipe.lib_i, f.kind)
        c.copy_settings(f)
        dest = self.pipe.container_of(f)
        dest.insert(dest.index(f) + 1, c)
        c.on, c.mix, c.removing = True, 0.0, False
        self.current_preset = None
        return c

    def new_group(self, into=None):
        g = Group()
        (self.pipe.order if into is None else into).append(g)
        self.pipe.alloc_group(g)
        return g

    def remove_effect(self, f):
        f.on, f.removing = False, True   # the pipeline drops it once faded out
        if self.picking is f:
            self.picking = None

    def randomize(self):
        picks = random.sample([f for f in self.pipe.effects if f.copy_no == 1], random.randint(2, 4))
        for f in self.pipe.order:
            if f not in picks:
                self.remove_effect(f)
        for f in picks:
            f.amt = random.uniform(.2, .9)
            f.mod = random.choice((MOD_OFF, MOD_AUDIO, MOD_WAVE))
            self.add_effect(f)
        self.current_preset = None

    def clear(self):
        for f in self.pipe.order:
            self.remove_effect(f)
        self.current_preset = None

    # --- looks: the chain as JSON
    def item_to_dict(self, f):
        if isinstance(f, Group):
            return dict(group=True, name=f.name, on=f.on, opacity=f.opacity, blend=f.blend, target=f.target,
                        expanded=f.expanded, source=f.source, size=f.size, centre=f.centre, fit=f.fit,
                        rotate=f.rotate, rounded=f.rounded, border=f.border, cutout=f.cutout,
                        children=[self.item_to_dict(c) for c in f.children if not c.removing])
        return dict(id=f.id, on=f.on, amt=f.amt, mod=f.mod, opacity=f.opacity, blend=f.blend,
                    centre=f.centre, opts=f.opts, params=f.pvals, speed=f.speed,
                    target=f.target, expanded=f.expanded, colours=f.colours, keep_out=f.keep_out, autos=f.autos,
                    listen=f.listen, rng=f.rng, resp=f.resp)

    def item_from_dict(self, e, by_id, used):
        """Build a chain item from a look; effects are reused objects (one of each exists)."""
        if e.get("group"):
            g = Group(e.get("name"))
            g.on, g.opacity, g.blend = e.get("on", True), e.get("opacity", 1.0), e.get("blend", 0)
            g.target, g.expanded = e.get("target", 0), e.get("expanded", True)
            g.tw = target_weights(g.target)
            g.source, g.size, g.fit = e.get("source", -1), e.get("size", 0.6), e.get("fit", 1)
            g.centre = list(e.get("centre", [0.5, 0.5]))
            g.rotate, g.rounded, g.border = e.get("rotate", 0.0), e.get("rounded", 0.0), e.get("border", 0.0)
            g.cutout = e.get("cutout", False)
            g.children = [c for c in (self.item_from_dict(x, by_id, used) for x in e.get("children", [])) if c]
            self.pipe.alloc_group(g)
            return g
        f = by_id.get(e["id"])
        if f is None or f in used:
            return None
        used.add(f)
        if self.pipe.container_of(f) is None:
            f.mix = 0.0
        f.on, f.removing, f.amt = e["on"], False, e["amt"]
        f.expanded = e.get("expanded", f.expanded)
        f.mod = e.get("mod", MOD_AUDIO if e.get("react") else MOD_OFF)
        f.opacity = e.get("opacity", 1.0)
        f.blend = min(e.get("blend", 0), len(E.BLEND_MODES) - 1)
        f.centre = list(e.get("centre", [0.5, 0.5]))
        saved = e.get("opts", [])
        f.opts = [min(saved[i], len(choices) - 1) if i < len(saved) else default
                  for i, (_label, choices, default) in enumerate(f.options)]
        saved = e.get("params", [])
        f.pvals = [min(hi, max(lo, saved[i])) if i < len(saved) else default
                   for i, (_label, default, lo, hi, _fmt) in enumerate(f.params)]
        f.speed = e.get("speed", 1.0)
        f.colours = [list(c) for c in e.get("colours", DEFAULT_COLOURS)]
        f.target = 0 if f.needs_mask else e.get("target", 0)
        f.tw = target_weights(f.target)   # a look arrives with its own setting, no glide
        f.keep_out = e.get("keep_out", False)
        f.autos = copy_autos(e.get("autos", {}))
        f.listen = e.get("listen") if e.get("listen") in A.SOURCE_KEYS else None
        f.rng = [float(x) for x in e.get("rng", [80.0, 250.0])][:2]
        f.resp = [float(x) for x in e["resp"]][:2] if e.get("resp") else None
        return f

    # --- auto-play
    def auto_step(self, direction=1):
        if self.auto_mode == AUTO_RANDOM:
            self.randomize()
        else:
            self.playlist_step(direction)

    def hold_time(self):
        """How long auto-play stays on the current look: (count, unit 0 = seconds / 1 = beats)."""
        if self.auto_mode == AUTO_PLAYLIST and self.current_preset:
            m = self.meta(self.current_preset)
            if m["hold"] > 0:
                return m["hold"], m["unit"]
        return self.auto_every, self.auto_unit

    def playlist_step(self, direction=1):
        if not self.playlist:
            self.flash("Save some looks to the playlist first (+ Save look).")
            return
        i = self.playlist.index(self.current_preset) if self.current_preset in self.playlist else -1
        if i < 0 and direction < 0:
            i = 0
        self.load_preset(self.playlist[(i + direction) % len(self.playlist)])

    # --- presets ("looks") and the playlist
    def load_playlist(self):
        """Look names in show order; also loads each look's transition/timing into self.look_meta."""
        os.makedirs(PRESET_DIR, exist_ok=True)
        on_disk = sorted(n[:-5] for n in os.listdir(PRESET_DIR) if n.endswith(".json") and not n.startswith("_"))
        try:
            with open(PLAYLIST_FILE) as fh:
                saved = json.load(fh)
        except (OSError, ValueError):
            saved = []
        if isinstance(saved, list):   # older files were just the order
            saved = dict(order=saved, meta={})
        self.look_meta = {n: m for n, m in saved.get("meta", {}).items() if n in on_disk}
        order = saved.get("order", [])
        return [n for n in order if n in on_disk] + [n for n in on_disk if n not in order]

    def save_playlist(self):
        with open(PLAYLIST_FILE, "w") as fh:
            json.dump(dict(order=self.playlist, meta=self.look_meta), fh, indent=1)

    def meta(self, name):
        """A look's own transition and timing. transition -1 / hold 0 mean 'use the defaults'."""
        return {**dict(transition=-1, fade=1.0, fade_unit=0, hold=0, unit=0), **self.look_meta.get(name, {})}

    def set_meta(self, name, **values):
        self.look_meta[name] = {**self.meta(name), **values}
        self.save_playlist()

    def save_preset(self, name):
        name = "".join(c for c in name if c.isalnum() or c in " -_").strip()
        if not name:
            return
        data = dict(version=2, band=self.band, gain=self.gain,
                    effects=[self.item_to_dict(f) for f in self.pipe.order if not f.removing])
        with open(os.path.join(PRESET_DIR, name + ".json"), "w") as fh:
            json.dump(data, fh, indent=1)
        if name not in self.playlist:
            self.playlist.append(name)
            self.save_playlist()
        self.current_preset = name
        self.save_thumb(name)
        self.flash(f"Saved look '{name}'")

    THUMB_W = 320   # thumbnail width in px (16:9 or the output's own shape)

    def thumb_path(self, name):
        return os.path.join(PRESET_DIR, name + ".png")

    def save_thumb(self, name):
        """A small snapshot of the output, shown on the look's playlist tile."""
        img = self.pipe.read_rgb()
        h, w = img.shape[:2]
        small = cv2.resize(img, (self.THUMB_W, max(1, round(h * self.THUMB_W / w))), interpolation=cv2.INTER_AREA)
        try:
            cv2.imwrite(self.thumb_path(name), cv2.cvtColor(small, cv2.COLOR_RGB2BGR))
        except cv2.error:
            pass
        self.thumb_tried.add(name)

    def delete_preset(self, name):
        for path in (os.path.join(PRESET_DIR, name + ".json"), self.thumb_path(name)):
            try:
                os.remove(path)
            except OSError:
                pass
        if name in self.playlist:
            self.playlist.remove(name)
            self.look_meta.pop(name, None)
            self.save_playlist()
        if self.current_preset == name:
            self.current_preset = None

    def load_preset(self, name, now=False):
        """Fire a look. With launch quantize on (and not now), it waits for the next beat or bar."""
        if self.quantize and not now:
            self.pending_look = (name, self.tempo.next_boundary(self.quantize))
            if self.tempo.phase >= self.pending_look[1] - 1e-6:   # right on a boundary already
                self.pending_look = None
            else:
                return
        self._load_preset(name)

    def _load_preset(self, name):
        try:
            with open(os.path.join(PRESET_DIR, name + ".json")) as fh:
                data = json.load(fh)
        except (OSError, ValueError) as e:
            self.flash(f"Couldn't load '{name}': {e}")
            return
        # this look's own transition, or the sidebar's; used for clicks and auto-play alike
        m = self.meta(name)
        style, secs = ((m["transition"], self.tempo.seconds(m["fade"], m["fade_unit"])) if m["transition"] >= 0
                       else (self.pipe.transition, self.pipe.trans_secs))
        if style == LOOK_MORPH and secs >= 0.05:
            self.morph_look(data, secs)
        elif style == 2 or secs < 0.05 or not any(not f.removing for f in self.pipe.order):
            self.pipe.override = (2, 0.0, glfw.get_time() + 0.1)   # Cut (or nothing on screen yet): instant
            self.apply_look(data)
        else:
            self.pipe.override = None
            self.crossfade_look(data, style, secs)
        self.current_preset = name
        self.preset_t = glfw.get_time()

    @staticmethod
    def settings_of(f):
        return dict(amt=f.amt, opacity=f.opacity, speed=f.speed, centre=list(f.centre), pvals=list(f.pvals),
                    colours=[list(c) for c in f.colours], opts=list(f.opts))

    def morph_look(self, data, seconds):
        """Morph: effects in both looks keep running and slide every setting from the old look's value to the
        new one over the transition (dropdown choices switch halfway); effects in only one look fade in / out."""
        before = {f.id: self.settings_of(f) for f in walk(self.pipe.order)
                  if not isinstance(f, Group) and not f.removing}
        now = glfw.get_time()
        self.pipe.override = (0, seconds, now + seconds)
        self.apply_look(data)
        for f in walk(self.pipe.order):
            if not isinstance(f, Group) and not f.removing and f.id in before:
                f.morph = (before[f.id], self.settings_of(f), now, seconds)
        self.morph_step(now)

    def morph_step(self, t):
        for f in walk(self.pipe.order):
            if isinstance(f, Group) or not f.morph:
                continue
            a, b, t0, secs = f.morph
            k = min(1.0, (t - t0) / max(secs, 1e-3))
            e = k * k * (3 - 2 * k)
            lerp = lambda x, y: x + (y - x) * e
            f.amt = f.amt_smooth = lerp(a["amt"], b["amt"])
            f.opacity, f.speed = lerp(a["opacity"], b["opacity"]), lerp(a["speed"], b["speed"])
            f.centre = [lerp(x, y) for x, y in zip(a["centre"], b["centre"])]
            f.pvals = [lerp(x, y) for x, y in zip(a["pvals"], b["pvals"])]
            f.colours = [[lerp(x, y) for x, y in zip(c0, c1)] for c0, c1 in zip(a["colours"], b["colours"])] \
                if len(a["colours"]) == len(b["colours"]) else b["colours"]
            f.opts = list(a["opts"] if k < 0.5 else b["opts"])
            if k >= 1.0:
                f.morph = None

    # --- automation: any effect setting can move on its own, like an LFO, timed by the tempo clock
    AUTO_SHAPES = ["Sine", "Triangle", "Ramp up", "Ramp down", "Square", "Random steps", "Smooth random", "Audio"]

    def effect_level(self, f, t):
        """The audio level an Audio-driven effect follows: its own source (or the main React to), smoothed by
        the main meter smoothing or its own attack / release."""
        key = f.listen or self.band
        target, level = self.audio.source(key, f.rng)
        if not f.resp:
            return level * self.gain
        if f.follow_t != t:   # once a frame, even if it's drawn twice (in both looks of a crossfade)
            dt = 1 / 60 if f.follow_t is None else min(max(t - f.follow_t, 0.0), 0.1)
            f.follow_t = t
            tau = f.resp[0] if target > f.follow else f.resp[1]
            f.follow = target if tau <= 1e-3 else f.follow + (target - f.follow) * (1 - math.exp(-dt / tau))
        return f.follow * self.gain

    AUDIO_FEELS = {   # one-click starting points for an audio-driven slider: attack, release (s), threshold, curve
        "Subtle": dict(resp=[0.12, 0.9], gain=1.0, gate=0.0, curve=-0.3),
        "Punchy": dict(resp=[0.004, 0.16], gain=1.0, gate=0.12, curve=0.35),
        "Hit": dict(resp=[0.0, 0.07], gain=1.0, gate=0.45, curve=0.8),
    }

    def audio_drive(self, f, key, a, t):
        """0..1 for a slider set to follow the sound: its source (a band, a drum, the beat or a frequency range),
        smoothed by its own attack / release (or the main smoothing), then shaped by Sensitivity, Threshold and
        Curve. A small Threshold ignores the quiet noise floor; a Curve above 0 lets only the loud parts move it,
        below 0 lets quiet details move it too."""
        src = A.SOURCE_KEYS[min(a.get("band", 0), len(A.SOURCE_KEYS) - 1)]
        target, level = self.audio.source(src, a.get("rng", [80.0, 250.0]))
        resp = a.get("resp")
        if resp:
            st = self.auto_state.setdefault((f.uid, key), [0.0, None])
            if st[1] != t:   # once a frame, even if it's drawn twice (both looks of a crossfade)
                dt = 1 / 60 if st[1] is None else min(max(t - st[1], 0.0), 0.1)
                st[1] = t
                tau = resp[0] if target > st[0] else resp[1]
                st[0] = target if tau <= 1e-3 else st[0] + (target - st[0]) * (1 - math.exp(-dt / tau))
            heard = st[0]
        else:
            heard = level
        w = heard * a.get("gain", 1.0) * self.gain
        gate = min(0.95, max(0.0, a.get("gate", 0.0)))
        if gate > 0:
            w = (w - gate) / (1 - gate)
        w = min(1.0, max(0.0, w))
        curve = a.get("curve", 0.0)
        if curve:
            w = w ** (2.0 ** (curve * 1.6))
        self.auto_live[(f.uid, key)] = (min(1.0, heard), w)
        return w

    def automate(self, t):
        tp = self.tempo
        rnd = lambda i, seed: (math.sin(i * 12.9898 + seed * 78.233) * 43758.5453) % 1.0
        for f in walk(self.pipe.order):
            if isinstance(f, Group) or not f.autos or f.morph:
                continue
            for key, a in f.autos.items():
                rate = max(a["rate"], 0.01)
                cyc = t / rate if a["unit"] == 0 else tp.phase / (rate * (1 if a["unit"] == 1 else tp.beats_per_bar))
                cyc += a["phase"]
                x, s, seed = cyc % 1.0, a["shape"], len(key) + ord(key[-1])
                if s == 0:
                    w = 0.5 - 0.5 * math.cos(2 * math.pi * x)
                elif s == 1:
                    w = 1 - abs(2 * x - 1)
                elif s == 2:
                    w = x
                elif s == 3:
                    w = 1 - x
                elif s == 4:
                    w = 1.0 if x < 0.5 else 0.0
                elif s == 5:
                    w = rnd(math.floor(cyc), seed)
                elif s == 6:
                    i, fr = math.floor(cyc), cyc % 1.0
                    w = rnd(i, seed) + (rnd(i + 1, seed) - rnd(i, seed)) * fr * fr * (3 - 2 * fr)
                else:
                    w = self.audio_drive(f, key, a, t)
                v = a["lo"] + (a["hi"] - a["lo"]) * w
                if key == "amt":
                    f.amt = f.amt_smooth = v
                elif key in ("opacity", "speed"):
                    setattr(f, key, v)
                elif key[:1] == "p" and key[1:].isdigit() and int(key[1:]) < len(f.pvals):
                    f.pvals[int(key[1:])] = v

    def crossfade_look(self, data, style, seconds):
        """Build the look on the idle effect set and crossfade to it; the current look keeps running meanwhile."""
        p = self.pipe
        old_by_id = {f.id: f for f in p.effects}
        p.lib_i ^= 1
        p.ensure_effects(p.lib_i, self.look_ids(data))
        for f in p.effects:
            f.on, f.mix, f.removing = False, 0.0, False
        by_id, used = {f.id: f for f in p.effects}, set()
        chain = [it for it in (self.item_from_dict(e, by_id, used) for e in self.look_entries(data)) if it]
        old_on = {f.id for f in walk(p.order) if not isinstance(f, Group) and f.on and not f.removing}
        new_on = {f.id for f in walk(chain) if not isinstance(f, Group) and f.on}
        for f in old_by_id.values():   # effects in both looks don't ramp during Grow
            f.xf_keep = f.id in new_on
        for it in walk(chain):   # fully on at once: the crossfade itself does the fading
            it.mix = 1.0 if it.on else 0.0
            it.amt_smooth = it.amt
            if not isinstance(it, Group):
                it.xf_keep = it.id in old_on
                if it.id in old_by_id:   # keep animations (spin, zoom...) continuous
                    it.clock = old_by_id[it.id].clock
        p.crossfade_to(chain, style, seconds, glfw.get_time())
        self.band, self.gain = data.get("band", self.band), data.get("gain", self.gain)
        self.picking = None
        self.auto_progress = 0.0

    def look_ids(self, data):
        """Every effect id a look uses, inside groups too."""
        def ids(entries):
            for e in entries:
                if e.get("group"):
                    yield from ids(e.get("children", []))
                else:
                    yield e["id"]
        return set(ids(self.look_entries(data)))

    @staticmethod
    def look_entries(data):
        old_format = data.get("version", 1) < 2   # v1 listed every effect; only the 'on' ones form the chain
        return [e for e in data["effects"] if not (old_format and not e["on"])]

    # --- session: the current setup is saved continuously and restored on the next launch
    def session_data(self):
        p = self.pipe
        return dict(version=2, band=self.band, gain=self.gain, hit_sens=self.audio.hit_sens,
                    current=self.current_preset,
                    audio_input=self.audio.device_name if self.audio.stream else None,
                    transition=p.transition, trans_time=p.trans_time, trans_unit=p.trans_unit, wave_rate=p.wave_rate,
                    tempo=dict(bpm=round(self.tempo.bpm, 2), source=self.tempo.source,
                               bar=self.tempo.beats_per_bar, quantize=self.quantize),
                    auto=dict(every=self.auto_every, unit=self.auto_unit),
                    record=dict(folder=self.rec_folder, format=self.rec_format, fps=self.rec_fps,
                                sound=self.rec_sound),
                    source=self.source_desc, extra_sources=self.extra_desc,
                    mask=dict(quality=self.mask_quality, refine=p.refine, stability=p.stability,
                              plate=p.plate_strength, plate_delay=self.plate_delay), spout=self.spout is not None,
                    effects=[self.item_to_dict(f) for f in p.order if not f.removing])

    def save_session(self):
        if self.held_session is not None:   # don't overwrite the setup we're offering to restore
            return
        text = json.dumps(self.session_data(), indent=1)
        if text == self.session_text:
            return
        try:
            with open(os.path.join(PRESET_DIR, "_session.json"), "w") as fh:
                fh.write(text)
            self.session_text = text
        except OSError:
            pass

    def restore_session(self):
        try:
            with open(os.path.join(PRESET_DIR, "_session.json")) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        if self.unclean:   # maybe this setup is what crashed it: ask first (the UI shows the question)
            self.held_session = data
        else:
            self.apply_look(data)
        p = self.pipe
        p.transition = data.get("transition", p.transition)
        p.trans_time, p.wave_rate = data.get("trans_time", p.trans_time), data.get("wave_rate", p.wave_rate)
        p.trans_unit = data.get("trans_unit", p.trans_unit)
        self.audio.hit_sens = float(data.get("hit_sens", self.audio.hit_sens))
        tm = data.get("tempo", {})
        self.tempo.bpm = tm.get("bpm", self.tempo.bpm)
        self.tempo.source = tm.get("source", self.tempo.source)
        self.tempo.beats_per_bar = tm.get("bar", self.tempo.beats_per_bar)
        self.quantize = tm.get("quantize", self.quantize)
        rc = data.get("record", {})
        self.rec_folder = rc.get("folder", self.rec_folder)
        self.rec_format, self.rec_fps = rc.get("format", self.rec_format), rc.get("fps", self.rec_fps)
        self.rec_sound = rc.get("sound", self.rec_sound)
        au = data.get("auto", {})
        self.auto_every, self.auto_unit = au.get("every", self.auto_every), au.get("unit", self.auto_unit)
        m = data.get("mask", {})
        p.refine, p.stability = m.get("refine", p.refine), m.get("stability", p.stability)
        p.plate_strength = m.get("plate", p.plate_strength)
        self.plate_delay = m.get("plate_delay", self.plate_delay)
        name = data.get("audio_input")   # the same audio input as last time, if it's still there
        dev = next((d for d, n in self.audio_devs if n == name), None) if name else None
        if dev is not None:
            self.audio.open(dev, name)
        if data.get("spout"):   # it was sending when Lumoria closed: OBS is probably expecting it
            self.toggle_spout(True)
        if m.get("quality", self.mask_quality) != self.mask_quality:
            self.set_mask_quality(min(m["quality"], len(SEG_QUALITY) - 1))
        self.current_preset = data.get("current") if data.get("current") in self.playlist else None
        # reopen the sources that were in use (a camera that's gone just shows a message)
        if data.get("source", {}).get("kind", "test") != "test":
            self.choose_source("main", data["source"])
        for slot, desc in enumerate(data.get("extra_sources", [])[:3]):
            if desc.get("kind", "none") != "none":
                self.choose_source(slot, desc)
        self.session_text = json.dumps(self.session_data(), indent=1)

    def apply_look(self, data):
        self.auto_progress = 0.0
        self.pipe.ensure_effects(self.pipe.lib_i, self.look_ids(data))
        by_id = {f.id: f for f in self.pipe.effects}
        entries = self.look_entries(data)
        used = set()
        chain = [it for it in (self.item_from_dict(e, by_id, used) for e in entries) if it]
        for f in used:   # effects the new look reuses leave wherever they were in the old chain
            if (old := self.pipe.container_of(f)) is not None:
                old.remove(f)
        leaving = list(self.pipe.order)   # whatever is left of the old chain (incl. old groups)
        for f in leaving:
            self.remove_effect(f)
        self.pipe.order = chain + leaving   # leaving ones fade out at the bottom, then drop
        self.band, self.gain = data.get("band", self.band), data.get("gain", self.gain)

    # --- per frame
    def mask_needed(self):
        def uses_mask(f):
            if f.needs_mask or f.target or f.tw[0] < 0.999:   # (still fading back to All)
                return True
            when = getattr(f, "mask_when", None) or []
            if when and isinstance(when[0], int):   # one (option, choices) pair, or a list of them
                when = [when]
            return any(f.opts[i] in choices for i, choices in when)
        items = list(walk(self.pipe.order))
        if self.pipe.outgoing:   # a look still fading out may be using it too
            items += list(walk(self.pipe.outgoing["order"]))
        return any(f.mix > 0 and uses_mask(f) for f in items)

    def set_mask_quality(self, idx):
        self.mask_quality = idx
        _label, long_side, ratio = SEG_QUALITY[idx]
        self.pipe.seg_long = long_side
        self.pipe.resize_seg()
        if self.segmenter:
            self.segmenter.ratio = ratio
            self.segmenter.reset()

    PLATE_DELAYS = (3.0, 5.0, 10.0, 15.0)

    def capture_background(self):
        """Count down so the person can step out of frame, then capture the empty room."""
        self.plate_at = glfw.get_time() + self.plate_delay

    def cancel_capture(self):
        self.plate_at = None
        self.flash("Background capture cancelled", 2)

    def plate_tick(self, t):
        if self.plate_at is not None:
            left = self.plate_at - t
            if left > 0:
                self.flash("Step out of frame...", 1)
            else:
                self.plate_at, self.plate_busy, self.plate_drift = None, True, 0.0
                self.pipe.capture_plate()
                self.flash("Capturing the background... stay out of frame", 2)
        elif self.plate_busy and self.pipe.plate:
            self.plate_busy = False
            self.flash("Background captured. You can step back in.", 4)
        # every second, check the camera/lighting still matches the plate
        if self.pipe.plate and self.pipe.mask_active and self.last_mask is not None and t - self.plate_check_t > 1:
            self.plate_check_t = t
            d = self.pipe.plate_drift(self.last_mask)
            self.plate_drift += (d - self.plate_drift) * 0.5

    def update_source_masks(self):
        """Run an AI segmenter for each of Sources 2-4 that a source group needs a person mask for (Cut out,
        or effects in the group that use the mask); idle ones cost nothing."""
        def uses(it):
            return it.needs_mask or it.target or any(it.opts[i] in ch for i, ch in
                                                     ([it.mask_when] if it.mask_when and isinstance(it.mask_when[0], int)
                                                      else (it.mask_when or [])))
        need = set()
        for g in walk(self.pipe.order):
            if isinstance(g, Group) and g.source >= 0 and g.on and not g.removing and (
                    g.cutout or any(not isinstance(c, Group) and c.on and uses(c) for c in walk(g.children))):
                need.add(g.source)
        p = self.pipe
        for slot in range(3):
            sm = p.slot_masks[slot]
            if slot not in need:
                if sm:
                    sm.active = False
                continue
            if sm is None:
                sm = p.slot_masks[slot] = SourceMask(p.ctx, p.size, p.seg_small.tex.size)
            if self.slot_segs[slot] is None:
                self.slot_segs[slot] = Segmenter(os.path.join(HERE, "models", SEG_MODEL))
                self.slot_segs[slot].start()
            sm.active = True
            seg = self.slot_segs[slot]
            seg.ratio = SEG_QUALITY[self.mask_quality][2]
            if (mask := seg.take_mask()) is not None:
                sm.upload(mask)
            if sm.ready is not None and seg.wants_frame():
                seg.submit(sm.ready)
                sm.ready = None

    def update_segmenter(self):
        """Start the person segmenter when an effect needs it; bring in its newest mask."""
        self.pipe.mask_active = self.mask_needed()
        if not self.pipe.mask_active:
            return None
        if self.segmenter is None:
            self.segmenter = Segmenter(os.path.join(HERE, "models", SEG_MODEL))
            self.segmenter.ratio = SEG_QUALITY[self.mask_quality][2]
            self.segmenter.start()
            self.flash("Loading background removal...", 3)
        seg = self.segmenter
        if seg.error and not self.seg_error_shown:
            self.flash(seg.error, 10)
            self.seg_error_shown = True
        if (mask := seg.take_mask()) is not None:
            self.pipe.upload_mask(mask)
            self.last_mask = mask
        return seg

    def process(self, t):
        if self.source:
            if self.source.error:
                self.flash(self.source.error)
                self.set_source(None, "Test pattern")
            elif (frame := self.source.latest()) is not None:
                self.pipe.upload(frame)
        if self.share_dialog or self.file_dialog:
            raise_dialogs()
        self.finish_share_dialog()
        if self.file_dialog and self.file_dialog[2].ready():
            (target, kind, dialog), self.file_dialog = self.file_dialog, None
            if files := dialog.result():
                self.choose_source(target, {"kind": kind, "path": files[0]})
        used = self.media_slots_used()
        for slot, src in enumerate(self.extra):   # Sources 2-4
            if src is None:
                continue
            # a source no Media Layer is showing pauses (a whole-screen grab costs most of a CPU core)
            src.paused = slot not in used and not (self.cropping and self.cropping["target"] == slot)
            if src.error:
                self.flash(f"Source {slot + 2}: {src.error}")
                self.extra[slot] = None
                self.pipe.upload_media(slot, None)
            elif (frame := src.latest()) is not None:
                self.pipe.upload_media(slot, frame)

        dt = 0.0 if self.last_t is None else min(t - self.last_t, 0.1)
        self.last_t = t
        au = self.audio
        au.update(t)
        if self.band not in au.level:
            self.band = "bass"

        # the tempo follows the kick drum; music with no kick for a while falls back to bass swells
        # (a simple detector with hysteresis, so one swell counts once)
        beat = au.hit_now["kick"]
        bass = au.level["bass"] if au.stream else 0.0
        swell = False
        if self.beat_armed and bass > 0.65:
            swell, self.beat_armed = True, False
        elif bass < 0.35:
            self.beat_armed = True
        if swell and t - au.last_kick > 4.0:
            beat = True
        if beat:
            self.beat_until = t + 0.12
        # the beat clock: follows the bass hits (Audio), taps, a set BPM or MIDI clock; shaders and auto-play
        # count its beats, so they keep steady time even when the music goes quiet
        tp = self.tempo
        if tp.source == tempo.MIDI_CLOCK and t - tp.clock_seen > 1.0:
            tp.clock_running = False   # the DAW stopped sending: run on freely
        tp.advance(dt, t, onset=beat)
        beat = tp.beat_now
        if beat:
            self.beat_until = t + 0.12
            au.pulse("beat", t)
        level = au.level[self.band] * self.gain
        b = self.pipe.beat
        b["count"], b["since"], b["len"] = float(int(tp.phase)), (tp.phase % 1.0) * tp.beat_len, tp.beat_len
        self.pipe.trans_secs = tp.seconds(self.pipe.trans_time, self.pipe.trans_unit)
        if self.pending_look and tp.phase >= self.pending_look[1] - 1e-6:   # a quantized launch's moment
            name, self.pending_look = self.pending_look[0], None
            self.load_preset(name, now=True)
        lv = self.audio.level
        b["bands"] = (lv["bass"] * self.gain, lv["mid"] * self.gain, lv["high"] * self.gain)
        b["hits"] = (lv["kick"], lv["snare"], lv["hat"], lv["accent"])
        self.pipe.audio_tex.write(self.audio.shader_data(t).tobytes())
        if self.auto_mode:
            every, unit = self.hold_time()
            self.auto_progress += dt / every if unit == 0 else beat / (every * (1 if unit == 1 else tp.beats_per_bar))
            if self.auto_progress >= 1:
                self.auto_progress = 0.0
                self.auto_step()

        for msg in self.midi.poll():
            self.handle_midi(msg, t)
        self.track_undo(t)
        cur = self.current_preset
        if (cur and cur not in self.thumb_tried and not self.pipe.outgoing and t - self.preset_t > 1.5
                and not os.path.exists(self.thumb_path(cur))):
            self.save_thumb(cur)
        seg = self.update_segmenter()
        self.update_source_masks()
        er = next((f for f in self.pipe.order if not isinstance(f, Group) and f.id == "cutout" and f.on
                   and not f.removing and f.opts[0] == 7), None)
        self.pipe.alpha_out = (0.02 + 0.23 * er.pvals[0], 0.5 - er.pvals[1] * 0.35) if er else None
        self.plate_tick(t)
        self.morph_step(t)
        self.automate(t)
        self.pipe.render(t, dt, level, self.source is None)
        if seg and seg.loaded:
            # copy a frame every frame without waiting; hand the previous one over when the AI is free
            small = self.pipe.grab_small_async()
            if small is not None and seg.wants_frame():
                seg.submit(small)

        if self.spout:
            self.spout.send(self.pipe.out.fbo.glo, *self.pipe.size)
            if self.spout.error:
                self.flash(f"Spout stopped: {self.spout.error}", 8)
                self.toggle_spout(False)
        if self.recorder.ready:   # a copy of the output, read back without waiting for the GPU
            frame = self.pipe.read_out_async()
            if frame is not None:
                self.recorder.push(frame, t)
        err = self.recorder.failed()
        if err:
            self.audio.tap = None
            self.flash(err, 6)

        if self.vcam and t - self.vcam_last >= 1 / VCAM_FPS - 0.002:
            self.vcam_last = t
            self.vcam.send(self.pipe.read_rgb())

        if t - self.code_check_t > 2.0:
            self.code_check_t = t
            self.update_ready = code_stamp() != self.code_stamp
        if t - self.session_t > 3.0:
            self.session_t = t
            self.save_session()
            in_use = set(walk(self.pipe.order))
            if self.pipe.outgoing:
                in_use |= set(walk(self.pipe.outgoing["order"]))
            if self.picking:
                in_use.add(self.picking)
            self.pipe.drop_unused_copies(in_use)

        self.frames += 1
        if t - self.fps_t >= 1:
            self.fps, self.frames, self.fps_t = self.frames, 0, t



# ---------------------------------------------------------------- main loop

_gl_errors_seen = set()


def run_selftest(app, frame):
    """Lumoria.exe --selftest: run a few seconds with the AI mask, an effect and Spout on, then write
    selftest.json (in the data folder) and quit. Proves a build has its DLLs, fonts, shaders and model."""
    if frame == 1:
        app.held_session = None
        by_id = {f.id: f for f in app.pipe.effects}
        for fid in ("cutout", "edges"):
            app.add_effect(by_id[fid])
        app.toggle_spout(True)
    if frame < 300:
        return False
    seg = app.segmenter
    report = dict(frozen=FROZEN, fps=app.fps, effects_compiled=len(app.pipe.effects),
                  ai_mask_loaded=bool(seg and seg.loaded), ai_mask_error=seg.error if seg else "not started",
                  ai_mask_ms=round(seg.ms, 1) if seg else None,
                  spout=bool(app.spout and not app.spout.error), midi_ports=[n for n, h, _ in app.midi.ports if h],
                  font_ok=bool(ui.S.mono), logo_ok=bool(ui.S.brand), fast_capture=sources.fast_capture_ok(),
                  recording=app.recorder.found, what_you_hear=selftest_loopback())
    info = app.pipe.ctx.info
    report.update(gpu=info.get("GL_RENDERER", "?"), gpu_vendor=info.get("GL_VENDOR", "?"),
                  gl_version=info.get("GL_VERSION", "?"), lumoria_version=VERSION)
    with open(os.path.join(DATA, "selftest.json"), "w") as fh:
        json.dump(report, fh, indent=1)
    if "--report" in sys.argv:   # the Start menu's "Lumoria Self-Test": a plain report to read and send back
        ok = lambda v: "OK" if v else "FAILED"
        lines = [f"Lumoria {VERSION} self-test", "",
                 f"Graphics card:   {report['gpu']}  ({report['gpu_vendor']})",
                 f"OpenGL:          {report['gl_version']}",
                 f"Frame rate:      {report['fps']} fps",
                 f"Effects:         {report['effects_compiled']} compiled",
                 f"AI mask:         {ok(report['ai_mask_loaded'])}" + (f"  ({report['ai_mask_ms']} ms per mask)"
                                                                       if report["ai_mask_loaded"] else
                                                                       f"  {report['ai_mask_error']}"),
                 f"Spout:           {ok(report['spout'])}",
                 f"Screen capture:  {'60 fps (fast)' if report['fast_capture'] else 'standard (about 30 fps)'}",
                 f"What you hear:   {ok(report['what_you_hear'])}",
                 f"Recording:       {report['recording'] or 'FAILED (no H.264 encoder)' if report['recording'] is not None else 'not checked'}",
                 f"Fonts / logo:    {ok(report['font_ok'])} / {ok(report['logo_ok'])}",
                 f"MIDI inputs:     {', '.join(report['midi_ports']) or 'none'}", "",
                 "Please send this to whoever gave you Lumoria. Thanks for testing!"]
        path = os.path.join(DATA, "Lumoria self-test.txt")
        with open(path, "w", encoding="utf8") as fh:
            fh.write("\n".join(lines) + "\n")
        try:
            os.startfile(path)
        except OSError:
            pass
    return True


_raised = set()


def raise_dialogs():
    """Bring Lumoria's open file dialogs in front once each. They open from a helper thread, so Windows can put
    them behind Lumoria's own windows, where they're easy to miss while Lumoria waits for an answer."""
    if os.name != "nt":
        return
    user32, me = ctypes.windll.user32, os.getpid()
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def visit(hwnd, _):
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
        cls = ctypes.create_unicode_buffer(16)
        user32.GetClassNameW(ctypes.c_void_p(hwnd), cls, 16)
        if pid.value == me and cls.value == "#32770" and user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
            found.append(hwnd)   # a standard dialog window of ours
        return True

    user32.EnumWindows(visit, None)
    for hwnd in found:
        if hwnd in _raised:
            continue
        _raised.add(hwnd)
        h = ctypes.c_void_p(hwnd)
        flags = 0x0001 | 0x0002 | 0x0040   # keep size and position, show
        user32.SetWindowPos(h, ctypes.c_void_p(-1), 0, 0, 0, 0, flags)   # on top of everything,
        user32.SetWindowPos(h, ctypes.c_void_p(-2), 0, 0, 0, 0, flags)   # then an ordinary window again
        user32.SetForegroundWindow(h)


def selftest_loopback():
    """Whether "What you hear" can listen to Windows' default output (briefly opens it)."""
    try:
        import loopback
        outs = loopback.list_outputs()
        if not outs:
            return False
        loopback.LoopbackStream(outs[0][0], lambda *a: None).close()
        return True
    except Exception:
        return False


def set_app_icon(win):
    """Lumoria's icon on a window's title bar and taskbar button. Neon styles: the bolder small tile up to 32 px, the full tile
    above, in the Neon logo styles; the original artwork otherwise (Settings > Interface > Logo)."""
    neon = ui.S.logo_look in (1, 2)
    icons = {}
    for key, name in (("small", "lumoria_icon_neon_small" if neon else "lumoria_icon"),
                      ("big", "lumoria_icon_neon" if neon else "lumoria_icon")):
        img = cv2.imread(os.path.join(HERE, "assets", name + ".png"), cv2.IMREAD_UNCHANGED)
        if img is None or img.ndim != 3 or img.shape[2] != 4:
            return
        icons[key] = img
    sizes = (16, 24, 32, 48, 64, 128, 256)   # Windows picks per spot and display scale (taskbar, Alt+Tab, title)
    glfw.set_window_icon(win, len(sizes), [
        (s, s, cv2.cvtColor(cv2.resize(icons["small" if s <= 32 else "big"], (s, s), interpolation=cv2.INTER_AREA),
                            cv2.COLOR_BGRA2RGBA))
        for s in sizes])


def set_taskbar_icon(win):
    """The taskbar button's icon. Run from source, Windows would take it from the Python launcher, not the window,
    so give the window Lumoria's app ID plus a relaunch command and icon (what a pinned button uses too). Must be
    set before the window is first shown."""
    if os.name != "nt":
        return
    neon = ui.S.logo_look in (1, 2)
    icon = os.path.join(HERE, "assets", "lumoria_neon.ico" if neon else "lumoria.ico")
    if FROZEN:
        command = f'"{sys.executable}"'
    else:
        exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        command = f'"{exe if os.path.exists(exe) else sys.executable}" "{os.path.join(HERE, "app.py")}"'

    class GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", ctypes.c_ulong)]

    class PROPVARIANT(ctypes.Structure):   # only the VT_LPWSTR case is used here
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                    ("r3", ctypes.c_ushort), ("val", ctypes.c_void_p), ("pad", ctypes.c_void_p)]

    def guid(text):
        g = GUID()
        ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
        return g

    try:
        hwnd = glfw.get_win32_window(win)
        store = ctypes.c_void_p()
        iid = guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")   # IPropertyStore
        if ctypes.windll.shell32.SHGetPropertyStoreForWindow(ctypes.c_void_p(hwnd), ctypes.byref(iid),
                                                             ctypes.byref(store)) != 0:
            return
        vtbl = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                       ctypes.POINTER(PROPVARIANT))(vtbl[6])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
        app_model = guid("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}")   # PKEY_AppUserModel_*
        texts = []
        for pid, text in ((5, APP_ID), (2, command), (3, icon + ",0"), (4, "Lumoria")):
            buf = ctypes.create_unicode_buffer(text)
            texts.append(buf)
            set_value(store, ctypes.byref(PROPERTYKEY(app_model, pid)),
                      ctypes.byref(PROPVARIANT(31, 0, 0, 0, ctypes.cast(buf, ctypes.c_void_p), None)))
        release(store)
    except (OSError, AttributeError, ValueError):
        pass


def log_gl_errors(stage):
    """Report (once each) GL errors raised during a stage, without crashing the show."""
    while (err := GL.glGetError()) != GL.GL_NO_ERROR:
        if (stage, err) not in _gl_errors_seen:
            _gl_errors_seen.add((stage, err))
            print(f"[Lumoria] OpenGL error {err} during {stage} (ignored, please report)", flush=True)


def code_stamp():
    """Modification times of Lumoria's own source files (none when installed: it updates by reinstalling)."""
    stamps = {}
    if FROZEN:
        return stamps
    for name in os.listdir(HERE):
        if name.endswith(".py"):
            try:
                stamps[name] = os.path.getmtime(os.path.join(HERE, name))
            except OSError:
                pass
    return stamps


APP_ID = "Lumoria.VisualFXEngine"


def main():
    # our own taskbar identity: without it Windows files the windows under python.exe and shows Python's icon
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError, OSError):
            pass
    if not glfw.init():
        raise SystemExit("Couldn't start GLFW")
    for hint, v in ((glfw.CONTEXT_VERSION_MAJOR, 3), (glfw.CONTEXT_VERSION_MINOR, 3),
                    (glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE), (glfw.OPENGL_FORWARD_COMPAT, True)):
        glfw.window_hint(hint, v)
    glfw.window_hint(glfw.VISIBLE, False)   # shown once the taskbar knows its icon (set_taskbar_icon)
    win = glfw.create_window(1600, 960, "Lumoria Visual FX Engine", None, None)
    glfw.make_context_current(win)
    glfw.swap_interval(1)

    imgui.create_context()
    imgui.get_io().set_ini_filename("")
    impl = GlfwRenderer(win)
    ui.setup_style()
    ctx = moderngl.create_context()

    out_win = OutputWindow(share=win)
    ui.S.windows = [win, out_win.win]
    ui.tint_title_bars()   # before they're shown, so they never flash white
    for w in (out_win.win, win):
        set_app_icon(w)
        set_taskbar_icon(w)
        glfw.show_window(w)
    x, y = glfw.get_window_pos(win)
    glfw.set_window_pos(out_win.win, x + 420, y + 120)
    glfw.make_context_current(win)
    glfw.focus_window(win)

    app = App(ctx, out_win)
    selftest = 0 if "--selftest" in sys.argv else None   # build check: see run_selftest
    try:
        while not glfw.window_should_close(win) and not app.restart_requested:
            if selftest is not None:
                selftest += 1
                if run_selftest(app, selftest):
                    break
            glfw.poll_events()
            impl.process_inputs()
            glfw.make_context_current(win)

            log_gl_errors("output window / frame start")
            app.process(glfw.get_time())
            log_gl_errors("effects")

            imgui.new_frame()
            ui.draw(app)
            imgui.render()
            ctx.screen.use()
            ctx.clear(0.027, 0.027, 0.043, 1)
            impl.render(imgui.get_draw_data())
            log_gl_errors("UI drawing")
            glfw.swap_buffers(win)

            out_win.draw(app.pipe.out.tex)
        app.clean_exit()   # only reached when the loop ends normally (not on a crash)
    finally:
        app.save_session()   # so closing or restarting never loses the current setup
        app.set_source(None, "")
        for src in app.extra:
            if src:
                src.close()
        app.audio.close()
        app.midi.close()   # free the ports, so a relaunch (or another program) can open them
        app.audio.tap = None
        app.recorder.close()   # finish the file properly and let the recording helper go
        if app.spout:
            app.spout.close()   # unlists "Lumoria" so receivers don't wait for it
        if app.vcam:
            app.vcam.close()
        impl.shutdown()
        glfw.terminate()
    if app.restart_requested:  # relaunch with the updated code (camera and windows are released above)
        subprocess.Popen([sys.executable] if FROZEN else [sys.executable, os.path.join(HERE, "app.py")],
                         cwd=DATA if FROZEN else HERE)


if __name__ == "__main__":
    try:
        main()
    except Exception:   # a relaunched Lumoria has no console, so keep the error somewhere findable
        import traceback
        with open(os.path.join(DATA, "crash.log"), "a", encoding="utf8") as fh:
            fh.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')}\n{traceback.format_exc()}")
        raise
