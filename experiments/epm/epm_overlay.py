"""EPM-specific live overlay: fills the arm currently containing the
mouse, draws open arms as dashed outlines + closed arms as filled
polygons, and shows per-arm entry count + time labels."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QPen

from .zones import ARM_NAMES, ARM_LABELS, KIND_COLORS


def _point_in_polygon(x, y, poly):
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
    """Return the zone name containing the normalized point — arm_n/s/e/w
    or 'center_zone' — or None if outside every zone. Center checked first
    so it wins overlap with arms near the hub."""
    z = zd.get_zone("center_zone")
    if z and z.get("geometry") and _point_in_polygon(nx, ny, z["geometry"]):
        return "center_zone"
    for name in ARM_NAMES:
        z = zd.get_zone(name)
        if not z:
            continue
        geom = z.get("geometry") or []
        if _point_in_polygon(nx, ny, geom):
            return name
    return None


def _arm_kind(z):
    return (z.get("style") or {}).get("epm_kind", "closed")


def paint_epm_overlay(host, zd, painter, ox, oy, dw, dh):
    """Render: (a) per-arm style — open = dashed outline, closed = filled
    translucent body — (b) current-arm highlight stronger than base,
    (c) per-zone label + entries/time stats. Names + custom names show
    above the body or in label-pos overlay."""
    current = getattr(host, "_epm_current_arm", None)

    # ── Base per-arm draw (style by kind).
    pen_solid = painter.pen()
    for name in ARM_NAMES:
        z = zd.get_zone(name)
        if not z or len(z.get("geometry") or []) < 3:
            continue
        kind = _arm_kind(z)
        color_hex = z["style"].get("color", KIND_COLORS.get(kind, "#888"))
        base_color = QColor(color_hex)
        pts = [zd._norm_to_disp(p, ox, oy, dw, dh) for p in z["geometry"]]
        pts_int = [(int(x), int(y)) for x, y in pts]

        if kind == "closed":
            fill = QColor(base_color)
            fill.setAlpha(45)
            painter.setPen(Qt.NoPen)
            painter.setBrush(fill)
            zd._draw_polygon(painter, pts_int)
            pen = QPen(base_color, 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            zd._draw_polygon(painter, pts_int)
        else:
            # open / neutral / custom — dashed outline only.
            pen = QPen(base_color, 2,
                       Qt.DashLine if kind == "open" else Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            zd._draw_polygon(painter, pts_int)

    painter.setPen(pen_solid)

    # ── Current-arm highlight — stronger fill for closed, brighter
    # dashed outline for open.
    if current is not None and current != "center_zone":
        z = zd.get_zone(current)
        if z and z.get("geometry") and len(z["geometry"]) >= 3:
            kind = _arm_kind(z)
            color_hex = z["style"].get("color", KIND_COLORS.get(kind, "#888"))
            base_color = QColor(color_hex)
            pts = [zd._norm_to_disp(p, ox, oy, dw, dh) for p in z["geometry"]]
            pts_int = [(int(x), int(y)) for x, y in pts]
            if kind == "closed":
                hi = QColor(base_color)
                hi.setAlpha(110)
                painter.setPen(Qt.NoPen)
                painter.setBrush(hi)
                zd._draw_polygon(painter, pts_int)
            else:
                # Open / other — thick dashed outline + light fill.
                hi_fill = QColor(base_color)
                hi_fill.setAlpha(50)
                painter.setPen(Qt.NoPen)
                painter.setBrush(hi_fill)
                zd._draw_polygon(painter, pts_int)
                pen = QPen(base_color, 3, Qt.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                zd._draw_polygon(painter, pts_int)
    elif current == "center_zone":
        z = zd.get_zone("center_zone")
        if z and z.get("geometry") and len(z["geometry"]) >= 3:
            color = QColor(z["style"].get("color", "#BDBDBD"))
            color.setAlpha(110)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            pts = [zd._norm_to_disp(p, ox, oy, dw, dh) for p in z["geometry"]]
            zd._draw_polygon(painter, [(int(x), int(y)) for x, y in pts])

    # ── Labels + stats.
    show_names = bool(getattr(zd, "_arm_show_numbers", True))
    show_entries = bool(getattr(zd, "_arm_show_entries", True))
    show_timer = bool(getattr(zd, "_arm_show_timer", True))
    entries = getattr(host, "_epm_arm_entries", {}) or {}
    times = getattr(host, "_epm_arm_times", {}) or {}
    arm_custom = getattr(host, "_epm_arm_custom_names", {}) or {}

    name_labels = {}
    for name in ARM_NAMES:
        zone = zd.get_zone(name)
        kind = _arm_kind(zone) if zone else "closed"
        custom = arm_custom.get(name) or ""
        base = custom if custom else ARM_LABELS[name]
        tag = {"open": "Open", "closed": "Closed",
               "neutral": "Neutral", "custom": "Custom"}.get(kind, "")
        name_labels[name] = f"{base} ({tag})" if tag and not custom else base
    name_labels["center_zone"] = "Center"

    font = QFont("Arial", 9, QFont.Bold)
    painter.setFont(font)
    fm = painter.fontMetrics()
    for name in list(ARM_NAMES) + ["center_zone"]:
        z = zd.get_zone(name)
        if not z or len(z.get("geometry") or []) < 3:
            continue
        geom = z["geometry"]
        acx = sum(p[0] for p in geom) / len(geom)
        acy = sum(p[1] for p in geom) / len(geom)
        acx_d, acy_d = zd._norm_to_disp((acx, acy), ox, oy, dw, dh)
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
            if user_dragged:
                return anchor_x
            return anchor_x - text_w if anchor_x < acx_d else anchor_x

        if user_dragged:
            primary_y = ly + fm.ascent()
            stats_y_offset = fm.height() + 2
        elif ly < acy_d:
            primary_y = ly
            stats_y_offset = -fm.height() - 2
        else:
            primary_y = ly + fm.ascent()
            stats_y_offset = fm.height() + 2

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
        if hit_x1 > hit_x0:
            z["style"]["_label_rect"] = (
                hit_x0 - 4, hit_y0 - 4,
                (hit_x1 - hit_x0) + 8, (hit_y1 - hit_y0) + 8,
            )
        else:
            z["style"].pop("_label_rect", None)
