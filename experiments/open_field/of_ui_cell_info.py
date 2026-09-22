"""Cell Info tab UI + region presets.

Builds the tab where the user labels each of the 16 grid cells with a
region (Corner / Edge / Middle / Custom) and shows a region-aggregated
readout after tracking. Min-dwell tuner lives in Step 5 — single source
of truth for OF + Y-Maze.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
)


CELL_CATEGORIES = ["Corner", "Side", "Middle", "Custom"]
# Standard 4x4 preset: corners 1/4/13/16, middle 6/7/10/11, rest = side.
CELL_PRESET_STANDARD = {
    1: "Corner", 4: "Corner", 13: "Corner", 16: "Corner",
    2: "Side",   3: "Side",   5: "Side",   8: "Side",
    9: "Side",   12: "Side",  14: "Side",  15: "Side",
    6: "Middle", 7: "Middle", 10: "Middle", 11: "Middle",
}
CELL_HIGHLIGHT_PRESETS = [
    "#3CDC64", "#3CA0FF", "#FFDC00", "#FF6464", "#C864FF", "#FFFFFF",
]


def _build_cell_info_tab(host):
    """Tab where the user labels each of the 16 cells with a category
    (Corner / Edge / Middle / Custom) so summary metrics can be
    aggregated by region."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(8, 8, 8, 8)
    v.setSpacing(6)

    v.addWidget(QLabel(
        "Tag each cell with a region. Used to aggregate metrics by "
        "region (Corner / Side / Middle / Custom)."
    ))

    # Min-dwell control moved to Step 5 — single source of truth for OF + Y-Maze.

    # Preset / clear row.
    preset_row = QHBoxLayout()
    b_std = QPushButton("Apply Standard 4×4")
    b_std.setToolTip("Corners=1,4,13,16  Middle=6,7,10,11  Side=others")
    b_std.clicked.connect(lambda: host._apply_cell_preset(host.CELL_PRESET_STANDARD))
    preset_row.addWidget(b_std)
    b_clear = QPushButton("Clear all → Custom")
    b_clear.clicked.connect(
        lambda: host._apply_cell_preset({i: "Custom" for i in range(1, 17)})
    )
    preset_row.addWidget(b_clear)
    preset_row.addStretch()
    v.addLayout(preset_row)

    # 4×4 grid of dropdowns matching cell layout.
    grid = QGridLayout()
    grid.setSpacing(4)
    host._cell_combo = {}  # cid → QComboBox
    for idx in range(16):
        row, col = idx // 4, idx % 4
        cid = idx + 1
        cell_box = QFrame()
        cell_box.setFrameShape(QFrame.StyledPanel)
        cv = QVBoxLayout(cell_box)
        cv.setContentsMargins(4, 4, 4, 4)
        cv.setSpacing(2)
        lbl = QLabel(f"Cell {cid}")
        lbl.setStyleSheet("font-weight:bold; font-size:11px;")
        lbl.setAlignment(Qt.AlignCenter)
        cv.addWidget(lbl)
        cb = QComboBox()
        cb.addItems(host.CELL_CATEGORIES)
        cb.setFixedHeight(22)
        host._cell_combo[cid] = cb
        cv.addWidget(cb)
        grid.addWidget(cell_box, row, col)
    for c in range(4):
        grid.setColumnStretch(c, 1)
    for r in range(4):
        grid.setRowStretch(r, 1)
    v.addLayout(grid, 1)

    # Aggregated readout.
    v.addWidget(QLabel("Aggregated by region (after tracking):"))
    from gui.table_copy import enable_excel_copy
    host._table_cell_agg = QTableWidget()
    host._table_cell_agg.setEditTriggers(QTableWidget.NoEditTriggers)
    host._table_cell_agg.setColumnCount(4)
    host._table_cell_agg.setHorizontalHeaderLabels(
        ["Region", "Cells", "Total time (s)", "Total entries"]
    )
    enable_excel_copy(host._table_cell_agg)
    host._table_cell_agg.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    host._table_cell_agg.setMaximumHeight(150)
    v.addWidget(host._table_cell_agg)

    # Apply default preset.
    host._apply_cell_preset(host.CELL_PRESET_STANDARD)
    # Refresh aggregated table whenever any combo changes.
    for cb in host._cell_combo.values():
        cb.currentIndexChanged.connect(host._refresh_cell_aggregation)
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
    host._table_cell_agg.setRowCount(len(rows))
    for r, (region, cells_s, t_s, e_s) in enumerate(rows):
        host._table_cell_agg.setItem(r, 0, QTableWidgetItem(region))
        host._table_cell_agg.setItem(r, 1, QTableWidgetItem(cells_s))
        host._table_cell_agg.setItem(r, 2, QTableWidgetItem(str(t_s)))
        host._table_cell_agg.setItem(r, 3, QTableWidgetItem(str(e_s)))
