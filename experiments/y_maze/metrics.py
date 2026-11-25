"""Y-Maze metrics: arm entries, time per arm, spontaneous alternation %,
latency to first entry, plus generic kinematics from core."""
import numpy as np
import pandas as pd

from core.arm_entries import arm_visits, point_in_polys
from core.kinematics import (
    compute_step_distance, compute_basic_kinematics, compute_pauses, time_at,
)
from .zones import ARM_NAMES, ARM_LABELS


def _arm_letter(arm_name):
    """arm_a → 'A', arm_b → 'B', arm_c → 'C'."""
    return arm_name[-1].upper() if arm_name else ""


def _alternation_pct(seq):
    """Spontaneous alternation: walk the entry sequence with a 3-wide
    sliding window. Each window of 3 consecutive entries is one triplet.
    A triplet is 'acceptable' (alternation) when all three are distinct
    arms; 'unacceptable' otherwise (one arm repeats inside the triplet).

    Returns (pct, acceptable_count, denominator, triplets_all,
             triplets_ok, triplets_bad). The triplet lists hold 3-letter
    strings like 'ABC' / 'BCB' so they can be written directly to Excel."""
    if len(seq) < 3:
        return 0.0, 0, max(0, len(seq) - 2), [], [], []
    triplets_all = []
    triplets_ok = []
    triplets_bad = []
    for i in range(len(seq) - 2):
        tri = seq[i:i + 3]
        label = "".join(_arm_letter(a) for a in tri)
        triplets_all.append(label)
        if len(set(tri)) == 3:
            triplets_ok.append(label)
        else:
            triplets_bad.append(label)
    alt = len(triplets_ok)
    denom = len(seq) - 2
    pct = (alt / denom * 100.0) if denom > 0 else 0.0
    return pct, alt, denom, triplets_all, triplets_ok, triplets_bad


def compute(results, settings, fps, px_per_cm):
    """settings: dict with arms (name -> px polygon), entry_rule,
    min_dwell_s, movement_threshold, bin_size_s."""
    df = pd.DataFrame(results)
    scale, unit = compute_step_distance(df, px_per_cm, fps)
    move_thr = float(settings.get("movement_threshold", 0.0))
    basic = compute_basic_kinematics(df, fps, unit, movement_threshold=move_thr)
    pauses = compute_pauses(df, fps, unit, movement_threshold=max(move_thr, 1e-6),
                             min_dur_s=float(settings.get("pause_min_dur_s", 1.0)))

    arms_px = settings.get("arms") or {}
    neutral_px = settings.get("neutral") or []
    # entry_rule is always body center now; the legacy "nose" / "all" options
    # were removed when those points stopped being tracked. Kept in metrics
    # output for backwards-compatible columns.
    rule = "body"
    min_dwell_s = float(settings.get("min_dwell_s", 0.5))
    min_frames = max(1, int(round(min_dwell_s * (fps or 30.0))))

    xs = df["x"].astype(float).values
    ys = df["y"].astype(float).values

    # Build a zone polygon dict that includes neutral; assign neutral
    # FIRST so it wins overlap with arms near the hub (matches live
    # paint_ym_overlay behavior).
    zone_polys = dict(arms_px)
    if neutral_px and len(neutral_px) >= 3:
        zone_polys["neutral_zone"] = neutral_px
    zone_seq = point_in_polys(
        xs, ys, zone_polys, priority_first="neutral_zone"
    )
    # Confirmed zone per frame (arm, neutral_zone or None), entries,
    # and entry events (frame, arm) for per-bin counts + alternation.
    confirmed_seq, entries, times_f, seq, entry_events = arm_visits(
        zone_seq, ARM_NAMES, min_frames)
    frame_dur = 1.0 / fps if fps else 0.0
    times_s = {a: times_f[a] * frame_dur for a in ARM_NAMES}

    # Neutral entries + time. An entry counts on each transition INTO the
    # neutral zone from a different zone (matches the live overlay rule).
    # Time accumulates per-frame the body is in neutral, no debounce.
    neutral_frames = int(sum(1 for z in zone_seq if z == "neutral_zone"))
    neutral_entries = 0
    prev = None
    for z in zone_seq:
        if z == "neutral_zone" and prev != "neutral_zone":
            neutral_entries += 1
        if z is not None:
            prev = z
    neutral_time_s = neutral_frames * frame_dur

    (alt_pct, alt_count, alt_denom,
     triplets_all, triplets_ok, triplets_bad) = _alternation_pct(seq)

    # Same-Arm Return: an entry into the arm the mouse just left (A → A).
    sar_count = sum(1 for i in range(1, len(seq)) if seq[i] == seq[i - 1])

    total_entries = sum(entries.values())
    duration_s_val = float(basic.get("Duration (s)", 0.0)) or 0.0
    low_activity_flag = total_entries < 8
    first_arm = _arm_letter(seq[0]) if seq else None

    # Latency to first *confirmed* entry (s, source-video time).
    # Sub-threshold blips don't count; trim offset is added back so the
    # number is comparable to wall-clock video time, not trim-relative.
    trim_start_s = float(settings.get("trim_start_s", 0.0))
    latency_s = None
    for i, a in enumerate(confirmed_seq):
        if a in ARM_NAMES:
            latency_s = time_at(df, i, fps) + trim_start_s
            break

    # compute_basic_kinematics / compute_pauses return human-readable
    # keys like "Total Distance (cm)" — pull the values out by those
    # actual keys, otherwise everything ends up as the 0.0 default.
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
        # Track corrections (same counts as Open Field / box tests).
        "interpolated_frames": basic.get("Interpolated Frames", 0),
        "hand_fixed_frames":   basic.get("Hand-fixed Frames", 0),
        "removed_frames":      basic.get("Removed Frames", 0),
        "corrected_frames_pct": basic.get("Corrected Frames (%)", 0.0),
        "unit":           unit,
        # Blank (not 0 %) when there are < 3 entries — no triplet exists.
        "alternation_pct": round(alt_pct, 2) if alt_denom > 0 else None,
        "alternations":    alt_count,
        "alternation_denominator": alt_denom,
        "sar_count":       sar_count,
        "first_arm":       first_arm,
        "low_activity_flag": low_activity_flag,
        "total_entries":   total_entries,
        "entry_rule":      rule,
        "min_dwell_s":     min_dwell_s,
        "latency_first_entry_s": (round(latency_s, 3) if latency_s is not None else None),
        "pause_count":    pauses.get("Pause Count (#)", 0),
        "pause_total_s":  pauses.get("Total Time in Pauses (s)", 0.0),
        "pause_mean_s":   pauses.get("Mean Pause Duration (s)", 0.0),
        "pause_longest_s": pauses.get("Longest Pause (s)", 0.0),
        "entry_sequence": "".join("ABC"["abc".index(a[-1])] for a in seq),
        # Sliding-window triplets of the entry sequence and their A/U
        # classification. Strings are space-separated so they read cleanly
        # in Excel cells (e.g. "ABC BCA CAB ABC BCB").
        "triplets_all":               " ".join(triplets_all),
        "triplets_acceptable":        " ".join(triplets_ok),
        "triplets_unacceptable":      " ".join(triplets_bad),
        "triplets_total_count":       len(triplets_all),
        "triplets_acceptable_count":  len(triplets_ok),
        "triplets_unacceptable_count": len(triplets_bad),
    }
    for a in ARM_NAMES:
        e = entries[a]
        t_s = times_s[a]
        metrics[f"entries_{a}"] = e
        metrics[f"time_{a}_s"]  = round(t_s, 3)
        metrics[f"pct_entries_{a}"] = (
            round(e / total_entries * 100.0, 2) if total_entries > 0 else 0.0
        )
        metrics[f"pct_time_{a}"] = (
            round(t_s / duration_s_val * 100.0, 2) if duration_s_val > 0 else 0.0
        )
        metrics[f"mean_dwell_{a}_s"] = (
            round(t_s / e, 3) if e > 0 else None
        )
    metrics["entries_neutral_zone"] = neutral_entries
    metrics["time_neutral_zone_s"] = round(neutral_time_s, 3)

    # Raw per-frame. Column names match the OF contract ("X (px)", "Y (px)",
    # "Zone", "Step Distance (unit)", "Speed (unit/s)") so downstream consumers
    # (excel_export, tracking_issues, graphs) work without an experiment branch.
    # "Zone" carries the geometric zone (Arm A/B/C, Neutral, or blank);
    # "Arm (Confirmed)" is the debounced arm-only column for metric matching.
    arm_col = [
        ("Neutral" if z == "neutral_zone"
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
        # Per-bin time uses the debounced sequence for arms so totals
        # match the "time_arm_*_s" metrics; neutral time per bin is read
        # off the raw geometric zone_seq (no debounce on neutral, same
        # as the live overlay).
        bin_df = _bin_metrics(confirmed_seq, list(zone_seq), fps, bin_size_s,
                              df=df, unit=unit, entry_events=entry_events)

    return metrics, raw_df, bin_df


def _bin_metrics(arm_seq, zone_seq, fps, bin_size_s,
                 df=None, unit="cm", entry_events=None):
    """Per-bin time-course metrics. Beyond time-per-zone, each bin also
    carries entries-per-arm (filtered from the global entry_events list),
    locomotion (distance + mean speed from df), and a per-bin spontaneous
    alternation % (computed on the bin-local arm-entry sequence)."""
    frame_dur = 1.0 / fps if fps else 0.0
    bin_frames = max(1, int(round(bin_size_s * fps)))
    rows = []
    n = len(arm_seq)
    entry_events = entry_events or []
    has_df = df is not None and len(df) > 0
    for start in range(0, n, bin_frames):
        end = min(n, start + bin_frames)
        arm_chunk = arm_seq[start:end]
        zone_chunk = zone_seq[start:end]
        row = {
            "bin_start_s": round(start * frame_dur, 2),
            "bin_end_s":   round(end * frame_dur, 2),
        }
        for a in ARM_NAMES:
            row[f"time_{a}_s"] = round(
                sum(1 for x in arm_chunk if x == a) * frame_dur, 3
            )
        row["time_neutral_zone_s"] = round(
            sum(1 for z in zone_chunk if z == "neutral_zone") * frame_dur, 3
        )

        # Per-bin entries from the precomputed event list.
        bin_events = [(f, a) for (f, a) in entry_events if start <= f < end]
        for a in ARM_NAMES:
            row[f"entries_{a}"] = sum(1 for (_, x) in bin_events if x == a)
        row["total_entries"] = len(bin_events)

        # Per-bin alternation % on the bin-local entry sequence.
        bin_seq = [a for (_, a) in bin_events]
        pct, _alt, _den, _all, _ok, _bad = _alternation_pct(bin_seq)
        row["alternation_pct"] = round(pct, 2) if len(bin_seq) >= 3 else None

        # Per-bin locomotion.
        if has_df:
            chunk = df.iloc[start:end]
            row[f"distance_{unit}"] = round(
                float(chunk["step_dist"].sum(skipna=True)), 3
            )
            mean_sp = float(chunk["speed"].mean(skipna=True))
            row[f"mean_speed_{unit}_per_s"] = (
                round(mean_sp, 3) if mean_sp == mean_sp else None  # NaN check
            )
        rows.append(row)
    return pd.DataFrame(rows)


EXPORT_COLUMNS = [
    "Animal ID", "Group", "Sex", "Date", "Trial",
    "duration_s", "total_distance", "mean_speed",
    "alternation_pct", "alternations", "alternation_denominator",
    "sar_count", "first_arm", "low_activity_flag",
    "total_entries", "entries_arm_a", "entries_arm_b", "entries_arm_c",
    "entries_neutral_zone",
    "pct_entries_arm_a", "pct_entries_arm_b", "pct_entries_arm_c",
    "time_arm_a_s", "time_arm_b_s", "time_arm_c_s", "time_neutral_zone_s",
    "pct_time_arm_a", "pct_time_arm_b", "pct_time_arm_c",
    "mean_dwell_arm_a_s", "mean_dwell_arm_b_s", "mean_dwell_arm_c_s",
    "latency_first_entry_s", "entry_rule", "min_dwell_s",
    "entry_sequence",
    "triplets_all", "triplets_acceptable", "triplets_unacceptable",
    "triplets_total_count", "triplets_acceptable_count",
    "triplets_unacceptable_count",
    "pause_count", "pause_total_s", "Notes",
]


# Combined-export "All Animals" master-sheet layout for Y-Maze. Sections
# group related metrics with banner headers in row 1, column titles in
# row 2, and one row per animal beneath. Same structure pattern as OF's
# BATCH_SCHEMA so the export writer renders both consistently.
BATCH_SCHEMA = [
    ("Experiment Metadata", [
        "Video", "Animal ID", "Group", "Sex", "Date", "Trial", "Notes",
    ]),
    ("Locomotion", [
        "duration_s", "total_distance", "mean_speed", "max_speed",
    ]),
    ("Arm Entries", [
        "total_entries",
        "entries_arm_a", "entries_arm_b", "entries_arm_c",
        "entries_neutral_zone",
        "pct_entries_arm_a", "pct_entries_arm_b", "pct_entries_arm_c",
    ]),
    ("Arm Time (s)", [
        "time_arm_a_s", "time_arm_b_s", "time_arm_c_s",
        "time_neutral_zone_s",
        "pct_time_arm_a", "pct_time_arm_b", "pct_time_arm_c",
        "mean_dwell_arm_a_s", "mean_dwell_arm_b_s", "mean_dwell_arm_c_s",
    ]),
    ("Alternation", [
        "alternation_pct", "alternations", "alternation_denominator",
        "sar_count", "first_arm", "entry_sequence",
    ]),
    ("QC", [
        "low_activity_flag",
    ]),
    ("Triplets", [
        "triplets_total_count", "triplets_acceptable_count",
        "triplets_unacceptable_count",
        "triplets_all", "triplets_acceptable", "triplets_unacceptable",
    ]),
    ("Timing", [
        "latency_first_entry_s", "entry_rule", "min_dwell_s",
    ]),
    ("Pauses / Freezing", [
        "pause_count", "pause_total_s",
    ]),
]
BATCH_SCHEMA.append(("Tracking Corrections", [
    "interpolated_frames", "hand_fixed_frames", "removed_frames",
    "corrected_frames_pct",
]))
