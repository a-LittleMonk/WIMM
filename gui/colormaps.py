"""Colour ramps shared by the video-canvas heatmap, the occupancy mini-map and
the graphs (same viridis anchors as the redesign mock-up)."""
import numpy as np

_VIR = np.array([[68, 1, 84], [65, 68, 135], [42, 120, 142],
                 [34, 168, 132], [122, 209, 81], [253, 231, 37]], dtype=float)


def viridis(t):
    """Map t∈[0,1] (scalar or ndarray) to RGB uint8 (…, 3)."""
    t = np.clip(np.asarray(t, dtype=float), 0.0, 1.0)
    p = t * 5.0
    i = np.minimum(4, np.floor(p).astype(int))
    f = (p - i)[..., None]
    rgb = _VIR[i] + (_VIR[i + 1] - _VIR[i]) * f
    return np.rint(rgb).astype(np.uint8)


def heat_rgba(grid, empty=(26, 30, 34, 0), gamma=0.5):
    """Occupancy grid (seconds) → RGBA uint8 image; empty cells transparent
    (alpha from `empty`). Square-root scale like the mock-up."""
    g = np.asarray(grid, dtype=float)
    vmax = float(g.max()) if g.size else 0.0
    out = np.zeros(g.shape + (4,), dtype=np.uint8)
    out[...] = empty
    if vmax <= 0:
        return out, 0.0
    mask = g > 0
    rgb = viridis((g / vmax) ** gamma)
    out[mask, :3] = rgb[mask]
    out[mask, 3] = 255
    return out, vmax
