"""EPM tab: thin subclass of OpenFieldTab that swaps the experiment
plugin to EPMExperiment. The plugin handles the geometry pane, results
tab additions, and metric computation so this class stays small.

EPMBatchTab is the equivalent thin subclass of ExperimentBatchTab."""
from gui.open_field_tab import OpenFieldTab
from gui.experiment_batch_tab import ExperimentBatchTab
from experiments.epm import EPMExperiment


class EPMTab(OpenFieldTab):
    def __init__(self, config):
        super().__init__(config, experiment=EPMExperiment())
        # Add EPM results tab right after Summary (index 1).
        try:
            tab = self.experiment.build_results_tabs(self, self._excel_tabs)
            if tab is not None and hasattr(self, "_excel_tabs"):
                self._excel_tabs.insertTab(1, tab, "EPM")
        except Exception:
            pass
        # Live per-zone tracking state — arms + center.
        from experiments.epm.zones import ARM_NAMES as _AN
        _ZONES = list(_AN) + ["center_zone"]
        self._epm_current_arm = None
        self._epm_last_committed_arm = None
        self._epm_arm_entries = {n: 0 for n in _ZONES}
        self._epm_arm_times = {n: 0.0 for n in _ZONES}
        self._epm_pending_arm = None
        self._epm_pending_frames = 0
        # Register the EPM overlay renderer with the shared zone drawer.
        from experiments.epm.epm_overlay import paint_epm_overlay
        zd = self.zone_drawer
        zd.set_overlay_renderer(
            lambda p, ox, oy, dw, dh: paint_epm_overlay(self, zd, p, ox, oy, dw, dh)
        )
        # Step 3 — replace OF cage W×H with an "Arm length (cm)" spinbox.
        if hasattr(self, "_cage_size_widget"):
            self._install_epm_arm_length_widget()
            if hasattr(self, "_refresh_calib_mode_visibility"):
                self._refresh_calib_mode_visibility()

    def _install_epm_arm_length_widget(self):
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
        # Mouse-EPM default 30 cm.
        spin.setValue(float(self.config.get("epm_arm_length_cm", 30.0)))
        spin.setToolTip(
            "Physical hub-to-tip distance of one arm in cm. Auto-"
            "calibration uses mean pixel spoke length ÷ this value = px/cm."
        )
        from gui.info_box import attach_info_box
        attach_info_box(self._step_groups["scale"], [("Arm length", spin)])

        def _on_change(v):
            self.config["epm_arm_length_cm"] = float(v)
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
        self.spin_epm_arm_length_cm = spin
        self._epm_arm_length_widget = widget
        idx = layout.indexOf(self._cage_size_widget)
        if idx >= 0:
            layout.insertWidget(idx, widget)
        else:
            layout.addWidget(widget)

    def _on_tracking_body_pos(self, body_xy):
        """Per-frame body position from the tracker. Mirrors Y-Maze rule
        but extends to 4 arms + center."""
        if self._tracking_active and not self._live_cell_overlay:
            return
        zd = self.zone_drawer
        if body_xy is None or not (self.video_w and self.video_h):
            zd.set_body_pos_norm(None)
            self._epm_current_arm = None
            zd.update()
            return
        x_px, y_px = body_xy
        nx, ny = x_px / float(self.video_w), y_px / float(self.video_h)
        zd.set_body_pos_norm((nx, ny))
        from experiments.epm.epm_overlay import point_to_arm
        arm = point_to_arm(zd, nx, ny)  # arm_n/s/e/w, "center_zone", or None
        fps = self.fps or 30.0
        dt = 1.0 / fps
        min_dwell = float(self.spin_min_dwell.value())
        min_frames = max(1, int(round(min_dwell * fps))) if min_dwell > 0 else 1
        if arm == self._epm_pending_arm:
            self._epm_pending_frames += 1
        else:
            self._epm_pending_arm = arm
            self._epm_pending_frames = 1
        if self._epm_pending_frames < min_frames:
            zd.update()
            return
        if arm != self._epm_current_arm:
            self._epm_current_arm = arm
            if arm is not None:
                if arm != self._epm_last_committed_arm:
                    self._epm_arm_entries[arm] = self._epm_arm_entries.get(arm, 0) + 1
                    self._epm_last_committed_arm = arm
                self._epm_arm_times[arm] = (
                    self._epm_arm_times.get(arm, 0.0)
                    + self._epm_pending_frames * dt
                )
        elif self._epm_pending_frames == min_frames:
            if arm is not None:
                self._epm_arm_times[arm] = (
                    self._epm_arm_times.get(arm, 0.0)
                    + self._epm_pending_frames * dt
                )
        else:
            if arm is not None:
                self._epm_arm_times[arm] = self._epm_arm_times.get(arm, 0.0) + dt
        zd.update()

    def _on_preview_bg_ready(self, bg):
        """When in template mode and no hub/endpoints saved yet, drop the
        default plus template on the preview the moment a video loads."""
        super()._on_preview_bg_ready(bg)
        if bg is None:
            return
        if not getattr(self, "rb_epm_template", None) or not self.rb_epm_template.isChecked():
            return
        if getattr(self, "_epm_hub", None) and getattr(self, "_epm_endpoints", None):
            return
        try:
            from experiments.epm.ui import _start_template
            _start_template(self)
        except Exception:
            pass

    def apply_settings(self, s):
        """After the base apply restores the panel, rebuild the EPM
        perspective warp from the saved snapshot.

        The base ExperimentTab._apply_settings_body drives the OpenField
        arena-based perspective and, since EPM never sets the OF "perspective"
        key, takes its else-branch and clears self._H / _perspective_on. On a
        normal load that's harmless, but on the post-tracking embedded reload
        it tears down the warp the user set — so the preview falls back to the
        un-warped native frame. Re-apply the EPM warp here so the corrected
        view survives the reload."""
        super().apply_settings(s)
        try:
            self._restore_epm_perspective(s if isinstance(s, dict) else {})
        except Exception:
            import traceback
            traceback.print_exc()

    def _restore_epm_perspective(self, s):
        from experiments.epm.zones import canonical_plus_geometry
        exp = getattr(self, "experiment", None)
        zd = self.zone_drawer
        if exp is None or not s.get("epm_perspective"):
            return
        # build_tracking_homography reads epm_original_hub/endpoints from the
        # snapshot and maps them onto the canonical plus in native pixels —
        # the exact warp the tracker used, so the preview matches the data.
        # Build from the TRUE native size (video_w/h may already be the warp
        # size after _load_video_path's restore).
        native = getattr(self, "_native_video_size", None) or (self.video_w, self.video_h)
        res = exp.build_tracking_homography(s, native)
        if not res:
            return
        H, warp_size = res
        # Preserve the pre-perspective geometry so Adjust… / revert still work.
        if s.get("epm_original_hub"):
            self._epm_original_hub = tuple(s["epm_original_hub"])
        if s.get("epm_original_endpoints"):
            self._epm_original_endpoints = [tuple(p) for p in s["epm_original_endpoints"]]
        if not getattr(self, "_native_video_size", None):
            self._native_video_size = tuple(native)
        self._epm_perspective_on = True
        self._perspective_on = True
        self._H = H
        self.video_w, self.video_h = warp_size
        self._perspective_warp_size = tuple(warp_size)
        # Snap the template to canonical positions inside the warp space.
        canon_hub, canon_tips = canonical_plus_geometry(warp_size)
        if canon_hub:
            self._epm_hub = canon_hub
            self._epm_endpoints = canon_tips
        if hasattr(zd, "set_perspective_locked"):
            zd.set_perspective_locked(True)
        # Sync the checkbox + Adjust button without re-opening the dialog.
        if hasattr(self, "chk_epm_perspective"):
            self.chk_epm_perspective.blockSignals(True)
            self.chk_epm_perspective.setChecked(True)
            self.chk_epm_perspective.blockSignals(False)
        if hasattr(self, "btn_epm_perspective_adjust"):
            self.btn_epm_perspective_adjust.setEnabled(True)
        # Re-warp the cached scrub frame so the preview shows the corrected view.
        if getattr(self, "slider_scrub", None) is not None:
            try:
                self._on_scrub(self.slider_scrub.value())
            except Exception:
                pass
        zd.emit_change("epm perspective restored")

    def begin_tracking(self):
        super().begin_tracking()
        from experiments.epm.zones import ARM_NAMES as _AN
        _ZONES = list(_AN) + ["center_zone"]
        self._epm_current_arm = None
        self._epm_last_committed_arm = None
        self._epm_arm_entries = {n: 0 for n in _ZONES}
        self._epm_arm_times = {n: 0.0 for n in _ZONES}
        self._epm_pending_arm = None
        self._epm_pending_frames = 0

    def _push_cell_state_for_frame(self, frame_idx):
        """Replay arm assignment over frames [0..idx] on scrub."""
        from experiments.epm.zones import ARM_NAMES as _AN
        from experiments.epm.epm_overlay import point_to_arm
        _ZONES = list(_AN) + ["center_zone"]
        zd = self.zone_drawer
        if not self.tracking_results:
            zd.set_body_pos_norm(None)
            self._epm_arm_entries = {n: 0 for n in _ZONES}
            self._epm_arm_times = {n: 0.0 for n in _ZONES}
            self._epm_current_arm = None
            zd.update()
            return
        rel_idx = self._slider_to_results_idx(frame_idx)
        r = self.tracking_results[rel_idx]
        bx, by = r.get("x"), r.get("y")
        if bx is not None and by is not None and self.video_w and self.video_h:
            zd.set_body_pos_norm((bx / float(self.video_w),
                                   by / float(self.video_h)))
        else:
            zd.set_body_pos_norm(None)
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
        self._epm_arm_entries = entries
        self._epm_arm_times = times
        self._epm_current_arm = current_arm
        zd.update()


class EPMBatchTab(ExperimentBatchTab):
    embedded_tab_class = EPMTab
