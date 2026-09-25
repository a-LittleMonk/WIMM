"""Video canvas chrome: View button + popover (layer toggles and overlay
options) and legend. They sit in a toolbar above the video and a strip below it (never
on the picture itself), wired to the tab's existing controls. Colours follow
gui.theme; overlay swatches keep the colours drawn on the video."""
from PyQt5.QtCore import QObject, QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from gui import icons, theme
from gui.widgets_v2 import SegTabs, hline, mono_font

LAYER_COLORS = {"arena": "#A9B4C6", "zones": "#C9D1DE", "trail": "#E4D3AE",
                "heat": "#8C97A9"}


class LayerChip(QPushButton):
    def __init__(self, key, label, parent=None):
        super().__init__(label, parent)
        self._key = key
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(26)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)
        theme.notifier.changed.connect(lambda _m: self.update())

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 9 + 6 + 9 + 7 + 2, 26)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        enabled = self.isEnabled()
        if on or (self.underMouse() and enabled):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT_BG if on else theme.HOVER))
            p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 4, 4)
        # Swatch = the colour this layer is drawn in on the video.
        box = QRectF(8.5, (self.height() - 9) / 2.0, 9, 9)
        p.setPen(QPen(QColor(theme.BORDER_2), 1))
        p.setBrush(QColor(theme.VIDEO_BG))
        p.drawRoundedRect(box, 2, 2)
        if on:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(LAYER_COLORS[self._key]))
            p.drawRoundedRect(box.adjusted(2, 2, -2, -2), 1, 1)
        f = QFont(self.font())
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT if (on and enabled) else (theme.TEXT_2 if enabled else theme.DISABLED)))
        p.drawText(QRectF(22, 0, self.width() - 22, self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   self.text())


class LayerBar(QFrame):
    """Arena · Zones · Trail · Heatmap chips (shown in the View popover).
    The body marker has its own section there, not a chip."""
    LAYERS = (("arena", "Arena"), ("zones", "Zones"), ("heat", "Heatmap"))

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self.setObjectName("CanvasGroup")  # styled in theme.py
        self._tab = tab
        h = QHBoxLayout(self)
        h.setContentsMargins(2, 2, 2, 2)
        h.setSpacing(2)
        self.chips = {}
        for key, label in self.LAYERS:
            c = LayerChip(key, label)
            c.setMinimumWidth(c.sizeHint().width())  # never clip the label
            c.toggled.connect(lambda on, k=key: self._toggled(k, on))
            h.addWidget(c)
            self.chips[key] = c
        for k in ("arena", "zones"):
            self.chips[k].setChecked(True)
        self.chips["heat"].setEnabled(False)
        # Heatmap needs results; remember whether the user wants it so it
        # comes back on as soon as there is something to show.
        self.want_heat = False

    def _toggled(self, key, on):
        if key == "heat":
            self.want_heat = bool(on)
        self._tab.zone_drawer.set_layer(key, on)
        self.update()

    def refresh_enabled(self):
        has = bool(getattr(self._tab, "tracking_results", None))
        c = self.chips["heat"]
        c.setEnabled(has)
        self.set_chip("heat", has and self.want_heat)

    def set_chip(self, key, on):
        """Set a chip + its layer without touching the saved preference."""
        c = self.chips[key]
        c.blockSignals(True)
        c.setChecked(bool(on))
        c.blockSignals(False)
        c.update()
        self._tab.zone_drawer.set_layer(key, bool(on))


class ViewButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__("View", parent)
        self.setObjectName("CanvasView")  # styled in theme.py
        self.setFixedHeight(30)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(13, 13))
        self.setMinimumWidth(78)
        theme.notifier.changed.connect(lambda _m: self._render())
        self._render()

    def _render(self):
        self.setIcon(QIcon(icons.pixmap("eye", 13, theme.TEXT_2)))
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.drawPixmap(self.width() - 20, (self.height() - 9) // 2,
                     icons.pixmap("chevron_d", 9, theme.TEXT_2))


class VideoLegend(QWidget):
    """Legend strip under the video: what each overlay mark means, plus the
    run summary (scale · model · sensitivity) on the right."""

    ITEMS = (("Trajectory", "line"), ("Body marker", "ring"),
             ("Center zone", "zone"), ("Arena", "box"))

    def __init__(self, tab=None, parent=None):
        super().__init__(parent)
        self._tab = tab
        self.setObjectName("CanvasLegend")  # styled in theme.py
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._info = ""
        self.setFixedHeight(30)
        theme.notifier.changed.connect(lambda _m: self.update())

    def set_info(self, text):
        if text != self._info:
            self._info = text
            self.update()

    def _font(self):
        f = QFont(theme.sans_family())
        f.setPixelSize(10)
        return f

    def _paint_marker(self, p, c, r):
        """Legend sample of the body marker in its current shape + colour."""
        tab = self._tab
        col = QColor(getattr(tab, "_colors", {}).get("body", "#F2F4F7"))
        combo = getattr(tab, "combo_marker_shape", None)
        shape = combo.currentData() if combo is not None else "ring"
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(col, 1.4, Qt.DashLine if shape == "ring" else Qt.SolidLine))
        if shape == "dot":
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(c, r, r)
        elif shape == "cross":
            p.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()))
            p.drawLine(QPointF(c.x(), c.y() - r), QPointF(c.x(), c.y() + r))
        elif shape == "square":
            p.drawRect(QRectF(c.x() - r * 0.85, c.y() - r * 0.85, r * 1.7, r * 1.7))
        elif shape in ("diamond", "triangle"):
            pts = ([QPointF(c.x(), c.y() - r), QPointF(c.x() + r, c.y()),
                    QPointF(c.x(), c.y() + r), QPointF(c.x() - r, c.y())]
                   if shape == "diamond" else
                   [QPointF(c.x(), c.y() - r), QPointF(c.x() + r * 0.87, c.y() + r / 2),
                    QPointF(c.x() - r * 0.87, c.y() + r / 2)])
            p.drawPolygon(QPolygonF(pts))
        else:
            p.drawEllipse(c, r, r)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(self._font())
        fm = p.fontMetrics()
        x, cy = 14.0, self.height() / 2.0
        for label, kind in self.ITEMS:
            # Each sample sits on a small video-coloured tile so it shows
            # the mark as it appears on the picture, in either theme.
            tile = QRectF(x - 3, cy - 7, (16 if kind == "line" else 9) + 6, 14)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.VIDEO_BG))
            p.drawRoundedRect(tile, 3, 3)
            if kind == "line":
                p.setPen(QPen(QColor(LAYER_COLORS["trail"]), 2, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(QPointF(x, cy), QPointF(x + 16, cy))
                x += 16
            elif kind == "ring":
                self._paint_marker(p, QPointF(x + 4.5, cy), 4.2)
                x += 9
            elif kind == "zone":
                p.setPen(QPen(QColor(LAYER_COLORS["zones"]), 1, Qt.DashLine))
                p.setBrush(QColor(201, 209, 222, 26))
                p.drawRect(QRectF(x + 0.5, cy - 4.5, 9, 9))
                x += 10
            else:
                p.setPen(QPen(QColor(LAYER_COLORS["arena"]), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawRect(QRectF(x + 0.75, cy - 4.25, 8.5, 8.5))
                x += 10
            x += 9
            p.setPen(QColor(theme.TEXT_2))
            p.setBrush(Qt.NoBrush)
            p.drawText(QRectF(x, 0, fm.horizontalAdvance(label) + 2, self.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, label)
            x += fm.horizontalAdvance(label) + 18
        if self._info:
            p.setFont(mono_font(10))
            p.setPen(QColor(theme.FAINT))
            p.drawText(QRectF(x, 0, self.width() - x - 14, self.height()),
                       Qt.AlignVCenter | Qt.AlignRight, self._info)


class ViewPopover(QFrame):
    """View popover: layer toggles (arena · zones · heatmap), body
    marker (show · shape · size · colour · info tag), trail / path options,
    status markers and cell highlight. Re-parents the tab's real controls."""

    def __init__(self, tab, layers, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("ViewPop")
        self.setFixedWidth(max(300, layers.sizeHint().width() + 24))
        self._tab = tab
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(9)

        def caption(text):
            c = QLabel(text)
            c.setProperty("role", "subcaps")
            v.addWidget(c)

        def row(label, widget, stretch=True):
            g = QGridLayout()
            g.setContentsMargins(0, 0, 0, 0)
            g.setColumnMinimumWidth(0, 90)
            g.setColumnStretch(1, 1)
            lb = QLabel(label)
            theme.set_tone(lb, "text2")
            g.addWidget(lb, 0, 0)
            if stretch:
                g.addWidget(widget, 0, 1)
            else:
                g.addWidget(widget, 0, 1, Qt.AlignLeft)
            w = QWidget()
            w.setLayout(g)
            return w

        caption("LAYERS")
        v.addWidget(layers)
        v.addWidget(hline())

        caption("BODY MARKER")
        v.addWidget(row("Show", tab.combo_body_style))
        self._marker_rows = (
            row("Shape", tab.combo_marker_shape),
            row("Size", tab.spin_marker_size),
            row("Color", tab.btn_marker_color, stretch=False),
            tab.chk_marker_tag,
        )
        for w in self._marker_rows:
            v.addWidget(w)
        tab.combo_body_style.currentIndexChanged.connect(self._sync_marker_rows)
        self._sync_marker_rows()
        v.addWidget(hline())

        caption("TRAIL & PATH")
        v.addWidget(tab.chk_trail)
        # Trail length: All / 60 s / 10 s  →  spin_trail_len (frames)
        seg = SegTabs(["All", "60 s", "10 s"], current=getattr(tab, "_trail_seg_idx", 0))
        tab._trail_seg = seg

        def seg_to_spin(i):
            tab._trail_seg_idx = i
            tab._sync_trail_len()
            tab._schedule_view_save()
        seg.changed.connect(seg_to_spin)
        v.addWidget(row("Trail length", seg))
        v.addWidget(tab.chk_trail_fade)
        # Length / fade only matter while the trail is shown.
        self._trail_rows = (seg.parentWidget(), tab.chk_trail_fade)
        tab.chk_trail.toggled.connect(self._sync_trail_rows)
        self._sync_trail_rows()
        v.addWidget(tab.chk_ellipse)
        v.addWidget(row("Smooth path", tab.spin_smooth))
        v.addWidget(hline())

        caption("STATUS MARKERS")
        st = QHBoxLayout()
        st.setSpacing(12)
        for name, col in (("Corrected", "#E8C547"), ("Interpolated", "#D36BA6")):
            chip = QLabel(f"<span style='color:{col}'>■</span>&nbsp;{name}")
            theme.set_tone(chip, "text2", "font-size:11px;")
            st.addWidget(chip)
        st.addStretch()
        sw = QWidget()
        sw.setLayout(st)
        v.addWidget(sw)
        if hasattr(tab, "_build_cell_highlight_controls"):
            v.addWidget(hline())
            caption("CELL HIGHLIGHT")
            v.addWidget(tab._build_cell_highlight_controls())
        self.adjustSize()

    def _sync_trail_rows(self, *_):
        on = self._tab.chk_trail.isChecked()
        for w in self._trail_rows:
            w.setEnabled(on)

    def _sync_marker_rows(self, *_):
        """Shape / size / colour / tag only matter while a marker is shown."""
        on = self._tab.combo_body_style.currentData() != "off"
        for w in self._marker_rows:
            w.setEnabled(on)

    def show_below(self, anchor):
        self.adjustSize()
        g = anchor.mapToGlobal(anchor.rect().bottomRight())
        self.move(g.x() - self.width(), g.y() + 6)
        self.show()


class CanvasChrome(QObject):
    """Owns the canvas controls: toolbar above the video, legend below."""

    def __init__(self, tab):
        super().__init__(tab)
        self._tab = tab
        zd = tab.zone_drawer
        self.bar = QWidget()
        self.bar.setObjectName("CanvasBar")  # styled in theme.py
        self.bar.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(self.bar)
        h.setContentsMargins(10, 6, 10, 6)
        h.setSpacing(8)
        # Layer toggles live inside the View popover (built on first open);
        # the bar keeps just the View button.
        self.layers = LayerBar(tab)
        self.view_btn = ViewButton()
        self.view_btn.clicked.connect(self._open_view)
        h.addStretch(1)
        h.addWidget(self.view_btn)
        self.legend = VideoLegend(tab)
        self._popover = None
        # Insert around the video in its own layout: bar above, legend below.
        lay = zd.parentWidget().layout()
        i = lay.indexOf(zd)
        lay.insertWidget(i, self.bar)
        lay.insertWidget(i + 2, self.legend)

    def _open_view(self):
        if self._popover is None:
            self._popover = ViewPopover(self._tab, self.layers)
        self._popover.show_below(self.view_btn)

    def refresh(self):
        self.layers.refresh_enabled()


def attach_canvas_chrome(tab):
    tab._chrome = CanvasChrome(tab)
    tab._video_legend = tab._chrome.legend
    return tab._chrome
