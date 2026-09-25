"""cv2 burn-in helpers — overlays drawn onto numpy frames for video
export so the exported clip matches the Qt live preview.

Two entry points:
  - _draw_cell_overlay_cv2: cell highlight + per-cell text + center tag
  - _draw_zones_on_frame_cv2: arena outline, center polygon, grid lines,
    exclusion mask shading
"""
import cv2
import numpy as np

_FONT = cv2.FONT_HERSHEY_SIMPLEX


def _sc(frame):
    return max(0.75, frame.shape[1] / 640.0)


def _dashed_poly(frame, pts, color, thickness=1, dash=9, gap=5):
    """Dashed closed polyline (pixel-length dashes)."""
    n = len(pts)
    for k in range(n):
        p0 = np.array(pts[k], dtype=float)
        p1 = np.array(pts[(k + 1) % n], dtype=float)
        length = float(np.linalg.norm(p1 - p0))
        if length < 1:
            continue
        d = (p1 - p0) / length
        pos = 0.0
        while pos < length:
            a = p0 + d * pos
            b = p0 + d * min(length, pos + dash)
            cv2.line(frame, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])),
                     color, thickness, cv2.LINE_AA)
            pos += dash + gap


def _draw_tag(frame, x, y, text, fill_bgr, text_bgr, sc):
    """Small filled tag above (x, y) — e.g. "CENTER 50% · 1.2s · #2"."""
    fs = 0.36 * sc
    th = max(1, int(round(sc)))
    (tw, tht), _ = cv2.getTextSize(text, _FONT, fs, th)
    pad = int(5 * sc)
    h = int(14 * sc)
    x0, y0 = int(x), int(y) - h - 1
    y0 = max(0, y0)
    cv2.rectangle(frame, (x0, y0), (x0 + tw + 2 * pad, y0 + h), fill_bgr, -1)
    cv2.putText(frame, text, (x0 + pad, y0 + int(h * 0.72)), _FONT, fs,
                text_bgr, th, cv2.LINE_AA)


def _center_tag_text(host, cell_times=None, cell_entries=None,
                     draw_timer=False, draw_entries=False):
    pct = getattr(getattr(host, "spin_center_pct", None), "value", lambda: None)()
    bits = ["CENTER" + (f" {int(pct)}%" if pct else "")]
    if draw_timer and cell_times is not None:
        bits.append(f"{cell_times.get('C', 0.0):.1f}s")
    if draw_entries and cell_entries is not None:
        bits.append(f"#{int((cell_entries or {}).get('C', 0))}")
    return " · ".join(bits)


def _draw_cell_overlay_cv2(host, frame, active_cell, cell_times, cell_entries,
                            draw_highlight=True, draw_numbers=True,
                            draw_timer=True, draw_entries=True):
    """Burn the cell-highlight fill + numbers/timer/entries text onto
    a frame. Mirrors zone_drawer's Qt paint of the same elements."""
    zd = host.zone_drawer
    arena = zd.get_arena_pixels() if hasattr(zd, "get_arena_pixels") else None
    if not arena or len(arena) < 3:
        return
    sc = _sc(frame)

    # ── Active-cell highlight (semi-transparent fill)
    if draw_highlight and active_cell is not None:
        quad = None
        if zd.zone_mode == "grid":
            try:
                idx = int(active_cell) - 1
            except (TypeError, ValueError):
                idx = None
            if idx is not None and 0 <= idx < 16 and len(arena) == 4:
                quad = host._grid_cell_quad_px(arena, idx // 4, idx % 4)
        elif zd.zone_mode != "grid" and active_cell == "C":
            center_pix = zd.get_center_pixels()
            if center_pix and len(center_pix) >= 3:
                quad = center_pix
        if quad:
            pts = np.array(quad, dtype=np.int32).reshape(-1, 1, 2)
            overlay = frame.copy()
            # Use the user-picked highlight color from zone_drawer state.
            hl_hex = getattr(zd, "_cell_highlight_color", "#C9D1DE")
            hl_alpha = max(0, min(255, int(getattr(zd, "_cell_highlight_alpha", 60))))
            from gui.open_field_tab import _hex_to_bgr
            hl_bgr = _hex_to_bgr(hl_hex)
            cv2.fillPoly(overlay, [pts], hl_bgr)
            a = hl_alpha / 255.0
            cv2.addWeighted(overlay, a, frame, 1.0 - a, 0, dst=frame)

    # ── Cell numbers / timer / entries text
    if not (draw_numbers or draw_timer or draw_entries):
        return
    if zd.zone_mode == "grid" and len(arena) == 4:
        for idx in range(16):
            row, col = idx // 4, idx % 4
            quad = host._grid_cell_quad_px(arena, row, col)
            cx = int(sum(p[0] for p in quad) / 4)
            cy = int(sum(p[1] for p in quad) / 4)
            cid = str(idx + 1)
            tl, tr = quad[0], quad[1]
            if draw_numbers:
                cv2.putText(frame, cid, (int(tl[0] + 5 * sc), int(tl[1] + 13 * sc)),
                            _FONT, 0.36 * sc, (242, 235, 221), 1, cv2.LINE_AA)
            if draw_entries:
                label = f"#{int(cell_entries.get(cid, 0))}"
                (tw, _th), _ = cv2.getTextSize(label, _FONT, 0.36 * sc, 1)
                cv2.putText(frame, label, (int(tr[0] - tw - 5 * sc), int(tr[1] + 13 * sc)),
                            _FONT, 0.36 * sc, host._bgr("trail"), 1, cv2.LINE_AA)
            if draw_timer:
                label = f"{cell_times.get(cid, 0.0):.1f}s"
                (tw, _th), _ = cv2.getTextSize(label, _FONT, 0.38 * sc, 1)
                pos = (int(cx - tw / 2), int(cy + 4 * sc))
                cv2.putText(frame, label, (pos[0] + 1, pos[1] + 1), _FONT, 0.38 * sc,
                            (20, 18, 16), 1, cv2.LINE_AA)
                cv2.putText(frame, label, pos, _FONT, 0.38 * sc, (250, 234, 230), 1, cv2.LINE_AA)
    # Center tag — with the running timer / entry count of the center zone.
    pts = zd.get_center_pixels()
    if pts and len(pts) >= 3 and (draw_timer or draw_entries):
        tx = min(int(p[0]) for p in pts)
        ty = min(int(p[1]) for p in pts)
        _draw_tag(frame, tx, ty,
                  _center_tag_text(host, cell_times, cell_entries, draw_timer, draw_entries),
                  host._bgr("center_zone"), (38, 24, 18), sc)


def _draw_zones_on_frame_cv2(host, frame, draw_arena=True,
                             draw_center=True, draw_grid=True,
                             draw_exclusion=True):
    """Burn arena outline / center polygon / grid lines onto a numpy
    frame using cv2. Matches what zone_drawer paints in Qt so the
    exported video looks like the live preview. Flags allow the
    export pipeline to opt out of individual layers."""
    sc = _sc(frame)
    arena = host.zone_drawer.get_arena_pixels() if hasattr(host, "zone_drawer") else None
    if draw_arena and arena and len(arena) >= 3:
        pts = np.array(arena, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(frame, [pts], True, host._bgr("arena"),
                      max(1, int(round(1.5 * sc))), cv2.LINE_AA)
        for (x, y) in arena:
            r = int(round(4 * sc))
            cv2.rectangle(frame, (x - r, y - r), (x + r, y + r), (14, 12, 10), -1)
            cv2.rectangle(frame, (x - r, y - r), (x + r, y + r), host._bgr("arena"), 1, cv2.LINE_AA)
    center = host.zone_drawer.get_center_pixels() if hasattr(host, "zone_drawer") else None
    if draw_center and center and len(center) >= 3:
        cpts = np.array(center, dtype=np.int32).reshape(-1, 1, 2)
        col = host._bgr("center_zone")
        overlay = frame.copy()
        cv2.fillPoly(overlay, [cpts], col)
        cv2.addWeighted(overlay, 0.12, frame, 0.88, 0, dst=frame)
        _dashed_poly(frame, center, col, max(1, int(round(1.3 * sc))),
                     dash=int(8 * sc), gap=int(4 * sc))
        _draw_tag(frame, min(p[0] for p in center), min(p[1] for p in center),
                  _center_tag_text(host), col, (38, 24, 18), sc)
    if (draw_grid and host.zone_drawer.zone_mode == "grid"
            and arena and len(arena) == 4):
        TL, TR, BR, BL = host.zone_drawer._sorted_corners(arena)
        col = host._bgr("grid")
        overlay = frame.copy()

        def bilin(u, v):
            top = (TL[0] + (TR[0] - TL[0]) * u, TL[1] + (TR[1] - TL[1]) * u)
            bot = (BL[0] + (BR[0] - BL[0]) * u, BL[1] + (BR[1] - BL[1]) * u)
            return (int(top[0] + (bot[0] - top[0]) * v),
                    int(top[1] + (bot[1] - top[1]) * v))
        for k in range(1, 4):
            t = k / 4.0
            cv2.line(overlay, bilin(t, 0), bilin(t, 1), col, 1, cv2.LINE_AA)
            cv2.line(overlay, bilin(0, t), bilin(1, t), col, 1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, dst=frame)
    # Exclusion mask shading.
    if draw_exclusion:
        excl = host.zone_drawer.get_exclusion_mask() if hasattr(host, "zone_drawer") else None
        if excl is not None and excl.any():
            try:
                shade = frame.copy()
                shade[excl > 0] = (40, 40, 200)
                cv2.addWeighted(shade, 0.35, frame, 0.65, 0, dst=frame)
            except Exception:
                pass
