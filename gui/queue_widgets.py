"""Session-queue widgets of the redesign: video rows, stats strip, drop hint,
run panel with batch segments."""
import os

import cv2
from PyQt5.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from gui import icons, theme
from gui.widgets_v2 import ElidingLabel, IconButton, IconTextButton, mono_font, prop, repolish

# Status codes (mirrors gui.experiment_batch_tab; kept here to avoid a cycle)
NEEDS, READY, RUNNING, DONE, ERROR = "needs", "ready", "running", "done", "error"

_TIPS = {
    NEEDS: "Needs setup — click row to configure",
    READY: "Configured — ready to run",
    RUNNING: "Running…",
    DONE: "Completed",
    ERROR: "Error",
}
_LABELS = {NEEDS: "Needs setup", READY: "Ready", RUNNING: "Tracking",
           DONE: "Completed", ERROR: "Error"}
# status -> (dot token, label token)
_TONES = {
    NEEDS: ("BORDER_2", "FAINT"),
    READY: ("FAINT", "TEXT_2"),
    RUNNING: ("ACCENT", "ACCENT"),
    DONE: ("OK", "OK"),
    ERROR: ("ERR", "ERR"),
}


class _ProgBar(QWidget):
    """3 px rounded progress line."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(3)
        self._f = 0.0

    def set_fraction(self, f):
        self._f = max(0.0, min(1.0, f))
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.BORDER))
        p.drawRoundedRect(QRectF(0, 0, self.width(), 3), 1.5, 1.5)
        if self._f > 0:
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(QRectF(0, 0, self.width() * self._f, 3), 1.5, 1.5)


class _Thumb(QWidget):
    """34×34 frame thumbnail with the status dot badge in its corner."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(37, 37)
        self._pix = None
        self._dot = "FAINT"
        theme.notifier.changed.connect(lambda _m: self.update())

    def set_pixmap(self, pix):
        self._pix = pix
        self.update()

    def set_dot(self, token):
        self._dot = token
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, 34, 34)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1A1E22"))
        p.drawRoundedRect(r, 5, 5)
        if self._pix is not None:
            p.save()
            from PyQt5.QtGui import QPainterPath
            path = QPainterPath()
            path.addRoundedRect(r, 5, 5)
            p.setClipPath(path)
            p.drawPixmap(0, 0, self._pix)
            p.restore()
        else:
            p.setBrush(QColor("#3A4046"))
            p.drawRect(QRectF(5, 5, 24, 24))
        # status dot with a surface-coloured ring
        c = QPointF(31.5, 31.5)
        p.setBrush(QColor(theme.SURFACE))
        p.drawEllipse(c, 5.5, 5.5)
        p.setBrush(QColor(getattr(theme, self._dot)))
        p.drawEllipse(c, 3.5, 3.5)


class VideoRow(QFrame):
    """One video in the queue."""
    status_changed = pyqtSignal()

    def __init__(self, path, on_edit, on_run, on_remove, on_trim, parent=None):
        super().__init__(parent)
        self.path = path
        self.status = NEEDS
        self.animal_id = ""
        self.selected = False
        self.progress = 0
        self._on_edit_cb = on_edit
        self.setObjectName("VideoRow")
        self.setFrameShape(QFrame.NoFrame)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumHeight(48)
        self.setCursor(Qt.PointingHandCursor)

        h = QHBoxLayout(self)
        h.setContentsMargins(6, 6, 6, 6)
        h.setSpacing(9)
        self.thumb = _Thumb()
        h.addWidget(self.thumb, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        self.lbl_name = ElidingLabel(os.path.basename(path))
        self.lbl_name.setObjectName("RowName")
        self.lbl_name.setFont(mono_font(11, 500))
        col.addWidget(self.lbl_name)
        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(6)
        self.lbl_state = QLabel("Needs setup")
        self.lbl_state.setObjectName("RowState")
        self.lbl_aid = QLabel("")
        self.lbl_aid.setProperty("role", "faint11")
        self.lbl_aid.setMaximumWidth(80)
        self.lbl_aid.hide()
        meta.addWidget(self.lbl_state)
        meta.addWidget(self.lbl_aid)
        meta.addStretch(1)
        col.addLayout(meta)
        self.bar = _ProgBar()
        self.bar.hide()
        col.addWidget(self.bar)
        h.addLayout(col, 1)

        acts = QHBoxLayout()
        acts.setContentsMargins(0, 0, 0, 0)
        acts.setSpacing(1)
        self.btn_trim = IconButton("trim", 12, "FAINT", "TEXT", "Trim — set start time and duration", 22)
        self.btn_run = IconButton("play", 11, "FAINT", "ACCENT", "Run this video", 22)
        self.btn_remove = IconButton("x", 11, "FAINT", "ERR", "Remove", 22, "danger")
        self.btn_trim.clicked.connect(lambda: on_trim(self.path))
        self.btn_run.clicked.connect(lambda: on_run(self.path))
        self.btn_remove.clicked.connect(lambda: on_remove(self.path))
        for b in (self.btn_trim, self.btn_run, self.btn_remove):
            b.setCursor(Qt.ArrowCursor)
            acts.addWidget(b)
        h.addLayout(acts)

        self._refresh_status()
        theme.notifier.changed.connect(self._on_theme)
        QTimer.singleShot(0, self._load_thumb)

    # -- thumbnail ---------------------------------------------------------
    def _load_thumb(self):
        try:
            cap = cv2.VideoCapture(self.path)
            ok, frame = cap.read()
            cap.release()
            if not ok:
                return
            h, w = frame.shape[:2]
            s = min(h, w)
            y0, x0 = (h - s) // 2, (w - s) // 2
            sq = cv2.resize(frame[y0:y0 + s, x0:x0 + s], (34, 34), interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(sq, cv2.COLOR_BGR2RGB)
            img = QImage(rgb.data, 34, 34, 34 * 3, QImage.Format_RGB888).copy()
            self.thumb.set_pixmap(QPixmap.fromImage(img))
        except Exception:
            pass

    # -- interaction ---------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._on_edit_cb(self.path)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._on_edit_cb(self.path)

    # -- state ---------------------------------------------------------------
    def set_status(self, status):
        self.status = status
        if status != RUNNING:
            self.progress = 0
        self._refresh_status()
        self.status_changed.emit()

    def set_progress(self, pct):
        self.progress = max(0, min(100, int(pct)))
        if self.status == RUNNING:
            self.lbl_state.setText(f"Tracking {self.progress}%")
            self.bar.set_fraction(self.progress / 100.0)

    def set_animal_id(self, aid):
        self.animal_id = aid or ""
        self.lbl_aid.setText(self.animal_id)
        self.lbl_aid.setVisible(bool(self.animal_id))

    def set_selected(self, on):
        self.selected = bool(on)
        prop(self, selected="true" if self.selected else "false")
        repolish(self)

    def _on_theme(self, _m):
        self._refresh_status()

    def _refresh_status(self):
        dot, lab = _TONES.get(self.status, _TONES[NEEDS])
        self.thumb.set_dot(dot)
        self.setToolTip(_TIPS.get(self.status, ""))
        text = _LABELS.get(self.status, "")
        if self.status == RUNNING:
            text = f"Tracking {self.progress}%"
        self.lbl_state.setText(text)
        self.lbl_state.setProperty("vstate", self.status)
        self.bar.setVisible(self.status == RUNNING)
        self.bar.set_fraction(self.progress / 100.0)
        repolish(self.lbl_state)
        # keep the dynamic property in sync for the stylesheet
        self.setProperty("vstatus", self.status)
        self.setProperty("selected", "true" if self.selected else "false")
        repolish(self)


class QueueStats(QFrame):
    """Done / Running / Ready / Attention counters."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StatGrid")
        self.setAttribute(Qt.WA_StyledBackground, True)
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 1)
        g.setSpacing(1)
        self._grid = g
        self._cells = []
        self._cols = 4
        self._num = {}
        for i, (key, label, tone) in enumerate((
                ("done", "Done", "ok"), ("running", "Running", "accent"),
                ("ready", "Ready", "text"), ("attention", "Attention", "err"))):
            cell = QWidget()
            cell.setObjectName("StatCell")
            cell.setAttribute(Qt.WA_StyledBackground, True)
            v = QVBoxLayout(cell)
            v.setContentsMargins(0, 9, 0, 8)
            v.setSpacing(1)
            n = QLabel("0")
            n.setAlignment(Qt.AlignCenter)
            n.setFont(mono_font(15, 500))
            theme.set_tone(n, tone)
            t = QLabel(label.upper())
            t.setAlignment(Qt.AlignCenter)
            t.setProperty("role", "statlabel")
            v.addWidget(n)
            v.addWidget(t)
            g.addWidget(cell, 0, i)
            self._num[key] = n
            self._cells.append(cell)

    def set_counts(self, done, running, ready, attention):
        for k, v in (("done", done), ("running", running),
                     ("ready", ready), ("attention", attention)):
            self._num[k].setText(str(v))

    # 4 counters in a row need ~300 px to breathe; wrap to 2 x 2 below that.
    WRAP_AT = 300

    def minimumSizeHint(self):
        m = super().minimumSizeHint()
        return m.__class__(min(m.width(), 150), m.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cols = 2 if self.width() < self.WRAP_AT else 4
        if cols != self._cols:
            self._cols = cols
            for i, cell in enumerate(self._cells):
                self._grid.removeWidget(cell)
                self._grid.addWidget(cell, i // cols, i % cols)


class DropHint(QWidget):
    """Dashed "Drop video files here" panel; click opens the file picker."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(88)
        self.setCursor(Qt.PointingHandCursor)
        theme.notifier.changed.connect(lambda _m: self.update())

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setBrush(QColor(theme.SURFACE_2))
        pen = QPen(QColor(theme.BORDER_2), 1, Qt.DashLine)
        pen.setDashPattern([3, 3])
        p.setPen(pen)
        p.drawRoundedRect(r, 7, 7)
        pm = icons.pixmap("upload", 18, theme.FAINT)
        p.drawPixmap(int(self.width() / 2 - 9), 14, pm)
        p.setPen(QColor(theme.FAINT))
        f = self.font()
        f.setPixelSize(11)
        p.setFont(f)
        p.drawText(QRectF(0, 36, self.width(), 16), Qt.AlignCenter, "Drop video files here")
        p.setFont(mono_font(9))
        p.drawText(QRectF(0, 54, self.width(), 14), Qt.AlignCenter, ".mp4 .avi .mov .mkv .wmv .flv")


class _Segs(QWidget):
    """Batch progress segments — one 4 px cell per video."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(4)
        self._cols = []
        theme.notifier.changed.connect(lambda _m: self.update())

    def set_tokens(self, tokens):
        self._cols = list(tokens)
        self.update()

    def paintEvent(self, _e):
        n = len(self._cols)
        if n == 0:
            return
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        gap = 2
        w = (self.width() - gap * (n - 1)) / float(n)
        for i, tok in enumerate(self._cols):
            p.setBrush(QColor(getattr(theme, tok)))
            p.drawRoundedRect(QRectF(i * (w + gap), 0, w, 4), 1, 1)


class _ProgressProxy:
    """Drop-in for the QProgressBar API the batch code drives."""

    def __init__(self, on_change):
        self._on_change = on_change
        self._lo, self._hi, self._val = 0, 100, 0
        self.visible = False

    def setRange(self, lo, hi):
        self._lo, self._hi = lo, hi
        self._on_change()

    def setValue(self, v):
        self._val = v
        self._on_change()

    def value(self):
        return self._val

    def maximum(self):
        return self._hi

    def setVisible(self, on):
        self.visible = bool(on)
        self._on_change()

    def isVisible(self):
        return self.visible


class RunPanel(QFrame):
    """Run all / Stop + batch progress readout."""

    def __init__(self, on_run, on_stop, parent=None):
        super().__init__(parent)
        self.setObjectName("RunPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_run_all = IconTextButton("play_bar", "Run all", 11, height=34, primary=True)
        self.btn_run_all.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_run_all.clicked.connect(on_run)
        self.btn_stop = IconTextButton("stop", "Stop", 10, height=34)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(on_stop)
        row.addWidget(self.btn_run_all, 1)
        row.addWidget(self.btn_stop)
        v.addLayout(row)

        info = QVBoxLayout()
        info.setSpacing(5)
        top = QHBoxLayout()
        self.lbl_batch = QLabel("Batch")
        self.lbl_batch.setTextFormat(Qt.RichText)
        theme.set_tone(self.lbl_batch, "text2", "font-size:11px;")
        self.lbl_pct = QLabel("")
        self.lbl_pct.setFont(mono_font(11))
        theme.set_tone(self.lbl_pct, "text2")
        top.addWidget(self.lbl_batch)
        top.addStretch(1)
        top.addWidget(self.lbl_pct)
        info.addLayout(top)
        self.segs = _Segs()
        info.addWidget(self.segs)
        bot = QHBoxLayout()
        self.lbl_elapsed = QLabel("")
        self.lbl_eta = QLabel("")
        for lb in (self.lbl_elapsed, self.lbl_eta):
            lb.setFont(mono_font(10))
            theme.set_tone(lb, "faint")
        bot.addWidget(self.lbl_elapsed)
        bot.addStretch(1)
        bot.addWidget(self.lbl_eta)
        info.addLayout(bot)
        v.addLayout(info)

    def set_batch(self, done, total, pct, tokens):
        mono = theme.mono_family()
        self.lbl_batch.setText(
            f"Batch <span style=\"font-family:'{mono}'; color:{theme.TEXT}\">{done} / {total}</span>")
        self.lbl_pct.setText(f"{pct:.1f}%" if total else "")
        self.segs.set_tokens(tokens)

