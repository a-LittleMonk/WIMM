"""Tracking-issue detector. Flags frames where tracking likely glitched —
sudden jumps, points outside the arena, big acceleration spikes, or
detection gaps followed by far re-acquisition.

Pure-function module: no Qt, no I/O. Consumed by experiment_tab.py to
populate the 'Tracking Issues' results tab.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Detector keys. Stored as a set so multiple flags can coexist on one frame.
SPEED      = "speed"
OUTSIDE    = "outside"
ACCEL      = "accel"
GAP_JUMP   = "gap_jump"

REASON_LABELS = {
    SPEED:    "Speed spike",
    OUTSIDE:  "Outside arena",
    ACCEL:    "Accel spike",
    GAP_JUMP: "Gap + jump",
}


def detect_issues(raw_df: pd.DataFrame,
                  fps: float,
                  px_per_cm: float | None,
                  arena: list | None,
                  *,
                  speed_thresh_cms: float = 120.0,
                  accel_thresh_cms2: float = 500.0,
                  gap_frames: int = 5,
                  gap_jump_cm: float = 8.0,
                  detectors: set[str] | None = None,
                  auto_speed: bool = True) -> pd.DataFrame:
    """Return one row per flagged frame.

    Columns: Frame, Time (s), Speed (cm/s), Reasons, Severity, Status.
    - Reasons: comma-separated detector labels.
    - Severity: 0..1, max signal across active detectors.
    - Status: always "active" here; callers may flip to "false_positive".

    `speed_thresh_cms` is the cutoff. If `auto_speed`, the threshold is
    replaced with max(60.0, 1.5 × p99.9) so noisy sessions self-calibrate.

    `arena` is the pixel polygon (Nx2). If None, OUTSIDE detector is skipped.
    `px_per_cm` is required for the cm-based detectors; absent → speed/accel
    fall back to px-based units with the same numeric threshold (less ideal
    but never blocks).
    """
    if detectors is None:
        detectors = {SPEED, OUTSIDE, ACCEL, GAP_JUMP}

    if raw_df is None or len(raw_df) == 0:
        return _empty_issues_df()

    df = raw_df.reset_index(drop=True)
    n = len(df)
    fps = float(fps) if fps and fps > 0 else 30.0

    xs = df["X (px)"].values.astype(float)
    ys = df["Y (px)"].values.astype(float)
    nan_mask = np.isnan(xs) | np.isnan(ys)

    # Frame-to-frame distance in px (NaN if either endpoint is NaN).
    dx = np.diff(xs, prepend=xs[0])
    dy = np.diff(ys, prepend=ys[0])
    step_px = np.sqrt(dx * dx + dy * dy)
    step_px[nan_mask] = np.nan

    # Convert to cm where possible.
    if px_per_cm and px_per_cm > 0:
        step_cm = step_px / float(px_per_cm)
        unit = "cm"
    else:
        step_cm = step_px
        unit = "px"
    speed = step_cm * fps  # cm/s (or px/s if uncalibrated)
    if n:
        speed[0] = np.nan    # no previous frame (0 here faked an accel spike on frame 1)

    # Auto-calibrate speed threshold from the data's own p99.9. Keeps the
    # user's value as a floor so quiet sessions don't get over-flagged;
    # uses 2.5× p99.9 so legitimate sprint bursts don't trip the detector.
    if auto_speed and SPEED in detectors:
        finite = speed[np.isfinite(speed)]
        if finite.size >= 100:
            p999 = float(np.quantile(finite, 0.999))
            speed_thresh_cms = max(speed_thresh_cms, p999 * 2.5)

    # Per-frame severity, max over active detectors. Reason strings
    # accumulate the labels that triggered.
    severity = np.zeros(n, dtype=float)
    reasons: list[set[str]] = [set() for _ in range(n)]

    # 1) Speed spike — > threshold.
    if SPEED in detectors:
        spike = np.where(np.isfinite(speed) & (speed > speed_thresh_cms))[0]
        for i in spike:
            reasons[i].add(SPEED)
            # Map ratio (speed / thresh) → 0..1 via tanh so a 2× spike = 0.76.
            sev = np.tanh((float(speed[i]) / max(1e-6, speed_thresh_cms)) - 1.0)
            severity[i] = max(severity[i], min(1.0, max(0.0, sev)))

    # 2) Acceleration spike — |Δspeed| / dt > threshold.
    # Compute accel for ALL frames (not only when detector is on) so the
    # value can be shown in the output table even if ACCEL is disabled.
    d_speed = np.diff(speed, prepend=speed[0])
    accel = np.abs(d_speed) * fps
    if ACCEL in detectors:
        spike = np.where(np.isfinite(accel) & (accel > accel_thresh_cms2))[0]
        for i in spike:
            reasons[i].add(ACCEL)
            sev = np.tanh((float(accel[i]) / max(1e-6, accel_thresh_cms2)) - 1.0)
            severity[i] = max(severity[i], min(1.0, max(0.0, sev)))

    # 3) Outside arena — point-in-polygon false on a valid frame.
    if OUTSIDE in detectors and arena and len(arena) >= 3:
        try:
            from matplotlib.path import Path as MplPath
            poly = np.asarray(arena, dtype=float)
            valid = ~nan_mask
            pts = np.column_stack([xs[valid], ys[valid]])
            inside = MplPath(poly).contains_points(pts)
            valid_idx = np.where(valid)[0]
            outside_idx = valid_idx[~inside]
            for i in outside_idx:
                reasons[i].add(OUTSIDE)
                severity[i] = max(severity[i], 1.0)   # always max severity
        except Exception:
            pass

    # 4) Gap-after-loss → big jump on re-acquisition.
    if GAP_JUMP in detectors:
        # Track runs of NaN; when one ends, check distance from the last
        # known position to the re-acquisition point.
        last_good_x = last_good_y = None
        gap_len = 0
        thresh_px = (gap_jump_cm * float(px_per_cm)
                     if px_per_cm and px_per_cm > 0 else gap_jump_cm)
        for i in range(n):
            if nan_mask[i]:
                gap_len += 1
                continue
            if (last_good_x is not None and gap_len >= gap_frames):
                d = float(np.hypot(xs[i] - last_good_x, ys[i] - last_good_y))
                if d > thresh_px:
                    reasons[i].add(GAP_JUMP)
                    sev = np.tanh((d / max(1e-6, thresh_px)) - 1.0)
                    severity[i] = max(severity[i], min(1.0, max(0.0, 0.5 + 0.5 * sev)))
            last_good_x, last_good_y = xs[i], ys[i]
            gap_len = 0

    flagged = [i for i in range(n) if reasons[i]]
    if not flagged:
        return _empty_issues_df()

    accel_unit = f"{unit}/s²"
    rows = []
    for i in flagged:
        rows.append({
            "Frame":       int(df["Frame"].iloc[i]) if "Frame" in df.columns else i,
            "Time (s)":    round(float(df["Time (s)"].iloc[i]) if "Time (s)" in df.columns else i / fps, 3),
            f"Speed ({unit}/s)":  round(float(speed[i]) if np.isfinite(speed[i]) else 0.0, 2),
            f"Accel ({accel_unit})": round(float(accel[i]) if np.isfinite(accel[i]) else 0.0, 1),
            "Reasons":     ", ".join(REASON_LABELS[r] for r in sorted(reasons[i])),
            "Severity":    round(float(severity[i]), 3),
            "Status":      "active",
            "_row":        i,  # original raw_df index, hidden in UI
        })
    return pd.DataFrame(rows)


def _empty_issues_df() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "Frame", "Time (s)", "Speed (cm/s)", "Accel (cm/s²)", "Reasons",
        "Severity", "Status", "_row",
    ])


def smooth_flagged(raw_df: pd.DataFrame,
                   issues_df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `raw_df` with `X_clean (px)` / `Y_clean (px)`
    columns: original values everywhere except the rows in `issues_df`
    whose Status is 'active', which get linearly interpolated from
    surrounding non-flagged frames.

    Original X/Y stays intact — callers can compare before/after.
    """
    if raw_df is None or len(raw_df) == 0:
        return raw_df
    df = raw_df.copy()
    x_clean = df["X (px)"].values.astype(float).copy()
    y_clean = df["Y (px)"].values.astype(float).copy()
    if issues_df is not None and len(issues_df) > 0:
        active = issues_df[issues_df["Status"] == "active"]
        for idx in active["_row"].values:
            i = int(idx)
            if 0 <= i < len(x_clean):
                x_clean[i] = np.nan
                y_clean[i] = np.nan
        x_clean = _linear_interp(x_clean)
        y_clean = _linear_interp(y_clean)
    df["X_clean (px)"] = x_clean
    df["Y_clean (px)"] = y_clean
    return df


def _linear_interp(arr: np.ndarray) -> np.ndarray:
    """In-place linear interp over NaNs. NaNs at the very edges → carried
    from the nearest non-NaN."""
    out = arr.copy()
    n = out.size
    nan_idx = np.where(np.isnan(out))[0]
    good_idx = np.where(~np.isnan(out))[0]
    if good_idx.size == 0:
        return out
    out[nan_idx] = np.interp(nan_idx, good_idx, out[good_idx])
    return out


# ── Auto-fix: find the frames that are really wrong ──────────────────────
#
# A flagged frame is often not the faulty one: when the dot jumps away for
# one frame, both the jump-out and the jump-back frames get flagged, and a
# wrong point can sit 1-3 frames before / after the flag. So instead of
# blindly interpolating the flagged frame, every short run of frames around
# it is tried: interpolate the run, re-score the neighbourhood, and keep
# the run that removes the problem while changing the fewest frames.

def effective_speed_threshold(xs, ys, fps, px_per_cm, speed_thresh_cms,
                              auto_speed=True):
    """The speed cutoff detect_issues really uses (after Auto)."""
    xs = np.asarray(xs, float)
    ys = np.asarray(ys, float)
    fps = float(fps) if fps and fps > 0 else 30.0
    step = np.hypot(np.diff(xs, prepend=xs[0]), np.diff(ys, prepend=ys[0]))
    if px_per_cm and px_per_cm > 0:
        step = step / float(px_per_cm)
    speed = step * fps
    thr = float(speed_thresh_cms)
    if auto_speed:
        finite = speed[np.isfinite(speed)]
        if finite.size >= 100:
            thr = max(thr, float(np.quantile(finite, 0.999)) * 2.5)
    return thr


def _interp_run(xs, ys, a, b):
    """Copy of xs/ys with frames a..b (inclusive) replaced by a straight
    line between the nearest valid frames outside the run (held flat at
    the video's start / end). None if there is nothing to anchor on."""
    n = xs.size
    pa = a - 1
    while pa >= 0 and not np.isfinite(xs[pa]):
        pa -= 1
    nb = b + 1
    while nb < n and not np.isfinite(xs[nb]):
        nb += 1
    if pa < 0 and nb >= n:
        return None
    x2, y2 = xs.copy(), ys.copy()
    for i in range(a, b + 1):
        if pa < 0:
            x2[i], y2[i] = xs[nb], ys[nb]
        elif nb >= n:
            x2[i], y2[i] = xs[pa], ys[pa]
        else:
            t = (i - pa) / float(nb - pa)
            x2[i] = xs[pa] + t * (xs[nb] - xs[pa])
            y2[i] = ys[pa] + t * (ys[nb] - ys[pa])
    return x2, y2


def _local_flags(xs, ys, lo, hi, fps, px_per_cm, speed_thr, accel_thr, arena_path):
    """Frames in lo..hi the speed / accel / outside-arena detectors would
    flag, plus a score of how far over the limits they are."""
    lo = max(0, lo)
    hi = min(xs.size - 1, hi)
    s0 = max(0, lo - 2)
    x = xs[s0:hi + 1]
    y = ys[s0:hi + 1]
    step = np.hypot(np.diff(x, prepend=np.nan), np.diff(y, prepend=np.nan))
    if px_per_cm and px_per_cm > 0:
        step = step / float(px_per_cm)
    speed = step * fps
    if s0 == 0:
        speed[0] = np.nan
    accel = np.abs(np.diff(speed, prepend=np.nan)) * fps
    k = lo - s0
    sp, ac = speed[k:], accel[k:]
    with np.errstate(invalid="ignore"):
        bad = (np.nan_to_num(sp, nan=0.0) > speed_thr) | (np.nan_to_num(ac, nan=0.0) > accel_thr)
        score = float(np.nansum(np.clip(sp / speed_thr - 1.0, 0, None)))
        score += float(np.nansum(np.clip(ac / accel_thr - 1.0, 0, None)))
    if arena_path is not None:
        pts = np.column_stack([xs[lo:hi + 1], ys[lo:hi + 1]])
        ok = np.isfinite(pts).all(axis=1)
        out = np.zeros(len(pts), bool)
        if ok.any():
            out[ok] = ~arena_path.contains_points(pts[ok])
        bad |= out
        score += float(out.sum())
    return {lo + int(i) for i in np.where(bad)[0]}, score


CHANGE_COST = 0.05     # score cost per replaced frame (prefer small fixes)


def best_local_fix(xs, ys, center, fps, px_per_cm, speed_thr, accel_thr,
                   arena=None, radius=3, max_gap=2, protect=(), taken=()):
    """Try every run of 1..max_gap frames starting within `radius` frames
    of `center`: interpolate it and re-check the neighbourhood.

    A run is only accepted when no frame that was fine becomes flagged (a
    fix never creates a new problem; a long loss that needs more than
    max_gap frames is left alone) and the excess over the limits drops by
    at least 90% (a partial fix that draws from a still-wrong frame is
    rejected). A straight line meets the real path with a small kink, so the
    flagged frame itself may stay mildly flagged. Runs touching frames already replaced (`taken`) count as one
    change, which must also fit in max_gap. Among accepted runs: fewest
    flags left nearby, then fewest frames changed, then the cleanest
    result, then closest to the flagged frame. Returns (a, b) or None."""
    xs = np.asarray(xs, float)
    ys = np.asarray(ys, float)
    n = xs.size
    fps = float(fps) if fps and fps > 0 else 30.0
    arena_path = None
    if arena is not None and len(arena) >= 3:
        from matplotlib.path import Path as MplPath
        arena_path = MplPath(np.asarray(arena, float))
    lo = center - radius - max_gap - 3
    hi = center + radius + max_gap + 3
    flags0, score0 = _local_flags(xs, ys, lo, hi, fps, px_per_cm, speed_thr,
                                  accel_thr, arena_path)
    if center not in flags0:
        return None
    protect = set(int(p) for p in protect)
    taken = set(int(t) for t in taken)
    best, best_key = None, None
    for a in range(max(0, center - radius), min(n, center + radius + 1)):
        for length in range(1, max_gap + 1):
            b = a + length - 1
            if b >= n or b in protect or a in protect:
                break
            if b < center - 1:
                continue          # must reach the flagged frame (or the one before it)
            if not np.isfinite(xs[a:b + 1]).any():
                continue
            if taken:
                lo_t, hi_t = a, b
                while lo_t - 1 in taken:
                    lo_t -= 1
                while hi_t + 1 in taken:
                    hi_t += 1
                if hi_t - lo_t + 1 > max_gap:
                    break             # would grow an earlier fix past the limit
            r = _interp_run(xs, ys, a, b)
            if r is None:
                continue
            flags, score = _local_flags(r[0], r[1], lo, hi, fps, px_per_cm,
                                        speed_thr, accel_thr, arena_path)
            # Never create a new problem; must remove >= 90% of the trouble
            # (a partial fix anchored on a still-wrong frame is rejected).
            if not flags <= flags0 or score > 0.1 * score0:
                continue
            # Smallest remaining excess, with a small cost per frame
            # changed (so the exact faulty frames win over wider runs).
            key = (round(score + CHANGE_COST * length, 6), length,
                   abs((a + b) / 2.0 - center))
            if best_key is None or key < best_key:
                best_key, best = key, (a, b)
    return best


def plan_auto_fix(xs, ys, fps, px_per_cm, arena, *, speed_thresh_cms,
                  accel_thresh_cms2, auto_speed=True, detectors=None,
                  protect=(), only=None, radius=3, max_gap=2, max_passes=4):
    """Simulate Auto-fix on a copy of the track (indexes = frame numbers).

    Returns (xs, ys, runs, unresolved):
      runs        (a, b) index runs, in the order they were replaced
                  (apply them in this order to reproduce the result)
      unresolved  flagged indexes still flagged afterwards
    `only` limits the work to these flagged indexes (Auto-fix & next).
    `protect` = indexes never changed (false-positives). The caller's data
    is not modified."""
    xs = np.asarray(xs, float).copy()
    ys = np.asarray(ys, float).copy()
    n = xs.size
    fps = float(fps) if fps and fps > 0 else 30.0
    protect = set(int(p) for p in protect)
    # Threshold fixed from the ORIGINAL track, so the target can't move.
    speed_thr = effective_speed_threshold(xs, ys, fps, px_per_cm,
                                          speed_thresh_cms, auto_speed)

    def flagged_now():
        df = pd.DataFrame({"Frame": np.arange(n), "X (px)": xs, "Y (px)": ys})
        iss = detect_issues(df, fps, px_per_cm, arena,
                            speed_thresh_cms=speed_thr,
                            accel_thresh_cms2=accel_thresh_cms2,
                            detectors=detectors, auto_speed=False)
        f = {int(r) for r in iss["_row"]} if len(iss) else set()
        f -= protect
        if only is not None:
            f &= set(int(o) for o in only)
        return sorted(f)

    runs, tried = [], set()
    for _ in range(max_passes):
        todo = [c for c in flagged_now() if c not in tried]
        if not todo:
            break
        changed = False
        for c in todo:
            tried.add(c)
            taken = {i for a, b in runs for i in range(a, b + 1)}
            fix = best_local_fix(xs, ys, c, fps, px_per_cm, speed_thr,
                                 accel_thresh_cms2, arena, radius=radius,
                                 max_gap=max_gap, protect=protect, taken=taken)
            if fix is None:
                continue
            xs, ys = _interp_run(xs, ys, fix[0], fix[1])
            runs.append((fix[0], fix[1]))
            changed = True
        if not changed:
            break
    return xs, ys, runs, flagged_now()   # runs in the order they were applied


def _merge_runs(runs):
    out = []
    for a, b in sorted(runs):
        if out and a <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out
