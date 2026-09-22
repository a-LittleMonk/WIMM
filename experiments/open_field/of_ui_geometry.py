"""Step 2 — Geometry UI builder.

The big block that puts together: arena-define dropdown (manual / auto
contrast / auto movement), padding, perspective + cage-shape advanced
toggles, zone style combo, center-zone % spinner, zone-color picker.
Also the on-change handler for the zone-mode combo.
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox,
    QToolButton, QMenu,
)


def _step_geometry_of(host):
    grp = host._group("Step 2 — Geometry", status_id="geometry")
    layout = QVBoxLayout(grp)
    layout.setSpacing(4)

    # ── Arena: define mode dropdown
    host.btn_define_arena = QToolButton()
    host.btn_define_arena.setText("Define arena ▾")
    host.btn_define_arena.setPopupMode(QToolButton.InstantPopup)
    host.btn_define_arena.setEnabled(False)
    host.btn_define_arena.setStyleSheet("padding:4px 10px;")
    # Lock width to longest mode label so the button doesn't resize as
    # the user picks different modes.
    _fm = host.btn_define_arena.fontMetrics()
    _arena_btn_labels = [
        "Define arena ▾",
        "Manual — click 4 corners ▾",
        "Premade square arena ▾",
        "Auto — from movement (next run) ▾",
    ]
    _w = max(_fm.horizontalAdvance(t) for t in _arena_btn_labels) + 28
    host.btn_define_arena.setFixedWidth(_w)
    host.btn_define_arena.setFixedHeight(26)
    menu = QMenu(host.btn_define_arena)
    def _wire(label, fn, mode_key, clear_movement=True):
        act = menu.addAction(label)
        def run(_checked=False, lbl=label, f=fn, mk=mode_key,
                clr=clear_movement):
            if clr:
                host._arena_auto_movement = False
            host._arena_define_mode = mk
            host.btn_define_arena.setText(f"{lbl} ▾")
            host._refresh_arena_mode_chip()
            f()
        act.triggered.connect(run)
        return act
    _wire("Manual — click 4 corners", host._start_draw_arena, "manual")
    act_square = _wire("Premade square arena",
                        host._apply_premade_square_arena, "square")
    act_square.setToolTip(
        "Drop a centered square arena (80% of the shorter video side). "
        "Drag the corners to fine-tune."
    )

    # "Auto — from movement (next run)" is gated behind an Extra Features
    # toggle (off by default). Re-enable from launcher → Settings → Extra
    # features. The default-assignment code in experiment_tab /
    # experiment_batch_tab is gated on the same flag.
    if host.config.get("enable_auto_movement_arena", False):
        act_movement = _wire("Auto — from movement (next run)",
                              host._enable_auto_movement_arena,
                              "movement", clear_movement=False)
        act_movement.setToolTip(
            "Don't define an arena now. On the next tracking run, the arena "
            "will be auto-built from the convex hull of the mouse's path "
            "(simplified to a 4-sided polygon). Shape grows live as the "
            "mouse moves."
        )
    host.btn_define_arena.setMenu(menu)

    host.btn_clear_arena = host._btn("Clear", width=50)
    host.btn_clear_arena.setEnabled(False)
    host.btn_clear_arena.clicked.connect(host._clear_arena)
    layout.addLayout(host._row(host.btn_define_arena, host.btn_clear_arena))

    # Padding — only relevant for auto-movement mode.
    host._arena_pad_widget = QWidget()
    pad_row = QHBoxLayout(host._arena_pad_widget)
    pad_row.setContentsMargins(0, 0, 0, 0)
    pad_row.addWidget(QLabel("Auto-arena padding:"))
    host.spin_arena_pad_pct = QDoubleSpinBox()
    host.spin_arena_pad_pct.setRange(0.0, 50.0)
    host.spin_arena_pad_pct.setDecimals(1)
    host.spin_arena_pad_pct.setSingleStep(1.0)
    host.spin_arena_pad_pct.setSuffix(" %")
    host.spin_arena_pad_pct.setFixedWidth(75)
    host.spin_arena_pad_pct.setFixedHeight(24)
    host.spin_arena_pad_pct.setValue(5.0)
    host.spin_arena_pad_pct.setToolTip(
        "Pad the auto-detected arena outward by this fraction of its "
        "size — mice rarely touch the wall, so without padding the "
        "arena ends up smaller than the real cage."
    )
    pad_row.addWidget(host.spin_arena_pad_pct)
    pad_row.addStretch()
    layout.addWidget(host._arena_pad_widget)
    host._arena_pad_widget.setVisible(False)

    # Backwards-compat alias used elsewhere when enabling controls.
    host.btn_arena = host.btn_define_arena
    host.btn_auto_arena = host.btn_define_arena

    # Perspective + cage shape — advanced (hidden in Simple).
    persp_widget = QWidget()
    pv = QVBoxLayout(persp_widget)
    pv.setContentsMargins(0, 0, 0, 0)
    pv.setSpacing(4)
    pv.addWidget(host._sep())
    host.chk_perspective = QCheckBox("Correct perspective")
    host.chk_perspective.setStyleSheet("font-size:11px;")
    host.chk_perspective.setToolTip(
        "Warp video so the arena trapezoid becomes a true axis-aligned rectangle.\n"
        "Use when camera is at an angle. Improves distance/speed accuracy.\n"
        "Requires arena to be drawn first. Toggle off to return to original view."
    )
    host.chk_perspective.setEnabled(False)
    host.chk_perspective.toggled.connect(host._on_perspective_toggled)
    host._perspective_widget = host.chk_perspective
    pv.addWidget(host.chk_perspective)

    host._cage_shape_widget = QWidget()
    shape_row = QHBoxLayout(host._cage_shape_widget)
    shape_row.setContentsMargins(0, 0, 0, 0)
    shape_row.addWidget(QLabel("Cage shape:"))
    host.combo_cage_shape = QComboBox()
    host.combo_cage_shape.addItem("Rectangle", "rectangle")
    host.combo_cage_shape.addItem("Square",    "square")
    host.combo_cage_shape.addItem("Custom",    "custom")
    host.combo_cage_shape.setFixedHeight(24)
    host.combo_cage_shape.setToolTip(
        "Physical cage shape — applies to perspective correction, graphs,\n"
        "and auto-calibration when real-world dimensions are entered.\n"
        "Custom: skip auto-calibration; use the manual calibration line."
    )
    idx = host.combo_cage_shape.findData(host.config.get("cage_shape", "rectangle"))
    if idx >= 0:
        host.combo_cage_shape.setCurrentIndex(idx)
    host.combo_cage_shape.currentIndexChanged.connect(host._on_cage_shape_changed)
    shape_row.addWidget(host.combo_cage_shape)
    shape_row.addStretch()
    pv.addWidget(host._cage_shape_widget)
    layout.addWidget(persp_widget)
    host._advanced_widgets.append(persp_widget)

    layout.addWidget(host._sep())

    # ── Zones (style + center % + colors)
    zone_hdr = QLabel("Zones")
    zone_hdr.setStyleSheet("color:#aaa; font-size:11px; font-weight:bold;")
    layout.addWidget(zone_hdr)

    # Zone style combo — advanced.
    zone_style_widget = QWidget()
    mode_row = QHBoxLayout(zone_style_widget)
    mode_row.setContentsMargins(0, 0, 0, 0)
    mode_row.addWidget(QLabel("Zone style:"))
    host.combo_zone_mode = QComboBox()
    host.combo_zone_mode.addItem("Center only",        "center_zone")
    host.combo_zone_mode.addItem("Grid 4×4 + center",  "grid")
    host.combo_zone_mode.setFixedHeight(24)
    host.combo_zone_mode.setToolTip(
        "Center only: classic open-field (center zone vs periphery).\n"
        "Grid 4×4 + center: arena split into 16 cells with a center zone rectangle on top."
    )
    _saved_mode = host.config.get("zone_mode", "center_zone")
    if _saved_mode == "center":  # legacy upgrade
        _saved_mode = "center_zone"
    idx = host.combo_zone_mode.findData(_saved_mode)
    if idx >= 0:
        host.combo_zone_mode.setCurrentIndex(idx)
    host.combo_zone_mode.currentIndexChanged.connect(host._on_zone_mode_changed)
    mode_row.addWidget(host.combo_zone_mode)
    mode_row.addStretch()
    layout.addWidget(zone_style_widget)
    host._advanced_widgets.append(zone_style_widget)

    center_row = QHBoxLayout()
    center_row.addWidget(QLabel("Center zone:"))
    host.spin_center_pct = QSpinBox()
    host.spin_center_pct.setRange(1, 99)
    host.spin_center_pct.setValue(50)
    host.spin_center_pct.setSuffix(" %")
    host.spin_center_pct.setFixedWidth(65)
    host.spin_center_pct.setFixedHeight(24)
    host.spin_center_pct.setToolTip("% of arena size for the auto-drawn center zone")
    host.spin_center_pct.valueChanged.connect(host._compute_center)
    def _log_center_pct(v):
        try:
            from core import logger
            logger.info(
                f"Center zone size → {int(v)}% | zone_mode={host.zone_drawer.zone_mode}",
                source="zones",
            )
        except Exception:
            pass
    host.spin_center_pct.editingFinished.connect(
        lambda: _log_center_pct(host.spin_center_pct.value())
    )
    center_row.addWidget(host.spin_center_pct)
    center_row.addStretch()
    layout.addLayout(center_row)

    # Zone colors — advanced.
    zone_colors_widget = QWidget()
    zone_color_row = QHBoxLayout(zone_colors_widget)
    zone_color_row.setContentsMargins(0, 0, 0, 0)
    zone_color_row.setSpacing(4)
    host.btn_zone_colors = host._btn("Colors", width=70)
    host.btn_zone_colors.setToolTip("Open color picker for Arena, Center Zone, Grid")
    host.btn_zone_colors.clicked.connect(host._open_zone_colors_dialog)
    zone_color_row.addWidget(host.btn_zone_colors)
    zone_color_row.addStretch()
    layout.addWidget(zone_colors_widget)
    host._advanced_widgets.append(zone_colors_widget)

    host.lbl_zones = QLabel("No zones defined")
    host.lbl_zones.setWordWrap(True)
    host.lbl_zones.setStyleSheet("color:#888; font-size:11px;")
    layout.addWidget(host.lbl_zones)
    return grp


def _on_zone_mode_changed(host):
    mode = host.combo_zone_mode.currentData()
    host.zone_drawer.set_zone_mode(mode)
    host.config["zone_mode"] = mode
    host.spin_center_pct.blockSignals(True)
    host.spin_center_pct.setValue(25 if mode == "grid" else 50)
    host.spin_center_pct.blockSignals(False)
    try:
        from core import logger
        logger.info(
            f"Zone mode → {mode} | center_pct={host.spin_center_pct.value()}",
            source="zones",
        )
    except Exception:
        pass
    win = host.window()
    if hasattr(win, "_save_config"):
        win._save_config()
    host._compute_center()
