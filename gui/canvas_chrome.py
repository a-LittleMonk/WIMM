"""Chrome floating over the video canvas (redesign v2): tool rail, layer chips,
View button + popover, legend chip. Built on top of the tab's ZoneDrawer and
wired to the tab's existing controls."""
from PyQt5.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget,
)

from gui import icons, theme
from gui.widgets_v2 import SegTabs, SwitchBox, hline, mono_font

GLASS = ("QFrame#Glass { background: rgba(14,17,20,0.82); "
         "border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; }")

LAYER_COLORS = {"arena": "#A9B4C6", "zones": "#C9D1DE", "trail": "#E4D3AE",
                "marker": "#F2F4F7", "heat": "#8C97A9"}


class _ToolBtn(QToolButton):
    def __init__(self, icon_name, tip, parent=None):
        super().__init__(parent)
        self._name = icon_name
        self.setToolTip(tip)
        self.setCheckable(True)
        self.setFixedSize(30, 30)
        self.setIconSize(QSize(15, 15))
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "QToolButton { border: 0; border-radius: 5px; background: transparent; }"
            "QToolButton:hover { background: rgba(255,255,255,0.10); }"
            "QToolButton:checked { background: #E4E8EF; }"
            "QToolButton:disabled { background: transparent; }")
        self.toggled.connect(lambda _c: self._render())
        self._render()

    def _render(self):
        col = "#121826" if self.isChecked() else ("#C9D1D9" if self.isEnabled() else "#5C656E")
        self.setIcon(QIcon(icons.pixmap(self._name, 15, col)))

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.EnabledChange:
            self._render()


class ToolRail(QFrame):
    """Select / Define arena / Draw scale line / Fix position."""

    def __init__(self, tab, parent):
        super().__init__(parent)
        self.setObjectName("Glass")
        self.setStyleSheet(GLASS)
        self._tab = tab
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(2)
        self.b_select = _ToolBtn("t_select", "Select / pan")
        self.b_arena = _ToolBtn("t_arena", "Define arena — click 4 corners")
        self.b_calib = _ToolBtn("t_calib", "Draw scale line")
        self.b_fix = _ToolBtn("t_fix", "Fix position — click to override tracked point")
        self._all = (self.b_select, self.b_arena, self.b_calib, self.b_fix)
        for b in self._all:
            v.addWidget(b)
            b.clicked.connect(lambda _=False, x=b: self._picked(x))
        self.b_select.setChecked(True)
        tab.zone_drawer.mode_changed.connect(self._sync_mode)

    def _set_only(self, btn):
        for b in self._all:
            b.blockSignals(True)
            b.setChecked(b is btn)
            b.blockSignals(False)
            b._render()

    def _picked(self, btn):
        tab, zd = self._tab, self._tab.zone_drawer
        if btn is self.b_select:
            if getattr(tab, "btn_fix", None) is not None and tab.btn_fix.isChecked():
                tab.btn_fix.setChecked(False)
            zd.set_mode(zd.MODE_IDLE)
            self._set_only(self.b_select)
        elif btn is self.b_arena:
            if tab.btn_arena.isEnabled():
                tab._start_draw_arena()
            self._sync_mode(zd.mode)
        elif btn is self.b_calib:
            if tab.btn_calib.isEnabled():
                tab._start_draw_calib()
            self._sync_mode(zd.mode)
        elif btn is self.b_fix:
            if tab.btn_fix.isEnabled():
                tab.btn_fix.setChecked(not tab.btn_fix.isChecked())
            self._sync_mode(zd.mode)

    def _sync_mode(self, mode):
        zd = self._tab.zone_drawer
        if mode == zd.MODE_ARENA:
            self._set_only(self.b_arena)
        elif mode == zd.MODE_CALIB:
            self._set_only(self.b_calib)
        elif mode == zd.MODE_CORRECT:
            self._set_only(self.b_fix)
        else:
            self._set_only(self.b_select)

    def refresh_enabled(self):
        t = self._tab
        self.b_arena.setEnabled(bool(t.btn_arena.isEnabled()))
        self.b_calib.setEnabled(bool(t.btn_calib.isEnabled()))
        self.b_fix.setEnabled(bool(t.btn_fix.isEnabled()))


class LayerChip(QPushButton):
    def __init__(self, key, label, parent=None):
        super().__init__(label, parent)
        self._key = key
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(26)
        self.setFocusPolicy(Qt.NoFocus)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 9 + 6 + 9 + 7 + 2, 26)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        enabled = self.isEnabled()
        if on:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 31))
            p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 5, 5)
        elif self.underMouse() and enabled:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 18))
            p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 5, 5)
        sw = QColor(LAYER_COLORS[self._key]) if on else QColor(255, 255, 255, 46)
        p.setPen(Qt.NoPen)
        p.setBrush(sw)
        p.drawRoundedRect(QRectF(9, (self.height() - 7) / 2.0, 7, 7), 2, 2)
        f = QFont(self.font())
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(QColor("#FFFFFF") if (on and enabled) else QColor("#7E8891" if enabled else "#4B535B"))
        p.drawText(QRectF(22, 0, self.width() - 22, self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   self.text())


class LayerBar(QFrame):
    """Arena · Zones · Trail · Marker · Heatmap chips."""
    LAYERS = (("arena", "Arena"), ("zones", "Zones"), ("trail", "Trail"),
              ("marker", "Marker"), ("heat", "Heatmap"))

    def __init__(self, tab, parent):
        super().__init__(parent)
        self.setObjectName("Glass")
        self.setStyleSheet(GLASS)
        self._tab = tab
        h = QHBoxLayout(self)
        h.setContentsMargins(4, 4, 4, 4)
        h.setSpacing(2)
        self.chips = {}
        for key, label in self.LAYERS:
            c = LayerChip(key, label)
            c.toggled.connect(lambda on, k=key: self._toggled(k, on))
            h.addWidget(c)
            self.chips[key] = c
        for k in ("arena", "zones", "marker"):
            self.chips[k].setChecked(True)
        self.chips["trail"].setChecked(bool(tab.chk_trail.isChecked()))
        self.chips["heat"].setEnabled(False)
        tab.chk_trail.toggled.connect(self._trail_from_tab)

    def _trail_from_tab(self, on):
        c = self.chips["trail"]
        c.blockSignals(True)
        c.setChecked(bool(on))
        c.blockSignals(False)
        c.update()

    def _toggled(self, key, on):
        tab = self._tab
        if key == "trail":
            tab.chk_trail.setChecked(on)
        else:
            tab.zone_drawer.set_layer(key, on)
            if key == "marker":
                tab._render_current_frame()
        self.update()

    def refresh_enabled(self):
        has = bool(getattr(self._tab, "tracking_results", None))
        c = self.chips["heat"]
        c.setEnabled(has)
        if not has and c.isChecked():
            c.setChecked(False)


class ViewButton(QPushButton):
    def __init__(self, parent):
        super().__init__("View", parent)
        self.setFixedHeight(36)
        self.setCursor(Qt.PointingHandCursor)
        self.setIcon(QIcon(icons.pixmap("eye", 13, "#E6EAEE")))
        self.setIconSize(QSize(13, 13))
        self.setStyleSheet(
            "QPushButton { background: rgba(14,17,20,0.82); color: #E6EAEE; "
            "border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; "
            "padding: 0 26px 0 11px; font-size: 11px; text-align: left; }"
            "QPushButton:hover { background: rgba(30,34,38,0.92); }")
        self.setMinimumWidth(78)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.drawPixmap(self.width() - 20, (self.height() - 9) // 2,
                     icons.pixmap("chevron_d", 9, "#E6EAEE"))


class VideoLegend(QWidget):
    """Bottom-left legend chip with the run summary on the right."""

    def __init__(self, host):
        super().__init__(host)
        self._host = host
        self._info = ""
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._resize()

    def set_info(self, text):
        if text != self._info:
            self._info = text
            self._resize()
            self.update()

    ITEMS = (("Trajectory", "line"), ("Centroid", "ring"),
             ("Center zone", "zone"), ("Arena", "box"))

    def _font(self):
        f = QFont(theme.sans_family())
        f.setPixelSize(10)
        return f

    def _resize(self):
        from PyQt5.QtGui import QFontMetrics
        fm = QFontMetrics(self._font())
        w = 11
        for label, _k in self.ITEMS:
            w += 16 + 6 + fm.horizontalAdvance(label) + 14
        if self._info:
            mfm = QFontMetrics(mono_font(10))
            w += 12 + 1 + mfm.horizontalAdvance(self._info)
        else:
            w -= 14
        self.setFixedSize(int(w + 11), 30)
        self._place()

    def _place(self):
        self.move(12, max(0, self._host.height() - self.height() - 12))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 20), 1))
        p.setBrush(QColor(14, 17, 20, 210))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 8, 8)
        p.setFont(self._font())
        fm = p.fontMetrics()
        x, cy = 11.0, self.height() / 2.0
        for label, kind in self.ITEMS:
            if kind == "line":
                p.setPen(QPen(QColor("#E4D3AE"), 2, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(QPointF(x, cy), QPointF(x + 16, cy))
                x += 16
            elif kind == "ring":
                p.setPen(QPen(QColor("#F2F4F7"), 1.4))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(x + 4.5, cy), 4.2, 4.2)
                x += 9
            elif kind == "zone":
                pen = QPen(QColor("#C9D1DE"), 1, Qt.DashLine)
                p.setPen(pen)
                p.setBrush(QColor(201, 209, 222, 26))
                p.drawRect(QRectF(x + 0.5, cy - 4.5, 9, 9))
                x += 10
            else:
                p.setPen(QPen(QColor("#A9B4C6"), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawRect(QRectF(x + 0.75, cy - 4.25, 8.5, 8.5))
                x += 10
            x += 6
            p.setPen(QColor("#C9D1D9"))
            p.setBrush(Qt.NoBrush)
            p.drawText(QRectF(x, 0, fm.horizontalAdvance(label) + 2, self.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, label)
            x += fm.horizontalAdvance(label) + 14
        if self._info:
            p.setPen(QPen(QColor(255, 255, 255, 30), 1))
            p.drawLine(QPointF(x - 2, 6), QPointF(x - 2, self.height() - 6))
            p.setFont(mono_font(10))
            p.setPen(QColor("#8F99A3"))
            p.drawText(QRectF(x + 10, 0, self.width() - x - 10, self.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, self._info)


class ViewPopover(QFrame):
    """Overlay options popover (body marker · ellipse · trail · smooth ·
    status markers · cell highlight). Re-parents the tab's real controls."""

    def __init__(self, tab, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("ViewPop")
        self.setFixedWidth(282)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(9)
        cap = QLabel("OVERLAY")
        cap.setProperty("role", "subcaps")
        v.addWidget(cap)

        def row(label, widget):
            g = QGridLayout()
            g.setContentsMargins(0, 0, 0, 0)
            g.setColumnMinimumWidth(0, 90)
            g.setColumnStretch(1, 1)
            lb = QLabel(label)
            theme.set_tone(lb, "text2")
            g.addWidget(lb, 0, 0)
            g.addWidget(widget, 0, 1)
            w = QWidget()
            w.setLayout(g)
            return w

        v.addWidget(row("Body marker", tab.combo_body_style))
        v.addWidget(tab.chk_ellipse)
        # Trail length: All / 60 s / 10 s  →  spin_trail_len (frames)
        seg = SegTabs(["All", "60 s", "10 s"])
        tab._trail_seg = seg

        def seg_to_spin(i):
            fps = float(tab.fps or 30.0)
            tab.spin_trail_len.setValue((0, int(fps * 60), int(fps * 10))[i])
        seg.changed.connect(seg_to_spin)
        v.addWidget(row("Trail length", seg))
        v.addWidget(tab.chk_trail_fade)
        v.addWidget(row("Smooth path", tab.spin_smooth))
        v.addWidget(hline())
        cap2 = QLabel("STATUS MARKERS")
        cap2.setProperty("role", "subcaps")
        v.addWidget(cap2)
        st = QHBoxLayout()
        st.setSpacing(12)
        for name, col in (("Corrected", "#E8C547"), ("Interpolated", "#D36BA6"), ("Body", "#F2F4F7")):
            chip = QLabel(f"<span style='color:{col}'>■</span>&nbsp;{name}")
            theme.set_tone(chip, "text2", "font-size:11px;")
            st.addWidget(chip)
        st.addStretch()
        sw = QWidget()
        sw.setLayout(st)
        v.addWidget(sw)
        if hasattr(tab, "_build_cell_highlight_controls"):
            v.addWidget(hline())
            cap3 = QLabel("CELL HIGHLIGHT")
            cap3.setProperty("role", "subcaps")
            v.addWidget(cap3)
            v.addWidget(tab._build_cell_highlight_controls())
        if hasattr(tab, "btn_dot_colors"):
            v.addWidget(hline())
            b = QPushButton("Marker colors…")
            b.setProperty("link", True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(22)
            b.clicked.connect(tab._open_dot_colors_dialog)
            v.addWidget(b, 0, Qt.AlignLeft)
        self.adjustSize()

    def show_below(self, anchor):
        self.adjustSize()
        g = anchor.mapToGlobal(anchor.rect().bottomRight())
        self.move(g.x() - self.width(), g.y() + 6)
        self.show()


class CanvasChrome(QObject):
    """Owns the floating widgets and keeps them positioned."""

    def __init__(self, tab):
        super().__init__(tab)
        self._tab = tab
        zd = tab.zone_drawer
        self.rail = ToolRail(tab, zd)
        self.layers = LayerBar(tab, zd)
        self.view_btn = ViewButton(zd)
        self.view_btn.clicked.connect(self._open_view)
        self.legend = VideoLegend(zd)
        self._popover = None
        zd.installEventFilter(self)
        self.place()

    def _open_view(self):
        if self._popover is None:
            self._popover = ViewPopover(self._tab)
        self._popover.show_below(self.view_btn)

    def place(self):
        zd = self._tab.zone_drawer
        self.rail.adjustSize()
        self.rail.move(12, 12)
        self.layers.adjustSize()
        bw, vw = self.layers.width(), self.view_btn.width()
        total = bw + 6 + vw
        y = 44
        if zd.width() - 72 >= total:
            self.layers.move(zd.width() - 12 - total, y)
            self.view_btn.move(zd.width() - 12 - vw, y - 5)
        else:
            self.layers.move(max(66, zd.width() - 12 - bw), y)
            self.view_btn.move(zd.width() - 12 - vw, y + self.layers.height() + 6)
        self.legend._place()
        for w in (self.rail, self.layers, self.view_btn, self.legend):
            w.raise_()

    def refresh(self):
        self.rail.refresh_enabled()
        self.layers.refresh_enabled()

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Resize, QEvent.Show):
            self.place()
        return False


def attach_canvas_chrome(tab):
    tab._chrome = CanvasChrome(tab)
    tab._video_legend = tab._chrome.legend
    return tab._chrome
