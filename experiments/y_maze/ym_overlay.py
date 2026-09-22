"""Y-Maze-specific live overlay: fills the arm currently containing the
mouse and shows per-arm entry counts + time-in-arm. Registered with the
shared ZoneDrawer in YMazeTab.__init__ so the rendering code physically
lives in the Y-maze plugin instead of the base."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont

from .zones import ARM_NAMES, ARM_LABELS


def _point_in_polygon(x, y, poly):
    """Ray-cast point-in-polygon. poly is a list of (x, y) tuples."""
    n = len(poly)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def point_to_arm(zd, nx, ny):
    """Return the zone name containing the normalized point — arm_a/b/c
    or 'neutral_zone' — or None if the body is outside every zone.
    Checks neutral first so it wins over arm overlap near the hub."""
    z = zd.get_zone("neutral_zone")
    if z and z.get("geometry") and _point_in_polygon(nx, ny, z["geometry"]):
        return "neutral_zone"
    for name in ARM_NAMES:
        z = zd.get_zone(name)
        if not z:
            continue
        geom = z.get("geometry") or []
        if _point_in_polygon(nx, ny, geom):
            return name
    return None


def paint_ym_overlay(host, zd, painter, ox, oy, dw, dh):
    """Render: (a) translucent fill of the arm currently containing the
    body, (b) a secondary "#N | Ts" label below each arm's name showing
    live entries + accumulated time."""
    # ── Live fill: highlight whichever arm the mouse is currently in.
    current = getattr(host, "_ym_current_arm", None)
    if current is not None:
        z = zd.get_zone(current)
        if z and z.get("geometry") and len(z["geometry"]) >= 3:
            color = QColor(z["style"].get("color", "#888"))
            color.setAlpha(120)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            pts = [zd._norm_to_disp(p, ox, oy, dw, dh) for p in z["geometry"]]
            zd._draw_polygon(painter, [(int(x), int(y)) for x, y in pts])

    # ── Per-zone labels (primary "Arm A/B/C" / "Neutral" + stats line).
    # Primary label moved here (was in zone_drawer schema label_text) so we
    # can gate it on zd._arm_show_numbers. Stats row gated on
    # _arm_show_entries / _arm_show_timer.
    show_names = bool(getattr(zd, "_arm_show_numbers", True))
    show_entries = bool(getattr(zd, "_arm_show_entries", True))
    show_timer = bool(getattr(zd, "_arm_show_timer", True))
    entries = getattr(host, "_ym_arm_entries", {}) or {}
    times = getattr(host, "_ym_arm_times", {}) or {}
    name_labels = dict(ARM_LABELS)
    name_labels["neutral_zone"] = "Neutral"
    font = QFont("Arial", 9, QFont.Bold)
    painter.setFont(font)
    fm = painter.fontMetrics()
    for name in list(ARM_NAMES) + ["neutral_zone"]:
        z = zd.get_zone(name)
        if not z or len(z.get("geometry") or []) < 3:
            continue
        geom = z["geometry"]
        # Arm centroid (display coords) — used to align text so it grows
        # AWAY from the arm rectangle, never back into it.
        acx = sum(p[0] for p in geom) / len(geom)
        acy = sum(p[1] for p in geom) / len(geom)
        acx_d, acy_d = zd._norm_to_disp((acx, acy), ox, oy, dw, dh)
        # User-drag override takes priority over the auto-computed label_pos.
        # _rebuild_template builds fresh zones without an override key, so any
        # arm-handle drag naturally resets the label back to default.
        override = z["style"].get("label_pos_override")
        if override and len(override) == 2:
            lx, ly = zd._norm_to_disp(override, ox, oy, dw, dh)
            user_dragged = True
        else:
            lpos = z["style"].get("label_pos")
            if lpos and len(lpos) == 2:
                lx, ly = zd._norm_to_disp(lpos, ox, oy, dw, dh)
            else:
                lx, ly = acx_d, acy_d
            user_dragged = False
        color = QColor(z["style"].get("color", "#fff"))

        def _aligned_x(text_w, anchor_x):
            # Auto-pos: anchor is OUTER edge — text grows away from arm.
            # User-dragged: simple left-anchored so it lands where dropped.
            if user_dragged:
                return anchor_x
            return anchor_x - text_w if anchor_x < acx_d else anchor_x

        # Vertical alignment: same idea. For user-dragged, baseline below
        # the click point feels natural.
        if user_dragged:
            primary_y = ly + fm.ascent()
            stats_y_offset = fm.height() + 2
        elif ly < acy_d:
            primary_y = ly
            stats_y_offset = -fm.height() - 2   # stats ABOVE primary
        else:
            primary_y = ly + fm.ascent()
            stats_y_offset = fm.height() + 2    # stats BELOW primary

        # Track the union rect of every line we draw — used by zone_drawer
        # mousePressEvent to hit-test label drags. Reset each paint.
        hit_x0 = hit_y0 = 10**9
        hit_x1 = hit_y1 = -10**9
        def _stamp(x, y, text):
            nonlocal hit_x0, hit_y0, hit_x1, hit_y1
            w = fm.horizontalAdvance(text)
            asc, desc = fm.ascent(), fm.descent()
            hit_x0 = min(hit_x0, x)
            hit_y0 = min(hit_y0, y - asc)
            hit_x1 = max(hit_x1, x + w)
            hit_y1 = max(hit_y1, y + desc)

        if show_names:
            label = name_labels[name]
            tw = fm.horizontalAdvance(label)
            x = _aligned_x(tw, lx)
            painter.setPen(color)
            painter.drawText(x, primary_y, label)
            _stamp(x, primary_y, label)
        if show_entries or show_timer:
            parts = []
            if show_entries:
                parts.append(f"#{int(entries.get(name, 0))}")
            if show_timer:
                parts.append(f"{float(times.get(name, 0.0)):.2f}s")
            text = "  ".join(parts)
            tw = fm.horizontalAdvance(text)
            sx = _aligned_x(tw, lx)
            sy = primary_y + stats_y_offset
            painter.setPen(QColor(0, 0, 0, 200))
            painter.drawText(sx + 1, sy + 1, text)
            painter.setPen(color)
            painter.drawText(sx, sy, text)
            _stamp(sx, sy, text)
        # Pad the hit rect 4px so the click target isn't pixel-tight.
        if hit_x1 > hit_x0:
            z["style"]["_label_rect"] = (
                hit_x0 - 4, hit_y0 - 4,
                (hit_x1 - hit_x0) + 8, (hit_y1 - hit_y0) + 8,
            )
        else:
            z["style"].pop("_label_rect", None)
