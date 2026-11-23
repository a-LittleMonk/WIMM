"""Custom experiment: user-defined zones / lines and the measures chosen."""
import json

import numpy as np
import pytest

from experiments.custom.experiment import (
    CustomExperiment, check_design, crossings, default_zone, zone_poly,
)

ARENA = [(0, 0), (400, 0), (400, 400), (0, 400)]          # 40 × 40 cm, 10 px/cm


def _track(points, fps=30):
    return [{"frame": i, "timestamp": i / fps, "x": float(x), "y": float(y)}
            for i, (x, y) in enumerate(points)]


def _run(zones, measures, points):
    exp = CustomExperiment()
    s = {"arena": ARENA, "cage_w_cm": 40, "cage_h_cm": 40, "min_dwell_s": 0.0,
         "box_params": {"zones": zones, "measures": measures}}
    m, _raw, _bins = exp.compute_metrics(_track(points), s, 30.0, 10.0)
    return m


def test_circle_is_round_in_cm_on_a_non_square_arena():
    z = default_zone("circle", 1)
    z.update(x=50, y=50, w=10)                              # 10 cm diameter
    pts = np.array(zone_poly(z, (60.0, 30.0)))
    width_cm = (pts[:, 0].max() - pts[:, 0].min()) * 60
    height_cm = (pts[:, 1].max() - pts[:, 1].min()) * 30
    assert width_cm == pytest.approx(10, abs=0.05) and height_cm == pytest.approx(10, abs=0.05)


def test_time_entries_latency_and_distance_in_a_zone():
    sq = default_zone("square", 1)
    sq.update(name="Corner", x=12.5, y=12.5, w=10)          # 0–10 cm square
    path = [(300, 300)] * 30 + [(50, 50)] * 60 + [(60, 50)] * 30 + [(300, 300)] * 30
    m = _run([sq], ["time", "entries", "latency", "distance"], path)
    assert m["Time in Corner (s)"] == pytest.approx(3.0)
    assert m["Entries into Corner (#)"] == 1
    assert m["Latency to Corner (s)"] == pytest.approx(1.0)
    # only the 1 cm move made inside counts, not the jump into the zone
    assert m["Distance in Corner (cm)"] == pytest.approx(1.0)


def test_line_crossings_and_unticked_measures_are_left_out():
    ln = default_zone("line", 1)
    ln.update(name="Gate", x=50, y=0, x2=50, y2=100)
    path = [(100 + i * 10, 200) for i in range(30)] + [(390 - i * 10, 200) for i in range(30)]
    m = _run([ln, default_zone("circle", 2)], ["crossings"], path)
    assert m["Crossings of Gate (#)"] == 2
    assert m["First Crossing of Gate (s)"] == pytest.approx(10 / 30, abs=0.04)
    assert not any(k.startswith(("Time in", "Entries", "Total Distance")) for k in m)


def test_crossing_needs_the_step_to_pass_through_the_segment():
    u = np.array([0.2, 0.8]); v = np.array([0.9, 0.9])
    assert crossings(u, v, (0.5, 0.0), (0.5, 0.5)) == []    # passes below the segment's end
    assert crossings(u, v, (0.5, 0.0), (0.5, 1.0)) == [1]


def test_design_file_round_trip_and_bad_files(tmp_path):
    exp = CustomExperiment()
    zones = [default_zone("rectangle", 1), default_zone("polygon", 2)]
    path = tmp_path / "d.json"
    exp.save_design(str(path), {"zones": zones, "measures": ["time", "bogus"]})
    z2, ms = exp.load_design(str(path))
    assert [z["shape"] for z in z2] == ["rectangle", "polygon"] and ms == ["time"]
    with pytest.raises(ValueError):
        check_design({"zones": [{"shape": "star"}]})
    with pytest.raises(ValueError):
        check_design({"zones": [{"shape": "polygon", "pts": [[0, 0]]}]})
    with pytest.raises(ValueError):
        check_design(json.loads('{"hello": 1}'))


def test_moving_zones_on_the_video_updates_the_design():
    """Dragging a circle / a line on the video moves its centre / ends."""
    from types import SimpleNamespace
    from experiments.box import geometry as geo
    from experiments.box.ui import ZONE_PREFIX
    exp = CustomExperiment()
    c = default_zone("circle", 1)
    ln = default_zone("line", 2)
    arena = [(0.2, 0.1), (0.8, 0.1), (0.8, 0.9), (0.2, 0.9)]        # normalized video coords
    H = geo.box_homography(arena)
    shift = 0.06                                                    # 10 % of the arena width
    drawn = {
        ZONE_PREFIX + c["id"]: {"geometry": [(x + shift, y) for x, y in
                                             geo.from_box(H, zone_poly(c, (40, 40)))]},
        ZONE_PREFIX + ln["id"]: {"geometry": [(x + shift, y) for x, y in
                                              geo.from_box(H, [(0.5, 0.2), (0.5, 0.8)])]},
    }
    zd = SimpleNamespace(arena=arena, get_zone=drawn.get, geometry_dragged=False,
                         _moving_zone=None, _dragging_extra=None)
    host = SimpleNamespace(zone_drawer=zd,
                           _box_params={"zones": [c, ln], "measures": ["time"]})
    assert not exp._sync_dragged(host)          # no drag: a typed change is not undone
    assert c["x"] == 50.0
    zd.geometry_dragged = True                  # the user dragged on the video
    assert exp._sync_dragged(host)
    assert (c["x"], c["y"]) == (pytest.approx(60, abs=0.1), pytest.approx(50, abs=0.1))
    assert (ln["x"], ln["x2"]) == (pytest.approx(60, abs=0.1), pytest.approx(60, abs=0.1))
    assert not exp._sync_dragged(host)                              # nothing new


def test_drawn_shapes_keep_exactly_the_drawn_outline():
    """Drawing on the video keeps the drawn outline, even on a tilted
    arena (it is not re-fitted to the arena's axes)."""
    from experiments.box import geometry as geo
    from experiments.custom.ui import zone_from_drawing
    arena = [(0.30, 0.12), (0.74, 0.20), (0.70, 0.90), (0.25, 0.80)]   # tilted
    H = geo.box_homography(arena)
    video = (1280, 720)
    r = zone_from_drawing("rectangle", [(0.40, 0.40), (0.55, 0.50)], arena, (40, 40), 1,
                          video_size=video)
    back = geo.from_box(H, r["pts"])
    assert [tuple(round(c, 4) for c in p) for p in back] == [
        (0.40, 0.40), (0.55, 0.40), (0.55, 0.50), (0.40, 0.50)]
    c = zone_from_drawing("circle", [(0.5, 0.5), (0.55, 0.5)], arena, (40, 40), 2,
                          video_size=video)
    px = [((x - 0.5) * 1280, (y - 0.5) * 720) for x, y in geo.from_box(H, c["pts"])]
    radii = [(dx * dx + dy * dy) ** 0.5 for dx, dy in px]
    assert max(radii) - min(radii) < 0.01 and abs(radii[0] - 64) < 0.01   # round on screen
    ln = zone_from_drawing("line", [(0.4, 0.3), (0.6, 0.3)], arena, (40, 40), 3,
                           video_size=video)
    assert "pts" not in ln and 0 <= ln["x"] <= 100


def test_saved_experiment_library(tmp_path):
    """Save → listed by name; saving again with its path overwrites;
    delete removes; a design with no zones or no measures is refused."""
    from experiments.custom import library
    folder = str(tmp_path)
    z = [default_zone("circle", 1)]
    p = library.save("Food cup test", z, ["time"], folder=folder)
    assert library.list_saved(folder) == [("Food cup test", p)]
    library.save("Food cup test", z, ["time", "entries"], path=p)
    assert library.load(p)[2] == ["time", "entries"] and len(library.list_saved(folder)) == 1
    with pytest.raises(ValueError):
        library.save("Empty", [], ["time"], folder=folder)
    with pytest.raises(ValueError):
        library.save("No measures", z, [], folder=folder)
    with pytest.raises(ValueError):
        library.save("   ", z, ["time"], folder=folder)
    library.delete(p)
    assert library.list_saved(folder) == []
