"""Reliable frame rate, frame count and frame seeking for cv2 captures.

Container problems seen in real lab videos:
  * a WMV reported 1000 fps and 602,849 frames (really ~30 fps, 18,072
    frames) — every duration / speed would be off ~33×;
  * MP4s whose frames are not evenly spaced (dropped frames; one 5 s
    gap): cv2's set(CAP_PROP_POS_FRAMES, n) then lands up to 146 frames
    early while still reporting n — scrub previews, manual fixes and trim
    starts hit the wrong frame.
Reading frames in order is always correct, so exact seeking uses each
frame's decoder timestamp, read once per file.
"""
import os

import cv2

MAX_FPS = 240.0
FPS_UNKNOWN = ("Can't read this video's frame rate. Set an FPS override "
               "(Video step) and run again.")
_TIMES = {}


def probe(cap):
    """(fps, frame_count). When the container's fps is impossible (0 or
    above 240), the real rate comes from the first frames' timestamps and
    the frame count is rescaled to the same duration. fps is 0.0 when it
    can't be worked out (impossible value and no usable timestamps) — the
    caller must then ask for an FPS override, never guess."""
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if 1.0 <= fps <= MAX_FPS:
        return fps, n
    pos = cap.get(cv2.CAP_PROP_POS_FRAMES)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    ts = []
    for _ in range(31):
        if not cap.grab():
            break
        ts.append(cap.get(cv2.CAP_PROP_POS_MSEC))
    cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
    if len(ts) < 2 or ts[-1] <= ts[0]:
        return 0.0, n
    real = (len(ts) - 1) * 1000.0 / (ts[-1] - ts[0])
    if fps > 0 and n > 0:
        n = int(round(n / fps * real))
    return real, n


def frame_times(path):
    """Decoder timestamp (ms) of every frame in reading order — one fast
    grab pass (~5 s for a 10-min 720p video), cached per file. None when
    the backend gives no usable timestamps."""
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return None
    if key not in _TIMES:
        cap = cv2.VideoCapture(path)
        ts = []
        while cap.grab():
            ts.append(cap.get(cv2.CAP_PROP_POS_MSEC))
        cap.release()
        _TIMES[key] = ts if len(ts) > 1 and ts[-1] > ts[0] else None
    return _TIMES[key]


def cached_frame_times(path):
    """frame_times(path) if already read, else None (never blocks)."""
    try:
        return _TIMES.get((path, os.path.getmtime(path)))
    except OSError:
        return None


def warm_frame_times(path):
    """Read frame_times(path) in a background thread (call on video load)
    so the first scrub jump does not wait for it."""
    import threading
    threading.Thread(target=frame_times, args=(path,), daemon=True).start()


def seek_exact(cap, idx, times):
    """Position `cap` so the next read() returns frame `idx` (0-based, in
    reading order). `times` = frame_times(path). Jumps, then reads forward
    to the timestamp of frame idx - 1; jumps earlier when it overshoots.
    Plain jump when no timestamps."""
    idx = int(idx)
    if idx <= 0 or not times or idx > len(times):
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, idx))
        return
    want = times[idx - 1]   # (the loop below does the jump — no extra one)
    back = 0
    for _attempt in range(5):
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, idx - back))
        if not cap.grab():
            return
        ms = cap.get(cv2.CAP_PROP_POS_MSEC)
        if ms > want + 0.5:              # landed past idx - 1: jump earlier
            back = back * 2 + 300
            continue
        while ms < want - 0.5:
            if not cap.grab():
                return
            ms = cap.get(cv2.CAP_PROP_POS_MSEC)
        return                           # just read idx - 1
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)


def skip_to(cap, idx, path=None):
    """Start reading at frame `idx`, exactly. With the file's frame times
    already read (cached_frame_times(path)) this is a timestamp-checked
    jump; otherwise frames are read from the beginning."""
    idx = max(0, int(idx))
    times = cached_frame_times(path) if (path and idx > 0) else None
    if times and idx <= len(times):
        seek_exact(cap, idx, times)
        return
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    for _ in range(idx):
        if not cap.grab():
            break
