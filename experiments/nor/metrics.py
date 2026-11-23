"""NOR metrics: per-object nose-interaction stats + discrimination index.

Inputs (settings dict):
  arena_px       — arena polygon in pixel coords (4 points)
  objects        — dict obj_id -> {name, role, zone_px (list of (x,y) px),
                                    footprint_px, color}
  min_dwell_s    — debounce threshold; a bout must last ≥ this many seconds
                   to count (entry + time + bout).
  angle_enabled  — bool; when True, require nose to point toward object
                   center within angle_max_deg for the nose-in-zone test.
  angle_max_deg  — float; angle threshold (default 45°).
"""
import math
import numpy as np
import pandas as pd
from matplotlib.path import Path

from core.kinematics import (
    compute_step_distance, compute_basic_kinematics, compute_pauses,
)
from .zones import (
    OBJECT_NAMES, OBJECT_LABELS, ROLE_FAMILIAR, ROLE_NOVEL,
)


def _point_in_poly_mask(xs, ys, poly_px):
    """Vectorized point-in-polygon test. Returns bool array.
    NaN coords → False. poly_px is a list of (x, y) tuples."""
    mask = np.zeros(len(xs), dtype=bool)
    if not poly_px or len(poly_px) < 3:
        return mask
    notna = ~np.isnan(xs) & ~np.isnan(ys)
    if not notna.any():
        return mask
    pts = np.stack([xs, ys], axis=1)
    path = Path(np.array(poly_px, dtype=float))
    mask[notna] = path.contains_points(pts[notna])
    return mask


def _polygon_centroid(poly_px):
    if not poly_px:
        return (float("nan"), float("nan"))
    cx = sum(p[0] for p in poly_px) / len(poly_px)
    cy = sum(p[1] for p in poly_px) / len(poly_px)
    return (cx, cy)


def _debounce_bouts(mask, min_frames):
    """From a boolean per-frame in-zone mask, return:
       (entries, total_frames, bouts) where bouts is a list of (start, end)
       frame indices for each confirmed bout (length ≥ min_frames).
    Sub-threshold runs are dropped entirely — no contribution to time."""
    min_frames = max(1, int(min_frames))
    bouts = []
    n = len(mask)
    i = 0
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            if (j - i) >= min_frames:
                bouts.append((i, j))
            i = j
        else:
            i += 1
    entries = len(bouts)
    total_frames = sum(b[1] - b[0] for b in bouts)
    return entries, total_frames, bouts


def compute(results, settings, fps, px_per_cm):
    """Compute NOR metrics. Returns (metrics_dict, raw_df, bin_df)."""
    df = pd.DataFrame(results)
    scale, unit = compute_step_distance(df, px_per_cm, fps)
    move_thr = float(settings.get("movement_threshold", 0.0))
    basic = compute_basic_kinematics(df, fps, unit, movement_threshold=move_thr)
    pauses = compute_pauses(df, fps, unit,
                            movement_threshold=max(move_thr, 1e-6),
                            min_dur_s=float(settings.get("pause_min_dur_s", 1.0)))

    fps_safe = fps or 30.0
    frame_dur = 1.0 / fps_safe
    trim_start_s = float(settings.get("trim_start_s", 0.0))
    min_dwell_s = float(settings.get("min_dwell_s", 0.5))
    min_frames = max(1, int(round(min_dwell_s * fps_safe)))

    angle_enabled = bool(settings.get("angle_enabled", False))
    angle_max_deg = float(settings.get("angle_max_deg", 45.0))

    objects = settings.get("objects") or {}
    arena_px = settings.get("arena_px") or []

    # Nose coords drive the interaction test; body coords drive the
    # arena-entry counter + the angle filter heading.
    xs = df["x"].astype(float).values
    ys = df["y"].astype(float).values
    nose_xs = (df["nose_x"].astype(float).values
               if "nose_x" in df.columns else np.full(len(df), np.nan))
    nose_ys = (df["nose_y"].astype(float).values
               if "nose_y" in df.columns else np.full(len(df), np.nan))

    metrics = {
        "duration_s":     basic.get("Duration (s)", 0.0),
        "total_distance": basic.get(f"Total Distance ({unit})", 0.0),
        "mean_speed":     basic.get(f"Average Speed ({unit}/s)", 0.0),
        "max_speed":      basic.get(f"Max Speed ({unit}/s)", 0.0),
        "median_speed":   basic.get(f"Median Speed ({unit}/s)", 0.0),
        "mobility_time_s":   basic.get("Mobility Time (s)", 0.0),
        "immobility_time_s": basic.get("Immobility Time (s)", 0.0),
        "tortuosity":     basic.get("Tortuosity", "n/a"),
        "frames_detected":   basic.get("Frames Detected", 0),
        "total_frames":      basic.get("Total Frames", 0),
        "detection_rate_pct": basic.get("Detection Rate (%)", 0.0),
        "unit":           unit,
        "min_dwell_s":    min_dwell_s,
        "angle_enabled":  angle_enabled,
        "angle_max_deg":  angle_max_deg if angle_enabled else None,
        "pause_count":    pauses.get("Pause Count (#)", 0),
        "pause_total_s":  pauses.get("Total Time in Pauses (s)", 0.0),
        "pause_mean_s":   pauses.get("Mean Pause Duration (s)", 0.0),
        "pause_longest_s": pauses.get("Longest Pause (s)", 0.0),
    }

    # ── Arena entries + total time (body, not nose).
    if arena_px and len(arena_px) >= 3:
        in_arena = _point_in_poly_mask(xs, ys, arena_px)
        entries_arena, frames_arena, _ = _debounce_bouts(in_arena, min_frames)
        metrics["arena_entries"] = entries_arena
        metrics["arena_total_time_s"] = round(frames_arena * frame_dur, 3)

    # ── Per-object interaction stats.
    role_times_s = {ROLE_FAMILIAR: 0.0, ROLE_NOVEL: 0.0}
    per_object_in_mask = {}  # obj_id -> bool array (used by raw_df + bin_df)
    for obj_id in OBJECT_NAMES:
        st = objects.get(obj_id) or {}
        zone_px = st.get("zone_px") or []
        name = st.get("name", OBJECT_LABELS[obj_id])
        role = st.get("role", "none")

        in_zone = _point_in_poly_mask(nose_xs, nose_ys, zone_px)
        if angle_enabled and len(zone_px) >= 3:
            tx, ty = _polygon_centroid(zone_px)
            # Vectorized angle filter — keep only frames where heading
            # toward target centroid is within threshold.
            hx = nose_xs - xs
            hy = nose_ys - ys
            tx_arr = tx - xs
            ty_arr = ty - ys
            h_len = np.hypot(hx, hy)
            t_len = np.hypot(tx_arr, ty_arr)
            denom = h_len * t_len
            cos_a = np.full(len(df), np.nan)
            ok = denom > 1e-6
            cos_a[ok] = (hx[ok] * tx_arr[ok] + hy[ok] * ty_arr[ok]) / denom[ok]
            cos_a = np.clip(cos_a, -1.0, 1.0)
            ang_deg = np.degrees(np.arccos(cos_a))
            facing = ~np.isnan(ang_deg) & (ang_deg <= angle_max_deg)
            in_zone = in_zone & facing

        per_object_in_mask[obj_id] = in_zone
        entries, total_frames, bouts = _debounce_bouts(in_zone, min_frames)
        total_s = total_frames * frame_dur

        bout_lens_s = [(b[1] - b[0]) * frame_dur for b in bouts]
        mean_bout_s = (sum(bout_lens_s) / len(bout_lens_s)) if bout_lens_s else 0.0
        longest_bout_s = max(bout_lens_s) if bout_lens_s else 0.0

        latency_s = None
        for (s, _e) in bouts:
            latency_s = round(s * frame_dur + trim_start_s, 3)
            break

        prefix = obj_id  # "object_a" / "object_b"
        metrics[f"{prefix}_name"] = name
        metrics[f"{prefix}_role"] = role
        metrics[f"{prefix}_total_time_s"]    = round(total_s, 3)
        metrics[f"{prefix}_entries"]         = entries
        metrics[f"{prefix}_latency_first_s"] = latency_s
        metrics[f"{prefix}_bouts_count"]     = len(bouts)
        metrics[f"{prefix}_mean_bout_s"]     = round(mean_bout_s, 3)
        metrics[f"{prefix}_longest_bout_s"]  = round(longest_bout_s, 3)

        if role in role_times_s:
            role_times_s[role] += total_s

    # ── Discrimination Index + preference (only when both roles set).
    # One object never explored is a real result (DI = ±1), not missing.
    t_fam = role_times_s[ROLE_FAMILIAR]
    t_nov = role_times_s[ROLE_NOVEL]
    roles = {(objects.get(o) or {}).get("role") for o in OBJECT_NAMES}
    if ROLE_FAMILIAR in roles and ROLE_NOVEL in roles and t_fam + t_nov > 0:
        metrics["discrimination_index"] = round(
            (t_nov - t_fam) / (t_nov + t_fam), 4
        )
        metrics["preference_pct_novel"] = round(
            t_nov / (t_nov + t_fam) * 100.0, 2
        )
        metrics["familiar_time_s"] = round(t_fam, 3)
        metrics["novel_time_s"]    = round(t_nov, 3)
    else:
        metrics["discrimination_index"] = None
        metrics["preference_pct_novel"] = None

    # ── Raw per-frame DF (mirrors OF/YM column contract).
    raw_df = df[["frame", "timestamp", "x", "y", "step_dist", "speed"]].copy()
    raw_df.columns = [
        "Frame", "Time (s)", "X (px)", "Y (px)",
        f"Step Distance ({unit})", f"Speed ({unit}/s)",
    ]
    # Single Zone column — first-wins assignment (A before B).
    zone_col = [""] * len(df)
    for obj_id in OBJECT_NAMES:
        st = objects.get(obj_id) or {}
        label = st.get("name", OBJECT_LABELS[obj_id])
        mask = per_object_in_mask.get(obj_id)
        if mask is None:
            continue
        for i in range(len(df)):
            if zone_col[i] == "" and bool(mask[i]):
                zone_col[i] = label
    raw_df["Zone"] = zone_col
    for src, dst in (("nose_x", "Nose X (px)"), ("nose_y", "Nose Y (px)"),
                     ("tail_x", "Tail X (px)"), ("tail_y", "Tail Y (px)"),
                     ("nose_confidence", "Nose Confidence")):
        if src in df.columns:
            raw_df[dst] = df[src]

    # ── Per-bin time-course (matches YM bin pattern).
    bin_df = None
    bin_size_s = float(settings.get("bin_size_s", 0.0))
    if bin_size_s > 0 and frame_dur > 0:
        bin_df = _bin_metrics(per_object_in_mask, objects, fps_safe, bin_size_s,
                              df=df, unit=unit)

    return metrics, raw_df, bin_df


def _bin_metrics(per_object_in_mask, objects, fps, bin_size_s, df, unit):
    """Per-bin: time-in-zone for each object + locomotion."""
    frame_dur = 1.0 / fps if fps else 0.0
    bin_frames = max(1, int(round(bin_size_s * fps)))
    n = len(df)
    has_df = df is not None and len(df) > 0
    rows = []
    for start in range(0, n, bin_frames):
        end = min(n, start + bin_frames)
        row = {
            "bin_start_s": round(start * frame_dur, 2),
            "bin_end_s":   round(end * frame_dur, 2),
        }
        for obj_id in OBJECT_NAMES:
            mask = per_object_in_mask.get(obj_id)
            label = (objects.get(obj_id) or {}).get("name", OBJECT_LABELS[obj_id])
            if mask is None:
                row[f"time_{label}_s"] = 0.0
                continue
            row[f"time_{label}_s"] = round(
                float(np.sum(mask[start:end])) * frame_dur, 3
            )
        if has_df:
            chunk = df.iloc[start:end]
            row[f"distance_{unit}"] = round(
                float(chunk["step_dist"].sum(skipna=True)), 3
            )
            mean_sp = float(chunk["speed"].mean(skipna=True))
            row[f"mean_speed_{unit}_per_s"] = (
                round(mean_sp, 3) if mean_sp == mean_sp else None
            )
        rows.append(row)
    return pd.DataFrame(rows)


EXPORT_COLUMNS = [
    "Animal ID", "Group", "Sex", "Date", "Trial",
    "duration_s", "total_distance", "mean_speed",
    "object_a_name", "object_a_role",
    "object_a_total_time_s", "object_a_entries", "object_a_latency_first_s",
    "object_a_bouts_count", "object_a_mean_bout_s", "object_a_longest_bout_s",
    "object_b_name", "object_b_role",
    "object_b_total_time_s", "object_b_entries", "object_b_latency_first_s",
    "object_b_bouts_count", "object_b_mean_bout_s", "object_b_longest_bout_s",
    "familiar_time_s", "novel_time_s",
    "discrimination_index", "preference_pct_novel",
    "arena_entries", "arena_total_time_s",
    "min_dwell_s", "angle_enabled", "angle_max_deg",
    "pause_count", "pause_total_s", "Notes",
]


BATCH_SCHEMA = [
    ("Experiment Metadata", [
        "Video", "Animal ID", "Group", "Sex", "Date", "Trial", "Notes",
    ]),
    ("Locomotion", [
        "duration_s", "total_distance", "mean_speed", "max_speed",
    ]),
    ("Object A", [
        "object_a_name", "object_a_role",
        "object_a_total_time_s", "object_a_entries",
        "object_a_latency_first_s",
        "object_a_bouts_count", "object_a_mean_bout_s",
        "object_a_longest_bout_s",
    ]),
    ("Object B", [
        "object_b_name", "object_b_role",
        "object_b_total_time_s", "object_b_entries",
        "object_b_latency_first_s",
        "object_b_bouts_count", "object_b_mean_bout_s",
        "object_b_longest_bout_s",
    ]),
    ("Discrimination", [
        "familiar_time_s", "novel_time_s",
        "discrimination_index", "preference_pct_novel",
    ]),
    ("Arena", [
        "arena_entries", "arena_total_time_s",
    ]),
    ("Settings", [
        "min_dwell_s", "angle_enabled", "angle_max_deg",
    ]),
    ("Pauses / Freezing", [
        "pause_count", "pause_total_s",
    ]),
]
