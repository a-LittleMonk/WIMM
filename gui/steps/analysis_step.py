"""Step 5 — Analysis (model selector, frame skip, proc resolution, trim holders).

Shared across experiments. Builder takes the host tab and assigns the
expected widget attributes onto it.
"""
from PyQt5.QtWidgets import (
    QLabel, QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QSpinBox,
    QDoubleSpinBox, QComboBox, QSizePolicy, QCheckBox,
)
from tracking.tracker import DEFAULT_MODEL_PARAMS, DEFAULT_POST_PARAMS


def build_analysis_step(host):
    """Build the Analysis group box. Sets attributes on host:
        _model_widget, combo_model, btn_model_tuning,
        spin_frame_skip, combo_proc_scale,
        _model_params, _post_params,
        spin_trim_start, spin_trim_duration,
        lbl_track
    Whole group is appended to host._advanced_widgets (Simple-mode hides it).
    """
    grp = host._group("Step 5 — Analysis", status_id="analysis")
    # Whole step is hidden in Simple mode.
    host._advanced_widgets.append(grp)
    layout = QVBoxLayout(grp)

    host._model_widget = QWidget()
    model_row = QHBoxLayout(host._model_widget)
    model_row.setContentsMargins(0, 0, 0, 0)
    model_row.setSpacing(4)
    model_row.addWidget(QLabel("Model:"))
    host.combo_model = QComboBox()
    host.combo_model.addItem("Median BG", "median")
    host.combo_model.setFixedHeight(24)
    model_row.addWidget(host.combo_model)
    host.btn_model_tuning = QPushButton("⚙")
    host.btn_model_tuning.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    host.btn_model_tuning.setFixedSize(24, 24)
    host.btn_model_tuning.setToolTip("Tune History / Learn rate for the selected model.")
    host.btn_model_tuning.clicked.connect(host._open_model_tuning_dialog)
    model_row.addWidget(host.btn_model_tuning)
    model_row.addStretch()
    layout.addWidget(host._model_widget)

    # Frame skip (saved per video) — speed knob with linear interpolation.
    skip_row = QHBoxLayout()
    skip_row.addWidget(QLabel("Frame skip:"))
    host.spin_frame_skip = QSpinBox()
    host.spin_frame_skip.setRange(1, 10)
    host.spin_frame_skip.setValue(1)
    host.spin_frame_skip.setSpecialValueText("Off (every frame)")
    host.spin_frame_skip.setSuffix("×")
    host.spin_frame_skip.setFixedWidth(120)
    host.spin_frame_skip.setFixedHeight(24)
    host.spin_frame_skip.setToolTip(
        "Process every Nth frame; skipped frames are linearly "
        "interpolated. 1 = no skip (most accurate). 2× ≈ 2× faster, "
        "negligible accuracy loss for OFT mice. Higher values smear "
        "rapid direction changes."
    )
    skip_row.addWidget(host.spin_frame_skip)
    skip_row.addStretch()
    layout.addLayout(skip_row)

    smooth_row = QHBoxLayout()
    smooth_row.addWidget(QLabel("Smoothing:"))
    host.spin_smooth_window = QSpinBox()
    host.spin_smooth_window.setRange(1, 9)
    host.spin_smooth_window.setSingleStep(2)
    host.spin_smooth_window.setSpecialValueText("Off")
    host.spin_smooth_window.setSuffix(" frames")
    host.spin_smooth_window.setFixedWidth(120)
    host.spin_smooth_window.setFixedHeight(24)
    host.spin_smooth_window.setValue(1)   # Off by default
    host.spin_smooth_window.setToolTip(
        "Rolling-median window applied to body/nose/tail coords after "
        "tracking. Kills single-frame jerks without blurring real motion.\n"
        "Off / 3 / 5 / 7 / 9 — larger smooths more, may flatten fast turns."
    )
    smooth_row.addWidget(host.spin_smooth_window)
    smooth_row.addStretch()
    layout.addLayout(smooth_row)

    proc_row = QHBoxLayout()
    proc_row.setSpacing(6)
    proc_row.addWidget(QLabel("Proc res:"))
    host.combo_proc_scale = QComboBox()
    host.combo_proc_scale.setFixedHeight(24)
    host.combo_proc_scale.addItem("Full (1×)", 1.0)
    host.combo_proc_scale.addItem("75%  (faster)", 0.75)
    host.combo_proc_scale.addItem("50%  (2× faster)", 0.5)
    host.combo_proc_scale.addItem("25%  (4× faster)", 0.25)
    host.combo_proc_scale.setToolTip(
        "Downscale frames before detection.\n"
        "50% = ~4× faster on HD video.\n"
        "Coordinates are scaled back to full resolution."
    )
    proc_row.addWidget(host.combo_proc_scale)
    proc_row.addStretch()
    layout.addLayout(proc_row)

    # Min dwell — body must stay in a cell (OF) or arm (Y-Maze) at least
    # this long to count as an entry. Single source of truth for both
    # experiments; per-experiment min-dwell rows in Cell Info / Step 2
    # were removed when this widget moved here.
    dwell_row = QHBoxLayout()
    dwell_row.addWidget(QLabel("Min dwell:"))
    host.spin_min_dwell = QDoubleSpinBox()
    host.spin_min_dwell.setRange(0.0, 60.0)
    host.spin_min_dwell.setDecimals(2)
    host.spin_min_dwell.setSingleStep(0.1)
    host.spin_min_dwell.setSuffix(" s")
    host.spin_min_dwell.setSpecialValueText("Off")
    host.spin_min_dwell.setFixedWidth(120)
    host.spin_min_dwell.setFixedHeight(24)
    host.spin_min_dwell.setToolTip(
        "Body must stay in a cell (OF) or arm (Y-Maze) at least this long "
        "to count as an entry — and to count toward time in that zone."
    )
    host.spin_min_dwell.setValue(0.2)
    if hasattr(host, "_on_min_dwell_changed"):
        host.spin_min_dwell.valueChanged.connect(host._on_min_dwell_changed)
    dwell_row.addWidget(host.spin_min_dwell)
    dwell_row.addStretch()
    layout.addLayout(dwell_row)

    # ── Nose detection toggle ─────────────────────────────────────────
    # Off by default for OF / Y-Maze / EPM (those use body-center metrics
    # and don't need orientation). ON by default for NOR (its angle filter
    # needs the nose heading). When OFF, the tracker skips the mass-asym
    # scan + leading-edge frame-diff + _resolve_nose state machine and
    # writes None for nose_x/y/tail_x/y/nose_confidence — saves measurable
    # per-frame time on long runs.
    nose_row = QHBoxLayout()
    exp = getattr(host, "experiment", None)
    nose_default = (exp.default_enable_nose()
                    if exp is not None and hasattr(exp, "default_enable_nose")
                    else False)
    host.chk_enable_nose = QCheckBox("Nose detection")
    host.chk_enable_nose.setChecked(bool(nose_default))
    host.chk_enable_nose.setToolTip(
        "Detect nose + tail endpoints each frame via mass asymmetry +\n"
        "leading-edge frame-diff + continuity. Adds ~1–3 ms / frame.\n"
        "Default OFF for OF / Y-Maze / EPM (body-center metrics don't\n"
        "need it). Default ON for Novel Object (the angle filter wants\n"
        "the nose heading)."
    )
    nose_row.addWidget(host.chk_enable_nose)
    nose_row.addStretch()
    layout.addLayout(nose_row)

    # Live overlay toggle — controls per-frame painting of body/cells (or
    # arms) during tracking. Label comes from the plugin so each experiment
    # names it after its primary live element. Wires to the existing
    # _live_cell_overlay flag + _on_live_overlay_toggled handler.
    exp = getattr(host, "experiment", None)
    overlay_label = (exp.live_overlay_label() if exp is not None
                     else "Live overlay during tracking (slower)")
    host.chk_live_overlay = QCheckBox(overlay_label)
    host.chk_live_overlay.setChecked(bool(getattr(host, "_live_cell_overlay", False)))
    host.chk_live_overlay.setToolTip(
        "Default OFF for speed. When ON, the live overlay (body / arm fill, "
        "labels, per-zone timer + entry count) updates every frame during "
        "tracking. After tracking finishes, everything is shown regardless "
        "of this toggle — use the View popup to hide specific elements."
    )
    host.chk_live_overlay.toggled.connect(host._on_live_overlay_toggled)
    layout.addWidget(host.chk_live_overlay)

    # Persist per-model tuning data for the gear-icon dialog.
    saved_mp = host.config.get("model_params", {}) if isinstance(host.config.get("model_params"), dict) else {}
    host._model_params = {
        m: {**defaults, **saved_mp.get(m, {})}
        for m, defaults in DEFAULT_MODEL_PARAMS.items()
    }
    saved_pp = host.config.get("post_params", {}) if isinstance(host.config.get("post_params"), dict) else {}
    host._post_params = {**DEFAULT_POST_PARAMS, **saved_pp}
    host.combo_model.currentIndexChanged.connect(host._update_model_tuning_button)
    def _log_model_change(_idx):
        try:
            from core import logger
            logger.info(
                f"Tracking model → {host.combo_model.currentText()} "
                f"({host.combo_model.currentData()})",
                source="settings",
            )
        except Exception:
            pass
    host.combo_model.currentIndexChanged.connect(_log_model_change)
    host._update_model_tuning_button()

    # Trim spinboxes — headless data holders. The Trim & Crop popup in
    # the video-list owns the UI; these back snapshot/apply and the
    # _trim_start_s / _trim_duration_s helpers used by tracker calls.
    host.spin_trim_start = QDoubleSpinBox()
    host.spin_trim_start.setRange(0.0, 100000.0)
    host.spin_trim_start.setDecimals(1)
    host.spin_trim_start.setValue(0.0)
    host.spin_trim_start.editingFinished.connect(host.apply_trim_to_scrub)
    host.spin_trim_duration = QDoubleSpinBox()
    host.spin_trim_duration.setRange(0.0, 100000.0)
    host.spin_trim_duration.setDecimals(1)
    host.spin_trim_duration.setValue(0.0)
    host.spin_trim_duration.editingFinished.connect(host.apply_trim_to_scrub)

    # Multi run button.
    mr_row = QHBoxLayout()
    host.btn_multirun = QPushButton("Multi run")
    host.btn_multirun.setFixedHeight(26)
    host.btn_multirun.setToolTip(
        "Re-run this video N times changing only one variable between runs "
        "(e.g. proc_scale, threshold, model). Outputs a comparison xlsx."
    )
    def _open_multirun_from_step5():
        from PyQt5.QtWidgets import QMessageBox, QApplication
        # The embedded ExperimentTab is hidden and never parented, so walking
        # from `host` fails. The button itself, however, lives inside
        # _config_scroll which the batch tab reparents into its middle pane,
        # so walking parents from the button reaches the batch tab.
        batch = None
        w = host.btn_multirun.parentWidget()
        while w is not None:
            if hasattr(w, "_track_for_multirun"):
                batch = w
                break
            w = w.parentWidget()
        # Fallback: scan all top-level widgets for the active batch tab.
        if batch is None:
            for tlw in QApplication.topLevelWidgets():
                for child in tlw.findChildren(type(tlw)):
                    pass
                if hasattr(tlw, "_track_for_multirun"):
                    batch = tlw
                    break
                for child in tlw.findChildren(object):
                    if (hasattr(child, "_track_for_multirun")
                            and getattr(child, "embedded_tab", None) is host):
                        batch = child
                        break
                if batch is not None:
                    break
        if batch is None:
            QMessageBox.information(
                host, "Multi run",
                "Open this from inside an experiment tab."
            )
            return
        if not getattr(batch, "_embedded_loaded_path", None):
            QMessageBox.information(
                host, "Multi run", "Load a video first."
            )
            return
        from gui.multi_run_dialog import MultiRunDialog
        MultiRunDialog(batch, host).exec_()
    host.btn_multirun.clicked.connect(_open_multirun_from_step5)
    mr_row.addWidget(host.btn_multirun)
    mr_row.addStretch()
    layout.addLayout(mr_row)

    # Status label for interpolate / fix feedback (run controls live in
    # the video-list pane in batch mode; standalone path was retired).
    host.lbl_track = QLabel("")
    host.lbl_track.setWordWrap(True)
    host.lbl_track.setStyleSheet("color:#888; font-size:11px;")
    layout.addWidget(host.lbl_track)
    return grp
