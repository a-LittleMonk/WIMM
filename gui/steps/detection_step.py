"""Step 4 — Detection (sensitivity + image presets + sliders + exclusion brush + preview).

Shared across experiments. Builder takes the host tab and assigns the
expected widget attributes onto it.
"""
from PyQt5.QtWidgets import (
    QLabel, QWidget, QHBoxLayout, QVBoxLayout, QSpinBox,
    QComboBox, QCheckBox,
)


def build_detection_step(host):
    """Build the Detection group box. Sets attributes on host:
        spin_threshold, _adv_image_box, combo_preset, btn_reset,
        btn_preset_save, btn_preset_load, btn_preset_delete,
        slider_brightness, slider_contrast, slider_blur, slider_gamma,
        slider_sharpen, spin_clahe, spin_max_blob,
        _sep_before_excl, _excl_widget,
        btn_excl, spin_brush, btn_clear_excl,
        btn_preview, btn_preview_mode, btn_view_processed, lbl_adjust
    """
    grp = host._group("Step 4 — Detection", status_id="detection")
    layout = QVBoxLayout(grp)
    layout.setSpacing(4)

    # Sensitivity slider — always visible. Lives in its own wrapper so
    # the advanced image box can hide everything else in Simple mode.
    sens_widget = QWidget()
    sens_layout = QVBoxLayout(sens_widget)
    sens_layout.setContentsMargins(0, 0, 0, 0)
    sens_layout.setSpacing(0)
    host.spin_threshold, _ = host._slider_row(
        sens_layout, "Sensitivity", 5, 100, 25, lambda v: str(v)
    )
    host.spin_threshold.setToolTip(
        "Lower = more sensitive\nHigher = ignores noise/shadows\nDefault 25"
    )
    layout.addWidget(sens_widget)

    # ── advanced image settings
    host._adv_image_box = QWidget()
    adv = QVBoxLayout(host._adv_image_box)
    adv.setContentsMargins(0, 0, 0, 0)
    adv.setSpacing(4)

    # Top: preset combo + Reset.
    preset_row = QHBoxLayout()
    preset_row.setSpacing(6)
    preset_row.addWidget(QLabel("Preset:"))
    host.combo_preset = QComboBox()
    host.combo_preset.setFixedHeight(24)
    host.combo_preset.setMinimumWidth(110)
    preset_row.addWidget(host.combo_preset, 1)
    host.btn_reset = host._btn("Reset", width=55)
    host.btn_reset.setToolTip("Reset all detection sliders to defaults")
    host.btn_reset.clicked.connect(host._reset_sliders)
    preset_row.addWidget(host.btn_reset)
    adv.addLayout(preset_row)

    # Bottom: Save / Load / Del.
    preset_btn_row = QHBoxLayout()
    preset_btn_row.setSpacing(6)
    host.btn_preset_save = host._btn("Save", width=55)
    host.btn_preset_save.setToolTip("Save current settings as a named preset")
    host.btn_preset_save.clicked.connect(host._save_preset)
    host.btn_preset_load = host._btn("Load", width=55)
    host.btn_preset_load.setToolTip("Apply selected preset")
    host.btn_preset_load.clicked.connect(host._load_preset)
    host.btn_preset_delete = host._btn("Del", width=45)
    host.btn_preset_delete.setToolTip("Delete selected preset")
    host.btn_preset_delete.clicked.connect(host._delete_preset)
    preset_btn_row.addWidget(host.btn_preset_save)
    preset_btn_row.addWidget(host.btn_preset_load)
    preset_btn_row.addWidget(host.btn_preset_delete)
    preset_btn_row.addStretch()
    adv.addLayout(preset_btn_row)
    host._populate_preset_combo()

    adv.addWidget(host._sep())

    host.slider_brightness, _ = host._slider_row(adv, "Brightness", -100, 100, 0, lambda v: f"{v:+d}")
    host.slider_contrast,   _ = host._slider_row(adv, "Contrast", 50, 300, 100, lambda v: f"{v/100:.1f}x", step=10)
    host.slider_blur,       _ = host._slider_row(adv, "Blur", 0, 10, 0, lambda v: str(v))
    host.slider_gamma,      _ = host._slider_row(adv, "Gamma", 30, 300, 100, lambda v: f"{v/100:.1f}x", step=10)
    host.slider_sharpen,    _ = host._slider_row(adv, "Sharpen", 0, 10, 0, lambda v: str(v))

    clahe_row = QHBoxLayout()
    clahe_row.setSpacing(6)
    clahe_row.addWidget(QLabel("CLAHE:"))
    host.spin_clahe = QSpinBox()
    host.spin_clahe.setRange(0, 10)
    host.spin_clahe.setValue(0)
    host.spin_clahe.setSpecialValueText("Off")
    host.spin_clahe.setFixedWidth(55)
    host.spin_clahe.setFixedHeight(24)
    host.spin_clahe.setToolTip(
        "CLAHE — adaptive local contrast enhancement\n"
        "Helps in uneven lighting. Higher = more aggressive.\n0 = disabled"
    )
    host.spin_clahe.valueChanged.connect(host._update_preview)
    clahe_row.addWidget(host.spin_clahe)
    clahe_row.addStretch()
    adv.addLayout(clahe_row)

    adv.addWidget(host._sep())

    blob_row = QHBoxLayout()
    blob_row.setSpacing(6)
    blob_row.addWidget(QLabel("Max blob:"))
    host.spin_max_blob = QSpinBox()
    host.spin_max_blob.setRange(0, 100)
    host.spin_max_blob.setValue(0)
    host.spin_max_blob.setSuffix(" %")
    host.spin_max_blob.setSpecialValueText("Off")
    host.spin_max_blob.setFixedWidth(65)
    host.spin_max_blob.setFixedHeight(24)
    host.spin_max_blob.setToolTip(
        "Reject blobs larger than this % of frame area\n"
        "Filters shadows and large artifacts\n0 = disabled"
    )
    blob_row.addWidget(host.spin_max_blob)
    blob_row.addStretch()
    adv.addLayout(blob_row)

    layout.addWidget(host._adv_image_box)
    host._advanced_widgets.append(host._adv_image_box)

    host._sep_before_excl = host._sep()
    layout.addWidget(host._sep_before_excl)
    host._advanced_widgets.append(host._sep_before_excl)

    # ── exclusion brush — widgets created but not added to layout (hidden in OF/Y-Maze).
    # Attrs preserved because save/load (brush_radius) and runtime code still reference them.
    host._excl_widget = QWidget()
    excl_row = QHBoxLayout(host._excl_widget)
    excl_row.setContentsMargins(0, 0, 0, 0)
    excl_row.setSpacing(6)
    host.btn_excl = host._btn("Exclusion Brush")
    host.btn_excl.setCheckable(True)
    host.btn_excl.setEnabled(False)
    host.btn_excl.toggled.connect(host._on_excl_toggled)
    excl_row.addWidget(host.btn_excl)
    host.spin_brush = QSpinBox()
    host.spin_brush.setRange(5, 200)
    host.spin_brush.setValue(20)
    host.spin_brush.setSuffix("px")
    host.spin_brush.valueChanged.connect(lambda v: setattr(host.zone_drawer, "brush_radius", v))
    excl_row.addWidget(host.spin_brush)
    host.btn_clear_excl = host._btn("Clear", width=42)
    host.btn_clear_excl.setEnabled(False)
    host.btn_clear_excl.clicked.connect(host._clear_exclusions)
    excl_row.addWidget(host.btn_clear_excl)
    host._excl_widget.setVisible(False)

    # ── preview controls (advanced)
    preview_widget = QWidget()
    preview_box = QVBoxLayout(preview_widget)
    preview_box.setContentsMargins(0, 0, 0, 0)
    preview_box.setSpacing(2)

    host.btn_preview = QCheckBox("Preview Detection")
    host.btn_preview.setEnabled(False)
    host.btn_preview.toggled.connect(host._on_preview_toggled)
    preview_box.addWidget(host.btn_preview)

    host.btn_preview_mode = QCheckBox("Show mask")
    host.btn_preview_mode.setEnabled(False)
    host.btn_preview_mode.setToolTip("Off: overlay. On: binary mask.")
    host.btn_preview_mode.toggled.connect(host._on_preview_mode_toggled)
    preview_box.addWidget(host.btn_preview_mode)

    host.btn_view_processed = QCheckBox("View effects")
    host.btn_view_processed.setChecked(True)
    host.btn_view_processed.setEnabled(False)
    host.btn_view_processed.setToolTip(
        "Show the full frame with all preprocessing applied\n"
        "so you can see the visual effect of your settings."
    )
    host.btn_view_processed.toggled.connect(
        lambda: host._update_preview() if host._preview_active else host._render_current_frame()
    )
    preview_box.addWidget(host.btn_view_processed)

    det_row = QHBoxLayout()
    det_row.setSpacing(4)
    det_row.addWidget(host._make_color_button("detection", size=14))
    det_lbl = QLabel("Detection")
    det_lbl.setStyleSheet("font-size:10px;")
    det_lbl.setToolTip("Click swatch to change color and opacity (alpha slider in picker)")
    det_row.addWidget(det_lbl)
    det_row.addStretch()
    preview_box.addLayout(det_row)

    layout.addWidget(preview_widget)
    host._advanced_widgets.append(preview_widget)

    host.lbl_adjust = QLabel("Load a video first")
    host.lbl_adjust.setWordWrap(True)
    host.lbl_adjust.setStyleSheet("color:#888; font-size:11px;")
    layout.addWidget(host.lbl_adjust)
    return grp
