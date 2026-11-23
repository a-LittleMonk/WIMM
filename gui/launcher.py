"""Launcher (start) screen — redesign per design_handoff_launcher/Launcher.dc.html
(section "Turn 4", variant 4a).

Two-column body: a brand column (logo, big WIMM logo, a technical
backdrop centred on the logo) on the left; on the right a "New experiment"
card (text + Create on the left, an arena sketch on the right) and one icon
dropdown — search, sections, arena icons — to open any experiment (built-in
or saved). Colours always come from `gui.theme` tokens (never hard-coded), so the
screen follows the user's palette and light/dark switch.
"""
import os
import time

from PyQt5.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QFontMetricsF, QImage, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap, QRadialGradient,
)
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QStyledItemDelegate,
    QStyleOptionViewItem, QVBoxLayout, QWidget,
)

from gui import icons, theme

ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets"
)
_PKG_PNG = os.path.join(ASSETS_DIR, "logo-package-v4", "png")
# QtSvg's <mask> support is too limited for these marks (it ignores the
# luminance mask that cuts the eye / nose dots / tail out of the solid pin
# shape, rendering it fully filled) — use the pre-rendered PNGs instead, at
# a high enough source size to stay crisp when tinted and downscaled.
LOGO_OUTLINE = os.path.join(_PKG_PNG, "mouse-track-4e-outline-white-1024.png")  # 4e — launcher + header mark
# 4b tile (solid square, negative-space mouse cutout) — not used by default;
# the outline mark above reads better at the header's small 26 px size.
LOGO_TILE = os.path.join(_PKG_PNG, "mouse-track-4b-tile-white-1024.png")

_svg_cache = {}


def tinted_svg_pixmap(path, size, color):
    """Render an SVG or raster mark tinted with `color`
    (CompositionMode_SourceIn), HiDPI aware and cached. The source assets are
    white-on-transparent marks meant to be recoloured this way."""
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    key = (path, int(size), str(color), float(dpr))
    pm = _svg_cache.get(key)
    if pm is not None:
        return pm
    px = max(1, int(round(size * dpr)))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if path.lower().endswith(".svg"):
        renderer = QSvgRenderer(path.replace("\\", "/"))
        renderer.render(p, QRectF(0, 0, px, px))
    else:
        # QPainter.drawImage() does not reliably honour the
        # SmoothPixmapTransform render hint (a known Qt raster-engine quirk)
        # — it can fall back to nearest-neighbour and look pixelated.
        # QImage.scaled(..., Qt.SmoothTransformation) always does a proper
        # smooth resize, so do that first and draw the result 1:1.
        src = QImage(path).scaled(
            px, px, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
        )
        p.drawImage(0, 0, src)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(0, 0, px, px, QColor(color))
    p.end()
    pm.setDevicePixelRatio(dpr)
    _svg_cache[key] = pm
    return pm


def _parse_css_color(s):
    """QColor() doesn't parse CSS rgba()/rgb() strings — theme.py's glass
    tokens are exactly that, so pull the RGB out by hand."""
    s = s.strip()
    if s.startswith("rgba") or s.startswith("rgb"):
        nums = s[s.index("(") + 1: s.index(")")].split(",")
        r, g, b = (int(float(n)) for n in nums[:3])
        return QColor(r, g, b)
    return QColor(s)


def _line_qcolor(alpha):
    """A backdrop/border line colour: the app's pane-outline tint
    (`theme.G_RIM`) at a custom alpha — matches the handoff's `BORDER` token
    at whichever alpha a given line needs (.06 … .18)."""
    base = _parse_css_color(theme.G_RIM)
    c = QColor(base.red(), base.green(), base.blue())
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


class TitleBlock(QWidget):
    """WIMM logo (variant 2f4 from WIMM-logo-2f4.md), painted directly:
    "W I M M" in Quicksand Bold with the words WHERE / IS / MY / MOUSE?
    (Instrument Sans Medium) centred under each letter. Both fonts ship in
    assets/fonts, so the mark looks the same on every computer. Everything
    scales from one size (`_px` = letter size); ratios are from the spec."""

    LETTERS = ("W", "I", "M", "M")
    WORDS = ("WHERE", "IS", "MY", "MOUSE?")
    LINE_HEIGHT = 0.8          # letter line-height, × size
    LETTER_SPACING = -0.02     # W, M, M (I gets 0), × size
    I_PAD_LEFT = 0.0615        # optical compensation for I, × size
    I_MARGIN_RIGHT = -0.0163
    ROW_GAP = 0.113            # letters → words, × size
    WORD_SIZE = 0.129          # word font size, × size
    WORD_SPACING = 0.12        # word letter-spacing, × word size

    def __init__(self, parent=None):
        super().__init__(parent)
        self._px = 124
        self._color = QColor(theme.TEXT)
        self.setAccessibleName("WIMM — Where is my mouse?")

    def set_size(self, px):
        if px != self._px:
            self._px = px
            self.updateGeometry()
            self.update()

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def _fonts(self):
        lf = QFont("Quicksand")
        lf.setWeight(QFont.Bold)
        lf.setPixelSize(self._px)
        wpx = max(1.0, self._px * self.WORD_SIZE)
        wf = QFont("Instrument Sans Medium")  # bundled logo font (own family name)
        wf.setPixelSize(max(1, round(wpx)))
        return lf, wf, wpx

    def _layout(self):
        """Grid geometry: column left edges/widths, letter/word positions."""
        S = float(self._px)
        lf, wf, wpx = self._fonts()
        lm, wm = QFontMetricsF(lf), QFontMetricsF(wf)
        ws = self.WORD_SPACING * wpx
        cols = []   # (item_left_pad, letter_adv, margin_box_w, word_w)
        for i, (ch, word) in enumerate(zip(self.LETTERS, self.WORDS)):
            adv = lm.horizontalAdvance(ch)
            if ch == "I":
                pad, ls, mr = self.I_PAD_LEFT * S, 0.0, self.I_MARGIN_RIGHT * S
            else:
                pad, ls, mr = 0.0, self.LETTER_SPACING * S, 0.0
            item_w = pad + adv + ls
            word_w = wm.horizontalAdvance(word) + ws * len(word)
            cols.append((pad, adv, item_w, mr, word_w))
        col_w = [max(c[2] + c[3], c[4]) for c in cols]
        line_h = self.LINE_HEIGHT * S
        base = (line_h - (lm.ascent() + lm.descent())) / 2 + lm.ascent()
        word_top = line_h + self.ROW_GAP * S
        height = word_top + wm.height()
        return lf, wf, ws, cols, col_w, base, word_top, wm.ascent(), sum(col_w), height

    def sizeHint(self):
        *_, width, height = self._layout()
        return QSize(int(width) + 2, int(height) + 2)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, _event):
        lf, wf, ws, cols, col_w, base, word_top, word_asc, _w, _h = self._layout()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setPen(self._color)
        wf.setLetterSpacing(QFont.AbsoluteSpacing, ws)
        x = 0.0
        for ch, word, (pad, adv, item_w, mr, word_w), cw in zip(
                self.LETTERS, self.WORDS, cols, col_w):
            box_left = x + (cw - (item_w + mr)) / 2
            lf2 = QFont(lf)
            if ch != "I":
                lf2.setLetterSpacing(QFont.AbsoluteSpacing, self.LETTER_SPACING * self._px)
            p.setFont(lf2)
            p.drawText(QPointF(box_left + pad, base), ch)
            p.setFont(wf)
            p.drawText(QPointF(x + (cw - word_w) / 2, word_top + word_asc), word)
            x += cw
        p.end()


class BrandColumn(QWidget):
    """Left column: logo, technical backdrop (paintEvent, centred on the
    logo), and the WIMM logo / "BEHAVIOR LAB" title block."""

    WIDE_WIDTH = 540
    NARROW_WIDTH = 460
    WIDE_TITLE = 144
    NARROW_TITLE = 118
    NARROW_BREAKPOINT = 1100
    ORIGIN = QPointF(100, 100)  # logo centre — everything below is drawn around it

    def __init__(self, parent=None):
        super().__init__(parent)
        self.show_grid = True
        self._grid_pm = None
        self._grid_key = None

        self.setFixedWidth(self.WIDE_WIDTH)
        v = QVBoxLayout(self)
        v.setContentsMargins(64, 64, 56, 48)
        v.setSpacing(0)

        self.logo = QLabel()
        self.logo.setFixedSize(72, 72)
        v.addWidget(self.logo, 0, Qt.AlignLeft | Qt.AlignTop)

        v.addStretch(1)

        self.title = TitleBlock()
        v.addWidget(self.title, 0, Qt.AlignLeft | Qt.AlignBottom)

        v.addSpacing(40)
        self.rule = QFrame()
        self.rule.setFixedHeight(1)
        v.addWidget(self.rule)
        v.addSpacing(18)
        self.tag = QLabel("BEHAVIOR LAB")
        v.addWidget(self.tag)

        self._retint()
        theme.notifier.changed.connect(self._retint)

    def set_narrow(self, narrow):
        width = self.NARROW_WIDTH if narrow else self.WIDE_WIDTH
        if self.width() != width:
            self.setFixedWidth(width)
            self._grid_pm = None
        self.title.set_size(self.NARROW_TITLE if narrow else self.WIDE_TITLE)

    def set_show_grid(self, on):
        on = bool(on)
        if on != self.show_grid:
            self.show_grid = on
            self.update()

    def _retint(self, *_):
        self.logo.setPixmap(tinted_svg_pixmap(LOGO_OUTLINE, 72, theme.TEXT))
        self.title.set_color(theme.TEXT)
        self.rule.setStyleSheet(f"background:{_line_qcolor(0.18).name(QColor.HexArgb)}; border:0;")
        f = QFont(theme.mono_family())
        f.setPixelSize(11)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        self.tag.setFont(f)
        self.tag.setStyleSheet(
            f"color:{theme.FAINT}; background:transparent; letter-spacing:4px;"
        )
        self._grid_pm = None
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._grid_pm = None

    # ── backdrop ─────────────────────────────────────────────────────────
    def _grid_pixmap(self):
        w, h = max(1, self.width()), max(1, self.height())
        dpr = self.devicePixelRatioF()
        key = (w, h, dpr, theme.mode())
        if self._grid_pm is not None and self._grid_key == key:
            return self._grid_pm
        pm = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(_line_qcolor(0.06))
        pen.setWidth(1)
        p.setPen(pen)
        step = 36
        x = 28.0
        while x < w:
            p.drawLine(QPointF(x, 0), QPointF(x, h))
            x += step
        y = 28.0
        while y < h:
            p.drawLine(QPointF(0, y), QPointF(w, y))
            y += step
        # Radial fade: full opacity at O → 35% at 294px (70%) → 0 at 420px.
        grad = QRadialGradient(self.ORIGIN, 420)
        grad.setColorAt(0.0, QColor(0, 0, 0, 255))
        grad.setColorAt(0.7, QColor(0, 0, 0, round(255 * 0.35)))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.fillRect(0, 0, w, h, grad)
        p.end()
        self._grid_pm = pm
        self._grid_key = key
        return pm

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        O = self.ORIGIN
        if self.show_grid:
            p.drawPixmap(0, 0, self._grid_pixmap())

            for radius, style, alpha in (
                (72, Qt.DashLine, 0.16), (180, Qt.SolidLine, 0.12),
                (324, Qt.SolidLine, 0.09), (504, Qt.SolidLine, 0.06),
            ):
                pen = QPen(_line_qcolor(alpha))
                pen.setWidth(1)
                pen.setStyle(style)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(O, radius, radius)

            vgrad = QLinearGradient(0, 0, 0, h)
            vgrad.setColorAt(0.0, _line_qcolor(0.16))
            vgrad.setColorAt(0.85, _line_qcolor(0.0))
            vgrad.setColorAt(1.0, _line_qcolor(0.0))
            p.fillRect(QRectF(O.x() - 0.5, 0, 1, h), QBrush(vgrad))

            hgrad = QLinearGradient(0, 0, w, 0)
            hgrad.setColorAt(0.0, _line_qcolor(0.16))
            hgrad.setColorAt(0.95, _line_qcolor(0.0))
            hgrad.setColorAt(1.0, _line_qcolor(0.0))
            p.fillRect(QRectF(0, O.y() - 0.5, w, 1), QBrush(hgrad))

            pen = QPen(_line_qcolor(0.18))
            pen.setWidth(1)
            pen.setStyle(Qt.SolidLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(64.5, 64.5, 71, 71))

        # Right-edge divider — always on, independent of the backdrop toggle.
        pen = QPen(_line_qcolor(0.11))
        pen.setWidth(1)
        p.setPen(pen)
        p.drawLine(QPointF(w - 0.5, 0), QPointF(w - 0.5, h))
        p.end()


class _Card(QFrame):
    """Launcher pane in the start-page card look (theme glass tokens)."""

    clicked = pyqtSignal()

    def __init__(self, clickable=False, parent=None):
        super().__init__(parent)
        self._clickable = clickable
        self._hover = False
        if clickable:
            self.setCursor(Qt.PointingHandCursor)
        self._retint()
        theme.notifier.changed.connect(self._retint)

    def enterEvent(self, event):
        if self._clickable:
            self._hover = True
            self._retint()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._hover:
            self._hover = False
            self._retint()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if self._clickable and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def _retint(self, *_):
        bg = theme.G_HOVER if self._hover else theme.G_PANEL
        border = theme.G_ACC_LINE if self._hover else theme.G_RIM
        top = "" if self._hover else f"border-top-color:{theme.G_HI};"
        self.setStyleSheet(
            f"_Card {{ background:{bg}; border:1px solid {border}; {top} border-radius:12px; }}"
            f"_Card QLabel {{ background:transparent; }}")


# ── Experiment picker (design "A") ──────────────────────────────────────
# Built-in test title → (arena icon in gui.icons, one-line description).
TEST_META = {
    "Open Field": ("t_open_field", "Locomotion · anxiety"),
    "Y-Maze": ("t_y_maze", "Spontaneous alternation"),
    "Novel Object": ("t_novel_object", "Recognition memory"),
    "Elevated Plus": ("t_elevated_plus", "Anxiety-like behavior"),
    "Object Location": ("t_object_location", "Spatial memory"),
    "Three Chamber": ("t_three_chamber", "Sociability"),
    "Place Preference": ("t_place_pref", "Reward · conditioning"),
    "Light–Dark Box": ("t_light_dark", "Anxiety-like behavior"),
    "Zero Maze": ("t_zero_maze", "Anxiety-like behavior"),
    "T-Maze": ("t_t_maze", "Working memory"),
    "Radial Arm Maze": ("t_radial_maze", "Spatial working memory"),
    "Water Maze": ("t_water_maze", "Spatial learning"),
}
SAVED_ICON = "t_custom"


def _qc(token, alpha=None):
    """QColor from a theme token — '#RRGGBB' or the CSS 'rgba(r,g,b,a)'
    strings theme.py builds (a = 0–255). `alpha` (0–1) overrides."""
    s = (token or "").strip()
    if s.startswith("rgb"):
        nums = [float(n) for n in s[s.index("(") + 1: s.index(")")].split(",")]
        c = QColor(int(nums[0]), int(nums[1]), int(nums[2]))
        if len(nums) > 3:
            c.setAlpha(max(0, min(255, int(round(nums[3])))))
    else:
        c = QColor(s)
    if alpha is not None:
        c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _saved_color():
    """Hue that marks the user's own experiments (vs. the built-in tests)."""
    return "#9FC3FF" if theme.mode() == "dark" else "#3566B8"


def _font(px, weight=QFont.Normal, mono=False, spacing=0.0):
    f = QFont(theme.mono_family() if mono else theme.sans_family())
    f.setPixelSize(px)
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def _draw_icon(p, name, rect, color):
    pm = icons.pixmap(name, int(round(rect.width())), color)
    p.drawPixmap(rect, pm, QRectF(pm.rect()))


def _paint_tile(p, rect, icon_name, active=False, icon_color=None):
    """The rounded square behind each experiment icon (accent when active)."""
    if active:
        bg, edge, ic = _qc(theme.ACCENT, 0.13), _qc(theme.ACCENT, 0.35), theme.ACCENT
    else:
        bg, edge, ic = _qc(theme.TEXT, 0.05), _qc(theme.TEXT, 0.09), icon_color or theme.TEXT_2
    p.setPen(QPen(edge, 1))
    p.setBrush(bg)
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
    s = round(rect.height() * 0.56)
    _draw_icon(p, icon_name, QRectF(rect.center().x() - s / 2, rect.center().y() - s / 2, s, s), ic)


class ArenaSketch(QWidget):
    """Right half of the New-experiment card: a drafting grid with an arena
    outline, a dashed zone with corner handles, a dashed line and a pen —
    "draw your own"."""

    RADIUS = 12   # matches _Card's border-radius

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(240)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        theme.notifier.changed.connect(self.update)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = self.RADIUS - 1
        clip = QPainterPath()
        clip.moveTo(0, 0)
        clip.lineTo(w - r, 0)
        clip.arcTo(QRectF(w - 2 * r, 0, 2 * r, 2 * r), 90, -90)
        clip.lineTo(w, h - r)
        clip.arcTo(QRectF(w - 2 * r, h - 2 * r, 2 * r, 2 * r), 0, -90)
        clip.lineTo(0, h)
        clip.closeSubpath()
        p.setClipPath(clip)
        p.setPen(QPen(_qc(theme.TEXT, 0.05), 1))
        for x in range(20, w, 20):
            p.drawLine(QPointF(x + 0.5, 0), QPointF(x + 0.5, h))
        for y in range(20, h, 20):
            p.drawLine(QPointF(0, y + 0.5), QPointF(w, y + 0.5))
        p.setClipping(False)
        p.setPen(QPen(_qc(theme.TEXT, 0.08), 1))
        p.drawLine(QPointF(0.5, 0), QPointF(0.5, h))

        # The sketch is laid out on a 200×160 board, centred and scaled.
        s = min((w - 40) / 200.0, (h - 24) / 160.0, 1.2)
        p.translate(w / 2 - 100 * s, h / 2 - 80 * s)
        p.scale(s, s)
        acc = theme.ACCENT
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_qc(theme.TEXT_2, 0.9), 1.5))
        p.drawRoundedRect(QRectF(30, 20, 140, 120), 4, 4)
        pen = QPen(QColor(acc), 1.5)
        pen.setDashPattern([3.3, 2.7])
        p.setPen(pen)
        p.setBrush(_qc(acc, 0.12))
        p.drawRoundedRect(QRectF(65, 50, 70, 60), 2, 2)
        pen = QPen(QColor(_saved_color()), 1.5)
        pen.setDashPattern([2, 2])
        p.setPen(pen)
        p.drawLine(QPointF(30, 80), QPointF(65, 80))
        p.setPen(QPen(QColor(acc), 1.5))
        p.setBrush(QColor(theme.SURFACE))
        for cx, cy in ((65, 50), (135, 50), (135, 110), (65, 110)):
            p.drawEllipse(QPointF(cx, cy), 3.5, 3.5)
        p.setPen(QPen(QColor(theme.TEXT), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        pencil = QPainterPath(QPointF(150, 128))
        for x, y in ((164, 114), (170, 120), (156, 134), (150, 134)):
            pencil.lineTo(x, y)
        pencil.closeSubpath()
        p.drawPath(pencil)
        p.end()


class _ExperimentField(QWidget):
    """The closed dropdown: icon tile, name, description and a chevron."""

    clicked = pyqtSignal()
    RING = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entry = None
        self._open = False
        self._hover = False
        self.setFixedHeight(56 + 2 * self.RING)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("Experiment")
        theme.notifier.changed.connect(self.update)

    def set_entry(self, entry):
        self._entry = entry
        self.setAccessibleDescription(entry["name"] if entry else "")
        self.update()

    def set_open(self, on):
        self._open = bool(on)
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        k = event.key()
        if k in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Down, Qt.Key_F4):
            self.clicked.emit()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.update()
        super().focusOutEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        g = self.RING
        box = QRectF(self.rect()).adjusted(g + 0.5, g + 0.5, -g - 0.5, -g - 0.5)
        active = self._open or self.hasFocus()
        if active:
            p.setPen(QPen(_qc(theme.ACCENT, 0.18), g))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box.adjusted(-g / 2, -g / 2, g / 2, g / 2), 11.5, 11.5)
        edge = QColor(theme.ACCENT) if active else (
            _qc(theme.TEXT, 0.22) if self._hover else _qc(theme.G_LINE_2))
        p.setPen(QPen(edge, 1))
        p.setBrush(_qc(theme.G_INPUT))
        p.drawRoundedRect(box, 10, 10)
        e = self._entry
        if e:
            tile = QRectF(box.left() + 10, box.center().y() - 18, 36, 36)
            _paint_tile(p, tile, e["icon"], active=not e["saved"],
                        icon_color=_saved_color() if e["saved"] else None)
            x = tile.right() + 12
            tw = box.right() - 40 - x
            p.setPen(QColor(theme.TEXT))
            f = _font(14, QFont.Medium)
            p.setFont(f)
            p.drawText(QRectF(x, box.center().y() - 19, tw, 19), Qt.AlignLeft | Qt.AlignBottom,
                       QFontMetrics(f).elidedText(e["name"], Qt.ElideRight, int(tw)))
            p.setPen(QColor(theme.FAINT))
            f = _font(12)
            p.setFont(f)
            sub = ("Your experiment · " if e["saved"] else "Built-in · ") + e["sub"]
            p.drawText(QRectF(x, box.center().y() + 1, tw, 17), Qt.AlignLeft | Qt.AlignTop,
                       QFontMetrics(f).elidedText(sub, Qt.ElideRight, int(tw)))
        s = 16
        _draw_icon(p, "chevron_u" if self._open else "chevron_d",
                   QRectF(box.right() - 14 - s, box.center().y() - s / 2, s, s), theme.FAINT)
        p.end()


ROLE_KIND = Qt.UserRole + 1
ROLE_ENTRY = Qt.UserRole + 2


class _RowDelegate(QStyledItemDelegate):
    """Paints the popup's rows: section headers, experiment rows (icon tile,
    name, description, check / edit + delete) and the empty state."""

    ROW_H, HEAD_H, EMPTY_H = 52, 34, 44

    def __init__(self, popup):
        super().__init__(popup)
        self.popup = popup

    def sizeHint(self, option, index):
        kind = index.data(ROLE_KIND)
        h = {"header": self.HEAD_H, "empty": self.EMPTY_H}.get(kind, self.ROW_H)
        e = index.data(ROLE_ENTRY) or {}
        if kind == "header" and e.get("divider"):
            h += 9
        return QSize(option.rect.width(), h)

    @staticmethod
    def action_rects(row_rect):
        """(edit, delete) hit areas at the right of a saved-experiment row."""
        r = QRectF(row_rect)
        dele = QRectF(r.right() - 10 - 30, r.center().y() - 15, 30, 30)
        edit = dele.translated(-34, 0)
        return edit, dele

    def paint(self, p, option, index):
        kind = index.data(ROLE_KIND)
        e = index.data(ROLE_ENTRY) or {}
        r = QRectF(option.rect)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if kind == "header":
            if e.get("divider"):
                p.setPen(QPen(_qc(theme.TEXT, 0.08), 1))
                p.drawLine(QPointF(r.left() + 8, r.top() + 4.5), QPointF(r.right() - 8, r.top() + 4.5))
                r = r.adjusted(0, 9, 0, 0)
            p.setPen(QColor(theme.FAINT))
            p.setFont(_font(11, mono=True, spacing=2))
            tr = r.adjusted(12, 0, -12, -6)
            p.drawText(tr, Qt.AlignLeft | Qt.AlignBottom, e.get("text", ""))
            p.drawText(tr, Qt.AlignRight | Qt.AlignBottom, str(e.get("count", "")))
        elif kind == "empty":
            p.setPen(QColor(theme.FAINT))
            p.setFont(_font(13))
            p.drawText(r.adjusted(14, 0, -12, 0), Qt.AlignLeft | Qt.AlignVCenter, e.get("text", ""))
        else:
            row = r.adjusted(2, 2, -2, -2)
            current = e.get("key") == self.popup.current_key
            hovered = index.row() == self.popup.hover_row
            if current:
                p.setPen(Qt.NoPen)
                p.setBrush(_qc(theme.ACCENT, 0.10))
                p.drawRoundedRect(row, 9, 9)
            elif hovered:
                p.setPen(Qt.NoPen)
                p.setBrush(_qc(theme.TEXT, 0.05))
                p.drawRoundedRect(row, 9, 9)
            saved = e.get("saved")
            tile = QRectF(row.left() + 8, row.center().y() - 18, 36, 36)
            _paint_tile(p, tile, e["icon"], active=current and not saved,
                        icon_color=_saved_color() if saved else None)
            show_actions = saved and (hovered or current)
            right = row.right() - 12
            if show_actions:
                edit_r, del_r = self.action_rects(row)
                right = edit_r.left() - 8
                for rect, name, color, which in ((edit_r, "edit", theme.TEXT_2, "edit"),
                                                 (del_r, "trash", theme.ERR, "delete")):
                    if hovered and self.popup.hover_action == which:
                        p.setPen(Qt.NoPen)
                        p.setBrush(_qc(theme.TEXT, 0.09))
                        p.drawRoundedRect(rect, 7, 7)
                    _draw_icon(p, name, QRectF(rect.center().x() - 8, rect.center().y() - 8, 16, 16), color)
            elif current:
                _draw_icon(p, "check", QRectF(row.right() - 12 - 16, row.center().y() - 8, 16, 16),
                           theme.ACCENT)
                right = row.right() - 36
            x = tile.right() + 12
            tw = max(10.0, right - x)
            f = _font(14, QFont.Medium)
            p.setFont(f)
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(x, row.center().y() - 18, tw, 18), Qt.AlignLeft | Qt.AlignBottom,
                       QFontMetrics(f).elidedText(e["name"], Qt.ElideRight, int(tw)))
            f = _font(12)
            p.setFont(f)
            p.setPen(QColor(theme.FAINT))
            p.drawText(QRectF(x, row.center().y() + 1, tw, 16), Qt.AlignLeft | Qt.AlignTop,
                       QFontMetrics(f).elidedText(e["sub"], Qt.ElideRight, int(tw)))
        p.restore()


class _ExperimentPopup(QFrame):
    """The open dropdown: a search box over a sectioned, icon list of every
    experiment. Type to filter; ↑/↓ + Enter to pick; Esc to close. Saved
    experiments get edit / delete buttons on hover."""

    picked = pyqtSignal(object)          # entry key
    closed = pyqtSignal()
    action = pyqtSignal(str, object)     # ("edit" | "delete", path)
    MARGIN = 14                          # room for the drop shadow
    MAX_LIST_H = 440

    def __init__(self, entries, current_key, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.current_key = current_key
        self.hover_row = -1
        self.hover_action = None

        outer = QVBoxLayout(self)
        m = self.MARGIN
        outer.setContentsMargins(m, m - 6, m, m + 6)
        self.panel = QFrame()
        self.panel.setObjectName("ExpPopupPanel")
        shadow = QGraphicsDropShadowEffect(self.panel)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 120 if theme.mode() == "dark" else 50))
        self.panel.setGraphicsEffect(shadow)
        outer.addWidget(self.panel)

        v = QVBoxLayout(self.panel)
        v.setContentsMargins(8, 10, 8, 8)
        v.setSpacing(4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search experiments…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(38)
        self.search.addAction(icons.icon("search", 14, theme.FAINT), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._filter)
        self.search.installEventFilter(self)
        v.addWidget(self.search)

        self.list = QListWidget()
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setMouseTracking(True)
        self.list.viewport().setMouseTracking(True)
        self.list.setUniformItemSizes(False)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setItemDelegate(_RowDelegate(self))
        self.list.viewport().installEventFilter(self)
        self.list.viewport().setCursor(Qt.PointingHandCursor)
        v.addWidget(self.list)

        for e in entries:
            it = QListWidgetItem()
            it.setData(ROLE_KIND, e["kind"])
            it.setData(ROLE_ENTRY, e)
            if e["kind"] != "item":
                it.setFlags(Qt.NoItemFlags)
            self.list.addItem(it)
        self._no_match = QListWidgetItem()
        self._no_match.setData(ROLE_KIND, "empty")
        self._no_match.setData(ROLE_ENTRY, {"text": ""})
        self._no_match.setFlags(Qt.NoItemFlags)
        self.list.addItem(self._no_match)

        self._retint()
        self._filter("")
        row = self._row_of(current_key)
        if row is not None:
            self.list.scrollToItem(self.list.item(row), QListWidget.PositionAtCenter)

    # ── helpers
    def _entry(self, row):
        it = self.list.item(row)
        return it.data(ROLE_ENTRY) if it is not None else None

    def _row_of(self, key):
        for r in range(self.list.count()):
            e = self._entry(r)
            if e and e.get("key") == key and not self.list.isRowHidden(r):
                return r
        return None

    def _selectable_rows(self):
        return [r for r in range(self.list.count())
                if not self.list.isRowHidden(r) and self.list.item(r).data(ROLE_KIND) == "item"]

    def _filter(self, text):
        q = text.strip().lower()
        section, shown_in = None, {}
        for r in range(self.list.count()):
            it = self.list.item(r)
            if it is self._no_match:
                continue
            kind, e = it.data(ROLE_KIND), it.data(ROLE_ENTRY)
            if kind == "header":
                section = r
                shown_in[r] = 0
                continue
            if kind == "empty":   # "none yet" placeholder: only when not searching
                hide = bool(q)
            else:
                hide = bool(q) and q not in (e["name"] + " " + e["sub"]).lower()
            self.list.setRowHidden(r, hide)
            if not hide and section is not None:
                shown_in[section] += 1
        for r, n in shown_in.items():
            self.list.setRowHidden(r, bool(q) and n == 0)
        any_hit = bool(self._selectable_rows())
        self._no_match.setData(ROLE_ENTRY, {"text": f"No experiments match “{text.strip()}”"})
        self.list.setRowHidden(self.list.row(self._no_match), any_hit or not q)
        first_header = next((r for r in range(self.list.count())
                             if not self.list.isRowHidden(r)
                             and self.list.item(r).data(ROLE_KIND) == "header"), None)
        for r in range(self.list.count()):   # no divider above the first visible section
            it = self.list.item(r)
            if it.data(ROLE_KIND) == "header":
                e = dict(it.data(ROLE_ENTRY))
                e["divider"] = r != first_header
                it.setData(ROLE_ENTRY, e)
        rows = self._selectable_rows()
        if q and rows and self._row_of(self.current_key) is None:
            self.current_key = self._entry(rows[0])["key"]
        self._fit()
        self.list.viewport().update()

    def _fit(self):
        d = self.list.itemDelegate()
        opt = QStyleOptionViewItem()
        total = sum(d.sizeHint(opt, self.list.model().index(r, 0)).height()
                    for r in range(self.list.count()) if not self.list.isRowHidden(r))
        self.list.setFixedHeight(min(total + 2, self.MAX_LIST_H))
        self.adjustSize()

    def _move(self, step):
        rows = self._selectable_rows()
        if not rows:
            return
        cur = self._row_of(self.current_key)
        if cur not in rows:
            nxt = rows[0] if step > 0 else rows[-1]
        else:
            nxt = rows[max(0, min(len(rows) - 1, rows.index(cur) + step))]
        self.current_key = self._entry(nxt)["key"]
        self.list.scrollToItem(self.list.item(nxt))
        self.list.viewport().update()

    # ── events
    def eventFilter(self, obj, ev):
        t = ev.type()
        if obj is self.search and t == QEvent.KeyPress:
            k = ev.key()
            if k in (Qt.Key_Down, Qt.Key_Up):
                self._move(1 if k == Qt.Key_Down else -1)
                return True
            if k in (Qt.Key_PageDown, Qt.Key_PageUp):
                self._move(6 if k == Qt.Key_PageDown else -6)
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                if self._row_of(self.current_key) is not None:
                    self.picked.emit(self.current_key)
                return True
            if k == Qt.Key_Escape:
                self.close()
                return True
        elif getattr(self, "list", None) is not None and obj is self.list.viewport():
            if t == QEvent.MouseMove:
                self._hover_at(ev.pos())
            elif t == QEvent.Leave:
                self.hover_row, self.hover_action = -1, None
                obj.update()
            elif t == QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton:
                self._click_at(ev.pos())
                return True
        return super().eventFilter(obj, ev)

    def _hit(self, pos):
        it = self.list.itemAt(pos)
        if it is None or it.data(ROLE_KIND) != "item":
            return -1, None, None
        row = self.list.row(it)
        e = it.data(ROLE_ENTRY)
        act = None
        if e.get("saved"):
            edit_r, del_r = _RowDelegate.action_rects(QRectF(self.list.visualItemRect(it)).adjusted(2, 2, -2, -2))
            if edit_r.contains(QPointF(pos)):
                act = "edit"
            elif del_r.contains(QPointF(pos)):
                act = "delete"
        return row, e, act

    def _hover_at(self, pos):
        row, _e, act = self._hit(pos)
        if (row, act) != (self.hover_row, self.hover_action):
            self.hover_row, self.hover_action = row, act
            self.list.viewport().update()

    def _click_at(self, pos):
        row, e, act = self._hit(pos)
        if row < 0:
            return
        if act:
            self.action.emit(act, e["key"][1])
        else:
            self.picked.emit(e["key"])

    def hideEvent(self, event):
        self.closed.emit()
        super().hideEvent(event)

    def popup_below(self, field):
        """Show under `field` (or above it when the screen runs out)."""
        m = self.MARGIN
        self.setFixedWidth(field.width() - 2 * _ExperimentField.RING + 2 * m)
        self._fit()
        g = _ExperimentField.RING
        # panel top sits 4 px under the field's box; the window adds the
        # shadow margins (top m-6, bottom m+6) around the panel.
        top_left = field.mapToGlobal(QPoint(g - m, field.height() - g + 4 - (m - 6)))
        screen = QApplication.screenAt(field.mapToGlobal(QPoint(0, 0))) or QApplication.primaryScreen()
        avail = screen.availableGeometry()
        y = top_left.y()
        if y + self.height() - (m + 6) > avail.bottom():
            field_top = field.mapToGlobal(QPoint(0, g)).y()
            y = max(avail.top(), field_top - 4 - (self.height() - 2 * m) - (m - 6))
        self.move(top_left.x(), y)
        self.show()
        self.search.setFocus()

    def _retint(self, *_):
        self.panel.setStyleSheet(
            f"#ExpPopupPanel {{ background:{theme.POPUP}; border:1px solid {theme.POPUP_EDGE};"
            f" border-radius:12px; }}"
            f"#ExpPopupPanel QLineEdit {{ background:{theme.G_INPUT}; color:{theme.TEXT};"
            f" border:1px solid {theme.G_LINE}; border-radius:8px; padding:0 8px;"
            f" font-family:'{theme.sans_family()}'; font-size:13px; }}"
            f"#ExpPopupPanel QLineEdit:focus {{ border-color:{theme.G_ACC_LINE}; }}"
            f"#ExpPopupPanel QListWidget {{ background:transparent; border:0; outline:0; }}")


class ExperimentPicker(QWidget):
    """Right column of the start page: a "New experiment" card (opens the
    custom-experiment designer) and an "Open an experiment" card with one
    icon dropdown of every experiment — built-in tests and the ones saved by
    the user (those can also be edited or deleted, from the buttons below
    it or straight from the list).

    builtins: [(title, open_fn)]; saved_fn() -> [(name, path)];
    on_new(); on_open_saved(path); on_edit(path); on_delete(path)."""

    def __init__(self, builtins, saved_fn, on_new, on_open_saved, on_edit, on_delete,
                 parent=None):
        super().__init__(parent)
        self._builtins = list(builtins)
        self._saved_fn = saved_fn
        self._on_open_saved, self._on_edit, self._on_delete = on_open_saved, on_edit, on_delete
        self._entries = []
        self._current = None
        self._popup = None
        self._popup_closed_at = 0.0

        v = QVBoxLayout(self)
        v.setContentsMargins(48, 64, 56, 48)
        v.setSpacing(16)

        # ── New experiment: text + Create on the left, arena sketch on the right
        self.new_card = _Card(clickable=True)
        self.new_card.setFixedHeight(200)
        self.new_card.setToolTip("Design your own experiment")
        nh = QHBoxLayout(self.new_card)
        nh.setContentsMargins(0, 1, 1, 1)
        nh.setSpacing(0)
        left = QVBoxLayout()
        left.setContentsMargins(26, 24, 26, 24)
        left.setSpacing(8)
        self.new_kicker = QLabel("CUSTOM DESIGN")
        self.new_title = QLabel("New experiment")
        self.new_hint = QLabel("Draw your zones and lines, choose what to measure, "
                               "and save it under a name.")
        self.new_hint.setWordWrap(True)
        self.new_hint.setMaximumWidth(320)
        self.btn_create = QPushButton("Create")
        self.btn_create.setProperty("primary", True)
        self.btn_create.setMinimumHeight(36)
        self.btn_create.setCursor(Qt.PointingHandCursor)
        self.btn_create.clicked.connect(on_new)
        left.addWidget(self.new_kicker)
        left.addWidget(self.new_title)
        left.addWidget(self.new_hint)
        left.addStretch(1)
        left.addWidget(self.btn_create, 0, Qt.AlignLeft)
        nh.addLayout(left, 1)
        self.sketch = ArenaSketch()
        nh.addWidget(self.sketch)
        self.new_card.clicked.connect(on_new)
        v.addWidget(self.new_card)

        # ── Open an experiment
        self.open_card = _Card()
        ol = QVBoxLayout(self.open_card)
        ol.setContentsMargins(26 - _ExperimentField.RING, 22, 26 - _ExperimentField.RING, 20)
        ol.setSpacing(10)
        self.open_title = QLabel("Open an experiment")
        self.open_title.setContentsMargins(_ExperimentField.RING, 0, 0, 0)
        ol.addWidget(self.open_title)
        self.field = _ExperimentField()
        self.field.clicked.connect(self._show_popup)
        self.open_title.setBuddy(self.field)
        ol.addWidget(self.field)
        row = QHBoxLayout()
        row.setContentsMargins(_ExperimentField.RING, 0, _ExperimentField.RING, 0)
        row.setSpacing(8)
        self.btn_open = QPushButton("Open")
        self.btn_open.setProperty("primary", True)
        self.btn_open.setMinimumHeight(36)
        self.btn_open.clicked.connect(self._open)
        self.btn_edit = QPushButton("Edit design")
        self.btn_edit.setToolTip("Change this experiment's zones and measures")
        self.btn_edit.setMinimumHeight(36)
        self.btn_edit.clicked.connect(lambda: self._act(self._on_edit))
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setToolTip("Remove this saved experiment")
        self.btn_delete.setMinimumHeight(36)
        self.btn_delete.clicked.connect(lambda: self._act(self._on_delete))
        row.addWidget(self.btn_open)
        row.addStretch(1)
        row.addWidget(self.btn_edit)
        row.addWidget(self.btn_delete)
        ol.addLayout(row)
        self.open_hint = QLabel("")
        self.open_hint.setWordWrap(True)
        self.open_hint.setContentsMargins(_ExperimentField.RING, 0, 0, 0)
        ol.addWidget(self.open_hint)
        v.addWidget(self.open_card)
        v.addStretch(1)

        self._retint()
        theme.notifier.changed.connect(self._retint)
        self.reload()

    # ── data
    def reload(self, select_path=None):
        """Rebuild the list (after a save / delete)."""
        entries = [{"kind": "header", "text": "BUILT-IN TESTS", "count": len(self._builtins)}]
        for i, (title, _fn) in enumerate(self._builtins):
            ic, sub = TEST_META.get(title, ("arena", "Built-in test"))
            entries.append({"kind": "item", "key": ("builtin", i), "name": title,
                            "sub": sub, "icon": ic, "saved": False})
        saved = list(self._saved_fn())
        entries.append({"kind": "header", "text": "YOUR EXPERIMENTS", "count": len(saved),
                        "divider": True})
        if saved:
            for name, path in saved:
                entries.append({"kind": "item", "key": ("saved", path), "name": name,
                                "sub": "Your design", "icon": SAVED_ICON, "saved": True})
        else:
            entries.append({"kind": "empty", "text": "None yet — use New experiment"})
        self._entries = entries
        keys = [e["key"] for e in entries if e["kind"] == "item"]
        want = ("saved", select_path) if select_path else self._current
        self._current = want if want in keys else (keys[0] if keys else None)
        if self._popup is not None:
            self._popup.close()
        self._sync()

    def currentData(self):
        """The selected entry's key: ("builtin", index) or ("saved", path)."""
        return self._current

    def _entry(self, key):
        return next((e for e in self._entries if e.get("key") == key), None)

    def _sync(self):
        e = self._entry(self._current)
        self.field.set_entry(e)
        saved = bool(e) and e["saved"]
        self.btn_edit.setEnabled(saved)
        self.btn_delete.setEnabled(saved)
        self.btn_open.setEnabled(bool(e))
        self.open_hint.setText(
            "Your own experiment: its zones and measures are fixed; you only "
            "draw the arena for each video." if saved else
            "A built-in test with its own settings.")

    # ── popup
    def _show_popup(self):
        if self._popup is not None:
            self._popup.close()
            return
        # A click on the field while the list is open first closes the popup
        # (Qt.Popup) and then lands here — treat that click as "close".
        if time.monotonic() - self._popup_closed_at < 0.25:
            return
        pop = _ExperimentPopup(self._entries, self._current, self)
        pop.picked.connect(self._picked)
        pop.action.connect(self._popup_action)
        pop.closed.connect(self._popup_gone)
        self._popup = pop
        self.field.set_open(True)
        pop.popup_below(self.field)

    def _popup_gone(self, *_):
        self._popup = None
        self._popup_closed_at = time.monotonic()
        self.field.set_open(False)

    def _picked(self, key):
        self._current = key
        self._sync()
        if self._popup is not None:
            self._popup.close()
        self.field.setFocus()

    def _popup_action(self, which, path):
        self._current = ("saved", path)
        self._sync()
        if self._popup is not None:
            self._popup.close()
        fn = self._on_edit if which == "edit" else self._on_delete
        QTimer.singleShot(0, lambda: fn(path))

    # ── actions
    def _open(self):
        data = self._current
        if not data:
            return
        if data[0] == "builtin":
            self._builtins[data[1]][1]()
        else:
            self._on_open_saved(data[1])

    def _act(self, fn):
        data = self._current
        if data and data[0] == "saved":
            fn(data[1])

    def _retint(self, *_):
        sans = theme.sans_family()
        self.new_kicker.setFont(_font(11, mono=True, spacing=2))
        self.new_kicker.setStyleSheet(f"color:{theme.ACCENT}; background:transparent;")
        self.new_title.setStyleSheet(
            f"font-family:'{sans}'; font-weight:600; font-size:26px; color:{theme.TEXT};")
        self.open_title.setStyleSheet(
            f"font-family:'{sans}'; font-weight:600; font-size:17px; color:{theme.TEXT};")
        self.new_hint.setStyleSheet(
            f"font-family:'{sans}'; font-size:13px; color:{theme.TEXT_2};")
        self.open_hint.setStyleSheet(f"font-family:'{sans}'; font-size:12px; color:{theme.FAINT};")
        self.btn_create.setIcon(icons.icon("plus", 14, theme.ON_ACCENT))
        self.btn_edit.setIcon(icons.icon("edit", 14, theme.TEXT_2))
        self.btn_delete.setIcon(icons.icon("trash", 14, theme.TEXT_2))
        self.field.update()
        self.sketch.update()
