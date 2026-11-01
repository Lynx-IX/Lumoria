"""Constants shared by the engine (app.py) and the interface (ui.py)."""
import os
import sys

# Installed (Lumoria.exe, built with PyInstaller): built-in files (assets, models) sit in the app's own folder,
# which may be read-only (Program Files), so looks, settings, MIDI links and logs live in %APPDATA%\Lumoria.
# Run from source: both are this folder.
VERSION = "0.9.0"   # Lumoria's version (build.py reads it from here for the installer)
SOURCE_URL = ""      # where the source code lives (GitHub); Settings > About links to it once set
SUPPORT_URL = ""     # a tip / support page (Ko-fi); Settings > About shows a Support button once set
FROZEN = getattr(sys, "frozen", False)
HERE = getattr(sys, "_MEIPASS", "") if FROZEN else os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Lumoria") if FROZEN else HERE
if "--selftest" in sys.argv:   # the build check runs on a throwaway data folder, never the user's looks
    import tempfile
    DATA = os.path.join(tempfile.gettempdir(), "LumoriaSelftest")
os.makedirs(DATA, exist_ok=True)
RESOLUTIONS = [("1280 x 720", 1280, 720), ("1920 x 1080", 1920, 1080),
               ("1080 x 1920  vertical", 1080, 1920), ("1080 x 1080  square", 1080, 1080)]
MOD_OFF, MOD_AUDIO, MOD_WAVE = 0, 1, 2            # what drives an effect's amount
AUTO_OFF, AUTO_PLAYLIST, AUTO_RANDOM = 0, 1, 2    # auto-play modes
TRANSITIONS = ["Dissolve", "Grow", "Cut"]                          # effects fading in/out
LOOK_TRANSITIONS = TRANSITIONS + ["Wipe", "Flash", "Morph"]         # whole looks changing over
LOOK_MORPH = 5   # Morph: effects both looks share slide their settings across instead of crossfading
