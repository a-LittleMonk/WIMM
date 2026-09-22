"""cv2 burn-in helpers — overlays drawn onto numpy frames for video
export so the exported clip matches the Qt live preview.

Two entry points:
  - _draw_cell_overlay_cv2: cell highlight + per-cell text + Center HUD
  - _draw_zones_on_frame_cv2: arena outline, center polygon, grid lines,
    exclusion mask shading
"""
import cv2
import numpy as np


def _draw_cell_overlay_cv2(host, frame, active_cell, cell_times, cell_entries,
                            draw_highlight=True, draw_numbers=True,
                            draw_timer=True, draw_entries=True):
    """Burn the cell-highlight fill + numbers/timer/entries text onto
    a frame. Mirrors zone_drawer's Qt paint of the same elements."""
    zd = host.zone_drawer
    arena = zd.get_arena_pixels() if hasattr(zd, "get_arena_pixels") else None
    if not arena or len(arena) < 3:
        return

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
            hl_hex = getattr(zd, "_cell_highlight_color", "#3CDC64")
            hl_alpha = max(0, min(255, int(getattr(zd, "_cell_highlight_alpha", 100))))
            from gui.open_field_tab import _hex_to_bgr
            hl_bgr = _hex_to_bgr(hl_hex)
            cv2.fillPoly(overlay, [pts], hl_bgr)
            a = hl_alpha / 255.0
            cv2.addWeighted(overlay, a, frame, 1.0 - a, 0, dst=frame)

    # ── Cell numbers / timer / entries text
    if not (draw_numbers or draw_timer or draw_entries):
        return
    font = cv2.FONT_HERSHEY_SIMPLEX
    if zd.zone_mode == "grid" and len(arena) == 4:
        for idx in range(16):
            row, col = idx // 4, idx % 4
            quad = host._grid_cell_quad_px(arena, row, col)
            cx = int(sum(p[0] for p in quad) / 4)
            cy = int(sum(p[1] for p in quad) / 4)
            cid = str(idx + 1)
            if draw_numbers:
                (tw, th), _ = cv2.getTextSize(cid, font, 0.45, 1)
                nx = cx - tw // 2
                cv2.putText(frame, cid, (nx + 1, cy + 1), font, 0.45, (0, 0, 0), 2, cv2.LINE_AA)
                cv2.putText(frame, cid, (nx, cy), font, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
            if draw_timer:
                label = f"{cell_times.get(cid, 0.0):.2f}"
                (tw, th), _ = cv2.getTextSize(label, font, 0.40, 1)
                tx = cx - tw // 2
                cv2.putText(frame, label, (tx + 1, cy + 14), font, 0.40, (0, 0, 0), 2, cv2.LINE_AA)
                cv2.putText(frame, label, (tx, cy + 13), font, 0.40, (180, 230, 180), 1, cv2.LINE_AA)
            if draw_entries:
                tl = quad[0]
                ex = int(tl[0]) + 4
                ey = int(tl[1]) + 14
                label = f"#{int(cell_entries.get(cid, 0))}"
                cv2.putText(frame, label, (ex + 1, ey + 1), font, 0.36, (0, 0, 0), 2, cv2.LINE_AA)
                cv2.putText(frame, label, (ex, ey), font, 0.36, (64, 215, 255), 1, cv2.LINE_AA)
    # Center HUD — pinned just OUTSIDE the arena (above its top edge).
    # Falls back to below the arena if there's no room at the top.
    pts = zd.get_center_pixels()
    if pts and len(pts) >= 3 and arena and len(arena) >= 3 and (
        draw_numbers or draw_timer or draw_entries
    ):
        # Build HUD text from enabled fields.
        bits = []
        if draw_numbers:
            bits.append("Center Zone:")
        if draw_timer:
            bits.append(f"{cell_times.get('C', 0.0):.2f}s")
        if draw_entries:
            bits.append(f"#{int(cell_entries.get('C', 0))}")
        label = "  ".join(bits)
        (tw, th), _ = cv2.getTextSize(label, font, 0.50, 1)
        pad_x, pad_y = 8, 5
        box_w = tw + pad_x * 2
        box_h = th + pad_y * 2
        h_frame, w_frame = frame.shape[:2]
        top_y    = min(int(p[1]) for p in arena)
        bot_y    = max(int(p[1]) for p in arena)
        left_x   = min(int(p[0]) for p in arena)
        right_x  = max(int(p[0]) for p in arena)
        # Default: above the arena, horizontally centered on the arena.
        center_x = (left_x + right_x) // 2
        x0 = max(2, min(w_frame - box_w - 2, center_x - box_w // 2))
        y0 = top_y - box_h - 6
        if y0 < 2:
            # Not enough headroom — drop below the arena instead.
            y0 = bot_y + 6
            if y0 + box_h > h_frame - 2:
                y0 = max(2, h_frame - box_h - 2)
        # Semi-transparent dark background.
        overlay = frame.copy()
        cv2.rectangle(overlay, (x0, y0), (x0 + box_w, y0 + box_h), (20, 20, 20), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, dst=frame)
        cv2.rectangle(frame, (x0, y0), (x0 + box_w, y0 + box_h),
                      (200, 200, 200), 1, cv2.LINE_AA)
        tx = x0 + pad_x
        ty = y0 + pad_y + th
        cv2.putText(frame, label, (tx + 1, ty + 1), font, 0.50, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(frame, label, (tx, ty), font, 0.50, (180, 230, 180), 1, cv2.LINE_AA)


def _draw_zones_on_frame_cv2(host, frame, draw_arena=True,
                             draw_center=True, draw_grid=True,
                             draw_exclusion=True):
    """Burn arena outline / center polygon / grid lines onto a numpy
    frame using cv2. Matches what zone_drawer paints in Qt so the
    exported video looks like the live preview. Flags allow the
    export pipeline to opt out of individual layers."""
    arena = host.zone_drawer.get_arena_pixels() if hasattr(host, "zone_drawer") else None
    if draw_arena and arena and len(arena) >= 3:
        pts = np.array(arena, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(frame, [pts], True, host._bgr("arena"), 2, cv2.LINE_AA)
    center = host.zone_drawer.get_center_pixels() if hasattr(host, "zone_drawer") else None
    if draw_center and center and len(center) >= 3:
        pts = np.array(center, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(frame, [pts], True, host._bgr("center_zone"), 2, cv2.LINE_AA)
    if (draw_grid and host.zone_drawer.zone_mode == "grid"
            and arena and len(arena) == 4):
        TL, TR, BR, BL = host.zone_drawer._sorted_corners(arena)
        col = host._bgr("grid")
        def bilin(u, v):
            top = (TL[0] + (TR[0] - TL[0]) * u, TL[1] + (TR[1] - TL[1]) * u)
            bot = (BL[0] + (BR[0] - BL[0]) * u, BL[1] + (BR[1] - BL[1]) * u)
            return (int(top[0] + (bot[0] - top[0]) * v),
                    int(top[1] + (bot[1] - top[1]) * v))
        for k in range(1, 4):
            t = k / 4.0
            cv2.line(frame, bilin(t, 0), bilin(t, 1), col, 1, cv2.LINE_AA)
            cv2.line(frame, bilin(0, t), bilin(1, t), col, 1, cv2.LINE_AA)
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
