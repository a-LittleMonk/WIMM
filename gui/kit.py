"""Instrument control kit — scientific-style controls.

  LampToggle     on/off toggle drawn as an indicator lamp + ON/OFF readout
  ScaleSlider    calibrated slider: ticks, min/mid/max labels, notch handle
  MeasureField   numeric well: − value unit +, tabular mono digits
  ScaleControl   ScaleSlider + MeasureField kept in sync

Colours come from gui.theme tokens at paint time, so theme switches only
need a repaint. Buttons / text fields / combos are styled in theme._kit_qss.
"""
from PyQt5.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt5.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QDoubleSpinBox, QFrame, QHBoxLayout,
    QSlider, QToolButton, QVBoxLayout, QWidget,
)

from gui import theme


def _mono(px):
    f = QFont(theme.mono_family())
    f.setPixelSize(px)
    f.setStyleHint(QFont.Monospace)
    return f


def _sans(px):
    f = QFont(theme.sans_family())
    f.setPixelSize(px)
    return f


# ── Lamp toggle ────────────────────────────────────────────────────────────
class LampToggle(QAbstractButton):
    """Checkable toggle: a recessed well holding a square indicator lamp and
    an ON / OFF readout, followed by an optional label."""
    WELL_W, H = 58, 24

    def __init__(self, text="", checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_Hover, True)
        theme.notifier.changed.connect(lambda _m: self.update())

    def sizeHint(self):
        w = self.WELL_W
        if self.text():
            w += 8 + QFontMetrics(_sans(12)).horizontalAdvance(self.text())
        return QSize(w, self.H)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on, en = self.isChecked(), self.isEnabled()
        well = QRectF(0.5, 0.5, self.WELL_W - 1, self.H - 1)
        edge = theme.ACCENT if self.hasFocus() else (theme.FAINT if self.underMouse() and en else theme.BORDER_2)
        p.setPen(QPen(QColor(edge), 1))
        p.setBrush(QColor(theme.INPUT))
        p.drawRoundedRect(well, 4, 4)

        lamp = QRectF(9, self.H / 2 - 4, 8, 8)
        if on and en:
            glow = QRadialGradient(lamp.center(), 9)
            c = QColor(theme.ACCENT)
            c.setAlphaF(0.45)
            glow.setColorAt(0, c)
            c.setAlphaF(0)
            glow.setColorAt(1, c)
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(lamp.center(), 9, 9)
            p.setBrush(QColor(theme.ACCENT))
        else:
            p.setBrush(QColor(theme.SURFACE_2))
        p.setPen(QPen(QColor(theme.ACCENT if on and en else theme.BORDER_2), 1))
        p.drawRoundedRect(lamp, 1.5, 1.5)

        p.setFont(_mono(10))
        p.setPen(QColor(theme.TEXT if on and en else theme.FAINT))
        p.drawText(QRectF(24, 0, self.WELL_W - 28, self.H), Qt.AlignVCenter | Qt.AlignLeft,
                   "ON" if on else "OFF")

        if self.text():
            p.setFont(_sans(12))
            p.setPen(QColor(theme.TEXT if en else theme.DISABLED))
            p.drawText(QRectF(self.WELL_W + 8, 0, self.width() - self.WELL_W - 8, self.H),
                       Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()


# ── Calibrated slider ──────────────────────────────────────────────────────
class ScaleSlider(QSlider):
    """Horizontal slider drawn as a calibrated scale. `major` / `minor` are
    tick spacings in value units; labels at min, midpoint and max."""
    PAD = 7          # keeps the notch inside the widget at the ends
    TRACK_Y = 9

    def __init__(self, minimum=0, maximum=100, major=None, minor=None, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setRange(minimum, maximum)
        span = maximum - minimum
        self._major = major or max(1, span // 4)
        self._minor = minor or max(1, self._major // 5)
        self.setFixedHeight(38)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        theme.notifier.changed.connect(lambda _m: self.update())

    def _x(self, v):
        span = max(1, self.maximum() - self.minimum())
        return self.PAD + (v - self.minimum()) / span * (self.width() - 2 * self.PAD)

    def _value_at(self, x):
        frac = (x - self.PAD) / max(1, self.width() - 2 * self.PAD)
        frac = min(1.0, max(0.0, frac))
        return round(self.minimum() + frac * (self.maximum() - self.minimum()))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.isEnabled():
            self.setSliderDown(True)
            self.setValue(self._value_at(e.x()))
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.isSliderDown():
            self.setValue(self._value_at(e.x()))
            e.accept()

    def mouseReleaseEvent(self, e):
        if self.isSliderDown():
            self.setSliderDown(False)
            e.accept()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        en = self.isEnabled()
        acc = QColor(theme.ACCENT if en else theme.DISABLED)
        y = self.TRACK_Y
        x0, x1, xv = self._x(self.minimum()), self._x(self.maximum()), self._x(self.value())

        # track: full hairline + accent fill up to the value
        p.setPen(QPen(QColor(theme.BORDER_2), 2, cap=Qt.FlatCap))
        p.drawLine(QPointF(x0, y), QPointF(x1, y))
        p.setPen(QPen(acc, 2, cap=Qt.FlatCap))
        p.drawLine(QPointF(x0, y), QPointF(xv, y))

        # ticks
        tick = QColor(theme.FAINT)
        lo, hi = self.minimum(), self.maximum()
        v = lo
        while v <= hi:
            major = (v - lo) % self._major == 0
            p.setPen(QPen(tick, 1))
            p.drawLine(QPointF(self._x(v), y + 4), QPointF(self._x(v), y + (10 if major else 7)))
            v += self._minor

        # labels: min, mid, max
        p.setFont(_mono(9))
        p.setPen(QColor(theme.FAINT))
        mid = (lo + hi) / 2
        mid_txt = f"{mid:g}"
        ly = y + 12
        p.drawText(QRectF(x0 - 2, ly, 60, 14), Qt.AlignLeft | Qt.AlignTop, f"{lo}")
        p.drawText(QRectF(self._x(mid) - 30, ly, 60, 14), Qt.AlignHCenter | Qt.AlignTop, mid_txt)
        p.drawText(QRectF(x1 - 58, ly, 60, 14), Qt.AlignRight | Qt.AlignTop, f"{hi}")

        # notch handle: cursor line through the track with a cap
        hot = self.isSliderDown() or (self.underMouse() and en)
        p.setPen(QPen(acc, 2 if hot else 1.6, cap=Qt.FlatCap))
        p.drawLine(QPointF(xv, y - 6), QPointF(xv, y + 10))
        cap = QPainterPath()
        w = 5 if hot else 4
        cap.moveTo(xv - w, y - 9)
        cap.lineTo(xv + w, y - 9)
        cap.lineTo(xv, y - 3)
        cap.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(acc)
        p.drawPath(cap)
        if self.hasFocus():
            p.setPen(QPen(QColor(theme.ACCENT), 1, Qt.DotLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1))
        p.end()


# ── Measurement field ──────────────────────────────────────────────────────
class MeasureField(QFrame):
    """Numeric input well: [ − | 12.50 cm | + ]. Right-aligned tabular mono
    digits; unit shown faintly. Use set_error("reason") to flag a bad value."""
    valueChanged = pyqtSignal(float)

    def __init__(self, value=0.0, minimum=0.0, maximum=100.0, step=1.0,
                 decimals=0, unit="", parent=None):
        super().__init__(parent)
        self.setObjectName("MeasureField")
        self.setFixedHeight(28)
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        self.btn_minus = QToolButton()
        self.btn_minus.setText("−")
        self.btn_plus = QToolButton()
        self.btn_plus.setText("+")
        for b in (self.btn_minus, self.btn_plus):
            b.setObjectName("MeasureStep")
            b.setFixedSize(24, 26)
            b.setAutoRepeat(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
        self.spin = QDoubleSpinBox()
        self.spin.setObjectName("MeasureSpin")
        self.spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.spin.setDecimals(decimals)
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(step)
        self.spin.setValue(value)
        self.spin.setFont(_mono(12))
        if unit:
            self.spin.setSuffix(f" {unit}")
        self.btn_minus.clicked.connect(self.spin.stepDown)
        self.btn_plus.clicked.connect(self.spin.stepUp)
        self.spin.valueChanged.connect(self.valueChanged)
        self.spin.installEventFilter(self)
        lay.addWidget(self.btn_minus)
        lay.addWidget(self.spin, 1)
        lay.addWidget(self.btn_plus)

    def value(self):
        return self.spin.value()

    def setValue(self, v):
        self.spin.setValue(v)

    def set_error(self, reason=""):
        self._set_prop("invalid", bool(reason))
        self.setToolTip(reason)

    def _set_prop(self, name, on):
        if self.property(name) != on:
            self.setProperty(name, on)
            self.style().unpolish(self)
            self.style().polish(self)

    def eventFilter(self, obj, ev):
        if obj is self.spin and ev.type() in (ev.FocusIn, ev.FocusOut):
            self._set_prop("focused", ev.type() == ev.FocusIn)
        return False


class ScaleControl(QWidget):
    """Calibrated slider with a linked measurement field."""
    valueChanged = pyqtSignal(int)

    def __init__(self, value, minimum, maximum, unit="", major=None, minor=None, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.slider = ScaleSlider(minimum, maximum, major, minor)
        self.field = MeasureField(value, minimum, maximum, 1, 0, unit)
        self.field.setFixedWidth(104)
        self.slider.setValue(value)
        self.slider.valueChanged.connect(lambda v: self.field.setValue(v))
        self.field.valueChanged.connect(lambda v: self.slider.setValue(int(round(v))))
        self.slider.valueChanged.connect(self.valueChanged)
        col = QVBoxLayout()
        col.setContentsMargins(0, 2, 0, 0)
        col.addWidget(self.slider)
        lay.addLayout(col, 1)
        lay.addWidget(self.field, 0, Qt.AlignTop)

    def value(self):
        return self.slider.value()
