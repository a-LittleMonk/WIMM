"""Shared occupancy-heatmap math, driven by the graph style.

Every heatmap renderer (Output → Graphs, the Y-Maze Raw/Aligned pair, the
Customize-graphs preview) goes through these helpers so the style settings
below behave the same everywhere:

    hm_bins   grid size — the region is split into N × N squares
    hm_blur   smoothing radius in squares (Gaussian sigma; 0 = none)
    hm_interp 'bilinear' (smooth) or 'nearest' (blocky, squares visible)
    hm_units  colour-scale unit:
                'seconds'  — seconds spent per square (after blur)
                'percent'  — % of the total tracked time per square
                'relative' — 0 … 1 of the hottest square
    hm_vmax   fixed top of the colour scale in the chosen unit (0 = auto,
              i.e. the hottest square). Use the same value for every animal
              to make their heatmaps directly comparable.
"""
import numpy as np

HM_DEFAULTS = {
    "hm_bins": 200,
    "hm_blur": 3.75,
    "hm_interp": "bilinear",
    "hm_units": "seconds",
    "hm_vmax": 0.0,
}
HM_BINS_RANGE = (10, 600)

# Customize-graphs editor choices / help text.
HM_INTERP_CHOICES = [("Smooth", "bilinear"), ("Blocky (show squares)", "nearest")]
HM_UNIT_CHOICES = [("Seconds per square", "seconds"),
                   ("% of total time", "percent"),
                   ("Relative (0 to max)", "relative")]
HM_HELP = ("Grid size: how many squares the area is split into, across and down. "
           "Blur: smoothing radius in squares (0 = raw squares). "
           "Fixed maximum: set the same value for every animal so the colors "
           "mean the same amount of time in each heatmap (in the scale unit).")

_UNIT_LABELS = {"seconds": "seconds", "percent": "% of time",
                "relative": "relative time"}


def _get(st, key):
    v = (st or {}).get(key, HM_DEFAULTS[key])
    return HM_DEFAULTS[key] if v is None else v


def bins(st):
    try:
        n = int(_get(st, "hm_bins"))
    except (TypeError, ValueError):
        n = HM_DEFAULTS["hm_bins"]
    return max(HM_BINS_RANGE[0], min(HM_BINS_RANGE[1], n))


def interpolation(st):
    v = _get(st, "hm_interp")
    return v if v in ("bilinear", "nearest") else "bilinear"


def units(st):
    v = _get(st, "hm_units")
    return v if v in _UNIT_LABELS else "seconds"


def seconds_grid(x, y, xrange, yrange, fps, st):
    """(grid, xedges, yedges, total_s). grid[row=y, col=x] holds the
    seconds spent in each square, blurred per hm_blur. total_s is the
    tracked time inside the range (before blurring)."""
    n = bins(st)
    hm, xe, ye = np.histogram2d(x, y, bins=n, range=[xrange, yrange])
    fps = float(fps) if fps else 30.0
    grid = (hm * (1.0 / fps)).T.astype(np.float32)
    total_s = float(hm.sum()) / fps
    try:
        sigma = float(_get(st, "hm_blur"))
    except (TypeError, ValueError):
        sigma = HM_DEFAULTS["hm_blur"]
    if sigma > 0:
        try:
            import cv2
            grid = cv2.GaussianBlur(grid, ksize=(0, 0),
                                    sigmaX=sigma, sigmaY=sigma)
        except Exception:
            pass
    return grid, xe, ye, total_s


def _in_units(grid, total_s, st):
    """seconds → the chosen unit (relative is handled in scale())."""
    if units(st) == "percent":
        return grid * (100.0 / total_s) if total_s > 0 else grid * 0.0
    return grid


def peak(grid, total_s, st):
    """Hottest square in the chosen unit (relative: in seconds)."""
    g = _in_units(grid, total_s, st)
    return float(np.nanmax(g)) if np.isfinite(g).any() else 0.0


def scale(grid, total_s, st, ref_peak=None):
    """(display_grid, vmax) for imshow. `ref_peak` shares one scale across
    panels (pass the max of peak() over them)."""
    g = _in_units(grid, total_s, st)
    top = ref_peak if ref_peak is not None else (
        float(np.nanmax(g)) if np.isfinite(g).any() else 0.0)
    if units(st) == "relative":
        return (g / top if top > 0 else g * 0.0), 1.0
    try:
        fixed = float(_get(st, "hm_vmax"))
    except (TypeError, ValueError):
        fixed = 0.0
    return g, (fixed if fixed > 0 else top)


def tick_labels(vmax, st):
    """Colour-bar end labels for 0 and vmax."""
    u = units(st)
    if u == "relative":
        return ["0", "max"]
    if u == "percent":
        return ["0%", f"{vmax:.3g}%"]
    return ["0s", f"{vmax:.2f}s" if vmax < 1 else f"{vmax:.1f}s"]


def colorbar_label(st):
    """User label, except the stock 'seconds' follows the chosen unit."""
    lbl = (st or {}).get("colorbar_label") or ""
    if lbl.strip().lower() == "seconds" and units(st) != "seconds":
        return _UNIT_LABELS[units(st)]
    return lbl
