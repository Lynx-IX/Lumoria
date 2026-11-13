"""Constants shared by the engine (app.py) and the interface (ui.py)."""
import json
import os
import sys


def save_text(path, text):
    """Write a file so a crash or power cut mid-save can't leave it cut off: the new text goes into a temporary
    file beside it, is flushed to the disk, and only then swapped in for the old one (in one step)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def save_json(path, data):
    save_text(path, json.dumps(data, indent=1))

# Installed (LumaTRX.exe, built with PyInstaller): built-in files (assets, models) sit in the app's own folder,
# which may be read-only (Program Files), so looks, settings, MIDI links and logs live in %APPDATA%\LumaTRX.
# Run from source: both are this folder.
VERSION = "0.12.0"   # LumaTRX's version (build.py reads it from here for the installer)
SOURCE_URL = "https://github.com/Lynx-IX/Lumoria"   # Settings > About links to it
SUPPORT_URL = ""     # a tip / support page (Ko-fi); Settings > About shows a Support button once set
FROZEN = getattr(sys, "frozen", False)
HERE = getattr(sys, "_MEIPASS", "") if FROZEN else os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "LumaTRX") if FROZEN else HERE
if "--selftest" in sys.argv:   # the build check runs on a throwaway data folder, never the user's looks
    import tempfile
    DATA = os.path.join(tempfile.gettempdir(), "LumaTRXSelftest")


def carry_over_data(new, old):
    """LumaTRX was called Lumoria: the first time it runs, it brings the old data folder's looks, settings and MIDI
    links over (a copy - the old folder is left as it was, in case of second thoughts)."""
    if os.path.exists(new) or not os.path.isdir(old):
        return False
    import shutil
    try:
        shutil.copytree(old, new)
        return True
    except OSError:
        return False


if FROZEN and "--selftest" not in sys.argv:
    carry_over_data(DATA, os.path.join(os.path.dirname(DATA), "Lumoria"))
os.makedirs(DATA, exist_ok=True)
RESOLUTIONS = [("1280 x 720", 1280, 720), ("1920 x 1080", 1920, 1080),
               ("1080 x 1920  vertical", 1080, 1920), ("1080 x 1080  square", 1080, 1080),
               ("2560 x 1440  (1440p)", 2560, 1440), ("3840 x 2160  (4K)", 3840, 2160),
               ("2160 x 3840  4K vertical", 2160, 3840)]
MOD_OFF, MOD_AUDIO, MOD_WAVE = 0, 1, 2            # what drives an effect's amount
AUTO_OFF, AUTO_PLAYLIST, AUTO_RANDOM = 0, 1, 2    # auto-play modes
TRANSITIONS = ["Dissolve", "Grow", "Cut"]                          # effects fading in/out
LOOK_TRANSITIONS = TRANSITIONS + ["Wipe", "Flash", "Morph"]         # whole looks changing over
LOOK_MORPH = 5   # Morph: effects both looks share slide their settings across instead of crossfading
