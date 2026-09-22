"""Step 3 — Scale (px↔cm calibration via auto / manual line / pixels mode).

Shared across experiments. Builder takes the host tab and assigns the
expected widget attributes onto it.
"""
from PyQt5.QtWidgets import (
    QLabel, QWidget, QHBoxLayout, QVBoxLayout, QDoubleSpinBox,
    QRadioButton, QButtonGroup,
)


def build_scale_step(host):
    """Build the Scale group box. Sets attributes on host:
        calib_mode_group, rb_calib_auto, rb_calib_manual, rb_calib_none,
        spin_cage_w, spin_cage_h, lbl_cage_w, lbl_cage_x, lbl_cage_h,
        _calib_auto_widget, _cage_size_widget, lbl_calib_auto_hint,
        _calib_manual_widget, btn_calib, btn_clear_calib, spin_cm,
        lbl_calib
    """
    grp = host._group("Step 3 — Scale", status_id="scale", optional=True)
    layout = QVBoxLayout(grp)
    layout.setSpacing(4)

    host.calib_mode_group = QButtonGroup(grp)
    host.rb_calib_auto   = QRadioButton("Auto from cage size")
    host.rb_calib_manual = QRadioButton("Manual line")
    host.rb_calib_none   = QRadioButton("None (pixels)")
    for rb in (host.rb_calib_auto, host.rb_calib_manual, host.rb_calib_none):
        rb.setStyleSheet("font-size:11px;")
    host.calib_mode_group.addButton(host.rb_calib_auto, 0)
    host.calib_mode_group.addButton(host.rb_calib_manual, 1)
    host.calib_mode_group.addButton(host.rb_calib_none, 2)
    layout.addWidget(host.rb_calib_auto)
    layout.addWidget(host.rb_calib_manual)
    layout.addWidget(host.rb_calib_none)

    # Auto sub-panel: cage real-world dimensions (Width × Height).
    host._calib_auto_widget = QWidget()
    auto_v = QVBoxLayout(host._calib_auto_widget)
    auto_v.setContentsMargins(14, 0, 0, 0)
    auto_v.setSpacing(2)

    host._cage_size_widget = QWidget()
    size_row = QHBoxLayout(host._cage_size_widget)
    size_row.setContentsMargins(0, 0, 0, 0)
    size_row.setSpacing(4)
    host.lbl_cage_w = QLabel("Width:")
    host.spin_cage_w = QDoubleSpinBox()
    host.spin_cage_w.setRange(0.1, 9999.0)
    host.spin_cage_w.setDecimals(1)
    host.spin_cage_w.setSingleStep(1.0)
    host.spin_cage_w.setSuffix(" cm")
    host.spin_cage_w.setFixedWidth(80)
    host.spin_cage_w.setFixedHeight(24)
    host.spin_cage_w.setValue(float(host.config.get("cage_w_cm", 30.0)))
    host.spin_cage_w.valueChanged.connect(host._on_cage_size_changed)
    host.lbl_cage_x = QLabel("×")
    host.lbl_cage_h = QLabel("Height:")
    host.spin_cage_h = QDoubleSpinBox()
    host.spin_cage_h.setRange(0.1, 9999.0)
    host.spin_cage_h.setDecimals(1)
    host.spin_cage_h.setSingleStep(1.0)
    host.spin_cage_h.setSuffix(" cm")
    host.spin_cage_h.setFixedWidth(80)
    host.spin_cage_h.setFixedHeight(24)
    host.spin_cage_h.setValue(float(host.config.get("cage_h_cm", 30.0)))
    host.spin_cage_h.valueChanged.connect(host._on_cage_size_changed)
    size_row.addWidget(host.lbl_cage_w)
    size_row.addWidget(host.spin_cage_w)
    size_row.addWidget(host.lbl_cage_x)
    size_row.addWidget(host.lbl_cage_h)
    size_row.addWidget(host.spin_cage_h)
    size_row.addStretch()
    auto_v.addWidget(host._cage_size_widget)

    host.lbl_calib_auto_hint = QLabel("Cage shape = Custom — Auto unavailable.")
    host.lbl_calib_auto_hint.setStyleSheet("color:#888; font-size:10px;")
    host.lbl_calib_auto_hint.setVisible(False)
    auto_v.addWidget(host.lbl_calib_auto_hint)
    layout.addWidget(host._calib_auto_widget)

    # Manual sub-panel: draw line + real length spinbox.
    host._calib_manual_widget = QWidget()
    man_v = QVBoxLayout(host._calib_manual_widget)
    man_v.setContentsMargins(14, 0, 0, 0)
    man_v.setSpacing(2)

    host.btn_calib = host._btn("Draw Line")
    host.btn_calib.setEnabled(False)
    host.btn_calib.clicked.connect(host._start_draw_calib)
    host.btn_clear_calib = host._btn("Clear", width=50)
    host.btn_clear_calib.setEnabled(False)
    host.btn_clear_calib.clicked.connect(host._clear_calib)
    man_v.addLayout(host._row(host.btn_calib, host.btn_clear_calib))

    dist_row = QHBoxLayout()
    dist_row.addWidget(QLabel("Real length:"))
    host.spin_cm = QDoubleSpinBox()
    host.spin_cm.setRange(0.1, 9999)
    host.spin_cm.setValue(30.0)
    host.spin_cm.setSuffix(" cm")
    host.spin_cm.setFixedWidth(95)
    host.spin_cm.valueChanged.connect(host._on_calib_cm_changed)
    dist_row.addWidget(host.spin_cm)
    dist_row.addStretch()
    man_v.addLayout(dist_row)
    layout.addWidget(host._calib_manual_widget)

    # Status row.
    host.lbl_calib = QLabel("Not calibrated — distances will be in pixels")
    host.lbl_calib.setWordWrap(True)
    host.lbl_calib.setStyleSheet("color:#888; font-size:11px;")
    layout.addWidget(host.lbl_calib)

    # Initial mode: prefer config; legacy snapshots default to Auto.
    saved_mode = host.config.get("calib_mode", "auto")
    if saved_mode == "manual":
        host.rb_calib_manual.setChecked(True)
    elif saved_mode == "none":
        host.rb_calib_none.setChecked(True)
    else:
        host.rb_calib_auto.setChecked(True)
    host.calib_mode_group.buttonToggled.connect(host._on_calib_mode_changed)
    host._refresh_cage_size_inputs()
    host._refresh_calib_mode_visibility()
    return grp
