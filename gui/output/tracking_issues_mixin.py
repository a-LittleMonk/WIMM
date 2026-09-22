"""IssuesMixin — Tracking Issues tab (glitch detector + table + mini-map
+ inline frame preview + status / smoothing / CSV actions).

Mixed into ExperimentTab. Owns the entire "Tracking Issues" tab UI plus
its persistence per-video (threshold, accel threshold, detector toggles,
false-positive marks) inside the host's `config["tracking_issues"]`.

Reuses host attrs / methods:
    self.config, self.video_path, self.raw_df, self.fps, self.metrics,
    self.zone_drawer, self.slider_scrub, self._graph_data,
    self._trim_start_frame, self._on_scrub, self._open_corrections_popup,
    self._populate_excel_tab.
"""
import numpy as np

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QCheckBox, QDoubleSpinBox,
    QFileDialog, QMessageBox,
)

from core import logger


class IssuesMixin:
    def _build_tracking_issues_tab(self):
        """Glitch finder UI: threshold + detector toggles + table + mini
        trajectory map + action buttons. Populated in
        `_populate_tracking_issues_tab` after each tracking run."""
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        import matplotlib.pyplot as plt

        w = QWidget()
        vlay = QVBoxLayout(w)
        vlay.setContentsMargins(6, 6, 6, 6)
        vlay.setSpacing(6)

        # Row 1: thresholds. Speed (with Auto) + Accel.
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.addWidget(QLabel("Speed:"))
        self._issues_thresh = QDoubleSpinBox()
        self._issues_thresh.setRange(5.0, 1000.0)
        self._issues_thresh.setSuffix(" cm/s")
        self._issues_thresh.setDecimals(1)
        self._issues_thresh.setSingleStep(10.0)
        self._issues_thresh.setValue(120.0)
        self._issues_thresh.setFixedWidth(120)
        row1.addWidget(self._issues_thresh)
        self._issues_chk_auto = QCheckBox("Auto")
        self._issues_chk_auto.setToolTip(
            "Self-calibrate to max(threshold, 2.5 × p99.9 of session speed)."
        )
        self._issues_chk_auto.setChecked(True)
        row1.addWidget(self._issues_chk_auto)
        row1.addSpacing(16)
        row1.addWidget(QLabel("Accel:"))
        self._issues_accel_thresh = QDoubleSpinBox()
        self._issues_accel_thresh.setRange(50.0, 5000.0)
        self._issues_accel_thresh.setSuffix(" cm/s²")
        self._issues_accel_thresh.setDecimals(0)
        self._issues_accel_thresh.setSingleStep(50.0)
        self._issues_accel_thresh.setValue(500.0)
        self._issues_accel_thresh.setFixedWidth(130)
        self._issues_accel_thresh.setToolTip(
            "Flag frames where |Δspeed| × fps exceeds this. Mice can hit "
            "~300 cm/s² in a real burst; >500 is usually a tracker artifact."
        )
        row1.addWidget(self._issues_accel_thresh)
        row1.addStretch()
        vlay.addLayout(row1)

        # Row 2: detector toggles + Recompute.
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(QLabel("Detectors:"))
        self._issues_chk_speed   = QCheckBox("Speed")
        self._issues_chk_outside = QCheckBox("Outside arena")
        self._issues_chk_accel   = QCheckBox("Accel")
        self._issues_chk_gap     = QCheckBox("Gap+jump")
        for cb in (self._issues_chk_speed, self._issues_chk_outside,
                   self._issues_chk_accel, self._issues_chk_gap):
            cb.setChecked(True)
            row2.addWidget(cb)
        row2.addStretch()
        self._issues_btn_recompute = QPushButton("Recompute")
        self._issues_btn_recompute.setFixedHeight(24)
        self._issues_btn_recompute.clicked.connect(
            lambda: self._recompute_tracking_issues(save_state=True)
        )
        row2.addWidget(self._issues_btn_recompute)
        vlay.addLayout(row2)

        # Row 2: stats summary.
        self._issues_stats_lbl = QLabel(
            "Run tracking first to see flagged frames."
        )
        self._issues_stats_lbl.setStyleSheet("color:#666; font-size:11px;")
        vlay.addWidget(self._issues_stats_lbl)

        # Middle: table | mini map.
        middle = QSplitter(Qt.Horizontal)
        middle.setChildrenCollapsible(False)

        self._issues_table = QTableWidget()
        self._issues_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._issues_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._issues_table.setSelectionMode(QTableWidget.SingleSelection)
        self._issues_table.setSortingEnabled(True)
        # Single click on a row = highlight on mini map + seek video.
        self._issues_table.itemSelectionChanged.connect(
            self._on_issue_row_selected
        )
        middle.addWidget(self._issues_table)

        # Right column = mini map (top) + video preview (bottom). Vertical
        # splitter so the user can rebalance.
        right_split = QSplitter(Qt.Vertical)
        right_split.setChildrenCollapsible(False)
        self._issues_mini_fig = plt.figure(figsize=(3, 3))
        self._issues_mini_canvas = FigureCanvasQTAgg(self._issues_mini_fig)
        self._issues_mini_canvas.setMinimumWidth(220)
        right_split.addWidget(self._issues_mini_canvas)

        self._issues_video_lbl = QLabel(
            "Click a row to preview the frame here."
        )
        self._issues_video_lbl.setAlignment(Qt.AlignCenter)
        self._issues_video_lbl.setWordWrap(True)
        self._issues_video_lbl.setMinimumHeight(160)
        self._issues_video_lbl.setStyleSheet(
            "background:#1A1A1A; color:#888; padding:8px; border-radius:3px;"
        )
        self._issues_video_frame_no = None  # for redraws on resize

        # Wrap preview + a prev/next frame strip so user can compare with
        # neighbouring frames without leaving the tab.
        video_wrap = QWidget()
        video_lay = QVBoxLayout(video_wrap)
        video_lay.setContentsMargins(0, 0, 0, 0)
        video_lay.setSpacing(3)
        video_lay.addWidget(self._issues_video_lbl, 1)

        nav_row = QHBoxLayout()
        nav_row.setContentsMargins(0, 0, 0, 0)
        nav_row.setSpacing(4)
        self._issues_btn_prev = QPushButton("◀")
        self._issues_btn_prev.setFixedWidth(40)
        self._issues_btn_prev.setToolTip("Previous frame")
        self._issues_btn_prev.clicked.connect(lambda: self._step_issue_frame(-1))
        nav_row.addWidget(self._issues_btn_prev)
        self._issues_frame_lbl = QLabel("—")
        self._issues_frame_lbl.setAlignment(Qt.AlignCenter)
        self._issues_frame_lbl.setStyleSheet("color:#888; font-size:10px;")
        nav_row.addWidget(self._issues_frame_lbl, 1)
        self._issues_btn_next = QPushButton("▶")
        self._issues_btn_next.setFixedWidth(40)
        self._issues_btn_next.setToolTip("Next frame")
        self._issues_btn_next.clicked.connect(lambda: self._step_issue_frame(+1))
        nav_row.addWidget(self._issues_btn_next)
        video_lay.addLayout(nav_row)

        right_split.addWidget(video_wrap)
        right_split.setSizes([260, 240])
        middle.addWidget(right_split)
        middle.setSizes([520, 280])

        vlay.addWidget(middle, 1)

        # Action buttons. (Seek happens automatically on row selection.)
        act = QHBoxLayout()
        self._issues_btn_fp = QPushButton("✓ Mark false-positive")
        self._issues_btn_fp.setToolTip(
            "Dismiss the selected glitch. Will be excluded from smoothing + "
            "remembered next time this video is opened."
        )
        self._issues_btn_fp.clicked.connect(
            lambda: self._set_issue_status("false_positive")
        )
        act.addWidget(self._issues_btn_fp)
        self._issues_btn_unmark = QPushButton("Unmark")
        self._issues_btn_unmark.clicked.connect(
            lambda: self._set_issue_status("active")
        )
        act.addWidget(self._issues_btn_unmark)
        act.addSpacing(12)
        self._issues_btn_smooth = QPushButton("~ Smooth flagged")
        self._issues_btn_smooth.setToolTip(
            "Linear-interp active flagged frames into X_clean / Y_clean "
            "columns. Original X/Y untouched."
        )
        self._issues_btn_smooth.clicked.connect(self._smooth_flagged_frames)
        act.addWidget(self._issues_btn_smooth)
        self._issues_btn_csv = QPushButton("Export CSV")
        self._issues_btn_csv.clicked.connect(self._export_issues_csv)
        act.addWidget(self._issues_btn_csv)
        self._issues_btn_corrections = QPushButton("Open Corrections")
        self._issues_btn_corrections.clicked.connect(self._open_corrections_popup)
        act.addWidget(self._issues_btn_corrections)
        act.addStretch()
        vlay.addLayout(act)

        # Internal state.
        self._issues_df = None
        self._issues_fp_set = set()   # frame numbers user marked false-positive
        return w

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
                if isinstance(val, float):
                    item.setData(Qt.DisplayRole, float(val))
                elif isinstance(val, (int, np.integer)):
                    item.setData(Qt.DisplayRole, int(val))
                else:
                    item.setText(str(val))
                # Severity → color dot via bg gradient on row.
                if col == "Severity":
                    sev = float(row.get("Severity", 0.0))
                    if sev >= 0.75:
                        item.setBackground(QColor("#FF6464"))    # red
                    elif sev >= 0.4:
                        item.setBackground(QColor("#FFB347"))    # orange
                    else:
                        item.setBackground(QColor("#FFE066"))    # yellow
                if col == "Status" and str(val) == "false_positive":
                    item.setForeground(QColor("#888888"))
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
            f"Flagged: {active} active / {flagged} total / {total} frames "
            f"({pct:.2f}%)   Speed: {thr:.0f} cm/s{auto}   "
            f"Accel: {acc:.0f} cm/s²{peak_txt}"
        )

    def _render_issues_mini_map(self):
        """Draw trajectory + red dots at flagged frames in the mini canvas."""
        self._issues_mini_fig.clear()
        ax = self._issues_mini_fig.add_subplot(111)
        if self.raw_df is None or len(self.raw_df) == 0:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                    transform=ax.transAxes, color="#888")
            ax.set_xticks([]); ax.set_yticks([])
            self._issues_mini_canvas.draw_idle()
            return
        xs = self.raw_df["X (px)"].values.astype(float)
        ys = self.raw_df["Y (px)"].values.astype(float)
        ax.plot(xs, ys, color="#777777", linewidth=0.7, alpha=0.6, zorder=1)
        # Active vs FP markers.
        if self._issues_df is not None and len(self._issues_df) > 0:
            active = self._issues_df[self._issues_df["Status"] == "active"]
            fp = self._issues_df[self._issues_df["Status"] == "false_positive"]
            if len(active) > 0:
                ax.scatter(xs[active["_row"].values],
                           ys[active["_row"].values],
                           s=12, c="#FF4444", edgecolors="white",
                           linewidths=0.4, zorder=3, label="Active")
            if len(fp) > 0:
                ax.scatter(xs[fp["_row"].values],
                           ys[fp["_row"].values],
                           s=10, c="#BBBBBB", edgecolors="white",
                           linewidths=0.3, zorder=2, label="FP")
        # Arena outline if available.
        try:
            _, arena, _, _ = self._graph_data()
            if arena and len(arena) >= 3:
                from matplotlib.patches import Polygon as MplPolygon
                ax.add_patch(MplPolygon(arena, closed=True, fill=False,
                                         edgecolor="#444444", linewidth=1.0,
                                         zorder=2))
        except Exception as e:
            logger.warn(f"mini-map arena draw failed: {e}", source="issues")
        ax.set_aspect("equal", adjustable="box")
        ax.invert_yaxis()
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color("#BBBBBB")
        self._issues_mini_fig.tight_layout()
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

    def _on_issue_row_selected(self):
        """Single click on a row = ring on mini map + seek video + paint
        inline preview. Everything happens in one click; no buttons needed.

        Frame coord-space note: `raw_df["Frame"]` is trim-relative (starts
        at 0 even when trim_start > 0). The scrub slider is in absolute
        source-frame coords. We have to add trim_start before seeking, or
        the video shows a different frame than the tracker dot belongs to."""
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
                       edgecolor="#FFD700", linewidths=2.0, zorder=5)
            self._issues_mini_canvas.draw_idle()
        except Exception as e:
            logger.warn(f"mini-map highlight failed: {e}", source="issues")
        # Seek: trim-relative frame → absolute source frame.
        try:
            src_frame = self._trim_start_frame() + int(frame)
            self.slider_scrub.setValue(src_frame)
            self._on_scrub(src_frame)
        except Exception as e:
            logger.warn(f"row-select seek failed: {e}", source="issues")
        # X/Y lookup still keys on the trim-relative value (matches raw_df).
        self._render_issue_video_frame(int(frame))

    def _render_issue_video_frame(self, frame_no):
        """Mirror the main video display into the inline preview by grabbing
        zone_drawer's `_base_pixmap` directly. That pixmap already contains
        the tracker's body dot drawn by `_render_current_frame`, so there
        is exactly zero risk of coord-space drift between the two views —
        they show the SAME bytes.

        We don't redraw anything: the body dot already tells the story —
        it sits at the raw_df X/Y. Compare that dot to where the mouse
        actually is in the same image:
            • Body dot ON the mouse  → tracker fine here, real burst → mark FP.
            • Body dot OFF the mouse → genuine glitch."""
        base_pix = getattr(self.zone_drawer, "_base_pixmap", None)
        if base_pix is None or base_pix.isNull():
            self._issues_video_lbl.setText("(no video loaded)")
            self._issues_video_lbl.setPixmap(QPixmap())
            return
        pix = base_pix
        target = self._issues_video_lbl.size()
        if target.width() > 1 and target.height() > 1:
            pix = pix.scaled(target, Qt.KeepAspectRatio,
                             Qt.SmoothTransformation)
        self._issues_video_lbl.setPixmap(pix)
        self._issues_video_frame_no = int(frame_no)
        # Label below the prev/next buttons — show trim-relative frame +
        # whether this exact frame is in the flagged list.
        flagged = False
        if self._issues_df is not None and len(self._issues_df) > 0:
            flagged = bool((self._issues_df["Frame"] == int(frame_no)).any())
        marker = "  ⚠ flagged" if flagged else ""
        try:
            self._issues_frame_lbl.setText(f"frame {int(frame_no)}{marker}")
        except Exception:
            # Label widget may have been torn down on tab swap.
            pass

    def _step_issue_frame(self, delta):
        """Step the video by ±1 (or ±N) frame. Mirrors the slider, refreshes
        the inline preview, and notes whether the new frame is itself in
        the flagged list — quick context check for neighbouring frames."""
        if self._issues_video_frame_no is None:
            return
        trim_offset = self._trim_start_frame()
        cur_src = trim_offset + int(self._issues_video_frame_no)
        new_src = cur_src + int(delta)
        # Clamp to slider's valid range.
        new_src = max(self.slider_scrub.minimum(),
                      min(self.slider_scrub.maximum(), new_src))
        if new_src == cur_src:
            return
        try:
            self.slider_scrub.setValue(new_src)
            self._on_scrub(new_src)
        except Exception as e:
            logger.warn(f"step_issue_frame seek failed: {e}", source="issues")
            return
        self._render_issue_video_frame(new_src - trim_offset)

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
            QMessageBox.information(self, "Export CSV",
                                    f"Saved {len(export)} row(s) to:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Export CSV", f"Failed: {e}")
