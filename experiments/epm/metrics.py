"""EPM metrics: per-arm entries + time, open/closed aggregation, percent
time per category, latency to first open-arm entry, plus generic
kinematics from core."""
import numpy as np
import pandas as pd

from core.arm_entries import arm_visits, point_in_polys
from core.kinematics import (
    compute_step_distance, compute_basic_kinematics, compute_pauses,
)
from .zones import (
    ARM_NAMES, ARM_LABELS, DEFAULT_ARM_KINDS, aggregate_kind_membership,
)


def _arm_letter(arm_name):
    """arm_n -> 'N', arm_s -> 'S', arm_e -> 'E', arm_w -> 'W'."""
    return arm_name[-1].upper() if arm_name else ""


def compute(results, settings, fps, px_per_cm):
    """settings keys: arms (name -> px polygon), center (px polygon),
    arm_kinds (name -> 'open'|'closed'|'neutral'|'custom'),
    arm_custom_names (name -> user string), entry_rule, min_dwell_s,
    movement_threshold, bin_size_s, trim_start_s."""
    df = pd.DataFrame(results)
    scale, unit = compute_step_distance(df, px_per_cm, fps)
    move_thr = float(settings.get("movement_threshold", 0.0))
    basic = compute_basic_kinematics(df, fps, unit, movement_threshold=move_thr)
    pauses = compute_pauses(df, fps, unit,
                            movement_threshold=max(move_thr, 1e-6),
                            min_dur_s=float(settings.get("pause_min_dur_s", 1.0)))

    arms_px = settings.get("arms") or {}
    center_px = settings.get("center") or []
    arm_kinds = dict(DEFAULT_ARM_KINDS)
    arm_kinds.update(settings.get("arm_kinds") or {})
    arm_custom_names = settings.get("arm_custom_names") or {}

    rule = "body"
    min_dwell_s = float(settings.get("min_dwell_s", 0.5))
    min_frames = max(1, int(round(min_dwell_s * (fps or 30.0))))

    xs = df["x"].astype(float).values
    ys = df["y"].astype(float).values

    zone_polys = dict(arms_px)
    if center_px and len(center_px) >= 3:
        zone_polys["center_zone"] = center_px
    zone_seq = point_in_polys(
        xs, ys, zone_polys, priority_first="center_zone"
    )
    # Confirmed zone per frame (arm, center_zone or None) + entries.
    confirmed_seq, entries, times_f, seq, entry_events = arm_visits(
        zone_seq, ARM_NAMES, min_frames)
    frame_dur = 1.0 / fps if fps else 0.0
    times_s = {a: times_f[a] * frame_dur for a in ARM_NAMES}

    # Center entries + time (no debounce on center; matches live overlay).
    center_frames = int(sum(1 for z in zone_seq if z == "center_zone"))
    center_entries = 0
    prev = None
    for z in zone_seq:
        if z == "center_zone" and prev != "center_zone":
            center_entries += 1
        if z is not None:
            prev = z
    center_time_s = center_frames * frame_dur

    total_entries = sum(entries.values())
    duration_s_val = float(basic.get("Duration (s)", 0.0)) or 0.0
    first_arm = _arm_letter(seq[0]) if seq else None

    # Kind aggregation: total entries + time per category.
    kind_map = aggregate_kind_membership(arm_kinds)
    open_arms = kind_map.get("open", [])
    closed_arms = kind_map.get("closed", [])
    entries_open_total = sum(entries[a] for a in open_arms)
    entries_closed_total = sum(entries[a] for a in closed_arms)
    time_open_total_s = sum(times_s[a] for a in open_arms)
    time_closed_total_s = sum(times_s[a] for a in closed_arms)

    entries_categorized = entries_open_total + entries_closed_total

    def _pct(a, b):
        return round(a / b * 100.0, 2) if b > 0 else 0.0

    # Standard EPM index: % of arm time (open + closed), same base as
    # % open entries. Center % stays a share of the whole session.
    arm_time_s = time_open_total_s + time_closed_total_s
    pct_time_open = _pct(time_open_total_s, arm_time_s)
    pct_time_closed = _pct(time_closed_total_s, arm_time_s)
    pct_time_center = _pct(center_time_s, duration_s_val)
    pct_entries_open = _pct(entries_open_total, entries_categorized)
    pct_entries_closed = _pct(entries_closed_total, entries_categorized)

    # Latency to first open-arm entry. If the mouse starts already inside
    # an open arm (frame 0 confirmed as open), latency = 0.0.
    trim_start_s = float(settings.get("trim_start_s", 0.0))
    latency_open_s = None
    open_set = set(open_arms)
    for i, a in enumerate(confirmed_seq):
        if a in open_set:
            latency_open_s = i * frame_dur + trim_start_s
            break

    # Generic latency to first ANY confirmed arm entry (kept for parity).
    latency_any_s = None
    for i, a in enumerate(confirmed_seq):
        if a in ARM_NAMES:
            latency_any_s = i * frame_dur + trim_start_s
            break

    low_activity_flag = entries_categorized < 10

    metrics = {
        "duration_s":     basic.get("Duration (s)", 0.0),
        "total_distance": basic.get(f"Total Distance ({unit})", 0.0),
        "mean_speed":     basic.get(f"Average Speed ({unit}/s)", 0.0),
        "max_speed":      basic.get(f"Max Speed ({unit}/s)", 0.0),
        "median_speed":   basic.get(f"Median Speed ({unit}/s)", 0.0),
        "p90_speed":      basic.get(f"P90 Speed ({unit}/s)", 0.0),
        "p99_speed":      basic.get(f"P99 Speed ({unit}/s)", 0.0),
        "mobility_time_s":   basic.get("Mobility Time (s)", 0.0),
        "immobility_time_s": basic.get("Immobility Time (s)", 0.0),
        "tortuosity":     basic.get("Tortuosity", "n/a"),
        "frames_detected":   basic.get("Frames Detected", 0),
        "total_frames":      basic.get("Total Frames", 0),
        "detection_rate_pct": basic.get("Detection Rate (%)", 0.0),
        "unit":           unit,
        "entry_rule":     rule,
        "min_dwell_s":    min_dwell_s,
        "first_arm":      first_arm,
        "low_activity_flag": low_activity_flag,
        "total_entries":  total_entries,
        # Open/closed aggregation.
        "entries_open_total":   entries_open_total,
        "entries_closed_total": entries_closed_total,
        "time_open_total_s":    round(time_open_total_s, 3),
        "time_closed_total_s":  round(time_closed_total_s, 3),
        "time_center_s":        round(center_time_s, 3),
        "entries_center":       center_entries,
        "pct_time_open_of_arms":        pct_time_open,
        "pct_time_closed_of_arms":      pct_time_closed,
        "pct_time_center":      pct_time_center,
        "pct_entries_open":     pct_entries_open,
        "pct_entries_closed":   pct_entries_closed,
        "latency_first_open_entry_s":
            (round(latency_open_s, 3) if latency_open_s is not None else None),
        "latency_first_entry_s":
            (round(latency_any_s, 3) if latency_any_s is not None else None),
        "pause_count":    pauses.get("Pause Count (#)", 0),
        "pause_total_s":  pauses.get("Total Time in Pauses (s)", 0.0),
        "pause_mean_s":   pauses.get("Mean Pause Duration (s)", 0.0),
        "pause_longest_s": pauses.get("Longest Pause (s)", 0.0),
        "entry_sequence": "".join(_arm_letter(a) for a in seq),
    }

    # Per-arm details (entries, time, %, mean dwell, kind, custom name).
    for a in ARM_NAMES:
        e = entries[a]
        t_s = times_s[a]
        metrics[f"entries_{a}"] = e
        metrics[f"time_{a}_s"]  = round(t_s, 3)
        metrics[f"pct_entries_{a}"] = (
            round(e / total_entries * 100.0, 2) if total_entries > 0 else 0.0
        )
        metrics[f"pct_time_{a}"] = (
            round(t_s / duration_s_val * 100.0, 2)
            if duration_s_val > 0 else 0.0
        )
        metrics[f"mean_dwell_{a}_s"] = (
            round(t_s / e, 3) if e > 0 else None
        )
        metrics[f"kind_{a}"] = arm_kinds.get(a, DEFAULT_ARM_KINDS[a])
        cname = arm_custom_names.get(a)
        if cname:
            metrics[f"name_{a}"] = cname

    # Raw per-frame columns mirror OF / Y-Maze contract.
    arm_col = [
        ("Center" if z == "center_zone"
         else ARM_LABELS.get(z, "") if z else "")
        for z in zone_seq
    ]
    arm_confirmed_col = [
        ARM_LABELS.get(a, "") if a else "" for a in confirmed_seq
    ]
    raw_df = df[["frame", "timestamp", "x", "y", "step_dist", "speed"]].copy()
    raw_df["Zone"] = arm_col
    raw_df["Arm (Confirmed)"] = arm_confirmed_col
    raw_df.columns = [
        "Frame", "Time (s)", "X (px)", "Y (px)",
        f"Step Distance ({unit})", f"Speed ({unit}/s)",
        "Zone", "Arm (Confirmed)",
    ]
    for src, dst in (("nose_x", "Nose X (px)"), ("nose_y", "Nose Y (px)"),
                     ("tail_x", "Tail X (px)"), ("tail_y", "Tail Y (px)"),
                     ("nose_confidence", "Nose Confidence")):
        if src in df.columns:
            raw_df[dst] = df[src]

    bin_size_s = float(settings.get("bin_size_s", 0.0))
    bin_df = None
    if bin_size_s > 0 and frame_dur > 0:
        bin_df = _bin_metrics(
            confirmed_seq, list(zone_seq), fps, bin_size_s,
            df=df, unit=unit, entry_events=entry_events, kind_map=kind_map,
        )

    return metrics, raw_df, bin_df


def _bin_metrics(arm_seq, zone_seq, fps, bin_size_s,
                 df=None, unit="cm", entry_events=None, kind_map=None):
    """Per-bin time-course metrics: time per kind (open/closed/center),
    entries per kind, plus per-bin distance + mean speed."""
    frame_dur = 1.0 / fps if fps else 0.0
    bin_frames = max(1, int(round(bin_size_s * fps)))
    rows = []
    n = len(arm_seq)
    entry_events = entry_events or []
    kind_map = kind_map or {}
    open_arms = set(kind_map.get("open", []))
    closed_arms = set(kind_map.get("closed", []))
    has_df = df is not None and len(df) > 0
    for start in range(0, n, bin_frames):
        end = min(n, start + bin_frames)
        arm_chunk = arm_seq[start:end]
        zone_chunk = zone_seq[start:end]
        row = {
            "bin_start_s": round(start * frame_dur, 2),
            "bin_end_s":   round(end * frame_dur, 2),
        }
        open_frames = sum(1 for x in arm_chunk if x in open_arms)
        closed_frames = sum(1 for x in arm_chunk if x in closed_arms)
        center_frames = sum(1 for z in zone_chunk if z == "center_zone")
        row["time_open_s"] = round(open_frames * frame_dur, 3)
        row["time_closed_s"] = round(closed_frames * frame_dur, 3)
        row["time_center_s"] = round(center_frames * frame_dur, 3)
        bin_events = [(f, a) for (f, a) in entry_events if start <= f < end]
        row["entries_open"] = sum(1 for (_, a) in bin_events if a in open_arms)
        row["entries_closed"] = sum(1 for (_, a) in bin_events if a in closed_arms)
        row["total_entries"] = len(bin_events)
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
    "total_entries",
    "entries_open_total", "entries_closed_total", "entries_center",
    "time_open_total_s", "time_closed_total_s", "time_center_s",
    "pct_time_open_of_arms", "pct_time_closed_of_arms", "pct_time_center",
    "pct_entries_open", "pct_entries_closed",
    "latency_first_open_entry_s",
    "entries_arm_n", "entries_arm_s", "entries_arm_e", "entries_arm_w",
    "time_arm_n_s", "time_arm_s_s", "time_arm_e_s", "time_arm_w_s",
    "pct_time_arm_n", "pct_time_arm_s", "pct_time_arm_e", "pct_time_arm_w",
    "pct_entries_arm_n", "pct_entries_arm_s", "pct_entries_arm_e", "pct_entries_arm_w",
    "mean_dwell_arm_n_s", "mean_dwell_arm_s_s", "mean_dwell_arm_e_s", "mean_dwell_arm_w_s",
    "kind_arm_n", "kind_arm_s", "kind_arm_e", "kind_arm_w",
    "first_arm", "low_activity_flag",
    "entry_rule", "min_dwell_s",
    "entry_sequence",
    "pause_count", "pause_total_s", "Notes",
]


BATCH_SCHEMA = [
    ("Experiment Metadata", [
        "Video", "Animal ID", "Group", "Sex", "Date", "Trial", "Notes",
    ]),
    ("Locomotion", [
        "duration_s", "total_distance", "mean_speed", "max_speed",
    ]),
    ("Open Arms", [
        "entries_open_total", "time_open_total_s",
        "pct_time_open_of_arms", "pct_entries_open",
        "latency_first_open_entry_s",
    ]),
    ("Closed Arms", [
        "entries_closed_total", "time_closed_total_s",
        "pct_time_closed_of_arms", "pct_entries_closed",
    ]),
    ("Center", [
        "entries_center", "time_center_s", "pct_time_center",
    ]),
    ("Per-Arm Entries", [
        "total_entries",
        "entries_arm_n", "entries_arm_s", "entries_arm_e", "entries_arm_w",
        "pct_entries_arm_n", "pct_entries_arm_s",
        "pct_entries_arm_e", "pct_entries_arm_w",
    ]),
    ("Per-Arm Time (s)", [
        "time_arm_n_s", "time_arm_s_s", "time_arm_e_s", "time_arm_w_s",
        "pct_time_arm_n", "pct_time_arm_s",
        "pct_time_arm_e", "pct_time_arm_w",
        "mean_dwell_arm_n_s", "mean_dwell_arm_s_s",
        "mean_dwell_arm_e_s", "mean_dwell_arm_w_s",
    ]),
    ("Arm Kinds", [
        "kind_arm_n", "kind_arm_s", "kind_arm_e", "kind_arm_w",
        "first_arm",
    ]),
    ("QC", [
        "low_activity_flag",
    ]),
    ("Timing", [
        "entry_rule", "min_dwell_s", "latency_first_entry_s",
    ]),
    ("Pauses / Freezing", [
        "pause_count", "pause_total_s",
    ]),
]
