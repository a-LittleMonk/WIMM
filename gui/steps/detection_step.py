"""Step 4 — Detection (sensitivity + image presets + sliders + exclusion brush + preview).

Shared across experiments. Builder takes the host tab and assigns the
expected widget attributes onto it.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QSlider, QSpinBox,
    QVBoxLayout, QWidget,
)

from gui import theme
from gui.info_box import attach_info_box
from gui.widgets_v2 import IconTextButton, SwitchBox, field, link_button


def _caps(text):
    lb = QLabel(text.upper())
    lb.setProperty("role", "subcaps")
    return lb


def build_detection_step(host):
    """Build the Detection card. Sets attributes on host:
        spin_threshold, _adv_image_box, combo_preset, btn_reset,
        btn_preset_save, btn_preset_load, btn_preset_delete, btn_preset_export,
        slider_brightness, slider_contrast, slider_blur, slider_gamma,
        slider_sharpen, spin_clahe, spin_max_blob,
        _sep_before_excl, _excl_widget,
        btn_excl, spin_brush, btn_clear_excl,
        btn_preview, btn_preview_mode, btn_view_processed, lbl_adjust
    """
    grp = host._group("Step 4 — Detection", status_id="detection", name="Detection")
    layout = QVBoxLayout(grp)

    # ── Sensitivity box — always visible
    box = QFrame()
    box.setObjectName("SensBox")
    bv = QVBoxLayout(box)
    bv.setContentsMargins(10, 9, 10, 7)
    bv.setSpacing(5)
    head = QHBoxLayout()
    title = QLabel("Sensitivity")
    title.setStyleSheet("font-weight:600;")
    val = QLabel("25")
    val.setProperty("role", "sensval")
    head.addWidget(title)
    head.addStretch(1)
    head.addWidget(val)
    bv.addLayout(head)
    host.spin_threshold = QSlider(Qt.Horizontal)
    host.spin_threshold.setRange(5, 100)
    host.spin_threshold.setValue(25)
    host.spin_threshold.setMinimumHeight(22)
    host.spin_threshold.setToolTip(
        "Lower = more sensitive\nHigher = ignores noise/shadows\nDefault 25"
    )
    host.spin_threshold.valueChanged.connect(lambda v: val.setText(str(v)))
    host.spin_threshold.valueChanged.connect(host._update_preview)
    bv.addWidget(host.spin_threshold)
    hints = QHBoxLayout()
    for text in ("more sensitive", "ignores noise"):
        h = QLabel(text)
        h.setProperty("role", "hint9")
        hints.addWidget(h)
        if text == "more sensitive":
            hints.addStretch(1)
    bv.addLayout(hints)
    layout.addWidget(box)

    # ── advanced image settings
    host._adv_image_box = QWidget()
    adv = QVBoxLayout(host._adv_image_box)
    adv.setContentsMargins(0, 0, 0, 0)
    adv.setSpacing(7)

    # Preset combo + Reset.
    preset_row = QHBoxLayout()
    preset_row.setSpacing(6)
    host.combo_preset = QComboBox()
    host.combo_preset.setMinimumWidth(110)
    preset_row.addWidget(host.combo_preset, 1)
    host.btn_reset = IconTextButton("reset", "Reset", 11, height=28)
    host.btn_reset.setToolTip("Reset all detection sliders to defaults")
    host.btn_reset.clicked.connect(host._reset_sliders)
    preset_row.addWidget(host.btn_reset)
    adv.addLayout(preset_row)

    # Save / Delete / Import… / Export… as flat accent links.
    preset_btn_row = QHBoxLayout()
    preset_btn_row.setContentsMargins(0, 0, 0, 0)
    preset_btn_row.setSpacing(2)
    host.btn_preset_save = link_button("Save", "Save current settings as a named preset")
    host.btn_preset_save.clicked.connect(host._save_preset)
    host.btn_preset_delete = link_button("Delete", "Delete selected preset")
    host.btn_preset_delete.clicked.connect(host._delete_preset)
    host.btn_preset_load = link_button("Import…", "Import a preset from a file")
    host.btn_preset_load.clicked.connect(host._import_preset)
    host.btn_preset_export = link_button(
        "Export…", "Export selected preset to a file (to import on another computer)")
    host.btn_preset_export.clicked.connect(host._export_preset)
    for b in (host.btn_preset_save, host.btn_preset_delete,
              host.btn_preset_load, host.btn_preset_export):
        preset_btn_row.addWidget(b)
    preset_btn_row.addStretch()
    adv.addLayout(preset_btn_row)
    host._populate_preset_combo()
    # Picking a preset in the dropdown applies its own saved values.
    host.combo_preset.activated.connect(lambda _i: host._load_preset())

    adv.addWidget(_caps("Image"))
    host.slider_brightness, _ = host._slider_row(adv, "Brightness", -100, 100, 0, lambda v: f"{v:+d}")
    host.slider_contrast,   _ = host._slider_row(adv, "Contrast", 50, 300, 100, lambda v: f"{v/100:.1f}×", step=10)
    host.slider_blur,       _ = host._slider_row(adv, "Blur", 0, 10, 0, lambda v: str(v))
    host.slider_gamma,      _ = host._slider_row(adv, "Gamma", 30, 300, 100, lambda v: f"{v/100:.1f}×", step=10)
    host.slider_sharpen,    _ = host._slider_row(adv, "Sharpen", 0, 10, 0, lambda v: str(v))

    host.spin_clahe = QSpinBox()
    host.spin_clahe.setRange(0, 10)
    host.spin_clahe.setValue(0)
    host.spin_clahe.setSpecialValueText("Off")
    host.spin_clahe.setToolTip(
        "CLAHE — adaptive local contrast enhancement\n"
        "Helps in uneven lighting. Higher = more aggressive.\n0 = disabled"
    )
    host.spin_clahe.valueChanged.connect(host._update_preview)
    host.spin_max_blob = QSpinBox()
    host.spin_max_blob.setRange(0, 100)
    host.spin_max_blob.setValue(0)
    host.spin_max_blob.setSuffix(" % frame")
    host.spin_max_blob.setSpecialValueText("Off")
    host.spin_max_blob.setToolTip(
        "Reject blobs larger than this % of frame area\n"
        "Filters shadows and large artifacts\n0 = disabled"
    )
    two = QGridLayout()
    two.setContentsMargins(0, 2, 0, 0)
    two.setHorizontalSpacing(8)
    two.setColumnStretch(0, 1)
    two.setColumnStretch(1, 1)
    two.addWidget(field("CLAHE", host.spin_clahe), 0, 0)
    two.addWidget(field("Max blob", host.spin_max_blob), 0, 1)
    adv.addLayout(two)

    layout.addWidget(host._adv_image_box)
    host._advanced_widgets.append(host._adv_image_box)

    host._sep_before_excl = host._sep()
    host._sep_before_excl.hide()          # separators are gone in the card design
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

    # ── preview controls (advanced): switches with key hints
    preview_widget = QWidget()
    preview_box = QVBoxLayout(preview_widget)
    preview_box.setContentsMargins(0, 0, 0, 0)
    preview_box.setSpacing(2)
    preview_box.addWidget(_caps("Preview"))

    host.btn_preview = SwitchBox("Preview detection")
    host.btn_preview.setEnabled(False)
    host.btn_preview.toggled.connect(host._on_preview_toggled)
    host.btn_preview.hint = "D"
    preview_box.addWidget(host.btn_preview)

    host.btn_preview_mode = SwitchBox("Show mask")
    host.btn_preview_mode.setEnabled(False)
    host.btn_preview_mode.setToolTip("Off: overlay. On: binary mask.")
    host.btn_preview_mode.toggled.connect(host._on_preview_mode_toggled)
    host.btn_preview_mode.hint = "M"
    preview_box.addWidget(host.btn_preview_mode)

    host.btn_view_processed = SwitchBox("View effects")
    host.btn_view_processed.setChecked(True)
    host.btn_view_processed.setEnabled(False)
    host.btn_view_processed.setToolTip(
        "Show the full frame with all preprocessing applied\n"
        "so you can see the visual effect of your settings."
    )
    host.btn_view_processed.toggled.connect(
        lambda: host._update_preview() if host._preview_active else host._render_current_frame()
    )
    host.btn_view_processed.hint = "E"
    preview_box.addWidget(host.btn_view_processed)

    det_row = QHBoxLayout()
    det_row.setSpacing(6)
    det_row.addWidget(host._make_color_button("detection", size=12))
    det_lbl = QLabel("Detection overlay")
    theme.set_tone(det_lbl, "text2")
    det_lbl.setToolTip("Click swatch to change color and opacity (alpha slider in picker)")
    det_row.addWidget(det_lbl)
    det_row.addStretch()
    preview_box.addLayout(det_row)

    layout.addWidget(preview_widget)
    host._advanced_widgets.append(preview_widget)

    host.lbl_adjust = QLabel("Load a video first")
    host.lbl_adjust.setWordWrap(True)
    theme.set_tone(host.lbl_adjust, "faint", "font-size:11px;")
    layout.addWidget(host.lbl_adjust)

    attach_info_box(grp, [
        ("Sensitivity", host.spin_threshold),
        ("Reset", host.btn_reset),
        ("Save", host.btn_preset_save),
        ("Delete", host.btn_preset_delete),
        ("Import", host.btn_preset_load),
        ("Export", host.btn_preset_export),
        ("CLAHE", host.spin_clahe),
        ("Max blob", host.spin_max_blob),
        ("Show mask", host.btn_preview_mode),
        ("View effects", host.btn_view_processed),
        ("Detection color", det_lbl),
    ])
    return grp
