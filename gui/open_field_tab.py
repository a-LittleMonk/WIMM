"""OpenFieldTab — thin OF-flavored subclass of ExperimentTab.

The shared / generic shell lives in gui/experiment_tab.py (ExperimentTab).
OF-specific UI builders + per-frame helpers (Cell Info tab, grid drawing,
_step_geometry_of, cell highlight controls, _compute_center, etc.) are
physically housed in experiments/open_field/of_methods.py and bound onto
this subclass below.

Re-exports DEFAULT_COLORS, _hex_to_bgr, _FitLabel, PRESETS_PATH so the
batch tab and other historical importers don't break.

Y-Maze inherits from OpenFieldTab and swaps the experiment plugin —
see gui/y_maze_tab.py.
"""
from gui.experiment_tab import (
    ExperimentTab,
    DEFAULT_COLORS,
    _hex_to_bgr,
    _FitLabel,
    PRESETS_PATH,
)
from experiments.open_field import of_methods as _ofm


class OpenFieldTab(ExperimentTab):
    """Open-Field-flavored experiment tab. Defaults `experiment` to
    OpenFieldExperiment when not explicitly provided."""

    # OF cell-info preset constants. Bound to the class so methods that
    # call `self.CELL_PRESET_STANDARD` etc keep working.
    CELL_CATEGORIES         = _ofm.CELL_CATEGORIES
    CELL_PRESET_STANDARD    = _ofm.CELL_PRESET_STANDARD
    CELL_HIGHLIGHT_PRESETS  = _ofm.CELL_HIGHLIGHT_PRESETS

    def __init__(self, config, experiment=None):
        if experiment is None:
            from experiments.open_field import OpenFieldExperiment
            experiment = OpenFieldExperiment()
        super().__init__(config, experiment=experiment)
        # Register OF overlay painters with the shared ZoneDrawer only when
        # we ARE running as Open Field. YMazeTab inherits this __init__ but
        # passes its own experiment, so we gate on the key — the rendering
        # code physically lives in experiments/open_field/of_zone_overlay.py
        # and stays unbound for Y-Maze (or any other experiment).
        if getattr(self.experiment, "key", None) == "open_field":
            from experiments.open_field.of_zone_overlay import (
                paint_of_overlay, paint_of_grid_lines,
            )
            zd = self.zone_drawer
            zd.set_overlay_renderer(
                lambda p, ox, oy, dw, dh: paint_of_overlay(zd, p, ox, oy, dw, dh)
            )
            zd.set_grid_renderer(
                lambda p, ox, oy, dw, dh: paint_of_grid_lines(zd, p, ox, oy, dw, dh)
            )


# Bind OF-specific functions as methods on OpenFieldTab. Each function in
# of_methods takes `host` as its first arg → bound directly.
_OF_METHOD_NAMES = [
    "_step_geometry_of",
    "_on_zone_mode_changed",
    "_compute_center",
    "_ensure_cell_id_cache",
    "_build_cell_id_sequence",
    "_grid_cell_quad_px",
    "_draw_cell_overlay_cv2",
    "_draw_zones_on_frame_cv2",
    "_push_cell_state_for_frame",
    "_compute_cell_times_through",
    "_build_cell_info_tab",
    "_apply_cell_preset",
    "get_cell_categories",
    "set_cell_categories",
    "_on_min_dwell_changed",
    "_cell_min_dwell_s",
    "_refresh_cell_aggregation",
    "_build_cell_highlight_controls",
    "_pick_cell_highlight_color",
    "_on_cell_timer_toggled",
    "_on_cell_entries_toggled",
    "_on_live_overlay_toggled",
]
for _name in _OF_METHOD_NAMES:
    fn = getattr(_ofm, _name, None)
    if fn is not None:
        setattr(OpenFieldTab, _name, fn)
del _name
