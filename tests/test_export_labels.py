"""Readable Excel names for Y-Maze / EPM / NOR / Object Location measures."""
from core import units
from export.labels import readable, readable_metrics, readable_schema


def test_examples():
    assert readable("time_arm_a_s") == "Time in Arm A (s)"
    assert readable("time_arm_s_s") == "Time in Arm S (s)"          # EPM south arm, seconds
    assert readable("entries_arm_s") == "Entries into Arm S (#)"
    assert readable("pct_time_arm_n") == "% Time in Arm N"
    assert readable("mean_dwell_arm_b_min") == "Mean Visit in Arm B (min)"
    assert readable("alternation_pct") == "Spontaneous Alternation (%)"
    assert readable("latency_first_entry_s") == "Latency to First Arm Entry (s)"
    assert readable("object_a_total_time_s") == "Exploration of Object A (s)"
    assert readable("object_b_latency_first_min") == "Latency to Object B (min)"
    assert readable("mean_speed_cm_per_s") == "Average Speed (cm/s)"
    assert readable("total_distance") == "Total Distance (cm)"
    assert readable("total_distance", "px") == "Total Distance (px)"
    assert readable("hand_fixed_frames") == "Hand-fixed Frames"
    # already readable names (Open Field, box tests) stay as they are
    assert readable("Total Distance (cm)") == "Total Distance (cm)"
    assert readable("Animal ID") == "Animal ID"


def test_readable_names_still_get_every_unit():
    m = readable_metrics({"unit": "cm", "time_arm_a_s": 60.0, "total_distance": 100.0})
    out = units.expand_metrics(m)
    assert out["Time in Arm A (min)"] == 1.0
    assert out["Total Distance (m)"] == 1.0


def test_uncalibrated_runs_stay_in_px():
    m = readable_metrics({"unit": "px", "total_distance": 100.0, "mean_speed": 5.0})
    assert "Total Distance (px)" in m and "Average Speed (px/s)" in m
    assert units.expand_metrics(m) == m          # px is never converted


def test_no_two_measures_share_a_name():
    from experiments.y_maze.metrics import BATCH_SCHEMA as ym
    from experiments.epm.metrics import BATCH_SCHEMA as epm
    from experiments.nor.metrics import BATCH_SCHEMA as nor
    for schema in (ym, epm, nor):
        cols = [c for _s, cs in schema for c in cs]
        names = [c for _s, cs in readable_schema(schema) for c in cs]
        assert len(set(names)) == len(set(cols))
