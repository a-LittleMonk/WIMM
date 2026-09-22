"""Log viewer dialog. Shows the in-memory event log with filter, refresh,
clear, and save-to-file actions. Auto-updates via logger subscription."""
from __future__ import annotations
import os
import time
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QPushButton,
    QLabel, QComboBox, QFileDialog, QCheckBox,
)

from core import logger


_LEVEL_COLORS = {
    "DEBUG": "#7f8c8d",
    "INFO":  "#dcdcdc",
    "WARN":  "#f39c12",
    "ERROR": "#e74c3c",
}


class LogDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Logs")
        self.resize(900, 560)
        self._auto_scroll = True
        self._level_filter = "ALL"
        self._build_ui()
        self._refresh()
        # Live update — poll every 500ms (avoid cross-thread Qt issues from
        # the subscriber callback).
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(QLabel("Level:"))
        self.combo_level = QComboBox()
        self.combo_level.addItems(["ALL", "DEBUG", "INFO", "WARN", "ERROR"])
        self.combo_level.setFixedHeight(24)
        self.combo_level.currentTextChanged.connect(self._on_filter_changed)
        top.addWidget(self.combo_level)

        self.chk_autoscroll = QCheckBox("Auto-scroll")
        self.chk_autoscroll.setChecked(True)
        self.chk_autoscroll.toggled.connect(self._on_autoscroll)
        top.addWidget(self.chk_autoscroll)
        top.addStretch()

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setFixedHeight(24)
        self.btn_refresh.clicked.connect(self._refresh)
        top.addWidget(self.btn_refresh)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setFixedHeight(24)
        self.btn_clear.clicked.connect(self._clear)
        top.addWidget(self.btn_clear)

        self.btn_save = QPushButton("Save to file…")
        self.btn_save.setFixedHeight(24)
        self.btn_save.clicked.connect(self._save)
        top.addWidget(self.btn_save)

        v.addLayout(top)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        f = QFont("Consolas", 9)
        if not f.exactMatch():
            f = QFont("Courier New", 9)
        self.text.setFont(f)
        self.text.setStyleSheet("background:#1e1e1e; color:#dcdcdc;")
        v.addWidget(self.text, 1)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color:#888; font-size:11px;")
        v.addWidget(self.lbl_status)

    def _on_filter_changed(self, level: str):
        self._level_filter = level
        self._refresh()

    def _on_autoscroll(self, on: bool):
        self._auto_scroll = bool(on)

    def _refresh(self):
        entries = logger.get_entries()
        if self._level_filter != "ALL":
            entries = [e for e in entries if e[1] == self._level_filter]
        # Re-render fully — simple and correct.
        lines = []
        for ts, level, source, msg in entries:
            t = time.strftime("%H:%M:%S", time.localtime(ts))
            ms = int((ts - int(ts)) * 1000)
            src = f"[{source}] " if source else ""
            color = _LEVEL_COLORS.get(level, "#dcdcdc")
            line = (
                f'<span style="color:#888;">{t}.{ms:03d}</span>  '
                f'<span style="color:{color};font-weight:bold;">{level:<5}</span>  '
                f'<span style="color:#9cdcfe;">{src}</span>'
                f'<span style="color:#dcdcdc;">{self._escape(msg)}</span>'
            )
            lines.append(line)
        html = "<br>".join(lines) if lines else '<span style="color:#666;">(no log entries)</span>'
        self.text.setUpdatesEnabled(False)
        self.text.clear()
        self.text.appendHtml(html)
        if self._auto_scroll:
            cur = self.text.textCursor()
            cur.movePosition(QTextCursor.End)
            self.text.setTextCursor(cur)
        self.text.setUpdatesEnabled(True)
        self.lbl_status.setText(f"{len(entries)} entries")

    @staticmethod
    def _escape(s: str) -> str:
        return (
            s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
        )

    def _clear(self):
        logger.clear()
        self._refresh()

    def _save(self):
        default_name = f"mice_tracker_log_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save log", default_name, "Text files (*.txt);;All files (*)"
        )
        if not path:
            return
        try:
            logger.save_to_file(path)
            self.lbl_status.setText(f"Saved → {os.path.basename(path)}")
        except Exception as e:
            self.lbl_status.setText(f"Save failed: {e}")

    def closeEvent(self, event):
        try:
            self._timer.stop()
        except Exception:
            pass
        super().closeEvent(event)
