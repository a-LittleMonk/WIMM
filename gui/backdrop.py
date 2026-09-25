"""Aurora backdrop — the soft colour field the glass panes float over.

Painted once per (size, theme) into a cached pixmap; each paint event just
blits the dirty region, so translucent children repaint cheaply.
"""
from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPixmap, QRadialGradient
from PyQt5.QtWidgets import QWidget

from gui import theme


def paint_aurora(p, w, h, spec):
    """Paint a backdrop spec (see theme.AURORA) into a w×h area."""
    p.setRenderHint(QPainter.Antialiasing)
    p.fillRect(0, 0, w, h, QColor(spec["base"]))
    p.setPen(Qt.NoPen)
    span = max(w, h)
    for fx, fy, fr, color, alpha in theme.aurora_glows(spec):
        g = QRadialGradient(QPointF(fx * w, fy * h), fr * span)
        for stop, k in ((0.0, 1.0), (0.45, 0.35), (1.0, 0.0)):
            c = QColor(color)
            c.setAlphaF(alpha * k)
            g.setColorAt(stop, c)
        p.setBrush(g)
        p.drawRect(0, 0, w, h)


class AuroraBackdrop(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self._cache = None
        self._cache_key = None
        theme.notifier.changed.connect(self._invalidate)
        theme.notifier.aurora_changed.connect(self._invalidate)

    def _invalidate(self, *_):
        self._cache = None
        self.update()

    def _render(self):
        w, h = max(1, self.width()), max(1, self.height())
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        p = QPainter(pm)
        paint_aurora(p, w, h, theme.AURORA[theme.mode()])
        p.end()
        return pm

    def paintEvent(self, event):
        key = (self.width(), self.height(), theme.mode(), self.devicePixelRatioF(),
               repr(theme.AURORA[theme.mode()]))
        if self._cache is None or self._cache_key != key:
            self._cache = self._render()
            self._cache_key = key
        r = QRectF(event.rect())
        dpr = self._cache.devicePixelRatio()
        src = QRectF(r.x() * dpr, r.y() * dpr, r.width() * dpr, r.height() * dpr)
        p = QPainter(self)
        p.drawPixmap(r, self._cache, src)
