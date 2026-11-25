"""Readable Excel names for the snake_case measures of the Y-Maze, EPM,
NOR and Object Location tests ('time_arm_a_s' -> 'Time in Arm A (s)').

Open Field and the box tests already compute readable names; with this
step every experiment's Excel uses the same style, and the unit in
'(…)' lets core.units add every other scale next to it. Only the Excel
files are renamed — the computed metrics keep their keys.
"""
import re

# measures without a time unit
_PLAIN = {
    "alternation_pct": "Spontaneous Alternation (%)",
    "alternations": "Alternations (#)",
    "alternation_denominator": "Possible Alternations (#)",
    "sar_count": "Same-Arm Returns (#)",
    "first_arm": "First Arm Entered",
    "low_activity_flag": "Low Activity Flag",
    "total_entries": "Total Arm Entries (#)",
    "entry_rule": "Entry Rule",
    "entry_sequence": "Arm Entry Sequence",
    "triplets_all": "All Triplets",
    "triplets_acceptable": "Alternation Triplets",
    "triplets_unacceptable": "Non-alternation Triplets",
    "triplets_total_count": "Triplets (#)",
    "triplets_acceptable_count": "Alternation Triplets (#)",
    "triplets_unacceptable_count": "Non-alternation Triplets (#)",
    "frames_detected": "Frames Detected",
    "total_frames": "Total Frames",
    "detection_rate_pct": "Detection Rate (%)",
    "interpolated_frames": "Interpolated Frames",
    "hand_fixed_frames": "Hand-fixed Frames",
    "removed_frames": "Removed Frames",
    "corrected_frames_pct": "Corrected Frames (%)",
    "tortuosity": "Tortuosity",
    "unit": "Length Unit",
    "pause_count": "Pause Count (#)",
    "entries_open_total": "Entries into Open Arms (#)",
    "entries_closed_total": "Entries into Closed Arms (#)",
    "entries_center": "Entries into Center (#)",
    "entries_neutral_zone": "Entries into Neutral Zone (#)",
    "pct_time_open_of_arms": "% Arm Time in Open Arms",
    "pct_time_closed_of_arms": "% Arm Time in Closed Arms",
    "pct_time_center": "% Time in Center",
    "pct_entries_open": "% Open-Arm Entries",
    "pct_entries_closed": "% Closed-Arm Entries",
    "angle_enabled": "Nose-Angle Filter",
    "angle_max_deg": "Max Nose Angle (°)",
    "arena_entries": "Arena Entries (#)",
    "discrimination_index": "Discrimination Index",
    "preference_pct_novel": "% Preference for Novel Object",
    "preference_pct_moved": "% Preference for Moved Object",
}

# time measures: stem -> label; the unit ('s' / 'min') is added in '(…)'
_TIME = {
    "duration": "Duration",
    "mobility_time": "Mobility Time",
    "immobility_time": "Immobility Time",
    "min_dwell": "Min Dwell",
    "latency_first_entry": "Latency to First Arm Entry",
    "latency_first_open_entry": "Latency to First Open-Arm Entry",
    "pause_total": "Total Time in Pauses",
    "pause_mean": "Mean Pause",
    "pause_longest": "Longest Pause",
    "time_open_total": "Time in Open Arms",
    "time_closed_total": "Time in Closed Arms",
    "time_center": "Time in Center",
    "time_neutral_zone": "Time in Neutral Zone",
    "arena_total_time": "Time in Arena",
    "bin_start": "Bin Start",
    "bin_end": "Bin End",
    "familiar_time": "Time at Familiar Object",
    "novel_time": "Time at Novel Object",
}

_SPEED = {"mean": "Average", "max": "Max", "median": "Median", "p90": "P90", "p99": "P99"}

# snake unit spelling -> unit text
_UNITS = {"cm": "cm", "mm": "mm", "m": "m", "px": "px",
          "cm_per_s": "cm/s", "mm_per_s": "mm/s", "m_per_s": "m/s",
          "m_per_min": "m/min", "km_per_h": "km/h", "px_per_s": "px/s"}

_OBJECT = {  # object_<x>_<field>
    "name": "Object {X} Name", "role": "Object {X} Role",
    "entries": "Approaches to Object {X} (#)",
    "bouts_count": "Exploration Bouts at Object {X} (#)",
}
_OBJECT_TIME = {
    "total_time": "Exploration of Object {X}",
    "latency_first": "Latency to Object {X}",
    "mean_bout": "Mean Bout at Object {X}",
    "longest_bout": "Longest Bout at Object {X}",
}


def _area(token):
    """'arm_a' -> 'Arm A', 'object_b' -> 'Object B', 'center_zone' -> 'Center Zone'."""
    parts = token.split("_")
    if len(parts) == 2 and len(parts[1]) == 1:
        return f"{parts[0].capitalize()} {parts[1].upper()}"
    return " ".join(p.capitalize() for p in parts)


def readable(key, base_len="cm"):
    """Readable Excel name for a snake_case measure; other names unchanged.
    `base_len` ('cm' / 'px') names the unit of bare 'total_distance' /
    'mean_speed' columns."""
    k = str(key)
    if not k or k != k.lower() or " " in k or "(" in k:
        return key
    if k in _PLAIN:
        return _PLAIN[k]
    m = re.fullmatch(r"(.+)_(s|min)", k)
    if m and m.group(1) in _TIME:
        return f"{_TIME[m.group(1)]} ({m.group(2)})"
    # distance / speed, bare (unit from the calibration) or with a unit
    m = re.fullmatch(r"(total_distance|distance)(?:_(cm|mm|m|px))?", k)
    if m:
        name = "Total Distance" if m.group(1) == "total_distance" else "Distance"
        return f"{name} ({m.group(2) or base_len})"
    m = re.fullmatch(r"(mean|max|median|p90|p99)_speed(?:_(\w+))?", k)
    if m and (m.group(2) is None or m.group(2) in _UNITS):
        unit = _UNITS[m.group(2)] if m.group(2) else f"{base_len}/s"
        return f"{_SPEED[m.group(1)]} Speed ({unit})"
    # per arm / zone (Y-Maze arms a-c, EPM arms n/s/e/w, bins)
    m = re.fullmatch(r"(entries|pct_entries|pct_time|kind|name)_(arm_[a-z0-9]+|[a-z]+_zone)", k)
    if m:
        area = _area(m.group(2))
        return {"entries": f"Entries into {area} (#)",
                "pct_entries": f"% Entries into {area}",
                "pct_time": f"% Time in {area}",
                "kind": f"{area} Type",
                "name": f"{area} Name"}[m.group(1)]
    m = re.fullmatch(r"(time|mean_dwell)_(arm_[a-z0-9]+|object_[a-z0-9]+|[a-z]+_zone)_(s|min)", k)
    if m:
        what = "Time in" if m.group(1) == "time" else "Mean Visit in"
        if m.group(2).startswith("object_"):
            what = "Time at" if m.group(1) == "time" else "Mean Visit at"
        return f"{what} {_area(m.group(2))} ({m.group(3)})"
    # objects (NOR / Object Location)
    m = re.fullmatch(r"object_([a-z0-9])_(.+)", k)
    if m:
        x, field = m.group(1).upper(), m.group(2)
        if field in _OBJECT:
            return _OBJECT[field].format(X=x)
        t = re.fullmatch(r"(.+)_(s|min)", field)
        if t and t.group(1) in _OBJECT_TIME:
            return f"{_OBJECT_TIME[t.group(1)].format(X=x)} ({t.group(2)})"
    # anything else: words capitalised, a trailing unit moved into '(…)'
    for suffix, unit in (("_pct", "%"), ("_s", "s"), ("_min", "min"), ("_deg", "°")):
        if k.endswith(suffix) and len(k) > len(suffix):
            return f"{k[:-len(suffix)].replace('_', ' ').capitalize()} ({unit})"
    return k.replace("_", " ").capitalize()


def readable_metrics(metrics):
    """Copy of `metrics` with readable names, order kept."""
    if not metrics:
        return metrics
    base = metrics.get("unit") if isinstance(metrics.get("unit"), str) else "cm"
    out = {}
    for k, v in metrics.items():
        name = readable(k, base or "cm")
        out[name if name not in out else k] = v
    return out


def readable_schema(schema, base_len="cm"):
    """[(section, [columns])] with readable column names."""
    if not schema:
        return schema
    return [(sec, [readable(c, base_len) for c in cols]) for sec, cols in schema]


def readable_columns(df, base_len="cm"):
    """DataFrame (Time Bins …) with readable column names."""
    if df is None or getattr(df, "empty", True):
        return df
    return df.rename(columns={c: readable(c, base_len) for c in df.columns})
