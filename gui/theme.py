"""Application theme — implements the "Mice Tracker Redesign v2" look.

Warm neutral greys, a single deep-navy accent (light theme) / soft steel-blue
accent (dark theme), Segoe UI + Consolas (system fonts). Only the launcher logo
fonts (Quicksand Bold, Instrument Sans Medium) ship in assets/fonts; they are
registered at start-up by `register_bundled_fonts()`.

`apply_theme(app, mode)` installs palette + stylesheet; `set_mode()` swaps the
colour tokens at runtime and `notifier.changed` fires so custom-painted
widgets can repaint.  Modules read tokens as `theme.TEXT`, `theme.ACCENT` ...
(attribute access at call time — don't `from gui.theme import TEXT`).
"""
import glob
import os

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QPalette

FONTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")

# ── Design tokens (from the redesign) ──────────────────────────────────────
# Names map to the mock-up's CSS variables:
#   BG=--bg  SURFACE=--p  SURFACE_2=--p2  BORDER=--ln  BORDER_2=--ln2
#   TEXT=--ink  TEXT_2/MUTED=--ink2  FAINT=--ink3  ACCENT=--ac
#   ACCENT_BG=--acs  ACCENT_LINE=--acl  ON_ACCENT=--onac  HOVER=--hv  INPUT=--inp
# Translucent tokens of the dark theme are pre-blended over SURFACE so they
# stay valid for QColor() as well as QSS.
LIGHT = {
    "BG": "#ECE9F8", "SURFACE": "#F8F7FD", "SURFACE_2": "#F0EEFA",
    "HOVER": "#EBE8F8", "INPUT": "#FFFFFF",
    "BORDER": "#DEDAF0", "BORDER_2": "#C9C3E6",
    "TEXT": "#1C1737", "TEXT_2": "#4A4470", "MUTED": "#4A4470", "FAINT": "#736D98",
    "DISABLED": "#B3AECB",
    "ACCENT": "#5B45D8", "ACCENT_HI": "#4A35C6", "ACCENT_BG": "#E7E2FB",
    "ACCENT_LINE": "#C6BCF4", "ON_ACCENT": "#FFFFFF", "ACCENT_DIS": "#A99EE6",
    "OK": "#23855A", "OK_BG": "#DFF1E8",
    "WARN": "#8E6A1F", "WARN_BG": "#F4EBD8",
    "ERR": "#C23A4F", "ERR_BG": "#F8E0E4", "ERR_LINE": "#EDB9C2",
    "SCROLL": "#C9C3E6", "SCROLL_HI": "#ABA3D6",
}
DARK = {
    "BG": "#0C0820", "SURFACE": "#130E2A", "SURFACE_2": "#100B24",
    "HOVER": "#1E1840", "INPUT": "#0B0720",
    "BORDER": "#2A2350", "BORDER_2": "#3A3268",
    "TEXT": "#EEEAFB", "TEXT_2": "#B8B1D9", "MUTED": "#B8B1D9", "FAINT": "#8A83AD",
    "DISABLED": "#5A5480",
    "ACCENT": "#9D8CFF", "ACCENT_HI": "#B4A7FF", "ACCENT_BG": "#2C2560",
    "ACCENT_LINE": "#4D429A", "ON_ACCENT": "#150F2E", "ACCENT_DIS": "#4E477E",
    "OK": "#6FD6A8", "OK_BG": "#1B3036",
    "WARN": "#E8C27A", "WARN_BG": "#2E2838",
    "ERR": "#FF7D8C", "ERR_BG": "#3A1C35", "ERR_LINE": "#6A2F50",
    "SCROLL": "#463C78", "SCROLL_HI": "#5E53A0",
}

# Glass layer — stylesheet-only (rgba) values. The opaque tokens above stay
# the source for QColor painting; these only feed _qss().
#   G_PANEL  floating pane fill      G_RIM   pane outline
#   G_HI     pane top-edge highlight G_SOFT  control fill on glass
#   G_SUNK   recessed wells          G_LINE  dividers inside panes
#   G_LINE_2 control outlines        G_HOVER hover wash
#   G_INPUT  text-field fill         G_ACC_BG / G_ACC_LINE  selection wash
#   POPUP / POPUP_EDGE  menus, tooltips, combo lists (top-level → opaque)
# Panel-dependent values (G_PANEL, G_RIM, G_SUNK, G_LINE*, POPUP*) and the
# opaque surface tokens are derived from the palette's panel colour in
# _derive_surfaces(); the washes below are the same for every palette.
GLASS_LIGHT = {
    "G_HI": "rgba(255,255,255,245)", "G_SOFT": "rgba(255,255,255,90)",
    "G_HOVER": "rgba(255,255,255,205)", "G_INPUT": "rgba(255,255,255,200)"
}
GLASS_DARK = {
    "G_HI": "rgba(255,255,255,40)", "G_SOFT": "rgba(255,255,255,8)",
    "G_HOVER": "rgba(255,255,255,18)", "G_INPUT": "rgba(8,4,24,95)"
}

# Aurora backdrop painted behind the window (gui.backdrop): a base colour and
# up to AURORA_MAX soft radial glows. Each glow is [colour, strength 0..1];
# where it sits comes from AURORA_ANCHORS by position in the list.
# Optional "panel": [colour, opacity 0..1] tints the glass panes; without it
# the panel colour follows the palette (auto_panel()). "accent" is the
# highlight colour (buttons, selection, sliders, focus); all accent shades
# are derived from it.
# Users edit these in View → Appearance; saved under config["aurora"].
AURORA_MAX = 6
AURORA_ANCHORS = [  # (x, y, radius) as fractions of the window
    (0.08, 0.02, 0.72), (0.98, 0.98, 0.78), (0.88, 0.06, 0.42),
    (0.30, 0.98, 0.52), (0.02, 0.62, 0.45), (0.62, 0.40, 0.38),
]
AURORA_PRESETS = {
    "light": {
        "Lilac daylight": {"accent": "#5B45D8", "base": "#ECE8F8", "colors": [
            ["#BBA8FF", 0.75], ["#A6D4F2", 0.80], ["#F2C9E8", 0.65], ["#D5CCFF", 0.55]]},
        "Sea glass": {"accent": "#1E7F8C", "base": "#E6F2F2", "colors": [
            ["#A8DCD8", 0.70], ["#B8D4F0", 0.70], ["#DDEFD8", 0.50]]},
        "Peach": {"accent": "#C4532B", "base": "#F8EEE8", "colors": [
            ["#F6C6B0", 0.70], ["#F2D8E6", 0.60], ["#FBE3B8", 0.50]]},
        "Mist": {"accent": "#3D5A80", "base": "#EEF0F3", "colors": [["#CBD3DE", 0.70], ["#DCE2EA", 0.70]]},
    },
    "dark": {
        "Dusk violet": {"accent": "#9D8CFF", "base": "#08051A", "colors": [
            ["#4A33B0", 0.38], ["#123E6E", 0.42], ["#6A2C88", 0.22], ["#1C1456", 0.40]]},
        "Deep ocean": {"accent": "#4FD1D9", "base": "#04101A", "colors": [
            ["#0E5A7A", 0.40], ["#0B3350", 0.45], ["#2A7F8F", 0.20]]},
        "Ember": {"accent": "#FF9B5E", "base": "#140806", "colors": [
            ["#8A2E12", 0.35], ["#5A1530", 0.40], ["#B5561C", 0.18]]},
        "Forest night": {"accent": "#7FD69A", "base": "#06110C", "colors": [
            ["#1E5E3E", 0.35], ["#0E3B4A", 0.40], ["#4E6B1E", 0.18]]},
        "Graphite": {"accent": "#F2B35B", "base": "#0A0B0D", "colors": [["#2A2F38", 0.50], ["#1B2230", 0.50]]},
    },
}
AURORA_DEFAULT_PRESET = {"light": "Lilac daylight", "dark": "Graphite"}


def copy_spec(spec):
    out = {"base": spec["base"], "colors": [list(c) for c in spec["colors"]]}
    if spec.get("accent"):
        out["accent"] = spec["accent"]
    if spec.get("panel"):
        out["panel"] = list(spec["panel"])
    return out


AURORA = {m: copy_spec(AURORA_PRESETS[m][AURORA_DEFAULT_PRESET[m]]) for m in ("light", "dark")}


def aurora_default(m):
    return copy_spec(AURORA_PRESETS[m][AURORA_DEFAULT_PRESET[m]])


def aurora_glows(spec):
    """Spec → [(x, y, radius, colour, strength)] for painting."""
    return [(x, y, r, c, float(a))
            for (x, y, r), (c, a) in zip(AURORA_ANCHORS, spec["colors"][:AURORA_MAX])]


def auto_panel(m, spec):
    """Panel colour that matches a palette: a whisper of its first glow
    mixed into the background (dark), or milky white (light)."""
    if m == "light":
        return ["#FFFFFF", 0.55]
    first = spec["colors"][0][0] if spec["colors"] else spec["base"]
    return [_mix(spec["base"], first, 0.12), 0.47]


DEFAULT_ACCENT = {"light": "#5B45D8", "dark": "#9D8CFF"}


def accent_of(m, spec):
    return spec.get("accent") or DEFAULT_ACCENT[m]


def contrast(a, b):
    """WCAG contrast ratio between two colours (1..21)."""
    def lum(c):
        q = QColor(c)
        ch = []
        for v in (q.redF(), q.greenF(), q.blueF()):
            ch.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def panel_of(m, spec):
    return list(spec.get("panel") or auto_panel(m, spec))


def set_aurora(m, spec):
    """Install a validated spec for mode `m`; bad input is ignored."""
    try:
        base = spec["base"]
        colors = [[str(c), max(0.0, min(1.0, float(a)))] for c, a in spec["colors"]]
        if not QColor(base).isValid() or not colors or not all(QColor(c).isValid() for c, _ in colors):
            return False
        panel = spec.get("panel")
        if panel:
            panel = [str(panel[0]), max(0.0, min(1.0, float(panel[1])))]
            if not QColor(panel[0]).isValid():
                panel = None
    except (KeyError, TypeError, ValueError, IndexError):
        return False
    AURORA[m] = {"base": base, "colors": colors[:AURORA_MAX]}
    accent = spec.get("accent")
    if accent and QColor(accent).isValid():
        AURORA[m]["accent"] = QColor(accent).name().upper()
    if panel:
        AURORA[m]["panel"] = panel
    return True


def _mix(a, b, t):
    """Blend colour a toward b by t (0..1); returns #RRGGBB."""
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t),
                  round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t)).name().upper()


def _rgba(c, alpha):
    q = QColor(c)
    return f"rgba({q.red()},{q.green()},{q.blue()},{round(alpha * 255)})"


def _derive_surfaces(m, spec):
    """Panel-tinted tokens: the glass values for QSS plus the opaque surface
    tokens painters use, all following the palette's panel colour."""
    base = spec["base"]
    pc, pa = panel_of(m, spec)
    seen = _mix(base, pc, pa)              # what a pane looks like over the base
    out = _derive_accent(m, accent_of(m, spec), seen)
    out.update(_derive_panel(m, base, pc, pa, seen))
    return out


def _derive_accent(m, acc, seen):
    # Text on a filled accent button: whichever of ink / white reads better.
    on = "#FFFFFF" if contrast(acc, "#FFFFFF") >= contrast(acc, "#150F2E") else "#150F2E"
    if m == "dark":
        return {
            "ACCENT": acc, "ACCENT_HI": _mix(acc, "#FFFFFF", 0.2),
            "ACCENT_BG": _mix(seen, acc, 0.22), "ACCENT_LINE": _mix(seen, acc, 0.5),
            "ON_ACCENT": on, "ACCENT_DIS": _mix(seen, acc, 0.4),
            "G_ACC_BG": _rgba(acc, 0.16), "G_ACC_LINE": _rgba(acc, 0.45),
        }
    return {
        "ACCENT": acc, "ACCENT_HI": _mix(acc, "#000000", 0.15),
        "ACCENT_BG": _mix(seen, acc, 0.12), "ACCENT_LINE": _mix(seen, acc, 0.35),
        "ON_ACCENT": on, "ACCENT_DIS": _mix(seen, acc, 0.45),
        "G_ACC_BG": _rgba(acc, 0.12), "G_ACC_LINE": _rgba(acc, 0.37),
    }


def _derive_panel(m, base, pc, pa, seen):
    if m == "dark":
        tint = _mix(pc, "#FFFFFF", 0.75)   # light edge colour in the panel's hue
        return {
            "G_PANEL": _rgba(pc, pa), "G_RIM": _rgba(tint, 0.18),
            "G_SUNK": _rgba(_mix(pc, "#000000", 0.5), 0.35),
            "G_LINE": _rgba(tint, 0.11), "G_LINE_2": _rgba(tint, 0.23),
            "BG": _mix(base, seen, 0.5), "SURFACE": _mix(seen, "#FFFFFF", 0.04),
            "SURFACE_2": _mix(seen, "#000000", 0.10), "HOVER": _mix(seen, "#FFFFFF", 0.09),
            "INPUT": _mix(seen, "#000000", 0.35),
            "BORDER": _mix(seen, tint, 0.18), "BORDER_2": _mix(seen, tint, 0.30),
            "SCROLL": _mix(seen, tint, 0.30), "SCROLL_HI": _mix(seen, tint, 0.45),
            "POPUP": _mix(seen, "#FFFFFF", 0.05), "POPUP_EDGE": _mix(seen, tint, 0.30),
        }
    ink = _mix(base, "#000000", 0.55)      # dark line colour in the palette's hue
    return {
        "G_PANEL": _rgba(pc, pa), "G_RIM": _rgba("#FFFFFF", 0.85),
        "G_SUNK": _rgba(base, 0.6),
        "G_LINE": _rgba(ink, 0.14), "G_LINE_2": _rgba(ink, 0.24),
        "BG": base, "SURFACE": _mix(seen, "#FFFFFF", 0.4),
        "SURFACE_2": _mix(seen, ink, 0.04), "HOVER": _mix(seen, ink, 0.06),
        "INPUT": "#FFFFFF",
        "BORDER": _mix(seen, ink, 0.12), "BORDER_2": _mix(seen, ink, 0.22),
        "SCROLL": _mix(seen, ink, 0.22), "SCROLL_HI": _mix(seen, ink, 0.35),
        "POPUP": _mix(seen, "#FFFFFF", 0.6), "POPUP_EDGE": _mix(seen, ink, 0.22),
    }


def load_aurora(config):
    """Apply the user's saved backdrop palettes from config["aurora"]."""
    for m, spec in (config.get("aurora") or {}).items():
        if m in AURORA:
            set_aurora(m, spec)


VIDEO_BG = "#0D0A1E"   # video canvas stays dark in both themes

SANS_STACK = ["Segoe UI", "Helvetica Neue", "Arial"]
MONO_STACK = ["Consolas", "Cascadia Mono", "Courier New"]

# Live tokens — populated by set_mode(); defaults keep static analysers happy.
BG = SURFACE = SURFACE_2 = HOVER = INPUT = BORDER = BORDER_2 = ""
TEXT = TEXT_2 = MUTED = FAINT = DISABLED = ""
ACCENT = ACCENT_HI = ACCENT_BG = ACCENT_LINE = ON_ACCENT = ACCENT_DIS = ""
OK = OK_BG = WARN = WARN_BG = ERR = ERR_BG = ERR_LINE = ""
SCROLL = SCROLL_HI = ""
G_PANEL = G_RIM = G_HI = G_SOFT = G_SUNK = G_LINE = G_LINE_2 = ""
G_HOVER = G_INPUT = G_ACC_BG = G_ACC_LINE = POPUP = POPUP_EDGE = ""
STATUS_STYLE = {}
_mode = "light"


class _Notifier(QObject):
    changed = pyqtSignal(str)
    aurora_changed = pyqtSignal()  # backdrop palette edited (View → Appearance)


notifier = _Notifier()


def mode():
    return _mode


def set_mode(new_mode):
    """Swap the live colour tokens. Returns the mode actually applied."""
    global _mode
    _mode = "dark" if new_mode == "dark" else "light"
    globals().update(DARK if _mode == "dark" else LIGHT)
    globals().update(GLASS_DARK if _mode == "dark" else GLASS_LIGHT)
    globals().update(_derive_surfaces(_mode, AURORA[_mode]))
    # Video-row status colours: (background, border, dot, text)
    STATUS_STYLE.clear()
    STATUS_STYLE.update({
        "needs":   (SURFACE, BORDER,      FAINT,  MUTED),
        "ready":   (SURFACE, BORDER,      ACCENT, TEXT),
        "running": (ACCENT_BG, ACCENT_LINE, ACCENT, TEXT),
        "done":    (SURFACE, BORDER,      OK,     TEXT),
        "error":   (ERR_BG, ERR_LINE,     ERR,    ERR),
    })
    return _mode


set_mode("light")


def set_tone(widget, tone, css=""):
    """Colour a widget's text by semantic tone (text / text2 / muted / faint /
    accent / ok / warn / err) via the global stylesheet, so it follows
    light/dark switches. `css` carries any non-colour inline styling."""
    widget.setProperty("tone", tone)
    if widget.styleSheet() != css:
        widget.setStyleSheet(css)
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)
    widget.update()


def _assets():
    """Render the small raster assets QSS can't draw itself (checkbox tick,
    radio dot, combo / spin arrows) for the current mode. Returns
    {name: forward-slash path}. Each asset also gets an @2x twin for HiDPI."""
    import os
    from PyQt5.QtCore import QPointF, QRectF, Qt
    from PyQt5.QtGui import QBrush, QPainter, QPen, QPixmap
    from gui import icons
    from core.app_paths import CACHE_DIR

    # Keyed by the colours used: Qt caches stylesheet images by path. Kept in
    # the app folder (settings/cache), not the system temp folder.
    key = "_".join(c.lstrip("#") for c in (ACCENT, INPUT, BORDER_2, ON_ACCENT, FAINT, TEXT_2, SCROLL))
    folder = os.path.join(CACHE_DIR, "theme", f"{_mode}_{key}")
    os.makedirs(folder, exist_ok=True)
    out = {}

    def save(name, size, draw, height=None):
        height = height or size
        out[name] = '"' + os.path.join(folder, f"{name}.png").replace("\\", "/") + '"'
        if all(os.path.exists(os.path.join(folder, f"{name}{sfx}.png")) for sfx in ("", "@2x")):
            return          # same colours rendered before — reuse (faster theme switch)
        for scale, suffix in ((1, ""), (2, "@2x")):
            pm = QPixmap(size * scale, height * scale)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.scale(scale, scale)
            draw(p, scale)
            p.end()
            pm.save(os.path.join(folder, f"{name}{suffix}.png"), "PNG")

    def box(checked, hover=False):
        def draw(p, _s):
            r = QRectF(0.5, 0.5, 13, 13)
            p.setPen(QPen(QColor(ACCENT if (checked or hover) else BORDER_2), 1))
            p.setBrush(QBrush(QColor(ACCENT if checked else INPUT)))
            p.drawRoundedRect(r, 3, 3)
            if checked:
                p.setBrush(Qt.NoBrush)
                pen = QPen(QColor(ON_ACCENT), 1.8)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                p.setPen(pen)
                p.drawPolyline(*[QPointF(x, y) for x, y in ((3.6, 7.2), (6.0, 9.6), (10.4, 4.8))])
        return draw

    def radio(checked):
        def draw(p, _s):
            p.setPen(QPen(QColor(ACCENT if checked else BORDER_2), 1))
            p.setBrush(QBrush(QColor(INPUT)))
            p.drawEllipse(QRectF(0.5, 0.5, 13, 13))
            if checked:
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor(ACCENT)))
                p.drawEllipse(QRectF(3.5, 3.5, 7, 7))
        return draw

    def glyph(name, size, color):
        def draw(p, scale):
            p.drawPixmap(0, 0, icons.pixmap(name, size, color, dpr=scale))
        return draw

    def switch(on, disabled=False):
        def draw(p, _s):
            track = QColor(ACCENT if on else SCROLL)
            if disabled:
                track.setAlphaF(0.45)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(track))
            p.drawRoundedRect(QRectF(0, 0, 30, 18), 9, 9)
            p.setBrush(QBrush(QColor("#FFFFFF" if not disabled else "#EEEEEE")))
            p.drawEllipse(QRectF(14 if on else 2, 2, 14, 14))
        return draw

    save("switch_off", 30, switch(False), 18)
    save("switch_on", 30, switch(True), 18)
    save("switch_off_dis", 30, switch(False, True), 18)
    save("switch_on_dis", 30, switch(True, True), 18)
    save("check_off", 14, box(False))
    save("check_off_hover", 14, box(False, True))
    save("check_on", 14, box(True))
    save("radio_off", 14, radio(False))
    save("radio_on", 14, radio(True))
    save("arrow_down", 10, glyph("chevron_d", 10, FAINT))
    save("arrow_up", 10, glyph("chevron_u", 10, FAINT))
    save("step_minus", 12, glyph("minus", 12, TEXT_2))
    save("step_plus", 12, glyph("plus", 12, TEXT_2))
    return out


# ── Fonts ──────────────────────────────────────────────────────────────────
# Three roles the user can set in View → Appearance → Fonts (config["fonts"]):
#   ui     interface text — buttons, labels, menus
#   data   numbers, units, times, file names, tables (monospace reads best)
#   label  small section headers ("CURRENT FRAME"); defaults to the data font
# None = automatic (first installed font from the stack).
FONT_ROLES = ("ui", "data", "label")
FONTS = {"ui": None, "data": None, "label": None}
FONT_CHOICES = {  # suggestions shown first, when installed
    "ui": ["Segoe UI", "Segoe UI Variable Text", "Bahnschrift", "Aptos", "Calibri",
           "Inter", "IBM Plex Sans", "Roboto", "Source Sans 3", "Arial", "Verdana", "Tahoma"],
    "data": ["Consolas", "Cascadia Mono", "IBM Plex Mono", "Roboto Mono",
             "Source Code Pro", "Lucida Console", "Courier New"],
}
_families = None
# Not offered as UI / data fonts (the bundled logo font and the old defaults).
HIDDEN_FAMILY_PREFIXES = ("Instrument Sans", "JetBrains Mono")


def _user_font_dirs():
    """Per-user font folders that matplotlib does not scan on its own."""
    local = os.environ.get("LOCALAPPDATA")
    return [os.path.join(local, "Microsoft", "Windows", "Fonts")] if local else []


def register_bundled_fonts():
    """Load assets/fonts into Qt (and matplotlib) so the app never depends on
    what is installed on the machine. Call once, after QApplication exists and
    before any font lookup. Missing files are skipped silently (the stacks
    still fall back to system fonts)."""
    global _families
    files = sorted(glob.glob(os.path.join(FONTS_DIR, "*.ttf"))
                   + glob.glob(os.path.join(FONTS_DIR, "*.otf")))
    for path in files:
        QFontDatabase.addApplicationFont(path)
    _families = None
    try:  # matplotlib graphs use theme.mono_family() too
        from matplotlib import font_manager
        extra = list(files)
        for d in _user_font_dirs():
            extra += glob.glob(os.path.join(d, "*.ttf")) + glob.glob(os.path.join(d, "*.otf"))
        for path in extra:
            try:
                font_manager.fontManager.addfont(path)
            except Exception:
                pass
    except Exception:
        pass


def installed_families():
    global _families
    if _families is None:
        _families = {f for f in QFontDatabase().families()
                     if not f.startswith(HIDDEN_FAMILY_PREFIXES)}
    return _families


def _first_available(candidates):
    families = installed_families()
    for name in candidates:
        if name in families:
            return name
    return candidates[-1]


def _chosen(role):
    name = FONTS.get(role)
    return name if name and name in installed_families() else None


def sans_family():
    return _chosen("ui") or _first_available(SANS_STACK)


def mono_family():
    return _chosen("data") or _first_available(MONO_STACK)


def label_family():
    return _chosen("label") or mono_family()


def set_fonts(fonts):
    """Install font choices {role: family or None}; unknown roles ignored."""
    for role in FONT_ROLES:
        name = (fonts or {}).get(role)
        FONTS[role] = str(name) if name else None


def load_fonts(config):
    set_fonts(config.get("fonts") or {})


def _palette():
    p = QPalette()
    p.setColor(QPalette.Window, QColor(BG))
    p.setColor(QPalette.WindowText, QColor(TEXT))
    p.setColor(QPalette.Base, QColor(INPUT))
    p.setColor(QPalette.AlternateBase, QColor(SURFACE_2))
    p.setColor(QPalette.Text, QColor(TEXT))
    p.setColor(QPalette.Button, QColor(SURFACE))
    p.setColor(QPalette.ButtonText, QColor(TEXT))
    p.setColor(QPalette.ToolTipBase, QColor(TEXT))
    p.setColor(QPalette.ToolTipText, QColor(SURFACE))
    p.setColor(QPalette.Highlight, QColor(ACCENT))
    p.setColor(QPalette.HighlightedText, QColor(ON_ACCENT))
    p.setColor(QPalette.Link, QColor(ACCENT))
    p.setColor(QPalette.PlaceholderText, QColor(FAINT))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(DISABLED))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(DISABLED))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(DISABLED))
    return p


def _qss(sans, mono, A):
    # Inside the stylesheet, surfaces become glass: translucent washes over
    # the aurora backdrop. Painters keep using the opaque module tokens.
    base_bg = AURORA[_mode]["base"]
    SURFACE, SURFACE_2, HOVER, INPUT = G_SOFT, G_SUNK, G_HOVER, G_INPUT
    BORDER, BORDER_2, ACCENT_BG, ACCENT_LINE = G_LINE, G_LINE_2, G_ACC_BG, G_ACC_LINE
    BG = "transparent"
    label = label_family()
    return f"""
* {{ font-family: "{sans}"; }}
QWidget {{ font-size: 12px; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QToolTip {{ background: {TEXT}; color: {SURFACE}; border: 0; padding: 4px 6px; }}

/* ── Menus ────────────────────────────────────────────────────── */
QMenuBar {{ background: transparent; border: 0; padding: 0; }}
QMenuBar::item {{ background: transparent; padding: 5px 10px; border-radius: 5px; color: {TEXT_2}; }}
QMenuBar::item:selected, QMenuBar::item:pressed {{ background: {HOVER}; color: {TEXT}; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER_2}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 6px 26px 6px 12px; border-radius: 5px; color: {TEXT}; }}
QMenu::item:selected {{ background: {HOVER}; color: {TEXT}; }}
QMenu::item:disabled {{ color: {DISABLED}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; color: {MUTED}; font-size: 11px; min-height: 26px; }}
QStatusBar::item {{ border: 0; }}
QStatusBar QLabel {{ font-size: 11px; color: {MUTED}; }}

/* ── Buttons ──────────────────────────────────────────────────── */
QPushButton {{
    background: {SURFACE}; border: 1px solid {BORDER_2}; border-radius: 6px;
    padding: 3px 10px; color: {TEXT};
}}
QPushButton:hover {{ background: {HOVER}; }}
QPushButton:pressed {{ background: {ACCENT_BG}; }}
QPushButton:disabled {{ color: {DISABLED}; background: {SURFACE_2}; border-color: {BORDER}; }}
QPushButton:checked {{ background: {ACCENT_BG}; border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton:focus {{ outline: none; }}
QPushButton[primary="true"] {{
    background: {ACCENT}; border-color: {ACCENT}; color: {ON_ACCENT}; font-weight: 600;
}}
QPushButton[primary="true"]:hover {{ background: {ACCENT_HI}; border-color: {ACCENT_HI}; }}
QPushButton[primary="true"]:disabled {{ background: {ACCENT_DIS}; border-color: {ACCENT_DIS}; color: {ON_ACCENT}; }}
QPushButton[flat="true"], QPushButton[ghost="true"] {{
    background: transparent; border: 1px solid transparent; color: {MUTED};
}}
QPushButton[flat="true"]:hover, QPushButton[ghost="true"]:hover {{ background: {HOVER}; }}
QToolButton {{ background: transparent; border: 0; border-radius: 4px; padding: 2px; color: {TEXT_2}; }}
QToolButton:hover {{ background: {HOVER}; }}

/* ── Inputs ───────────────────────────────────────────────────── */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit, QTimeEdit {{
    background: {INPUT}; border: 1px solid {BORDER_2}; border-radius: 6px;
    padding: 2px 6px; min-height: 22px; selection-background-color: {ACCENT};
    selection-color: {ON_ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background: {SURFACE_2}; color: {DISABLED}; border-color: {BORDER};
}}
QLineEdit:read-only {{ background: {SURFACE_2}; }}
QComboBox::drop-down {{ border: 0; width: 20px; }}
QComboBox::down-arrow {{ image: url({A["arrow_down"]}); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {BORDER_2}; selection-background-color: {HOVER};
    selection-color: {TEXT}; outline: 0;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 16px; border: 0; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({A["arrow_up"]}); width: 8px; height: 8px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({A["arrow_down"]}); width: 8px; height: 8px; }}
QPlainTextEdit, QTextEdit {{
    background: {INPUT}; border: 1px solid {BORDER_2}; border-radius: 6px;
    selection-background-color: {ACCENT}; selection-color: {ON_ACCENT};
}}

/* ── Checkbox / radio ─────────────────────────────────────────── */
QCheckBox, QRadioButton {{ spacing: 6px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}
QCheckBox::indicator:unchecked {{ image: url({A["check_off"]}); }}
QCheckBox::indicator:unchecked:hover {{ image: url({A["check_off_hover"]}); }}
QCheckBox::indicator:checked {{ image: url({A["check_on"]}); }}
QCheckBox[switch="true"] {{ spacing: 8px; }}
QCheckBox[switch="true"]::indicator {{ width: 30px; height: 18px; }}
QCheckBox[switch="true"]::indicator:unchecked {{ image: url({A["switch_off"]}); }}
QCheckBox[switch="true"]::indicator:unchecked:hover {{ image: url({A["switch_off"]}); }}
QCheckBox[switch="true"]::indicator:checked {{ image: url({A["switch_on"]}); }}
QCheckBox[switch="true"]::indicator:unchecked:disabled {{ image: url({A["switch_off_dis"]}); }}
QCheckBox[switch="true"]::indicator:checked:disabled {{ image: url({A["switch_on_dis"]}); }}
QRadioButton::indicator:unchecked {{ image: url({A["radio_off"]}); }}
QRadioButton::indicator:checked {{ image: url({A["radio_on"]}); }}

/* ── Sliders / progress ───────────────────────────────────────── */
QSlider::groove:horizontal {{ height: 4px; background: {BORDER_2}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {ACCENT}; border: 2px solid {SURFACE}; width: 10px; height: 10px;
    margin: -6px 0; border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ background: {ACCENT_HI}; }}
QProgressBar {{
    background: {BORDER}; border: 0; border-radius: 2px; max-height: 4px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}

/* ── Tabs (underline style) ───────────────────────────────────── */
QTabWidget::pane {{ border: 0; border-top: 1px solid {BORDER}; background: {SURFACE}; top: -1px; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent; color: {FAINT}; padding: 8px 14px; margin-right: 2px;
    border: 0; border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:disabled {{ color: {DISABLED}; }}

/* ── Group boxes → flat sections ──────────────────────────────── */
QGroupBox {{
    background: transparent; border: 0; border-top: 1px solid {BORDER};
    margin-top: 12px; padding: 10px 2px 4px 2px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; padding: 0 4px 0 0; color: {TEXT}; }}

/* ── Scroll areas / bars ──────────────────────────────────────── */
QScrollArea {{ border: 0; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {SCROLL}; border-radius: 4px; min-height: 28px; margin: 1px; }}
QScrollBar::handle:horizontal {{ background: {SCROLL}; border-radius: 4px; min-width: 28px; margin: 1px; }}
QScrollBar::handle:hover {{ background: {SCROLL_HI}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ── Tables / lists ───────────────────────────────────────────── */
QTableView, QTableWidget, QListView, QListWidget, QTreeView {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    gridline-color: {HOVER}; alternate-background-color: {SURFACE_2};
    selection-background-color: {ACCENT_BG}; selection-color: {TEXT};
}}
QHeaderView::section {{
    background: {SURFACE_2}; color: {MUTED}; font-weight: 500; padding: 5px 8px;
    border: 0; border-bottom: 1px solid {BORDER};
}}
QTableCornerButton::section {{ background: {SURFACE_2}; border: 0; }}

/* ── Splitter ─────────────────────────────────────────────────── */
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:hover {{ background: {ACCENT}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

/* ── Named parts used by the redesign ─────────────────────────── */
QLabel[role="pane-header"] {{
    color: {TEXT}; font-family: "{label}"; font-size: 11px; font-weight: 600; letter-spacing: 1px;
    padding: 0 12px; background: {SURFACE}; border-bottom: 1px solid {BORDER};
}}
QLabel[role="muted"] {{ color: {FAINT}; font-size: 11px; }}
QLabel[role="mono"] {{ font-family: "{mono}"; }}
QLabel[role="caps"] {{
    font-family: "{label}"; font-size: 11px; font-weight: 600; letter-spacing: 1px; color: {TEXT};
}}
QLabel[role="faint"] {{ color: {FAINT}; }}
QLabel[role="faint11"] {{ color: {FAINT}; font-size: 11px; }}
QLabel[role="muted10"] {{ color: {MUTED}; font-size: 10px; }}
QLabel[role="muted11"] {{ color: {MUTED}; font-size: 11px; }}
QLabel[role="metric-name"], QLabel[role="metric-val"] {{ border: 0; background: transparent; }}
QLabel[role="metric-name"] {{ color: {TEXT_2}; }}
QLabel[state="ok"] {{ color: {OK}; }}
QLabel[state="err"] {{ color: {ERR}; }}
QFrame[role="card"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; }}
QFrame[role="hline"] {{ background: {BORDER}; border: 0; }}
QWidget[role="metric-row"] {{ border-bottom: 1px dashed {BORDER}; }}
QWidget[role="meas-section"] {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
QFrame#GridCells {{ background: {BORDER}; border: 1px solid {BORDER}; border-radius: 7px; }}
QWidget#GridCell {{ background: {SURFACE}; }}
QLabel[role="cellcap"] {{ font-size: 10px; color: {FAINT}; letter-spacing: 0.5px; background: transparent; }}
QFrame#HeroTile {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 7px; }}
QFrame#HeroTile QLabel {{ background: transparent; }}
QLabel#AccentDot {{ background: {ACCENT}; border-radius: 3px; }}
QLabel#ZonePill {{ border-radius: 5px; padding: 0 9px; font-size: 11.5px; font-weight: 600;
    background: {SURFACE_2}; color: {TEXT_2}; }}
QLabel#ZonePill[zone="center"] {{ background: {ACCENT_BG}; color: {ACCENT}; }}

/* Semantic text tones — see set_tone() */
QWidget[tone="text"] {{ color: {TEXT}; }}
QWidget[tone="text2"] {{ color: {TEXT_2}; }}
QWidget[tone="muted"] {{ color: {MUTED}; }}
QWidget[tone="faint"] {{ color: {FAINT}; }}
QWidget[tone="accent"] {{ color: {ACCENT}; }}
QWidget[tone="ok"] {{ color: {OK}; }}
QWidget[tone="warn"] {{ color: {WARN}; }}
QWidget[tone="err"] {{ color: {ERR}; }}

/* Header */
QWidget#AppHeader {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
QFrame#HeaderSep {{ background: {BORDER}; border: 0; }}
QLabel#BrandMark {{ background: transparent; }}
QLabel#BrandName {{ font-size: 13px; font-weight: 700; }}
QLabel#BrandTag {{
    font-family: "{label}"; font-size: 9px; letter-spacing: 1px; color: {FAINT};
}}
QLabel#Crumb {{ font-family: "{mono}"; font-size: 11px; font-weight: 500; color: {TEXT}; }}
QLabel#CrumbSep {{ color: {BORDER_2}; }}
QLabel#StatusPill {{
    background: {ACCENT_BG}; color: {TEXT}; border: 1px solid {ACCENT_LINE};
    border-radius: 11px; padding: 0 10px; font-size: 11px;
}}
QFrame#Segmented {{ border: 1px solid {BORDER_2}; border-radius: 6px; background: {SURFACE_2}; }}
QFrame#Segmented QPushButton {{
    border: 0; border-radius: 0; padding: 0 10px; background: transparent;
    color: {FAINT}; font-size: 11px; min-height: 0;
}}
QFrame#Segmented QPushButton:hover {{ background: {HOVER}; color: {TEXT}; }}
QFrame#Segmented QPushButton:checked {{ background: {SURFACE}; color: {TEXT}; font-weight: 600; }}

/* Redesign v2 building blocks */
QWidget#FooterBar {{ background: transparent; }}
QWidget#FooterBar QLabel {{ font-size: 10.5px; color: {TEXT_2}; background: transparent; }}
QCheckBox[chip="true"] {{
    spacing: 0; padding: 0 9px; height: 22px; border-radius: 11px; font-size: 11px;
    background: {SURFACE_2}; color: {FAINT}; border: 1px solid {BORDER};
}}
QCheckBox[chip="true"]:checked {{ background: {ACCENT_BG}; color: {ACCENT}; border: 1px solid {ACCENT_LINE}; }}
QCheckBox[chip="true"]::indicator {{ width: 0px; height: 0px; }}
QFrame#Section {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 0; }}
QLabel#SectionTitle {{ font-size: 13px; font-weight: 600; background: transparent; }}
QLabel#PathBox {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 4px; padding: 0 8px;
    font-family: "{mono}"; font-size: 11px; color: {TEXT};
}}
QFrame#ExportSeg {{ border: 1px solid {BORDER_2}; border-radius: 4px; background: {SURFACE}; }}
QPushButton[segbtn="true"] {{
    border: 0; border-left: 1px solid {BORDER}; border-radius: 0; background: {SURFACE}; padding: 0 8px;
    font-size: 11px; min-height: 0; color: {TEXT};
}}
QPushButton[segbtn="true"]:first-child {{ border-left: 0; }}
QPushButton[segbtn="true"]:hover {{ background: {HOVER}; }}
QPushButton[graphitem="true"] {{
    border: 0; border-radius: 4px; background: transparent; text-align: left; padding: 0;
}}
QPushButton[graphitem="true"]:hover {{ background: {BORDER}; }}
QPushButton[graphitem="true"]:checked {{ background: {ACCENT_BG}; }}
QLabel[role="graphname"] {{ font-size: 12px; font-weight: 500; color: {TEXT}; background: transparent; }}
QLabel[role="graphdesc"] {{ font-size: 10.5px; color: {FAINT}; background: transparent; }}
QPushButton[graphitem="true"]:checked QLabel[role="graphname"] {{ color: {ACCENT}; }}
QWidget#OutFooter {{ background: {SURFACE}; border-top: 1px solid {BORDER}; }}
QWidget#SubTabHeader {{ background: {SURFACE_2}; border-bottom: 1px solid {BORDER}; }}
QPushButton[subtab="true"] {{
    border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: transparent;
    color: {FAINT}; padding: 0 10px; font-size: 12px; min-height: 0; height: 37px;
}}
QPushButton[subtab="true"]:hover {{ color: {TEXT}; background: transparent; }}
QPushButton[subtab="true"]:checked {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabWidget#ExcelTabs::pane {{ border: 0; background: {BG}; top: 0; }}
QWidget#OutPage {{ background: {BG}; }}
QFrame#OutPanel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 0; }}
QWidget#OutPanelBar {{ background: {SURFACE}; border: 0; border-bottom: 1px solid {BORDER}; }}
QLabel#OutPanelTitle {{ font-size: 13px; font-weight: 600; background: transparent; }}
QTableWidget[out="true"] {{
    background: {SURFACE}; border: 0; border-radius: 0; gridline-color: {BORDER};
    alternate-background-color: {SURFACE}; selection-background-color: {ACCENT_BG}; selection-color: {TEXT};
    outline: 0;
}}
QTableWidget[out="true"] QHeaderView::section {{
    background: {SURFACE_2}; color: {TEXT_2}; font-weight: 500; font-size: 11px; padding: 0 14px;
    border: 0; border-bottom: 1px solid {BORDER}; height: 30px;
}}
QTableWidget[out="true"]::item {{ padding: 0 14px; border-bottom: 1px solid {BORDER}; }}
QTableWidget[out="true"]::item:hover {{ background: {SURFACE_2}; }}
QWidget#MainTabHeader {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
QPushButton[maintab="true"] {{
    border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: transparent;
    color: {FAINT}; padding: 0 12px; font-size: 12.5px; min-height: 0; height: 39px;
}}
QPushButton[maintab="true"]:hover {{ color: {TEXT}; background: transparent; }}
QPushButton[maintab="true"]:checked {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QLabel#MetaChip {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 4px; padding: 0 8px; font-size: 11px;
}}
QLabel#TrackedChip {{ background: {OK_BG}; border-radius: 11px; padding: 0 10px; font-size: 11px; }}
QSpinBox, QDoubleSpinBox {{ font-family: "{mono}"; font-size: 11px; }}
QAbstractSpinBox[stepper="true"] {{ padding: 0 28px; qproperty-alignment: AlignCenter; }}
QAbstractSpinBox[stepper="true"]::down-button {{
    subcontrol-origin: border; subcontrol-position: left; width: 26px;
    border: 0; border-right: 1px solid {BORDER}; background: {SURFACE_2};
    border-top-left-radius: 5px; border-bottom-left-radius: 5px;
}}
QAbstractSpinBox[stepper="true"]::up-button {{
    subcontrol-origin: border; subcontrol-position: right; width: 26px;
    border: 0; border-left: 1px solid {BORDER}; background: {SURFACE_2};
    border-top-right-radius: 5px; border-bottom-right-radius: 5px;
}}
QAbstractSpinBox[stepper="true"]::down-arrow {{ image: url({A["step_minus"]}); width: 12px; height: 12px; }}
QAbstractSpinBox[stepper="true"]::up-arrow {{ image: url({A["step_plus"]}); width: 12px; height: 12px; }}
QPushButton[link="true"] {{
    background: transparent; border: 0; color: {ACCENT}; padding: 0 6px; min-height: 0; font-size: 11px;
}}
QPushButton[link="true"]:hover {{ background: {ACCENT_BG}; }}
QPushButton[link="true"]:disabled {{ color: {DISABLED}; }}
QFrame#SegTabs {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 6px; }}
QFrame#SegTabs QPushButton {{
    border: 1px solid transparent; border-radius: 4px; background: transparent; color: {FAINT};
    font-size: 11px; min-height: 0; height: 22px; padding: 0 4px;
}}
QFrame#SegTabs QPushButton:hover {{ color: {TEXT}; }}
QFrame#SegTabs QPushButton:checked {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; }}
QPushButton[tile="true"] {{
    text-align: left; padding: 0 10px; border-radius: 6px; font-size: 11.5px;
    background: {SURFACE}; color: {TEXT_2}; border: 1px solid {BORDER_2};
}}
QPushButton[tile="true"]:hover {{ background: {HOVER}; }}
QPushButton[tile="true"]:checked {{ background: {ACCENT_BG}; color: {ACCENT}; border: 1px solid {ACCENT_LINE}; }}
QPushButton#ArenaMode {{
    background: {INPUT}; border: 1px solid {BORDER_2}; border-radius: 6px; padding: 0 24px 0 8px;
    text-align: left; color: {TEXT}; font-size: 12px;
}}
QPushButton#ArenaMode:hover {{ background: {INPUT}; border-color: {ACCENT_LINE}; }}
QPushButton#ArenaMode:disabled {{ background: {SURFACE_2}; color: {DISABLED}; border-color: {BORDER}; }}
QPushButton#ArenaMode::menu-indicator {{ image: url({A["arrow_down"]}); subcontrol-origin: padding;
    subcontrol-position: right center; right: 8px; width: 10px; height: 10px; }}
QFrame#SensBox {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 6px; }}
QFrame#SensBox QLabel {{ background: transparent; }}
QLabel[role="sensval"] {{ font-family: "{mono}"; font-size: 13px; font-weight: 500; color: {ACCENT}; }}
QLabel[role="valuepill"] {{
    font-family: "{mono}"; font-size: 11px; padding: 2px 0; border-radius: 4px;
    background: {SURFACE_2}; border: 1px solid {BORDER};
}}
QLabel[role="hint9"] {{ font-size: 9.5px; color: {FAINT}; }}
QLabel[role="subcaps"] {{
    font-family: "{label}"; font-size: 9.5px; letter-spacing: 1px; color: {FAINT};
}}

QToolButton[ibtn] {{ background: transparent; border: 0; border-radius: 5px; padding: 0; }}
QToolButton[ibtn]:hover {{ background: {HOVER}; }}
QToolButton[ibtn="danger"]:hover {{ background: {ERR_BG}; }}
QToolButton[ibtn="border"] {{ border: 1px solid {BORDER_2}; background: {SURFACE}; }}
QToolButton[ibtn]:disabled {{ background: transparent; }}
QWidget#PaneHeader {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
QLabel[role="keyhint"] {{
    font-family: "{mono}"; font-size: 10px; color: {FAINT}; padding: 0 4px;
    border: 1px solid {BORDER}; border-radius: 3px; background: transparent;
}}
QLabel[role="countpill"] {{
    font-family: "{mono}"; font-size: 10px; color: {FAINT}; padding: 1px 6px;
    border-radius: 8px; background: {SURFACE_2}; border: 1px solid {BORDER};
}}
QLabel[role="statlabel"] {{ font-size: 9.5px; color: {FAINT}; letter-spacing: 0.5px; }}
QFrame#StatGrid {{ background: {BORDER}; border: 0; border-bottom: 1px solid {BORDER}; }}
QWidget#StatCell {{ background: {SURFACE}; }}
QFrame#RunPanel {{ background: {SURFACE_2}; border-top: 1px solid {BORDER}; }}
QFrame#VideoRow {{ background: transparent; border: 1px solid transparent; border-radius: 7px; }}
QFrame#VideoRow:hover {{ background: {HOVER}; }}
QFrame#VideoRow[selected="true"] {{ background: {ACCENT_BG}; border: 1px solid {ACCENT_LINE}; }}
QLabel#RowName {{ color: {TEXT}; background: transparent; }}
QLabel#RowState {{ font-size: 10.5px; background: transparent; color: {TEXT_2}; }}
QLabel#RowState[vstate="done"] {{ color: {OK}; }}
QLabel#RowState[vstate="running"] {{ color: {ACCENT}; }}
QLabel#RowState[vstate="ready"] {{ color: {TEXT_2}; }}
QLabel#RowState[vstate="needs"] {{ color: {FAINT}; }}
QLabel#RowState[vstate="error"] {{ color: {ERR}; }}

/* Experiment tab surfaces (objectNames set in gui/experiment*_tab.py) */
QWidget#Pane {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QFrame#ResultCard {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
}}
QFrame#TransportCard {{ background: {SURFACE}; border: 0; border-top: 1px solid {BORDER}; }}
QFrame#TransportGroup {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 7px; }}
QFrame#FrameBlock {{ background: transparent; border: 0; border-left: 1px solid {BORDER}; }}
QFrame#FrameBlock QLabel {{ background: transparent; }}
QLabel#ErrDot {{ background: {ERR}; border-radius: 2px; }}
QToolButton[ibtn="primary"] {{ background: {ACCENT}; border-radius: 5px; }}
QToolButton[ibtn="primary"]:hover {{ background: {ACCENT_HI}; }}
QToolButton[ibtn="primary"]:disabled {{ background: {ACCENT_DIS}; }}
QLabel[role="scrub"] {{ font-family: "{mono}"; font-size: 19px; font-weight: 500; color: {TEXT}; letter-spacing: -0.3px; }}
QLabel[role="scrubtotal"] {{ font-family: "{mono}"; font-size: 11.5px; color: {FAINT}; }}
QLabel[role="slidervalue"] {{ font-family: "{mono}"; font-size: 10.5px; color: {TEXT_2}; }}
QLabel[role="frame"] {{ font-family: "{mono}"; font-size: 11.5px; color: {TEXT}; }}
QGroupBox#StepGroup {{
    margin: 0; background: transparent; border: 0; border-bottom: 1px solid {BORDER};
    /* 46 px header (step_card.HEADER_H) + 12 px gap before the content */
    padding: 58px 0px 6px 0px; font-size: 12px; color: {TEXT};
}}
QGroupBox#StepGroup::title {{ subcontrol-origin: margin; height: 0px; padding: 0; }}
QToolButton#InfoBtn {{
    color: {MUTED}; font-size: 12px; padding: 0; background: transparent;
    border: 1px solid {BORDER_2}; border-radius: 9px;
}}
QToolButton#InfoBtn:hover {{ background: {ACCENT_BG}; border-color: {ACCENT}; color: {TEXT}; }}
QToolButton#InfoBtn:pressed {{ background: {ACCENT_LINE}; }}

/* Panels (gui/panels.py): header = drag handle on top of the pane body */
QMainWindow#PanelHost {{ background: transparent; }}
QMainWindow#PanelHost::separator {{ background: transparent; width: 10px; height: 10px; }}
QMainWindow#PanelHost::separator:hover {{ background: {G_ACC_BG}; }}
QWidget#PaneHeader[panel="true"] {{
    background: {G_PANEL}; border: 1px solid {G_RIM}; border-top-color: {G_HI};
    border-bottom: 1px solid {G_LINE};
    border-top-left-radius: 14px; border-top-right-radius: 14px;
}}
QWidget#PanelBody {{
    background: {G_PANEL}; border: 1px solid {G_RIM}; border-top: 0;
    border-bottom-left-radius: 14px; border-bottom-right-radius: 14px;
}}
QWidget#Pane[panel="true"], QScrollArea#Measurements[panel="true"] {{
    background: transparent; border: 0; border-radius: 0;
}}
QFrame#PanelDivider {{ background: {G_LINE}; border: 0; margin: 0 2px; }}
QWidget#PaneHeader[floating="true"], QWidget#PanelBody[floating="true"] {{
    background: {POPUP}; border-radius: 0;
}}

/* Video canvas toolbar + legend (gui/canvas_chrome.py) */
QWidget#CanvasBar {{ background: transparent; border-bottom: 1px solid {BORDER}; }}
QFrame#CanvasGroup {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 6px; }}
QPushButton#CanvasView {{ padding: 0 26px 0 10px; font-size: 11px; text-align: left; }}
QWidget#CanvasLegend {{ background: transparent; border-top: 1px solid {BORDER}; }}

/* Right-hand measurements sidebar */
QScrollArea#Measurements {{ background: {SURFACE}; border-left: 1px solid {BORDER}; }}
QWidget#MeasBody {{ background: {SURFACE}; }}

/* ── Glass layer ─────────────────────────────────────────────────
   Floating panes over the aurora (gui.backdrop). Declared last so it
   wins over the base rules above. */
QMainWindow {{ background: {base_bg}; }}
QDialog {{ background: {base_bg}; }}
QWidget#AppHeader {{ background: {G_PANEL}; border: 0; border-bottom: 1px solid {G_RIM}; }}
QStatusBar {{ background: {G_PANEL}; border-top: 1px solid {G_RIM}; }}
QWidget#Pane, QScrollArea#Measurements {{
    background: {G_PANEL}; border: 1px solid {G_RIM}; border-top-color: {G_HI};
    border-radius: 14px;
}}
QWidget#MeasBody, QWidget#PaneHeader, QWidget#StatCell, QWidget[role="meas-section"] {{
    background: transparent;
}}
QWidget#PaneHeader {{ border-top-left-radius: 14px; border-top-right-radius: 14px; }}
QFrame#ResultCard, QFrame[role="card"] {{
    background: {G_PANEL}; border: 1px solid {G_RIM}; border-top-color: {G_HI}; border-radius: 12px;
}}
QFrame#StatGrid, QFrame#GridCells {{ background: {G_SUNK}; border: 1px solid {G_LINE}; border-radius: 10px; }}
QWidget#StatCell, QWidget#GridCell {{ background: transparent; }}
QFrame#RunPanel {{
    background: {G_SUNK}; border-bottom-left-radius: 13px; border-bottom-right-radius: 13px;
}}
QTabWidget::pane {{ background: transparent; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {G_ACC_BG}; }}
QPushButton, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    border-radius: 8px;
}}
QMenu, QComboBox QAbstractItemView {{
    background: {POPUP}; border: 1px solid {POPUP_EDGE}; border-radius: 10px;
}}
QMenu::item:selected {{ background: {G_ACC_BG}; }}
QToolTip {{ background: {POPUP}; color: {TEXT}; border: 1px solid {POPUP_EDGE}; border-radius: 6px; }}
"""


# ── Instrument control kit ────────────────────────────────────────────────
# Scientific-style buttons, fields, chips and segmented controls (custom
# widgets live in gui.kit). Uses the *opaque* tokens so controls read as
# solid instruments on the glass panes. KIT_SCOPE limits the kit to widgets
# under that selector — "" applies it app-wide.
KIT_SCOPE = "QWidget#KitSheet "


def _kit_qss(scope, mono):
    rules = f"""
@QPushButton {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER_2}; border-radius: 4px;
    padding: 0 12px; min-height: 26px; font-size: 12px; font-weight: 500;
}}
@QPushButton:hover {{ background: {HOVER}; border-color: {FAINT}; }}
@QPushButton:focus {{ border-color: {ACCENT}; }}
@QPushButton:pressed {{ background: {INPUT}; padding-top: 1px; }}
@QPushButton:disabled {{ background: transparent; color: {DISABLED}; border: 1px dashed {BORDER_2}; }}
@QPushButton[primary="true"] {{
    background: {ACCENT}; border: 1px solid {ACCENT}; color: {ON_ACCENT}; font-weight: 600;
}}
@QPushButton[primary="true"]:hover {{ background: {ACCENT_HI}; border-color: {ACCENT_HI}; }}
@QPushButton[primary="true"]:pressed {{ background: {ACCENT}; padding-top: 1px; }}
@QPushButton[primary="true"]:disabled {{ background: transparent; border: 1px dashed {ACCENT_DIS}; color: {DISABLED}; }}
@QPushButton[ghost="true"] {{ background: transparent; border-color: transparent; color: {TEXT_2}; }}
@QPushButton[ghost="true"]:hover {{ background: {HOVER}; color: {TEXT}; }}
@QPushButton[danger="true"] {{ background: transparent; border-color: {ERR_LINE}; color: {ERR}; }}
@QPushButton[danger="true"]:hover {{ background: {ERR_BG}; border-color: {ERR}; }}

@QLineEdit, @QComboBox, @QSpinBox, @QDoubleSpinBox {{
    background: {INPUT}; color: {TEXT}; border: 1px solid {BORDER_2}; border-radius: 4px;
    padding: 0 8px; min-height: 26px; selection-background-color: {ACCENT}; selection-color: {ON_ACCENT};
}}
@QLineEdit:hover, @QComboBox:hover, @QSpinBox:hover, @QDoubleSpinBox:hover {{ border-color: {FAINT}; }}
@QLineEdit:focus, @QComboBox:focus, @QSpinBox:focus, @QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
@QLineEdit[invalid="true"] {{ border-color: {ERR}; background: {ERR_BG}; }}
@QComboBox::drop-down {{ width: 24px; border: 0; border-left: 1px solid {BORDER}; }}
@QFrame#MeasureField {{ background: {INPUT}; border: 1px solid {BORDER_2}; border-radius: 4px; }}
@QFrame#MeasureField:hover {{ border-color: {FAINT}; }}
@QFrame#MeasureField[focused="true"] {{ border-color: {ACCENT}; }}
@QFrame#MeasureField[invalid="true"] {{ border-color: {ERR}; background: {ERR_BG}; }}
@QDoubleSpinBox#MeasureSpin {{
    background: transparent; border: 0; padding: 0 4px; min-height: 0; font-family: "{mono}";
}}
@QToolButton#MeasureStep {{
    background: transparent; border: 0; border-radius: 3px; color: {TEXT_2}; font-size: 14px; padding: 0;
}}
@QToolButton#MeasureStep:hover {{ background: {HOVER}; color: {TEXT}; }}
@QToolButton#MeasureStep:pressed {{ background: {ACCENT_BG}; color: {ACCENT}; }}

@QCheckBox[chip="true"] {{
    spacing: 0; padding: 0 8px; height: 22px; border-radius: 3px; font-family: "{mono}"; font-size: 11px;
    background: {INPUT}; color: {TEXT_2}; border: 1px solid {BORDER_2};
}}
@QCheckBox[chip="true"]:checked {{ background: {ACCENT_BG}; color: {ACCENT}; border: 1px solid {ACCENT_LINE}; }}
@QCheckBox[chip="true"]::indicator {{ width: 0; height: 0; }}

@QFrame#Segmented {{ background: {INPUT}; border: 1px solid {BORDER_2}; border-radius: 4px; }}
@QFrame#Segmented QPushButton {{
    background: transparent; border: 0; border-radius: 0;
    color: {TEXT_2}; font-size: 11.5px; font-weight: 500; min-height: 0; padding: 0 12px;
}}
@QFrame#Segmented QPushButton:hover {{ background: {HOVER}; color: {TEXT}; }}
@QFrame#Segmented QPushButton:checked {{ background: {ACCENT_BG}; color: {ACCENT}; }}

@QLabel[role="kit-section"] {{ font-size: 13px; font-weight: 600; color: {TEXT}; background: transparent; }}
@QLabel[role="kit-caption"] {{ font-size: 11px; color: {FAINT}; background: transparent; }}
@QLabel[role="kit-label"] {{ font-size: 12px; color: {TEXT_2}; background: transparent; }}
@QLabel[role="kit-error"] {{ font-size: 11px; color: {ERR}; background: transparent; }}
"""
    return rules.replace("@", scope)


_applied_fonts = {}


def _remap_widget_fonts(app, new):
    """Widgets given an explicit font at build time (e.g. mono_font()) keep
    it through stylesheet changes — swap their family when a role changes."""
    remap = {_applied_fonts[r]: f for r, f in new.items()
             if _applied_fonts.get(r) and _applied_fonts[r] != f}
    _applied_fonts.update(new)
    if not remap:
        return
    from PyQt5.QtCore import Qt
    for w in app.allWidgets():
        if w.testAttribute(Qt.WA_SetFont):
            f = w.font()
            if f.family() in remap:
                f.setFamily(remap[f.family()])
                w.setFont(f)


def apply_theme(app, new_mode=None):
    """Install palette, font and global stylesheet on the QApplication.

    Pass `new_mode` ("light" / "dark") to switch tokens first; the
    `notifier.changed` signal is emitted so custom-painted widgets refresh.
    """
    # Always re-derive: the palette may have changed (View → Appearance).
    set_mode(new_mode if new_mode is not None else _mode)
    if app.style().objectName().lower() != "fusion":
        app.setStyle("Fusion")
    sans, mono = sans_family(), mono_family()
    _remap_widget_fonts(app, {"ui": sans, "data": mono})
    font = QFont(sans)
    font.setPixelSize(12)
    app.setFont(font)
    app.setPalette(_palette())
    sheet = _qss(sans, mono, _assets()) + _kit_qss(KIT_SCOPE, mono)
    # Repaint once at the end instead of widget-by-widget while restyling.
    windows = [w for w in app.topLevelWidgets() if w.updatesEnabled()]
    for w in windows:
        w.setUpdatesEnabled(False)
    try:
        # Swapping one big stylesheet for another makes Qt re-resolve every
        # widget against the old one (~0.8s); clearing first is ~8x faster
        # and renders identically.
        app.setStyleSheet("")
        app.setStyleSheet(sheet)
        notifier.changed.emit(_mode)
    finally:
        for w in windows:
            w.setUpdatesEnabled(True)
