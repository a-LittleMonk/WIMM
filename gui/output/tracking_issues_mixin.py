"""IssuesMixin — Tracking Issues tab (glitch detector + table + mini-map
+ inline frame preview + status / smoothing / CSV actions).

Mixed into ExperimentTab. Owns the entire "Tracking Issues" UI (shown in a
popup from the preview, with red marks on the frame slider) plus
its persistence per-video (threshold, accel threshold, detector toggles,
false-positive marks) inside the host's `config["tracking_issues"]`.

Reuses host attrs / methods:
    self.config, self.video_path, self.raw_df, self.fps, self.metrics,
    self.zone_drawer, self.slider_scrub, self._graph_data,
    self._trim_start_frame, self._on_scrub, self._open_corrections_popup,
    self._populate_excel_tab.
"""
import os
import numpy as np

from PyQt5.QtCore import Qt, QTimer, QRectF, QSize, pyqtSignal
from PyQt5.QtGui import QColor, QPixmap, QImage, QPainter
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSplitter, QFrame,
    QTableWidget, QTableWidgetItem, QCheckBox, QDoubleSpinBox,
    QFileDialog, QMessageBox, QSizePolicy,
)

from core import logger


from gui import theme


class _IssueFrameView(QWidget):
    """Frame picture scaled to fit (keeps aspect). Never asks for more room
    than it has, so it can't push other parts of the popup around. In pick
    mode a click emits the position as 0-1 fractions of the frame."""
    clicked = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix = None
        self._msg = "Click a row, or play the video, to see the frame here."
        self._target = None
        self._pick = False
        self.setMinimumSize(240, 140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def sizeHint(self):
        return QSize(800, 560)

    def set_image(self, pix, msg=None):
        self._pix = pix
        if msg is not None:
            self._msg = msg
        self.update()

    # Back-compat with the old QLabel preview.
    def setPixmap(self, pix):
        self.set_image(pix if pix is not None and not pix.isNull() else None)

    def setText(self, text):
        self.set_image(None, text)

    def set_pick(self, on):
        self._pick = bool(on)
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0A0C0E"))
        pix = self._pix
        if pix is None or pix.isNull():
            self._target = None
            p.setPen(QColor("#8F99A3"))
            p.drawText(self.rect().adjusted(12, 12, -12, -12),
                       Qt.AlignCenter | Qt.TextWordWrap, self._msg)
            return
        W, H = self.width(), self.height()
        s = min(W / pix.width(), H / pix.height())
        tw, th = pix.width() * s, pix.height() * s
        self._target = QRectF((W - tw) / 2.0, (H - th) / 2.0, tw, th)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(self._target, pix, QRectF(pix.rect()))
        if self._pick:
            p.setPen(QColor("#E8B04A"))
            p.drawText(self.rect().adjusted(10, 8, -10, -8), Qt.AlignTop | Qt.AlignLeft,
                       "Fix position: click the mouse")

    def mousePressEvent(self, e):
        t = self._target
        if self._pick and t is not None and e.button() == Qt.LeftButton \
                and t.contains(e.pos().x(), e.pos().y()):
            self.clicked.emit((e.pos().x() - t.x()) / t.width(),
                              (e.pos().y() - t.y()) / t.height())
            return
        super().mousePressEvent(e)


class _ElideLabel(QLabel):
    """One-line label that elides ("…") instead of asking for more width;
    the full text is in the tooltip."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setToolTip(text)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)
        self.update()

    def minimumSizeHint(self):
        return QSize(20, super().minimumSizeHint().height())

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.contentsRect()
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        p.drawText(r, int(self.alignment()) | Qt.AlignVCenter,
                   self.fontMetrics().elidedText(self.text(), Qt.ElideRight, r.width()))


class IssuesMixin:
    def _build_tracking_issues_tab(self):
        """Tracking-issues tool (shown in a popup from the preview):

            [ detector settings — wrap onto more lines when narrow        ]
            [ issue table      |  frame view (big)                         ]
            [ ---------------  |  Detected area · Show mask · frame / nav  ]
            [ mini map         |  corrections: Fix / Remove / Undo / …     ]
            [ false-positive · smooth · CSV                                ]

        Every part sits in a splitter with a sensible minimum, so dragging
        the dividers or resizing the window never draws parts on top of
        each other."""
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        from matplotlib.figure import Figure
        from gui.out_widgets import OutPanel, Section
        from gui.responsive import pair
        from gui.widgets_v2 import SwitchBox, IconButton, IconTextButton

        w = QWidget()
        vlay = QVBoxLayout(w)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(10)

        # ── Detector settings (wrapping row) ──────────────────────────────
        params = Section("")
        params.title.hide()
        params.body.setContentsMargins(12, 8, 12, 8)
        flow_host = QWidget()
        rows = QVBoxLayout(flow_host)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(6)
        row_a, row_b = QHBoxLayout(), QHBoxLayout()
        row_a.setSpacing(14)
        row_b.setSpacing(6)
        rows.addLayout(row_a)
        rows.addLayout(row_b)
        self._issues_thresh = QDoubleSpinBox()
        self._issues_thresh.setRange(5.0, 1000.0)
        self._issues_thresh.setSuffix(" cm/s")
        self._issues_thresh.setDecimals(1)
        self._issues_thresh.setSingleStep(10.0)
        self._issues_thresh.setValue(120.0)
        self._issues_thresh.setFixedWidth(108)
        self._issues_chk_auto = QCheckBox("Auto")
        self._issues_chk_auto.setToolTip(
            "Self-calibrate to max(threshold, 2.5 × p99.9 of session speed)."
        )
        self._issues_chk_auto.setChecked(True)
        row_a.addWidget(pair(self._issues_lbl("Speed >"), self._issues_thresh,
                            self._issues_chk_auto))
        self._issues_accel_thresh = QDoubleSpinBox()
        self._issues_accel_thresh.setRange(50.0, 5000.0)
        self._issues_accel_thresh.setSuffix(" cm/s²")
        self._issues_accel_thresh.setDecimals(0)
        self._issues_accel_thresh.setSingleStep(50.0)
        self._issues_accel_thresh.setValue(500.0)
        self._issues_accel_thresh.setFixedWidth(116)
        self._issues_accel_thresh.setToolTip(
            "Flag frames where |Δspeed| × fps exceeds this. Mice can hit "
            "~300 cm/s² in a real burst; >500 is usually a tracker artifact."
        )
        row_a.addWidget(pair(self._issues_lbl("Accel >"), self._issues_accel_thresh))
        self._issues_chk_speed   = QCheckBox("Speed spike")
        self._issues_chk_outside = QCheckBox("Outside arena")
        self._issues_chk_accel   = QCheckBox("Accel spike")
        self._issues_chk_gap     = QCheckBox("Gap+jump")
        chips = [self._issues_lbl("Detectors")]
        for cb in (self._issues_chk_speed, self._issues_chk_outside,
                   self._issues_chk_accel, self._issues_chk_gap):
            cb.setChecked(True)
            cb.setProperty("chip", True)
            cb.setCursor(Qt.PointingHandCursor)
            chips.append(cb)
        for c in chips:
            row_b.addWidget(c)
        row_b.addStretch(1)
        self._issues_btn_recompute = QPushButton("Recompute")
        self._issues_btn_recompute.setFixedHeight(26)
        self._issues_btn_recompute.clicked.connect(
            lambda: self._recompute_tracking_issues(save_state=True)
        )
        row_a.addStretch(1)
        row_a.addWidget(self._issues_btn_recompute)
        params.body.addWidget(flow_host)
        vlay.addWidget(params)

        # ── Left: issue table (top) + mini map (bottom) ───────────────────
        panel = OutPanel("")
        panel.bar.show()
        panel.title.setText("Flagged frames")
        self._issues_panel = panel
        self._issues_stats_lbl = _ElideLabel("Run tracking first to see flagged frames.")
        self._issues_stats_lbl.setObjectName("IssuesStats")
        theme.set_tone(self._issues_stats_lbl, "faint", "font-size:11px;")
        stats_box = QWidget()
        sb = QVBoxLayout(stats_box)
        sb.setContentsMargins(12, 6, 12, 6)
        sb.addWidget(self._issues_stats_lbl)
        panel.body.addWidget(stats_box)

        self._issues_table = QTableWidget()
        self._issues_table.setProperty("out", True)
        self._issues_table.setShowGrid(False)
        self._issues_table.setFrameShape(QFrame.NoFrame)
        self._issues_table.verticalHeader().setVisible(False)
        self._issues_table.verticalHeader().setDefaultSectionSize(22)
        self._issues_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._issues_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._issues_table.setSelectionMode(QTableWidget.SingleSelection)
        self._issues_table.setSortingEnabled(True)
        self._issues_table.setMinimumSize(200, 120)
        # Compact numbers: smaller type than the app's default tables.
        self._issues_table.setStyleSheet(
            "QTableWidget { font-size: 11px; }"
            "QHeaderView::section { font-size: 10px; padding: 2px 6px; }")
        self._issues_table.itemSelectionChanged.connect(self._on_issue_row_selected)
        panel.body.addWidget(self._issues_table, 1)

        self._issues_mini_fig = Figure(figsize=(3, 3))
        self._issues_mini_canvas = FigureCanvasQTAgg(self._issues_mini_fig)
        self._issues_mini_canvas.setMinimumSize(160, 120)

        left = QSplitter(Qt.Vertical)
        left.setChildrenCollapsible(False)
        left.setHandleWidth(8)
        left.addWidget(panel)
        left.addWidget(self._issues_mini_canvas)
        left.setStretchFactor(0, 3)
        left.setStretchFactor(1, 2)
        left.setSizes([380, 240])

        # ── Right: big frame view + its controls ──────────────────────────
        vpanel = OutPanel("")
        vpanel.bar.show()
        vpanel.title.setText("Frame")
        self._issues_sw_detect = SwitchBox("Detected area")
        self._issues_sw_detect.setToolTip(
            "Paint what the detection settings find on this frame (same as "
            "'Detected area' in Detection). The red dot is the tracked point.\n"
            "Dot on the mouse but area wrong → tune detection.\n"
            "Area right but dot elsewhere → a tracking glitch: fix it here.")
        self._issues_sw_mask = SwitchBox("Show mask")
        self._issues_sw_mask.setToolTip("Show the black-and-white detection mask.")
        for sw in (self._issues_sw_detect, self._issues_sw_mask):
            sw.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            sw.setMinimumWidth(92)              # label elides when narrow
            sw.setMaximumWidth(sw.sizeHint().width())
            sw.toggled.connect(lambda _c: self._refresh_issue_view())
            vpanel._bar_layout.addWidget(sw)

        self._issues_view = _IssueFrameView()
        self._issues_view.clicked.connect(self._on_issue_view_click)
        vpanel.body.addWidget(self._issues_view, 1)
        # Kept for older callers.
        self._issues_video_lbl = self._issues_view
        self._issues_video_frame_no = None

        # Navigation: ⏮ prev issue · ◀ frame · [frame info] · frame ▶ · next issue ⏭
        nav_host = QWidget()
        nav_host.setObjectName("OutPanelBar")
        nav_host.setAttribute(Qt.WA_StyledBackground, True)
        nav = QHBoxLayout(nav_host)
        nav.setContentsMargins(10, 6, 10, 6)
        nav.setSpacing(4)

        def _nb(icon, tip, slot):
            b = IconButton(icon, 12, "TEXT_2", "TEXT", tip, 28, variant="border")
            b.clicked.connect(slot)
            nav.addWidget(b)
            return b
        self._issues_btn_prev_issue = _nb("first", "Previous flagged frame",
                                          lambda: self._jump_issue(-1))
        self._issues_btn_prev = _nb("prev", "Previous frame (step 1)",
                                    lambda: self._step_issue_frame(-1))
        self._issues_frame_lbl = QLabel("—")
        self._issues_frame_lbl.setAlignment(Qt.AlignCenter)
        theme.set_tone(self._issues_frame_lbl, "text", "font-size:12px; font-weight:600;")
        nav.addWidget(self._issues_frame_lbl, 1)
        self._issues_btn_next = _nb("next", "Next frame (step 1)",
                                    lambda: self._step_issue_frame(+1))
        self._issues_btn_next_issue = _nb("last", "Next flagged frame",
                                          lambda: self._jump_issue(+1))
        vpanel.body.addWidget(nav_host)
        # What this frame is: flagged reason, fixed / removed, detected px.
        self._issues_state_lbl = _ElideLabel("")
        self._issues_state_lbl.setContentsMargins(12, 0, 12, 4)
        theme.set_tone(self._issues_state_lbl, "text2", "font-size:11px;")
        vpanel.body.addWidget(self._issues_state_lbl)

        # Corrections (same actions as the Frame corrections panel; they
        # act on the frame shown here).
        corr_host = QWidget()
        corr_host.setObjectName("OutPanelBar")
        corr_host.setAttribute(Qt.WA_StyledBackground, True)
        cv = QVBoxLayout(corr_host)
        cv.setContentsMargins(10, 6, 10, 8)
        cv.setSpacing(4)
        corr_title = QLabel("Corrections")
        theme.set_tone(corr_title, "text2", "font-size:11px; font-weight:600;")
        cv.addWidget(corr_title)
        from PyQt5.QtWidgets import QGridLayout
        cflow_host = QWidget()
        cgrid = QGridLayout(cflow_host)
        cgrid.setContentsMargins(0, 0, 0, 0)
        cgrid.setHorizontalSpacing(6)
        cgrid.setVerticalSpacing(6)
        _cpos = [0]

        def _cb(text, tip, slot, checkable=False):
            icon, text = text.split(" ", 1)
            b = IconTextButton(icon, text.strip(), 12, height=26)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            if checkable:
                b.toggled.connect(slot)
            else:
                b.clicked.connect(slot)
            i = _cpos[0]
            _cpos[0] += 1
            cgrid.addWidget(b, i // 3, i % 3)
            return b
        self._issues_btn_fix = _cb(
            "t_fix Fix position",
            "Turn on, then click the mouse on the frame above to move the "
            "tracked point there.", self._on_issue_fix_toggled, checkable=True)
        self._issues_btn_remove = _cb(
            "x Remove point",
            "This frame's point is wrong → mark the frame as missed "
            "(then use Interpolate to fill it).", self._issue_remove_point)
        self._issues_btn_undo = _cb(
            "reset Undo fix here",
            "Put back the tracker's own point on this frame.", self._issue_undo_fix)
        self._issues_btn_interp = _cb(
            "analysis Interpolate gaps",
            "Fill missed / removed frames from the good frames around them "
            "(runs up to Max gap; longer ones stay missed).",
            lambda: (self._interpolate_gaps(max_len=self._autofix_max_gap()),
                     self._refresh_issue_view()))
        self._issues_btn_clear_all = _cb(
            "trash Clear all fixes", "Undo every manual fix and interpolation.",
            lambda: (self._clear_fixes(), self._refresh_issue_view()))
        self._issues_btn_auto = _cb(
            "next Auto-fix && next",
            "For this flagged frame (or the next one): try removing the "
            "frames around it one run at a time, keep the smallest change "
            "that clears the problem, recalculate, go to the next.",
            self._issue_auto_fix_next)
        self._issues_btn_auto_all = _cb(
            "last Auto-fix all",
            "Plan Auto-fix for every active flagged frame, show how many "
            "frames would change, and apply after you confirm. "
            "False-positives are left alone.",
            self._issue_auto_fix_all)
        cv.addWidget(cflow_host)

        # Max gap: the longest run Auto-fix / Interpolate gaps may fill.
        from PyQt5.QtWidgets import QSpinBox
        tools = QHBoxLayout()
        tools.setSpacing(6)
        self._issues_max_gap = QSpinBox()
        self._issues_max_gap.setRange(1, 150)
        self._issues_max_gap.setValue(2)          # default: 2 frames
        self._issues_max_gap.setSuffix(" frames")
        self._issues_max_gap.setFixedWidth(104)
        self._issues_max_gap.setToolTip(
            "Longest run of frames Auto-fix and Interpolate gaps may fill with "
            "a straight line. Longer losses stay as they are (flagged / missed) "
            "for you to check, so a straight line can't invent movement or "
            "zone entries.")
        self._issues_max_gap_s = QLabel("")
        theme.set_tone(self._issues_max_gap_s, "faint", "font-size:11px;")
        self._issues_max_gap.valueChanged.connect(self._on_max_gap_changed)
        tools.addWidget(self._issues_lbl("Max gap"))
        tools.addWidget(self._issues_max_gap)
        tools.addWidget(self._issues_max_gap_s)
        tools.addStretch(1)

        # Review the frames that were filled in / fixed: ◀ Go to ▶ (k of N)
        def _ib(icon, tip, slot):
            bt = IconButton(icon, 12, "TEXT_2", "TEXT", tip, 26, variant="border")
            bt.clicked.connect(slot)
            return bt
        tools.addWidget(self._issues_lbl("Interpolated"))
        self._issues_btn_interp_prev = _ib("prev", "Previous interpolated / fixed frame",
                                           lambda: self._goto_fixed(-1))
        self._issues_btn_interp_go = QPushButton("Go to")
        self._issues_btn_interp_go.setFixedHeight(26)
        self._issues_btn_interp_go.setToolTip(
            "Go to the nearest interpolated / fixed frame (from the current frame).")
        self._issues_btn_interp_go.clicked.connect(lambda: self._goto_fixed(0))
        self._issues_btn_interp_next = _ib("next", "Next interpolated / fixed frame",
                                           lambda: self._goto_fixed(+1))
        self._issues_interp_pos = QLabel("")
        theme.set_tone(self._issues_interp_pos, "faint", "font-size:11px;")
        for wdg in (self._issues_btn_interp_prev, self._issues_btn_interp_go,
                    self._issues_btn_interp_next, self._issues_interp_pos):
            tools.addWidget(wdg)
        cv.addLayout(tools)
        vpanel.body.addWidget(corr_host)

        main = QSplitter(Qt.Horizontal)
        main.setChildrenCollapsible(False)
        main.setHandleWidth(8)
        main.addWidget(left)
        main.addWidget(vpanel)
        main.setStretchFactor(0, 2)
        main.setStretchFactor(1, 5)
        main.setSizes([360, 820])
        # (frame panel minimum comes from its contents)
        left.setMinimumWidth(220)
        vlay.addWidget(main, 1)

        # ── Bottom: review actions ────────────────────────────────────────
        strip = QWidget()
        strip.setObjectName("OutPanelBar")
        strip.setAttribute(Qt.WA_StyledBackground, True)
        act_flow = QHBoxLayout(strip)
        act_flow.setContentsMargins(12, 8, 12, 8)
        act_flow.setSpacing(6)
        self._issues_btn_fp = QPushButton("Mark false-positive")
        self._issues_btn_fp.setToolTip(
            "Dismiss the selected glitch. Will be excluded from smoothing + "
            "remembered next time this video is opened."
        )
        self._issues_btn_fp.clicked.connect(lambda: self._set_issue_status("false_positive"))
        self._issues_btn_unmark = QPushButton("Unmark")
        self._issues_btn_unmark.clicked.connect(lambda: self._set_issue_status("active"))
        self._issues_btn_smooth = QPushButton("Smooth flagged")
        self._issues_btn_smooth.setToolTip(
            "Linear-interp active flagged frames into X_clean / Y_clean "
            "columns. Original X/Y untouched."
        )
        self._issues_btn_smooth.clicked.connect(self._smooth_flagged_frames)
        self._issues_btn_csv = QPushButton("Export CSV")
        self._issues_btn_csv.clicked.connect(self._export_issues_csv)
        for b in (self._issues_btn_fp, self._issues_btn_unmark,
                  self._issues_btn_smooth, self._issues_btn_csv):
            b.setFixedHeight(26)
            act_flow.addWidget(b)
        # The Frame-corrections panel / popup is still reachable.
        self._issues_btn_corrections = QPushButton("Corrections panel")
        self._issues_btn_corrections.setFixedHeight(26)
        self._issues_btn_corrections.clicked.connect(self._open_corrections_popup)
        self._issues_btn_corrections.hide()
        act_flow.addStretch(1)
        vlay.addWidget(strip)

        # Internal state.
        self._issues_df = None
        self._issues_fp_set = set()   # frame numbers user marked false-positive
        self._issues_view_timer = QTimer(w)
        self._issues_view_timer.setSingleShot(True)
        self._issues_view_timer.setInterval(0)
        self._issues_view_timer.timeout.connect(self._refresh_issue_view)
        theme.notifier.changed.connect(self._on_theme_issues)
        return w

    @staticmethod
    def _issues_lbl(text):
        lb = QLabel(text)
        theme.set_tone(lb, "text2")
        return lb

    def _on_theme_issues(self, _mode):
        try:
            if self._issues_df is not None:
                self._fill_issues_table(self._issues_df)
            self._render_issues_mini_map()
        except Exception:
            pass

    def _tracking_issues_state_key(self):
        """Persistence key in `config["tracking_issues"]` — keyed by video
        path so each video remembers its own threshold + FP marks."""
        return self.video_path or "__unknown__"

    def _load_tracking_issues_state(self):
        store = self.config.get("tracking_issues") or {}
        s = store.get(self._tracking_issues_state_key()) or {}
        try:
            self._issues_thresh.blockSignals(True)
            self._issues_thresh.setValue(float(s.get("threshold_cms", 120.0)))
            self._issues_thresh.blockSignals(False)
            self._issues_accel_thresh.blockSignals(True)
            self._issues_accel_thresh.setValue(float(s.get("accel_thresh_cms2", 500.0)))
            self._issues_accel_thresh.blockSignals(False)
            self._issues_chk_auto.setChecked(bool(s.get("auto", True)))
            self._issues_max_gap.blockSignals(True)
            # Older builds saved their default (10 frames / 0.33 s) under
            # other keys; those are ignored so the new default (2) applies.
            self._issues_max_gap.setValue(int(s.get("autofix_gap_frames") or 2))
            self._issues_max_gap.blockSignals(False)
            self._on_max_gap_changed(None, save=False)
            dets = set(s.get("detectors", ["speed", "outside", "accel", "gap_jump"]))
            self._issues_chk_speed.setChecked("speed" in dets)
            self._issues_chk_outside.setChecked("outside" in dets)
            self._issues_chk_accel.setChecked("accel" in dets)
            self._issues_chk_gap.setChecked("gap_jump" in dets)
            self._issues_fp_set = {int(f) for f in s.get("false_positives", [])}
        except Exception as e:
            logger.warn(f"tracking_issues state load failed: {e}",
                        source="issues")
            self._issues_fp_set = set()

    def _save_tracking_issues_state(self):
        try:
            store = self.config.setdefault("tracking_issues", {})
            detectors = []
            if self._issues_chk_speed.isChecked():   detectors.append("speed")
            if self._issues_chk_outside.isChecked(): detectors.append("outside")
            if self._issues_chk_accel.isChecked():   detectors.append("accel")
            if self._issues_chk_gap.isChecked():     detectors.append("gap_jump")
            store[self._tracking_issues_state_key()] = {
                "threshold_cms":     float(self._issues_thresh.value()),
                "accel_thresh_cms2": float(self._issues_accel_thresh.value()),
                "auto":              bool(self._issues_chk_auto.isChecked()),
                "autofix_gap_frames": int(self._issues_max_gap.value()),
                "detectors":         detectors,
                "false_positives":   sorted(int(f) for f in self._issues_fp_set),
            }
            win = self.window()
            if hasattr(win, "_save_config"):
                win._save_config()
        except Exception as e:
            logger.warn(f"tracking_issues state save failed: {e}",
                        source="issues")

    def _active_detectors(self):
        from analysis.tracking_issues import SPEED, OUTSIDE, ACCEL, GAP_JUMP
        s = set()
        if self._issues_chk_speed.isChecked():   s.add(SPEED)
        if self._issues_chk_outside.isChecked(): s.add(OUTSIDE)
        if self._issues_chk_accel.isChecked():   s.add(ACCEL)
        if self._issues_chk_gap.isChecked():     s.add(GAP_JUMP)
        return s

    # ── Main-screen access: slider marks + popup ─────────────────────────
    def _refresh_issue_marks(self):
        """Red marks on the frame slider at every *active* issue, and the
        count on the Tracking issues button."""
        slider = getattr(self, "slider_scrub", None)
        btn = getattr(self, "btn_issues", None)
        df = getattr(self, "_issues_df", None)
        marks = []
        if df is not None and len(df) > 0:
            trim = self._trim_start_frame()
            active = df[df["Status"] == "active"]
            for _, r in active.iterrows():
                f = int(r["Frame"])
                tip = f"Frame {trim + f}  ·  {float(r['Time (s)']):.2f} s\n{r['Reasons']}"
                marks.append((trim + f, tip))
        if hasattr(slider, "set_marks"):
            slider.set_marks(marks)
        if btn is not None:
            n = len(marks)
            btn._text.setText(f"Tracking issues ({n})" if n else "Tracking issues")
            btn.updateGeometry()
            btn.setEnabled(df is not None)

    def _open_tracking_issues_popup(self):
        """Non-modal window with the full tracking-issues tool (table, mini
        map, big frame view with Detected area, corrections, detectors,
        false-positive marks, smoothing)."""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout
        if self._issues_popup is None:
            host = self.slider_scrub.window()
            dlg = QDialog(host)
            dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowMaximizeButtonHint)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(12, 10, 12, 12)
            lay.addWidget(self._issues_widget)
            # Minimum size comes from the layout, so parts can't overlap.
            # Big by default, but never larger than the screen.
            scr = host.screen() if hasattr(host, "screen") else None
            ag = scr.availableGeometry() if scr is not None else None
            wd, ht = 1280, 820
            if ag is not None:
                wd = min(wd, int(ag.width() * 0.92))
                ht = min(ht, int(ag.height() * 0.9))
            dlg.resize(wd, ht)
            dlg.finished.connect(lambda _r: self._issues_btn_fix.setChecked(False))
            self._issues_popup = dlg
            # Follow the main frame slider while the popup is open.
            self.slider_scrub.valueChanged.connect(self._schedule_issue_view)
        name = os.path.basename(self.video_path) if getattr(self, "video_path", None) else ""
        self._issues_popup.setWindowTitle(f"Tracking issues — {name}" if name else "Tracking issues")
        try:
            self._render_issues_mini_map()   # draw in the current theme
        except Exception as e:
            logger.warn(f"issues mini-map refresh failed: {e}", source="issues")
        self._refresh_corrections_buttons_issues()
        self._issues_popup.show()
        self._issues_popup.raise_()
        self._issues_popup.activateWindow()
        self._refresh_issue_view()

    def _schedule_issue_view(self, *_):
        dlg = getattr(self, "_issues_popup", None)
        if dlg is not None and dlg.isVisible():
            self._issues_view_timer.start()

    # ── Frame view ───────────────────────────────────────────────────────
    def _issue_current_rel_frame(self):
        try:
            return int(self.slider_scrub.value()) - int(self._trim_start_frame())
        except Exception:
            return None

    def _refresh_issue_view(self):
        """Draw the current frame in the popup: (processed) frame, optional
        detected area / mask, and the tracked point on top."""
        view = getattr(self, "_issues_view", None)
        if view is None:
            return
        frame = (self._current_scrub_frame_bgr
                 if getattr(self, "_current_scrub_frame_bgr", None) is not None
                 else getattr(self, "_first_frame_bgr", None))
        if frame is None:
            view.set_image(None, "(no video loaded)")
            self._issues_frame_lbl.setText("—")
            self._issues_state_lbl.setText("")
            return
        import cv2
        processed = getattr(self, "btn_view_processed", None)
        base = (self._get_processed_frame_bgr(frame)
                if processed is not None and processed.isChecked() else frame.copy())
        info = ""
        want_det = self._issues_sw_detect.isChecked()
        want_mask = self._issues_sw_mask.isChecked()
        if want_det or want_mask:
            mask = self._detection_mask(frame)
            if mask is None:
                info = "  ·  detected area: preview background still being built…"
            else:
                from tracking.preprocessor import make_overlay, make_mask_view
                if want_mask:
                    base = make_mask_view(mask)
                if want_det:
                    base = make_overlay(base, mask, self._bgr("detection"),
                                        self.overlay_alpha / 100.0)
                n_px = int(np.count_nonzero(mask))
                info = (f"  ·  detected {n_px:,} px at threshold "
                        f"{int(self.spin_threshold.value())}" if n_px
                        else "  ·  nothing detected with these settings")
        self._draw_tracked_point(base)
        if base.ndim == 2:
            base = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)
        rgb = np.ascontiguousarray(base[:, :, ::-1])
        h, wd = rgb.shape[:2]
        img = QImage(rgb.data, wd, h, 3 * wd, QImage.Format_RGB888).copy()
        view.set_image(QPixmap.fromImage(img))

        rel = self._issue_current_rel_frame()
        self._issues_video_frame_no = rel
        state = ""
        if rel is not None:
            if self._issues_df is not None and len(self._issues_df) > 0:
                hit = self._issues_df[self._issues_df["Frame"] == rel]
                if len(hit):
                    st = str(hit["Status"].iloc[0])
                    state = ("  ·  Flagged: " + str(hit["Reasons"].iloc[0])
                             if st == "active" else "  ·  flagged (false-positive)")
            res = self.tracking_results or []
            if res and 0 <= rel < len(res):
                r = res[rel]
                if r.get("corrected") and r.get("x") is None:
                    state += "  ·  point removed"
                elif r.get("corrected"):
                    state += "  ·  fixed by hand"
                elif r.get("interpolated"):
                    state += "  ·  interpolated"
                elif r.get("x") is None:
                    state += "  ·  missed"
        self._issues_frame_lbl.setText(f"Frame {rel}" if rel is not None else "—")
        note = getattr(self, "_issues_note", "")
        self._issues_state_lbl.setText(((f"  ·  {note}" if note else "") + state + info).lstrip(" ·"))
        self._refresh_corrections_buttons_issues()

    def _render_issue_video_frame(self, frame_no):
        """Back-compat: the view now always mirrors the current frame."""
        self._refresh_issue_view()

    def _on_issue_row_selected(self):
        """Single click on a row = ring on mini map + seek the video (the
        frame view follows the slider).

        Frame coord-space note: `raw_df["Frame"]` is trim-relative (starts
        at 0 even when trim_start > 0). The scrub slider is in absolute
        source-frame coords, so trim_start is added before seeking."""
        self._render_issues_mini_map()
        frame = self._selected_issue_frame()
        if frame is None or self._issues_df is None:
            return
        match = self._issues_df[self._issues_df["Frame"] == frame]
        if len(match) == 0:
            return
        try:
            r = int(match["_row"].iloc[0])
            xs = self.raw_df["X (px)"].values.astype(float)
            ys = self.raw_df["Y (px)"].values.astype(float)
            ax = self._issues_mini_fig.axes[0]
            ax.scatter([xs[r]], [ys[r]], s=80, facecolor="none",
                       edgecolor=theme.ACCENT, linewidths=2.0, zorder=5)
            self._issues_mini_canvas.draw_idle()
        except Exception as e:
            logger.warn(f"mini-map highlight failed: {e}", source="issues")
        self._seek_issue_rel(int(frame))

    def _seek_issue_rel(self, rel):
        try:
            src = self._trim_start_frame() + int(rel)
            src = max(self.slider_scrub.minimum(), min(self.slider_scrub.maximum(), src))
            if self.slider_scrub.value() != src:
                self.slider_scrub.setValue(src)   # → _on_scrub + view refresh
            else:
                self._on_scrub(src)
        except Exception as e:
            logger.warn(f"issue seek failed: {e}", source="issues")
        self._refresh_issue_view()

    def _step_issue_frame(self, delta):
        """Step the video by ±delta frames (frame view follows)."""
        self._issues_note = ""
        rel = self._issue_current_rel_frame()
        if rel is None:
            return
        self._seek_issue_rel(rel + int(delta))

    def _jump_issue(self, direction):
        """Go to the next / previous active flagged frame."""
        self._issues_note = ""
        df = self._issues_df
        rel = self._issue_current_rel_frame()
        if df is None or len(df) == 0 or rel is None:
            return
        frames = sorted(int(f) for f in df.loc[df["Status"] == "active", "Frame"])
        if not frames:
            return
        if direction > 0:
            nxt = next((f for f in frames if f > rel), frames[0])
        else:
            nxt = next((f for f in reversed(frames) if f < rel), frames[-1])
        # Select the matching row (also seeks), else seek directly.
        tbl = self._issues_table
        for row in range(tbl.rowCount()):
            it = tbl.item(row, 0)
            if it is not None and int(it.data(Qt.DisplayRole)) == nxt:
                tbl.selectRow(row)
                tbl.scrollToItem(it)
                return
        self._seek_issue_rel(nxt)

    # ── Corrections inside the popup ─────────────────────────────────────
    def _refresh_corrections_buttons_issues(self):
        has = bool(self.tracking_results)
        rel = self._issue_current_rel_frame()
        cur = None
        if has and rel is not None and 0 <= rel < len(self.tracking_results):
            cur = self.tracking_results[rel]
        any_fix = has and any(r.get("corrected") or r.get("interpolated")
                              for r in (self._raw_results or self.tracking_results))
        self._issues_btn_fix.setEnabled(has)
        self._issues_btn_remove.setEnabled(cur is not None and cur.get("x") is not None)
        self._issues_btn_undo.setEnabled(bool(cur) and bool(cur.get("corrected") or cur.get("interpolated")))
        self._issues_btn_interp.setEnabled(has)
        self._issues_btn_clear_all.setEnabled(bool(any_fix))
        n_active = 0
        if has and self._issues_df is not None and len(self._issues_df):
            n_active = int((self._issues_df["Status"] == "active").sum())
        self._issues_btn_auto.setEnabled(n_active > 0)
        self._issues_btn_auto_all.setEnabled(n_active > 0)
        runs = self._fixed_runs() if has else []
        for bt in (self._issues_btn_interp_prev, self._issues_btn_interp_go,
                   self._issues_btn_interp_next):
            bt.setEnabled(bool(runs))
        if not runs:
            self._issues_interp_pos.setText("none")
        else:
            k = next((k for k, (a, b) in enumerate(runs) if a <= (rel or 0) <= b), None)
            n_fr = sum(b - a + 1 for a, b in runs)
            self._issues_interp_pos.setText(
                f"{k + 1} of {len(runs)}" if k is not None
                else f"{len(runs)} place(s), {n_fr} frame(s)")
        if not has and self._issues_btn_fix.isChecked():
            self._issues_btn_fix.setChecked(False)

    def _on_max_gap_changed(self, _v=None, save=True):
        fps = float(self.fps or 30.0)
        self._issues_max_gap_s.setText(f"≈ {self._issues_max_gap.value() / fps:.2f} s")
        if save:
            self._save_tracking_issues_state()

    def _fixed_runs(self):
        """(start, end) result-index runs of interpolated / hand-fixed /
        removed frames."""
        runs, start = [], None
        res = self.tracking_results or []
        for i, r in enumerate(res):
            on = bool(r.get("interpolated") or r.get("corrected"))
            if on and start is None:
                start = i
            elif not on and start is not None:
                runs.append((start, i - 1))
                start = None
        if start is not None:
            runs.append((start, len(res) - 1))
        return runs

    def _goto_fixed(self, direction):
        """Jump to the previous / nearest / next run of fixed frames."""
        runs = self._fixed_runs()
        if not runs:
            self._issues_note = "No interpolated or fixed frames yet."
            self._refresh_issue_view()
            return
        rel = self._issue_current_rel_frame() or 0
        cur = next((k for k, (a, b) in enumerate(runs) if a <= rel <= b), None)
        if direction > 0:
            k = next((k for k, (a, _b) in enumerate(runs) if a > rel), 0)
        elif direction < 0:
            if cur is not None and runs[cur][0] < rel:
                k = cur                      # inside a run → its start first
            else:
                k = next((k for k in range(len(runs) - 1, -1, -1) if runs[k][1] < rel),
                         len(runs) - 1)
        else:
            k = min(range(len(runs)),
                    key=lambda j: 0 if runs[j][0] <= rel <= runs[j][1]
                    else min(abs(runs[j][0] - rel), abs(runs[j][1] - rel)))
        a, b = runs[k]
        self._issues_note = ""
        self._seek_issue_rel(a)
        span = f"frame {a}" if a == b else f"frames {a}–{b}"
        self._issues_interp_pos.setText(f"{k + 1} of {len(runs)}  ({span})")

    def _on_issue_fix_toggled(self, on):
        self._issues_view.set_pick(bool(on))

    def _on_issue_view_click(self, nx, ny):
        if not self._issues_btn_fix.isChecked() or not self.tracking_results:
            return
        self._on_correction_click(nx, ny)     # same as Frame corrections → Fix position
        self._refresh_issue_view()

    def _issue_remove_point(self):
        """Mark the shown frame as missed (wrong detection)."""
        if not self.tracking_results:
            return
        idx = self._slider_to_results_idx(self.slider_scrub.value())
        for r in self._result_rows(idx):
            if not r.get("corrected") and not r.get("interpolated"):
                r["orig_x"], r["orig_y"] = r.get("x"), r.get("y")
            r.pop("interpolated", None)
            r["x"] = None
            r["y"] = None
            r["corrected"] = True
        self.btn_clear_fixes.setEnabled(True)
        self._on_scrub(self.slider_scrub.value())
        self._corrections_changed()
        self._refresh_issue_view()

    # ── Auto-fix: remove the point, interpolate that frame, recalc, next ─
    def _active_issue_frames(self):
        df = self._issues_df
        if df is None or len(df) == 0:
            return []
        n = len(self.tracking_results or [])
        return sorted(int(f) for f in df.loc[df["Status"] == "active", "Frame"]
                      if 0 <= int(f) < n)

    def _interpolate_frames(self, idxs):
        """Replace the point of each frame in `idxs` with a straight-line
        estimate from the nearest good frames before / after it (frames
        being fixed and missed frames are skipped as anchors). The
        tracker's own point is kept so "Undo fix here" / "Clear all fixes"
        can bring it back. Returns how many frames were filled."""
        res = self.tracking_results
        n = len(res)
        todo = set(int(i) for i in idxs if 0 <= int(i) < n)

        def good(j):
            return j not in todo and res[j].get("x") is not None

        filled = 0
        for i in sorted(todo):
            a = next((j for j in range(i - 1, -1, -1) if good(j)), None)
            b = next((j for j in range(i + 1, n) if good(j)), None)
            if a is None and b is None:
                continue
            if a is None:
                x, y = res[b]["x"], res[b]["y"]
            elif b is None:
                x, y = res[a]["x"], res[a]["y"]
            else:
                t = (i - a) / float(b - a)
                x = res[a]["x"] + t * (res[b]["x"] - res[a]["x"])
                y = res[a]["y"] + t * (res[b]["y"] - res[a]["y"])
            for r in self._result_rows(i):
                if not r.get("corrected") and not r.get("interpolated"):
                    r["orig_x"], r["orig_y"] = r.get("x"), r.get("y")
                r.pop("corrected", None)
                r["x"], r["y"] = float(x), float(y)
                r["interpolated"] = True
            filled += 1
        return filled

    def _recalc_after_autofix(self):
        """Recalculate numbers, graphs and the issue list right away."""
        t = getattr(self, "_corrections_timer", None)
        if t is not None:
            t.stop()
        self.btn_clear_fixes.setEnabled(True)
        self._recompute_metrics_and_views()

    def _autofix_max_gap(self):
        """Longest run (frames) Auto-fix may replace."""
        fps = float(self.fps or 30.0)
        return max(1, int(self._issues_max_gap.value()))

    def _plan_autofix(self, only_frames=None):
        """Simulate Auto-fix on the current track (nothing is changed).
        Returns (xs, ys, runs, unresolved_frames, row_frames) with runs as
        raw_df row ranges, or None when there is no data."""
        from analysis.tracking_issues import plan_auto_fix
        df = self.raw_df
        if df is None or len(df) == 0 or not self.tracking_results:
            return None
        xs = df["X (px)"].values.astype(float)
        ys = df["Y (px)"].values.astype(float)
        frames = (df["Frame"].values.astype(int) if "Frame" in df.columns
                  else np.arange(len(df)))
        row_of = {int(f): i for i, f in enumerate(frames)}
        protect = {row_of[f] for f in self._issues_fp_set if f in row_of}
        only = None
        if only_frames is not None:
            only = {row_of[f] for f in only_frames if f in row_of}
        _, arena, _, px_per_cm = self._graph_data()
        nx, ny, runs, still = plan_auto_fix(
            xs, ys, float(self.fps or 30.0), px_per_cm, arena,
            speed_thresh_cms=float(self._issues_thresh.value()),
            accel_thresh_cms2=float(self._issues_accel_thresh.value()),
            auto_speed=bool(self._issues_chk_auto.isChecked()),
            detectors=self._active_detectors(),
            protect=protect, only=only, max_gap=self._autofix_max_gap())
        return nx, ny, runs, [int(frames[i]) for i in still], frames

    def _apply_autofix(self, nx, ny, runs):
        """Replay the planned runs on the results, in their own pixel
        coordinates (the raw table can be scaled differently; a straight
        line is the same line in both). The tracker's own point is kept
        for Undo / Clear all fixes. Returns the number of frames changed."""
        from analysis.tracking_issues import _interp_run
        res = self.tracking_results
        n = len(res)
        xs = np.array([np.nan if r.get("x") is None else r["x"] for r in res], float)
        ys = np.array([np.nan if r.get("y") is None else r["y"] for r in res], float)
        touched = set()
        for a, b in runs:
            if b >= n:
                continue
            out = _interp_run(xs, ys, a, b)
            if out is None:
                continue
            xs, ys = out
            touched.update(range(a, b + 1))
        for i in sorted(touched):
            for r in self._result_rows(i):
                if not r.get("corrected") and not r.get("interpolated"):
                    r["orig_x"], r["orig_y"] = r.get("x"), r.get("y")
                r.pop("corrected", None)
                r["x"], r["y"] = float(xs[i]), float(ys[i])
                r["interpolated"] = True
        return len(touched)

    @staticmethod
    def _runs_text(runs, frames, limit=4):
        from analysis.tracking_issues import _merge_runs
        runs = _merge_runs(runs)
        parts = []
        for a, b in runs[:limit]:
            fa, fb = int(frames[a]), int(frames[b])
            parts.append(f"{fa}" if fa == fb else f"{fa}–{fb}")
        more = f" +{len(runs) - limit} more" if len(runs) > limit else ""
        return ", ".join(parts) + more

    def _issue_auto_fix_next(self):
        """Fix the flagged frame shown (or the next one): search the frames
        around it for the real fault, replace the smallest run that clears
        it, recalculate, then go to the next flagged frame."""
        if not self.tracking_results:
            return
        frames_flagged = self._active_issue_frames()
        if not frames_flagged:
            self._issues_note = "No active flagged frames left."
            self._refresh_issue_view()
            return
        rel = self._issue_current_rel_frame()
        target = rel if rel in frames_flagged else next(
            (f for f in frames_flagged if f > (rel if rel is not None else -1)),
            frames_flagged[0])
        from PyQt5.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            plan = self._plan_autofix(only_frames={target})
            fixed = False
            if plan is not None and plan[2]:
                nx, ny, runs, _still, frames = plan
                self._apply_autofix(nx, ny, runs)
                self._recalc_after_autofix()
                fixed = True
        finally:
            QApplication.restoreOverrideCursor()
        left = self._active_issue_frames()
        if fixed:
            where = self._runs_text(runs, frames)
            self._issues_note = (f"Frame {target}: replaced frame(s) {where}"
                                 + (" — still flagged, check by hand" if target in left else ""))
        else:
            self._issues_note = (f"Frame {target}: no safe fix within "
                                 f"{self._autofix_max_gap()} frames — check by hand")
        later = [f for f in left if f > target]
        if later:
            self._jump_issue_to(later[0])
        else:
            self._seek_issue_rel(target)
        self._refresh_issue_view()

    def _issue_auto_fix_all(self):
        """Plan fixes for every active flagged frame, show what will change,
        and apply on confirmation."""
        if not self.tracking_results or not self._active_issue_frames():
            return
        from PyQt5.QtWidgets import QApplication
        n_before = len(self._active_issue_frames())
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            plan = self._plan_autofix()
        finally:
            QApplication.restoreOverrideCursor()
        if plan is None:
            return
        nx, ny, runs, still, frames = plan
        from analysis.tracking_issues import _merge_runs
        merged = _merge_runs(runs)
        if not runs:
            self._issues_note = (f"No safe fix found for the {n_before} flagged "
                                 f"frame(s) — check them by hand")
            self._refresh_issue_view()
            return
        n_frames = sum(b - a + 1 for a, b in merged)
        longest = max(b - a + 1 for a, b in merged)
        fps = float(self.fps or 30.0)
        total = len(self.tracking_results)
        msg = (f"Auto-fix will replace the tracked point on {n_frames} frame(s) "
               f"({100.0 * n_frames / max(1, total):.2f}% of the video) in "
               f"{len(merged)} place(s), using straight lines from the good "
               f"frames around them.\n\n"
               f"Longest replaced run: {longest} frame(s) ({longest / fps:.2f} s); "
               f"limit {self._autofix_max_gap()} frames.\n"
               f"Flagged now: {n_before}  →  still flagged after: {len(still)}"
               + (" (check these by hand)" if still else "") + ".\n\n"
               "False-positive frames are not touched. Undo fix here / Clear all "
               "fixes bring the original points back.\n\nApply?")
        box = QMessageBox(self._issues_popup or self)
        box.setWindowTitle("Auto-fix all")
        box.setIcon(QMessageBox.Question)
        box.setText(msg)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Yes)
        if box.exec_() != QMessageBox.Yes:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            changed = self._apply_autofix(nx, ny, runs)
            self._recalc_after_autofix()
        finally:
            QApplication.restoreOverrideCursor()
        left = self._active_issue_frames()
        self._issues_note = (f"Auto-fixed {changed} frame(s) in {len(merged)} place(s)"
                             f" · {len(left)} still flagged")
        if left:
            self._jump_issue_to(left[0])
        self._refresh_issue_view()

    def _jump_issue_to(self, frame):
        tbl = self._issues_table
        for row in range(tbl.rowCount()):
            it = tbl.item(row, 0)
            if it is not None and int(it.data(Qt.DisplayRole)) == int(frame):
                tbl.selectRow(row)
                tbl.scrollToItem(it)
                return
        self._seek_issue_rel(frame)

    def _issue_undo_fix(self):
        """Put back the tracker's own point on the shown frame."""
        if not self.tracking_results:
            return
        idx = self._slider_to_results_idx(self.slider_scrub.value())
        for r in self._result_rows(idx):
            if r.pop("corrected", None) or r.pop("interpolated", None):
                r["x"] = r.pop("orig_x", None)
                r["y"] = r.pop("orig_y", None)
            r.pop("interpolated", None)
        if self._raw_results:
            self.tracking_results = self._apply_smoothing(
                self._raw_results, self.spin_smooth.value())
        self._refresh_correction_buttons()
        self._on_scrub(self.slider_scrub.value())
        self._corrections_changed()
        self._refresh_issue_view()

    def _populate_tracking_issues_tab(self):
        """Called from _recompute_metrics_and_views after each tracking run.
        Loads persisted state for this video, then runs detection."""
        self._load_tracking_issues_state()
        self._recompute_tracking_issues(save_state=False)

    def _recompute_tracking_issues(self, *, save_state=True):
        from analysis.tracking_issues import detect_issues
        if self.raw_df is None or len(self.raw_df) == 0:
            self._issues_df = None
            self._issues_table.setRowCount(0)
            self._issues_stats_lbl.setText("Run tracking first to see flagged frames.")
            self._render_issues_mini_map()
            self._refresh_issue_marks()
            return
        _, arena, _, px_per_cm = self._graph_data()
        issues = detect_issues(
            self.raw_df,
            fps=float(self.fps or 30.0),
            px_per_cm=px_per_cm,
            arena=arena,
            speed_thresh_cms=float(self._issues_thresh.value()),
            accel_thresh_cms2=float(self._issues_accel_thresh.value()),
            detectors=self._active_detectors(),
            auto_speed=bool(self._issues_chk_auto.isChecked()),
        )
        # Restore user marks: any frame in fp_set → "false_positive".
        if len(issues) > 0 and self._issues_fp_set:
            issues.loc[issues["Frame"].isin(self._issues_fp_set), "Status"] = "false_positive"
        self._issues_df = issues
        self._fill_issues_table(issues)
        self._refresh_issues_stats(issues)
        self._render_issues_mini_map()
        self._refresh_issue_marks()
        if save_state:
            self._save_tracking_issues_state()

    def _fill_issues_table(self, issues):
        """Populate the QTableWidget with one row per flagged frame."""
        tbl = self._issues_table
        tbl.setSortingEnabled(False)
        # Determine speed + accel column names dynamically (cm/s or px/s).
        speed_col = next((c for c in issues.columns
                          if c.startswith("Speed (") and "/s" in c
                          and "²" not in c), None) or "Speed (cm/s)"
        accel_col = next((c for c in issues.columns
                          if c.startswith("Accel (") and "²" in c),
                         None) or "Accel (cm/s²)"
        visible_cols = ["Frame", "Time (s)", speed_col, accel_col,
                        "Reasons", "Severity", "Status"]
        tbl.clear()
        tbl.setColumnCount(len(visible_cols))
        tbl.setHorizontalHeaderLabels(visible_cols)
        tbl.setRowCount(len(issues))
        for r, (_, row) in enumerate(issues.iterrows()):
            for c, col in enumerate(visible_cols):
                val = row.get(col, "")
                item = QTableWidgetItem()
                if isinstance(val, (float, np.floating)):
                    # Compact numbers: 2 decimals for time / severity,
                    # 1 for speed, none for acceleration.
                    dec = 2 if col in ("Time (s)", "Severity") else (0 if col == accel_col else 1)
                    v = float(val)
                    item.setData(Qt.DisplayRole, round(v, dec) if np.isfinite(v) else v)
                elif isinstance(val, (int, np.integer)):
                    item.setData(Qt.DisplayRole, int(val))
                else:
                    item.setText(str(val))
                # Severity → tinted cell (error / warning / neutral)
                if col == "Severity":
                    sev = float(row.get("Severity", 0.0))
                    if sev >= 0.75:
                        item.setBackground(QColor(theme.ERR_BG))
                        item.setForeground(QColor(theme.ERR))
                    elif sev >= 0.4:
                        item.setBackground(QColor(theme.WARN_BG))
                        item.setForeground(QColor(theme.WARN))
                    else:
                        item.setBackground(QColor(theme.SURFACE_2))
                        item.setForeground(QColor(theme.TEXT_2))
                if col == "Status" and str(val) == "false_positive":
                    item.setForeground(QColor(theme.FAINT))
                elif col == "Status":
                    item.setForeground(QColor(theme.TEXT_2))
                if col in ("Frame", "Time (s)", speed_col, accel_col, "Severity"):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                # Stash the underlying raw_df row index in user data.
                if c == 0:
                    item.setData(Qt.UserRole, int(row.get("_row", -1)))
                tbl.setItem(r, c, item)
        tbl.resizeColumnsToContents()
        tbl.setSortingEnabled(True)

    def _refresh_issues_stats(self, issues):
        if self.raw_df is None or len(self.raw_df) == 0:
            self._issues_stats_lbl.setText("")
            return
        total = len(self.raw_df)
        flagged = int(len(issues))
        active = int((issues["Status"] == "active").sum()) if flagged else 0
        pct = 100.0 * active / max(1, total)
        peak_txt = ""
        speed_col = next((c for c in issues.columns
                          if c.startswith("Speed (") and "/s" in c), None)
        if flagged and speed_col:
            try:
                peak_row = issues.loc[issues[speed_col].idxmax()]
                peak_txt = (f"  |  Peak: {float(peak_row[speed_col]):.1f} "
                            f"{speed_col.split('(')[-1].rstrip(')')} "
                            f"@ frame {int(peak_row['Frame'])}")
            except Exception as e:
                logger.warn(f"issues peak compute failed: {e}", source="issues")
        thr = float(self._issues_thresh.value())
        acc = float(self._issues_accel_thresh.value())
        auto = " (auto)" if self._issues_chk_auto.isChecked() else ""
        self._issues_stats_lbl.setText(
            f"· {active} active / {flagged} flagged of {total} frames ({pct:.2f}%)  ·  "
            f"speed {thr:.0f} cm/s{auto}  ·  accel {acc:.0f} cm/s²{peak_txt.replace('  |  ', '  ·  ')}"
        )

    def _render_issues_mini_map(self):
        """Draw trajectory + red dots at flagged frames in the mini canvas."""
        self._issues_mini_fig.clear()
        self._issues_mini_fig.set_facecolor(theme.SURFACE)
        ax = self._issues_mini_fig.add_subplot(111)
        ax.set_facecolor(theme.SURFACE)
        if self.raw_df is None or len(self.raw_df) == 0:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                    transform=ax.transAxes, color=theme.FAINT)
            ax.set_xticks([]); ax.set_yticks([])
            self._issues_mini_canvas.draw_idle()
            return
        xs = self.raw_df["X (px)"].values.astype(float)
        ys = self.raw_df["Y (px)"].values.astype(float)
        ax.plot(xs, ys, color=theme.FAINT, linewidth=0.7, alpha=0.8, zorder=1)
        # Active vs FP markers.
        if self._issues_df is not None and len(self._issues_df) > 0:
            active = self._issues_df[self._issues_df["Status"] == "active"]
            fp = self._issues_df[self._issues_df["Status"] == "false_positive"]
            if len(active) > 0:
                ax.scatter(xs[active["_row"].values],
                           ys[active["_row"].values],
                           s=12, c=theme.ERR, edgecolors=theme.SURFACE,
                           linewidths=0.4, zorder=3, label="Active")
            if len(fp) > 0:
                ax.scatter(xs[fp["_row"].values],
                           ys[fp["_row"].values],
                           s=10, c=theme.BORDER_2, edgecolors=theme.SURFACE,
                           linewidths=0.3, zorder=2, label="FP")
        # Arena outline if available.
        try:
            _, arena, _, _ = self._graph_data()
            if arena and len(arena) >= 3:
                from matplotlib.patches import Polygon as MplPolygon
                ax.add_patch(MplPolygon(arena, closed=True, fill=False,
                                         edgecolor=theme.TEXT_2, linewidth=1.0,
                                         zorder=2))
        except Exception as e:
            logger.warn(f"mini-map arena draw failed: {e}", source="issues")
        ax.set_aspect("equal", adjustable="box")
        ax.invert_yaxis()
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color(theme.BORDER_2)
        self._issues_mini_fig.subplots_adjust(left=0.03, right=0.97, bottom=0.03, top=0.97)
        self._issues_mini_canvas.draw_idle()

    def _selected_issue_frame(self):
        """Source-video frame # of the currently-selected table row, or None."""
        tbl = self._issues_table
        rows = tbl.selectionModel().selectedRows() if tbl.selectionModel() else []
        if not rows:
            return None
        r = rows[0].row()
        item = tbl.item(r, 0)
        if item is None:
            return None
        try:
            return int(item.data(Qt.DisplayRole))
        except (TypeError, ValueError):
            try:
                return int(item.text())
            except Exception:
                return None

    def _set_issue_status(self, status):
        """Toggle Status (active ↔ false_positive) for the selected row."""
        frame = self._selected_issue_frame()
        if frame is None or self._issues_df is None:
            return
        mask = self._issues_df["Frame"] == frame
        if not mask.any():
            return
        self._issues_df.loc[mask, "Status"] = status
        if status == "false_positive":
            self._issues_fp_set.add(int(frame))
        else:
            self._issues_fp_set.discard(int(frame))
        self._fill_issues_table(self._issues_df)
        self._refresh_issues_stats(self._issues_df)
        self._refresh_issue_marks()
        self._render_issues_mini_map()
        self._save_tracking_issues_state()

    def _smooth_flagged_frames(self):
        """Linear-interp active flagged frames into X_clean/Y_clean cols on
        raw_df. Original X/Y untouched."""
        if self.raw_df is None or self._issues_df is None or len(self._issues_df) == 0:
            QMessageBox.information(self, "Smooth flagged",
                                    "No flagged frames to smooth.")
            return
        from analysis.tracking_issues import smooth_flagged
        active = int((self._issues_df["Status"] == "active").sum())
        if active == 0:
            QMessageBox.information(self, "Smooth flagged",
                                    "All flagged frames are marked false-positive.")
            return
        self.raw_df = smooth_flagged(self.raw_df, self._issues_df)
        # Refresh Raw Data table so the new columns appear.
        try:
            self._populate_excel_tab()
        except Exception as e:
            logger.warn(f"_populate_excel_tab post-smooth failed: {e}",
                        source="ui")
        QMessageBox.information(
            self, "Smooth flagged",
            f"Interpolated {active} frame(s) into X_clean / Y_clean columns. "
            f"Original X/Y values are unchanged."
        )

    def _export_issues_csv(self):
        if self._issues_df is None or len(self._issues_df) == 0:
            QMessageBox.information(self, "Export CSV",
                                    "Nothing to export — no flagged frames.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export tracking issues",
            "tracking_issues.csv",
            "CSV files (*.csv);;All files (*)",
        )
        if not path:
            return
        try:
            export = self._issues_df.drop(columns=["_row"], errors="ignore")
            export.to_csv(path, index=False)
            from gui.notify import show_done
            show_done(self._issues_popup or self, "Tracking issues exported",
                      f"{len(export)} flagged frame(s).", path=path)
        except Exception as e:
            from gui.notify import show_done
            show_done(self._issues_popup or self, "CSV export failed", str(e), kind="err")
