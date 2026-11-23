"""EPM and Y-Maze arm entries: a confirmed visit to the center / neutral
zone ends the arm visit (arm → center → same arm = 2 entries); a blip
shorter than min dwell does not."""
import pytest

from experiments.epm import metrics as EPM
from experiments.y_maze import metrics as YM

FPS = 30


def _sq(cx, cy, h):
    return [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)]


def _track(path):
    """path: [((x, y), seconds), ...] → tracker results."""
    out, f = [], 0
    for (x, y), s in path:
        for _ in range(int(round(s * FPS))):
            out.append({"frame": f, "timestamp": f / FPS, "x": x, "y": y})
            f += 1
    return out


# EPM: plus maze, center square at (200, 200).
EPM_ARMS = {
    "arm_n": [(190, 0), (210, 0), (210, 190), (190, 190)],
    "arm_s": [(190, 210), (210, 210), (210, 400), (190, 400)],
    "arm_e": [(210, 190), (400, 190), (400, 210), (210, 210)],
    "arm_w": [(0, 190), (190, 190), (190, 210), (0, 210)],
}
EPM_SET = {"arms": EPM_ARMS, "center": _sq(200, 200, 10), "min_dwell_s": 0.5}
N, C, E = (200, 100), (200, 200), (300, 200)


def test_epm_reentry_through_center_counts():
    m, _, _ = EPM.compute(_track([(N, 3), (C, 3), (N, 3), (C, 3), (E, 3)]),
                          EPM_SET, FPS, 5)
    assert m["entries_arm_n"] == 2 and m["entries_arm_e"] == 1
    assert m["total_entries"] == 3 and m["entry_sequence"] == "NNE"


def test_epm_short_center_blip_does_not_split_visit():
    m, _, _ = EPM.compute(_track([(N, 3), (C, 0.2), (N, 3)]), EPM_SET, FPS, 5)
    assert m["entries_arm_n"] == 1


# Y-Maze: three square arms around a neutral square.
YM_SET = {"arms": {"arm_a": _sq(100, 100, 40), "arm_b": _sq(300, 100, 40),
                   "arm_c": _sq(200, 300, 40)},
          "neutral": _sq(200, 170, 25), "min_dwell_s": 0.5}
A, B, Cc, NZ = (100, 100), (300, 100), (200, 300), (200, 170)


def test_y_maze_same_arm_return_counts_and_lowers_alternation():
    m, _, _ = YM.compute(
        _track([(A, 2), (NZ, 1), (A, 2), (NZ, 1), (B, 2), (NZ, 1), (Cc, 2)]),
        YM_SET, FPS, 5)
    assert m["entry_sequence"] == "AABC"
    assert m["entries_arm_a"] == 2 and m["total_entries"] == 4
    assert m["sar_count"] == 1
    # Triplets AAB (no) + ABC (yes) → 50 %.
    assert m["alternation_pct"] == pytest.approx(50.0)


def test_y_maze_short_neutral_blip_does_not_split_visit():
    m, _, _ = YM.compute(_track([(A, 2), (NZ, 0.2), (A, 2), (NZ, 1), (B, 2)]),
                         YM_SET, FPS, 5)
    assert m["entry_sequence"] == "AB"


def test_epm_pct_open_time_is_share_of_arm_time():
    # 6 s open, 3 s closed, 6 s center → open = 6 / (6 + 3) = 66.67 %.
    m, _, _ = EPM.compute(_track([(N, 3), (C, 3), (N, 3), (C, 3), (E, 3)]),
                          EPM_SET, FPS, 5)
    assert m["pct_time_open_of_arms"] == pytest.approx(66.67)
    assert m["pct_time_closed_of_arms"] == pytest.approx(33.33)
    assert m["pct_time_center"] == pytest.approx(40.0)     # of the session


def test_y_maze_bin_entries_add_up_to_total():
    path = [(A, 2), (NZ, 1), (A, 2), (NZ, 1), (B, 2), (NZ, 1), (Cc, 2)]
    m, _, bins = YM.compute(_track(path), dict(YM_SET, bin_size_s=3.0), FPS, 5)
    assert bins["total_entries"].sum() == m["total_entries"]


def test_outside_a_narrow_arm_zone_does_not_split_the_visit():
    """A mouse along the wall just outside a slightly narrow arm zone (in no
    zone, not the neutral one) is still in that arm — no fake re-entry."""
    wall = (A[0] + 45, A[1])                    # arm A zone is ±40 px
    m, _, _ = YM.compute(_track([(A, 2), (wall, 1), (A, 2), (NZ, 1), (B, 2)]),
                         YM_SET, FPS, 5)
    assert m["entry_sequence"] == "AB" and m["sar_count"] == 0


def test_run_is_blocked_without_neutral_or_center_zone():
    from experiments.y_maze.experiment import YMazeExperiment
    from experiments.epm.experiment import EPMExperiment
    tri = [(0, 0), (1, 0), (0, 1)]
    assert YMazeExperiment().preflight_zone_problem({}) is not None
    assert YMazeExperiment().preflight_zone_problem({"neutral_norm": tri}) is None
    assert EPMExperiment().preflight_zone_problem({}) is not None
    assert EPMExperiment().preflight_zone_problem({"center_norm": tri}) is None


def test_lost_tracking_does_not_split_an_arm_visit():
    rows = _track([(A, 2), (A, 1), (A, 2), (NZ, 1), (B, 2)])
    for r in rows[60:90]:                       # 1 s undetected inside arm A
        r["x"] = r["y"] = None
    m, _, _ = YM.compute(rows, YM_SET, FPS, 5)
    assert m["entry_sequence"] == "AB"
