"""Step 3 — Scale (px↔cm calibration via auto / manual line / pixels mode).

Shared across experiments. Builder takes the host tab and assigns the
expected widget attributes onto it.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QButtonGroup, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QRadioButton,
    QVBoxLayout, QWidget,
)

from gui import theme
from gui.widgets_v2 import SegTabs

# Default Scale = Auto from a 50 × 50 cm cage (Open Field / NOR arenas).
DEFAULT_CAGE_CM = 50.0


def build_scale_step(host):
    """Build the Scale card. Sets attributes on host:
        calib_mode_group, rb_calib_auto, rb_calib_manual, rb_calib_none,
        spin_cage_w, spin_cage_h, lbl_cage_w, lbl_cage_x, lbl_cage_h,
        _calib_auto_widget, _cage_size_widget, lbl_calib_auto_hint,
        _calib_manual_widget, btn_calib, btn_clear_calib, spin_cm,
        lbl_calib
    The three radio buttons stay as the data holder (hidden); a segmented
    selector drives them.
    """
    grp = host._group("Step 3 — Scale", status_id="scale", optional=True, name="Scale")
    layout = QVBoxLayout(grp)

    host.calib_mode_group = QButtonGroup(grp)
    host.rb_calib_auto   = QRadioButton("Auto from cage size")
    host.rb_calib_manual = QRadioButton("Manual line")
    host.rb_calib_none   = QRadioButton("None (pixels)")
    radios = (host.rb_calib_auto, host.rb_calib_manual, host.rb_calib_none)
    for i, rb in enumerate(radios):
        host.calib_mode_group.addButton(rb, i)
        rb._keep_hidden = True   # opening the card must not re-show it
        rb.hide()
        layout.addWidget(rb)

    seg = SegTabs(["Auto · cage", "Manual line", "None (px)"])
    host._calib_seg = seg
    layout.addWidget(seg)

    def _seg_to_radio(i):
        radios[i].setChecked(True)

    def _radio_to_seg(*_):
        for i, rb in enumerate(radios):
            if rb.isChecked():
                seg.set_index(i)
    seg.changed.connect(_seg_to_radio)
    host.calib_mode_group.buttonToggled.connect(_radio_to_seg)

    # Auto sub-panel: cage real-world dimensions (Width × Height).
    host._calib_auto_widget = QWidget()
    auto_v = QVBoxLayout(host._calib_auto_widget)
    auto_v.setContentsMargins(0, 0, 0, 0)
    auto_v.setSpacing(4)

    host._cage_size_widget = QWidget()
    size_row = QGridLayout(host._cage_size_widget)
    size_row.setContentsMargins(0, 0, 0, 0)
    size_row.setHorizontalSpacing(6)
    size_row.setColumnStretch(0, 1)
    size_row.setColumnStretch(2, 1)
    host.lbl_cage_w = QLabel("Width")     # kept for visibility toggles
    host.lbl_cage_x = QLabel("×")
    host.lbl_cage_h = QLabel("Height")
    host.spin_cage_w = QDoubleSpinBox()
    host.spin_cage_w.setRange(0.1, 9999.0)
    host.spin_cage_w.setDecimals(1)
    host.spin_cage_w.setSingleStep(1.0)
    host.spin_cage_w.setSuffix(" cm")
    host.spin_cage_w.setValue(float(host.config.get("cage_w_cm", DEFAULT_CAGE_CM)))
    host.spin_cage_w.valueChanged.connect(host._on_cage_size_changed)
    host.spin_cage_h = QDoubleSpinBox()
    host.spin_cage_h.setRange(0.1, 9999.0)
    host.spin_cage_h.setDecimals(1)
    host.spin_cage_h.setSingleStep(1.0)
    host.spin_cage_h.setSuffix(" cm")
    host.spin_cage_h.setValue(float(host.config.get("cage_h_cm", DEFAULT_CAGE_CM)))
    host.spin_cage_h.valueChanged.connect(host._on_cage_size_changed)
    theme.set_tone(host.lbl_cage_x, "faint")

    def _captioned(caption_lbl, spin):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        theme.set_tone(caption_lbl, "text2", "font-size:10.5px;")
        v.addWidget(caption_lbl)
        v.addWidget(spin)
        return box
    size_row.addWidget(_captioned(host.lbl_cage_w, host.spin_cage_w), 0, 0)
    size_row.addWidget(host.lbl_cage_x, 0, 1, Qt.AlignBottom)
    size_row.addWidget(_captioned(host.lbl_cage_h, host.spin_cage_h), 0, 2)
    auto_v.addWidget(host._cage_size_widget)

    host.lbl_calib_auto_hint = QLabel("Cage shape = Custom — Auto unavailable.")
    theme.set_tone(host.lbl_calib_auto_hint, "faint", "font-size:10px;")
    host.lbl_calib_auto_hint.setVisible(False)
    auto_v.addWidget(host.lbl_calib_auto_hint)
    layout.addWidget(host._calib_auto_widget)

    # Manual sub-panel: draw line + real length spinbox.
    host._calib_manual_widget = QWidget()
    man_v = QHBoxLayout(host._calib_manual_widget)
    man_v.setContentsMargins(0, 0, 0, 0)
    man_v.setSpacing(6)

    host.btn_calib = host._btn("Draw line")
    host.btn_calib.setFixedHeight(28)
    host.btn_calib.setEnabled(False)
    host.btn_calib.clicked.connect(host._start_draw_calib)
    host.btn_clear_calib = host._btn("Clear")
    host.btn_clear_calib.setFixedHeight(28)
    host.btn_clear_calib.setProperty("flat", True)
    host.btn_clear_calib.setEnabled(False)
    host.btn_clear_calib.clicked.connect(host._clear_calib)
    host.spin_cm = QDoubleSpinBox()
    host.spin_cm.setRange(0.0, 9999)   # 0 is refused with a message (no silent change)
    host.spin_cm.setValue(30.0)
    host.spin_cm.setSuffix(" cm")
    host.spin_cm.valueChanged.connect(host._on_calib_cm_changed)
    man_v.addWidget(host.btn_calib)
    man_v.addWidget(host.btn_clear_calib)
    man_v.addWidget(host.spin_cm, 1)
    layout.addWidget(host._calib_manual_widget)

    # Status row.
    host.lbl_calib = QLabel("Not calibrated — distances will be in pixels")
    host.lbl_calib.setWordWrap(True)
    theme.set_tone(host.lbl_calib, "faint", "font-size:11px;")
    layout.addWidget(host.lbl_calib)

    # Initial mode: prefer config; legacy snapshots default to Auto.
    saved_mode = host.config.get("calib_mode", "auto")
    if saved_mode == "manual":
        host.rb_calib_manual.setChecked(True)
    elif saved_mode == "none":
        host.rb_calib_none.setChecked(True)
    else:
        host.rb_calib_auto.setChecked(True)
    _radio_to_seg()
    host.calib_mode_group.buttonToggled.connect(host._on_calib_mode_changed)
    host._refresh_cage_size_inputs()
    host._refresh_calib_mode_visibility()
    return grp
