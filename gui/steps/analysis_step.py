"""Steps 5–6 — Tracking card (model, frame skip, proc resolution, toggles) and
Analysis card (move threshold, time bin, min dwell).

Shared across experiments. Builder takes the host tab and assigns the
expected widget attributes onto it.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QSpinBox, QVBoxLayout, QWidget,
)

from gui import theme
from gui.info_box import attach_info_box
from gui.widgets_v2 import IconButton, SwitchBox, form_row
from tracking.tracker import DEFAULT_MODEL_PARAMS, DEFAULT_POST_PARAMS


# (key, label, tooltip) — keys match tracking.tracker's model names.
_MODELS = [
    ("median", "Median BG",
     "Static background built from sampled frames. Recommended: validated "
     "against an independent detector; handles a mouse that freezes for most "
     "of the video, light or dark mice, and light flicker."),
    # Validation (real open-field video): MOG2 +51 % distance, KNN +17 %,
    # Frame difference found the mouse in 31 % of frames. Kept, but labelled.
    ("mog2", "MOG2 (experimental)",
     "Experimental — in validation it overestimated distance by about 50 %. "
     "Use Median BG for results."),
    ("knn", "KNN (experimental)",
     "Experimental — in validation it put the mouse in the wrong place in "
     "about a third of frames. Use Median BG for results."),
    ("framediff", "Frame difference (experimental)",
     "Experimental — misses a mouse that walks slowly or stays still (found it "
     "in 31 % of frames in validation). Use Median BG for results."),
    ("hsv", "HSV threshold",
     "Colour / brightness threshold — for a dark mouse on a light floor (or "
     "the reverse, with Invert off)."),
    ("cnt", "CNT (fast)", "Counts pixel stability; very fast. Needs opencv-contrib."),
    ("gsoc", "GSOC", "Robust to lighting noise; slower. Needs opencv-contrib."),
    ("lsbp", "LSBP", "Texture-based background model. Needs opencv-contrib."),
]
_CONTRIB_MODELS = {"cnt", "gsoc", "lsbp"}


def _available_models():
    """Models the installed OpenCV can run (CNT / GSOC / LSBP need the
    opencv-contrib build)."""
    try:
        import cv2
        contrib = hasattr(cv2, "bgsegm")
    except Exception:
        contrib = False
    return [m for m in _MODELS if contrib or m[0] not in _CONTRIB_MODELS]


def build_analysis_step(host):
    """Build the Tracking + Analysis cards. Sets attributes on host:
        _model_widget, combo_model, btn_model_tuning,
        spin_frame_skip, combo_proc_scale, spin_smooth_window,
        chk_enable_nose, chk_live_overlay, btn_multirun,
        _model_params, _post_params,
        spin_movement_thr, spin_bin_size, spin_min_dwell,
        spin_trim_start, spin_trim_duration,
        lbl_track
    Both cards are Full-mode only.
    Returns the Tracking card.
    """
    grp = host._group("Step 5 — Analysis", status_id="analysis", icon="tracking", name="Tracking")
    # Whole step is hidden in Simple mode.
    host._advanced_widgets.append(grp)
    layout = QVBoxLayout(grp)

    host._model_widget = QWidget()
    model_row = QHBoxLayout(host._model_widget)
    model_row.setContentsMargins(0, 0, 0, 0)
    model_row.setSpacing(6)
    host.combo_model = QComboBox()
    for key, label, tip in _available_models():
        host.combo_model.addItem(label, key)
        host.combo_model.setItemData(host.combo_model.count() - 1, tip, Qt.ToolTipRole)
    host.combo_model.setToolTip(
        "How the animal is separated from the background.\n"
        "Median BG is the default and works for most fixed-camera videos.")
    model_row.addWidget(host.combo_model, 1)
    host.btn_model_tuning = IconButton("gear", 13, "TEXT_2", "TEXT",
                                       "Tune the settings of the selected model.",
                                       28, "border")
    host.btn_model_tuning.clicked.connect(host._open_model_tuning_dialog)
    model_row.addWidget(host.btn_model_tuning)
    layout.addWidget(form_row("Model", host._model_widget))

    # Process resolution
    host.combo_proc_scale = QComboBox()
    host.combo_proc_scale.addItem("Full (1×)", 1.0)
    host.combo_proc_scale.addItem("75%  (faster)", 0.75)
    host.combo_proc_scale.addItem("50%  (2× faster)", 0.5)
    host.combo_proc_scale.addItem("25%  (4× faster)", 0.25)
    host.combo_proc_scale.setToolTip(
        "Downscale frames before detection.\n"
        "50% = ~4× faster on HD video.\n"
        "Coordinates are scaled back to full resolution."
    )
    layout.addWidget(form_row("Process res.", host.combo_proc_scale))

    # Frame skip (saved per video) — speed knob with linear interpolation.
    host.spin_frame_skip = QSpinBox()
    host.spin_frame_skip.setRange(1, 10)
    host.spin_frame_skip.setValue(1)
    host.spin_frame_skip.setSpecialValueText("Off (every frame)")
    host.spin_frame_skip.setSuffix("×")
    host.spin_frame_skip.setToolTip(
        "Process every Nth frame; skipped frames are linearly "
        "interpolated. 1 = no skip (most accurate). 2× ≈ 2× faster, "
        "negligible accuracy loss for OFT mice. Higher values smear "
        "rapid direction changes."
    )
    layout.addWidget(form_row("Frame skip", host.spin_frame_skip))

    host.spin_smooth_window = QSpinBox()
    host.spin_smooth_window.setRange(1, 9)
    host.spin_smooth_window.setSingleStep(2)
    host.spin_smooth_window.setSpecialValueText("Off")
    host.spin_smooth_window.setSuffix(" frames")
    host.spin_smooth_window.setValue(1)   # Off by default
    host.spin_smooth_window.setToolTip(
        "Rolling-median window applied to body/nose/tail coords after "
        "tracking. Kills single-frame jerks without blurring real motion.\n"
        "Off / 3 / 5 / 7 / 9 — larger smooths more, may flatten fast turns."
    )
    layout.addWidget(form_row("Smoothing", host.spin_smooth_window))

    # ── Nose detection toggle
    # Off by default for OF / Y-Maze / EPM (those use body-center metrics
    # and don't need orientation). ON by default for NOR (its angle filter
    # needs the nose heading). When OFF, the tracker skips the mass-asym
    # scan + leading-edge frame-diff + _resolve_nose state machine and
    # writes None for nose_x/y/tail_x/y/nose_confidence — saves measurable
    # per-frame time on long runs.
    exp = getattr(host, "experiment", None)
    nose_default = (exp.default_enable_nose()
                    if exp is not None and hasattr(exp, "default_enable_nose")
                    else False)
    host.chk_enable_nose = SwitchBox("Nose detection")
    host.chk_enable_nose.setChecked(bool(nose_default))
    host.chk_enable_nose.setToolTip(
        "Detect nose + tail endpoints each frame via mass asymmetry +\n"
        "leading-edge frame-diff + continuity. Adds ~1–3 ms / frame.\n"
        "Default OFF for OF / Y-Maze / EPM (body-center metrics don't\n"
        "need it). Default ON for Novel Object (the angle filter wants\n"
        "the nose heading)."
    )
    layout.addWidget(host.chk_enable_nose)
    host.chk_enable_nose.toggled.connect(host._sync_nose_marker_option)
    host._sync_nose_marker_option()

    # Live overlay toggle — controls per-frame painting of body/cells (or
    # arms) during tracking. Label comes from the plugin so each experiment
    # names it after its primary live element. Wires to the existing
    # _live_cell_overlay flag + _on_live_overlay_toggled handler.
    overlay_label = (exp.live_overlay_label() if exp is not None
                     else "Live overlay during tracking (slower)")
    host.chk_live_overlay = SwitchBox(overlay_label)
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
    host.btn_multirun = QPushButton("Multi run…")
    host.btn_multirun.setFixedHeight(28)
    host.btn_multirun.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
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
    layout.addWidget(host.btn_multirun)

    # Status label for interpolate / fix feedback (run controls live in
    # the video-list pane in batch mode; standalone path was retired).
    host.lbl_track = QLabel("")
    host.lbl_track.setWordWrap(True)
    theme.set_tone(host.lbl_track, "faint", "font-size:11px;")
    layout.addWidget(host.lbl_track)

    attach_info_box(grp, [
        ("Model tuning (⚙)", host.btn_model_tuning),
        ("Frame skip", host.spin_frame_skip),
        ("Smoothing", host.spin_smooth_window),
        ("Process Resolution", host.combo_proc_scale),
        ("Nose detection", host.chk_enable_nose),
        (overlay_label, host.chk_live_overlay),
        ("Multi run", host.btn_multirun),
    ])

    # ── Analysis card: thresholds that recompute metrics live ─────────────
    mg = host._group("Analysis", status_id="metrics", icon="analysis", name="Analysis")
    host._advanced_widgets.append(mg)
    ml = QVBoxLayout(mg)

    def _stepper(spin):
        spin.setProperty("stepper", True)
        spin.setAlignment(Qt.AlignCenter)
        spin.setButtonSymbols(QDoubleSpinBox.UpDownArrows)
        return spin

    # Move threshold + Time bin recompute live — they don't change tracked
    # frames, only metric output.
    host.spin_movement_thr = _stepper(QDoubleSpinBox())
    host.spin_movement_thr.setRange(0.0, 100.0)
    host.spin_movement_thr.setDecimals(2)
    host.spin_movement_thr.setSingleStep(0.5)
    host.spin_movement_thr.setValue(0.0)
    # Suffix is set to cm/s or px/s depending on calibration state.
    # _refresh_move_threshold_suffix() keeps it in sync.
    host.spin_movement_thr.setSuffix(" cm/s")
    host.spin_movement_thr.setSpecialValueText("Off")
    host.spin_movement_thr.setToolTip(
        "Speed below this counts as immobile.\n"
        "Units track calibration: cm/s if scale-bar is drawn, else px/s."
        "\n0 = off (every frame counts as moving)."
    )
    # Move threshold affects: metrics dict + bin_df (via _bin_metrics).
    # Graphs affected: Habituation only (reads bin_df).
    host.spin_movement_thr.valueChanged.connect(
        lambda _: host._schedule_narrow_recompute({"Habituation"})
    )
    ml.addWidget(form_row("Move threshold", host.spin_movement_thr))

    host.spin_bin_size = _stepper(QDoubleSpinBox())
    host.spin_bin_size.setRange(0.0, 3600.0)
    host.spin_bin_size.setDecimals(1)
    host.spin_bin_size.setSingleStep(30.0)
    host.spin_bin_size.setValue(0.0)
    host.spin_bin_size.setSuffix(" s")
    host.spin_bin_size.setSpecialValueText("Off")
    host.spin_bin_size.setToolTip(
        "Bin size for per-bin metrics. 0 = off (no bin breakdown).\n"
        "Common: 60 (1 min), 300 (5 min)."
    )
    # Time bin affects: bin_df + Habituation slope / first-bin summary
    # metrics. Graphs affected: Habituation only.
    host.spin_bin_size.valueChanged.connect(
        lambda _: host._schedule_narrow_recompute({"Habituation"})
    )
    ml.addWidget(form_row("Time bin", host.spin_bin_size))
    if hasattr(host, "zone_drawer"):   # built later on first construction
        try:
            host._refresh_move_threshold_suffix()
        except Exception:
            pass

    # Min dwell — body must stay in a cell (OF) or arm (Y-Maze) at least
    # this long to count as an entry. Single source of truth for both
    # experiments.
    host.spin_min_dwell = QDoubleSpinBox()
    host.spin_min_dwell.setRange(0.0, 60.0)
    host.spin_min_dwell.setDecimals(2)
    host.spin_min_dwell.setSingleStep(0.1)
    host.spin_min_dwell.setSuffix(" s")
    host.spin_min_dwell.setSpecialValueText("Off")
    host.spin_min_dwell.setToolTip(
        "Body must stay in a cell (OF) or arm (Y-Maze) at least this long "
        "to count as an entry — and to count toward time in that zone."
    )
    host.spin_min_dwell.setValue(0.2)
    if hasattr(host, "_on_min_dwell_changed"):
        host.spin_min_dwell.valueChanged.connect(host._on_min_dwell_changed)
    ml.addWidget(form_row("Min dwell", host.spin_min_dwell))

    note = QLabel("Changes recompute metrics live — tracked frames are not re-run.")
    note.setWordWrap(True)
    theme.set_tone(note, "faint", "font-size:11px;")
    ml.addWidget(note)
    attach_info_box(mg, [
        ("Move threshold", host.spin_movement_thr),
        ("Time bin", host.spin_bin_size),
        ("Min dwell", host.spin_min_dwell),
    ])
    return grp
