"""Launcher (start) screen — redesign per design_handoff_launcher/Launcher.dc.html
(section "Turn 4", variant 4a).

Two-column body: a brand column (logo, big WIMM logo, a technical
backdrop centred on the logo) on the left, a dense grid of test cards on the
right. Colours always come from `gui.theme` tokens (never hard-coded), so the
screen follows the user's palette and light/dark switch.
"""
import os

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QFontMetricsF, QImage, QLinearGradient, QPainter,
    QPen, QPixmap, QRadialGradient,
)
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from gui import theme

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


class TestCard(QFrame):
    """One launcher card — enabled (clickable, index over name) or disabled
    ("coming soon": dashed border, index + label in a row)."""

    clicked = pyqtSignal()

    def __init__(self, index_text, name_text, enabled=True, parent=None):
        super().__init__(parent)
        self._enabled_card = enabled
        self._hover = False
        self._name_px = 17
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)

        if enabled:
            lay = QVBoxLayout(self)
            lay.setContentsMargins(20, 18, 20, 18)
            lay.setSpacing(0)
            self.idx = QLabel(index_text)
            lay.addWidget(self.idx, 0, Qt.AlignLeft | Qt.AlignTop)
            lay.addStretch(1)
            self.name = QLabel(name_text)
            self.name.setWordWrap(True)
            lay.addWidget(self.name, 0, Qt.AlignLeft | Qt.AlignBottom)
        else:
            lay = QHBoxLayout(self)
            lay.setContentsMargins(20, 0, 20, 0)
            lay.setSpacing(14)
            self.idx = QLabel(index_text)
            lay.addWidget(self.idx, 0, Qt.AlignVCenter)
            self.name = QLabel(name_text)
            lay.addWidget(self.name, 0, Qt.AlignVCenter)
            lay.addStretch(1)

        self._retint()
        theme.notifier.changed.connect(self._retint)

    def set_name_size(self, px):
        self._name_px = px
        self._retint()

    def enterEvent(self, event):
        if self._enabled_card:
            self._hover = True
            self._retint()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._hover:
            self._hover = False
            self._retint()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if self._enabled_card and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def _retint(self, *_):
        self.idx.setStyleSheet(
            f"font-family:'{theme.mono_family()}'; font-size:11px; "
            f"color:{theme.FAINT}; background:transparent;"
        )
        if self._enabled_card:
            self.name.setStyleSheet(
                f"font-family:'{theme.sans_family()}'; font-weight:600; "
                f"font-size:{self._name_px}px; letter-spacing:-0.3px; "
                f"line-height:1.2; color:{theme.TEXT}; background:transparent;"
            )
            bg = theme.G_HOVER if self._hover else theme.G_PANEL
            border = theme.G_ACC_LINE if self._hover else theme.G_RIM
            top = "" if self._hover else f"border-top-color:{theme.G_HI};"
            self.setStyleSheet(
                f"TestCard {{ background:{bg}; border:1px solid {border}; "
                f"{top} border-radius:12px; }}"
            )
        else:
            self.name.setStyleSheet(
                f"font-family:'{theme.sans_family()}'; font-size:13px; "
                f"color:{theme.FAINT}; background:transparent;"
            )
            self.setStyleSheet(
                f"TestCard {{ background:{theme.G_SOFT}; "
                f"border:1px dashed {theme.G_RIM}; border-radius:12px; }}"
            )


# (row, col, colspan, name font size) for the 7 cards, in launcher order.
GRID_LAYOUT = [
    (0, 0, 3, 22), (0, 3, 3, 22),
    (1, 0, 2, 17), (1, 2, 2, 17), (1, 4, 2, 17),
    (2, 0, 3, 13), (2, 3, 3, 13),
]


class TestGrid(QWidget):
    """Right column: 6-column grid of test cards."""

    def __init__(self, tests, parent=None):
        """tests: [(index_text, name_text, enabled, callback_or_None), ...],
        one entry per GRID_LAYOUT slot, in order."""
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(48, 64, 56, 48)
        grid.setSpacing(12)
        for c in range(6):
            grid.setColumnStretch(c, 1)
        grid.setRowStretch(0, 13)
        grid.setRowStretch(1, 10)
        grid.setRowStretch(2, 0)
        grid.setRowMinimumHeight(2, 60)

        self.cards = []
        for (idx_text, name_text, enabled, cb), (row, col, span, px) in zip(tests, GRID_LAYOUT):
            card = TestCard(idx_text, name_text, enabled)
            card.set_name_size(px)
            if enabled and cb is not None:
                card.clicked.connect(cb)
            grid.addWidget(card, row, col, 1, span)
            self.cards.append(card)
