"""Box-family tests (place preference, light–dark, three-chamber, zero
maze, water maze, T-maze, radial maze) and Novel Object Location:
simulated tracks with known answers."""
import math

import pytest

from experiments.box import paradigms as P
from experiments.box import geometry as geo
from experiments.box import engine

ARENA = [(100, 50), (700, 50), (700, 450), (100, 450)]     # 600 × 400 px
H = geo.box_homography(ARENA)


def _px(u, v):
    return tuple(geo.apply_h(H, [(u, v)])[0])


def _track(path, per=60, fps=30):
    out, f = [], 0
    for u, v in path:
        for _ in range(per):
            x, y = _px(u, v)
            out.append({"frame": f, "timestamp": f / fps, "x": x, "y": y})
            f += 1
    return out


def _run(exp, path, params=None, per=60, **settings):
    p = exp.defaults()
    p.update(params or {})
    w, h = exp.dims_of({})
    s = {"arena": ARENA, "box_params": p, "min_dwell_s": 0.5,
         "cage_w_cm": w, "cage_h_cm": h}
    s.update(settings)
    m, raw, _b = exp.compute_metrics(_track(path, per), s, 30, None)
    return m, raw


def _ring(a, r):
    return (0.5 + r * math.cos(math.radians(a)), 0.5 - r * math.sin(math.radians(a)))


# ── geometry ─────────────────────────────────────────────────────────────
def test_box_mapping_round_trip_any_corner_order():
    shuffled = [ARENA[2], ARENA[0], ARENA[3], ARENA[1]]
    Hs = geo.box_homography(shuffled)
    u, v = geo.to_box(Hs, [400.0], [250.0])
    assert u[0] == pytest.approx(0.5) and v[0] == pytest.approx(0.5)
    assert geo.box_homography([(0, 0), (1, 1)]) is None


def test_min_dwell_rule_ignores_short_visits():
    seq = ["A"] * 20 + ["B"] * 3 + ["A"] * 20
    st = engine.layer_stats(seq, ["A", "B"], min_frames=10)
    assert st.entries == {"A": 1, "B": 0}


# ── tests ────────────────────────────────────────────────────────────────
def test_place_preference():
    m, _ = _run(P.PlacePreference(), [(0.15, .5), (0.5, .5), (0.85, .5), (0.85, .4), (0.15, .5)])
    assert m["Time in Paired (s)"] == 4.0 and m["Time in Unpaired (s)"] == 4.0
    assert m["Entries into Paired (#)"] == 2 and m["Preference Score (s)"] == 0.0
    m, _ = _run(P.PlacePreference(), [(0.3, .5), (0.7, .5)], {"n_comp": 2, "paired": "B"})
    assert m["% Time in Paired"] == 50.0 and m["Paired Compartment"] == "Compartment B"


def test_light_dark_transitions_and_lost_frames():
    m, _ = _run(P.LightDark(), [(0.2, .5), (0.3, .5), (0.9, .5), (0.2, .5)])
    assert m["Time in Light (s)"] == 6.0 and m["Transitions (#)"] == 2
    assert m["Latency to Dark (s)"] == 4.0
    e = P.LightDark()
    p = e.defaults()
    p["lost_dark"] = True
    res = _track([(0.2, .5)]) + [{"frame": 60 + i, "timestamp": (60 + i) / 30,
                                  "x": None, "y": None} for i in range(90)]
    m, _, _ = e.compute_metrics(res, {"arena": ARENA, "box_params": p,
                                      "min_dwell_s": .5}, 30, None)
    assert m["Time in Dark (s)"] == 3.0


def test_three_chamber_indices():
    m, raw = _run(P.ThreeChamber(), [(0.165, .5), (0.165, .5), (0.5, .5), (0.85, .2)])
    assert m["Time in Stranger Chamber (s)"] == 4.0
    assert m["Time in Stranger sniff zone (s)"] == 4.0
    assert m["Sociability Index (chamber)"] == pytest.approx(round((4 - 2) / 6, 3))
    assert m["Sociability Index (sniffing)"] == 1.0
    assert "Sniff" in raw.columns
    m, _ = _run(P.ThreeChamber(), [(0.83, .5)], {"phase": "nov", "target_side": "R"})
    assert m["Time in Novel sniff zone (s)"] == 2.0 and m["Phase"] == "Social novelty"


def test_zero_maze_open_closed():
    m, _ = _run(P.ZeroMaze(), [_ring(90, .46), _ring(0, .46), _ring(270, .46), (0.5, 0.5)])
    assert m["Time in Open (s)"] == 4.0 and m["Time in Closed (s)"] == 2.0
    assert m["Entries into Open (#)"] == 2 and m["Open / Closed Crossings (#)"] == 2
    # Rotating the sections by 45° moves the boundaries onto the diagonals.
    m, _ = _run(P.ZeroMaze(), [_ring(90 - 50, .46)], {"rotation": 45})
    assert m["Time in Open (s)"] == 2.0


def test_water_maze_latency_and_quadrant():
    e = P.WaterMaze()
    cu, cv, _r = e._platform(e.defaults(), (120, 120))
    m, _ = _run(e, [_ring(225, .47), (0.4, .55), (cu, cv)])
    assert m["Latency to Platform (s)"] == 4.0
    assert m["Time in Target Quadrant (s)"] == 2.0
    assert m["% Time in Target Quadrant"] == pytest.approx(33.33)
    assert m["Time in Wall zone (s)"] == 2.0
    assert m["Mean Distance to Platform (cm)"] > 0


def test_water_maze_brief_platform_crossing_counts():
    """A crossing shorter than min dwell still counts (probe trials)."""
    e = P.WaterMaze()
    cu, cv, _r = e._platform(e.defaults(), (120, 120))
    m, _ = _run(e, [(0.3, 0.7), (cu, cv), (0.3, 0.7)], per=3)   # 0.1 s on it
    assert m["Entries into Platform (#)"] == 1


def test_t_maze_alternation_and_orientation():
    tm = P.TMaze()
    m, _ = _run(tm, [(.5, .9), (.5, .05), (.1, .05), (.5, .05), (.9, .05), (.5, .05), (.1, .05)])
    assert m["Choice Sequence"] == "LRL" and m["Alternation (%)"] == 100.0
    m, _ = _run(tm, [(.5, .1), (.5, .95), (.1, .95)], {"orient": "up"})
    assert m["First Choice"] == "Right"     # image left = the mouse's right


def test_radial_maze_errors():
    rm = P.RadialMaze()

    def arm(k, n=8):
        return _ring(90 - (k - 1) * 360 / n, 0.4)
    m, _ = _run(rm, [arm(1), (.5, .5), arm(3), (.5, .5), arm(1), (.5, .5), arm(5)],
                {"baited": [1, 3]})
    assert m["Arm Entry Sequence"] == "1-3-1-5"
    assert m["Working Memory Errors (#)"] == 1
    assert m["Reference Memory Errors (#)"] == 1
    assert m["Entries Before First Repeat (#)"] == 2
    assert m["Time to Visit All Arms (s)"] == 4.0


def test_every_test_has_consistent_keys():
    for cls in P.ALL:
        e = cls()
        p = e.defaults()
        zones = e.zones(p, e.dims_of({}), e.default_colors())
        assert zones, cls.__name__
        assert len({z.name for z in zones}) == len(zones)
        assert set(e.main_keys(p))
        for spec in e.PARAMS:
            assert spec.key in p


def test_nol_renames_roles():
    from experiments.nol import NOLExperiment
    from experiments.nor.experiment import NORExperiment
    e = NOLExperiment()
    assert e.family == NORExperiment.family == "nor"
    assert e.role_labels["novel"] == "Moved"
    keys = e.summary_table_keys({})
    assert "moved_time_s" in keys and "novel_time_s" not in keys


def test_registry_lists_every_test():
    from experiments import registry
    for cls in P.ALL:
        assert cls.key in registry.KEYS
    assert "nol" in registry.KEYS


def test_nor_di_when_only_novel_explored():
    """Exploring only the novel object is DI = +1, not a blank."""
    from experiments.nor import metrics as NM

    def sq(cx, cy):
        return [(cx - 20, cy - 20), (cx + 20, cy - 20), (cx + 20, cy + 20), (cx - 20, cy + 20)]
    objs = {"object_a": {"zone_px": sq(100, 100), "role": "familiar"},
            "object_b": {"zone_px": sq(300, 100), "role": "novel"}}
    rows = [{"frame": i, "timestamp": i / 30, "x": 300, "y": 130,
             "nose_x": 300 if i < 300 else 200, "nose_y": 100 if i < 300 else 300}
            for i in range(600)]
    m, _, _ = NM.compute(rows, {"objects": objs, "min_dwell_s": 0.2}, 30, 5)
    assert m["discrimination_index"] == 1.0
    assert m["preference_pct_novel"] == 100.0
    objs["object_b"]["role"] = "none"          # roles not both set → blank
    m, _, _ = NM.compute(rows, {"objects": objs, "min_dwell_s": 0.2}, 30, 5)
    assert m["discrimination_index"] is None
