"""Building blocks of the Output tab (redesign v2): sub-tab header, bordered
panels with a title bar, table helpers."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from gui import theme


class SubTabHeader(QWidget):
    """38 px tab strip (Summary · Raw data · Graphs …) with widgets on the
    right. Replaces the native tab bar of `tabs`."""

    def __init__(self, tabs, right_widgets=(), parent=None):
        super().__init__(parent)
        self.setObjectName("SubTabHeader")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(38)
        self._tabs = tabs
        tabs.tabBar().hide()
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 0, 12, 0)
        h.setSpacing(2)
        self._btns = []
        for i in range(tabs.count()):
            b = QPushButton(tabs.tabText(i))
            b.setCheckable(True)
            b.setProperty("subtab", True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, k=i: tabs.setCurrentIndex(k))
            h.addWidget(b)
            self._btns.append(b)
        h.addStretch(1)
        self._right = QHBoxLayout()
        self._right.setSpacing(12)
        for w in right_widgets:
            self._right.addWidget(w)
        h.addLayout(self._right)
        tabs.currentChanged.connect(self._sync)
        self._sync(tabs.currentIndex())

    def set_tab_visible(self, index, visible):
        if 0 <= index < len(self._btns):
            self._btns[index].setVisible(visible)

    def refresh_titles(self):
        for i, b in enumerate(self._btns):
            b.setText(self._tabs.tabText(i))

    def _sync(self, idx):
        for i, b in enumerate(self._btns):
            b.setChecked(i == idx)


class OutPanel(QFrame):
    """Bordered surface panel. Optional title bar with a button strip:
    `panel.title` (QLabel), `panel.add_button(text, slot)`, `panel.body` (layout)."""

    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.setObjectName("OutPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.bar = QWidget()
        self.bar.setObjectName("OutPanelBar")
        self.bar.setAttribute(Qt.WA_StyledBackground, True)
        self.bar.setFixedHeight(42)
        bh = QHBoxLayout(self.bar)
        bh.setContentsMargins(14, 0, 14, 0)
        bh.setSpacing(8)
        self.title = QLabel(title)
        self.title.setTextFormat(Qt.RichText)
        self.title.setObjectName("OutPanelTitle")
        bh.addWidget(self.title)
        bh.addStretch(1)
        self._bar_layout = bh
        v.addWidget(self.bar)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)
        v.addLayout(self.body, 1)
        if not title:
            self.bar.hide()

    def set_title(self, main, sub=""):
        mono_sub = (f" <span style='font-weight:400; color:{theme.FAINT}; font-size:11px'>{sub}</span>"
                    if sub else "")
        self.title.setText(f"{main}{mono_sub}")
        self.bar.show()

    def add_button(self, text, slot):
        b = QPushButton(text)
        b.setFixedHeight(24)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        self._bar_layout.addWidget(b)
        return b

    def add_widget(self, widget):
        self._bar_layout.addWidget(widget)
        return widget


def copy_table_all(table, with_header=True):
    """Copy the whole table as TSV (Excel-friendly)."""
    lines = []
    if with_header:
        heads = []
        for c in range(table.columnCount()):
            it = table.horizontalHeaderItem(c)
            heads.append(it.text() if it is not None else "")
        if any(heads):
            lines.append("\t".join(heads))
    for r in range(table.rowCount()):
        cells = []
        for c in range(table.columnCount()):
            it = table.item(r, c)
            cells.append(it.text() if it is not None else "")
        lines.append("\t".join(cells))
    QApplication.clipboard().setText("\n".join(lines))


def padded(widget, margin=16):
    """Wrap a page in a container with an outer margin."""
    box = QWidget()
    box.setObjectName("OutPage")
    v = QVBoxLayout(box)
    v.setContentsMargins(margin, margin, margin, margin)
    v.addWidget(widget)
    return box


class Section(QFrame):
    """Export-style card: bordered surface with a 13 px bold title.
    `section.body` is the content layout; `section.header` an HBox next to the title."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("Section")
        self.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)
        self.header = QHBoxLayout()
        self.header.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel(title)
        self.title.setObjectName("SectionTitle")
        self.header.addWidget(self.title)
        self.header.addStretch(1)
        v.addLayout(self.header)
        self.body = v
