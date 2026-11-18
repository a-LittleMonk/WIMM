"""Pure drawing helpers for body / trail / ellipse overlays.

Used by both the live preview and the annotated-video export thread. Free of
Qt widget references — caller passes flag values + a color resolver.

Look follows the Mice Tracker redesign: a soft-coloured trail that fades
into a dim tail, and a dashed-ring "centroid" marker with two tick marks.
"""
import cv2
import numpy as np

_FONT = cv2.FONT_HERSHEY_SIMPLEX


def _scale(frame):
    """Overlay sizes are authored for a 640 px wide frame."""
    return max(0.75, frame.shape[1] / 640.0)


def _dashed_circle(frame, center, radius, color, thickness=1,
                   dash_deg=26, gap_deg=14):
    a = 0
    while a < 360:
        cv2.ellipse(frame, center, (radius, radius), 0, a, min(360, a + dash_deg),
                    color, thickness, cv2.LINE_AA)
        a += dash_deg + gap_deg


# Body-marker shapes: (key, label) — shared by the View popover.
MARKER_SHAPES = (
    ("ring", "Dashed ring"), ("dot", "Filled dot"), ("circle", "Circle"),
    ("cross", "Crosshair"), ("square", "Square"), ("diamond", "Diamond"),
    ("triangle", "Triangle"),
)


def _draw_marker_shape(frame, c, shape, rad, col, sc):
    """Centre marker of radius `rad` px around point `c`."""
    x, y = c
    th = max(1, int(round(1.5 * sc)))
    core = max(2, int(round(2 * sc)))
    if shape == "dot":
        cv2.circle(frame, c, rad, col, -1, cv2.LINE_AA)
        cv2.circle(frame, c, rad + 1, (10, 12, 14), 1, cv2.LINE_AA)
        return
    if shape == "circle":
        cv2.circle(frame, c, rad, col, th, cv2.LINE_AA)
    elif shape == "cross":
        gap = max(2, rad // 3)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            cv2.line(frame, (x + dx * gap, y + dy * gap), (x + dx * rad, y + dy * rad),
                     col, th, cv2.LINE_AA)
    elif shape in ("square", "diamond", "triangle"):
        if shape == "square":
            pts = [(x - rad, y - rad), (x + rad, y - rad), (x + rad, y + rad), (x - rad, y + rad)]
        elif shape == "diamond":
            pts = [(x, y - rad), (x + rad, y), (x, y + rad), (x - rad, y)]
        else:
            h = int(round(rad * 0.87))
            pts = [(x, y - rad), (x + h, y + rad // 2), (x - h, y + rad // 2)]
        cv2.polylines(frame, [np.array(pts, np.int32).reshape(-1, 1, 2)], True, col, th, cv2.LINE_AA)
    else:  # "ring" — dashed ring with two tick marks (top and left)
        _dashed_circle(frame, c, rad, col, 1)
        a, b = int(round(rad * 1.47)), int(round(rad * 1.07))
        cv2.line(frame, (x, y - a), (x, y - b), col, 1, cv2.LINE_AA)
        cv2.line(frame, (x - a, y), (x - b, y), col, 1, cv2.LINE_AA)
    # small centre dot on a white halo so the exact point stays readable
    cv2.circle(frame, c, core + 1, (255, 255, 255), -1, cv2.LINE_AA)
    cv2.circle(frame, c, core, col, -1, cv2.LINE_AA)


def _draw_trail(frame, results, frame_idx, trail_len, trail_fade, color, sc):
    start = 0 if trail_len == 0 else max(0, frame_idx - trail_len)
    pts = []
    for i in range(start, min(frame_idx + 1, len(results))):
        tr = results[i]
        if tr.get("x") is not None:
            pts.append((int(tr["x"]), int(tr["y"])))
    if len(pts) < 2:
        return
    # One thin width along the whole trail.
    thick = max(1, int(round(1.0 * sc)))

    def _line(img, seg):
        if len(seg) >= 2:
            cv2.polylines(img, [np.array(seg, np.int32).reshape(-1, 1, 2)],
                          False, color, thick, cv2.LINE_AA)

    if not trail_fade:
        _line(frame, pts)
        return
    # Fade = older parts gradually dimmer (never thinner): the newest ~40
    # samples are solid, the rest is split into bands of rising opacity.
    cut = max(0, len(pts) - 40)
    if cut > 1:
        alphas = (0.2, 0.35, 0.55)
        n = len(alphas)
        for k, alpha in enumerate(alphas):
            lo = cut * k // n
            hi = cut * (k + 1) // n
            if hi - lo < 1:
                continue
            overlay = frame.copy()
            _line(overlay, pts[lo:hi + 1])   # +1 joins it to the next band
            cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, dst=frame)
    _line(frame, pts[cut:])


def draw_body_overlay(frame, r, frame_idx=None, results=None,
                     style="off", do_ellipse=False,
                     do_trail=False, trail_len=0, trail_fade=False,
                     color_fn=None, tag_lines=None,
                     shape="dot", size=5):
    """Burn body / ellipse / trail overlays onto a numpy frame.

    Parameters
    ----------
    frame : np.ndarray
        BGR frame to draw on (mutated in place).
    r : dict
        Per-frame tracking record with keys x, y, ellipse_*.
    frame_idx : int | None
        Current frame index (needed for trail).
    results : list[dict] | None
        Full tracking results list (needed for trail).
    style : str
        Body marker style. "none" / "off" = nothing; "dot" = centre marker;
        "ends" = centre marker + nose (green) + tail + axis line.
    shape : str
        Centre marker shape — one of MARKER_SHAPES.
    size : int
        Centre marker radius in px, authored for a 640 px wide frame.
    do_ellipse, do_trail : bool
        Toggles for each overlay.
    trail_len : int
        Trail length in frames. 0 = all frames from start.
    color_fn : callable(name) -> (B, G, R)
        Resolves a logical name ("body", "trail", "nose", "tail") to BGR.
    tag_lines : list[str] | None
        Optional info-tag text (burned into exports; the live preview draws
        the tag with Qt instead).
    """
    def _bgr(name, default):
        try:
            return color_fn(name) if color_fn else default
        except Exception:
            return default

    sc = _scale(frame)
    cx, cy = r.get("x"), r.get("y")

    # Trail
    if do_trail and results and frame_idx is not None:
        _draw_trail(frame, results, frame_idx, trail_len, trail_fade,
                    _bgr("trail", (174, 211, 228)), sc)

    # Bounding ellipse
    if do_ellipse and cx is not None:
        sma = r.get("ellipse_semi_major")
        smi = r.get("ellipse_semi_minor")
        ang = r.get("ellipse_angle")
        if sma is not None:
            cv2.ellipse(frame, (int(cx), int(cy)),
                        (max(1, int(sma)), max(1, int(smi))),
                        ang, 0, 360, _bgr("arena", (198, 180, 169)), 1, cv2.LINE_AA)

    if style in ("none", "off") or cx is None:
        return
    col = _bgr("body", (247, 244, 242))
    c = (int(cx), int(cy))
    _draw_marker_shape(frame, c, shape, max(2, int(round(size * sc))), col, sc)

    # "ends" extras: nose + tail + axis line.
    if style == "ends":
        nx, ny = r.get("nose_x"), r.get("nose_y")
        tx, ty = r.get("tail_x"), r.get("tail_y")
        if nx is not None and tx is not None:
            cv2.line(frame, (int(tx), int(ty)), (int(nx), int(ny)),
                     col, 1, cv2.LINE_AA)
        if nx is not None:
            nose_col = _bgr("nose", (133, 187, 93))
            cv2.circle(frame, (int(nx), int(ny)), max(3, int(round(4 * sc))), nose_col, -1, cv2.LINE_AA)
            cv2.circle(frame, (int(nx), int(ny)), max(4, int(round(6 * sc))), nose_col, 1, cv2.LINE_AA)
        if tx is not None:
            tail_col = _bgr("tail", (198, 180, 169))
            cv2.circle(frame, (int(tx), int(ty)), max(2, int(round(3 * sc))), tail_col, -1, cv2.LINE_AA)
            cv2.circle(frame, (int(tx), int(ty)), max(3, int(round(5 * sc))), tail_col, 1, cv2.LINE_AA)

    if tag_lines:
        _draw_tag(frame, c, tag_lines, sc)


def _draw_tag(frame, c, lines, sc):
    """Small dark info tag next to the marker (export burn-in)."""
    fs = 0.34 * sc
    th = max(1, int(round(sc)))
    widths = [cv2.getTextSize(s, _FONT, fs, th)[0][0] for s in lines]
    w = int(max(widths) + 14 * sc)
    h = int((12 * len(lines) + 6) * sc)
    H, W = frame.shape[:2]
    right = c[0] + int(20 * sc) + w < W
    bx = c[0] + int(20 * sc) if right else c[0] - int(20 * sc) - w
    by = max(2, c[1] - int(34 * sc))
    overlay = frame.copy()
    cv2.rectangle(overlay, (bx, by), (bx + w, by + h), (14, 12, 10), -1)
    cv2.addWeighted(overlay, 0.82, frame, 0.18, 0, dst=frame)
    cv2.rectangle(frame, (bx, by), (bx + w, by + h), (200, 200, 200), 1, cv2.LINE_AA)
    for i, s in enumerate(lines):
        col = (247, 244, 242) if i == 0 else (217, 209, 201)
        cv2.putText(frame, s, (bx + int(7 * sc), by + int((13 + 12 * i) * sc)),
                    _FONT, fs, col, th, cv2.LINE_AA)
