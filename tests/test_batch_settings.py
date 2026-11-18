"""Batch-run shared settings + Multi-Run combination helpers."""
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt5")

from gui.experiment_batch_tab import (
    PER_VIDEO_KEYS, merge_batch_settings, derive_center_zone,
)
from gui.multi_run_dialog import (
    variant_specs, variant_label, _MODE_GRID, _MODE_SINGLE,
)


ARENA_A = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]
ARENA_B = [(0.2, 0.2), (0.6, 0.2), (0.6, 0.6), (0.2, 0.6)]


def test_merge_takes_data_settings_from_source_and_keeps_geometry():
    src = {"threshold": 30, "blur": 3, "smooth": 5, "trim_start": 10.0,
           "model_params": {"mog2": {"history": 200}},
           "arena": ARENA_A, "metadata": {"Animal ID": "A1"},
           "calib_p1": (1, 1), "calib_p2": (2, 2), "calib_cm": 40.0}
    own = {"threshold": 18, "blur": 0, "arena": ARENA_B,
           "metadata": {"Animal ID": "B7"}, "calib_p1": (5, 5),
           "calib_p2": (9, 9), "calib_cm": 40.0,
           "exclusion_mask": np.zeros((4, 4), dtype=np.uint8)}
    m = merge_batch_settings(src, own)
    # Shared data settings come from the source.
    assert m["threshold"] == 30 and m["blur"] == 3 and m["smooth"] == 5
    assert m["trim_start"] == 10.0
    # Per-video geometry stays with the video.
    assert m["arena"] == ARENA_B
    assert m["metadata"] == {"Animal ID": "B7"}
    assert m["calib_p1"] == (5, 5)
    assert "exclusion_mask" in m
    # Nested values are copies, not shared objects.
    m["model_params"]["mog2"]["history"] = 1
    assert src["model_params"]["mog2"]["history"] == 200


def test_merge_does_not_invent_geometry_for_unconfigured_video():
    m = merge_batch_settings({"threshold": 30, "arena": ARENA_A}, {})
    assert m["threshold"] == 30
    assert "arena" not in m


def test_geometry_keys_are_per_video():
    for k in ("arena", "center_zone", "exclusion_mask", "crop", "metadata",
              "calib_p1", "calib_p2", "arms_norm", "objects_norm"):
        assert k in PER_VIDEO_KEYS
    for k in ("threshold", "model", "smooth", "smooth_window", "frame_skip",
              "center_pct", "movement_thr", "bin_size", "trim_start"):
        assert k not in PER_VIDEO_KEYS


def test_center_zone_rebuilt_from_shared_percent():
    s = derive_center_zone({"arena": ARENA_A, "center_pct": 50,
                            "center_zone": [(0, 0)] * 4}, "open_field")
    xs = sorted(p[0] for p in s["center_zone"])
    assert xs[0] == pytest.approx(0.3) and xs[-1] == pytest.approx(0.7)


def test_center_zone_untouched_for_other_experiments():
    cz = [(0.4, 0.4)] * 4
    s = derive_center_zone({"arena": ARENA_A, "center_pct": 50,
                            "center_zone": list(cz)}, "y_maze")
    assert s["center_zone"] == cz


PLAN = [("threshold", "Threshold", [(20, "20"), (30, "30")]),
        ("blur", "Blur", [(0, "0"), (3, "3"), (7, "7")])]


def test_grid_mode_runs_every_combination():
    specs = variant_specs(PLAN, _MODE_GRID)
    assert len(specs) == 6
    assert [(r[0][2], r[1][2]) for r in specs][:3] == [(20, 0), (20, 3), (20, 7)]


def test_single_mode_runs_each_variable_alone():
    specs = variant_specs(PLAN, _MODE_SINGLE)
    assert len(specs) == 5
    assert all(len(r) == 1 for r in specs)


def test_labels():
    spec = variant_specs(PLAN, _MODE_GRID)[1]
    assert variant_label(2, spec, True) == "Run 2: threshold=20, blur=3"
    assert variant_label(1, [PLAN[0][2] and ("threshold", "Threshold", 20, "20")], False) == "20"
