"""Unit tests for analysis.open_field.compute_metrics.

These lock down the numerical contract so future refactors (e.g. unifying
the cell-stats implementations) can't silently change reported numbers.
Each test builds a synthetic trajectory in a known 100×100 arena and
checks one metric family at a time.
"""
import math

import numpy as np
import pytest

from analysis.open_field import compute_metrics


# ── Test fixtures ─────────────────────────────────────────────────────

ARENA = [(0, 0), (100, 0), (100, 100), (0, 100)]
CENTER_ZONE_50 = [(25, 25), (75, 25), (75, 75), (25, 75)]   # central 50%
CENTER_ZONE_25 = [(37.5, 37.5), (62.5, 37.5), (62.5, 62.5), (37.5, 62.5)]
FPS = 30.0


def _results(points, fps=FPS):
    """Build the `results` list of dicts compute_metrics expects."""
    out = []
    for i, (x, y) in enumerate(points):
        out.append({
            "frame":     i,
            "timestamp": i / fps,
            "x":         x,
            "y":         y,
        })
    return out


def _const(point, n):
    """Constant-position trajectory of length n."""
    return [point] * n


def _line(a, b, n):
    """Linear interpolation between two points across n frames."""
    ax, ay = a
    bx, by = b
    return [
        (ax + (bx - ax) * t / (n - 1), ay + (by - ay) * t / (n - 1))
        for t in range(n)
    ]


# ── Smoke test ────────────────────────────────────────────────────────

def test_smoke_returns_three_outputs():
    metrics, raw_df, bin_df = compute_metrics(
        _results(_const((50, 50), 30)),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
    )
    assert isinstance(metrics, dict)
    assert len(raw_df) == 30
    assert bin_df is None


def test_basic_kinematics_keys_present():
    metrics, _, _ = compute_metrics(
        _results(_line((10, 10), (90, 90), 30)),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
    )
    assert "Total Distance (cm)" in metrics
    assert "Average Speed (cm/s)" in metrics
    assert "Duration (s)"          in metrics
    assert metrics["Duration (s)"] == pytest.approx(1.0, rel=1e-3)


# ── Zone classification ───────────────────────────────────────────────

def test_all_frames_in_center_zone():
    metrics, raw_df, _ = compute_metrics(
        _results(_const((50, 50), 60)),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        cell_min_dwell_s=0.0,  # disable debounce
    )
    assert metrics["Time in Center Zone (s)"] == pytest.approx(60 / FPS, rel=1e-3)
    assert metrics["Time in Periphery (s)"]   == pytest.approx(0.0, abs=1e-6)
    assert metrics["Center Zone Entries (#)"] == 1
    assert (raw_df["Zone"] == "center_zone").all()


def test_all_frames_in_periphery():
    # x=5, y=5 — inside arena but outside the 50% center.
    metrics, raw_df, _ = compute_metrics(
        _results(_const((5, 5), 60)),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        cell_min_dwell_s=0.0,
    )
    assert metrics["Time in Center Zone (s)"] == pytest.approx(0.0, abs=1e-6)
    assert metrics["Time in Periphery (s)"]   == pytest.approx(60 / FPS, rel=1e-3)
    assert metrics["Center Zone Entries (#)"] == 0
    assert (raw_df["Zone"] == "periphery").all()


def test_frames_outside_arena_classified():
    # Body sits at (200, 200) — way outside the arena.
    metrics, raw_df, _ = compute_metrics(
        _results(_const((200, 200), 30)),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
    )
    assert (raw_df["Zone"] == "outside").all()
    assert metrics["Center Zone Entries (#)"] == 0


def test_undetected_frames_marked():
    pts = [(50, 50)] * 10 + [(None, None)] * 5 + [(50, 50)] * 10
    metrics, raw_df, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        cell_min_dwell_s=0.0,
    )
    assert (raw_df["Zone"] == "undetected").sum() == 5
    assert metrics["Detection Rate (%)"] == pytest.approx(80.0, rel=1e-3)


# ── Min-dwell debounce ────────────────────────────────────────────────

def test_short_center_burst_does_not_count_as_entry():
    # 60 frames at periphery, 2 frames in center, 60 more periphery.
    # 2 frames @ 30 fps = 0.067 s — below the 0.2 s default dwell.
    pts = _const((5, 5), 60) + _const((50, 50), 2) + _const((5, 5), 60)
    metrics, _, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        cell_min_dwell_s=0.2,
    )
    assert metrics["Center Zone Entries (#)"] == 0
    assert metrics["Time in Center Zone (s)"] == pytest.approx(0.0, abs=1e-6)


def test_long_center_dwell_counts():
    # 60 frames in center = 2.0 s, comfortably above the dwell.
    pts = _const((5, 5), 30) + _const((50, 50), 60) + _const((5, 5), 30)
    metrics, _, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        cell_min_dwell_s=0.2,
    )
    assert metrics["Center Zone Entries (#)"] == 1
    assert metrics["Time in Center Zone (s)"] == pytest.approx(60 / FPS, rel=1e-3)


def test_multiple_long_entries_counted_separately():
    # Three long center visits separated by long peripheral gaps.
    chunk_c = _const((50, 50), 40)
    chunk_p = _const((5, 5), 40)
    pts = chunk_p + chunk_c + chunk_p + chunk_c + chunk_p + chunk_c + chunk_p
    metrics, _, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        cell_min_dwell_s=0.2,
    )
    assert metrics["Center Zone Entries (#)"] == 3
    assert metrics["Time in Center Zone (s)"] == pytest.approx(3 * 40 / FPS, rel=1e-3)


def test_dwell_zero_counts_every_change():
    # With dwell disabled, even a 1-frame center visit registers.
    pts = _const((5, 5), 10) + _const((50, 50), 1) + _const((5, 5), 10)
    metrics, _, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        cell_min_dwell_s=0.0,
    )
    assert metrics["Center Zone Entries (#)"] == 1


# ── Latency ───────────────────────────────────────────────────────────

def test_latency_to_first_center_entry():
    # Periphery for the first 60 frames, then center.
    pts = _const((5, 5), 60) + _const((50, 50), 60)
    metrics, _, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        cell_min_dwell_s=0.0,
    )
    assert metrics["Latency to First Center Zone Entry (s)"] == pytest.approx(
        60 / FPS, rel=1e-3
    )


def test_latency_includes_trim_offset():
    pts = _const((5, 5), 30) + _const((50, 50), 30)
    metrics, _, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        cell_min_dwell_s=0.0,
        trim_start_s=5.0,
    )
    # Latency reported in source-video time = trim offset + clip-relative.
    assert metrics["Latency to First Center Zone Entry (s)"] == pytest.approx(
        5.0 + 30 / FPS, rel=1e-3
    )


def test_latency_never_when_no_entry():
    metrics, _, _ = compute_metrics(
        _results(_const((5, 5), 60)),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        cell_min_dwell_s=0.0,
    )
    assert metrics["Latency to First Center Zone Entry (s)"] == "never"


# ── Dwell distribution ────────────────────────────────────────────────

def test_mean_and_longest_dwell():
    short_c = _const((50, 50), 30)   # 1.0 s
    long_c  = _const((50, 50), 90)   # 3.0 s
    gap     = _const((5, 5), 30)
    pts = gap + short_c + gap + long_c + gap
    metrics, _, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        cell_min_dwell_s=0.0,
    )
    assert metrics["Center Zone Entries (#)"] == 2
    assert metrics["Mean Center Zone Dwell (s)"] == pytest.approx(
        (1.0 + 3.0) / 2, rel=1e-3
    )
    assert metrics["Longest Center Zone Dwell (s)"] == pytest.approx(3.0, rel=1e-3)


# ── Thigmotaxis ───────────────────────────────────────────────────────

def test_thigmotaxis_with_calibration():
    # Mouse hugs the y=1 wall — well inside the 2 cm band.
    pts = [(x, 1.0) for x in np.linspace(2, 98, 60)]
    metrics, _, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        thigmotaxis_band_cm=2.0,
    )
    assert metrics["Thigmotaxis %"] == pytest.approx(100.0, rel=1e-3)


def test_thigmotaxis_center_only():
    pts = _const((50, 50), 60)
    metrics, _, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        thigmotaxis_band_cm=2.0,
    )
    assert metrics["Thigmotaxis %"] == pytest.approx(0.0, abs=1e-6)


def test_thigmotaxis_uncalibrated_uses_diagonal_band():
    # px_per_cm=None → fallback to 10% of arena diagonal.
    pts = [(x, 1.0) for x in np.linspace(2, 98, 60)]
    metrics, _, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=None, fps=FPS,
        thigmotaxis_band_cm=2.0,
    )
    assert metrics["Thigmotaxis Band"] == "10% of arena diagonal"
    assert metrics["Thigmotaxis %"] == pytest.approx(100.0, rel=1e-3)


# ── Pause / immobility ────────────────────────────────────────────────

def test_pause_detection_with_threshold():
    # Constant position → speed = 0, immobile across the whole clip.
    pts = _const((50, 50), 120)  # 4 seconds
    metrics, _, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        movement_threshold=0.5,
        pause_min_dur_s=1.0,
    )
    assert metrics["Pause Count (#)"] == 1
    # Frame 0 has no speed (no previous frame), so 119 of 120 frames count.
    assert metrics["Longest Pause (s)"] == pytest.approx(119 / FPS, abs=0.01)


def test_missed_frames_are_not_immobility_or_pauses():
    """A mouse that never stops, with tracking lost for 1.5 s, has no
    immobility and no pause — missed frames are not 'standing still'."""
    pts = _line((5, 50), (95, 50), 600)            # 20 s, always moving
    res = _results(pts)
    for r in res[300:345]:                          # 1.5 s lost
        r["x"] = r["y"] = None
    metrics, _, bins = compute_metrics(
        res, arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS, movement_threshold=0.5,
        pause_min_dur_s=1.0, bin_size_s=10.0,
    )
    assert metrics["Immobility Time (s)"] == pytest.approx(0.0, abs=0.05)
    assert metrics["Pause Count (#)"] == 0
    assert bins["Immobility (s)"].sum() == pytest.approx(0.0, abs=0.05)


def test_pauses_skipped_without_threshold():
    metrics, _, _ = compute_metrics(
        _results(_const((50, 50), 120)),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        movement_threshold=0.0,  # disabled
    )
    assert "Pause Count (#)" not in metrics


# ── Per-cell grid metrics ─────────────────────────────────────────────

def test_grid_mode_emits_per_cell_columns():
    # In a 100×100 arena split 4×4, x ∈ [25, 50), y ∈ [25, 50) is cell 6
    # (row 1, col 1, 1-indexed top-left → bottom-right).
    pts = _const((35, 35), 60)
    metrics, raw_df, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        zone_mode="grid",
        cell_min_dwell_s=0.0,
    )
    # All time concentrated in one cell, others zero.
    assert metrics["Cell 6 Time (s)"] == pytest.approx(60 / FPS, rel=1e-3)
    for cid in (1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16):
        assert metrics[f"Cell {cid} Time (s)"] == 0.0
    assert "Cell" in raw_df.columns
    assert (raw_df["Cell"] == 6).all()


def test_grid_mode_corner_cells_aggregate():
    # Park the animal in cell 1 (top-left corner): x ∈ [0, 25),
    # y ∈ [0, 25) in our 100×100 arena.
    pts = _const((10, 10), 60)
    metrics, _, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        zone_mode="grid",
        cell_min_dwell_s=0.0,
    )
    # Only cell 1 contributes; corner-cell aggregate = same.
    assert metrics["Cell 1 Time (s)"] == pytest.approx(60 / FPS, rel=1e-3)
    assert metrics["Corner Cells Time (s)"] == pytest.approx(60 / FPS, rel=1e-3)
    assert metrics["Corner Cells Entries (#)"] == 1
    # Center cells aggregate must be zero — we never crossed into the
    # 6/7/10/11 set.
    assert metrics["Center Cells Time (s)"] == 0.0
    assert metrics["Center Cells Entries (#)"] == 0


def test_grid_mode_corner_cells_multi_corner_visits():
    # Hit cell 1, then cell 4 (top-right corner), then cell 13 (bot-left).
    pts = (
        _const((10, 10), 30) +   # cell 1
        _const((90, 10), 30) +   # cell 4
        _const((10, 90), 30)     # cell 13
    )
    metrics, _, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        zone_mode="grid",
        cell_min_dwell_s=0.0,
    )
    assert metrics["Corner Cells Time (s)"] == pytest.approx(90 / FPS, rel=1e-3)
    # The animal never exits the corner-cell set, so 1 entry total.
    assert metrics["Corner Cells Entries (#)"] == 1


def test_grid_mode_side_cells_aggregate():
    # Park animal in cell 2 (top edge, between corner 1 and corner 4):
    # x ∈ [25, 50), y ∈ [0, 25) in our 100×100 arena.
    pts = _const((35, 10), 60)
    metrics, _, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        zone_mode="grid",
        cell_min_dwell_s=0.0,
    )
    assert metrics["Cell 2 Time (s)"] == pytest.approx(60 / FPS, rel=1e-3)
    assert metrics["Side Cells Time (s)"] == pytest.approx(60 / FPS, rel=1e-3)
    assert metrics["Side Cells Entries (#)"] == 1
    # Not in corners or center.
    assert metrics["Corner Cells Time (s)"] == 0.0
    assert metrics["Center Cells Time (s)"] == 0.0


def test_grid_mode_three_regions_partition_correctly():
    # 30 frames in cell 1 (corner) + 30 in cell 6 (center) + 30 in cell 2 (side).
    pts = (_const((10, 10), 30) + _const((35, 35), 30) + _const((35, 10), 30))
    metrics, _, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        zone_mode="grid",
        cell_min_dwell_s=0.0,
    )
    one_chunk = 30 / FPS
    assert metrics["Corner Cells Time (s)"] == pytest.approx(one_chunk, rel=1e-3)
    assert metrics["Center Cells Time (s)"] == pytest.approx(one_chunk, rel=1e-3)
    assert metrics["Side Cells Time (s)"]   == pytest.approx(one_chunk, rel=1e-3)
    # Region times must sum to total grid time.
    total_grid = sum(metrics.get(f"Cell {c} Time (s)", 0.0)
                     for c in range(1, 17))
    assert total_grid == pytest.approx(3 * one_chunk, rel=1e-3)


def test_grid_mode_center_cells_aggregate():
    # Visit all four center cells (6, 7, 10, 11) one after another with
    # long dwells each so they all clear the debounce.
    pts = (
        _const((35, 35), 30) +   # cell 6
        _const((60, 35), 30) +   # cell 7
        _const((35, 60), 30) +   # cell 10
        _const((60, 60), 30)     # cell 11
    )
    metrics, _, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        zone_mode="grid",
        cell_min_dwell_s=0.0,
    )
    assert metrics["Center Cells Time (s)"] == pytest.approx(120 / FPS, rel=1e-3)
    # 1 entry to the {6,7,10,11} set, then never exits.
    assert metrics["Center Cells Entries (#)"] == 1


def test_center_mode_skips_per_cell_columns():
    metrics, raw_df, _ = compute_metrics(
        _results(_const((50, 50), 30)),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        zone_mode="center_zone",
    )
    assert "Cell 1 Time (s)" not in metrics
    assert "Cell" not in raw_df.columns


# ── Bin breakdown + habituation ───────────────────────────────────────

def test_bin_df_emitted_when_requested():
    pts = _const((50, 50), 90)  # 3 seconds
    _, _, bin_df = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        bin_size_s=1.0,
    )
    assert bin_df is not None
    assert len(bin_df) == 3
    assert "Distance (cm)" in bin_df.columns
    assert "Time in Center Zone (s)" in bin_df.columns


def test_habituation_slope_negative_for_decaying_movement():
    # Bin 0: lots of movement. Bin 1: less. Bin 2: still less.
    fast = _line((10, 10), (90, 10), 30)    # 1 s
    medium = _line((90, 10), (90, 40), 30)  # 1 s
    slow = _line((90, 40), (90, 50), 30)    # 1 s
    metrics, _, bin_df = compute_metrics(
        _results(fast + medium + slow),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        bin_size_s=1.0,
    )
    assert bin_df is not None and len(bin_df) == 3
    # Distance per bin must be strictly decreasing in our synthetic clip.
    dists = bin_df["Distance (cm)"].tolist()
    assert dists[0] > dists[1] > dists[2]
    assert metrics["Habituation Slope (cm/min)"] < 0


# ── Tortuosity + mobility-only speed ──────────────────────────────────

def test_tortuosity_straight_line_is_one():
    # Straight line from (10, 50) to (90, 50): path == displacement.
    pts = _line((10, 50), (90, 50), 60)
    metrics, _, _ = compute_metrics(
        _results(pts),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
    )
    assert metrics["Tortuosity"] == pytest.approx(1.0, rel=1e-3)


def test_tortuosity_round_trip_is_high():
    # Long out-and-back path with a tiny offset at the end (real data
    # rarely lands exactly back on origin). Path is ~60 cm; net
    # displacement ~5 cm → tortuosity ~12.
    out_seg = _line((50, 50), (80, 50), 30)
    back_seg = _line((80, 50), (55, 50), 30)
    metrics, _, _ = compute_metrics(
        _results(out_seg + back_seg),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
    )
    t = metrics["Tortuosity"]
    assert isinstance(t, float)
    assert t > 10.0


def test_tortuosity_na_when_net_displacement_zero():
    # Animal returns exactly to start → displacement = 0 → undefined.
    out_seg = _line((50, 50), (80, 50), 30)
    back_seg = _line((80, 50), (50, 50), 30)
    metrics, _, _ = compute_metrics(
        _results(out_seg + back_seg),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
    )
    assert metrics["Tortuosity"] == "n/a"


def test_tortuosity_na_when_no_movement():
    metrics, _, _ = compute_metrics(
        _results(_const((50, 50), 30)),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
    )
    assert metrics["Tortuosity"] == "n/a"


def test_mobility_only_mean_speed_excludes_pauses():
    # 30 frames moving at 1 cm/frame, 30 frames stationary. With
    # movement_threshold=0.5, only the moving frames count.
    moving = _line((10, 50), (40, 50), 30)   # speed ≈ 30 cm/s
    paused = _const((40, 50), 30)             # speed = 0
    metrics, _, _ = compute_metrics(
        _results(moving + paused),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        movement_threshold=0.5,
    )
    overall = metrics["Average Speed (cm/s)"]
    mobile_only = metrics["Mean Speed When Mobile (cm/s)"]
    # Mobile-only should be roughly 2× the overall (pauses pull it down).
    assert mobile_only > overall
    assert mobile_only == pytest.approx(30.0, rel=0.1)


def test_mobility_only_speed_na_when_never_mobile():
    metrics, _, _ = compute_metrics(
        _results(_const((50, 50), 60)),
        arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        movement_threshold=0.5,
    )
    assert metrics["Mean Speed When Mobile (cm/s)"] == "n/a"


# ── Legacy keyword compat ─────────────────────────────────────────────

def test_legacy_center_keyword_still_works():
    """Older callers passed `center=` instead of `center_zone=`."""
    metrics, _, _ = compute_metrics(
        _results(_const((50, 50), 30)),
        arena=ARENA, center=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS,
        cell_min_dwell_s=0.0,
    )
    assert metrics["Center Zone Entries (#)"] == 1


def test_bins_count_a_center_visit_once_and_share_speed_base():
    """One center visit across a bin edge = one entry, in the bin where it
    starts; bin speed uses the same time base as the session average."""
    out = _const((10, 10), 90) + _const((50, 50), 60) + _const((10, 10), 90)
    res = _results(out)                                 # visit 3 s → 5 s
    for r in res[30:33]:
        r["x"] = r["y"] = None
    metrics, _, bins = compute_metrics(
        res, arena=ARENA, center_zone=CENTER_ZONE_50,
        px_per_cm=1.0, fps=FPS, bin_size_s=4.0,
    )
    assert metrics["Center Zone Entries (#)"] == 1
    assert list(bins["Center Zone Entries (#)"]) == [1, 0]
    dist = bins["Distance (cm)"].sum()
    assert dist / metrics["Duration (s)"] == pytest.approx(
        metrics["Average Speed (cm/s)"], abs=1e-3)


def test_csv_write_failure_is_reported(tmp_path, monkeypatch):
    import pandas as pd
    from export.excel_export import export_results
    metrics, raw, _ = compute_metrics(
        _results(_line((5, 5), (95, 95), 60)), arena=ARENA,
        center_zone=CENTER_ZONE_50, px_per_cm=1.0, fps=FPS)

    def locked(self, path, *a, **k):
        raise PermissionError(f"[Errno 13] Permission denied: '{path}'")
    monkeypatch.setattr(pd.DataFrame, "to_csv", locked)
    with pytest.raises(OSError, match="CSV copy could not be written"):
        export_results(metrics, raw, str(tmp_path / "v.xlsx"), "v", ARENA,
                       (100, 100), write_csv=True, all_units=False)
    assert (tmp_path / "v.xlsx").exists()
