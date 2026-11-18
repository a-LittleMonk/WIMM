"""Auto-fix engine (analysis.tracking_issues.plan_auto_fix)."""
import math

import numpy as np

from analysis.tracking_issues import plan_auto_fix, detect_issues
import pandas as pd


def _track(n=300):
    t = np.arange(n)
    return 320 + 120 * np.cos(t / 15.0), 240 + 120 * np.sin(t / 11.0)


def _plan(xs, ys, **kw):
    return plan_auto_fix(xs, ys, 30.0, 7.68, None, speed_thresh_cms=120.0,
                         accel_thresh_cms2=500.0, **kw)


def test_finds_the_real_fault_next_to_the_flag():
    tx, ty = _track()
    xs, ys = tx.copy(), ty.copy()
    xs[[100, 101]] -= 110          # two wrong frames; flags also land on 102/103
    xs[200] -= 90
    nx, ny, runs, still = _plan(xs, ys)
    assert still == []
    changed = sorted({i for a, b in runs for i in range(a, b + 1)})
    assert changed == [100, 101, 200]      # only the wrong frames are replaced
    assert np.max(np.hypot(nx - tx, ny - ty)) < 2.0


def test_long_loss_is_left_alone():
    tx, ty = _track()
    xs, ys = tx.copy(), ty.copy()
    xs[40:60], ys[40:60] = 470.0, 380.0    # 20-frame stuck glitch > max_gap
    nx, ny, runs, still = _plan(xs, ys, max_gap=10)
    assert runs == []
    assert set(still) >= {40, 60}
    assert np.array_equal(nx, xs)


def test_false_positives_are_never_changed():
    tx, ty = _track()
    xs, ys = tx.copy(), ty.copy()
    xs[100] -= 110
    _, _, runs, _ = _plan(xs, ys, protect={100})
    assert all(not (a <= 100 <= b) for a, b in runs)


def test_first_frame_has_no_fake_accel_spike():
    tx, ty = _track()
    df = pd.DataFrame({"Frame": np.arange(tx.size), "X (px)": tx, "Y (px)": ty})
    iss = detect_issues(df, 30.0, 7.68, None)
    assert 1 not in set(iss["Frame"])
