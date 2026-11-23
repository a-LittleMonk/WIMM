"""BoxExperiment — shared plugin for every box-family test.

A concrete test (place preference, light–dark, zero maze, …) only
declares:
  PARAMS        its Zones-card settings (ParamSpec list)
  zones()       its zones in box space for given settings
  main_keys()   names of its main results, in display order
  primary()     how those main results follow from the per-zone numbers
and a few labels. Everything else — Arena / Zones cards, live overlay,
per-video save / restore, metrics pipeline, Summary order, results table,
zone-time chart, graph decoration, Excel schema — is shared here, so all
box tests look and behave the same.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from experiments.base import Experiment
from . import engine
from . import geometry as geo


@dataclass
class ParamSpec:
    key: str
    label: str
    kind: str                 # pct | choice | cm | deg | toggle | multi
    default: Any
    options: Optional[list] = None      # choice: [(value, label)]; multi: n
    lo: float = 0.0
    hi: float = 100.0
    tip: str = ""
    show_if: Optional[Callable] = None  # f(params) -> bool
    # Per-animal assignment (counterbalanced: paired side, stranger side,
    # platform quadrant, baited arms…). Kept with each video in a batch
    # instead of being copied from the settings video.
    per_video: bool = False


_LOCOMOTION_ORDER = (
    "Duration (s)", "Total Frames", "Frames Detected", "Detection Rate (%)",
    "Total Distance (cm)", "Total Distance (px)",
    "Average Speed (cm/s)", "Average Speed (px/s)",
    "Max Speed (cm/s)", "Max Speed (px/s)",
    "Mobility Time (s)", "Immobility Time (s)",
    "Pause Count (#)", "Total Time in Pauses (s)", "Min Dwell (s)",
)


class BoxExperiment(Experiment):
    family = "box"
    name = "Box"
    key = "box"
    results_title = "Results"          # Output tab title
    arena_hint = "Click the 4 corners of the apparatus."
    # Scale card: ("rect", W, H) — width × height; ("square", side, label)
    scale = ("rect", 60.0, 40.0)
    uses_nose = False
    PARAMS: List[ParamSpec] = []
    # True: every zone gets corner handles on the video; dragged outlines
    # are kept per zone in params["zone_edits"] (box space) and cleared when
    # a setting that rebuilds the layout changes.
    EDITABLE_ZONES = False
    # Zone colours: key -> (label, default hex). Zones pick a colour key.
    COLORS = {}

    # ── to override ───────────────────────────────────────────────────
    def zones(self, p, dims, colors):
        """List[engine.ZoneDef] for settings `p`, cage dims (W, H) cm and
        colour map."""
        return []

    def main_keys(self, p):
        return []

    def primary(self, ctx, metrics, p, dims):
        return {}

    def zones_summary(self, p):
        return None

    # ── helpers ───────────────────────────────────────────────────────
    def defaults(self):
        d = {s.key: s.default for s in self.PARAMS}
        if self.EDITABLE_ZONES:
            d["zone_edits"] = {}
        return d

    def all_zones(self, p, dims, colors):
        """self.zones() with the user's hand-adjusted outlines applied."""
        zs = self.zones(p, dims, colors)
        if not self.EDITABLE_ZONES:
            return zs
        edits = p.get("zone_edits") or {}
        for z in zs:
            z.editable = True
            e = edits.get(z.name)
            if e and len(e) >= 3:
                z.poly = [tuple(q) for q in e]
                z.test = None                     # measure with the adjusted outline
        return zs

    def _sync_zone_edits(self, host):
        """Corners dragged on the video → params["zone_edits"]."""
        zd = getattr(host, "zone_drawer", None)
        params = getattr(host, "_box_params", None)
        if (zd is None or not zd.arena or not isinstance(params, dict)
                or not getattr(zd, "geometry_dragged", False)):
            return
        if zd._moving_zone is None and zd._dragging_extra is None:
            zd.geometry_dragged = False          # drag finished: last sync
        H = geo.box_homography(zd.arena)
        if H is None:
            return
        from .ui import ZONE_PREFIX
        import numpy as np
        edits = dict(params.get("zone_edits") or {})
        for z in self.all_zones(self.params_of(host), self.dims_of(host), self.colors_of(host)):
            geom = (zd.get_zone(ZONE_PREFIX + z.name) or {}).get("geometry") or []
            if len(geom) != len(z.poly):
                continue
            u, v = geo.to_box(H, [q[0] for q in geom], [q[1] for q in geom])
            pts = [[round(float(a), 5), round(float(b), 5)] for a, b in zip(u, v)]
            if np.abs(np.subtract(pts, np.asarray(z.poly, float))).max() > 1e-4:
                edits[z.name] = pts
        params["zone_edits"] = edits

    def params_of(self, host_or_settings):
        p = self.defaults()
        if isinstance(host_or_settings, dict):
            srcs = (host_or_settings.get("box_params"),
                    host_or_settings.get("box_assign"))
        else:
            srcs = (getattr(host_or_settings, "_box_params", None),)
        for src in srcs:
            if isinstance(src, dict):
                p.update({k: v for k, v in src.items() if k in p})
        if "zone_edits" in p:
            p["zone_edits"] = {k: [list(q) for q in v]
                               for k, v in (p["zone_edits"] or {}).items()}
        return p

    def split_params(self, p):
        """(shared settings, per-animal assignments)."""
        per = {s.key for s in self.PARAMS if s.per_video}
        return ({k: v for k, v in p.items() if k not in per},
                {k: v for k, v in p.items() if k in per})

    def default_colors(self):
        return {k: v[1] for k, v in self.COLORS.items()}

    def colors_of(self, host_or_settings):
        c = self.default_colors()
        src = (getattr(host_or_settings, "_box_colors", None)
               if not isinstance(host_or_settings, dict)
               else host_or_settings.get("box_colors"))
        if isinstance(src, dict):
            c.update({k: v for k, v in src.items() if k in c})
        return c

    def dims_of(self, host_or_settings):
        if isinstance(host_or_settings, dict):
            w = float(host_or_settings.get("cage_w_cm") or 0)
            h = float(host_or_settings.get("cage_h_cm") or 0)
        else:
            sw = getattr(host_or_settings, "spin_cage_w", None)
            sh = getattr(host_or_settings, "spin_cage_h", None)
            w = float(sw.value()) if sw is not None else 0.0
            h = float(sh.value()) if sh is not None else 0.0
        if self.scale[0] == "square":
            w = w or float(self.scale[1])
            return (w, w)
        return (w or float(self.scale[1]), h or float(self.scale[2]))

    def zone_defs_for_host(self, host):
        if self.EDITABLE_ZONES:
            self._sync_zone_edits(host)
        return self.all_zones(self.params_of(host), self.dims_of(host),
                          self.colors_of(host))

    # ── Experiment contract ───────────────────────────────────────────
    def default_enable_nose(self):
        return bool(self.uses_nose)

    def graph_names(self):
        from gui.graph_style import GRAPH_NAMES
        return [g for g in GRAPH_NAMES if g not in ("Triplets", "Cell Time")]

    def zones_schema(self, host):
        return []

    def build_geometry_step(self, host):
        from . import ui
        return ui.build_geometry_step(host, self)

    def build_results_tabs(self, host, right_tabs):
        from . import ui
        return ui.build_results_tab(host, self)

    def summary_zones(self, host):
        s = self.zones_summary(self.params_of(host))
        if s is not None:
            return s
        n = len(self.zone_defs_for_host(host))
        return f"{n} zones"

    def live_overlay_label(self):
        return "Live zone overlay during tracking (slower)"

    def cell_highlight_toggle_specs(self, host):
        zd = host.zone_drawer
        return [
            ("Hide zone names",
             lambda: not zd._arm_show_numbers,
             lambda hide: zd.set_arm_show_numbers(not hide)),
            ("Hide per-zone timer (SS.cc)",
             lambda: not zd._arm_show_timer,
             lambda hide: zd.set_arm_show_timer(not hide)),
            ("Hide per-zone entry count (#)",
             lambda: not zd._arm_show_entries,
             lambda hide: zd.set_arm_show_entries(not hide)),
        ]

    # Per-video persistence ------------------------------------------------
    def snapshot_extras(self, host):
        shared, assign = self.split_params(self.params_of(host))
        return {"box_params": shared, "box_assign": assign,
                "box_colors": dict(self.colors_of(host))}

    def apply_extras(self, host, extras):
        if not isinstance(extras, dict):
            return
        if isinstance(extras.get("box_params"), dict) or isinstance(extras.get("box_assign"), dict):
            host._box_params = self.params_of(extras)
        if isinstance(extras.get("box_colors"), dict):
            host._box_colors = self.colors_of({"box_colors": extras["box_colors"]})
        from . import ui
        ui.sync_widgets(host, self)
        ui.refresh_zones(host, self)

    def contribute_to_snapshot(self, host, snapshot):
        p = self.params_of(host)
        self._current_params = dict(p)
        shared, assign = self.split_params(p)
        snapshot["box_params"] = shared
        snapshot["box_assign"] = assign
        snapshot["box_colors"] = dict(self.colors_of(host))
        w, h = self.dims_of(host)
        snapshot["cage_w_cm"] = w
        snapshot["cage_h_cm"] = h
        snapshot["cage_shape"] = "square" if self.scale[0] == "square" else "rectangle"
        if hasattr(host, "spin_min_dwell"):
            snapshot["min_dwell_s"] = float(host.spin_min_dwell.value())

    _OF_ONLY_VIDEO_CONFIG_KEYS = (
        "cell_categories", "cell_min_dwell", "cell_min_dwell_s",
        "zone_mode", "center_pct", "center_zone",
    )

    def filter_video_config(self, snapshot):
        out = dict(snapshot)
        for k in self._OF_ONLY_VIDEO_CONFIG_KEYS:
            out.pop(k, None)
        return out

    # Scale ----------------------------------------------------------------
    def compute_auto_px_per_cm(self, snapshot, video_size):
        from experiments.open_field.experiment import OpenFieldExperiment
        snap = dict(snapshot or {})
        snap["cage_shape"] = "square" if self.scale[0] == "square" else "rectangle"
        return OpenFieldExperiment().compute_auto_px_per_cm(snap, video_size)

    def preflight_auto_scale_warning(self, snapshot):
        if float(snapshot.get("cage_w_cm") or 0) <= 0:
            return "auto-cal selected but the apparatus size is 0"
        return None

    def refresh_scale_step_visibility(self, host, calib_mode):
        if hasattr(host, "_cage_size_widget"):
            host._cage_size_widget.setVisible(calib_mode == "auto")
        if hasattr(host, "lbl_calib_auto_hint"):
            host.lbl_calib_auto_hint.setVisible(False)

    # Metrics ------------------------------------------------------------
    def compute_metrics(self, results, settings, fps, px_per_cm):
        p = self.params_of(settings)
        self._current_params = dict(p)
        dims = self.dims_of(settings)
        zones = self.all_zones(p, dims, self.colors_of(settings))
        s = dict(settings)
        s.update(self.engine_settings(p))
        ctx, metrics, raw_df, bin_df = engine.compute(
            results, s, fps, px_per_cm, zones, title=self.name)
        main = self.primary(ctx, metrics, p, dims) or {}
        out = dict(metrics)
        out.update(main)
        return out, raw_df, bin_df

    def engine_settings(self, p):
        """Extra engine options from the test's settings."""
        return {}

    def zone_metric_keys(self, p):
        keys = []
        for z in self.all_zones(p, self.dims_of({}), self.default_colors()):
            for fmt in ("Time in {} (s)", "% Time in {}", "Entries into {} (#)",
                        "Latency to {} (s)", "Mean Visit in {} (s)"):
                keys.append(fmt.format(z.label))
        return keys

    def summary_table_keys(self, metrics):
        p = getattr(self, "_current_params", None) or self.defaults()
        keys = [k for k in _LOCOMOTION_ORDER if k in metrics]
        main = [k for k in self.main_keys(p) if k in metrics]
        zone = [k for k in self.zone_metric_keys(p) if k in metrics]
        seen = set()
        out = []
        for k in keys[:4] + main + keys[4:] + zone:
            if k not in seen:
                seen.add(k)
                out.append(k)
        return out


    def batch_schema(self):
        p = getattr(self, "_current_params", None) or self.defaults()
        loco = [k for k in _LOCOMOTION_ORDER
                if "(px" not in k and k not in ("Total Frames", "Frames Detected")]
        return [
            ("Experiment Metadata", ["Video", "Animal ID", "Group", "Sex",
                                     "Date", "Trial", "Notes"]),
            # cm only, like Locomotion — no always-empty px twin column.
            ("Main results", [k for k in self.main_keys(p) if "(px" not in k]),
            ("Locomotion", loco),
            ("Zones", self.zone_metric_keys(p)),
        ]

    def export_columns(self):
        p = getattr(self, "_current_params", None) or self.defaults()
        return (["Animal ID", "Group", "Sex", "Date", "Trial"]
                + list(self.main_keys(p)) + ["Notes"])

    def populate_results_tab(self, host, metrics):
        from . import ui
        ui.populate_results(host, self, metrics)

    # Graphs -------------------------------------------------------------
    def zone_bar_data(self, host):
        m = getattr(host, "metrics", None) or {}
        zones = self.zone_defs_for_host(host)
        if not zones:
            return None
        first = zones[0].layer
        zs = [z for z in zones if z.layer == first]
        labels = [z.label for z in zs]
        values = [float(m.get(f"Time in {z.label} (s)", 0.0) or 0.0) for z in zs]
        colors = [z.color for z in zs]
        return (labels, values, colors, lambda v: f"{v:.1f}s",
                "Time per Zone", "Time (s)")

    def decorate_graph(self, host, graph_name, ax, arena_px):
        if graph_name not in ("Trajectory", "Heatmap") or not arena_px:
            return None
        H = geo.box_homography(arena_px)
        if H is None:
            return None
        from matplotlib.patches import Polygon
        from matplotlib.lines import Line2D
        handles = []
        for z in self.zone_defs_for_host(host):
            pts = geo.from_box(H, z.poly)
            if len(pts) < 3:
                continue
            ax.add_patch(Polygon(pts, closed=True, facecolor="none",
                                 edgecolor=z.color, linewidth=1.3,
                                 linestyle="--" if z.dashed else "-",
                                 alpha=0.9, zorder=5))
            handles.append(Line2D([], [], color=z.color, lw=2, label=z.label))
        return handles or None
