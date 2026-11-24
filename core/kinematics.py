"""Generic kinematics — distance / speed / mobility / pauses.

Shared across all behavioral assays (Open Field, FST, Y-Maze, NOR, Social).
Operates on a DataFrame with columns x, y, timestamp.
"""
import numpy as np
import pandas as pd


def compute_step_distance(df: pd.DataFrame, px_per_cm, fps):
    """Augment df with step_px, step_dist, speed columns. Returns
    (scale, unit) where scale is the per-pixel multiplier that converts
    pixel distances to the chosen unit, and unit is "cm" or "px".

    Mutates df in place. Distance bridges short tracker gaps: a step is
    measured from the LAST valid frame to the current valid frame (not
    only from the direct predecessor), so a 1-frame detection miss no
    longer drops motion on both sides of the gap. Speed is divided by
    the actual gap span so it remains in units/second."""
    df["x"] = pd.to_numeric(df["x"], errors="coerce")
    df["y"] = pd.to_numeric(df["y"], errors="coerce")
    n = len(df)
    xs = df["x"].to_numpy(dtype=float, copy=False)
    ys = df["y"].to_numpy(dtype=float, copy=False)
    step_px = np.full(n, np.nan)
    speed_px = np.full(n, np.nan)
    fps_eff = float(fps) if fps else 0.0
    # Real frame times (tracker reads them from the video) so a dropped-
    # frame gap does not turn into a speed spike.
    ts = (pd.to_numeric(df["timestamp"], errors="coerce").to_numpy(dtype=float)
          if "timestamp" in df.columns else np.full(n, np.nan))
    # Each detected frame steps from the previous detected one.
    valid = np.flatnonzero(~np.isnan(xs))
    if valid.size > 1:
        prev, cur = valid[:-1], valid[1:]
        dx = xs[cur] - xs[prev]
        dy = ys[cur] - ys[prev]
        d = np.sqrt(dx * dx + dy * dy)
        step_px[cur] = d
        span = ts[cur] - ts[prev]
        gap = cur - prev
        with np.errstate(invalid="ignore", divide="ignore"):
            by_time = span > 0
            sp = np.where(by_time, d / np.where(by_time, span, 1.0), np.nan)
            if fps_eff > 0:
                sp = np.where(by_time, sp, d * fps_eff / gap)
        speed_px[cur] = sp

    if px_per_cm and px_per_cm > 0:
        scale = 1.0 / px_per_cm
        unit = "cm"
    else:
        scale = 1.0
        unit = "px"

    df["step_px"]   = step_px
    df["step_dist"] = step_px * scale
    df["speed"]     = speed_px * scale
    return scale, unit


def time_at(df, i, fps):
    """Video time (s) of row i: the tracker's real frame time when present
    (correct across dropped-frame gaps), else i / fps."""
    if df is not None and "timestamp" in df.columns and 0 <= i < len(df):
        t = pd.to_numeric(df["timestamp"].iloc[i], errors="coerce")
        if pd.notna(t):
            return float(t)
    return i / fps if fps else 0.0


def session_duration(df, fps):
    """Real session length (s): first to last frame time plus one frame,
    so a dropped-frame gap in the recording counts. Falls back to
    frames / fps when the frame times are missing or out of order.
    Zone times still count observed frames only — where the mouse was
    during a gap is unknown."""
    n = len(df)
    if n == 0 or not fps:
        return 0.0
    by_frames = n / fps
    if "timestamp" not in df.columns:
        return by_frames
    ts = pd.to_numeric(df["timestamp"], errors="coerce").to_numpy(dtype=float)
    if np.isnan(ts).any() or (np.diff(ts) < 0).any():
        return by_frames
    real = float(ts[-1] - ts[0]) + 1.0 / fps
    # only trust it for a real gap, not timestamp jitter
    return real if real > by_frames + 1.5 / fps else by_frames


def compute_basic_kinematics(df: pd.DataFrame, fps, unit, movement_threshold=0.0):
    """Top-level distance / speed / mobility metrics.

    Requires df to already have step_dist + speed columns
    (call compute_step_distance first).

    Returns a dict with the metric names that go straight into the
    summary table.
    """
    # fps can be 0 if cv2 fails to read it AND fps_override is unset.
    # Substitute a sentinel so downstream divisions don't crash; metrics
    # will be meaningless but the run completes.
    fps = float(fps) if fps and fps > 0 else 30.0
    duration_s = session_duration(df, fps)
    total_dist = float(df["step_dist"].sum())
    avg_speed = total_dist / duration_s if duration_s > 0 else 0.0
    max_speed = float(df["speed"].max()) if df["speed"].notna().any() else 0.0
    detected = int(df["x"].notna().sum())
    total_frames = len(df)
    det_rate = round(100.0 * detected / total_frames, 1) if total_frames > 0 else 0.0

    out = {
        f"Total Distance ({unit})":  round(total_dist, 2),
        f"Average Speed ({unit}/s)": round(avg_speed, 3),
        f"Max Speed ({unit}/s)":     round(max_speed, 3),
        "Duration (s)":              round(duration_s, 2),
        "Frames Detected":           detected,
        "Total Frames":              total_frames,
        "Detection Rate (%)":        det_rate,
    }
    # Corrections: how much of the track is not the tracker's own output.
    def _flag(col):
        if col not in df.columns:
            return pd.Series(False, index=df.index)
        return df[col].fillna(False).astype(bool)
    interp = int(_flag("interpolated").sum())
    corr = _flag("corrected")
    hand = int((corr & df["x"].notna()).sum())
    removed = int((corr & df["x"].isna()).sum())
    out["Interpolated Frames"] = interp
    out["Hand-fixed Frames"] = hand
    out["Removed Frames"] = removed
    out["Corrected Frames (%)"] = (round(100.0 * (interp + hand + removed) / total_frames, 2)
                                   if total_frames > 0 else 0.0)

    speeds = df["speed"].dropna()
    if not speeds.empty:
        out[f"Median Speed ({unit}/s)"] = round(float(speeds.median()), 3)
        out[f"P90 Speed ({unit}/s)"]    = round(float(speeds.quantile(0.90)), 3)
        out[f"P99 Speed ({unit}/s)"]    = round(float(speeds.quantile(0.99)), 3)

    if movement_threshold and movement_threshold > 0:
        frame_dur = 1.0 / fps
        # Undetected frames (speed NaN) are neither mobile nor immobile.
        mobile_mask = df["speed"] > movement_threshold
        mobility_s   = float(mobile_mask.sum() * frame_dur)
        immobility_s = float((df["speed"] <= movement_threshold).sum() * frame_dur)
        out[f"Movement Threshold ({unit}/s)"] = round(movement_threshold, 3)
        out["Mobility Time (s)"]   = round(mobility_s, 2)
        out["Immobility Time (s)"] = round(immobility_s, 2)
        # Mean speed while mobile only — useful when the overall mean is
        # dragged down by long pauses. Reports n/a when there are no
        # mobile frames at all.
        mobile_speeds = df.loc[mobile_mask, "speed"].dropna()
        if not mobile_speeds.empty:
            out[f"Mean Speed When Mobile ({unit}/s)"] = round(
                float(mobile_speeds.mean()), 3
            )
        else:
            out[f"Mean Speed When Mobile ({unit}/s)"] = "n/a"

    # Tortuosity — total path length / net displacement. ≥ 1.0; higher
    # means a more circuitous path. Unitless ratio, so we can use pixel
    # distances directly (no unit conversion needed). Reports n/a if
    # the animal never moves (displacement = 0).
    valid_xy = df[["x", "y"]].dropna()
    total_px = float(df["step_px"].sum()) if df["step_px"].notna().any() else 0.0
    if len(valid_xy) >= 2 and total_px > 0:
        x0, y0 = valid_xy.iloc[0]
        x1, y1 = valid_xy.iloc[-1]
        net_disp_px = float(np.hypot(x1 - x0, y1 - y0))
        if net_disp_px > 0:
            out["Tortuosity"] = round(total_px / net_disp_px, 3)
        else:
            out["Tortuosity"] = "n/a"
    else:
        out["Tortuosity"] = "n/a"

    return out


def compute_pauses(df: pd.DataFrame, fps, unit, movement_threshold, min_dur_s):
    """Freezing / pause analysis. A pause is a contiguous run of frames
    where speed <= threshold for at least min_dur_s.

    Returns a dict of pause metrics (count, mean, longest, total)."""
    if not movement_threshold or movement_threshold <= 0:
        return {}
    fps = float(fps) if fps and fps > 0 else 30.0
    frame_dur = 1.0 / fps
    # Undetected frames (speed NaN) are False here, so a tracking gap
    # ends a pause instead of being counted as one.
    immobile_mask = (df["speed"] <= movement_threshold).values
    pause_durs = find_runs(immobile_mask, frame_dur, min_dur_s)
    return {
        f"Pause Threshold ({unit}/s)":   round(movement_threshold, 3),
        "Min Pause Duration (s)":        round(min_dur_s, 2),
        "Pause Count (#)":               len(pause_durs),
        "Mean Pause Duration (s)":       round(float(np.mean(pause_durs)), 2) if pause_durs else 0.0,
        "Longest Pause (s)":             round(float(np.max(pause_durs)), 2) if pause_durs else 0.0,
        "Total Time in Pauses (s)":      round(float(sum(pause_durs)), 2),
    }


def find_runs(mask, frame_dur, min_dur_s):
    """Given a boolean mask (one entry per frame), return a list of run
    durations (in seconds) where mask is True for at least min_dur_s."""
    if len(mask) == 0:
        return []
    out = []
    in_run = False
    run_start = 0
    for i, v in enumerate(mask):
        if v and not in_run:
            in_run = True
            run_start = i
        elif not v and in_run:
            in_run = False
            dur = (i - run_start) * frame_dur
            if dur >= min_dur_s:
                out.append(dur)
    if in_run:
        dur = (len(mask) - run_start) * frame_dur
        if dur >= min_dur_s:
            out.append(dur)
    return out
