"""In-memory event log for the Mice Tracker app.

Keeps a ring buffer of timestamped entries. Read via `get_entries()`,
clear via `clear()`, persist via `save_to_file(path)`. Subscribers can
attach via `subscribe(callback)` — called whenever a new entry lands.
"""
from __future__ import annotations
import time
import threading
from collections import deque
from typing import Callable, Iterable, List, Optional, Tuple

_MAX_ENTRIES = 5000
_lock = threading.Lock()
_entries: deque = deque(maxlen=_MAX_ENTRIES)
_subscribers: List[Callable[[Tuple[float, str, str, str]], None]] = []


LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")


def log(message: str, level: str = "INFO", source: str = "") -> None:
    """Append one entry. Thread-safe."""
    if level not in LEVELS:
        level = "INFO"
    ts = time.time()
    entry = (ts, level, source, str(message))
    with _lock:
        _entries.append(entry)
        subs = list(_subscribers)
    for cb in subs:
        try:
            cb(entry)
        except Exception:
            pass


def debug(msg: str, source: str = "") -> None: log(msg, "DEBUG", source)
def info(msg: str, source: str = "")  -> None: log(msg, "INFO",  source)
def warn(msg: str, source: str = "")  -> None: log(msg, "WARN",  source)
def error(msg: str, source: str = "") -> None: log(msg, "ERROR", source)


def get_entries() -> List[Tuple[float, str, str, str]]:
    with _lock:
        return list(_entries)


def clear() -> None:
    with _lock:
        _entries.clear()


def subscribe(cb: Callable[[Tuple[float, str, str, str]], None]) -> None:
    with _lock:
        if cb not in _subscribers:
            _subscribers.append(cb)


def format_entry(entry: Tuple[float, str, str, str]) -> str:
    ts, level, source, msg = entry
    t = time.strftime("%H:%M:%S", time.localtime(ts))
    ms = int((ts - int(ts)) * 1000)
    src = f"[{source}] " if source else ""
    return f"{t}.{ms:03d}  {level:<5}  {src}{msg}"


def format_all(entries: Optional[Iterable] = None) -> str:
    if entries is None:
        entries = get_entries()
    return "\n".join(format_entry(e) for e in entries)


def save_to_file(path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(format_all())
