"""Lumoria interface: neon-on-black theme, top bar, sidebar of effect cards, preview, playlist panel."""
import ctypes
import json
import math
import os
import re
import time
import webbrowser
from ctypes import wintypes

import cv2
import numpy as np
import glfw
import imgui_bundle
import moderngl
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

import effects as E
import recorder
import sysload
import tempo
import audio as A
from audio import list_inputs
from segment import QUALITY as SEG_QUALITY
from shared import (AUTO_OFF, AUTO_PLAYLIST, AUTO_RANDOM, DATA, HERE, LOOK_TRANSITIONS, MOD_AUDIO, MOD_OFF, MOD_WAVE,
                    RESOLUTIONS, SOURCE_URL, SUPPORT_URL, TRANSITIONS, VERSION, save_json)
from sources import CameraSource, describe, list_cameras, list_screens, window_label

V = imgui.ImVec2


def rgb(hex_, a=1.0):
    return imgui.ImVec4(int(hex_[1:3], 16) / 255, int(hex_[3:5], 16) / 255, int(hex_[5:7], 16) / 255, a)


def alpha(c, a):
    return imgui.ImVec4(c.x, c.y, c.z, a)


# Themes. Every colour the interface uses is a named token below; a theme is a set of values for them, applied
# by recolouring these same objects in place (apply_theme), so anything holding one follows along. The look
# is a hardware console: a chassis, raised modules, recessed wells for controls, keys with LED strips.
# CYAN / MAGENTA / VIOLET / RED are the LED colours (primary, secondary - audio mode, wave mode, alerts).
THEMES = {
    "Console": dict(   # graphite and brushed metal, ice-blue and amber lights
        BG="#0a0b0d", PANEL="#141518", CARD="#1a1b1f", CARD_ON="#1d1f23", GROUP_BG="#17181b",
        FRAME="#0c0d0f", FRAME_HI="#111215", FRAME_ACT="#15171a", BORDER="#2a2c31", TEXT="#e4e4df",
        DIM="#8b8e94", NAME_ON="#f4f4f0", KEY_TEXT="#c9cbd0", EDGE_HI="#3a3d44", EDGE_LO="#050506",
        KEY_TOP="#2b2d32", KEY_BOT="#1e2024", KEY_HOV="#33363c", STRIP_ON_TOP="#383b42", STRIP_ON_BOT="#2a2c32",
        STRIP_TOP="#2a2b30", STRIP_BOT="#212226", STRIP_EDGE="#4a4e56", TOPBAR_TOP="#1b1c20", POPUP="#17181c",
        HEAD="#24262b", HEAD_HI="#2a2d32", HEAD_ACT="#31343a", GRAB="#b4b8bf", GRAB_ACT="#eceef1",
        GROOVE="#2a2c30", SCROLL="#2c2e33", SCROLL_HI="#3a3d43", SCROLL_ACT="#4a4d54", LENS="#0d0e10",
        SEG_OFF="#1b1d21", LCD_BG="#07080a", LCD="#9fdcff", BEZEL="#060708", TOAST="#141518",
        CYAN="#5ec8ff", MAGENTA="#ffa630", VIOLET="#a08cff", RED="#ff4a4a"),
    "Neon": dict(   # the original: near-black with violet undertones, hot cyan and magenta
        BG="#07070b", PANEL="#0c0c13", CARD="#12121b", CARD_ON="#161624", GROUP_BG="#100f1a",
        FRAME="#0a0a12", FRAME_HI="#121220", FRAME_ACT="#191930", BORDER="#25253a", TEXT="#ededf7",
        DIM="#7a7a96", NAME_ON="#ffffff", KEY_TEXT="#d4d4e6", EDGE_HI="#33334f", EDGE_LO="#030306",
        KEY_TOP="#1d1d30", KEY_BOT="#141422", KEY_HOV="#26263e", STRIP_ON_TOP="#25253c", STRIP_ON_BOT="#1a1a2b",
        STRIP_TOP="#1a1a28", STRIP_BOT="#14141f", STRIP_EDGE="#3a3a5c", TOPBAR_TOP="#11111c", POPUP="#10101a",
        HEAD="#1c1c2e", HEAD_HI="#24243b", HEAD_ACT="#2b2b48", GRAB="#00f0ff", GRAB_ACT="#ff2bd6",
        GROOVE="#06303a", SCROLL="#26263c", SCROLL_HI="#33334f", SCROLL_ACT="#00f0ff", LENS="#0b0b14",
        SEG_OFF="#161625", LCD_BG="#05050a", LCD="#00f0ff", BEZEL="#040408", TOAST="#10101a",
        CYAN="#00f0ff", MAGENTA="#ff2bd6", VIOLET="#8f63ff", RED="#ff3b5c"),
    "Midnight": dict(   # deep navy anodised panels, cool white legends, blue and teal lights
        BG="#060a12", PANEL="#0d1420", CARD="#121b2a", CARD_ON="#152033", GROUP_BG="#0f1725",
        FRAME="#070c15", FRAME_HI="#0b121e", FRAME_ACT="#101a2a", BORDER="#22304a", TEXT="#e3ebf7",
        DIM="#7f8ea8", NAME_ON="#f5f9ff", KEY_TEXT="#c8d3e6", EDGE_HI="#2f4163", EDGE_LO="#02050a",
        KEY_TOP="#1d2a40", KEY_BOT="#141e2f", KEY_HOV="#25344f", STRIP_ON_TOP="#26365a", STRIP_ON_BOT="#1b2842",
        STRIP_TOP="#1a2539", STRIP_BOT="#141d2d", STRIP_EDGE="#3b5280", TOPBAR_TOP="#131d2e", POPUP="#101828",
        HEAD="#1a263b", HEAD_HI="#203048", HEAD_ACT="#273a57", GRAB="#a9bad6", GRAB_ACT="#e6eefc",
        GROOVE="#22304a", SCROLL="#1f2c44", SCROLL_HI="#2b3b5a", SCROLL_ACT="#3a4f78", LENS="#080d17",
        SEG_OFF="#141d2d", LCD_BG="#03070d", LCD="#7fe7ff", BEZEL="#03060b", TOAST="#0f1726",
        CYAN="#3fa9ff", MAGENTA="#2fe0c4", VIOLET="#8f8bff", RED="#ff4d6a"),
    "Analog": dict(   # vintage studio gear: warm dark walnut and bronze, cream legends, amber and green lamps
        BG="#0d0a07", PANEL="#17120d", CARD="#1e1812", CARD_ON="#221b14", GROUP_BG="#1a150f",
        FRAME="#0e0b08", FRAME_HI="#14100c", FRAME_ACT="#1a1510", BORDER="#33291e", TEXT="#efe4cf",
        DIM="#a08e74", NAME_ON="#fff3dc", KEY_TEXT="#dccbb0", EDGE_HI="#4a3b2a", EDGE_LO="#050302",
        KEY_TOP="#30261b", KEY_BOT="#221b13", KEY_HOV="#3a2e21", STRIP_ON_TOP="#3e3123", STRIP_ON_BOT="#2e2419",
        STRIP_TOP="#2b2219", STRIP_BOT="#211a13", STRIP_EDGE="#5a4732", TOPBAR_TOP="#1f1811", POPUP="#1b150f",
        HEAD="#2a2118", HEAD_HI="#33281d", HEAD_ACT="#3b2f22", GRAB="#c9b38d", GRAB_ACT="#f3e2c2",
        GROOVE="#3a2e21", SCROLL="#33291e", SCROLL_HI="#45382a", SCROLL_ACT="#5a4835", LENS="#100c08",
        SEG_OFF="#221b14", LCD_BG="#090603", LCD="#ffb547", BEZEL="#070503", TOAST="#1b150f",
        CYAN="#ffb547", MAGENTA="#8fd16a", VIOLET="#e08a5a", RED="#ff5a3c"),
    "Carbon": dict(   # matte black stage desk, crisp white legends, red and white lights
        BG="#050505", PANEL="#0e0e0e", CARD="#141414", CARD_ON="#171717", GROUP_BG="#111111",
        FRAME="#070707", FRAME_HI="#0c0c0c", FRAME_ACT="#121212", BORDER="#262626", TEXT="#f2f2f2",
        DIM="#8c8c8c", NAME_ON="#ffffff", KEY_TEXT="#d0d0d0", EDGE_HI="#333333", EDGE_LO="#000000",
        KEY_TOP="#232323", KEY_BOT="#181818", KEY_HOV="#2c2c2c", STRIP_ON_TOP="#2e2e2e", STRIP_ON_BOT="#222222",
        STRIP_TOP="#202020", STRIP_BOT="#191919", STRIP_EDGE="#454545", TOPBAR_TOP="#151515", POPUP="#121212",
        HEAD="#1e1e1e", HEAD_HI="#252525", HEAD_ACT="#2c2c2c", GRAB="#d9d9d9", GRAB_ACT="#ffffff",
        GROOVE="#2a2a2a", SCROLL="#262626", SCROLL_HI="#333333", SCROLL_ACT="#444444", LENS="#0a0a0a",
        SEG_OFF="#181818", LCD_BG="#030303", LCD="#ff5c5c", BEZEL="#020202", TOAST="#111111",
        CYAN="#ff3b3b", MAGENTA="#f2f2f2", VIOLET="#b38cff", RED="#ff3b3b"),
    "Forest": dict(   # deep green lacquer and moss, pale sage legends, green and gold lights
        BG="#060b08", PANEL="#0d1510", CARD="#121c16", CARD_ON="#15211a", GROUP_BG="#101913",
        FRAME="#070d09", FRAME_HI="#0c140f", FRAME_ACT="#111b14", BORDER="#22362a", TEXT="#e2efe5",
        DIM="#7f9a87", NAME_ON="#f2fbf4", KEY_TEXT="#c6d9cb", EDGE_HI="#2f4a39", EDGE_LO="#020503",
        KEY_TOP="#1c2c22", KEY_BOT="#141f18", KEY_HOV="#243829", STRIP_ON_TOP="#26402f", STRIP_ON_BOT="#1b2e22",
        STRIP_TOP="#1a281f", STRIP_BOT="#141f18", STRIP_EDGE="#3d6149", TOPBAR_TOP="#132019", POPUP="#101a13",
        HEAD="#1a2a20", HEAD_HI="#203327", HEAD_ACT="#273d2f", GRAB="#a9c9b2", GRAB_ACT="#e6f7ea",
        GROOVE="#22362a", SCROLL="#1f3125", SCROLL_HI="#2b4433", SCROLL_ACT="#3a5c45", LENS="#080e0a",
        SEG_OFF="#141f18", LCD_BG="#030704", LCD="#8dffb0", BEZEL="#030604", TOAST="#0f1912",
        CYAN="#3ddc84", MAGENTA="#ffc23d", VIOLET="#5ad1c8", RED="#ff5a4a"),
    "Phosphor": dict(   # an old green-screen terminal: black glass, green glow everywhere
        BG="#030603", PANEL="#081008", CARD="#0c160c", CARD_ON="#0f1b0f", GROUP_BG="#0a130a",
        FRAME="#040904", FRAME_HI="#081108", FRAME_ACT="#0c180c", BORDER="#1b3a1b", TEXT="#c8ffc8",
        DIM="#5f9a5f", NAME_ON="#e6ffe6", KEY_TEXT="#a9e8a9", EDGE_HI="#245024", EDGE_LO="#000200",
        KEY_TOP="#132613", KEY_BOT="#0d1a0d", KEY_HOV="#1a331a", STRIP_ON_TOP="#1c3a1c", STRIP_ON_BOT="#132813",
        STRIP_TOP="#122212", STRIP_BOT="#0d190d", STRIP_EDGE="#2f6a2f", TOPBAR_TOP="#0b170b", POPUP="#091209",
        HEAD="#112211", HEAD_HI="#172e17", HEAD_ACT="#1d3a1d", GRAB="#7dff7d", GRAB_ACT="#d9ffd9",
        GROOVE="#0f3a1a", SCROLL="#163016", SCROLL_HI="#1f421f", SCROLL_ACT="#33ff66", LENS="#050a05",
        SEG_OFF="#0d190d", LCD_BG="#020502", LCD="#66ff66", BEZEL="#010301", TOAST="#091209",
        CYAN="#33ff66", MAGENTA="#d4ff3d", VIOLET="#3dffd0", RED="#ff4a3d"),
    "Ember": dict(   # oxblood and charcoal, warm legends, red and orange lights
        BG="#0c0606", PANEL="#160c0c", CARD="#1d1111", CARD_ON="#221313", GROUP_BG="#190e0e",
        FRAME="#0e0707", FRAME_HI="#150a0a", FRAME_ACT="#1c0e0e", BORDER="#3a2020", TEXT="#f5e6e2",
        DIM="#a3807a", NAME_ON="#fff3f0", KEY_TEXT="#e0c8c3", EDGE_HI="#4f2b2b", EDGE_LO="#040101",
        KEY_TOP="#2e1818", KEY_BOT="#211111", KEY_HOV="#3a1f1f", STRIP_ON_TOP="#43221f", STRIP_ON_BOT="#311816",
        STRIP_TOP="#2b1616", STRIP_BOT="#211111", STRIP_EDGE="#6a3530", TOPBAR_TOP="#1f1010", POPUP="#1a0e0e",
        HEAD="#2a1515", HEAD_HI="#341a1a", HEAD_ACT="#3e2020", GRAB="#d6b0a8", GRAB_ACT="#fbe8e3",
        GROOVE="#3a2020", SCROLL="#331c1c", SCROLL_HI="#462626", SCROLL_ACT="#5e3330", LENS="#0f0808",
        SEG_OFF="#211111", LCD_BG="#080303", LCD="#ff9a6a", BEZEL="#060202", TOAST="#1a0e0e",
        CYAN="#ff6a3d", MAGENTA="#ffc04d", VIOLET="#ff5c8a", RED="#ff3b3b"),
    "Plum": dict(   # aubergine panels, lavender legends, pink and violet lights
        BG="#09060c", PANEL="#120c17", CARD="#18111f", CARD_ON="#1c1424", GROUP_BG="#150f1b",
        FRAME="#0a070d", FRAME_HI="#110b15", FRAME_ACT="#170f1d", BORDER="#33233f", TEXT="#efe6f5",
        DIM="#9581a3", NAME_ON="#fbf4ff", KEY_TEXT="#d6c8e0", EDGE_HI="#46305a", EDGE_LO="#030104",
        KEY_TOP="#281a32", KEY_BOT="#1c1324", KEY_HOV="#33213f", STRIP_ON_TOP="#3a2549", STRIP_ON_BOT="#2a1b35",
        STRIP_TOP="#25182e", STRIP_BOT="#1c1324", STRIP_EDGE="#5c3d74", TOPBAR_TOP="#1a1121", POPUP="#160f1c",
        HEAD="#24182d", HEAD_HI="#2d1e38", HEAD_ACT="#362444", GRAB="#c9b3d9", GRAB_ACT="#f4eafb",
        GROOVE="#33233f", SCROLL="#2d1f38", SCROLL_HI="#3d2a4c", SCROLL_ACT="#523866", LENS="#0d0911",
        SEG_OFF="#1c1324", LCD_BG="#050307", LCD="#f0a6ff", BEZEL="#040205", TOAST="#160f1c",
        CYAN="#ff5cc8", MAGENTA="#ffb05c", VIOLET="#a98cff", RED="#ff4a5c"),
}
# the primary light colour can also be picked on its own, over any theme ("Theme" = the theme's own)
ACCENTS = [("Theme", None), ("Ice blue", "#5ec8ff"), ("Cyan", "#00f0ff"), ("Amber", "#ffa630"),
           ("Green", "#3ddc84"), ("Red", "#ff3b3b"), ("Pink", "#ff4fb8"), ("Violet", "#a08cff"), ("White", "#f2f2f2")]

for _k, _v in THEMES["Console"].items():
    globals()[_k] = rgb(_v)
CLEAR = imgui.ImVec4(0, 0, 0, 0)
WHITE = rgb("#ffffff")
AMBER = rgb("#ffb020")   # warnings: the same in every theme
MOD_ICONS = (fa.ICON_FA_SLIDERS, fa.ICON_FA_MUSIC, fa.ICON_FA_WAVE_SQUARE)
MOD_COLS = (DIM, MAGENTA, VIOLET)
MOD_TIPS = ("Manual: the amount stays where you set it", "Audio: the amount follows the music",
            "Wave: the amount swells up and down automatically")


def music_toggle(f):
    """The effect's music switch: a note, lit when it listens. Off, the music doesn't touch it at all."""
    on = f.mod == MOD_AUDIO
    if on:
        tip = "Listening to the music: its amount follows the sound,\nand any ways it moves with the music are on.\nClick to stop"
    elif f.always_hears:
        tip = "Its amount stays where you set it. Its own music\nsettings still listen. Click to make the amount follow the music too"
    else:
        tip = "Not listening: the music doesn't touch this effect.\nClick to make it follow the music"
    learning = bool(S.app and S.app.midi_learn)
    if icon_button(fa.ICON_FA_MUSIC, "mod", MAGENTA if on else alpha(DIM, .4), tip) and not learning:
        f.mod = MOD_OFF if on else MOD_AUDIO
    if learning:
        midi_spot(S.app, (f.id, "mod"))

TOPBAR_H, PLAYLIST_SHUT_H, LABEL_W, GAP = 54, 52, 96, 6   # GAP: draggable seam between panels
SETTINGS_FILE = os.path.join(DATA, "ui_settings.json")
LAYOUT_DEFAULTS = dict(sidebar_w=410.0, playlist_h=196.0, playlist_open=True, scale=1.0, card_cols=0,
                       theme="Console", accent=0, side_tab=0, welcomed=False,
                       card_warnings=0, fx_view=1, fx_keep=0, fx_layout=0, num_boxes=1, auto_buttons=1,
                       layout=0, panels={}, panels_shut=[])
CARD_MIN_W = 300   # auto grid: a new column of effect cards appears whenever this much more width fits
CARD_MAX_W = 720   # an effect card never gets wider than this (long sliders are harder to set finely)


class _State:
    font = bold = None
    sidebar_w, playlist_h, playlist_open, scale = 410.0, 196.0, True, 1.0   # remembered layout
    card_cols = 0                  # effect card grid columns, 0 = auto from the sidebar width
    theme, accent = "Console", 0   # interface theme (THEMES) and light colour (ACCENTS index)
    card_warnings = 0              # "hidden by" notes on cards: 0 full text, 1 icon only, 2 off
    windows = []                   # the app's GLFW windows, for title bar colours (set by app.main)
    side_tab = 0                   # sidebar tab: 0 Effects, 1 Settings
    welcomed = False               # the welcome window has been seen (Settings > About shows it again)
    welcome_open = False
    fx_view = 1                    # Effects tab: 0 cards, 1 outline (the default) (a list, with the open effect(s) below it)
    num_boxes = 1                  # a number box beside each wide slider, to type an exact value
    auto_buttons = 1               # an Automate button at the end of each automatable slider (0: right-click only)
    fx_keep = 0                    # outline: 0 opening an effect closes the others, 1 keeps them open
    fx_layout = 0                  # outline: 0 auto (beside the list when wide, else under its row), 1 under the row, 2 beside
    fx_seen, fx_shift = None, False   # outline: which effects were open last frame; a Shift-click this frame
    pinned = set()                 # outline: effects (by uid) that stay open when another is opened
    confirm_delete = None          # a look waiting for "Delete it?" to be answered
    show_keys = False              # F1: the keyboard shortcuts sheet
    brand = None                   # (small symbol, large symbol, wordmark) textures from assets/, loaded on first use
    thumbs = {}                    # look name -> (texture, file time) for playlist tile thumbnails
    midi_scope = None              # the effect whose controls are being drawn (their MIDI target scope)
    app = None                     # set by draw(), for helpers that need it (MIDI learn in sliders)
    auto_kind = AUTO_PLAYLIST      # what the play button runs
    lib_filter = ""
    save_name = ""
    pending_move = None            # (item uid, destination list, index or None) from a card drag/menu
    open_save = False              # open the "save look" popup next frame
    open_lib, lib_target = False, None   # open the effect library; add into this group (None = top)
    meta_open = None               # look name whose transition & timing popup should open
    show_mask = False              # small view of the refined AI mask over the preview
    layout = 0                     # 0 Classic (fixed sidebar / preview / playlist), 1 Custom (panels you place)
    panels = {}                    # Custom: panel key -> [x, y, w, h] as fractions of the area under the top bar
    pdrag = None                   # Custom: the panel move / resize in progress
    panels_shut = []               # Custom: the panels folded down to their title strip
    settings_open = False          # the Settings drop-down (under its top-bar button)
    settings_focus = False
    settings_page = None           # the Settings section open in the panel beside its menu (None: all folded)
    settings_btn = None            # the Settings button's rect (min, max), for the drop-down to hang from
    file_anchor = None             # where the File menu opens (under its button)
    load = None                    # CPU / GPU load for the top bar readout (sysload.SysLoad, started on first use)
    topbar_h = 0.0                 # the top bar's height last frame (taller when its keys stack)
    rd = None                      # the effect being dragged to a new place in the chain (reorder_source)
    rd_zones, rd_stack, rd_rects, rd_prev_rects = [], [], {}, {}   # this frame's lists and items, for the next
    flow_first = True              # Custom: the next flow() item starts the panel (no same_line before it)


S = _State()


def u32(c):
    return imgui.get_color_u32(c)


def sc(x):
    """Scale a pixel size by the interface size setting."""
    return x * S.scale


def load_layout():
    try:
        with open(SETTINGS_FILE) as fh:
            saved = json.load(fh)
    except (OSError, ValueError):
        saved = {}
    for k, v in LAYOUT_DEFAULTS.items():
        try:
            setattr(S, k, type(v)(saved.get(k, v)))
        except (TypeError, ValueError):   # a damaged value: its default
            setattr(S, k, type(v)(v))


def save_layout():
    try:
        save_json(SETTINGS_FILE, {k: getattr(S, k) for k in LAYOUT_DEFAULTS})
    except OSError:
        pass


# ---------------------------------------------------------------- theme

def setup_style():
    io = imgui.get_io()
    fonts = os.path.join(os.path.dirname(imgui_bundle.__file__), "assets", "fonts")
    icons = os.path.join(fonts, "Font_Awesome_6_Free-Solid-900.otf")

    def load(path, size):
        if not os.path.exists(path):
            return None
        f = io.fonts.add_font_from_file_ttf(path, size)
        if os.path.exists(icons):
            cfg = imgui.ImFontConfig()
            cfg.merge_mode = True
            io.fonts.add_font_from_file_ttf(icons, size * 0.85, cfg)
        return f

    S.font = load(os.path.join(fonts, "Roboto", "Roboto-Regular.ttf"), 16)
    S.bold = load(os.path.join(fonts, "Roboto", "Roboto-Bold.ttf"), 16) or S.font
    S.mono = load(os.path.join(fonts, "Inconsolata-Medium.ttf"), 16) or S.font   # readouts, like an LCD
    load_layout()
    io.config_windows_move_from_title_bar_only = True   # dragging inside the Settings window never moves it

    imgui.style_colors_dark()
    s = imgui.get_style()
    apply_theme(S.theme, S.accent)
    s.font_size_base = 16
    s.window_padding, s.frame_padding = V(14, 12), V(9, 6)
    s.item_spacing, s.item_inner_spacing = V(8, 7), V(6, 6)
    s.window_rounding, s.child_rounding, s.frame_rounding = 0, 4, 3
    s.popup_rounding, s.grab_rounding, s.scrollbar_rounding = 4, 2, 2
    s.grab_min_size, s.scrollbar_size = 12, 9
    s.window_border_size, s.child_border_size, s.frame_border_size, s.popup_border_size = 0, 1, 1, 1
    s.separator_text_border_size = 1


def apply_theme(name, accent=0):
    """Recolour every token to theme `name` (in place) and the accent, then refresh imgui's colour table."""
    S.theme = name if name in THEMES else "Console"
    S.accent = accent if 0 <= accent < len(ACCENTS) else 0
    values = dict(THEMES[S.theme])
    if ACCENTS[S.accent][1]:
        values["CYAN"] = ACCENTS[S.accent][1]
        # the LCD readouts glow in the same light, lifted a little toward white like a backlit display
        r, g, b_ = (int(ACCENTS[S.accent][1][i:i + 2], 16) for i in (1, 3, 5))
        values["LCD"] = "#" + "".join(f"{round(c + (255 - c) * .25):02x}" for c in (r, g, b_))
    for token, hex_ in values.items():
        c, v = globals()[token], rgb(hex_)
        c.x, c.y, c.z, c.w = v.x, v.y, v.z, 1.0
    s = imgui.get_style()
    for col, c in (
        (imgui.Col_.window_bg, BG), (imgui.Col_.child_bg, CLEAR), (imgui.Col_.popup_bg, POPUP),
        (imgui.Col_.title_bg, PANEL), (imgui.Col_.title_bg_active, KEY_TOP), (imgui.Col_.title_bg_collapsed, PANEL), (imgui.Col_.modal_window_dim_bg, alpha(BG, .6)),
        (imgui.Col_.border, BORDER), (imgui.Col_.border_shadow, CLEAR),
        (imgui.Col_.text, TEXT), (imgui.Col_.text_disabled, DIM),
        (imgui.Col_.frame_bg, FRAME), (imgui.Col_.frame_bg_hovered, FRAME_HI), (imgui.Col_.frame_bg_active, FRAME_ACT),
        (imgui.Col_.button, FRAME), (imgui.Col_.button_hovered, FRAME_HI), (imgui.Col_.button_active, FRAME_ACT),
        (imgui.Col_.header, HEAD), (imgui.Col_.header_hovered, HEAD_HI),
        (imgui.Col_.header_active, HEAD_ACT),
        (imgui.Col_.check_mark, CYAN), (imgui.Col_.slider_grab, GRAB),   # brushed fader caps
        (imgui.Col_.slider_grab_active, GRAB_ACT),
        (imgui.Col_.separator, BORDER), (imgui.Col_.plot_histogram, CYAN),
        (imgui.Col_.scrollbar_bg, CLEAR), (imgui.Col_.scrollbar_grab, SCROLL),
        (imgui.Col_.scrollbar_grab_hovered, SCROLL_HI), (imgui.Col_.scrollbar_grab_active, SCROLL_ACT),
        (imgui.Col_.drag_drop_target, MAGENTA), (imgui.Col_.text_selected_bg, alpha(CYAN, .3)),
        (imgui.Col_.nav_cursor, CYAN),
        (imgui.Col_.resize_grip, CLEAR), (imgui.Col_.resize_grip_hovered, alpha(CYAN, .5)),   # the Settings window
        (imgui.Col_.resize_grip_active, CYAN),
    ):
        s.set_color_(col, c)
    tint_title_bars()


def tint_title_bars():
    """Windows 11: the system title bars (caption, title text, window edge) in the theme's own colours, flowing
    into the top bar; minimise / maximise / close and snap layouts stay Windows' own. Older Windows: dark title
    bars at least."""
    if os.name != "nt" or not S.windows:
        return
    ref = lambda c: int(c.x * 255) | int(c.y * 255) << 8 | int(c.z * 255) << 16   # COLORREF: 0x00BBGGRR
    for win in S.windows:
        try:
            hwnd = wintypes.HWND(glfw.get_win32_window(win))
            for attr, value in ((20, 1), (35, ref(TOPBAR_TOP)), (36, ref(TEXT)), (34, ref(BORDER))):
                v = ctypes.c_uint(value)   # 20 dark mode, 35 caption, 36 title text, 34 border
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
        except (OSError, AttributeError):
            pass


# ---------------------------------------------------------------- widgets

def bold(text, size=16, col=TEXT):
    imgui.push_font(S.bold, size)
    imgui.text_colored(col, text)
    imgui.pop_font()


def label(text):
    """Engraved legend (small capitals) in a fixed left column; the next widget fills the rest of the row."""
    imgui.align_text_to_frame_padding()
    text = text.upper()
    size = 12.5
    imgui.push_font(S.bold, size)
    w = imgui.calc_text_size(text).x
    imgui.pop_font()
    if w > sc(LABEL_W) - 8:   # long legends shrink to fit rather than run into the control
        size *= (sc(LABEL_W) - 8) / w
    p = imgui.get_cursor_screen_pos()
    imgui.push_font(S.bold, size)
    th = imgui.get_text_line_height()
    imgui.pop_font()
    imgui.get_window_draw_list().add_text(S.bold, size * S.scale, V(p.x, p.y + (imgui.get_frame_height() - th) / 2),
                                          u32(DIM), text)
    imgui.dummy(V(1, imgui.get_frame_height()))
    imgui.same_line(sc(LABEL_W))
    imgui.set_next_item_width(-1)


def keycap(dl, mn, mx, hovered=False, held=False, lit=None, rounding=3.0):
    """A hardware key: shaded cap with a lit top edge; `lit` (a colour) adds an LED strip along its foot."""
    top = KEY_HOV if hovered and not held else (FRAME_ACT if held else KEY_TOP)
    dl.add_rect_filled(mn, mx, u32(EDGE_LO), rounding)
    dl.add_rect_filled(V(mn.x + 1, mn.y + 1), V(mx.x - 1, mx.y - 1), u32(KEY_BOT), rounding)
    i = min(rounding * 0.6, 2.0)   # a smooth top-to-bottom shade, inset clear of the rounded corners
    t, bt = u32(top), u32(KEY_BOT)
    dl.add_rect_filled_multi_color(V(mn.x + 1 + i, mn.y + 1 + i), V(mx.x - 1 - i, mx.y - 1 - i), t, t, bt, bt)
    if not held:
        dl.add_line(V(mn.x + 3, mn.y + 1.5), V(mx.x - 3, mn.y + 1.5), u32(EDGE_HI), 1)
    if lit is not None:
        w = mx.x - mn.x
        a, b = V(mn.x + w * 0.18, mx.y - 4), V(mx.x - w * 0.18, mx.y - 2.5)
        dl.add_rect_filled(V(a.x - 2, a.y - 2), V(b.x + 2, b.y + 2), u32(alpha(lit, .18)), 3)   # glow
        dl.add_rect_filled(a, b, u32(lit), 1)


def led(dl, centre, col, on=True, r=3.2):
    """An indicator light: lit with a soft halo, or a dark lens."""
    if on:
        dl.add_circle_filled(centre, r * 2.4, u32(alpha(col, .14)))
        dl.add_circle_filled(centre, r, u32(col))
        dl.add_circle_filled(V(centre.x - r * .3, centre.y - r * .3), r * .35, u32(alpha(WHITE, .6)))
    else:
        dl.add_circle_filled(centre, r, u32(LENS))
        dl.add_circle(centre, r, u32(BORDER), thickness=1)


def header_strip(on, lamp=None):
    """A card's title strip: a raised, shaded band across its top, ruled off from the controls below; a card
    that's on takes on a little of its LED colour `lamp`.
    Call right after begin_child, before the header row (whose height is sc(28))."""
    wp, ww = imgui.get_window_pos(), imgui.get_window_width()
    bot = imgui.get_cursor_screen_pos().y + sc(28) + 3
    top_c, bot_c = (STRIP_ON_TOP, STRIP_ON_BOT) if on else (STRIP_TOP, STRIP_BOT)
    if on and lamp is not None:
        top_c, bot_c = mix_col(top_c, lamp, .22), mix_col(bot_c, lamp, .12)
    dl = imgui.get_window_draw_list()
    dl.add_rect_filled(V(wp.x + 1, wp.y + 1), V(wp.x + ww - 1, bot), u32(bot_c), 3, imgui.ImDrawFlags_.round_top)
    dl.add_rect_filled_multi_color(V(wp.x + 3, wp.y + 2), V(wp.x + ww - 3, bot), u32(top_c), u32(top_c),
                                   u32(bot_c), u32(bot_c))
    dl.add_line(V(wp.x + 4, wp.y + 1.5), V(wp.x + ww - 4, wp.y + 1.5), u32(STRIP_EDGE if on else EDGE_HI), 1)
    dl.add_line(V(wp.x + 1, bot), V(wp.x + ww - 1, bot), u32(EDGE_LO), 1)          # engraved rule
    dl.add_line(V(wp.x + 1, bot + 1), V(wp.x + ww - 1, bot + 1), u32(BORDER), 1)


def mix_col(a, b, t):
    return imgui.ImVec4(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t, a.z + (b.z - a.z) * t, 1.0)


def power_button(on, col, tip):
    """A card's power key: the symbol itself lights in its LED colour, with a soft glow, when on."""
    p, h = imgui.get_cursor_screen_pos(), imgui.get_frame_height()
    if on:   # the glow goes down first, so the symbol sits on top of it
        c = V(p.x + sc(14), p.y + h / 2)
        dl = imgui.get_window_draw_list()
        dl.add_circle_filled(c, h * 0.62, u32(alpha(col, .10)))
        dl.add_circle_filled(c, h * 0.42, u32(alpha(col, .16)))
    return icon_button(fa.ICON_FA_POWER_OFF, "pwr", col if on else alpha(DIM, .7), tip)


def bevel(mn, mx, rounding=4.0, dl=None):
    """Raised-module edge: a lit line along the top inside a dark outline."""
    dl = dl or imgui.get_window_draw_list()
    dl.add_rect(V(mn.x - 1, mn.y - 1), V(mx.x + 1, mx.y + 1), u32(EDGE_LO), rounding=rounding + 1, thickness=1)
    dl.add_line(V(mn.x + rounding, mn.y + 1), V(mx.x - rounding, mn.y + 1), u32(EDGE_HI), 1)


def icon_button(icon, uid, col=DIM, tip=None, size=None, hover_col=None):
    size = size or V(sc(28), 0)
    imgui.push_style_color(imgui.Col_.button, CLEAR)
    imgui.push_style_color(imgui.Col_.button_hovered, alpha(WHITE, .05))
    imgui.push_style_color(imgui.Col_.button_active, alpha(WHITE, .09))
    imgui.push_style_color(imgui.Col_.border, CLEAR)
    imgui.push_style_color(imgui.Col_.text, col)
    clicked = imgui.button(f"{icon}##{uid}", size)
    hovered = imgui.is_item_hovered()
    imgui.pop_style_color(5)
    if hovered and hover_col is not None:  # repaint the glyph in the hover colour
        mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        imgui.get_window_draw_list().add_rect_filled(mn, mx, u32(alpha(hover_col, .15)), 3)
    if tip and hovered:
        imgui.set_tooltip(tip)
    return clicked


def neon_button(text, col=CYAN, size=V(0, 0), active=False, tip=None, flat=False):
    """A hardware key. Active: its LED strip lights in `col`. flat: no cap until hovered (selector segments)."""
    dl = imgui.get_window_draw_list()
    dl.channels_split(2)   # the label first (to learn the size), the cap drawn underneath it after
    dl.channels_set_current(1)
    imgui.push_style_var(imgui.StyleVar_.frame_border_size, 0)
    for c in (imgui.Col_.button, imgui.Col_.button_hovered, imgui.Col_.button_active):
        imgui.push_style_color(c, CLEAR)
    imgui.push_style_color(imgui.Col_.text, TEXT if active else (DIM if flat else KEY_TEXT))
    clicked = imgui.button(text, size)
    imgui.pop_style_color(4)
    imgui.pop_style_var()
    hovered, held = imgui.is_item_hovered(), imgui.is_item_active()
    mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
    dl.channels_set_current(0)
    if not flat or active or hovered:
        keycap(dl, mn, mx, hovered, held, col if active else None)
    dl.channels_merge()
    if tip and hovered:
        imgui.set_tooltip(tip)
    return clicked


def segmented(uid, options, current, col=CYAN, width=-1.0):
    """A selector: one recessed strip of keys, the chosen one raised and lit."""
    avail = imgui.get_content_region_avail().x if width < 0 else width
    gap = 2
    w = (avail - 4 - gap * (len(options) - 1)) / len(options)
    p, h = imgui.get_cursor_screen_pos(), imgui.get_frame_height()
    dl = imgui.get_window_draw_list()
    dl.add_rect_filled(p, V(p.x + avail, p.y + h), u32(FRAME), 3)
    dl.add_rect(p, V(p.x + avail, p.y + h), u32(BORDER), 3)
    imgui.push_style_var(imgui.StyleVar_.frame_padding, V(4, imgui.get_style().frame_padding.y - 2))
    imgui.set_cursor_screen_pos(V(p.x + 2, p.y + 2))
    for i, opt in enumerate(options):
        if i:
            imgui.same_line(0, gap)
        if neon_button(f"{opt}##{uid}{i}", col, V(w, h - 4), active=(i == current), flat=True):
            current = i
    imgui.pop_style_var()
    imgui.set_cursor_screen_pos(p)
    imgui.dummy(V(avail, h))
    return current


def meter(frac, col, width=-1.0, height=4.0):
    """An LED bar meter: a row of small segments that light up to frac."""
    p = imgui.get_cursor_screen_pos()
    w = imgui.get_content_region_avail().x if width < 0 else width
    dl = imgui.get_window_draw_list()
    seg, gap = max(3.0, height * 1.5), 1.5
    n = max(1, int((w + gap) // (seg + gap)))
    lit = min(1.0, max(0.0, frac)) * n
    for i in range(n):
        x = p.x + i * (seg + gap)
        on = i < lit
        dl.add_rect_filled(V(x, p.y), V(x + seg, p.y + height), u32(col if on else SEG_OFF), 1)
    imgui.dummy(V(w, height))


_slider_start = {}   # value each slider had when last clicked, so a double-click doesn't keep the first click's jump
_typing = set()      # sliders currently showing their type-a-value box


def typeable(widget, default_fmt=None):
    """Wrap an imgui slider so double-clicking it opens a box to type an exact value (Ctrl+click works too).
    With default_fmt (single-value sliders), the number is drawn on whichever side the handle isn't."""
    def wrapped(label_, value, *args, **kw):
        target = slider_target(label_) if S.app and S.app.midi_learn else None
        if target:
            imgui.begin_disabled()
            changed, new = wrapped_inner(label_, value, *args, **kw)
            imgui.end_disabled()
            if target[1] == "centre":   # one widget, two values: the left half is x, the right half y
                midi_spot(S.app, (target[0], "cx"), (0, 2))
                midi_spot(S.app, (target[0], "cy"), (1, 2))
            else:
                midi_spot(S.app, target)
            if target[0] != "app" and imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled)                     and imgui.is_mouse_clicked(1):
                S.app.learn_target = (target[0], f"auto_{target[1]}")   # right-click: its automation on/off
            return False, value
        return wrapped_inner(label_, value, *args, **kw)

    def wrapped_inner(label_, value, *args, **kw):
        box_w = sc(70)
        boxed = bool(S.num_boxes and default_fmt is not None and imgui.calc_item_width() >= sc(210))
        if boxed:   # leave room for a number box after the slider, inside the width it was given
            imgui.set_next_item_width(imgui.calc_item_width() - box_w - 4)
        own = default_fmt is not None and imgui.get_id(label_) not in _typing
        if own:   # imgui centres the number, right where the handle sits at mid values; hide it, draw our own
            imgui.push_style_color(imgui.Col_.text, CLEAR)
        changed, new = widget(label_, value, *args, **kw)
        key = imgui.get_item_id()
        if own:
            imgui.pop_style_color()
            if not boxed:   # with a number box beside it, the box shows the value
                slider_value_text(new, args, kw, default_fmt)
        if imgui.is_item_active() and imgui.get_io().want_text_input:
            _typing.add(key)
        else:
            _typing.discard(key)
        if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
            new, changed = _slider_start.get(key, value), True
            imgui.set_keyboard_focus_here(-1)
        elif imgui.is_item_activated():
            _slider_start[key] = value
        if boxed:   # the number box: type a value and press Enter (or click away); kept within the slider's range
            fmt = args[2] if len(args) > 2 else kw.get("format", default_fmt)
            found = re.search(r"%[-+0-9.]*[dfgeE]", fmt or "")
            num_fmt = found.group(0) if found else "%.3f"
            lo, hi = args[0], args[1]
            imgui.same_line(0, 4)
            imgui.set_next_item_width(box_w)
            flags = imgui.InputTextFlags_.enter_returns_true | imgui.InputTextFlags_.auto_select_all
            if default_fmt == "%d":
                typed, v2 = imgui.input_int(f"##nb_{label_}", int(new), 0, 0, flags)
            else:
                typed, v2 = imgui.input_float(f"##nb_{label_}", float(new), 0.0, 0.0, num_fmt, flags)
            if typed:
                new, changed = type(value)(min(max(v2, min(lo, hi)), max(lo, hi))), True
        return changed, new
    return wrapped


def slider_target(label_):
    """The MIDI target (scope, key) of a slider, from where it's drawn and its label; None if not mappable."""
    key = label_.lstrip("#")
    if S.midi_scope and (key in ("amt", "opacity", "speed", "xs", "xr", "centre")
                         or (key[:1] == "p" and key[1:].isdigit())):
        return (S.midi_scope, key)
    if not S.midi_scope and key in ("gain", "ttime", "xfade"):
        return ("app", key)
    return None


def midi_spot(app, target, part=None):
    """MIDI learn on the control just drawn: outline it, tag it with its link, and pick it on click.
    part = (i, n): the control holds n values side by side (Centre x / y) and this is the i-th of them."""
    if not app.midi_learn or target is None:
        return
    mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
    if part:
        w = (mx.x - mn.x) / part[1]
        mn, mx = V(mn.x + w * part[0] + (2 if part[0] else 0), mn.y), V(mn.x + w * (part[0] + 1) - 2, mx.y)
    dl = imgui.get_window_draw_list()
    chosen = app.learn_target == tuple(target)
    src = app.midi_binding(target)
    col = AMBER if chosen else (CYAN if src else alpha(AMBER, .35))
    dl.add_rect(V(mn.x - 1, mn.y - 1), V(mx.x + 1, mx.y + 1), u32(col), rounding=3, thickness=2 if chosen else 1)
    if src:
        tag = app.midi_name(src)
        imgui.push_font(S.bold, 11)
        tw = imgui.calc_text_size(tag).x
        imgui.pop_font()
        a = V(mx.x - tw - 8, mn.y - 7)
        dl.add_rect_filled(a, V(mx.x - 2, mn.y + 7), u32(BEZEL), 2)
        dl.add_text(S.bold, 11 * S.scale, V(a.x + 3, a.y + 1), u32(CYAN), tag)
    if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled) and imgui.is_mouse_clicked(0) and             (not part or mn.x <= imgui.get_io().mouse_pos.x < mx.x + 2):
        app.learn_target = tuple(target)


def slider_value_text(value, args, kw, default_fmt):
    """The slider's number, left-aligned, or right-aligned while the handle is on the left."""
    lo, hi = args[0], args[1]
    fmt = args[2] if len(args) > 2 else kw.get("format", default_fmt)
    flags = args[3] if len(args) > 3 else kw.get("flags", 0)
    try:
        text = fmt % value
    except (TypeError, ValueError):
        text = str(value)
    if flags & imgui.SliderFlags_.logarithmic and lo > 0 and value > 0:
        import math
        frac = math.log(value / lo) / math.log(hi / lo)
    else:
        frac = (value - lo) / (hi - lo) if hi != lo else 0.0
    frac = min(1.0, max(0.0, frac))
    mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
    style = imgui.get_style()
    pad = style.frame_padding.x + 2
    tw, th = imgui.calc_text_size(text).x, imgui.get_text_line_height()
    grab = max(style.grab_min_size, 10) / 2 + 4
    grab_x = mn.x + pad + frac * (mx.x - mn.x - 2 * pad)
    x = mn.x + pad if grab_x - grab > mn.x + pad + tw else mx.x - pad - tw
    dl = imgui.get_window_draw_list()
    dl.add_line(V(mn.x + 3, mx.y - 2.5), V(max(mn.x + 3, grab_x - 6), mx.y - 2.5), u32(alpha(CYAN, .55)), 2)
    dl.add_line(V(grab_x, mn.y + 5), V(grab_x, mx.y - 5), u32(GROOVE), 1)   # the cap's centre groove
    dl.add_text(S.mono, 16 * S.scale, V(x, mn.y + (mx.y - mn.y - th) / 2), u32(TEXT), text)


slider_float, slider_int = typeable(imgui.slider_float, "%.3f"), typeable(imgui.slider_int, "%d")
slider_float2 = typeable(imgui.slider_float2)


def section(title, icon):
    imgui.spacing()
    imgui.push_font(S.bold, 13)
    imgui.push_style_color(imgui.Col_.header, CLEAR)
    imgui.push_style_color(imgui.Col_.header_hovered, alpha(WHITE, .03))
    imgui.push_style_color(imgui.Col_.header_active, alpha(WHITE, .05))
    imgui.push_style_color(imgui.Col_.text, DIM)
    opened = imgui.collapsing_header(f"{icon}   {title.upper()}##sec_{title}", imgui.TreeNodeFlags_.default_open)
    imgui.pop_style_color(4)
    imgui.pop_font()
    mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
    dl = imgui.get_window_draw_list()
    dl.add_line(V(mn.x, mx.y), V(mx.x, mx.y), u32(EDGE_LO), 1)          # an engraved rule
    dl.add_line(V(mn.x, mx.y + 1), V(mx.x, mx.y + 1), u32(BORDER), 1)
    if opened:
        imgui.spacing()
    return opened


# ---------------------------------------------------------------- top level

def draw(app):
    S.app = app
    reorder_begin_frame(app)
    shortcuts(app)
    vp = imgui.get_main_viewport()
    imgui.set_next_window_pos(vp.pos)
    imgui.set_next_window_size(vp.size)
    imgui.push_style_var(imgui.StyleVar_.window_padding, V(0, 0))
    imgui.begin("Lumoria", None, imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.no_move
                | imgui.WindowFlags_.no_saved_settings | imgui.WindowFlags_.no_bring_to_front_on_focus
                | imgui.WindowFlags_.no_scrollbar | imgui.WindowFlags_.no_scroll_with_mouse)
    imgui.pop_style_var()

    W, H = vp.size.x, vp.size.y
    imgui.get_style().font_scale_main = S.scale
    io = imgui.get_io()
    if io.key_ctrl and io.mouse_wheel:   # Ctrl + wheel zooms the whole interface
        S.scale = min(1.6, max(0.7, round(S.scale + io.mouse_wheel * 0.05, 2)))
        save_layout()

    tb = max(sc(TOPBAR_H), S.topbar_h)   # the top bar grows when a narrow window stacks its keys
    panel_flags = imgui.ChildFlags_.always_use_window_padding
    imgui.set_cursor_pos(V(0, 0))
    imgui.push_style_color(imgui.Col_.child_bg, PANEL)
    imgui.push_style_var(imgui.StyleVar_.window_padding, V(16, 10))
    imgui.begin_child("topbar", V(W, tb), panel_flags, imgui.WindowFlags_.no_scrollbar)
    p = imgui.get_window_pos()
    imgui.get_window_draw_list().add_rect_filled_multi_color(p, V(p.x + W, p.y + tb), u32(TOPBAR_TOP),
                                                             u32(TOPBAR_TOP), u32(PANEL), u32(PANEL))
    top_bar(app)
    imgui.end_child()
    imgui.pop_style_var()
    imgui.pop_style_color()

    if S.layout == 1:
        imgui.get_window_draw_list().add_line(V(0, tb), V(W, tb), u32(BORDER), 1)
        custom_layout(app, W, H, tb)   # ends the main window itself, then draws the panels
    else:
        classic_layout(app, W, H, tb)
        imgui.end()
    settings_window(app, W, H, tb)

    restore_prompt(app)
    welcome(app)
    delete_prompt(app)
    keys_sheet()
    reorder_ghost()

    if S.pending_move:   # applied after drawing so lists don't change mid-loop
        uid, dest, index = S.pending_move
        S.pending_move = None
        if (item := app.pipe.find(uid)) is not None and item is not (dest[index] if index is not None
                                                                       and index < len(dest) else None):
            app.pipe.move_item(item, dest, index)


def classic_layout(app, W, H, tb):
    """Today's fixed layout: the sidebar on the left, the preview beside it, the playlist along the bottom."""
    io = imgui.get_io()
    S.sidebar_w = min(max(S.sidebar_w, sc(280)), max(sc(280), W - 320))
    S.playlist_h = min(max(S.playlist_h, sc(130)), max(sc(130), H - tb - 220))
    pl_h = S.playlist_h if S.playlist_open else sc(PLAYLIST_SHUT_H)
    sw, mid_h = S.sidebar_w, max(50, H - tb - GAP - pl_h)
    panel_flags = imgui.ChildFlags_.always_use_window_padding

    imgui.push_style_color(imgui.Col_.child_bg, PANEL)
    imgui.set_cursor_pos(V(0, tb))
    imgui.begin_child("sidebar", V(sw, mid_h), panel_flags)
    sidebar(app)
    imgui.end_child()
    imgui.pop_style_color()

    imgui.set_cursor_pos(V(sw + GAP, tb))
    imgui.begin_child("preview", V(W - sw - GAP, mid_h), 0, imgui.WindowFlags_.no_scrollbar)
    preview(app)
    imgui.end_child()

    imgui.set_cursor_pos(V(0, tb + mid_h + GAP))
    imgui.push_style_color(imgui.Col_.child_bg, PANEL)
    imgui.push_style_var(imgui.StyleVar_.window_padding, V(16, 10))
    imgui.begin_child("playlist", V(W, pl_h), panel_flags, imgui.WindowFlags_.no_scrollbar)
    playlist_panel(app, pl_h)
    imgui.end_child()
    imgui.pop_style_var()
    imgui.pop_style_color()

    # drag seams between panels (they sit in the gaps, so the panels don't steal the mouse)
    dl = imgui.get_window_draw_list()
    dl.add_line(V(0, tb), V(W, tb), u32(BORDER), 1)
    if splitter("vsplit", V(sw, tb), V(GAP, mid_h), imgui.MouseCursor_.resize_ew, dl, vertical=True):
        S.sidebar_w += io.mouse_delta.x
    if splitter("hsplit", V(0, tb + mid_h), V(W, GAP), imgui.MouseCursor_.resize_ns, dl, vertical=False,
                enabled=S.playlist_open):
        S.playlist_h -= io.mouse_delta.y


# ---------------------------------------------------------------- custom layout (floating panels that snap)

PANELS = (("inputs", "Inputs", fa.ICON_FA_VIDEO), ("effects", "Effects", fa.ICON_FA_LAYER_GROUP),
          ("preview", "Preview", fa.ICON_FA_DISPLAY), ("playlist", "Playlist", fa.ICON_FA_LIST))
PANEL_MIN = {"inputs": (220, 120), "effects": (240, 140), "preview": (200, 120), "playlist": (300, 150)}
SNAP = 14       # how close (px) an edge has to come to another edge to snap onto it
PANEL_EDGE = 6  # the grab band along each panel edge, for resizing
PANEL_HEAD = 26


def default_rects(W, H):
    """The Custom layout's starting arrangement (like Classic): Inputs over Effects on the left, the preview beside
    them, the playlist along the bottom. Pixel rects [x, y, w, h] in the area under the top bar."""
    g = GAP
    sw = round(min(max(S.sidebar_w, sc(280)), W * .45))
    ph = round(min(max(S.playlist_h, sc(230)), H * .5))
    top = H - ph - g
    ih = round(top * .42)
    return {"inputs": [0, 0, sw, ih], "effects": [0, ih + g, sw, top - ih - g],
            "preview": [sw + g, 0, W - sw - g, top], "playlist": [0, top + g, W, ph]}


def panel_rects(W, H):
    """The saved arrangement (kept as fractions of the area, so it follows the window's size), in pixels."""
    rects = default_rects(W, H)
    for key, r in (S.panels or {}).items():
        if key in rects and isinstance(r, (list, tuple)) and len(r) == 4:
            try:
                x, y, w, h = (float(v) for v in r)
            except (TypeError, ValueError):
                continue
            rects[key] = [round(x * W), round(y * H), round(w * W), round(h * H)]
    for key, r in rects.items():   # always on screen and never smaller than its minimum
        mw, mh = (min(sc(v), lim) for v, lim in zip(PANEL_MIN[key], (W, H)))
        r[2], r[3] = max(mw, min(r[2], W)), max(mh, min(r[3], H))
        r[0], r[1] = max(0, min(r[0], W - r[2])), max(0, min(r[1], H - r[3]))
    return rects


def store_rects(rects, W, H):
    S.panels = {k: [r[0] / W, r[1] / H, r[2] / W, r[3] / H] for k, r in rects.items()}
    save_layout()


def panel_min(key, axis):
    return sc(PANEL_MIN[key][axis])


def near(r, o, axis, reach):
    """Do r and o overlap along `axis`, or come within `reach` of it?"""
    return r[axis] - reach <= o[axis] + o[axis + 2] and o[axis] - reach <= r[axis] + r[axis + 2]


def snap_targets(rects, skip, r, axis, size):
    """Where an edge along `axis` may snap: the area's own edges, and each nearby panel's edges - flush against it
    (with the usual gap) or lined up with it. (position, kind, whether that panel is beside this one)"""
    out = [(0.0, "edge", False), (float(size), "edge", False)]
    other = 1 - axis
    for k, o in rects.items():
        if k in skip:
            continue
        lo, hi = o[axis], o[axis] + o[axis + 2]
        touching = near(r, o, other, sc(SNAP))
        if touching:                      # side by side: flush against it
            out += [(hi + GAP, "after", True), (lo - GAP, "before", True)]
        if near(r, o, other, sc(80)):     # close by: line up with its edges
            out += [(lo, "align_lo", touching), (hi, "align_hi", touching)]
    return out


def best_snap(edges, targets, reach):
    """edges: (position, which end: 0 low / 1 high). The closest edge-to-target match within reach:
    (shift, target position) or None. A low edge doesn't take 'before' spots and a high edge doesn't take 'after'
    ones, and beside a panel an edge doesn't line up with that panel's far edge, so panels never snap on top of each
    other."""
    best = None
    for e, end in edges:
        for t, kind, touching in targets:
            if (kind == "before" and end == 0) or (kind == "after" and end == 1):
                continue
            if touching and ((kind == "align_hi" and end == 0) or (kind == "align_lo" and end == 1)):
                continue
            d = t - e
            if abs(d) <= reach and (best is None or abs(d) < abs(best[0])):
                best = (d, t)
    return best


def seam_members(rects, key, axis, side, solo):
    """An edge being dragged, and every edge that touches it in one line (panels flush against it, and panels
    lined up with it that touch those), so a seam between panels moves as one. (panel, side) pairs."""
    r = rects[key]
    s = r[axis] + (r[axis + 2] if side else 0)
    members = [(key, side)]
    if solo:
        return members
    tol = 3
    other = 1 - axis
    changed = True
    while changed:
        changed = False
        for k, o in rects.items():
            for sd in (0, 1):
                if (k, sd) in members:
                    continue
                e = o[axis] + (o[axis + 2] if sd else 0)
                want = s if sd == side else (s + GAP if side else s - GAP)
                if abs(e - want) > tol:
                    continue
                if any(near(rects[m], o, other, GAP + tol) for m, _ in members):
                    members.append((k, sd))
                    changed = True
    return members


def panel_drag_update(rects, W, H):
    """Apply the move or resize in progress (S.pdrag) to rects, snapping edges. Returns guide lines to draw:
    (axis, position, from, to)."""
    d = S.pdrag
    io = imgui.get_io()
    delta = (io.mouse_pos.x - d["m0"][0], io.mouse_pos.y - d["m0"][1])
    size = (W, H)
    guides = []
    base = d["r0"]
    for k in rects:
        rects[k] = list(base[k])
    key = d["key"]
    r = rects[key]
    if d["sides"] is None:   # moving: both axes, either edge may snap
        for axis in (0, 1):
            r[axis] = base[key][axis] + delta[axis]
            r[axis] = max(0, min(r[axis], size[axis] - r[axis + 2]))
            if not io.key_shift:   # Shift: no snapping
                tg = snap_targets(rects, {key}, r, axis, size[axis])
                hit = best_snap(((r[axis], 0), (r[axis] + r[axis + 2], 1)), tg, sc(SNAP))
                if hit:
                    r[axis] += hit[0]
                    guides.append((axis, hit[1]))
            r[axis] = max(0, min(r[axis], size[axis] - r[axis + 2]))
    else:                    # resizing: the dragged edge(s), and the seam they're part of
        for axis, side in d["sides"].items():
            members = d["seams"][axis]
            s0 = base[key][axis] + (base[key][axis + 2] if side else 0)
            s = s0 + delta[axis]
            if not io.key_shift:
                tg = snap_targets(rects, {m for m, _ in members}, r, axis, size[axis])
                hit = best_snap(((s, side),), tg, sc(SNAP))
                if hit:
                    s += hit[0]
                    guides.append((axis, hit[1]))
            lo_lim, hi_lim = -1e9, 1e9   # keep every member inside the area and at least its minimum size
            for m, sd in members:
                b = base[m]
                off = 0 if sd == side else (GAP if side else -GAP)
                if sd:   # its high edge sits at s + off
                    lo_lim = max(lo_lim, b[axis] + panel_min(m, axis) - off)
                    hi_lim = min(hi_lim, size[axis] - off)
                else:    # its low edge sits at s + off
                    hi_lim = min(hi_lim, b[axis] + b[axis + 2] - panel_min(m, axis) - off)
                    lo_lim = max(lo_lim, -off)
            s = max(lo_lim, min(s, hi_lim)) if lo_lim <= hi_lim else s0
            for m, sd in members:
                b, rm = base[m], rects[m]
                e = s + (0 if sd == side else (GAP if side else -GAP))
                if sd:
                    rm[axis + 2] = e - b[axis]
                else:
                    rm[axis], rm[axis + 2] = e, b[axis] + b[axis + 2] - e
    out = []
    for axis, pos in guides:   # a line along the snapped edge, across the panels it lines up with
        span = [rects[key][1 - axis], rects[key][1 - axis] + rects[key][3 - axis]]
        for o in rects.values():
            if abs(o[axis] - pos) < 2 or abs(o[axis] + o[axis + 2] - pos) < 2 \
                    or abs(o[axis] - GAP - pos) < 2 or abs(o[axis] + o[axis + 2] + GAP - pos) < 2:
                span = [min(span[0], o[1 - axis]), max(span[1], o[1 - axis] + o[3 - axis])]
        out.append((axis, pos, span[0], span[1]))
    return out


def shut_rects(full, H):
    """The panels as shown: a folded panel is just its title strip (at the bottom of its spot when it sits on the
    window's bottom edge, else at the top), and the panels flush against the freed side grow into the room."""
    rects = {k: list(r) for k, r in full.items()}
    hh = sc(PANEL_HEAD) + 2
    for key in S.panels_shut:
        if key not in rects:
            continue
        r = full[key]
        down = r[1] + r[3] >= H - 3
        if down:
            rects[key] = [r[0], r[1] + r[3] - hh, r[2], hh]
        else:
            rects[key] = [r[0], r[1], r[2], hh]
        for k, o in full.items():   # neighbours flush against the freed side, and no wider than it, take the room
            if k == key or k in S.panels_shut or o[0] < r[0] - 3 or o[0] + o[2] > r[0] + r[2] + 3:
                continue
            if not down and abs(o[1] - (r[1] + r[3] + GAP)) <= 3:
                bottom = rects[k][1] + rects[k][3]
                rects[k][1] = r[1] + hh + GAP
                rects[k][3] = bottom - rects[k][1]
            elif down and abs(o[1] + o[3] + GAP - r[1]) <= 3:
                rects[k][3] = r[1] + r[3] - hh - GAP - rects[k][1]
    return rects


def toggle_shut(key):
    if key in S.panels_shut:
        S.panels_shut = [k for k in S.panels_shut if k != key]
    else:
        S.panels_shut = S.panels_shut + [key]
    save_layout()


def panel_frame(key, title, icon, r, ox, oy, rects):
    """A panel's border, its title strip (drag it to move the panel; the arrow or a double-click folds it) and the
    grab bands along its edges (drag to resize). Starts S.pdrag when one is pressed."""
    x0, y0, x1, y1 = ox + r[0], oy + r[1], ox + r[0] + r[2], oy + r[1] + r[3]
    dl = imgui.get_window_draw_list()
    hh, e = sc(PANEL_HEAD), PANEL_EDGE
    busy = S.pdrag is not None and S.pdrag["key"] == key
    shut = key in S.panels_shut
    # title strip
    dl.add_rect_filled_multi_color(V(x0 + 1, y0 + 1), V(x1 - 1, y0 + hh), u32(TOPBAR_TOP), u32(TOPBAR_TOP),
                                   u32(PANEL), u32(PANEL))
    dl.add_line(V(x0 + 1, y0 + hh), V(x1 - 1, y0 + hh), u32(EDGE_LO), 1)
    dl.add_line(V(x0 + 1, y0 + hh + 1), V(x1 - 1, y0 + hh + 1), u32(BORDER), 1)
    imgui.push_font(S.bold, 12.5)
    th = imgui.get_text_line_height()
    arrow = fa.ICON_FA_CHEVRON_RIGHT if shut else fa.ICON_FA_CHEVRON_DOWN
    ax = x0 + sc(10)
    imgui.set_cursor_screen_pos(V(ax - 4, y0 + 3))
    imgui.invisible_button("##fold", V(sc(20), hh - 4))
    hot = imgui.is_item_hovered()
    if imgui.is_item_clicked(0):
        toggle_shut(key)
    if hot:
        imgui.set_tooltip(f"Show the {title} panel" if shut else f"Fold the {title} panel down to its title")
    imgui.push_font(S.bold, 10)
    aw = imgui.calc_text_size(arrow)
    dl.add_text(V(ax + (sc(12) - aw.x) / 2, y0 + (hh - aw.y) / 2 + 1), u32(TEXT if hot else DIM), arrow)
    imgui.pop_font()
    dl.add_text(V(x0 + sc(30), y0 + (hh - th) / 2 + 1), u32(TEXT if busy else DIM), f"{icon}   {title.upper()}")
    imgui.pop_font()
    for i in range(3):   # grip dots on the right: this is the handle
        dl.add_circle_filled(V(x1 - sc(16) - i * 6, y0 + hh / 2), 1.6, u32(alpha(DIM, .7)))
    # border: a lit outline while it's being moved or resized
    dl.add_rect(V(x0, y0), V(x1, y1), u32(CYAN if busy else BORDER), 4, thickness=2 if busy else 1)
    dl.add_line(V(x0 + 4, y0 + 1), V(x1 - 4, y0 + 1), u32(EDGE_HI), 1)

    def grab(uid, a, b, cursor, sides):
        imgui.set_cursor_screen_pos(a)
        imgui.invisible_button(f"##{uid}", V(max(1, b.x - a.x), max(1, b.y - a.y)))
        if imgui.is_item_hovered() or imgui.is_item_active():
            imgui.set_mouse_cursor(cursor)
        if imgui.is_item_activated():
            io = imgui.get_io()
            seams = {axis: seam_members(rects, key, axis, side, io.key_alt) for axis, side in (sides or {}).items()}
            S.pdrag = dict(key=key, sides=sides, seams=seams, m0=(io.mouse_pos.x, io.mouse_pos.y),
                           r0={k: list(v) for k, v in rects.items()})
    c = e * 2
    MC = imgui.MouseCursor_
    # corners first (the first item under the mouse wins), then edges, then the title strip
    if shut:   # folded: it can still move and be made wider, not taller
        grab("w", V(x0, y0), V(x0 + e, y1), MC.resize_ew, {0: 0})
        grab("e", V(x1 - e, y0), V(x1, y1), MC.resize_ew, {0: 1})
    else:
        grab("nw", V(x0, y0), V(x0 + c, y0 + c), MC.resize_nwse, {0: 0, 1: 0})
        grab("ne", V(x1 - c, y0), V(x1, y0 + c), MC.resize_nesw, {0: 1, 1: 0})
        grab("sw", V(x0, y1 - c), V(x0 + c, y1), MC.resize_nesw, {0: 0, 1: 1})
        grab("se", V(x1 - c, y1 - c), V(x1, y1), MC.resize_nwse, {0: 1, 1: 1})
        grab("n", V(x0 + c, y0), V(x1 - c, y0 + e - 2), MC.resize_ns, {1: 0})
        grab("s", V(x0 + c, y1 - e), V(x1 - c, y1), MC.resize_ns, {1: 1})
        grab("w", V(x0, y0 + c), V(x0 + e, y1 - c), MC.resize_ew, {0: 0})
        grab("e", V(x1 - e, y0 + c), V(x1, y1 - c), MC.resize_ew, {0: 1})
    grab("move", V(x0 + e, y0 + e - 2), V(x1 - e, y0 + hh), MC.hand, None)
    if imgui.is_item_hovered() and imgui.is_mouse_double_clicked(0):
        S.pdrag = None
        toggle_shut(key)
    if imgui.is_item_hovered(imgui.HoveredFlags_.delay_normal) and not S.pdrag:
        imgui.set_tooltip("Drag to move: edges snap to other panels and the window (Shift: no snapping)" + chr(10) +
                          "Drag a panel's edge to resize it; panels joined to that edge follow (Alt: just this one)"
                          + chr(10) + "Double-click (or the arrow) to fold it down to its title")
    return V(x0 + e, y0 + hh + 2), V(x1 - e, y1 - e)


def panel_body(app, key):
    if key == "inputs":
        settings_cards("inputs", [("Input", fa.ICON_FA_VIDEO, lambda: input_section(app)),
                                  ("Audio", fa.ICON_FA_MUSIC, lambda: audio_section(app))])
    elif key == "effects":
        effects_section(app)
    elif key == "preview":
        preview(app)
    else:
        flow_start()
        transport_buttons(app, flow)
        auto_controls(app, flow)
        tempo_strip(app, flow)
        look_file_buttons(app, flow)
        imgui.spacing()
        tiles(app, 0)


def flow_start():
    S.flow_first = True


def flow(w, gap=-1):
    """Custom layout: put the next item (w wide) beside the last one if it fits, else on a new line."""
    if S.flow_first:
        S.flow_first = False
        return
    imgui.same_line(0, gap)
    if imgui.get_content_region_avail().x < w:
        imgui.new_line()


def custom_layout(app, W, H, tb):
    """Every section is a panel you can move (by its title strip) and resize (by its edges) anywhere under the top
    bar. Edges snap onto the other panels' edges - flush beside them or lined up with them - and onto the window's.
    The arrangement is kept in ui_settings.json."""
    imgui.end()   # the main window: the panels are windows of their own, over it
    vp = imgui.get_main_viewport()
    ox, oy, ah = vp.pos.x, vp.pos.y + tb, H - tb
    full = panel_rects(W, ah)
    rects = shut_rects(full, ah)
    shown = {k: list(r) for k, r in rects.items()}
    guides = []
    if S.pdrag:
        guides = panel_drag_update(rects, W, ah)
        if not imgui.is_mouse_down(0):   # let go: keep the new arrangement (a folded panel keeps its full size)
            S.pdrag = None
            for k, r in full.items():
                for i in range(4):
                    r[i] += rects[k][i] - shown[k][i]
            store_rects(full, W, ah)
            guides = []
    flags = (imgui.WindowFlags_.no_title_bar | imgui.WindowFlags_.no_move | imgui.WindowFlags_.no_resize
             | imgui.WindowFlags_.no_collapse | imgui.WindowFlags_.no_saved_settings
             | imgui.WindowFlags_.no_scrollbar | imgui.WindowFlags_.no_scroll_with_mouse)
    for key, title, icon in PANELS:
        r = rects[key]
        imgui.set_next_window_pos(V(ox + r[0], oy + r[1]))
        imgui.set_next_window_size(V(r[2], r[3]))
        imgui.push_style_color(imgui.Col_.window_bg, PANEL)
        imgui.push_style_var(imgui.StyleVar_.window_padding, V(0, 0))
        imgui.push_style_var(imgui.StyleVar_.window_rounding, 4)
        imgui.begin(f"##panel_{key}", None, flags)
        imgui.pop_style_var(2)
        imgui.pop_style_color()
        a, b = panel_frame(key, title, icon, r, ox, oy, rects)
        if key in S.panels_shut:
            imgui.end()
            continue
        imgui.set_cursor_screen_pos(a)
        pad = V(0, 0) if key == "preview" else V(12, 8) if key == "playlist" else V(12, 10)
        imgui.push_style_var(imgui.StyleVar_.window_padding, pad)
        if key == "preview":
            imgui.push_style_color(imgui.Col_.child_bg, BG)
        body_flags = (imgui.WindowFlags_.no_scrollbar | imgui.WindowFlags_.no_scroll_with_mouse
                      if key in ("preview", "playlist") else 0)
        imgui.begin_child("body", V(max(1, b.x - a.x), max(1, b.y - a.y)),
                          imgui.ChildFlags_.always_use_window_padding, body_flags)
        if key == "preview":
            imgui.pop_style_color()
        imgui.pop_style_var()
        imgui.push_id(key)
        panel_body(app, key)
        imgui.pop_id()
        imgui.end_child()
        imgui.end()

    fg = imgui.get_foreground_draw_list()
    for axis, pos, lo, hi in guides:   # what a moving edge has locked onto
        if axis == 0:
            fg.add_line(V(ox + pos, oy + lo - 8), V(ox + pos, oy + hi + 8), u32(alpha(CYAN, .8)), 2)
        else:
            fg.add_line(V(ox + lo - 8, oy + pos), V(ox + hi + 8, oy + pos), u32(alpha(CYAN, .8)), 2)

    # opened here, beside the panels, so Ctrl+S always works
    if S.open_save:
        S.open_save = False
        S.save_name = f"Look {len(app.playlist) + 1}"
        imgui.open_popup("save_look")
    save_popup(app)


def settings_window(app, W, H, tb):
    """Settings drops down under its top-bar button (or opens from File) as a short menu of sections, all folded.
    Clicking one opens it in a panel to the right of the menu; opening another closes it (clicking the open one
    again folds it). The whole thing folds away with the button, Esc, or a click anywhere outside it (not while a
    menu inside it is open, or during MIDI learn)."""
    if not S.settings_open:
        S.settings_page = None   # folded again next time
        return
    vp = imgui.get_main_viewport()
    pages = settings_list(app)
    mw = min(sc(210), W - 16)
    if S.settings_btn:
        bmin, bmax = S.settings_btn
        x, y = max(vp.pos.x + 8, min(bmin.x, vp.pos.x + W - mw - 8)), bmax.y + 6
    else:
        x, y = vp.pos.x + 8, vp.pos.y + tb
    page = next((p for p in pages if p[0] == S.settings_page), None)
    pw = min(sc(480), max(sc(300), W - mw - 20))   # the open section's panel, beside the menu
    if page is not None:   # make room for it: the menu moves left as far as it has to
        x = max(vp.pos.x + 8, min(x, vp.pos.x + W - mw - 4 - pw - 8))
    row_h = imgui.get_frame_height() + sc(6)
    mh = min(len(pages) * (row_h + 2) + 20, vp.pos.y + H - y - 8)
    if S.settings_focus:
        imgui.set_next_window_focus()
        S.settings_focus = False
    flags = (imgui.WindowFlags_.no_title_bar | imgui.WindowFlags_.no_move | imgui.WindowFlags_.no_resize
             | imgui.WindowFlags_.no_collapse | imgui.WindowFlags_.no_saved_settings)

    def begin_drop(name, pos, size):
        imgui.set_next_window_pos(pos)
        imgui.set_next_window_size(size)
        imgui.push_style_color(imgui.Col_.window_bg, PANEL)
        imgui.push_style_color(imgui.Col_.border, BORDER)
        imgui.push_style_var(imgui.StyleVar_.window_border_size, 1)
        imgui.push_style_var(imgui.StyleVar_.window_rounding, 4)
        imgui.push_style_var(imgui.StyleVar_.window_padding, V(8, 10) if name == "##settings_drop" else V(12, 10))
        imgui.begin(name, None, flags)
        imgui.pop_style_var(3)
        imgui.pop_style_color(2)

    # the menu: one row per section, folded; the open one is lit, with its arrow pointing at its panel
    begin_drop("##settings_drop", V(x, y), V(mw, mh))
    pos = imgui.get_window_pos()
    if S.settings_btn:   # a little notch pointing up at the button
        cx = (S.settings_btn[0].x + S.settings_btn[1].x) / 2
        if pos.x + 12 < cx < pos.x + mw - 12:
            fg = imgui.get_foreground_draw_list()
            fg.add_triangle_filled(V(cx - 7, pos.y + 1), V(cx + 7, pos.y + 1), V(cx, pos.y - 6), u32(PANEL))
            fg.add_line(V(cx - 7, pos.y), V(cx, pos.y - 6), u32(BORDER), 1)
            fg.add_line(V(cx, pos.y - 6), V(cx + 7, pos.y), u32(BORDER), 1)
    imgui.push_style_var(imgui.StyleVar_.item_spacing, V(4, 2))
    for title, icon, _ in pages:
        on = S.settings_page == title
        imgui.push_style_color(imgui.Col_.header, alpha(CYAN, .14))
        imgui.push_style_color(imgui.Col_.header_hovered, alpha(CYAN, .08) if not on else alpha(CYAN, .18))
        imgui.push_style_color(imgui.Col_.header_active, alpha(CYAN, .22))
        if imgui.selectable(f"##page{title}", on, 0, V(0, row_h))[0]:
            S.settings_page = None if on else title   # opening one closes the one before
        imgui.pop_style_color(3)
        mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        dl = imgui.get_window_draw_list()
        ty = (mn.y + mx.y - imgui.get_text_line_height()) / 2
        dl.add_text(V(mn.x + 8, ty), u32(CYAN if on else DIM), icon)
        dl.add_text(V(mn.x + sc(34), ty), u32(TEXT if on else KEY_TEXT), title)
        dl.add_text(V(mx.x - sc(18), ty), u32(CYAN if on else alpha(DIM, .7)), fa.ICON_FA_CHEVRON_RIGHT)
    imgui.pop_style_var()
    mine = imgui.is_window_hovered(imgui.HoveredFlags_.root_and_child_windows
                                   | imgui.HoveredFlags_.allow_when_blocked_by_popup
                                   | imgui.HoveredFlags_.allow_when_blocked_by_active_item)
    imgui.end()

    # the open section, in a panel to the right of the menu (over it, if the window is too narrow for both)
    if page is not None:
        pw = min(pw, W - 16)
        px = min(x + mw + 4, vp.pos.x + W - pw - 8)
        ph = min(sc(760), vp.pos.y + H - y - 8)
        begin_drop("##settings_page", V(px, y), V(pw, max(sc(160), ph)))
        imgui.push_font(S.bold, 13)
        imgui.text_colored(DIM, f"{page[1]}   {page[0].upper()}")
        imgui.pop_font()
        imgui.separator()
        imgui.spacing()
        page[2]()
        mine = mine or imgui.is_window_hovered(imgui.HoveredFlags_.root_and_child_windows
                                               | imgui.HoveredFlags_.allow_when_blocked_by_popup
                                               | imgui.HoveredFlags_.allow_when_blocked_by_active_item)
        imgui.end()
    io = imgui.get_io()
    on_btn = S.settings_btn and imgui.is_mouse_hovering_rect(*S.settings_btn)
    if imgui.is_popup_open("", imgui.PopupFlags_.any_popup) or app.midi_learn:
        return
    if (imgui.is_mouse_clicked(0) and not mine and not on_btn) or (imgui.is_key_pressed(imgui.Key.escape, False) and not io.want_text_input):
        S.settings_open = False


WELCOME_TIPS = [
    (fa.ICON_FA_PLAY, "Fire a look", "Click a tile in the playlist at the bottom. The sample looks are there to try."),
    (fa.ICON_FA_LAYER_GROUP, "Make your own", "Effects: + Add effect, tweak the cards, then Save look."),
    (fa.ICON_FA_SLIDERS, "Play it with hardware", "MIDI learn (top bar): click a control, then move a knob or hit a pad."),
    (fa.ICON_FA_SHARE_NODES, "Send it to OBS", "Spout (top bar) with the Spout2 plugin, or Window Capture of "
                                                 "'Lumoria Output'."),
    (fa.ICON_FA_ROTATE_LEFT, "Experiment freely", "Ctrl+Z undoes any change. Themes, AI mask and MIDI are in "
                                                   "Settings, at the top left."),
]


def welcome(app):
    """The first-run window: what Lumoria is, pick a camera, a five-line tour, and the sample looks."""
    if app.held_session is not None:   # the "didn't close properly" question comes first
        return
    if not S.welcomed and not S.welcome_open:
        S.welcome_open = True
        if not app.playlist:   # a brand-new install: start with the samples in the playlist
            app.add_samples()
        imgui.open_popup("Welcome to Lumoria")
    if not S.welcome_open:
        return
    vp = imgui.get_main_viewport()
    imgui.set_next_window_pos(V(vp.pos.x + vp.size.x / 2, vp.pos.y + vp.size.y / 2), 0, V(0.5, 0.5))
    imgui.set_next_window_size(V(sc(640), 0))
    opened, _ = imgui.begin_popup_modal("Welcome to Lumoria", None,
                                        imgui.WindowFlags_.always_auto_resize | imgui.WindowFlags_.no_move
                                        | imgui.WindowFlags_.no_title_bar)
    if not opened:
        return
    dl = imgui.get_window_draw_list()
    brand = brand_textures(app.pipe.ctx)
    p = imgui.get_cursor_screen_pos()
    if brand:
        _, (sym, sym_asp), (word, word_asp) = brand
        h = sc(64)
        dl.add_image(imgui.ImTextureRef(sym.glo), p, V(p.x + h * sym_asp, p.y + h))
        wh = sc(30)
        x = p.x + h * sym_asp + sc(8)
        dl.add_image(imgui.ImTextureRef(word.glo), V(x, p.y + sc(8)), V(x + wh * word_asp, p.y + sc(8) + wh))
        dl.add_text(S.bold, 12 * S.scale, V(x + 4, p.y + sc(42)), u32(DIM), "V I S U A L   F X   E N G I N E")
        imgui.dummy(V(1, h + sc(6)))
    imgui.push_text_wrap_pos(sc(620))
    imgui.text("Live visuals for your camera, screen and music: stack GPU effects, cut yourself out with AI, "
               "make it react to the beat, and fire whole looks from the playlist.")
    imgui.pop_text_wrap_pos()
    imgui.spacing()
    label("Camera")
    if imgui.begin_combo("##wcam", f"{KIND_ICONS.get(app.source_desc.get('kind', 'test'), '')}   "
                                   f"{describe(app.source_desc)}"):
        for name, _backends in app.cameras:
            if imgui.selectable(f"{fa.ICON_FA_VIDEO}   {name}##w", app.source_desc.get("name") == name)[0]:
                app.choose_source("main", {"kind": "camera", "name": name})
        if imgui.selectable(f"{fa.ICON_FA_BARCODE}   Test pattern##w", app.source_desc.get("kind") == "test")[0]:
            app.choose_source("main", {"kind": "test"})
        imgui.end_combo()
    if not app.cameras:
        imgui.text_colored(DIM, "No camera found: plug one in, or pick a video or screen in the Input card.")
    imgui.spacing()
    imgui.separator()
    for icon, title, text in WELCOME_TIPS:
        imgui.spacing()
        imgui.text_colored(CYAN, f" {icon} ")
        imgui.same_line(sc(44))
        imgui.push_font(S.bold, 15)
        imgui.text(title)
        imgui.pop_font()
        imgui.same_line(sc(200))
        imgui.push_text_wrap_pos(sc(620))
        imgui.text_colored(KEY_TEXT, text)
        imgui.pop_text_wrap_pos()
    imgui.spacing()
    imgui.separator()
    imgui.spacing()
    missing = app.samples_missing()
    bw = (imgui.get_content_region_avail().x - 8) / 2
    if missing:
        if neon_button(f"{fa.ICON_FA_PLUS}  Add {len(missing)} sample look{'s' if len(missing) != 1 else ''}##ws",
                       DIM, V(bw, 0), tip="Adds them to the end of your playlist; your own looks are kept"):
            app.flash(f"Added {app.add_samples()} sample looks to the playlist", 3)
    else:
        imgui.text_colored(DIM, f"{fa.ICON_FA_CHECK}  Sample looks are in your playlist")
    imgui.same_line(0, 8)
    if neon_button(f"{fa.ICON_FA_ARROW_RIGHT}  Start##wgo", CYAN, V(bw, 0), True):
        S.welcomed, S.welcome_open = True, False
        save_layout()
        imgui.close_current_popup()
    imgui.end_popup()


def restore_prompt(app):
    """After an unexpected close: offer the last setup back, or a start with no effects (in case it caused it)."""
    if app.held_session is None:
        return
    if not imgui.is_popup_open("Lumoria didn't close properly"):
        imgui.open_popup("Lumoria didn't close properly")
    vp = imgui.get_main_viewport()
    imgui.set_next_window_pos(V(vp.pos.x + vp.size.x / 2, vp.pos.y + vp.size.y / 2), 0, V(0.5, 0.5))
    opened, _ = imgui.begin_popup_modal("Lumoria didn't close properly", None,
                                        imgui.WindowFlags_.always_auto_resize | imgui.WindowFlags_.no_move)
    if not opened:
        return
    n = len(app.held_session.get("effects", []))
    imgui.text(f"Your last setup ({n} effect{'s' if n != 1 else ''}) was saved.")
    if app.crash_note:
        imgui.text_colored(DIM, "Last error:")
        imgui.push_text_wrap_pos(sc(460))
        imgui.text_colored(AMBER, app.crash_note)
        imgui.pop_text_wrap_pos()
    imgui.text_colored(DIM, "If something in that setup caused the problem, start without effects.")
    imgui.spacing()
    if neon_button(f"{fa.ICON_FA_ROTATE_LEFT}  Restore last setup", CYAN, V(sc(220), 0), True):
        app.answer_restore(True)
        imgui.close_current_popup()
    imgui.same_line()
    if neon_button(f"{fa.ICON_FA_BAN}  Start without effects", DIM, V(sc(220), 0)):
        app.answer_restore(False)
        imgui.close_current_popup()
    imgui.end_popup()


def splitter(uid, pos, size, cursor, dl, vertical, enabled=True):
    """Invisible drag handle over a panel gap; returns True while being dragged."""
    imgui.set_cursor_pos(pos)
    if enabled:
        imgui.invisible_button(f"##{uid}", size)
    hot = enabled and (imgui.is_item_hovered() or imgui.is_item_active())
    active = enabled and imgui.is_item_active()
    if hot:
        imgui.set_mouse_cursor(cursor)
    if enabled and imgui.is_item_deactivated():
        save_layout()
    if vertical:
        a, b = V(pos.x + size.x / 2, pos.y), V(pos.x + size.x / 2, pos.y + size.y)
    else:
        a, b = V(pos.x, pos.y + size.y / 2), V(pos.x + size.x, pos.y + size.y / 2)
    dl.add_line(a, b, u32(CYAN if hot else BORDER), 2 if hot else 1)
    return active


def shortcuts(app):
    io = imgui.get_io()
    if io.want_text_input:
        return
    pressed = lambda k: imgui.is_key_pressed(k, False)
    if imgui.is_popup_open("", imgui.PopupFlags_.any_popup):   # a prompt or menu has the keys
        return
    if io.key_ctrl:   # Ctrl+Z undo, Ctrl+Y / Ctrl+Shift+Z redo (and no plain-key shortcuts while Ctrl is held)
        if pressed(imgui.Key.z):
            app.undo(redo=io.key_shift)
        elif pressed(imgui.Key.y):
            app.undo(redo=True)
        elif pressed(imgui.Key.s):
            S.open_save = True
        elif pressed(imgui.Key.i):
            app.ask_import()
        elif pressed(imgui.Key.e):
            app.ask_export()
        return
    if pressed(imgui.Key.f1):
        S.show_keys = True
    if pressed(imgui.Key.delete):
        if app.current_preset in app.playlist:
            S.confirm_delete = app.current_preset
        else:
            app.flash("Click a look in the playlist first, then Delete removes it.", 3)
    if app.playlist and (pressed(imgui.Key.home) or pressed(imgui.Key.end)):
        app.load_preset(app.playlist[0 if pressed(imgui.Key.home) else -1])
    chain = [f for f in app.pipe.order if not f.removing]
    for n in range(10):
        if pressed(getattr(imgui.Key, f"_{n}")):
            i = (n + 9) % 10
            if i < len(chain):
                chain[i].on = not chain[i].on
    if pressed(imgui.Key.x):
        app.randomize()
    if pressed(imgui.Key.c):
        app.clear()
    if pressed(imgui.Key.n) or pressed(imgui.Key.right_arrow):
        app.auto_progress = 0.0
        app.playlist_step(1) if S.auto_kind == AUTO_PLAYLIST else app.randomize()
    if pressed(imgui.Key.left_arrow):
        app.playlist_step(-1)
    if pressed(imgui.Key.enter) or pressed(imgui.Key.keypad_enter):
        app.take()
    if pressed(imgui.Key.down_arrow) or pressed(imgui.Key.up_arrow):
        app.cue_step(1 if pressed(imgui.Key.down_arrow) else -1)
    if pressed(imgui.Key.space):
        toggle_play(app)
    if pressed(imgui.Key.r):
        app.toggle_record()
    if pressed(imgui.Key.t):
        app.tempo.tap(glfw.get_time())
    if pressed(imgui.Key.b):
        app.tempo.resync_bar()
    if pressed(imgui.Key.m):
        app.flip_preview = not app.flip_preview
    if pressed(imgui.Key.o):
        app.out_win.set_visible(not app.out_win.visible)
    if pressed(imgui.Key.f11):
        app.out_win.set_visible(True)
        app.out_win.toggle_fullscreen()


def delete_prompt(app):
    """'Delete look X?': Enter or the Delete button confirms, Esc or Cancel keeps it."""
    name = S.confirm_delete
    if name is None:
        return
    if not imgui.is_popup_open("Delete look"):
        imgui.open_popup("Delete look")
    vp = imgui.get_main_viewport()
    imgui.set_next_window_pos(V(vp.pos.x + vp.size.x / 2, vp.pos.y + vp.size.y / 2), 0, V(0.5, 0.5))
    if not imgui.begin_popup_modal("Delete look", None, imgui.WindowFlags_.always_auto_resize
                                   | imgui.WindowFlags_.no_title_bar | imgui.WindowFlags_.no_move)[0]:
        S.confirm_delete = None
        return
    bold(f"Delete \"{name}\"?", 16)
    imgui.text_colored(DIM, "It's removed from the playlist and from disk (export it first to keep a copy).")
    imgui.spacing()
    w = sc(150)
    yes = neon_button(f"{fa.ICON_FA_TRASH}  Delete  [Enter]##del", RED, V(w, 0))
    imgui.same_line(0, 8)
    no = neon_button("Cancel  [Esc]##keep", DIM, V(w, 0))
    pressed = lambda k: imgui.is_key_pressed(k, False)
    # not the Delete key: the press that opened this prompt would confirm it straight away
    if yes or pressed(imgui.Key.enter) or pressed(imgui.Key.keypad_enter):
        app.delete_preset(name)
        app.flash(f"Deleted {name}", 3)
        S.confirm_delete = None
        imgui.close_current_popup()
    elif no or pressed(imgui.Key.escape):
        S.confirm_delete = None
        imgui.close_current_popup()
    imgui.end_popup()


KEYS = [("Looks", [("Click a tile", "fire that look"), ("<- / ->  or  N", "previous / next look"),
                   ("Shift+click a tile", "cue it (line it up without firing)"),
                   ("Up / Down", "cue the previous / next look"), ("Enter", "Take: bring the cued look on"),
                   ("Home / End", "first / last look"), ("Space", "play / pause the playlist"),
                   ("Delete", "delete the highlighted look (asks first)"), ("Ctrl+S", "save the chain as a new look"),
                   ("Ctrl+I / Ctrl+E", "import / export looks")]),
        ("Effects", [("1 - 0", "turn the first ten effects on / off"), ("X", "randomize"), ("C", "clear the chain"),
                     ("Ctrl+Z / Ctrl+Y", "undo / redo")]),
        ("Tempo", [("T", "tap tempo"), ("B", "this beat is beat 1 of the bar")]),
        ("Output", [("R", "record on / off"), ("O", "show / hide the output window"),
                    ("F11", "output fullscreen (Esc leaves)"), ("M", "flip the preview (only for you)")]),
        ("Help", [("F1", "this list")])]


def keys_sheet():
    """F1: every keyboard shortcut on one card."""
    if S.show_keys:
        S.show_keys = False
        imgui.open_popup("Keyboard shortcuts")
    vp = imgui.get_main_viewport()
    imgui.set_next_window_pos(V(vp.pos.x + vp.size.x / 2, vp.pos.y + vp.size.y / 2), 0, V(0.5, 0.5))
    if not imgui.begin_popup_modal("Keyboard shortcuts", None, imgui.WindowFlags_.always_auto_resize
                                   | imgui.WindowFlags_.no_title_bar | imgui.WindowFlags_.no_move)[0]:
        return
    bold(f"{fa.ICON_FA_KEYBOARD}  Keyboard shortcuts", 16)
    for group, keys in KEYS:
        imgui.spacing()
        imgui.push_font(S.bold, 12.5)
        imgui.text_colored(DIM, group.upper())
        imgui.pop_font()
        for key, what in keys:
            x = imgui.get_cursor_pos_x()
            imgui.push_font(S.mono, 15)
            imgui.text_colored(CYAN, key)
            imgui.pop_font()
            imgui.same_line(x + sc(150))
            imgui.text(what)
    imgui.spacing()
    # Esc or the button; not F1 again: the press that opened the sheet would close it straight away
    if neon_button("Close  [Esc]##keysclose", DIM, V(-1, 0)) or imgui.is_key_pressed(imgui.Key.escape, False):
        imgui.close_current_popup()
    imgui.end_popup()


def toggle_play(app):
    app.auto_kind_last = S.auto_kind   # what a MIDI play button starts too
    app.auto_progress = 0.0
    app.auto_mode = AUTO_OFF if app.auto_mode else S.auto_kind


# ---------------------------------------------------------------- top bar

LOGO = ("lumoria_symbol", "lumoria_symbol", "lumoria_wordmark")   # the original artwork


def brand_textures(ctx):
    """The logo as GPU textures, or None: the symbol for small spots (top bar), the same for large (welcome),
    and the LUMORIA wordmark, from assets/*.png."""
    if S.brand is None:
        texs = []
        for name in LOGO:
            img = cv2.imread(os.path.join(HERE, "assets", name + ".png"), cv2.IMREAD_UNCHANGED)
            if img is None or img.ndim != 3 or img.shape[2] != 4:
                S.brand = False
                return None
            ys, xs = np.nonzero(img[:, :, 3] > 8)   # trim the empty margin, so every style sits the same size
            if len(xs):
                img = np.ascontiguousarray(img[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
            h, w = img.shape[:2]
            tex = ctx.texture((w, h), 4, cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA).tobytes())
            tex.build_mipmaps()   # drawn much smaller than the artwork: keep it smooth
            tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
            texs.append((tex, w / h))
        S.brand = texs
    return S.brand or None


def top_bar(app):
    brand = brand_textures(app.pipe.ctx)
    if brand:
        (sym, sym_asp), _, (word, word_asp) = brand
        dl = imgui.get_window_draw_list()
        p = imgui.get_cursor_screen_pos()
        top = imgui.get_window_pos().y
        sh = sc(TOPBAR_H) - sc(12)
        dl.add_image(imgui.ImTextureRef(sym.glo), V(p.x - sc(4), top + sc(6)), V(p.x - sc(4) + sh * sym_asp, top + sc(6) + sh))
        x = p.x - sc(4) + sh * sym_asp + sc(4)
        wh = sc(22)
        ww = wh * word_asp
        dl.add_image(imgui.ImTextureRef(word.glo), V(x, top + sc(8)), V(x + ww, top + sc(8) + wh))
        # the descriptor in the theme's own legend colour, spread to the wordmark's width
        sub = "   ".join(" ".join(w) for w in ("VISUAL", "FX", "ENGINE"))
        size = 9.0
        imgui.push_font(S.bold, size)
        tw = imgui.calc_text_size(sub).x
        imgui.pop_font()
        size = min(11.0, max(7.5, size * (ww * 0.86) / max(tw, 1)))
        imgui.push_font(S.bold, size)
        tw = imgui.calc_text_size(sub).x
        imgui.pop_font()
        dl.add_text(S.bold, size * S.scale, V(x + (ww - tw) / 2, top + sc(31)), u32(DIM), sub)
        imgui.set_cursor_screen_pos(V(x + ww, p.y))
        imgui.dummy(V(1, 1))
    else:   # no artwork found: the name as text
        imgui.set_cursor_pos_y(sc(12))
        imgui.push_font(S.bold, 24)
        imgui.text_colored(TEXT, "LUM")
        imgui.same_line(0, 0)
        imgui.text_colored(CYAN, "ORIA")
        imgui.pop_font()
        imgui.same_line(0, 10)
        imgui.set_cursor_pos_y(sc(20))
        imgui.push_font(S.bold, 11)
        imgui.text_colored(DIM, "VISUAL FX ENGINE")
        imgui.pop_font()

    imgui.same_line(0, 22)
    imgui.set_cursor_pos_y(sc(12))
    file_menu(app)
    imgui.same_line(0, 6)
    imgui.set_cursor_pos_y(sc(12))
    if neon_button(f"{fa.ICON_FA_GEAR}  Settings##settingsbtn", DIM, V(0, 0), S.settings_open,
                   None if S.settings_open else
                   "AI mask, tempo, transitions, output, MIDI, interface (theme, lights, layout)", flat=True):
        S.settings_open = S.settings_focus = not S.settings_open
    S.settings_btn = (imgui.get_item_rect_min(), imgui.get_item_rect_max())
    left_end = imgui.get_item_rect_max().x - imgui.get_window_pos().x
    wp, W = imgui.get_window_pos(), imgui.get_window_width()
    right_edge = W - 16

    # the right-hand status keys, and the status readout (source, size, fps, CPU / GPU)
    items = top_bar_items(app)
    pad, gap = imgui.get_style().frame_padding.x, 8
    widths = [imgui.calc_text_size(t).x + pad * 2 for t, *_ in items]
    keys_w = sum(widths) + gap * (len(items) - 1)
    src_icon = fa.ICON_FA_VIDEO if isinstance(app.source, CameraSource) else (
        fa.ICON_FA_BARCODE if app.source is None else fa.ICON_FA_FILM)
    w, h = app.pipe.size
    readout = f"{w}x{h}  {app.fps:>3} FPS"
    if S.load is None:
        S.load = sysload.SysLoad()
    loads = [(n, v) for n, v in (("CPU", S.load.cpu), ("GPU", S.load.gpu)) if v is not None]
    label_ = app.source_label if len(app.source_label) <= 34 else app.source_label[:33] + "..."
    rw = readout_width(label_, readout, loads)

    if left_end + 14 + rw + 14 + keys_w <= right_edge:
        # wide: one row - the readout centred on the window (or in the free room, when that's tighter)
        right_x = right_edge - keys_w
        rx = max(left_end + 14, min(right_x - 14 - rw, (W - rw) / 2))
        draw_readout(app, V(wp.x + rx, wp.y + sc(21) - 2), rw, src_icon, label_, readout, loads)
        x = right_x
        for i, item in enumerate(items):
            top_bar_key(app, item, V(x, sc(12)), widths[i])
            x += widths[i] + gap
        S.topbar_h = sc(TOPBAR_H)
        return

    # narrower: the readout moves up into the right-hand corner and the keys go under it; when they no longer
    # fit with their names they become small icon keys, stacked in rows in the corner
    col_x, col_top = left_end + 14, sc(8)
    if right_edge - col_x < sc(190):   # too tight beside the logo: the readout and keys get rows of their own
        col_x, col_top = 16, sc(TOPBAR_H) - sc(4)
    room = right_edge - col_x
    full = app.source_label
    n = len(full)
    while rw > room and n > 4:   # shorten the source's name before anything else
        n -= 2
        label_ = full[:n].rstrip() + "..."
        rw = readout_width(label_, readout, loads)
    if rw > room:
        label_ = ""
        rw = readout_width(label_, readout, loads)
    draw_readout(app, V(wp.x + right_edge - rw, wp.y + col_top), rw, src_icon, label_, readout, loads)
    y = col_top + sc(27) + 4 + sc(6)
    if keys_w <= room:
        x = right_edge - keys_w
        for i, item in enumerate(items):
            top_bar_key(app, item, V(x, y), widths[i])
            x += widths[i] + gap
        bottom = y + imgui.get_frame_height()
    else:
        k, g = imgui.get_frame_height() + sc(4), 6
        per_row = max(1, int((room + g) // (k + g)))
        rows = [items[i:i + per_row] for i in range(0, len(items), per_row)]
        for row in rows:
            x = right_edge - len(row) * k - (len(row) - 1) * g
            for item in row:
                top_bar_key(app, item, V(x, y), k, icon_only=True)
                x += k + g
            y += k + g
        bottom = y - g
    S.topbar_h = max(sc(TOPBAR_H), bottom + sc(9))


def readout_width(label_, readout, loads):
    """How wide the top bar's readout is with this source name (and the loads, when there are any)."""
    imgui.push_font(S.mono, 16)
    rw = imgui.calc_text_size(readout).x + 46 + (imgui.calc_text_size(label_).x + 18 if label_ else 0)
    if loads:
        rw += imgui.calc_text_size("  ".join(f"{n} {v:>3.0f}%" for n, v in loads)).x + 18
    imgui.pop_font()
    return rw


def draw_readout(app, p, rw, src_icon, label_, readout, loads):
    """The status readout: a recessed LCD window at screen point `p` (its top left), `rw` wide."""
    top, bot = p.y, p.y + sc(27) + 4
    dl = imgui.get_window_draw_list()
    dl.add_rect_filled(V(p.x, top), V(p.x + rw, bot), u32(LCD_BG), 3)
    dl.add_rect(V(p.x, top), V(p.x + rw, bot), u32(EDGE_LO), 3)
    dl.add_line(V(p.x + 3, bot), V(p.x + rw - 3, bot), u32(EDGE_HI), 1)   # lit lower lip
    imgui.push_font(S.mono, 16)
    ty = (top + bot - imgui.get_text_line_height()) / 2
    lcd = LCD
    dl.add_text(S.mono, 16 * S.scale, V(p.x + 12, ty), u32(alpha(lcd, .55)), src_icon)
    x = p.x + 34
    if label_:
        dl.add_text(S.mono, 16 * S.scale, V(x, ty), u32(lcd), label_)
        x += imgui.calc_text_size(label_).x + 18
    dl.add_text(S.mono, 16 * S.scale, V(x, ty), u32(alpha(lcd, .7)), readout)
    x += imgui.calc_text_size(readout).x + 18
    for n, v in loads:   # CPU / GPU load: amber when the computer is nearly flat out
        part = f"{n} {v:>3.0f}%"
        dl.add_text(S.mono, 16 * S.scale, V(x, ty), u32(AMBER if v >= 85 else alpha(lcd, .7)), part)
        x += imgui.calc_text_size(part + "  ").x
    imgui.pop_font()
    imgui.set_cursor_screen_pos(V(p.x, top))
    imgui.dummy(V(rw, bot - top))
    if imgui.is_item_hovered():
        lines = [] if label_ == app.source_label else [f"Source: {app.source_label}"]
        own = lambda v: "" if v is None else f"  (Lumoria {v:.0f}%)"
        lines += [f"{n}: {v:.0f}% of the whole computer{own(S.load.own_cpu if n == 'CPU' else S.load.own_gpu)}"
                  for n, v in loads]
        if loads:
            lines.append("The same figures as Task Manager, once a second")
        if lines:
            imgui.set_tooltip("\n".join(lines))


def top_bar_key(app, item, pos, width, icon_only=False):
    """One of the top bar's status keys at `pos` (window coordinates). icon_only: a small square key showing
    just its symbol, with its name in the tooltip."""
    text, active, col, key, tip = item
    imgui.set_cursor_pos(pos)
    if icon_only:
        name = text.split("  ", 1)
        text, tip = name[0], (f"{name[1]}\n{tip}" if len(name) > 1 else tip)
    if neon_button(f"{text}##{key}", col, V(width, width if icon_only else 0), active, tip):
        if key == "upd":
            app.restart_requested = True
        elif key == "flip":
            app.flip_preview = not app.flip_preview
        elif key == "out":
            app.out_win.set_visible(not app.out_win.visible)
        elif key == "fs":
            app.out_win.set_visible(True)
            app.out_win.toggle_fullscreen()
        elif key == "spout":
            app.toggle_spout()
        elif key == "rec":
            app.toggle_record()
        elif key == "midi":
            app.midi_learn, app.learn_target = not app.midi_learn, None
        else:
            app.toggle_vcam()
    if key == "midi":   # activity light: flickers while MIDI is coming in
        mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        led(imgui.get_window_draw_list(), V(mx.x - 7, mn.y + 7), CYAN, glfw.get_time() - app.midi_seen < .12, 2.4)


def top_bar_items(app):
    """The top bar's right-hand toggles: (label, lit, colour, key, tooltip)."""
    items = [
        (f"{fa.ICON_FA_TABLE_COLUMNS}  Flip", app.flip_preview, CYAN, "flip",
         "Flip preview [M]: selfie view for you only, never broadcast"),
        (f"{fa.ICON_FA_DISPLAY}  Output", app.out_win.visible, CYAN, "out",
         "Show/hide the Lumoria Output window [O] (capture it in OBS)"),
        (f"{fa.ICON_FA_SHARE_NODES}  Spout", app.spout is not None, CYAN, "spout",
         "Share the output over Spout as 'Lumoria': full quality, straight from the GPU.\n"
         "OBS: install the Spout2 plugin, then add a 'Spout2 Capture' source.\n"
         "Also works with Resolume, TouchDesigner, MadMapper and other Spout apps."),
        (f"{fa.ICON_FA_EXPAND}", False, CYAN, "fs", "Output fullscreen [F11]"),
        (f"{fa.ICON_FA_CAMERA}  {'LIVE' if app.vcam else 'Virtual cam'}", app.vcam is not None, MAGENTA, "vcam",
         "Send to the OBS Virtual Camera (Discord, Zoom, browsers)"),
    ]
    rec = app.recorder
    secs = rec.seconds() if rec.recording else 0
    items.insert(0, (f"{fa.ICON_FA_CIRCLE}  " + (f"{int(secs // 60)}:{int(secs % 60):02d}" if rec.recording else "Rec"),
                     rec.recording, RED, "rec", "Record the output to a video file [R]\n"
                                                "Folder, format and frame rate: Settings > Output"))
    items.insert(0, (f"{fa.ICON_FA_SLIDERS}  MIDI learn", app.midi_learn, AMBER, "midi",
                     "Link knobs, faders and pads: turn this on, click a control, then move a knob\n"
                     "or hit a pad. Click again to finish. Links are listed in Settings > MIDI."))
    if app.update_ready:
        items.insert(0, (f"{fa.ICON_FA_ROTATE}  Update ready - restart", True, MAGENTA, "upd",
                         "Lumoria's code changed since it started. Click to relaunch with the new version\n"
                         "(your current effects aren't kept - save a look first if you want them)."))
    return items


def file_menu(app):
    """File: looks in and out of Lumoria, and the things people expect to find there."""
    if neon_button(f"{fa.ICON_FA_FOLDER_OPEN}  File##filemenu", DIM, V(0, 0), flat=True):
        imgui.open_popup("##file")
        S.file_anchor = V(imgui.get_item_rect_min().x, imgui.get_item_rect_max().y + 4)
    if S.file_anchor is not None:
        imgui.set_next_window_pos(S.file_anchor, imgui.Cond_.appearing)
    imgui.push_style_var(imgui.StyleVar_.item_spacing, V(10, 9))
    if imgui.begin_popup("##file"):
        item = lambda icon, text, keys="", ok=True: imgui.menu_item_simple(f"{icon}   {text}", keys, False, ok)
        if item(fa.ICON_FA_FILE, "New (clear the effects)", "C"):
            app.clear()
        if item(fa.ICON_FA_FLOPPY_DISK, "Save look...", "Ctrl+S"):
            S.open_save = True
        imgui.separator()
        if item(fa.ICON_FA_FILE_IMPORT, "Import looks / playlist...", "Ctrl+I"):
            app.ask_import()
        if item(fa.ICON_FA_FILE_EXPORT, "Export playlist...", "Ctrl+E", bool(app.playlist)):
            app.ask_export()
        if item(fa.ICON_FA_FILE_EXPORT, "Export this look...", "", app.current_preset in app.playlist):
            app.ask_export([app.current_preset])
        imgui.separator()
        if item(fa.ICON_FA_FOLDER_OPEN, "Open recordings folder"):
            os.makedirs(app.rec_folder, exist_ok=True)
            os.startfile(app.rec_folder)
        if item(fa.ICON_FA_GEAR, "Settings..."):
            S.settings_open = S.settings_focus = True
        if item(fa.ICON_FA_KEYBOARD, "Keyboard shortcuts", "F1"):
            S.show_keys = True
        imgui.separator()
        if item(fa.ICON_FA_RIGHT_FROM_BRACKET, "Exit", "Alt+F4") and S.windows:
            glfw.set_window_should_close(S.windows[0], True)
        imgui.end_popup()
    imgui.pop_style_var()


# ---------------------------------------------------------------- sidebar

def sidebar(app):
    """What you play: inputs, audio and the effect chain. (Settings - set once: AI mask, transitions, MIDI, output,
    interface, about - opens from the top bar.)"""
    imgui.spacing()
    settings_cards("top", [("Input", fa.ICON_FA_VIDEO, lambda: input_section(app)),
                           ("Audio", fa.ICON_FA_MUSIC, lambda: audio_section(app))])
    if section("Effects", fa.ICON_FA_LAYER_GROUP):
        effects_section(app)
    imgui.dummy(V(1, 12))


def settings_list(app):
    """The Settings tab's cards (the Settings panel in the Custom layout)."""
    return [("AI Mask", fa.ICON_FA_USER, lambda: mask_section(app)),
            ("Tempo", fa.ICON_FA_DRUM, lambda: tempo_section(app)),
            ("Transitions", fa.ICON_FA_WAND_MAGIC_SPARKLES, lambda: transitions_section(app)),
            ("Output", fa.ICON_FA_TV, lambda: output_section(app)),
            ("MIDI", fa.ICON_FA_SLIDERS, lambda: midi_section(app)),
            ("Interface", fa.ICON_FA_PALETTE, interface_section),
            ("About", fa.ICON_FA_CIRCLE_INFO, about_section)]


CREDITS = [   # what Lumoria is built with, and their licences (shown in Settings > About)
    ("Robust Video Matting (AI mask model)", "GPL-3.0"), ("ONNX Runtime + DirectML", "MIT"),
    ("Dear ImGui / imgui-bundle", "MIT"), ("ModernGL", "MIT"), ("GLFW / pyGLFW", "zlib / MIT"),
    ("PyOpenGL", "BSD"), ("OpenCV", "Apache-2.0"), ("NumPy", "BSD"), ("sounddevice / PortAudio", "MIT"),
    ("mss", "MIT"), ("cv2-enumerate-cameras", "MIT"),
    ("PyAV + FFmpeg (recording)", "BSD / LGPL / GPL"), ("windows-capture (screen capture)", "MIT"),
    ("Font Awesome Free icons", "CC BY 4.0 / OFL"), ("Roboto, Inconsolata fonts", "Apache-2.0 / OFL"),
    ("Python", "PSF"), ("Packaged with PyInstaller and Inno Setup", ""),
]


def about_section():
    imgui.push_font(S.bold, 15)
    imgui.text(f"Lumoria Visual FX Engine {VERSION}")
    imgui.pop_font()
    imgui.text_colored(DIM, "Live GPU visuals: effects, AI cut-outs, audio, MIDI, looks.")
    imgui.text_colored(DIM, "Open source under the GNU GPL v3.0: share it, change it, build on it.")
    if neon_button(f"{fa.ICON_FA_HAND_SPARKLES}  Show the welcome again##welcome", DIM, V(-1, 0)):
        S.welcomed = False
    if SUPPORT_URL and neon_button(f"{fa.ICON_FA_HEART}  Support Lumoria##support", MAGENTA, V(-1, 0),
                                   tip="Made by one person: a tip helps keep it going"):
        webbrowser.open(SUPPORT_URL)
    if SOURCE_URL and neon_button(f"{fa.ICON_FA_CODE}  Source code##source", DIM, V(-1, 0), tip=SOURCE_URL):
        webbrowser.open(SOURCE_URL)
    imgui.spacing()
    label("Built with")
    imgui.new_line()
    for name, lic in CREDITS:
        imgui.text(name)
        if lic:
            imgui.same_line()
            imgui.text_colored(DIM, f"({lic})")


def card_columns():
    """Columns for card grids: the Interface setting, or as many as fit (Auto)."""
    return S.card_cols or max(1, int((imgui.get_content_region_avail().x + 8) // (sc(CARD_MIN_W) + 8)))


def settings_cards(uid, cards):
    """Sidebar settings as collapsible cards that sit side by side when the sidebar is wide enough,
    like the effect cards. cards: (title, icon, draw function)."""
    cols = min(card_columns(), len(cards))
    imgui.push_style_var(imgui.StyleVar_.cell_padding, V(4, 4))
    if imgui.begin_table(f"settings_{uid}", cols, imgui.TableFlags_.sizing_stretch_same | imgui.TableFlags_.no_pad_outer_x):
        for title, icon, draw_fn in cards:
            imgui.table_next_column()
            imgui.push_id(title)
            imgui.push_style_color(imgui.Col_.child_bg, CARD)
            imgui.push_style_color(imgui.Col_.border, BORDER)
            imgui.push_style_var(imgui.StyleVar_.window_padding, V(8, 4))
            imgui.begin_child("card", V(-1, 0), imgui.ChildFlags_.borders | imgui.ChildFlags_.auto_resize_y
                              | imgui.ChildFlags_.always_use_window_padding, imgui.WindowFlags_.no_scrollbar)
            imgui.pop_style_var()
            imgui.pop_style_color(2)
            if section(title, icon):
                draw_fn()
                imgui.spacing()
            imgui.end_child()
            bevel(imgui.get_item_rect_min(), imgui.get_item_rect_max())
            imgui.pop_id()
        imgui.end_table()
    imgui.pop_style_var()


def midi_section(app):
    """MIDI ports and the list of links."""
    dl = imgui.get_window_draw_list()
    for name, h, err in app.midi.ports:
        p = imgui.get_cursor_screen_pos()
        led(dl, V(p.x + 6, p.y + imgui.get_text_line_height() / 2 + 1), CYAN if h else RED, True, 3)
        imgui.set_cursor_screen_pos(V(p.x + 18, p.y))
        imgui.text(name)
        if err:
            imgui.same_line()
            imgui.text_colored(DIM, err)
    if not app.midi.ports:
        imgui.text_colored(DIM, "No MIDI inputs found. Plug a controller in, then Rescan.")
    if neon_button(f"{fa.ICON_FA_ROTATE}  Rescan##midi", DIM, V(sc(110), 0)):
        app.midi.open_all()
        app.rescan_midi_out()
    imgui.same_line()
    if neon_button(f"{fa.ICON_FA_SLIDERS}  {'Finish learning' if app.midi_learn else 'MIDI learn'}##ml", AMBER,
                   V(-1, 0), app.midi_learn):
        app.midi_learn, app.learn_target = not app.midi_learn, None
    imgui.spacing()
    bold("Button lights", 13)
    if imgui.is_item_hovered():
        imgui.set_tooltip("Tick a controller to light its linked buttons and pads to match: on / off switches,\n"
                          "the music note, paused automations, play, record and the current look.\n"
                          "Lumoria sends the same note or CC the button sends (127 lit, 0 dark), which\n"
                          "lights most controllers (e.g. the MIDI Mix). Leave synths and interfaces unticked.")
    imgui.text_colored(DIM, "Light the linked buttons on:")
    errors = {n: e for n, _h, e in app.midi_out.ports if e}
    outs = [n for n in app.out_names if "GS Wavetable" not in n]   # Windows' built-in synth: it would just play notes
    for name in outs:
        changed, on = imgui.checkbox(f"{name}##lt", name in app.light_ports)
        if changed:
            app.set_light_port(name, on)
        if name in errors:
            imgui.same_line()
            imgui.text_colored(RED, errors[name])
    if not outs:
        imgui.text_colored(DIM, "No MIDI outputs found.")
    imgui.spacing()
    if not app.midi_map:
        imgui.text_colored(DIM, "No links yet. MIDI learn, click a control, move a knob.")
    drop = None
    for k, m in enumerate(app.midi_map):
        c = app.midi_control(tuple(m["target"]))
        imgui.push_font(S.mono, 15)
        imgui.text_colored(CYAN, f"{app.midi_name(m['src']):<12}")
        imgui.pop_font()
        imgui.same_line()
        imgui.text_colored(TEXT if c else DIM, c[5] if c else f"{m['target'][0]} (not available)")
        imgui.same_line(imgui.get_content_region_avail().x + imgui.get_cursor_pos_x() - sc(26))
        if icon_button(fa.ICON_FA_XMARK, f"unmap{k}", DIM, "Remove this link", V(sc(24), 0), hover_col=RED):
            drop = k
    if drop is not None:
        app.midi_map.pop(drop)
        app.save_midi_map()
    if app.midi_map and neon_button(f"{fa.ICON_FA_TRASH}  Clear all links##midiclr", RED, V(-1, 0)):
        app.midi_map = []
        app.save_midi_map()


def interface_section():
    label("Layout")
    lay = segmented("layout", ("Classic", "Custom"), S.layout, CYAN)
    if lay != S.layout:
        S.layout, S.pdrag = lay, None
        save_layout()
    if imgui.is_item_hovered():
        imgui.set_tooltip("Classic: the sidebar, preview and playlist in their fixed places" + chr(10) +
                          "Custom: Inputs, Effects, Preview and Playlist are panels you place yourself - drag one by" + chr(10) +
                          "its title strip and its edges snap to the other panels; drag an edge to resize." + chr(10) +
                          "Your arrangement is kept between runs.")
    label("Theme")
    names = list(THEMES)
    i = names.index(S.theme) if S.theme in names else 0
    changed, i = imgui.combo("##theme", i, names)
    if changed:
        apply_theme(names[i], S.accent)
        save_layout()
    if imgui.is_item_hovered():
        imgui.set_tooltip("Console: graphite and metal   Neon: the original neon-on-black\n"
                          "Midnight: navy and blue   Analog: warm vintage gear   Carbon: black stage desk\n"
                          "Forest: deep green and gold   Phosphor: green-screen terminal\n"
                          "Ember: oxblood, red and orange   Plum: aubergine, pink and violet")
    label("Lights")
    changed, a = imgui.combo("##accent", S.accent, [n for n, _ in ACCENTS])
    if changed:
        apply_theme(S.theme, a)
        save_layout()
    if imgui.is_item_hovered():
        imgui.set_tooltip("The main light colour: lit keys, LEDs, meters and slider levels.\n"
                          "Theme = the theme's own.")
    label("Effects view")
    fv = segmented("fxview", ("Cards", "Outline"), S.fx_view, CYAN)
    if fv != S.fx_view:
        S.fx_view, S.fx_seen = fv, None
        save_layout()
    if imgui.is_item_hovered():
        imgui.set_tooltip("Cards: every effect is a card in a grid" + chr(10) +
                          "Outline: a short list of the chain in order; the effect you pick opens below it" + chr(10) +
                          "(also the list button above the effects)")
    label("Number boxes")
    nb = segmented("numboxes", ("Off", "On"), S.num_boxes, CYAN)
    if nb != S.num_boxes:
        S.num_boxes = nb
        save_layout()
    if imgui.is_item_hovered():
        imgui.set_tooltip("A small box beside each wide slider to type an exact value (Enter to apply)" + chr(10) +
                          "Double-click or Ctrl+click a slider also works either way")
    label("Automate")
    ab = segmented("autobuttons", ("Right-click only", "Buttons"), S.auto_buttons, CYAN)
    if ab != S.auto_buttons:
        S.auto_buttons = ab
        save_layout()
    if imgui.is_item_hovered():
        imgui.set_tooltip("Buttons: a wave button at the end of every slider that can move on its own;" + chr(10) +
                          "it lights up while that slider is automated. Right-clicking a slider works either way")
    label("Open effects")
    fl = segmented("fxlayout", ("Auto", "Under the row", "Beside the list"), S.fx_layout, CYAN)
    if fl != S.fx_layout:
        S.fx_layout = fl
        save_layout()
    if imgui.is_item_hovered():
        imgui.set_tooltip("Outline view: where the effect you open appears" + chr(10) +
                          "Auto: beside the list when the sidebar is wide, under its row when narrow")
    label("Opening one")
    fk = segmented("fxkeep", ("Closes others", "Keeps others"), S.fx_keep, CYAN)
    if fk != S.fx_keep:
        S.fx_keep = fk
        save_layout()
    if imgui.is_item_hovered():
        imgui.set_tooltip("Outline view: picking an effect closes the one before it. Shift-click, or the pin on a row," + chr(10) +
                          "keeps several open at once")
    label("Card warnings")
    cw = segmented("cwarn", ("Full", "Icon only", "Off"), S.card_warnings, AMBER)
    if cw != S.card_warnings:
        S.card_warnings = cw
        save_layout()
    if imgui.is_item_hovered():
        imgui.set_tooltip("The amber notes on effect cards when a later effect hides them\n"
                          "Icon only: a small mark, hover it for the details")
    label("UI size")
    _, pct = slider_float("##uiscale", S.scale * 100, 70, 160, "%.0f%%")
    S.scale = round(pct) / 100
    if imgui.is_item_deactivated_after_edit():
        save_layout()
    if imgui.is_item_hovered():
        imgui.set_tooltip("Smaller fits more on screen. Ctrl + mouse wheel works anywhere.")
    label("Card columns")
    cols = segmented("cols", ("Auto", "1", "2", "3", "4"), S.card_cols)
    if cols != S.card_cols:
        S.card_cols = cols
        save_layout()
    if imgui.is_item_hovered():
        imgui.set_tooltip("Auto adds a column of cards each time the sidebar is wide enough")
    if S.layout == 1:
        imgui.text_colored(DIM, "Drag a panel by its title; its edges snap to the others.")
    else:
        imgui.text_colored(DIM, "Drag the lines between panels to resize them.")
    if neon_button(f"{fa.ICON_FA_ROTATE_LEFT}   Reset layout", DIM, V(-1, 0),
                   tip="Back to the starting sizes and options (keeps Classic / Custom);" + chr(10) +
                       "in Custom, puts every panel back in its starting place"):
        for k, v in LAYOUT_DEFAULTS.items():
            if k != "layout":
                setattr(S, k, type(v)(v))   # a copy, so the defaults themselves never change
        save_layout()


KIND_ICONS = {"camera": fa.ICON_FA_VIDEO, "video": fa.ICON_FA_FILM, "image": fa.ICON_FA_IMAGE,
              "screen": fa.ICON_FA_DESKTOP, "window": fa.ICON_FA_WINDOW_MAXIMIZE, "test": fa.ICON_FA_BARCODE,
              "none": fa.ICON_FA_CIRCLE_XMARK}
# the effect library's category headings (the icon set's choices; Feedback and Sources made distinct)
CAT_ICONS = {"Motion": fa.ICON_FA_ARROWS_UP_DOWN_LEFT_RIGHT, "Mirror & Geometry": fa.ICON_FA_SHAPES,
             "Stylize": fa.ICON_FA_STAR, "Colour": fa.ICON_FA_DROPLET, "Overlay": fa.ICON_FA_LAYER_GROUP,
             "Feedback": fa.ICON_FA_ARROWS_ROTATE, "Cutout": fa.ICON_FA_USER, "Sources": fa.ICON_FA_PHOTO_FILM,
             "Interactive": fa.ICON_FA_HAND_SPARKLES, "Audio": fa.ICON_FA_WAVE_SQUARE, "3D": fa.ICON_FA_CUBE, "Other": fa.ICON_FA_CUBES}


def source_picker(app, target, desc, src):
    """Dropdown for one source: cameras, video, image, screens, windows (+ test pattern for main, None for
    extras), with a crop button beside it."""
    kind = desc.get("kind", "none")
    croppable = src is not None and kind not in ("none", "test")
    imgui.set_next_item_width(-sc(34) if croppable else -1)
    if imgui.begin_combo(f"##src{target}", f"{KIND_ICONS.get(kind, '')}   {describe(desc)}"):
        if target != "main" and imgui.selectable(f"{fa.ICON_FA_CIRCLE_XMARK}   None", kind == "none")[0]:
            app.choose_source(target, {"kind": "none"})
        for name, _backends in app.cameras:
            if imgui.selectable(f"{fa.ICON_FA_VIDEO}   {name}##{target}",
                                kind == "camera" and desc.get("name") == name)[0]:
                app.choose_source(target, {"kind": "camera", "name": name})
        for idx, name in app.screens:
            if imgui.selectable(f"{fa.ICON_FA_DESKTOP}   {name}##{target}",
                                kind == "screen" and desc.get("index") == idx)[0]:
                app.choose_source(target, {"kind": "screen", "index": idx})
        if imgui.begin_menu(f"{fa.ICON_FA_WINDOW_MAXIMIZE}   Window##{target}"):
            app.refresh_windows(glfw.get_time())
            if not app.windows:
                imgui.text_colored(DIM, "No windows found")
            for hwnd, title, exe in app.windows:
                if imgui.menu_item(f"{window_label(title, exe)}##w{hwnd}", "",
                                   kind == "window" and desc.get("hwnd") == hwnd)[0]:
                    app.choose_source(target, {"kind": "window", "title": title, "exe": exe, "hwnd": hwnd})
            imgui.end_menu()
        imgui.separator()
        if imgui.selectable(f"{fa.ICON_FA_FILM}   Video file...##{target}", False)[0]:
            app.pick_file(target, "video")
        if imgui.selectable(f"{fa.ICON_FA_IMAGE}   Image...##{target}", False)[0]:
            app.pick_file(target, "image")
        if target == "main" and imgui.selectable(f"{fa.ICON_FA_BARCODE}   Test pattern", kind == "test")[0]:
            app.choose_source("main", {"kind": "test"})
        imgui.separator()
        if imgui.selectable(f"{fa.ICON_FA_ROTATE}   Rescan devices##{target}", False,
                            imgui.SelectableFlags_.no_auto_close_popups)[0]:
            app.cameras, app.audio_devs, app.screens = list_cameras(), list_inputs(), list_screens()
        imgui.end_combo()
    if croppable:
        imgui.same_line(0, sc(4))
        cropped = bool(desc.get("crop"))
        editing = app.cropping and app.cropping["target"] == target
        if icon_button(fa.ICON_FA_CROP_SIMPLE, f"crop{target}", MAGENTA if editing else (CYAN if cropped else DIM),
                       "Crop: drag a box on the preview to keep just part of this source"):
            app.finish_crop(False) if editing else app.start_crop(target)
    if kind in ("screen", "window"):   # capture rate, and for windows how it's grabbed
        imgui.dummy(V(sc(LABEL_W) - 8, 0))
        imgui.same_line()
        rate = segmented(f"rate{target}", ("30 fps", "60 fps"), 1 if desc.get("fps", 30) == 60 else 0, CYAN,
                         sc(130) if kind == "window" else -1)
        if imgui.is_item_hovered():
            imgui.set_tooltip("60 is smoother but costs more processor time (a small crop is cheap)")
        method = "compatible" if desc.get("method") == "compatible" else "smooth"
        if kind == "window":
            imgui.same_line(0, 6)
            m = segmented(f"meth{target}", ("Fast", "Behind others"), 0 if method == "smooth" else 1, VIOLET)
            if imgui.is_item_hovered():
                imgui.set_tooltip("Fast: grabbed from the screen; the window must be visible (not covered)\n"
                                  "Behind others: keeps working when covered, but much slower for big windows")
            method = ("smooth", "compatible")[m]
        if (30, 60)[rate] != desc.get("fps", 30) or method != desc.get("method", "smooth"):
            app.choose_source(target, {**desc, "fps": (30, 60)[rate], "method": method})
    if src is not None and getattr(src, "fps", 0) and kind in ("camera", "screen", "window"):
        imgui.dummy(V(sc(LABEL_W) - 8, 0))
        imgui.same_line()
        imgui.text_colored(DIM, f"receiving {src.fps:.0f} fps")


def input_section(app):
    label("Main")
    source_picker(app, "main", app.source_desc, app.source)
    for slot in range(3):
        label(f"Source {slot + 2}")
        source_picker(app, slot, app.extra_desc[slot], app.extra[slot])
    if any(d.get("kind", "none") != "none" for d in app.extra_desc) and not any(
            f.id.startswith("media_") for f in walk_items(app.pipe.order) if not f.removing):
        imgui.text_colored(DIM, "Add a Media Layer effect (Sources) to show these.")


def audio_section(app, meters=True):
    label("Input")
    if imgui.begin_combo("##audio", app.audio.device_name or "Off"):
        if imgui.selectable("Off", app.audio.stream is None)[0]:
            app.audio.close()
        shown_loop = False
        for idx, name in app.audio_devs:
            loop = isinstance(idx, tuple)
            if loop and not shown_loop:   # outputs come after the inputs
                imgui.separator()
                imgui.text_colored(DIM, "What you hear (an output's sound)")
                shown_loop = True
            icon = fa.ICON_FA_VOLUME_HIGH if loop else fa.ICON_FA_MICROPHONE
            shown = name.replace("What you hear: ", "") if loop else name
            if imgui.selectable(f"{icon}   {shown}##{idx}", name == app.audio.device_name)[0]:
                app.audio.open(idx, name)
                if app.audio.error:
                    app.flash(f"Audio failed: {app.audio.error}")
        imgui.end_combo()
    label("React to")
    for row, keys in enumerate((("bass", "mid", "high", "all"), ("kick", "snare", "hat", "beat"),
                                ("energy", "bright", "busy", "pan"))):
        if row:
            label("")
        names = [A.SOURCE_NAMES[k].split(" ")[0] for k in keys]
        cur = keys.index(app.band) if app.band in keys else -1
        new = segmented(f"band{row}", names, cur, MAGENTA)
        if new != cur:
            app.band = keys[new]
        if imgui.is_item_hovered():
            imgui.set_tooltip("What effects set to Audio follow (each effect can pick its own in its card)\n"
                              "Bass / Mids / Highs / All: how loud that part of the sound is\n"
                              "Kick / Snare / Hats: a pulse on each drum hit\n"
                              "Beat: a pulse on every beat of the tempo clock, even when the music goes quiet" + chr(10) +
                              "Energy: slow loudness (builds and drops)   Bright: dark to bright sound" + chr(10) +
                              "Busy: how much is changing   Pan: where the sound sits, left to right")
    label("Sensitivity")
    _, app.gain = slider_float("##gain", app.gain, 0.2, 3.0, "%.2f")
    label("Smoothness")
    _, app.audio.smooth = slider_float("##smooth", app.audio.smooth, 0.0, 1.0, "%.2f")
    if imgui.is_item_hovered():
        imgui.set_tooltip("How gradually audio-driven effects rise and fall" + chr(10) +
                          "0 = Snappy (quick, percussive)   1 = slow and flowing (good for ambient music)")
    label("Hit sensitivity")
    _, app.audio.hit_sens = slider_float("##hitsens", app.audio.hit_sens, 0.0, 1.0, "%.2f")
    if imgui.is_item_hovered():
        imgui.set_tooltip("How easily a drum counts as a hit: low = only the clearest hits, high = every little one")
    if meters:
        audio_meters(app)


def audio_meters(app):
    """Levels, drum-hit lights and the spectrum (the Meters panel in the Custom layout)."""
    for b, name in (("bass", "Bass"), ("mid", "Mids"), ("high", "Highs")):
        imgui.text_colored(DIM, name)
        imgui.same_line(sc(LABEL_W))
        imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + sc(7))
        meter(app.audio.level[b], MAGENTA if b == app.band else alpha(MAGENTA, .45))
    label("Hits")
    hit_lights(app)
    label("Spectrum")
    spectrum_strip(app)


def hit_lights(app):
    """A row of lamps that flash on each drum hit (and on the tempo clock's beat)."""
    keys = ("kick", "snare", "hat", "accent", "beat")
    names = ("Kick", "Snare", "Hats", "Big", "Beat")
    avail = imgui.get_content_region_avail().x
    p, h = imgui.get_cursor_screen_pos(), imgui.get_frame_height()
    dl = imgui.get_window_draw_list()
    w = (avail - 4 * 4) / len(keys)
    for i, (k, name) in enumerate(zip(keys, names)):
        x = p.x + i * (w + 4)
        v = app.audio.level[k]
        col = VIOLET if k == "beat" else MAGENTA
        dl.add_rect_filled(V(x, p.y + 2), V(x + w, p.y + h - 2), u32(FRAME), 3)
        dl.add_rect_filled(V(x, p.y + 2), V(x + w, p.y + h - 2), u32(alpha(col, .12 + .75 * v)), 3)
        if k == app.band:
            dl.add_rect(V(x, p.y + 2), V(x + w, p.y + h - 2), u32(col), 3)
        ts = imgui.calc_text_size(name)
        dl.add_text(V(x + (w - ts.x) / 2, p.y + (h - ts.y) / 2), u32(TEXT if v > .4 else DIM), name)
    imgui.dummy(V(avail, h))


def spectrum_strip(app, rng=None, height=34.0):
    """The live spectrum, low to high, as thin bars; rng (Hz) shades the part an effect listens to.
    Returns the frequency (Hz) under the mouse, or None."""
    au = app.audio
    spec = au.spectrum if au.stream else np.zeros(A.SPEC_N, np.float32)
    avail = imgui.get_content_region_avail().x
    hh = sc(height)
    p = imgui.get_cursor_screen_pos()
    dl = imgui.get_window_draw_list()
    dl.add_rect_filled(p, V(p.x + avail, p.y + hh), u32(FRAME), 3)
    lo_hz, hi_hz = math.log(30), math.log(16000)

    def x_of(hz):
        return p.x + 2 + (avail - 4) * (math.log(max(30.0, min(16000.0, hz))) - lo_hz) / (hi_hz - lo_hz)
    if rng:
        dl.add_rect_filled(V(x_of(min(rng)), p.y), V(x_of(max(rng)), p.y + hh), u32(alpha(MAGENTA, .18)), 2)
    n = len(spec)
    bw = (avail - 4) / n
    for i, v in enumerate(spec):
        hz = au.band_hz[i]
        inside = rng is None or min(rng) <= hz <= max(rng)
        x = p.x + 2 + i * bw
        top = p.y + hh - 2 - (hh - 4) * float(v)
        dl.add_rect_filled(V(x, top), V(x + max(1.0, bw - 1), p.y + hh - 2),
                           u32(MAGENTA if inside else alpha(MAGENTA, .35)))
    for hz, txt in ((100, "100"), (1000, "1k"), (10000, "10k")):
        dl.add_text(V(x_of(hz) + 2, p.y + 1), u32(alpha(DIM, .7)), txt)
    imgui.invisible_button("##spec", V(avail, hh))
    if imgui.is_item_hovered():
        mx = imgui.get_mouse_pos().x
        return math.exp(lo_hz + (hi_hz - lo_hz) * min(1.0, max(0.0, (mx - p.x - 2) / max(avail - 4, 1))))
    return None


def is_group(f):
    return hasattr(f, "children")


def walk_items(items):
    for it in items:
        yield it
        if is_group(it):
            yield from walk_items(it.children)


def effects_section(app):
    reorder_autoscroll()
    gap = 6
    w_small = sc(40)
    avail = imgui.get_content_region_avail().x
    if neon_button(f"{fa.ICON_FA_PLUS}   Add effect", CYAN, V(avail - 7 * (w_small + gap), 0)):
        S.lib_target, S.open_lib = None, True
    imgui.same_line(0, gap)
    if neon_button(f"{fa.ICON_FA_LIST if S.fx_view == 0 else fa.ICON_FA_TABLE_CELLS_LARGE}##view", CYAN,
                   V(w_small, 0), active=S.fx_view == 1,
                   tip="Outline view: every effect in order as a short list, and the one you pick opens below it"
                       if S.fx_view == 0 else "Back to cards"):
        S.fx_view, S.fx_seen = 1 - S.fx_view, None
        save_layout()
    imgui.same_line(0, gap)
    if neon_button(f"{fa.ICON_FA_FOLDER_PLUS}##grp", VIOLET, V(w_small, 0),
                   tip="New group: a layer with its own effects, blended back as one\n"
                       "(its effects only see the group's own copy of the picture)"):
        app.new_group()
    imgui.same_line(0, gap)
    everything = [f for f in walk_items(app.pipe.order) if not f.removing]
    any_open = any(f.expanded for f in everything)
    if neon_button(f"{fa.ICON_FA_ANGLES_UP if any_open else fa.ICON_FA_ANGLES_DOWN}##fold", CYAN, V(w_small, 0),
                   tip="Collapse all cards" if any_open else "Expand all cards"):
        S.fx_shift = True   # outline: opening them all together is on purpose
        for f in everything:
            f.expanded = not any_open
    imgui.same_line(0, gap)
    if neon_button(f"{fa.ICON_FA_SHUFFLE}##rand", VIOLET, V(w_small, 0), tip="Randomize [X]"):
        app.randomize()
    imgui.same_line(0, gap)
    if neon_button(f"{fa.ICON_FA_TRASH_CAN}##clear", RED, V(w_small, 0), tip="Clear all effects [C]"):
        app.clear()
    imgui.same_line(0, gap)
    if neon_button(f"{fa.ICON_FA_ROTATE_LEFT}##undo", DIM, V(w_small, 0),
                   tip=f"Undo [Ctrl+Z]  ({len(app.undo_stack)} step{'s' if len(app.undo_stack) != 1 else ''})"):
        app.undo()
    imgui.same_line(0, gap)
    if neon_button(f"{fa.ICON_FA_ROTATE_RIGHT}##redo", DIM, V(w_small, 0),
                   tip=f"Redo [Ctrl+Y]  ({len(app.redo_stack)} step{'s' if len(app.redo_stack) != 1 else ''})"):
        app.undo(redo=True)
    if S.open_lib:   # requested here or by a group's "+ Add" (which lives in another ID scope)
        S.open_lib = False
        imgui.open_popup("library")
    library_popup(app)

    if not any(not f.removing for f in app.pipe.order):
        imgui.spacing()
        imgui.text_colored(DIM, "No effects yet. Add one, or fire a look\nfrom the playlist below.")
        return
    imgui.spacing()
    if S.fx_view == 1:
        outline_view(app)
    else:
        draw_items(app, app.pipe.order, top=True)


def outline_flat(items, depth=0, top=True):
    """(item, its chain list, key number or None, indent) for each effect and group in order, a group followed by
    the effects inside it."""
    for i, f in enumerate([f for f in items if not f.removing]):
        yield f, items, (i if top else None), depth
        if is_group(f):
            yield from outline_flat(f.children, depth + 1, False)


def outline_focus(flat):
    """One at a time: an effect that has just been opened (a click, Add effect, a fired look) closes the others,
    unless it was Shift-clicked, the others are pinned, or Settings > Interface keeps them open."""
    now = {f.uid for f, *_ in flat if f.expanded}
    if S.fx_seen is not None:
        new = [f for f, *_ in flat if f.expanded and f.uid not in S.fx_seen]
        if new and not (S.fx_keep or S.fx_shift):
            keep = {new[0].uid}   # a look that opened several at once: show the first
            for f, *_ in flat:
                if f.expanded and f.uid not in keep and f.uid not in S.pinned:
                    f.expanded = False
            now = {f.uid for f, *_ in flat if f.expanded}
    S.fx_seen, S.fx_shift = now, False


def outline_row(app, f, key, container, depth):
    """One line of the outline: grip, power, name (click to open), mode, pin, remove."""
    imgui.push_id(f.id)
    group = is_group(f)
    accent = VIOLET if group else (MOD_COLS[f.mod] if f.mod else CYAN)
    pinned = f.uid in S.pinned
    h = sc(28)
    imgui.push_style_var(imgui.StyleVar_.item_spacing, V(2, 2))
    if depth:
        imgui.dummy(V(sc(14) * depth, 1))
        imgui.same_line(0, 0)
    icon_button(fa.ICON_FA_GRIP_VERTICAL, "grip", alpha(DIM, .7), size=V(sc(16), 0))
    if imgui.is_item_hovered():
        imgui.set_mouse_cursor(imgui.MouseCursor_.resize_all)
    reorder_source(f, container)
    imgui.same_line()
    if power_button(f.on, accent, "Group on/off (fades)" if group else "Bypass on/off (fades)") \
            and not app.midi_learn:
        f.on = not f.on
    imgui.same_line()
    right_w = sc(28) * (2 if group else 3) + 6
    name_w = imgui.get_content_region_avail().x - right_w
    imgui.push_style_color(imgui.Col_.header, alpha(accent, .16))
    imgui.push_style_color(imgui.Col_.header_hovered, alpha(accent, .24))
    imgui.push_style_color(imgui.Col_.header_active, alpha(accent, .32))
    if imgui.selectable("##row", f.expanded, imgui.SelectableFlags_.allow_overlap, V(name_w, h))[0]:
        f.expanded = not f.expanded
        S.fx_shift = imgui.get_io().key_shift   # Shift keeps the others open
    imgui.pop_style_color(3)
    reorder_source(f, container)   # the row itself can be dragged too
    card_menu(app, f, container)
    mn = imgui.get_item_rect_min()
    dl = imgui.get_window_draw_list()
    ty = mn.y + (h - imgui.get_text_line_height()) / 2
    if key is not None and key < 10:
        dl.add_text(S.mono, 16 * S.scale, V(mn.x + 4, ty), u32(alpha(DIM, .8)), f"{(key + 1) % 10}")
    imgui.push_font(S.bold if f.on else S.font, 16)
    label_text = f"{fa.ICON_FA_FOLDER_OPEN if f.expanded else fa.ICON_FA_FOLDER}  {f.name}" if group else f.name
    dl.add_text(V(mn.x + sc(22), ty - 1), u32((TEXT if group else NAME_ON) if f.on else DIM), label_text)
    tw = imgui.calc_text_size(label_text).x
    imgui.pop_font()
    if group:
        n = sum(1 for c in f.children if not c.removing)
        dl.add_text(V(mn.x + sc(22) + tw + sc(10), ty), u32(DIM), f"{n} effect{'s' if n != 1 else ''}")
    else:   # a thin live amount strip along the bottom of the row
        frac = f.live / 1.6 if f.mod else f.live * f.mix
        w_full = name_w - 8
        dl.add_rect_filled(V(mn.x + 4, mn.y + h - 3), V(mn.x + 4 + w_full, mn.y + h - 2), u32(SEG_OFF))
        dl.add_rect_filled(V(mn.x + 4, mn.y + h - 3), V(mn.x + 4 + w_full * min(1.0, max(0.0, frac)), mn.y + h - 2),
                           u32(accent if f.on else alpha(DIM, .4)))
        if S.card_warnings != 2 and f.on and not f.removing and app.covered_by(f, container) is not None:
            dl.add_text(V(mn.x + name_w - sc(22), ty), u32(AMBER), fa.ICON_FA_EYE_SLASH)
            if imgui.is_item_hovered() and imgui.get_io().mouse_pos.x > mn.x + name_w - sc(26):
                imgui.set_tooltip("Mostly hidden by a later effect: open it for details")
    imgui.same_line()
    if not group:
        music_toggle(f)
        imgui.same_line()
    if icon_button(fa.ICON_FA_THUMBTACK, "pin", AMBER if pinned else alpha(DIM, .45),
                   "Pinned: stays open while you open others (click to unpin)" if pinned
                   else "Pin: keep this open while you open other effects"):
        if pinned:
            S.pinned.discard(f.uid)
        else:
            S.pinned.add(f.uid)
            f.expanded = True
            S.fx_shift = True
    imgui.same_line()
    if icon_button(fa.ICON_FA_XMARK, "rm", DIM, "Remove from chain", hover_col=RED):
        app.remove_effect(f)
    imgui.pop_style_var()
    imgui.pop_id()


OUTLINE_LIST_W = 320   # the list's width when the open effects sit beside it


def begin_card_table(uid, n):
    """A row of n card columns that share the width, each at most CARD_MAX_W (then they keep to the left)."""
    avail = imgui.get_content_region_avail().x
    cap = sc(CARD_MAX_W)
    fixed = (avail - 8 * (n - 1)) / n > cap
    imgui.push_style_var(imgui.StyleVar_.cell_padding, V(4, 4))
    flags = (imgui.TableFlags_.sizing_fixed_same if fixed else imgui.TableFlags_.sizing_stretch_same) \
        | imgui.TableFlags_.no_pad_outer_x
    if not imgui.begin_table(uid, n, flags):
        imgui.pop_style_var()
        return False
    if fixed:
        for c in range(n):
            imgui.table_setup_column(f"c{c}", imgui.TableColumnFlags_.width_fixed, cap)
    return True


def end_card_table():
    imgui.end_table()
    imgui.pop_style_var()


def draw_cards(app, entries):
    """Cards for the open effects, in a grid like the card view (a group takes a full row)."""
    cols = card_columns()
    run = []

    def flush():
        if not run:
            return
        n = min(cols, len(run))   # fewer open cards than fit side by side: they share the width (up to a limit)
        if n == 1 and imgui.get_content_region_avail().x <= sc(CARD_MAX_W):
            for f, container, key in run:
                effect_card(app, f, key, container)
        elif begin_card_table(f"open{run[0][0].uid}", n):   # card k in column k % n: each column stacks its own
            for c in range(n):
                imgui.table_next_column()
                for f, container, key in run[c::n]:
                    effect_card(app, f, key, container)
            end_card_table()
        run.clear()

    for f, container, key in entries:
        if is_group(f):
            flush()
            group_card(app, f, key, container, show_children=False)
        else:
            run.append((f, container, key))
    flush()


def outline_view(app):
    """The Effects tab as a list of the whole chain. The effects you open sit BESIDE it when the sidebar is wide (so
    the list stays in view and scrolls on its own), or directly UNDER their own row when it's narrow."""
    flat = list(outline_flat(app.pipe.order))
    outline_focus(flat)
    avail = imgui.get_content_region_avail().x
    beside = S.fx_layout == 2 or (S.fx_layout == 0 and avail >= sc(OUTLINE_LIST_W) + sc(340) + 8)
    imgui.push_style_color(imgui.Col_.border, BORDER)
    if beside:
        h = max(sc(360), imgui.get_window_height() - sc(90))
        imgui.push_style_color(imgui.Col_.child_bg, CARD)
        imgui.push_style_var(imgui.StyleVar_.window_padding, V(6, 4))
        imgui.begin_child("outline_list", V(sc(OUTLINE_LIST_W), h), imgui.ChildFlags_.borders
                          | imgui.ChildFlags_.always_use_window_padding)
        imgui.pop_style_var()
        imgui.pop_style_color()
        reorder_autoscroll()
        outline_rows(app, flat, blocks=False)
        imgui.dummy(V(-1, sc(8)))
        imgui.end_child()
        bevel(imgui.get_item_rect_min(), imgui.get_item_rect_max())
        imgui.same_line(0, 6)
        imgui.begin_child("outline_detail", V(-1, h), 0)
        opened = [(f, container, key) for f, container, key, _ in flat if f.expanded]
        if opened:
            draw_cards(app, opened)
        else:
            imgui.dummy(V(1, sc(8)))
            imgui.text_colored(DIM, "Click an effect in the list to open its settings here.")
            imgui.text_colored(DIM, "Shift-click, or pin it, to keep several open.")
        imgui.end_child()
    else:
        outline_rows(app, flat, blocks=True)
        imgui.dummy(V(-1, sc(8)))
    imgui.pop_style_color()


def outline_rows(app, flat, blocks):
    """The outline's rows in chain order (blocks: each with its open settings under it), leaving out the one being
    dragged (and what's inside it), with the gap opening where it would land."""
    zone_open("list", top=app.pipe.order)
    hide, open_groups = None, []   # depth of a dragged group whose rows are skipped; groups whose rows we're in

    def close_groups(depth):   # a group's rows end: its end gap (an effect dropped in at its end)
        while open_groups and open_groups[-1][1] >= depth:
            g, d = open_groups.pop()
            for h, cur in gaps_here(g.children, None):
                gap_box(h, d + 1, cur)

    for f, container, key, depth in flat:
        if hide is not None and depth > hide:
            continue
        hide = None
        if dragging(f):
            hide = depth
            continue
        close_groups(depth)
        for h, cur in gaps_here(container, f.uid):
            gap_box(h, depth, cur)
        imgui.begin_group()
        if blocks:   # each row is a one-line card, with its settings right under it
            imgui.push_style_color(imgui.Col_.child_bg, CARD_ON if f.expanded else CARD)
            imgui.push_style_var(imgui.StyleVar_.window_padding, V(6, 3))
            imgui.begin_child(f"orow_{f.uid}", V(-1, 0), imgui.ChildFlags_.borders | imgui.ChildFlags_.auto_resize_y
                              | imgui.ChildFlags_.always_use_window_padding, imgui.WindowFlags_.no_scrollbar)
            imgui.pop_style_var()
            imgui.pop_style_color()
            outline_row(app, f, key, container, depth)
            imgui.end_child()
            if f.expanded:
                if is_group(f):
                    group_card(app, f, key, container, show_children=False)
                else:
                    draw_cards(app, [(f, container, key)])
        else:
            outline_row(app, f, key, container, depth)
        imgui.end_group()
        zone_item(f, container, depth, kind="list")
        if is_group(f):
            open_groups.append((f, depth))
    close_groups(0)
    for h, cur in gaps_here(app.pipe.order, None):
        gap_box(h, 0, cur)
    zone_close()


def draw_items(app, items, top):
    """Cards for one chain level: effects flow in a grid; a group takes a full row. While an effect is dragged, it
    is left out and a gap (a card-sized space) opens where it would land."""
    visible = [f for f in items if not f.removing]
    cols = card_columns()
    run = []
    zone_open("grid", top=items)

    def card(n, f):
        if isinstance(f, tuple):   # the gap
            gap_box(f[1], 0, f[2])
        else:
            effect_card(app, f, n, items)

    def flush():
        nonlocal tables
        if not run:
            return
        if cols == 1 and imgui.get_content_region_avail().x <= sc(CARD_MAX_W):
            for n, f in run:
                card(n, f)
        elif begin_card_table(f"cards{id(items)}_{tables}", cols):   # the same id while cards move about (a new
            # one would rebuild every card inside it, which shrinks the list for a frame and jumps its scroll)
            # masonry: card k goes in column k % cols, so chain order still reads left to right, and
            # each column stacks its own cards, so a short card never leaves a gap beside a tall one
            for c in range(cols):
                imgui.table_next_column()
                for n, f in run[c::cols]:
                    card(n, f)
            end_card_table()
            tables += 1
        run.clear()

    tables = 0   # the runs of cards between groups each get a table
    for i, f in enumerate(visible):
        n = i if top else None   # number keys work on the top level
        for h, cur in gaps_here(items, f.uid, ease=False):
            if S.rd["group"]:   # a group lands as a full row
                flush()
                gap_box(h, 0, cur)
            else:
                run.append((None, ("gap", h, cur)))
        if dragging(f):
            continue
        if is_group(f):
            flush()
            group_card(app, f, n, items)
        else:
            run.append((n, f))
    for h, cur in gaps_here(items, None, ease=False):
        if S.rd["group"]:
            flush()
            gap_box(h, 0, cur)
        else:
            run.append((None, ("gap", h, cur)))
    flush()
    zone_close()


# ---------------------------------------------------------------- reordering effects by dragging
# Grab an effect by its grip or its name and drag: it lifts out of the list, the others close up behind it and
# open a gap where it will land, and letting go anywhere puts it in that gap (Esc cancels). Each list drawn this
# frame is a "zone" (its rect and its items' rects); the next frame works out the landing spot from them.

def inside(p, r):
    return r[0].x <= p.x <= r[1].x and r[0].y <= p.y <= r[1].y


def live_after(container, uid):
    """The uid of the item after `uid` in container (skipping fading-out items and the one being dragged)."""
    seen = False
    for x in container:
        if seen and not x.removing and not (S.rd and x.uid == S.rd["uid"]):
            return x.uid
        seen = seen or x.uid == uid
    return None


def gap_key(target):
    return id(target[0]), target[1]


def reorder_source(f, container):
    """Call right after a grip or name item: dragging it (a little way) picks the effect up."""
    if S.rd is None and imgui.is_item_active() and imgui.is_mouse_dragging(0, sc(6)):
        r = S.rd_prev_rects.get(f.uid)
        gh = min(r[1].y - r[0].y, sc(220)) if r else sc(34)
        S.rd = dict(uid=f.uid, name=f.name, group=is_group(f), gh=gh, target=(container, None))
        S.rd["target"] = (container, live_after(container, f.uid))
        S.rd["gaps"] = {gap_key(S.rd["target"]): gh}   # the gap starts open where it was: nothing jumps


def reorder_begin_frame(app):
    """At the start of a frame: drop (mouse up) or cancel (Esc) the drag, else find where it would land now."""
    zones, S.rd_zones, S.rd_stack = S.rd_zones, [], []
    S.rd_prev_rects, S.rd_rects = S.rd_rects, {}
    rd = S.rd
    if rd is None:
        return
    if imgui.is_key_pressed(imgui.Key.escape) or app.pipe.find(rd["uid"]) is None:
        S.rd = None
        return
    if not imgui.is_mouse_down(0):
        dest, before = rd["target"]
        index = next((k for k, x in enumerate(dest) if x.uid == before), None) if before is not None else None
        if before is None or index is not None:
            S.pending_move = (rd["uid"], dest, index)
        S.rd = None
        return
    m = imgui.get_io().mouse_pos
    hit = None
    for z in zones:   # the innermost list under the mouse (a group's cards sit inside the chain's)
        if inside(m, z["rect"]) and (hit is None or z["depth"] >= hit["depth"]):
            hit = z
    if hit is not None:
        new = (pick_in_list if hit["kind"] == "list" else pick_in_grid)(m, hit)
        if new is not None:
            if new[1] == rd["uid"]:   # "before itself" is where it was
                new = new[0], live_after(new[0], rd["uid"])
            rd["target"] = new
    cur, dt = gap_key(rd["target"]), min(.1, imgui.get_io().delta_time)
    rd["gaps"].setdefault(cur, 0.0)
    for k in list(rd["gaps"]):   # gaps ease open and shut, so the others glide aside
        goal = rd["gh"] if k == cur else 0.0
        rd["gaps"][k] += (goal - rd["gaps"][k]) * min(1.0, dt * 16)
        if k != cur and rd["gaps"][k] < 0.5:
            del rd["gaps"][k]


def pick_in_list(m, z):
    """Outline: the gap goes before the first row whose middle is below the mouse. Where a group's rows end, the
    mouse's indent says whether it goes in at the end of that group or after it."""
    es = [e for e in z["entries"] if not e.get("gap")]
    k = next((k for k, e in enumerate(es) if (e["rect"][0].y + e["rect"][1].y) / 2 > m.y), len(es))
    prev, nxt = (es[k - 1] if k else None), (es[k] if k < len(es) else None)
    x0 = z["rect"][0].x + sc(24)
    if prev is not None and prev["group"] and prev["empty"] and m.x > x0 + sc(14) * (prev["depth"] + 1):
        return prev["children"], None
    if prev is not None and prev["depth"] > (nxt["depth"] if nxt else 0) and m.x > x0 + sc(14) * prev["depth"]:
        return prev["cont"], live_after(prev["cont"], prev["uid"])
    if nxt is not None:
        return nxt["cont"], nxt["uid"]
    return z["top"], None


def pick_in_grid(m, z):
    """Cards: over a card's upper half the gap goes before it, its lower half after it. A group card: its header
    strip before it, its foot after it, anywhere else into the group (at the end). Over the gap, it stays put."""
    for e in z["entries"]:
        if not inside(m, e["rect"]):
            continue
        if e.get("gap"):
            return None
        y, top, bot = m.y, e["rect"][0].y, e["rect"][1].y
        if e["group"]:
            if y - top <= min(sc(40), (bot - top) * .3):
                return e["cont"], e["uid"]
            if bot - y > min(sc(24), (bot - top) * .25):
                return e["children"], None
        elif y < (top + bot) / 2:
            return e["cont"], e["uid"]
        return e["cont"], live_after(e["cont"], e["uid"])
    # in the empty space under a short column: after that column's last card
    above = [e for e in z["entries"] if e["rect"][0].x <= m.x <= e["rect"][1].x and e["rect"][1].y <= m.y]
    if above:
        e = max(above, key=lambda e: e["rect"][1].y)
        if not e.get("gap") and not e["group"]:
            return e["cont"], live_after(e["cont"], e["uid"])
    return None


def zone_open(kind, top=None):
    """Start a list of effects (kind "list" or "grid") whose items can be dropped between."""
    imgui.begin_group()
    S.rd_stack.append(dict(kind=kind, entries=[], top=top, depth=len(S.rd_stack)))


def zone_close():
    imgui.end_group()
    z = S.rd_stack.pop()
    z["rect"] = (imgui.get_item_rect_min(), imgui.get_item_rect_max())
    S.rd_zones.append(z)


def zone_item(f, container, depth=0, kind="grid"):
    """Note the item just drawn (its rect is the last item's) in the open list of that kind."""
    r = (imgui.get_item_rect_min(), imgui.get_item_rect_max())
    if S.rd_stack and S.rd_stack[-1]["kind"] == kind:
        S.rd_rects[f.uid] = r   # its size, for the gap when it's picked up
        g = is_group(f)
        S.rd_stack[-1]["entries"].append(dict(
            uid=f.uid, cont=container, rect=r, depth=depth, group=g,
            children=f.children if g else None, empty=g and not any(not c.removing for c in f.children)))


def dragging(f):
    """This effect is the one being dragged (it isn't drawn in its list meanwhile)."""
    return S.rd is not None and f.uid == S.rd["uid"]


def gaps_here(container, before, ease=True):
    """The gaps (height, is the landing spot) open in `container` before item `before` (None: at its end).
    ease=False (card grids): only the landing spot, at full size - two half-open gaps would shuffle the columns."""
    if S.rd is None:
        return []
    cur, key = gap_key(S.rd["target"]), (id(container), before)
    if not ease:
        return [(S.rd["gh"], True)] if key == cur else []
    return [(h, k == cur) for k, h in S.rd["gaps"].items() if k == key]


def gap_box(h, depth=0, current=True):
    """The open gap where the dragged effect will land."""
    if h < 1:
        return
    imgui.dummy(V(max(1.0, imgui.get_content_region_avail().x), h))
    mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
    if S.rd_stack:
        S.rd_stack[-1]["entries"].append(dict(gap=True, rect=(mn, mx)))
    if h > 6:
        dl = imgui.get_window_draw_list()
        a = V(mn.x + sc(14) * depth + 2, mn.y + 2)
        b = V(mx.x - 2, mx.y - 2)
        dl.add_rect_filled(a, b, u32(alpha(CYAN, .07 if current else .03)), 4)
        dl.add_rect(a, b, u32(alpha(CYAN, .55 * min(1.0, h / max(1.0, S.rd["gh"])))), 4, thickness=1.5)


def reorder_autoscroll():
    """While dragging near the top or bottom of the current scrolling list, scroll it."""
    if S.rd is None:
        return
    m, wp, wh = imgui.get_io().mouse_pos, imgui.get_window_pos(), imgui.get_window_height()
    if not wp.x <= m.x <= wp.x + imgui.get_window_width():
        return
    edge, speed = sc(36), sc(14)
    if wp.y - sc(20) < m.y < wp.y + edge:
        imgui.set_scroll_y(max(0.0, imgui.get_scroll_y() - speed * (1 - (m.y - wp.y) / edge)))
    elif wp.y + wh - edge < m.y < wp.y + wh + sc(20):
        imgui.set_scroll_y(min(imgui.get_scroll_max_y(), imgui.get_scroll_y() + speed * (1 - (wp.y + wh - m.y) / edge)))


def reorder_ghost():
    """The effect being dragged, floating under the mouse."""
    if S.rd is None:
        return
    imgui.set_mouse_cursor(imgui.MouseCursor_.resize_all)
    m = imgui.get_io().mouse_pos
    dl = imgui.get_foreground_draw_list()
    text = f"{fa.ICON_FA_FOLDER if S.rd['group'] else fa.ICON_FA_GRIP_VERTICAL}   {S.rd['name']}"
    tw = imgui.calc_text_size(text).x
    a, b = V(m.x + 12, m.y - sc(14)), V(m.x + 12 + tw + sc(28), m.y + sc(14))
    dl.add_rect_filled(V(a.x + 3, a.y + 4), V(b.x + 3, b.y + 4), u32(alpha(BEZEL, .5)), 5)   # shadow
    keycap(dl, a, b, True, False, CYAN, 4)
    dl.add_text(V(a.x + sc(14), (a.y + b.y - imgui.get_text_line_height()) / 2), u32(NAME_ON), text)


def card_menu(app, f, container):
    """Right-click menu on a card's name: move it in or out of groups."""
    if not imgui.begin_popup_context_item("cardmenu"):
        return
    bold(f.name, 15)
    imgui.separator()
    if not is_group(f) and imgui.selectable(f"{fa.ICON_FA_CLONE}   Duplicate", False)[0]:
        app.duplicate_effect(f)
    inside_f = set(map(id, walk_items(f.children))) if is_group(f) else set()
    groups = [g for g in walk_items(app.pipe.order)
              if is_group(g) and g is not f and not g.removing and id(g) not in inside_f and g.children is not container]
    if groups and imgui.begin_menu(f"{fa.ICON_FA_FOLDER_OPEN}   Move into group"):
        for g in groups:
            if imgui.selectable(f"{g.name}##{g.uid}", False)[0]:
                S.pending_move = (f.uid, g.children, None)
        imgui.end_menu()
    if imgui.selectable(f"{fa.ICON_FA_FOLDER_PLUS}   Put in a new group", False)[0]:
        g = app.new_group(into=container)
        container.remove(g)
        container.insert(container.index(f), g)   # the new group takes the card's place
        S.pending_move = (f.uid, g.children, None)
    if container is not app.pipe.order:
        parent = next(g for g in walk_items(app.pipe.order) if is_group(g) and g.children is container)
        outer = app.pipe.container_of(parent)
        if imgui.selectable(f"{fa.ICON_FA_ARROW_RIGHT_FROM_BRACKET}   Move out of group", False)[0]:
            S.pending_move = (f.uid, outer, outer.index(parent) + 1)
    imgui.end_popup()


def library_popup(app):
    imgui.set_next_window_size_constraints(V(320, 0), V(320, 560))
    if not imgui.begin_popup("library"):
        return
    if imgui.is_window_appearing():
        S.lib_filter = ""
        imgui.set_keyboard_focus_here()
    imgui.set_next_item_width(-1)
    _, S.lib_filter = imgui.input_text_with_hint("##search", f"{fa.ICON_FA_MAGNIFYING_GLASS}   Search effects",
                                                 S.lib_filter)
    if S.lib_target is not None:
        group = next((g for g in walk_items(app.pipe.order) if is_group(g) and g.children is S.lib_target), None)
        imgui.text_colored(VIOLET, f"{fa.ICON_FA_FOLDER}  Adding into {group.name if group else 'group'}")
    q = S.lib_filter.lower().strip()
    in_chain = {f.id for f in walk_items(app.pipe.order) if not f.removing}
    for cat in E.CATEGORIES:
        items = [f for f in app.pipe.effects
                 if f.copy_no == 1 and f.cat == cat and (not q or q in f.name.lower())]
        if not items:
            continue
        imgui.push_style_color(imgui.Col_.text, CYAN)
        imgui.separator_text(f"{CAT_ICONS.get(cat, '')}   {cat.upper()}")
        imgui.pop_style_color()
        for f in items:
            added = f.id in in_chain
            text = f"{f.name}{'   ' + fa.ICON_FA_CHECK if added else ''}##lib"
            flags = imgui.SelectableFlags_.disabled if added else 0
            if imgui.selectable(text, False, flags)[0]:
                app.add_effect(f, into=S.lib_target)
                f.expanded = True
    imgui.end_popup()


def effect_card(app, f, i, container):
    imgui.push_id(f.id)
    outer_scope, S.midi_scope = S.midi_scope, f.id
    accent = MOD_COLS[f.mod] if f.mod else CYAN
    imgui.push_style_color(imgui.Col_.child_bg, CARD_ON if f.on else CARD)
    imgui.push_style_color(imgui.Col_.border, BORDER)
    imgui.push_style_var(imgui.StyleVar_.window_padding, V(8, 6))
    imgui.begin_child("card", V(-1, 0),
                      imgui.ChildFlags_.borders | imgui.ChildFlags_.auto_resize_y
                      | imgui.ChildFlags_.always_use_window_padding,
                      imgui.WindowFlags_.no_scrollbar)
    imgui.pop_style_var()
    imgui.pop_style_color(2)
    header_strip(f.on, accent)

    # header: grip | power | name | mod | chevron | remove
    imgui.push_style_var(imgui.StyleVar_.item_spacing, V(2, 4))
    icon_button(fa.ICON_FA_GRIP_VERTICAL, "grip", alpha(DIM, .7), size=V(18, 0))
    if imgui.is_item_hovered():
        imgui.set_mouse_cursor(imgui.MouseCursor_.resize_all)
    reorder_source(f, container)
    imgui.same_line()
    if power_button(f.on, accent, "Bypass on/off (fades)") and not app.midi_learn:
        f.on = not f.on
    midi_spot(app, (f.id, "on"))
    imgui.same_line()
    right_w = sc(28) * 4 + 6
    name_w = imgui.get_content_region_avail().x - right_w
    key = f"{(i + 1) % 10}  " if i is not None and i < 10 else "   "
    imgui.push_style_color(imgui.Col_.text, TEXT if f.on else DIM)
    imgui.push_style_color(imgui.Col_.header_hovered, alpha(WHITE, .03))
    imgui.push_style_color(imgui.Col_.header_active, alpha(WHITE, .05))
    imgui.align_text_to_frame_padding()
    if imgui.selectable(f"##name", False, imgui.SelectableFlags_.allow_overlap, V(name_w, sc(28)))[0]:
        f.expanded = not f.expanded
    reorder_source(f, container)   # so can its name
    card_menu(app, f, container)
    mn = imgui.get_item_rect_min()
    dl = imgui.get_window_draw_list()
    ty = mn.y + (sc(28) - imgui.get_text_line_height()) / 2
    dl.add_text(S.mono, 16 * S.scale, V(mn.x + 4, ty), u32(alpha(DIM, .8)), key)
    imgui.push_font(S.bold if f.on else S.font, 16)
    dl.add_text(V(mn.x + sc(22), ty - 1), u32(NAME_ON if f.on else DIM), f.name)
    imgui.pop_font()
    imgui.pop_style_color(3)
    imgui.same_line()
    music_toggle(f)
    imgui.same_line()
    if icon_button(fa.ICON_FA_CLONE, "dup", DIM, "Duplicate: add a copy with the same settings,\n"
                   "to change separately (e.g. one on the subject, one on the background)"):
        app.duplicate_effect(f)
    imgui.same_line()
    if icon_button(fa.ICON_FA_CHEVRON_DOWN if f.expanded else fa.ICON_FA_CHEVRON_RIGHT, "exp", DIM, "Settings"):
        f.expanded = not f.expanded
    imgui.same_line()
    if icon_button(fa.ICON_FA_XMARK, "rm", DIM, "Remove from chain", hover_col=RED):
        app.remove_effect(f)
    imgui.pop_style_var()

    # live amount strip
    meter(f.live / 1.6 if f.mod else f.live * f.mix, accent if f.on else alpha(DIM, .4), height=2)
    cover_notes(app, f, container)

    if f.expanded:
        effect_body(app, f)
    imgui.end_child()

    zone_item(f, container)
    bevel(imgui.get_item_rect_min(), imgui.get_item_rect_max())
    S.midi_scope = outer_scope
    imgui.pop_id()


COVER_NOTES = {   # what a card says about an effect later in the chain that hides it, and about itself
    "redraws": ("redrawn by {}", "Redraws the picture: cards above show only as part of its drawing"),
    "covers": ("covered by {}", "Covers the whole picture: cards above don't show"),
    "smears": ("washed out by {}", "Keeps mostly its own trails: quick things above fade into it"),
}


def cover_notes(app, f, container):
    """Warn on a card that something later in the chain hides it, and badge the card that does the hiding."""
    if S.card_warnings == 2:   # turned off in Settings > Interface
        return
    later = app.covered_by(f, container) if f.on and not f.removing else None
    notes = []   # (icon, text, colour, tooltip)
    if later is not None:
        kind = app.covers(later)
        n = container.index(later) + 1
        notes.append((fa.ICON_FA_EYE_SLASH, "Mostly hidden: " + COVER_NOTES[kind][0].format(f"{later.name} ({n})"),
                      AMBER, "Effects run top to bottom, each working on the picture the ones above made.\n"
                             f"Drag this card below {later.name} to show it on top, or change {later.name}'s\n"
                             "settings (Background / Amount / Opacity / Apply to)."))
    kind = app.covers(f)
    if kind and any(it.on and not it.removing for it in container[:container.index(f)]):
        notes.append((fa.ICON_FA_PAINTBRUSH, COVER_NOTES[kind][1], alpha(AMBER, .7), ""))
    if S.card_warnings == 1:   # icon only: the words move into the tooltip
        for k, (icon, text, col, tip) in enumerate(notes):
            if k:
                imgui.same_line()
            imgui.text_colored(col, icon)
            if imgui.is_item_hovered():
                imgui.set_tooltip(text + ("\n\n" + tip if tip else ""))
        return
    imgui.push_text_wrap_pos(0)
    for icon, text, col, tip in notes:
        imgui.text_colored(col, f"{icon}  {text}")
        if tip and imgui.is_item_hovered():
            imgui.set_tooltip(tip)
    imgui.pop_text_wrap_pos()


def group_card(app, g, i, container, show_children=True):
    """A layer: header like an effect card; body has its blend settings and its own effect cards."""
    imgui.push_id(g.id)
    imgui.push_style_color(imgui.Col_.child_bg, GROUP_BG)   # a sub-panel: darker than its modules
    imgui.push_style_color(imgui.Col_.border, BORDER)
    imgui.push_style_var(imgui.StyleVar_.window_padding, V(8, 6))
    imgui.begin_child("group", V(-1, 0),
                      imgui.ChildFlags_.borders | imgui.ChildFlags_.auto_resize_y
                      | imgui.ChildFlags_.always_use_window_padding,
                      imgui.WindowFlags_.no_scrollbar)
    imgui.pop_style_var()
    imgui.pop_style_color(2)
    header_strip(g.on, VIOLET)

    imgui.push_style_var(imgui.StyleVar_.item_spacing, V(2, 4))
    icon_button(fa.ICON_FA_GRIP_VERTICAL, "grip", alpha(DIM, .7), size=V(18, 0))
    if imgui.is_item_hovered():
        imgui.set_mouse_cursor(imgui.MouseCursor_.resize_all)
    reorder_source(g, container)
    imgui.same_line()
    if power_button(g.on, VIOLET, "Group on/off (fades)"):
        g.on = not g.on
    imgui.same_line()
    name_w = imgui.get_content_region_avail().x - (sc(28) * 2 + 2)
    imgui.push_style_color(imgui.Col_.header_hovered, alpha(VIOLET, .08))
    imgui.push_style_color(imgui.Col_.header_active, alpha(VIOLET, .14))
    if imgui.selectable("##gname", False, imgui.SelectableFlags_.allow_overlap, V(name_w, sc(28)))[0]:
        g.expanded = not g.expanded
    imgui.pop_style_color(2)
    reorder_source(g, container)
    card_menu(app, g, container)
    mn = imgui.get_item_rect_min()
    dl = imgui.get_window_draw_list()
    ty = mn.y + (sc(28) - imgui.get_text_line_height()) / 2
    key = f"{(i + 1) % 10}  " if i is not None and i < 10 else "   "
    dl.add_text(S.mono, 16 * S.scale, V(mn.x + 4, ty), u32(alpha(DIM, .8)), key)
    imgui.push_font(S.bold, 16)
    n = sum(1 for c in g.children if not c.removing)
    dl.add_text(V(mn.x + sc(22), ty - 1), u32(TEXT if g.on else DIM),
                f"{fa.ICON_FA_FOLDER_OPEN if g.expanded else fa.ICON_FA_FOLDER}  {g.name}")
    imgui.pop_font()
    dl.add_text(V(mn.x + sc(22) + imgui.calc_text_size(f"XX  {g.name}").x + sc(14), ty), u32(DIM),
                f"{n} effect{'s' if n != 1 else ''}")
    imgui.same_line()
    if icon_button(fa.ICON_FA_CHEVRON_DOWN if g.expanded else fa.ICON_FA_CHEVRON_RIGHT, "exp", DIM, "Open / fold"):
        g.expanded = not g.expanded
    imgui.same_line()
    if icon_button(fa.ICON_FA_XMARK, "rm", DIM, "Remove the group and its effects", hover_col=RED):
        app.remove_effect(g)
    imgui.pop_style_var()
    meter(g.mix, VIOLET if g.on else alpha(DIM, .4), height=2)

    if g.expanded:
        imgui.spacing()
        label("Name")
        _, g.name = imgui.input_text("##name", g.name)
        label("Start from")
        _, src = imgui.combo("##from", g.source + 1, ["Picture so far", "Source 2", "Source 3", "Source 4"])
        g.source = src - 1
        if imgui.is_item_hovered():
            imgui.set_tooltip("Picture so far: the group's effects work on everything above it.\n"
                              "Source 2-4: they work on that video alone, which is then placed in the\n"
                              "picture as a layer, so nothing else is touched.")
        if g.source >= 0:
            label("")
            _, g.cutout = imgui.checkbox("Cut out person (AI)", g.cutout)
            if imgui.is_item_hovered():
                imgui.set_tooltip("Place only the person from this source, not the whole picture\n"
                                  "(its own AI mask; effects in this group that use the mask use it too)")
            if app.extra_desc[g.source].get("kind", "none") == "none":
                imgui.text_colored(AMBER, f"Pick a video for Source {g.source + 2} in the Input card.")
            label("Size")
            _, g.size = slider_float("##gsize", g.size, 0.0, 1.0, "%.2f")
            label("Fit")
            g.fit = segmented("gfit", ("Fill box", "Fit inside", "Stretch"), g.fit, MAGENTA)
            label("Position")
            imgui.set_next_item_width(imgui.get_content_region_avail().x - 64)
            _, g.centre = slider_float2("##gcentre", g.centre, 0.0, 1.0, "%.2f")
            imgui.same_line(0, 4)
            picking = app.picking is g
            if icon_button(fa.ICON_FA_CROSSHAIRS, "gpick", MAGENTA if picking else DIM,
                           "Pick: click or drag on the preview to place it"):
                app.picking = None if picking else g
            imgui.same_line(0, 4)
            if icon_button(fa.ICON_FA_ROTATE_LEFT, "gcen", DIM, "Back to the middle"):
                g.centre = [0.5, 0.5]
            label("Rotate")
            _, g.rotate = slider_float("##grot", g.rotate, -180.0, 180.0, "%.0f deg")
            label("Rounded")
            _, g.rounded = slider_float("##ground", g.rounded, 0.0, 1.0, "%.2f")
            label("Border")
            _, g.border = slider_float("##gborder", g.border, 0.0, 1.0, "%.2f")
        label("Opacity")
        imgui.set_next_item_width(imgui.get_content_region_avail().x - 118)
        _, pct = slider_float("##opacity", g.opacity * 100, 0.0, 100.0, "%.0f%%")
        g.opacity = pct / 100
        imgui.same_line()
        imgui.set_next_item_width(-1)
        _, g.blend = imgui.combo("##blend", g.blend, E.BLEND_MODES)
        label("Apply to")
        g.target = segmented("target", ("All", "Subject", "Background"), g.target, MAGENTA)
        imgui.spacing()
        if neon_button(f"{fa.ICON_FA_PLUS}   Add effect into {g.name}", VIOLET, V(-1, 0)):
            S.lib_target, S.open_lib = g.children, True
        if not n:
            imgui.text_colored(DIM, "Empty: add effects here, drag cards onto this group,\n"
                                    "or right-click a card > Move into group.")
        elif show_children:
            imgui.spacing()
            draw_items(app, g.children, top=False)
        else:
            imgui.text_colored(DIM, "Its effects are in the list above, under the group.")
    imgui.end_child()
    zone_item(g, container)   # dropping on the group's middle puts the card inside, at the end
    if S.rd and S.rd["target"][0] is g.children and not (g.expanded and show_children and n):
        mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()   # it lands inside: the group lights up
        imgui.get_window_draw_list().add_rect(mn, mx, u32(CYAN), 4, thickness=2)
    bevel(imgui.get_item_rect_min(), imgui.get_item_rect_max())
    imgui.pop_id()


AUTO_RATES = [(0.1, 30.0, "%.1f s"), (0.25, 64.0, "%.2g beats"), (0.25, 16.0, "%.2g bars")]


def audio_map_controls(app, f, key, a, w):
    """An audio-driven slider: what it listens to, how fast it reacts, and how the sound is shaped into movement."""
    a.setdefault("rng", [80.0, 250.0])
    a.setdefault("gain", 1.0)
    a.setdefault("gate", 0.0)
    a.setdefault("curve", 0.0)
    a.setdefault("resp", None)
    label("Listens to")
    imgui.set_next_item_width(w)
    _, a["band"] = imgui.combo("##aband", min(a.get("band", 0), len(A.SOURCES) - 1), [n for _k, n in A.SOURCES])
    if imgui.is_item_hovered():
        imgui.set_tooltip("Bass / Mids / Highs / All: how loud that part of the sound is" + chr(10) +
                          "Kick / Snare / Hats / Big kicks: a pulse on each drum hit" + chr(10) +
                          "Beat: every beat of the tempo clock" + chr(10) +
                          "Frequency range: just the part of the sound you pick")
    if A.SOURCE_KEYS[min(a["band"], len(A.SOURCES) - 1)] == "range":
        range_controls(app, a["rng"])
    label("Feel")
    bw = (w - 12) / 3
    for i, name in enumerate(app.AUDIO_FEELS):
        if i:
            imgui.same_line(0, 6)
        if neon_button(f"{name}##feel{i}", DIM, V(bw, 0),
                       tip={"Subtle": "Slow swell: it rises gently and settles back slowly",
                            "Punchy": "Quick and snappy, ignoring the quiet noise floor",
                            "Hit": "Only the loud hits move it, then it drops away fast"}[name]):
            for k, v in app.AUDIO_FEELS[name].items():
                a[k] = list(v) if isinstance(v, list) else v
    label("Response")
    custom = segmented("aresp", ("Main smoothing", "My own"), 1 if a["resp"] else 0, MAGENTA, w)
    if custom and not a["resp"]:
        a["resp"] = [0.01, 0.25]
    elif not custom:
        a["resp"] = None
    if a["resp"]:
        label("Attack")
        imgui.set_next_item_width(w)
        _, ms = slider_float("##aatt", a["resp"][0] * 1000, 0.0, 1000.0, "%.0f ms")
        a["resp"][0] = ms / 1000
        label("Release")
        imgui.set_next_item_width(w)
        _, ms = slider_float("##arel", a["resp"][1] * 1000, 10.0, 4000.0, "%.0f ms", imgui.SliderFlags_.logarithmic)
        a["resp"][1] = ms / 1000
    label("Sensitivity")
    imgui.set_next_item_width(w)
    _, a["gain"] = slider_float("##again", a["gain"], 0.2, 4.0, "%.2fx", imgui.SliderFlags_.logarithmic)
    label("Threshold")
    imgui.set_next_item_width(w)
    _, a["gate"] = slider_float("##agate", a["gate"], 0.0, 0.9, "%.2f")
    if imgui.is_item_hovered():
        imgui.set_tooltip("Sound below this does nothing: ignores a quiet noise floor, or keeps only the loud parts")
    label("Curve")
    imgui.set_next_item_width(w)
    _, a["curve"] = slider_float("##acurve", a["curve"], -1.0, 1.0, "%.2f")
    if imgui.is_item_hovered():
        imgui.set_tooltip("Left: quiet sounds count more (subtle, always moving)" + chr(10) +
                          "Right: only loud sounds count (dramatic, mostly still)")
    heard, drive = app.auto_live.get((f.uid, key), (0.0, 0.0))
    label("Hearing")
    meter(heard, MAGENTA, width=w, height=5)
    label("Moving it")
    meter(drive, CYAN, width=w, height=5)


def automation_menu(app, f, key, lo, hi, name):
    """Right-click the slider just drawn: make it move on its own (an LFO timed by the tempo). An automated
    slider shows a wave mark beside it."""
    a = f.autos.get(key)
    if a and not S.auto_buttons:
        mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        heard = a["shape"] == 7
        imgui.get_window_draw_list().add_text(V(mn.x - sc(17), mn.y + (mx.y - mn.y - imgui.get_text_line_height()) / 2),
                                              u32(MAGENTA if heard else CYAN),
                                              fa.ICON_FA_MUSIC if heard else fa.ICON_FA_WAVE_SQUARE)
    if imgui.is_item_hovered() and not a and not S.auto_buttons:
        imgui.set_tooltip("Right-click: make it float around on its own" if key == "centre"
                          else "Right-click: make it move on its own, or follow the music")
    if not imgui.begin_popup_context_item(f"auto_{key}"):
        return
    bold(f"Automate: {name}", 15)
    imgui.separator()
    on = a is not None
    changed, on = imgui.checkbox("Float around on its own" if key == "centre" else "Move on its own", on)
    if changed:
        if on and key == "centre":
            a = f.autos[key] = dict(path=0, rate=8.0, unit=0, size=0.2, base=list(f.centre), phase=0.0, shape=0)
        elif on:
            a = f.autos[key] = dict(shape=0, rate=1.0, unit=2, lo=lo, hi=hi, phase=0.0, band=0)
        else:
            f.autos.pop(key, None)
            a = None
    if a:
        flipped, paused = imgui.checkbox("Paused", bool(a.get("paused")))
        if flipped:
            a["paused"] = paused
        if imgui.is_item_hovered():
            imgui.set_tooltip("Hold it where it is, keeping these settings (a MIDI button can do this too:\n"
                              "MIDI learn, click the Automate button, then press the button on your controller)")
    if a and key == "centre":
        centre_auto_controls(app, f, a, sc(300))
    elif a:
        w = sc(300)
        label("Shape")
        imgui.set_next_item_width(w)
        _, a["shape"] = imgui.combo("##ashape", a["shape"], app.AUTO_SHAPES)
        shape = a["shape"]
        if imgui.is_item_hovered():
            imgui.set_tooltip("Spin: keeps going one way forever, no back-and-forth\n"
                              "Intro: when the effect comes on, glides From -> To once, then holds")
        if shape == 7:
            audio_map_controls(app, f, key, a, w)
        else:
            label("One turn" if shape == 8 else "Takes" if shape == 9 else "Every")
            imgui.set_next_item_width(w - sc(156))
            r_lo, r_hi, fmt = AUTO_RATES[a["unit"]]
            _, a["rate"] = slider_float("##arate", a["rate"], r_lo, r_hi, fmt, imgui.SliderFlags_.logarithmic)
            imgui.same_line(0, 6)
            a["unit"] = segmented("aunit", tempo.UNITS, a["unit"], VIOLET, sc(150))
            if shape == 8:
                label("Direction")
                a["dir"] = segmented("adir", ("Forward", "Backward"), a.get("dir", 0), VIOLET, w)
            elif shape == 9:
                label("Ease")
                imgui.set_next_item_width(w - sc(90))
                _, a["ease"] = imgui.combo("##aease", a.get("ease", 0), app.INTRO_EASES)
                imgui.same_line(0, 6)
                if imgui.button("Replay", V(sc(84), 0)):
                    f.intro_reset = True
                label("Then")
                imgui.set_next_item_width(w)
                _, a["then"] = imgui.combo("##athen", a.get("then", 0), app.INTRO_THEN)
                if imgui.is_item_hovered():
                    imgui.set_tooltip("Once it arrives at To: hold there, or keep moving as a wave\n"
                                      "between To and Then to (starting from where the intro landed)")
            else:
                label("Phase")
                imgui.set_next_item_width(w)
                _, a["phase"] = slider_float("##aphase", a["phase"], 0.0, 1.0, "%.2f")
        if not (shape == 8 and key == "xr"):   # Rotate spins in whole turns
            label("From")
            imgui.set_next_item_width(w)
            _, a["lo"] = slider_float("##alo", a["lo"], lo, hi, "%.2f")
            label("To")
            imgui.set_next_item_width(w)
            _, a["hi"] = slider_float("##ahi", a["hi"], lo, hi, "%.2f")
        if shape == 9 and a.get("then", 0):
            label("Then to")
            imgui.set_next_item_width(w)
            _, a["then_to"] = slider_float("##athento", a.get("then_to", a["hi"]), lo, hi, "%.2f")
            label("Every")
            imgui.set_next_item_width(w - sc(156))
            a.setdefault("then_unit", 1)
            r_lo, r_hi, fmt = AUTO_RATES[a["then_unit"]]
            _, a["then_rate"] = slider_float("##athenrate", a.get("then_rate", 1.0), r_lo, r_hi, fmt,
                                             imgui.SliderFlags_.logarithmic)
            imgui.same_line(0, 6)
            a["then_unit"] = segmented("athenunit", tempo.UNITS, a["then_unit"], VIOLET, sc(150))
        if shape == 8 and key != "xr":
            imgui.text_colored(DIM, "Runs From -> To, then starts over: seamless when\nboth ends look the same (angles, hues).")
        imgui.text_colored(DIM, "Saved with the look. Morph transitions pause it while they slide.")
    imgui.end_popup()


def auto_w():
    """Width kept free at the end of each slider row for its Automate button (0 when the buttons are off)."""
    return sc(28) + 4 if S.auto_buttons else 0


def auto_button(app, f, key, name):
    """The Automate button at the end of a slider row: opens the slider's automation menu (as right-clicking it
    does). Dim when the slider is still, lit while it moves on its own (cyan) or follows the music (magenta).
    Call after automation_menu; pass key=None on rows that can't be automated, to keep the column lined up."""
    if not S.auto_buttons:
        return
    imgui.same_line(0, 4)
    if key is None:
        imgui.dummy(V(sc(28), imgui.get_frame_height()))
        return
    a = f.autos.get(key)
    heard = bool(a) and a.get("shape") == 7
    paused = bool(a) and bool(a.get("paused"))
    col = (MAGENTA if heard else CYAN) if a else alpha(DIM, .55)
    icon = fa.ICON_FA_PAUSE if paused else fa.ICON_FA_MUSIC if heard else fa.ICON_FA_WAVE_SQUARE
    if paused:
        col = alpha(col, .6)
    if a and not paused:   # a lit button: a soft glow behind the glyph
        p, h = imgui.get_cursor_screen_pos(), imgui.get_frame_height()
        imgui.get_window_draw_list().add_rect_filled(p, V(p.x + sc(28), p.y + h), u32(alpha(col, .16)), 3)
    if paused:
        tip = f"{name}: automation paused, held where it is" + chr(10) + "Click to change it"
    elif a:
        tip = (f"{name}: follows the music" if heard else f"{name}: moving on its own") + chr(10) + "Click to change it"
    else:
        tip = f"Automate {name}: make it move on its own" + chr(10) + "(an LFO in time with the tempo) or follow the music"
    learning = app.midi_learn
    if learning:
        tip = f"MIDI learn: click, then press a button to pause / resume {name}'s automation"
    if icon_button(icon, f"ab_{key}", col, tip, hover_col=col) and not learning:
        imgui.open_popup(f"auto_{key}")
    midi_spot(app, (f.id, f"auto_{key}"))


def centre_auto_controls(app, f, a, w):
    """The Centre floating on its own: a path round a base point."""
    label("Path")
    imgui.set_next_item_width(w)
    _, a["path"] = imgui.combo("##cpath", a.get("path", 0), app.CENTRE_PATHS)
    if a["path"] != 4:
        label("Every")
        imgui.set_next_item_width(w - sc(156))
        r_lo, r_hi, fmt = AUTO_RATES[a["unit"]]
        _, a["rate"] = slider_float("##crate", a["rate"], r_lo, r_hi, fmt, imgui.SliderFlags_.logarithmic)
        imgui.same_line(0, 6)
        a["unit"] = segmented("cunit", tempo.UNITS, a["unit"], VIOLET, sc(150))
    label("Size")
    imgui.set_next_item_width(w)
    _, a["size"] = slider_float("##csize", a.get("size", 0.2), 0.0, 0.6, "%.2f")
    label("Around")
    imgui.set_next_item_width(w - sc(90))
    _, a["base"] = slider_float2("##cbase", a.get("base", [0.5, 0.5]), 0.0, 1.0, "%.2f")
    a["base"] = list(a["base"])
    imgui.same_line(0, 6)
    if imgui.button("Middle", V(sc(84), 0)):
        a["base"] = [0.5, 0.5]
    imgui.text_colored(DIM, "Saved with the look. Turn it off to place the Centre by hand again.")


def effect_body(app, f):
    imgui.spacing()
    label(f.amt_label or "Amount")
    imgui.set_next_item_width(imgui.get_content_region_avail().x - auto_w())
    _, f.amt = slider_float("##amt", f.amt, 0.0, 1.0, "%.2f")
    automation_menu(app, f, "amt", 0.0, 1.0, f.amt_label or "Amount")
    auto_button(app, f, "amt", f.amt_label or "Amount")
    if f.mod == MOD_AUDIO:
        listen_controls(app, f)
    label("Opacity")
    imgui.set_next_item_width(imgui.get_content_region_avail().x - 118 - auto_w())
    _, pct = slider_float("##opacity", f.opacity * 100, 0.0, 100.0, "%.0f%%")
    f.opacity = pct / 100
    automation_menu(app, f, "opacity", 0.0, 1.0, "Opacity")
    imgui.same_line()
    imgui.set_next_item_width(-1 - auto_w())
    _, f.blend = imgui.combo("##blend", f.blend, E.BLEND_MODES)
    if imgui.is_item_hovered():
        imgui.set_tooltip("Blend mode: how this effect combines with what's under it")
    auto_button(app, f, "opacity", "Opacity")
    if f.needs_mask:   # eraser and tracers already work from the person mask themselves
        f.target = 0
    else:
        label("Apply to")
        f.target = segmented("target", ("All", "Subject", "Background"), f.target, MAGENTA)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Use AI background removal to limit this effect to you, or to everything behind you")
    affects_controls(app, f)
    if f.keep_out or (f in app.pipe.order and any(
            t.kind == "trails" and t.opts[0] == 1 and t.on and not t.removing for t in walk_items(app.pipe.order)
            if not is_group(t))):
        label("")
        _, f.keep_out = imgui.checkbox("Keep out of trails", f.keep_out)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Trails / Feedback set to 'Final output' won't pick this up, so it stays crisp\n"
                              "instead of being swept along. The trail is taken just before this card,\n"
                              "so cards below it are left out too: tick the first overlay at the bottom.")
    if f.has_centre:
        label("Centre")
        imgui.set_next_item_width(imgui.get_content_region_avail().x - 64 - auto_w())
        moved, f.centre = slider_float2("##centre", f.centre, 0.0, 1.0, "%.2f")
        if moved and "centre" in f.autos:   # floating: moving it moves the point it floats round
            f.autos["centre"]["base"] = list(f.centre)
        automation_menu(app, f, "centre", 0.0, 1.0, "Centre")
        imgui.same_line(0, 4)
        picking = app.picking is f
        if icon_button(fa.ICON_FA_CROSSHAIRS, "pick", MAGENTA if picking else DIM,
                       "Pick: click or drag on the preview to place the centre"):
            app.picking = None if picking else f
        imgui.same_line(0, 4)
        if icon_button(fa.ICON_FA_ROTATE_LEFT, "rc", DIM, "Reset to the middle"):
            f.centre = [0.5, 0.5]
            if "centre" in f.autos:
                f.autos["centre"]["base"] = [0.5, 0.5]
        auto_button(app, f, "centre", "Centre")
    if f.xform:
        label("Scale")
        imgui.set_next_item_width(imgui.get_content_region_avail().x - 32 - auto_w())
        _, f.xs = slider_float("##xs", f.xs, 0.1, 8.0, "%.2fx", imgui.SliderFlags_.logarithmic)
        automation_menu(app, f, "xs", 0.1, 8.0, "Scale")
        imgui.same_line(0, 4)
        if icon_button(fa.ICON_FA_ROTATE_LEFT, "rxs", DIM, "Back to normal size"):
            f.xs = 1.0
        auto_button(app, f, "xs", "Scale")
        label("Rotate")
        imgui.set_next_item_width(imgui.get_content_region_avail().x - 32 - auto_w())
        _, f.xr = slider_float("##xr", f.xr, -360.0, 360.0, "%.0f deg")
        automation_menu(app, f, "xr", -360.0, 360.0, "Rotate")
        imgui.same_line(0, 4)
        if icon_button(fa.ICON_FA_ROTATE_LEFT, "rxr", DIM, "Back to upright"):
            f.xr = 0.0
        auto_button(app, f, "xr", "Rotate")
        if imgui.is_item_hovered():
            imgui.set_tooltip("Scale and Rotate turn the effect about its Centre; the picture underneath stays put")
    music_controls(app, f)
    if f.has_speed:
        label("Speed")
        imgui.set_next_item_width(imgui.get_content_region_avail().x - 32 - auto_w())
        _, f.speed = slider_float("##speed", f.speed, -3.0, 3.0, "%.2fx")
        automation_menu(app, f, "speed", -3.0, 3.0, "Speed")
        if imgui.is_item_hovered():
            imgui.set_tooltip("0 freezes it, negative runs it backwards (Ctrl+click to type)")
        imgui.same_line(0, 4)
        if icon_button(fa.ICON_FA_ROTATE_LEFT, "rs", DIM, "Back to normal speed"):
            f.speed = 1.0
        auto_button(app, f, "speed", "Speed")
    for j, (name, _default, lo, hi, fmt) in enumerate(f.params):
        label(name)
        imgui.set_next_item_width(imgui.get_content_region_avail().x - auto_w())
        _, f.pvals[j] = slider_float(f"##p{j}", f.pvals[j], lo, hi, fmt)
        automation_menu(app, f, f"p{j}", lo, hi, name)
        auto_button(app, f, f"p{j}", name)
    for j, (name, choices, _default) in enumerate(f.options):
        label(name)
        imgui.begin_disabled(app.midi_learn)
        _, f.opts[j] = imgui.combo(f"##opt{j}", f.opts[j], choices)
        imgui.end_disabled()
        midi_spot(app, (f.id, f"opt{j}"))
        if choices[f.opts[j]] == "Custom":   # the effect's own colours
            custom_colours(f, j)
    imgui.spacing()


def range_controls(app, rng):
    """Pick a frequency range on the live spectrum (click or drag), or type it with two Hz sliders."""
    label("")
    hz = spectrum_strip(app, rng, 30)
    if hz is not None:
        imgui.set_tooltip(f"{hz:.0f} Hz" + chr(10) + "Click or drag to move the nearer end of the range here")
        if imgui.is_mouse_down(0):
            end = 0 if abs(math.log(hz / rng[0])) < abs(math.log(hz / rng[1])) else 1
            rng[end] = float(round(hz))
    label("Range")
    w = (imgui.get_content_region_avail().x - 6) / 2
    imgui.set_next_item_width(w)
    _, rng[0] = slider_float("##rlo", rng[0], 20.0, 16000.0, "%.0f Hz", imgui.SliderFlags_.logarithmic)
    imgui.same_line(0, 6)
    imgui.set_next_item_width(w)
    _, rng[1] = slider_float("##rhi", rng[1], 20.0, 16000.0, "%.0f Hz", imgui.SliderFlags_.logarithmic)


def affects_controls(app, f):
    """Affects: Everything (the picture as it is at this point) or Chosen (only what the effects you tick above it
    contributed, so a warp can hit an overlay and leave the video alone). Also tells a chosen effect who picked it."""
    cont = app.pipe.container_of(f)
    if cont is None or f not in cont:
        return
    i = cont.index(f)
    above = [x for x in cont[:i] if not x.removing]
    key_of = app.pipe.item_key
    mine = key_of(f)
    pickers = [x for x in cont[i + 1:] if not is_group(x) and x.pick and x.on and not x.removing and mine in x.chosen]
    if pickers:
        label("Feeds into")
        imgui.text_colored(MAGENTA, ", ".join(x.name for x in pickers))
        if imgui.is_item_hovered():
            imgui.set_tooltip("What this effect adds to the picture goes through that effect's Chosen setting first")
    label("Affects")
    c = segmented("pick", ("Everything", "Chosen"), int(f.pick), CYAN)
    if bool(c) != f.pick:
        f.pick = bool(c)
    if imgui.is_item_hovered():
        imgui.set_tooltip("Everything: the picture as it is at this point in the chain" + chr(10) +
                          "Chosen: only what the effects you tick below contributed, so it can work on an overlay" +
                          chr(10) + "and leave the video itself alone")
    if not f.pick:
        return
    if not above:
        label("")
        imgui.text_colored(DIM, "Nothing above it yet. Put it below the effects you want it to work on.")
        return
    for x in above:
        k = key_of(x)
        label("")
        ticked = k in f.chosen
        changed, v = imgui.checkbox(f"{x.name}##pk{k}", ticked)
        if changed:
            if v and k not in f.chosen:
                f.chosen.append(k)
            elif not v and k in f.chosen:
                f.chosen.remove(k)
    if not any(key_of(x) in f.chosen for x in above):
        label("")
        imgui.text_colored(DIM, "Tick what it should work on. Until then it does nothing.")


def music_controls(app, f):
    """How an audio-following effect feels: Reactive (as before), Swell (breathes with how loud it has been), Flow
    (travels on a clock that speeds up with the music) or Rhythmic (moves in time with the beat); and how slowly
    it answers. Shown where an effect can follow the sound."""
    audio_on = f.mod == MOD_AUDIO or any(a.get("shape") == 7 for a in f.autos.values())
    if not (f.music or audio_on):
        return
    label("Music")
    names = ("Reactive", "Swell", "Flow", "Rhythmic")
    c = segmented(f"char{f.uid}", names, f.char, CYAN)
    if c != f.char:
        f.char = c
    if imgui.is_item_hovered():
        imgui.set_tooltip("Reactive: follows the sound as it happens" + chr(10) +
                          "Swell: breathes with how loud it has been" + chr(10) +
                          "Flow: drifts on a clock that speeds up with the music" + chr(10) +
                          "Rhythmic: moves in time with the beat")
    label("Response")
    imgui.set_next_item_width(imgui.get_content_region_avail().x - 32 - auto_w())
    _, f.mresp = slider_float(f"##mresp{f.uid}", f.mresp, 0.0, 1.0, "%.2f")
    if imgui.is_item_hovered():
        imgui.set_tooltip("How slowly audio-driven settings answer: 0 quick .. 1 slow and smooth")
    imgui.same_line(0, 4)
    if icon_button(fa.ICON_FA_ROTATE_LEFT, f"rm{f.uid}", DIM, "Back to the middle"):
        f.mresp = 0.5
    auto_button(app, f, None, "Response")


def listen_controls(app, f):
    """What an Audio-driven effect follows, and how quickly it reacts."""
    label("Listens to")
    names = [f"Main setting ({A.SOURCE_NAMES[app.band]})"] + [n for _k, n in A.SOURCES]
    cur = 0 if f.listen is None else A.SOURCE_KEYS.index(f.listen) + 1
    changed, cur = imgui.combo("##listen", cur, names)
    if changed:
        f.listen = None if cur == 0 else A.SOURCE_KEYS[cur - 1]
    if imgui.is_item_hovered():
        imgui.set_tooltip("Main setting: whatever React to (Audio card) is set to\n"
                          "Kick / Snare / Hats / Big kicks: a pulse on each hit\n"
                          "Beat: every beat of the tempo clock\n"
                          "Frequency range: just the part of the sound you pick (e.g. only the vocals)")
    if f.listen == "range":
        range_controls(app, f.rng)
    label("Response")
    custom = segmented("resp", ("Main smoothing", "My own"), 1 if f.resp else 0, MAGENTA)
    if imgui.is_item_hovered():
        imgui.set_tooltip("How quickly it rises with the sound (attack) and falls back (release)")
    if custom and not f.resp:
        f.resp, f.follow = [0.01, 0.25], 0.0
    elif not custom:
        f.resp = None
    if f.resp:
        label("Attack")
        _, ms = slider_float("##att", f.resp[0] * 1000, 0.0, 1000.0, "%.0f ms")
        f.resp[0] = ms / 1000
        label("Release")
        _, ms = slider_float("##rel", f.resp[1] * 1000, 10.0, 4000.0, "%.0f ms", imgui.SliderFlags_.logarithmic)
        f.resp[1] = ms / 1000


def custom_colours(f, j):
    """Swatches for an effect's Custom palette, wrapping onto more rows, with + / - to add or remove one."""
    flags = imgui.ColorEditFlags_.no_inputs | imgui.ColorEditFlags_.picker_hue_wheel
    label("")
    row_x = imgui.get_cursor_pos_x()
    right = imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x
    step = imgui.get_frame_height() + 6
    remove = None
    for k in range(len(f.colours)):
        if k and imgui.get_cursor_pos_x() + step * 2 > right:   # wrap, leaving room for the buttons
            imgui.new_line()
            imgui.set_cursor_pos_x(row_x)
        _, f.colours[k] = imgui.color_edit3(f"##col{j}_{k}", f.colours[k], flags)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Click to pick a colour" + ("\nRight-click to remove it" if len(f.colours) > 2 else ""))
            if imgui.is_mouse_clicked(1) and len(f.colours) > 2:
                remove = k
        imgui.same_line(0, 6)
    if remove is not None:
        f.colours.pop(remove)
    if len(f.colours) < E.MAX_COLOURS:
        if icon_button(fa.ICON_FA_PLUS, f"addcol{j}", CYAN, "Add a colour", V(imgui.get_frame_height(), 0)):
            import colorsys
            h, s, v = colorsys.rgb_to_hsv(*f.colours[-1])
            f.colours.append(list(colorsys.hsv_to_rgb((h + 0.17) % 1.0, max(s, .6), max(v, .8))))
        imgui.same_line(0, 2)
    if len(f.colours) > 2:
        if icon_button(fa.ICON_FA_MINUS, f"delcol{j}", DIM, "Remove the last colour", V(imgui.get_frame_height(), 0)):
            f.colours.pop()
    else:
        imgui.new_line()   # end the row left open by same_line


def mask_section(app):
    """Settings for the AI person mask shared by Background Eraser, Tracers, person outlines and Apply to."""
    p = app.pipe
    label("Quality")
    q = segmented("mq", [name for name, _w, _r in SEG_QUALITY], app.mask_quality, MAGENTA)
    if q != app.mask_quality:
        app.set_mask_quality(q)
    if imgui.is_item_hovered():
        imgui.set_tooltip("How detailed the AI looks. Higher = finer edges, more GPU work\n"
                          "(it runs alongside the video, so frame rate stays the same)")
    label("Edge refine")
    _, p.refine = slider_float("##refine", p.refine, 0.0, 1.0, "%.2f")
    if imgui.is_item_hovered():
        imgui.set_tooltip("Snaps the mask's edge onto the real edges in your camera image\n(hair, fingers, clothing)")
    label("Stability")
    _, p.stability = slider_float("##stable", p.stability, 0.0, 1.0, "%.2f")
    if imgui.is_item_hovered():
        imgui.set_tooltip("Smooths flicker along the edge. Big movements still update instantly.")
    _, S.show_mask = imgui.checkbox("Show mask on preview", S.show_mask)
    plate_controls(app)
    seg = app.segmenter
    if not p.mask_active:
        imgui.text_colored(DIM, "Off until an effect needs it (Eraser, Tracers,\nperson outline, Apply to).")
    elif seg and seg.error:
        imgui.text_colored(RED, seg.error)
    elif seg and seg.loaded:
        imgui.text_colored(DIM, f"Running: {seg.ms:.0f} ms per mask, alongside the video")


def plate_controls(app):
    """Capture background: a photo of the empty room that sharpens the mask and allows Invisible."""
    p = app.pipe
    imgui.spacing()
    label("Countdown")
    delays = app.PLATE_DELAYS
    i = segmented("platedelay", [f"{d:.0f} s" for d in delays],
                  delays.index(app.plate_delay) if app.plate_delay in delays else 1, CYAN)
    app.plate_delay = delays[i]
    if imgui.is_item_hovered():
        imgui.set_tooltip("Time to get out of frame after pressing Capture background")
    counting, grabbing = app.plate_at is not None, p.plate_left > 0
    text = ("Cancel capture" if counting else "Capturing..." if grabbing
            else "Recapture background" if p.plate else "Capture background")
    icon = fa.ICON_FA_XMARK if counting else fa.ICON_FA_CAMERA
    if neon_button(f"{icon}  {text}##plate", RED if counting else CYAN,
                   V(-1 if not p.plate else -sc(34), 0), active=counting or grabbing):
        if counting:
            app.cancel_capture()
        elif not grabbing:
            app.capture_background()
    if imgui.is_item_hovered():
        imgui.set_tooltip("Press, then step out of frame: after the countdown it captures the empty room.\n"
                          "The mask then also uses what changed against it: held objects,\n"
                          "hair and fingers come through better. Keep the camera still and\n"
                          "turn off auto exposure / white balance if you can.\n"
                          "Also lets Background Eraser make you Invisible.")
    if p.plate:
        imgui.same_line()
        if icon_button(fa.ICON_FA_XMARK, "plateoff", RED, tip="Forget the captured background"):
            p.clear_plate()
            return
        label("Plate strength")
        _, p.plate_strength = slider_float("##platek", p.plate_strength, 0.0, 1.0, "%.2f")
        if imgui.is_item_hovered():
            imgui.set_tooltip("How much the captured background shapes the mask (0 = AI only)")
        if app.plate_drift > 0.08:
            imgui.text_colored(RED, f"{fa.ICON_FA_TRIANGLE_EXCLAMATION} The background has changed\n"
                                    "(camera moved or lighting). Recapture it.")
        else:
            imgui.text_colored(DIM, "Background captured")


def transitions_section(app):
    pipe = app.pipe
    label("Transition")
    pipe.transition = segmented("trans", TRANSITIONS, pipe.transition)
    if imgui.is_item_hovered():
        imgui.set_tooltip("Default for switching looks and for effects coming and going\n"
                          "Dissolve: crossfade   Grow: crossfade + strength ramps   Cut: instant\n"
                          "(a look can have its own: right-click its tile > Transition)")
    if pipe.transition != 2:
        label("Time")
        pipe.trans_time, pipe.trans_unit = time_with_unit(app, "ttime", pipe.trans_time, pipe.trans_unit)


def output_section(app):
    label("Resolution")
    changed, idx = imgui.combo("##res", app.res_idx, [r[0] for r in RESOLUTIONS])
    if changed:
        app.set_resolution(idx)
    imgui.spacing()
    label("Record as")
    imgui.begin_disabled(app.recorder.recording)
    _, app.rec_format = imgui.combo("##recfmt", app.rec_format, [f[0] for f in recorder.FORMATS])
    if imgui.is_item_hovered():
        imgui.set_tooltip("MP4 (H.264): plays and edits everywhere, good quality\n"
                          "MP4 small: the same at a third of the size, softer\n"
                          "MOV for editing: every frame a full picture, uncompressed sound, large files")
    label("Record rate")
    app.rec_fps = (30, 60)[segmented("recfps", ("30 fps", "60 fps"), 1 if app.rec_fps == 60 else 0, RED)]
    label("Sound")
    app.rec_sound = segmented("recsound", ("Off", "Audio input"), int(app.rec_sound), RED) == 1
    if imgui.is_item_hovered():
        imgui.set_tooltip("Records the audio input picked under Audio (the same sound the effects react to)\n"
                          "into the same file. Use Voicemeeter or a loopback input to record what you hear.")
    imgui.end_disabled()
    if app.rec_sound:
        src = app.audio.device_name if app.audio.stream else "none yet (Audio, under Input)"
        imgui.dummy(V(sc(LABEL_W) - 8, 0))
        imgui.same_line()
        imgui.text_colored(DIM, f"from: {src}")
    label("Folder")
    short = app.rec_folder if len(app.rec_folder) < 34 else "..." + app.rec_folder[-31:]
    if neon_button(f"{fa.ICON_FA_FOLDER_OPEN}  {short}##recdir", DIM, V(-1, 0),
                   tip="Open the recordings folder"):
        os.makedirs(app.rec_folder, exist_ok=True)
        os.startfile(app.rec_folder)
    imgui.spacing()
    imgui.text_colored(DIM, "OBS, best quality: Spout (top bar), then a\n'Spout2 Capture' source (Spout2 plugin).\n"
                            "Or: Window Capture > Lumoria Output\n"
                            "Virtual cam: Discord, Zoom, browsers.\nOutput window: double-click = fullscreen.")


# ---------------------------------------------------------------- preview

def preview(app):
    avail = imgui.get_content_region_avail()
    W, H = app.pipe.size
    margin = 22
    k = min((avail.x - 2 * margin) / W, (avail.y - 2 * margin) / H)
    size = V(max(1, W * k), max(1, H * k))
    pos = V((avail.x - size.x) / 2, (avail.y - size.y) / 2)
    imgui.set_cursor_pos(pos)
    if app.cropping:
        crop_editor(app, avail, margin)
        return
    uv0, uv1 = ((1, 0), (0, 1)) if app.flip_preview else ((0, 0), (1, 1))
    if app.pipe.alpha_out:   # transparent background: show the classic checkerboard through it
        p0, dl0, k = imgui.get_cursor_screen_pos(), imgui.get_window_draw_list(), sc(14)
        dl0.add_rect_filled(p0, V(p0.x + size.x, p0.y + size.y), u32(rgb("#5a5a5a")))
        for yy in range(int(size.y // k) + 1):
            for xx in range(int(size.x // k) + 1):
                if (xx + yy) % 2:
                    dl0.add_rect_filled(V(p0.x + xx * k, p0.y + yy * k),
                                        V(min(p0.x + size.x, p0.x + (xx + 1) * k), min(p0.y + size.y, p0.y + (yy + 1) * k)),
                                        u32(rgb("#8a8a8a")))
    imgui.image(imgui.ImTextureRef(app.pipe.out.tex.glo), size, V(*uv0), V(*uv1))
    lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
    dl = imgui.get_window_draw_list()
    # monitor bezel: a dark frame around the picture with a lit outer edge
    b = 7
    dl.add_rect_filled(V(lo.x - b, lo.y - b), V(hi.x + b, lo.y), u32(BEZEL))
    dl.add_rect_filled(V(lo.x - b, hi.y), V(hi.x + b, hi.y + b), u32(BEZEL))
    dl.add_rect_filled(V(lo.x - b, lo.y), V(lo.x, hi.y), u32(BEZEL))
    dl.add_rect_filled(V(hi.x, lo.y), V(hi.x + b, hi.y), u32(BEZEL))
    dl.add_rect(V(lo.x - b, lo.y - b), V(hi.x + b, hi.y + b), u32(BORDER), rounding=4, thickness=1)
    dl.add_line(V(lo.x - b + 4, lo.y - b), V(hi.x + b - 4, lo.y - b), u32(EDGE_HI), 1)
    dl.add_rect(V(lo.x - 1, lo.y - 1), V(hi.x + 1, hi.y + 1), u32(EDGE_LO), rounding=0, thickness=1)

    # tally: a red light when the picture is going out
    live = app.vcam is not None or app.out_win.visible
    chip = "PROGRAM" + ("   ON AIR" if live else "")
    imgui.push_font(S.bold, 12)
    tw = imgui.calc_text_size(chip).x
    imgui.pop_font()
    dl.add_rect_filled(V(lo.x + 10, lo.y + 10), V(lo.x + 38 + tw, lo.y + 32), u32(alpha(BEZEL, .8)), 3)
    dl.add_rect(V(lo.x + 10, lo.y + 10), V(lo.x + 38 + tw, lo.y + 32), u32(BORDER), 3)
    led(dl, V(lo.x + 22, lo.y + 21), RED, live, 3.5)
    dl.add_text(S.bold, 12 * S.scale, V(lo.x + 31, lo.y + 14), u32(TEXT if live else DIM), chip)

    if app.plate_at is not None:   # big countdown while the person steps out of frame
        left = max(0.0, app.plate_at - glfw.get_time())
        num, big = f"{int(left) + 1}", sc(150)
        imgui.push_font(S.bold, big)
        sz = imgui.calc_text_size(num)
        imgui.pop_font()
        mid = V((lo.x + hi.x) / 2, (lo.y + hi.y) / 2)
        dl.add_circle_filled(mid, big * .62, u32(alpha(BG, .6)))
        dl.add_text(S.bold, big, V(mid.x - sz.x / 2, mid.y - sz.y / 2), u32(CYAN), num)

    if app.midi_learn:   # what to do, and what's picked
        c = app.midi_control(app.learn_target) if app.learn_target else None
        text = (f"MIDI LEARN   {c[5]}  -  now move a knob / fader or hit a pad" if c else
                "MIDI LEARN   click a control (slider, dropdown, power, music note, Automate, look tile, play / next / prev)")
        imgui.push_font(S.bold, 13)
        tw = imgui.calc_text_size(text).x
        imgui.pop_font()
        cx = (lo.x + hi.x) / 2
        a, b = V(cx - tw / 2 - 14, lo.y + 10), V(cx + tw / 2 + 14, lo.y + 36)
        dl.add_rect_filled(a, b, u32(alpha(BEZEL, .92)), 3)
        dl.add_rect(a, b, u32(AMBER), rounding=3, thickness=1)
        dl.add_text(S.bold, 13 * S.scale, V(a.x + 14, a.y + 6), u32(AMBER), text)

    if app.picking:
        pick_centre(app, lo, hi)
    if S.show_mask and app.pipe.mask_active and app.pipe.mask_ref:
        # current refined mask (red = subject), bottom-right of the preview
        mw = (hi.x - lo.x) * .28
        mh = mw * (hi.y - lo.y) / (hi.x - lo.x)
        imgui.set_cursor_screen_pos(V(hi.x - mw - 12, hi.y - mh - 12))
        imgui.image(imgui.ImTextureRef(app.pipe.mask_ref[app.pipe.ref_i].tex.glo), V(mw, mh))
        a, b = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        dl.add_rect(a, b, u32(MAGENTA), rounding=2, thickness=1)
        dl.add_text(V(a.x + 6, a.y + 4), u32(TEXT), "AI mask")

    if app.msg and glfw.get_time() < app.msg_until:
        lines = app.msg.split("\n")
        tw = max(imgui.calc_text_size(l).x for l in lines)
        th = imgui.get_text_line_height_with_spacing() * len(lines)
        cx = (lo.x + hi.x) / 2
        a, b = V(cx - tw / 2 - 16, hi.y - th - 34), V(cx + tw / 2 + 16, hi.y - 16)
        dl.add_rect_filled(a, b, u32(alpha(TOAST, .94)), 4)
        dl.add_rect(a, b, u32(BORDER), rounding=4, thickness=1)
        dl.add_line(V(a.x + 4, a.y + 1), V(b.x - 4, a.y + 1), u32(EDGE_HI), 1)
        dl.add_text(V(a.x + 16, a.y + 9), u32(TEXT), app.msg)


def crop_editor(app, avail, margin):
    """The preview area while cropping: the whole uncropped source, a box to drag, Apply / Full / Cancel."""
    c = app.cropping
    target = c["target"]
    tex = app.pipe.src_tex if target == "main" else (
        app.pipe.media_tex[target] if app.pipe.media_live[target] else None)
    origin = imgui.get_cursor_screen_pos()
    if tex is None:
        imgui.set_cursor_pos(V(margin, margin))
        imgui.text_colored(DIM, "Waiting for a picture from this source...")
    else:
        tw, th = tex.size
        bar = sc(44)
        k = min((avail.x - 2 * margin) / tw, (avail.y - 2 * margin - bar) / th)
        size = V(max(1, tw * k), max(1, th * k))
        imgui.set_cursor_pos(V((avail.x - size.x) / 2, bar + (avail.y - bar - size.y) / 2))
        imgui.image(imgui.ImTextureRef(tex.glo), size)
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        hovered = imgui.is_item_hovered()
        m = imgui.get_mouse_pos()
        mx = min(1.0, max(0.0, (m.x - lo.x) / size.x))
        my = min(1.0, max(0.0, (m.y - lo.y) / size.y))
        if hovered:
            imgui.set_mouse_cursor(imgui.MouseCursor_.resize_all if c["drag"] is None else imgui.MouseCursor_.arrow)
        if hovered and imgui.is_mouse_clicked(0):
            c["drag"] = (mx, my)
        if c["drag"] is not None:
            if imgui.is_mouse_down(0):
                x0, y0 = c["drag"]
                if abs(mx - x0) > .01 and abs(my - y0) > .01:
                    c["rect"] = [min(x0, mx), min(y0, my), max(x0, mx), max(y0, my)]
            else:
                c["drag"] = None
        x0, y0, x1, y1 = c["rect"]
        a, b = V(lo.x + x0 * size.x, lo.y + y0 * size.y), V(lo.x + x1 * size.x, lo.y + y1 * size.y)
        dl = imgui.get_window_draw_list()
        shade = u32(alpha(BG, .65))
        dl.add_rect_filled(lo, V(hi.x, a.y), shade)                 # dim everything outside the box
        dl.add_rect_filled(V(lo.x, b.y), hi, shade)
        dl.add_rect_filled(V(lo.x, a.y), V(a.x, b.y), shade)
        dl.add_rect_filled(V(b.x, a.y), V(hi.x, b.y), shade)
        dl.add_rect(a, b, u32(MAGENTA), rounding=0, thickness=2)
        dl.add_text(V(a.x + 6, a.y + 4), u32(TEXT),
                    f"{int((x1 - x0) * tw)} x {int((y1 - y0) * th)}")
    # header bar: what's being cropped, and the buttons
    imgui.set_cursor_screen_pos(V(origin.x + margin, origin.y + sc(8)))
    name = "Main" if target == "main" else f"Source {target + 2}"
    imgui.align_text_to_frame_padding()
    imgui.text_colored(MAGENTA, f"{fa.ICON_FA_CROP_SIMPLE}  Crop {name}: drag a box over the part to keep")
    imgui.same_line(0, sc(16))
    if neon_button(f"{fa.ICON_FA_CHECK}  Apply##crop", CYAN, active=True):
        app.finish_crop(True)
        return
    imgui.same_line()
    if neon_button(f"{fa.ICON_FA_EXPAND}  Whole picture##crop", VIOLET):
        c["rect"] = [0.0, 0.0, 1.0, 1.0]
    imgui.same_line()
    if neon_button(f"{fa.ICON_FA_XMARK}  Cancel##crop", RED):
        app.finish_crop(False)


def pick_centre(app, lo, hi):
    """Click/drag on the preview to place the picking effect's centre; release to finish."""
    f = app.picking
    hovered = imgui.is_item_hovered()
    if hovered:
        imgui.set_mouse_cursor(imgui.MouseCursor_.hand)
    if imgui.is_mouse_down(0) and (hovered or app.pick_dragging):
        m = imgui.get_mouse_pos()
        x = min(1.0, max(0.0, (m.x - lo.x) / (hi.x - lo.x)))
        y = min(1.0, max(0.0, (m.y - lo.y) / (hi.y - lo.y)))
        f.centre = [1 - x if app.flip_preview else x, y]
        if "centre" in f.autos:   # floating: the pick sets the point it floats round
            f.autos["centre"]["base"] = list(f.centre)
        app.pick_dragging = True
    elif app.pick_dragging:
        app.picking, app.pick_dragging = None, False
        return
    cx = f.centre[0] if not app.flip_preview else 1 - f.centre[0]
    px, py = lo.x + cx * (hi.x - lo.x), lo.y + f.centre[1] * (hi.y - lo.y)
    dl = imgui.get_window_draw_list()
    col = u32(MAGENTA)
    dl.add_circle(V(px, py), 14, col, 0, 2)
    dl.add_line(V(px - 24, py), V(px + 24, py), col, 2)
    dl.add_line(V(px, py - 24), V(px, py + 24), col, 2)
    text = f"Placing centre: {f.name}  -  click or drag"
    tw = imgui.calc_text_size(text).x
    dl.add_rect_filled(V(hi.x - tw - 30, lo.y + 10), V(hi.x - 10, lo.y + 34), u32(alpha(BG, .8)), 12)
    dl.add_text(V(hi.x - tw - 20, lo.y + 13), col, text)


# ---------------------------------------------------------------- playlist

def playlist_panel(app, panel_h):
    # header / transport
    imgui.set_cursor_pos_y(sc(10))
    if icon_button(fa.ICON_FA_CHEVRON_DOWN if S.playlist_open else fa.ICON_FA_CHEVRON_UP, "plt", DIM,
                   "Collapse" if S.playlist_open else "Expand"):
        S.playlist_open = not S.playlist_open
        save_layout()
    imgui.same_line()
    imgui.align_text_to_frame_padding()
    imgui.push_font(S.bold, 13)
    imgui.text_colored(DIM, f"{fa.ICON_FA_LIST}   PLAYLIST")
    imgui.pop_font()
    imgui.same_line(0, 6)
    imgui.text_colored(alpha(DIM, .6), f"{len(app.playlist)}")

    same = lambda w, gap: imgui.same_line(0, gap)
    transport_buttons(app, same, 26)
    auto_controls(app, same)
    imgui.same_line(0, 18)
    tempo_strip(app)

    # import / export and save, on the right
    first = [True]

    def at_right(w, gap):
        if first[0]:
            first[0] = False
            imgui.same_line(imgui.get_window_width() - 16 - sc(130))
        else:
            imgui.same_line(0, gap)
        imgui.set_cursor_pos_y(sc(10))
    look_file_buttons(app, at_right)
    if S.open_save:   # also requested by the + tile, which lives in a child window
        S.open_save = False
        S.save_name = f"Look {len(app.playlist) + 1}"
        imgui.open_popup("save_look")
    save_popup(app)

    if not S.playlist_open:
        return
    imgui.spacing()
    tiles(app, panel_h)


def transport_buttons(app, nxt, gap=26):
    """Previous / play / next. nxt(width, gap) places each button (beside the last, or on a new line)."""
    fh = sc(28)   # icon_button's width
    nxt(fh, gap)
    if icon_button(fa.ICON_FA_BACKWARD_STEP, "prev", TEXT, "Previous look [Left]") and not app.midi_learn:
        app.playlist_step(-1)
    midi_spot(app, ("app", "prev"))
    nxt(44, 4)
    playing = app.auto_mode != AUTO_OFF
    if neon_button(f"{fa.ICON_FA_PAUSE if playing else fa.ICON_FA_PLAY}##play", CYAN, V(44, 0), playing,
                   "Auto-play [Space]") and not app.midi_learn:
        toggle_play(app)
    midi_spot(app, ("app", "play"))
    nxt(fh, 4)
    if icon_button(fa.ICON_FA_FORWARD_STEP, "next", TEXT, "Next look [Right / N]") and not app.midi_learn:
        app.auto_progress = 0.0
        app.playlist_step(1) if S.auto_kind == AUTO_PLAYLIST else app.randomize()
    midi_spot(app, ("app", "next"))


def auto_controls(app, nxt):
    """What auto-play runs (playlist / random) and how often."""
    nxt(sc(210), 18)
    kind = segmented("kind", (f"{fa.ICON_FA_LIST}  Playlist", f"{fa.ICON_FA_SHUFFLE}  Random"),
                     0 if S.auto_kind == AUTO_PLAYLIST else 1, CYAN, sc(210))
    S.auto_kind = AUTO_PLAYLIST if kind == 0 else AUTO_RANDOM
    if app.auto_mode:
        app.auto_mode = S.auto_kind

    sp = imgui.get_style().item_spacing.x
    nxt(imgui.calc_text_size("every").x + sp + sc(90) + sp + sc(150), 18)   # kept together on one line
    imgui.align_text_to_frame_padding()
    imgui.text_colored(DIM, "every")
    imgui.same_line()
    imgui.set_next_item_width(sc(90))
    _, app.auto_every = slider_int("##every", app.auto_every, 1, 32)
    imgui.same_line()
    app.auto_unit = segmented("unit", tempo.UNITS, app.auto_unit, VIOLET, sc(150))


def look_file_buttons(app, nxt):
    """Save look (importing and exporting looks: the File menu)."""
    save_w = sc(130)
    nxt(save_w, 6)
    if neon_button(f"{fa.ICON_FA_FLOPPY_DISK}   Save look", MAGENTA, V(save_w, 0),
                   tip="Save every effect in the chain, with its settings, as a look in the playlist [Ctrl+S]\n"
                       "Import and export looks: File, top left"):
        S.open_save = True


UNIT_RANGES = [(0.1, 10.0, "%.1f s"), (0.25, 32.0, "%.2g beats"), (0.25, 8.0, "%.2g bars")]


def amount_text(value, unit):
    if not unit:
        return f"{value:.1f}s"
    word = ("beat", "bar")[unit - 1]
    return f"{value:.2g} {word}{'' if value == 1 else 's'}"


def time_with_unit(app, uid, value, unit, width=None):
    """A time slider with its unit (sec / beats / bars). Switching unit keeps the same length at the current
    tempo, so a 2 s fade at 120 BPM becomes 4 beats or 1 bar."""
    avail = (width or imgui.get_content_region_avail().x)
    imgui.set_next_item_width(avail - sc(156))
    lo, hi, fmt = UNIT_RANGES[unit]
    _, value = slider_float(f"##{uid}", value, lo, hi, fmt, imgui.SliderFlags_.logarithmic)
    imgui.same_line(0, 6)
    new_unit = segmented(f"{uid}u", tempo.UNITS, unit, VIOLET, sc(150))
    if new_unit != unit:
        secs = app.tempo.seconds(value, unit)
        lo, hi, _ = UNIT_RANGES[new_unit]
        value = min(hi, max(lo, round(secs / app.tempo.seconds(1.0, new_unit), 2)))
    return value, new_unit


def beat_lights(app, dl, x, cy, r=3.4, gap=11):
    """One light per beat of the bar; the current beat lit (beat 1 in the main light colour)."""
    tp = app.tempo
    now = tp.beat_in_bar()
    fresh = (tp.phase % 1.0) < 0.35
    for i in range(tp.beats_per_bar):
        led(dl, V(x + i * sc(gap), cy), CYAN if i == 0 else MAGENTA, i == now and fresh, r)
    return tp.beats_per_bar * sc(gap)


def tempo_strip(app, nxt=None):
    """Playlist bar: beat lights, the BPM readout, TAP, and when a fired look starts (Launch).
    nxt(width, gap): the Custom layout's Tempo panel, which wraps onto more lines when narrow."""
    tp = app.tempo
    dl = imgui.get_window_draw_list()
    h = imgui.get_frame_height()
    if nxt:
        nxt(tp.beats_per_bar * sc(11) + sc(4), 18)
    p = imgui.get_cursor_screen_pos()
    w = beat_lights(app, dl, p.x + sc(6), p.y + h / 2)
    imgui.dummy(V(w + sc(4), h))
    step = nxt or (lambda w_, gap: imgui.same_line(0, gap))
    # BPM readout in a recessed window
    text = f"{tp.bpm:5.1f}"
    imgui.push_font(S.mono, 16)
    tw = imgui.calc_text_size(text).x
    imgui.pop_font()
    bw = tw + sc(52)
    step(bw, -1)
    p = imgui.get_cursor_screen_pos()
    dl.add_rect_filled(p, V(p.x + bw, p.y + h), u32(LCD_BG), 3)
    dl.add_rect(p, V(p.x + bw, p.y + h), u32(EDGE_LO), 3)
    ty = p.y + (h - imgui.get_text_line_height()) / 2
    dl.add_text(S.mono, 16 * S.scale, V(p.x + sc(8), ty), u32(LCD), text)
    dl.add_text(S.bold, 10 * S.scale, V(p.x + sc(14) + tw, ty + 3), u32(alpha(LCD, .6)),
                ("CLK" if tp.source == tempo.MIDI_CLOCK else tempo.SOURCES[tp.source][:3].upper()))
    imgui.invisible_button("##bpm", V(bw, h))
    if imgui.is_item_hovered():
        imgui.set_tooltip(f"Tempo: {tp.bpm:.1f} BPM from {tempo.SOURCES[tp.source]}  (Settings > Tempo)\n"
                          "T taps the tempo, B makes this beat beat 1 of the bar")
    step(sc(54), 6)
    if neon_button("TAP##tap", CYAN, V(sc(54), 0), glfw.get_time() - (tp.taps[-1] if tp.taps else -9) < .12,
                   "Tap on the beat a few times to set the tempo [T]") and not app.midi_learn:
        tp.tap(glfw.get_time())
    midi_spot(app, ("app", "tap"))
    # launch quantize too, if there's room before the buttons on the right (always in Settings > Tempo)
    if nxt is None:
        room = (imgui.get_window_width() - 16 - sc(130)
                - (imgui.get_item_rect_max().x - imgui.get_window_pos().x))
        if room < sc(320):
            return
    step(imgui.calc_text_size("launch").x + imgui.get_style().item_spacing.x + sc(240), 14)
    imgui.align_text_to_frame_padding()
    imgui.text_colored(DIM, "launch")
    imgui.same_line()
    q = segmented("launch", ("now", "beat", "bar", "4", "8", "16"), app.quantize, AMBER, sc(240))
    if q != app.quantize:
        app.quantize, app.pending_look = q, None
    if imgui.is_item_hovered():
        imgui.set_tooltip("When a look you fire starts: straight away, on the next beat or bar, or at the start\n"
                          "of the next 4, 8 or 16-bar phrase (clicks, Take, MIDI pads, arrow keys and auto-play).\n"
                          "Phrases count from beat 1: press B on a downbeat if they land in the wrong place.")


def tempo_section(app):
    """Settings > Tempo: where the beat comes from, the bar, and launch quantize."""
    tp = app.tempo
    label("Source")
    src = segmented("tsrc", tempo.SOURCES, tp.source, CYAN)
    if src != tp.source:
        tp.source, tp.taps = src, []
    if imgui.is_item_hovered():
        imgui.set_tooltip("Audio: follows the bass of the audio input, steady through quiet parts\n"
                          "Tap: tap a few times on the beat (T, the TAP button or a MIDI pad)\n"
                          "Manual: the BPM below\n"
                          "MIDI clock: follows your DAW's tempo (send MIDI clock to a port Lumoria can see)")
    label("BPM")
    changed, bpm = slider_float("##bpm", tp.bpm, 40.0, 240.0, "%.1f")
    if changed:
        tp.bpm = bpm
        if tp.source != tempo.MIDI_CLOCK:
            tp.source = tempo.MANUAL
    if tp.source == tempo.AUDIO:
        label("Feel")
        mults = (0.5, 1.0, 2.0)
        m = segmented("tmult", ("Half time", "As heard", "Double"), mults.index(tp.mult) if tp.mult in mults else 1,
                      CYAN)
        if mults[m] != tp.mult:
            tp.bpm *= mults[m] / tp.mult
            tp.mult = mults[m]
        if imgui.is_item_hovered():
            imgui.set_tooltip("If the beat feels twice too fast or too slow (common with drum & bass,\n"
                              "trap or half-time grooves), switch it here; the beats stay on the music's grid")
    label("Beats / bar")
    tp.beats_per_bar = segmented("tbar", ("3", "4", "5", "6", "7"), tp.beats_per_bar - 3, VIOLET) + 3
    label("Launch looks")
    q = segmented("tlaunch", ("Now", "Beat", "Bar", "4", "8", "16"), app.quantize, AMBER)
    if q != app.quantize:
        app.quantize, app.pending_look = q, None
    if imgui.is_item_hovered():
        imgui.set_tooltip("When a look starts: at once, on the next beat or bar, or at the start of the next\n"
                          "4, 8 or 16-bar phrase (counted from beat 1: press B on a downbeat to set it)")
    imgui.spacing()
    bw = (imgui.get_content_region_avail().x - 6) / 2
    if neon_button(f"{fa.ICON_FA_HAND_POINTER}  Tap  [T]##ttap", CYAN, V(bw, 0)) and not app.midi_learn:
        tp.tap(glfw.get_time())
    midi_spot(app, ("app", "tap"))
    imgui.same_line(0, 6)
    if neon_button(f"{fa.ICON_FA_1}  Beat 1  [B]##tres", DIM, V(bw, 0),
                   tip="Make this beat beat 1 of the bar (or the nearest one)") and not app.midi_learn:
        tp.resync_bar()
    midi_spot(app, ("app", "resync"))
    p = imgui.get_cursor_screen_pos()
    beat_lights(app, imgui.get_window_draw_list(), p.x + sc(8), p.y + sc(10), 4, 16)
    imgui.dummy(V(1, sc(20)))
    imgui.push_text_wrap_pos(0)
    if tp.source == tempo.AUDIO:
        heard = tp.locked_at is not None and time.perf_counter() - tp.locked_at < 2.0
        if not app.audio.stream:
            imgui.text_colored(DIM, "No audio input (Audio, under Input): running steadily at this BPM.")
        elif not heard:
            imgui.text_colored(AMBER, f"Listening to {app.audio.device_name} for the beat (a few seconds of music)...")
        elif tp.lock < 0.15:
            imgui.text_colored(DIM, f"Locked loosely at {tp.bpm:.1f} BPM: little steady beat in the music right now, "
                                    "so it keeps time on its own.")
        else:
            imgui.text_colored(CYAN, f"Locked to the music: {tp.bpm:.1f} BPM.  Press B on a downbeat to set beat 1.")
    elif tp.source == tempo.MIDI_CLOCK:
        imgui.text_colored(CYAN if tp.clock_running else AMBER,
                           "Receiving MIDI clock." if tp.clock_running else
                           "Waiting for MIDI clock: in your DAW, send MIDI clock to a MIDI port Lumoria can see "
                           "(for software on this PC, a virtual port such as loopMIDI). Start puts it on beat 1.")
    imgui.pop_text_wrap_pos()


def save_popup(app):
    if not imgui.begin_popup("save_look"):
        return
    bold("Save current look", 15)
    if imgui.is_window_appearing():
        imgui.set_keyboard_focus_here()
    imgui.set_next_item_width(240)
    entered, S.save_name = imgui.input_text("##lookname", S.save_name, imgui.InputTextFlags_.enter_returns_true)
    if neon_button("Save", MAGENTA, V(240, 0)) or entered:
        app.save_preset(S.save_name)
        imgui.close_current_popup()
    imgui.end_popup()


def look_meta_popup(app, name):
    """Per-look transition (how it fades in) and timing (how long auto-play stays on it)."""
    if not imgui.begin_popup("lookmeta"):
        return
    m = app.meta(name)
    w = sc(380)
    bold(f"{name}: transition", 15)
    imgui.separator()
    imgui.text_colored(DIM, "How the screen changes over to this look (clicking its tile or auto-play)")
    label("Transition")
    tr = segmented("tr", ["Default"] + LOOK_TRANSITIONS, m["transition"] + 1, VIOLET, w) - 1
    fade, fade_unit = m["fade"], m["fade_unit"]
    if tr == -1:
        imgui.text_colored(DIM, f"Uses the sidebar's Transitions setting: {TRANSITIONS[app.pipe.transition]}"
                                + ("" if app.pipe.transition == 2 else
                                   ", " + amount_text(app.pipe.trans_time, app.pipe.trans_unit)) + ".")
    elif tr != 2:
        label("Time")
        fade, fade_unit = time_with_unit(app, "fade", fade, fade_unit, w)
    imgui.spacing()
    imgui.separator()
    imgui.text_colored(DIM, "Auto-play only: how long to stay on this look before moving on")
    label("Stay")
    custom = segmented("hold", ("Default", "Custom"), 1 if m["hold"] > 0 else 0, VIOLET, w) == 1
    hold, unit = m["hold"], m["unit"]
    if custom:
        hold = max(1, hold or app.auto_every)
        label("For")
        imgui.set_next_item_width(w - sc(150))
        _, hold = slider_int("##holdn", hold, 1, 128)
        imgui.same_line()
        unit = segmented("unit", tempo.UNITS, unit, VIOLET, sc(142))
    else:
        hold = 0
        imgui.text_colored(DIM, f"Uses the playlist's 'every {amount_text(app.auto_every, app.auto_unit)}'.")
    new = dict(transition=tr, fade=round(fade, 2), fade_unit=fade_unit, hold=hold, unit=unit)
    if any(new[k] != m[k] for k in new):
        app.set_meta(name, **new)
    imgui.spacing()
    if neon_button("Done", VIOLET, V(-1, 0)):
        imgui.close_current_popup()
    imgui.end_popup()


def thumb_texture(app, name):
    """The look's thumbnail as a texture (reloaded when its file changes), or None."""
    path = app.thumb_path(name)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    tex, seen = S.thumbs.get(name, (None, None))
    if mtime != seen:
        if tex:
            tex.release()
        tex = None
        img = cv2.imread(path) if mtime else None
        if img is not None:
            h, w = img.shape[:2]
            tex = app.pipe.ctx.texture((w, h), 3, cv2.cvtColor(img, cv2.COLOR_BGR2RGB).tobytes(), alignment=1)
            tex.build_mipmaps()
            tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        S.thumbs[name] = (tex, mtime)
    return tex


def deck(app, panel=False):
    """Beside the tiles: what's cued (or waiting / fading), the crossfader with what's at each end, and Take.
    The fader's start is whichever end it sits nearer once a fade is done, so after a full fade the next look
    comes in on the way back (like A / B decks)."""
    imgui.push_style_var(imgui.StyleVar_.item_spacing, V(4, 3))
    imgui.begin_child("deck", V(0 if panel else sc(232), 0), 0 if panel else imgui.ChildFlags_.borders,
                      imgui.WindowFlags_.no_scrollbar | imgui.WindowFlags_.no_scroll_with_mouse)
    on_air = app.xf_live[0] if app.xf_live else app.current_preset
    left, right = (on_air, app.cued) if app.xf_dir > 0 else (app.cued, on_air)
    w = imgui.get_content_region_avail().x
    take_on = tempo.LAUNCH[app.quantize]
    # the top line: waiting for its beat / phrase, fading, cued, or how to cue
    if app.pending_look:
        left_beats = max(0.0, app.pending_look[1] - app.tempo.phase)
        bars, beats = divmod(math.ceil(left_beats), app.tempo.beats_per_bar)
        when = (f"{bars} bar{'s' if bars != 1 else ''}" + (f" {beats}" if beats else "")
                if bars else f"{beats} beat{'s' if beats != 1 else ''}")
        line, col = f"{fa.ICON_FA_HOURGLASS_HALF}  {app.pending_look[0]} in {when}", AMBER
    elif app.xf_live:
        prog = app.xfader if app.xf_dir > 0 else 1 - app.xfader
        line, col = f"{fa.ICON_FA_SHUFFLE}  Fading {round(prog * 100)}%: Take finishes it", VIOLET
    elif app.cued:
        line, col = f"{fa.ICON_FA_FORWARD}  {app.cued}", VIOLET
    else:
        line, col = "Shift-click a look to cue it", DIM
    imgui.text_colored(col, line)
    # the fader, with what's at each end (on air magenta, cued violet)
    clip = lambda s: "-" if not s else (s if len(s) <= 13 else s[:12] + "...")
    imgui.push_font(S.font, 12)
    imgui.text_colored(MAGENTA if left == on_air else VIOLET, clip(left))
    rt = clip(right)
    imgui.same_line(w - imgui.calc_text_size(rt).x)
    imgui.text_colored(MAGENTA if right == on_air else VIOLET, rt)
    imgui.pop_font()
    imgui.set_next_item_width(w)
    changed, v = slider_float("##xfade", app.xfader * 100, 0.0, 100.0, "%.0f%%")
    if changed:
        app.set_xfader(v / 100)
    if imgui.is_item_hovered():
        imgui.set_tooltip("Crossfader: slide toward the cued look to fade it in by hand; at the far end it's on air,\n"
                          "and the next cued look comes in on the way back.\n"
                          "Map it to a MIDI fader (MIDI learn, click here, move the fader).")
    bw = sc(30)
    if icon_button(fa.ICON_FA_CHEVRON_UP, "cueprev", DIM, "Cue the previous look [Up]", V(bw, 0))             and not app.midi_learn:
        app.cue_step(-1)
    midi_spot(app, ("app", "cue_prev"))
    imgui.same_line()
    if icon_button(fa.ICON_FA_CHEVRON_DOWN, "cuenext", DIM, "Cue the next look [Down]", V(bw, 0))             and not app.midi_learn:
        app.cue_step(1)
    midi_spot(app, ("app", "cue_next"))
    imgui.same_line()
    label_ = "Take" if not app.quantize else f"Take: {take_on if app.quantize > 1 else 'beat'}"
    if neon_button(f"{fa.ICON_FA_PLAY}  {label_}##take", VIOLET, V(-1, 0), bool(app.cued or app.xf_live),
                   "Bring the cued look on with its own transition, "
                   + ("at once" if not app.quantize else f"at the start of the next {take_on if app.quantize > 1 else 'beat'}")
                   + " (set by launch) [Enter]") and not app.midi_learn:
        app.take()
    midi_spot(app, ("app", "take"))
    imgui.end_child()
    imgui.pop_style_var()


def tile_menu_key(mn, mx, tile_hovered):
    """A small drop-down key in a look tile's lower-right corner: opens the same menu as right-clicking the tile.
    Call last for the tile (after its context menu), inside its ID scope; leaves the layout as the tile left it."""
    d = sc(22)
    a = V(mx.x - d - sc(6), mx.y - d - sc(8))
    imgui.set_cursor_screen_pos(a)
    if imgui.invisible_button("##tmenu", V(d, d)):
        imgui.open_popup("tilemenu")
    hov = imgui.is_item_hovered()
    if hov:
        imgui.set_tooltip("Look menu: cue, transition, overwrite, export, thumbnail, delete (or right-click the tile)")
    dl = imgui.get_window_draw_list()
    b = V(a.x + d, a.y + d)
    dl.add_rect_filled(a, b, u32(alpha(BEZEL, .85 if hov else .6)), 3)
    if hov or tile_hovered:
        dl.add_rect(a, b, u32(EDGE_HI if not hov else CYAN), 3)
    icon = fa.ICON_FA_CARET_DOWN
    tw = imgui.calc_text_size(icon)
    dl.add_text(V((a.x + b.x - tw.x) / 2, (a.y + b.y - tw.y) / 2 + 1),
                u32(CYAN if hov else (TEXT if tile_hovered else alpha(DIM, .8))), icon)
    imgui.set_cursor_screen_pos(mn)   # put the layout back as if the tile were the last item
    imgui.dummy(V(mx.x - mn.x, mx.y - mn.y))


def tiles(app, panel_h, with_deck=True):
    # fixed-size tiles that wrap into more rows as the panel gets taller (scroll for the rest)
    th = sc(96)
    tile = V(th * 1.6, th)
    if with_deck:   # the Custom layout has the deck in a panel of its own
        deck(app)
        imgui.same_line(0, 10)
    imgui.begin_child("tiles", V(0, 0))
    per_row = max(1, int((imgui.get_content_region_avail().x + 10) // (tile.x + 10)))
    move = None
    for i, name in enumerate(list(app.playlist)):
        if i % per_row:
            imgui.same_line(0, 10)
        active = name == app.current_preset
        imgui.push_id(f"tile{name}")
        imgui.set_next_item_allow_overlap()   # the menu key in its corner sits on top of it
        if imgui.invisible_button("##tile", tile) and not app.midi_learn:
            if imgui.get_io().key_shift:
                app.cue(None if app.cued == name else name)
            else:
                app.load_preset(name)
        midi_spot(app, ("look", name))
        mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        dl = imgui.get_window_draw_list()
        hovered = imgui.is_item_hovered()
        keycap(dl, mn, mx, hovered, imgui.is_item_active(), None, 4)
        thumb = thumb_texture(app, name)
        if thumb:   # the look itself, behind its number and name, with shading so the text stays readable
            tw_, th_ = thumb.size
            a, b = V(mn.x + 2, mn.y + 2), V(mx.x - 2, mx.y - 2)
            box, img = (b.x - a.x) / (b.y - a.y), tw_ / th_
            u0, v0 = (0.5 - box / img / 2, 0.0) if img > box else (0.0, 0.5 - img / box / 2)
            shade = 1.0 if active or hovered else 0.72
            dl.add_image_rounded(imgui.ImTextureRef(thumb.glo), a, b, V(u0, v0), V(1 - u0, 1 - v0),
                                 u32(imgui.ImVec4(shade, shade, shade, 1.0)), 3)
            dark, clear = u32(alpha(BEZEL, .82)), u32(alpha(BEZEL, 0.0))
            mid = a.y + (b.y - a.y) * 0.42
            dl.add_rect_filled_multi_color(a, V(b.x, mid), dark, dark, clear, clear)   # under number + badge
            mid = a.y + (b.y - a.y) * 0.45
            dl.add_rect_filled_multi_color(V(a.x, mid), b, clear, clear, dark, dark)   # under the name
            if active:
                dl.add_rect(V(mn.x + 1, mn.y + 1), V(mx.x - 1, mx.y - 1), u32(CYAN), rounding=4, thickness=2)
        dl.add_text(S.mono, 16 * S.scale, V(mn.x + sc(12), mn.y + sc(10)),
                    u32(TEXT if active or thumb else DIM), f"{i + 1:02d}")
        imgui.push_font(S.bold, 17)
        room, shown = mx.x - mn.x - sc(12) - sc(34), name   # clear of the menu key in the corner
        while len(shown) > 1 and imgui.calc_text_size(shown if shown == name else shown + "...").x > room:
            shown = shown[:-1]
        dl.add_text(V(mn.x + sc(12), mx.y - sc(34)), u32(TEXT if active or thumb else KEY_TEXT),
                    shown if shown == name else shown.rstrip() + "...")
        imgui.pop_font()
        led(dl, V(mx.x - sc(16), mn.y + sc(17)), CYAN, active, 3.5)   # lit on the look that's playing
        if app.cued == name:   # lined up to go next
            dl.add_rect(V(mn.x + 1, mn.y + 1), V(mx.x - 1, mx.y - 1), u32(VIOLET), rounding=4, thickness=2)
            imgui.push_font(S.bold, 11)
            cw = imgui.calc_text_size("CUED").x
            imgui.pop_font()
            dl.add_rect_filled(V(mx.x - cw - sc(34), mn.y + sc(10)), V(mx.x - sc(26), mn.y + sc(24)), u32(VIOLET), 2)
            dl.add_text(S.bold, 11 * S.scale, V(mx.x - cw - sc(30), mn.y + sc(11)), u32(BEZEL), "CUED")
        if app.pending_look and app.pending_look[0] == name:   # fired, waiting for its beat / bar
            left = app.pending_look[1] - app.tempo.phase
            pulse = .5 + .5 * math.cos(app.tempo.phase * 6.2832)
            dl.add_rect(V(mn.x + 1, mn.y + 1), V(mx.x - 1, mx.y - 1), u32(alpha(AMBER, .45 + .55 * pulse)),
                        rounding=4, thickness=2)
            imgui.push_font(S.mono, 22)
            txt = f"{max(1, math.ceil(left))}"
            tw_ = imgui.calc_text_size(txt).x
            imgui.pop_font()
            dl.add_text(S.mono, 22 * S.scale, V(mx.x - tw_ - sc(12), mn.y + sc(28)), u32(AMBER), txt)
        # this look's own transition / timing, if it has any
        m = app.meta(name)
        badge = []
        if m["transition"] >= 0:
            badge.append(LOOK_TRANSITIONS[m["transition"]] + ("" if m["transition"] == 2 else
                                                              " " + amount_text(m["fade"], m["fade_unit"])))
        if m["hold"] > 0:
            badge.append(f"{fa.ICON_FA_CLOCK} {amount_text(m['hold'], m['unit'])}")
        if badge:
            dl.add_text(V(mn.x + sc(12), mn.y + sc(32)), u32(alpha(CYAN, .85)), "  ".join(badge))   # in the theme's light
        if active and app.auto_mode:   # how long until auto-play moves on
            dl.add_rect_filled(V(mn.x + 6, mx.y - 5), V(mn.x + 6 + (mx.x - mn.x - 12) * min(1, app.auto_progress),
                                                        mx.y - 3), u32(CYAN), 1)
        if imgui.begin_drag_drop_source():
            imgui.set_drag_drop_payload_py_id("LOOK", i)
            imgui.text(name)
            imgui.end_drag_drop_source()
        if imgui.begin_drag_drop_target():
            payload = imgui.accept_drag_drop_payload_py_id("LOOK")
            if payload is not None:
                move = (payload.data_id, i)
            imgui.end_drag_drop_target()
        if imgui.begin_popup_context_item("tilemenu"):
            bold(name, 15)
            imgui.separator()
            if imgui.selectable(f"{fa.ICON_FA_FORWARD}   " + ("Uncue" if app.cued == name else "Cue (line it up to go next)"),
                                False)[0]:
                app.cue(None if app.cued == name else name)
            if imgui.selectable(f"{fa.ICON_FA_WAND_MAGIC_SPARKLES}   Transition...", False)[0]:
                S.meta_open = name
            if imgui.selectable(f"{fa.ICON_FA_FLOPPY_DISK}   Overwrite with current look", False)[0]:
                app.save_preset(name)
            if imgui.selectable(f"{fa.ICON_FA_FILE_EXPORT}   Export this look...", False)[0]:
                app.ask_export([name])
            if imgui.selectable(f"{fa.ICON_FA_CAMERA}   Update thumbnail (from the output now)", False)[0]:
                app.save_thumb(name)
            if imgui.selectable(f"{fa.ICON_FA_TRASH}   Delete...", False)[0]:
                S.confirm_delete = name
            imgui.end_popup()
        tile_menu_key(mn, mx, hovered)
        if S.meta_open == name:   # opened here so it shares the tile's ID scope
            S.meta_open = None
            imgui.open_popup("lookmeta")
        look_meta_popup(app, name)
        imgui.pop_id()

    # the last tile saves what's on screen right now as a new look
    if len(app.playlist) % per_row:
        imgui.same_line(0, 10)
    if imgui.invisible_button("##addtile", tile):
        S.open_save = True
    mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
    dl = imgui.get_window_draw_list()
    hov = imgui.is_item_hovered()
    dl.add_rect_filled(mn, mx, u32(FRAME), 4)   # an empty slot, recessed, until hovered
    dl.add_rect(mn, mx, u32(EDGE_HI if hov else BORDER), rounding=4, thickness=1)
    for k, line in enumerate((fa.ICON_FA_PLUS, "SAVE CURRENT LOOK")):
        imgui.push_font(S.bold, 12.5)
        tw = imgui.calc_text_size(line).x
        imgui.pop_font()
        dl.add_text(S.bold, 12.5 * S.scale, V((mn.x + mx.x - tw) / 2, (mn.y + mx.y) / 2 - sc(16) + k * sc(18)),
                    u32(TEXT if hov else DIM), line)
    if imgui.is_item_hovered():
        imgui.set_tooltip("Saves every effect in the chain, with all its settings, as a look you can fire later")
    if not app.playlist:
        imgui.same_line(0, 18)
        imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + th / 2 - imgui.get_text_line_height())
        imgui.text_colored(DIM, "Build a chain of effects in the sidebar, then save it here as a look.\n"
                                "Click a look's tile any time to bring that whole setup back.")
    imgui.end_child()
    if move and move[0] != move[1]:
        app.playlist.insert(move[1], app.playlist.pop(move[0]))
        app.save_playlist()
