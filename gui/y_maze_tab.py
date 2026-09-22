"""Y-Maze tab: thin subclass of OpenFieldTab that swaps the experiment
plugin to YMazeExperiment. The plugin handles the geometry pane, results
tab additions, and metric computation so this class stays small.

YMazeBatchTab is the equivalent thin subclass of ExperimentBatchTab
(via OpenFieldBatchTab — same generic shell, different embedded tab)."""
from gui.open_field_tab import OpenFieldTab
from gui.experiment_batch_tab import ExperimentBatchTab
from experiments.y_maze import YMazeExperiment


class YMazeTab(OpenFieldTab):
    def __init__(self, config):
        super().__init__(config, experiment=YMazeExperiment())
        # Add Y-Maze results tab (arms / alternation %). Insert right
        # after Summary (index 1) so the user lands on it after the
        # at-a-glance Summary view.
        try:
            tab = self.experiment.build_results_tabs(self, self._excel_tabs)
            if tab is not None and hasattr(self, "_excel_tabs"):
                self._excel_tabs.insertTab(1, tab, "Y-Maze")
        except Exception:
            pass
        # Live per-zone tracking state — arms + the neutral hub. Updated
        # frame-by-frame in _on_tracking_body_pos and consumed by
        # paint_ym_overlay for the live fill + per-zone count/time.
        # The pending/confirmed split mirrors the post-tracking debounce
        # in ym_metrics — same min_dwell_s threshold from the Y-maze UI,
        # so the live counts match what gets written to Excel.
        from experiments.y_maze.zones import ARM_NAMES as _AN
        _ZONES = list(_AN) + ["neutral_zone"]
        self._ym_current_arm = None
        self._ym_last_committed_arm = None
        self._ym_arm_entries = {n: 0 for n in _ZONES}
        self._ym_arm_times = {n: 0.0 for n in _ZONES}
        self._ym_pending_arm = None
        self._ym_pending_frames = 0
        # Register the Y-Maze overlay renderer with the shared zone drawer
        # so the live highlight + stats paint over the schema-zone outlines.
        from experiments.y_maze.ym_overlay import paint_ym_overlay
        zd = self.zone_drawer
        zd.set_overlay_renderer(
            lambda p, ox, oy, dw, dh: paint_ym_overlay(self, zd, p, ox, oy, dw, dh)
        )
        # Step 3 (Scale step) — replace the OF cage W × H widget with a
        # Y-maze "Arm length (cm)" spinbox. Plugin's compute_auto_px_per_cm
        # reads it + live hub/endpoints and returns px/cm from spoke length.
        if hasattr(self, "_cage_size_widget"):
            self._install_ym_arm_length_widget()
            if hasattr(self, "_refresh_calib_mode_visibility"):
                self._refresh_calib_mode_visibility()

    def _install_ym_arm_length_widget(self):
        """Inject the 'Arm length (cm)' spinbox into the Scale step's
        auto-calibration panel, in the same parent layout where the OF
        cage-size widget sits."""
        from PyQt5.QtWidgets import (
            QWidget, QHBoxLayout, QLabel, QDoubleSpinBox,
        )
        parent = self._cage_size_widget.parentWidget()
        layout = parent.layout() if parent else None
        if layout is None:
            return
        widget = QWidget()
        h = QHBoxLayout(widget)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addWidget(QLabel("Arm length:"))
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 9999.0)
        spin.setDecimals(1)
        spin.setSingleStep(1.0)
        spin.setSuffix(" cm")
        spin.setFixedWidth(95)
        spin.setFixedHeight(24)
        spin.setValue(float(self.config.get("ym_arm_length_cm", 30.0)))
        spin.setToolTip(
            "Physical hub-to-tip distance of one arm in cm. Auto-"
            "calibration uses pixel spoke length ÷ this value = px/cm."
        )

        def _on_change(v):
            self.config["ym_arm_length_cm"] = float(v)
            win = self.window()
            if hasattr(win, "_save_config"):
                try:
                    win._save_config()
                except Exception:
                    pass
            # Live: refresh auto-cal px/cm label.
            if hasattr(self, "_update_calib_status"):
                try:
                    self._update_calib_status()
                except Exception:
                    pass
            # Live: refresh Move-threshold suffix (cm/s ↔ px/s).
            if hasattr(self, "_refresh_move_threshold_suffix"):
                try:
                    self._refresh_move_threshold_suffix()
                except Exception:
                    pass
            # If tracking has already run, recompute distance/speed metrics
            # against the new scale so the Output tabs update too.
            if getattr(self, "tracking_results", None):
                try:
                    self._recompute_metrics_and_views()
                except Exception:
                    pass
        spin.valueChanged.connect(_on_change)
        h.addWidget(spin)
        h.addStretch()
        self.spin_ym_arm_length_cm = spin
        self._ym_arm_length_widget = widget
        # Drop it where the cage-size widget sat so it slots into the
        # same auto-cal sub-panel position.
        idx = layout.indexOf(self._cage_size_widget)
        if idx >= 0:
            layout.insertWidget(idx, widget)
        else:
            layout.addWidget(widget)

    def _on_tracking_body_pos(self, body_xy):
        """Per-frame body position from the tracker. Determines which arm
        contains the point and accumulates entries + time. Overrides the
        OF cell-tracking base implementation."""
        # Live overlay defaults OFF for speed — same contract as OF.
        # Skip per-frame arm math + zd.update() during the run; data is
        # recomputed on scrub from tracking_results once tracking ends.
        if self._tracking_active and not self._live_cell_overlay:
            return
        zd = self.zone_drawer
        if body_xy is None or not (self.video_w and self.video_h):
            zd.set_body_pos_norm(None)
            self._ym_current_arm = None
            zd.update()
            return
        x_px, y_px = body_xy
        nx, ny = x_px / float(self.video_w), y_px / float(self.video_h)
        zd.set_body_pos_norm((nx, ny))
        from experiments.y_maze.ym_overlay import point_to_arm
        arm = point_to_arm(zd, nx, ny)  # arm_a/b/c, "neutral_zone", or None
        fps = self.fps or 30.0
        dt = 1.0 / fps
        # Min-dwell debounce — body must stay in a zone for this many
        # seconds before the visit counts. 0 = no debounce.
        min_dwell = float(self.spin_min_dwell.value())
        min_frames = max(1, int(round(min_dwell * fps))) if min_dwell > 0 else 1
        # Track how long the body has been in the current pending zone.
        if arm == self._ym_pending_arm:
            self._ym_pending_frames += 1
        else:
            self._ym_pending_arm = arm
            self._ym_pending_frames = 1
        if self._ym_pending_frames < min_frames:
            zd.update()
            return  # not yet confirmed — no entry, no time, no fill change
        # Confirmed. Treat the moment of confirmation as "we just arrived":
        # flush the accumulated pending dwell into time-in-zone, count an
        # entry if the zone differs from the last committed one.
        if arm != self._ym_current_arm:
            self._ym_current_arm = arm
            if arm is not None:
                # Count entry on transition into a different zone.
                if arm != self._ym_last_committed_arm:
                    self._ym_arm_entries[arm] = self._ym_arm_entries.get(arm, 0) + 1
                    self._ym_last_committed_arm = arm
                # Flush the pending frames into time-in-zone in one shot.
                self._ym_arm_times[arm] = (
                    self._ym_arm_times.get(arm, 0.0)
                    + self._ym_pending_frames * dt
                )
        elif self._ym_pending_frames == min_frames:
            # Re-entered the same confirmed zone after a sub-threshold
            # excursion; flush the pending dwell so we don't lose frames.
            if arm is not None:
                self._ym_arm_times[arm] = (
                    self._ym_arm_times.get(arm, 0.0)
                    + self._ym_pending_frames * dt
                )
        else:
            # Already credited — just add this frame's dt.
            if arm is not None:
                self._ym_arm_times[arm] = self._ym_arm_times.get(arm, 0.0) + dt
        zd.update()

    def _on_preview_bg_ready(self, bg):
        """After base sets _preview_bg_raw, auto-detect the Y when we're in
        template mode and no hub/endpoints have been restored or placed yet.
        Result: opening a new video in Y-Maze mode draws the Y shape on the
        preview frame without the user clicking 'Define Y' first."""
        super()._on_preview_bg_ready(bg)
        if bg is None:
            return
        if not getattr(self, "rb_ym_template", None) or not self.rb_ym_template.isChecked():
            return
        if getattr(self, "_ym_hub", None) and getattr(self, "_ym_endpoints", None):
            # Saved (or already-placed) geometry — keep it.
            return
        try:
            from experiments.y_maze.ui import _start_template
            _start_template(self)
        except Exception:
            pass

    def begin_tracking(self):
        # Reset live Y-maze stats at the start of every tracking run.
        super().begin_tracking()
        from experiments.y_maze.zones import ARM_NAMES as _AN
        _ZONES = list(_AN) + ["neutral_zone"]
        self._ym_current_arm = None
        self._ym_last_committed_arm = None
        self._ym_arm_entries = {n: 0 for n in _ZONES}
        self._ym_arm_times = {n: 0.0 for n in _ZONES}
        self._ym_pending_arm = None
        self._ym_pending_frames = 0

    def _push_cell_state_for_frame(self, frame_idx):
        """Y-Maze scrub: replay arm assignment over frames [0..idx] so the
        per-arm entries + time labels show accurate cumulative counts even
        when live overlay was off during tracking. Mirrors the debounce
        in _on_tracking_body_pos so scrub matches what live would have
        shown. Cheap enough to run per scrub click on typical-length runs."""
        from experiments.y_maze.zones import ARM_NAMES as _AN
        from experiments.y_maze.ym_overlay import point_to_arm
        _ZONES = list(_AN) + ["neutral_zone"]
        zd = self.zone_drawer
        # Body dot still drives the live highlight on scrub. Default off
        # unless results carry a position for this frame.
        if not self.tracking_results:
            zd.set_body_pos_norm(None)
            self._ym_arm_entries = {n: 0 for n in _ZONES}
            self._ym_arm_times = {n: 0.0 for n in _ZONES}
            self._ym_current_arm = None
            zd.update()
            return
        rel_idx = self._slider_to_results_idx(frame_idx)
        # Push body position for the current frame.
        r = self.tracking_results[rel_idx]
        bx, by = r.get("x"), r.get("y")
        if bx is not None and by is not None and self.video_w and self.video_h:
            zd.set_body_pos_norm((bx / float(self.video_w),
                                   by / float(self.video_h)))
        else:
            zd.set_body_pos_norm(None)
        # Replay debounced arm assignment over results [0..rel_idx].
        fps = self.fps or 30.0
        dt = 1.0 / fps
        min_dwell = float(self.spin_min_dwell.value())
        min_frames = max(1, int(round(min_dwell * fps))) if min_dwell > 0 else 1
        entries = {n: 0 for n in _ZONES}
        times = {n: 0.0 for n in _ZONES}
        pending_arm = None
        pending_frames = 0
        current_arm = None
        last_committed = None
        vw = float(self.video_w or 1)
        vh = float(self.video_h or 1)
        for k in range(rel_idx + 1):
            rk = self.tracking_results[k]
            xk, yk = rk.get("x"), rk.get("y")
            if xk is None or yk is None:
                arm = None
            else:
                arm = point_to_arm(zd, xk / vw, yk / vh)
            if arm == pending_arm:
                pending_frames += 1
            else:
                pending_arm = arm
                pending_frames = 1
            if pending_frames < min_frames:
                continue
            if arm != current_arm:
                current_arm = arm
                if arm is not None:
                    if arm != last_committed:
                        entries[arm] = entries.get(arm, 0) + 1
                        last_committed = arm
                    times[arm] = times.get(arm, 0.0) + pending_frames * dt
            elif pending_frames == min_frames:
                if arm is not None:
                    times[arm] = times.get(arm, 0.0) + pending_frames * dt
            else:
                if arm is not None:
                    times[arm] = times.get(arm, 0.0) + dt
        self._ym_arm_entries = entries
        self._ym_arm_times = times
        self._ym_current_arm = current_arm
        zd.update()


class YMazeBatchTab(ExperimentBatchTab):
    embedded_tab_class = YMazeTab
