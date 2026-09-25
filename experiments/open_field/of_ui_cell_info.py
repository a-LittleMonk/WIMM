"""Cell Info tab UI + region presets.

Builds the tab where the user labels each of the 16 grid cells with a
region (Corner / Edge / Middle / Custom) and shows a region-aggregated
readout after tracking. Min-dwell tuner lives in Step 5 — single source
of truth for OF + Y-Maze.
"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
)

from gui import theme


CELL_CATEGORIES = ["Corner", "Side", "Middle", "Custom"]
# Standard 4x4 preset: corners 1/4/13/16, middle 6/7/10/11, rest = side.
CELL_PRESET_STANDARD = {
    1: "Corner", 4: "Corner", 13: "Corner", 16: "Corner",
    2: "Side",   3: "Side",   5: "Side",   8: "Side",
    9: "Side",   12: "Side",  14: "Side",  15: "Side",
    6: "Middle", 7: "Middle", 10: "Middle", 11: "Middle",
}
CELL_HIGHLIGHT_PRESETS = [
    "#C9D1DE", "#E4D3AE", "#5DBB85", "#E8C547", "#D36BA6", "#FFFFFF",
]


class _CellTile(QWidget):
    """Category tile of the Cell-info grid: number top-left, category bottom.
    Click cycles the category (the hidden combo stays the data holder)."""
    clicked = pyqtSignal()

    _TONES = {"Corner": ("WARN_BG", "WARN"), "Side": ("SURFACE_2", "TEXT_2"),
              "Middle": ("OK_BG", "OK"), "Custom": ("ACCENT_BG", "ACCENT")}

    def __init__(self, number, parent=None):
        super().__init__(parent)
        self._n, self._cat = number, "Side"
        self.setMinimumHeight(74)
        self.setCursor(Qt.PointingHandCursor)
        theme.notifier.changed.connect(lambda _m: self.update())

    def set_category(self, cat):
        self._cat = cat
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _e):
        from PyQt5.QtCore import QRectF
        from PyQt5.QtGui import QColor, QFont, QPainter, QPen
        bg, fg = self._TONES.get(self._cat, ("SURFACE_2", "TEXT_2"))
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(theme.BORDER_2), 1))
        p.setBrush(QColor(getattr(theme, bg)))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 3, 3)
        f = QFont(theme.mono_family())
        f.setPixelSize(10)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT_2))
        p.drawText(QRectF(8, 6, self.width() - 16, 14), Qt.AlignLeft | Qt.AlignVCenter, str(self._n))
        f2 = QFont(theme.sans_family())
        f2.setPixelSize(11)
        f2.setWeight(QFont.Medium)
        p.setFont(f2)
        p.setPen(QColor(getattr(theme, fg)))
        p.drawText(QRectF(8, self.height() - 22, self.width() - 16, 16),
                   Qt.AlignLeft | Qt.AlignVCenter, self._cat)


def _build_cell_info_tab(host):
    """Tab where the user labels each of the 16 cells with a category
    (Corner / Side / Middle / Custom) so summary metrics can be
    aggregated by region."""
    from gui.out_widgets import OutPanel
    w = QWidget()
    outer = QHBoxLayout(w)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(16)

    # ── Left: category grid ───────────────────────────────────────────────
    left = OutPanel("Cell categories · 4 × 4")
    left.setMaximumWidth(440)
    hint = QLabel("click a cell to relabel")
    theme.set_tone(hint, "faint", "font-size:11px;")
    left._bar_layout.addWidget(hint)
    inner = QVBoxLayout()
    inner.setContentsMargins(14, 12, 14, 14)
    inner.setSpacing(12)
    left.body.addLayout(inner)

    grid = QGridLayout()
    grid.setSpacing(4)
    host._cell_combo = {}  # cid → QComboBox (hidden data holder)
    host._cell_tiles = {}
    hidden_box = QWidget()
    hidden_box.hide()
    hl = QVBoxLayout(hidden_box)
    for idx in range(16):
        row, col = idx // 4, idx % 4
        cid = idx + 1
        cb = QComboBox()
        cb.addItems(host.CELL_CATEGORIES)
        host._cell_combo[cid] = cb
        hl.addWidget(cb)
        tile = _CellTile(cid)
        host._cell_tiles[cid] = tile

        def _cycle(_=None, c=cb):
            c.setCurrentIndex((c.currentIndex() + 1) % c.count())
        tile.clicked.connect(_cycle)
        cb.currentTextChanged.connect(lambda txt, tl=tile: tl.set_category(txt))
        grid.addWidget(tile, row, col)
    for c in range(4):
        grid.setColumnStretch(c, 1)
    inner.addLayout(grid)
    inner.addWidget(hidden_box)

    preset_row = QHBoxLayout()
    preset_row.setSpacing(6)
    b_std = QPushButton("Apply standard 4×4")
    b_std.setFixedHeight(26)
    b_std.setToolTip("Corners=1,4,13,16  Middle=6,7,10,11  Side=others")
    b_std.clicked.connect(lambda: host._apply_cell_preset(host.CELL_PRESET_STANDARD))
    preset_row.addWidget(b_std)
    b_clear = QPushButton("Clear all → Custom")
    b_clear.setProperty("flat", True)
    b_clear.setFixedHeight(26)
    b_clear.clicked.connect(
        lambda: host._apply_cell_preset({i: "Custom" for i in range(1, 17)})
    )
    preset_row.addWidget(b_clear)
    preset_row.addStretch()
    inner.addLayout(preset_row)
    outer.addWidget(left, 0, Qt.AlignTop)

    # ── Right: aggregated by region ────────────────────────────────────────
    right = OutPanel("Aggregated by region")
    from gui.table_copy import enable_excel_copy
    host._table_cell_agg = QTableWidget()
    host._table_cell_agg.setProperty("out", True)
    host._table_cell_agg.setShowGrid(False)
    host._table_cell_agg.setFrameShape(QFrame.NoFrame)
    host._table_cell_agg.verticalHeader().setVisible(False)
    host._table_cell_agg.verticalHeader().setDefaultSectionSize(30)
    host._table_cell_agg.setEditTriggers(QTableWidget.NoEditTriggers)
    host._table_cell_agg.setColumnCount(5)
    host._table_cell_agg.setHorizontalHeaderLabels(
        ["Region", "Cells", "Time (s)", "Entries (#)", "% time"]
    )
    enable_excel_copy(host._table_cell_agg)
    hdr = host._table_cell_agg.horizontalHeader()
    hdr.setSectionResizeMode(QHeaderView.Stretch)
    hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host._table_cell_agg.setMaximumHeight(34 + 30 * 4)
    right.body.addWidget(host._table_cell_agg)
    host._lbl_cell_warn = QLabel("")
    host._lbl_cell_warn.setWordWrap(True)
    host._lbl_cell_warn.setContentsMargins(14, 10, 14, 10)
    theme.set_tone(host._lbl_cell_warn, "warn", "font-size:11px;")
    right.body.addWidget(host._lbl_cell_warn)
    outer.addWidget(right, 1, Qt.AlignTop)

    # Apply default preset.
    host._apply_cell_preset(host.CELL_PRESET_STANDARD)
    # Refresh aggregated table whenever any combo changes.
    for cb in host._cell_combo.values():
        cb.currentIndexChanged.connect(host._refresh_cell_aggregation)
    theme.notifier.changed.connect(lambda _m: host._refresh_cell_aggregation())
    return w


def _apply_cell_preset(host, mapping):
    if not hasattr(host, "_cell_combo"):
        return
    for cid, cb in host._cell_combo.items():
        cat = mapping.get(cid, "Custom")
        i = cb.findText(cat)
        if i >= 0:
            cb.setCurrentIndex(i)
    host._refresh_cell_aggregation()


def get_cell_categories(host):
    """Returns dict cid → category string (1..16)."""
    if not hasattr(host, "_cell_combo"):
        return {}
    return {cid: cb.currentText() for cid, cb in host._cell_combo.items()}


def set_cell_categories(host, mapping):
    if not hasattr(host, "_cell_combo") or not mapping:
        return
    # Legacy: older configs used "Edge" for the perimeter cells.
    legacy_remap = {"Edge": "Side"}
    for cid, cat in mapping.items():
        try:
            cid_i = int(cid)
        except (TypeError, ValueError):
            continue
        cb = host._cell_combo.get(cid_i)
        if cb:
            cat_str = legacy_remap.get(str(cat), str(cat))
            i = cb.findText(cat_str)
            if i >= 0:
                cb.setCurrentIndex(i)
    host._refresh_cell_aggregation()


def _on_min_dwell_changed(host, _v):
    # Refresh live overlay numbers for current scrub frame and recompute
    # debounced cell entries / dwell so the Cell Info table updates live.
    # Narrow scope: only the Cell Time graph reads per-cell debounced
    # metrics; all others are unrelated. Debounced through the standard
    # _schedule_narrow_recompute path.
    if host.tracking_results:
        host._push_cell_state_for_frame(host.slider_scrub.value())
        if hasattr(host, "_schedule_narrow_recompute"):
            host._schedule_narrow_recompute({"Cell Time"})
        else:
            host._recompute_metrics_and_views()


def _cell_min_dwell_s(host):
    if hasattr(host, "spin_min_dwell"):
        return float(host.spin_min_dwell.value())
    return 0.0


def _refresh_cell_aggregation(host):
    """Sum per-cell time / entries by region using current metrics."""
    if not hasattr(host, "_table_cell_agg"):
        return
    cats = host.get_cell_categories()
    # Group cells by region.
    by_region = {}
    for cid, cat in cats.items():
        by_region.setdefault(cat, []).append(cid)
    # Pull time/entries from metrics (set after tracking).
    m = getattr(host, "metrics", {}) or {}
    rows = []
    for region in sorted(by_region.keys()):
        cells = sorted(by_region[region])
        total_t = 0.0
        total_e = 0
        for cid in cells:
            t = m.get(f"Cell {cid} Time (s)")
            e = m.get(f"Cell {cid} Entries (#)")
            if isinstance(t, (int, float)):
                total_t += float(t)
            if isinstance(e, (int, float)):
                total_e += int(e)
        rows.append((region,
                     ",".join(str(c) for c in cells),
                     round(total_t, 2),
                     total_e))
    dur = m.get("Duration (s)")
    tb = host._table_cell_agg
    tb.setRowCount(len(rows))
    tones = {"Corner": "WARN", "Side": "TEXT_2", "Middle": "OK", "Custom": "ACCENT"}
    mono = QFont(theme.mono_family())
    mono.setPixelSize(11)
    for r, (region, cells_s, t_s, e_s) in enumerate(rows):
        it0 = QTableWidgetItem(f"  {region} cells")
        it0.setIcon(_swatch_icon(getattr(theme, tones.get(region, "TEXT_2"))))
        tb.setItem(r, 0, it0)
        it1 = QTableWidgetItem(cells_s)
        it1.setFont(mono)
        it1.setForeground(QBrush(QColor(theme.FAINT)))
        tb.setItem(r, 1, it1)
        pct = (100.0 * t_s / float(dur)) if isinstance(dur, (int, float)) and dur else 0.0
        for c, txt in ((2, f"{t_s:.1f}"), (3, str(e_s)), (4, f"{pct:.1f}")):
            it = QTableWidgetItem(txt)
            it.setFont(mono)
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tb.setItem(r, c, it)
    tb.setMaximumHeight(34 + 30 * max(1, len(rows)))
    warn = getattr(host, "_lbl_cell_warn", None)
    if warn is not None:
        grid_mode = getattr(host.zone_drawer, "zone_mode", "grid") == "grid"
        warn.setText("" if grid_mode else
                     "Zone style is “Center + periphery” — switch to Grid 4×4 + center "
                     "(Zones) to compute per-cell metrics.")
        warn.setVisible(not grid_mode)


def _swatch_icon(color, size=10):
    from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(0, 0, size, size, 2, 2)
    p.end()
    return QIcon(pm)
