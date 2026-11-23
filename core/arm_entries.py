"""Arm-entry rule shared by EPM and Y-Maze (the live overlay and scrub
counters in gui/epm_tab.py and gui/y_maze_tab.py follow the same rule).

A zone visit counts once the body stays in it for `min_frames`. An arm
entry counts when the confirmed zone changes to an arm, so a confirmed
visit to the neutral / center zone ends the arm visit and arm → center →
same arm is two entries. Time outside every drawn zone (a mouse along the
wall of a slightly narrow arm), short blips and lost tracking do not end
a visit. The neutral / center zone is required (see the tests' preflight).
"""
import numpy as np
from matplotlib.path import Path


def point_in_polys(xs, ys, polys, priority_first=None):
    """polys: dict name -> list of (x, y) px. Zone name per frame, None when
    in no zone or undetected. `priority_first` wins overlap (center /
    neutral outranks the arms near the hub)."""
    out = np.full(len(xs), None, dtype=object)
    notna = ~np.isnan(xs) & ~np.isnan(ys)
    if not notna.any():
        return out
    pts = np.stack([xs, ys], axis=1)
    keys = list(polys.keys())
    if priority_first and priority_first in keys:
        keys.remove(priority_first)
        keys.insert(0, priority_first)
    for name in keys:
        poly_pts = polys[name]
        if not poly_pts or len(poly_pts) < 3:
            continue
        path = Path(np.array(poly_pts, dtype=float))
        inside = np.zeros(len(xs), dtype=bool)
        inside[notna] = path.contains_points(pts[notna])
        out[inside & (out == None)] = name  # noqa: E711
    return out


def arm_visits(zone_seq, arms, min_frames):
    """zone_seq: zone per frame (None = no zone / undetected). Returns
    (confirmed, entries, times_frames, seq, events): confirmed zone per
    frame (None included), entries and frame counts per arm, entered arms
    in order, [(frame, arm)]."""
    visit = list(zone_seq)
    n = len(visit)
    confirmed = [None] * n
    m = max(1, int(min_frames))
    i = 0
    while i < n:
        j = i
        while j < n and visit[j] == visit[i]:
            j += 1
        if visit[i] is not None and (j - i) >= m:
            confirmed[i:j] = [visit[i]] * (j - i)
        i = j
    entries = {a: 0 for a in arms}
    times = {a: 0 for a in arms}
    seq, events = [], []
    last = None
    for k, a in enumerate(confirmed):
        if a is None:
            continue
        if a != last:
            last = a
            if a in entries:
                entries[a] += 1
                seq.append(a)
                events.append((k, a))
        if a in times:
            times[a] += 1
    return confirmed, entries, times, seq, events
