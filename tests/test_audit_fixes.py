"""Regression tests for bugs found in the 2026-11-24 full-app audit."""
import pytest

from core import units


def test_bin_mean_speed_is_a_speed_not_a_time():
    v = dict(units.variants("mean_speed_cm_per_s"))
    assert v["mean_speed_m_per_min"] == pytest.approx(0.6)   # 1 cm/s = 0.6 m/min
    assert "mean_speed_cm_per_min" not in v
    assert units.variants("mean_speed_px_per_s") == []       # px rate: no conversion


def test_tiny_negative_never_displays_as_minus_zero():
    row = units.display_row("Habituation Slope (cm/min)", -0.00004, {"distance": "m"})
    assert row[1] != "-0"


# ── lost frames inside one visit don't split it ──────────────────────────

def test_arm_visit_survives_single_lost_frames():
    from core.arm_entries import arm_visits
    seq = ["neutral_zone"] * 20 + (["arm_a"] * 9 + [None]) * 6 + ["neutral_zone"] * 20
    _, entries, times, _, _ = arm_visits(seq, ["arm_a", "arm_b", "arm_c"], 15)
    assert entries["arm_a"] == 1
    assert times["arm_a"] >= 54


def test_gap_between_two_different_zones_is_not_filled():
    from core.arm_entries import bridge_gaps
    assert bridge_gaps(["a", None, "b"], [False, True, False]) == ["a", None, "b"]
    assert bridge_gaps([None, "a", None], [True, False, True]) == [None, "a", None]
    assert bridge_gaps(["a", None, None, "a"], [False, True, True, False]) == ["a"] * 4


def test_open_field_center_visit_with_lost_frames_is_one_entry():
    from analysis.open_field import compute_metrics
    arena = [(0, 0), (400, 0), (400, 400), (0, 400)]
    center = [(100, 100), (300, 100), (300, 300), (100, 300)]
    res = []
    for i in range(300):
        in_c = 60 <= i < 240
        x = y = 200.0 if in_c else 20.0
        if in_c and i % 30 == 15:
            x = y = None
        res.append({"frame": i, "timestamp": i / 30, "x": x, "y": y})
    m, _, _ = compute_metrics(res, arena, center, px_per_cm=None, fps=30.0,
                              cell_min_dwell_s=0.2)
    assert m["Center Zone Entries (#)"] == 1
    assert m["Time in Center Zone (s)"] == pytest.approx(6.0, abs=0.05)
    assert m["Time in Center Zone (s)"] + m["Time in Periphery (s)"] <= 10.0 + 1e-9


def test_nor_bins_add_up_to_summary_and_survive_duplicate_names():
    from experiments.nor import metrics as NM
    sq = lambda cx, cy: [(cx - 20, cy - 20), (cx + 20, cy - 20), (cx + 20, cy + 20), (cx - 20, cy + 20)]
    res = []
    for i in range(300):
        # 3 short blips (4 frames) at A — under min dwell; then 2 s at B
        at_a = i % 40 < 4 and i < 120
        at_b = 150 <= i < 210
        nx, ny = (100, 100) if at_a else (300, 100) if at_b else (200, 300)
        res.append({"frame": i, "timestamp": i / 30, "x": nx, "y": ny + 30,
                    "nose_x": nx, "nose_y": ny})
    objs = {"object_a": {"zone_px": sq(100, 100), "role": "familiar", "name": "Cube"},
            "object_b": {"zone_px": sq(300, 100), "role": "novel", "name": "Cube"}}
    m, raw, bins = NM.compute(res, {"objects": objs, "min_dwell_s": 0.5, "bin_size_s": 5.0}, 30, 5)
    assert bins["time_object_a_s"].sum() == pytest.approx(m["object_a_total_time_s"])
    assert bins["time_object_b_s"].sum() == pytest.approx(m["object_b_total_time_s"])
    assert m["object_b_total_time_s"] == pytest.approx(2.0)


def test_dropped_frame_gap_counts_in_duration_and_speed():
    import pandas as pd
    from core.kinematics import compute_step_distance, compute_basic_kinematics
    rows = [{"frame": i, "timestamp": i / 30 + (5.0 if i >= 150 else 0.0)} for i in range(300)]
    for r in rows:
        r["x"], r["y"] = 10.0 * r["timestamp"], 0.0
    df = pd.DataFrame(rows)
    _, unit = compute_step_distance(df, 1.0, 30.0)
    m = compute_basic_kinematics(df, 30.0, unit)
    assert m["Duration (s)"] == pytest.approx(15.0, abs=0.01)
    assert m["Average Speed (cm/s)"] == pytest.approx(10.0, rel=0.01)


def test_normal_video_duration_is_frames_over_fps():
    import pandas as pd
    from core.kinematics import session_duration
    df = pd.DataFrame({"timestamp": [i / 30 + (0.004 if i % 2 else 0) for i in range(300)]})
    assert session_duration(df, 30.0) == pytest.approx(10.0)


def test_unknowable_fps_is_zero_not_a_guess():
    import cv2
    from core.video import probe

    class Cap:  # container says 1000 fps, decoder gives no timestamps
        def get(self, prop):
            return {cv2.CAP_PROP_FPS: 1000.0, cv2.CAP_PROP_FRAME_COUNT: 5000}.get(prop, 0.0)
        def set(self, *a):
            return True
        def grab(self):
            return True
    assert probe(Cap())[0] == 0.0


def test_batch_center_with_perspective_matches_panel():
    from gui.experiment_batch_tab import derive_center_zone, zone_pixels
    s = derive_center_zone({"arena": [(0, 0), (1, 0), (1, 1), (0, 1)],
                            "perspective": True, "center_pct": 50}, "open_field")
    arena, center = zone_pixels(s["arena"], s["center_zone"], (600, 600), warped=True)
    assert arena == [(0, 0), (600, 0), (600, 600), (0, 600)]
    assert center == [(150, 150), (450, 150), (450, 450), (150, 450)]


def test_zone_pixels_without_perspective_uses_video_size():
    from gui.experiment_batch_tab import zone_pixels
    a, c = zone_pixels([(0, 0), (0.5, 0), (0.5, 0.5)], None, (1280, 720), warped=False)
    assert a == [(0, 0), (640, 0), (640, 360)] and c is None


def test_damaged_settings_file_is_set_aside_not_overwritten(tmp_path):
    from core import app_paths
    p = tmp_path / "mice_tracker.json"
    p.write_text("{ not json", encoding="utf-8")
    app_paths.pop_notices()
    assert app_paths.read_json(str(p)) == {}
    kept = [f for f in tmp_path.iterdir() if f.name.startswith("mice_tracker.json.bad-")]
    assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == "{ not json"
    assert any("damaged" in n for n in app_paths.pop_notices())
    app_paths.write_json(str(p), {"theme": "dark"})
    assert app_paths.read_json(str(p)) == {"theme": "dark"}


def test_custom_experiment_names_never_share_a_file(tmp_path):
    from experiments.custom import library
    from experiments.custom.ui import default_zone
    z = [default_zone("circle", 1)]
    d = str(tmp_path)
    paths = {library.save(n, z, ["time"], folder=d) for n in ("Test", "Test!", "آزمایش", "تست")}
    assert len(paths) == 4
    assert sorted(n for n, _ in library.list_saved(d)) == sorted(["Test", "Test!", "آزمایش", "تست"])
    # saving the same name again replaces that one file
    assert library.save("test!", z, ["time"], folder=d) in paths
    assert len(library.list_saved(d)) == 4


def test_flat_or_point_arena_is_refused():
    from gui.experiment_batch_tab import check_arena
    with pytest.raises(RuntimeError):
        check_arena([(100, 100)] * 4, (1280, 720))
    with pytest.raises(RuntimeError):
        check_arena([(0, 0), (640, 360), (1280, 720), (320, 180)], (1280, 720))
    check_arena([(256, 72), (1024, 72), (1024, 648), (256, 648)], (1280, 720))  # normal


def test_every_export_records_the_app_version():
    from core.version import APP_VERSION
    from export.excel_export import _video_config_rows
    rows = _video_config_rows({"threshold": 25}, (1280, 720))
    assert rows[0] == ("App version", f"WIMM {APP_VERSION}")


def test_zero_real_length_is_refused():
    from gui.experiment_batch_tab import _px_per_cm_for
    s = {"calib_mode": "manual", "calib_p1": (0.2, 0.5), "calib_p2": (0.8, 0.5), "calib_cm": 0}
    with pytest.raises(RuntimeError):
        _px_per_cm_for(s, None, (1280, 720))
    assert _px_per_cm_for(dict(s, calib_cm=40), None, (1280, 720)) == pytest.approx(19.2)
