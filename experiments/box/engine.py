"""Shared measurement engine for box-family experiments.

A test supplies a list of ZoneDef (in box space, see geometry.py); the
engine classifies every frame, applies the shared min-dwell rule (the same
one Y-Maze / EPM / NOR use: a visit only counts once the animal has stayed
`min dwell` seconds, and leaving for a shorter moment does not split it),
and returns per-zone time / % / entries / latency / mean visit plus the
standard locomotion block. The test then adds its own main results from
those numbers.
"""
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import numpy as np
import pandas as pd

from core.kinematics import (
    compute_step_distance, compute_basic_kinematics, compute_pauses,
)
from . import geometry as geo

OUT = "_out"          # inside the arena but in no zone of this layer


@dataclass
class ZoneDef:
    name: str                       # stable id (used in saved settings)
    label: str                      # shown in results ("Light", "Arm 3")
    poly: list                      # box-space outline for drawing
    layer: str = "zone"             # zones of one layer are exclusive
    point: str = "body"             # "body" | "nose" (nose falls back to body)
    color: str = "#A9B4C6"
    kind: str = ""                  # optional group (open / closed …)
    test: Optional[Callable] = None  # f(u, v) -> bool; default = polygon
    dashed: bool = False
    fill_alpha: int = 40
    label_pos: Optional[tuple] = None  # box-space label anchor
    # False: the min-dwell rule is off for this zone's layer (brief
    # crossings must count, e.g. water-maze platform crossings).
    dwell: bool = True

    def contains(self, u, v):
        if self.test is not None:
            return self.test(u, v)
        return geo.in_polygon(u, v, self.poly)


@dataclass
class LayerStats:
    seq: list                       # confirmed zone per frame (None = no data)
    raw: list                       # unconfirmed zone per frame
    frames: dict = field(default_factory=dict)
    entries: dict = field(default_factory=dict)
    first: dict = field(default_factory=dict)
    visits: list = field(default_factory=list)   # [(zone, start, end)]


def classify(u, v, zones):
    """Zone name per frame (first matching zone wins), OUT when inside no
    zone, None when the point is missing."""
    n = len(u)
    out = np.full(n, None, dtype=object)
    ok = ~(np.isnan(u) | np.isnan(v))
    out[ok] = OUT
    for z in zones:
        free = ok & (out == OUT)
        if not free.any():
            break
        hit = np.zeros(n, bool)
        hit[free] = z.contains(u[free], v[free])
        out[hit] = z.name
    return list(out)


def confirm(seq, min_frames):
    """Blank runs shorter than min_frames (None) — the shared dwell rule."""
    n = len(seq)
    res = [None] * n
    i = 0
    m = max(1, int(min_frames))
    while i < n:
        j = i
        while j < n and seq[j] == seq[i]:
            j += 1
        if seq[i] is not None and (j - i) >= m:
            res[i:j] = [seq[i]] * (j - i)
        i = j
    return res


def layer_stats(raw_seq, names, min_frames):
    seq = confirm(raw_seq, min_frames)
    st = LayerStats(seq=seq, raw=raw_seq)
    st.frames = {n: 0 for n in names}
    st.entries = {n: 0 for n in names}
    st.first = {}
    last = None
    start = None
    for i, z in enumerate(seq):
        if z is None:
            continue
        if z != last:
            if last is not None and start is not None:
                st.visits.append((last, start, i))
            start = i
            last = z
            if z in st.entries:
                st.entries[z] += 1
                st.first.setdefault(z, i)
        if z in st.frames:
            st.frames[z] += 1
    if last is not None and start is not None:
        st.visits.append((last, start, len(seq)))
    return st


def committed_sequence(stats):
    """Zones in the order they were entered (OUT included)."""
    return [z for z, _s, _e in stats.visits]


def compute(results, settings, fps, px_per_cm, zones, *, title=""):
    """Run the shared pipeline. Returns (ctx, metrics, raw_df, bin_df) —
    `ctx` carries everything a test needs to add its own main results."""
    df = pd.DataFrame(results)
    if df.empty:
        df = pd.DataFrame(columns=["frame", "timestamp", "x", "y"])
    scale, unit = compute_step_distance(df, px_per_cm, fps)
    move_thr = float(settings.get("movement_threshold", 0.0))
    basic = compute_basic_kinematics(df, fps, unit, movement_threshold=move_thr)
    pauses = compute_pauses(df, fps, unit,
                            movement_threshold=max(move_thr, 1e-6),
                            min_dur_s=float(settings.get("pause_min_dur_s", 1.0)))
    fps = float(fps or 30.0)
    dt = 1.0 / fps
    min_dwell = float(settings.get("min_dwell_s", 0.0) or 0.0)
    min_frames = max(1, int(round(min_dwell * fps))) if min_dwell > 0 else 1
    trim_start = float(settings.get("trim_start_s", 0.0) or 0.0)

    arena = settings.get("arena") or []
    H = geo.box_homography(arena)
    xs = df["x"].astype(float).values if "x" in df else np.array([])
    ys = df["y"].astype(float).values if "y" in df else np.array([])
    n = len(xs)
    if H is not None:
        bu, bv = geo.to_box(H, xs, ys)
    else:
        bu = bv = np.full(n, np.nan)
    if "nose_x" in df.columns and H is not None:
        nx = pd.to_numeric(df["nose_x"], errors="coerce").values.astype(float)
        ny = pd.to_numeric(df["nose_y"], errors="coerce").values.astype(float)
        # No nose estimate on a frame → use the body point for that frame.
        miss = np.isnan(nx) | np.isnan(ny)
        nx = np.where(miss, xs, nx)
        ny = np.where(miss, ys, ny)
        nu, nv = geo.to_box(H, nx, ny)
    else:
        nu, nv = bu, bv

    layers = []
    for z in zones:
        if z.layer not in layers:
            layers.append(z.layer)
    undetected_as = settings.get("_undetected_as") or {}
    stats = {}
    for layer in layers:
        lz = [z for z in zones if z.layer == layer]
        use_nose = lz and lz[0].point == "nose"
        u, v = (nu, nv) if use_nose else (bu, bv)
        raw = classify(u, v, lz) if n else []
        fill = undetected_as.get(layer)
        if fill:
            raw = [fill if r is None else r for r in raw]
        stats[layer] = layer_stats(raw, [z.name for z in lz],
                                   min_frames if lz[0].dwell else 1)

    duration = float(basic.get("Duration (s)", 0.0) or 0.0) or (n * dt)
    metrics = dict(basic)
    metrics["unit"] = unit
    metrics["Min Dwell (s)"] = min_dwell
    for k in ("Pause Count (#)", "Total Time in Pauses (s)"):
        if k in pauses:
            metrics[k] = pauses[k]

    labels = {z.name: z.label for z in zones}
    for layer in layers:
        st = stats[layer]
        for z in [z for z in zones if z.layer == layer]:
            t = st.frames[z.name] * dt
            e = st.entries[z.name]
            metrics[f"Time in {z.label} (s)"] = round(t, 3)
            metrics[f"% Time in {z.label}"] = (
                round(100.0 * t / duration, 2) if duration > 0 else 0.0)
            metrics[f"Entries into {z.label} (#)"] = e
            f0 = st.first.get(z.name)
            metrics[f"Latency to {z.label} (s)"] = (
                round(f0 * dt + trim_start, 3) if f0 is not None else "never")
            metrics[f"Mean Visit in {z.label} (s)"] = (
                round(t / e, 3) if e else 0.0)

    # Raw per-frame table (same first columns as OF / EPM / Y-Maze).
    base_cols = [c for c in ("frame", "timestamp", "x", "y", "step_dist", "speed")
                 if c in df.columns]
    raw_df = df[base_cols].copy()
    raw_df.columns = [{"frame": "Frame", "timestamp": "Time (s)",
                       "x": "X (px)", "y": "Y (px)",
                       "step_dist": f"Step Distance ({unit})",
                       "speed": f"Speed ({unit}/s)"}[c] for c in base_cols]
    for i, layer in enumerate(layers):
        col = "Zone" if i == 0 else layer.capitalize()
        raw_df[col] = [labels.get(z, "") if z and z != OUT else ""
                       for z in stats[layer].raw]
    for src, dst in (("nose_x", "Nose X (px)"), ("nose_y", "Nose Y (px)"),
                     ("tail_x", "Tail X (px)"), ("tail_y", "Tail Y (px)"),
                     ("nose_confidence", "Nose Confidence")):
        if src in df.columns:
            raw_df[dst] = df[src]

    bin_df = None
    bin_s = float(settings.get("bin_size_s", 0.0) or 0.0)
    if bin_s > 0 and n and layers:
        first = stats[layers[0]]
        lz = [z for z in zones if z.layer == layers[0]]
        bf = max(1, int(round(bin_s * fps)))
        rows = []
        for s0 in range(0, n, bf):
            s1 = min(n, s0 + bf)
            chunk = first.seq[s0:s1]
            row = {"bin_start_s": round(s0 * dt, 2), "bin_end_s": round(s1 * dt, 2)}
            for z in lz:
                row[f"time_{z.name}_s"] = round(sum(1 for c in chunk if c == z.name) * dt, 3)
            row["entries"] = sum(1 for (zn, a, _b) in first.visits
                                 if s0 <= a < s1 and zn != OUT)
            if "step_dist" in df.columns:
                part = df.iloc[s0:s1]
                row[f"distance_{unit}"] = round(float(part["step_dist"].sum(skipna=True)), 3)
                sp = float(part["speed"].mean(skipna=True)) if "speed" in part else float("nan")
                row[f"mean_speed_{unit}_per_s"] = round(sp, 3) if sp == sp else None
            rows.append(row)
        bin_df = pd.DataFrame(rows)

    ctx = {
        "df": df, "unit": unit, "fps": fps, "dt": dt, "duration": duration,
        "trim_start": trim_start, "stats": stats, "layers": layers,
        "zones": zones, "labels": labels, "H": H,
        "body_uv": (bu, bv), "nose_uv": (nu, nv), "px_per_cm": px_per_cm,
    }
    return ctx, metrics, raw_df, bin_df
