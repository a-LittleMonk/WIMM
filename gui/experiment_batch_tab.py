"""ExperimentBatchTab — generic batch tab base.

Video-list-centric, per-video editor (embedded ExperimentTab subclass) +
queue runner + crop/trim + per-video result cards + apply-to dialog +
combined-Excel + annotated-video export.

OpenFieldBatchTab subclasses this and pins embedded_tab_class to
OpenFieldTab. YMazeBatchTab pins it to YMazeTab.

OF-specific Excel column ordering / file naming / cell_min_dwell reads
still happen here — Phase 3 keeps them generic by reading from the
embedded tab's `experiment` plugin where the contract supports it. Where
the contract doesn't yet support it, the legacy hard-coded calls remain
(behavior-preserving).
"""
"""Open Field — batch-centric main tab.

Replaces the old steps-driven Open Field UI. Main UI is video-list-centric:
  - drag-and-drop / Add videos
  - per-row Edit / Run / Remove buttons + status icon
  - shared live-preview pane (currently running video)
  - Run All / Stop + progress bars
  - Apply Template to All button
  - Per-video collapsible result cards
"""
import os
from contextlib import contextmanager
import cv2
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QFileDialog, QProgressBar, QMessageBox, QFrame,
    QSizePolicy, QScrollArea, QSplitter, QComboBox, QDialog, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QSlider, QCheckBox, QSpinBox,
    QRadioButton, QButtonGroup, QDialogButtonBox, QGroupBox, QAbstractItemView,
)
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QObject, QTimer
from PyQt5.QtGui import QPixmap, QImage, QKeySequence
from PyQt5.QtWidgets import QShortcut
from gui.open_field_tab import OpenFieldTab
from tracking.tracker import TrackerThread
from analysis.open_field import compute_metrics
from export.excel_export import export_results
from core import logger
from gui import theme
from gui.widgets_v2 import (
    ElidingLabel, IconButton, IconTextButton, PaneHeader, CountPill, KeyHint,
)
from gui.queue_widgets import (
    VideoRow, QueueStats, DropHint, RunPanel, _ProgressProxy,
)

VIDEO_EXTS = (".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv")


# Status codes
STATUS_NEEDS  = "needs"
STATUS_READY  = "ready"
STATUS_RUNNING = "running"
STATUS_DONE   = "done"
STATUS_ERROR  = "error"

STATUS_ICONS = {
    STATUS_NEEDS:   ("⚙", "#8A8F95",    "Needs setup — click row to configure"),
    STATUS_READY:   ("⏳", "#1B2436", "Configured — ready to run"),
    STATUS_RUNNING: ("▶", "#1B2436", "Running…"),
    STATUS_DONE:    ("✅", "#2F7A4B", "Completed"),
    STATUS_ERROR:   ("❌", "#B3382E", "Error"),
}


# Maps a user-facing field-group label → list of snapshot_settings() keys.
# Order matters — listed top-down in the Apply-To dialog.
APPLY_FIELD_GROUPS = [
    ("Detection (sliders / threshold / model)",
        ["threshold", "low_contrast", "brightness", "contrast", "blur", "gamma", "sharpen",
         "clahe", "max_blob", "proc_scale", "model", "model_params", "post_params"]),
    ("Visualization (overlays / colors)",
        ["body_style", "ellipse", "trail", "trail_len",
         "brush_radius", "colors", "overlay_alpha"]),
    ("Smoothing & timing",
        ["smooth", "movement_thr", "bin_size"]),
    ("Trim",
        ["trim_start", "trim_duration"]),
    ("FPS override",
        ["fps_override"]),
    ("Calibration (px/cm line)",
        ["calib_p1", "calib_p2", "calib_cm"]),
    ("Zone mode / cage shape / perspective",
        ["zone_mode", "cage_shape", "perspective", "center_pct"]),
    ("Arena & center polygons",
        ["arena", "center_zone"]),
    ("Exclusion mask",
        ["exclusion_mask"]),
    ("Metadata (Animal ID / Group / Sex / …)",
        ["metadata"]),
]
# Defaults — only Detection is on. Per-video stuff stays off so the user
# explicitly opts in to overwriting arena / metadata / etc.
APPLY_DEFAULTS_ON = {"Detection (sliders / threshold / model)"}

# Batch rule: every setting that changes the data is shared by the whole
# batch (taken from the video the user set up). Only what is drawn on /
# tied to one particular video stays per video.
def _warp_size_for(s, exp, vw, vh):
    """Straightened-arena size for a batch / Multi-Run video — the same
    rule as ExperimentTab._warp_target_size."""
    from experiments.open_field.experiment import warp_target_size
    shape = "square" if getattr(exp, "fam", None) == "nor" else s.get("cage_shape")
    return warp_target_size(vw, vh, shape, float(s.get("cage_w_cm") or 0),
                            float(s.get("cage_h_cm") or 0))


def _px_per_cm_for(s, exp, size):
    """px/cm for a batch / Multi-Run video — the same rules as the screen
    (ExperimentTab._get_px_per_cm): honour the calibration mode, and read
    the line / arena in the frame they were drawn in (`size`: the warped
    frame when perspective is on, else the video)."""
    mode = s.get("calib_mode")
    if mode == "none":
        return None
    vw, vh = size
    cp1, cp2, cm = s.get("calib_p1"), s.get("calib_p2"), float(s.get("calib_cm") or 0)
    if mode in ("manual", None) and cp1 and cp2 and cm > 0:
        d = ((cp2[0] - cp1[0]) * vw) ** 2 + ((cp2[1] - cp1[1]) * vh) ** 2
        if d > 0:
            return d ** 0.5 / cm
    if mode == "manual" or exp is None:
        return None
    try:
        return exp.compute_auto_px_per_cm(s, size)
    except Exception as e:
        logger.warn(f"auto px/cm failed: {e}", source="batch")
        return None


PER_VIDEO_KEYS = frozenset({
    # Arena / area detection
    "arena", "original_arena", "perspective",
    "arena_auto_movement", "arena_define_mode", "arena_pad_pct",
    "center_zone", "center",          # center is re-derived from center_pct
    # Calibration line drawn on this video
    "calib_p1", "calib_p2", "calib_cm",
    # Masks / crop / animal info
    "exclusion_mask", "crop", "metadata",
    "video_w", "video_h",
    # EPM geometry
    "arms_norm", "center_norm", "arm_kinds", "arm_custom_names",
    "epm_endpoints", "epm_hub", "epm_original_endpoints", "epm_original_hub",
    "epm_homography", "epm_warp_size", "epm_perspective",
    # Y-Maze geometry
    "neutral_norm", "ym_endpoints", "ym_hub",
    "ym_original_endpoints", "ym_original_hub", "ym_perspective",
    # NOR object placement / roles
    "objects_norm",
    # Box-family per-animal assignments (paired side, stranger side,
    # platform quadrant, trial type, baited arms)
    "box_assign",
})


def merge_batch_settings(shared_src, own):
    """Settings one video runs with in a batch: its own per-video keys plus
    every other key from `shared_src` (deep-copied so videos never share
    mutable objects)."""
    import copy
    merged = dict(own or {})
    for k, v in (shared_src or {}).items():
        if k in PER_VIDEO_KEYS:
            continue
        merged[k] = copy.deepcopy(v)
    return merged


def derive_center_zone(s, exp_key):
    """Open Field: rebuild the center polygon from the arena and center_pct,
    exactly as the panel does, so a shared / swept center % really applies.
    Mutates and returns `s`."""
    if exp_key != "open_field":
        return s
    arena = s.get("arena")
    if not arena or len(arena) < 3 or s.get("center_pct") is None:
        return s
    pct = float(s["center_pct"]) / 100.0
    n = float(len(arena))
    cx = sum(p[0] for p in arena) / n
    cy = sum(p[1] for p in arena) / n
    s["center_zone"] = [(cx + (p[0] - cx) * pct, cy + (p[1] - cy) * pct)
                        for p in arena]
    s.pop("center", None)
    return s


class _RangeSlider(QWidget):
    """Horizontal slider with two handles: start (left) and end (right).
    Emits start_changed / end_changed when their values change. Also
    emits handle_moved("start"|"end", value) so the popup can know
    which handle was just touched (and show that frame)."""

    start_changed = pyqtSignal(int)
    end_changed   = pyqtSignal(int)
    handle_moved  = pyqtSignal(str, int)

    HANDLE_W = 10
    TRACK_H  = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(28)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self._min = 0
        self._max = 100
        self._start = 0
        self._end = 100
        self._dragging = None  # 'start' | 'end' | None

    # ── public API ──
    def setRange(self, lo, hi):
        self._min = int(lo)
        self._max = int(hi)
        self._start = max(self._min, min(self._max, self._start))
        self._end   = max(self._start, min(self._max, self._end))
        self.update()

    def setStart(self, v):
        v = max(self._min, min(self._end, int(v)))
        if v != self._start:
            self._start = v
            self.update()
            self.start_changed.emit(v)

    def setEnd(self, v):
        v = max(self._start, min(self._max, int(v)))
        if v != self._end:
            self._end = v
            self.update()
            self.end_changed.emit(v)

    def start(self):
        return self._start

    def end(self):
        return self._end

    # ── geometry helpers ──
    def _track_x_range(self):
        return self.HANDLE_W // 2, self.width() - self.HANDLE_W // 2

    def _value_to_x(self, v):
        x0, x1 = self._track_x_range()
        if self._max <= self._min:
            return x0
        return int(x0 + (v - self._min) / (self._max - self._min) * (x1 - x0))

    def _x_to_value(self, x):
        x0, x1 = self._track_x_range()
        if x1 <= x0:
            return self._min
        v = self._min + (x - x0) / (x1 - x0) * (self._max - self._min)
        return max(self._min, min(self._max, int(round(v))))

    def _hit_handle(self, pos):
        sx = self._value_to_x(self._start)
        ex = self._value_to_x(self._end)
        if abs(pos.x() - sx) <= self.HANDLE_W:
            return "start"
        if abs(pos.x() - ex) <= self.HANDLE_W:
            return "end"
        return None

    # ── mouse ──
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        h = self._hit_handle(e.pos())
        if h is None:
            # Clicked the track — move the nearest handle.
            v = self._x_to_value(e.pos().x())
            if abs(v - self._start) <= abs(v - self._end):
                h = "start"
            else:
                h = "end"
        self._dragging = h
        self._move_handle_to(e.pos().x())

    def mouseMoveEvent(self, e):
        if self._dragging is None:
            h = self._hit_handle(e.pos())
            self.setCursor(Qt.SizeHorCursor if h else Qt.ArrowCursor)
            return
        self._move_handle_to(e.pos().x())

    def mouseReleaseEvent(self, e):
        self._dragging = None

    def _move_handle_to(self, px):
        v = self._x_to_value(px)
        if self._dragging == "start":
            self.setStart(v)
            self.handle_moved.emit("start", self._start)
        elif self._dragging == "end":
            self.setEnd(v)
            self.handle_moved.emit("end", self._end)

    # ── paint ──
    def paintEvent(self, event):
        from PyQt5.QtGui import QPainter, QPen, QColor, QBrush
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        x0, x1 = self._track_x_range()
        ty = (h - self.TRACK_H) // 2
        # Inactive track
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.BORDER_2))
        painter.drawRoundedRect(x0, ty, x1 - x0, self.TRACK_H, 2, 2)
        # Active range
        sx = self._value_to_x(self._start)
        ex = self._value_to_x(self._end)
        painter.setBrush(QColor(theme.ACCENT))
        painter.drawRoundedRect(sx, ty, ex - sx, self.TRACK_H, 2, 2)
        # Handles
        painter.setBrush(QColor(theme.SURFACE))
        painter.setPen(QPen(QColor(theme.ACCENT), 2))
        for x in (sx, ex):
            painter.drawEllipse(x - self.HANDLE_W // 2,
                                 (h - self.HANDLE_W) // 2,
                                 self.HANDLE_W, self.HANDLE_W)


class _CropFrameLabel(QLabel):
    """QLabel that renders a video frame and (optionally) overlays a
    draggable crop rectangle with 4 corner handles."""
    HANDLE = 12  # widget-pixel grab radius

    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 240)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background:#0A0C0E;")
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setMouseTracking(True)
        self._pixmap = None      # full-resolution QPixmap of current frame
        self._frame_w = 1
        self._frame_h = 1
        self.crop_enabled = False
        self.crop_rect = None    # (x, y, w, h) in FRAME pixels
        self._dragging = None    # 'tl' | 'tr' | 'br' | 'bl' | 'inside'
        self._drag_anchor = None # widget pixel where drag started
        self._drag_orig_rect = None

    def set_frame(self, bgr):
        """Set the displayed frame from a BGR numpy array."""
        if bgr is None:
            self._pixmap = None
            self.update()
            return
        h, w = bgr.shape[:2]
        self._frame_h, self._frame_w = h, w
        rgb = bgr[:, :, ::-1].copy()
        img = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
        self._pixmap = QPixmap.fromImage(img)
        self.update()


    def set_crop_rect(self, rect):
        """Set crop in frame pixel coords (x, y, w, h) or None."""
        self.crop_rect = rect
        if rect is not None:
            self.crop_enabled = True
        self.update()

    # ── geometry helpers ──
    def _disp_rect(self):
        """Pixel rect on the widget where the (scaled) frame is drawn."""
        if self._pixmap is None:
            return 0, 0, 0, 0
        ww, wh = self.width(), self.height()
        pw, ph = self._pixmap.width(), self._pixmap.height()
        if pw <= 0 or ph <= 0:
            return 0, 0, 0, 0
        scale = min(ww / pw, wh / ph)
        dw, dh = int(pw * scale), int(ph * scale)
        ox, oy = (ww - dw) // 2, (wh - dh) // 2
        return ox, oy, dw, dh

    def _frame_to_widget(self, fx, fy):
        ox, oy, dw, dh = self._disp_rect()
        return (ox + int(fx * dw / max(self._frame_w, 1)),
                oy + int(fy * dh / max(self._frame_h, 1)))

    def _widget_to_frame(self, wx, wy):
        ox, oy, dw, dh = self._disp_rect()
        if dw <= 0 or dh <= 0:
            return 0, 0
        fx = max(0, min(self._frame_w, int((wx - ox) * self._frame_w / dw)))
        fy = max(0, min(self._frame_h, int((wy - oy) * self._frame_h / dh)))
        return fx, fy

    def _crop_corners_widget(self):
        """Returns dict of 4 corner positions in widget coords."""
        if not self.crop_rect:
            return {}
        x, y, w, h = self.crop_rect
        return {
            "tl": self._frame_to_widget(x, y),
            "tr": self._frame_to_widget(x + w, y),
            "br": self._frame_to_widget(x + w, y + h),
            "bl": self._frame_to_widget(x, y + h),
        }

    def _hit_test(self, pos):
        if not (self.crop_enabled and self.crop_rect):
            return None
        for name, (cx, cy) in self._crop_corners_widget().items():
            if abs(pos.x() - cx) <= self.HANDLE and abs(pos.y() - cy) <= self.HANDLE:
                return name
        # Inside the rect → drag whole crop
        x, y, w, h = self.crop_rect
        tl = self._frame_to_widget(x, y)
        br = self._frame_to_widget(x + w, y + h)
        if tl[0] <= pos.x() <= br[0] and tl[1] <= pos.y() <= br[1]:
            return "inside"
        return None

    # ── mouse events ──
    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        hit = self._hit_test(e.pos())
        if hit is None:
            return
        self._dragging = hit
        self._drag_anchor = e.pos()
        self._drag_orig_rect = self.crop_rect

    def mouseMoveEvent(self, e):
        if self._dragging is None:
            # Update cursor over handle / inside crop
            hit = self._hit_test(e.pos())
            if hit in ("tl", "br"):
                self.setCursor(Qt.SizeFDiagCursor)
            elif hit in ("tr", "bl"):
                self.setCursor(Qt.SizeBDiagCursor)
            elif hit == "inside":
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            return
        # Active drag.
        ox, oy = self._drag_orig_rect[0], self._drag_orig_rect[1]
        ow, oh = self._drag_orig_rect[2], self._drag_orig_rect[3]
        if self._dragging == "inside":
            # Translate by frame-pixel delta.
            df_x, df_y = self._widget_to_frame(e.pos().x(), e.pos().y())
            af_x, af_y = self._widget_to_frame(self._drag_anchor.x(),
                                                self._drag_anchor.y())
            dx, dy = df_x - af_x, df_y - af_y
            nx = max(0, min(self._frame_w - ow, ox + dx))
            ny = max(0, min(self._frame_h - oh, oy + dy))
            self.crop_rect = (nx, ny, ow, oh)
        else:
            fx, fy = self._widget_to_frame(e.pos().x(), e.pos().y())
            x0, y0 = ox, oy
            x1, y1 = ox + ow, oy + oh
            if "l" in self._dragging:
                x0 = min(x1 - 10, fx)
            if "r" in self._dragging:
                x1 = max(x0 + 10, fx)
            if "t" in self._dragging:
                y0 = min(y1 - 10, fy)
            if "b" in self._dragging:
                y1 = max(y0 + 10, fy)
            self.crop_rect = (x0, y0, x1 - x0, y1 - y0)
        self.update()

    def mouseReleaseEvent(self, e):
        self._dragging = None
        self._drag_anchor = None
        self._drag_orig_rect = None

    # ── paint ──
    def paintEvent(self, event):
        super().paintEvent(event)
        if self._pixmap is None:
            return
        ox, oy, dw, dh = self._disp_rect()
        from PyQt5.QtGui import QPainter, QPen, QColor
        painter = QPainter(self)
        scaled = self._pixmap.scaled(dw, dh, Qt.KeepAspectRatio,
                                      Qt.SmoothTransformation)
        painter.drawPixmap(ox, oy, scaled)
        if self.crop_enabled and self.crop_rect:
            x, y, w, h = self.crop_rect
            tl = self._frame_to_widget(x, y)
            br = self._frame_to_widget(x + w, y + h)
            # Dim outside-crop area.
            dim = QColor(0, 0, 0, 130)
            painter.fillRect(0, 0, self.width(), tl[1], dim)
            painter.fillRect(0, br[1], self.width(),
                              self.height() - br[1], dim)
            painter.fillRect(0, tl[1], tl[0], br[1] - tl[1], dim)
            painter.fillRect(br[0], tl[1], self.width() - br[0],
                              br[1] - tl[1], dim)
            # Crop outline.
            painter.setPen(QPen(QColor("#E8C547"), 2))
            painter.drawRect(tl[0], tl[1], br[0] - tl[0], br[1] - tl[1])
            # Corner handles.
            painter.setBrush(QColor("#E8C547"))
            for cx, cy in self._crop_corners_widget().values():
                painter.drawRect(cx - 5, cy - 5, 10, 10)


class TrimCropDialog(QDialog):
    """Per-video trim + crop popup. Frame preview + two scrub sliders
    (start / end) + optional crop rectangle."""

    def __init__(self, parent, path, current_settings):
        super().__init__(parent)
        self.setWindowTitle(f"Trim & Crop — {os.path.basename(path)}")
        self.setMinimumSize(640, 560)
        self.path = path

        # Probe video
        from core.video import probe
        cap = cv2.VideoCapture(path)
        self.fps, self.n_frames = probe(cap)
        cap.release()
        self.duration = self.n_frames / self.fps if self.fps > 0 else 0.0

        # Result fields
        cur_start = float(current_settings.get("trim_start", 0.0))
        cur_dur   = float(current_settings.get("trim_duration", 0.0))
        cur_end   = (cur_start + cur_dur) if cur_dur > 0 else self.duration
        self._initial_crop = current_settings.get("crop")  # dict or None

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)

        v.addWidget(QLabel(
            f"Duration: {self.duration:.2f} s  ·  {self.n_frames} frames @ {self.fps:.1f} fps"
        ))

        self.frame_lbl = _CropFrameLabel()
        v.addWidget(self.frame_lbl, 1)

        self.lbl_showing = QLabel("Showing: start")
        theme.set_tone(self.lbl_showing, "faint", "font-size:11px;")
        v.addWidget(self.lbl_showing)

        # Single timeline with two handles (left=start, right=end).
        self.range_slider = _RangeSlider()
        self.range_slider.setRange(0, max(0, self.n_frames - 1))
        self.range_slider.setStart(int(cur_start * self.fps))
        self.range_slider.setEnd(min(int(cur_end * self.fps), self.n_frames - 1))
        self.range_slider.handle_moved.connect(self._on_handle_moved)
        v.addWidget(self.range_slider)

        # Numeric readouts under the timeline.
        labels_row = QHBoxLayout()
        self.lbl_start = QLabel("Start: 0.00 s")
        self.lbl_dur   = QLabel("Duration: 0.00 s")
        theme.set_tone(self.lbl_dur, "accent", "font-weight:bold;")
        self.lbl_end   = QLabel("End: 0.00 s")
        labels_row.addWidget(self.lbl_start)
        labels_row.addStretch()
        labels_row.addWidget(self.lbl_dur)
        labels_row.addStretch()
        labels_row.addWidget(self.lbl_end)
        v.addLayout(labels_row)

        # ±1s nudge buttons — fine control next to each handle. Frame-quantized
        # so a button press always lands on an exact frame boundary.
        nudge_row = QHBoxLayout()
        nudge_row.setSpacing(4)
        btn_start_back = QPushButton("Start −1s")
        btn_start_fwd  = QPushButton("Start +1s")
        btn_end_back   = QPushButton("End −1s")
        btn_end_fwd    = QPushButton("End +1s")
        for b in (btn_start_back, btn_start_fwd, btn_end_back, btn_end_fwd):
            b.setFixedHeight(24)
            b.setStyleSheet("font-size:11px; padding:2px 8px;")
        btn_start_back.setToolTip("Move start handle 1 second earlier")
        btn_start_fwd.setToolTip("Move start handle 1 second later (trim more from the start)")
        btn_end_back.setToolTip("Move end handle 1 second earlier (trim more from the end)")
        btn_end_fwd.setToolTip("Move end handle 1 second later")
        btn_start_back.clicked.connect(lambda: self._nudge("start", -1.0))
        btn_start_fwd.clicked.connect(lambda: self._nudge("start", +1.0))
        btn_end_back.clicked.connect(lambda: self._nudge("end", -1.0))
        btn_end_fwd.clicked.connect(lambda: self._nudge("end", +1.0))
        nudge_row.addWidget(btn_start_back)
        nudge_row.addWidget(btn_start_fwd)
        nudge_row.addStretch()
        nudge_row.addWidget(btn_end_back)
        nudge_row.addWidget(btn_end_fwd)
        v.addLayout(nudge_row)

        # Crop is always on — drag handles to set the region. A crop that
        # covers the full frame is treated as "no crop" on save.
        v.addWidget(QLabel(
            "Drag the yellow handles to crop the region the tracker will see."
        ))

        # Buttons
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Save")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

        # Initial frame + restore crop if any (else default to full frame).
        self._cap = cv2.VideoCapture(path)
        self._show_frame_at(self.range_slider.start(), "start")
        self.frame_lbl.crop_enabled = True
        if self._initial_crop:
            c = self._initial_crop
            self.frame_lbl.set_crop_rect(
                (int(c.get("x", 0)), int(c.get("y", 0)),
                 int(c.get("w", 0)), int(c.get("h", 0)))
            )
        else:
            # Default = full frame, so "no drag" = no crop.
            self.frame_lbl.set_crop_rect(
                (0, 0, self.frame_lbl._frame_w, self.frame_lbl._frame_h)
            )
        self._update_labels()

    def _show_frame_at(self, frame_idx, which):
        if self._cap is None or not self._cap.isOpened():
            return
        from core.video import cached_frame_times, seek_exact
        seek_exact(self._cap, frame_idx, cached_frame_times(self.path))
        ret, frame = self._cap.read()
        if ret:
            self.frame_lbl.set_frame(frame)
            self.lbl_showing.setText(f"Showing: {which} (frame {frame_idx})")

    def _on_handle_moved(self, which, frame_idx):
        # Update labels and show the frame for whichever handle just moved.
        self._update_labels()
        self._show_frame_at(frame_idx, which)

    def _nudge(self, which, delta_s):
        """Shift the start or end handle by `delta_s` seconds, frame-quantized.
        The range slider clamps to [min, max] and to the other handle's
        position, so over-shooting just pins at the limit."""
        delta_f = int(round(delta_s * self.fps))
        if delta_f == 0:
            return
        if which == "start":
            self.range_slider.setStart(self.range_slider.start() + delta_f)
            self._on_handle_moved("start", self.range_slider.start())
        else:
            self.range_slider.setEnd(self.range_slider.end() + delta_f)
            self._on_handle_moved("end", self.range_slider.end())

    def _update_labels(self):
        s = self.range_slider.start() / self.fps
        e = self.range_slider.end()   / self.fps
        self.lbl_start.setText(f"Start: {s:.2f} s")
        self.lbl_end.setText(f"End: {e:.2f} s")
        self.lbl_dur.setText(f"Duration: {max(0.0, e - s):.2f} s")

    def closeEvent(self, e):
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        super().closeEvent(e)

    def result_dict(self):
        start_s = self.range_slider.start() / self.fps
        end_s   = self.range_slider.end()   / self.fps
        out = {
            "trim_start":    start_s,
            "trim_duration": max(0.0, end_s - start_s),
        }
        # Crop = full frame ⇒ no crop (saved as None).
        if self.frame_lbl.crop_rect:
            x, y, w, h = self.frame_lbl.crop_rect
            full_w = self.frame_lbl._frame_w
            full_h = self.frame_lbl._frame_h
            covers_all = (x <= 0 and y <= 0 and x + w >= full_w
                           and y + h >= full_h)
            out["crop"] = None if covers_all else {
                "x": int(x), "y": int(y), "w": int(w), "h": int(h),
            }
        else:
            out["crop"] = None
        return out


class ApplyToDialog(QDialog):
    """Pick which fields to copy from the current video, and which targets
    receive them. Returns selected_fields() (set of keys) and
    selected_targets() (list of paths) on accept."""

    TARGET_ALL_OTHERS = "all_others"
    TARGET_UNCONFIGURED = "unconfigured"
    TARGET_PICK = "pick"

    def __init__(self, parent, src_path, all_paths, video_settings):
        super().__init__(parent)
        self.setWindowTitle("Apply settings to other videos")
        self.setMinimumWidth(560)
        self._src_path = src_path
        self._all_paths = list(all_paths)
        self._video_settings = video_settings

        root = QVBoxLayout(self)
        hdr = QLabel(
            f"Source: <b>{os.path.basename(src_path)}</b> — "
            "choose which fields to copy and which videos receive them."
        )
        hdr.setWordWrap(True)
        root.addWidget(hdr)

        body = QHBoxLayout()
        root.addLayout(body, 1)

        # Left: field groups
        fields_box = QGroupBox("Fields")
        fl = QVBoxLayout(fields_box)
        fl.setSpacing(2)
        self._field_checks = {}
        for label, _ in APPLY_FIELD_GROUPS:
            cb = QCheckBox(label)
            cb.setChecked(label in APPLY_DEFAULTS_ON)
            self._field_checks[label] = cb
            fl.addWidget(cb)
        sel_row = QHBoxLayout()
        b_all = QPushButton("Select all")
        b_all.clicked.connect(lambda: self._set_all_fields(True))
        b_none = QPushButton("Clear")
        b_none.clicked.connect(lambda: self._set_all_fields(False))
        sel_row.addWidget(b_all)
        sel_row.addWidget(b_none)
        sel_row.addStretch()
        fl.addLayout(sel_row)
        fl.addStretch()
        body.addWidget(fields_box, 1)

        # Right: targets
        targets_box = QGroupBox("Targets")
        tl = QVBoxLayout(targets_box)
        self._target_group = QButtonGroup(self)
        self._rb_all = QRadioButton("All other videos")
        self._rb_unconfigured = QRadioButton("Unconfigured videos only (no saved settings)")
        self._rb_pick = QRadioButton("Pick specific videos…")
        self._rb_unconfigured.setChecked(True)
        for rb in (self._rb_all, self._rb_unconfigured, self._rb_pick):
            self._target_group.addButton(rb)
            tl.addWidget(rb)
        self._pick_list = QListWidget()
        self._pick_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._pick_list.setEnabled(False)
        for p in self._all_paths:
            if p == src_path:
                continue
            it = QListWidgetItem(os.path.basename(p))
            it.setData(Qt.UserRole, p)
            tagged = "configured" if p in self._video_settings else "unconfigured"
            it.setToolTip(f"{p}\n[{tagged}]")
            self._pick_list.addItem(it)
        tl.addWidget(self._pick_list, 1)
        self._rb_pick.toggled.connect(self._pick_list.setEnabled)
        body.addWidget(targets_box, 1)

        # Buttons
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Apply")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _set_all_fields(self, on):
        for cb in self._field_checks.values():
            cb.setChecked(on)

    def selected_fields(self):
        keys = set()
        for label, group_keys in APPLY_FIELD_GROUPS:
            if self._field_checks[label].isChecked():
                keys.update(group_keys)
        return keys

    def selected_targets(self):
        if self._rb_all.isChecked():
            return [p for p in self._all_paths if p != self._src_path]
        if self._rb_unconfigured.isChecked():
            return [p for p in self._all_paths
                    if p != self._src_path and p not in self._video_settings]
        # pick mode
        out = []
        for i in range(self._pick_list.count()):
            it = self._pick_list.item(i)
            if it.isSelected():
                out.append(it.data(Qt.UserRole))
        return out


class _Spinner(QLabel):
    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._i = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setFixedWidth(14)
        theme.set_tone(self, "accent", "font-size:14px;")
        self.setAlignment(Qt.AlignCenter)

    def start(self):
        self.setText(self._FRAMES[0])
        self.show()
        self._timer.start(90)

    def stop(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._i = (self._i + 1) % len(self._FRAMES)
        self.setText(self._FRAMES[self._i])


class ResultCard(QFrame):
    def __init__(self, video_path, animal_id, metrics, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("ResultCard")  # styled in theme.py
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(2)
        title = animal_id or os.path.splitext(os.path.basename(video_path))[0]
        h_title = QLabel(f"<b>{title}</b>")
        h_title.setStyleSheet("font-size:13px;")
        v.addWidget(h_title)
        # First few key metrics
        keys = [
            "Total Distance (cm)", "Total Distance (px)",
            "Time in Center Zone (s)", "% Time in Center Zone",
            "Center Zone Entries (#)", "Average Speed (cm/s)", "Average Speed (px/s)",
            "Mobility Time (s)", "Latency to First Center Zone Entry (s)",
            "Center Cells Time (s)", "Center Cells Entries (#)",
        ]
        for k in keys:
            if k in metrics:
                row = QLabel(f"<span style='color:{theme.MUTED};'>{k}:</span> "
                             f"<b>{metrics[k]}</b>")
                row.setStyleSheet("font-size:11px;")
                v.addWidget(row)


class ExcelPreviewDialog(QDialog):
    """Per-video Excel preview: Summary / Raw Data / Graphs."""

    def __init__(self, video_path, data, cage_shape="rectangle", parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.data = data
        self.cage_shape = cage_shape
        title = data.get("animal_id") or os.path.splitext(os.path.basename(video_path))[0]
        self.setWindowTitle(f"Excel Preview — {title}")
        self.resize(900, 620)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)

        tabs = QTabWidget()
        tabs.addTab(self._build_summary_tab(), "Summary")
        tabs.addTab(self._build_raw_tab(),     "Raw Data")
        tabs.addTab(self._build_graphs_tab(),  "Graphs")
        outer.addWidget(tabs, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedSize(80, 26)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)

    def _build_summary_tab(self):
        from gui.table_copy import enable_excel_copy
        metrics = self.data["metrics"]
        t = QTableWidget()
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setColumnCount(2)
        t.setHorizontalHeaderLabels(["Metric", "Value"])
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        t.setRowCount(len(metrics))
        for r, (k, v) in enumerate(metrics.items()):
            t.setItem(r, 0, QTableWidgetItem(str(k)))
            t.setItem(r, 1, QTableWidgetItem(str(v)))
        enable_excel_copy(t)
        return t

    def _build_raw_tab(self):
        df = self.data["raw_df"]
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        cap = 5000
        display = df.head(cap)
        cols = list(display.columns)
        t = QTableWidget()
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setColumnCount(len(cols))
        t.setHorizontalHeaderLabels(cols)
        t.setRowCount(len(display))
        for r in range(len(display)):
            for c, val in enumerate(display.iloc[r]):
                try:
                    text = "" if val != val else (f"{val:.3f}" if isinstance(val, float) else str(val))
                except Exception:
                    text = str(val)
                t.setItem(r, c, QTableWidgetItem(text))
        from gui.table_copy import enable_excel_copy
        enable_excel_copy(t)
        v.addWidget(t, 1)
        if len(df) > cap:
            note = QLabel(f"Showing first {cap} of {len(df)} frames. Saved .xlsx contains all rows.")
            theme.set_tone(note, "faint", "font-size:10px;")
            v.addWidget(note)
        return wrap

    def _build_graphs_tab(self):
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(4)

        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("Plot:"))
        self._combo_plot = QComboBox()
        self._combo_plot.addItems(["Trajectory", "Heatmap", "Speed over time"])
        sel_row.addWidget(self._combo_plot, 1)
        self._chk_perspective = QCheckBox("Correct perspective")
        self._chk_perspective.setChecked(True)
        self._chk_perspective.setToolTip(
            "Rectify trajectory to a top-down rectangle using the arena corners.\n"
            "Disabled if arena is not 4 points."
        )
        if not self.data.get("arena_px") or len(self.data["arena_px"]) != 4:
            self._chk_perspective.setEnabled(False)
            self._chk_perspective.setChecked(False)
        sel_row.addWidget(self._chk_perspective)
        v.addLayout(sel_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._graph_lbl = QLabel("(no plot)")
        self._graph_lbl.setAlignment(Qt.AlignCenter)
        self._graph_lbl.setStyleSheet("background:#0A0C0E;")
        scroll.setWidget(self._graph_lbl)
        v.addWidget(scroll, 1)

        self._combo_plot.currentIndexChanged.connect(self._render_plot)
        self._chk_perspective.toggled.connect(lambda _: self._render_plot(self._combo_plot.currentIndex()))
        self._render_plot(0)
        return wrap

    def _sorted_quad(self, pts):
        pts = sorted(pts, key=lambda p: p[1])
        top, bot = sorted(pts[:2], key=lambda p: p[0]), sorted(pts[2:], key=lambda p: p[0])
        return [top[0], top[1], bot[1], bot[0]]  # tl, tr, br, bl

    def _rectify_xy(self, xs, ys):
        import numpy as np
        arena = self.data.get("arena_px") or []
        vw, vh = self.data["video_size"]
        if len(arena) != 4:
            return xs, ys, (vw, vh), arena
        if self.cage_shape == "square":
            S = min(vw, vh)
            TW, TH = S, S
        else:
            TW, TH = vw, vh
        src = np.array(self._sorted_quad(arena), dtype=np.float32)
        dst = np.array([(0, 0), (TW, 0), (TW, TH), (0, TH)], dtype=np.float32)
        try:
            H = cv2.getPerspectiveTransform(src, dst)
        except cv2.error:
            return xs, ys, (vw, vh), arena
        pts = np.array([list(zip(xs, ys))], dtype=np.float32)
        out = cv2.perspectiveTransform(pts, H)[0]
        rect_arena = [(0, 0), (TW, 0), (TW, TH), (0, TH)]
        return out[:, 0], out[:, 1], (TW, TH), rect_arena

    def _render_plot(self, _idx):
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from io import BytesIO
        except Exception:
            self._graph_lbl.setText("matplotlib not available")
            return

        df = self.data["raw_df"]
        kind = self._combo_plot.currentText()

        x = df["X (px)"].dropna().values if "X (px)" in df.columns else []
        y = df["Y (px)"].dropna().values if "Y (px)" in df.columns else []

        if self._chk_perspective.isChecked() and len(x) > 0:
            x, y, (vw, vh), arena = self._rectify_xy(x, y)
        else:
            vw, vh = self.data["video_size"]
            arena = self.data.get("arena_px")

        is_dark = False          # preview plots use the light figure palette
        bg = "#FBFBF9"
        fig, ax = plt.subplots(figsize=(7, 7 * vh / vw), facecolor=bg)
        ax.set_facecolor(bg)
        ax.set_xlim(0, vw); ax.set_ylim(vh, 0)
        ax.set_xticks([]); ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(is_dark)
        edge_color = "#A9B4C6"
        if arena and not is_dark:
            xs = [p[0] for p in arena] + [arena[0][0]]
            ys = [p[1] for p in arena] + [arena[0][1]]
            ax.plot(xs, ys, color=edge_color, linewidth=1.5)
        elif arena:
            xs = [p[0] for p in arena] + [arena[0][0]]
            ys = [p[1] for p in arena] + [arena[0][1]]
            ax.plot(xs, ys, color="#888", linewidth=1)

        if kind == "Trajectory" and len(x) > 1:
            ax.plot(x, y, color="#1B2436", linewidth=1.2, alpha=0.9,
                    solid_capstyle="round", solid_joinstyle="round")
            ax.plot([x[0]], [y[0]], "o", color="#2F7A4B",
                    markersize=7, markeredgecolor="#FBFBF9", markeredgewidth=1.0)
            ax.plot([x[-1]], [y[-1]], "s", color="#B3382E",
                    markersize=7, markeredgecolor="#FBFBF9", markeredgewidth=1.0)
        elif kind == "Heatmap" and len(x) > 0:
            ax.hexbin(x, y, gridsize=40, cmap="viridis", mincnt=1)
        elif kind == "Speed over time":
            ax.clear()
            ax.set_facecolor(bg)
            t_col = "Time (s)" if "Time (s)" in df.columns else None
            s_col = "Speed (cm/s)" if "Speed (cm/s)" in df.columns else (
                "Speed (px/s)" if "Speed (px/s)" in df.columns else None)
            if t_col and s_col:
                ax.plot(df[t_col], df[s_col], color="#1B2436", linewidth=0.8)
                ax.set_xlabel("Time (s)", color="#16181B")
                ax.set_ylabel(s_col, color="#16181B")
                ax.tick_params(colors="#4D535A")
                for spine in ax.spines.values():
                    spine.set_color("#16181B")
            else:
                ax.text(0.5, 0.5, "Speed columns missing", color="#8A8F95",
                        ha="center", va="center", transform=ax.transAxes)

        buf = BytesIO()
        fig.tight_layout(pad=0.5)
        fig.savefig(buf, format="png", dpi=110, facecolor=bg)
        plt.close(fig)
        from PyQt5.QtGui import QPixmap
        pix = QPixmap()
        pix.loadFromData(buf.getvalue())
        self._graph_lbl.setPixmap(pix)
        self._graph_lbl.setMinimumSize(pix.size())


class ExperimentBatchTab(QWidget):
    """Main tab: video-list-centric Open Field workflow."""

    # Subclasses (Y-Maze) override to embed a different experiment tab.
    embedded_tab_class = OpenFieldTab

    def __init__(self, config, parent=None, tab_class=None):
        super().__init__(parent)
        self.config = config
        if tab_class is not None:
            self.embedded_tab_class = tab_class
        self.setAcceptDrops(True)
        # path -> snapshot dict (set once configured)
        self.video_settings = {}
        # path -> last-known status
        self.video_status = {}
        # ordered list of video paths (matches list order)
        self.videos = []
        # row widgets keyed by path
        self.row_widgets = {}
        self._stop_flag = False
        self._tracker_thread = None
        # Lock to drop row clicks while a video load is in flight.
        # Prevents stacking up cv2 reads / bg-builder threads on rapid clicks.
        self._loading = False
        # Completed video results: list of (path, animal_id, metrics_dict, metadata_dict)
        self._completed = []
        # Per-video full data for Excel preview: path -> dict(metrics, raw_df, bin_df, arena_px, vw, vh, animal_id)
        self._completed_data = {}
        self._scrub_path = None
        self._scrub_cap = None
        self._scrub_active = False

        self._read_only = False
        self._build_ui()
        QShortcut(QKeySequence("Ctrl+Up"),   self, activated=lambda: self._copy_from_neighbor(-1))
        QShortcut(QKeySequence("Ctrl+Down"), self, activated=lambda: self._copy_from_neighbor(+1))

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_export_tab(self):
        """Export tab — output folder + per-video and batch re-export buttons."""
        from PyQt5.QtWidgets import QGridLayout, QRadioButton, QButtonGroup, QScrollArea
        from gui.out_widgets import Section
        from gui.widgets_v2 import SegTabs, form_row
        from gui.responsive import FlowLayout
        w = QWidget()
        w.setObjectName("OutPage")
        outer = QVBoxLayout(w)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(0)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # ── Output folder section
        folder_box = Section("Export folder")
        fl = QHBoxLayout()
        fl.setSpacing(6)
        self.lbl_output = ElidingLabel("(not set)")
        self.lbl_output.setObjectName("PathBox")
        self.lbl_output.setFixedHeight(28)
        self.lbl_output.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fl.addWidget(self.lbl_output, 1)
        b_change = QPushButton("Change…")
        b_change.setToolTip("Folder the export dialogs open in. Every export still lets you pick.")
        b_change.clicked.connect(self._change_output_folder)
        fl.addWidget(b_change)
        b_open = QPushButton("Open")
        b_open.clicked.connect(self._open_output_folder)
        fl.addWidget(b_open)
        folder_box.body.addLayout(fl)
        self.lbl_backup_note = QLabel("")
        self.lbl_backup_note.setTextFormat(Qt.RichText)
        self.lbl_backup_note.setWordWrap(True)
        theme.set_tone(self.lbl_backup_note, "faint", "font-size:11px;")
        folder_box.body.addWidget(self.lbl_backup_note)
        grid.addWidget(folder_box, 0, 0)

        # ── Batch downloads
        batch_box = Section("Downloads")
        self.lbl_export_batch = QLabel("Completed: 0 video(s).")
        theme.set_tone(self.lbl_export_batch, "text2", "font-size:11px;")
        batch_box.header.addWidget(self.lbl_export_batch)
        batch_btn_row = QHBoxLayout()
        batch_btn_row.setSpacing(6)
        self.btn_combined_excel = QPushButton("Combined Excel")
        self.btn_combined_excel.setProperty("primary", True)
        self.btn_combined_excel.setFixedHeight(28)
        self.btn_combined_excel.setEnabled(False)
        self.btn_combined_excel.setToolTip(
            "One xlsx with All Animals master sheet + per-animal dashboard "
            "(metadata / metrics / time bins + 5 graphs)."
        )
        self.btn_combined_excel.clicked.connect(self._save_combined_excel)
        batch_btn_row.addWidget(self.btn_combined_excel)
        self.btn_combined_raw = QPushButton("Download raw data")
        self.btn_combined_raw.setFixedHeight(28)
        self.btn_combined_raw.setEnabled(False)
        self.btn_combined_raw.setToolTip(
            "One xlsx with one sheet per animal. Each sheet has the "
            "animal's metadata at the top and the full per-frame raw "
            "data below."
        )
        self.btn_combined_raw.clicked.connect(self._save_combined_raw)
        batch_btn_row.addWidget(self.btn_combined_raw)
        batch_btn_row.addStretch(1)
        batch_box.body.addLayout(batch_btn_row)

        # Graph style used for every graph written to disk (Excel images,
        # combined Excel, SVG / PDF). Remembered in config.
        class _PresetCombo(QComboBox):
            def __init__(self, refill):
                super().__init__()
                self._refill = refill

            def showPopup(self):            # pick up presets made meanwhile
                self._refill()
                super().showPopup()

        self.combo_export_preset = _PresetCombo(self._fill_export_presets)
        self.combo_export_preset.setToolTip(
            "Preset used for exported graphs: Excel images, the combined "
            "Excel and SVG / PDF files. Presets are made in Customize graphs."
        )
        self._fill_export_presets()
        self.combo_export_preset.currentIndexChanged.connect(self._on_export_preset)
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        preset_lbl = QLabel("Graph style")
        theme.set_tone(preset_lbl, "text2", "font-size:11px;")
        preset_row.addWidget(preset_lbl)
        preset_row.addWidget(self.combo_export_preset, 1)
        batch_box.body.addLayout(preset_row)
        hint = QLabel(
            "Each video's Excel is backed up automatically when tracking "
            "finishes. The buttons above ask where to save the export."
        )
        theme.set_tone(hint, "faint", "font-size:11px;")
        hint.setWordWrap(True)
        batch_box.body.addWidget(hint)
        grid.addWidget(batch_box, 0, 1)

        # ── Vector graphs (auto-save SVG / PDF beside each per-video Excel)
        vec_box = Section("Vector graph exports")
        vec_row = QHBoxLayout()
        vec_row.setSpacing(16)
        self.chk_export_svg = QCheckBox("Also save SVG")
        self.chk_export_svg.setChecked(bool(self.config.get("export_svg", False)))
        self.chk_export_svg.toggled.connect(
            lambda v: (self.config.__setitem__("export_svg", bool(v)),
                       self._save_config())
        )
        vec_row.addWidget(self.chk_export_svg)
        self.chk_export_pdf = QCheckBox("Also save PDF")
        self.chk_export_pdf.setChecked(bool(self.config.get("export_pdf", False)))
        self.chk_export_pdf.toggled.connect(
            lambda v: (self.config.__setitem__("export_pdf", bool(v)),
                       self._save_config())
        )
        vec_row.addWidget(self.chk_export_pdf)
        vec_row.addStretch(1)
        self.btn_export_vectors = QPushButton("Export graphs now")
        self.btn_export_vectors.setFixedHeight(28)
        self.btn_export_vectors.setToolTip(
            "Write SVG / PDF graphs for every tracked video now (new runs "
            "also write them automatically when tracking finishes)."
        )
        self.btn_export_vectors.clicked.connect(self._export_vectors_now)
        vec_row.addWidget(self.btn_export_vectors)
        vec_box.body.addLayout(vec_row)
        self.lbl_vec_status = QLabel("")
        self.lbl_vec_status.setWordWrap(True)
        theme.set_tone(self.lbl_vec_status, "text2", "font-size:11px;")
        vec_box.body.addWidget(self.lbl_vec_status)
        vec_hint = QLabel(
            "Written next to the PNGs, one file per graph per video — ready "
            "for figures. SVG opens in Inkscape / Illustrator; PDF is "
            "publication-ready."
        )
        theme.set_tone(vec_hint, "faint", "font-size:11px;")
        vec_hint.setWordWrap(True)
        vec_box.body.addWidget(vec_hint)
        vec_box.body.addStretch(1)
        grid.addWidget(vec_box, 1, 0, Qt.AlignTop)

        # ── Annotated video (per-loaded-video render with overlays burned in)
        video_box = Section("Annotated video")
        hint_av = QLabel(
            "Save a copy of the loaded video with the overlays you pick "
            "below burned into the frames. Range: trim window."
        )
        theme.set_tone(hint_av, "faint", "font-size:11px;")
        hint_av.setWordWrap(True)
        video_box.body.addWidget(hint_av)

        # Overlay checkboxes — two-column grid for compactness.
        chk_grid = QGridLayout()
        chk_grid.setHorizontalSpacing(12)
        chk_grid.setVerticalSpacing(4)

        def _mk_chk(label, tip=""):
            c = QCheckBox(label)
            c.setChecked(True)
            if tip:
                c.setToolTip(tip)
            return c
        self.chk_export_arena     = _mk_chk("Arena outline")
        self.chk_export_center    = _mk_chk("Center zone")
        self.chk_export_grid      = _mk_chk("Grid 4×4",
            "Only renders when zone style is Grid.")
        self.chk_export_exclusion = _mk_chk("Exclusion mask")
        self.chk_export_ellipse   = _mk_chk("Bounding ellipse")
        self.chk_export_trail     = _mk_chk("Trail")
        self.chk_export_trail_fade = _mk_chk("Trail fade",
            "On: older trail segments dimmer/thinner.\n"
            "Off: solid body-color trail throughout.")
        self.chk_export_trail_fade.setChecked(True)
        self.chk_export_tag       = _mk_chk("Marker info tag",
            "Small tag next to the marker: animal · speed / x y position.")
        self.chk_export_cell_hi   = _mk_chk("Cell highlight",
            "Semi-transparent fill on the cell currently containing the body.")
        self.chk_export_cell_num  = _mk_chk("Cell numbers",
            "Cell ids drawn at each cell corner (1–16 in Grid mode).")
        self.chk_export_cell_tim  = _mk_chk("Cell timer",
            "Cumulative seconds per cell, drawn in the cell.")
        self.chk_export_cell_ent  = _mk_chk("Cell entries",
            "Cumulative entry count per cell.")
        self.chk_export_view_fx   = _mk_chk("Apply preprocessing",
            "Applies brightness / contrast / blur / CLAHE etc.\n"
            "Off = raw frame.")
        chks = [
            self.chk_export_arena,     self.chk_export_center,
            self.chk_export_grid,      self.chk_export_exclusion,
            self.chk_export_ellipse,   self.chk_export_trail,
            self.chk_export_trail_fade, self.chk_export_tag,
            self.chk_export_cell_hi,   self.chk_export_cell_num,
            self.chk_export_cell_tim,  self.chk_export_cell_ent,
            self.chk_export_view_fx,
        ]
        for i, c in enumerate(chks):
            chk_grid.addWidget(c, i // 2, i % 2)
        video_box.body.addLayout(chk_grid)

        # Body-style dropdown — mirrors the View popover's combo; the user
        # can override here before clicking Render.
        self.combo_export_body_style = QComboBox()
        self.combo_export_body_style.addItem("Off", "off")
        self.combo_export_body_style.addItem("Center", "dot")
        self.combo_export_body_style.addItem("Center + nose + tail", "ends")
        self.combo_export_body_style.setCurrentIndex(1)
        video_box.body.addWidget(form_row("Body markers", self.combo_export_body_style, 96))

        self.spin_export_trail_len = QSpinBox()
        self.spin_export_trail_len.setRange(0, 100000)
        self.spin_export_trail_len.setValue(0)  # "All frames" by default
        self.spin_export_trail_len.setSuffix(" frames")
        self.spin_export_trail_len.setSpecialValueText("All frames")
        self.spin_export_trail_len.setToolTip(
            "Length of the trail drawn behind the body.\n"
            "0 = full path from start of video."
        )
        video_box.body.addWidget(form_row("Trail length", self.spin_export_trail_len, 96))

        self.spin_export_smooth = QSpinBox()
        self.spin_export_smooth.setRange(0, 30)
        self.spin_export_smooth.setValue(0)
        self.spin_export_smooth.setSuffix(" frames")
        self.spin_export_smooth.setSpecialValueText("Off")
        self.spin_export_smooth.setToolTip(
            "Moving-average window applied to the body-center track\n"
            "before drawing the trail and body marker in the export.\n"
            "Doesn't change the live preview or the saved metrics. 0 = off."
        )
        video_box.body.addWidget(form_row("Smooth path", self.spin_export_smooth, 96))

        # Target scope: hidden radios (data) + segmented selector.
        self.rb_export_current = QRadioButton("Current video")
        self.rb_export_all     = QRadioButton("All completed")
        self.rb_export_pick    = QRadioButton("Pick…")
        self.rb_export_current.setChecked(True)
        self._export_scope_group = QButtonGroup(video_box)
        self._export_scope_group.addButton(self.rb_export_current, 0)
        self._export_scope_group.addButton(self.rb_export_all, 1)
        self._export_scope_group.addButton(self.rb_export_pick, 2)
        radios = (self.rb_export_current, self.rb_export_all, self.rb_export_pick)
        for rb in radios:
            rb.hide()
            video_box.body.addWidget(rb)
        scope_seg = SegTabs(["Current video", "All completed", "Pick…"])
        scope_seg.changed.connect(lambda i: radios[i].setChecked(True))
        video_box.body.addWidget(form_row("Render", scope_seg, 96))

        av_row = QHBoxLayout()
        av_row.setSpacing(6)
        self.btn_export_video = QPushButton("Render…")
        self.btn_export_video.setProperty("primary", True)
        self.btn_export_video.setFixedHeight(28)
        self.btn_export_video.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_export_video.clicked.connect(self._on_export_video_clicked)
        av_row.addWidget(self.btn_export_video)
        self.btn_export_video_stop = QPushButton("Stop")
        self.btn_export_video_stop.setFixedHeight(28)
        self.btn_export_video_stop.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_export_video_stop.setEnabled(False)
        self.btn_export_video_stop.clicked.connect(self._on_export_video_stop)
        av_row.addWidget(self.btn_export_video_stop)
        self.progress_export_video = QProgressBar()
        self.progress_export_video.setRange(0, 100)
        self.progress_export_video.setVisible(False)
        av_row.addWidget(self.progress_export_video, 1)
        video_box.body.addLayout(av_row)
        self.lbl_export_video = QLabel("")
        theme.set_tone(self.lbl_export_video, "faint", "font-size:11px;")
        self.lbl_export_video.setWordWrap(True)
        video_box.body.addWidget(self.lbl_export_video)
        grid.addWidget(video_box, 1, 1, Qt.AlignTop)
        self._export_video_thread = None

        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        gw = QWidget()
        gw.setLayout(grid)
        gw.setMaximumWidth(1040)
        wl.addWidget(gw)
        wl.addStretch(1)
        outer.addWidget(wrap)

        # Status line
        self.lbl_export_status = QLabel("")
        theme.set_tone(self.lbl_export_status, "accent", "font-size:11px;")
        self.lbl_export_status.setWordWrap(True)
        outer.addSpacing(10)
        outer.addWidget(self.lbl_export_status)

        outer.addStretch(1)
        self._refresh_output_label()
        # Scrollable: at small window sizes the tab scrolls (vertically and,
        # if needed, horizontally) instead of squashing/overlapping controls.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(w)
        return scroll

    # ── Annotated-video export handlers (button lives in the Export tab,
    # rendering uses the embedded OpenFieldTab's state).

    def _collect_export_flags(self):
        body_style = self.combo_export_body_style.currentData()
        return {
            "arena":          self.chk_export_arena.isChecked(),
            "center_zone":    self.chk_export_center.isChecked(),
            "grid":           self.chk_export_grid.isChecked(),
            "exclusion":      self.chk_export_exclusion.isChecked(),
            "body_style":     body_style,
            "body":           body_style != "off",
            "ellipse":        self.chk_export_ellipse.isChecked(),
            "trail":          self.chk_export_trail.isChecked(),
            "trail_fade":     self.chk_export_trail_fade.isChecked(),
            "marker_tag":     self.chk_export_tag.isChecked(),
            "trail_len":      int(self.spin_export_trail_len.value()),
            "smooth_n":       int(self.spin_export_smooth.value()),
            "cell_highlight": self.chk_export_cell_hi.isChecked(),
            "cell_numbers":   self.chk_export_cell_num.isChecked(),
            "cell_timer":     self.chk_export_cell_tim.isChecked(),
            "cell_entries":   self.chk_export_cell_ent.isChecked(),
            "view_effects":   self.chk_export_view_fx.isChecked(),
        }

    def _completed_paths(self):
        """Paths in the user's video-list order that have tracking results."""
        return [p for p in self.videos if p in self._completed_data]

    def _pick_export_targets(self, completed):
        """Modal listing completed videos with checkboxes. Returns chosen
        paths (list) or None if cancelled."""
        from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                     QDialogButtonBox)
        dlg = QDialog(self)
        dlg.setWindowTitle("Pick videos to render")
        dlg.setMinimumWidth(480)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(
            "Select which completed videos to render with the chosen overlays."
        ))
        # Select-all / clear row.
        ctl_row = QHBoxLayout()
        b_all   = QPushButton("Select all")
        b_clear = QPushButton("Clear")
        ctl_row.addWidget(b_all)
        ctl_row.addWidget(b_clear)
        ctl_row.addStretch()
        v.addLayout(ctl_row)
        # Checkbox list.
        boxes = []
        for p in completed:
            cb = QCheckBox(os.path.basename(p))
            cb.setChecked(True)
            cb.setProperty("path", p)
            cb.setStyleSheet("font-size:11px;")
            v.addWidget(cb)
            boxes.append(cb)
        b_all.clicked.connect(lambda: [c.setChecked(True) for c in boxes])
        b_clear.clicked.connect(lambda: [c.setChecked(False) for c in boxes])
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec_() != QDialog.Accepted:
            return None
        return [c.property("path") for c in boxes if c.isChecked()]

    def _on_export_video_clicked(self):
        et = getattr(self, "embedded_tab", None)
        if et is None:
            return
        if self._export_video_thread is not None:
            return
        # Mirror View popup's body-style into the export combo at render time.
        view_combo = getattr(et, "combo_body_style", None)
        if view_combo is not None:
            idx = self.combo_export_body_style.findData(view_combo.currentData())
            if idx >= 0:
                self.combo_export_body_style.setCurrentIndex(idx)
        completed = self._completed_paths()
        # Determine targets per scope radio.
        if self.rb_export_current.isChecked():
            cur = getattr(et, "video_path", None)
            if not cur:
                QMessageBox.warning(self, "No video",
                                    "Click a video in the list first.")
                return
            if cur not in self._completed_data:
                QMessageBox.warning(self, "Not tracked yet",
                                    "Run tracking on this video first.")
                return
            targets = [cur]
        elif self.rb_export_all.isChecked():
            if not completed:
                QMessageBox.warning(self, "Nothing to render",
                                    "No completed videos yet.")
                return
            targets = list(completed)
        else:  # Pick…
            if not completed:
                QMessageBox.warning(self, "Nothing to pick from",
                                    "No completed videos yet.")
                return
            picked = self._pick_export_targets(completed)
            if picked is None:
                return
            if not picked:
                self.lbl_export_video.setText("Nothing selected.")
                theme.set_tone(self.lbl_export_video, "faint", "font-size:11px;")
                return
            targets = picked
        # Every target is written as <chosen folder>/<videoname>_annotated.mp4.
        out_folder = self._ask_export_folder("Save rendered video(s) to…")
        if not out_folder:
            return
        # Warn before silently overwriting any existing files.
        existing = []
        queue = []
        for p in targets:
            base = os.path.splitext(os.path.basename(p))[0]
            out_path = os.path.join(out_folder, f"{base}_annotated.mp4")
            if os.path.exists(out_path):
                existing.append(os.path.basename(out_path))
            queue.append((p, out_path))
        if existing:
            n = len(existing)
            ans = QMessageBox.question(
                self, "Overwrite existing files?",
                f"{n} annotated video(s) already exist in the output folder "
                "and will be overwritten:\n\n  • " +
                "\n  • ".join(existing[:8]) +
                ("\n  • …" if len(existing) > 8 else "") +
                "\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if ans != QMessageBox.Yes:
                return
        # Save the original loaded path so we can restore the embedded panel
        # to whatever the user was looking at after the batch finishes.
        self._export_queue = queue
        self._export_total = len(queue)
        self._export_done_count = 0
        self._export_failed = []
        self._export_stop_requested = False
        self._export_orig_path = getattr(et, "video_path", None)
        self.progress_export_video.setVisible(True)
        self.progress_export_video.setValue(0)
        self.btn_export_video.setEnabled(False)
        self.btn_export_video_stop.setEnabled(True)
        self._start_next_export()

    def _start_next_export(self):
        if self._export_stop_requested or not self._export_queue:
            self._on_export_all_done()
            return
        path, out = self._export_queue.pop(0)
        idx = self._export_done_count + 1
        self.lbl_export_video.setText(
            f"Rendering {idx}/{self._export_total}: {os.path.basename(path)}…"
        )
        theme.set_tone(self.lbl_export_video, "faint", "font-size:11px;")
        # Load the target into the embedded tab if it isn't already loaded.
        et = self.embedded_tab
        if getattr(et, "video_path", None) != path:
            try:
                self._load_into_embedded(path)
            except Exception as e:
                self._export_failed.append((path, str(e)))
                self._export_done_count += 1
                self._start_next_export()
                return
        fps = et.fps or 30.0
        total = int(getattr(et, "_total_frames", 0) or 0)
        if total <= 0:
            self._export_failed.append((path, "no frame count"))
            self._export_done_count += 1
            self._start_next_export()
            return
        start_f = max(0, int(round(et._trim_start_s() * fps)))
        dur_s = et._trim_duration_s()
        end_f = total - 1
        if dur_s > 0:
            end_f = min(total - 1, start_f + int(round(dur_s * fps)) - 1)
        if end_f < start_f:
            end_f = start_f
        flags = self._collect_export_flags()
        from core.io.video_export import VideoExportThread
        t = VideoExportThread(et, out, start_f, end_f, flags=flags)
        t.progress.connect(self._on_one_export_progress)
        t.error.connect(self._on_one_export_error)
        t.done.connect(self._on_one_export_done)
        t.finished.connect(lambda: setattr(self, "_export_video_thread", None))
        self._export_video_thread = t
        t.start()

    def _on_one_export_progress(self, pct):
        # Combine per-video progress with overall progress.
        if self._export_total <= 0:
            self.progress_export_video.setValue(int(pct))
            return
        per_video_share = 100.0 / self._export_total
        overall = self._export_done_count * per_video_share + (pct / 100.0) * per_video_share
        self.progress_export_video.setValue(int(overall))

    def _on_one_export_done(self, _out):
        self._export_done_count += 1
        # Schedule the next render on the event loop so the previous thread
        # can finish + clean up before we kick off another.
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, self._start_next_export)

    def _on_one_export_error(self, msg):
        # Record the failure but keep going through the queue.
        path = "(unknown)"
        self._export_failed.append((path, msg))
        self._export_done_count += 1
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, self._start_next_export)

    def _on_export_video_stop(self):
        self._export_stop_requested = True
        # Drop pending queue + cancel current thread.
        self._export_queue = []
        if self._export_video_thread is not None:
            try:
                self._export_video_thread.stop()
            except Exception:
                pass

    def _on_export_all_done(self):
        self.progress_export_video.setVisible(False)
        self.btn_export_video.setEnabled(True)
        self.btn_export_video_stop.setEnabled(False)
        ok = self._export_done_count - len(self._export_failed)
        if self._export_stop_requested:
            self.lbl_export_video.setText(
                f"Cancelled. Saved {ok} of {self._export_total}."
            )
            theme.set_tone(self.lbl_export_video, "warn", "font-size:11px;")
        elif self._export_failed:
            self.lbl_export_video.setText(
                f"Saved {ok} / {self._export_total}. "
                f"{len(self._export_failed)} failed."
            )
            theme.set_tone(self.lbl_export_video, "err", "font-size:11px;")
        else:
            self.lbl_export_video.setText(
                f"Saved {ok} video(s)." if ok != 1 else "Saved 1 video."
            )
            theme.set_tone(self.lbl_export_video, "ok", "font-size:11px;")
        # Restore the originally-loaded video.
        try:
            if (self._export_orig_path and
                    self.embedded_tab.video_path != self._export_orig_path):
                self._load_into_embedded(self._export_orig_path)
        except Exception:
            pass
        from gui.notify import show_done
        folder = self.config.get("output_folder") or None
        if self._export_stop_requested:
            show_done(self, "Video render cancelled",
                      f"{ok} of {self._export_total} video(s) were saved before stopping.",
                      folder=folder, kind="warn")
        elif self._export_failed:
            show_done(self, "Video render finished with errors",
                      f"{ok} of {self._export_total} saved, {len(self._export_failed)} failed. "
                      "See Logs for details.", folder=folder, kind="warn")
        else:
            show_done(self, "Videos rendered",
                      "1 annotated video saved." if ok == 1 else f"{ok} annotated videos saved.",
                      folder=folder)

    def _refresh_export_buttons(self):
        """Enable/disable Export-tab buttons based on current state."""
        n = len(self._completed_data)
        if hasattr(self, "btn_combined_excel"):
            self.btn_combined_excel.setEnabled(n > 0)
        if hasattr(self, "btn_combined_raw"):
            self.btn_combined_raw.setEnabled(n > 0)
        if hasattr(self, "lbl_export_batch"):
            self.lbl_export_batch.setText(f"Completed: {n} video(s).")

    def _start_track_timer(self):
        import time as _time
        self._track_t0 = _time.monotonic()
        self._track_timer.start()
        self._render_track_time(per_video=0.0, finishing=False)

    def _set_pill(self, text):
        win = self.window()
        if hasattr(win, "set_tracking_status"):
            win.set_tracking_status(text)

    def _stop_track_timer(self):
        self._track_timer.stop()
        self._set_pill(None)
        if self._track_t0 is not None:
            import time as _time
            elapsed = _time.monotonic() - self._track_t0
            self._render_track_time(per_video=elapsed, finishing=True)
        self._track_t0 = None

    def _tick_track_time(self):
        if self._track_t0 is None:
            return
        import time as _time
        elapsed = _time.monotonic() - self._track_t0
        self._render_track_time(per_video=elapsed, finishing=False)

    def _render_track_time(self, per_video, finishing):
        """Bottom of the run panel: 'elapsed mm:ss' (batch total when a batch
        is running) and an ETA estimated from the progress so far."""
        import time as _time
        vp = float(self.progress_video.value() or 0)
        if self._batch_t0 is not None:
            total = _time.monotonic() - self._batch_t0
            n = max(1, int(self.progress_overall.maximum() or 1))
            idx = float(self.progress_overall.value() or 0)
            frac = (idx + vp / 100.0) / n
            elapsed_txt = f"elapsed {self._fmt_elapsed(total)}"
            eta = (total / frac - total) if frac > 0.01 else None
        else:
            elapsed_txt = (f"done in {self._fmt_elapsed(per_video)}" if finishing
                           else f"elapsed {self._fmt_elapsed(per_video)}")
            eta = (per_video / (vp / 100.0) - per_video) if (vp > 1 and not finishing) else None
        self.lbl_track_time.setText(elapsed_txt)
        self.lbl_eta.setText("" if (finishing or eta is None) else f"eta {self._fmt_elapsed(eta)}")

    def _refresh_queue_stats(self, *_):
        """Queue counters, count pill and batch segments from row states."""
        if not hasattr(self, "queue_stats"):
            return
        rows = [self.row_widgets[p] for p in self.videos if p in self.row_widgets]
        n = len(rows)

        def cnt(s):
            return sum(1 for r in rows if r.status == s)

        done, running = cnt(STATUS_DONE), cnt(STATUS_RUNNING)
        self.pill_count.setText(str(n))
        self.queue_stats.set_counts(done, running, cnt(STATUS_READY),
                                    cnt(STATUS_NEEDS) + cnt(STATUS_ERROR))
        vp = float(self.progress_video.value() or 0) if running else 0.0
        frac = ((done + vp / 100.0) / n) if n else 0.0
        tok = {STATUS_DONE: "OK", STATUS_RUNNING: "ACCENT", STATUS_ERROR: "ERR"}
        self.run_panel.set_batch(done, n, frac * 100.0, [tok.get(r.status, "BORDER") for r in rows])

    @staticmethod
    def _fmt_elapsed(seconds):
        m, s = divmod(int(seconds), 60)
        if m >= 60:
            h, m = divmod(m, 60)
            return f"{h:d}h {m:02d}m {s:02d}s"
        return f"{m:02d}:{s:02d}"

    def _save_combined_raw(self):
        if not self._completed_data:
            self.lbl_export_status.setText("Nothing to export — run tracking first.")
            return
        out_folder = self._ask_export_folder("Save combined raw data to…")
        if not out_folder:
            return
        self._prepare_exports()
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = os.path.join(out_folder, f"open_field_raw-{ts}.xlsx")
        animals = []
        for path, data in self._completed_data.items():
            meta = (self.video_settings.get(path) or {}).get("metadata") or {}
            aid = data.get("animal_id") or meta.get("Animal ID") or \
                  os.path.splitext(os.path.basename(path))[0]
            md = dict(meta)
            md.setdefault("Animal ID", aid)
            animals.append({
                "animal_id": aid,
                "metadata":  md,
                "raw_df":    data.get("raw_df"),
            })
        try:
            from export.excel_export import export_combined_raw
            export_combined_raw(out_path, animals)
            self.lbl_export_status.setText(f"Wrote {out_path}")
            from gui.notify import show_done
            show_done(self, "Raw data exported",
                      f"{len(animals)} animal(s) in one workbook.", path=out_path)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.lbl_export_status.setText(f"Raw-data export failed: {e}")
            from gui.notify import show_done
            show_done(self, "Raw-data export failed", str(e), kind="err")

    # ── Export graph style (preset) ─────────────────────────────────────
    def _chosen_export_preset(self):
        """Saved export preset if it still exists, else the preset active
        in Customize graphs, else "Default"."""
        gs = getattr(getattr(self, "embedded_tab", None), "_graph_style", None)
        if gs is None:
            return None
        names = gs.all_preset_names()
        # The Output graphs and the exports use one preset: the active one.
        for cand in (gs.active_preset, self.config.get("export_graph_preset")):
            if cand in names:
                return cand
        return names[0]

    def _fill_export_presets(self):
        combo = getattr(self, "combo_export_preset", None)
        gs = getattr(getattr(self, "embedded_tab", None), "_graph_style", None)
        if combo is None or gs is None:
            return
        names = gs.all_preset_names()
        want = self._chosen_export_preset()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(names)
        combo.setCurrentText(want)
        combo.blockSignals(False)

    def _on_export_preset(self, _i=None):
        name = self.combo_export_preset.currentText()
        et = getattr(self, "embedded_tab", None)
        # Same preset for the Output graphs and the exports, so what is on
        # screen matches the files.
        if et is not None and hasattr(et, "_choose_graph_preset"):
            if not et._choose_graph_preset(name):
                self._fill_export_presets()          # cancelled → show the active one
                return
        self.config["export_graph_preset"] = name
        self._save_config()

    def _export_preset_name(self):
        """Preset to render exports in, or None when the on-screen graphs
        already are exactly that preset (cached images can be reused)."""
        gs = getattr(getattr(self, "embedded_tab", None), "_graph_style", None)
        name = self._chosen_export_preset()
        if name is None or name == gs.active_preset:
            return None             # exports = the graphs as shown (incl. edits)
        return name

    @contextmanager
    def _export_style(self):
        """Temporarily render the embedded tab's graphs in the export preset."""
        et = self.embedded_tab
        name = self._export_preset_name()
        if name is None:
            yield
            return
        from gui.graph_style import GraphStyleConfig
        saved = et._graph_style
        tmp = GraphStyleConfig.from_dict(saved.to_dict())
        tmp.apply_preset(name)
        et._graph_style = tmp
        try:
            yield
        finally:
            et._graph_style = saved

    def _render_export_pngs(self):
        """PNG bytes of every graph of the loaded video, export look +
        export preset. {} if nothing to draw."""
        et = self.embedded_tab
        if et.raw_df is None or len(et.raw_df) == 0:
            return {}
        x = et.raw_df["X (px)"].dropna().values
        y = et.raw_df["Y (px)"].dropna().values
        if len(x) < 2:
            return {}
        out = {}
        with self._export_style():
            _, arena, _, _ = et._graph_data()
            builders = et._make_graph_builders(x, y, arena)
            et._force_fig_mode = "export"
            try:
                for gname, build in builders.items():
                    try:
                        fig = build()
                        if fig is not None:
                            out[gname] = et._fig_to_pixmap_and_bytes(fig)[1]
                    except Exception as e:
                        logger.warn(f"Export render of '{gname}' failed: {e}", source="graphs")
            finally:
                et._force_fig_mode = None
        return out

    def _for_each_completed(self, fn):
        """Load each tracked video into the embedded tab, call fn(path),
        then put back the video that was showing."""
        from PyQt5.QtWidgets import QApplication
        shown = self._embedded_loaded_path
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for path in list(self._completed_data):
                if self._embedded_loaded_path != path:
                    self._load_into_embedded(path, read_only=True)
                fn(path)
                QApplication.processEvents()
        finally:
            if shown and self._embedded_loaded_path != shown:
                self._load_into_embedded(shown)
            QApplication.restoreOverrideCursor()

    # ── Keep exports identical to what the app shows ─────────────────────

    def _graph_sig(self):
        """Everything that changes how graphs are drawn."""
        import json
        from gui.graph_style import export_bg
        et = getattr(self, "embedded_tab", None)
        gs = getattr(et, "_graph_style", None)
        try:
            return json.dumps([gs.to_dict() if gs is not None else None, export_bg(),
                               ], sort_keys=True, default=str)
        except Exception:
            return None

    def _settings_sig(self, path):
        import json
        try:
            return json.dumps(self.video_settings.get(path) or {}, sort_keys=True, default=str)
        except Exception:
            return None

    def _sync_completed_from_embedded(self):
        """Copy the loaded video's current results (with corrections),
        numbers and graph images into its export cache."""
        path = self._embedded_loaded_path
        data = self._completed_data.get(path) if path else None
        et = self.embedded_tab
        if not data or et._raw_results is None or et.raw_df is None:
            return
        data["results"] = [dict(r) for r in et._raw_results]
        data["metrics"] = dict(et.metrics or {})
        data["raw_df"] = et.raw_df
        data["bin_df"] = et.bin_df
        if getattr(et, "_graph_png_bytes", None):
            data["graph_pngs"] = dict(et._graph_png_bytes)
            data["graph_sig"] = self._graph_sig()
        data["settings_sig"] = self._settings_sig(path)
        for i, row in enumerate(self._completed):
            if row and row[0] == path:
                self._completed[i] = (row[0], row[1], dict(data["metrics"]), row[3])

    def _prepare_exports(self):
        """Before a batch export: save the shown video's edits, then redo
        any video whose numbers or graphs are older than its settings /
        the current graph style."""
        if not getattr(self, "_read_only", False):
            self._capture_embedded_settings()
        self._sync_completed_from_embedded()
        sig = self._graph_sig()
        stale = [p for p, d in self._completed_data.items()
                 if d.get("results") and (d.get("graph_sig") != sig
                                          or d.get("settings_sig") != self._settings_sig(p))]
        if not stale:
            return
        from PyQt5.QtWidgets import QApplication
        shown = self._embedded_loaded_path
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for p in stale:
                if self._embedded_loaded_path == p:
                    self.embedded_tab._recompute_metrics_and_views()
                else:
                    self._load_into_embedded(p, read_only=True)
                self._sync_completed_from_embedded()
                QApplication.processEvents()
        finally:
            if shown and self._embedded_loaded_path != shown:
                self._load_into_embedded(shown)
            QApplication.restoreOverrideCursor()

    def _render_export_pngs_all(self):
        """{path: png map} in the export preset, or {} when cached images match it."""
        if self._export_preset_name() is None:
            return {}
        out = {}
        self._for_each_completed(lambda p: out.__setitem__(p, self._render_export_pngs()))
        return out

    def _write_vector_graphs(self, name, out_folder):
        """SVG / PDF of the loaded video's graphs into <out_folder>/<name>_graphs.
        Returns the number of files written (0 when switched off)."""
        out_folder = (out_folder or "").strip()
        want = [ext for ext, key in ((".svg", "export_svg"), (".pdf", "export_pdf"))
                if self.config.get(key)]
        et = self.embedded_tab
        if not (out_folder and os.path.isdir(out_folder) and want):
            return 0
        graphs_dir = os.path.join(out_folder, f"{name}_graphs")
        prefix = ""
        try:
            os.makedirs(graphs_dir, exist_ok=True)
        except Exception as e:
            logger.warn(f"Vector dir mkdir failed: {e}", source="graphs")
            graphs_dir, prefix = out_folder, f"{name}_"   # don't overwrite other videos
        n = 0
        with self._export_style():
            for gname in list(getattr(et, "_graph_pixmaps", {}) or {}):
                slug = gname.lower().replace(" ", "_")
                for ext in want:
                    if et._export_graph_to_path(gname, os.path.join(graphs_dir, f"{prefix}{slug}{ext}")):
                        n += 1
        return n

    def _export_vectors_now(self):
        lbl = self.lbl_vec_status
        if not (self.config.get("export_svg") or self.config.get("export_pdf")):
            lbl.setText("Tick “Also save SVG” and/or “Also save PDF” first.")
            return
        if not self._completed_data:
            lbl.setText("Nothing to export — run tracking first.")
            return
        out_folder = self._ask_export_folder("Save SVG / PDF graphs to…")
        if not out_folder:
            return
        self._prepare_exports()
        count = {"files": 0, "videos": 0}

        def one(path):
            n = self._write_vector_graphs(os.path.splitext(os.path.basename(path))[0], out_folder)
            count["files"] += n
            count["videos"] += 1 if n else 0
        self._for_each_completed(one)
        if count["files"]:
            lbl.setText(f"Wrote {count['files']} graph file(s) for {count['videos']} "
                        f"video(s) to {out_folder}")
        else:
            lbl.setText("No graphs written — see View → Logs for details.")

    def _save_combined_excel(self):
        if not self._completed_data:
            self.lbl_export_status.setText("Nothing to combine — run tracking first.")
            return
        out_folder = self._ask_export_folder("Save combined Excel to…")
        if not out_folder:
            return
        self._prepare_exports()
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        exp = getattr(self.embedded_tab, "experiment", None) if hasattr(
            self, "embedded_tab"
        ) else None
        exp_key = getattr(exp, "key", None) or "experiment"
        out_path = os.path.join(out_folder, f"{exp_key}_combined-{ts}.xlsx")
        preset_pngs = self._render_export_pngs_all()   # {} when "current"
        animals = []
        for path, data in self._completed_data.items():
            meta = (self.video_settings.get(path) or {}).get("metadata") or {}
            aid = data.get("animal_id") or meta.get("Animal ID") or \
                  os.path.splitext(os.path.basename(path))[0]
            md = dict(meta)
            md.setdefault("Animal ID", aid)
            animals.append({
                "animal_id": aid,
                "metadata":  md,
                "metrics":   data.get("metrics") or {},
                "bin_df":    data.get("bin_df"),
                "graph_pngs": preset_pngs.get(path) or data.get("graph_pngs") or {},
                "video_config": self.video_settings.get(path) or {},
                "video_size":   data.get("video_size"),
            })
        try:
            from export.excel_export import export_combined
            # Pull the section-grouped schema from the active experiment
            # plugin when it provides one; falls back to first-seen order
            # inside export_combined when None.
            schema = None
            exp = getattr(self.embedded_tab, "experiment", None) if hasattr(
                self, "embedded_tab"
            ) else None
            if exp is not None and hasattr(exp, "batch_schema"):
                try:
                    schema = exp.batch_schema()
                except Exception:
                    schema = None
            export_combined(out_path, animals, schema=schema)
            self.lbl_export_status.setText(f"Wrote {out_path}")
            from gui.notify import show_done
            show_done(self, "Combined Excel saved",
                      f"Results of {len(animals)} animal(s) in one workbook.", path=out_path)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.lbl_export_status.setText(f"Combined export failed: {e}")
            from gui.notify import show_done
            show_done(self, "Combined export failed", str(e), kind="err")


    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)  # gutter: aurora shows around the panes
        root.setSpacing(0)

        # ── Left side: session queue
        left = QWidget()
        left.setObjectName("Pane")
        left.setMinimumWidth(200)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)

        qh = PaneHeader("queue", "Queue")
        self.pill_count = qh.add_left(CountPill("0"))
        b_add = IconTextButton("plus", "Add", 11, height=26)
        b_add.setToolTip("Add videos")
        b_add.clicked.connect(self._add_videos)
        b_clear = IconButton("trash", 13, "FAINT", "TEXT", "Clear queue", 26)
        b_clear.clicked.connect(self._clear_videos)
        qh.add_right(b_add)
        qh.add_right(b_clear)
        # qh sits on top of the Queue pane (see the splitter below).

        self.queue_stats = QueueStats()
        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(10, 0, 10, 4)
        stats_row.addWidget(self.queue_stats)
        lv.addLayout(stats_row)

        # Video list (rows are inserted before the drop hint + stretch)
        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.NoFrame)
        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setSpacing(2)
        self.list_layout.setContentsMargins(10, 6, 10, 6)  # same inset as the counters
        self.drop_hint = DropHint()
        self.drop_hint.clicked.connect(self._add_videos)
        self.list_layout.addWidget(self.drop_hint)
        self.list_layout.addStretch()
        self.list_scroll.setWidget(self.list_host)
        lv.addWidget(self.list_scroll, 1)

        self.lbl_status = QLabel("")
        theme.set_tone(self.lbl_status, "muted", "font-size:11px;")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setContentsMargins(12, 4, 12, 4)
        lv.addWidget(self.lbl_status)

        # Run controls + batch progress
        self.run_panel = RunPanel(self._run_all, self._stop)
        self.btn_run_all = self.run_panel.btn_run_all
        self.btn_stop = self.run_panel.btn_stop
        self.progress_overall = _ProgressProxy(self._refresh_queue_stats)
        self.progress_video = _ProgressProxy(self._refresh_queue_stats)
        self.lbl_track_time = self.run_panel.lbl_elapsed
        self.lbl_eta = self.run_panel.lbl_eta
        lv.addWidget(self.run_panel)
        # Timer that updates the elapsed-time label while tracking is running.
        self._track_timer = QTimer(self)
        self._track_timer.setInterval(1000)
        self._track_timer.timeout.connect(self._tick_track_time)
        self._track_t0 = None
        # Set when a batch (Run All) is in progress, so the per-video timer
        # can also show "Batch total: …".
        self._batch_t0 = None
        self._running_path = None
        self._refresh_queue_stats()

        # ── Build embedded OpenFieldTab. We then steal its internal scroll
        # (config column) and right_tabs (preview) and re-parent them as
        # separate splitter children so the user gets 3 draggable panes:
        # list | config | preview.
        cfg_copy = dict(self.config or {})
        cfg_copy.pop("last_video", None)
        cfg_copy.pop("recent_videos", None)
        self.embedded_tab = self.embedded_tab_class(cfg_copy)
        # Embedded tab is parent-less + hidden; QWidget.window() can't reach
        # MainWindow from it, and cfg_copy is detached from self.config.
        # Stash a back-ref so settings that need to persist (graph styles,
        # presets) can write to the live MainWindow config dict.
        self.embedded_tab._batch_owner = self
        try:
            # Keep both tabs — rename "Excel Output" to "Output" so the user
            # sees: [Video Preview] [Output] [Export].
            if hasattr(self.embedded_tab, "right_tabs"):
                rt = self.embedded_tab.right_tabs
                for i in range(rt.count()):
                    if rt.tabText(i).strip().lower() in ("excel output", "output"):
                        rt.setTabText(i, "Output")
                    elif rt.tabText(i).strip().lower() in ("video preview", "preview"):
                        rt.setTabText(i, "Preview")
                # Add the Export tab.
                rt.addTab(self._build_export_tab(), "Export")
        except Exception:
            import traceback
            traceback.print_exc()
        self.embedded_tab.hide()  # never shown directly; we use its parts.

        # Autosave the loaded video's settings whenever the zone drawer
        # commits a change — defining the arena, calibration line, center
        # zone, or painting an exclusion area should not require an extra
        # click to persist.
        try:
            zd = self.embedded_tab.zone_drawer
            zd.zones_changed.connect(self._on_embedded_zones_changed)
            zd.exclusion_changed.connect(self._on_embedded_zones_changed)
        except Exception:
            pass
        # Refresh the per-video metrics cache after every recompute on the
        # embedded panel (arena / calib / sliders that affect metrics). Keeps
        # swap-away/back consistent with the user's edits.
        try:
            self.embedded_tab.metrics_changed.connect(
                self._on_embedded_metrics_changed
            )
        except Exception:
            pass

        # Save reference — _apply_read_only_state needs it after reparenting.
        self._config_scroll = self.embedded_tab.findChild(QScrollArea)

        # ── Middle pane: config column (was fixed-width inside embedded_tab).
        middle = QWidget()
        middle.setObjectName("Pane")
        mv = QVBoxLayout(middle)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(4)
        ch = PaneHeader("config", "Configuration")
        self.btn_apply_to = ch.add_right(IconTextButton("copy", "Apply to…", 12, height=26))
        self.btn_apply_to.setToolTip(
            "Copy selected fields from this video's panel to other videos."
        )
        self.btn_apply_to.clicked.connect(self._open_apply_to_dialog)
        # ch sits on top of the Configuration pane (see the splitter below).
        if self._config_scroll is not None:
            # Let the scroll fill the middle pane; inner panel now has a
            # min width but no fixed width so it stretches with the scroll.
            self._config_scroll.setFrameShape(QFrame.NoFrame)
            self._config_scroll.setMinimumWidth(0)
            self._config_scroll.setMaximumWidth(16777215)
            self._config_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            mv.addWidget(self._config_scroll, 1)

        # ── Right pane: just the preview tabs.
        right = QWidget()
        right.setObjectName("Pane")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(4)

        if hasattr(self.embedded_tab, "right_tabs"):
            from gui.main_tabs import MainTabHeader
            preview_widget = self.embedded_tab.right_tabs
            preview_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            rv.addWidget(MainTabHeader(preview_widget, self.embedded_tab))
            rv.addWidget(preview_widget, 1)

        self._embedded_loaded_path = None


        # ── Main screen: three fixed panes side by side —
        # Queue | Configuration | Preview (no movable / extra panels).
        mp = getattr(self.embedded_tab, "measure_panel", None)
        if mp is not None:
            mp.hide()   # Measurements sidebar is not shown on this screen

        def card(header, body):
            """Pane card: header strip on top of the pane body."""
            header.setProperty("panel", True)
            body.setProperty("panel", True)
            holder = QWidget()
            holder.setObjectName("PanelBody")
            holder.setAttribute(Qt.WA_StyledBackground, True)
            hl = QVBoxLayout(holder)
            hl.setContentsMargins(0, 10, 0, 0)
            hl.setSpacing(0)
            hl.addWidget(body)
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            v.addWidget(header)
            v.addWidget(holder, 1)
            return w

        split = QSplitter(Qt.Horizontal)
        split.setObjectName("MainSplit")
        split.addWidget(card(qh, left))
        split.addWidget(card(ch, middle))
        split.addWidget(right)
        left.setMinimumWidth(200)
        middle.setMinimumWidth(260)
        right.setMinimumWidth(420)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 0)
        split.setStretchFactor(2, 1)
        for i in range(3):
            split.setCollapsible(i, False)
        split.setHandleWidth(10)
        split.setSizes([290, 305, 900])
        root.addWidget(split, 1)
        # Output folder + export buttons live in the Export sub-tab now.

    # ── Drag-and-drop ─────────────────────────────────────────────────────

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                if u.toLocalFile().lower().endswith(VIDEO_EXTS):
                    e.acceptProposedAction()
                    return
        e.ignore()

    def dragMoveEvent(self, e):
        self.dragEnterEvent(e)

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(VIDEO_EXTS) and os.path.isfile(p):
                self._add_video(p)
        e.acceptProposedAction()

    # ── Video list ops ────────────────────────────────────────────────────

    def _add_videos(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select videos", "",
            "Videos (*.mp4 *.avi *.mov *.mkv *.wmv *.flv);;All files (*)"
        )
        for p in paths:
            self._add_video(p)

    def _add_video(self, path):
        if path in self.videos:
            return
        is_first = (
            len(self.videos) == 0
            and getattr(self, "_embedded_loaded_path", None) is None
        )
        self.videos.append(path)
        self.video_status[path] = STATUS_NEEDS
        # Seed auto-from-movement as the arena default so a freshly added
        # video can run without manual arena drawing. _has_arena/preflight
        # read video_settings, not the embedded widget — must persist here.
        # Skip for Y-Maze: it requires user-defined arms, not an auto arena.
        exp_key = getattr(getattr(self.embedded_tab, "experiment", None),
                          "key", None)
        if (path not in self.video_settings and exp_key != "y_maze"
                and self.config.get("enable_auto_movement_arena", False)):
            self.video_settings[path] = {
                "arena_auto_movement": True,
                "arena_define_mode": "movement",
            }
        elif path not in self.video_settings:
            self.video_settings[path] = {}
        row = VideoRow(path, self._on_edit, self._on_run, self._on_remove,
                       self._on_trim)
        self.row_widgets[path] = row
        # insert before stretch
        row.status_changed.connect(self._refresh_queue_stats)
        self.list_layout.insertWidget(self.list_layout.count() - 2, row)
        self._refresh_queue_stats()
        self._refresh_video_combo()
        # First video added → auto-select it so the user lands on a real
        # frame instead of an empty embedded panel.
        if is_first:
            self._load_into_embedded(path)

    def _on_remove(self, path):
        if path not in self.videos:
            return
        was_loaded = self._embedded_loaded_path == path
        self.videos.remove(path)
        self.video_status.pop(path, None)
        self.video_settings.pop(path, None)
        self._completed_data.pop(path, None)
        # Drop this video from the completed-runs list too, so the
        # "Batch finished — N video(s)" counter reflects what's actually
        # in the list, not stale entries from prior batches.
        self._completed = [c for c in self._completed if c[0] != path]
        w = self.row_widgets.pop(path, None)
        if w:
            self.list_layout.removeWidget(w)
            w.setParent(None)
        self._refresh_video_combo()
        # If the removed video was the one shown in the embedded panel,
        # clear it (or load whichever remaining video is at its old index).
        if was_loaded:
            self._embedded_loaded_path = None
            if self.videos:
                self._load_into_embedded(self.videos[0])
            else:
                self._clear_embedded_panel()
        self._refresh_export_buttons()
        self._refresh_queue_stats()

    def _clear_videos(self):
        for p in list(self.videos):
            self._on_remove(p)

    def _on_trim(self, path):
        """Open the trim+crop popup for a single video."""
        if path not in self.videos:
            return
        s = dict(self.video_settings.get(path) or {})
        dlg = TrimCropDialog(self, path, s)
        if dlg.exec_() != QDialog.Accepted:
            return
        out = dlg.result_dict()
        s["trim_start"]    = out["trim_start"]
        s["trim_duration"] = out["trim_duration"]
        s["crop"]          = out["crop"]
        # Crop change invalidates arena/center_zone/exclusion (they were drawn
        # in the old coordinate system). Clear them so the user re-draws.
        old_crop = (self.video_settings.get(path) or {}).get("crop")
        if old_crop != s["crop"]:
            for k in ("arena", "center_zone", "center", "exclusion_mask"):
                s.pop(k, None)
        self.video_settings[path] = s
        # Push into the embedded panel if this video is loaded.
        if self._embedded_loaded_path == path:
            try:
                self.embedded_tab.spin_trim_start.setValue(s["trim_start"])
                self.embedded_tab.spin_trim_duration.setValue(s["trim_duration"])
            except Exception:
                pass
            # Reload so the cropped frame replaces the full frame.
            self._load_into_embedded(path)
        dur_label = ("full" if s["trim_duration"] == 0
                     else f"{s['trim_duration']:.1f}s")
        crop_label = ("none" if not s.get("crop") else
                      f"{s['crop']['w']}×{s['crop']['h']}")
        self.lbl_status.setText(
            f"Trim/Crop set on '{os.path.basename(path)}': "
            f"skip {s['trim_start']:.1f}s, duration {dur_label}, crop {crop_label}"
        )

    # ── Per-video config ──────────────────────────────────────────────────

    def _on_edit(self, path):
        """Select a video. Highlights row immediately, then loads into preview.
        Border updates do NOT depend on load success — visual feedback first."""
        if self._tracker_thread is not None:
            self.lbl_status.setText(
                "Tracking in progress — wait for it to finish before switching."
            )
            return
        # Highlight the clicked row IMMEDIATELY. This is independent of the
        # load pipeline so the user always sees the click landed.
        self._sync_selection(path)
        if self._loading:
            self.lbl_status.setText("Still loading previous video — please wait.")
            return
        if self._embedded_loaded_path == path:
            # Same video already loaded. Auto-capture current panel state into
            # this video's slot so the user's edits are preserved.
            self._capture_embedded_settings()
            return
        self._loading = True
        try:
            # Auto-save current panel state to the PREVIOUS video before swap.
            self._capture_embedded_settings()
            ok = self._load_into_embedded(path)
            if not ok:
                # Load failed. Status bar already shows the specific reason
                # (set by _load_into_embedded). Border has already moved
                # because _sync_selection ran above.
                return
        finally:
            self._loading = False

    def _copy_from_neighbor(self, direction):
        """Ctrl+↑/↓ — clone the prev/next row's settings onto the current
        video. Detection knobs only; arena/calibration/metadata stay scoped
        to this video so user doesn't accidentally inherit a wrong arena."""
        if self._tracker_thread is not None or self._loading:
            return
        cur = self._embedded_loaded_path
        if not cur or cur not in self.videos:
            return
        idx = self.videos.index(cur)
        nbr_idx = idx + direction
        if nbr_idx < 0 or nbr_idx >= len(self.videos):
            return
        nbr_path = self.videos[nbr_idx]
        nbr_settings = self.video_settings.get(nbr_path)
        if not nbr_settings:
            self.lbl_status.setText(
                f"Neighbor '{os.path.basename(nbr_path)}' has no settings yet."
            )
            return
        snap = dict(nbr_settings)
        # Strip per-video bits — only copy detection knobs.
        for k in ("arena", "center_zone", "center", "calib_p1", "calib_p2", "calib_cm", "metadata"):
            snap.pop(k, None)
        try:
            self.embedded_tab.apply_settings(snap)
        except Exception:
            return
        # Capture the now-merged state back into this video's slot.
        try:
            full = self.embedded_tab.snapshot_settings()
        except Exception:
            return
        self.video_settings[cur] = full
        self._mark_ready_if_eligible(cur, full)
        self.lbl_status.setText(
            f"Copied detection settings from '{os.path.basename(nbr_path)}'"
        )

    def _mark_ready_if_eligible(self, path, snap):
        """A video is Ready once it has an arena (model has a sane default)."""
        row = self.row_widgets.get(path)
        if not row:
            return
        if snap.get("arena"):
            self.video_status[path] = STATUS_READY
            row.set_status(STATUS_READY)
        else:
            self.video_status[path] = STATUS_NEEDS
            row.set_status(STATUS_NEEDS)
        aid = (snap.get("metadata") or {}).get("Animal ID", "")
        row.set_animal_id(aid)

    # ── Run pipeline ──────────────────────────────────────────────────────

    def _on_run(self, path):
        self._run_video(path)

    def _on_embedded_zones_changed(self):
        """Autosave: the user just changed arena / calibration / exclusion
        on the embedded zone drawer. Capture into video_settings now."""
        path = self._embedded_loaded_path
        if not path or self._loading:
            return
        if getattr(self, "_read_only", False):
            return
        self._capture_embedded_settings()
        snap = self.video_settings.get(path) or {}
        self._mark_ready_if_eligible(path, snap)

    def _on_embedded_metrics_changed(self):
        """Embedded tab just recomputed metrics. Sync them into the per-video
        cache so swap-away then swap-back shows the post-edit state, not the
        original tracking-pass state."""
        path = self._embedded_loaded_path
        if not path or self._loading:
            return
        data = self._completed_data.get(path)
        if not data:
            return
        et = self.embedded_tab
        try:
            data["metrics"]    = dict(et.metrics or {})
            data["raw_df"]     = et.raw_df
            data["bin_df"]     = et.bin_df
            data["graph_pngs"] = dict(getattr(et, "_graph_png_bytes", {}) or {})
            # Keep manual fixes / interpolation when swapping videos.
            if et._raw_results:
                data["results"] = [dict(r) for r in et._raw_results]
        except Exception:
            pass

    def _clear_embedded_panel(self):
        """Reset the embedded preview to a blank state — used when the
        currently-loaded video is removed and no replacement exists."""
        et = self.embedded_tab
        try:
            et.tracking_results = None
            et._raw_results = None
            et._refresh_correction_buttons()
            et._current_scrub_frame_bgr = None
            et._first_frame_bgr = None
            et.video_path = None
            et._crop_rect = None
            et.apply_settings({})
            zd = et.zone_drawer
            zd._base_pixmap = None
            zd.setText("Load a video to begin")
            zd.set_body_pos_norm(None)
            zd.reset_cell_times()
            zd.update()
            et.lbl_video.setText("No video loaded")
            et.slider_scrub.setEnabled(False)
            et.slider_scrub.setMinimum(0)
            et.slider_scrub.setMaximum(0)
            et.slider_scrub.setValue(0)
            et.btn_step_prev.setEnabled(False)
            et.btn_step_next.setEnabled(False)
            if hasattr(et, "_sync_redesign_reset"):
                et._sync_redesign_reset()
        except Exception:
            import traceback
            traceback.print_exc()
        # Clear row highlight + status text.
        try:
            self._sync_selection(None)
        except Exception:
            pass
        self.lbl_status.setText("")

    def _on_body_for_auto_movement(self, body_xy):
        """Collect body positions during auto-from-movement runs and grow
        the displayed arena (4-sided polygon) live."""
        if body_xy is None:
            return
        x, y = float(body_xy[0]), float(body_xy[1])
        self._auto_movement_pts.append((x, y))
        # Re-fit only every few frames to keep the UI snappy.
        if len(self._auto_movement_pts) % 5 != 0:
            return
        et = self.embedded_tab
        try:
            import numpy as _np
            pts = _np.array(self._auto_movement_pts, dtype=_np.float32)
            if len(pts) < 4:
                # Too few — bracket with a small square so the user sees
                # the box has appeared.
                cx, cy = float(pts[:, 0].mean()), float(pts[:, 1].mean())
                s = 25.0
                quad = _np.array([(cx - s, cy - s), (cx + s, cy - s),
                                   (cx + s, cy + s), (cx - s, cy + s)],
                                  dtype=_np.float32)
            else:
                quad = et._fit_quad_from_points(pts)
                if quad is None:
                    return
            pad = et.auto_arena_padding_pct() / 100.0
            quad = et._expand_quad(quad, pad)
            fw, fh = et.video_w or 1, et.video_h or 1
            arena_norm = [(float(p[0]) / fw, float(p[1]) / fh) for p in quad]
            et.zone_drawer.arena = arena_norm
            et.zone_drawer.update()
        except Exception:
            pass

    def _has_live_ymaze_arms(self, path):
        """For Y-Maze runs where the embedded panel is showing `path` but
        the capture pipeline hasn't persisted arms yet. Reads zones directly
        off the embedded zone drawer."""
        if self._embedded_loaded_path != path:
            return False
        et = self.embedded_tab
        exp = getattr(et, "experiment", None)
        if exp is None or getattr(exp, "key", None) != "y_maze":
            return False
        zd = getattr(et, "zone_drawer", None)
        if zd is None:
            return False
        from experiments.y_maze.zones import ARM_NAMES
        for name in ARM_NAMES:
            z = zd.get_zone(name)
            if not z or len(z.get("geometry") or []) < 3:
                return False
        return True

    def _experiment_key(self):
        exp = getattr(getattr(self, "embedded_tab", None), "experiment", None)
        return getattr(exp, "key", None)

    def _smooth_for_metrics(self, results, s):
        window = int(s.get("smooth", 0) or 0)
        et = getattr(self, "embedded_tab", None)
        if window <= 1 or et is None or not hasattr(et, "_apply_smoothing"):
            return results
        try:
            return et._apply_smoothing(results, window)
        except Exception as e:
            logger.warn(f"Smoothing skipped: {e}", source="tracking")
            return results

    def _has_arena(self, path):
        """True if `path` has an arena polygon saved OR is queued for
        auto-from-movement detection (which builds the arena during the run).
        For Y-Maze, also accepts user-drawn arms as a valid 'arena' since the
        tracker arena will be derived from them on the run path."""
        s = self.video_settings.get(path)
        if not s:
            # Fallback for Y-Maze single-row run: settings may be unsaved if
            # the per-video capture hasn't fired yet. Look at the embedded
            # tab's live zones when we're running the currently-loaded path.
            return self._has_live_ymaze_arms(path)
        if s.get("arena_auto_movement"):
            return True
        # Y-Maze: arms count as valid arena.
        arms_norm = s.get("arms_norm") or {}
        if arms_norm and all(len(v or []) >= 3 for v in arms_norm.values()):
            return True
        # Final fallback — read live zones from the embedded panel.
        if self._has_live_ymaze_arms(path):
            return True
        arena = s.get("arena")
        return bool(arena) and len(arena) >= 3

    def _preflight_video(self, path, s=None):
        """Return (status, reasons) where status ∈ {ok, warn, blocked}.
        Blocked = cannot run; warn = runs but with caveats; ok = green.
        `s` overrides the saved settings (used for the batch-merged ones)."""
        reasons = []
        if s is None:
            s = self.video_settings.get(path) or {}
        # Arena (blocking).
        if not self._has_arena(path):
            reasons.append(("blocked", "no arena drawn"))
        exp = getattr(self.embedded_tab, "experiment", None)
        problem = exp.preflight_zone_problem(s) if exp is not None else None
        if problem:
            reasons.append(("blocked", problem))
        # Scale. The auto-cal check is plugin-specific: OF needs cage W/H,
        # Y-Maze needs arm-length + hub + endpoints. Delegate to the
        # experiment plugin so this stays generic.
        mode = s.get("calib_mode", "auto")
        has_line = bool(s.get("calib_p1") and s.get("calib_p2"))
        if mode == "none":
            reasons.append(("warn", "calibration off — distances in pixels"))
        elif mode == "manual" and not has_line:
            reasons.append(("warn", "manual calibration selected but no line drawn"))
        elif mode == "auto":
            exp = getattr(self.embedded_tab, "experiment", None)
            warn = (exp.preflight_auto_scale_warning(s)
                    if exp is not None else None)
            if warn:
                reasons.append(("warn", warn))
        # Determine overall status.
        if any(level == "blocked" for level, _ in reasons):
            return "blocked", reasons
        if reasons:
            return "warn", reasons
        return "ok", reasons

    def _show_preflight_dialog(self, report, note=None):
        """report: list of (path, status, reasons). Returns True if user
        wants to proceed, False to cancel. With `note`, the dialog is shown
        even when every video is ready."""
        from PyQt5.QtWidgets import QDialog, QDialogButtonBox
        glyphs = {"ok": "✓", "warn": "⚠", "blocked": "✗"}
        colors = {"ok": theme.OK, "warn": theme.WARN, "blocked": theme.ERR}
        any_blocked = any(st == "blocked" for _, st, _ in report)
        any_warn    = any(st == "warn"    for _, st, _ in report)
        if not any_blocked and not any_warn and not note:
            return True
        dlg = QDialog(self)
        dlg.setWindowTitle("Pre-flight check")
        dlg.setMinimumWidth(560)
        v = QVBoxLayout(dlg)
        hdr = QLabel(
            "Cannot run — fix the blocked videos first." if any_blocked
            else "Run anyway? Some videos have warnings." if any_warn
            else f"Ready to run {len(report)} video(s)."
        )
        hdr.setStyleSheet("font-weight:bold; font-size:13px;")
        v.addWidget(hdr)
        if note:
            nl = QLabel(note)
            nl.setWordWrap(True)
            nl.setStyleSheet("font-size:11px;")
            v.addWidget(nl)
        for path, status, reasons in report:
            row = QHBoxLayout()
            glyph = QLabel(glyphs[status])
            glyph.setStyleSheet(f"color:{colors[status]}; font-weight:bold; font-size:14px;")
            glyph.setFixedWidth(20)
            row.addWidget(glyph)
            name = QLabel(os.path.basename(path))
            name.setStyleSheet(f"font-family:'{theme.mono_family()}';")
            row.addWidget(name)
            row.addStretch()
            detail = ", ".join(msg for _, msg in reasons) if reasons else "ready"
            d = QLabel(detail)
            d.setStyleSheet(f"color:{colors[status]}; font-size:11px;")
            row.addWidget(d)
            v.addLayout(row)
        if any_blocked:
            bb = QDialogButtonBox(QDialogButtonBox.Cancel)
            bb.rejected.connect(dlg.reject)
        else:
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.button(QDialogButtonBox.Ok).setText(
                "Run anyway" if any_warn else "Run all")
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        return dlg.exec_() == QDialog.Accepted

    def _run_all(self):
        if not self.videos:
            QMessageBox.warning(self, "Nothing to run", "Add videos first.")
            return
        # One settings source for the whole batch: the video currently shown
        # in the panel. Everything that affects the data comes from it; only
        # per-video geometry (arena, zones, calibration line, mask, crop,
        # animal info) stays with each video.
        src = self._embedded_loaded_path
        if not src or src not in self.videos:
            QMessageBox.information(
                self, "Pick the settings video",
                "Click the video whose settings the whole batch should use, "
                "then press Run all again."
            )
            return
        if not getattr(self, "_read_only", False):
            self._capture_embedded_settings()
        try:
            shared = dict(self.embedded_tab.snapshot_settings())
        except Exception:
            shared = dict(self.video_settings.get(src) or {})
        exp_key = self._experiment_key()
        merged = {}
        for p in self.videos:
            own = self.video_settings.get(p) or {}
            merged[p] = derive_center_zone(merge_batch_settings(shared, own), exp_key)
        # Pre-flight: per-video readiness check on the settings that will run.
        report = [(p, *self._preflight_video(p, merged[p])) for p in self.videos]
        note = None
        if len(self.videos) > 1:
            note = (f"All videos will use the settings of <b>{os.path.basename(src)}</b>. "
                    "Only the arena, zones, calibration line, exclusion mask, crop, "
                    "animal info and per-animal assignments (e.g. paired side, "
                    "object roles, platform quadrant) stay per video.")
        if not self._show_preflight_dialog(report, note=note):
            return
        for p in self.videos:
            self.video_settings[p] = merged[p]
            self._mark_ready_if_eligible(p, merged[p])
        logger.info(
            f"Batch settings source: {os.path.basename(src)} -> {len(self.videos)} video(s)",
            source="tracking",
        )
        configured = list(self.videos)
        self._stop_flag = False
        self._low_detection = []
        # Reset per-batch completion log so the "Batch finished — N video(s)"
        # message + the auto-load-last-completed logic reflect only this
        # batch's runs, not stale entries from prior batches.
        self._completed = []
        self.btn_run_all.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_overall.setVisible(True)
        self.progress_overall.setRange(0, len(configured))
        self.progress_overall.setValue(0)
        # Start batch-total clock so the per-video label can also show it.
        import time as _time
        self._batch_t0 = _time.monotonic()
        try:
            for i, p in enumerate(configured):
                if self._stop_flag:
                    break
                self.progress_overall.setValue(i)
                self._run_video(p, in_batch=True)
        finally:
            batch_elapsed = _time.monotonic() - self._batch_t0
            self._batch_t0 = None
            self.progress_overall.setValue(len(configured))
            self.btn_run_all.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.progress_video.setVisible(False)
            self.lbl_track_time.setText(
                f"Batch finished in {self._fmt_elapsed(batch_elapsed)} "
                f"({len(self._completed)} video(s))"
            )
        if self._stop_flag:
            self.lbl_status.setText("Batch stopped by user.")
        else:
            self.lbl_status.setText("Batch complete.")
        # Surface low-detection-rate warnings, if any.
        low = getattr(self, "_low_detection", [])
        if low:
            lines = "\n  • ".join(
                f"{os.path.basename(p)} — {r:.1f}% detected" for p, r in low
            )
            QMessageBox.warning(
                self, "Low detection rate",
                "These videos finished with detection rate under 90% — review "
                "tracker sensitivity, lighting, or exclusion mask:\n\n"
                f"  • {lines}"
            )
        # Auto-load last completed video into the preview.
        if self._completed:
            last_path = self._completed[-1][0]
            self._load_into_embedded(last_path)

    def _stop(self):
        self._stop_flag = True
        if self._tracker_thread is not None:
            try:
                self._tracker_thread.stop()
            except Exception:
                pass

    def _run_video(self, path, in_batch=False):
        logger.info(
            f"Run requested: {os.path.basename(path)} | batch={in_batch}",
            source="tracking",
        )
        # If user has been editing inline, capture latest embedded state
        if self._embedded_loaded_path == path:
            self._capture_embedded_settings()
        # The only hard requirement is an arena polygon. Single-video runs
        # validate here; batch runs already validated in _run_all.
        if not in_batch and not self._has_arena(path):
            QMessageBox.warning(
                self, "Arena not defined",
                f"'{os.path.basename(path)}' has no arena drawn yet. "
                "Click the row to select it, then draw the arena (Step 3)."
            )
            return
        # No folder needed to run: results are backed up automatically
        # (<app folder>/backup unless one is set in Settings).
        out_folder = None

        s = dict(self.video_settings.get(path, {}))
        row = self.row_widgets.get(path)
        if row:
            row.set_status(STATUS_RUNNING)
        self.lbl_status.setText(f"Tracking: {os.path.basename(path)}")
        self._running_name = os.path.splitext(os.path.basename(path))[0]
        self._running_path = path
        self._set_pill(f"Tracking {self._running_name} · 0%")
        self.progress_video.setVisible(True)
        self.progress_video.setRange(0, 100)
        self.progress_video.setValue(0)
        # Show the running video in the embedded preview so live frames make sense
        if self._embedded_loaded_path != path:
            self._load_into_embedded(path)
        self._scrub_active = False
        # Lock the panel during tracking so settings can't drift mid-run.
        self._read_only = True
        self._apply_read_only_state()

        # Start elapsed-time counter.
        self._start_track_timer()
        try:
            self._do_track_and_export(path, s, out_folder)
            if row:
                row.set_status(STATUS_DONE)
        except Exception as e:
            self.lbl_status.setText(f"FAILED: {os.path.basename(path)} — {e}")
            if row:
                row.set_status(STATUS_ERROR)
        finally:
            self._stop_track_timer()
            self._read_only = False
            self._apply_read_only_state()
            self.progress_video.setValue(100)
            from PyQt5.QtWidgets import QApplication
            QApplication.processEvents()

    def _do_track_and_export(self, path, s, out_folder):
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            raise RuntimeError("Cannot open video")
        full_vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        full_vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        from core.video import probe
        auto_fps = probe(cap)[0]
        cap.release()

        # When crop is set, the frame the tracker / panel sees is the cropped
        # one. All normalized coords (arena, center, calibration line) are
        # relative to the displayed (= cropped) frame.
        crop = s.get("crop")
        if crop:
            vw, vh = int(crop["w"]), int(crop["h"])
        else:
            vw, vh = full_vw, full_vh

        # ── Auto-from-movement: skip arena up front; will be built live
        # from the body's path and committed after tracking completes.
        # OF-ONLY feature — never fires for other experiments even if the
        # flag somehow leaked into the snapshot.
        exp_key = getattr(getattr(self.embedded_tab, "experiment", None),
                          "key", None)
        auto_movement = (bool(s.get("arena_auto_movement"))
                         and exp_key == "open_field")
        if auto_movement:
            arena_norm = None
            center_norm = None
        else:
            arena_norm = s.get("arena")
            center_norm = s.get("center_zone", s.get("center"))  # legacy fallback
            # Y-Maze fallback: if the snapshot didn't persist the hull (e.g.
            # the user changed arms and clicked Run before zones_changed
            # propagated), build the hull from arms_norm on the spot.
            if not arena_norm:
                arms_norm = s.get("arms_norm") or {}
                # Plugin-aware fallback: pick the right ARM_NAMES + hull
                # helper based on the embedded experiment.
                if not arms_norm and self._embedded_loaded_path == path:
                    et = self.embedded_tab
                    plug_key = getattr(getattr(et, "experiment", None),
                                       "key", None)
                    zd = getattr(et, "zone_drawer", None) if et is not None else None
                    if plug_key == "y_maze" and zd is not None:
                        from experiments.y_maze.zones import ARM_NAMES as _AN
                        for name in _AN:
                            z = zd.get_zone(name)
                            arms_norm[name] = (list(z["geometry"])
                                               if (z and z.get("geometry"))
                                               else [])
                        s["arms_norm"] = arms_norm
                    elif plug_key == "epm" and zd is not None:
                        from experiments.epm.zones import ARM_NAMES as _AN
                        for name in _AN:
                            z = zd.get_zone(name)
                            arms_norm[name] = (list(z["geometry"])
                                               if (z and z.get("geometry"))
                                               else [])
                        s["arms_norm"] = arms_norm
                if arms_norm:
                    plug_key = getattr(getattr(self.embedded_tab,
                                                "experiment", None),
                                        "key", None) if hasattr(
                        self, "embedded_tab") else None
                    if plug_key == "epm":
                        from experiments.epm.zones import convex_hull, ARM_NAMES
                    else:
                        from experiments.y_maze.zones import convex_hull, ARM_NAMES
                    pts = []
                    for name in ARM_NAMES:
                        g = arms_norm.get(name) or []
                        if len(g) >= 3:
                            pts.extend(g)
                    if len(pts) >= 3:
                        hull = convex_hull(pts)
                        if hull and len(hull) >= 3:
                            arena_norm = hull
                            s["arena"] = hull
        # If perspective correction is on, the saved "arena" is the post-warp
        # full-frame quad. Use the original polygon to build the homography
        # and let the tracker see the WARPED video — same as the GUI preview.
        # Auto-from-movement mode disables perspective (no arena to warp).
        homography = None
        warp_size = None
        # Plugin-supplied homography first (Y-maze builds from hub + 3
        # endpoints; OF returns None and falls through to the cage logic).
        if not auto_movement:
            exp = getattr(self.embedded_tab, "experiment", None)
            if exp is not None:
                try:
                    res = exp.build_tracking_homography(s, (vw, vh))
                except Exception:
                    res = None
                if res is not None:
                    homography, warp_size = res
        if homography is None and s.get("perspective") and not auto_movement:
            original = s.get("original_arena") or arena_norm
            if original and len(original) >= 4:
                import numpy as _np
                # Target size matches the in-app _warp_target_size.
                warp_size = _warp_size_for(
                    s, getattr(self.embedded_tab, "experiment", None), vw, vh)
                pts_px = [(nx * vw, ny * vh) for nx, ny in original]
                # Sort to TL/TR/BR/BL (screen coords, y-down).
                TL = min(pts_px, key=lambda p: p[0] + p[1])
                BR = max(pts_px, key=lambda p: p[0] + p[1])
                TR = max(pts_px, key=lambda p: p[0] - p[1])
                BL = min(pts_px, key=lambda p: p[0] - p[1])
                src = _np.array([TL, TR, BR, BL], dtype=_np.float32)
                TW, TH = warp_size
                dst = _np.array([(0, 0), (TW, 0), (TW, TH), (0, TH)],
                                 dtype=_np.float32)
                try:
                    homography = cv2.getPerspectiveTransform(src, dst)
                except cv2.error:
                    homography = None
                    warp_size = None
        # After warp the arena fills the whole warped frame. Otherwise use
        # the user's drawn polygon as-is.
        if homography is not None:
            TW, TH = warp_size
            arena_px  = [(0, 0), (TW, 0), (TW, TH), (0, TH)]
            # Center polygon was drawn relative to original frame. Project it
            # through the homography so it lines up with the warped image.
            if center_norm:
                pts = _np.array(
                    [[(nx * vw, ny * vh) for nx, ny in center_norm]],
                    dtype=_np.float32,
                )
                warped = cv2.perspectiveTransform(pts, homography)[0]
                center_px = [(int(p[0]), int(p[1])) for p in warped]
            else:
                center_px = None
        else:
            arena_px  = [(int(nx * vw), int(ny * vh)) for nx, ny in arena_norm] if arena_norm else None
            center_px = [(int(nx * vw), int(ny * vh)) for nx, ny in center_norm] if center_norm else None
        px_per_cm = _px_per_cm_for(
            s, getattr(self.embedded_tab, "experiment", None),
            warp_size if homography is not None else (vw, vh))

        from gui.open_field_tab import DEFAULT_COLORS as DC, _hex_to_bgr
        colors = s.get("colors", DC)
        def bgr(name):
            return _hex_to_bgr(colors.get(name, DC.get(name, "#FFFFFF")))

        # Snapshot stores proc_scale / model / body_style as direct values
        # now (float / string), but old snapshots may still carry list
        # indices. Migrate both paths so a config rename can't break a run.
        from gui.experiment_tab import (
            _migrate_combo_value as _mig,
            _LEGACY_PROC_SCALES as _LPS,
            _LEGACY_MODEL_ORDER as _LMO,
            _LEGACY_BODY_STYLES as _LBS,
        )
        proc_scale = _mig(s.get("proc_scale", 1.0), _LPS, 1.0)
        model_key = _mig(s.get("model", "median"), _LMO, "median")
        body_style_key = _mig(s.get("body_style", "dot"), _LBS, "dot")
        captured = []
        # Crop tuple for the tracker (everything else is in cropped coords).
        crop = s.get("crop")
        crop_tuple = None
        if crop:
            crop_tuple = (int(crop["x"]), int(crop["y"]),
                          int(crop["w"]), int(crop["h"]))
        # Pass the user's painted exclusion mask as-is — it's already in the
        # cropped coord system (because the panel re-draws after a crop change).
        excl_mask = s.get("exclusion_mask")
        logger.info(
            f"Tracker start: arena_corners={len(arena_px) if arena_px else 0} | "
            f"center_corners={len(center_px) if center_px else 0} | "
            f"video_res={vw}x{vh} | px_per_cm={px_per_cm} | "
            f"model={model_key} | threshold={s.get('threshold', 25)} | "
            f"proc_scale={proc_scale} | crop={crop_tuple} | "
            f"trim_start={s.get('trim_start', 0.0)}s | trim_dur={s.get('trim_duration', 0.0)}s | "
            f"fps_override={s.get('fps_override', 0.0)} | frame_skip={int(s.get('frame_skip', 1) or 1)} | "
            f"zone_mode={s.get('zone_mode')} | center_pct={s.get('center_pct')}",
            source="tracking",
        )
        thread = TrackerThread(
            video_path=path,
            arena=arena_px,
            threshold=s.get("threshold", 25),
            low_contrast=bool(s.get("low_contrast", False)),
            brightness=s.get("brightness", 0),
            contrast=s.get("contrast", 100) / 100.0,
            blur=s.get("blur", 0),
            gamma=s.get("gamma", 100) / 100.0,
            sharpen=s.get("sharpen", 0),
            clahe_clip=s.get("clahe", 0),
            model=model_key,
            exclusion_mask=excl_mask,
            crop_rect=crop_tuple,
            body_style=body_style_key,
            max_blob_pct=s.get("max_blob", 0),
            proc_scale=proc_scale,
            colors={
                "body": bgr("body"),
                "nose": bgr("nose"),
                "tail": bgr("tail"),
            },
            homography=homography,
            warp_size=warp_size,
            model_params=dict((s.get("model_params") or {}).get(
                model_key, {}
            )),
            post_params=dict(s.get("post_params") or {}),
            fps_override=s.get("fps_override", 0.0),
            trim_start_s=s.get("trim_start", 0.0),
            trim_duration_s=s.get("trim_duration", 0.0),
            frame_skip=int(s.get("frame_skip", 1) or 1),
            smooth_window=int(s.get("smooth_window", 3) or 3),
            enable_nose=bool(s.get("enable_nose", False)),
        )
        thread.finished_tracking.connect(lambda r: captured.append(r))
        thread.progress.connect(self._on_progress)
        thread.preview.connect(self._on_preview)
        # Forward per-frame body coords to the embedded tab's cell-highlight.
        et = self.embedded_tab
        et._live_cell_times = {}
        et._live_cell_entries = {}
        et._live_prev_cid = None
        et._live_pending_cid = None
        et._live_pending_frames = 0
        et._live_confirmed_cid = None
        thread.body_pos.connect(et._on_tracking_body_pos)
        # NOR (and any future nose-driven experiment) opts in via a
        # _on_tracking_nose_pos handler. Hasattr-guarded so OF/YM ignore.
        if hasattr(et, "_on_tracking_nose_pos"):
            thread.nose_pos.connect(et._on_tracking_nose_pos)
        # Auto-from-movement: also collect positions and grow the live arena.
        auto_pts = []
        if auto_movement:
            self._auto_movement_pts = auto_pts
            thread.body_pos.connect(self._on_body_for_auto_movement)
        self._tracker_thread = thread
        # Notify the embedded tab so it can drop live cell overlays for speed.
        et.begin_tracking()
        try:
            thread.run()
        finally:
            et.end_tracking()
            # Disconnect every signal we connected above. Lambdas hold refs
            # to self/et/auto_pts; without disconnect they accumulate across
            # videos in long batches even though `thread` itself is dropped.
            for sig in (thread.finished_tracking, thread.progress,
                        thread.preview, thread.body_pos, thread.nose_pos):
                try:
                    sig.disconnect()
                except Exception:
                    pass
            thread.deleteLater()
        self._tracker_thread = None

        results = captured[0] if captured else []
        logger.info(
            f"Tracker finished | result_frames={len(results)} | "
            f"detected={sum(1 for r in results if r.get('x') is not None)}",
            source="tracking",
        )
        if not results:
            logger.error("No tracking results returned", source="tracking")
            raise RuntimeError("No tracking results")

        # Auto-from-movement: commit the final arena from collected points.
        if auto_movement:
            arena_norm = self.embedded_tab.commit_auto_movement_arena(
                auto_pts, vw, vh
            )
            if arena_norm:
                arena_px = [(int(nx * vw), int(ny * vh)) for nx, ny in arena_norm]
                # Persist into the per-video settings so re-runs / saves keep it.
                s["arena"] = arena_norm
                s["arena_auto_movement"] = False  # one-shot — clear flag.
                self.video_settings[path] = dict(s)
                # If center zone polygon was auto-computed by commit, save it too.
                if self.embedded_tab.zone_drawer.center_zone:
                    s["center_zone"] = list(self.embedded_tab.zone_drawer.center_zone)
                    self.video_settings[path]["center_zone"] = s["center_zone"]

        fps = s.get("fps_override", 0.0) or auto_fps
        # Route through the experiment plugin so Y-Maze gets Y-Maze
        # metrics (alternation, per-arm entries, etc.) instead of having
        # OF's compute_metrics shoehorned onto its raw data.
        plugin_settings = dict(s)
        plugin_settings["arena"] = arena_px
        plugin_settings["center_zone"] = center_px
        plugin_settings["video_w"] = vw
        plugin_settings["video_h"] = vh
        plugin_settings["movement_threshold"] = float(s.get("movement_thr", 0.0))
        plugin_settings["bin_size_s"] = float(s.get("bin_size", 0.0))
        plugin_settings["cell_min_dwell_s"] = float(
            s.get("cell_min_dwell_s", s.get("cell_min_dwell", 0.2))
        )
        plugin_settings["trim_start_s"] = float(s.get("trim_start", 0.0))
        # Apply the track-smoothing setting ("Smoothing, frames") so batch /
        # Multi-Run numbers match what the panel shows for this video.
        metric_results = self._smooth_for_metrics(results, s)
        exp = getattr(self.embedded_tab, "experiment", None)
        if exp is not None:
            metrics, raw_df, bin_df = exp.compute_metrics(
                metric_results, plugin_settings, fps, px_per_cm,
            )
        else:
            metrics, raw_df, bin_df = compute_metrics(
                results=metric_results, arena=arena_px, center_zone=center_px,
                px_per_cm=px_per_cm, fps=fps,
                movement_threshold=plugin_settings["movement_threshold"],
                bin_size_s=plugin_settings["bin_size_s"],
                zone_mode=s.get("zone_mode", "center_zone"),
                cell_min_dwell_s=plugin_settings["cell_min_dwell_s"],
                trim_start_s=plugin_settings["trim_start_s"],
            )

        meta = dict(s.get("metadata") or {})
        if not meta.get("Animal ID"):
            meta["Animal ID"] = os.path.splitext(os.path.basename(path))[0]
        name = os.path.splitext(os.path.basename(path))[0]

        # Quality flag: detection rate below 90% means the tracker missed a
        # lot of frames — accumulate so the batch summary can surface them.
        # EPM / Y-Maze / NOR / NOL name it detection_rate_pct.
        det_rate = float(metrics.get("Detection Rate (%)",
                                     metrics.get("detection_rate_pct", 100)) or 0)
        if det_rate < 90.0:
            if not hasattr(self, "_low_detection"):
                self._low_detection = []
            self._low_detection.append((path, det_rate))

        # Stash results FIRST so _load_into_embedded can populate the Output
        # tab graphs using the correct arena / settings for THIS video.
        self._completed.append((path, meta.get("Animal ID", ""), dict(metrics), dict(meta)))
        self._completed_data[path] = {
            "metrics": dict(metrics),
            "raw_df":  raw_df,
            "bin_df":  bin_df,
            "results": list(results),
            "arena_px": arena_px,
            "video_size": (vw, vh),
            "animal_id": meta.get("Animal ID", ""),
        }
        # Load into the embedded tab — this calls _recompute_metrics_and_views
        # which fills et._graph_png_bytes with graphs that match what the user
        # sees in the Output tab.
        self._load_into_embedded(path)
        graph_images = dict(getattr(self.embedded_tab, "_graph_png_bytes", {}) or {})
        self._completed_data[path]["graph_pngs"] = graph_images
        self._completed_data[path]["graph_sig"] = self._graph_sig()
        self._completed_data[path]["settings_sig"] = self._settings_sig(path)
        # Files use the export preset (the Output tab keeps the current look).
        if self._export_preset_name() is not None:
            graph_images = self._render_export_pngs() or graph_images

        # Autosave goes to the BACKUP folder (separate from the exports the
        # user starts, which ask for a folder). xlsx only — no CSVs. Default:
        # <app folder>/backup, or the folder set in Settings.
        from core.app_paths import backup_dir
        backup_folder = backup_dir(self.config)
        if backup_folder and os.path.isdir(backup_folder):
            exp = getattr(self.embedded_tab, "experiment", None)
            fkey = getattr(exp, "file_key", None) or exp_key or "open_field"
            backup_path = os.path.join(backup_folder, f"{name}_{fkey}.xlsx")
            vc = exp.filter_video_config(s) if exp is not None else s
            export_results(
                metrics=metrics, raw_df=raw_df, output_path=backup_path,
                video_name=name, arena=arena_px, video_size=(vw, vh),
                graph_images=graph_images, bin_df=bin_df, metadata=meta,
                write_csv=False, video_config=vc,
                test_name=getattr(exp, "report_title", None) or f"{getattr(exp, 'name', 'Open Field')} Test",
            )
            logger.info(
                f"Backup saved: {os.path.basename(backup_path)} | "
                f"metrics_keys={len(metrics)} | raw_rows={len(raw_df) if raw_df is not None else 0}",
                source="backup",
            )

        # Vector exports — write SVG/PDF for every output graph beside the
        # per-video Excel. Target folder = main output folder (publication
        # bundle goes with the main artifacts). Skips silently when neither
        # checkbox is on, or when the output folder isn't set.
        else:
            logger.info(
                "Backup skipped — no backup folder set (Settings → Set Backup Folder…)",
                source="backup",
            )
        self._write_vector_graphs(name, backup_folder)

    # ── Multi-Run helper ────────────────────────────────────────────────
    def _track_for_multirun(self, path, s, progress_cb=None):
        """Run the tracking pipeline once for a Multi-Run variant.

        Pure compute: no _completed_data update, no embedded reload,
        no backup save. Returns dict with metrics / raw_df / bin_df / video size
        / fps, or None on failure. `progress_cb(int 0..100)` reports tracker
        progress for THIS run.
        """
        import math
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            raise RuntimeError("Cannot open video")
        full_vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        full_vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        from core.video import probe
        auto_fps = probe(cap)[0]
        cap.release()

        crop = s.get("crop")
        if crop:
            vw, vh = int(crop["w"]), int(crop["h"])
        else:
            vw, vh = full_vw, full_vh

        # Multi-Run requires an explicit arena (no auto-from-movement here).
        s = derive_center_zone(dict(s), self._experiment_key())
        arena_norm = s.get("arena")
        center_norm = s.get("center_zone", s.get("center"))  # legacy fallback
        exp = getattr(self.embedded_tab, "experiment", None)
        # EPM / Y-Maze have no arena rectangle — their arms are the zones.
        if not arena_norm and getattr(exp, "fam", "open_field") in ("open_field", "nor", "box"):
            raise RuntimeError("No arena defined for this video")

        # Homography for perspective correction (mirrors _do_track_and_export):
        # plugin first (EPM / Y-Maze from hub + arm tips), then the arena.
        homography = None
        warp_size = None
        if exp is not None:
            try:
                res = exp.build_tracking_homography(s, (vw, vh))
            except Exception:
                res = None
            if res is not None:
                homography, warp_size = res
        if homography is None and s.get("perspective"):
            import numpy as _np
            original = s.get("original_arena") or arena_norm
            if original and len(original) >= 4:
                warp_size = _warp_size_for(s, exp, vw, vh)
                pts_px = [(nx * vw, ny * vh) for nx, ny in original]
                TL = min(pts_px, key=lambda p: p[0] + p[1])
                BR = max(pts_px, key=lambda p: p[0] + p[1])
                TR = max(pts_px, key=lambda p: p[0] - p[1])
                BL = min(pts_px, key=lambda p: p[0] - p[1])
                src = _np.array([TL, TR, BR, BL], dtype=_np.float32)
                TW, TH = warp_size
                dst = _np.array([(0, 0), (TW, 0), (TW, TH), (0, TH)],
                                 dtype=_np.float32)
                try:
                    homography = cv2.getPerspectiveTransform(src, dst)
                except cv2.error:
                    homography = None
                    warp_size = None

        if homography is not None:
            TW, TH = warp_size
            arena_px = [(0, 0), (TW, 0), (TW, TH), (0, TH)] if arena_norm else None
            if center_norm:
                import numpy as _np
                pts = _np.array(
                    [[(nx * vw, ny * vh) for nx, ny in center_norm]],
                    dtype=_np.float32,
                )
                warped = cv2.perspectiveTransform(pts, homography)[0]
                center_px = [(int(p[0]), int(p[1])) for p in warped]
            else:
                center_px = None
        else:
            arena_px = ([(int(nx * vw), int(ny * vh)) for nx, ny in arena_norm]
                        if arena_norm else None)
            center_px = ([(int(nx * vw), int(ny * vh)) for nx, ny in center_norm]
                         if center_norm else None)

        px_per_cm = _px_per_cm_for(
            s, exp, warp_size if homography is not None else (vw, vh))

        from gui.open_field_tab import DEFAULT_COLORS as DC, _hex_to_bgr
        colors = s.get("colors", DC)
        def _bgr(name):
            return _hex_to_bgr(colors.get(name, DC.get(name, "#FFFFFF")))

        # Snapshot stores proc_scale / model / body_style as direct values
        # now; legacy int indices still accepted via _migrate_combo_value.
        from gui.experiment_tab import (
            _migrate_combo_value as _mig,
            _LEGACY_PROC_SCALES as _LPS,
            _LEGACY_MODEL_ORDER as _LMO,
            _LEGACY_BODY_STYLES as _LBS,
        )
        proc_scale = _mig(s.get("proc_scale", 1.0), _LPS, 1.0)
        model_key = _mig(s.get("model", "median"), _LMO, "median")
        body_style_key = _mig(s.get("body_style", "dot"), _LBS, "dot")
        crop_tuple = None
        if crop:
            crop_tuple = (int(crop["x"]), int(crop["y"]),
                          int(crop["w"]), int(crop["h"]))
        excl_mask = s.get("exclusion_mask")

        logger.info(
            f"Multi-Run tracker: model={model_key} "
            f"threshold={s.get('threshold', 25)} "
            f"brightness={s.get('brightness', 0)} "
            f"contrast={s.get('contrast', 100)} "
            f"blur={s.get('blur', 0)} gamma={s.get('gamma', 100)} "
            f"sharpen={s.get('sharpen', 0)} clahe={s.get('clahe', 0)} "
            f"proc_scale={proc_scale} frame_skip={int(s.get('frame_skip', 1) or 1)} "
            f"fps_override={s.get('fps_override', 0.0)}",
            source="multirun",
        )

        captured = []
        thread = TrackerThread(
            video_path=path,
            arena=arena_px,
            threshold=s.get("threshold", 25),
            low_contrast=bool(s.get("low_contrast", False)),
            brightness=s.get("brightness", 0),
            contrast=s.get("contrast", 100) / 100.0,
            blur=s.get("blur", 0),
            gamma=s.get("gamma", 100) / 100.0,
            sharpen=s.get("sharpen", 0),
            clahe_clip=s.get("clahe", 0),
            model=model_key,
            exclusion_mask=excl_mask,
            crop_rect=crop_tuple,
            body_style=body_style_key,
            max_blob_pct=s.get("max_blob", 0),
            proc_scale=proc_scale,
            colors={
                "body": _bgr("body"),
                "nose": _bgr("nose"),
                "tail": _bgr("tail"),
            },
            homography=homography,
            warp_size=warp_size,
            model_params=dict((s.get("model_params") or {}).get(
                model_key, {}
            )),
            post_params=dict(s.get("post_params") or {}),
            fps_override=s.get("fps_override", 0.0),
            trim_start_s=s.get("trim_start", 0.0),
            trim_duration_s=s.get("trim_duration", 0.0),
            frame_skip=int(s.get("frame_skip", 1) or 1),
            smooth_window=int(s.get("smooth_window", 3) or 3),
            enable_nose=bool(s.get("enable_nose", False)),
        )
        thread.finished_tracking.connect(lambda r: captured.append(r))
        if progress_cb is not None:
            thread.progress.connect(lambda p: progress_cb(int(p)))
        thread.run()
        results = captured[0] if captured else []
        if not results:
            raise RuntimeError("No tracking results")

        fps = s.get("fps_override", 0.0) or auto_fps
        # Route through plugin so Y-Maze metrics are produced for Y-Maze runs.
        plugin_settings = dict(s)
        plugin_settings["arena"] = arena_px
        plugin_settings["center_zone"] = center_px
        plugin_settings["video_w"] = vw
        plugin_settings["video_h"] = vh
        plugin_settings["movement_threshold"] = float(s.get("movement_thr", 0.0))
        plugin_settings["bin_size_s"] = float(s.get("bin_size", 0.0))
        plugin_settings["cell_min_dwell_s"] = float(
            s.get("cell_min_dwell_s", s.get("cell_min_dwell", 0.2))
        )
        plugin_settings["trim_start_s"] = float(s.get("trim_start", 0.0))
        # Apply the track-smoothing setting ("Smoothing, frames") so batch /
        # Multi-Run numbers match what the panel shows for this video.
        metric_results = self._smooth_for_metrics(results, s)
        exp = getattr(self.embedded_tab, "experiment", None)
        if exp is not None:
            metrics, raw_df, bin_df = exp.compute_metrics(
                metric_results, plugin_settings, fps, px_per_cm,
            )
        else:
            metrics, raw_df, bin_df = compute_metrics(
                results=metric_results, arena=arena_px, center_zone=center_px,
                px_per_cm=px_per_cm, fps=fps,
                movement_threshold=plugin_settings["movement_threshold"],
                bin_size_s=plugin_settings["bin_size_s"],
                zone_mode=s.get("zone_mode", "center_zone"),
                cell_min_dwell_s=plugin_settings["cell_min_dwell_s"],
                trim_start_s=plugin_settings["trim_start_s"],
            )

        # Build the same 8 graphs the Output tab shows. Temporarily inject
        # variant's metrics/raw_df/bin_df into the embedded tab, call its
        # graph builder, snapshot _graph_png_bytes, then restore.
        graph_pngs = {}
        et = getattr(self, "embedded_tab", None)
        if et is not None and hasattr(et, "_populate_graph_tab"):
            saved = {
                "metrics": getattr(et, "metrics", None),
                "raw_df":  getattr(et, "raw_df", None),
                "bin_df":  getattr(et, "bin_df", None),
                "graphs":  dict(getattr(et, "_graph_png_bytes", {}) or {}),
            }
            try:
                et.metrics = dict(metrics)
                et.raw_df  = raw_df
                et.bin_df  = bin_df
                et._populate_graph_tab()
            except Exception as e:
                logger.warn(f"Multi-Run graph build failed: {e}",
                            source="multirun")
            finally:
                # Capture whatever was rasterized BEFORE restoring baseline.
                # _populate_graph_tab may raise after the bytes are written
                # (e.g. during combo-box wiring); we still want those graphs.
                graph_pngs = dict(getattr(et, "_graph_png_bytes", {}) or {})
                et.metrics = saved["metrics"]
                et.raw_df  = saved["raw_df"]
                et.bin_df  = saved["bin_df"]
                et._graph_png_bytes = saved["graphs"]

        return {
            "metrics":    metrics,
            "raw_df":     raw_df,
            "bin_df":     bin_df,
            "arena_px":   arena_px,
            "video_size": (vw, vh),
            "fps":        fps,
            "graph_pngs": graph_pngs,
        }

    def _on_progress(self, p):
        # The tracker runs synchronously on the GUI thread and emits progress
        # every frame. setValue is cheap, but processEvents() pumps the whole
        # event loop (repaints etc.) — doing that per frame dominates run time.
        # Throttle the pump to ~20 Hz; the bar value still updates every frame.
        self.progress_video.setValue(int(p))
        _row = self.row_widgets.get(self._running_path)
        if _row is not None:
            _row.set_progress(int(p))
        self._set_pill(f"Tracking {getattr(self, '_running_name', '')} · {int(p)}%")
        import time
        now = time.time()
        if now - getattr(self, "_last_progress_pump", 0.0) >= 0.05:
            self._last_progress_pump = now
            from PyQt5.QtWidgets import QApplication
            QApplication.processEvents()

    def _on_preview(self, frame):
        if frame is None:
            return
        try:
            zd = getattr(self.embedded_tab, "zone_drawer", None)
            if zd is not None:
                zd.set_frame(frame)
        except Exception:
            pass
        from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()

    # ── Video selector + Excel preview ────────────────────────────────────

    def _refresh_video_combo(self):
        # Combo removed — left for callers; nothing to update.
        pass


    def _load_into_embedded(self, path, read_only=False):
        if not path:
            return False
        # While the next video's settings go in, the panel's change signals
        # must not autosave them under the video being left.
        was_loading = self._loading
        self._loading = True
        try:
            return self._load_into_embedded_impl(path, read_only)
        finally:
            self._loading = was_loading

    def _load_into_embedded_impl(self, path, read_only=False):
        # Snapshot the previously-loaded video's panel state before switching
        # (no-op in read-only mode).
        if self._embedded_loaded_path and self._embedded_loaded_path != path:
            self._capture_embedded_settings()
            # Keep the edits made on the video we leave (corrections, new
            # thresholds / zones, graph style) for its exports.
            self._sync_completed_from_embedded()
        # Reset stale state so a previous video's results / scrub frame can't
        # bleed onto the new one's preview.
        et = self.embedded_tab
        et.tracking_results = None
        et._raw_results = None
        et._current_scrub_frame_bgr = None
        et._refresh_correction_buttons()
        # Push crop into the embedded tab BEFORE loading so the displayed
        # frame and all subsequent scrubs are cropped.
        crop_dict = (self.video_settings.get(path) or {}).get("crop")
        if crop_dict:
            et._crop_rect = (int(crop_dict["x"]), int(crop_dict["y"]),
                              int(crop_dict["w"]), int(crop_dict["h"]))
        else:
            et._crop_rect = None
        try:
            et._load_video_path(path)
        except Exception as e:
            self.lbl_status.setText(f"_load_video_path failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        # _load_video_path returns silently on bad files (no exception). Detect
        # failure via et.video_path, which is only set after a successful read.
        if getattr(et, "video_path", None) != path:
            self.lbl_status.setText(
                f"_load_video_path silent fail (video_path={getattr(et, 'video_path', None)})"
            )
            return False
        # Apply this video's saved settings, or hard defaults for a brand-new
        # video (apply_settings({}) sets every widget to its .get default).
        settings = self.video_settings.get(path) or {}
        try:
            et.apply_settings(settings)
        except Exception as e:
            # Roll back to previous video's settings so the panel doesn't
            # leave half-applied state visible. Surface the error to the user.
            self.lbl_status.setText(f"apply_settings failed: {e}")
            import traceback
            traceback.print_exc()
            prev = self._embedded_loaded_path
            if prev:
                try:
                    et.apply_settings(self.video_settings.get(prev) or {})
                except Exception:
                    pass
            return False
        # Default new videos to "Auto — from movement": skip arena
        # setup now and let the next tracking run build the polygon
        # from the mouse's positions. Only triggers when there's no
        # arena saved AND no arena currently on the drawer (so an
        # in-session manual draw isn't overwritten).
        zd = getattr(et, "zone_drawer", None)
        no_saved_arena = not (self.video_settings.get(path) or {}).get("arena")
        exp_key = getattr(getattr(et, "experiment", None), "key", None)
        # OF / NOR default to a centered premade square. Y-Maze / EPM use
        # their own geometry. Auto-from-movement is still available behind
        # the Extra features toggle and overrides the square.
        if zd is not None and zd.arena is None and no_saved_arena:
            _fam = getattr(getattr(et, "experiment", None), "fam", exp_key)
            if (_fam in ("open_field", "nor", "box")
                    and not self.config.get("enable_auto_movement_arena", False)):
                try:
                    et._apply_premade_square_arena()
                    et._arena_define_mode = "square"
                    if hasattr(et, "btn_define_arena"):
                        try:
                            et.btn_define_arena.setText(
                                "Premade square arena ▾"
                            )
                        except Exception:
                            pass
                    if hasattr(et, "_refresh_arena_mode_chip"):
                        try:
                            et._refresh_arena_mode_chip()
                        except Exception:
                            pass
                except Exception:
                    pass
            elif (exp_key != "y_maze"
                    and self.config.get("enable_auto_movement_arena", False)):
                et._arena_auto_movement = True
                et._arena_define_mode = "movement"
                # Persist into video_settings so _has_arena / preflight see
                # the queued auto-mode without waiting for a later capture.
                vs = self.video_settings.setdefault(path, {})
                vs["arena_auto_movement"] = True
                vs["arena_define_mode"] = "movement"
                if hasattr(et, "btn_define_arena"):
                    try:
                        et.btn_define_arena.setText(
                            "Auto — from movement (next run) ▾"
                        )
                    except Exception:
                        pass
                if hasattr(et, "_refresh_arena_mode_chip"):
                    try:
                        et._refresh_arena_mode_chip()
                    except Exception:
                        pass
                if hasattr(et, "lbl_zones"):
                    et.lbl_zones.setText(
                        "Auto-from-movement queued — run tracking; arena "
                        "will form from the mouse's path."
                    )

        self._embedded_loaded_path = path
        self._read_only = read_only
        self._apply_read_only_state()
        self._sync_selection(path)
        self._refresh_export_buttons()
        # Now that crop + trim values are applied to the embedded panel,
        # clamp the scrub slider's range to the trim window.
        try:
            et.apply_trim_to_scrub()
        except Exception:
            pass
        # If this video has been tracked, push results so the Results tab
        # works (scrub + overlays). Otherwise show the clean first frame.
        data = self._completed_data.get(path)
        if data and data.get("results"):
            # Pass the whole cache dict — _apply_results_to_embedded will
            # reuse cached metrics + graphs and skip the recompute — unless
            # this video's settings changed since (e.g. "Apply to…"): then
            # recompute so numbers match the settings.
            fresh = data.get("settings_sig") == self._settings_sig(path)
            self._apply_results_to_embedded(data["results"], cached=data if fresh else None)
            if not fresh:
                self._sync_completed_from_embedded()
        else:
            if et._first_frame_bgr is not None:
                et.zone_drawer.set_frame(et._first_frame_bgr)
        # Force immediate repaint so the new frame shows before a slider is touched.
        et.zone_drawer.repaint()
        return True

    def _open_apply_to_dialog(self):
        """Open the Apply-To dialog. Source = currently loaded video."""
        src = self._embedded_loaded_path
        if not src:
            QMessageBox.information(
                self, "No source video",
                "Click a video in the list first — its current panel "
                "settings are what gets copied."
            )
            return
        if len(self.videos) <= 1:
            QMessageBox.information(
                self, "Nothing to copy to",
                "Add more videos first."
            )
            return
        # Snapshot the panel as the source. Capture once, immediately, so the
        # user can't accidentally edit while the dialog is open.
        try:
            src_snap = self.embedded_tab.snapshot_settings()
        except Exception as e:
            QMessageBox.warning(self, "Snapshot failed", str(e))
            return
        dlg = ApplyToDialog(self, src, self.videos, self.video_settings)
        if dlg.exec_() != QDialog.Accepted:
            return
        fields = dlg.selected_fields()
        targets = dlg.selected_targets()
        if not fields:
            self.lbl_status.setText("Apply-to: no fields selected.")
            return
        if not targets:
            self.lbl_status.setText("Apply-to: no targets selected.")
            return
        # Confirmation if writing to already-configured videos.
        will_overwrite = [t for t in targets if t in self.video_settings]
        if will_overwrite:
            n = len(will_overwrite)
            ans = QMessageBox.question(
                self, "Overwrite existing settings?",
                f"{n} target video(s) already have saved settings. "
                "The selected fields will be overwritten on those videos. "
                "Continue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if ans != QMessageBox.Yes:
                return
        # Apply.
        for tgt in targets:
            existing = dict(self.video_settings.get(tgt) or {})
            for k in fields:
                if k in src_snap:
                    # Deep-ish copy for nested dicts / arrays so later edits
                    # to the source video's panel don't bleed into targets.
                    v = src_snap[k]
                    if isinstance(v, dict):
                        existing[k] = {kk: (dict(vv) if isinstance(vv, dict) else vv)
                                        for kk, vv in v.items()}
                    elif isinstance(v, list):
                        existing[k] = list(v)
                    elif hasattr(v, "copy"):
                        existing[k] = v.copy()
                    else:
                        existing[k] = v
            self.video_settings[tgt] = existing
            self._mark_ready_if_eligible(tgt, existing)
        # If the currently-loaded video was a target, re-apply so the panel
        # reflects the new state.
        if self._embedded_loaded_path in targets:
            try:
                self.embedded_tab.apply_settings(
                    self.video_settings.get(self._embedded_loaded_path) or {}
                )
            except Exception:
                pass
        self.lbl_status.setText(
            f"Applied {len(fields)} field(s) to {len(targets)} video(s)."
        )

    def _sync_selection(self, path):
        """Highlight matching row + sync combo to `path`. Surfaces any error
        instead of swallowing — silent failures here are why borders get stuck."""
        # Snapshot to a list to avoid concurrent-modification issues.
        for p, row in list(self.row_widgets.items()):
            try:
                row.set_selected(p == path)
            except Exception as e:
                self.lbl_status.setText(f"set_selected failed on {os.path.basename(p)}: {e}")
                import traceback
                traceback.print_exc()
        # Combo removed — only the row highlight needs syncing now.

    def _apply_read_only_state(self):
        """Disable / enable the embedded config panel based on read-only mode."""
        # Toggle the controls scroll area only — preview stays interactive
        # (scrub still works even read-only). We keep a direct reference to
        # the scroll because it was re-parented out of embedded_tab.
        try:
            if self._config_scroll is not None:
                self._config_scroll.setEnabled(not self._read_only)
        except Exception:
            pass

    def _apply_results_to_embedded(self, results, cached=None):
        """Push tracked results into the embedded panel.

        If `cached` is provided (dict with metrics / raw_df / bin_df /
        graph_pngs from a prior tracking pass), reuse it instead of re-
        running compute_metrics + matplotlib. Big speed win when swapping
        between already-tracked videos.
        """
        et = self.embedded_tab
        et._raw_results = [dict(r) for r in results]
        try:
            et.tracking_results = et._apply_smoothing(et._raw_results, et.spin_smooth.value())
        except Exception:
            et.tracking_results = list(et._raw_results)
        try:
            et._on_scrub(et.slider_scrub.value())
        except Exception:
            pass
        et._refresh_correction_buttons()
        # Only use the cached fast path when graphs are actually available —
        # otherwise we'd silently leave the Output / Excel-export panels empty.
        # On the first tracking pass `cached` exists but `graph_pngs` is still
        # unset, so this falls through to the cold path that runs matplotlib.
        if cached and cached.get("graph_pngs"):
            try:
                et.metrics = dict(cached.get("metrics") or {})
                et.raw_df  = cached.get("raw_df")
                et.bin_df  = cached.get("bin_df")
                if et.raw_df is not None and et.metrics:
                    et._populate_excel_tab()
                self._hydrate_cached_graphs(et, cached.get("graph_pngs") or {})
                # timeline / sidebar / heat layer aren't part of the cache
                et._refresh_redesign_data()
                if et.raw_df is not None:
                    # Redraw with the CURRENT preset / style (it may have
                    # changed since this video was tracked); also refreshes
                    # the export images used by Excel.
                    et._populate_graph_tab()
            except Exception:
                import traceback
                traceback.print_exc()
            return
        # Cold path: compute + render graphs.
        try:
            et._recompute_metrics_and_views()
        except Exception:
            import traceback
            traceback.print_exc()

    def _hydrate_cached_graphs(self, et, png_map):
        """Push pre-rendered PNG bytes back into the embedded tab's graph
        widgets. Avoids regenerating matplotlib figures on swap."""
        from PyQt5.QtGui import QPixmap
        et._graph_pixmaps = {}
        et._graph_png_bytes = {}
        for name, png in (png_map or {}).items():
            if not png:
                continue
            pix = QPixmap()
            if pix.loadFromData(png):
                et._graph_pixmaps[name] = pix
                et._graph_png_bytes[name] = png
        et._combo_graph.blockSignals(True)
        et._combo_graph.clear()
        for name in et._graph_pixmaps:
            et._combo_graph.addItem(name)
        et._combo_graph.blockSignals(False)
        if et._graph_pixmaps:
            et._combo_graph.setCurrentIndex(0)
            et._on_graph_select(0)
            et.lbl_graph_hint.setVisible(False)
            et._graph_selector_widget.setVisible(True)
            et._graph_scroll.setVisible(True)

    def _capture_embedded_settings(self):
        if not self._embedded_loaded_path:
            return
        if getattr(self, "_read_only", False):
            return  # don't overwrite saved settings while in read-only view
        try:
            snap = self.embedded_tab.snapshot_settings()
        except Exception:
            return
        self.video_settings[self._embedded_loaded_path] = snap

    # Legacy no-ops — kept so existing callers don't break.


    def _on_scrub(self, idx):
        pass


    # ── Output folder ─────────────────────────────────────────────────────

    def _refresh_output_label(self):
        if not hasattr(self, "lbl_output"):
            return
        f = self.config.get("output_folder")
        self.lbl_output.setText(f if f else "(you choose the folder at each export)")
        if hasattr(self, "lbl_backup_note"):
            from core.app_paths import backup_dir
            bk = backup_dir(self.config)
            mono = theme.mono_family()
            self.lbl_backup_note.setText(
                f"Automatic backup after each run: <span style=\"font-family:'{mono}'; "
                f"color:{theme.TEXT_2}\">{bk}</span> — change in Settings → Set Backup Folder…")

    def _ask_export_folder(self, title="Export to…"):
        """Folder picker shown by every export; opens in the last folder used
        and remembers the choice. Returns the folder or None (cancelled)."""
        from core.app_paths import app_dir
        start = self.config.get("output_folder") or ""
        if not os.path.isdir(start):
            start = app_dir()
        folder = QFileDialog.getExistingDirectory(self, title, start)
        if not folder:
            return None
        if folder != self.config.get("output_folder"):
            self.config["output_folder"] = folder
            self._save_config()
            self._refresh_output_label()
            win = self.window()
            if hasattr(win, "_refresh_status"):
                win._refresh_status()
        return folder

    def _change_output_folder(self):
        start = self.config.get("output_folder") or ""
        if not os.path.isdir(start):
            from core.app_paths import app_dir
            start = app_dir()
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", start)
        if folder:
            self.config["output_folder"] = folder
            self._save_config()
            self._refresh_output_label()

    def _open_output_folder(self):
        f = self.config.get("output_folder")
        if not f or not os.path.isdir(f):
            return
        try:
            os.startfile(f)
        except AttributeError:
            import subprocess, sys
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, f])

    def _save_config(self):
        win = self.window()
        if win is not self and hasattr(win, "_save_config"):
            win._save_config()

    def set_simple_mode(self, simple: bool):
        """Forward Simple/Full toggle to the embedded OpenFieldTab. Also
        persists to the shared config so per-video config dialogs spawn in
        the same mode."""
        self.config["simple_mode"] = bool(simple)
        if hasattr(self, "embedded_tab"):
            try:
                self.embedded_tab.set_simple_mode(bool(simple))
            except Exception:
                pass
        self._save_config()

