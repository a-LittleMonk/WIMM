"""Open-Field-specific overlays painted on top of the shared ZoneDrawer:
4x4 cell grid, current-cell highlight, per-cell number / timer / entry
counters, and the center-zone HUD. ZoneDrawer registers `paint_of_overlay`
as its OF-overlay callback in OpenFieldTab.__init__ and invokes it from
paintEvent — non-OF experiments leave the callback unset and get none of
this rendering."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QPen


def paint_of_overlay(zd, painter, ox, oy, dw, dh):
    """Render OF-specific overlays. Accesses ZoneDrawer state directly
    (cell counts, grid mode, etc.) so the rendering can stay in lock-step
    with whatever the user has dialed in via the OF UI."""
    # ── Cell highlight (current cell green-fill)
    if zd._cell_highlight_alpha > 0 and zd.arena:
        cell_id = zd._current_cell_id()
        color = QColor(zd._cell_highlight_color)
        color.setAlpha(zd._cell_highlight_alpha)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        if zd.zone_mode == "grid" and cell_id:
            idx = int(cell_id) - 1
            row, col = idx // 4, idx % 4
            quad = zd._grid_cell_corners(ox, oy, dw, dh, row, col)
            if quad:
                poly = [(int(p[0]), int(p[1])) for p in quad]
                zd._draw_polygon(painter, poly)
        elif zd.zone_mode != "grid" and cell_id == "C" and zd.center_zone:
            pts = [zd._norm_to_disp(p, ox, oy, dw, dh) for p in zd.center_zone]
            zd._draw_polygon(painter, [(int(x), int(y)) for x, y in pts])

    # ── Cell numbers / timers / entries
    if ((zd._cell_show_numbers or zd._cell_show_timer
         or zd._cell_show_entries) and zd.arena):
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.setBrush(Qt.NoBrush)
        font = QFont("Arial", 9, QFont.Bold)
        painter.setFont(font)
        small_font = QFont("Arial", 8)
        if zd.zone_mode == "grid":
            for idx in range(16):
                row, col = idx // 4, idx % 4
                quad = zd._grid_cell_corners(ox, oy, dw, dh, row, col)
                if not quad:
                    continue
                cx = int(sum(p[0] for p in quad) / 4)
                cy = int(sum(p[1] for p in quad) / 4)
                cid = str(idx + 1)
                if zd._cell_show_numbers:
                    painter.setFont(font)
                    fm = painter.fontMetrics()
                    tw = fm.horizontalAdvance(cid)
                    nx = cx - tw // 2
                    painter.setPen(QColor(0, 0, 0, 180))
                    painter.drawText(nx + 1, cy + 1, cid)
                    painter.setPen(QColor(255, 255, 255))
                    painter.drawText(nx, cy, cid)
                if zd._cell_show_timer:
                    painter.setFont(font)
                    secs = zd._cell_times.get(cid, 0.0)
                    label = f"{secs:.2f}"
                    fm = painter.fontMetrics()
                    tw = fm.horizontalAdvance(label)
                    tx = cx - tw // 2
                    painter.setPen(QColor(0, 0, 0, 180))
                    painter.drawText(tx + 1, cy + 13, label)
                    painter.setPen(QColor(180, 230, 180))
                    painter.drawText(tx, cy + 12, label)
                if zd._cell_show_entries:
                    tl = quad[0]
                    ex = int(tl[0]) + 4
                    ey = int(tl[1]) + 12
                    painter.setFont(small_font)
                    ent = int(zd._cell_entries.get(cid, 0))
                    elabel = f"#{ent}"
                    painter.setPen(QColor(0, 0, 0, 180))
                    painter.drawText(ex + 1, ey + 1, elabel)
                    painter.setPen(QColor(255, 215, 64))
                    painter.drawText(ex, ey, elabel)
        # Center HUD
        if zd.center_zone and zd.arena and (
            zd._cell_show_numbers or zd._cell_show_timer
            or zd._cell_show_entries
        ):
            arena_disp = [zd._norm_to_disp(p, ox, oy, dw, dh) for p in zd.arena]
            bits = []
            if zd._cell_show_numbers:
                bits.append("Center Zone:")
            if zd._cell_show_timer:
                bits.append(f"{zd._cell_times.get('C', 0.0):.2f}s")
            if zd._cell_show_entries:
                bits.append(f"#{int(zd._cell_entries.get('C', 0))}")
            label = "  ".join(bits)
            hud_font = QFont("Arial", 9, QFont.Bold)
            painter.setFont(hud_font)
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(label)
            th = fm.height()
            pad_x, pad_y = 6, 3
            box_w = tw + pad_x * 2
            box_h = th + pad_y * 2
            top_y   = min(p[1] for p in arena_disp)
            bot_y   = max(p[1] for p in arena_disp)
            left_x  = min(p[0] for p in arena_disp)
            right_x = max(p[0] for p in arena_disp)
            widget_h = zd.height()
            widget_w = zd.width()
            center_x = (left_x + right_x) / 2.0
            x0 = max(2, min(widget_w - box_w - 2, int(center_x - box_w / 2.0)))
            y0 = int(top_y) - box_h - 6
            if y0 < 2:
                y0 = int(bot_y) + 6
                if y0 + box_h > widget_h - 2:
                    y0 = max(2, widget_h - box_h - 2)
            painter.setPen(QPen(QColor(200, 200, 200), 1))
            painter.setBrush(QColor(20, 20, 20, 160))
            painter.drawRect(x0, y0, box_w, box_h)
            tx = x0 + pad_x
            ty = y0 + pad_y + fm.ascent()
            painter.setPen(QColor(0, 0, 0, 200))
            painter.drawText(tx + 1, ty + 1, label)
            painter.setPen(QColor(180, 230, 180))
            painter.drawText(tx, ty, label)


def paint_of_grid_lines(zd, painter, ox, oy, dw, dh):
    """4×4 grid lines drawn over the arena polygon. Painted AFTER the
    arena outline so the grid sits on top."""
    if zd.zone_mode != "grid" or not zd.arena:
        return
    pts = [zd._norm_to_disp(p, ox, oy, dw, dh) for p in zd.arena]
    TL, TR, BR, BL = zd._sorted_corners(pts)
    grid_color = QColor(zd._colors["grid"])
    grid_color.setAlpha(160)
    painter.setPen(QPen(grid_color, 1, Qt.SolidLine))
    painter.setBrush(Qt.NoBrush)
    for u in (0.25, 0.5, 0.75):
        top = (TL[0] + (TR[0] - TL[0]) * u, TL[1] + (TR[1] - TL[1]) * u)
        bot = (BL[0] + (BR[0] - BL[0]) * u, BL[1] + (BR[1] - BL[1]) * u)
        painter.drawLine(int(top[0]), int(top[1]), int(bot[0]), int(bot[1]))
    for v in (0.25, 0.5, 0.75):
        left  = (TL[0] + (BL[0] - TL[0]) * v, TL[1] + (BL[1] - TL[1]) * v)
        right = (TR[0] + (BR[0] - TR[0]) * v, TR[1] + (BR[1] - TR[1]) * v)
        painter.drawLine(int(left[0]), int(left[1]), int(right[0]), int(right[1]))
