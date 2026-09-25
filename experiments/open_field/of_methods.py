"""Facade for the OF-specific helpers.

The physical code lives in five focused modules; this file re-exports
their public symbols so existing importers (``from experiments.open_field
import of_methods as _ofm``) keep working without touching every call
site:

* of_ui_cell_info       — Cell Info tab + min-dwell + region presets
* of_ui_cell_highlight  — Cell-highlight color / opacity / toggles
* of_ui_geometry        — Step 2 (Geometry) UI builder + zone-mode change
* of_state              — Cell-ID cache, center math, scrub state push
* of_cv2_drawing        — cv2 burn-in (cell overlay + zones)
"""
from .of_ui_cell_info import (
    CELL_CATEGORIES,
    CELL_PRESET_STANDARD,
    CELL_HIGHLIGHT_PRESETS,
    _build_cell_info_tab,
    _apply_cell_preset,
    get_cell_categories,
    set_cell_categories,
    _on_min_dwell_changed,
    _cell_min_dwell_s,
    _refresh_cell_aggregation,
)
from .of_ui_cell_highlight import (
    _build_cell_highlight_controls,
    _pick_cell_highlight_color,
    _on_cell_timer_toggled,
    _on_cell_entries_toggled,
    _on_live_overlay_toggled,
)
from .of_ui_geometry import (
    _step_geometry_of,
    _on_zone_mode_changed,
)
from .of_state import (
    _compute_center,
    _arena_recompute,
    _ensure_cell_id_cache,
    _build_cell_id_sequence,
    _periphery_cum_times,
    _grid_cell_quad_px,
    _push_cell_state_for_frame,
    _compute_cell_times_through,
)
from .of_cv2_drawing import (
    _draw_cell_overlay_cv2,
    _draw_zones_on_frame_cv2,
)

__all__ = [
    "CELL_CATEGORIES",
    "CELL_PRESET_STANDARD",
    "CELL_HIGHLIGHT_PRESETS",
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
    "_step_geometry_of",
    "_on_zone_mode_changed",
    "_compute_center",
    "_arena_recompute",
    "_ensure_cell_id_cache",
    "_build_cell_id_sequence",
    "_periphery_cum_times",
    "_grid_cell_quad_px",
    "_push_cell_state_for_frame",
    "_compute_cell_times_through",
    "_draw_cell_overlay_cv2",
    "_draw_zones_on_frame_cv2",
]
