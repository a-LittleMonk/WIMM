"""Steps 1–2 — Video info card and Animal metadata card.

Shared across experiments. Builder takes the host tab and assigns the
expected widget attributes onto it. Both accordion cards register with the
host through `host._group()`; the Animal card is Full-mode only.
"""
from PyQt5.QtWidgets import (
    QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QSizePolicy, QVBoxLayout, QWidget,
)

from gui import theme
from gui.widgets_v2 import ElidingLabel, field, form_row, mono_font


def _mono_label(text="—"):
    lb = QLabel(text)
    lb.setFont(mono_font(11))
    return lb


def build_source_step(host):
    """Build the Video + Animal cards. Sets attributes on host:
        lbl_video, lbl_fps_detected, spin_fps_override, lbl_resolution,
        lbl_trim_val, edit_meta_id, edit_meta_group, combo_meta_sex,
        edit_meta_date, edit_meta_trial, edit_meta_notes, _recent_btns
    Appends advanced widgets to host._advanced_widgets.
    Returns the Video card (the Animal card is registered via _group too).
    """
    grp = host._group("Step 1 — Source", status_id="source", name="Video")
    layout = QVBoxLayout(grp)

    host.lbl_video = ElidingLabel("No video loaded")
    host.lbl_video.setFont(mono_font(11))
    layout.addWidget(form_row("File", host.lbl_video))

    host.lbl_resolution = _mono_label()
    layout.addWidget(form_row("Resolution", host.lbl_resolution))

    fps_box = QWidget()
    fh = QHBoxLayout(fps_box)
    fh.setContentsMargins(0, 0, 0, 0)
    fh.setSpacing(4)
    host.lbl_fps_detected = _mono_label()
    fh.addWidget(host.lbl_fps_detected)
    host.lbl_fps_src = QLabel("· detected")
    theme.set_tone(host.lbl_fps_src, "ok")
    fh.addWidget(host.lbl_fps_src)
    fh.addStretch(1)
    layout.addWidget(form_row("Frame rate", fps_box))

    # FPS override — Full mode only.
    host.spin_fps_override = QDoubleSpinBox()
    host.spin_fps_override.setRange(0.0, 1000.0)
    host.spin_fps_override.setDecimals(2)
    host.spin_fps_override.setValue(0.0)
    host.spin_fps_override.setSpecialValueText("Auto")
    host.spin_fps_override.setSuffix(" fps")
    host.spin_fps_override.setToolTip("Manual FPS override. 0 = auto-detect from video.")
    host.spin_fps_override.valueChanged.connect(host._on_fps_override_changed)
    fps_row = form_row("FPS override", host.spin_fps_override)
    layout.addWidget(fps_row)
    host._advanced_widgets.append(fps_row)

    host.lbl_trim_val = _mono_label()
    layout.addWidget(form_row("Trim", host.lbl_trim_val))
    # Recent-videos buttons removed — videos are loaded via the batch
    # tab's row list. _push_recent/_refresh_recent_buttons are no-ops now.
    host._recent_btns = []

    # ── Animal card (Full mode) ──────────────────────────────────────────
    ag = host._group("Animal metadata", status_id="animal", name="Animal")
    host._advanced_widgets.append(ag)
    av = QVBoxLayout(ag)
    grid = QGridLayout()
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(8)
    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)

    def _line(placeholder, mono=False):
        w = QLineEdit()
        w.setPlaceholderText(placeholder)
        if mono:
            w.setFont(mono_font(11))
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return w

    host.edit_meta_id = _line("e.g. M01", True)
    host.edit_meta_group = _line("e.g. Saline / KO")
    host.combo_meta_sex = QComboBox()
    host.combo_meta_sex.addItems(["", "Male", "Female"])
    host.edit_meta_trial = _line("e.g. 1", True)
    host.edit_meta_date = _line("YYYY-MM-DD", True)
    host.edit_meta_notes = _line("free text")
    grid.addWidget(field("Animal ID", host.edit_meta_id), 0, 0)
    grid.addWidget(field("Group", host.edit_meta_group), 0, 1)
    grid.addWidget(field("Sex", host.combo_meta_sex), 1, 0)
    grid.addWidget(field("Trial #", host.edit_meta_trial), 1, 1)
    grid.addWidget(field("Date", host.edit_meta_date), 2, 0, 1, 2)
    grid.addWidget(field("Notes", host.edit_meta_notes), 3, 0, 1, 2)
    av.addLayout(grid)
    return grp
