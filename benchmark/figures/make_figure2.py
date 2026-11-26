"""Figure 2: WIMM app vs synthetic ground truth (4 agreement panels).

Reads the per-paradigm sheets of the benchmark summary workbook (one point per WIMM value).
- A Time, B Distance, C Counts, D Speed: every row of each section, nothing dropped.
- Light-Dark Box drawn hollow (animal not detectable in the dark half), max speed as
  triangles; both are included in n and in the error summary. One shared legend. Saves PDF, SVG and 600 dpi PNG next to this script.
"""
import os

import matplotlib.pyplot as plt
import openpyxl
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "APP_vs_benchmark_summary.xlsx")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Figure2_validation")
EXCLUDED = "Light Dark Box"

EXPS = ["Open Field", "Y Maze", "Novel Object", "Elevated Plus Maze", "Object Location",
        "Three Chamber", "Place Preference", "Light Dark Box", "Zero Maze", "T Maze",
        "Radial Arm Maze", "Water Maze"]
COLORS = dict(zip(EXPS, ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b",
                         "#e377c2", "#7f7f7f", "#bcbd22", "#17becf", "#000000", "#b8860b"]))

PANELS = [  # (letter, title, sheet section, keep measure?)
    ("A", "Time (s)", "Time (s)", lambda m: True),
    ("B", "Distance (cm)", "Distance (cm)", lambda m: True),
    ("C", "Counts", "Counts (#)", lambda m: True),
    ("D", "Speed (cm/s)", "Speed (cm/s)", lambda m: True),
]


UNITS = [("(cm/s)", "Speed (cm/s)"), ("(cm)", "Distance (cm)"), ("(#)", "Counts (#)"), ("(s)", "Time (s)")]


def read_sections(path):
    """Per-paradigm sheets, one point per WIMM exported value: the sheets list some WIMM values
    under two benchmark names (e.g. NOR entries = exploration bouts), which must not be plotted twice."""
    wb = openpyxl.load_workbook(path, data_only=True)
    data = {sec: [] for _, sec in UNITS}
    for ws in wb.worksheets:
        if not ws.title[:2].isdigit():
            continue
        exp, seen = ws.title[3:].replace("_", " "), set()
        for _, meas, bench, app, wimm_name, *_ in ws.iter_rows(min_row=2, values_only=True):
            if not (isinstance(bench, (int, float)) and isinstance(app, (int, float))) or wimm_name in seen:
                continue
            seen.add(wimm_name)
            sec = next((s for u, s in UNITS if meas.endswith(u)), None)
            if sec:
                data[sec].append((exp, meas, float(bench), float(app)))
    assert [len(data[s]) for _, s in UNITS] == [32, 14, 75, 200], [len(data[s]) for _, s in UNITS]
    return data


def main():
    data = read_sections(SRC)
    plt.rcParams.update({"font.family": "Arial", "font.size": 10, "axes.linewidth": 0.8,
                         "svg.fonttype": "path", "pdf.fonttype": 42})
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 7.6))
    for ax, (letter, title, sec, keep) in zip(axes.flat, PANELS):
        rows = [r for r in data[sec] if keep(r[1])]
        assert rows, f"no rows for {sec}"
        hi = max(max(b, a) for _, _, b, a in rows) * 1.08
        ax.plot([0, hi], [0, hi], "--", color="0.5", lw=0.8, zorder=1)
        for exp, meas, b, a in rows:
            c = COLORS[exp]
            hollow = exp == EXCLUDED
            ax.scatter(b, a, s=26, zorder=2, linewidths=0.9, marker="^" if "Max" in meas else "o",
                       facecolors="none" if hollow else c, edgecolors=c)
        ax.set_xlim(0, hi)
        ax.set_ylim(0, hi)
        ax.set_aspect("equal")
        if sec == "Counts (#)":  # whole-number ticks for counts
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.set_xlabel("Benchmark", fontsize=11, fontweight="bold")
        ax.set_ylabel("WIMM", fontsize=11, fontweight="bold")
        ax.spines[["top", "right"]].set_visible(False)
        ax.text(-0.2, 1.06, letter, transform=ax.transAxes, fontsize=15, fontweight="bold")

    handles = [Line2D([], [], ls="", marker="o", ms=6, color=COLORS[e],
                      markerfacecolor="none" if e == EXCLUDED else COLORS[e],
                      label=e + (" (not detectable in dark)" if e == EXCLUDED else ""))
               for e in EXPS]
    handles.append(Line2D([], [], ls="", marker="^", ms=6, color="0.3", label="Maximum speed"))
    handles.append(Line2D([], [], ls="--", color="0.5", label="Perfect agreement"))
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, fontsize=9.5,
               bbox_to_anchor=(0.5, 0.0))
    fig.tight_layout(rect=(0, 0.15, 1, 1), h_pad=2.0, w_pad=2.5)
    for ext, kw in (("png", {"dpi": 600}), ("svg", {}), ("pdf", {})):
        fig.savefig(f"{OUT}.{ext}", **kw)
    # second SVG with live (editable) text; PowerPoint renders its letter spacing slightly off
    with plt.rc_context({"svg.fonttype": "none"}):
        fig.savefig(f"{OUT}_editable.svg")
    print("saved", OUT + ".pdf/.svg/.png")


if __name__ == "__main__":
    main()
