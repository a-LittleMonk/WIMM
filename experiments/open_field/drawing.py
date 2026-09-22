"""OF cv2 zone / cell drawing helpers.

Wraps the OF-specific drawing functions in `of_methods` so the plugin
contract is the canonical entry point. The actual code lives in
`of_methods.py` (physically moved out of OpenFieldTab during the
ExperimentTab refactor — Phase 2).
"""
from . import of_methods as _ofm


def draw_zones(host, frame, draw_arena=True, draw_center=True,
               draw_grid=True, draw_exclusion=True):
    return _ofm._draw_zones_on_frame_cv2(
        host, frame, draw_arena=draw_arena, draw_center=draw_center,
        draw_grid=draw_grid, draw_exclusion=draw_exclusion,
    )


def draw_cell_overlay(host, frame, active_cell, cell_times, cell_entries,
                     draw_highlight=True, draw_numbers=True,
                     draw_timer=True, draw_entries=True):
    return _ofm._draw_cell_overlay_cv2(
        host, frame, active_cell, cell_times, cell_entries,
        draw_highlight=draw_highlight, draw_numbers=draw_numbers,
        draw_timer=draw_timer, draw_entries=draw_entries,
    )


def build_cell_id_sequence(host):
    return _ofm._build_cell_id_sequence(host)


def grid_cell_quad_px(host, arena, row, col):
    return _ofm._grid_cell_quad_px(host, arena, row, col)
