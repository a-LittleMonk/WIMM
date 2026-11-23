"""Accordion header of a configuration step (icon tile · title · number ·
summary line · status dot · chevron), as in the redesign's config column."""
from PyQt5.QtCore import QEvent, QObject, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QGroupBox, QWidget

from gui import icons, theme

HEADER_H = 46

# status -> (dot token, ring token or None)
_DOT = {
    "ok": ("OK", "OK_BG"),
    "warn": ("WARN", "WARN_BG"),
    "blocked": ("ERR", "ERR_BG"),
    "none": ("BORDER_2", None),
}

# status_id -> (icon, title) — overrides the parsed "Step N — Title"
STEP_META = {
    "source": ("video", "Video"),
    "animal": ("tag", "Animal"),
    "geometry": ("arena", "Arena"),
    "zones": ("zones", "Zones"),
    "scale": ("scale", "Scale"),
    "detection": ("detection", "Detection"),
    "tracking": ("tracking", "Tracking"),
    "analysis": ("analysis", "Analysis"),
}


class StepHeader(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent, icon_name="config", title="", number=0):
        super().__init__(parent)
        self.setFixedHeight(HEADER_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self._icon = icon_name
        self._title = title
        self._number = number
        self._summary = ""
        self._status = "none"
        self._open = True
        self._hover = False
        theme.notifier.changed.connect(lambda _m: self.update())

    # -- API ---------------------------------------------------------------

    def set_title(self, title):
        self._title = title
        self.update()

    def set_number(self, n):
        self._number = n
        self.update()

    def set_summary(self, text):
        if text != self._summary:
            self._summary = text
            self.update()

    def set_status(self, status):
        status = status if status in _DOT else "none"
        if status != self._status:
            self._status = status
            self.update()

    def set_open(self, on):
        self._open = bool(on)
        self.update()

    # -- events ------------------------------------------------------------
    def enterEvent(self, _e):
        self._hover = True
        self.update()

    def leaveEvent(self, _e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.pos()):
            self.clicked.emit()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if self._hover:
            p.fillRect(self.rect(), QColor(theme.HOVER))
        # icon tile
        tile = QRectF(12.5, 10.5, 25, 25)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(theme.SURFACE_2))
        p.drawRoundedRect(tile, 6, 6)
        p.drawPixmap(19, 16, icons.pixmap(self._icon, 14, theme.TEXT_2))
        # right-hand cluster: dot + chevron
        right = w - 12
        p.save()
        cx, cy = right - 6, h / 2.0
        p.translate(cx, cy)
        p.rotate(90 if self._open else 0)
        p.drawPixmap(-6, -6, icons.pixmap("chevron_r", 12, theme.FAINT))
        p.restore()
        dot_c = right - 12 - 12 - 3.5
        dtok, rtok = _DOT[self._status]
        if rtok:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(getattr(theme, rtok)))
            p.drawEllipse(QRectF(dot_c - 6.5, cy - 6.5, 13, 13))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(getattr(theme, dtok)))
        p.drawEllipse(QRectF(dot_c - 3.5, cy - 3.5, 7, 7))
        # text
        text_x = 50
        text_right = dot_c - 6.5 - 26     # keep clear of the ⓘ button
        f = QFont(self.font())
        f.setPixelSize(12)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(text_x, 8, 200, 16), Qt.AlignLeft | Qt.AlignVCenter, self._title)
        tw = p.fontMetrics().horizontalAdvance(self._title)
        if self._number:
            mf = QFont(theme.mono_family())
            mf.setPixelSize(9)
            p.setFont(mf)
            p.setPen(QColor(theme.FAINT))
            p.drawText(QRectF(text_x + tw + 6, 9, 30, 14), Qt.AlignLeft | Qt.AlignVCenter,
                       f"{int(self._number):02d}")
        if self._summary:
            mf = QFont(theme.mono_family())
            mf.setPixelSize(10)
            p.setFont(mf)
            p.setPen(QColor(theme.FAINT))
            fm = p.fontMetrics()
            avail = max(10, int(text_right - text_x))
            p.drawText(QRectF(text_x, 25, avail, 14), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(self._summary, Qt.ElideRight, avail))


class StepGroup(QGroupBox):
    """QGroupBox used as the body of an accordion card. Not really
    "checkable" (Qt would disable the header child when collapsed) — it just
    mimics the isChecked / setChecked / toggled API the step builders use."""
    toggled = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self._open = True

    def isChecked(self):
        return self._open

    def setChecked(self, on):
        on = bool(on)
        if on != self._open:
            self._open = on
            self.toggled.emit(on)

    def setCheckable(self, _on):
        pass


class HeaderPlacer(QObject):
    """Keeps a card's header pinned to the top of its QGroupBox body."""

    def __init__(self, group, header):
        super().__init__(group)
        self._g, self._h = group, header
        group.installEventFilter(self)
        self.place()

    def place(self):
        self._h.setGeometry(0, 0, self._g.width(), HEADER_H)
        self._h.raise_()

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
            self.place()
        return False
