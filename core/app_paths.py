"""Where the app keeps its own files: everything lives inside the app folder.

    <app folder>/settings/mice_tracker.json        app settings (theme, panels, graph styles …)
    <app folder>/settings/detection_presets.json   saved detection presets
    <app folder>/settings/cache/                   generated theme images

Nothing is written to the user's home folder, AppData or the system temp
folder, so each copy / version of the app has its own independent settings
and deleting the folder removes everything.
"""
import os
import sys


def app_dir():
    """Folder that holds main.py (or the .exe in a PyInstaller build)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


SETTINGS_DIR = os.path.join(app_dir(), "settings")
CONFIG_PATH = os.path.join(SETTINGS_DIR, "mice_tracker.json")
PRESETS_PATH = os.path.join(SETTINGS_DIR, "detection_presets.json")
CACHE_DIR = os.path.join(SETTINGS_DIR, "cache")
# Automatic backup after every tracking run (Excel + graphs). Exports the
# user starts go to a folder they pick at export time.
BACKUP_DIR = os.path.join(app_dir(), "backup")


def backup_dir(config=None):
    """Folder for the automatic backup: the one chosen in Settings -> Set
    Backup Folder... if it still exists, else <app folder>/backup (created)."""
    chosen = ((config or {}).get("backup_folder") or "").strip()
    if chosen and os.path.isdir(chosen):
        return chosen
    return ensure_dir(BACKUP_DIR)


def ensure_dir(path):
    """Create `path` (and parents) if missing; returns it."""
    os.makedirs(path, exist_ok=True)
    return path
