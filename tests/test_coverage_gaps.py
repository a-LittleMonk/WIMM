"""Tests for the riskiest code the 2026-11-24 coverage audit found untested:
unit conversion, auto calibration, NOR object zones and heading filter,
smoothing, unit display, raw export, bin totals, issue detectors and
custom-design validation."""
import math

import numpy as np
import pandas as pd
import pytest

FPS = 30


def _line(p0, p1, n):
    return [{"frame": i, "timestamp": i / FPS,
             "x": p0[0] + (p1[0] - p0[0]) * i / (n - 1),
             "y": p0[1] + (p1[1] - p0[1]) * i / (n - 1)} for i in range(n)]


# 1. Open Field distance / speed really divide by px/cm (all other OF tests use 1).
def test_of_distance_and_speed_use_px_per_cm():
    from analysis.open_field import compute_metrics
    arena = [(0, 0), (400, 0), (400, 400), (0, 400)]
    m, raw, _ = compute_metrics(_line((0, 50), (100, 50), 31), arena, None,
                                px_per_cm=10.0, fps=FPS)
    assert m["Total Distance (cm)"] == pytest.approx(10.0, rel=1e-3)      # 100 px / 10
    assert m["Average Speed (cm/s)"] == pytest.approx(10.0 * 30 / 31, rel=1e-3)  # 10 cm in 31 frames
    assert raw["Step Distance (cm)"].iloc[1:].sum() == pytest.approx(10.0, rel=1e-3)


# 2. EPM / Y-Maze automatic scale.
def test_epm_auto_px_per_cm_is_mean_spoke_over_arm_length():
    from experiments.epm.experiment import EPMExperiment
    snap = {"epm_hub": (0.5, 0.5), "arm_length_cm": 50,
            "epm_endpoints": [(0.5, 0.0), (0.5, 1.0), (0.0, 0.5), (1.0, 0.5)]}
    exp = EPMExperiment()
    assert exp.compute_auto_px_per_cm(snap, (1000, 1000)) == pytest.approx(10.0)
    assert exp.compute_auto_px_per_cm(dict(snap, arm_length_cm=0), (1000, 1000)) is None
    assert exp.compute_auto_px_per_cm(dict(snap, epm_endpoints=snap["epm_endpoints"][:3]),
                                      (1000, 1000)) is None


def test_ymaze_auto_px_per_cm_is_mean_spoke_over_arm_length():
    from experiments.y_maze.experiment import YMazeExperiment
    snap = {"ym_hub": (0.5, 0.5), "arm_length_cm": 40,
            "ym_endpoints": [(0.5, 0.1), (0.1, 0.5), (0.9, 0.5)]}
    assert YMazeExperiment().compute_auto_px_per_cm(snap, (1000, 1000)) == pytest.approx(10.0)


# 4. NOR heading filter decides which frames count as exploring.
def _sqp(cx, cy, h=20):
    return [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)]


def test_nor_angle_filter_drops_frames_facing_away():
    from experiments.nor import metrics as NM
    objs = {"object_a": {"zone_px": _sqp(100, 100), "role": "familiar"},
            "object_b": {"zone_px": _sqp(300, 100), "role": "novel"}}
    # body below the object, nose inside the zone and pointing at its centre
    facing = [{"frame": i, "timestamp": i / FPS, "x": 100, "y": 140,
               "nose_x": 100, "nose_y": 115} for i in range(90)]
    # body between the object's centre and the nose: heading points away
    away = [{"frame": i, "timestamp": i / FPS, "x": 100, "y": 108,
             "nose_x": 100, "nose_y": 115} for i in range(90)]
    s = {"objects": objs, "min_dwell_s": 0.2, "angle_enabled": True, "angle_max_deg": 45}
    assert NM.compute(facing, s, FPS, 5)[0]["object_a_total_time_s"] == pytest.approx(3.0)
    assert NM.compute(away, s, FPS, 5)[0]["object_a_total_time_s"] == 0.0
    s_off = dict(s, angle_enabled=False)
    assert NM.compute(away, s_off, FPS, 5)[0]["object_a_total_time_s"] == pytest.approx(3.0)


# 5. NOR object zone sizes in cm.
def test_nor_footprint_and_halo_sizes_in_cm():
    from experiments.nor.zones import build_footprint_norm, build_zone_norm
    st = {"shape": "circle", "size_cm": 4, "center_norm": (0.5, 0.5), "padding_cm": 2}
    fp = build_footprint_norm(st, 10.0, (400, 400))
    r = max(math.hypot(x * 400 - 200, y * 400 - 200) for x, y in fp)
    assert r == pytest.approx(20, abs=0.5)                 # 2 cm radius × 10 px/cm
    z = build_zone_norm(fp, st, 10.0, (400, 400))
    rz = max(math.hypot(x * 400 - 200, y * 400 - 200) for x, y in z)
    assert rz == pytest.approx(40, abs=1.0)                # + 2 cm padding
    assert build_zone_norm(fp, dict(st, padding_cm=0), 10.0, (400, 400)) == fp


# 6. Smoothing keeps manual fixes and missing frames, and never edits its input.
def test_smoothing_moving_average_keeps_corrections_and_gaps():
    from gui.output.corrections_mixin import CorrectionsMixin
    raw = [{"x": 0.0, "y": 0.0}, {"x": 3.0, "y": 0.0}, {"x": 6.0, "y": 0.0},
           {"x": None, "y": None}, {"x": 9.0, "y": 0.0, "corrected": True}]
    out = CorrectionsMixin._apply_smoothing(None, raw, 3)
    assert [r["x"] for r in out[:3]] == [1.5, 3.0, 4.5]
    assert out[3]["x"] is None and out[4]["x"] == 9.0
    assert raw[1]["x"] == 3.0
    assert CorrectionsMixin._apply_smoothing(None, raw, 1) == raw


# 7. Unit display / raw-sheet scales.
def test_display_conversions():
    from core.units import normalize, display_row, display_column
    assert normalize({"speed": "km/h", "distance": "parsec"}) == {
        "distance": "cm", "speed": "km/h", "time": "s"}
    assert display_row("Average Speed (cm/s)", 10.0, {"speed": "km/h"}) == (
        "Average Speed", "0.36", "km/h")
    assert display_row("Duration (s)", "n/a", {"time": "min"}) == ("Duration", "n/a", "min")
    assert display_column("Speed (cm/s)", {"speed": "mm/s"}) == (10.0, "Speed (mm/s)")


def test_expand_df_adds_every_scale():
    from core.units import expand_df
    df = pd.DataFrame({"Step Distance (cm)": [1.0, np.nan], "Time (s)": [0, 60],
                       "Zone": ["a", "b"]})
    out = expand_df(df)
    cols = list(out.columns)
    assert cols.index("Step Distance (mm)") == cols.index("Step Distance (cm)") + 1
    assert out["Step Distance (mm)"].iloc[0] == 10.0
    assert pd.isna(out["Step Distance (mm)"].iloc[1])
    assert out["Time (min)"].tolist() == [0.0, 1.0]
    assert out["Zone"].tolist() == ["a", "b"]


# 8. Combined raw export: one sheet per animal, duplicate IDs kept apart.
def test_export_combined_raw_one_sheet_per_animal(tmp_path):
    from openpyxl import load_workbook
    from export.excel_export import export_combined_raw
    df = pd.DataFrame({"Frame": [0, 1], "X (px)": [1.0, np.nan], "Speed (cm/s)": [0.0, 30.0]})
    p = tmp_path / "r.xlsx"
    export_combined_raw(str(p), [{"animal_id": "A1", "metadata": {"Group": "Ctrl"}, "raw_df": df},
                                 {"animal_id": "A1", "metadata": {}, "raw_df": None}])
    wb = load_workbook(p)
    assert len(wb.sheetnames) == 2
    headers = [c.value for row in wb.worksheets[0].iter_rows() for c in row]
    assert "Speed (km/h)" in headers
    assert 30.0 in headers and "nan" not in [str(v).lower() for v in headers if isinstance(v, str)]


# 9. EPM per-bin entries add up to the session.
def test_epm_bins_sum_to_session():
    from experiments.epm import metrics as EPM
    from tests.test_maze_entries import _track, EPM_SET, N, C, E
    m, _, b = EPM.compute(_track([(N, 3), (C, 3), (E, 3)]), dict(EPM_SET, bin_size_s=2.0), FPS, 5)
    assert b["total_entries"].sum() == m["total_entries"]
    assert b["time_center_s"].sum() == pytest.approx(m["time_center_s"], abs=0.05)
    assert b["time_open_s"].sum() == pytest.approx(m["time_open_total_s"], abs=0.05)


# 10. "Outside arena" and "jump after a lost-tracking gap" detectors.
def test_outside_and_gap_jump_detectors():
    from analysis.tracking_issues import detect_issues
    df = pd.DataFrame({"Frame": range(20),
                       "X (px)": [50.0] * 10 + [np.nan] * 6 + [500.0] * 4,
                       "Y (px)": [50.0] * 20})
    iss = detect_issues(df, 30, 1.0, [(0, 0), (100, 0), (100, 100), (0, 100)],
                        gap_frames=5, gap_jump_cm=8, auto_speed=False)
    flagged = set(iss["Frame"])
    assert {16, 17, 18, 19} <= flagged                     # outside the arena
    reasons = " ".join(iss[iss["Frame"] == 16]["Reasons"]).lower()
    assert "outside" in reasons and ("jump" in reasons or "gap" in reasons)


# 11. Custom design validation.
def test_check_design_rejects_non_numeric_coords():
    from experiments.custom.experiment import check_design, default_zone
    good = default_zone("circle", 1)
    check_design({"zones": [good], "measures": ["time"]})
    with pytest.raises(ValueError):
        check_design({"zones": [dict(good, x="abc")], "measures": ["time"]})
