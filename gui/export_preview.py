"""Export preview — shows a graph exactly as the export writes it.

The Output → Graphs panel draws graphs in the app's light / dark colours, so
it is hard to tell what the saved file will look like. This popup renders
the graph through the same code path as the SVG / PDF / PNG export (export
preset, light palette, white or transparent background, same dpi and tight
crop) and shows that picture untouched. A transparent background is shown
over a checkerboard, the way image editors show it.
"""
from PyQt5.QtCore import QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from gui import theme


class _PreviewCanvas(QWidget):
    """Paints the exported picture: fitted to the window or at 100 %."""

    PAD = 18
    CHECK = 10   # checkerboard square size (px)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix = None
        self._transparent = False
        self._fit = True
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_picture(self, pix, transparent):
        self._pix = pix
        self._transparent = transparent
        self._update_size()
        self.update()

    def set_fit(self, fit):
        self._fit = fit
        self._update_size()
        self.update()

    def _logical_size(self):
        if self._pix is None or self._pix.isNull():
            return QSize(0, 0)
        dpr = self._pix.devicePixelRatio() or 1.0
        return QSize(round(self._pix.width() / dpr), round(self._pix.height() / dpr))

    def _update_size(self):
        if self._fit or self._pix is None:
            self.setMinimumSize(200, 200)
        else:
            s = self._logical_size()
            self.setMinimumSize(s.width() + 2 * self.PAD, s.height() + 2 * self.PAD)
        self.updateGeometry()

    def _target_rect(self):
        s = self._logical_size()
        if s.isEmpty():
            return QRectF()
        avail_w = max(1, self.width() - 2 * self.PAD)
        avail_h = max(1, self.height() - 2 * self.PAD)
        if self._fit:
            k = min(avail_w / s.width(), avail_h / s.height())
        else:
            k = 1.0
        w, h = s.width() * k, s.height() * k
        return QRectF((self.width() - w) / 2.0, (self.height() - h) / 2.0, w, h)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#5E6066"))   # neutral, theme independent
        r = self._target_rect()
        if r.isEmpty():
            p.setPen(QColor("#E6E6E6"))
            p.drawText(self.rect(), Qt.AlignCenter, "Nothing to preview")
            return
        if self._transparent:
            p.save()
            p.setClipRect(r)
            light, dark = QColor("#FFFFFF"), QColor("#D9D9D9")
            n = self.CHECK
            y = int(r.top())
            row = 0
            while y < r.bottom():
                x = int(r.left())
                col = row % 2
                while x < r.right():
                    p.fillRect(x, y, n, n, light if col % 2 == 0 else dark)
                    x += n
                    col += 1
                y += n
                row += 1
            p.restore()
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(r, self._pix, QRectF(self._pix.rect()))
        # Thin outline so a white picture stays visible against the frame.
        p.setPen(QColor(0, 0, 0, 90))
        p.drawRect(r.adjusted(-0.5, -0.5, 0.5, 0.5))


class ExportPreviewDialog(QDialog):
    """`host` is the experiment tab (GraphsMixin): it renders the PNG."""

    def __init__(self, host, graph_names, current, parent=None):
        super().__init__(parent or host)
        self._host = host
        self.setWindowTitle("Export preview")
        self.setModal(True)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("Graph"))
        self.combo = QComboBox()
        self.combo.addItems(graph_names)
        if current in graph_names:
            self.combo.setCurrentText(current)
        self.combo.currentTextChanged.connect(self._render)
        top.addWidget(self.combo)
        top.addStretch(1)
        from gui.redesign_widgets import SegmentedControl
        self.seg_zoom = SegmentedControl(["Fit", "100 %"], 0)
        self.seg_zoom.setToolTip("Fit the picture to the window, or show it at its real pixel size")
        self.seg_zoom.changed.connect(lambda i: self.canvas.set_fit(i == 0))
        top.addWidget(self.seg_zoom)
        v.addLayout(top)

        self.canvas = _PreviewCanvas()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.canvas)
        self.scroll.setMinimumSize(520, 420)
        v.addWidget(self.scroll, 1)

        self.info = QLabel("")
        self.info.setWordWrap(True)
        theme.set_tone(self.info, "text2", "font-size: 11px;")
        v.addWidget(self.info)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.b_save = QPushButton("Export…")
        self.b_save.setToolTip("Save this graph as SVG / PDF / PNG")
        self.b_save.clicked.connect(self._save)
        b_close = QPushButton("Close")
        b_close.clicked.connect(self.accept)
        btns.addWidget(self.b_save)
        btns.addWidget(b_close)
        v.addLayout(btns)

        scr = (host.window().screen() or QApplication.primaryScreen()).availableGeometry()
        self.resize(min(900, int(scr.width() * 0.8)), min(860, int(scr.height() * 0.85)))
        self._render(self.combo.currentText())

    def _render(self, name):
        from gui.graph_style import export_bg
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            png = self._host._render_export_png(name) if name else None
        finally:
            QApplication.restoreOverrideCursor()
        pix = QPixmap()
        if png:
            pix.loadFromData(png)
        transparent = export_bg() == "transparent"
        if pix.isNull():
            self.canvas.set_picture(None, transparent)
            self.info.setText("This graph cannot be drawn for the current data.")
            self.b_save.setEnabled(False)
            return
        # Show 1 picture pixel per physical screen pixel at "100 %".
        pix.setDevicePixelRatio(self.devicePixelRatioF() or 1.0)
        self.canvas.set_picture(pix, transparent)
        self.b_save.setEnabled(True)
        gs = getattr(self._host, "_graph_style", None)
        preset = getattr(gs, "active_preset", "") if gs is not None else ""
        if gs is not None and gs.is_modified():
            preset += " (modified)"
        dpi = getattr(self._host, "EXPORT_DPI", 200)
        bg = "transparent (shown on a checkerboard)" if transparent else "white"
        self.info.setText(
            f"Exactly as exported  ·  preset <b>{preset or 'Default'}</b>  ·  "
            f"background {bg}  ·  PNG {pix.width()} × {pix.height()} px at {dpi} dpi "
            f"(SVG / PDF look the same, at any size)")
        self.info.setTextFormat(Qt.RichText)

    def _save(self):
        name = self.combo.currentText()
        host = self._host
        if hasattr(host, "_combo_graph") and name:
            host._combo_graph.setCurrentText(name)
        host._export_current_graph_dialog()
