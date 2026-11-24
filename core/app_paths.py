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
    if chosen:
        notice(f"The backup folder {chosen} can't be reached (unplugged or "
               f"offline?), so backups go to {BACKUP_DIR} instead.")
    return ensure_dir(BACKUP_DIR)


def ensure_dir(path):
    """Create `path` (and parents) if missing; returns it."""
    os.makedirs(path, exist_ok=True)
    return path


# ── Problems the user must hear about (shown at start-up / end of a run) ──
_notices = []


def notice(text):
    """Queue a message for the next dialog the app shows the user."""
    if text not in _notices:
        _notices.append(text)


def pop_notices():
    out = list(_notices)
    _notices.clear()
    return out


def read_json(path):
    """Contents of a JSON settings file, {} when missing. A damaged file is
    renamed to <name>.bad-<time> (never overwritten by the next save) and
    the user is told."""
    import json
    import time
    from core import logger
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        bad = f"{path}.bad-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            os.replace(path, bad)
            kept = f"It was kept as {os.path.basename(bad)}."
        except OSError:
            kept = "It could not be renamed."
        logger.error(f"Settings file unreadable ({path}): {e}", source="settings")
        notice(f"{os.path.basename(path)} was damaged and could not be read, so "
               f"defaults are used. {kept}")
        return {}


def write_json(path, data):
    """Write via a temp file so a crash mid-write can't empty the file."""
    import json
    ensure_dir(os.path.dirname(path))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
