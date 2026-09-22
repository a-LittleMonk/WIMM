"""Excel-friendly clipboard copy for QTableWidget.

Default Qt copy on a QTableWidget only copies the focused cell. Most users
expect Excel-style behavior: select a rectangular block, Ctrl+C, paste
into Excel as a TSV grid. `enable_excel_copy(table)` installs that.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QShortcut, QApplication, QAbstractItemView


def enable_excel_copy(table):
    """Wire Ctrl+C on `table` to copy the current selection as TSV (one
    row per line, tab-separated cells). Bounds the copy by the union
    rectangle of all selected ranges so non-contiguous selections still
    paste as a complete grid (missing cells become empty)."""
    table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    table.setSelectionBehavior(QAbstractItemView.SelectItems)
    sc = QShortcut(QKeySequence.Copy, table)
    sc.setContext(Qt.WidgetShortcut)
    sc.activated.connect(lambda: _copy_selection_to_clipboard(table))


def _copy_selection_to_clipboard(table):
    ranges = table.selectedRanges()
    if not ranges:
        item = table.currentItem()
        if item is not None:
            QApplication.clipboard().setText(item.text())
        return
    rows = sorted({r for sel in ranges
                   for r in range(sel.topRow(), sel.bottomRow() + 1)})
    cols = sorted({c for sel in ranges
                   for c in range(sel.leftColumn(), sel.rightColumn() + 1)})
    lines = []
    for r in rows:
        cells = []
        for c in cols:
            item = table.item(r, c)
            cells.append(item.text() if item is not None else "")
        lines.append("\t".join(cells))
    QApplication.clipboard().setText("\n".join(lines))
