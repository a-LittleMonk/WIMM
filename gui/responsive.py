"""Small layout helpers so controls adapt to the available width
instead of being clipped or squashed."""
from PyQt5.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PyQt5.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLayout, QWidget,
)


class FlowLayout(QLayout):
    """Left-to-right layout that wraps items onto new lines when the
    available width runs out (height-for-width aware)."""

    def __init__(self, parent=None, h_spacing=12, v_spacing=2):
        super().__init__(parent)
        self._items = []
        self._hs = h_spacing
        self._vs = v_spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = eff.x(), eff.y(), 0
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width()
            if next_x > eff.right() + 1 and line_h > 0:
                x = eff.x()
                y += line_h + self._vs
                next_x = x + hint.width()
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x + self._hs
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


class _Check(QCheckBox):
    """Checkbox whose companion label follows its enabled state."""
    _lbl = None

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.EnabledChange and self._lbl is not None:
            self._lbl.setEnabled(self.isEnabled())


def wrapped_checkbox(text):
    """Checkbox with a word-wrapped label (a plain QCheckBox clips long
    text). Returns (checkbox, container); add the container to a layout.
    Clicking the text toggles the checkbox."""
    chk = _Check()
    chk.setAccessibleName(text)
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setMinimumWidth(40)
    lbl.mouseReleaseEvent = (
        lambda e, c=chk: c.toggle() if c.isEnabled() and e.button() == Qt.LeftButton else None
    )
    chk._lbl = lbl
    box = QWidget()
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(4)
    h.addWidget(chk, 0, Qt.AlignTop)
    h.addWidget(lbl, 1)
    return chk, box


def pair(*widgets):
    """Group widgets (e.g. label + spinbox) so a FlowLayout keeps them together."""
    box = QWidget()
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    for w in widgets:
        h.addWidget(w)
    return box
