"""EPM perspective-correction dialog.

Two modes:
  - quad: drag 4 corners around the whole maze area; warp maps that quad
          to a square output.
  - plus: place TWO rectangles — one over the open arms (long-axis), one
          over the closed arms — and the homography lines both up so the
          output frame has a perfect axis-aligned plus.

Plus mode is the natural fit for EPM: the maze IS a plus, not a single
quad. Aligning the two arm rects against the visible maze walls gives a
correction that handles camera tilt, lens distortion at edges, and
non-rectangular real-world geometry far better than a single quad.
"""
import numpy as np
import cv2
from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import (QImage, QPixmap, QPainter, QPen, QColor, QFont,
                          QBrush)
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QComboBox, QWidget, QMessageBox, QSpinBox, QRadioButton, QButtonGroup,
    QGroupBox, QDoubleSpinBox,
)


def _bgr_to_qimage(bgr):
    if bgr is None:
        return None
    if bgr.ndim == 2:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_GRAY2RGB)
    else:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    rgb = np.ascontiguousarray(rgb)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()


def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


# Default corner positions per mode (all normalized 0–1 frame coords).
_QUAD_DEFAULT = [
    (0.10, 0.10), (0.90, 0.10),
    (0.90, 0.90), (0.10, 0.90),
]
# Open rect = vertical pair (N→S). Corner order: N-Left, N-Right, S-Right, S-Left
_PLUS_OPEN_DEFAULT = [
    (0.42, 0.08), (0.58, 0.08),
    (0.58, 0.92), (0.42, 0.92),
]
# Closed rect = horizontal pair (W→E). Corner order: W-Top, E-Top, E-Bottom, W-Bottom
_PLUS_CLOSED_DEFAULT = [
    (0.08, 0.42), (0.92, 0.42),
    (0.92, 0.58), (0.08, 0.58),
]

_QUAD_LABELS = ["TL", "TR", "BR", "BL"]
_OPEN_LABELS = ["N-L", "N-R", "S-R", "S-L"]
_CLOSED_LABELS = ["W-T", "E-T", "E-B", "W-B"]

OPEN_COLOR = QColor(80, 170, 255)    # blue
CLOSED_COLOR = QColor(255, 130, 60)  # orange


class _CornerEditor(QWidget):
    """Canvas widget. Mode-aware: paints source frame + draggable corners
    + gridlines. Quad mode = one quad. Plus mode = two rectangles."""
    HANDLE_R = 5       # visible handle radius (px) — kept small for precision
    GRAB_R = 16        # mouse-grab radius (px) — generous for easy clicking
    LOUPE_D = 140      # magnifier diameter (px)
    LOUPE_ZOOM = 4     # magnification factor
    _MARGIN_FRAC = 0.15

    def __init__(self, frame_bgr, parent=None):
        super().__init__(parent)
        self._frame_bgr = frame_bgr
        self._qimg = _bgr_to_qimage(frame_bgr)
        self._fw = frame_bgr.shape[1] if frame_bgr is not None else 1
        self._fh = frame_bgr.shape[0] if frame_bgr is not None else 1
        self.mode = "quad"   # "quad" or "plus"
        self.corners = list(_QUAD_DEFAULT)
        self.open_corners = list(_PLUS_OPEN_DEFAULT)
        self.closed_corners = list(_PLUS_CLOSED_DEFAULT)
        self.grid_n = 6
        self.show_grid = True
        self.show_diagonals = False
        self._drag = None         # (group, idx) — group in {"quad","open","closed"}
        self.setMinimumSize(560, 440)
        self.setMouseTracking(True)
        self._on_change_cb = None

    def set_change_callback(self, cb):
        self._on_change_cb = cb

    def _emit(self):
        if self._on_change_cb:
            self._on_change_cb()

    def set_mode(self, mode):
        if mode not in ("quad", "plus"):
            return
        self.mode = mode
        self._drag = None
        self.update()
        self._emit()

    # ── Quad mode controls ────────────────────────────────────────────
    def set_corners(self, corners_norm):
        if corners_norm and len(corners_norm) >= 4:
            self.corners = [
                (float(p[0]), float(p[1])) for p in corners_norm[:4]
            ]
            self.update()
            self._emit()

    def reset_quad_default(self):
        self.corners = list(_QUAD_DEFAULT)
        self.update()
        self._emit()

    def reset_quad_full(self):
        self.corners = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        self.update()
        self._emit()

    # ── Plus mode controls ────────────────────────────────────────────
    def set_plus_corners(self, open_pts, closed_pts):
        if open_pts and len(open_pts) >= 4:
            self.open_corners = [
                (float(p[0]), float(p[1])) for p in open_pts[:4]
            ]
        if closed_pts and len(closed_pts) >= 4:
            self.closed_corners = [
                (float(p[0]), float(p[1])) for p in closed_pts[:4]
            ]
        self.update()
        self._emit()

    def reset_plus_default(self):
        self.open_corners = list(_PLUS_OPEN_DEFAULT)
        self.closed_corners = list(_PLUS_CLOSED_DEFAULT)
        self.update()
        self._emit()

    def swap_plus_axes(self):
        """Rotate roles: what was open becomes closed and vice-versa
        (useful if the camera is rotated 90°)."""
        self.open_corners, self.closed_corners = (
            list(self.closed_corners), list(self.open_corners),
        )
        self.update()
        self._emit()

    # ── Display helpers ───────────────────────────────────────────────
    def set_grid_n(self, n):
        self.grid_n = max(2, int(n))
        self.update()

    def set_show_grid(self, on):
        self.show_grid = bool(on)
        self.update()

    def set_show_diagonals(self, on):
        self.show_diagonals = bool(on)
        self.update()

    def _disp_rect(self):
        ww = self.width()
        wh = self.height()
        if self._qimg is None or self._fw <= 0 or self._fh <= 0:
            return QRect(0, 0, ww, wh)
        m = self._MARGIN_FRAC
        avail_w = max(1, int(ww * (1 - 2 * m)))
        avail_h = max(1, int(wh * (1 - 2 * m)))
        s = min(avail_w / self._fw, avail_h / self._fh)
        dw = int(self._fw * s)
        dh = int(self._fh * s)
        dx = (ww - dw) // 2
        dy = (wh - dh) // 2
        return QRect(dx, dy, dw, dh)

    def _norm_to_widget(self, pn):
        r = self._disp_rect()
        return (r.x() + pn[0] * r.width(),
                r.y() + pn[1] * r.height())

    def _widget_to_norm(self, x, y):
        r = self._disp_rect()
        if r.width() <= 0 or r.height() <= 0:
            return (0.0, 0.0)
        return ((x - r.x()) / r.width(),
                (y - r.y()) / r.height())

    # ── Paint ─────────────────────────────────────────────────────────
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(20, 20, 20))
        r = self._disp_rect()
        if self._qimg is not None:
            p.drawImage(r, self._qimg)
            p.setPen(QPen(QColor(120, 120, 120, 200), 1, Qt.SolidLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)

        if self.mode == "quad":
            self._paint_quad(p)
        else:
            self._paint_plus(p)
        # Magnifier loupe — only visible while a handle is being dragged.
        self._paint_magnifier(p)
        p.end()

    def _paint_quad(self, p):
        pts = [self._norm_to_widget(c) for c in self.corners]
        tl, tr, br, bl = pts

        if self.show_grid and self.grid_n >= 2:
            p.setPen(QPen(QColor(0, 220, 255, 170), 1, Qt.SolidLine))
            n = self.grid_n
            for i in range(1, n):
                t = i / n
                left = _lerp(tl, bl, t); right = _lerp(tr, br, t)
                p.drawLine(int(left[0]), int(left[1]),
                           int(right[0]), int(right[1]))
                top = _lerp(tl, tr, t); bot = _lerp(bl, br, t)
                p.drawLine(int(top[0]), int(top[1]),
                           int(bot[0]), int(bot[1]))
        if self.show_diagonals:
            p.setPen(QPen(QColor(255, 150, 0, 180), 1, Qt.DashLine))
            p.drawLine(int(tl[0]), int(tl[1]), int(br[0]), int(br[1]))
            p.drawLine(int(tr[0]), int(tr[1]), int(bl[0]), int(bl[1]))

        p.setPen(QPen(QColor(255, 200, 0, 240), 2, Qt.SolidLine))
        for i in range(4):
            x1, y1 = pts[i]; x2, y2 = pts[(i + 1) % 4]
            p.drawLine(int(x1), int(y1), int(x2), int(y2))

        self._paint_handles(p, pts, _QUAD_LABELS, QColor(255, 70, 70))

    def _paint_plus(self, p):
        op_pts = [self._norm_to_widget(c) for c in self.open_corners]
        cl_pts = [self._norm_to_widget(c) for c in self.closed_corners]

        # Filled rects (transparent) so visual hits are obvious.
        p.setPen(QPen(OPEN_COLOR, 2, Qt.DashLine))
        p.setBrush(QBrush(QColor(OPEN_COLOR.red(), OPEN_COLOR.green(),
                                  OPEN_COLOR.blue(), 50)))
        self._draw_quad(p, op_pts)
        p.setPen(QPen(CLOSED_COLOR, 2, Qt.DashLine))
        p.setBrush(QBrush(QColor(CLOSED_COLOR.red(), CLOSED_COLOR.green(),
                                  CLOSED_COLOR.blue(), 50)))
        self._draw_quad(p, cl_pts)

        # Center markers — long-axis midline for each rect.
        if self.show_diagonals:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(OPEN_COLOR, 1, Qt.DotLine))
            mid_n = _lerp(op_pts[0], op_pts[1], 0.5)
            mid_s = _lerp(op_pts[3], op_pts[2], 0.5)
            p.drawLine(int(mid_n[0]), int(mid_n[1]),
                       int(mid_s[0]), int(mid_s[1]))
            p.setPen(QPen(CLOSED_COLOR, 1, Qt.DotLine))
            mid_w = _lerp(cl_pts[0], cl_pts[3], 0.5)
            mid_e = _lerp(cl_pts[1], cl_pts[2], 0.5)
            p.drawLine(int(mid_w[0]), int(mid_w[1]),
                       int(mid_e[0]), int(mid_e[1]))

        # Gridlines: bilinear-grid for both rects (so the cyan grid follows
        # both rectangles independently). Less useful than quad-mode grid
        # but still helps eyeball "is my rect aligned with the wall."
        if self.show_grid and self.grid_n >= 2:
            for q in (op_pts, cl_pts):
                p.setPen(QPen(QColor(0, 220, 255, 130), 1, Qt.SolidLine))
                tl, tr, br, bl = q
                n = self.grid_n
                for i in range(1, n):
                    t = i / n
                    p.drawLine(*self._line_int(_lerp(tl, bl, t),
                                                _lerp(tr, br, t)))
                    p.drawLine(*self._line_int(_lerp(tl, tr, t),
                                                _lerp(bl, br, t)))

        self._paint_handles(p, op_pts, _OPEN_LABELS, OPEN_COLOR)
        self._paint_handles(p, cl_pts, _CLOSED_LABELS, CLOSED_COLOR)

    @staticmethod
    def _line_int(a, b):
        return (int(a[0]), int(a[1]), int(b[0]), int(b[1]))

    @staticmethod
    def _draw_quad(p, pts):
        from PyQt5.QtGui import QPolygon
        from PyQt5.QtCore import QPoint
        poly = QPolygon([QPoint(int(x), int(y)) for x, y in pts])
        p.drawPolygon(poly)

    def _paint_handles(self, p, pts, labels, color):
        font = QFont("Arial", 8, QFont.Bold)
        p.setFont(font)
        for (cx, cy), lab in zip(pts, labels):
            p.setPen(QPen(QColor(255, 255, 255), 1))
            p.setBrush(color)
            p.drawEllipse(int(cx) - self.HANDLE_R, int(cy) - self.HANDLE_R,
                          self.HANDLE_R * 2, self.HANDLE_R * 2)
            p.setPen(QColor(255, 255, 255))
            p.drawText(int(cx) + self.HANDLE_R + 3,
                       int(cy) - self.HANDLE_R - 1, lab)

    def _paint_magnifier(self, p):
        """Circular zoomed view of the source frame around the cursor,
        shown while a handle is dragged. Crosshair marks the exact target
        pixel so the user can place the corner precisely."""
        if self._drag is None or self._qimg is None:
            return
        group, idx = self._drag
        if group == "quad":
            c = self.corners[idx]
        elif group == "open":
            c = self.open_corners[idx]
        elif group == "closed":
            c = self.closed_corners[idx]
        else:
            return
        # Handle widget position.
        hx, hy = self._norm_to_widget(c)
        d = self.LOUPE_D
        zoom = self.LOUPE_ZOOM
        # Source-frame region to sample (centered on the corner's source pixel).
        src_fx = c[0] * self._fw
        src_fy = c[1] * self._fh
        src_size = d / zoom
        from PyQt5.QtCore import QRect, QPoint
        from PyQt5.QtGui import QPainterPath
        src_rect = QRect(int(src_fx - src_size / 2),
                          int(src_fy - src_size / 2),
                          int(src_size), int(src_size))
        # Loupe position: above-right of cursor by default, flip / clamp
        # so it never falls outside the widget.
        offset = 24
        lx = int(hx + offset)
        ly = int(hy - offset - d)
        if lx + d > self.width() - 6:
            lx = int(hx - offset - d)
        if ly < 6:
            ly = int(hy + offset)
        lx = max(6, min(self.width() - d - 6, lx))
        ly = max(6, min(self.height() - d - 6, ly))
        # Clip to circle and draw zoomed source.
        path = QPainterPath()
        path.addEllipse(lx, ly, d, d)
        p.save()
        p.setClipPath(path)
        p.fillRect(lx, ly, d, d, QColor(0, 0, 0))
        try:
            p.drawImage(QRect(lx, ly, d, d), self._qimg, src_rect)
        except Exception:
            pass
        p.restore()
        # Border ring + crosshair.
        p.setPen(QPen(QColor(255, 200, 0), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(lx, ly, d, d)
        ccx = lx + d // 2
        ccy = ly + d // 2
        p.setPen(QPen(QColor(255, 60, 60), 1))
        p.drawLine(ccx - 14, ccy, ccx + 14, ccy)
        p.drawLine(ccx, ccy - 14, ccx, ccy + 14)
        p.setPen(QPen(QColor(255, 60, 60), 1))
        p.setBrush(QColor(255, 60, 60))
        p.drawEllipse(ccx - 2, ccy - 2, 4, 4)

    # ── Mouse ─────────────────────────────────────────────────────────
    def _candidate_groups(self):
        if self.mode == "quad":
            return [("quad", self.corners)]
        return [("open", self.open_corners),
                ("closed", self.closed_corners)]

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        x, y = ev.pos().x(), ev.pos().y()
        nearest = None
        nearest_d = self.GRAB_R ** 2
        for group, lst in self._candidate_groups():
            for i, c in enumerate(lst):
                cx, cy = self._norm_to_widget(c)
                d = (cx - x) ** 2 + (cy - y) ** 2
                if d < nearest_d:
                    nearest_d = d
                    nearest = (group, i)
        if nearest is not None:
            self._drag = nearest
            self.update()  # show loupe immediately on click

    def mouseMoveEvent(self, ev):
        if self._drag is None:
            return
        group, idx = self._drag
        n = self._widget_to_norm(ev.pos().x(), ev.pos().y())
        if group == "quad":
            self.corners[idx] = n
        elif group == "open":
            self.open_corners[idx] = n
        elif group == "closed":
            self.closed_corners[idx] = n
        self.update()
        self._emit()

    def mouseReleaseEvent(self, ev):
        self._drag = None
        self.update()  # hide loupe on release


class PerspectiveDialog(QDialog):
    """Modal dialog for manual perspective definition. Supports two modes
    (quad or plus). Returns the chosen state + computed homography."""

    def __init__(self, frame_bgr, initial_state=None,
                 video_size=None, parent=None):
        super().__init__(parent)
        self._host = parent
        self.setWindowTitle("Perspective Correction — Manual")
        self.resize(960, 700)
        if frame_bgr is not None:
            self._video_size = video_size or (frame_bgr.shape[1],
                                              frame_bgr.shape[0])
        else:
            self._video_size = video_size or (640, 480)

        outer = QVBoxLayout(self)
        outer.setSpacing(8)
        outer.setContentsMargins(10, 10, 10, 10)

        # ── Mode picker (top row) ─────────────────────────────────────
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self.rb_quad = QRadioButton("Quad")
        self.rb_plus = QRadioButton("Plus arms")
        self.rb_quad.setToolTip(
            "Drag 4 corners around the whole maze area; that quad becomes "
            "a square after correction."
        )
        self.rb_plus.setToolTip(
            "Place a rectangle over the open arms (blue) and another over "
            "the closed arms (orange). The app computes a homography so "
            "both line up into a perfect axis-aligned plus."
        )
        self._mode_grp = QButtonGroup(self)
        self._mode_grp.addButton(self.rb_quad, 0)
        self._mode_grp.addButton(self.rb_plus, 1)
        self.rb_plus.setChecked(True)  # plus is the natural fit for EPM
        mode_row.addWidget(self.rb_quad)
        mode_row.addWidget(self.rb_plus)
        mode_row.addStretch()
        outer.addLayout(mode_row)

        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet("color:#aaa; font-size:11px;")
        outer.addWidget(self.lbl_info)

        body = QHBoxLayout()
        body.setSpacing(8)
        self.editor = _CornerEditor(frame_bgr, self)
        self.editor.set_change_callback(self._refresh_preview)
        body.addWidget(self.editor, 1)

        # ── Right side panel ─────────────────────────────────────────
        side = QVBoxLayout()
        side.setSpacing(6)
        side.addWidget(QLabel("Warped preview:"))
        self.preview_lbl = QLabel("(drag a corner to preview)")
        self.preview_lbl.setFixedSize(260, 220)
        self.preview_lbl.setStyleSheet(
            "background:#111; border:1px solid #444; color:#666;"
        )
        self.preview_lbl.setAlignment(Qt.AlignCenter)
        side.addWidget(self.preview_lbl)

        side.addSpacing(6)
        grid_row = QHBoxLayout()
        grid_row.addWidget(QLabel("Grid:"))
        self.cmb_grid = QComboBox()
        for n in (3, 4, 5, 6, 8, 10, 12, 16):
            self.cmb_grid.addItem(f"{n}×{n}", n)
        self.cmb_grid.setCurrentIndex(3)
        self.cmb_grid.setFixedHeight(24)
        self.cmb_grid.currentIndexChanged.connect(
            lambda: self.editor.set_grid_n(self.cmb_grid.currentData())
        )
        grid_row.addWidget(self.cmb_grid)
        grid_row.addStretch()
        side.addLayout(grid_row)

        self.chk_grid = QCheckBox("Show gridlines")
        self.chk_grid.setChecked(True)
        self.chk_grid.toggled.connect(self.editor.set_show_grid)
        side.addWidget(self.chk_grid)

        self.chk_diag = QCheckBox("Show midlines / diagonals")
        self.chk_diag.setChecked(False)
        self.chk_diag.toggled.connect(self.editor.set_show_diagonals)
        side.addWidget(self.chk_diag)

        side.addSpacing(8)
        side.addWidget(QLabel("Output size:"))
        out_row = QHBoxLayout()
        self.spin_out = QSpinBox()
        self.spin_out.setRange(256, 4096)
        self.spin_out.setSingleStep(32)
        self.spin_out.setValue(int(min(self._video_size)))
        self.spin_out.setSuffix(" px")
        self.spin_out.setFixedHeight(24)
        self.spin_out.valueChanged.connect(lambda _: self._refresh_preview())
        out_row.addWidget(self.spin_out)
        out_row.addStretch()
        side.addLayout(out_row)
        out_hint = QLabel("Square output side. Smaller = faster tracking.")
        out_hint.setStyleSheet("color:#888; font-size:10px;")
        out_hint.setWordWrap(True)
        side.addWidget(out_hint)

        # ── Plus-mode extras (arm width %) ────────────────────────────
        self.plus_box = QGroupBox("Plus output")
        pl = QVBoxLayout(self.plus_box)
        pl.setSpacing(4)
        aw_row = QHBoxLayout()
        aw_row.addWidget(QLabel("Arm width:"))
        self.spin_arm_w = QDoubleSpinBox()
        self.spin_arm_w.setRange(0.02, 0.5)
        self.spin_arm_w.setDecimals(2)
        self.spin_arm_w.setSingleStep(0.01)
        self.spin_arm_w.setValue(0.12)
        self.spin_arm_w.setSuffix(" w")
        self.spin_arm_w.setFixedHeight(24)
        self.spin_arm_w.valueChanged.connect(lambda _: self._refresh_preview())
        aw_row.addWidget(self.spin_arm_w)
        aw_row.addStretch()
        pl.addLayout(aw_row)
        margin_row = QHBoxLayout()
        margin_row.addWidget(QLabel("Margin:"))
        self.spin_margin = QDoubleSpinBox()
        self.spin_margin.setRange(0.0, 0.4)
        self.spin_margin.setDecimals(2)
        self.spin_margin.setSingleStep(0.01)
        self.spin_margin.setValue(0.05)
        self.spin_margin.setSuffix(" m")
        self.spin_margin.setFixedHeight(24)
        self.spin_margin.valueChanged.connect(lambda _: self._refresh_preview())
        margin_row.addWidget(self.spin_margin)
        margin_row.addStretch()
        pl.addLayout(margin_row)
        plus_hint = QLabel(
            "Arm width = thickness of each arm rectangle in the output, "
            "as a fraction of side. Margin = empty space at each arm tip."
        )
        plus_hint.setStyleSheet("color:#888; font-size:10px;")
        plus_hint.setWordWrap(True)
        pl.addWidget(plus_hint)
        btn_swap = QPushButton("Swap open ↔ closed")
        btn_swap.setFixedHeight(22)
        btn_swap.setToolTip(
            "Flip the roles of the two rectangles. Use if your camera has "
            "the maze rotated 90°."
        )
        btn_swap.clicked.connect(self.editor.swap_plus_axes)
        pl.addWidget(btn_swap)
        side.addSpacing(6)
        side.addWidget(self.plus_box)

        side.addSpacing(8)

        # Reset buttons (relabel based on mode).
        self.btn_reset = QPushButton("Reset")
        self.btn_reset.setFixedHeight(24)
        self.btn_reset.clicked.connect(self._reset_default)
        side.addWidget(self.btn_reset)

        self.btn_full = QPushButton("Reset (full frame)")
        self.btn_full.setFixedHeight(24)
        self.btn_full.clicked.connect(self.editor.reset_quad_full)
        side.addWidget(self.btn_full)

        self.btn_template = QPushButton("Use EPM template")
        self.btn_template.setFixedHeight(24)
        self.btn_template.setToolTip(
            "Snap to the current EPM hub + endpoints. In plus mode, lays "
            "rectangles along the N/S and E/W arm directions."
        )
        self.btn_template.clicked.connect(self._use_template)
        side.addWidget(self.btn_template)

        side.addStretch()
        body.addLayout(side)
        outer.addLayout(body)

        actions = QHBoxLayout()
        actions.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedHeight(26)
        btn_cancel.clicked.connect(self.reject)
        actions.addWidget(btn_cancel)
        btn_apply = QPushButton("Apply perspective")
        btn_apply.setFixedHeight(26)
        btn_apply.setDefault(True)
        btn_apply.clicked.connect(self._on_apply)
        actions.addWidget(btn_apply)
        outer.addLayout(actions)

        # Mode change → editor mode + label + side-panel visibility.
        self.rb_quad.toggled.connect(self._on_mode_changed)
        self.rb_plus.toggled.connect(self._on_mode_changed)

        # Apply initial state (after widgets exist).
        self._apply_initial_state(initial_state)
        self._on_mode_changed()
        self._refresh_preview()

    # ── Mode wiring ───────────────────────────────────────────────────
    def _on_mode_changed(self):
        mode = "quad" if self.rb_quad.isChecked() else "plus"
        self.editor.set_mode(mode)
        if mode == "quad":
            self.lbl_info.setText(
                "Drag the four yellow corners to outline the maze area. "
                "TL → TR → BR → BL clockwise. The cyan grid shows how the "
                "area will straighten after correction."
            )
            self.btn_reset.setText("Reset (inset 10%)")
            self.btn_full.setVisible(True)
            self.plus_box.setVisible(False)
        else:
            self.lbl_info.setText(
                "Place the BLUE rectangle over the OPEN-arm pair (long edge "
                "along the open arms), and the ORANGE rectangle over the "
                "CLOSED-arm pair. Drag each rectangle's 4 corners to hug "
                "the visible arm walls. Apply makes both rectangles into a "
                "perfect axis-aligned plus."
            )
            self.btn_reset.setText("Reset rectangles")
            self.btn_full.setVisible(False)
            self.plus_box.setVisible(True)
        self._refresh_preview()

    def _reset_default(self):
        if self.editor.mode == "quad":
            self.editor.reset_quad_default()
        else:
            self.editor.reset_plus_default()

    # ── Initial state loading ─────────────────────────────────────────
    def _apply_initial_state(self, state):
        if not state:
            return
        if isinstance(state, dict):
            mode = state.get("mode")
            if mode == "plus":
                self.rb_plus.setChecked(True)
                self.editor.set_plus_corners(
                    state.get("open"), state.get("closed"))
                if state.get("arm_w") is not None:
                    self.spin_arm_w.setValue(float(state["arm_w"]))
                if state.get("margin") is not None:
                    self.spin_margin.setValue(float(state["margin"]))
                if state.get("output_side") is not None:
                    self.spin_out.setValue(int(state["output_side"]))
            elif mode == "quad":
                self.rb_quad.setChecked(True)
                self.editor.set_corners(state.get("quad"))
                if state.get("output_side") is not None:
                    self.spin_out.setValue(int(state["output_side"]))
        elif isinstance(state, (list, tuple)) and len(state) >= 4:
            # Backward-compat: bare list of 4 → quad mode.
            self.rb_quad.setChecked(True)
            self.editor.set_corners(list(state))

    # ── EPM-template seeding ─────────────────────────────────────────
    def _use_template(self):
        host = self._host
        if host is None:
            return
        hub = getattr(host, "_epm_hub", None)
        eps = getattr(host, "_epm_endpoints", None)
        if not hub or not eps or len(eps) < 4:
            QMessageBox.information(
                self, "EPM template",
                "Set the EPM plus template first (Step 2 → Plus-template)."
            )
            return

        if self.editor.mode == "quad":
            all_pts = [hub] + list(eps)
            xs = [p[0] for p in all_pts]
            ys = [p[1] for p in all_pts]
            x0, x1 = min(xs), max(xs)
            y0, y1 = min(ys), max(ys)
            pad = 0.02
            x0 -= pad; y0 -= pad; x1 += pad; y1 += pad
            self.editor.set_corners(
                [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            )
        else:
            # Identify which two endpoints are the open pair vs closed pair
            # by checking the kind dict the user set in Step 2.
            kinds = getattr(host, "_epm_arm_kinds", None) or {}
            from .zones import ARM_NAMES
            name_to_kind = {n: kinds.get(n, "closed") for n in ARM_NAMES}
            # Map endpoints by index — endpoints list is N, S, E, W in
            # template order (see zones.default_plus_template_geometry).
            ep_by_name = {n: eps[i] for i, n in enumerate(ARM_NAMES[:4])}
            open_eps = [ep_by_name[n] for n in ARM_NAMES
                        if name_to_kind.get(n) == "open"]
            closed_eps = [ep_by_name[n] for n in ARM_NAMES
                          if name_to_kind.get(n) == "closed"]
            if len(open_eps) < 2 or len(closed_eps) < 2:
                # Fall back: N/S = open, E/W = closed.
                open_eps = [eps[0], eps[1]]
                closed_eps = [eps[2], eps[3]]
            # Build rect along each pair: short edge = arm_w (in norm).
            arm_w = float(self.spin_arm_w.value())
            self.editor.set_plus_corners(
                _rect_along_axis(open_eps[0], open_eps[1], arm_w),
                _rect_along_axis(closed_eps[0], closed_eps[1], arm_w),
            )
        self._refresh_preview()

    # ── Preview + homography ─────────────────────────────────────────
    def _refresh_preview(self):
        H, warp_size = self.compute_homography()
        if H is None or self.editor._frame_bgr is None:
            self.preview_lbl.setText("(invalid configuration)")
            self.preview_lbl.setPixmap(QPixmap())
            return
        try:
            warped = cv2.warpPerspective(
                self.editor._frame_bgr, H, warp_size
            )
        except cv2.error:
            self.preview_lbl.setText("(warp failed)")
            return
        # Draw axis-aligned plus outline on top of the preview so user
        # sees where the arms will land.
        if self.editor.mode == "plus":
            warped = warped.copy()
            self._draw_target_plus_on_preview(warped, warp_size)
        qimg = _bgr_to_qimage(warped)
        if qimg is None:
            return
        target_w = self.preview_lbl.width() - 4
        target_h = self.preview_lbl.height() - 4
        scaled = QPixmap.fromImage(qimg).scaled(
            target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.preview_lbl.setText("")
        self.preview_lbl.setPixmap(scaled)

    def _draw_target_plus_on_preview(self, img, warp_size):
        side = warp_size[0]
        cx = cy = side // 2
        margin = int(float(self.spin_margin.value()) * side)
        half_w = int(float(self.spin_arm_w.value()) * side / 2)
        # Vertical (open) rect.
        cv2.rectangle(img, (cx - half_w, margin),
                       (cx + half_w, side - margin), (80, 170, 255), 1)
        # Horizontal (closed) rect.
        cv2.rectangle(img, (margin, cy - half_w),
                       (side - margin, cy + half_w), (60, 130, 255), 1)

    def compute_homography(self):
        fw, fh = self._video_size
        side = int(self.spin_out.value())
        if self.editor.mode == "quad":
            return self._homography_quad(fw, fh, side)
        return self._homography_plus(fw, fh, side)

    def _homography_quad(self, fw, fh, side):
        src_pts = np.array(
            [(c[0] * fw, c[1] * fh) for c in self.editor.corners],
            dtype=np.float32,
        )
        if src_pts.shape != (4, 2):
            return None, None
        for i in range(4):
            for j in range(i + 1, 4):
                if (abs(src_pts[i, 0] - src_pts[j, 0]) < 1.0
                        and abs(src_pts[i, 1] - src_pts[j, 1]) < 1.0):
                    return None, None
        dst_pts = np.array(
            [(0, 0), (side - 1, 0), (side - 1, side - 1), (0, side - 1)],
            dtype=np.float32,
        )
        try:
            H = cv2.getPerspectiveTransform(src_pts, dst_pts)
        except cv2.error:
            return None, None
        return H, (side, side)

    def _homography_plus(self, fw, fh, side):
        op = self.editor.open_corners
        cl = self.editor.closed_corners
        if len(op) < 4 or len(cl) < 4:
            return None, None
        cx = cy = side // 2
        half_w = float(self.spin_arm_w.value()) * side / 2.0
        margin = float(self.spin_margin.value()) * side
        # Source (8 pixel points): open N-L, N-R, S-R, S-L, then closed
        # W-T, E-T, E-B, W-B.
        src = np.array(
            [(op[0][0] * fw, op[0][1] * fh),  # N-L
             (op[1][0] * fw, op[1][1] * fh),  # N-R
             (op[2][0] * fw, op[2][1] * fh),  # S-R
             (op[3][0] * fw, op[3][1] * fh),  # S-L
             (cl[0][0] * fw, cl[0][1] * fh),  # W-T
             (cl[1][0] * fw, cl[1][1] * fh),  # E-T
             (cl[2][0] * fw, cl[2][1] * fh),  # E-B
             (cl[3][0] * fw, cl[3][1] * fh)], # W-B
            dtype=np.float32,
        )
        dst = np.array(
            [(cx - half_w, margin),
             (cx + half_w, margin),
             (cx + half_w, side - margin),
             (cx - half_w, side - margin),
             (margin,         cy - half_w),
             (side - margin,  cy - half_w),
             (side - margin,  cy + half_w),
             (margin,         cy + half_w)],
            dtype=np.float32,
        )
        # Reject if any pair of source points is coincident — degenerate.
        for i in range(len(src)):
            for j in range(i + 1, len(src)):
                if (abs(src[i, 0] - src[j, 0]) < 1.0
                        and abs(src[i, 1] - src[j, 1]) < 1.0):
                    return None, None
        try:
            # findHomography handles the overdetermined 8-pt LS fit.
            H, _ = cv2.findHomography(src, dst, method=0)
        except cv2.error:
            return None, None
        if H is None:
            return None, None
        return H, (side, side)

    def _on_apply(self):
        H, _ = self.compute_homography()
        if H is None:
            QMessageBox.warning(
                self, "Perspective correction",
                "The current corner positions are invalid (degenerate "
                "quad / rectangles too small). Adjust the corners and "
                "click Apply again."
            )
            return
        self.accept()

    # ── Result accessors ──────────────────────────────────────────────
    def result_state(self):
        """Return a dict capturing the current mode + corner data so the
        dialog can be re-seeded next time the user opens it."""
        side = int(self.spin_out.value())
        if self.editor.mode == "quad":
            return {
                "mode": "quad",
                "quad": [tuple(c) for c in self.editor.corners],
                "output_side": side,
            }
        return {
            "mode": "plus",
            "open":   [tuple(c) for c in self.editor.open_corners],
            "closed": [tuple(c) for c in self.editor.closed_corners],
            "arm_w":  float(self.spin_arm_w.value()),
            "margin": float(self.spin_margin.value()),
            "output_side": side,
        }

    def result_homography(self):
        return self.compute_homography()


def _rect_along_axis(p1, p2, width_norm):
    """Build a 4-corner rect (TL, TR, BR, BL in the rect's local axis)
    centered on the line p1↔p2 with the given norm width perpendicular
    to the long axis. Returns the corners in the canonical TL/TR/BR/BL
    order so they slot into the editor's open_corners / closed_corners
    arrays directly."""
    import math
    p1 = (float(p1[0]), float(p1[1]))
    p2 = (float(p2[0]), float(p2[1]))
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return [p1, p2, p2, p1]
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux
    h = width_norm / 2.0
    a = (p1[0] + nx * h, p1[1] + ny * h)  # near p1, +n
    b = (p2[0] + nx * h, p2[1] + ny * h)  # near p2, +n
    c = (p2[0] - nx * h, p2[1] - ny * h)  # near p2, -n
    d = (p1[0] - nx * h, p1[1] - ny * h)  # near p1, -n
    return [a, b, c, d]
