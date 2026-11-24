"""Completion popup for exports and renders.

    show_done(parent, "Excel file saved", path=out_path)
    show_done(parent, "Videos rendered", "3 videos saved.", folder=out_dir)
    show_done(parent, "Export failed", str(err), kind="err")

A small centred window with a status mark, a title, what happened, and —
when a file or folder is given — Open file / Show in folder buttons.
"""
import os
import subprocess
import sys

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt, QUrl
from PyQt5.QtGui import QColor, QDesktopServices, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from gui import theme


class _Mark(QWidget):
    """Round status mark: ✓ done, ! partly done, × failed."""

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self._kind = kind
        self.setFixedSize(QSize(44, 44))

    def paintEvent(self, _e):
        col = QColor({"ok": theme.OK, "warn": theme.WARN, "err": theme.ERR}[self._kind])
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QColor(col)
        bg.setAlphaF(0.16)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawEllipse(QRectF(1, 1, 42, 42))
        p.setPen(QPen(col, 3.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if self._kind == "ok":
            p.drawPolyline(QPointF(13, 23), QPointF(19.5, 29), QPointF(31, 16))
        elif self._kind == "warn":
            p.drawLine(QPointF(22, 12), QPointF(22, 25))
            p.drawPoint(QPointF(22, 31))
        else:
            p.drawLine(QPointF(15, 15), QPointF(29, 29))
            p.drawLine(QPointF(29, 15), QPointF(15, 29))
        p.end()


def _reveal(path):
    """Open the folder holding `path` with the file selected (Windows)."""
    path = os.path.normpath(path)
    if sys.platform.startswith("win") and os.path.exists(path):
        subprocess.Popen(["explorer", "/select,", path])
    else:
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


def show_notices(parent):
    """Show (once) the problems queued with core.app_paths.notice — e.g. a
    graph that could not be drawn and is missing from an export."""
    from core.app_paths import pop_notices
    msgs = pop_notices()
    if msgs:
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning(parent, "Please check", "\n\n".join(msgs))


def explain_error(e):
    """Export error in plain words: a locked file gets the usual cause."""
    if isinstance(e, PermissionError):
        name = os.path.basename(getattr(e, "filename", "") or "") or "The file"
        return (f"{name} can't be written — it is probably open in Excel or "
                "another program. Close it and export again.")
    return str(e)


def show_done(parent, title, message="", path=None, folder=None, kind="ok"):
    """Show the completion popup (blocks until closed, like a message box)."""
    host = parent.window() if parent is not None else None
    if host is None or not host.isVisible():
        host = QApplication.activeWindow() or host
    dlg = QDialog(host)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(440)
    root = QVBoxLayout(dlg)
    root.setContentsMargins(22, 20, 22, 18)
    root.setSpacing(16)

    top = QHBoxLayout()
    top.setSpacing(16)
    top.addWidget(_Mark(kind), 0, Qt.AlignTop)
    text = QVBoxLayout()
    text.setSpacing(6)
    t = QLabel(title)
    t.setStyleSheet("font-size: 16px; font-weight: 600;")
    text.addWidget(t)
    lines = []
    if message:
        lines.append(message)
    shown = path or folder
    if shown:
        name = os.path.basename(os.path.normpath(shown))
        where = os.path.dirname(os.path.normpath(shown)) if path else shown
        if path:
            lines.append(f"<b>{name}</b>")
        lines.append(f"<span style='color:{theme.FAINT}'>{where}</span>")
    if lines:
        body = QLabel("<br>".join(lines))
        body.setTextFormat(Qt.RichText)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text.addWidget(body)
    top.addLayout(text, 1)
    root.addLayout(top)

    btns = QHBoxLayout()
    btns.addStretch(1)
    if path and os.path.exists(path) and kind != "err":
        b_open = QPushButton("Open file")
        b_open.clicked.connect(lambda: (QDesktopServices.openUrl(QUrl.fromLocalFile(path)),
                                        dlg.accept()))
        btns.addWidget(b_open)
    if shown and os.path.exists(shown) and kind != "err":
        b_folder = QPushButton("Show in folder")
        b_folder.clicked.connect(lambda: (_reveal(shown), dlg.accept()))
        btns.addWidget(b_folder)
    ok = QPushButton("OK")
    ok.setProperty("primary", True)
    ok.setDefault(True)
    ok.clicked.connect(dlg.accept)
    btns.addWidget(ok)
    root.addLayout(btns)
    dlg.exec_()
