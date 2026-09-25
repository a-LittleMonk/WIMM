"""Open-Field-specific overlays painted on top of the shared ZoneDrawer:
current-cell highlight, per-cell number / timer / entry counters and the 4×4
grid lines. ZoneDrawer registers `paint_of_overlay` as its OF-overlay
callback in OpenFieldTab.__init__ and invokes it from paintEvent — non-OF
experiments leave the callback unset and get none of this rendering.

Look follows the redesign: small mono cell numbers in each cell's top-left,
entries top-right, dwell time centred. The center-zone tag (with its own
timer / entry count) is painted by ZoneDrawer itself.
"""
from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPen

from gui import theme


def _mono(px, bold=False):
    f = QFont(theme.mono_family())
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def paint_of_overlay(zd, painter, ox, oy, dw, dh):
    """Render OF-specific overlays. Accesses ZoneDrawer state directly
    (cell counts, grid mode, etc.) so the rendering can stay in lock-step
    with whatever the user has dialed in via the OF UI."""
    # ── Cell highlight (current cell fill)
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

    # ── Cell numbers / timers / entries (grid mode)
    if not ((zd._cell_show_numbers or zd._cell_show_timer
             or zd._cell_show_entries) and zd.arena and zd.zone_mode == "grid"):
        return
    painter.setBrush(Qt.NoBrush)
    for idx in range(16):
        row, col = idx // 4, idx % 4
        quad = zd._grid_cell_corners(ox, oy, dw, dh, row, col)
        if not quad:
            continue
        cid = str(idx + 1)
        tl, tr = quad[0], quad[1]
        if zd._cell_show_numbers:
            painter.setFont(_mono(9))
            c = QColor("#DDEBF2")
            c.setAlphaF(0.8)
            painter.setPen(c)
            painter.drawText(int(tl[0]) + 5, int(tl[1]) + 13, cid)
        if zd._cell_show_entries:
            painter.setFont(_mono(9))
            ent = int(zd._cell_entries.get(cid, 0))
            label = f"#{ent}"
            tw = painter.fontMetrics().horizontalAdvance(label)
            painter.setPen(QColor(zd._colors.get("trail", "#E4D3AE")))
            painter.drawText(int(tr[0]) - tw - 5, int(tr[1]) + 13, label)
        if zd._cell_show_timer:
            cx = sum(p[0] for p in quad) / 4.0
            cy = sum(p[1] for p in quad) / 4.0
            secs = zd._cell_times.get(cid, 0.0)
            label = f"{secs:.1f}s"
            painter.setFont(_mono(10, True))
            tw = painter.fontMetrics().horizontalAdvance(label)
            painter.setPen(QColor(0, 0, 0, 150))
            painter.drawText(int(cx - tw / 2.0) + 1, int(cy) + 5, label)
            painter.setPen(QColor("#E6EAEE"))
            painter.drawText(int(cx - tw / 2.0), int(cy) + 4, label)


def paint_of_grid_lines(zd, painter, ox, oy, dw, dh):
    """4×4 grid lines drawn over the arena polygon. Painted AFTER the
    arena outline so the grid sits on top."""
    if zd.zone_mode != "grid" or not zd.arena:
        return
    pts = [zd._norm_to_disp(p, ox, oy, dw, dh) for p in zd.arena]
    TL, TR, BR, BL = zd._sorted_corners(pts)
    grid_color = QColor(zd._colors["grid"])
    grid_color.setAlphaF(0.5)
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
