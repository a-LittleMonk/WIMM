"""Reusable building blocks of the Mice Tracker redesign (v2).

Everything here is theme-aware: colours come from `gui.theme` at paint /
render time and the icon-bearing widgets re-render on `theme.notifier`.
"""
from PyQt5.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QButtonGroup, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from gui import icons, theme


# CSS-style weights → Qt5's 0..99 scale
_QT_WEIGHT = {300: 25, 400: 50, 500: 57, 600: 63, 700: 75}


def mono_font(px=11, weight=None):
    f = QFont(theme.mono_family())
    f.setPixelSize(px)
    if weight is not None:
        f.setWeight(_QT_WEIGHT.get(int(weight), min(99, max(0, int(weight)))))
    return f


def prop(widget, **props):
    """Set dynamic properties consumed by the global stylesheet (and repolish
    when the widget is already shown)."""
    for k, v in props.items():
        widget.setProperty(k, v)
    if widget.isVisible():
        st = widget.style()
        st.unpolish(widget)
        st.polish(widget)
    return widget


def repolish(widget):
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)
    widget.update()


class ElidingLabel(QLabel):
    """QLabel that elides its text in the middle when too narrow."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)

    def setText(self, text):
        self._full = text or ""
        self._update_elided()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_elided()

    def _update_elided(self):
        fm = self.fontMetrics()
        elided = fm.elidedText(self._full, Qt.ElideMiddle, max(0, self.width()))
        super().setText(elided)
        self.setToolTip(self._full)


class IconButton(QToolButton):
    """Flat square icon button. `tone` / `hover_tone` are theme token names
    (e.g. "FAINT", "TEXT", "ACCENT", "ERR"); `variant` = "" | "danger" |
    "border" (adds the control border)."""

    def __init__(self, name, size=14, tone="FAINT", hover_tone="TEXT", tip="",
                 box=26, variant="", parent=None):
        super().__init__(parent)
        self._name, self._size = name, size
        self._tone, self._hover_tone = tone, hover_tone
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(box, box)
        self.setIconSize(QSize(size, size))
        self.setFocusPolicy(Qt.NoFocus)
        self.setProperty("ibtn", variant or "true")
        self._render()
        theme.notifier.changed.connect(self._render)

    def set_icon_name(self, name):
        self._name = name
        self._render()

    def set_compact(self, on):
        """Icon-only (label kept as tooltip) — used when space is tight."""
        on = bool(on)
        if on == getattr(self, "_compact", False):
            return
        self._compact = on
        if on:
            self._full_text = self.text()
            if not self.toolTip():
                self.setToolTip(self._full_text)
            self.setText("")
        else:
            self.setText(getattr(self, "_full_text", ""))
        self.updateGeometry()

    def _render(self, *_):
        from PyQt5.QtGui import QIcon
        ic = QIcon()
        ic.addPixmap(icons.pixmap(self._name, self._size, getattr(theme, self._tone)),
                     QIcon.Normal)
        ic.addPixmap(icons.pixmap(self._name, self._size, getattr(theme, self._hover_tone)),
                     QIcon.Active)
        ic.addPixmap(icons.pixmap(self._name, self._size, theme.DISABLED), QIcon.Disabled)
        self.setIcon(ic)


class IconLabel(QLabel):
    """Non-interactive themed icon."""

    def __init__(self, name, size=14, tone="TEXT_2", parent=None):
        super().__init__(parent)
        self._name, self._size, self._tone = name, size, tone
        self.setFixedSize(size, size)
        self._render()
        theme.notifier.changed.connect(self._render)

    def _render(self, *_):
        self.setPixmap(icons.pixmap(self._name, self._size, getattr(theme, self._tone)))


class IconTextButton(QPushButton):
    """Bordered button with a leading icon (e.g. "+ Add", "Apply to…")."""

    def __init__(self, name, text, size=12, tone="TEXT", height=26, primary=False,
                 parent=None):
        super().__init__(text, parent)
        self._name, self._size = name, size
        self._tone = "ON_ACCENT" if primary else tone
        self.setFixedHeight(height)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(size, size))
        if primary:
            self.setProperty("primary", True)
        self._render()
        theme.notifier.changed.connect(self._render)

    def set_compact(self, on):
        """Icon-only (label kept as tooltip) — used when space is tight."""
        on = bool(on)
        if on == getattr(self, "_compact", False):
            return
        self._compact = on
        if on:
            self._full_text = self.text()
            if not self.toolTip():
                self.setToolTip(self._full_text)
            self.setText("")
        else:
            self.setText(getattr(self, "_full_text", ""))
        self.updateGeometry()

    def _render(self, *_):
        from PyQt5.QtGui import QIcon
        ic = QIcon()
        ic.addPixmap(icons.pixmap(self._name, self._size, getattr(theme, self._tone)),
                     QIcon.Normal)
        ic.addPixmap(icons.pixmap(self._name, self._size, theme.DISABLED), QIcon.Disabled)
        self.setIcon(ic)


class SwitchBox(QCheckBox):
    """`label ············ (switch)` row — drop-in QCheckBox replacement."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.hint = ""          # optional key-hint chip after the label ("D")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(24)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self.text()) + 30 + 12, 24)

    def minimumSizeHint(self):
        return QSize(60, 24)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        enabled = self.isEnabled()
        w, h = self.width(), self.height()
        # label
        p.setPen(QColor(theme.TEXT if enabled else theme.DISABLED))
        p.setFont(self.font())
        text_rect = QRectF(0, 0, max(0, w - 30 - 10), h)
        hint_w = 0
        if self.hint:
            hint_w = QFontMetricsF(mono_font(9)).horizontalAdvance(self.hint) + 12
        avail = max(0, int(text_rect.width() - (hint_w + 6 if hint_w else 0)))
        elided = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, avail)
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, elided)
        if self.hint:
            tx = self.fontMetrics().horizontalAdvance(elided) + 6
            cr = QRectF(tx, (h - 15) / 2.0, hint_w, 15)
            p.setPen(QPen(QColor(theme.BORDER), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(cr.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
            p.setPen(QColor(theme.FAINT))
            p.setFont(mono_font(9))
            p.drawText(cr, Qt.AlignCenter, self.hint)
            p.setFont(self.font())
            p.setPen(QColor(theme.TEXT if enabled else theme.DISABLED))
        # track
        on = self.isChecked()
        tr = QRectF(w - 30, (h - 18) / 2.0, 30, 18)
        track = QColor(theme.ACCENT if on else theme.SCROLL)
        if not enabled:
            track.setAlphaF(0.45)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(tr, 9, 9)
        # knob
        kx = tr.left() + (14 if on else 2)
        p.setBrush(QColor("#FFFFFF" if enabled else "#EEEEEE"))
        p.drawEllipse(QRectF(kx, tr.top() + 2, 14, 14))
        if self.hasFocus():
            p.setPen(QPen(QColor(theme.ACCENT_LINE), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 4, 4)


class KeyHint(QLabel):
    """Tiny bordered mono key label ("N", "⌃K", "D")."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setProperty("role", "keyhint")
        self.setAlignment(Qt.AlignCenter)


class ValueEdit(QLineEdit):
    """The number beside a slider: shows `fmt(slider value)`, and you can
    click it and type a value (Enter or clicking away applies, Esc undoes).
    `to_slider` turns the typed number into the slider's own units
    (e.g. 1.2 -> 120 for a ×-scaled slider); out-of-range values clamp."""

    def __init__(self, slider, fmt, to_slider=lambda n: n, role="slidervalue",
                 parent=None):
        super().__init__(parent)
        self._slider, self._fmt, self._to = slider, fmt, to_slider
        self.setProperty("role", role)
        self.setFrame(False)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setToolTip("Click and type a value, then press Enter")
        slider.valueChanged.connect(self.show_value)
        self.editingFinished.connect(self._apply)
        self.show_value(slider.value())

    def show_value(self, v):
        if not self.hasFocus():
            self.setText(self._fmt(v))

    def _apply(self):
        import re
        text = self.text().strip().lower().replace(",", ".")
        m = re.search(r"[-+]?\d*\.?\d+", text)
        s = self._slider
        if m:
            v = int(round(self._to(float(m.group()))))
            s.setValue(max(s.minimum(), min(s.maximum(), v)))
        elif text.startswith("off"):
            s.setValue(s.minimum())
        self.setText(self._fmt(s.value()))
        self.clearFocus()

    def focusInEvent(self, e):
        super().focusInEvent(e)
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, self.selectAll)     # typing replaces the number

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            # Restore first: leaving the box applies whatever text it holds.
            self.setText(self._fmt(self._slider.value()))
            self.clearFocus()
            return
        super().keyPressEvent(e)


class CountPill(QLabel):
    def __init__(self, text="0", parent=None):
        super().__init__(text, parent)
        self.setProperty("role", "countpill")
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(18)  # a pill, not a column: never stretch with the header
        self.setMinimumWidth(22)


def caps_label(text):
    """Mono uppercase section caption (QUEUE / CONFIGURATION / ...)."""
    lbl = QLabel(text.upper())
    lbl.setProperty("role", "caps")
    return lbl


class PaneHeader(QWidget):
    """40 px pane header: icon · CAPS TITLE · [pill] · stretch · right widgets."""

    def __init__(self, icon_name, title, parent=None):
        super().__init__(parent)
        self.setObjectName("PaneHeader")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(42)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(14, 0, 10, 0)
        self._lay.setSpacing(8)
        self._lay.addWidget(IconLabel(icon_name, 14, "TEXT_2"))
        self._lay.addWidget(caps_label(title))
        self._stretch_added = False

    # Report the real (fixed) height: a dock panel sizes its title area from
    # sizeHint(), and the layout's natural ~26 px would let the panel body
    # slide up underneath the header.
    def sizeHint(self):
        s = super().sizeHint()
        return QSize(s.width(), self.maximumHeight())

    def minimumSizeHint(self):
        s = super().minimumSizeHint()
        return QSize(s.width(), self.maximumHeight())

    def add_left(self, widget):
        self._lay.addWidget(widget, 0, Qt.AlignVCenter)
        return widget

    def set_compact(self, on):
        """Narrow mode: text buttons in this header shrink to icons."""
        for b in self.findChildren(IconTextButton):
            b.set_compact(on)

    def add_right(self, widget):
        if not self._stretch_added:
            self._lay.addStretch(1)
            self._stretch_added = True
        self._lay.addWidget(widget, 0, Qt.AlignVCenter)
        return widget


def hline():
    f = QFrame()
    f.setProperty("role", "hline")
    f.setFixedHeight(1)
    return f


# ── form helpers ───────────────────────────────────────────────────────────
def form_row(label, widget, label_w=92, tip=None, min_h=26):
    """`label | widget` row of a config card (92 px label column)."""
    row = QWidget()
    g = QGridLayout(row)
    g.setContentsMargins(0, 0, 0, 0)
    g.setHorizontalSpacing(8)
    g.setColumnMinimumWidth(0, label_w)
    g.setColumnStretch(1, 1)
    lb = QLabel(label)
    theme.set_tone(lb, "text2")
    g.addWidget(lb, 0, 0, Qt.AlignVCenter)
    if isinstance(widget, QWidget):
        g.addWidget(widget, 0, 1, Qt.AlignVCenter)
    else:
        g.addLayout(widget, 0, 1)
    row.setMinimumHeight(min_h)
    if tip:
        row.setToolTip(tip)
    return row


def field(label, widget):
    """Small caption above an input (used in 2-column grids)."""
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(4)
    lb = QLabel(label)
    theme.set_tone(lb, "text2", "font-size:10.5px;")
    v.addWidget(lb)
    v.addWidget(widget)
    return box


def link_button(text, tip=""):
    """Flat accent text button (Save / Delete / Import… / Export…)."""
    b = QPushButton(text)
    b.setProperty("link", True)
    b.setCursor(Qt.PointingHandCursor)
    b.setFixedHeight(22)
    if tip:
        b.setToolTip(tip)
    return b


class SegTabs(QFrame):
    """Inline segmented selector (Auto · cage | Manual line | None (px))."""
    changed = pyqtSignal(int)

    def __init__(self, labels, current=0, parent=None):
        super().__init__(parent)
        self.setObjectName("SegTabs")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self._btns = []
        for i, text in enumerate(labels):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.clicked.connect(lambda _=False, k=i: self.set_index(k, emit=True))
            lay.addWidget(b)
            self._btns.append(b)
        self.set_index(current, emit=False)

    def index(self):
        for i, b in enumerate(self._btns):
            if b.isChecked():
                return i
        return 0

    def set_index(self, i, emit=False):
        for k, b in enumerate(self._btns):
            b.setChecked(k == i)
        if emit:
            self.changed.emit(i)


class ToggleTile(QPushButton):
    """40 px checkable tile with a leading icon (Center + periphery / Grid 4×4)."""

    def __init__(self, icon_name, text, size=16, parent=None):
        super().__init__(text, parent)
        self._name, self._size = icon_name, size
        self.setCheckable(True)
        self.setProperty("tile", True)
        self.setFixedHeight(40)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(size, size))
        self.toggled.connect(lambda _c: self._render())
        theme.notifier.changed.connect(self._render)
        self._render()

    def _render(self, *_):
        from PyQt5.QtGui import QIcon
        col = theme.ACCENT if self.isChecked() else theme.TEXT_2
        self.setIcon(QIcon(icons.pixmap(self._name, self._size, col)))


class ColorButtons(QWidget):
    """Arena / Center / Grid as real buttons, each with a swatch of the
    colour that zone is drawn in. Clicking one emits `picked(key)`."""
    picked = pyqtSignal(str)

    def __init__(self, get_colors, items, parent=None):
        super().__init__(parent)
        self._get, self._buttons = get_colors, {}
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        for key, lbl in items:
            b = QPushButton(lbl)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(26)
            b.setIconSize(QSize(12, 12))
            b.setToolTip(f"Change the color the {lbl.lower()} is drawn in")
            b.clicked.connect(lambda _=False, k=key: self.picked.emit(k))
            h.addWidget(b)
            self._buttons[key] = b
        h.addStretch(1)
        theme.notifier.changed.connect(lambda _m: self.refresh())
        self.refresh()

    def refresh(self):
        """Repaint the swatches from the current colours."""
        colors = self._get() or {}
        dpr = self.devicePixelRatioF() or 1.0
        for key, b in self._buttons.items():
            pm = QPixmap(int(12 * dpr), int(12 * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(QPen(QColor(theme.BORDER), 1))
            p.setBrush(QColor(colors.get(key, "#888888")))
            p.drawRoundedRect(QRectF(0.5, 0.5, 11, 11), 3, 3)
            p.end()
            b.setIcon(QIcon(pm))

    def update(self):
        self.refresh()
        super().update()


class ArenaModeButton(QPushButton):
    """Select-like menu button. Strips the legacy trailing "▾" from setText
    (the arrow is drawn by the stylesheet) and lets follower widgets
    (Redraw / Clear) mirror its enabled state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ArenaMode")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(28)
        self.setCursor(Qt.PointingHandCursor)
        self._followers = []

    def follow(self, widget):
        self._followers.append(widget)

    def setText(self, text):
        super().setText(str(text).replace(" \u25be", "").replace("\u25be", "").strip())

    def setEnabled(self, on):
        super().setEnabled(on)
        for w in self._followers:
            w.setEnabled(on)


class KeyedButton(QPushButton):
    """Bordered action button: [lead] text [KEY] (Next miss · N, Corrections… · ⌃K)."""

    def __init__(self, text, key="", lead=None, height=30, parent=None):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 0, 10, 0)
        h.setSpacing(7)
        self._lead = None
        if lead == "dot":
            d = QLabel()
            d.setFixedSize(7, 7)
            d.setObjectName("ErrDot")
            h.addWidget(d)
            self._lead = d
        elif lead:
            ic = IconLabel(lead, 12, "TEXT_2")
            h.addWidget(ic)
            self._lead = ic
        self._text = QLabel(text)
        self._text.setStyleSheet("font-size: 11.5px; background: transparent;")
        h.addWidget(self._text)
        self._key = None
        if key:
            self._key = KeyHint(key)
            h.addWidget(self._key)
        for w in self.findChildren(QLabel):
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def sizeHint(self):
        return QSize(self.layout().sizeHint().width(), self.height())

    def minimumSizeHint(self):
        return self.sizeHint()

    def setEnabled(self, on):
        super().setEnabled(on)
        self._text.setEnabled(on)


class LayoutButton(QPushButton):
    """QPushButton whose size hint comes from its child layout (rich content)."""

    def sizeHint(self):
        lay = self.layout()
        if lay is None:
            return super().sizeHint()
        h = lay.sizeHint()
        return QSize(h.width(), h.height())

    def minimumSizeHint(self):
        return self.sizeHint()
