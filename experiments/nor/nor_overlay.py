"""NOR live overlay — fills the interaction zone of whichever object the
mouse's NOSE is currently inside and renders per-object stats (name |
time | entries) next to each zone. The arena outline stays unfilled."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont

from .zones import OBJECT_NAMES, OBJECT_LABELS, zone_name, footprint_name

# Widget-px radius for the center drag handle. Also used by the
# event-filter hit-test in NORTab so the visual + click target match.
HANDLE_RADIUS_PX = 7


def _point_in_polygon(x, y, poly):
    """Ray-cast PIP. poly is list of (x, y) tuples."""
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


def point_to_object(zd, nx, ny):
    """Return obj_id whose interaction zone contains the normalized point,
    or None. First-wins (A then B) so overlapping zones don't double-count."""
    for obj_id in OBJECT_NAMES:
        z = zd.get_zone(zone_name(obj_id))
        if not z:
            continue
        geom = z.get("geometry") or []
        if _point_in_polygon(nx, ny, geom):
            return obj_id
    return None


def paint_nor_overlay(host, zd, painter, ox, oy, dw, dh):
    """Render: (a) translucent fill of the interaction zone currently
    containing the nose, (b) per-object label "Name | #N | Ts" placed at
    the zone centroid."""
    states = getattr(host, "_nor_objects", None) or {}
    current = getattr(host, "_nor_current_obj", None)
    entries_map = getattr(host, "_nor_object_entries", {}) or {}
    times_map = getattr(host, "_nor_object_times", {}) or {}

    show_names   = bool(getattr(zd, "_arm_show_numbers", True))
    show_entries = bool(getattr(zd, "_arm_show_entries", True))
    show_timer   = bool(getattr(zd, "_arm_show_timer", True))

    # ── Live fill: highlight whichever interaction zone the nose is in.
    if current is not None:
        z = zd.get_zone(zone_name(current))
        if z and z.get("geometry") and len(z["geometry"]) >= 3:
            color = QColor(z["style"].get("color", "#888"))
            color.setAlpha(120)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            pts = [zd._norm_to_disp(p, ox, oy, dw, dh) for p in z["geometry"]]
            zd._draw_polygon(painter, [(int(x), int(y)) for x, y in pts])

    # ── Per-object label (name + counters) at zone centroid.
    font = QFont("Arial", 9, QFont.Bold)
    painter.setFont(font)
    fm = painter.fontMetrics()
    for obj_id in OBJECT_NAMES:
        z = zd.get_zone(zone_name(obj_id))
        if not z or len(z.get("geometry") or []) < 3:
            continue
        state = states.get(obj_id) or {}
        label = state.get("name", OBJECT_LABELS[obj_id])
        role = state.get("role", "none")
        geom = z["geometry"]
        # Anchor: use style.label_pos_override (user drag) if present,
        # else top-center of the zone bbox (so text sits ABOVE the zone
        # outline instead of overlapping it).
        override = z["style"].get("label_pos_override")
        if override and len(override) == 2:
            lx, ly = zd._norm_to_disp(override, ox, oy, dw, dh)
            user_dragged = True
        else:
            cx_n = sum(p[0] for p in geom) / len(geom)
            top_y_n = min(p[1] for p in geom)
            lx, ly = zd._norm_to_disp((cx_n, top_y_n), ox, oy, dw, dh)
            user_dragged = False
        color = QColor(z["style"].get("color", "#fff"))

        # Track hit-rect for label-drag (matches YM convention).
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

        # Stack the two text lines ABOVE the top-of-zone anchor:
        #   stats line  (bottom — sits just above the zone outline)
        #   name line   (top    — one font-height above stats)
        # When the user has dragged the label, anchor at the drop point and
        # grow downward like a normal text box for a more natural feel.
        line_h = fm.height()
        gap = 2
        if user_dragged:
            name_y  = ly + fm.ascent()
            stats_y = name_y + line_h + gap
        else:
            stats_y = ly - gap                       # just above zone top
            name_y  = stats_y - line_h - gap         # one line above stats
        if show_names:
            text = label
            if role == "novel":
                text += " (N)"
            elif role == "familiar":
                text += " (F)"
            tw = fm.horizontalAdvance(text)
            x = lx - tw // 2  # centered on anchor x
            painter.setPen(QColor(0, 0, 0, 200))
            painter.drawText(x + 1, name_y + 1, text)
            painter.setPen(color)
            painter.drawText(x, name_y, text)
            _stamp(x, name_y, text)
        if show_entries or show_timer:
            parts = []
            if show_entries:
                parts.append(f"#{int(entries_map.get(obj_id, 0))}")
            if show_timer:
                parts.append(f"{float(times_map.get(obj_id, 0.0)):.2f}s")
            text = "  ".join(parts)
            tw = fm.horizontalAdvance(text)
            sx = lx - tw // 2
            painter.setPen(QColor(0, 0, 0, 200))
            painter.drawText(sx + 1, stats_y + 1, text)
            painter.setPen(color)
            painter.drawText(sx, stats_y, text)
            _stamp(sx, stats_y, text)
        if hit_x1 > hit_x0:
            z["style"]["_label_rect"] = (
                hit_x0 - 4, hit_y0 - 4,
                (hit_x1 - hit_x0) + 8, (hit_y1 - hit_y0) + 8,
            )
        else:
            z["style"].pop("_label_rect", None)

    # ── Center drag handles (one per placed object) ─────────────────────
    # Painted last so they sit on top of the zone fill + outline. The
    # event filter installed by NORTab hit-tests against the footprint
    # centroid using HANDLE_RADIUS_PX so visual + click area stay aligned.
    for obj_id in OBJECT_NAMES:
        fp = zd.get_zone(footprint_name(obj_id))
        if not fp or len(fp.get("geometry") or []) < 3:
            continue
        geom = fp["geometry"]
        cx_n = sum(p[0] for p in geom) / len(geom)
        cy_n = sum(p[1] for p in geom) / len(geom)
        hx, hy = zd._norm_to_disp((cx_n, cy_n), ox, oy, dw, dh)
        color = QColor(fp["style"].get("color", "#fff"))
        # White outer ring → object-colored inner dot. Reads against any
        # background.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 220))
        painter.drawEllipse(int(hx) - HANDLE_RADIUS_PX,
                            int(hy) - HANDLE_RADIUS_PX,
                            HANDLE_RADIUS_PX * 2, HANDLE_RADIUS_PX * 2)
        painter.setBrush(color)
        r_inner = max(2, HANDLE_RADIUS_PX - 2)
        painter.drawEllipse(int(hx) - r_inner, int(hy) - r_inner,
                            r_inner * 2, r_inner * 2)
