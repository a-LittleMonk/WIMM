"""Step 1 — Source (video info, FPS override, resolution, metadata).

Shared across experiments. Builder takes the host tab and assigns the
expected widget attributes onto it. Caller appends the returned group
box to its config layout.
"""
from PyQt5.QtWidgets import (
    QLabel, QWidget, QHBoxLayout, QVBoxLayout, QDoubleSpinBox, QSpinBox,
    QComboBox, QLineEdit, QSizePolicy,
)


def build_source_step(host):
    """Build the Source group box. Sets attributes on host:
        lbl_video, lbl_fps_detected, spin_fps_override, lbl_resolution,
        edit_meta_id, edit_meta_group, combo_meta_sex,
        edit_meta_date, edit_meta_trial, edit_meta_notes,
        _recent_btns
    Appends advanced widgets to host._advanced_widgets.
    """
    grp = host._group("Step 1 — Source", status_id="source")
    layout = QVBoxLayout(grp)
    layout.setSpacing(4)
    host.lbl_video = QLabel("No video loaded")
    host.lbl_video.setWordWrap(True)
    host.lbl_video.setStyleSheet("color:#888; font-size:11px;")
    layout.addWidget(host.lbl_video)

    # FPS row — advanced (FPS override hidden in Simple).
    fps_widget = QWidget()
    fps_row = QHBoxLayout(fps_widget)
    fps_row.setContentsMargins(0, 0, 0, 0)
    fps_row.setSpacing(4)
    fps_row.addWidget(QLabel("FPS:"))
    host.lbl_fps_detected = QLabel("—")
    host.lbl_fps_detected.setStyleSheet("font-size:11px; color:#aaa;")
    host.lbl_fps_detected.setFixedWidth(50)
    fps_row.addWidget(host.lbl_fps_detected)
    fps_row.addWidget(QLabel("Override:"))
    host.spin_fps_override = QDoubleSpinBox()
    host.spin_fps_override.setRange(0.0, 1000.0)
    host.spin_fps_override.setDecimals(2)
    host.spin_fps_override.setValue(0.0)
    host.spin_fps_override.setSpecialValueText("Auto")
    host.spin_fps_override.setFixedWidth(80)
    host.spin_fps_override.setFixedHeight(24)
    host.spin_fps_override.setToolTip("Manual FPS override. 0 = auto-detect from video.")
    host.spin_fps_override.valueChanged.connect(host._on_fps_override_changed)
    fps_row.addWidget(host.spin_fps_override)
    fps_row.addStretch()
    layout.addWidget(fps_widget)
    host._advanced_widgets.append(fps_widget)

    res_row = QHBoxLayout()
    res_row.setSpacing(4)
    res_row.addWidget(QLabel("Resolution:"))
    host.lbl_resolution = QLabel("—")
    host.lbl_resolution.setStyleSheet("font-size:11px; color:#aaa;")
    res_row.addWidget(host.lbl_resolution)
    res_row.addStretch()
    layout.addLayout(res_row)
    # Recent-videos buttons removed — videos are loaded via the batch
    # tab's row list. _push_recent/_refresh_recent_buttons are no-ops now.
    host._recent_btns = []

    # Metadata block — advanced.
    meta_widget = QWidget()
    mv = QVBoxLayout(meta_widget)
    mv.setContentsMargins(0, 0, 0, 0)
    mv.setSpacing(4)
    mv.addWidget(host._sep())
    meta_hdr = QLabel("Metadata (optional)")
    meta_hdr.setStyleSheet("color:#aaa; font-size:11px; font-weight:bold;")
    mv.addWidget(meta_hdr)

    def _field(label, placeholder, kind="line"):
        lbl = QLabel(label)
        lbl.setStyleSheet("font-size:10px; color:#aaa;")
        mv.addWidget(lbl)
        if kind == "combo":
            w = QComboBox()
        else:
            w = QLineEdit()
            w.setPlaceholderText(placeholder)
        w.setFixedHeight(22)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        mv.addWidget(w)
        return w

    host.edit_meta_id    = _field("Animal ID", "e.g. M01")
    host.edit_meta_group = _field("Group",     "e.g. Saline / KO")
    host.combo_meta_sex  = _field("Sex",       "", "combo")
    host.combo_meta_sex.addItems(["", "Male", "Female"])
    host.edit_meta_date  = _field("Date",      "YYYY-MM-DD")
    host.edit_meta_trial = _field("Trial #",   "e.g. 1")
    host.edit_meta_notes = _field("Notes",     "free text")
    layout.addWidget(meta_widget)
    host._advanced_widgets.append(meta_widget)
    return grp
