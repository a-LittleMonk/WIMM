"""Icon set from the Mice Tracker redesign (16×16 line icons).

`pixmap(name, size, color)` renders an inline SVG with QtSvg, HiDPI aware and
cached.  `icon(name, size, color)` wraps it in a QIcon.  Colours come from
`gui.theme` tokens at call time, so callers re-render on theme changes.
"""
from PyQt5.QtCore import QByteArray, QRectF, Qt
from PyQt5.QtGui import QIcon, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QApplication

# name -> (inner svg markup, "stroke"|"fill", stroke-width)
_ICONS = {
    "queue":    ('<path d="M2.5 4h11M2.5 8h11M2.5 12h7"/>', "stroke", 1.4),
    "config":   ('<path d="M2.5 4h6M11.5 4h2M2.5 8h2M7.5 8h6M2.5 12h8M13.5 12h0"/>'
                 '<circle cx="10" cy="4" r="1.5"/><circle cx="6" cy="8" r="1.5"/>'
                 '<circle cx="12" cy="12" r="1.5"/>', "stroke", 1.4),
    "plus":     ('<path d="M8 3v10M3 8h10"/>', "stroke", 1.8),
    "trash":    ('<path d="M2.5 4.5h11M6 4.5V2.5h4v2M4 4.5l.7 9h6.6l.7-9"/>', "stroke", 1.4),
    "copy":     ('<rect x="5" y="5" width="8.5" height="8.5" rx="1.5"/>'
                 '<path d="M11 5V3.5A1 1 0 0010 2.5H3.5a1 1 0 00-1 1V10a1 1 0 001 1H5"/>', "stroke", 1.4),
    "video":    ('<rect x="2" y="3" width="12" height="10" rx="1"/>'
                 '<path d="M5 3v10M11 3v10M2 6.3h3M2 9.7h3M11 6.3h3M11 9.7h3"/>', "stroke", 1.4),
    "tag":      ('<path d="M2 2.5h5.5l6.5 6.5-5 5L2.5 7.5z"/><circle cx="5.2" cy="5.7" r="1"/>', "stroke", 1.4),
    "arena":    ('<rect x="3.5" y="3.5" width="9" height="9"/>'
                 '<path d="M1.5 3.5h2M3.5 1.5v2M12.5 1.5v2M14.5 3.5h-2M1.5 12.5h2M3.5 14.5v-2M14.5 12.5h-2M12.5 14.5v-2"/>',
                 "stroke", 1.4),
    "zones":    ('<rect x="2" y="2" width="12" height="12"/>'
                 '<rect x="5" y="5" width="6" height="6" stroke-dasharray="1.8 1.3"/>', "stroke", 1.4),
    "scale":    ('<path d="M1.5 10.5l9-9 4 4-9 9z"/><path d="M4.3 7.7l1.4 1.4M6.4 5.6l2 2M8.5 3.5l1.4 1.4"/>',
                 "stroke", 1.4),
    "detection": ('<path d="M2 5V2h3M11 2h3v3M14 11v3h-3M5 14H2v-3"/>'
                  '<ellipse cx="8" cy="8" rx="3.2" ry="2" transform="rotate(-25 8 8)"/>', "stroke", 1.4),
    "tracking": ('<circle cx="8" cy="8" r="4.5"/><path d="M8 1.5v3M8 11.5v3M1.5 8h3M11.5 8h3"/>', "stroke", 1.4),
    "analysis": ('<path d="M2 13.5h12M4 11V7.5M7 11V4M10 11V8.5M13 11V5.5"/>', "stroke", 1.4),
    "geometry": ('<rect x="3.5" y="3.5" width="9" height="9"/><rect x="6" y="6" width="4" height="4" '
                 'stroke-dasharray="1.6 1.2"/>', "stroke", 1.4),
    "chevron_r": ('<path d="M6 3l5 5-5 5"/>', "stroke", 1.8),
    "chevron_d": ('<path d="M4 6l4 4 4-4"/>', "stroke", 2.0),
    "chevron_u": ('<path d="M4 10l4-4 4 4"/>', "stroke", 2.0),
    "trim":     ('<circle cx="4.5" cy="11.5" r="2"/><circle cx="11.5" cy="11.5" r="2"/>'
                 '<path d="M6 10l6-7.5M10 10L4 2.5"/>', "stroke", 1.4),
    "play":     ('<path d="M4.5 2.5l9 5.5-9 5.5z"/>', "fill", 0),
    "play_bar": ('<path d="M4 2.5l9.5 5.5L4 13.5z"/>', "fill", 0),
    "pause":    ('<path d="M4 3h3v10H4z M9 3h3v10H9z"/>', "fill", 0),
    "stop":     ('<rect x="3" y="3" width="10" height="10" rx="1"/>', "fill", 0),
    "first":    ('<rect x="2.5" y="3" width="1.8" height="10"/><path d="M13.5 3L5.5 8l8 5z"/>', "fill", 0),
    "prev":     ('<path d="M12 3L4 8l8 5z"/>', "fill", 0),
    "next":     ('<path d="M4 3l8 5-8 5z"/>', "fill", 0),
    "last":     ('<path d="M2.5 3l8 5-8 5z"/><rect x="11.7" y="3" width="1.8" height="10"/>', "fill", 0),
    "x":        ('<path d="M4 4l8 8M12 4l-8 8"/>', "stroke", 1.7),
    "upload":   ('<path d="M8 10.5V2.5M5 5.5l3-3 3 3M2.5 10v3.5h11V10"/>', "stroke", 1.3),
    "check":    ('<path d="M3 8.5l3.2 3L13 4.5"/>', "stroke", 2.4),
    "eye":      ('<path d="M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z"/>'
                 '<circle cx="8" cy="8" r="2"/>', "stroke", 1.4),
    "reset":    ('<path d="M2.5 8a5.5 5.5 0 105.5-5.5H5M5 .5v4h4" transform="translate(0 1)"/>', "stroke", 1.6),
    "edit":     ('<path d="M2.5 13.5l1-3.5 7.5-7.5 2.5 2.5-7.5 7.5z"/>', "stroke", 1.4),
    "gear":     ('<circle cx="8" cy="8" r="2.2"/>'
                 '<path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4"/>',
                 "stroke", 1.4),
    "folder":   ('<path d="M1.5 4.5v8h13v-7H8L6.5 3.5h-5z"/>', "stroke", 1.4),
    # video-canvas tools
    "t_select": ('<path d="M3.5 2l9 5-4 1.3-1.6 4.2z"/>', "stroke", 1.4),
    "t_arena":  ('<path d="M4 4h8v8H4z M1.5 4H4 M4 1.5V4 M12 1.5V4 M14.5 4H12 M1.5 12H4 M4 14.5V12 M14.5 12H12 M12 14.5V12"/>',
                 "stroke", 1.4),
    "t_calib":  ('<path d="M1.5 10.5l9-9 4 4-9 9z M4.3 7.7l1.4 1.4 M6.4 5.6l2 2 M8.5 3.5l1.4 1.4"/>', "stroke", 1.4),
    "t_fix":    ('<path d="M2.5 13.5l1-3.5 7.5-7.5 2.5 2.5-7.5 7.5z M9.5 4l2.5 2.5"/>', "stroke", 1.4),
    "zone_center": ('<rect x="1.5" y="1.5" width="13" height="13"/>'
                    '<rect x="5" y="5" width="6" height="6" fill="currentColor" fill-opacity=".15"/>', "stroke", 1.2),
    "zone_grid": ('<rect x="1.5" y="1.5" width="13" height="13"/>'
                  '<path d="M4.75 1.5v13M8 1.5v13M11.25 1.5v13M1.5 4.75h13M1.5 8h13M1.5 11.25h13" '
                  'stroke-opacity=".55"/>', "stroke", 1.2),
    "minus":    ('<path d="M3.5 8h9"/>', "stroke", 1.8),
    "logo":     ('<rect x="3.5" y="3.5" width="9" height="9" rx="1.2"/><circle cx="8" cy="8" r="1.4" fill="currentColor"/>',
                 "stroke", 1.5),
}

_cache = {}


def _svg(name, size, color):
    inner, kind, sw = _ICONS[name]
    if kind == "fill":
        attrs = f'fill="{color}" stroke="none"'
    else:
        attrs = (f'fill="none" stroke="{color}" stroke-width="{sw}" '
                 f'stroke-linecap="round" stroke-linejoin="round"')
    inner = inner.replace("currentColor", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" '
            f'width="{size}" height="{size}" {attrs}>{inner}</svg>')


def pixmap(name, size=14, color="#000000", dpr=None):
    if dpr is None:
        app = QApplication.instance()
        dpr = app.devicePixelRatio() if app else 1.0
    key = (name, int(size), str(color), float(dpr))
    pm = _cache.get(key)
    if pm is not None:
        return pm
    px = max(1, int(round(size * dpr)))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    r = QSvgRenderer(QByteArray(_svg(name, size, color).encode("utf-8")))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, px, px))
    p.end()
    pm.setDevicePixelRatio(dpr)
    _cache[key] = pm
    return pm


def icon(name, size=14, color="#000000"):
    return QIcon(pixmap(name, size, color))
