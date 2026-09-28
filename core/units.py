"""Unit scales for distance / speed / time values.

Metrics are always computed in cm, cm/s and s. This module knows how to
recognise such a value from its name and re-express it in other scales:

  - the Output panel uses it to DISPLAY one chosen scale per dimension;
  - the Excel export uses it to write EVERY scale side by side
    ('Average Speed (cm/s)', 'Average Speed (mm/s)', … '(km/h)').

Recognised names:
    'Total Distance (cm)'        → distance      'X (mm)', 'X (m)'
    'Average Speed (cm/s)'       → speed         'X (mm/s)', … 'X (km/h)'
    'Habituation Slope (cm/min)' → distance/min  'X (mm/min)', 'X (m/min)'
    'Duration (s)'               → time          'X (min)'
    snake_case plugin keys (Y-Maze / NOR / EPM):
    'total_distance', 'distance_cm'           → '_mm', '_m'
    'mean_speed', 'mean_speed_cm_per_s', '_cmps' → '_mm_per_s', … '_km_per_h'
    'latency_first_entry_s'                   → '_min'

Uncalibrated runs (px) are never converted — there is no real-world scale.
"""
import math

import pandas as pd

# factor = number of target units in one base unit (cm, cm/s, s)
DISTANCE_UNITS = {"mm": 10.0, "cm": 1.0, "m": 0.01}
SPEED_UNITS = {"mm/s": 10.0, "cm/s": 1.0, "m/s": 0.01,
               "m/min": 0.6, "km/h": 0.036}
TIME_UNITS = {"s": 1.0, "min": 1.0 / 60.0}

DEFAULT_UNITS = {"distance": "cm", "speed": "cm/s", "time": "s"}
_TABLES = {"distance": DISTANCE_UNITS, "speed": SPEED_UNITS, "time": TIME_UNITS}

# snake_case spelling of each unit
_SNAKE = {"mm": "mm", "cm": "cm", "m": "m",
          "mm/s": "mm_per_s", "cm/s": "cm_per_s", "m/s": "m_per_s",
          "m/min": "m_per_min", "km/h": "km_per_h",
          "s": "s", "min": "min"}

# snake_case keys ending in '_s' that mean the SOUTH arm (EPM), not seconds
_NOT_SECONDS_PREFIXES = ("pct_", "entries_", "kind_", "name_")


def normalize(units):
    """Fill missing / invalid entries of a {'distance','speed','time'}
    choice with the defaults."""
    out = dict(DEFAULT_UNITS)
    if isinstance(units, dict):
        for dim, table in _TABLES.items():
            if units.get(dim) in table:
                out[dim] = units[dim]
    return out


def base_length_unit(metrics):
    """'cm' if the run is calibrated, 'px' otherwise."""
    metrics = metrics or {}
    u = metrics.get("unit")
    if isinstance(u, str) and u:
        return u
    for k in metrics:
        if "(px" in str(k):
            return "px"
    return "cm"


class _Kind:
    """How a name carries its unit: dimension + a function that rebuilds
    the name for another unit. `label` is the name without its unit (used
    by the Output panel's label column)."""

    def __init__(self, dim, label, build, suffix="", bare=False):
        self.dim = dim
        self.label = label
        self.build = build
        self.suffix = suffix      # '/min' for 'cm/min' rates
        # name carries no unit ('total_distance') — in the all-scales
        # export its base column is renamed 'total_distance_cm' so the cm
        # column is as recognisable as the mm / m ones next to it.
        self.bare = bare

    def base_name(self, key):
        return self.build(DEFAULT_UNITS[self.dim]) if self.bare else key

    def unit_text(self, unit):
        return unit + self.suffix


def _paren(key):
    k = str(key)
    if not (k.endswith(")") and "(" in k):
        return None
    i = k.rfind("(")
    label, unit = k[:i].strip(), k[i + 1:-1]
    build = lambda u, s="": f"{label} ({u}{s})"
    if unit in DISTANCE_UNITS:
        if unit != "cm":
            return None
        return _Kind("distance", label, build)
    if unit == "s":
        return _Kind("time", label, build)
    if "/" in unit:
        num, den = unit.split("/", 1)
        if num == "cm" and den == "s":
            return _Kind("speed", label, build)
        if num == "cm" and den and den[0].isalpha():
            return _Kind("distance", label,
                         lambda u, d=den: f"{label} ({u}/{d})", "/" + den)
    return None


def _snake(key, base_len):
    k = str(key)
    if not k or " " in k or "(" in k or k != k.lower():
        return None
    # time: '..._s'
    if k.endswith("_s") and len(k) > 2:
        if k.startswith(_NOT_SECONDS_PREFIXES) or k == "arm_s":
            return None
        stem = k[:-2]
        return _Kind("time", stem, lambda u: f"{stem}_{_SNAKE[u]}")
    # speed with explicit cm unit
    for tail in ("_cm_per_s", "_cmps"):
        if k.endswith(tail) and "speed" in k:
            stem = k[:-len(tail)]
            return _Kind("speed", stem, lambda u: f"{stem}_{_SNAKE[u]}")
    # distance with explicit cm unit
    if k.endswith("_cm") and "distance" in k:
        stem = k[:-3]
        return _Kind("distance", stem, lambda u: f"{stem}_{_SNAKE[u]}")
    # bare names — unit comes from the run's calibration
    if base_len != "cm":
        return None
    if k == "total_distance":
        return _Kind("distance", k, lambda u: f"{k}_{_SNAKE[u]}", bare=True)
    if k.endswith("speed"):
        return _Kind("speed", k, lambda u: f"{k}_{_SNAKE[u]}", bare=True)
    return None


def classify(key, base_len="cm"):
    """_Kind for a convertible name, or None."""
    return _paren(key) or _snake(key, base_len)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(float(v)))


def _round(v):
    """Trim float noise (0.30409200000000003) — 6 significant digits."""
    return float(f"{v:.6g}")


def variants(key, base_len="cm"):
    """[(name, factor)] for every scale of `key`, the base scale (factor
    1) first — named `key` itself unless `key` has no unit in its name
    ('total_distance' → 'total_distance_cm'). [] if not convertible."""
    kind = classify(key, base_len)
    if kind is None:
        return []
    base = DEFAULT_UNITS[kind.dim]
    out = [(kind.base_name(key), 1.0)]
    for u, f in _TABLES[kind.dim].items():
        if u != base:
            out.append((kind.build(u), f))
    return out


def scales(key, base_len="cm"):
    """(label, [(name, unit_text)]) — the name without its unit, then
    every scale of `key` (original first). Non-convertible names give a
    single entry with whatever unit their '(…)' suffix carries."""
    kind = classify(key, base_len)
    if kind is None:
        k = str(key)
        if k.endswith(")") and "(" in k:
            i = k.rfind("(")
            return k[:i].strip(), [(key, k[i + 1:-1])]
        return k, [(key, "")]
    base = DEFAULT_UNITS[kind.dim]
    out = [(kind.base_name(key), kind.unit_text(base))]
    for u in _TABLES[kind.dim]:
        if u != base:
            out.append((kind.build(u), kind.unit_text(u)))
    return kind.label, out


# ── Output panel (one chosen scale) ─────────────────────────────────────

def _fmt(v):
    """~4 significant digits, never scientific notation."""
    if v == 0:
        return "0"
    d = 3 - int(math.floor(math.log10(abs(v))))
    d = max(0, min(d, 6))
    s = f"{v:.{d}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def display_row(key, value, units, base_len="cm"):
    """(label, value_text, unit) for one Summary row in the chosen units,
    or None if the row isn't convertible (caller shows it as is)."""
    kind = classify(key, base_len)
    if kind is None:
        return None
    target = normalize(units)[kind.dim]
    factor = _TABLES[kind.dim][target]
    text = "" if value is None else str(value)
    if factor != 1.0 and _is_number(value):
        text = _fmt(float(value) * factor)
    return kind.label, text, kind.unit_text(target)


def display_column(col, units, base_len="cm"):
    """(factor, header) for a Raw data column in the chosen units."""
    kind = classify(col, base_len)
    if kind is None:
        return 1.0, str(col)
    target = normalize(units)[kind.dim]
    if target == DEFAULT_UNITS[kind.dim]:
        return 1.0, str(col)
    return _TABLES[kind.dim][target], kind.build(target)


# ── Excel export (every scale) ──────────────────────────────────────────

def expand_metrics(metrics, base_len=None):
    """Copy of `metrics` where each distance / speed / time entry is
    followed by the same value in every other scale. Non-numeric values
    ('n/a', 'never') are copied to every scale unchanged."""
    if not metrics:
        return metrics
    if base_len is None:
        base_len = base_length_unit(metrics)
    out = {}
    for k, v in metrics.items():
        vs = variants(k, base_len)
        if not vs:
            out[k] = v
            continue
        for name, f in vs:
            if name == k:
                out[k] = v
            elif name not in metrics:
                out[name] = _round(float(v) * f) if _is_number(v) else v
    return out


def expand_schema(schema, base_len="cm"):
    """Same as expand_metrics but for a [(section, [columns])] layout."""
    if not schema:
        return schema
    out = []
    for section, cols in schema:
        new_cols = []
        for c in cols:
            vs = variants(c, base_len) or [(c, 1.0)]
            for name, _f in vs:
                if name == c or (name not in cols and name not in new_cols):
                    new_cols.append(name)
        out.append((section, new_cols))
    return out


def expand_df(df, base_len="cm"):
    """Copy of `df` with every distance / speed / time column followed by
    its other-scale columns."""
    if df is None or getattr(df, "empty", True):
        return df
    cols = {}
    for c in df.columns:
        vs = variants(c, base_len)
        if not vs:
            cols[c] = df[c]
            continue
        for name, f in vs:
            if name == c:
                cols[c] = df[c]
                continue
            if name in df.columns:
                continue
            s = pd.to_numeric(df[c], errors="coerce")
            if s.notna().sum() < df[c].notna().sum():
                cols[name] = df[c]          # not purely numeric — copy
            else:
                cols[name] = (s * f).map(
                    lambda v: v if pd.isna(v) else _round(v))
    return pd.DataFrame(cols, index=df.index)
