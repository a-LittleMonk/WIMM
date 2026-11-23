"""OpenFieldExperiment — the plugin object that wires the OF tab into the
generic Experiment contract. The actual logic still lives on OpenFieldTab
(since rewriting 3949 lines would be a regression risk); this object is
the indirection point that Y-Maze and future experiments can replace."""
from experiments.base import Experiment
from . import zones as of_zones
from . import metrics as of_metrics
from . import ui as of_ui


def warp_target_size(vw, vh, cage_shape, w_cm=0.0, h_cm=0.0):
    """Size of the straightened ("warped") arena, in px. It keeps the
    cage's real shape so one px/cm holds in both directions: square →
    side × side; rectangle → w_cm : h_cm, as large as fits the frame.
    Unknown dims → the frame size (old behaviour)."""
    if not vw or not vh:
        return None
    if cage_shape == "square":
        s = min(vw, vh)
        return (s, s)
    if w_cm and h_cm and w_cm > 0 and h_cm > 0:
        k = min(vw / float(w_cm), vh / float(h_cm))
        return (max(1, int(round(w_cm * k))), max(1, int(round(h_cm * k))))
    return (vw, vh)


class OpenFieldExperiment(Experiment):
    name = "Open Field"
    key = "open_field"

    def zones_schema(self, host):
        return of_zones.build_schema(host)

    def build_geometry_step(self, host):
        return of_ui.build_geometry_step(host)

    def build_results_tabs(self, host, right_tabs):
        # OF historically adds a "Cell Info" tab inside the Excel-output
        # tab widget. The tab's _build_excel_tab still owns this; the
        # plugin just exposes the entry point.
        return of_ui.build_cell_info_tab(host)

    def preflight_auto_scale_warning(self, snapshot):
        shape = snapshot.get("cage_shape", "rectangle")
        if shape == "custom":
            return "auto-cal unavailable for Custom cage shape"
        cage_w = float(snapshot.get("cage_w_cm") or 0)
        cage_h = float(snapshot.get("cage_h_cm") or 0)
        if cage_w <= 0 or (shape == "rectangle" and cage_h <= 0):
            return "auto-cal selected but cage size = 0"
        return None

    def contribute_to_snapshot(self, host, snapshot):
        """Inject OF-specific per-video keys into the shared snapshot:
        cell-category map, cage W/H (auto-cal source), arena-from-movement
        flag + pad %, and the last-picked arena-define mode. Keeping these
        here (instead of in base ExperimentTab.snapshot_settings) means the
        base stays experiment-agnostic and Y-Maze doesn't have to strip
        them out via filter_video_config."""
        if hasattr(host, "get_cell_categories"):
            snapshot["cell_categories"] = host.get_cell_categories()
        if hasattr(host, "spin_cage_w"):
            snapshot["cage_w_cm"] = host.spin_cage_w.value()
        if hasattr(host, "spin_cage_h"):
            snapshot["cage_h_cm"] = host.spin_cage_h.value()
        snapshot["arena_auto_movement"] = bool(
            getattr(host, "_arena_auto_movement", False)
        )
        if hasattr(host, "spin_arena_pad_pct"):
            snapshot["arena_pad_pct"] = host.spin_arena_pad_pct.value()
        snapshot["arena_define_mode"] = getattr(host, "_arena_define_mode", None)

    def compute_metrics(self, results, settings, fps, px_per_cm):
        return of_metrics.compute(results, settings, fps, px_per_cm)

    def export_columns(self):
        return list(of_metrics.EXPORT_COLUMNS)

    def batch_schema(self):
        # Drives the combined-export "All Animals" master-sheet layout
        # (section headers + ordered columns). See of_metrics.BATCH_SCHEMA.
        return list(of_metrics.BATCH_SCHEMA)

    def snapshot_extras(self, host):
        return {
            "cell_categories": host.get_cell_categories() if hasattr(host, "get_cell_categories") else {},
            "cell_min_dwell_s": host._cell_min_dwell_s() if hasattr(host, "_cell_min_dwell_s") else 0.2,
            "zone_mode": (host.combo_zone_mode.currentData()
                          if hasattr(host, "combo_zone_mode") else "center_zone"),
            "center_pct": (host.spin_center_pct.value()
                           if hasattr(host, "spin_center_pct") else 25),
        }

    def apply_extras(self, host, extras):
        if not isinstance(extras, dict):
            return
        cats = extras.get("cell_categories")
        if cats and hasattr(host, "set_cell_categories"):
            host.set_cell_categories(cats)
        # Accept legacy "cell_min_dwell" key alongside the new "_s" suffix.
        cmd = extras.get("cell_min_dwell_s", extras.get("cell_min_dwell"))
        if cmd is not None:
            try:
                host.spin_min_dwell.setValue(float(cmd))
            except Exception:
                pass

    def compute_auto_px_per_cm(self, snapshot, video_size):
        """OF auto-cal: pixel arena dims ÷ real-world cage dims.
        Square = single side; rectangle = average of W and H ratios; custom skips.
        Arena in snapshot is normalized — scaled to pixels via video_size."""
        if not snapshot or not video_size:
            return None
        shape = snapshot.get("cage_shape", "rectangle")
        if shape == "custom":
            return None
        arena_norm = snapshot.get("arena")
        if not arena_norm or len(arena_norm) < 4:
            return None
        vw, vh = video_size
        if not vw or not vh:
            return None
        arena_px = [(x * vw, y * vh) for x, y in arena_norm]
        pts = arena_px
        TL = min(pts, key=lambda p: p[0] + p[1])
        BR = max(pts, key=lambda p: p[0] + p[1])
        TR = max(pts, key=lambda p: p[0] - p[1])
        BL = min(pts, key=lambda p: p[0] - p[1])
        import math
        def d(a, b):
            return math.hypot(a[0] - b[0], a[1] - b[1])
        width_px  = (d(TL, TR) + d(BL, BR)) / 2.0
        height_px = (d(TL, BL) + d(TR, BR)) / 2.0
        if shape == "square":
            side_cm = float(snapshot.get("cage_w_cm") or 0.0)
            if side_cm <= 0:
                return None
            return ((width_px + height_px) / 2.0) / side_cm
        w_cm = float(snapshot.get("cage_w_cm") or 0.0)
        h_cm = float(snapshot.get("cage_h_cm") or 0.0)
        if w_cm <= 0 or h_cm <= 0:
            return None
        return (width_px / w_cm + height_px / h_cm) / 2.0

    def live_overlay_label(self):
        return "Live cell overlay during tracking (slower)"

    def cell_highlight_toggle_specs(self, host):
        """Returns 'Hide X' toggles: checked = hidden, unchecked = shown.
        Defaults unchecked so post-tracking shows everything by default."""
        zd = host.zone_drawer
        def _hide_numbers(hide):
            zd.set_cell_show_numbers(not hide)
        def _hide_timer(hide):
            zd.set_cell_show_timer(not hide)
            if getattr(host, "tracking_results", None):
                host._push_cell_state_for_frame(host.slider_scrub.value())
        def _hide_entries(hide):
            zd.set_cell_show_entries(not hide)
            if getattr(host, "tracking_results", None):
                host._push_cell_state_for_frame(host.slider_scrub.value())
        return [
            ("Hide cell numbers (1–16, ‘C’)",
             lambda: not zd._cell_show_numbers, _hide_numbers),
            ("Hide per-cell timer (SS.cc)",
             lambda: not zd._cell_show_timer, _hide_timer),
            ("Hide per-cell entry count (#)",
             lambda: not zd._cell_show_entries, _hide_entries),
        ]

    def graph_caps(self, graph_name):
        """OF enables the 4×4 grid overlay on Trajectory / Heatmap / Cell
        Time, and the user-sized 'Center' overlay on Trajectory."""
        caps = set()
        if graph_name in ("Heatmap", "Cell Time", "Trajectory"):
            caps.add("grid")
        if graph_name == "Trajectory":
            caps.add("center_pct")
        return caps

    def refresh_scale_step_visibility(self, host, calib_mode):
        """Show OF cage W×H only when calib mode = auto AND cage shape != custom."""
        if not hasattr(host, "_cage_size_widget"):
            return
        is_custom = (host.combo_cage_shape.currentData() == "custom"
                     if hasattr(host, "combo_cage_shape") else False)
        host._cage_size_widget.setVisible(calib_mode == "auto" and not is_custom)
        if hasattr(host, "lbl_calib_auto_hint"):
            host.lbl_calib_auto_hint.setVisible(calib_mode == "auto" and is_custom)
