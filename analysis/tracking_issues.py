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
