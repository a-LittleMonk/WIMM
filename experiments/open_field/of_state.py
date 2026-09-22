"""Non-UI OF state helpers.

Per-frame cell-ID caching, center-polygon math, arena-edit recompute
dispatch, live-scrub state push, and the cumulative-times-through
walker. These are the host-attached helpers behind the live HUD and
the cv2 burn-in — both backed by the canonical analysis.open_field
implementations so summary / live / video numbers stay in sync.
"""
import numpy as np


def _compute_center(host):
    # Y-Maze (no arena/center widgets) — short-circuit.
    if not hasattr(host, "spin_center_pct"):
        return
    if not host.zone_drawer.arena:
        host.zone_drawer.center_zone = None
        host.zone_drawer.update()
        if host.tracking_results:
            _arena_recompute(host)
        return
    arena = host.zone_drawer.arena
    pct = host.spin_center_pct.value() / 100.0
    cx = sum(p[0] for p in arena) / 4
    cy = sum(p[1] for p in arena) / 4
    host.zone_drawer.center_zone = [
        (cx + (p[0] - cx) * pct, cy + (p[1] - cy) * pct)
        for p in arena
    ]
    host.zone_drawer.update()
    host._refresh_zones_label()
    if host.tracking_results:
        _arena_recompute(host)


def _arena_recompute(host):
    """Selective recompute for arena / center polygon edits. Positions are
    unchanged → Speed / Speed Histogram / Habituation can be skipped, and
    only the Zone (+ Cell, in grid mode) columns of the Raw Data table
    need rewriting. Tracking Issues IS refreshed because the
    outside-arena detector uses the polygon."""
    dirty = {"Trajectory", "Heatmap", "Cell Time", "Zone Time"}
    raw_cols = ["Zone", "Cell"]
    if hasattr(host, "_recompute_metrics_and_views"):
        try:
            host._recompute_metrics_and_views(
                dirty=dirty,
                raw_cols=raw_cols,
                refresh_tracking_issues=True,
            )
        except TypeError:
            # Older signature fallback — never run in practice.
            host._recompute_metrics_and_views()


def _ensure_cell_id_cache(host):
    """Build (or return cached) per-frame arrays:
      - grid_ids: int32 array of cell ids 0..16 (0 = outside / NaN)
      - center_mask: bool array, True if inside center polygon
    Cache key = (n, arena, center, zone_mode, video size). Any change
    automatically invalidates. The expensive parts (perspective transform
    + polygon hit-tests) run once per tracking run; subsequent scrub /
    burn calls reuse the arrays."""
    if not (host.tracking_results and host.video_w and host.video_h):
        return None, None
    zd = host.zone_drawer
    arena = zd.get_arena_pixels() if hasattr(zd, "get_arena_pixels") else None
    center_px = zd.get_center_pixels() if hasattr(zd, "get_center_pixels") else None
    key = (
        len(host.tracking_results),
        tuple(tuple(p) for p in arena) if arena else None,
        tuple(tuple(p) for p in center_px) if center_px else None,
        zd.zone_mode,
        host.video_w, host.video_h,
    )
    cached = getattr(host, "_cell_id_cache", None)
    if cached is not None and cached.get("key") == key:
        return cached["grid_ids"], cached["center_mask"]

    from analysis.open_field import per_frame_cell_ids, point_in_polygon_mask
    n = len(host.tracking_results)
    xs = np.array(
        [r.get("x") if r.get("x") is not None else np.nan
         for r in host.tracking_results], dtype=float,
    )
    ys = np.array(
        [r.get("y") if r.get("y") is not None else np.nan
         for r in host.tracking_results], dtype=float,
    )
    if zd.zone_mode == "grid" and arena and len(arena) == 4:
        grid_ids = per_frame_cell_ids(xs, ys, arena)
    else:
        grid_ids = np.zeros(n, dtype=np.int32)
    if center_px and len(center_px) >= 3:
        center_mask = point_in_polygon_mask(xs, ys, center_px)
    else:
        center_mask = np.zeros(n, dtype=bool)

    host._cell_id_cache = {
        "key": key,
        "grid_ids": grid_ids,
        "center_mask": center_mask,
    }
    return grid_ids, center_mask


def _build_cell_id_sequence(host):
    """One pass over tracking_results returning a list of cell ids
    (str: '1'..'16' for grid mode, 'C' for center mode, or None).

    Backed by the host cell-id cache so the cv2 burn-in (called per
    frame during export) doesn't redo the perspective transform every
    time."""
    grid_ids, center_mask = _ensure_cell_id_cache(host)
    if grid_ids is None:
        return []
    n = len(grid_ids)
    cids = [None] * n
    if host.zone_drawer.zone_mode == "grid":
        for i in range(n):
            c = int(grid_ids[i])
            if c > 0:
                cids[i] = str(c)
    else:
        for i in range(n):
            if center_mask[i]:
                cids[i] = "C"
    return cids


def _grid_cell_quad_px(host, arena, row, col):
    """Pixel quad for grid cell (row, col) ∈ [0..3] inside arena."""
    TL, TR, BR, BL = host.zone_drawer._sorted_corners(arena)
    def bilin(u, v):
        top = (TL[0] + (TR[0] - TL[0]) * u, TL[1] + (TR[1] - TL[1]) * u)
        bot = (BL[0] + (BR[0] - BL[0]) * u, BL[1] + (BR[1] - BL[1]) * u)
        return (top[0] + (bot[0] - top[0]) * v, top[1] + (bot[1] - top[1]) * v)
    u0, v0 = col / 4.0, row / 4.0
    u1, v1 = (col + 1) / 4.0, (row + 1) / 4.0
    return [bilin(u0, v0), bilin(u1, v0), bilin(u1, v1), bilin(u0, v1)]


def _push_cell_state_for_frame(host, frame_idx):
    """Update zone_drawer.body_pos + cumulative cell times based on
    tracking_results up to frame_idx. Called from _on_scrub with a
    source-frame slider value; convert to a trim-relative index here."""
    zd = host.zone_drawer
    if not host.tracking_results:
        zd.set_body_pos_norm(None)
        zd.reset_cell_times()
        return
    idx = host._slider_to_results_idx(frame_idx)
    r = host.tracking_results[idx]
    bx, by = r.get("x"), r.get("y")
    if bx is not None and by is not None and host.video_w and host.video_h:
        zd.set_body_pos_norm((bx / float(host.video_w),
                               by / float(host.video_h)))
    else:
        zd.set_body_pos_norm(None)
    # Cumulative cell time + entries up to and including current frame.
    if zd._cell_show_timer or zd._cell_show_entries:
        times, entries = host._compute_cell_times_through(idx)
        zd.set_cell_times(times)
        zd.set_cell_entries(entries)


def _compute_cell_times_through(host, last_idx):
    """Cumulative seconds + entries per cell over frames [0..last_idx]
    of host.tracking_results. Reuses the cached per-frame cell IDs so
    scrubbing on long videos stays smooth — only the debounce walk
    runs per call. Same numerical contract as the batch-Excel metrics
    (analysis.open_field.debounce_cell_runs / debounce_bool_runs)."""
    from analysis.open_field import debounce_cell_runs, debounce_bool_runs
    fps = host.fps or 30.0
    min_dwell = host._cell_min_dwell_s()
    times, entries = {}, {}
    grid_ids, center_mask = _ensure_cell_id_cache(host)
    if grid_ids is None:
        return times, entries
    n = min(last_idx + 1, len(grid_ids))
    if host.zone_drawer.zone_mode == "grid":
        grid_times, grid_entries = debounce_cell_runs(
            grid_ids[:n], fps, min_dwell
        )
        for cid, t in grid_times.items():
            times[str(int(cid))] = t
        for cid, e in grid_entries.items():
            entries[str(int(cid))] = e
    if center_mask.size:
        c_time, c_entries = debounce_bool_runs(center_mask[:n], fps, min_dwell)
        if c_time > 0:
            times["C"] = c_time
            entries["C"] = c_entries
    return times, entries
