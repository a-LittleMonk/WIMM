"""Pure drawing helpers for body / trail / ellipse overlays.

Used by both the live preview and the annotated-video export thread. Free of
Qt widget references — caller passes flag values + a color resolver.
"""
import cv2


def draw_body_overlay(frame, r, frame_idx=None, results=None,
                     style="off", do_ellipse=False,
                     do_trail=False, trail_len=0, trail_fade=False,
                     color_fn=None):
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
        Body marker style. "none" = nothing; "off" or "dot" = body dot;
        "ends" = body dot + nose (green) + tail (blue) + axis line.
    do_ellipse, do_trail : bool
        Toggles for each overlay.
    trail_len : int
        Trail length in frames. 0 = all frames from start.
    color_fn : callable(name) -> (B, G, R)
        Resolves a logical name ("body") to BGR.
    """
    def _bgr(name):
        return color_fn(name) if color_fn else (0, 255, 255)

    cx, cy = r.get("x"), r.get("y")

    # Trail
    if do_trail and results and frame_idx is not None:
        start = 0 if trail_len == 0 else max(0, frame_idx - trail_len)
        trail = []
        for i in range(start, frame_idx):
            tr = results[i]
            if tr.get("x") is not None:
                trail.append((int(tr["x"]), int(tr["y"])))
        if trail_fade:
            for j in range(1, len(trail)):
                alpha = j / len(trail)
                intensity = int(80 + 175 * alpha)
                cv2.line(frame, trail[j - 1], trail[j],
                         (0, intensity, intensity), max(1, int(2 * alpha)), cv2.LINE_AA)
        else:
            solid_col = _bgr("body")
            for j in range(1, len(trail)):
                cv2.line(frame, trail[j - 1], trail[j],
                         solid_col, 2, cv2.LINE_AA)

    # Bounding ellipse
    if do_ellipse and cx is not None:
        sma = r.get("ellipse_semi_major")
        smi = r.get("ellipse_semi_minor")
        ang = r.get("ellipse_angle")
        if sma is not None:
            cv2.ellipse(frame, (int(cx), int(cy)),
                        (max(1, int(sma)), max(1, int(smi))),
                        ang, 0, 360, (100, 200, 255), 1, cv2.LINE_AA)

    # Body style: only "none" suppresses; everything else draws the body dot.
    if style != "none" and cx is not None:
        col = _bgr("body")
        cv2.circle(frame, (int(cx), int(cy)), 6, col, -1)
        cv2.circle(frame, (int(cx), int(cy)), 8, col, 2)

    # "ends" extras: nose + tail + axis line.
    if style == "ends":
        nx, ny = r.get("nose_x"), r.get("nose_y")
        tx, ty = r.get("tail_x"), r.get("tail_y")
        body_col = _bgr("body")
        if nx is not None and tx is not None:
            cv2.line(frame, (int(tx), int(ty)), (int(nx), int(ny)),
                     body_col, 1, cv2.LINE_AA)
        if nx is not None:
            nose_col = color_fn("nose") if color_fn else (0, 200, 0)
            cv2.circle(frame, (int(nx), int(ny)), 5, nose_col, -1)
            cv2.circle(frame, (int(nx), int(ny)), 7, nose_col, 2)
        if tx is not None:
            tail_col = color_fn("tail") if color_fn else (200, 100, 0)
            cv2.circle(frame, (int(tx), int(ty)), 4, tail_col, -1)
            cv2.circle(frame, (int(tx), int(ty)), 6, tail_col, 2)
