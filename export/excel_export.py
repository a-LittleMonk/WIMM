import os
from io import BytesIO
from typing import Optional, Tuple, Dict
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from core import units


def _center_cell(cell):
    """Force horizontal=center on a value cell, regardless of content
    type. Used at every label/value write site so text values look
    centered just like numeric ones (without disturbing the bold
    left-aligned label in the column beside them)."""
    cell.alignment = Alignment(horizontal="center", vertical="center")


def _center_align_numbers(ws):
    """Center-align every cell whose value is numeric. Strings, None,
    and booleans are left untouched so existing left-aligned headers
    and labels keep their original look."""
    for row in ws.iter_rows():
        for cell in row:
            v = cell.value
            if isinstance(v, bool):
                continue
            if not isinstance(v, (int, float)):
                continue
            old = cell.alignment
            cell.alignment = Alignment(
                horizontal="center",
                vertical=(old.vertical if old and old.vertical else "center"),
                wrap_text=(old.wrap_text if old else None),
                text_rotation=(old.text_rotation if old else 0),
                indent=(old.indent if old else 0),
            )


def _center_align_workbook(wb):
    """Apply numeric center-alignment to every sheet in a workbook.
    Called just before save so every exporter benefits from one place."""
    for ws in wb.worksheets:
        _center_align_numbers(ws)


def export_results(
    metrics: dict,
    raw_df: pd.DataFrame,
    output_path: str,
    video_name: str,
    arena: Optional[Tuple],
    video_size: Optional[Tuple[int, int]],
    graph_images: Optional[Dict[str, bytes]] = None,
    bin_df: Optional[pd.DataFrame] = None,
    metadata: Optional[dict] = None,
    write_csv: bool = True,
    video_config: Optional[dict] = None,
    all_units: bool = True,
    test_name: str = "Open Field",
):
    # Every distance / speed / time value is written in all scales side
    # by side (cm, mm, m · cm/s … km/h · s, min) so the examiner can pick.
    if all_units:
        base_len = units.base_length_unit(metrics)
        metrics = units.expand_metrics(metrics, base_len)
        raw_df = units.expand_df(raw_df, base_len)
        bin_df = units.expand_df(bin_df, base_len)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary_df = pd.DataFrame(
            list(metrics.items()), columns=["Metric", "Value"]
        )
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        if metadata:
            meta_items = [(k, v) for k, v in metadata.items() if v not in (None, "", [])]
            if meta_items:
                pd.DataFrame(meta_items, columns=["Field", "Value"]).to_excel(
                    writer, sheet_name="Metadata", index=False
                )
        raw_df.to_excel(writer, sheet_name="Raw Data", index=False)
        if bin_df is not None and not bin_df.empty:
            bin_df.to_excel(writer, sheet_name="Time Bins", index=False)

    wb = load_workbook(output_path)
    _style_summary(wb["Summary"], video_name, test_name)
    if "Metadata" in wb.sheetnames:
        _style_meta(wb["Metadata"])
    _style_raw(wb["Raw Data"])
    if "Time Bins" in wb.sheetnames:
        _style_raw(wb["Time Bins"])

    if video_config:
        _write_video_config_sheet(wb, video_config, video_size, all_units)

    if not graph_images and video_size:
        x_vals = raw_df["X (px)"].dropna().values
        y_vals = raw_df["Y (px)"].dropna().values
        if len(x_vals) > 1:
            graph_images = {
                "Trajectory": _trajectory_png(x_vals, y_vals, arena, video_size),
                "Heatmap":    _heatmap_png(x_vals, y_vals, arena, video_size),
            }

    if graph_images:
        ws = wb.create_sheet("Graphs")
        ws.column_dimensions["A"].width = 4
        bold = Font(bold=True, size=12)
        row = 1
        for name, png in graph_images.items():
            ws.cell(row=row, column=2, value=name).font = bold
            row += 1
            img = XLImage(BytesIO(png))
            scale = 600.0 / max(img.width, 1)
            if scale < 1:
                img.width = int(img.width * scale)
                img.height = int(img.height * scale)
            ws.add_image(img, f"B{row}")
            row += int(img.height / 18) + 3

    _center_align_workbook(wb)
    wb.save(output_path)

    if write_csv:
        base = os.path.splitext(output_path)[0]
        try:
            raw_df.to_csv(base + "_raw.csv", index=False)
            pd.DataFrame(list(metrics.items()), columns=["Metric", "Value"]).to_csv(
                base + "_summary.csv", index=False
            )
            if bin_df is not None and not bin_df.empty:
                bin_df.to_csv(base + "_bins.csv", index=False)
            if metadata:
                pd.DataFrame(
                    [(k, v) for k, v in metadata.items() if v not in (None, "", [])],
                    columns=["Field", "Value"],
                ).to_csv(base + "_metadata.csv", index=False)
            if video_config:
                pd.DataFrame(
                    _video_config_rows(video_config, video_size, all_units),
                    columns=["Setting", "Value"],
                ).to_csv(base + "_video_config.csv", index=False)
        except OSError as e:
            # Usually a CSV left open in Excel (Windows locks it). Say so
            # instead of silently keeping the old, out-of-date CSV.
            raise OSError(
                f"The Excel file was saved, but a CSV copy could not be "
                f"written: {e}. Close it if it is open and export again."
            ) from e


def _style_meta(ws):
    bold = Font(bold=True)
    for cell in ws[1]:
        cell.font = bold
    # Center the Value column (B). Field labels in col A stay default.
    for r in range(2, ws.max_row + 1):
        _center_cell(ws.cell(row=r, column=2))
    for col in ws.columns:
        length = max((len(str(c.value or "")) for c in col), default=0)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(length + 4, 40)


def _style_summary(ws, video_name: str, test_name: str = "Open Field"):
    blue = PatternFill("solid", fgColor="1A6EA8")
    white_bold = Font(color="FFFFFF", bold=True, size=11)
    dark_bold = Font(bold=True, size=13)

    ws.insert_rows(1)
    ws.insert_rows(1)
    ws["A1"] = f"{test_name} Test — {video_name}"
    ws["A1"].font = dark_bold
    ws["A1"].alignment = Alignment(horizontal="left")

    for cell in ws[3]:
        cell.fill = blue
        cell.font = white_bold
        cell.alignment = Alignment(horizontal="left")

    # Data rows are 4+ (rows 1-3 are title + blank + Metric/Value header).
    # Center the value column (B) even when the value is a string like
    # "never" for missing-latency or "n/a" for tortuosity.
    for r in range(4, ws.max_row + 1):
        _center_cell(ws.cell(row=r, column=2))

    for col in ws.columns:
        length = max((len(str(c.value or "")) for c in col), default=0)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(length + 4, 40)


def _style_raw(ws):
    grey = PatternFill("solid", fgColor="3A3A3A")
    white_bold = Font(color="FFFFFF", bold=True)
    for cell in ws[1]:
        cell.fill = grey
        cell.font = white_bold
    for col in ws.columns:
        length = max((len(str(c.value or "")) for c in col), default=0)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(length + 4, 22)


_VC_MODELS = ["median", "mog2", "knn", "cnt", "gsoc", "lsbp", "framediff", "hsv"]
_VC_BODY_STYLES = ["off", "dots", "skeleton", "dots+skeleton"]
_VC_PROC_SCALES = ["100%", "75%", "50%", "25%"]

_VC_LABELS = {
    "threshold":            "Threshold",
    "brightness":           "Brightness",
    "contrast":             "Contrast (%)",
    "blur":                 "Blur",
    "gamma":                "Gamma (%)",
    "sharpen":              "Sharpen",
    "clahe":                "CLAHE clip",
    "max_blob":             "Max blob (%)",
    "proc_scale":           "Processing scale",
    "model":                "Tracking model",
    "body_style":           "Body style",
    "frame_skip":           "Frame skip",
    "fps_override":         "FPS override (0 = auto)",
    "movement_thr":         "Movement threshold (cm/s)",
    "bin_size":             "Time bin size (s)",
    "trim_start":           "Trim start (s)",
    "trim_duration":        "Trim duration (s)",
    "smooth":               "Smoothing",
    "zone_mode":            "Zone mode",
    "cage_shape":           "Cage shape",
    "perspective":          "Perspective correction",
    "center_pct":           "Center zone (%)",
    "calib_mode":           "Calibration mode",
    "calib_cm":             "Calibration length (cm)",
    "arm_length_cm":        "Arm length (cm)",
    "cage_w_cm":            "Cage width (cm)",
    "cage_h_cm":            "Cage height (cm)",
    "arena_define_mode":    "Arena define mode",
    "arena_pad_pct":        "Arena pad (%)",
    "arena_auto_movement":  "Arena auto-from-movement",
    "trail":                "Trail enabled",
    "trail_len":            "Trail length",
    "trail_fade":           "Trail fade",
    "arrow":                "Direction arrow",
    "ellipse":              "Body ellipse",
    "brush_radius":         "Brush radius",
    "overlay_alpha":        "Overlay alpha",
    "cell_min_dwell":       "Cell min dwell (s)",  # legacy key
    "cell_min_dwell_s":     "Cell min dwell (s)",
}

_VC_PREFERRED = [
    "model", "frame_skip", "proc_scale", "threshold",
    "brightness", "contrast", "blur", "gamma", "sharpen",
    "clahe", "max_blob",
    "fps_override", "trim_start", "trim_duration",
    "movement_thr", "bin_size", "smooth",
    "body_style", "zone_mode", "cage_shape", "center_pct",
    "perspective", "calib_mode", "calib_cm",
    "arm_length_cm",
    "cage_w_cm", "cage_h_cm",
    "arena_define_mode", "arena_pad_pct", "arena_auto_movement",
    "cell_min_dwell_s",
    "trail", "trail_len", "trail_fade", "arrow", "ellipse",
    "brush_radius", "overlay_alpha",
]

_VC_SKIP = {
    "metadata", "exclusion_mask", "arena", "original_arena",
    "center_zone", "center", "calib_p1", "calib_p2", "colors", "model_params",
    "post_params", "cell_categories", "crop",
}


def _vc_fmt(key, val):
    # Legacy int → label fallback for old saved snapshots.
    if key == "model" and isinstance(val, int) and 0 <= val < len(_VC_MODELS):
        return _VC_MODELS[val]
    if key == "body_style" and isinstance(val, int) and 0 <= val < len(_VC_BODY_STYLES):
        return _VC_BODY_STYLES[val]
    if key == "proc_scale" and isinstance(val, int) and 0 <= val < len(_VC_PROC_SCALES):
        return _VC_PROC_SCALES[val]
    # New direct-value path: render proc_scale floats as percentages.
    if key == "proc_scale" and isinstance(val, (int, float)):
        return f"{int(round(float(val) * 100))}%"
    if isinstance(val, bool):
        return "Yes" if val else "No"
    return val


def _video_config_rows(settings: dict, video_size, all_units=False) -> list:
    """Return [(label, value)] rows for the Video Config sheet/CSV.
    `all_units` follows each cm / cm/s / s setting with its other scales
    ('Movement threshold (mm/s)', …)."""
    if all_units:
        rows = []
        for label, value in _video_config_rows(settings, video_size):
            rows.append((label, value))
            if not label.startswith(" "):
                for name, f in units.variants(label)[1:]:
                    rows.append((name, units._round(float(value) * f)
                                 if units._is_number(value) else value))
        return rows
    rows = []
    if video_size:
        rows.append(("Video resolution", f"{video_size[0]} x {video_size[1]} px"))

    seen = set()

    def emit(key):
        if key in seen or key in _VC_SKIP or key not in settings:
            return
        val = settings.get(key)
        if val is None:
            return
        seen.add(key)
        label = _VC_LABELS.get(key, key.replace("_", " ").title())
        rows.append((label, _vc_fmt(key, val)))

    for k in _VC_PREFERRED:
        emit(k)
    for k, v in settings.items():
        if k in seen or k in _VC_SKIP:
            continue
        if v is None:
            continue
        if isinstance(v, (dict, list, tuple, np.ndarray)):
            continue
        seen.add(k)
        rows.append((_VC_LABELS.get(k, k.replace("_", " ").title()), _vc_fmt(k, v)))

    # Nested model params for the selected model only. Accept string (new
    # format) or legacy int index.
    mp = settings.get("model_params")
    mi = settings.get("model")
    model_name = None
    if isinstance(mi, str):
        model_name = mi
    elif isinstance(mi, int) and 0 <= mi < len(_VC_MODELS):
        model_name = _VC_MODELS[mi]
    if isinstance(mp, dict) and model_name:
        params = mp.get(model_name) or {}
        if params:
            rows.append(("", ""))
            rows.append((f"Model params ({model_name})", ""))
            for k, v in params.items():
                rows.append((f"  {k}", v))

    pp = settings.get("post_params")
    if isinstance(pp, dict) and pp:
        rows.append(("", ""))
        rows.append(("Post-processing params", ""))
        for k, v in pp.items():
            rows.append((f"  {k}", v))

    return rows


def _write_video_config_sheet(wb, settings: dict, video_size, all_units=False):
    ws = wb.create_sheet("Video Config")
    blue = PatternFill("solid", fgColor="1A6EA8")
    white_bold = Font(color="FFFFFF", bold=True, size=11)
    section_font = Font(bold=True, size=11, color="1A4F72")

    ws.append(["Setting", "Value"])
    for cell in ws[1]:
        cell.fill = blue
        cell.font = white_bold
        cell.alignment = Alignment(horizontal="left")

    rows = _video_config_rows(settings, video_size, all_units)
    for label, value in rows:
        ws.append([label, value])
        # Style section headers (label set, value empty, label contains "params").
        if value == "" and label and ("params" in label.lower()):
            for cell in ws[ws.max_row]:
                cell.font = section_font
        else:
            # Center the value cell (col B). Labels in col A stay default.
            _center_cell(ws.cell(row=ws.max_row, column=2))

    for col in ws.columns:
        length = max((len(str(c.value or "")) for c in col), default=0)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(length + 4, 42)


def _trajectory_png(x, y, arena, video_size):
    vw, vh = video_size
    fig, ax = plt.subplots(figsize=(6, 6 * vh / vw), facecolor="white")
    ax.set_facecolor("white")

    ax.plot(x, y, color="#7A2E8E", linewidth=2.2, alpha=0.9,
            solid_capstyle="round", solid_joinstyle="round", zorder=2)

    edge_color = "#FF9F4A"
    if arena and len(arena) >= 3:
        ax.add_patch(plt.Polygon(arena, linewidth=1.5, edgecolor=edge_color,
                                 facecolor="none", closed=True, zorder=4))

    def _pin(px, py, color, label):
        ax.scatter([px], [py], s=160, c=color, marker="o",
                   edgecolors="white", linewidths=1.5, zorder=6)
        ax.annotate(
            label, xy=(px, py), xytext=(12, -14), textcoords="offset points",
            fontsize=9, color="white", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3",
                      facecolor=color, edgecolor="white", linewidth=1.0),
            zorder=7,
        )
    _pin(x[0], y[0], "#23C552", "Start")
    _pin(x[-1], y[-1], "#E5484D", "End")

    if arena and len(arena) >= 3:
        arr = np.array(arena, dtype=float)
        x_min, x_max = float(arr[:, 0].min()), float(arr[:, 0].max())
        y_min, y_max = float(arr[:, 1].min()), float(arr[:, 1].max())
        pad_x = (x_max - x_min) * 0.08
        pad_y = (y_max - y_min) * 0.08
        ax.set_xlim(x_min - pad_x, x_max + pad_x)
        ax.set_ylim(y_max + pad_y, y_min - pad_y)
    else:
        ax.set_xlim(0, vw)
        ax.set_ylim(vh, 0)

    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_aspect("equal", adjustable="datalim")
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def _heatmap_png(x, y, arena, video_size):
    from matplotlib.path import Path
    from matplotlib import colors as mcolors

    vw, vh = video_size
    fig, ax = plt.subplots(figsize=(6, 6 * vh / vw), facecolor="white")
    ax.set_facecolor("white")

    bins = 80
    hm, xedges, yedges = np.histogram2d(x, y, bins=bins, range=[[0, vw], [0, vh]])
    hm = hm.T.astype(np.float32)

    try:
        import cv2
        hm = cv2.GaussianBlur(hm, ksize=(0, 0), sigmaX=1.5, sigmaY=1.5)
    except Exception:
        pass

    if arena and len(arena) >= 3:
        poly = np.array(arena, dtype=float)
        xc = 0.5 * (xedges[:-1] + xedges[1:])
        yc = 0.5 * (yedges[:-1] + yedges[1:])
        xx, yy = np.meshgrid(xc, yc, indexing="xy")
        pts = np.column_stack([xx.ravel(), yy.ravel()])
        try:
            inside = Path(poly).contains_points(pts).reshape(xx.shape)
            hm_disp = np.where(inside, hm, np.nan)
        except Exception:
            hm_disp = hm
    else:
        hm_disp = hm

    max_v = float(np.nanmax(hm_disp)) if np.isfinite(hm_disp).any() else 0.0

    base = plt.get_cmap("jet")
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "jet_mask", base(np.linspace(0, 1, 256))
    )
    cmap.set_bad((1, 1, 1, 0))

    ax.imshow(hm_disp, origin="upper", extent=[0, vw, vh, 0],
              cmap=cmap, interpolation="bilinear", aspect="auto",
              vmin=0.0, vmax=max_v if max_v > 0 else 1.0)

    edge_color = "#FF9F4A"
    if arena and len(arena) >= 3:
        ax.add_patch(plt.Polygon(arena, linewidth=1.2, edgecolor=edge_color,
                                 facecolor="none", closed=True))
        arr = np.array(arena, dtype=float)
        x_min, x_max = float(arr[:, 0].min()), float(arr[:, 0].max())
        y_min, y_max = float(arr[:, 1].min()), float(arr[:, 1].max())
        pad_x = (x_max - x_min) * 0.05
        pad_y = (y_max - y_min) * 0.05
        ax.set_xlim(x_min - pad_x, x_max + pad_x)
        ax.set_ylim(y_max + pad_y, y_min - pad_y)

    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)

    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def _bin_dist_png(bin_df):
    """Line plot: distance per time-bin. Returns PNG bytes, or None."""
    if bin_df is None or bin_df.empty:
        return None
    if "Bin Start (s)" not in bin_df.columns:
        return None
    dist_col = next(
        (c for c in bin_df.columns if str(c).lower().startswith("distance")),
        None,
    )
    if not dist_col:
        return None
    try:
        x = bin_df["Bin Start (s)"].values.astype(float)
        y = bin_df[dist_col].values.astype(float)
    except Exception:
        return None
    fig, ax = plt.subplots(figsize=(5, 2.4))
    ax.plot(x, y, color="#1A6EA8", linewidth=1.5, marker="o", markersize=3)
    ax.set_xlabel("Bin start (s)", fontsize=9)
    ax.set_ylabel(str(dist_col), fontsize=9)
    ax.set_title("Distance per bin", fontsize=10)
    ax.tick_params(labelsize=8)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


# ───────────────────────── Combined batch export ──────────────────────────

def _expand_result(res):
    """All-scales copy of a {metrics, raw_df, bin_df, …} dict."""
    if not res:
        return res
    res = dict(res)
    m = res.get("metrics") or {}
    base_len = units.base_length_unit(m)
    if m:
        res["metrics"] = units.expand_metrics(m, base_len)
    for k in ("raw_df", "bin_df"):
        if res.get(k) is not None:
            res[k] = units.expand_df(res[k], base_len)
    return res


def _expand_animals(animals, schema):
    """All-scales copies of the animal dicts (+ schema). Snake_case
    plugin keys ('total_distance') are only expanded when calibrated, so
    the schema follows the calibration of the animals themselves."""
    out = [_expand_result(a) for a in animals]
    if schema:
        calibrated = any(
            units.base_length_unit(a.get("metrics") or {}) == "cm"
            for a in animals) or not animals
        schema = units.expand_schema(schema, "cm" if calibrated else "px")
    return out, schema


def _safe_sheet_name(name: str, used: set) -> str:
    """Excel: 31-char limit, no [ ] : * ? / \\, must be unique."""
    bad = '[]:*?/\\'
    cleaned = "".join("_" if c in bad else c for c in (name or "Sheet"))
    cleaned = cleaned[:31] or "Sheet"
    base = cleaned
    n = 2
    while cleaned in used:
        suffix = f"_{n}"
        cleaned = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(cleaned)
    return cleaned


def _write_master_legacy(master, animals, blue, white_bold):
    """Original master-sheet layout: single header row in first-seen
    metric order. Used when no schema is supplied."""
    meta_keys = ["Animal ID", "Group", "Sex", "Date", "Trial", "Notes"]
    metric_keys = []
    for a in animals:
        for k in (a.get("metrics") or {}).keys():
            if k not in metric_keys:
                metric_keys.append(k)
    headers = ["Video"] + meta_keys + metric_keys
    master.append(headers)
    for cell in master[1]:
        cell.fill = blue
        cell.font = white_bold
        cell.alignment = Alignment(horizontal="left")
    for a in animals:
        md = a.get("metadata") or {}
        m  = a.get("metrics") or {}
        row = [a.get("animal_id", "")]
        row += [md.get(k, "") for k in meta_keys]
        row += [m.get(k, "") for k in metric_keys]
        master.append(row)
    # Center every data cell (rows 2+).
    for r in range(2, master.max_row + 1):
        for c_idx in range(1, master.max_column + 1):
            _center_cell(master.cell(row=r, column=c_idx))
    for col in master.columns:
        length = max((len(str(c.value or "")) for c in col), default=0)
        master.column_dimensions[
            get_column_letter(col[0].column)
        ].width = min(length + 3, 28)


def _write_animal_metric_sections(ws, row, metrics, schema,
                                   blue, white_bold, bold):
    """Per-animal metrics laid out by schema section, each section as
    a banner + label/value pairs (2 per row). Matches the column groups
    of the All Animals master sheet so a reader can recognise the same
    blocks here. Returns the next free row index.

    The "Experiment Metadata" section in the schema is skipped because
    the per-animal sheet already has its own METADATA block above."""
    METADATA_SECTION = "Experiment Metadata"
    for section_name, cols in schema:
        if section_name == METADATA_SECTION:
            continue
        # Pair each schema column with its metric value (blank when
        # missing). Skip the section entirely if there's nothing to show.
        pairs = []
        for col in cols:
            if col in metrics:
                pairs.append((col, metrics[col]))
            else:
                pairs.append((col, ""))
        # If every value is blank (e.g. center-only run rendered in a
        # batch alongside grid runs), skip the section to keep the
        # sheet clean.
        if all(v in ("", None) for _, v in pairs):
            continue

        # Section banner — spans cols A:D.
        ws.cell(row=row, column=1, value=section_name).font = white_bold
        ws.cell(row=row, column=1).fill = blue
        ws.cell(row=row, column=1).alignment = Alignment(
            horizontal="left", vertical="center"
        )
        ws.merge_cells(start_row=row, start_column=1,
                       end_row=row, end_column=4)
        row += 1

        # 2 pairs per row. Values centered, labels left-default + bold.
        for i in range(0, len(pairs), 2):
            k1, v1 = pairs[i]
            ws.cell(row=row, column=1, value=str(k1)).font = bold
            _center_cell(ws.cell(row=row, column=2, value=v1))
            if i + 1 < len(pairs):
                k2, v2 = pairs[i + 1]
                ws.cell(row=row, column=3, value=str(k2)).font = bold
                _center_cell(ws.cell(row=row, column=4, value=v2))
            row += 1
        row += 1  # blank spacer between sections
    return row


def _write_scale_row(ws, row, label, cells, bold):
    """One row: bold label in A, then value/unit pairs (B/C, D/E, …).
    Values stay real numbers so Excel can compute with them."""
    ws.cell(row=row, column=1, value=str(label)).font = bold
    col = 2
    for val, unit in cells:
        _center_cell(ws.cell(row=row, column=col, value=val))
        if unit:
            u = ws.cell(row=row, column=col + 1, value=unit)
            u.font = Font(color="808080", size=10)
            u.alignment = Alignment(horizontal="left", vertical="center")
        col += 2


def _write_animal_metric_rows(ws, row, metrics, sections, base_len,
                              blue, white_bold, bold):
    """All-scales variant of _write_animal_metric_sections: one metric
    per row, every scale of it on the same row —
        Total Distance | 1402.23 cm | 14022.3 mm | 14.0223 m
    `metrics` is the expanded dict (already holds every scale)."""
    for section_name, cols in sections:
        if section_name == "Experiment Metadata":
            continue
        entries = []
        for col in cols:
            label, names = units.scales(col, base_len)
            entries.append((label, [(metrics.get(n, ""), u) for n, u in names]))
        if all(v in ("", None) for _l, cells in entries for v, _u in cells):
            continue
        ws.cell(row=row, column=1, value=section_name).font = white_bold
        ws.cell(row=row, column=1).fill = blue
        ws.cell(row=row, column=1).alignment = Alignment(
            horizontal="left", vertical="center")
        ws.merge_cells(start_row=row, start_column=1,
                       end_row=row, end_column=_SCALE_LAST_COL)
        row += 1
        for label, cells in entries:
            _write_scale_row(ws, row, label, cells, bold)
            row += 1
        row += 1
    return row


# Per-animal all-scales layout: label A + up to 5 value/unit pairs → K.
_SCALE_LAST_COL = 11


def _write_master_schema(master, animals, schema,
                          section_fill, section_font,
                          blue, white_bold):
    """Schema-driven master sheet:
      row 1 = sparse section headers (only first cell of each section)
      row 2 = column titles
      row 3+ = one row per animal
    Metadata pulled from `animals[i]["metadata"]` for the metadata
    section; everything else from `animals[i]["metrics"]`. Missing
    values render as blank."""
    # Flatten the schema into (col_idx → section, column) so writes
    # are straightforward. Also record where each section starts so
    # row 1 can be sparse + merged.
    columns = []
    section_starts = []  # list of (section_name, start_col_idx, span)
    col_idx = 1
    for section_name, cols in schema:
        section_starts.append((section_name, col_idx, len(cols)))
        for c in cols:
            columns.append(c)
            col_idx += 1

    # Row 1 — section headers, merged across each section's columns.
    for section_name, start, span in section_starts:
        cell = master.cell(row=1, column=start, value=section_name)
        cell.fill = section_fill
        cell.font = section_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        if span > 1:
            master.merge_cells(
                start_row=1, start_column=start,
                end_row=1, end_column=start + span - 1,
            )

    # Row 2 — column titles.
    for i, name in enumerate(columns, start=1):
        cell = master.cell(row=2, column=i, value=name)
        cell.fill = blue
        cell.font = white_bold
        cell.alignment = Alignment(horizontal="left", vertical="center")

    # Rows 3+ — data, one row per animal. The Video and metadata
    # columns are pulled from animal["metadata"] (plus the special
    # "Video" → animal_id mapping); everything else is from
    # animal["metrics"]. Anything missing → blank.
    meta_lookup_keys = {
        "Video": lambda a: a.get("animal_id", ""),
        "Animal ID": lambda a: (a.get("metadata") or {}).get("Animal ID", ""),
        "Group":     lambda a: (a.get("metadata") or {}).get("Group", ""),
        "Sex":       lambda a: (a.get("metadata") or {}).get("Sex", ""),
        "Date":      lambda a: (a.get("metadata") or {}).get("Date", ""),
        "Trial":     lambda a: (a.get("metadata") or {}).get("Trial", ""),
        "Notes":     lambda a: (a.get("metadata") or {}).get("Notes", ""),
    }
    for r_idx, a in enumerate(animals, start=3):
        m = a.get("metrics") or {}
        for c_idx, col_name in enumerate(columns, start=1):
            if col_name in meta_lookup_keys:
                val = meta_lookup_keys[col_name](a)
            else:
                val = m.get(col_name, "")
            cell = master.cell(row=r_idx, column=c_idx, value=val)
            _center_cell(cell)

    # Column widths — based on the widest value in each column.
    for ci in range(1, len(columns) + 1):
        col_letter = get_column_letter(ci)
        widest = max(
            (len(str(master.cell(row=r, column=ci).value or ""))
             for r in range(1, master.max_row + 1)),
            default=0,
        )
        master.column_dimensions[col_letter].width = min(widest + 3, 28)

    # Freeze the two header rows so scrolling keeps them visible.
    master.freeze_panes = "A3"


def export_combined(output_path: str, animals: list, schema=None,
                    all_units: bool = True):
    """Write one combined xlsx with:
      - Sheet 1 ("All Animals"): one row per animal (metadata + metrics).
      - Per-animal sheets: dashboard with metadata / metrics / time bins on
        the left and 5 graphs stacked on the right.

    `animals` is a list of dicts, each containing:
      animal_id (str), metadata (dict), metrics (dict),
      bin_df (pandas.DataFrame or None),
      graph_pngs (dict[str, bytes]).

    `schema` (optional) drives the master-sheet layout. Format:
      [(section_name, [col1, col2, ...]), ...]
    When provided, row 1 = sparse section headers, row 2 = column titles,
    row 3+ = data. When None, falls back to first-seen-across-animals
    order with a single header row (legacy behavior).

    `all_units` adds every other scale of each distance / speed / time
    column right after it (see core.units).
    """
    from openpyxl import Workbook
    # Master sheet: every scale as adjacent columns. Per-animal sheets:
    # one metric per row with all its scales across the row.
    base_schema = schema
    base_animals = animals
    if all_units:
        animals, schema = _expand_animals(animals, schema)
    wb = Workbook()
    wb.remove(wb.active)

    blue       = PatternFill("solid", fgColor="1A6EA8")
    section_fill = PatternFill("solid", fgColor="0D4F75")
    light_blue = PatternFill("solid", fgColor="DCE9F4")
    grey       = PatternFill("solid", fgColor="3A3A3A")
    white_bold = Font(color="FFFFFF", bold=True, size=11)
    section_font = Font(color="FFFFFF", bold=True, size=11)
    bold       = Font(bold=True, size=11)
    title_font = Font(bold=True, size=14, color="1A4F72")

    # ── Master sheet ──────────────────────────────────────────────────────
    master = wb.create_sheet("All Animals")
    if schema:
        _write_master_schema(
            master, animals, schema,
            section_fill, section_font, blue, white_bold,
        )
    else:
        _write_master_legacy(master, animals, blue, white_bold)

    # ── Per-animal sheets ─────────────────────────────────────────────────
    used_names = {"All Animals"}
    for a, a_base in zip(animals, base_animals):
        sheet_name = _safe_sheet_name(a.get("animal_id") or "Animal", used_names)
        ws = wb.create_sheet(sheet_name)
        base_len = units.base_length_unit(a_base.get("metrics") or {})
        # Graphs sit right of the data block, which is wider with all scales.
        g_col = _SCALE_LAST_COL + 2 if all_units else 6
        g_letter = get_column_letter(g_col)

        # Banner (row 1)
        ws.merge_cells("A1:I1")
        ws["A1"] = f"Animal: {a.get('animal_id', '')}"
        ws["A1"].font = title_font
        ws["A1"].fill = light_blue
        ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[1].height = 22

        # Left column widths (data side)
        if all_units:
            ws.column_dimensions["A"].width = 34
            for ci in range(2, _SCALE_LAST_COL + 1):
                ws.column_dimensions[get_column_letter(ci)].width = (
                    13 if ci % 2 == 0 else 8)
        else:
            for col, w in zip("ABCD", (16, 18, 16, 18)):
                ws.column_dimensions[col].width = w
        # Spacer
        ws.column_dimensions[get_column_letter(g_col - 1)].width = 2
        # Right side (graphs) — wide enough for ~400px image
        for ci in range(g_col, g_col + 4):
            ws.column_dimensions[get_column_letter(ci)].width = 12

        row = 3

        # METADATA section
        ws.cell(row=row, column=1, value="METADATA").font = white_bold
        ws.cell(row=row, column=1).fill = blue
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
        row += 1
        md = a.get("metadata") or {}
        # Local list — was previously held by an outer-scope variable
        # before the master-sheet builder got extracted.
        _meta_keys = ["Animal ID", "Group", "Sex", "Date", "Trial", "Notes"]
        meta_pairs = [(k, md.get(k, "")) for k in _meta_keys]
        # 2 pairs per row (label, value, label, value).
        # Labels in cols A/C stay bold + default-aligned. Values in
        # cols B/D get centered so text and numbers both line up.
        for i in range(0, len(meta_pairs), 2):
            k1, v1 = meta_pairs[i]
            ws.cell(row=row, column=1, value=k1).font = bold
            _center_cell(ws.cell(row=row, column=2, value=v1))
            if i + 1 < len(meta_pairs):
                k2, v2 = meta_pairs[i + 1]
                ws.cell(row=row, column=3, value=k2).font = bold
                _center_cell(ws.cell(row=row, column=4, value=v2))
            row += 1
        row += 1  # blank

        # METRICS — schema-driven sectioned layout when a schema was
        # passed (matches the All Animals master sheet's section groups);
        # falls back to a single flat METRICS block when not.
        m = a.get("metrics") or {}
        if all_units:
            sections = base_schema or [
                ("METRICS", list((a_base.get("metrics") or {}).keys()))]
            row = _write_animal_metric_rows(
                ws, row, m, sections, base_len,
                blue, white_bold, bold,
            )
        elif schema:
            row = _write_animal_metric_sections(
                ws, row, m, schema,
                blue, white_bold, bold,
            )
        else:
            ws.cell(row=row, column=1, value="METRICS").font = white_bold
            ws.cell(row=row, column=1).fill = blue
            ws.merge_cells(start_row=row, start_column=1,
                           end_row=row, end_column=4)
            row += 1
            m_pairs = list(m.items())
            for i in range(0, len(m_pairs), 2):
                k1, v1 = m_pairs[i]
                ws.cell(row=row, column=1, value=str(k1)).font = bold
                _center_cell(ws.cell(row=row, column=2, value=v1))
                if i + 1 < len(m_pairs):
                    k2, v2 = m_pairs[i + 1]
                    ws.cell(row=row, column=3, value=str(k2)).font = bold
                    _center_cell(ws.cell(row=row, column=4, value=v2))
                row += 1
            row += 1  # blank

        # VIDEO CONFIG section
        vc = a.get("video_config")
        if vc:
            ws.cell(row=row, column=1, value="VIDEO CONFIG").font = white_bold
            ws.cell(row=row, column=1).fill = blue
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
            row += 1
            vc_rows = _video_config_rows(vc, a.get("video_size"))
            for label, value in vc_rows:
                if (all_units and units.classify(label) is not None
                        and units._is_number(value)):
                    # cm / cm/s / s setting → every scale on this row
                    lbl, names = units.scales(label)
                    cells = [(units._round(float(value) * f), u)
                             for (_n, u), (_n2, f)
                             in zip(names, units.variants(label))]
                    _write_scale_row(ws, row, lbl, cells, bold)
                    row += 1
                    continue
                ws.cell(row=row, column=1, value=label).font = bold
                # value spans cols 2-4 so long strings (model params) fit.
                vc_val_cell = ws.cell(row=row, column=2, value=value)
                ws.merge_cells(start_row=row, start_column=2,
                               end_row=row, end_column=4)
                _center_cell(vc_val_cell)
                row += 1
            row += 1  # blank

        # TIME BINS section
        ws.cell(row=row, column=1, value="TIME BINS").font = white_bold
        ws.cell(row=row, column=1).fill = blue
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
        row += 1
        bin_df = a.get("bin_df")
        if bin_df is not None and not bin_df.empty:
            # header
            for ci, col_name in enumerate(bin_df.columns, start=1):
                c = ws.cell(row=row, column=ci, value=str(col_name))
                c.font = white_bold
                c.fill = grey
            row += 1
            for _, r in bin_df.iterrows():
                for ci, val in enumerate(r.values, start=1):
                    _center_cell(ws.cell(row=row, column=ci, value=val))
                row += 1
        else:
            ws.cell(row=row, column=1, value="(no bin data — set Time bin > 0 in config)")
            row += 1

        # GRAPHS — embedded on the right side starting at row 3.
        graph_pngs = a.get("graph_pngs") or {}
        graph_row = 3
        for name, png in graph_pngs.items():
            if not png:
                continue
            ws.cell(row=graph_row, column=g_col, value=name).font = bold
            graph_row += 1
            try:
                img = XLImage(BytesIO(png))
                target_w = 380
                if img.width > target_w:
                    s = target_w / float(img.width)
                    img.width = int(img.width * s)
                    img.height = int(img.height * s)
                ws.add_image(img, f"{g_letter}{graph_row}")
                graph_row += int(img.height / 18) + 2
            except Exception:
                ws.cell(row=graph_row, column=g_col, value="(could not embed graph)")
                graph_row += 1

    _center_align_workbook(wb)
    wb.save(output_path)


def export_multi_run(output_path: str, video_name: str,
                     swept_key: str, swept_label: str,
                     base_settings: dict, variants: list,
                     all_units: bool = True):
    """Combined xlsx for a Multi-Run sweep.

    `swept_key` / `swept_label` may be a single string or a list (one entry
    per swept variable). With several variables, each variant also carries
    `values` = {key: value_label} and the compare sheet gets one row per
    swept variable above the metrics.

    Sheets:
      - Sweep Compare: rows = metric, cols = variant value
      - Settings:      locked common settings + the swept variable
      - One sheet per variant: metric/value + time bins.

    `variants` is a list of dicts:
      {label (str), value (Any), settings (dict),
       result: {metrics, raw_df, bin_df, video_size, fps}}
    """
    from openpyxl import Workbook
    swept_keys = [swept_key] if isinstance(swept_key, str) else list(swept_key or [])
    swept_labels = ([swept_label] if isinstance(swept_label, str)
                    else list(swept_label or []))
    if len(swept_labels) < len(swept_keys):
        swept_labels += swept_keys[len(swept_labels):]
    multi = len(swept_keys) > 1
    swept_title = " × ".join(swept_labels)

    def _vals_of(v):
        vals = v.get("values")
        if vals:
            return vals
        # Single-variable variant from an older caller.
        return {swept_keys[0]: v.get("label", v.get("value", ""))} if swept_keys else {}

    if all_units:
        variants = [dict(v, result=_expand_result(v.get("result")))
                    for v in variants]
    wb = Workbook()
    wb.remove(wb.active)

    blue       = PatternFill("solid", fgColor="1A6EA8")
    light_blue = PatternFill("solid", fgColor="DCE9F4")
    grey       = PatternFill("solid", fgColor="3A3A3A")
    white_bold = Font(color="FFFFFF", bold=True, size=11)
    bold       = Font(bold=True, size=11)
    title_font = Font(bold=True, size=14, color="1A4F72")

    # ── Compare sheet ────────────────────────────────────────────────────
    cmp_ws = wb.create_sheet("Sweep Compare")
    cmp_ws.merge_cells("A1:Z1")
    cmp_ws["A1"] = f"Multi-Run — {video_name} — swept: {swept_title}"
    cmp_ws["A1"].font = title_font
    cmp_ws["A1"].fill = light_blue
    cmp_ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    cmp_ws.row_dimensions[1].height = 22

    metric_order = []
    seen_metrics = set()
    for v in variants:
        m = (v.get("result") or {}).get("metrics") or {}
        for k in m.keys():
            if k not in seen_metrics:
                seen_metrics.add(k)
                metric_order.append(k)

    if multi:
        headers = ["Metric"] + [f"Run {i}" for i in range(1, len(variants) + 1)]
    else:
        headers = ["Metric"] + [str(v.get("label", v.get("value", ""))) for v in variants]
    cmp_ws.append([])  # row 2 blank
    cmp_ws.append(headers)
    hdr_row = cmp_ws.max_row
    for cell in cmp_ws[hdr_row]:
        cell.fill = blue
        cell.font = white_bold
        cell.alignment = Alignment(horizontal="left")

    # With several swept variables, list each run's values first so the
    # columns can be read (and filtered) without opening the run sheets.
    if multi:
        for key, lbl in zip(swept_keys, swept_labels):
            row = [lbl] + [_vals_of(v).get(key, "baseline") for v in variants]
            cmp_ws.append(row)
            for cell in cmp_ws[cmp_ws.max_row]:
                cell.fill = light_blue
                cell.font = bold

    for mk in metric_order:
        row = [mk]
        for v in variants:
            m = (v.get("result") or {}).get("metrics") or {}
            row.append(m.get(mk, ""))
        cmp_ws.append(row)

    for col in cmp_ws.columns:
        length = max((len(str(c.value or "")) for c in col), default=0)
        cmp_ws.column_dimensions[get_column_letter(col[0].column)].width = min(length + 3, 32)

    # ── Graphs to the right of the data table ────────────────────────────
    # Layout: data table occupies cols A..(N+1). One spacer col. Then each
    # variant gets a 2-col block. Per variant column (top → bottom):
    # variant label → each graph stacked vertically in fixed slots so
    # corresponding graphs align across variants.
    data_cols = 1 + len(variants)            # Metric col + N variants
    graph_start_col = data_cols + 2          # leave one spacer col
    graph_header_row = hdr_row               # align with variant header (row 3)
    graph_first_row = hdr_row + 1            # first image row

    rep_vsize = None
    for v in variants:
        vs = (v.get("result") or {}).get("video_size")
        if vs and vs[0] and vs[1]:
            rep_vsize = vs
            break

    IMG_W = 280

    # Slot order. Output-tab order first, then a bin distance plot at the end.
    GRAPH_ORDER = [
        "Trajectory", "Heatmap", "Cell Time",
        "Speed", "Speed Histogram", "Habituation", "Zone Time", "Triplets",
    ]

    # Pre-scale all variant graphs once. Collect height per slot to align rows.
    # prepared[(variant_idx, slot)] = (png_bytes, scaled_w, scaled_h)
    prepared = {}
    slot_max_h = {name: 0 for name in GRAPH_ORDER}

    for i, v in enumerate(variants):
        result = v.get("result") or {}
        pngs = result.get("graph_pngs") or {}
        # Fallback: if no embedded graphs (e.g. older run), render
        # trajectory + heatmap directly from raw_df so the compare sheet
        # is never empty.
        if not pngs:
            raw_df = result.get("raw_df")
            arena_px = result.get("arena_px")
            vsize = result.get("video_size") or rep_vsize
            if (raw_df is not None and vsize
                    and "X (px)" in raw_df.columns
                    and "Y (px)" in raw_df.columns):
                try:
                    xs = raw_df["X (px)"].dropna().values
                    ys = raw_df["Y (px)"].dropna().values
                    if len(xs) > 1:
                        pngs = {
                            "Trajectory": _trajectory_png(xs, ys, arena_px, vsize),
                            "Heatmap":    _heatmap_png(xs, ys, arena_px, vsize),
                        }
                except Exception:
                    pngs = {}

        for name in GRAPH_ORDER:
            png = pngs.get(name)
            if not png:
                continue
            try:
                probe = XLImage(BytesIO(png))
                if probe.width > IMG_W:
                    scale = IMG_W / float(probe.width)
                else:
                    scale = 1.0
                sw = int(probe.width * scale)
                sh = int(probe.height * scale)
            except Exception:
                continue
            prepared[(i, name)] = (png, sw, sh)
            if sh > slot_max_h[name]:
                slot_max_h[name] = sh

    # Optional bin distance plot (one extra slot if any variant has bin data).
    bin_pngs = {}
    bin_max_h = 0
    for i, v in enumerate(variants):
        bin_df = (v.get("result") or {}).get("bin_df")
        if bin_df is None or bin_df.empty:
            continue
        png = _bin_dist_png(bin_df)
        if not png:
            continue
        try:
            probe = XLImage(BytesIO(png))
            scale = IMG_W / float(probe.width) if probe.width > IMG_W else 1.0
            sw = int(probe.width * scale)
            sh = int(probe.height * scale)
        except Exception:
            continue
        bin_pngs[i] = (png, sw, sh)
        if sh > bin_max_h:
            bin_max_h = sh

    # Compute slot start rows from cumulative heights.
    slot_row = {}
    cursor = graph_first_row
    for name in GRAPH_ORDER:
        h = slot_max_h.get(name, 0)
        if h <= 0:
            continue  # no variant produced this graph — skip the slot
        slot_row[name] = cursor
        cursor += max(1, int(h / 18) + 2)
    bin_slot_row = None
    if bin_max_h > 0:
        bin_slot_row = cursor
        cursor += max(1, int(bin_max_h / 18) + 2)

    # Spacer column.
    cmp_ws.column_dimensions[get_column_letter(graph_start_col - 1)].width = 2

    # Per-variant header + image placement.
    for i, v in enumerate(variants):
        col1 = graph_start_col + i * 2
        col2 = col1 + 1
        cmp_ws.column_dimensions[get_column_letter(col1)].width = 16
        cmp_ws.column_dimensions[get_column_letter(col2)].width = 16

        label = (f"Run {i + 1}" if multi
                 else str(v.get("label", v.get("value", ""))))
        hcell = cmp_ws.cell(row=graph_header_row, column=col1, value=label)
        hcell.fill = blue
        hcell.font = white_bold
        hcell.alignment = Alignment(horizontal="center")
        cmp_ws.merge_cells(start_row=graph_header_row, start_column=col1,
                           end_row=graph_header_row, end_column=col2)

        anchor_letter = get_column_letter(col1)
        for name, row in slot_row.items():
            entry = prepared.get((i, name))
            if not entry:
                continue
            png, sw, sh = entry
            try:
                img = XLImage(BytesIO(png))
                img.width = sw
                img.height = sh
                cmp_ws.add_image(img, f"{anchor_letter}{row}")
            except Exception:
                pass
        # Bin plot last.
        if bin_slot_row is not None and i in bin_pngs:
            png, sw, sh = bin_pngs[i]
            try:
                img = XLImage(BytesIO(png))
                img.width = sw
                img.height = sh
                cmp_ws.add_image(img, f"{anchor_letter}{bin_slot_row}")
            except Exception:
                pass

    # ── Settings sheet (locked + swept) ──────────────────────────────────
    set_ws = wb.create_sheet("Settings")
    set_ws.append(["Setting", "Value"])
    for cell in set_ws[1]:
        cell.fill = blue
        cell.font = white_bold
    if multi:
        set_ws.append(["Swept variables", swept_title])
        for key, lbl in zip(swept_keys, swept_labels):
            seen, ordered = set(), []
            for v in variants:
                val = _vals_of(v).get(key)
                if val is not None and str(val) not in seen:
                    seen.add(str(val))
                    ordered.append(str(val))
            set_ws.append([f"  {lbl} values", ", ".join(ordered)])
    else:
        set_ws.append(["Swept variable", swept_title])
        set_ws.append(["Swept values", ", ".join(str(v.get("label", v.get("value", ""))) for v in variants)])
    set_ws.append(["", ""])
    set_ws.append(["LOCKED COMMON SETTINGS", ""])
    for cell in set_ws[set_ws.max_row]:
        cell.font = Font(bold=True, color="1A4F72")
    # Locked = base settings minus the swept keys.
    locked = {k: v for k, v in (base_settings or {}).items() if k not in swept_keys}
    vs = (variants[0].get("result") or {}).get("video_size") if variants else None
    for label, value in _video_config_rows(locked, vs, all_units):
        set_ws.append([label, value])
    for col in set_ws.columns:
        length = max((len(str(c.value or "")) for c in col), default=0)
        set_ws.column_dimensions[get_column_letter(col[0].column)].width = min(length + 3, 42)

    # ── Per-variant sheets ───────────────────────────────────────────────
    used = {"Sweep Compare", "Settings"}
    for vi, v in enumerate(variants, start=1):
        label = str(v.get("label", v.get("value", "")))
        if multi:
            vals = _vals_of(v)
            short = ",".join(f"{k}={vals[k]}" for k in swept_keys if k in vals)
            sheet_name = _safe_sheet_name(f"Run {vi} {short}", used)
            title = ", ".join(f"{lbl} = {vals[k]}"
                              for k, lbl in zip(swept_keys, swept_labels) if k in vals)
            title = f"Run {vi}: {title}"
        else:
            sheet_name = _safe_sheet_name(f"{swept_keys[0]}={label}", used)
            title = f"{swept_title} = {label}"
        ws = wb.create_sheet(sheet_name)

        ws.merge_cells("A1:D1")
        ws["A1"] = title
        ws["A1"].font = title_font
        ws["A1"].fill = light_blue
        ws.row_dimensions[1].height = 22

        for col, w in zip("ABCD", (28, 18, 18, 18)):
            ws.column_dimensions[col].width = w

        row = 3
        ws.cell(row=row, column=1, value="METRICS").font = white_bold
        ws.cell(row=row, column=1).fill = blue
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
        row += 1
        m = (v.get("result") or {}).get("metrics") or {}
        for mk, mv in m.items():
            ws.cell(row=row, column=1, value=str(mk)).font = bold
            ws.cell(row=row, column=2, value=mv)
            row += 1
        row += 1

        bin_df = (v.get("result") or {}).get("bin_df")
        if bin_df is not None and not bin_df.empty:
            ws.cell(row=row, column=1, value="TIME BINS").font = white_bold
            ws.cell(row=row, column=1).fill = blue
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
            row += 1
            for ci, col_name in enumerate(bin_df.columns, start=1):
                c = ws.cell(row=row, column=ci, value=str(col_name))
                c.font = white_bold
                c.fill = grey
            row += 1
            for _, r in bin_df.iterrows():
                for ci, val in enumerate(r.values, start=1):
                    _center_cell(ws.cell(row=row, column=ci, value=val))
                row += 1

    _center_align_workbook(wb)
    wb.save(output_path)


def export_combined_raw(output_path: str, animals: list,
                        all_units: bool = True):
    """Write one xlsx with one sheet per animal. Each sheet has the animal's
    metadata block at the top and the full per-frame raw data below.

    `animals` is a list of dicts with: animal_id (str), metadata (dict),
    raw_df (pandas.DataFrame).
    """
    from openpyxl import Workbook
    if all_units:
        animals, _ = _expand_animals(animals, None)
    wb = Workbook()
    wb.remove(wb.active)

    blue       = PatternFill("solid", fgColor="1A6EA8")
    light_blue = PatternFill("solid", fgColor="DCE9F4")
    grey       = PatternFill("solid", fgColor="3A3A3A")
    white_bold = Font(color="FFFFFF", bold=True, size=11)
    bold       = Font(bold=True, size=11)
    title_font = Font(bold=True, size=14, color="1A4F72")

    used_names = set()
    meta_keys = ["Animal ID", "Group", "Sex", "Date", "Trial", "Notes"]

    for a in animals:
        sheet_name = _safe_sheet_name(a.get("animal_id") or "Animal", used_names)
        ws = wb.create_sheet(sheet_name)
        raw_df = a.get("raw_df")
        n_cols = max(len(raw_df.columns) if raw_df is not None else 0, 4)

        # Banner row
        end_col_letter = get_column_letter(min(n_cols, 12))
        ws.merge_cells(f"A1:{end_col_letter}1")
        ws["A1"] = f"Animal: {a.get('animal_id', '')}"
        ws["A1"].font = title_font
        ws["A1"].fill = light_blue
        ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[1].height = 22

        row = 3

        # METADATA header
        ws.cell(row=row, column=1, value="METADATA").font = white_bold
        ws.cell(row=row, column=1).fill = blue
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
        row += 1
        md = a.get("metadata") or {}
        meta_pairs = [(k, md.get(k, "")) for k in meta_keys]
        for i in range(0, len(meta_pairs), 2):
            k1, v1 = meta_pairs[i]
            ws.cell(row=row, column=1, value=k1).font = bold
            ws.cell(row=row, column=2, value=v1)
            if i + 1 < len(meta_pairs):
                k2, v2 = meta_pairs[i + 1]
                ws.cell(row=row, column=3, value=k2).font = bold
                ws.cell(row=row, column=4, value=v2)
            row += 1
        row += 1  # blank

        # RAW DATA section
        ws.cell(row=row, column=1, value="RAW DATA").font = white_bold
        ws.cell(row=row, column=1).fill = blue
        ws.merge_cells(start_row=row, start_column=1,
                       end_row=row, end_column=min(n_cols, 12))
        row += 1

        if raw_df is not None and not raw_df.empty:
            # Column headers
            for ci, col_name in enumerate(raw_df.columns, start=1):
                c = ws.cell(row=row, column=ci, value=str(col_name))
                c.font = white_bold
                c.fill = grey
            row += 1
            # Data rows
            for _, r in raw_df.iterrows():
                for ci, val in enumerate(r.values, start=1):
                    ws.cell(row=row, column=ci, value=val)
                row += 1
            # Column widths (sample first 200 rows for speed)
            for col in ws.iter_cols(min_row=1, max_col=n_cols):
                length = max((len(str(c.value or "")) for c in col[:200]), default=0)
                ws.column_dimensions[
                    get_column_letter(col[0].column)
                ].width = min(length + 3, 22)
        else:
            ws.cell(row=row, column=1, value="(no raw data)")

    _center_align_workbook(wb)
    wb.save(output_path)
