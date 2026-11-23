"""Custom experiment — the user designs the test.

Built on the box-family engine (experiments.box): the arena is the usual
4-corner outline, every zone is described in box space (u, v) ∈ [0, 1]²,
and time / entries / latency / mean visit come from the same tested
pipeline (shared min-dwell rule) as the built-in box tests. What the user
adds:

  zones     circle · square · rectangle · polygon (area zones) and line
            (crossing lines). Area zones are measured independently (each
            has its own layer), so zones may overlap or nest.
  measures  which results to report (checkboxes).

A design (zones + measures) is a plain dict, saved with each video and
exportable as a .json file so a lab can reuse one protocol.
"""
import json

import numpy as np

from core.kinematics import time_at
from experiments.box.base import BoxExperiment
from experiments.box.engine import OUT, ZoneDef, committed_sequence
from experiments.box import geometry as geo

SHAPES = ("circle", "square", "rectangle", "polygon", "line")
SHAPE_LABELS = {"circle": "Circle", "square": "Square", "rectangle": "Rectangle",
                "polygon": "Polygon", "line": "Line"}
PALETTE = ("#E8A87C", "#7FA6D9", "#8FC79A", "#D98FB5", "#E4D3AE",
           "#9FD3D6", "#C3A6E8", "#E88C8C")

# (key, label, default on, tooltip). Area-zone measures are per zone.
MEASURES = (
    ("time",       "Time",           True,  "Time spent in each zone (s)"),
    ("pct",        "% of session",   True,  "Time in each zone as % of the session"),
    ("entries",    "Entries",        True,  "Number of entries into each zone"),
    ("latency",    "Latency",        True,  "Time until the first entry into each zone (s)"),
    ("visit",      "Mean visit",     False, "Average length of one visit to each zone (s)"),
    ("distance",   "Distance",       False, "Distance moved while inside each zone"),
    ("speed",      "Speed",          False, "Mean speed while inside each zone"),
    ("sequence",   "Sequence",       True,  "Order in which the zones were entered, and the number of zone changes"),
    ("crossings",  "Line crossings", True,  "How often each line was crossed, and when first"),
    ("locomotion", "Locomotion",     True,  "Total distance, speeds, mobility and pauses for the whole session"),
)

DESIGN_VERSION = 1


def default_zone(shape, n, existing_names=()):
    """A new zone of `shape`, centred in the arena (n = running number)."""
    base = SHAPE_LABELS[shape]
    name = f"{base} {n}"
    while name in existing_names:
        n += 1
        name = f"{base} {n}"
    z = {"id": f"z{n}_{shape}", "name": name, "shape": shape, "point": "body",
         "color": PALETTE[(n - 1) % len(PALETTE)],
         "x": 50.0, "y": 50.0, "w": 10.0, "h": 10.0}
    if shape == "rectangle":
        z["w"], z["h"] = 15.0, 8.0
    if shape == "line":
        z.update({"x": 50.0, "y": 20.0, "x2": 50.0, "y2": 80.0})
    if shape == "polygon":
        z["pts"] = [list(p) for p in geo.regular_polygon(0.5, 0.5, 0.15, 6, 90)]
    return z


def zone_poly(z, dims):
    """Box-space outline of an area zone. A zone drawn on the video keeps
    the exact outline that was drawn ("pts"). Otherwise (typed / older
    designs) it is built from centre % and size in cm; dims = (W, H) cm of
    the arena, so circles and squares stay physically round / square."""
    pts = z.get("pts")
    if pts and len(pts) >= 3:
        return [tuple(p) for p in pts]
    W, H = (float(dims[0]) or 1.0), (float(dims[1]) or 1.0)
    cu, cv = float(z.get("x", 50)) / 100.0, float(z.get("y", 50)) / 100.0
    shape = z.get("shape")
    if shape == "circle":
        r = float(z.get("w", 10)) / 2.0
        return geo.ellipse(cu, cv, r / W, r / H)
    if shape == "square":
        s = float(z.get("w", 10)) / 2.0
        return geo.rect(cu - s / W, cv - s / H, cu + s / W, cv + s / H)
    if shape == "rectangle":
        hw, hh = float(z.get("w", 15)) / 2.0, float(z.get("h", 8)) / 2.0
        return geo.rect(cu - hw / W, cv - hh / H, cu + hw / W, cv + hh / H)
    if shape == "polygon":
        return [tuple(p) for p in (z.get("pts") or [])]
    return []


def line_pts(z):
    return [(float(z.get("x", 50)) / 100.0, float(z.get("y", 20)) / 100.0),
            (float(z.get("x2", 50)) / 100.0, float(z.get("y2", 80)) / 100.0)]


def crossings(u, v, a, b):
    """Frames (indices) where the path crosses segment a→b. Undetected
    frames are bridged: each step runs from the last detected point."""
    def side(px, py):
        return (b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0])

    hits = []
    last = None            # last point clearly on one side (points on the line wait)
    for i in range(len(u)):
        if np.isnan(u[i]) or np.isnan(v[i]):
            continue
        s2 = side(u[i], v[i])
        if s2 == 0:
            continue
        if last is not None:
            p, q = (u[last], v[last]), (u[i], v[i])
            if side(*p) * s2 < 0:
                # the move must also pass between the line's two ends
                def side2(px, py):
                    return (q[0] - p[0]) * (py - p[1]) - (q[1] - p[1]) * (px - p[0])
                if side2(*a) * side2(*b) <= 0:
                    hits.append(i)
        last = i
    return hits


def _unique_labels(zones):
    seen = {}
    out = []
    for z in zones:
        base = (str(z.get("name") or "").strip() or SHAPE_LABELS.get(z.get("shape"), "Zone"))
        k = seen.get(base, 0)
        seen[base] = k + 1
        out.append(base if k == 0 else f"{base} ({k + 1})")
    return out


def check_design(design):
    """Validate a loaded design dict; returns (zones, measures) or raises
    ValueError with a readable message."""
    if not isinstance(design, dict) or not isinstance(design.get("zones"), list):
        raise ValueError("Not a WIMM custom-experiment design file.")
    zones = []
    for z in design["zones"]:
        if not isinstance(z, dict) or z.get("shape") not in SHAPES:
            raise ValueError("A zone in the file has an unknown shape.")
        if z["shape"] == "polygon":
            pts = z.get("pts")
            if not (isinstance(pts, list) and len(pts) >= 3
                    and all(isinstance(p, (list, tuple)) and len(p) == 2 for p in pts)):
                raise ValueError(f"Polygon '{z.get('name')}' needs at least 3 corners.")
        zones.append(dict(z))
    known = {k for k, _l, _d, _t in MEASURES}
    measures = [m for m in (design.get("measures") or []) if m in known]
    return zones, measures


class CustomExperiment(BoxExperiment):
    key = "custom"
    name = "Custom Experiment"
    results_title = "Custom"
    arena_hint = ("Click the 4 corners of the apparatus, then add zones "
                  "and lines below.")
    scale = ("rect", 40.0, 40.0)
    PARAMS = []
    locked = False            # True: a saved experiment in use (design fixed)

    @property
    def report_title(self):
        """Excel title: the experiment's own name."""
        return self.name

    @property
    def file_key(self):
        """Backup file suffix — one file per saved experiment and video."""
        import re
        if self.name == CustomExperiment.name:
            return self.key
        return "custom_" + (re.sub(r"[^A-Za-z0-9]+", "_", self.name).strip("_")[:40] or "x")

    # ── design ────────────────────────────────────────────────────────
    def defaults(self):
        return {"zones": [],
                "measures": [k for k, _l, on, _t in MEASURES if on]}

    def params_of(self, host_or_settings):
        p = super().params_of(host_or_settings)
        p["zones"] = [dict(z) for z in (p.get("zones") or [])]
        p["measures"] = list(p.get("measures") or [])
        return p

    def design_of(self, host):
        p = self.params_of(host)
        return {"wimm_custom_design": DESIGN_VERSION,
                "zones": p["zones"], "measures": p["measures"]}

    @staticmethod
    def save_design(path, design):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(design, f, indent=2)

    @staticmethod
    def load_design(path):
        with open(path, encoding="utf-8") as f:
            return check_design(json.load(f))

    def _labelled(self, p):
        zones = p["zones"]
        return list(zip(zones, _unique_labels(zones)))

    def zones(self, p, dims, colors):
        """Area zones only — what the engine measures. Each zone is its own
        layer, so zones are measured independently (overlap allowed)."""
        out = []
        for z, label in self._labelled(p):
            if z.get("shape") == "line":
                continue
            poly = zone_poly(z, dims)
            if len(poly) < 3:
                continue
            test = None
            if z.get("shape") == "circle" and not z.get("pts"):
                W, H = (dims[0] or 1.0), (dims[1] or 1.0)
                cu, cv = float(z.get("x", 50)) / 100.0, float(z.get("y", 50)) / 100.0
                r = float(z.get("w", 10)) / 2.0
                # exact ellipse test (the outline is only for drawing)
                test = (lambda u, v, cu=cu, cv=cv, ru=r / W, rv=r / H:
                        ((np.asarray(u, float) - cu) / ru) ** 2
                        + ((np.asarray(v, float) - cv) / rv) ** 2 <= 1.0)
            out.append(ZoneDef(z["id"], label, poly, layer=label,
                               point=z.get("point", "body"), color=z.get("color", "#A9B4C6"),
                               test=test,
                               editable=z.get("shape") == "polygon" and not self.locked,
                               movable=True))
        return out

    def line_defs(self, p):
        return [(z, label) for z, label in self._labelled(p) if z.get("shape") == "line"]

    def _sync_dragged(self, host):
        """Zones moved / reshaped by dragging on the video → the design.
        Returns True when something changed."""
        zd = getattr(host, "zone_drawer", None)
        params = getattr(host, "_box_params", None)
        if zd is None or not zd.arena or not isinstance(params, dict):
            return False
        # Only after a real drag — otherwise a typed change would be undone
        # by the (not yet redrawn) old geometry on the video.
        if not getattr(zd, "geometry_dragged", False):
            return False
        if zd._moving_zone is None and zd._dragging_extra is None:
            zd.geometry_dragged = False          # drag finished: this is its last sync
        H = geo.box_homography(zd.arena)
        if H is None:
            return False
        from experiments.box.ui import ZONE_PREFIX
        changed = False

        def pct(a):
            return round(min(100.0, max(0.0, float(a) * 100.0)), 2)

        for z in params.get("zones") or []:
            geom = (zd.get_zone(ZONE_PREFIX + z["id"]) or {}).get("geometry") or []
            if not geom:
                continue
            u, v = geo.to_box(H, [p[0] for p in geom], [p[1] for p in geom])
            shape = z.get("shape")
            if z.get("pts"):                      # drawn outline: moves as drawn
                if len(geom) != len(z.get("pts") or []):
                    continue
                new = {"pts": [[round(float(a), 5), round(float(b), 5)] for a, b in zip(u, v)]}
            elif shape == "line":
                if len(geom) != 2:
                    continue
                new = {"x": pct(u[0]), "y": pct(v[0]), "x2": pct(u[1]), "y2": pct(v[1])}
            else:
                # outline moved as a whole: its centre is the vertex mean
                new = {"x": pct(np.mean(u)), "y": pct(np.mean(v))}
            old = {k: z.get(k) for k in new}
            if "pts" in new:
                old = {"pts": [[round(a, 5), round(b, 5)] for a, b in z.get("pts") or []]}
            if any(abs(np.subtract(np.array(new[k], float), np.array(old[k] or 0, float))).max() > 0.02
                   if k != "pts" else new[k] != old[k] for k in new):
                z.update(new)
                changed = True
        if changed:
            host._cx_dragged = True       # the designer refreshes its fields on release
        return changed

    def zone_defs_for_host(self, host):
        """Area zones plus lines (drawn on the video, never 'entered')."""
        self._sync_dragged(host)
        p = self.params_of(host)
        defs = self.zones(p, self.dims_of(host), self.colors_of(host))
        for z, label in self.line_defs(p):
            defs.append(ZoneDef(z["id"], label, line_pts(z), layer="__line__" + label,
                                color=z.get("color", "#E88C8C"),
                                test=lambda u, v: np.zeros(np.shape(u), bool),
                                fill_alpha=0, editable=not self.locked, movable=True))
        return defs

    def default_enable_nose(self):
        return False

    def zones_summary(self, p):
        n_area = sum(1 for z in p["zones"] if z.get("shape") != "line")
        n_line = sum(1 for z in p["zones"] if z.get("shape") == "line")
        parts = [f"{n_area} zone{'s' if n_area != 1 else ''}"]
        if n_line:
            parts.append(f"{n_line} line{'s' if n_line != 1 else ''}")
        return " · ".join(parts)

    # ── metrics ───────────────────────────────────────────────────────
    _PER_ZONE = (("time", "Time in {} (s)"), ("pct", "% Time in {}"),
                 ("entries", "Entries into {} (#)"), ("latency", "Latency to {} (s)"),
                 ("visit", "Mean Visit in {} (s)"))

    def _zone_keys(self, label, measures, unit="cm"):
        keys = [fmt.format(label) for m, fmt in self._PER_ZONE if m in measures]
        if "distance" in measures:
            keys.append(f"Distance in {label} ({unit})")
        if "speed" in measures:
            keys.append(f"Mean Speed in {label} ({unit}/s)")
        return keys

    def main_keys(self, p):
        keys = []
        ms = set(p["measures"])
        if "sequence" in ms:
            keys += ["Zone Sequence", "Zone Transitions (#)"]
        if "crossings" in ms:
            for _z, label in self.line_defs(p):
                keys += [f"Crossings of {label} (#)", f"First Crossing of {label} (s)"]
        return keys

    def zone_metric_keys(self, p):
        ms = set(p["measures"])
        keys = []
        for z, label in self._labelled(p):
            if z.get("shape") != "line":
                keys += self._zone_keys(label, ms)
        return keys

    def primary(self, ctx, m, p, dims):
        out = {}
        ms = set(p["measures"])
        df, unit, stats = ctx["df"], ctx["unit"], ctx["stats"]
        area = [label for z, label in self._labelled(p) if z.get("shape") != "line"]

        if ms & {"distance", "speed"} and "step_dist" in df.columns:
            step = df["step_dist"].to_numpy(dtype=float)
            for label in area:
                st = stats.get(label)
                if st is None:
                    continue
                inside = np.array([s not in (None, OUT) for s in st.seq], bool)
                # A step counts when it starts and ends inside: the step
                # that brings the animal into the zone is not "in" it.
                both = inside & np.concatenate(([False], inside[:-1]))
                d = float(np.nansum(step[both])) if len(inside) == len(step) else 0.0
                t = float(m.get(f"Time in {label} (s)", 0.0) or 0.0)
                out[f"Distance in {label} ({unit})"] = round(d, 3)
                out[f"Mean Speed in {label} ({unit}/s)"] = round(d / t, 3) if t > 0 else 0.0

        if "sequence" in ms:
            # Entries into any zone, in time order (a zone re-entered
            # straight after leaving to the open floor counts again).
            visits = []
            for label in area:
                st = stats.get(label)
                if st is None:
                    continue
                visits += [(s, label) for zname, s, _e in st.visits if zname != OUT]
            visits.sort()
            seq = [label for _s, label in visits]
            out["Zone Sequence"] = " → ".join(seq) if seq else ""
            out["Zone Transitions (#)"] = sum(
                1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])

        if "crossings" in ms:
            bu, bv = ctx["body_uv"]
            for z, label in self.line_defs(p):
                a, b = line_pts(z)
                hits = crossings(np.asarray(bu, float), np.asarray(bv, float), a, b)
                out[f"Crossings of {label} (#)"] = len(hits)
                out[f"First Crossing of {label} (s)"] = (
                    round(time_at(df, hits[0], ctx["fps"]) + ctx["trim_start"], 3)
                    if hits else "never")
        return out

    _LOCO = ("Total Distance", "Average Speed", "Max Speed", "Median Speed",
             "P90 Speed", "P99 Speed", "Mobility Time", "Immobility Time",
             "Mean Speed When Mobile", "Movement Threshold", "Tortuosity",
             "Pause Count", "Total Time in Pauses")

    def compute_metrics(self, results, settings, fps, px_per_cm):
        """Shared pipeline, then keep only what the user ticked."""
        metrics, raw_df, bin_df = super().compute_metrics(results, settings, fps, px_per_cm)
        p = self.params_of(settings)
        ms = set(p["measures"])
        unit = metrics.get("unit", "cm")
        keep = set(self.main_keys(p))
        for z, label in self._labelled(p):
            if z.get("shape") != "line":
                keep.update(self._zone_keys(label, ms, unit))
        out = {}
        for k, v in metrics.items():
            per_zone = k.startswith(("Time in ", "% Time in ", "Entries into ", "Latency to ",
                                     "Mean Visit in ", "Distance in ", "Mean Speed in ",
                                     "Zone ", "Crossings of ", "First Crossing of "))
            loco = k.startswith(self._LOCO)
            if per_zone and k not in keep:
                continue
            if loco and "locomotion" not in ms:
                continue
            out[k] = v
        return out, raw_df, bin_df

    def populate_results_tab(self, host, metrics):
        """Results table: chosen main results, then the per-zone numbers."""
        from PyQt5.QtWidgets import QTableWidgetItem
        t = getattr(host, "_box_table", None)
        if t is None or not metrics:
            return
        p = self.params_of(host)
        unit = metrics.get("unit", "cm")
        keys = list(self.main_keys(p))
        for z, label in self._labelled(p):
            if z.get("shape") != "line":
                keys += self._zone_keys(label, set(p["measures"]), unit)
        rows = [(k, metrics.get(k)) for k in keys if k in metrics]
        t.setRowCount(len(rows))
        for r, (k, val) in enumerate(rows):
            t.setItem(r, 0, QTableWidgetItem(str(k)))
            t.setItem(r, 1, QTableWidgetItem("" if val is None else str(val)))

    # ── graphs ────────────────────────────────────────────────────────
    def zone_bar_data(self, host):
        m = getattr(host, "metrics", None) or {}
        zones = self.zones(self.params_of(host), self.dims_of(host), {})
        if not zones:
            return None
        return ([z.label for z in zones],
                [float(m.get(f"Time in {z.label} (s)", 0.0) or 0.0) for z in zones],
                [z.color for z in zones], lambda v: f"{v:.1f}s",
                "Time per Zone", "Time (s)")

    def decorate_graph(self, host, graph_name, ax, arena_px):
        handles = super().decorate_graph(host, graph_name, ax, arena_px) or []
        if graph_name not in ("Trajectory", "Heatmap") or not arena_px:
            return handles or None
        H = geo.box_homography(arena_px)
        if H is None:
            return handles or None
        from matplotlib.lines import Line2D
        for z, label in self.line_defs(self.params_of(host)):
            (x0, y0), (x1, y1) = geo.from_box(H, line_pts(z))
            color = z.get("color", "#E88C8C")
            ax.plot([x0, x1], [y0, y1], color=color, linewidth=1.8, zorder=5)
            handles.append(Line2D([], [], color=color, lw=2, label=label))
        return handles or None

    def apply_extras(self, host, extras):
        super().apply_extras(host, extras)
        from . import ui
        ui.refresh_designer(host, self)

    def build_geometry_step(self, host):
        from experiments.box import ui as box_ui
        from . import ui
        grp = box_ui.build_geometry_step(host, self)
        ui.build_designer(host, self)
        return grp

