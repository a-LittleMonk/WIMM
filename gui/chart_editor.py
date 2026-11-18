"""Chart editor — PowerPoint-style graph formatting.

    ┌ toolbar: preset · undo / redo · reset · sample · export · close ┐
    │ graph        │                                  │ Format pane    │
    │ thumbnails   │   live chart — click any part    │ (only the      │
    │              │   to select it, drag to move     │  selection's   │
    │              │                                  │  settings)     │

Click an element (title, axis titles, axis numbers, legend, colour bar,
data, arena, center zone, start/end markers, plot area, chart background)
to select it; the Format pane shows just its settings. Title, axis titles,
legend, colour bar and cell labels drag to move; the plot area has resize
handles. Every change applies at once (the app's graphs follow); Ctrl+Z /
Ctrl+Y undo and redo. "Apply to all graphs" copies the selected element's
formatting to every graph of this test.

Built on GraphStyleDialog: its per-graph renderers, sample data, presets,
persistence and field editors are reused — only the shell and the
click / drag interaction are new. Drag positions are stored as style
fields and applied by graph_style.apply_layout_overrides(), the same step
the app's real graphs use.
"""
import copy
import time

from PyQt5.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QLineEdit, QFrame, QHBoxLayout, QLabel, QListView,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea, QShortcut, QSizePolicy,
    QSpinBox, QSplitter, QStyle, QStyledItemDelegate, QTabBar, QVBoxLayout, QWidget,
)
from matplotlib.transforms import ScaledTranslation

from gui import theme
from gui.graph_style import (DISTANCE_UNIT_CHOICES, SPEED_UNIT_CHOICES, TIME_UNIT_CHOICES, apply_layout_overrides, default_style_for,
                             resolve_style, resolve_token, resolve_field)
from gui.heatmap_grid import HM_BINS_RANGE, HM_HELP, HM_INTERP_CHOICES, HM_UNIT_CHOICES
from gui.graph_style_dialog import (
    GRID_AXIS_CHOICES, LEGEND_LOC_CHOICES, LINESTYLE_CHOICES, MARKER_CHOICES,
    PIN_MARKER_CHOICES, CMAP_CHOICES, CUSTOM_CMAP_STOPS, GraphStyleDialog,
    _ColorButton, _fig_mode,
)

LEGEND_FONT_RANGE = (4.0, 40.0)   # legend text size limits (pt) when resizing

# Which unit belongs to which axis — an axis-title panel shows only its own.
UNIT_FIELDS = {"speed_unit", "time_unit", "distance_unit"}
AXIS_UNIT = {
    ("Speed", "xlabel"): "time_unit",           ("Speed", "ylabel"): "speed_unit",
    ("Speed Histogram", "xlabel"): "speed_unit", ("Speed Histogram", "ylabel"): "time_unit",
    ("Habituation", "xlabel"): "time_unit",     ("Habituation", "ylabel"): "distance_unit",
    ("Zone Time", "ylabel"): "time_unit",
}

# ── Chart elements ─────────────────────────────────────────────────────────
# key → (label, [(field, row label, kind, options)]). A row only appears when
# the current graph supports that field. Kinds: color, text, int, float,
# bool, combo, pair, font, spines, cmap, bars, textcolor.
ELEMENTS = {
    "chart": ("Chart area", [
        ("speed_unit", "Speed unit", "combo", SPEED_UNIT_CHOICES),
        ("time_unit", "Time unit", "combo", TIME_UNIT_CHOICES),
        ("distance_unit", "Distance unit", "combo", DISTANCE_UNIT_CHOICES),
        ("outer_bg", "Background", "color", None),
        ("font_family", "Font (all text)", "font", None),
        ("text_color", "Text color (all text)", "color", None),
    ]),
    "plot": ("Plot area", [
        ("bg", "Background", "color", None),
        ("spines", "Border", "spines", None),
        ("spine_color", "Border color", "color", None),
        ("spine_width", "Border width", "float", (0.1, 6.0, 0.1)),
        ("grid", "Gridlines", "bool", None),
        ("grid_color", "Gridline color", "color", None),
        ("grid_alpha", "Gridline opacity", "float", (0.05, 1.0, 0.05)),
        ("grid_linestyle", "Gridline style", "pair", LINESTYLE_CHOICES),
        ("grid_axis", "Gridlines on", "combo", GRID_AXIS_CHOICES),
    ]),
    "title": ("Chart title", [
        ("title", "Text", "text", None),
        ("font_family", "Font (all text)", "font", None),
        ("title_size", "Size", "int", (6, 36)),
        ("title_bold", "Bold", "bool", None),
        ("title_color", "Color", "textcolor", None),
    ]),
    "xlabel": ("Horizontal axis title", [
        ("xlabel", "Text", "text", None),
        ("speed_unit", "Speed unit", "combo", SPEED_UNIT_CHOICES),
        ("time_unit", "Time unit", "combo", TIME_UNIT_CHOICES),
        ("distance_unit", "Distance unit", "combo", DISTANCE_UNIT_CHOICES),
        ("xlabel_size", "Size", "int", (6, 32)),
        ("xlabel_bold", "Bold", "bool", None),
        ("xlabel_color", "Color", "textcolor", None),
    ]),
    "ylabel": ("Vertical axis title", [
        ("ylabel", "Text", "text", None),
        ("speed_unit", "Speed unit", "combo", SPEED_UNIT_CHOICES),
        ("time_unit", "Time unit", "combo", TIME_UNIT_CHOICES),
        ("distance_unit", "Distance unit", "combo", DISTANCE_UNIT_CHOICES),
        ("ylabel_size", "Size", "int", (6, 32)),
        ("ylabel_bold", "Bold", "bool", None),
        ("ylabel_color", "Color", "textcolor", None),
    ]),
    "ticks": ("Axis numbers", [
        ("show_ticks", "Show", "bool", None),
        ("speed_unit", "Speed unit", "combo", SPEED_UNIT_CHOICES),
        ("time_unit", "Time unit", "combo", TIME_UNIT_CHOICES),
        ("distance_unit", "Distance unit", "combo", DISTANCE_UNIT_CHOICES),
        ("tick_size", "Size", "int", (5, 24)),
        ("tick_bold", "Bold", "bool", None),
        ("tick_color", "Color", "color", None),
    ]),
    "series": ("Data", [
        ("cmap", "Color scale", "cmap", None),
        ("speed_unit", "Speed unit", "combo", SPEED_UNIT_CHOICES),
        ("time_unit", "Time unit", "combo", TIME_UNIT_CHOICES),
        ("distance_unit", "Distance unit", "combo", DISTANCE_UNIT_CHOICES),
        ("hm_bins", "Grid size (squares across)", "int", HM_BINS_RANGE),
        ("hm_blur", "Blur (radius in squares)", "float", (0.0, 30.0, 0.25)),
        ("hm_interp", "Drawing", "pair", HM_INTERP_CHOICES),
        ("hm_units", "Scale unit", "pair", HM_UNIT_CHOICES),
        ("hm_vmax", "Fixed maximum (0 = auto)", "float", (0.0, 100000.0, 0.1)),
        ("path_color", "Color", "color", None),
        ("path_width", "Line width", "float", (0.1, 12.0, 0.1)),
        ("linestyle", "Line style", "pair", LINESTYLE_CHOICES),
        ("alpha", "Opacity", "float", (0.05, 1.0, 0.05)),
        ("marker", "Markers", "pair", MARKER_CHOICES),
        ("marker_size", "Marker size", "int", (1, 30)),
        ("bar_colors", "Bar colors", "bars", None),
        ("hist_edge_color", "Bar edges", "color", None),
    ]),
    "arena": ("Arena outline", [
        ("arena_color", "Color", "color", None),
        ("arena_width", "Width", "float", (0.1, 8.0, 0.1)),
        ("shape_thickness", "Arm thickness (%)", "int", (8, 48)),
    ]),
    "center": ("Center zone", [
        ("show_center_pct", "Show", "bool", None),
        ("center_pct_color", "Color", "color", None),
        ("center_size_pct", "Size (% of arena)", "int", (5, 100)),
    ]),
    "pins": ("Start / end markers", [
        ("pin_start_color", "Start color", "color", None),
        ("pin_start_marker", "Start shape", "pair", PIN_MARKER_CHOICES),
        ("pin_end_color", "End color", "color", None),
        ("pin_end_marker", "End shape", "pair", PIN_MARKER_CHOICES),
        ("pin_size", "Size", "int", (20, 400)),
    ]),
    "legend": ("Legend", [
        ("legend_show", "Show", "bool", None),
        ("legend_fontsize", "Text size", "float", LEGEND_FONT_RANGE + (0.5,)),
        ("legend_text_color", "Text color", "textcolor", None),
        ("legend_bg", "Background", "color", None),
        ("legend_loc", "Position", "combo", LEGEND_LOC_CHOICES),
        ("legend_inset_pct", "Gap from edge (%)", "float", (0.0, 25.0, 0.5)),
    ]),
    "colorbar": ("Color bar", [
        ("colorbar_show", "Show", "bool", None),
        ("colorbar_label", "Label", "text", None),
        ("cmap", "Color scale", "cmap", None),
        ("colorbar_w", "Width (% of chart)", "cbsize", None),
        ("colorbar_h", "Height (% of chart)", "cbsize", None),
    ]),
    "cells": ("Cell labels", [
        ("cell_label_size", "Size", "int", (5, 30)),
        ("cell_label_font", "Font", "font", None),
        ("cell_label_bold", "Bold", "bool", None),
    ]),
}
ELEMENT_ORDER = ["chart", "plot", "title", "xlabel", "ylabel", "ticks", "series",
                 "arena", "center", "pins", "legend", "colorbar", "cells"]
SPINES = [("spine_top", "Top"), ("spine_right", "Right"),
          ("spine_bottom", "Bottom"), ("spine_left", "Left")]

# Fields that store an element's dragged position (Reset position clears them).
POSITION_FIELDS = {
    "title": {"title_dx": 0.0, "title_pad": 0.0},
    "xlabel": {"xlabel_dx": 0.0, "xlabel_dy": 0.0},
    "ylabel": {"ylabel_dx": 0.0, "ylabel_dy": 0.0},
    "plot": {"plot_dl": 0.0, "plot_db": 0.0, "plot_dr": 0.0, "plot_dt": 0.0},
    "colorbar": {"colorbar_x": 0.0, "colorbar_y": 0.0, "colorbar_w": 0.0, "colorbar_h": 0.0},
    "cells": {"cell_label_dx": 0, "cell_label_dy": 0},
    "legend": {"legend_x_offset": 0.0, "legend_y_offset": 0.0},
}
DRAGGABLE = {"title", "xlabel", "ylabel", "legend", "colorbar", "plot", "cells"}
RESIZABLE = {"plot", "colorbar", "legend"}   # get 8 resize handles when selected
HANDLE = 7          # px, plot-area / colour-bar resize handles

# Colour bar rect = base + stored offset (see _maybe_colorbar / graphs_mixin).
# Size limits keep it visible and inside the chart.
CB_BASE_W, CB_BASE_H = 0.88, 0.04
CB_W_RANGE = (0.05, 1.0)
CB_H_RANGE = (0.005, 0.35)
DRAG_START = 3      # px of movement before a press becomes a drag
SNAP_PX = 8         # px: how close an edge / middle must be to a guide to snap


class _Overlay(QWidget):
    """Selection outline + resize handles painted over the chart canvas."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.rects = []        # QRectF in widget coords
        self.handles = False   # draw 8 resize handles on rects[0]
        self.guides = []       # ("v", x) / ("h", y) snap lines, widget coords

    def paintEvent(self, _e):
        if not self.rects and not self.guides:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.guides:
            gp = QPen(QColor(theme.WARN), 1)
            p.setPen(gp)
            for kind, v in self.guides:
                if kind == "v":
                    p.drawLine(QPointF(v, 0), QPointF(v, self.height()))
                else:
                    p.drawLine(QPointF(0, v), QPointF(self.width(), v))
        pen = QPen(QColor(theme.ACCENT), 1.2, Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for r in self.rects:
            p.drawRect(r.adjusted(-3, -3, 3, 3))
        if self.handles and self.rects:
            p.setPen(QPen(QColor(theme.ACCENT), 1))
            p.setBrush(QColor("#FFFFFF"))
            for pt in _handle_points(self.rects[0]):
                p.drawRect(QRectF(pt.x() - HANDLE / 2, pt.y() - HANDLE / 2, HANDLE, HANDLE))
        p.end()


class _ThumbDelegate(QStyledItemDelegate):
    """Graph list entry: chart thumbnail with its name underneath (like
    PowerPoint's slide list); the selected graph gets an accent frame."""
    W, IMG_H, TXT_H = 176, 118, 24

    def sizeHint(self, _opt, _idx):
        return QSize(self.W, self.IMG_H + self.TXT_H + 14)

    def paint(self, p, opt, idx):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(opt.rect).adjusted(8, 5, -8, -5)
        img = QRectF(r.left(), r.top(), r.width(), self.IMG_H)
        selected = bool(opt.state & QStyle.State_Selected)
        hover = bool(opt.state & QStyle.State_MouseOver)
        p.setPen(QPen(QColor(theme.ACCENT if selected else theme.BORDER_2), 2 if selected else 1))
        p.setBrush(QColor(theme.VIDEO_BG))
        p.drawRoundedRect(img, 6, 6)
        icon = idx.data(Qt.DecorationRole)
        if isinstance(icon, QIcon) and not icon.isNull():
            pm = icon.pixmap(QSize(int(img.width()) - 6, int(img.height()) - 6))
            x = img.left() + (img.width() - pm.width() / pm.devicePixelRatio()) / 2
            y = img.top() + (img.height() - pm.height() / pm.devicePixelRatio()) / 2
            p.drawPixmap(QPointF(x, y), pm)
        p.setPen(QColor(theme.TEXT if (selected or hover) else theme.TEXT_2))
        f = opt.font
        f.setBold(selected)
        p.setFont(f)
        p.drawText(QRectF(r.left(), img.bottom() + 2, r.width(), self.TXT_H),
                   Qt.AlignCenter, idx.data(Qt.DisplayRole) or "")
        p.restore()


class _ClickAway(QObject):
    """App-wide filter, installed only while an inline edit is open: a
    mouse press anywhere outside the edit box saves it. The click itself
    still goes through (select another element, press a button, …)."""

    def __init__(self, editor, on_click_away):
        super().__init__(editor)
        self._ed = editor
        self._cb = on_click_away

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            if not (obj is self._ed or (isinstance(obj, QWidget)
                                        and self._ed.isAncestorOf(obj))):
                self._cb()
        return False


class _InlineEdit(QLineEdit):
    """Text box laid over the chart for editing a title / legend entry in
    place. Enter, focus-out or a click anywhere else → committed, Esc →
    cancelled."""
    committed = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self._done = False
        self.returnPressed.connect(self._commit)

    def _commit(self):
        if not self._done:
            self._done = True
            self.committed.emit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._done = True
            self.cancelled.emit()
            return
        super().keyPressEvent(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self._commit()


def _handle_points(r):
    cx, cy = r.center().x(), r.center().y()
    return [QPointF(r.left(), r.top()), QPointF(cx, r.top()), QPointF(r.right(), r.top()),
            QPointF(r.right(), cy), QPointF(r.right(), r.bottom()), QPointF(cx, r.bottom()),
            QPointF(r.left(), r.bottom()), QPointF(r.left(), cy)]


# Handle index → which plot edges it moves (left, bottom, right, top).
_HANDLE_EDGES = ["lt", "t", "rt", "r", "rb", "b", "lb", "l"]


class ChartEditor(GraphStyleDialog):
    def __init__(self, *args, **kwargs):
        self._sel = "title"
        self._artists = {}
        self._undo, self._redo = [], []
        self._last_push = (None, 0.0)
        self._label_widgets = {}
        self._thumb_busy = False
        super().__init__(*args, **kwargs)
        self.setWindowTitle("Customize graphs")
        # Maximise / minimise buttons on the title bar (a plain QDialog has
        # none); F11 toggles full screen.
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint
                            | Qt.WindowMinimizeButtonHint)
        self.setSizeGripEnabled(True)
        self.resize(1320, 800)
        self.setMinimumSize(1040, 640)
        QShortcut(QKeySequence(Qt.Key_F11), self, activated=self._toggle_full_screen)
        self._live = True          # every change reaches the app's graphs
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(400)
        self._thumb_timer.timeout.connect(self._update_current_thumb)
        QShortcut(QKeySequence.Undo, self, activated=self._do_undo)
        QShortcut(QKeySequence.Redo, self, activated=self._do_redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self._do_redo)
        QTimer.singleShot(0, self._render_all_thumbs)

    def _toggle_full_screen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def showEvent(self, e):
        super().showEvent(e)
        # Never open larger than the monitor (small / scaled screens).
        if not getattr(self, "_fitted_to_screen", False):
            self._fitted_to_screen = True
            h = self.windowHandle()
            scr = h.screen() if h is not None else None
            if scr is not None:
                avail = scr.availableGeometry()
                w = min(self.width(), avail.width() - 20)
                hh = min(self.height(), avail.height() - 40)
                if (w, hh) != (self.width(), self.height()):
                    self.setMinimumSize(min(self.minimumWidth(), w),
                                        min(self.minimumHeight(), hh))
                    self.resize(w, hh)

    # ── UI shell ─────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(10)

        # Test tabs on their own row (Open Field / Novel Object / …).
        self.tabs_plugin = QTabBar()
        self.tabs_plugin.setExpanding(False)
        self.tabs_plugin.setDocumentMode(True)
        for p in self._plugins:
            self.tabs_plugin.addTab(p["label"])
        sel = next((i for i, p in enumerate(self._plugins)
                    if p["key"] == self._current_plugin_key), 0)
        self.tabs_plugin.setCurrentIndex(sel)
        self.tabs_plugin.currentChanged.connect(self._on_plugin_tab_changed)
        self.tabs_plugin.setVisible(len(self._plugins) > 1)
        # Row 1: test tabs + preview / export / close on the right.
        # Row 2: presets + editing. (One row was too wide — buttons got
        # squeezed and overlapped.)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.tabs_plugin)
        top.addStretch(1)
        root.addLayout(top)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(QLabel("Preset"))
        self.cmb_preset = QComboBox()
        self.cmb_preset.setMinimumWidth(150)
        self.cmb_preset.setToolTip("A preset holds the look of every graph of every test")
        self.cmb_preset.currentTextChanged.connect(self._on_preset_pick)
        bar.addWidget(self.cmb_preset)
        self.lbl_preset_state = QLabel("")
        theme.set_tone(self.lbl_preset_state, "warn", "font-size: 11px; padding-left: 8px;")
        self.lbl_preset_state.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        bar.addWidget(self.lbl_preset_state)
        self.btn_update_preset = QPushButton("Update preset")
        self.btn_update_preset.clicked.connect(self._update_preset)
        bar.addWidget(self.btn_update_preset)
        b = QPushButton("Save as new")
        b.setToolTip("Save every graph of every test as a new preset")
        b.clicked.connect(self._save_preset_dialog)
        bar.addWidget(b)
        self.btn_delete_preset = QPushButton("Delete preset")
        self.btn_delete_preset.clicked.connect(self._delete_preset)
        bar.addWidget(self.btn_delete_preset)
        self._reload_presets()
        bar.addWidget(self._vsep())
        self.btn_undo = QPushButton("Undo")
        self.btn_undo.setToolTip("Undo (Ctrl+Z)")
        self.btn_undo.clicked.connect(self._do_undo)
        self.btn_redo = QPushButton("Redo")
        self.btn_redo.setToolTip("Redo (Ctrl+Y)")
        self.btn_redo.clicked.connect(self._do_redo)
        bar.addWidget(self.btn_undo)
        bar.addWidget(self.btn_redo)
        bar.addWidget(self._vsep())
        self.btn_reset_graph = QPushButton("Reset graph")
        self.btn_reset_graph.setToolTip("Put this graph back to how the current preset draws it")
        self.btn_reset_graph.clicked.connect(self._reset_graph_undoable)
        bar.addWidget(self.btn_reset_graph)
        bar.addWidget(self._vsep())
        self.chk_snap = QCheckBox("Snap")
        self.chk_snap.setChecked(True)
        self.chk_snap.setToolTip("While dragging, snap to the edges and middles of the chart, "
                                 "the plot area and other elements (hold Alt to move freely)")
        bar.addWidget(self.chk_snap)
        bar.addStretch(1)
        root.addLayout(bar)
        bar_rows = (top, bar)
        bar = top          # the rest goes on the tab row, right-aligned
        self.chk_real = QCheckBox("Show my data")
        self.chk_real.setToolTip("Preview with the tracked session instead of sample data")
        self.chk_real.toggled.connect(self._on_real_toggle)
        has_real = self._maybe_real_sample() is not None
        self.chk_real.setEnabled(has_real)
        bar.addWidget(self.chk_real)
        self.btn_regen = QPushButton("New sample")
        self.btn_regen.setToolTip("Draw a different sample mouse path")
        self.btn_regen.clicked.connect(self._regen_sample)
        bar.addWidget(self.btn_regen)
        self.btn_export_preview = QPushButton("Export preview")
        self.btn_export_preview.setCheckable(True)
        self.btn_export_preview.setToolTip(
            "Show the graphs exactly as exported files and Excel images look "
            "(light background), whatever the app theme")
        self.btn_export_preview.toggled.connect(self._on_export_preview)
        bar.addWidget(self.btn_export_preview)
        self.btn_export_graph = QPushButton("Export…")
        self.btn_export_graph.setToolTip("Save this graph as SVG / PDF / PNG")
        self.btn_export_graph.clicked.connect(self._on_export_graph_clicked)
        bar.addWidget(self.btn_export_graph)
        close = QPushButton("Close")
        close.setProperty("primary", True)
        close.clicked.connect(self._accept)
        bar.addWidget(close)
        # Never squeeze a control below its text (texts were cut off /
        # "edited" slid under the preset box).
        for row in bar_rows:
            for i in range(row.count()):
                w = row.itemAt(i).widget()
                if isinstance(w, (QPushButton, QCheckBox, QLabel)):
                    w.ensurePolished()
                    w.setMinimumWidth(w.sizeHint().width())
        self.lbl_preset_state.setFixedWidth(
            self.lbl_preset_state.fontMetrics().horizontalAdvance("edited") + 20)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

        # Left — graph thumbnails (like slides).
        self.list_graphs = QListWidget()
        self.list_graphs.setItemDelegate(_ThumbDelegate(self.list_graphs))
        self.list_graphs.setUniformItemSizes(True)
        self.list_graphs.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.list_graphs.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_graphs.setMinimumWidth(190)
        self.list_graphs.setMaximumWidth(230)
        for name in self._plugin_graph_names:
            self.list_graphs.addItem(QListWidgetItem(name))
        self.list_graphs.currentTextChanged.connect(self._select)
        split.addWidget(self.list_graphs)

        # Centre — the live chart.
        centre = QWidget()
        cv = QVBoxLayout(centre)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(6)
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
        self._fig = plt.figure(figsize=(6.4, 5.0))
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._canvas.setMinimumSize(420, 340)
        cv.addWidget(self._canvas, 1)
        self._overlay = _Overlay(self._canvas)
        self._hint = QLabel("Click any part of the graph to format it. "
                            "Drag the title, axis titles, legend or color bar to move them. "
                            "Double-click a title or legend text to edit it.")
        theme.set_tone(self._hint, "faint", "font-size: 11px;")
        self._export_banner = QLabel("Export preview — this is how saved files and "
                                     "Excel images look. Turn it off to see the on-screen version.")
        self._export_banner.setWordWrap(True)
        theme.set_tone(self._export_banner, "warn", "font-size: 11px; font-weight: 600;")
        self._export_banner.hide()
        cv.addWidget(self._export_banner)
        cv.addWidget(self._hint)
        split.addWidget(centre)
        self._canvas.mpl_connect("button_press_event", self._on_press)
        self._canvas.mpl_connect("motion_notify_event", self._on_motion)
        self._canvas.mpl_connect("button_release_event", self._on_release)
        self._canvas.mpl_connect("resize_event", lambda _e: self._update_overlay())
        self._drag = None

        # Right — Format pane.
        pane = QFrame()
        pane.setObjectName("FormatPane")
        pane.setMinimumWidth(330)
        pane.setMaximumWidth(420)
        pv = QVBoxLayout(pane)
        pv.setContentsMargins(14, 12, 14, 12)
        pv.setSpacing(10)
        self.lbl_format = QLabel("Format")
        self.lbl_format.setStyleSheet("font-size: 15px; font-weight: 600;")
        pv.addWidget(self.lbl_format)
        self.cmb_element = QComboBox()
        self.cmb_element.setToolTip("Pick any part of the graph — also ones that are hidden")
        self.cmb_element.activated.connect(
            lambda i: self._set_selection(self.cmb_element.itemData(i)))
        pv.addWidget(self.cmb_element)
        self.props_scroll = QScrollArea()
        self.props_scroll.setWidgetResizable(True)
        self.props_scroll.setFrameShape(QFrame.NoFrame)
        self.props_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        pv.addWidget(self.props_scroll, 1)
        acts = QHBoxLayout()
        self.btn_reset_pos = QPushButton("Reset position")
        self.btn_reset_pos.setToolTip("Put this element back where the current preset has it")
        self.btn_reset_pos.clicked.connect(self._reset_position)
        self.btn_apply_all = QPushButton("Apply to all graphs")
        self.btn_apply_all.setToolTip("Copy this element's formatting to every graph of this test")
        self.btn_apply_all.clicked.connect(self._apply_to_all)
        acts.addWidget(self.btn_reset_pos)
        acts.addStretch(1)
        acts.addWidget(self.btn_apply_all)
        pv.addLayout(acts)
        split.addWidget(pane)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([210, 760, 350])
        self._update_undo_buttons()

    @staticmethod
    def _vsep():
        f = QFrame()
        f.setObjectName("PanelDivider")
        f.setFixedSize(1, 20)
        return f

    # ── graph selection ──────────────────────────────────────────────────
    def _select(self, name):
        if not name:
            return
        self._current = name
        items = self.list_graphs.findItems(name, Qt.MatchExactly)
        if items and self.list_graphs.currentItem() is not items[0]:
            self.list_graphs.blockSignals(True)
            self.list_graphs.setCurrentItem(items[0])
            self.list_graphs.blockSignals(False)
        if self._sel not in self._available_elements():
            self._sel = "title" if "title" in self._available_elements() else "chart"
        self._refresh_preview()
        self._build_format_pane()

    def _available_elements(self):
        allowed = self._allowed_fields(self._current)
        out = []
        for key in ELEMENT_ORDER:
            label, rows = ELEMENTS[key]
            if key == "cells":
                if self._current == "Cell Time":
                    out.append(key)
                continue
            fields = set()
            for f, _l, kind, _o in rows:
                fields.update(k for k, _ in SPINES) if kind == "spines" else fields.add(f)
            if key == "series" and self._current in ("Trajectory", "Speed", "Speed Histogram",
                                                      "Habituation", "Zone Time", "Heatmap",
                                                      "Cell Time", "Triplets"):
                out.append(key)
            elif fields & allowed:
                out.append(key)
        return out

    # ── Format pane ──────────────────────────────────────────────────────
    def _build_format_pane(self):
        key = self._sel
        label, rows = ELEMENTS[key]
        self.lbl_format.setText(f"Format {label.lower()}" if key != "chart" else "Format chart area")
        self.cmb_element.blockSignals(True)
        self.cmb_element.clear()
        for k in self._available_elements():
            self.cmb_element.addItem(ELEMENTS[k][0], k)
        self.cmb_element.setCurrentIndex(max(0, self.cmb_element.findData(key)))
        self.cmb_element.blockSignals(False)

        allowed = self._allowed_fields(self._current)
        style = self._axis_fallbacks(self._cfg.get_for(self._current_plugin_key, self._current))
        baseline = self._axis_fallbacks(default_style_for(self._current, self._current_plugin_key))
        self._diff_fields = {f for f in allowed if baseline.get(f) != style.get(f)}
        self._editors = {}
        self._label_widgets = {}
        self._palette_label = self._palette_container = None

        host = QWidget()
        form = QFormLayout(host)
        form.setContentsMargins(0, 4, 4, 4)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        n = 0
        for field, text, kind, opt in rows:
            if kind == "spines":
                if any(k in allowed for k, _ in SPINES):
                    self._add_spines(form, style, allowed)
                    n += 1
                continue
            if kind == "cmap":
                if "cmap" in allowed:
                    self._add_combo(form, "cmap", text, style, CMAP_CHOICES)
                    if any(k in allowed for k in CUSTOM_CMAP_STOPS):
                        self._add_palette_row(form, style, allowed)
                    n += 1
                continue
            if field not in allowed:
                continue
            if (key in ("xlabel", "ylabel") and field in UNIT_FIELDS
                    and AXIS_UNIT.get((self._current, key)) != field):
                continue                     # that unit belongs to the other axis
            n += 1
            if kind == "cbsize":
                self._add_cb_size(form, field, text, style)
                continue
            if kind == "color":
                self._add_color(form, field, text, style)
            elif kind == "textcolor":
                self._add_text_color(form, field, text, style)
            elif kind == "text":
                self._add_text(form, field, text, style)
            elif kind == "int":
                self._add_int_spin(form, field, text, style, *opt)
            elif kind == "float":
                self._add_spin(form, field, text, style, *opt)
            elif kind == "bool":
                self._add_check(form, field, text, style)
            elif kind == "combo":
                self._add_combo(form, field, text, style, opt)
            elif kind == "pair":
                self._add_pair_combo(form, field, text, style, opt)
            elif kind == "font":
                self._add_font(form, field, text, style)
            elif kind == "bars":
                self._add_bar_colors(form, style)
        if key == "series" and "hm_bins" in allowed:
            hm_help = QLabel(HM_HELP)
            hm_help.setWordWrap(True)
            theme.set_tone(hm_help, "faint", "font-size: 11px;")
            form.addRow(hm_help)
        if key == "legend":
            n += self._add_legend_label_rows(form)
        if key == "cells":
            form.addRow(QLabel("Drag the cell labels on the graph to move them."))
        elif n == 0:
            form.addRow(QLabel("Nothing to format here for this graph."))
        if key in DRAGGABLE:
            tip = {"plot": "Drag the handles to resize the plot area, or drag inside it to move it.",
                   "legend": "Drag the handles to make the legend bigger or smaller, "
                             "or drag inside it to move it.",
                   "colorbar": "Drag the handles to resize the color bar, or drag inside it to move it.",
                   "cells": ""}.get(key, "Drag it on the graph to move it.")
            if tip:
                hint = QLabel(tip)
                hint.setWordWrap(True)
                theme.set_tone(hint, "faint", "font-size: 11px;")
                form.addRow(hint)
        self._fit_pane_width(form, host)
        self.props_scroll.setWidget(host)
        self.btn_reset_pos.setVisible(key in POSITION_FIELDS)
        self.btn_apply_all.setEnabled(bool(rows))

    @staticmethod
    def _axis_fallbacks(style):
        """Copy of `style` where unset per-axis title settings show the
        shared value they currently fall back to (label_size / _bold)."""
        style = dict(style)
        for axis in ("xlabel", "ylabel"):
            if style.get(f"{axis}_size") in (None, ""):
                style[f"{axis}_size"] = style.get("label_size", 10)
            if style.get(f"{axis}_bold") is None:
                style[f"{axis}_bold"] = bool(style.get("label_bold", False))
            if not style.get(f"{axis}_color") and style.get("label_color"):
                style[f"{axis}_color"] = style["label_color"]
        return style

    @staticmethod
    def _fit_pane_width(form, host):
        """Keep every row inside the Format pane (no horizontal scrolling):
        a label that doesn't fit next to its field goes above it, and fields
        may shrink to the pane width instead of insisting on their natural
        width (long font / preset names, colour rows with extra buttons)."""
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for w in host.findChildren(QWidget):
            if isinstance(w, QComboBox):
                w.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
                w.setMinimumContentsLength(6)
                w.setMinimumWidth(0)
            elif isinstance(w, (QLineEdit, QDoubleSpinBox, QSpinBox)):
                w.setMinimumWidth(min(w.minimumWidth(), 60))
            elif isinstance(w, QLabel) and w.wordWrap() is False and len(w.text()) > 30:
                w.setWordWrap(True)

    def _add_cb_size(self, form, field, label, style):
        """Colour-bar width / height as a plain % of the chart. Stored as
        an offset from the default size (colorbar_w / colorbar_h)."""
        base, (lo, hi) = ((CB_BASE_W, CB_W_RANGE) if field == "colorbar_w"
                          else (CB_BASE_H, CB_H_RANGE))
        sp = QDoubleSpinBox()
        sp.setRange(lo * 100.0, hi * 100.0)
        sp.setDecimals(1)
        sp.setSingleStep(0.5 if field == "colorbar_h" else 2.0)
        sp.setSuffix(" %")
        try:
            cur = base + float(style.get(field, 0.0))
        except Exception:
            cur = base
        sp.setValue(min(hi, max(lo, cur)) * 100.0)
        sp.valueChanged.connect(
            lambda v, f=field, b=base: self._commit(f, round(v / 100.0 - b, 4)))
        form.addRow(self._row_label_widget(field, label), sp)
        self._editors[field] = sp

    def _add_spines(self, form, style, allowed):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        for k, lbl in SPINES:
            if k not in allowed:
                continue
            cb = QCheckBox(lbl)
            cb.setChecked(bool(style.get(k, True)))
            cb.toggled.connect(lambda v, f=k: self._commit(f, bool(v)))
            h.addWidget(cb)
            self._editors[k] = cb
        h.addStretch(1)
        form.addRow(self._row_label_widget("spine_top", "Border"), row)

    def _color_field(self, hex_value, on_pick):
        """Office-style colour control: swatch button (full picker) + ▾ menu
        of preset colours. Returns (widget, swatch button)."""
        from PyQt5.QtWidgets import QGridLayout, QMenu, QToolButton, QWidgetAction
        from gui.graph_style_dialog import SWATCHES
        btn = _ColorButton(hex_value, on_pick, self)
        btn.setFixedSize(92, 26)
        more = QToolButton()
        more.setText("▾")
        more.setToolTip("Preset colors")
        more.setPopupMode(QToolButton.InstantPopup)
        more.setFixedSize(26, 26)
        menu = QMenu(more)
        grid_w = QWidget()
        g = QGridLayout(grid_w)
        g.setContentsMargins(8, 8, 8, 8)
        g.setSpacing(5)
        for i, hx in enumerate(SWATCHES):
            sw = QPushButton()
            sw.setFixedSize(22, 22)
            sw.setToolTip(hx)
            sw.setStyleSheet(f"QPushButton {{ background:{hx}; border:1px solid rgba(128,128,128,0.5);"
                             f" border-radius: 3px; }}")
            sw.clicked.connect(lambda _=False, h=hx: (btn.set_hex(h), on_pick(h), menu.close()))
            g.addWidget(sw, i // 6, i % 6)
        act = QWidgetAction(menu)
        act.setDefaultWidget(grid_w)
        menu.addAction(act)
        more.setMenu(menu)
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addWidget(btn)
        h.addWidget(more)
        return w, btn

    def _add_color(self, form, field, label, style):
        w, btn = self._color_field(resolve_field(field, style.get(field, "#000000"), _fig_mode()),
                                   lambda hx, f=field: self._commit(f, hx))
        w.layout().addStretch(1)
        form.addRow(self._row_label_widget(field, label), w)
        self._editors[field] = btn

    def _add_text_color(self, form, field, label, style):
        """Per-element colour; blank means 'same as all text'."""
        eff = style.get(field) or style.get("text_color") or "@ink"
        w, btn = self._color_field(resolve_token(eff, _fig_mode()),
                                   lambda hx, f=field: self._commit(f, hx))
        same = QPushButton("Same as text")
        same.setToolTip("Use the chart's text color")
        same.clicked.connect(lambda _=False, f=field: self._commit(f, ""))
        # …and show that colour on the swatch straight away.
        same.clicked.connect(lambda _=False, b=btn, s=style: b.set_hex(
            resolve_token(s.get("text_color") or "@ink", _fig_mode())))
        h = w.layout()
        h.addSpacing(4)
        h.addWidget(same)
        h.addStretch(1)
        form.addRow(self._row_label_widget(field, label), w)
        self._editors[field] = btn

    def _add_font(self, form, field, label, style):
        from gui.appearance_dialog import FontPicker
        cb = FontPicker()
        cb.addItems(["sans-serif", "serif", "monospace"])
        cb.insertSeparator(cb.count())
        for fam in sorted(theme.installed_families(), key=str.lower):
            if not fam.startswith("@"):
                cb.addItem(fam)
        cur = resolve_token(style.get(field, "@sans"), _fig_mode())
        i = cb.findText(cur)
        cb.setCurrentIndex(i if i >= 0 else 0)
        cb.currentTextChanged.connect(
            lambda v, f=field, w=cb: self._commit(f, v) if w.findText(v) >= 0 else None)
        form.addRow(self._row_label_widget(field, label), cb)
        self._editors[field] = cb

    def _row_label(self, field, text):
        return text   # no "• changed" markers in the Office-style pane

    # ── commits + undo ───────────────────────────────────────────────────
    # An undo step is {"styles": [(test, graph, style)], "active": preset}.
    def _snapshot(self, names=None, all_tests=False):
        if all_tests:
            from gui.graph_style import ALL_PLUGIN_KEYS
            pairs = [(pk, g) for pk in ALL_PLUGIN_KEYS for g in self._all_graph_names()]
        else:
            pairs = [(self._current_plugin_key, n) for n in (names or [self._current])]
        return {"styles": [(pk, n, copy.deepcopy(self._cfg.get_for(pk, n))) for pk, n in pairs],
                "active": self._cfg.active_preset}

    @staticmethod
    def _all_graph_names():
        from gui.graph_style import GRAPH_NAMES
        return list(GRAPH_NAMES)

    def _push_undo(self, key=None, names=None, all_tests=False):
        """Record the state before a change. Rapid edits of the same field
        (typing, spinning) merge into one undo step."""
        now = time.monotonic()
        if key is not None and self._last_push[0] == key and now - self._last_push[1] < 0.8:
            self._last_push = (key, now)
            return
        self._last_push = (key, now)
        self._undo.append(self._snapshot(names, all_tests))
        del self._undo[:-100]
        self._redo.clear()
        self._update_undo_buttons()

    def _commit(self, field, value):
        self._push_undo(key=(self._current, field))
        super()._commit(field, value)
        self._sync_preset_ui()
        self._thumb_timer.start()

    def _commit_many(self, values):
        """Several fields as one undo step (a drag, a reset)."""
        self._push_undo()
        s = self._cfg.get_for(self._current_plugin_key, self._current)
        s.update(values)
        self._cfg.set_for(self._current_plugin_key, self._current, s)
        self._after_external_change()

    def _after_external_change(self, rebuild_pane=True):
        self._sync_preset_ui()
        self._refresh_preview()
        if rebuild_pane:
            self._build_format_pane()
        self._rerender_timer.start()
        self._thumb_timer.start()

    def _restore(self, snap):
        for plugin, name, style in snap["styles"]:
            self._cfg.set_for(plugin, name, copy.deepcopy(style))
        self._cfg.active_preset = snap["active"]

    def _mirror(self, snap):
        """Current state of whatever `snap` covers (for the opposite stack)."""
        m = {"styles": [(pk, n, copy.deepcopy(self._cfg.get_for(pk, n)))
                        for pk, n, _s in snap["styles"]],
             "active": self._cfg.active_preset}
        return m

    def _do_undo(self):
        if not self._undo:
            return
        snap = self._undo.pop()
        self._redo.append(self._mirror(snap))
        self._restore(snap)
        self._last_push = (None, 0.0)
        self._update_undo_buttons()
        self._after_undo(snap)

    def _do_redo(self):
        if not self._redo:
            return
        snap = self._redo.pop()
        self._undo.append(self._mirror(snap))
        self._restore(snap)
        self._last_push = (None, 0.0)
        self._update_undo_buttons()
        self._after_undo(snap)

    def _after_undo(self, snap):
        names = [n for pk, n, _s in snap["styles"] if pk == self._current_plugin_key]
        if names and self._current not in names:
            self._select(names[0])
        self._after_external_change()
        QTimer.singleShot(0, self._render_all_thumbs)
        if self._rerender:
            try:
                self._rerender(None)
            except Exception:
                pass

    def _update_undo_buttons(self):
        if hasattr(self, "btn_undo"):
            self.btn_undo.setEnabled(bool(self._undo))
            self.btn_redo.setEnabled(bool(self._redo))

    # ── presets (each holds every graph of every test) ───────────────────
    def _reload_presets(self):
        self.cmb_preset.blockSignals(True)
        self.cmb_preset.clear()
        for name in self._cfg.all_preset_names():
            self.cmb_preset.addItem(name)
        self.cmb_preset.blockSignals(False)
        self._sync_preset_ui()

    def _sync_preset_ui(self):
        """Show the active preset, whether it has unsaved edits, and which
        preset actions make sense right now."""
        if not hasattr(self, "cmb_preset"):
            return
        active = self._cfg.active_preset
        self.cmb_preset.blockSignals(True)
        i = self.cmb_preset.findText(active)
        self.cmb_preset.setCurrentIndex(max(0, i))
        self.cmb_preset.blockSignals(False)
        edited = self._cfg.is_modified()
        if hasattr(self, "lbl_preset_state"):
            self.lbl_preset_state.setText("edited" if edited else "")
            builtin = self._cfg.is_builtin(active)
            self.btn_update_preset.setEnabled(edited and not builtin)
            self.btn_update_preset.setToolTip(
                "The Default preset can't be changed — use Save as new preset"
                if builtin else f"Save your changes into '{active}'")
            self.btn_delete_preset.setEnabled(not builtin)

    def _on_preset_pick(self, name):
        if not name or name == self._cfg.active_preset and not self._cfg.is_modified():
            return
        self._push_undo(all_tests=True)
        self._cfg.apply_preset(name)
        self._select(self._current)
        self._after_external_change()
        QTimer.singleShot(0, self._render_all_thumbs)
        if self._rerender:
            try:
                self._rerender(None)
            except Exception:
                pass

    def _update_preset(self):
        name = self._cfg.active_preset
        if self._cfg.is_builtin(name):
            return
        self._cfg.save_preset(name)
        self._persist_now()
        self._sync_preset_ui()

    def _save_preset_dialog(self):
        from PyQt5.QtWidgets import QInputDialog, QMessageBox
        name, ok = QInputDialog.getText(self, "Save as new preset",
                                        "Name for this preset (all graphs of every test):")
        name = (name or "").strip()
        if not ok or not name:
            return
        if self._cfg.is_builtin(name):
            QMessageBox.warning(self, "Name in use", f"'{name}' is a built-in preset. Pick another name.")
            return
        if name in self._cfg.custom_presets and QMessageBox.question(
                self, "Replace preset", f"A preset called '{name}' exists. Replace it?") != QMessageBox.Yes:
            return
        self._cfg.save_preset(name)
        self._reload_presets()
        self._persist_now()

    def _delete_preset(self):
        from PyQt5.QtWidgets import QMessageBox
        name = self._cfg.active_preset
        if self._cfg.is_builtin(name):
            return
        if QMessageBox.question(self, "Delete preset",
                                f"Delete the preset '{name}'? Your graphs keep their "
                                "current look.") != QMessageBox.Yes:
            return
        self._cfg.delete_preset(name)
        self._reload_presets()
        self._persist_now()

    def _reset_graph_undoable(self):
        """Reset graph = back to how the *active preset* draws this graph."""
        self._push_undo()
        self._cfg.set_for(self._current_plugin_key, self._current,
                          self._cfg.preset_style(self._cfg.active_preset,
                                                 self._current_plugin_key, self._current))
        self._after_external_change()

    def _reset_position(self):
        preset = self._cfg.preset_style(self._cfg.active_preset,
                                        self._current_plugin_key, self._current)
        vals = {k: preset.get(k, v) for k, v in POSITION_FIELDS.get(self._sel, {}).items()}
        if self._sel == "legend":
            vals["legend_loc"] = preset.get("legend_loc", "best")
        if vals:
            self._commit_many(vals)

    def _apply_to_all(self):
        """Copy the selected element's formatting to every graph of this test."""
        _label, rows = ELEMENTS[self._sel]
        fields = set()
        for f, _l, kind, _o in rows:
            if kind == "spines":
                fields.update(k for k, _ in SPINES)
            elif kind == "cmap":
                fields.update({"cmap", "cmap_custom_n", *CUSTOM_CMAP_STOPS})
            else:
                fields.add(f)
        fields -= {"title", "xlabel", "ylabel", "colorbar_label"}   # words stay per graph
        src = self._cfg.get_for(self._current_plugin_key, self._current)
        others = [n for n in self._plugin_graph_names if n != self._current]
        self._push_undo(names=[self._current] + others)
        for n in others:
            ok = self._allowed_fields(n)
            s = self._cfg.get_for(self._current_plugin_key, n)
            changed = False
            for f in fields & ok:
                if f in src:
                    s[f] = copy.deepcopy(src[f])
                    changed = True
            if changed:
                self._cfg.set_for(self._current_plugin_key, n, s)
        self._sync_preset_ui()
        QTimer.singleShot(0, self._render_all_thumbs)
        if self._rerender:
            try:
                self._rerender(None)
            except Exception:
                pass

    def _on_plugin_tab_changed(self, index):
        super()._on_plugin_tab_changed(index)
        self._sync_preset_ui()
        for i in range(self.list_graphs.count()):
            self.list_graphs.item(i).setIcon(QIcon())
        QTimer.singleShot(0, self._render_all_thumbs)

    # ── preview + element map ────────────────────────────────────────────
    def _setup_drag_handlers(self, ax):
        self._ax = ax      # interaction is handled by _on_press / _on_motion

    def _teardown_drag_handlers(self):
        pass

    def _refresh_preview(self):
        super()._refresh_preview()
        st = resolve_style(self._cfg.get_for(self._current_plugin_key, self._current), _fig_mode())
        try:
            apply_layout_overrides(self._fig, st, self._ax)
        except Exception:
            pass
        self._canvas.draw()
        self._collect_artists(st)
        self._update_overlay()

    def _collect_artists(self, st):
        """Map element keys → matplotlib artists of the freshly drawn chart."""
        from matplotlib.lines import Line2D
        from matplotlib.patches import Circle, Polygon, Rectangle
        ax = self._ax
        a = {"title": [ax.title] if ax.title.get_text() else [],
             "xlabel": [ax.xaxis.label] if ax.xaxis.label.get_text() else [],
             "ylabel": [ax.yaxis.label] if ax.yaxis.label.get_text() else [],
             "ticks": [t for t in ax.get_xticklabels() + ax.get_yticklabels() if t.get_text()],
             "legend": [ax.get_legend()] if ax.get_legend() is not None else [],
             "colorbar": [], "cells": [], "series": [], "arena": [],
             "center": [], "pins": [], "grid": []}
        cax = self._drag_artists.get("cax")
        if cax is not None:
            a["colorbar"] = [cax]
        a["cells"] = list(self._drag_artists.get("cell_texts") or [])
        grid_col = str(st.get("grid_color", "")).lower()
        for ln in ax.lines:
            if not isinstance(ln, Line2D):
                continue
            col = str(ln.get_color()).lower()
            if abs(ln.get_linewidth() - 0.8) < 1e-6 and col == grid_col:
                a["grid"].append(ln)
            else:
                a["series"].append(ln)
        a["series"] += list(ax.images)
        a["pins"] = list(ax.collections)
        for pt in ax.patches:
            if isinstance(pt, Rectangle) and not pt.get_fill() and pt.get_linestyle() in ("--", "dashed"):
                a["center"].append(pt)
            elif isinstance(pt, (Polygon, Circle, Rectangle)) and not pt.get_fill():
                a["arena"].append(pt)
            elif isinstance(pt, Rectangle) and pt.get_fill():
                a["series"].append(pt)      # bars, histogram bins, grid cells
        self._artists = a

    # ── overlay (selection outline) ──────────────────────────────────────
    def _to_qt(self, bbox):
        r = getattr(self._canvas, "device_pixel_ratio", 1.0) or 1.0
        H = self._fig.bbox.height
        return QRectF(bbox.x0 / r, (H - bbox.y1) / r, bbox.width / r, bbox.height / r)

    def _element_bboxes(self, key):
        rend = self._canvas.get_renderer()
        if key == "plot":
            return [self._ax.bbox]
        if key == "chart":
            return [self._fig.bbox]
        out = []
        for art in self._artists.get(key, []):
            try:
                bb = art.bbox if key == "colorbar" else art.get_window_extent(rend)
                if bb.width > 0 or bb.height > 0:
                    out.append(bb)
            except Exception:
                pass
        if key in ("series", "arena", "ticks", "cells", "pins") and len(out) > 1:
            from matplotlib.transforms import Bbox
            out = [Bbox.union(out)]
        return out

    def _update_overlay(self):
        ov = getattr(self, "_overlay", None)
        if ov is None:
            return
        ov.setGeometry(self._canvas.rect())
        ov.rects = [self._to_qt(b) for b in self._element_bboxes(self._sel)] \
            if self._sel != "chart" else []
        ov.handles = self._sel in RESIZABLE
        ov.raise_()
        ov.update()

    def _set_selection(self, key):
        if not key:
            return
        self._sel = key
        self._update_overlay()
        self._build_format_pane()

    # ── hit testing ──────────────────────────────────────────────────────
    def _hit(self, ev):
        a = self._artists
        for key in ("legend", "title", "xlabel", "ylabel", "cells"):
            for art in a.get(key, []):
                try:
                    if art.contains(ev)[0]:
                        return key
                except Exception:
                    pass
        for cax in a.get("colorbar", []):
            if cax.bbox.contains(ev.x, ev.y):
                return "colorbar"
        for art in a.get("pins", []):
            try:
                if art.contains(ev)[0]:
                    return "pins"
            except Exception:
                pass
        for key in ("center", "arena"):
            for pt in a.get(key, []):
                if self._near_outline(pt, ev.x, ev.y):
                    return key
        for art in a.get("series", []):
            try:
                if art.contains(ev)[0]:
                    return "series"
            except Exception:
                pass
        for art in a.get("ticks", []):
            try:
                if art.contains(ev)[0]:
                    return "ticks"
            except Exception:
                pass
        if self._ax.bbox.contains(ev.x, ev.y):
            return "plot"
        return "chart"

    @staticmethod
    def _near_outline(patch, x, y, tol=5.0):
        import numpy as np
        try:   # outline in display pixels (patch transform + data transform)
            pts = patch.get_transform().transform(patch.get_path().vertices)
        except Exception:
            return False
        if len(pts) < 2:
            return False
        a, b = pts[:-1], pts[1:]
        d = b - a
        L = (d ** 2).sum(axis=1)
        L[L == 0] = 1e-9
        t = np.clip(((x - a[:, 0]) * d[:, 0] + (y - a[:, 1]) * d[:, 1]) / L, 0, 1)
        px, py = a[:, 0] + t * d[:, 0], a[:, 1] + t * d[:, 1]
        return bool(np.min(np.hypot(px - x, py - y)) <= tol)

    def _plot_handle_at(self, ev):
        """Resize handle under the mouse on the selected plot area / colour
        bar → the edges it moves ('lt', 'r', …), else None."""
        if self._sel not in RESIZABLE:
            return None
        bbs = self._element_bboxes(self._sel)
        if not bbs:
            return None
        r = getattr(self._canvas, "device_pixel_ratio", 1.0) or 1.0
        q = self._to_qt(bbs[0])
        H = self._fig.bbox.height
        mx, my = ev.x / r, (H - ev.y) / r
        for i, pt in enumerate(_handle_points(q)):
            if abs(pt.x() - mx) <= HANDLE and abs(pt.y() - my) <= HANDLE:
                return _HANDLE_EDGES[i]
        return None

    # ── mouse: select + drag ─────────────────────────────────────────────
    def _on_press(self, ev):
        if ev.button != 1 or ev.x is None:
            return
        if getattr(self, "_inline", None):       # click on the chart = save
            self._finish_inline_edit(save=True)
        if getattr(ev, "dblclick", False):
            target = self._text_target(ev)
            if target is not None:
                self._drag = None
                self._start_inline_edit(*target)
                return
        edges = self._plot_handle_at(ev)
        key = self._sel if edges else self._hit(ev)
        if key != self._sel:
            self._set_selection(key)
        if key in DRAGGABLE:
            self._drag = self._start_drag(key, ev, edges)
        else:
            self._drag = None

    # ── inline text editing (double-click a text on the chart) ───────────
    def _text_target(self, ev):
        """(field, legend_key, artist) for the editable text under the
        mouse, or None. field is the style field that holds the text;
        legend_key is the entry's default text for legend entries."""
        allowed = self._allowed_fields(self._current)
        ax = self._ax

        def hit(art):
            try:
                return bool(art is not None and art.get_visible()
                            and art.get_text() and art.contains(ev)[0])
            except Exception:
                return False

        for field, art in (("title", ax.title), ("xlabel", ax.xaxis.label),
                           ("ylabel", ax.yaxis.label)):
            if field in allowed and hit(art):
                return field, None, art
        leg = ax.get_legend()
        if leg is not None:
            origs = getattr(leg, "_orig_labels", None) or \
                [t.get_text() for t in leg.get_texts()]
            for t, orig in zip(leg.get_texts(), origs):
                if hit(t):
                    return "legend_labels", orig, t
        cax = self._drag_artists.get("cax")
        if cax is not None and "colorbar_label" in allowed and hit(cax.xaxis.label):
            return "colorbar_label", None, cax.xaxis.label
        return None

    def _start_inline_edit(self, field, legend_key, art):
        """Put a text box over `art` on the chart. Enter / clicking away
        saves (one undo step), Esc cancels."""
        self._finish_inline_edit(save=False)
        try:
            bb = art.get_window_extent(self._canvas.get_renderer())
        except Exception:
            return
        r = self._to_qt(bb)
        ed = _InlineEdit(self._canvas)
        ed.setText(art.get_text())
        ed.setAlignment(Qt.AlignCenter)
        # Solid box, and hide the chart text underneath while typing (the
        # old text used to show through behind the new one).
        ed.setStyleSheet(
            f"QLineEdit {{ background: {theme.SURFACE}; color: {theme.TEXT};"
            f" border: 1.5px solid {theme.ACCENT}; border-radius: 4px;"
            f" padding: 0 6px; }}")
        art.set_visible(False)
        self._canvas.draw()
        w = max(160, int(r.width()) + 40) if r.width() > r.height() else 200
        h = max(26, min(40, int(min(r.width(), r.height())) + 10))
        cx, cy = r.center().x(), r.center().y()
        x = int(min(max(0, cx - w / 2), self._canvas.width() - w))
        y = int(min(max(0, cy - h / 2), self._canvas.height() - h))
        ed.setGeometry(x, y, w, h)
        ed.setToolTip("Enter or click anywhere else to save, Esc to cancel")
        self._inline = (ed, field, legend_key, art)
        ed.committed.connect(lambda: self._finish_inline_edit(save=True))
        ed.cancelled.connect(lambda: self._finish_inline_edit(save=False))
        ed.show()
        ed.setFocus()
        ed.selectAll()
        # Watch clicks only after the double-click that opened the box has
        # been fully delivered.
        flt = _ClickAway(ed, lambda: self._finish_inline_edit(save=True))
        self._inline_filter = flt
        QTimer.singleShot(0, lambda f=flt: self._inline_filter is f
                          and QApplication.instance().installEventFilter(f))

    def _finish_inline_edit(self, save):
        inline, self._inline = getattr(self, "_inline", None), None
        if not inline:
            return
        ed, field, legend_key, art = inline
        flt, self._inline_filter = getattr(self, "_inline_filter", None), None
        if flt is not None:
            QApplication.instance().removeEventFilter(flt)
        text = ed.text()
        ed.hide()
        ed.deleteLater()
        try:
            art.set_visible(True)
        except Exception:
            pass
        if not (save and self._commit_text(field, legend_key, text)):
            self._canvas.draw()          # nothing saved: just show the text again

    def _commit_text(self, field, legend_key, text):
        """Save an edited chart text (one undo step). Returns True if
        something changed. The format pane is NOT rebuilt (this can run in
        the middle of a click on one of its controls) — its text boxes are
        updated in place instead."""
        st = self._cfg.get_for(self._current_plugin_key, self._current)
        if field == "legend_labels":
            m = dict(st.get("legend_labels") or {})
            if text == legend_key or not text.strip():
                m.pop(legend_key, None)          # back to the default text
            else:
                m[legend_key] = text
            if m == (st.get("legend_labels") or {}):
                return False
            values = {"legend_labels": m}
        elif text != st.get(field, ""):
            values = {field: text}
        else:
            return False
        self._push_undo()
        st.update(values)
        self._cfg.set_for(self._current_plugin_key, self._current, st)
        self._after_external_change(rebuild_pane=False)
        self._sync_text_boxes(field, legend_key, text)
        return True

    def _sync_text_boxes(self, field, legend_key, text):
        """Show a text saved on the chart in the matching pane text box."""
        if field == "legend_labels":
            w = (getattr(self, "_legend_edits", None) or {}).get(legend_key)
            text = text if text.strip() else legend_key
        else:
            w = self._editors.get(field)
        if isinstance(w, QLineEdit) and w.text() != text:
            w.blockSignals(True)
            w.setText(text)
            w.blockSignals(False)

    def _add_legend_label_rows(self, form):
        """One text box per legend entry (same thing as double-clicking
        the entry on the chart). Returns the number of rows added."""
        leg = self._ax.get_legend() if getattr(self, "_ax", None) is not None else None
        if leg is None:
            return 0
        origs = getattr(leg, "_orig_labels", None) or [t.get_text() for t in leg.get_texts()]
        mapping = self._cfg.get_for(self._current_plugin_key,
                                    self._current).get("legend_labels") or {}
        self._legend_edits = {}
        for i, orig in enumerate(origs):
            le = QLineEdit(mapping.get(orig, orig))
            self._legend_edits[orig] = le
            le.setPlaceholderText(orig)
            le.setToolTip(f"Legend text for “{orig}” (empty = default)")
            le.editingFinished.connect(
                lambda w=le, o=orig: self._commit_text("legend_labels", o, w.text()))
            form.addRow(QLabel(f"Entry {i + 1} text"), le)
        return len(origs)

    def _snap_guides(self, key):
        """Guide positions (display px) the dragged element can snap to:
        chart edges + middle, plot-area edges + middle, other elements."""
        W, H = self._fig.bbox.width, self._fig.bbox.height
        gx, gy = [0.0, W / 2.0, W], [0.0, H / 2.0, H]
        boxes = []
        if key != "plot":
            boxes.append(self._ax.bbox)
        for other in ("title", "xlabel", "ylabel", "legend", "colorbar"):
            if other != key:
                boxes += self._element_bboxes(other)
        for b in boxes:
            gx += [b.x0, (b.x0 + b.x1) / 2.0, b.x1]
            gy += [b.y0, (b.y0 + b.y1) / 2.0, b.y1]
        return gx, gy

    @staticmethod
    def _best_snap(points, guides):
        """Smallest shift that puts one of `points` on one of `guides`."""
        best = None
        for p in points:
            for g in guides:
                diff = g - p
                if abs(diff) <= SNAP_PX and (best is None or abs(diff) < abs(best[0])):
                    best = (diff, g)
        return best

    def _apply_snap(self, d, dx, dy):
        """Adjust a drag delta so edges / middles land on guides; returns the
        snapped delta and records the guide lines to draw."""
        from PyQt5.QtWidgets import QApplication
        self._overlay.guides = []
        if (not self.chk_snap.isChecked() or d["key"] == "cells" or "bb0" not in d
                or QApplication.keyboardModifiers() & Qt.AltModifier):
            return dx, dy
        b = d["bb0"]
        e = d.get("edges")
        if d["key"] in RESIZABLE and e:   # resizing: only the edges that move
            xs = ([b.x0 + dx] if "l" in e else []) + ([b.x1 + dx] if "r" in e else [])
            ys = ([b.y0 + dy] if "b" in e else []) + ([b.y1 + dy] if "t" in e else [])
        else:
            xs = [b.x0 + dx, (b.x0 + b.x1) / 2.0 + dx, b.x1 + dx]
            ys = [b.y0 + dy, (b.y0 + b.y1) / 2.0 + dy, b.y1 + dy]
        gx, gy = d["guides"]
        r = getattr(self._canvas, "device_pixel_ratio", 1.0) or 1.0
        H = self._fig.bbox.height
        sx = self._best_snap(xs, gx)
        if sx:
            dx += sx[0]
            self._overlay.guides.append(("v", sx[1] / r))
        sy = self._best_snap(ys, gy)
        if sy:
            dy += sy[0]
            self._overlay.guides.append(("h", (H - sy[1]) / r))
        return dx, dy

    def _start_drag(self, key, ev, edges):
        from matplotlib.transforms import Bbox
        d = {"key": key, "x0": ev.x, "y0": ev.y, "moved": False, "edges": edges}
        bbs = self._element_bboxes(key)
        if bbs:
            d["bb0"] = Bbox(bbs[0].get_points().copy())
            d["guides"] = self._snap_guides(key)
        ax, fig = self._ax, self._fig
        if key in ("title", "xlabel", "ylabel"):
            art = self._artists[key][0]
            d["art"], d["tf"] = art, art.get_transform()
        elif key == "legend":
            leg = self._artists["legend"][0]
            bb = leg.get_window_extent(self._canvas.get_renderer())
            ll = ax.transAxes.inverted().transform((bb.x0, bb.y0))
            pad_px = leg.borderaxespad * leg._fontsize * fig.dpi / 72.0
            d["art"] = leg
            d["anchor"] = (ll[0] - pad_px / ax.bbox.width, ll[1] - pad_px / ax.bbox.height)
            st0 = self._cfg.get_for(self._current_plugin_key, self._current)
            d["font0"] = float(st0.get("legend_fontsize", 8))
            d["mscale0"] = float(st0.get("legend_markerscale", 1.0) or 1.0)
            d["pos0"] = {k: st0.get(k) for k in
                         ("legend_loc", "legend_x_offset", "legend_y_offset")}
            d["bbw0"], d["bbh0"] = bb.width, bb.height
        elif key == "colorbar":
            d["art"] = self._artists["colorbar"][0]
            d["pos"] = d["art"].get_position()
        elif key == "plot":
            d["pos"] = ax.get_position()
        elif key == "cells":
            d["cells"] = [(t, t.get_position()) for t in self._artists["cells"]]
        return d

    def _on_motion(self, ev):
        if ev.x is None:
            return
        d = self._drag
        if d is None:
            self._set_hover_cursor(ev)
            return
        dx, dy = ev.x - d["x0"], ev.y - d["y0"]
        if not d["moved"] and abs(dx) + abs(dy) < DRAG_START:
            return
        d["moved"] = True
        dx, dy = self._apply_snap(d, dx, dy)
        # Anywhere on the chart — outside the plot area too — but never off it.
        b = d.get("bb0")
        if b is not None and not (d["key"] in RESIZABLE and d.get("edges")):
            W0, H0 = self._fig.bbox.width, self._fig.bbox.height
            dx = min(max(dx, -b.x0), W0 - b.x1)
            dy = min(max(dy, -b.y0), H0 - b.y1)
        fig, ax = self._fig, self._ax
        W, H = fig.bbox.width, fig.bbox.height
        key = d["key"]
        if key in ("title", "xlabel", "ylabel"):
            d["art"].set_transform(d["tf"] + ScaledTranslation(dx / fig.dpi, dy / fig.dpi,
                                                               fig.dpi_scale_trans))
        elif key == "legend" and d.get("edges"):
            if self._resize_legend_live(d, dx, dy):
                return                       # preview was rebuilt
        elif key == "legend":
            ax_w, ax_h = ax.bbox.width, ax.bbox.height
            d["new"] = (d["anchor"][0] + dx / ax_w, d["anchor"][1] + dy / ax_h)
            leg = d["art"]
            leg.set_bbox_to_anchor(d["new"], transform=ax.transAxes)
            try:
                leg.set_loc("lower left")
            except Exception:
                leg._loc = 3
        elif key == "colorbar":
            p = d["pos"]
            e = d["edges"]
            if not e:
                d["art"].set_position([p.x0 + dx / W, p.y0 + dy / H, p.width, p.height])
            else:
                x0, y0, x1, y1 = p.x0, p.y0, p.x1, p.y1
                if "l" in e:
                    x0 += dx / W
                if "r" in e:
                    x1 += dx / W
                if "b" in e:
                    y0 += dy / H
                if "t" in e:
                    y1 += dy / H
                w, h = x1 - x0, y1 - y0
                if CB_W_RANGE[0] <= w <= CB_W_RANGE[1] and CB_H_RANGE[0] <= h <= CB_H_RANGE[1]:
                    d["art"].set_position([x0, y0, w, h])
                    d["rect"] = (x0, y0, w, h)
        elif key == "plot":
            p = d["pos"]
            fx, fy = dx / W, dy / H
            x0, y0, x1, y1 = p.x0, p.y0, p.x1, p.y1
            e = d["edges"] or "lbrt"        # dragging inside = move the whole area
            if "l" in e:
                x0 += fx
            if "r" in e:
                x1 += fx
            if "b" in e:
                y0 += fy
            if "t" in e:
                y1 += fy
            if x1 - x0 > 0.08 and y1 - y0 > 0.08:
                ax.set_position([x0, y0, x1 - x0, y1 - y0])
        elif key == "cells":
            inv = ax.transData.inverted()
            (ax0, ay0), (ax1, ay1) = inv.transform([(d["x0"], d["y0"]), (ev.x, ev.y)])
            d["ddata"] = (ax1 - ax0, ay1 - ay0)
            for t, (px, py) in d["cells"]:
                t.set_position((px + ax1 - ax0, py + ay1 - ay0))
        d["dx"], d["dy"] = dx, dy
        self._canvas.draw_idle()
        self._canvas.draw()
        self._update_overlay()

    def _resize_legend_live(self, d, dx, dy):
        """Legend handle drag: scale text + markers by how much the
        dragged edge(s) grew. Redraws the preview live (style values set
        without an undo step — _on_release commits them). Returns True if
        the preview was rebuilt."""
        e = d["edges"]
        w0, h0 = max(1.0, d["bbw0"]), max(1.0, d["bbh0"])
        w = w0 + (dx if "r" in e else 0.0) - (dx if "l" in e else 0.0)
        h = h0 + (dy if "t" in e else 0.0) - (dy if "b" in e else 0.0)
        sx, sy = max(0.05, w / w0), max(0.05, h / h0)
        horiz, vert = ("l" in e or "r" in e), ("t" in e or "b" in e)
        scale = (sx * sy) ** 0.5 if (horiz and vert) else (sx if horiz else sy)
        lo, hi = LEGEND_FONT_RANGE
        font = min(hi, max(lo, round(d["font0"] * scale * 2.0) / 2.0))   # 0.5 pt steps
        mscale = round(d["mscale0"] * font / d["font0"], 3)
        if d.get("size") == (font, mscale):
            return False
        d["size"] = (font, mscale)
        st = self._cfg.get_for(self._current_plugin_key, self._current)
        st.update({"legend_fontsize": font, "legend_markerscale": mscale})
        self._cfg.set_for(self._current_plugin_key, self._current, st)
        self._refresh_preview()
        self._pin_resized_legend(d)
        return True

    def _pin_resized_legend(self, d):
        """Keep the side opposite the dragged handle where it was (like
        resizing a box in PowerPoint): left handle grows left, bottom handle
        grows down, a corner grows away from the opposite corner; the axis
        that isn't dragged stays centred. Done by pinning the legend at a
        custom position (its lower-left anchor, like a move-drag writes)."""
        leg = self._ax.get_legend()
        b0 = d.get("bb0")
        if leg is None or b0 is None:
            return
        ax, fig = self._ax, self._fig
        bb = leg.get_window_extent(self._canvas.get_renderer())
        w1, h1 = bb.width, bb.height
        e = d["edges"]
        if "l" in e:
            x0 = b0.x1 - w1                      # right edge fixed
        elif "r" in e:
            x0 = b0.x0                           # left edge fixed
        else:
            x0 = (b0.x0 + b0.x1 - w1) / 2.0      # centred
        if "b" in e:
            y0 = b0.y1 - h1                      # top edge fixed
        elif "t" in e:
            y0 = b0.y0                           # bottom edge fixed
        else:
            y0 = (b0.y0 + b0.y1 - h1) / 2.0
        ll = ax.transAxes.inverted().transform((x0, y0))
        pad_px = leg.borderaxespad * leg._fontsize * fig.dpi / 72.0
        anchor = (max(-1.0, min(2.0, ll[0] - pad_px / ax.bbox.width)),
                  max(-1.0, min(2.0, ll[1] - pad_px / ax.bbox.height)))
        d["anchor_new"] = anchor
        st = self._cfg.get_for(self._current_plugin_key, self._current)
        st.update({"legend_loc": "custom", "legend_x_offset": anchor[0],
                   "legend_y_offset": anchor[1]})
        self._cfg.set_for(self._current_plugin_key, self._current, st)
        leg.set_bbox_to_anchor(anchor, transform=ax.transAxes)
        try:
            leg.set_loc("lower left")
        except Exception:
            leg._loc = 3
        self._canvas.draw()
        self._update_overlay()

    def _on_release(self, ev):
        d, self._drag = self._drag, None
        if self._overlay.guides:
            self._overlay.guides = []
            self._overlay.update()
        if not d or not d["moved"]:
            return
        st = self._cfg.get_for(self._current_plugin_key, self._current)
        fig = self._fig
        W, H = fig.bbox.width, fig.bbox.height
        dx, dy = d.get("dx", 0.0), d.get("dy", 0.0)
        pt = 72.0 / fig.dpi
        key = d["key"]
        vals = {}
        if key == "title":
            vals = {"title_dx": float(st.get("title_dx", 0.0)) + dx * pt,
                    "title_pad": float(st.get("title_pad", 0.0)) + dy * pt}
        elif key in ("xlabel", "ylabel"):
            vals = {f"{key}_dx": float(st.get(f"{key}_dx", 0.0)) + dx * pt,
                    f"{key}_dy": float(st.get(f"{key}_dy", 0.0)) + dy * pt}
        elif key == "legend" and d.get("edges"):
            if "size" in d:
                # Put the pre-drag values back so the commit is one clean
                # undo step from the original size.
                st.update({"legend_fontsize": d["font0"],
                           "legend_markerscale": d["mscale0"]})
                st.update({k: v for k, v in d["pos0"].items() if v is not None})
                self._cfg.set_for(self._current_plugin_key, self._current, st)
                vals = {"legend_fontsize": d["size"][0],
                        "legend_markerscale": d["size"][1]}
                if "anchor_new" in d:
                    vals.update({"legend_loc": "custom",
                                 "legend_x_offset": d["anchor_new"][0],
                                 "legend_y_offset": d["anchor_new"][1]})
        elif key == "legend" and "new" in d:
            vals = {"legend_loc": "custom",
                    "legend_x_offset": max(-1.0, min(2.0, d["new"][0])),
                    "legend_y_offset": max(-1.0, min(2.0, d["new"][1]))}
        elif key == "colorbar" and d.get("edges"):
            if "rect" in d:
                # stored as offsets from the default rect (0.06, 0.06, w, h)
                x0, y0, w, h = d["rect"]
                vals = {"colorbar_x": round(float(x0) - 0.06, 4),
                        "colorbar_y": round(float(y0) - 0.06, 4),
                        "colorbar_w": round(float(w) - CB_BASE_W, 4),
                        "colorbar_h": round(float(h) - CB_BASE_H, 4)}
        elif key == "colorbar":
            vals = {"colorbar_x": float(st.get("colorbar_x", 0.0)) + dx / W,
                    "colorbar_y": float(st.get("colorbar_y", 0.0)) + dy / H}
        elif key == "plot":
            fx, fy = dx / W, dy / H
            e = d["edges"] or "lbrt"
            vals = {k: float(st.get(k, 0.0)) for k in ("plot_dl", "plot_db", "plot_dr", "plot_dt")}
            if "l" in e:
                vals["plot_dl"] += fx
            if "r" in e:
                vals["plot_dr"] += fx
            if "b" in e:
                vals["plot_db"] += fy
            if "t" in e:
                vals["plot_dt"] += fy
        elif key == "cells" and "ddata" in d:
            ddx, ddy = d["ddata"]
            vals = {"cell_label_dx": int(round(float(st.get("cell_label_dx", 0)) + ddx * 100)),
                    "cell_label_dy": int(round(float(st.get("cell_label_dy", 0)) + ddy * 100))}
        if vals:
            self._commit_many(vals)

    def _set_hover_cursor(self, ev):
        edges = self._plot_handle_at(ev)
        if edges:
            shape = {"l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor, "t": Qt.SizeVerCursor,
                     "b": Qt.SizeVerCursor, "lt": Qt.SizeFDiagCursor, "rb": Qt.SizeFDiagCursor,
                     "rt": Qt.SizeBDiagCursor, "lb": Qt.SizeBDiagCursor}[edges]
        else:
            key = self._hit(ev)
            shape = Qt.SizeAllCursor if (key in DRAGGABLE and key == self._sel) else \
                Qt.PointingHandCursor if key != "chart" else Qt.ArrowCursor
        self._canvas.setCursor(shape)

    # ── thumbnails ───────────────────────────────────────────────────────
    def _grab_canvas(self):
        self._canvas.draw()
        w, h = self._canvas.get_width_height(physical=True)
        img = QImage(bytes(self._canvas.buffer_rgba()), w, h, QImage.Format_RGBA8888).copy()
        return QPixmap.fromImage(img).scaled(300, 236, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _render_thumb(self, name, restore=True):
        if self._thumb_busy:
            return
        items = self.list_graphs.findItems(name, Qt.MatchExactly)
        if not items:
            return
        self._thumb_busy = True
        cur = self._current
        try:
            if name != cur:
                self._current = name
                GraphStyleDialog._refresh_preview(self)
                st = resolve_style(self._cfg.get_for(self._current_plugin_key, name), _fig_mode())
                apply_layout_overrides(self._fig, st, self._ax)
            items[0].setIcon(QIcon(self._grab_canvas()))
        except Exception:
            pass
        finally:
            self._current = cur
            self._thumb_busy = False
            if name != cur and restore:
                self._refresh_preview()

    def _render_all_thumbs(self):
        others = [n for n in self._plugin_graph_names if n != self._current]
        for n in others:
            self._render_thumb(n, restore=False)
        if others:
            self._refresh_preview()      # back to the graph being edited
        self._update_current_thumb()

    def _update_current_thumb(self):
        items = self.list_graphs.findItems(self._current, Qt.MatchExactly)
        if items:
            items[0].setIcon(QIcon(self._grab_canvas()))
        self._update_overlay()

    # ── export preview ───────────────────────────────────────────────────
    def _on_export_preview(self, on):
        """Draw with the export palette (light) instead of the app theme."""
        from gui.graph_style_dialog import set_fig_mode_override
        set_fig_mode_override("export" if on else None)
        self._export_banner.setVisible(on)
        self._refresh_preview()
        self._build_format_pane()          # colour swatches show export colours
        QTimer.singleShot(0, self._render_all_thumbs)

    # ── close = keep (changes are already live) ──────────────────────────
    def reject(self):
        self._accept()

    def _accept(self):
        from gui.graph_style_dialog import set_fig_mode_override
        set_fig_mode_override(None)        # never leak into the next editor
        self._persist_now()
        super()._accept()
