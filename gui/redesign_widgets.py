"""Custom widgets from the Mice Tracker redesign (v2): segmented control,
status pill, time ruler, measurements sidebar."""
from PyQt5.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PyQt5.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSlider, QStyle, QStyleOptionSlider, QToolTip, QVBoxLayout, QWidget,
)

from gui import icons, theme
from gui.widgets_v2 import mono_font, prop


def _mono(size=11):
    return mono_font(size)


# ── Segmented control (Simple | Full, light | dark) ────────────────────────
class SegmentedControl(QFrame):
    changed = pyqtSignal(int)

    def __init__(self, labels, current=0, parent=None):
        super().__init__(parent)
        self.setObjectName("Segmented")
        self.setFixedHeight(26)
        self._btns = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.setAttribute(Qt.WA_StyledBackground, True)  # styled in theme.py
        for i, text in enumerate(labels):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setFixedHeight(24)
            b.setCursor(Qt.PointingHandCursor)
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


class ThemeToggle(SegmentedControl):
    """Light | dark switch drawn with sun / moon icons (no font glyphs)."""

    def __init__(self, current=0, parent=None):
        super().__init__(["", ""], current, parent)
        for b, name in zip(self._btns, ("sun", "moon")):
            b.setProperty("icon_name", name)
            b.setFixedWidth(38)
            b.setIconSize(QSize(15, 15))
        self.setToolTip("Light / dark theme")
        theme.notifier.changed.connect(lambda _m: self._refresh_icons())
        self.set_index(current, emit=False)

    def set_index(self, i, emit=False):
        super().set_index(i, emit=False)
        self._refresh_icons()
        if emit:
            # Paint the new position first; the app-wide restyle follows.
            self.repaint()
            self.changed.emit(i)

    def _refresh_icons(self):
        if not hasattr(self, "_btns"):
            return
        for b in self._btns:
            name = b.property("icon_name")
            if name:
                b.setIcon(icons.icon(name, 15, theme.TEXT if b.isChecked() else theme.FAINT))


# ── Status pill (header "Tracking OF_M08 · 62%") ───────────────────────────
class StatusPill(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StatusPill")  # styled in theme.py
        self.setFixedHeight(22)
        self.hide()

    def show_text(self, text):
        if text:
            self.setText("●  " + text)
            self.show()
        else:
            self.hide()


class TimeTicks(QWidget):
    """Tick ruler under the scrub slider (0, 1, 2 … min or seconds)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(16)
        self._dur = 0.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        theme.notifier.changed.connect(lambda _m: self.update())

    def set_duration(self, seconds):
        self._dur = max(0.0, float(seconds or 0.0))
        self.update()

    def paintEvent(self, _e):
        if self._dur <= 0:
            return
        p = QPainter(self)
        w = self.width() - 12          # slider handle inset
        x0 = 6
        steps = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200, 3600]
        step = next((s for s in steps if self._dur / s <= 10), steps[-1])
        use_min = step >= 60
        p.setFont(_mono(9))
        fm = p.fontMetrics()
        half = step / 2.0
        t = 0.0
        while t <= self._dur + 1e-6:
            x = x0 + w * t / self._dur
            major = abs((t / step) - round(t / step)) < 1e-6
            p.setPen(QPen(QColor(theme.BORDER_2), 1))
            p.drawLine(QPointF(x, 0), QPointF(x, 5 if major else 3))
            if major:
                val = t / 60.0 if use_min else t
                lab = f"{val:g}"
                if t + step > self._dur + 1e-6:
                    lab += " min" if use_min else " s"
                p.setPen(QColor(theme.FAINT))
                tw = fm.horizontalAdvance(lab)
                p.drawText(QPointF(min(max(0, x - tw / 2.0), self.width() - tw), 15), lab)
            t += half


# ── Measurements sidebar ────────────────────────────────────────────────────
def _prop_label(text="", role=None, tone=None, mono=None, weight=None):
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    if tone:
        theme.set_tone(lb, tone)
    if mono:
        lb.setFont(mono_font(mono, weight))
    return lb


def _caps(text):
    return _prop_label(text.upper(), role="caps")


def _repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class _Bar(QWidget):
    """Rounded progress bar (surface track with border) filled with a token."""

    def __init__(self, token, height=6, parent=None):
        super().__init__(parent)
        self.setFixedHeight(height)
        self._token = token
        self._f = 0.0
        theme.notifier.changed.connect(lambda _m: self.update())

    def set_fraction(self, f):
        self._f = max(0.0, min(1.0, f or 0.0))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        rad = self.height() / 2.0
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(theme.SURFACE_2))
        p.drawRoundedRect(r, rad, rad)
        if self._f > 0:
            p.save()
            clip = QPainterPath()
            clip.addRoundedRect(r, rad, rad)
            p.setClipPath(clip)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(getattr(theme, self._token)))
            p.drawRect(QRectF(0, 0, self.width() * self._f, self.height()))
            p.restore()


class _MiniSpeed(QWidget):
    """±30 s speed sparkline with a centre marker."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self._v = []
        self._mid = 0.5
        theme.notifier.changed.connect(lambda _m: self.update())

    def set_data(self, values, mid_frac=0.5):
        self._v = list(values or [])
        self._mid = mid_frac
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        n = len(self._v)
        if n > 1:
            vmax = max(4.0, max(self._v))
            path = QPainterPath()
            for i, v in enumerate(self._v):
                x = w * i / (n - 1)
                y = h - 4 - (h - 8) * v / vmax
                path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
            area = QPainterPath(path)
            area.lineTo(w, h)
            area.lineTo(0, h)
            area.closeSubpath()
            p.fillPath(area, QColor(theme.ACCENT_BG))
            p.setPen(QPen(QColor(theme.ACCENT), 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        x = w * self._mid
        p.setPen(QPen(QColor(theme.TEXT_2), 1))
        p.drawLine(QPointF(x, 0), QPointF(x, h))


class _HeadingDial(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self._deg = None
        theme.notifier.changed.connect(lambda _m: self.update())

    def set_degrees(self, deg):
        self._deg = deg
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(theme.BORDER_2), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(1, 1, 14, 14))
        if self._deg is None:
            return
        p.translate(8, 8)
        p.rotate(-self._deg)          # 0° = east, counter-clockwise
        path = QPainterPath()
        path.moveTo(4.5, 0)
        path.lineTo(-2.5, 2.5)
        path.lineTo(-2.5, -2.5)
        path.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.ACCENT))
        p.drawPath(path)


class _HeatMini(QWidget):
    """20×20 occupancy mini-map (viridis) with the centre-zone outline."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(104, 104)
        self._img = None
        self._center = None
        theme.notifier.changed.connect(lambda _m: self.update())

    def set_data(self, rgba_img, center_rel):
        self._img, self._center = rgba_img, center_rel
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, 104, 104)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1A1E22"))
        p.drawRoundedRect(r, 4, 4)
        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(r, 4, 4)
        p.setClipPath(clip)
        if self._img is not None:
            p.drawImage(r, self._img)
        if self._center:
            x0, y0, x1, y1 = self._center
            pen = QPen(QColor(255, 255, 255, 204), 0.8)
            pen.setDashPattern([2.5, 1.9])
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(x0 * 104, y0 * 104, (x1 - x0) * 104, (y1 - y0) * 104))
        p.restore()


class _Ramp(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(5)

    def paintEvent(self, _):
        from gui.colormaps import viridis
        p = QPainter(self)
        g = QLinearGradient(0, 0, self.width(), 0)
        for k in range(6):
            r, gg, b = viridis(k / 5.0)
            g.setColorAt(k / 5.0, QColor(int(r), int(gg), int(b)))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(QRectF(0, 0, self.width(), 5), 2, 2)


class MeasurementsPanel(QScrollArea):
    """Right sidebar: current frame, session metrics, occupancy."""

    HERO = (
        ("Distance",        ("total distance",),       "ACCENT"),
        ("Center time",     ("time in center",),       "TEXT_2"),
        ("Center entries",  ("center zone entries", "entries"), "ACCENT_LINE"),
        ("Immobility",      ("immobil",),              "FAINT"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(296)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setObjectName("Measurements")  # styled in theme.py
        body = QWidget()
        body.setObjectName("MeasBody")
        self.setWidget(body)
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self._last_session = (None, 0.0, None)
        self._last_frame = None
        self._occ = None
        self._rows = []
        self._hero_tiles = []

        # ── Current frame ────────────────────────────────────────────────
        sec1 = QWidget()
        sec1.setProperty("role", "meas-section")
        sec1.setAttribute(Qt.WA_StyledBackground, True)
        s1 = QVBoxLayout(sec1)
        s1.setContentsMargins(14, 12, 14, 14)
        s1.setSpacing(0)
        head = QHBoxLayout()
        dot = QLabel()
        dot.setFixedSize(6, 6)
        dot.setObjectName("AccentDot")
        head.addWidget(dot)
        head.addSpacing(7)
        head.addWidget(_caps("Current frame"))
        head.addStretch(1)
        self.lbl_time = _prop_label("—", role="faint", mono=11)
        head.addWidget(self.lbl_time)
        s1.addLayout(head)
        s1.addSpacing(10)

        grid_host = QFrame()
        grid_host.setObjectName("GridCells")
        gl = QGridLayout(grid_host)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(1)
        self._cur = {}

        def cell(key, caption, r, c):
            w = QWidget()
            w.setObjectName("GridCell")
            w.setAttribute(Qt.WA_StyledBackground, True)
            cv = QVBoxLayout(w)
            cv.setContentsMargins(10, 8, 10, 8)
            cv.setSpacing(3)
            cap = _prop_label(caption.upper(), role="cellcap")
            val = _prop_label("—", mono=14, weight=500)
            cv.addWidget(cap)
            if key == "heading":
                row = QHBoxLayout()
                row.setSpacing(6)
                self.dial = _HeadingDial()
                row.addWidget(self.dial)
                row.addWidget(val)
                row.addStretch(1)
                cv.addLayout(row)
            else:
                cv.addWidget(val)
            self._cur[key] = val
            self._cur[key + "_cap"] = cap
            gl.addWidget(w, r, c)
        cell("pos", "Position", 0, 0)
        cell("speed", "Speed", 0, 1)
        cell("heading", "Heading", 1, 0)
        cell("conf", "Confidence", 1, 1)
        s1.addWidget(grid_host)
        s1.addSpacing(10)

        zrow = QHBoxLayout()
        zrow.setSpacing(8)
        self.pill_zone = QLabel("—")
        self.pill_zone.setObjectName("ZonePill")
        self.pill_zone.setFixedHeight(24)
        self.lbl_moving = _prop_label("", role="faint11")
        zrow.addWidget(self.pill_zone)
        zrow.addWidget(self.lbl_moving)
        zrow.addStretch(1)
        s1.addLayout(zrow)
        s1.addSpacing(12)

        sp_head = QHBoxLayout()
        sp_head.addWidget(_prop_label("SPEED · ±30 S", role="cellcap"))
        sp_head.addStretch(1)
        self.lbl_winmax = _prop_label("", role="faint", mono=10)
        sp_head.addWidget(self.lbl_winmax)
        s1.addLayout(sp_head)
        s1.addSpacing(4)
        self.mini = _MiniSpeed()
        s1.addWidget(self.mini)
        s1.addSpacing(10)

        cum_head = QHBoxLayout()
        cum_head.addWidget(_prop_label("CUMULATIVE DISTANCE", role="cellcap"))
        cum_head.addStretch(1)
        self.lbl_cum = _prop_label("—", mono=12, weight=500)
        self.lbl_cum.setTextFormat(Qt.RichText)
        cum_head.addWidget(self.lbl_cum)
        s1.addLayout(cum_head)
        s1.addSpacing(5)
        self.bar_cum = _Bar("ACCENT", 7)
        s1.addWidget(self.bar_cum)
        v.addWidget(sec1)

        # ── Session ──────────────────────────────────────────────────────
        sec2 = QWidget()
        sec2.setProperty("role", "meas-section")
        sec2.setAttribute(Qt.WA_StyledBackground, True)
        s2 = QVBoxLayout(sec2)
        s2.setContentsMargins(14, 12, 14, 14)
        s2.setSpacing(0)
        h2 = QHBoxLayout()
        h2.addWidget(_caps("Session"))
        h2.addStretch(1)
        self.lbl_range = _prop_label("", role="faint", mono=10)
        h2.addWidget(self.lbl_range)
        s2.addLayout(h2)
        s2.addSpacing(10)
        self.hero_grid = QGridLayout()
        self.hero_grid.setContentsMargins(0, 0, 0, 0)
        self.hero_grid.setSpacing(6)
        s2.addLayout(self.hero_grid)
        s2.addSpacing(8)
        self.metrics_box = QVBoxLayout()
        self.metrics_box.setSpacing(0)
        s2.addLayout(self.metrics_box)
        self.lbl_empty = _prop_label("Run tracking to see measurements.", role="faint11")
        self.lbl_empty.setWordWrap(True)
        s2.addWidget(self.lbl_empty)
        v.addWidget(sec2)

        # ── Occupancy ────────────────────────────────────────────────────
        sec3 = QWidget()
        sec3.setProperty("role", "meas-section")
        sec3.setAttribute(Qt.WA_StyledBackground, True)
        s3 = QVBoxLayout(sec3)
        s3.setContentsMargins(14, 12, 14, 14)
        s3.setSpacing(0)
        s3.addWidget(_caps("Occupancy"))
        s3.addSpacing(10)
        occ = QHBoxLayout()
        occ.setSpacing(12)
        self.heat_mini = _HeatMini()
        occ.addWidget(self.heat_mini, 0, Qt.AlignTop)
        bars = QVBoxLayout()
        bars.setSpacing(10)
        self._occ_bars = {}
        for key, label, tok in (("center", "Center", "ACCENT"), ("mobile", "Mobile", "ACCENT"),
                                ("wall", "Wall band", "WARN")):
            col = QVBoxLayout()
            col.setSpacing(4)
            top = QHBoxLayout()
            top.addWidget(_prop_label(label, tone="text2", role=None))
            top.addStretch(1)
            val = _prop_label("—", mono=10)
            top.addWidget(val)
            col.addLayout(top)
            bar = _Bar(tok, 8)
            col.addWidget(bar)
            bars.addLayout(col)
            self._occ_bars[key] = (val, bar, col)
            for i in range(top.count()):
                w = top.itemAt(i).widget()
                if isinstance(w, QLabel) and w is not val:
                    w.setStyleSheet("font-size:10.5px;")
        bars.addStretch(1)
        occ.addLayout(bars, 1)
        s3.addLayout(occ)
        s3.addSpacing(10)
        ramp = QHBoxLayout()
        ramp.setSpacing(6)
        ramp.addWidget(_prop_label("0 s", role="faint", mono=9))
        ramp.addWidget(_Ramp(), 1)
        self.lbl_ramp = _prop_label("", role="faint", mono=9)
        ramp.addWidget(self.lbl_ramp)
        s3.addLayout(ramp)
        v.addWidget(sec3)
        v.addStretch(1)

        self.clear()
        theme.notifier.changed.connect(self._on_theme)

    def _on_theme(self, _mode):
        self.set_session(*self._last_session)
        self.set_frame(self._last_frame)
        if self._occ:
            self.set_occupancy(**self._occ)

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _split_unit(key):
        if key.endswith(")") and "(" in key:
            i = key.rfind("(")
            return key[:i].strip(), key[i + 1:-1]
        if key.startswith("%") or key.endswith("%"):
            return key.replace("%", "").strip() or key, "%"
        return key, ""

    @staticmethod
    def _find(metrics, needles):
        for n in needles:
            for k in metrics:
                if n in str(k).lower():
                    return k
        return None

    @staticmethod
    def _fmt(val):
        if isinstance(val, float):
            return f"{val:.2f}" if abs(val) < 100 else f"{val:.1f}"
        return str(val)

    def _unit_span(self, unit, px=10):
        return (f"<span style='font-size:{px}px; color:{theme.FAINT}; font-weight:400'>"
                f"&nbsp;{unit}</span>") if unit else ""

    # -- session --------------------------------------------------------
    def clear(self):
        self.set_session(None, 0.0)
        self.set_frame(None)
        self.set_occupancy(None)

    def set_session(self, metrics, duration_s, extra=None):
        self._last_session = (metrics, duration_s, extra)
        for w in self._rows:
            w.setParent(None)
            w.deleteLater()
        self._rows = []
        for w in self._hero_tiles:
            w.setParent(None)
            w.deleteLater()
        self._hero_tiles = []
        has = bool(metrics)
        self.lbl_empty.setVisible(not has)
        self.lbl_range.setText(f"0 – {duration_s:.0f} s" if has and duration_s else "")
        if not has:
            return
        used = set()
        # hero tiles ------------------------------------------------------
        tiles = []
        for label, needles, tok in self.HERO:
            k = self._find(metrics, needles)
            if k is None or k in used or not isinstance(metrics[k], (int, float)):
                continue
            used.add(k)
            val, unit = metrics[k], self._split_unit(k)[1]
            if "distance" in label.lower() and unit == "cm":
                val, unit = float(val) / 100.0, "m"
            elif label == "Center entries":
                unit = "#"
            tiles.append((label, self._fmt(val), unit, tok))
        if len(tiles) < 4:
            for k, val in metrics.items():
                if k in used or not isinstance(val, (int, float)) or len(tiles) >= 4:
                    continue
                name, unit = self._split_unit(k)
                used.add(k)
                tiles.append((name, self._fmt(val), unit, "FAINT"))
        for i, (label, val, unit, tok) in enumerate(tiles[:4]):
            tile = QFrame()
            tile.setObjectName("HeroTile")
            tv = QVBoxLayout(tile)
            tv.setContentsMargins(10, 9, 10, 9)
            tv.setSpacing(4)
            cap = QHBoxLayout()
            cap.setSpacing(5)
            sw = QLabel()
            sw.setFixedSize(6, 6)
            sw.setStyleSheet(f"background:{getattr(theme, tok)}; border-radius:2px;")
            cap.addWidget(sw)
            cap.addWidget(_prop_label(label, tone="text2", role=None))
            cap.addStretch(1)
            tv.addLayout(cap)
            cap.itemAt(1).widget().setStyleSheet("font-size:10px;")
            vv = QLabel(f"{val}{self._unit_span(unit, 10)}")
            vv.setTextFormat(Qt.RichText)
            vv.setFont(mono_font(18, 500))
            tv.addWidget(vv)
            self.hero_grid.addWidget(tile, i // 2, i % 2)
            self._hero_tiles.append(tile)
        # key rows -------------------------------------------------------
        rows = []
        wanted = (("Mean speed", ("average speed", "mean speed")),
                  ("Latency to center", ("latency",)),
                  ("Thigmotaxis (5 cm band)", ("thigmotaxis %",)))
        for label, needles in wanted:
            k = self._find(metrics, needles)
            if k is not None and k not in used:
                used.add(k)
                val = metrics[k]
                rows.append((label, self._fmt(val) if isinstance(val, (int, float)) else str(val),
                             self._split_unit(k)[1] or ("s" if "latency" in label.lower() else "")))
        for label, val, unit in (extra or []):
            rows.append((label, val, unit))
        if not rows:
            for k, val in metrics.items():
                if k not in used and isinstance(val, (int, float)) and len(rows) < 6:
                    name, unit = self._split_unit(k)
                    rows.append((name, self._fmt(val), unit))
        for label, val, unit in rows:
            row = QWidget()
            row.setProperty("role", "metric-row")
            row.setAttribute(Qt.WA_StyledBackground, True)
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 7, 0, 7)
            a = _prop_label(label, role="metric-name")
            b = QLabel(f"{val}{self._unit_span(unit, 10)}")
            b.setTextFormat(Qt.RichText)
            b.setFont(mono_font(12, 500))
            h.addWidget(a, 1)
            h.addWidget(b)
            self.metrics_box.addWidget(row)
            self._rows.append(row)

    # -- occupancy ------------------------------------------------------
    def set_occupancy(self, grid=None, vmax=0.0, center_rel=None, pct_center=None,
                      pct_mobile=None, pct_wall=None, bin_text=""):
        self._occ = None if grid is None else dict(
            grid=grid, vmax=vmax, center_rel=center_rel, pct_center=pct_center,
            pct_mobile=pct_mobile, pct_wall=pct_wall, bin_text=bin_text)
        if grid is None:
            self.heat_mini.set_data(None, None)
            for val, bar, _c in self._occ_bars.values():
                val.setText("—")
                bar.set_fraction(0)
            self.lbl_ramp.setText("")
            return
        from gui.colormaps import heat_rgba
        rgba, _vm = heat_rgba(grid, empty=(26, 30, 34, 255))
        img = QImage(rgba.tobytes(), rgba.shape[1], rgba.shape[0], rgba.shape[1] * 4,
                     QImage.Format_RGBA8888).copy()
        self.heat_mini.set_data(img, center_rel)
        for key, pct in (("center", pct_center), ("mobile", pct_mobile), ("wall", pct_wall)):
            val, bar, col = self._occ_bars[key]
            if pct is None:
                val.setText("—")
                bar.set_fraction(0)
            else:
                val.setText(f"{pct:.1f} %")
                bar.set_fraction(pct / 100.0)
        self.lbl_ramp.setText(f"{vmax:.1f} s{bin_text}")

    # -- per-frame ------------------------------------------------------
    def set_frame(self, info):
        """info: dict(time, pos, pos_unit, speed, speed_unit, zone, zone_center,
        detected, cum, cum_unit, cum_frac, heading, conf, moving, window) or None."""
        self._last_frame = info
        if not info:
            for k in ("pos", "speed", "heading", "conf"):
                self._cur[k].setText("—")
            self.dial.set_degrees(None)
            self.lbl_time.setText("—")
            self.bar_cum.set_fraction(0)
            self.lbl_cum.setText("—")
            self.pill_zone.setText("—")
            self.lbl_moving.setText("")
            self.mini.set_data([])
            self.lbl_winmax.setText("")
            prop(self.pill_zone, zone="none")
            _repolish(self.pill_zone)
            return
        self.lbl_time.setText(info.get("time", "—"))
        self._cur["pos"].setText(info.get("pos", "—"))
        self._cur["pos_cap"].setText(f"POSITION · {info.get('pos_unit', '').upper()}".rstrip(" ·"))
        self._cur["speed"].setText(info.get("speed", "—"))
        self._cur["speed_cap"].setText(f"SPEED · {info.get('speed_unit', '').upper()}".rstrip(" ·"))
        hd = info.get("heading")
        self.dial.set_degrees(hd)
        self._cur["heading"].setText("—" if hd is None else f"{int(round(hd)) % 360}°")
        det = info.get("detected", True)
        conf = info.get("conf")
        self._cur["conf"].setText(f"{conf:.2f}" if isinstance(conf, float) else ("detected" if det else "missed"))
        self._cur["conf"].setProperty("state", "ok" if det else "err")
        _repolish(self._cur["conf"])
        zone = info.get("zone", "—")
        self.pill_zone.setText("●  " + str(zone).capitalize())
        prop(self.pill_zone, zone="center" if info.get("zone_center") else "periph")
        _repolish(self.pill_zone)
        mv = info.get("moving")
        self.lbl_moving.setText("" if mv is None else
                                ("Mobile · above threshold" if mv else "Immobile · below threshold"))
        win = info.get("window")
        if win:
            self.mini.set_data(win["values"], win.get("mid", 0.5))
            self.lbl_winmax.setText(f"max {win['max']:.1f}")
        cum_unit = info.get("cum_unit", "")
        self.lbl_cum.setText(f"{info.get('cum', '—')}{self._unit_span(cum_unit, 10)}")
        self.bar_cum.set_fraction(info.get("cum_frac", 0.0))


# ── Frame slider with tracking-issue marks ────────────────────────────────
class IssueSlider(QSlider):
    """The frame scrubber, with a thin red mark at every flagged frame.
    Hovering a mark shows what was flagged; clicking seeks as usual."""
    HIT = 4   # px either side of a mark that counts as hovering it

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(22)
        self._marks = []          # [(slider value, tooltip text)]
        theme.notifier.changed.connect(lambda _m: self.update())

    def set_marks(self, marks):
        self._marks = sorted(marks or [], key=lambda m: m[0])
        self.update()

    def marks(self):
        return list(self._marks)

    def _x_of(self, value):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        st = self.style()
        groove = st.subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
        handle = st.subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
        span = max(1, groove.width() - handle.width())
        pos = QStyle.sliderPositionFromValue(self.minimum(), self.maximum(), int(value), span)
        return groove.x() + handle.width() / 2.0 + pos, groove

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self._marks or self.maximum() <= self.minimum():
            return
        p = QPainter(self)
        col = QColor(theme.ERR)
        col.setAlphaF(0.9 if self.isEnabled() else 0.4)
        p.setPen(QPen(col, 1.6, cap=Qt.FlatCap))
        cy = self.height() / 2.0
        for value, _tip in self._marks:
            x, _g = self._x_of(value)
            p.drawLine(QPointF(x, cy - 7), QPointF(x, cy + 7))
        # Keep the handle on top of the marks.
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        opt.subControls = QStyle.SC_SliderHandle
        self.style().drawComplexControl(QStyle.CC_Slider, opt, p, self)
        p.end()

    def _mark_near(self, x):
        best, best_d = None, self.HIT + 1
        for value, _tip in self._marks:
            d = abs(self._x_of(value)[0] - x)
            if d < best_d:
                best, best_d = value, d
        return best

    def mousePressEvent(self, e):
        # Clicking a red mark jumps straight to that flagged frame.
        if e.button() == Qt.LeftButton and self._marks and self.isEnabled():
            v = self._mark_near(e.x())
            if v is not None:
                self.setValue(int(v))
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        if not self._marks:
            return
        best, best_d = None, self.HIT + 1
        for value, tip in self._marks:
            d = abs(self._x_of(value)[0] - e.x())
            if d < best_d:
                best, best_d = tip, d
        if best is not None:
            QToolTip.showText(e.globalPos(), best, self)
        else:
            QToolTip.hideText()
