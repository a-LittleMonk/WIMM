from typing import Optional, Tuple, List
import numpy as np
import pandas as pd
import cv2
from matplotlib.path import Path

from core.arm_entries import bridge_gaps
from core.kinematics import (
    compute_step_distance, compute_basic_kinematics, compute_pauses, find_runs,
    session_duration,
)


def compute_metrics(
    results: List[dict],
    arena: Optional[Tuple[int, int, int, int]],
    center_zone: Optional[Tuple[int, int, int, int]] = None,
    *,
    center: Optional[Tuple[int, int, int, int]] = None,
    px_per_cm: Optional[float],
    fps: float,
    movement_threshold: float = 0.0,
    bin_size_s: float = 0.0,
    zone_mode: str = "center_zone",
    pause_min_dur_s: float = 1.0,
    thigmotaxis_band_cm: float = 2.0,
    cell_min_dwell_s: float = 0.2,
    trim_start_s: float = 0.0,
):
    """Compute open-field metrics.

    movement_threshold: speed threshold in (cm/s if px_per_cm set, else px/s).
        Frames at or below threshold count as immobile. 0 disables.
    bin_size_s: if > 0, also compute per-bin breakdown DataFrame.
    zone_mode: "grid" or "center_zone" — controls whether per-cell (1..16) metrics
        are included.
    pause_min_dur_s: minimum continuous immobility (in seconds) to count as
        a pause/freezing event.
    thigmotaxis_band_cm: distance from arena perimeter (in cm if calibrated,
        else as a fraction of arena diagonal) defining the wall-hugging band.
    Returns (metrics: dict, raw_df: DataFrame, bin_df: Optional[DataFrame]).
    """
    # Legacy keyword 'center' still accepted; prefer 'center_zone'.
    if center_zone is None and center is not None:
        center_zone = center

    df = pd.DataFrame(results)
    scale, unit = compute_step_distance(df, px_per_cm, fps)

    # Zone classification
    def _in_polygon(poly, df):
        notna = df["x"].notna().values
        result = np.zeros(len(df), dtype=bool)
        if notna.any():
            path = Path(np.array(poly, dtype=float))
            xy = df[["x", "y"]].values
            result[notna] = path.contains_points(xy[notna])
        return pd.Series(result, index=df.index)

    in_arena  = _in_polygon(arena, df)       if arena       else pd.Series([True]  * len(df), index=df.index)
    in_center = _in_polygon(center_zone, df) if center_zone else pd.Series([False] * len(df), index=df.index)

    # Raw zone classification: where the body is geometrically.
    df["zone"] = "periphery"
    df.loc[in_center & in_arena, "zone"] = "center_zone"
    df.loc[df["x"].isna(), "zone"] = "undetected"
    if arena:
        df.loc[~in_arena & df["x"].notna(), "zone"] = "outside"

    duration_s = session_duration(df, fps)  # gaps count, like undetected frames
    frame_dur = 1.0 / fps

    # Distance / speed / mobility — generic (shared with other assays).
    metrics = compute_basic_kinematics(df, fps, unit, movement_threshold)

    # Center entries / dwells / inter-entry / latency / time — all debounced
    # by the same min-dwell used for the burn-in 'C' counter and live HUD,
    # so every report of "Center" agrees. Sub-threshold center frames are
    # treated as border-jitter and reclassified to periphery for time
    # accounting (zone_confirmed). The raw `zone` column is preserved.
    # Lost-tracking frames inside one center visit don't split it.
    zone_seq = bridge_gaps(df["zone"].tolist(),
                           (df["zone"] == "undetected").tolist())
    is_center = pd.Series([z == "center_zone" for z in zone_seq], index=df.index)
    min_frames_center = (
        max(1, int(round(cell_min_dwell_s * fps))) if cell_min_dwell_s > 0 else 1
    )
    # Walk center runs once, collect (start_idx, end_idx) for runs that
    # cross the dwell threshold. Used for entries, dwells, inter-entry,
    # latency, and confirmed time-in-center.
    center_run_ranges = []
    mask = is_center.values
    in_run = False
    run_start = 0
    for i, v in enumerate(mask):
        if v and not in_run:
            in_run = True
            run_start = i
        elif not v and in_run:
            in_run = False
            if (i - run_start) >= min_frames_center:
                center_run_ranges.append((run_start, i))
    if in_run and (len(mask) - run_start) >= min_frames_center:
        center_run_ranges.append((run_start, len(mask)))

    # Confirmed-center boolean mask + reclassified zone column.
    is_confirmed_center = np.zeros(len(df), dtype=bool)
    for s, e in center_run_ranges:
        is_confirmed_center[s:e] = True
    df["zone_confirmed"] = df["zone"]
    df.loc[is_confirmed_center, "zone_confirmed"] = "center_zone"
    sub_threshold_center = (df["zone"] == "center_zone").values & ~is_confirmed_center
    df.loc[sub_threshold_center, "zone_confirmed"] = "periphery"

    center_dwells = [(e - s) * frame_dur for (s, e) in center_run_ranges]
    entries = len(center_run_ranges)
    inter_entry = [
        (center_run_ranges[k + 1][0] - center_run_ranges[k][1]) * frame_dur
        for k in range(len(center_run_ranges) - 1)
    ]
    # Latency is reported in source-video time (frame 0 of the raw clip),
    # not trim-relative. So we add the trim offset back to the per-frame
    # timestamp (which the tracker emits starting at 0).
    latency = (round(float(df["timestamp"].iloc[center_run_ranges[0][0]]) + float(trim_start_s), 2)
               if center_run_ranges else None)

    # Debounced time accounting — drives "Time in Center Zone", "% Time in Center Zone",
    # and (via zone_confirmed) the per-bin breakdown.
    time_center = int(is_confirmed_center.sum()) * frame_dur
    time_periph = int((df["zone_confirmed"] == "periphery").sum()) * frame_dur
    pct_center = 100 * time_center / duration_s if duration_s > 0 else 0.0
    pct_periph = 100 * time_periph / duration_s if duration_s > 0 else 0.0

    metrics.update({
        "Time in Center Zone (s)":           round(time_center, 2),
        "Time in Periphery (s)":             round(time_periph, 2),
        "% Time in Center Zone":             round(pct_center, 1),
        "% Time in Periphery":               round(pct_periph, 1),
        "Center Zone Entries (#)":           entries,
        "Latency to First Center Zone Entry (s)": latency if latency is not None else "never",
    })
    total_frames = metrics.get("Total Frames", len(df))

    # Center Zone dwell distribution
    if center_dwells:
        metrics["Mean Center Zone Dwell (s)"]     = round(float(np.mean(center_dwells)), 2)
        metrics["Longest Center Zone Dwell (s)"]  = round(float(np.max(center_dwells)), 2)
    else:
        metrics["Mean Center Zone Dwell (s)"]     = 0.0
        metrics["Longest Center Zone Dwell (s)"]  = 0.0
    if inter_entry:
        metrics["Mean Inter-Entry Interval (s)"] = round(float(np.mean(inter_entry)), 2)
    else:
        metrics["Mean Inter-Entry Interval (s)"] = "n/a"

    # ── Thigmotaxis (wall-hugging)
    if arena and len(arena) >= 3:
        if px_per_cm and px_per_cm > 0:
            band_px = thigmotaxis_band_cm * px_per_cm
            band_label = f"{thigmotaxis_band_cm:.1f} cm"
        else:
            arena_arr = np.array(arena, dtype=float)
            diag = float(np.linalg.norm(arena_arr.max(axis=0) - arena_arr.min(axis=0)))
            band_px = diag * 0.1
            band_label = "10% of arena diagonal"
        valid_xy = df[["x", "y"]].dropna().values
        if len(valid_xy) > 0:
            d_to_edge = _dist_points_to_polygon_edge(valid_xy, np.array(arena, dtype=float))
            thigmo_count = int(np.sum(d_to_edge < band_px))
            thigmo_s = thigmo_count * frame_dur
            metrics["Thigmotaxis Band"]     = band_label
            metrics["Thigmotaxis Time (s)"] = round(thigmo_s, 2)
            metrics["Thigmotaxis %"] = (
                round(100 * thigmo_count / total_frames, 1)
                if total_frames > 0 else 0.0
            )

    # ── Pause / freezing analysis (generic)
    metrics.update(compute_pauses(df, fps, unit, movement_threshold, pause_min_dur_s))

    # ── Per-cell metrics (grid mode only)
    cell_ids_per_frame = None
    if zone_mode == "grid" and arena and len(arena) == 4:
        cell_ids_per_frame = per_frame_cell_ids(
            df["x"].values, df["y"].values, arena
        )
        # Apply min-dwell de-bounce: brief sub-threshold visits contribute
        # nothing to either time or entries. Shared with the live HUD
        # (of_methods._compute_cell_times_through) so numbers agree.
        min_frames = max(1, int(round(cell_min_dwell_s * fps))) if cell_min_dwell_s > 0 else 1
        debounced_times, debounced_entries = debounce_cell_runs(
            cell_ids_per_frame, fps, cell_min_dwell_s
        )
        for cid in range(1, 17):
            metrics[f"Cell {cid} Time (s)"]    = round(debounced_times.get(cid, 0.0), 2)
            metrics[f"Cell {cid} Entries (#)"] = int(debounced_entries.get(cid, 0))
        metrics["Cell Entry Min-Dwell (s)"] = round(cell_min_dwell_s, 2)

        # Region aggregates (sum of per-cell time within a fixed cell set,
        # plus debounced enter/exit transitions). Cells 6/7/10/11 = center
        # 2×2; 1/4/13/16 = corners; 2/3/5/8/9/12/14/15 = edges.
        min_frames_region = (
            max(1, int(round(cell_min_dwell_s * fps)))
            if cell_min_dwell_s and cell_min_dwell_s > 0 else 1
        )
        for label, cell_set in (
            ("Corner Cells", {1, 4, 13, 16}),
            ("Center Cells", {6, 7, 10, 11}),
            ("Side Cells",   {2, 3, 5, 8, 9, 12, 14, 15}),
        ):
            r_time, r_entries = _region_aggregate(
                cell_ids_per_frame, cell_set,
                debounced_times, min_frames_region,
            )
            metrics[f"{label} Time (s)"]    = round(r_time, 2)
            metrics[f"{label} Entries (#)"] = int(r_entries)

    raw_df = df[["frame", "timestamp", "x", "y", "zone", "step_dist", "speed"]].copy()
    raw_df.columns = [
        "Frame", "Time (s)", "X (px)", "Y (px)", "Zone",
        f"Step Distance ({unit})", f"Speed ({unit}/s)"
    ]
    if cell_ids_per_frame is not None:
        raw_df["Cell"] = cell_ids_per_frame
    for src, dst in (("nose_x", "Nose X (px)"), ("nose_y", "Nose Y (px)"),
                     ("tail_x", "Tail X (px)"), ("tail_y", "Tail Y (px)"),
                     ("nose_confidence", "Nose Confidence")):
        if src in df.columns:
            raw_df[dst] = df[src]

    bin_df = None
    if bin_size_s and bin_size_s > 0 and duration_s > 0:
        bin_df = _bin_metrics(df, bin_size_s, frame_dur, unit, movement_threshold,
                              [s for s, _e in center_run_ranges])

    # ── Habituation slope (linear regression of bin distance vs time)
    if bin_df is not None and len(bin_df) >= 2:
        x_vals = bin_df["Bin Start (s)"].values.astype(float)
        y_vals = bin_df[f"Distance ({unit})"].values.astype(float)
        try:
            slope, intercept = np.polyfit(x_vals, y_vals, 1)
            # slope is unit/s²; convert to unit/min for intuition.
            metrics[f"Habituation Slope ({unit}/min)"] = round(float(slope) * 60.0, 4)
            metrics[f"First-Bin Distance ({unit})"]   = round(float(y_vals[0]), 2)
            metrics[f"Last-Bin Distance ({unit})"]    = round(float(y_vals[-1]), 2)
            if y_vals[0] > 0:
                pct_change = 100 * (y_vals[-1] - y_vals[0]) / y_vals[0]
                metrics["Habituation Last/First (%)"] = round(float(pct_change), 1)
        except Exception as e:   # e.g. NaN bins — the cells stay empty
            from core import logger
            logger.warn(f"Habituation slope not computed: {e}", source="metrics")

    return metrics, raw_df, bin_df


def _bin_metrics(df, bin_size_s, frame_dur, unit, movement_threshold,
                 entry_starts=()):
    """entry_starts: frame index where each confirmed center visit starts
    (same list as the main Center Zone Entries), so a visit that crosses
    a bin edge is one entry, in the bin where it started."""
    df = df.copy()
    df["bin"] = (df["timestamp"] // bin_size_s).astype(int)
    rows = []
    for b, sub in df.groupby("bin"):
        start = b * bin_size_s
        end   = start + bin_size_s
        dist  = float(sub["step_dist"].sum())
        n     = len(sub)
        dur   = n * frame_dur
        # Same base as the session Average Speed: distance bridges tracking
        # gaps, so it covers the whole bin time.
        avg_v = dist / dur if dur > 0 else 0.0
        max_v = float(sub["speed"].max()) if sub["speed"].notna().any() else 0.0
        # Debounced zone classification (sub-threshold center → periphery)
        # so per-bin totals add up to the main metrics.
        zone_col = "zone_confirmed" if "zone_confirmed" in sub.columns else "zone"
        t_c   = float((sub[zone_col] == "center_zone").sum() * frame_dur)
        t_p   = float((sub[zone_col] == "periphery").sum() * frame_dur)
        ent   = int(sub.index.isin(entry_starts).sum())
        if movement_threshold and movement_threshold > 0:
            mob = float((sub["speed"] > movement_threshold).sum() * frame_dur)
            immob = float((sub["speed"] <= movement_threshold).sum() * frame_dur)
        else:
            mob = immob = None
        row = {
            "Bin Start (s)":                round(start, 2),
            "Bin End (s)":                  round(end, 2),
            f"Distance ({unit})":           round(dist, 2),
            f"Avg Speed ({unit}/s)":        round(avg_v, 3),
            f"Max Speed ({unit}/s)":        round(max_v, 3),
            "Time in Center Zone (s)":      round(t_c, 2),
            "Time in Periphery (s)":        round(t_p, 2),
            "Center Zone Entries (#)":      ent,
        }
        if mob is not None:
            row["Mobility (s)"]   = round(mob, 2)
            row["Immobility (s)"] = round(immob, 2)
        rows.append(row)
    return pd.DataFrame(rows)


# ─────────────────────────── Helpers ────────────────────────────────────
#
# The four functions below are the single source of truth for OF cell
# stats. compute_metrics (batch / Excel), the live-scrub HUD in
# of_methods._compute_cell_times_through, and the cv2 burn-in in
# of_methods._build_cell_id_sequence all route through them so the
# numbers reported in summary, on screen, and in exported video agree.


def per_frame_cell_ids(xs, ys, arena):
    """For each (x, y) in pixel coords, return cell id 1..16 (top-to-bottom,
    left-to-right of the 4×4 grid inside `arena`). Returns 0 for invalid /
    outside-arena frames so the output is a uniform int32 array.

    `arena` must be a 4-corner polygon (TL/TR/BR/BL in any order); the
    perspective transform is built from `_sorted_corners`."""
    n = len(xs)
    out = np.zeros(n, dtype=np.int32)
    if not arena or len(arena) != 4:
        return out
    arena_pts = _sorted_corners(arena)
    src = np.array(arena_pts, dtype=np.float32)
    dst = np.array([(0, 0), (1, 0), (1, 1), (0, 1)], dtype=np.float32)
    try:
        M = cv2.getPerspectiveTransform(src, dst)
    except cv2.error as e:
        # Every frame would land in no cell and all 16 cells read 0.
        raise ValueError("The arena corners can't form a 4×4 grid "
                         "(points on one line?) — redraw the arena.") from e
    xs_arr = np.asarray(xs, dtype=float)
    ys_arr = np.asarray(ys, dtype=float)
    ok = ~np.isnan(xs_arr) & ~np.isnan(ys_arr)
    if not ok.any():
        return out
    pts = np.stack([xs_arr[ok], ys_arr[ok]], axis=1).astype(np.float32)[:, None, :]
    uv = cv2.perspectiveTransform(pts, M)[:, 0, :].astype(float)
    u, v = uv[:, 0], uv[:, 1]
    inside = (u >= 0.0) & (u <= 1.0) & (v >= 0.0) & (v <= 1.0)
    col = np.clip((u * 4).astype(int), 0, 3)
    row = np.clip((v * 4).astype(int), 0, 3)
    cells = np.where(inside, row * 4 + col + 1, 0)   # 1..16, 0 = outside
    out[np.where(ok)[0]] = cells
    return out


def point_in_polygon_mask(xs, ys, poly):
    """Boolean mask — True for indices where (x, y) is inside the closed
    polygon. NaN coords always return False. Vectorized."""
    xs_arr = np.asarray(xs, dtype=float)
    ys_arr = np.asarray(ys, dtype=float)
    valid = ~(np.isnan(xs_arr) | np.isnan(ys_arr))
    result = np.zeros(len(xs_arr), dtype=bool)
    if valid.any() and poly and len(poly) >= 3:
        path = Path(np.array(poly, dtype=float))
        pts = np.column_stack([xs_arr[valid], ys_arr[valid]])
        result[valid] = path.contains_points(pts)
    return result


def debounce_cell_runs(cell_ids, fps, min_dwell_s):
    """Walk a cell-id sequence (0 = no detection / outside). Runs shorter
    than the dwell threshold contribute nothing to either time or entries.
    Entries count on the FIRST confirmed transition into a cell — bouncing
    back into the same cell after a sub-threshold blip does NOT re-enter.
    Returns (times: dict[cid → seconds], entries: dict[cid → int])."""
    fps = float(fps) if fps else 30.0
    frame_dur = 1.0 / fps
    min_frames = (
        max(1, int(round(min_dwell_s * fps))) if min_dwell_s and min_dwell_s > 0 else 1
    )
    times, entries = {}, {}
    n = len(cell_ids)
    confirmed = 0
    i = 0
    while i < n:
        cid = int(cell_ids[i])
        if cid == 0:
            i += 1
            continue
        j = i
        while j < n and int(cell_ids[j]) == cid:
            j += 1
        run_len = j - i
        if run_len >= min_frames:
            times[cid] = times.get(cid, 0.0) + run_len * frame_dur
            if cid != confirmed:
                entries[cid] = entries.get(cid, 0) + 1
                confirmed = cid
        i = j
    return times, entries


def debounce_bool_runs(mask, fps, min_dwell_s):
    """Walk a boolean mask. Returns (total_time_s, entries_count) where
    only runs of True that meet the min-dwell threshold contribute."""
    fps = float(fps) if fps else 30.0
    frame_dur = 1.0 / fps
    min_frames = (
        max(1, int(round(min_dwell_s * fps))) if min_dwell_s and min_dwell_s > 0 else 1
    )
    total = 0.0
    entries = 0
    n = len(mask)
    i = 0
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        while j < n and mask[j]:
            j += 1
        run_len = j - i
        if run_len >= min_frames:
            total += run_len * frame_dur
            entries += 1
        i = j
    return total, entries


def _region_aggregate(cell_ids, cell_set, debounced_times, min_frames):
    """Sum confirmed time across `cell_set` (using already-debounced
    per-cell times) and count debounced enter transitions into the set.
    A brief detour out of the set that doesn't clear `min_frames`
    counts as continuous occupancy — so consecutive same-region cells
    don't double-count as new entries."""
    region_time = sum(float(debounced_times.get(c, 0.0)) for c in cell_set)
    in_region = np.isin(cell_ids, list(cell_set))
    entries = 0
    n = len(in_region)
    i = 0
    was_in = False
    while i < n:
        if in_region[i]:
            j = i
            while j < n and in_region[j]:
                j += 1
            if (j - i) >= min_frames:
                if not was_in:
                    entries += 1
                was_in = True
            i = j
        else:
            j = i
            while j < n and not in_region[j]:
                j += 1
            if (j - i) >= min_frames:
                was_in = False
            i = j
    return region_time, entries


# Backwards-compat alias so any older import keeps working.
_per_frame_cells = per_frame_cell_ids


def _sorted_corners(pts):
    """Returns (TL, TR, BR, BL) for screen coords (y-down)."""
    TL = min(pts, key=lambda p: p[0] + p[1])
    BR = max(pts, key=lambda p: p[0] + p[1])
    TR = max(pts, key=lambda p: p[0] - p[1])
    BL = min(pts, key=lambda p: p[0] - p[1])
    return TL, TR, BR, BL


def _dist_points_to_polygon_edge(points, polygon):
    """For each point, return the perpendicular distance to the nearest
    edge of the closed polygon. points: (N, 2). polygon: (K, 2)."""
    n_edges = len(polygon)
    min_dists = np.full(len(points), np.inf)
    for i in range(n_edges):
        a = polygon[i]
        b = polygon[(i + 1) % n_edges]
        d = _segment_distance(points, a, b)
        min_dists = np.minimum(min_dists, d)
    return min_dists


def _segment_distance(points, a, b):
    """Distance from each point to segment ab. Vectorized."""
    ax, ay = a
    bx, by = b
    abx, aby = bx - ax, by - ay
    seg_len2 = abx * abx + aby * aby
    if seg_len2 == 0:
        # Degenerate segment.
        return np.sqrt((points[:, 0] - ax) ** 2 + (points[:, 1] - ay) ** 2)
    apx = points[:, 0] - ax
    apy = points[:, 1] - ay
    t = (apx * abx + apy * aby) / seg_len2
    t = np.clip(t, 0.0, 1.0)
    cx = ax + t * abx
    cy = ay + t * aby
    return np.sqrt((points[:, 0] - cx) ** 2 + (points[:, 1] - cy) ** 2)


# Backwards-compat re-export — older code may import _find_runs from here.
_find_runs = find_runs
