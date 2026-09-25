"""Per-block ⓘ Information popup.

Replaces hover tooltips on a step's parameters with a small ⓘ button
that floats in the top-right corner of the step's group box (it is not
part of the group's layout, so it takes no layout space). Clicking it
opens a compact popup, sized to its text, listing each parameter title
(bold) followed by its original explanatory text. The popup never
touches the Configuration layout; it closes on any outside click / Esc.
"""
from html import escape

from PyQt5.QtCore import QEvent, QObject, QPoint, Qt
from PyQt5.QtWidgets import (
    QApplication, QFrame, QLabel, QToolButton, QVBoxLayout,
)

_POPUP_TEXT_WIDTH = 320


class _InfoPopup(QFrame):
    def __init__(self, parent, html):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("infoPopup")
        from gui import theme
        self.setStyleSheet(
            f"QFrame#infoPopup {{ background: {theme.SURFACE};"
            f" border: 1px solid {theme.BORDER_2}; border-radius: 8px; }}"
            "QLabel { background: transparent; border: none; font-size: 11px; }"
        )
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 4)
        lbl = QLabel(html)
        lbl.setTextFormat(Qt.RichText)
        lbl.setWordWrap(True)
        lbl.setFixedWidth(_POPUP_TEXT_WIDTH)
        lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        v.addWidget(lbl)
        self.adjustSize()

    def popup_at(self, btn):
        self.adjustSize()
        anchor = btn.mapToGlobal(QPoint(btn.width(), btn.height() + 2))
        x, y = anchor.x() - self.width(), anchor.y()
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        if screen is not None:
            g = screen.availableGeometry()
            x = max(g.left(), min(x, g.right() - self.width()))
            if y + self.height() > g.bottom():
                y = max(g.top(), btn.mapToGlobal(QPoint(0, 0)).y() - self.height() - 2)
        self.move(x, y)
        self.show()


class _Corner(QObject):
    """Keeps the ⓘ button pinned to the group box's top-right corner."""

    def __init__(self, grp, btn):
        super().__init__(grp)
        self._grp, self._btn = grp, btn
        grp.installEventFilter(self)
        self.place()

    def place(self):
        # sits in the card header, left of the status dot + chevron
        self._btn.move(self._grp.width() - 76, 14)
        self._btn.raise_()

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Resize, QEvent.Show):
            self.place()
        return False


def attach_info_box(grp, entries):
    """Move tooltips into an Information popup on `grp`.

    entries: list of (title, source) where source is a widget (its
    tooltip text is moved into the popup and cleared) or a plain string.
    Entries with no text are skipped; if none remain, nothing is added.
    """
    items = []
    for title, src in entries:
        if isinstance(src, str):
            text = src
        else:
            text = src.toolTip()
            src.setToolTip("")
        if text and text.strip():
            items.append((title, text))
    if not items:
        return None

    parts = []
    for title, text in items:
        body = escape(text).replace("\n", "<br>")
        parts.append(
            f'<p style="margin:0 0 6px 0;"><b>{escape(title)}</b><br>{body}</p>'
        )
    html = "".join(parts)

    btn = QToolButton(grp)
    btn.setText("ⓘ")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedSize(18, 18)
    btn.setFocusPolicy(Qt.NoFocus)
    btn.setObjectName("InfoBtn")  # styled in theme.py
    def _open():
        pop = _InfoPopup(grp.window(), html)
        pop.setAttribute(Qt.WA_DeleteOnClose)
        pop.popup_at(btn)

    btn.clicked.connect(_open)
    btn._corner = _Corner(grp, btn)
    btn.show()
    return btn
