"""Saved custom experiments — one .json file per experiment in
<app folder>/settings/experiments. The start page lists them; opening one
gives a Custom Experiment tab with that design fixed (zones + measures).
"""
import os
import re

from core.app_paths import SETTINGS_DIR, ensure_dir
from .experiment import DESIGN_VERSION, check_design

LIB_DIR = os.path.join(SETTINGS_DIR, "experiments")

# Called after a save / delete (the start page refreshes its list).
_listeners = []
last_saved = None          # path of the most recent save


def on_change(fn):
    _listeners.append(fn)


def _changed():
    for fn in list(_listeners):
        try:
            fn()
        except Exception:
            pass


def _slug(name):
    s = re.sub(r"[^A-Za-z0-9 _-]+", "", name).strip().replace(" ", "_")
    return s[:60] or "experiment"


def list_saved(folder=None):
    """[(name, path)] of saved experiments, sorted by name. Unreadable
    files are skipped."""
    folder = folder or LIB_DIR
    out = []
    if not os.path.isdir(folder):
        return out
    for fn in os.listdir(folder):
        if not fn.lower().endswith(".json"):
            continue
        path = os.path.join(folder, fn)
        try:
            name, _z, _m = load(path)
        except (OSError, ValueError):
            continue
        out.append((name, path))
    return sorted(out, key=lambda t: t[0].lower())


def load(path):
    """(name, zones, measures) of a saved experiment; ValueError if bad."""
    import json
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    zones, measures = check_design(data)
    name = str(data.get("name") or os.path.splitext(os.path.basename(path))[0])
    return name, zones, measures


def path_for(name, folder=None):
    return os.path.join(folder or LIB_DIR, _slug(name) + ".json")


def save(name, zones, measures, path=None, folder=None):
    """Write the experiment; returns its path. `path` overwrites that file
    (Edit design); otherwise the file is named after the experiment."""
    import json
    name = (name or "").strip()
    if not name:
        raise ValueError("Give the experiment a name.")
    if not any(z.get("shape") for z in zones):
        raise ValueError("Add at least one zone or line first.")
    if not measures:
        raise ValueError("Tick at least one measure.")
    path = path or path_for(name, folder)
    ensure_dir(os.path.dirname(path))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"wimm_custom_design": DESIGN_VERSION, "name": name,
                   "zones": zones, "measures": measures}, f, indent=2)
    os.replace(tmp, path)               # never leave a half-written file
    global last_saved
    last_saved = path
    _changed()
    return path


def delete(path):
    if os.path.isfile(path):
        os.remove(path)
    _changed()
