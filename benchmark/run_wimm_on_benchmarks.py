"""Run every benchmark video through WIMM itself (its tracker, its
experiment results code and its Excel export), save WIMM's result file in
the test's folder, and write a side-by-side comparison with the benchmark.

    <WIMM .venv python> run_wimm_on_benchmarks.py [test_key ...]

WIMM folder: ../../WIMM (change WIMM_DIR below if it moves). The zones
given to WIMM are the ones in each benchmark's "WIMM settings" sheet.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WIMM_DIR = os.path.abspath(os.environ.get("WIMM_DIR") or os.path.join(HERE, ".."))  # WIMM source: the repo this folder sits in
sys.path.insert(0, WIMM_DIR)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import openpyxl                                   # noqa: E402
from openpyxl.styles import Font, PatternFill     # noqa: E402
from PyQt5.QtWidgets import QApplication          # noqa: E402

from core.version import APP_VERSION              # noqa: E402
from export.excel_export import export_results    # noqa: E402
from tracking.tracker import TrackerThread        # noqa: E402

W, H = 1280, 720
APP = QApplication.instance() or QApplication([])


def norm(pts):
    return [(x / W, y / H) for x, y in pts]


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def circle(cx, cy, r, n=64):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def bar(cx, cy, ang, r0, r1, hw):
    ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    nx, ny = -uy, ux
    return [(cx + ux * r0 + nx * hw, cy + uy * r0 + ny * hw), (cx + ux * r1 + nx * hw, cy + uy * r1 + ny * hw),
            (cx + ux * r1 - nx * hw, cy + uy * r1 - ny * hw), (cx + ux * r0 - nx * hw, cy + uy * r0 - ny * hw)]


SQUARE_OF = rect(370, 90, 910, 630)
COMMON = {"movement_threshold": 2.0, "bin_size_s": 5.0, "pause_min_dur_s": 1.0, "min_dwell_s": 0.0,
          "trim_start_s": 0.0, "video_w": W, "video_h": H}


def of_setup():
    from experiments.open_field.experiment import OpenFieldExperiment
    c = 0.5
    cen = [(640 + (x - 640) * c, 360 + (y - 360) * c) for x, y in SQUARE_OF]
    return OpenFieldExperiment(), SQUARE_OF, 13.5, False, {
        "arena": SQUARE_OF, "center_zone": cen, "zone_mode": "center_zone", "center_pct": 50,
        "thigmotaxis_band_cm": 2.0, "cell_min_dwell_s": 0.2}


def ym_setup():
    from experiments.y_maze.experiment import YMazeExperiment
    cx, cy, hw = 640, 410, 43
    r0 = hw / math.tan(math.radians(60))
    arms = {"arm_a": bar(cx, cy, -90, r0, 300, hw), "arm_b": bar(cx, cy, 150, r0, 300, hw),
            "arm_c": bar(cx, cy, 30, r0, 300, hw)}
    rc = hw / math.sin(math.radians(60))
    hub = [(cx + rc * math.cos(math.radians(a)), cy + rc * math.sin(math.radians(a))) for a in (-30, 90, 210)]
    outline = []
    for a in (-90, 30, 150):
        q = bar(cx, cy, a, 0, 300, hw)
        outline += [(cx + rc * math.cos(math.radians(a - 60)), cy + rc * math.sin(math.radians(a - 60))), q[2], q[1]]
    return YMazeExperiment(), outline, 8.6, False, {
        "arms_norm": {k: norm(v) for k, v in arms.items()}, "neutral_norm": norm(hub)}


def epm_setup():
    from experiments.epm.experiment import EPMExperiment
    cx, cy, h = 640, 360, 33
    arms = {"arm_n": rect(cx - h, cy - 320, cx + h, cy - h), "arm_s": rect(cx - h, cy + h, cx + h, cy + 320),
            "arm_e": rect(cx + h, cy - h, cx + 330, cy + h), "arm_w": rect(cx - 330, cy - h, cx - h, cy + h)}
    outline = [(cx - h, cy - 320), (cx + h, cy - 320), (cx + h, cy - h), (cx + 330, cy - h), (cx + 330, cy + h),
               (cx + h, cy + h), (cx + h, cy + 320), (cx - h, cy + 320), (cx - h, cy + h), (cx - 330, cy + h),
               (cx - 330, cy - h), (cx - h, cy - h)]
    return EPMExperiment(), outline, 13.2, False, {
        "arms_norm": {k: norm(v) for k, v in arms.items()}, "center_norm": norm(rect(cx - h, cy - h, cx + h, cy + h)),
        "arm_kinds": {"arm_n": "closed", "arm_s": "closed", "arm_e": "open", "arm_w": "open"}}


def nor_setup(nol=False):
    from experiments.nor.experiment import NORExperiment
    from experiments.nol.experiment import NOLExperiment
    pad = 2 * 13.5
    if nol:
        objs = {"object_a": ("Stationary", "familiar", circle(510, 240, 32), circle(510, 240, 32 + pad)),
                "object_b": ("Moved", "novel", circle(770, 490, 32), circle(770, 490, 32 + pad))}
    else:
        objs = {"object_a": ("Object A", "familiar", circle(520, 240, 34), circle(520, 240, 34 + pad)),
                "object_b": ("Object B", "novel", rect(730, 450, 790, 510), rect(703, 423, 817, 537))}
    on = {k: {"name": n, "role": r, "footprint_norm": norm(f), "zone_norm": norm(z)}
          for k, (n, r, f, z) in objs.items()}
    exp = NOLExperiment() if nol else NORExperiment()
    return exp, SQUARE_OF, 13.5, True, {"arena": SQUARE_OF, "objects_norm": on, "angle_enabled": False}


def box_setup(cls_name, arena, ppc, params, w_cm, h_cm, nose=False, extra=None):
    from experiments.box import paradigms
    exp = getattr(paradigms, cls_name)()
    s = {"arena": arena, "box_params": params, "cage_w_cm": w_cm, "cage_h_cm": h_cm}
    s.update(extra or {})
    return exp, arena, ppc, nose, s


SETUPS = {
    "open_field": ("01_Open_Field", of_setup),
    "y_maze": ("02_Y_Maze", ym_setup),
    "novel_object": ("03_Novel_Object", lambda: nor_setup(False)),
    "elevated_plus": ("04_Elevated_Plus_Maze", epm_setup),
    "object_location": ("05_Object_Location", lambda: nor_setup(True)),
    "three_chamber": ("06_Three_Chamber", lambda: box_setup(
        "ThreeChamber", rect(190, 160, 1090, 560), 15.0,
        {"phase": "soc", "target_side": "L", "center_pct": 33, "layout": "h", "cup_pos": "mid",
         "cup_cm": 8.3, "sniff_cm": 3.0}, 60.0, 400 / 15.0, nose=True)),
    "place_preference": ("07_Place_Preference", lambda: box_setup(
        "PlacePreference", rect(170, 170, 1110, 550), 940 / 60.0,
        {"n_comp": 3, "neutral_pct": 19, "layout": "h", "paired": "A"}, 60.0, 380 / (940 / 60.0))),
    "light_dark": ("08_Light_Dark_Box", lambda: box_setup(
        "LightDark", rect(260, 140, 1020, 580), 760 / 45.0,
        {"dark_pct": 40, "dark_side": "R", "lost_dark": True}, 45.0, 440 / (760 / 45.0))),
    "zero_maze": ("09_Zero_Maze", lambda: box_setup(
        "ZeroMaze", rect(328, 48, 952, 672), 624 / 50.0,
        {"ring_pct": 21, "rotation": 0, "k_top": "closed", "k_right": "open", "k_bottom": "closed",
         "k_left": "open"}, 50.0, 50.0)),
    "t_maze": ("10_T_Maze", lambda: box_setup(
        "TMaze", rect(250, 150, 1030, 640), 780 / 70.0, {"orient": "down", "arm_pct": 17},
        70.0, 490 / (780 / 70.0))),
    "radial_arm": ("11_Radial_Arm_Maze", lambda: box_setup(
        "RadialMaze", rect(310, 30, 970, 690), 6.6,
        {"n_arms": 8, "arm_pct": 8, "hub_pct": 21, "rotation": 22.5, "baited": []}, 100.0, 100.0)),
    "water_maze": ("12_Water_Maze", lambda: box_setup(
        "WaterMaze", rect(310, 30, 970, 690), 5.5,
        {"target": "NE", "plat_dist": 56, "plat_cm": 9.5, "wall_pct": 10, "trial": "train"}, 120.0, 120.0)),
}


def track(video, arena, nose):
    """WIMM's tracker with its default settings (threshold 25, median
    background, 3-frame smoothing), the arena outline as the only input."""
    th = TrackerThread(video_path=video, arena=[tuple(map(float, p)) for p in arena], enable_nose=nose)
    out, err = [], []
    th.finished_tracking.connect(out.append)
    th.error.connect(err.append)
    th.run()
    if err or not out:
        raise RuntimeError(f"tracking failed: {err}")
    return out[0]


def readable(metrics):
    """WIMM's own readable measure names (as in its Summary sheet)."""
    from export.excel_export import _readable_result
    return _readable_result({"metrics": metrics, "bin_df": None})["metrics"]


def status(true, val):
    """exact / close (within 0.1 or 5 %) / differs; counts and text must be exact."""
    if isinstance(val, str) and val == "not reported":
        return "not reported by WIMM"
    if isinstance(true, (int, float)) and isinstance(val, (int, float)) and not isinstance(val, bool):
        if abs(val - true) < 1e-9 or round(val, 2) == round(true, 2):
            return "exact"
        if isinstance(true, int) and isinstance(val, int):
            return "differs"
        return "close" if abs(val - true) <= 0.1 or (true and abs(val - true) / abs(true) <= 0.05) else "differs"
    return "exact" if str(true) == str(val) else "differs"


def compare(bench_path, wimm, out_path, mapping, folder):
    rows = list(openpyxl.load_workbook(bench_path, read_only=True)["Benchmark"].iter_rows(values_only=True))[1:]
    out = openpyxl.Workbook()
    ws = out.active
    ws.title = "Comparison"
    ws.append(HEAD)
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="2F4F6F")
    fills = {"exact": "C6EFCE", "close": "FFEB9C", "differs": "FFC7CE"}
    done = []
    for sec, meas, true, _unit, _how in rows:
        m = mapping.get(meas, meas)
        key, fn = (m if isinstance(m, tuple) else (m, None))
        val = "not reported" if key is None else wimm.get(key, "not reported")
        if fn and true is not None:
            true = fn(true)
        diff = pct = None
        if isinstance(true, (int, float)) and isinstance(val, (int, float)) and not isinstance(val, bool):
            diff = round(val - true, 3)
            pct = round(100 * diff / true, 2) if true else None
        st = status(true, val)
        row = [sec, meas, true, str(val) if isinstance(val, (list, dict, bool)) or val is None else val,
               key if key in wimm else "", diff, pct, st]
        ws.append(row)
        if st in fills:
            ws.cell(ws.max_row, 8).fill = PatternFill("solid", fgColor=fills[st])
        done.append([folder] + row)
    for i, w in enumerate([24, 40, 16, 16, 40, 22, 12, 22], 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    out.save(out_path)
    return done


HEAD = ["Section", "Measure", "Benchmark (true)", "WIMM", "WIMM measure name", "Difference (WIMM - true)",
        "Difference %", "Status"]


def _epm_seq(s):
    letter = {"Closed arm top": "N", "Open arm right": "E", "Closed arm bottom": "S", "Open arm left": "W"}
    return "".join(letter[p] for p in s.split("-"))


_NO = None   # benchmark measure that WIMM does not report
MAPS = {
    "open_field": {"Entries into Center Zone (#)": "Center Zone Entries (#)",
                   "Latency to Center Zone (s)": "Latency to First Center Zone Entry (s)",
                   "Mean Visit in Center Zone (s)": "Mean Center Zone Dwell (s)",
                   "Entries into Periphery (#)": _NO, "Latency to Periphery (s)": _NO,
                   "Mean Visit in Periphery (s)": _NO},
    "y_maze": {"Mean Speed When Mobile (cm/s)": _NO, "Latency to Arm A (s)": _NO, "Latency to Arm B (s)": _NO,
               "Latency to Arm C (s)": _NO, "Spontaneous Alternations (#)": "Alternations (#)",
               "Alternate Arm Returns (#)": _NO, "Same Arm Returns (#)": "Same-Arm Returns (#)"},
    "elevated_plus": {"Mean Speed When Mobile (cm/s)": _NO, "Latency to Center (s)": _NO,
                      "Mean Visit in Center (s)": _NO,
                      "% Time Open (of arm time)": "% Arm Time in Open Arms",
                      "Open Arm Entries (#)": "Entries into Open Arms (#)",
                      "Closed Arm Entries (#)": "Entries into Closed Arms (#)",
                      "% Open Entries": "% Open-Arm Entries",
                      "Latency to First Open Entry (s)": "Latency to First Open-Arm Entry (s)",
                      "Entry Sequence": ("Arm Entry Sequence", _epm_seq)},
    "light_dark": {"Distance in Light (cm)": _NO},
}
for _b, _w in (("Open arm right", "Arm E"), ("Open arm left", "Arm W"),
               ("Closed arm top", "Arm N"), ("Closed arm bottom", "Arm S")):
    MAPS["elevated_plus"].update({f"Time in {_b} (s)": f"Time in {_w} (s)", f"% Time in {_b}": f"% Time in {_w}",
                                  f"Entries into {_b} (#)": f"Entries into {_w} (#)",
                                  f"Latency to {_b} (s)": _NO,
                                  f"Mean Visit in {_b} (s)": f"Mean Visit in {_w} (s)"})
for _k, _objs, _roles in (
        ("novel_object", (("Object 1 (cylinder)", "A"), ("Object 2 (block)", "B")),
         {"Novel exploration (s)": "Time at Novel Object (s)",
          "Familiar exploration (s)": "Time at Familiar Object (s)",
          "Preference % Novel": "% Preference for Novel Object"}),
        ("object_location", (("Stationary object", "A"), ("Moved object", "B")),
         {"Moved exploration (s)": "Moved time (s)", "Stationary exploration (s)": "Stationary time (s)",
          "Preference % Moved": "% Preference for Moved Object"})):
    _mp = dict(_roles)
    _mp.update({"Mean Speed When Mobile (cm/s)": _NO, "Total exploration (s)": _NO})
    for _b, _l in _objs:
        _mp.update({f"Time in {_b} (s)": f"Exploration of Object {_l} (s)", f"% Time in {_b}": _NO,
                    f"Entries into {_b} (#)": f"Exploration Bouts at Object {_l} (#)",
                    f"Latency to {_b} (s)": f"Latency to Object {_l} (s)",
                    f"Mean Visit in {_b} (s)": f"Mean Bout at Object {_l} (s)",
                    f"Exploration bouts {_b} (#)": f"Exploration Bouts at Object {_l} (#)"})
    MAPS[_k] = _mp
for _k in ("three_chamber", "place_preference", "light_dark", "zero_maze", "t_maze", "radial_arm", "water_maze"):
    MAPS.setdefault(_k, {})["Longest Pause (s)"] = _NO
for _k in SETUPS:
    MAPS.setdefault(_k, {})["Total Distance (px)"] = _NO


def run(key):
    folder, setup = SETUPS[key]
    d = os.path.join(HERE, folder)
    exp, arena, ppc, nose, extra = setup()
    s = dict(COMMON)
    s.update(extra)
    s.setdefault("arena", arena)
    results = track(os.path.join(d, f"{folder}.mp4"), arena, nose)
    metrics, raw_df, bin_df = exp.compute_metrics(results, s, 30.0, ppc)
    vc = dict(s)
    vc["px_per_cm"] = ppc
    export_results(metrics=metrics, raw_df=raw_df, output_path=os.path.join(d, f"{folder}_WIMM_results.xlsx"),
                   video_name=folder, arena=arena, video_size=(W, H), bin_df=bin_df,
                   metadata={"Animal ID": folder, "WIMM version": APP_VERSION}, write_csv=False,
                   video_config=exp.filter_video_config(vc) if hasattr(exp, "filter_video_config") else vc,
                   test_name=getattr(exp, "report_title", None) or f"{exp.name} Test")
    rows = compare(os.path.join(d, f"{folder}_benchmark.xlsx"), readable(metrics),
                   os.path.join(d, f"{folder}_comparison.xlsx"), MAPS.get(key, {}), folder)
    print("done", folder, f"detected {sum(1 for r in results if r.get('x') is not None)}/{len(results)}")
    return rows


def write_summary(all_rows, path=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Overview"
    ws.append(["Test", "Measures compared", "Exact", "Close (within 0.1 or 5 %)", "Differs",
               "Not reported by WIMM"])
    for t in dict.fromkeys(r[0] for r in all_rows):
        st = [r[8] for r in all_rows if r[0] == t]
        ws.append([t, sum(1 for s in st if s != "not reported by WIMM"), st.count("exact"), st.count("close"),
                   st.count("differs"), st.count("not reported by WIMM")])
    fills = {"exact": "C6EFCE", "close": "FFEB9C", "differs": "FFC7CE"}
    sheets = [ws]
    for t in dict.fromkeys(r[0] for r in all_rows):           # one sheet per experiment
        w = wb.create_sheet(t[:31])
        w.append(HEAD)
        for r in all_rows:
            if r[0] == t:
                w.append(r[1:])
                if r[8] in fills:
                    w.cell(w.max_row, 8).fill = PatternFill("solid", fgColor=fills[r[8]])
        for i, wd in enumerate([24, 40, 16, 16, 40, 22, 12, 22], 1):
            w.column_dimensions[openpyxl.utils.get_column_letter(i)].width = wd
        sheets.append(w)
    ws3 = wb.create_sheet("Differs")
    ws3.append(["Test"] + HEAD)
    for r in all_rows:
        if r[8] == "differs":
            ws3.append(r)
    for w in (ws, ws3):
        for i in range(1, 10):
            w.column_dimensions[openpyxl.utils.get_column_letter(i)].width = 22
    for w in sheets + [ws3]:
        for c in w[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="2F4F6F")
        w.freeze_panes = "A2"
    wb.save(path or os.path.join(HERE, "WIMM_vs_benchmark_summary.xlsx"))


def saved_rows():
    """Comparison rows of every test, read back from each folder's file
    (so a run of one test still gives a complete summary)."""
    rows = []
    for folder, _ in SETUPS.values():
        f = os.path.join(HERE, folder, f"{folder}_comparison.xlsx")
        if os.path.exists(f):
            ws = openpyxl.load_workbook(f, read_only=True)["Comparison"]
            rows += [[folder] + list(r) for r in ws.iter_rows(min_row=2, values_only=True)]
    return rows


if __name__ == "__main__":
    for k in sys.argv[1:] or list(SETUPS):
        run(k)
    write_summary(saved_rows())


