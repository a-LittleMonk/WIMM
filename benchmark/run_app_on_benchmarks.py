"""Run every benchmark video through the WIMM app's own Run path (the batch
screen: load the video, apply its settings, Run -> track -> results ->
backup Excel with the app's graphs), with the app window hidden.

Everything not listed in OVERRIDES keeps the app's own default (tracker
settings, smoothing, graph style ...). Settings come from your app's
settings file (settings/mice_tracker.json); it is read, never written.

    <WIMM .venv python> run_app_on_benchmarks.py [test_key ...]

Per test folder: <test>_APP_results.xlsx (the app's export), App graphs/
(the app's graph PNGs) and <test>_APP_comparison.xlsx. Summary of all
tests: APP_vs_benchmark_summary.xlsx (one sheet per experiment).
"""
import copy
import json
import math
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WIMM_DIR = os.path.abspath(os.environ.get("WIMM_DIR") or os.path.join(HERE, ".."))  # WIMM source: the repo this folder sits in
sys.path.insert(0, WIMM_DIR)
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import openpyxl                                    # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox   # noqa: E402

APP = QApplication.instance() or QApplication([])

import run_wimm_on_benchmarks as R                 # noqa: E402  (zone shapes + comparison)
from experiments import registry                   # noqa: E402

W, H = 1280, 720
POPUPS = []


def _popup(kind):
    def f(_parent, title, text, *a, **k):
        POPUPS.append(f"{kind}: {title}: {text}")
        return QMessageBox.Ok
    return f


for _k in ("information", "warning", "critical", "question"):
    setattr(QMessageBox, _k, staticmethod(_popup(_k)))
import core.app_paths as _ap                       # noqa: E402
_ap.notice = lambda msg, *a, **k: POPUPS.append(f"notice: {msg}")


def n(p):
    return (p[0] / W, p[1] / H)


def nl(pts):
    return [n(p) for p in pts]


def calib(p1, p2, cm):
    return {"calib_mode": "manual", "calib_p1": n(p1), "calib_p2": n(p2), "calib_cm": cm}


COMMON = {"movement_thr": 2.0, "min_dwell_s": 0.0, "bin_size": 5.0}


def of_like(extra):
    d = {"arena": nl(R.SQUARE_OF), "arena_define_mode": "polygon", "cage_shape": "square",
         "cage_w_cm": 40.0, "cage_h_cm": 40.0}
    d.update(calib((370, 90), (910, 90), 40.0))
    d.update(extra)
    return d


def nor_objects(nol):
    if nol:
        o = {"object_a": ("Stationary", "familiar", "circle", 4.7, (510, 240)),
             "object_b": ("Moved", "novel", "circle", 4.7, (770, 490))}
    else:
        o = {"object_a": ("Object A", "familiar", "circle", 5.0, (520, 240)),
             "object_b": ("Object B", "novel", "square", 4.4, (760, 480))}
    _exp, _a, _p, _nose, s = R.nor_setup(nol)
    objs, objs_norm = {}, {}
    for k, (name, role, shape, size, c) in o.items():
        st = {"name": name, "role": role, "shape": shape, "size_cm": size, "padding_cm": 2.0,
              "center_norm": n(c), "custom_geom_norm": []}
        objs[k] = dict(st)
        objs_norm[k] = dict(st, footprint_norm=s["objects_norm"][k]["footprint_norm"],
                            zone_norm=s["objects_norm"][k]["zone_norm"])
    return {"objects": objs, "objects_norm": objs_norm, "angle_enabled": False}


def ym():
    _e, _o, _p, _n, s = R.ym_setup()
    a = math.radians
    eps = [(640 + 300 * math.cos(a(t)), 410 + 300 * math.sin(a(t))) for t in (-90, 150, 30)]
    d = {"arms_norm": s["arms_norm"], "neutral_norm": s["neutral_norm"], "ym_hub": n((640, 410)),
         "ym_endpoints": nl(eps), "entry_rule": "body"}
    d.update(calib((597, 110), (683, 110), 10.0))
    return d


def epm():
    _e, _o, _p, _n, s = R.epm_setup()
    d = {"arms_norm": s["arms_norm"], "center_norm": s["center_norm"], "arm_kinds": s["arm_kinds"],
         "epm_hub": n((640, 360)), "epm_endpoints": nl([(640, 40), (640, 680), (970, 360), (310, 360)]),
         "epm_perspective": False, "entry_rule": "body"}
    d.update(calib((310, 360), (970, 360), 50.0))
    return d


def box(key, extra_assign=None):
    _exp, arena, _ppc, _nose, s = R.SETUPS[key][1]()
    p = dict(s["box_params"])
    assign = {k: p.pop(k) for k in list(p) if k in (extra_assign or ())}
    x0, y0 = arena[0]
    x1 = arena[1][0]
    d = {"arena": nl(arena), "arena_define_mode": "polygon", "box_params": p, "box_assign": assign,
         "cage_w_cm": s["cage_w_cm"], "cage_h_cm": s["cage_h_cm"],
         "cage_shape": "square" if s["cage_w_cm"] == s["cage_h_cm"] else "rectangle"}
    d.update(calib((x0, y0), (x1, y0), s["cage_w_cm"]))
    return d


# test key -> (app experiment key, settings that differ from the app's defaults)
OVERRIDES = {
    "open_field": ("open_field", lambda: of_like({"zone_mode": "center_zone", "center_pct": 50})),
    "y_maze": ("y_maze", ym),
    "novel_object": ("nor", lambda: of_like(nor_objects(False))),
    "elevated_plus": ("epm", epm),
    "object_location": ("nol", lambda: of_like(nor_objects(True))),
    "three_chamber": ("three_chamber", lambda: box("three_chamber", ("target_side",))),
    "place_preference": ("cpp", lambda: box("place_preference", ("paired",))),
    "light_dark": ("light_dark", lambda: box("light_dark")),
    "zero_maze": ("zero_maze", lambda: box("zero_maze")),
    "t_maze": ("t_maze", lambda: box("t_maze")),
    "radial_arm": ("radial_maze", lambda: box("radial_arm", ("baited",))),
    "water_maze": ("water_maze", lambda: box("water_maze", ("target", "trial"))),
}

GEOMETRY_KEYS = ("arena", "arms_norm", "center_norm", "objects_norm", "box_params", "box_assign",
                 "calib_p1", "calib_p2", "calib_cm", "min_dwell_s", "movement_thr")


def app_config(backup):
    path = os.path.join(WIMM_DIR, "settings", "mice_tracker.json")
    cfg = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    cfg = copy.deepcopy(cfg)
    cfg["backup_folder"] = backup                   # the app's backup goes here, not your folder
    return cfg


def run(key, backup):
    folder = R.SETUPS[key][0]
    d = os.path.join(HERE, folder)
    video = os.path.join(d, f"{folder}.mp4")
    app_key, make = OVERRIDES[key]
    bt = registry.tab_class(app_key)(app_config(backup))
    bt._add_video(video)                            # loads it into the app's screen
    snap = bt.embedded_tab.snapshot_settings()      # the app's defaults for this video
    want = dict(COMMON)
    want.update(make())
    snap.update(want)
    snap["metadata"] = dict(snap.get("metadata") or {}, **{"Animal ID": folder})
    bt.video_settings[video] = snap
    bt._embedded_loaded_path = None
    bt._load_into_embedded(video)                   # the screen applies them, like reopening a video
    et = bt.embedded_tab
    if hasattr(et, "spin_min_dwell"):               # typed into the box, as a user would
        et.spin_min_dwell.setValue(COMMON["min_dwell_s"])
    # The low-detection help window can't open with the app hidden: note it instead.
    bt._show_run_warnings = lambda: POPUPS.append(
        f"run warning (low detection etc.): {getattr(bt, '_low_detection', [])}")
    POPUPS.clear()
    bt._run_video(video)                            # = pressing Run on the row
    used = bt.video_settings[video]
    # objects_norm is rebuilt by the app from each object's centre / size / padding
    lost = [k for k in GEOMETRY_KEYS if k in want and k != "objects_norm" and used.get(k) != want[k]
            and not (k == "min_dwell_s" and used.get(k) is None)]   # OF has no min dwell
    data = bt._completed_data.get(video)
    if not data:
        raise RuntimeError(f"{folder}: the app produced no result. {POPUPS} {bt.lbl_status.text()}")
    src = os.path.join(backup, f"{folder}_{getattr(bt.embedded_tab.experiment, 'file_key', None) or bt.embedded_tab.experiment.key}.xlsx")
    dst = os.path.join(d, f"{folder}_APP_results.xlsx")
    shutil.copyfile(src, dst)
    gdir = os.path.join(d, "App graphs")
    shutil.rmtree(gdir, ignore_errors=True)
    os.makedirs(gdir)
    for name, png in (data.get("graph_pngs") or {}).items():
        with open(os.path.join(gdir, f"{name}.png"), "wb") as f:
            f.write(png)
    ws = openpyxl.load_workbook(dst, read_only=True)["Summary"]
    vals = {}
    for r in ws.iter_rows(values_only=True):
        if r and r[0] is not None and len(r) > 1:
            vals.setdefault(str(r[0]), r[1])
    rows = R.compare(os.path.join(d, f"{folder}_benchmark.xlsx"), vals,
                     os.path.join(d, f"{folder}_APP_comparison.xlsx"), R.MAPS.get(key, {}), folder)
    used_report = {k: used.get(k) for k in ("smooth_window", "smooth", "threshold", "model", "min_dwell_s",
                                            "movement_thr", "enable_nose", "calib_mode")}
    print("done", folder, "| graphs:", len(data.get("graph_pngs") or {}), "| settings used:", used_report,
          "| zones not kept:", lost or "none", "| pop-ups:", POPUPS or "none")
    return rows


def saved_rows():
    rows = []
    for folder, _ in R.SETUPS.values():
        f = os.path.join(HERE, folder, f"{folder}_APP_comparison.xlsx")
        if os.path.exists(f):
            ws = openpyxl.load_workbook(f, read_only=True)["Comparison"]
            rows += [[folder] + list(r) for r in ws.iter_rows(min_row=2, values_only=True)]
    return rows


TRAJ_PNG = "Trajectory - benchmark vs app.png"


def trajectory_png(key):
    """True path and the app's tracked path, drawn on the video's first frame."""
    import cv2
    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = "Arial"
    folder = R.SETUPS[key][0]
    d = os.path.join(HERE, folder)
    ppc = R.SETUPS[key][1]()[2]
    b = pd.read_excel(os.path.join(d, f"{folder}_benchmark.xlsx"), sheet_name="Per frame")
    a = pd.read_excel(os.path.join(d, f"{folder}_APP_results.xlsx"), sheet_name="Raw Data")
    bx, by = b["Body X (px)"].to_numpy(float), b["Body Y (px)"].to_numpy(float)
    ax_, ay_ = a["X (px)"].to_numpy(float), a["Y (px)"].to_numpy(float)
    err = np.hypot(ax_ - bx, ay_ - by)
    seen = ~np.isnan(err)
    cap = cv2.VideoCapture(os.path.join(d, f"{folder}.mp4"))
    ok, frame = cap.read()
    cap.release()
    fig, ax = plt.subplots(figsize=(9, 5.6))
    if ok:
        ax.imshow(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    ax.plot(bx, by, color="#1f77b4", lw=2.4, alpha=0.8, label="Benchmark (true path)")
    ax.plot(ax_, ay_, color="#d62728", lw=1.0, ls="--", label="WIMM app (tracked)")
    ax.plot(bx[0], by[0], "o", color="#2ca02c", ms=7, label="start")
    xs = np.r_[bx, ax_[seen]]
    ys = np.r_[by, ay_[seen]]
    ax.set_xlim(max(0, xs.min() - 90), min(W, xs.max() + 90))
    ax.set_ylim(min(H, ys.max() + 90), max(0, ys.min() - 90))
    ax.set_axis_off()
    txt = (f"position error: median {np.median(err[seen]):.1f} px ({np.median(err[seen]) / ppc:.2f} cm), "
           f"max {err[seen].max():.1f} px")
    if (~seen).any():
        txt += f" · mouse not found on {int((~seen).sum())} of {len(err)} frames"
    ax.set_title(f"{folder}: trajectory\n{txt}", fontsize=10)
    ax.legend(loc="lower right", fontsize=8, framealpha=0.85)
    out = os.path.join(d, TRAJ_PNG)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def all_trajectories_png(out=None, dpi=140):
    """One figure: every experiment's true path vs the app's, one legend."""
    import cv2
    import numpy as np
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    plt.rcParams.update({"font.family": "Arial", "svg.fonttype": "path", "pdf.fonttype": 42})
    keys = [k for k, (f, _) in R.SETUPS.items()
            if os.path.exists(os.path.join(HERE, f, f"{f}_APP_results.xlsx"))]
    cols = 4
    rows = math.ceil(len(keys) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(4.2 * cols, 3.6 * rows))
    for ax in axes.flat:
        ax.set_axis_off()
    for ax, key in zip(axes.flat, keys):
        folder = R.SETUPS[key][0]
        d = os.path.join(HERE, folder)
        b = pd.read_excel(os.path.join(d, f"{folder}_benchmark.xlsx"), sheet_name="Per frame")
        a = pd.read_excel(os.path.join(d, f"{folder}_APP_results.xlsx"), sheet_name="Raw Data")
        bx, by = b["Body X (px)"].to_numpy(float), b["Body Y (px)"].to_numpy(float)
        ax_, ay_ = a["X (px)"].to_numpy(float), a["Y (px)"].to_numpy(float)
        cap = cv2.VideoCapture(os.path.join(d, f"{folder}.mp4"))
        ok, frame = cap.read()
        cap.release()
        if ok:
            ax.imshow(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        ax.plot(bx, by, color="#1f77b4", lw=2.0, alpha=0.8)
        ax.plot(ax_, ay_, color="#d62728", lw=0.9, ls="--")
        ax.plot(bx[0], by[0], "o", color="#2ca02c", ms=5)
        arena = np.array(R.SETUPS[key][1]()[1], float)     # whole apparatus in view
        ax.set_xlim(max(0, arena[:, 0].min() - 20), min(W, arena[:, 0].max() + 20))
        ax.set_ylim(min(H, arena[:, 1].max() + 20), max(0, arena[:, 1].min() - 20))
        ax.set_title(folder.split("_", 1)[1].replace("_", " "), fontsize=12)
    handles = [Line2D([], [], color="#1f77b4", lw=2.4, label="Benchmark (true path)"),
               Line2D([], [], color="#d62728", lw=1.2, ls="--", label="WIMM app (tracked)"),
               Line2D([], [], marker="o", color="#2ca02c", ls="", label="Start")]
    fig.legend(handles=handles, loc="lower center", ncol=3, fontsize=12, frameon=False)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    out = out or os.path.join(HERE, "All trajectories - benchmark vs app.png")
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out


def _kind(measure):
    m = measure.lower()
    if "speed" in m and "(cm/s)" in m:
        return "Speed (cm/s)"
    if "(cm)" in m:
        return "Distance (cm)"
    if "(#)" in m:
        return "Counts (#)"
    if m.endswith("(s)"):
        return "Time (s)"
    return "Percentages and indices"


EXP_COLORS = ["1F77B4", "FF7F0E", "2CA02C", "D62728", "9467BD", "8C564B",
              "E377C2", "7F7F7F", "BCBD22", "17BECF", "393B79", "AD494A"]
KINDS = ["Time (s)", "Counts (#)", "Distance (cm)", "Speed (cm/s)", "Percentages and indices"]


def add_graphs_sheet(summary, rows):
    """'Graphs' sheet: native Excel charts, each beside the data it plots."""
    from openpyxl.chart import Reference, ScatterChart, Series
    from openpyxl.styles import Font, PatternFill
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)   # noqa: E731
    pts = [(r[0].split("_", 1)[1].replace("_", " "), r[2], r[3], r[4], r[7])
           for r in rows if num(r[3]) and num(r[4])]
    exps = list(dict.fromkeys(p[0] for p in pts))
    wb = openpyxl.load_workbook(summary)
    if "Graphs" in wb.sheetnames:
        del wb["Graphs"]
    ws = wb.create_sheet("Graphs", 2)
    head_font, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="2F4F6F")

    def header(r, cols):
        for j, t in enumerate(cols, 1):
            c = ws.cell(r, j, t)
            c.font, c.fill = head_font, head_fill

    for j, w in enumerate([18, 40, 14, 14, 14], 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(j)].width = w
    row = 1
    # 1) agreement: one scatter chart per kind of measure, one series per experiment
    for kind in KINDS:
        sub = [p for p in pts if _kind(p[1]) == kind]
        if not sub:
            continue
        ws.cell(row, 1, f"Agreement — {kind}").font = Font(bold=True, size=13)
        header(row + 1, ["Experiment", "Measure", "Benchmark (true)", "WIMM app"])
        r0 = row + 2
        ch = ScatterChart()
        ch.title = f"Benchmark vs WIMM — {kind}"
        ch.x_axis.title, ch.y_axis.title = "Benchmark (true)", "WIMM app"
        ch.x_axis.delete = ch.y_axis.delete = False       # show the axis numbers
        ch.legend.position = "b"
        ch.legend.overlay = False
        ch.x_axis.crosses = ch.y_axis.crosses = "min"      # axes at the bottom / left edge
        ch.height, ch.width = 11, 18
        r = r0
        for k, e in enumerate(exps):
            es = [p for p in sub if p[0] == e]
            if not es:
                continue
            start = r
            for p in es:
                ws.cell(r, 1, e), ws.cell(r, 2, p[1]), ws.cell(r, 3, p[2]), ws.cell(r, 4, p[3])
                r += 1
            s = Series(Reference(ws, min_col=4, min_row=start, max_row=r - 1),
                       Reference(ws, min_col=3, min_row=start, max_row=r - 1), title=e)
            s.marker.symbol, s.marker.size = "circle", 6
            s.marker.graphicalProperties.solidFill = EXP_COLORS[k % len(EXP_COLORS)]
            s.marker.graphicalProperties.line.solidFill = EXP_COLORS[k % len(EXP_COLORS)]
            s.graphicalProperties.line.noFill = True
            ch.series.append(s)
        lo = min(min(p[2], p[3]) for p in sub)
        hi = max(max(p[2], p[3]) for p in sub)
        ws.cell(r, 2, "Perfect agreement line"), ws.cell(r, 3, lo), ws.cell(r, 4, lo)
        ws.cell(r + 1, 2, "Perfect agreement line"), ws.cell(r + 1, 3, hi), ws.cell(r + 1, 4, hi)
        line = Series(Reference(ws, min_col=4, min_row=r, max_row=r + 1),
                      Reference(ws, min_col=3, min_row=r, max_row=r + 1), title="Perfect agreement")
        line.marker.symbol = "none"
        line.graphicalProperties.line.solidFill = "7F7F7F"
        line.graphicalProperties.line.dashStyle = "dash"
        ch.series.append(line)
        ws.add_chart(ch, f"G{row}")
        row = max(r + 2, row + 21) + 2
    # 2) % difference per measure, grouped by experiment (dots), with ±5 % limits
    ws.cell(row, 1, "Error — % difference from the true value, per measure").font = Font(bold=True, size=13)
    ws.cell(row + 1, 1, "x = experiment number (1-12, see the Experiment column); y = % difference. "
                        "Measures with a true value of 0 have no %.")
    header(row + 2, ["Experiment", "Measure", "Experiment #", "% difference"])
    ch = ScatterChart()
    ch.title = "% difference (WIMM − true) per measure, by experiment"
    ch.x_axis.title, ch.y_axis.title = "Experiment # (see legend)", "% difference"
    ch.x_axis.delete = ch.y_axis.delete = False
    ch.x_axis.scaling.min, ch.x_axis.scaling.max, ch.x_axis.majorUnit = 0, len(exps) + 1, 1
    ch.legend.position = "b"
    ch.legend.overlay = False
    ch.x_axis.crosses = ch.y_axis.crosses = "min"          # experiment numbers along the bottom
    ch.height, ch.width = 12, 24
    r = row + 3
    for k, e in enumerate(exps):
        es = [p for p in pts if p[0] == e and num(p[4])]
        if not es:
            continue
        start = r
        for p in es:
            ws.cell(r, 1, e), ws.cell(r, 2, p[1]), ws.cell(r, 3, k + 1), ws.cell(r, 4, p[4])
            r += 1
        s = Series(Reference(ws, min_col=4, min_row=start, max_row=r - 1),
                   Reference(ws, min_col=3, min_row=start, max_row=r - 1), title=f"{k + 1} {e}")
        s.marker.symbol, s.marker.size = "circle", 6
        s.marker.graphicalProperties.solidFill = EXP_COLORS[k % len(EXP_COLORS)]
        s.marker.graphicalProperties.line.solidFill = EXP_COLORS[k % len(EXP_COLORS)]
        s.graphicalProperties.line.noFill = True
        ch.series.append(s)
    for v, label in ((5, "+5 % limit"), (-5, "-5 % limit")):
        ws.cell(r, 2, label), ws.cell(r, 3, 0.5), ws.cell(r, 4, v)
        ws.cell(r + 1, 2, label), ws.cell(r + 1, 3, len(exps) + 0.5), ws.cell(r + 1, 4, v)
        s = Series(Reference(ws, min_col=4, min_row=r, max_row=r + 1),
                   Reference(ws, min_col=3, min_row=r, max_row=r + 1), title=label)
        s.marker.symbol = "none"
        s.graphicalProperties.line.solidFill = "D62728"
        s.graphicalProperties.line.dashStyle = "dash"
        ch.series.append(s)
        r += 2
    ws.add_chart(ch, f"G{row}")
    wb.save(summary)


def embed(xlsx, sheet, png, anchor="J2", width=720):
    from openpyxl.drawing.image import Image as XLImage
    wb = openpyxl.load_workbook(xlsx)
    img = XLImage(png)
    s = width / img.width
    img.width, img.height = int(img.width * s), int(img.height * s)
    wb[sheet].add_image(img, anchor)
    wb.save(xlsx)


def add_trajectories(summary):
    for key, (folder, _) in R.SETUPS.items():
        if not os.path.exists(os.path.join(HERE, folder, f"{folder}_APP_results.xlsx")):
            continue
        png = trajectory_png(key)
        embed(os.path.join(HERE, folder, f"{folder}_APP_comparison.xlsx"), "Comparison", png)
        embed(summary, folder[:31], png)
    wb = openpyxl.load_workbook(summary)                 # one sheet with every experiment
    wb.create_sheet("All trajectories", 1)
    wb.save(summary)
    embed(summary, "All trajectories", all_trajectories_png(), anchor="A1", width=1500)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--pictures-only"]
    backup = tempfile.mkdtemp(prefix="wimm_app_backup_")
    if "--pictures-only" not in sys.argv:          # else: keep the app results, redo pictures + files
        for k in args or list(OVERRIDES):
            run(k, backup)
    for k in args or list(OVERRIDES):                # comparison files without pictures, then add them
        folder = R.SETUPS[k][0]
        d = os.path.join(HERE, folder)
        if "--pictures-only" in sys.argv and os.path.exists(os.path.join(d, f"{folder}_APP_results.xlsx")):
            ws = openpyxl.load_workbook(os.path.join(d, f"{folder}_APP_results.xlsx"), read_only=True)["Summary"]
            vals = {}
            for r in ws.iter_rows(values_only=True):
                if r and r[0] is not None and len(r) > 1:
                    vals.setdefault(str(r[0]), r[1])
            R.compare(os.path.join(d, f"{folder}_benchmark.xlsx"), vals,
                      os.path.join(d, f"{folder}_APP_comparison.xlsx"), R.MAPS.get(k, {}), folder)
    summary = os.path.join(HERE, "APP_vs_benchmark_summary.xlsx")
    R.write_summary(saved_rows(), summary)
    add_trajectories(summary)
    add_graphs_sheet(summary, saved_rows())
