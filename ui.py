"""Lumoria interface: neon-on-black theme, top bar, sidebar of effect cards, preview, playlist panel."""
import ctypes
import json
import math
import os
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
import tempo
from audio import list_inputs
from segment import QUALITY as SEG_QUALITY
from shared import (AUTO_OFF, AUTO_PLAYLIST, AUTO_RANDOM, DATA, HERE, LOOK_TRANSITIONS, MOD_AUDIO, MOD_WAVE,
                    RESOLUTIONS, SOURCE_URL, SUPPORT_URL, TRANSITIONS, VERSION)
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

TOPBAR_H, PLAYLIST_SHUT_H, LABEL_W, GAP = 54, 52, 96, 6   # GAP: draggable seam between panels
SETTINGS_FILE = os.path.join(DATA, "ui_settings.json")
LAYOUT_DEFAULTS = dict(sidebar_w=410.0, playlist_h=196.0, playlist_open=True, scale=1.0, card_cols=0,
                       theme="Console", accent=0, header_tint=False, side_tab=0, welcomed=False,
                       card_warnings=0, logo_look=0, theme_keys=0)
CARD_MIN_W = 300   # auto grid: a new column of effect cards appears whenever this much more width fits


class _State:
    font = bold = None
    sidebar_w, playlist_h, playlist_open, scale = 410.0, 196.0, True, 1.0   # remembered layout
    card_cols = 0                  # effect card grid columns, 0 = auto from the sidebar width
    theme, accent = "Console", 0   # interface theme (THEMES) and light colour (ACCENTS index)
    header_tint = False            # card headers take on a little of their LED colour
    card_warnings = 0              # "hidden by" notes on cards: 0 full text, 1 icon only, 2 off
    theme_anchor = None            # bottom-right of the palette button when its popup opened
    windows = []                   # the app's GLFW windows, for title bar colours (set by app.main)
    theme_keys = 0                 # where the theme keys live: 0 a palette button (top bar, right), 1 a strip after the readout
    logo_look = 0                  # 0 Original artwork, 1 Neon (redrawn, white wordmark), 2 Neon colour (gradient wordmark)
    side_tab = 0                   # sidebar tab: 0 Effects, 1 Settings
    welcomed = False               # the welcome window has been seen (Settings > About shows it again)
    welcome_open = False
    confirm_delete = None          # a look waiting for "Delete it?" to be answered
    show_keys = False              # F1: the keyboard shortcuts sheet
    brand = None                   # (small symbol, large symbol, wordmark) textures from assets/, loaded on first use
    lcd_end = 0.0                  # where the top bar's readout ends (theme keys go after it)
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
        setattr(S, k, type(v)(saved.get(k, v)))


def save_layout():
    try:
        with open(SETTINGS_FILE, "w") as fh:
            json.dump({k: getattr(S, k) for k in LAYOUT_DEFAULTS}, fh, indent=1)
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
    """A card's title strip: a raised, shaded band across its top, ruled off from the controls below; with the
    Tinted header option, a card that's on takes on a little of its LED colour `lamp`.
    Call right after begin_child, before the header row (whose height is sc(28))."""
    wp, ww = imgui.get_window_pos(), imgui.get_window_width()
    bot = imgui.get_cursor_screen_pos().y + sc(28) + 3
    top_c, bot_c = (STRIP_ON_TOP, STRIP_ON_BOT) if on else (STRIP_TOP, STRIP_BOT)
    if on and lamp is not None and S.header_tint:
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
            midi_spot(S.app, target)
            return False, value
        return wrapped_inner(label_, value, *args, **kw)

    def wrapped_inner(label_, value, *args, **kw):
        own = default_fmt is not None and imgui.get_id(label_) not in _typing
        if own:   # imgui centres the number, right where the handle sits at mid values; hide it, draw our own
            imgui.push_style_color(imgui.Col_.text, CLEAR)
        changed, new = widget(label_, value, *args, **kw)
        key = imgui.get_item_id()
        if own:
            imgui.pop_style_color()
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
        return changed, new
    return wrapped


def slider_target(label_):
    """The MIDI target (scope, key) of a slider, from where it's drawn and its label; None if not mappable."""
    key = label_.lstrip("#")
    if S.midi_scope and (key in ("amt", "opacity", "speed") or (key[:1] == "p" and key[1:].isdigit())):
        return (S.midi_scope, key)
    if not S.midi_scope and key in ("gain", "ttime", "wave"):
        return ("app", key)
    return None


def midi_spot(app, target):
    """MIDI learn on the control just drawn: outline it, tag it with its link, and pick it on click."""
    if not app.midi_learn or target is None:
        return
    mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
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
    if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled) and imgui.is_mouse_clicked(0):
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

    tb = sc(TOPBAR_H)
    S.sidebar_w = min(max(S.sidebar_w, sc(280)), max(sc(280), W - 320))
    S.playlist_h = min(max(S.playlist_h, sc(130)), max(sc(130), H - tb - 220))
    pl_h = S.playlist_h if S.playlist_open else sc(PLAYLIST_SHUT_H)
    sw, mid_h = S.sidebar_w, max(50, H - tb - GAP - pl_h)
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
    imgui.end()

    restore_prompt(app)
    welcome(app)
    delete_prompt(app)
    keys_sheet()

    if S.pending_move:   # applied after drawing so lists don't change mid-loop
        uid, dest, index = S.pending_move
        S.pending_move = None
        if (item := app.pipe.find(uid)) is not None and item is not (dest[index] if index is not None
                                                                       and index < len(dest) else None):
            app.pipe.move_item(item, dest, index)


WELCOME_TIPS = [
    (fa.ICON_FA_PLAY, "Fire a look", "Click a tile in the playlist at the bottom. The sample looks are there to try."),
    (fa.ICON_FA_LAYER_GROUP, "Make your own", "Effects tab: + Add effect, tweak the cards, then Save look."),
    (fa.ICON_FA_SLIDERS, "Play it with hardware", "MIDI learn (top bar): click a control, then move a knob or hit a pad."),
    (fa.ICON_FA_SHARE_NODES, "Send it to OBS", "Spout (top bar) with the Spout2 plugin, or Window Capture of "
                                                 "'Lumoria Output'."),
    (fa.ICON_FA_ROTATE_LEFT, "Experiment freely", "Ctrl+Z undoes any change. Themes, AI mask and MIDI are in the "
                                                   "Settings tab."),
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

def theme_menu():
    """The palette button's popup: the themes, each with an LED in its light colour, and the Lights choice."""
    if S.theme_anchor is not None:
        imgui.set_next_window_pos(V(S.theme_anchor.x, S.theme_anchor.y + 4), imgui.Cond_.appearing, V(1, 0))
    if not imgui.begin_popup("##themes"):
        return
    imgui.push_font(S.bold, 12.5)
    imgui.text_colored(DIM, "THEME")
    imgui.pop_font()
    dl = imgui.get_window_draw_list()
    for name in THEMES:
        p = imgui.get_cursor_screen_pos()
        if imgui.selectable(f"      {name}##pick{name}", name == S.theme, 0, V(sc(150), 0))[0]:
            apply_theme(name, S.accent)
            save_layout()
        led(dl, V(p.x + sc(8), p.y + imgui.get_text_line_height() / 2), rgb(THEMES[name]["CYAN"]), True, 2.8)
    imgui.separator()
    imgui.push_font(S.bold, 12.5)
    imgui.text_colored(DIM, "LIGHTS")
    imgui.pop_font()
    for i, (name, col) in enumerate(ACCENTS):
        p = imgui.get_cursor_screen_pos()
        if imgui.selectable(f"      {name}##light{i}", i == S.accent, 0, V(sc(150), 0))[0]:
            apply_theme(S.theme, i)
            save_layout()
        led(dl, V(p.x + sc(8), p.y + imgui.get_text_line_height() / 2),
            rgb(col or THEMES[S.theme]["CYAN"]), True, 2.8)
    imgui.end_popup()


def theme_chips(right_edge):
    """A strip of theme keys after the readout, each with an LED in its theme's light colour. Left out when
    the window is too narrow (Settings > Interface has the same choice)."""
    names = list(THEMES)
    pad = imgui.get_style().frame_padding.x
    imgui.push_font(S.bold, 12.5)
    ws = [imgui.calc_text_size(n).x + pad * 2 + sc(16) for n in names]
    imgui.pop_font()
    start = S.lcd_end + sc(18)
    total = sum(ws) + 4 + 2 * (len(ws) - 1)
    if start + total > right_edge - sc(18):
        return
    y = imgui.get_window_pos().y + sc(12)
    h = imgui.get_frame_height()
    dl = imgui.get_window_draw_list()
    dl.add_rect_filled(V(start, y), V(start + total, y + h), u32(FRAME), 3)
    dl.add_rect(V(start, y), V(start + total, y + h), u32(BORDER), 3)
    cx = start + 2
    imgui.push_font(S.bold, 12.5)
    for name, w in zip(names, ws):
        imgui.set_cursor_screen_pos(V(cx, y + 2))
        if neon_button(f"      {name}##theme{name}", CYAN, V(w, h - 4), name == S.theme, f"{name} theme",
                       flat=True):
            apply_theme(name, S.accent)
            save_layout()
        mn = imgui.get_item_rect_min()
        led(dl, V(mn.x + sc(10), mn.y + (h - 4) / 2), rgb(THEMES[name]["CYAN"]), True, 2.6)
        cx += w + 2
    imgui.pop_font()


LOGO_SETS = [("lumoria_symbol", "lumoria_symbol", "lumoria_wordmark"),
             ("lumoria_symbol_neon", "lumoria_symbol_neon_glow", "lumoria_wordmark_neon"),
             ("lumoria_symbol_neon", "lumoria_symbol_neon_glow", "lumoria_wordmark_neon_gradient")]


def brand_textures(ctx):
    """The logo as GPU textures, or None: a crisp symbol for small spots (top bar), a glowing one for large
    (welcome), and the LUMORIA wordmark, from assets/*.png in the chosen Settings > Interface > Logo."""
    if S.brand is None:
        texs = []
        for name in LOGO_SETS[S.logo_look if 0 <= S.logo_look < len(LOGO_SETS) else 0]:
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

    # status readout: a recessed LCD window
    imgui.same_line(0, 28)
    src_icon = fa.ICON_FA_VIDEO if isinstance(app.source, CameraSource) else (
        fa.ICON_FA_BARCODE if app.source is None else fa.ICON_FA_FILM)
    w, h = app.pipe.size
    readout = f"{w}x{h}  {app.fps:>3} FPS"
    label_ = app.source_label if len(app.source_label) <= 34 else app.source_label[:33] + "..."
    imgui.push_font(S.mono, 16)
    rw = imgui.calc_text_size(f"{src_icon}  {label_}").x + imgui.calc_text_size(readout).x + 46
    imgui.pop_font()
    p = imgui.get_cursor_screen_pos()
    top, bot = p.y + sc(9) - 2, p.y + sc(36) + 2
    dl = imgui.get_window_draw_list()
    dl.add_rect_filled(V(p.x, top), V(p.x + rw, bot), u32(LCD_BG), 3)
    dl.add_rect(V(p.x, top), V(p.x + rw, bot), u32(EDGE_LO), 3)
    dl.add_line(V(p.x + 3, bot), V(p.x + rw - 3, bot), u32(EDGE_HI), 1)   # lit lower lip
    ty = (top + bot - imgui.get_text_line_height()) / 2
    lcd = LCD
    dl.add_text(S.mono, 16 * S.scale, V(p.x + 12, ty), u32(alpha(lcd, .55)), src_icon)
    dl.add_text(S.mono, 16 * S.scale, V(p.x + 34, ty), u32(lcd), label_)
    imgui.push_font(S.mono, 16)
    lw = imgui.calc_text_size(label_).x
    imgui.pop_font()
    dl.add_text(S.mono, 16 * S.scale, V(p.x + 34 + lw + 18, ty), u32(alpha(lcd, .7)), readout)
    imgui.dummy(V(rw, 1))
    S.lcd_end = p.x + rw

    # right-hand status toggles
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
    if S.theme_keys == 0:
        items.append((f"{fa.ICON_FA_PALETTE}", False, CYAN, "theme", f"Theme and lights ({S.theme})"))
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
    pad = imgui.get_style().frame_padding.x
    widths = [imgui.calc_text_size(t).x + pad * 2 for t, *_ in items]
    x = imgui.get_window_width() - 16 - sum(widths) - 8 * (len(items) - 1)
    if S.theme_keys == 1:
        theme_chips(imgui.get_window_pos().x + x)
    for i, (text, active, col, key, tip) in enumerate(items):
        imgui.same_line(x)
        imgui.set_cursor_pos_y(sc(12))
        if neon_button(f"{text}##{key}", col, V(widths[i], 0), active, tip):
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
            elif key == "theme":
                imgui.open_popup("##themes")
                S.theme_anchor = imgui.get_item_rect_max()   # the popup hangs below the button, right-aligned
            elif key == "midi":
                app.midi_learn, app.learn_target = not app.midi_learn, None
            else:
                app.toggle_vcam()
        if key == "midi":   # activity light: flickers while MIDI is coming in
            mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            led(imgui.get_window_draw_list(), V(mx.x - 7, mn.y + 7), CYAN, glfw.get_time() - app.midi_seen < .12, 2.4)
        x += widths[i] + 8
    theme_menu()


# ---------------------------------------------------------------- sidebar

def sidebar(app):
    """Two tabs: Effects (what you play: inputs, audio, the chain) and Settings (set once: AI mask, transitions,
    MIDI, output, interface, about)."""
    imgui.spacing()
    tab = segmented("sidetab", (f"{fa.ICON_FA_LAYER_GROUP}   EFFECTS", f"{fa.ICON_FA_GEAR}   SETTINGS"), S.side_tab)
    if tab != S.side_tab:
        S.side_tab = tab
        save_layout()
    imgui.spacing()
    if S.side_tab == 0:
        settings_cards("top", [("Input", fa.ICON_FA_VIDEO, lambda: input_section(app)),
                               ("Audio", fa.ICON_FA_MUSIC, lambda: audio_section(app))])
        if section("Effects", fa.ICON_FA_LAYER_GROUP):
            effects_section(app)
    else:
        settings_cards("settings", [("AI Mask", fa.ICON_FA_USER, lambda: mask_section(app)),
                                    ("Tempo", fa.ICON_FA_DRUM, lambda: tempo_section(app)),
                                    ("Transitions", fa.ICON_FA_WAND_MAGIC_SPARKLES, lambda: transitions_section(app)),
                                    ("Output", fa.ICON_FA_TV, lambda: output_section(app)),
                                    ("MIDI", fa.ICON_FA_SLIDERS, lambda: midi_section(app)),
                                    ("Interface", fa.ICON_FA_PALETTE, interface_section),
                                    ("About", fa.ICON_FA_CIRCLE_INFO, about_section)])
    imgui.dummy(V(1, 12))


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
    imgui.same_line()
    if neon_button(f"{fa.ICON_FA_SLIDERS}  {'Finish learning' if app.midi_learn else 'MIDI learn'}##ml", AMBER,
                   V(-1, 0), app.midi_learn):
        app.midi_learn, app.learn_target = not app.midi_learn, None
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
    label("Theme")
    names = list(THEMES)
    i = names.index(S.theme) if S.theme in names else 0
    changed, i = imgui.combo("##theme", i, names)
    if changed:
        apply_theme(names[i], S.accent)
        save_layout()
    if imgui.is_item_hovered():
        imgui.set_tooltip("Console: graphite and metal   Neon: the original neon-on-black\n"
                          "Midnight: navy and blue   Analog: warm vintage gear   Carbon: black stage desk")
    label("Lights")
    changed, a = imgui.combo("##accent", S.accent, [n for n, _ in ACCENTS])
    if changed:
        apply_theme(S.theme, a)
        save_layout()
    if imgui.is_item_hovered():
        imgui.set_tooltip("The main light colour: lit keys, LEDs, meters and slider levels.\n"
                          "Theme = the theme's own.")
    label("Theme keys")
    tk = segmented("themekeys", ("Palette button", "Top bar strip"), S.theme_keys, CYAN)
    if tk != S.theme_keys:
        S.theme_keys = tk
        save_layout()
    if imgui.is_item_hovered():
        imgui.set_tooltip("Quick theme switching from the top bar:\n"
                          "a palette button at the right, or the row of theme keys after the readout")
    label("Card warnings")
    cw = segmented("cwarn", ("Full", "Icon only", "Off"), S.card_warnings, AMBER)
    if cw != S.card_warnings:
        S.card_warnings = cw
        save_layout()
    if imgui.is_item_hovered():
        imgui.set_tooltip("The amber notes on effect cards when a later effect hides them\n"
                          "Icon only: a small mark, hover it for the details")
    label("Logo")
    ls = segmented("logo", ("Original", "Neon", "Neon colour"), S.logo_look, VIOLET)
    if ls != S.logo_look:
        for tex, _ in S.brand or []:
            tex.release()
        S.logo_look, S.brand = ls, None   # reloads in the new style on the next frame
        save_layout()
    if imgui.is_item_hovered():
        imgui.set_tooltip("The Lumoria logo in the top bar, welcome window and window icon (after a restart)\n"
                          "Original: the glossy artwork   Neon: redrawn crisp light trails, white wordmark\n"
                          "Neon colour: the same with a gradient wordmark")
    label("Card headers")
    tint = segmented("tint", ("Plain", "Tinted"), int(S.header_tint), CYAN) == 1
    if tint != S.header_tint:
        S.header_tint = tint
        save_layout()
    if imgui.is_item_hovered():
        imgui.set_tooltip("Tinted: a card that's on takes on a little of its LED colour\n"
                          "(blue = manual, amber = audio, violet = wave and groups)")
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
    imgui.text_colored(DIM, "Drag the lines between panels to resize them.")
    if neon_button(f"{fa.ICON_FA_ROTATE_LEFT}   Reset layout", DIM, V(-1, 0)):
        for k, v in LAYOUT_DEFAULTS.items():
            setattr(S, k, v)
        save_layout()


KIND_ICONS = {"camera": fa.ICON_FA_VIDEO, "video": fa.ICON_FA_FILM, "image": fa.ICON_FA_IMAGE,
              "screen": fa.ICON_FA_DESKTOP, "window": fa.ICON_FA_WINDOW_MAXIMIZE, "test": fa.ICON_FA_BARCODE,
              "none": fa.ICON_FA_CIRCLE_XMARK}
# the effect library's category headings (the icon set's choices; Feedback and Sources made distinct)
CAT_ICONS = {"Motion": fa.ICON_FA_ARROWS_UP_DOWN_LEFT_RIGHT, "Mirror & Geometry": fa.ICON_FA_SHAPES,
             "Stylize": fa.ICON_FA_STAR, "Colour": fa.ICON_FA_DROPLET, "Overlay": fa.ICON_FA_LAYER_GROUP,
             "Feedback": fa.ICON_FA_ARROWS_ROTATE, "Cutout": fa.ICON_FA_USER, "Sources": fa.ICON_FA_PHOTO_FILM,
             "Interactive": fa.ICON_FA_HAND_SPARKLES, "Other": fa.ICON_FA_CUBES}


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


def audio_section(app):
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
    bands = ("bass", "mid", "high", "all")
    label("React to")
    app.band = bands[segmented("band", ("Bass", "Mids", "Highs", "All"), bands.index(app.band), MAGENTA)]
    label("Sensitivity")
    _, app.gain = slider_float("##gain", app.gain, 0.2, 3.0, "%.2f")
    for b, name in (("bass", "Bass"), ("mid", "Mids"), ("high", "Highs")):
        imgui.text_colored(DIM, name)
        imgui.same_line(sc(LABEL_W))
        imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + sc(7))
        meter(app.audio.level[b], MAGENTA if b == app.band else alpha(MAGENTA, .45))


def is_group(f):
    return hasattr(f, "children")


def walk_items(items):
    for it in items:
        yield it
        if is_group(it):
            yield from walk_items(it.children)


def effects_section(app):
    gap = 6
    w_small = sc(40)
    avail = imgui.get_content_region_avail().x
    if neon_button(f"{fa.ICON_FA_PLUS}   Add effect", CYAN, V(avail - 6 * (w_small + gap), 0)):
        S.lib_target, S.open_lib = None, True
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
    draw_items(app, app.pipe.order, top=True)


def draw_items(app, items, top):
    """Cards for one chain level: effects flow in a grid; a group takes a full row."""
    visible = [f for f in items if not f.removing]
    cols = card_columns()
    run = []

    def flush():
        if not run:
            return
        if cols == 1:
            for n, f in run:
                effect_card(app, f, n, items)
        else:   # masonry: card k goes in column k % cols, so chain order still reads left to right, and
            # each column stacks its own cards, so a short card never leaves a gap beside a tall one
            imgui.push_style_var(imgui.StyleVar_.cell_padding, V(4, 4))
            if imgui.begin_table(f"cards{run[0][1].uid}", cols,
                                 imgui.TableFlags_.sizing_stretch_same | imgui.TableFlags_.no_pad_outer_x):
                for c in range(cols):
                    imgui.table_next_column()
                    for n, f in run[c::cols]:
                        effect_card(app, f, n, items)
                imgui.end_table()
            imgui.pop_style_var()
        run.clear()

    for i, f in enumerate(visible):
        n = i if top else None   # number keys work on the top level
        if is_group(f):
            flush()
            group_card(app, f, n, items)
        else:
            run.append((n, f))
    flush()


def card_drag_source(f):
    if imgui.begin_drag_drop_source():
        imgui.set_drag_drop_payload_py_id("FX", f.uid)
        imgui.text(f"{fa.ICON_FA_FOLDER if is_group(f) else fa.ICON_FA_LAYER_GROUP}  {f.name}")
        imgui.end_drag_drop_source()


def card_drop_target(dest, index):
    """Dropping a card here moves it into dest (a chain list) before index, or to the end if None."""
    if imgui.begin_drag_drop_target():
        payload = imgui.accept_drag_drop_payload_py_id("FX")
        if payload is not None:
            S.pending_move = (payload.data_id, dest, index)
        imgui.end_drag_drop_target()


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
    card_drag_source(f)
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
    if icon_button(MOD_ICONS[f.mod], "mod", MOD_COLS[f.mod], MOD_TIPS[f.mod] + "\n(click to cycle)"):
        f.mod = (f.mod + 1) % 3
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

    card_drop_target(container, container.index(f))   # drop a card here to put it before this one
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


def group_card(app, g, i, container):
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
    card_drag_source(g)
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
        else:
            imgui.spacing()
            draw_items(app, g.children, top=False)
    imgui.end_child()
    card_drop_target(g.children, None)   # dropping on the group puts the card inside, at the end
    bevel(imgui.get_item_rect_min(), imgui.get_item_rect_max())
    imgui.pop_id()


AUTO_RATES = [(0.1, 30.0, "%.1f s"), (0.25, 64.0, "%.2g beats"), (0.25, 16.0, "%.2g bars")]


def automation_menu(app, f, key, lo, hi, name):
    """Right-click the slider just drawn: make it move on its own (an LFO timed by the tempo). An automated
    slider shows a wave mark beside it."""
    a = f.autos.get(key)
    if a:
        mn, mx = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        imgui.get_window_draw_list().add_text(V(mn.x - sc(17), mn.y + (mx.y - mn.y - imgui.get_text_line_height()) / 2),
                                              u32(CYAN), fa.ICON_FA_WAVE_SQUARE)
    if imgui.is_item_hovered() and not a:
        imgui.set_tooltip("Right-click: automate (move on its own)")
    if not imgui.begin_popup_context_item(f"auto_{key}"):
        return
    bold(f"Automate: {name}", 15)
    imgui.separator()
    on = a is not None
    changed, on = imgui.checkbox("Move on its own", on)
    if changed:
        if on:
            a = f.autos[key] = dict(shape=0, rate=1.0, unit=2, lo=lo, hi=hi, phase=0.0, band=0)
        else:
            f.autos.pop(key, None)
            a = None
    if a:
        w = sc(300)
        label("Shape")
        imgui.set_next_item_width(w)
        _, a["shape"] = imgui.combo("##ashape", a["shape"], app.AUTO_SHAPES)
        if a["shape"] == 7:
            label("Follows")
            a["band"] = segmented("aband", ("Bass", "Mids", "Highs"), a.get("band", 0), MAGENTA, w)
        else:
            label("Every")
            imgui.set_next_item_width(w - sc(156))
            r_lo, r_hi, fmt = AUTO_RATES[a["unit"]]
            _, a["rate"] = slider_float("##arate", a["rate"], r_lo, r_hi, fmt, imgui.SliderFlags_.logarithmic)
            imgui.same_line(0, 6)
            a["unit"] = segmented("aunit", tempo.UNITS, a["unit"], VIOLET, sc(150))
            label("Phase")
            imgui.set_next_item_width(w)
            _, a["phase"] = slider_float("##aphase", a["phase"], 0.0, 1.0, "%.2f")
        label("From")
        imgui.set_next_item_width(w)
        _, a["lo"] = slider_float("##alo", a["lo"], lo, hi, "%.2f")
        label("To")
        imgui.set_next_item_width(w)
        _, a["hi"] = slider_float("##ahi", a["hi"], lo, hi, "%.2f")
        imgui.text_colored(DIM, "Saved with the look. Morph transitions pause it while they slide.")
    imgui.end_popup()


def effect_body(app, f):
    imgui.spacing()
    label(f.amt_label or "Amount")
    _, f.amt = slider_float("##amt", f.amt, 0.0, 1.0, "%.2f")
    automation_menu(app, f, "amt", 0.0, 1.0, f.amt_label or "Amount")
    label("Opacity")
    imgui.set_next_item_width(imgui.get_content_region_avail().x - 118)
    _, pct = slider_float("##opacity", f.opacity * 100, 0.0, 100.0, "%.0f%%")
    f.opacity = pct / 100
    automation_menu(app, f, "opacity", 0.0, 1.0, "Opacity")
    imgui.same_line()
    imgui.set_next_item_width(-1)
    _, f.blend = imgui.combo("##blend", f.blend, E.BLEND_MODES)
    if imgui.is_item_hovered():
        imgui.set_tooltip("Blend mode: how this effect combines with what's under it")
    if f.needs_mask:   # eraser and tracers already work from the person mask themselves
        f.target = 0
    else:
        label("Apply to")
        f.target = segmented("target", ("All", "Subject", "Background"), f.target, MAGENTA)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Use AI background removal to limit this effect to you, or to everything behind you")
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
        imgui.set_next_item_width(imgui.get_content_region_avail().x - 64)
        _, f.centre = slider_float2("##centre", f.centre, 0.0, 1.0, "%.2f")
        imgui.same_line(0, 4)
        picking = app.picking is f
        if icon_button(fa.ICON_FA_CROSSHAIRS, "pick", MAGENTA if picking else DIM,
                       "Pick: click or drag on the preview to place the centre"):
            app.picking = None if picking else f
        imgui.same_line(0, 4)
        if icon_button(fa.ICON_FA_ROTATE_LEFT, "rc", DIM, "Reset to the middle"):
            f.centre = [0.5, 0.5]
    if f.has_speed:
        label("Speed")
        imgui.set_next_item_width(imgui.get_content_region_avail().x - 32)
        _, f.speed = slider_float("##speed", f.speed, -3.0, 3.0, "%.2fx")
        automation_menu(app, f, "speed", -3.0, 3.0, "Speed")
        if imgui.is_item_hovered():
            imgui.set_tooltip("0 freezes it, negative runs it backwards (Ctrl+click to type)")
        imgui.same_line(0, 4)
        if icon_button(fa.ICON_FA_ROTATE_LEFT, "rs", DIM, "Back to normal speed"):
            f.speed = 1.0
    for j, (name, _default, lo, hi, fmt) in enumerate(f.params):
        label(name)
        _, f.pvals[j] = slider_float(f"##p{j}", f.pvals[j], lo, hi, fmt)
        automation_menu(app, f, f"p{j}", lo, hi, name)
    for j, (name, choices, _default) in enumerate(f.options):
        label(name)
        imgui.begin_disabled(app.midi_learn)
        _, f.opts[j] = imgui.combo(f"##opt{j}", f.opts[j], choices)
        imgui.end_disabled()
        midi_spot(app, (f.id, f"opt{j}"))
        if choices[f.opts[j]] == "Custom":   # the effect's own colours
            custom_colours(f, j)
    imgui.spacing()


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
    label("Wave speed")
    _, pipe.wave_rate = slider_float("##wave", pipe.wave_rate, 0.02, 2.0, "%.2f Hz",
                                           imgui.SliderFlags_.logarithmic)


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
        src = app.audio.device_name if app.audio.stream else "none yet (Effects tab > Audio)"
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
                "MIDI LEARN   click a control (slider, dropdown, power, look tile, play / next / prev)")
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

    imgui.same_line(0, 26)
    if icon_button(fa.ICON_FA_BACKWARD_STEP, "prev", TEXT, "Previous look [Left]") and not app.midi_learn:
        app.playlist_step(-1)
    midi_spot(app, ("app", "prev"))
    imgui.same_line(0, 4)
    playing = app.auto_mode != AUTO_OFF
    if neon_button(f"{fa.ICON_FA_PAUSE if playing else fa.ICON_FA_PLAY}##play", CYAN, V(44, 0), playing,
                   "Auto-play [Space]") and not app.midi_learn:
        toggle_play(app)
    midi_spot(app, ("app", "play"))
    imgui.same_line(0, 4)
    if icon_button(fa.ICON_FA_FORWARD_STEP, "next", TEXT, "Next look [Right / N]") and not app.midi_learn:
        app.auto_progress = 0.0
        app.playlist_step(1) if S.auto_kind == AUTO_PLAYLIST else app.randomize()
    midi_spot(app, ("app", "next"))

    imgui.same_line(0, 18)
    kind = segmented("kind", (f"{fa.ICON_FA_LIST}  Playlist", f"{fa.ICON_FA_SHUFFLE}  Random"),
                     0 if S.auto_kind == AUTO_PLAYLIST else 1, CYAN, sc(210))
    S.auto_kind = AUTO_PLAYLIST if kind == 0 else AUTO_RANDOM
    if app.auto_mode:
        app.auto_mode = S.auto_kind

    imgui.same_line(0, 18)
    imgui.align_text_to_frame_padding()
    imgui.text_colored(DIM, "every")
    imgui.same_line()
    imgui.set_next_item_width(sc(90))
    _, app.auto_every = slider_int("##every", app.auto_every, 1, 32)
    imgui.same_line()
    app.auto_unit = segmented("unit", tempo.UNITS, app.auto_unit, VIOLET, sc(150))
    imgui.same_line(0, 18)
    tempo_strip(app)

    # import / export and save, on the right
    save_w, io_w = sc(130), sc(44)
    imgui.same_line(imgui.get_window_width() - 16 - save_w - 2 * (io_w + 6))
    imgui.set_cursor_pos_y(sc(10))
    if neon_button(f"{fa.ICON_FA_FILE_IMPORT}##import", DIM, V(io_w, 0),
                   tip="Import: add looks from a .lumoria-look or .lumoria-playlist file to the end of the playlist\n"
                       "(looks with a name you already use get a number, nothing is overwritten)"):
        app.ask_import()
    imgui.same_line(0, 6)
    imgui.set_cursor_pos_y(sc(10))
    if neon_button(f"{fa.ICON_FA_FILE_EXPORT}##export", DIM, V(io_w, 0),
                   tip="Export: save the whole playlist (every look, with its transition and timing) to one\n"
                       ".lumoria-playlist file, to back it up or share it. One look: right-click its tile."):
        if app.playlist:
            app.ask_export()
        else:
            app.flash("The playlist is empty: save some looks first.")
    imgui.same_line(0, 6)
    imgui.set_cursor_pos_y(sc(10))
    if neon_button(f"{fa.ICON_FA_FLOPPY_DISK}   Save look", MAGENTA, V(save_w, 0),
                   tip="Save every effect in the chain, with its settings, as a look in the playlist"):
        S.open_save = True
    if S.open_save:   # also requested by the + tile, which lives in a child window
        S.open_save = False
        S.save_name = f"Look {len(app.playlist) + 1}"
        imgui.open_popup("save_look")
    save_popup(app)

    if not S.playlist_open:
        return
    imgui.spacing()
    tiles(app, panel_h)


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


def tempo_strip(app):
    """Playlist bar: beat lights, the BPM readout, TAP, and when a fired look starts (Launch)."""
    tp = app.tempo
    dl = imgui.get_window_draw_list()
    p, h = imgui.get_cursor_screen_pos(), imgui.get_frame_height()
    w = beat_lights(app, dl, p.x + sc(6), p.y + h / 2)
    imgui.dummy(V(w + sc(4), h))
    imgui.same_line()
    # BPM readout in a recessed window
    p = imgui.get_cursor_screen_pos()
    text = f"{tp.bpm:5.1f}"
    imgui.push_font(S.mono, 16)
    tw = imgui.calc_text_size(text).x
    imgui.pop_font()
    bw = tw + sc(52)
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
    imgui.same_line(0, 6)
    if neon_button("TAP##tap", CYAN, V(sc(54), 0), glfw.get_time() - (tp.taps[-1] if tp.taps else -9) < .12,
                   "Tap on the beat a few times to set the tempo [T]") and not app.midi_learn:
        tp.tap(glfw.get_time())
    midi_spot(app, ("app", "tap"))
    # launch quantize too, if there's room before the buttons on the right (always in Settings > Tempo)
    room = (imgui.get_window_width() - 16 - sc(130) - 2 * (sc(44) + 6)
            - (imgui.get_item_rect_max().x - imgui.get_window_pos().x))
    if room < sc(230):
        return
    imgui.same_line(0, 14)
    imgui.align_text_to_frame_padding()
    imgui.text_colored(DIM, "launch")
    imgui.same_line()
    q = segmented("launch", ("now", "beat", "bar"), app.quantize, AMBER, sc(150))
    if q != app.quantize:
        app.quantize, app.pending_look = q, None
    if imgui.is_item_hovered():
        imgui.set_tooltip("When a look you fire starts: straight away, or on the next beat or bar\n"
                          "(clicks, MIDI pads, arrow keys and auto-play)")


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
    label("Beats / bar")
    tp.beats_per_bar = segmented("tbar", ("3", "4", "5", "6", "7"), tp.beats_per_bar - 3, VIOLET) + 3
    label("Launch looks")
    q = segmented("tlaunch", ("At once", "Next beat", "Next bar"), app.quantize, AMBER)
    if q != app.quantize:
        app.quantize, app.pending_look = q, None
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
        imgui.text_colored(DIM, f"Following the bass of {app.audio.device_name}." if app.audio.stream else
                           "No audio input (Effects tab > Audio): running steadily at this BPM.")
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


def tiles(app, panel_h):
    # fixed-size tiles that wrap into more rows as the panel gets taller (scroll for the rest)
    th = sc(96)
    tile = V(th * 1.6, th)
    imgui.begin_child("tiles", V(0, 0))
    per_row = max(1, int((imgui.get_content_region_avail().x + 10) // (tile.x + 10)))
    move = None
    for i, name in enumerate(list(app.playlist)):
        if i % per_row:
            imgui.same_line(0, 10)
        active = name == app.current_preset
        imgui.push_id(f"tile{name}")
        if imgui.invisible_button("##tile", tile) and not app.midi_learn:
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
        dl.add_text(V(mn.x + sc(12), mx.y - sc(34)), u32(TEXT if active or thumb else KEY_TEXT),
                    name if len(name) <= 16 else name[:15] + "...")
        imgui.pop_font()
        led(dl, V(mx.x - sc(16), mn.y + sc(17)), CYAN, active, 3.5)   # lit on the look that's playing
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
