"""Step 2 — Geometry UI builder.

The big block that puts together: arena-define dropdown (manual / auto
contrast / auto movement), padding, perspective + cage-shape advanced
toggles, zone style combo, center-zone % spinner, zone-color picker.
Also the on-change handler for the zone-mode combo.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox,
    QToolButton, QMenu,
)
from gui.info_box import attach_info_box


from gui import theme


def _step_geometry_of(host):
    """Arena card (define mode, redraw / clear, cage shape, perspective) and
    Zones card (style tiles, center %, colors)."""
    from PyQt5.QtWidgets import QSlider
    from gui.widgets_v2 import (
        ArenaModeButton, ColorButtons, IconButton, SwitchBox, ToggleTile, form_row,
        mono_font,
    )
    from experiments import common_ui
    grp, layout = common_ui.arena_card(host)

    # ── Arena: define mode select + Redraw + clear
    host.btn_define_arena = ArenaModeButton()
    host.btn_define_arena.setText("Define arena")
    host.btn_define_arena.setEnabled(False)
    menu = QMenu(host.btn_define_arena)
    _actions = {}

    def _wire(label, fn, mode_key):
        act = menu.addAction(label)
        _actions[mode_key] = (label, fn)

        def run(_checked=False, lbl=label, f=fn, mk=mode_key):
            host._arena_define_mode = mk
            host.btn_define_arena.setText(lbl)
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

    host.btn_define_arena.setMenu(menu)

    def _redraw():
        mk = getattr(host, "_arena_define_mode", None) or "manual"
        label, fn = _actions.get(mk, _actions["manual"])
        host._arena_define_mode = mk
        host.btn_define_arena.setText(label)
        fn()

    host.btn_redraw_arena = host._btn("Redraw")
    host.btn_redraw_arena.setFixedHeight(28)
    host.btn_redraw_arena.setEnabled(False)
    host.btn_redraw_arena.clicked.connect(_redraw)
    host.btn_clear_arena = IconButton("x", 11, "FAINT", "TEXT", "Clear arena", 28)
    host.btn_clear_arena.setEnabled(False)
    host.btn_clear_arena.clicked.connect(host._clear_arena)
    host.btn_define_arena.follow(host.btn_redraw_arena)
    host.btn_define_arena.follow(host.btn_clear_arena)
    arow = QHBoxLayout()
    arow.setSpacing(6)
    arow.addWidget(host.btn_define_arena, 1)
    arow.addWidget(host.btn_redraw_arena)
    arow.addWidget(host.btn_clear_arena)
    layout.addLayout(arow)

    # Backwards-compat alias used elsewhere when enabling controls.
    host.btn_arena = host.btn_define_arena
    host.btn_auto_arena = host.btn_define_arena

    # Perspective + cage shape — advanced (hidden in Simple).
    persp_widget = QWidget()
    pv = QVBoxLayout(persp_widget)
    pv.setContentsMargins(0, 0, 0, 0)
    pv.setSpacing(7)
    host._cage_shape_widget = QWidget()
    shape_row = QHBoxLayout(host._cage_shape_widget)
    shape_row.setContentsMargins(0, 0, 0, 0)
    host.combo_cage_shape = QComboBox()
    host.combo_cage_shape.addItem("Rectangle", "rectangle")
    host.combo_cage_shape.addItem("Square",    "square")
    host.combo_cage_shape.addItem("Custom",    "custom")
    host.combo_cage_shape.setToolTip(
        "Physical cage shape — applies to perspective correction, graphs,\n"
        "and auto-calibration when real-world dimensions are entered.\n"
        "Custom: skip auto-calibration; use the manual calibration line."
    )
    idx = host.combo_cage_shape.findData(host.config.get("cage_shape", "rectangle"))
    if idx >= 0:
        host.combo_cage_shape.setCurrentIndex(idx)
    host.combo_cage_shape.currentIndexChanged.connect(host._on_cage_shape_changed)
    shape_row.addWidget(host.combo_cage_shape, 1)
    pv.addWidget(form_row("Cage shape", host._cage_shape_widget))
    host.chk_perspective = SwitchBox("Correct perspective")
    host.chk_perspective.setToolTip(
        "Warp video so the arena trapezoid becomes a true axis-aligned rectangle.\n"
        "Use when camera is at an angle. Improves distance/speed accuracy.\n"
        "Requires arena to be drawn first. Toggle off to return to original view."
    )
    host.chk_perspective.setEnabled(False)
    host.chk_perspective.toggled.connect(host._on_perspective_toggled)
    host._perspective_widget = host.chk_perspective
    pv.addWidget(host.chk_perspective)
    layout.addWidget(persp_widget)
    host._advanced_widgets.append(persp_widget)

    attach_info_box(grp, [
        ("Premade square arena", act_square.toolTip()),
        ("Correct perspective", host.chk_perspective),
        ("Cage shape", host.combo_cage_shape),
    ])
    act_square.setToolTip("")

    # ── Zones card ───────────────────────────────────────────────────────
    zg, zl = common_ui.zones_card(host)

    # Zone style — hidden data holder (combo) + two tiles that drive it.
    host.combo_zone_mode = QComboBox()
    host.combo_zone_mode.addItem("Center + periphery", "center_zone")
    host.combo_zone_mode.addItem("Grid 4×4 + center",  "grid")
    host.combo_zone_mode.setToolTip(
        "Center + periphery: classic open-field (center zone vs periphery).\n"
        "Grid 4×4 + center: arena split into 16 cells with a center zone rectangle on top."
    )
    _saved_mode = host.config.get("zone_mode", "center_zone")
    if _saved_mode == "center":  # legacy upgrade
        _saved_mode = "center_zone"
    idx = host.combo_zone_mode.findData(_saved_mode)
    if idx >= 0:
        host.combo_zone_mode.setCurrentIndex(idx)
    host.combo_zone_mode.currentIndexChanged.connect(host._on_zone_mode_changed)
    host.combo_zone_mode.hide()
    host.combo_zone_mode._keep_hidden = True   # the two tiles are the control;
                                               # opening the card must not show it
    zone_style_widget = QWidget()
    tiles = QHBoxLayout(zone_style_widget)
    tiles.setContentsMargins(0, 0, 0, 0)
    tiles.setSpacing(6)
    tile_center = ToggleTile("zone_center", "Center + periphery")
    tile_grid = ToggleTile("zone_grid", "Grid 4×4")
    tile_grid.setToolTip("Grid 4×4 + center")
    tiles.addWidget(tile_center)
    tiles.addWidget(tile_grid)

    def _tile_from_combo(*_):
        grid = host.combo_zone_mode.currentData() == "grid"
        tile_center.setChecked(not grid)
        tile_grid.setChecked(grid)
    tile_center.clicked.connect(lambda: host.combo_zone_mode.setCurrentIndex(0) or _tile_from_combo())
    tile_grid.clicked.connect(lambda: host.combo_zone_mode.setCurrentIndex(1) or _tile_from_combo())
    host.combo_zone_mode.currentIndexChanged.connect(_tile_from_combo)
    _tile_from_combo()
    zl.addWidget(zone_style_widget)
    zl.addWidget(host.combo_zone_mode)
    host._advanced_widgets.append(zone_style_widget)

    # Center zone %: hidden spin (data / signal source) + visible slider.
    host.spin_center_pct = QSpinBox()
    host.spin_center_pct.setRange(1, 99)
    host.spin_center_pct.setValue(50)
    host.spin_center_pct.setSuffix(" %")
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
    host.spin_center_pct.hide()
    host.spin_center_pct._keep_hidden = True   # the slider is the control
    zl.addWidget(host.spin_center_pct)
    host.slider_center_pct = QSlider(Qt.Horizontal)
    host.slider_center_pct.setRange(10, 90)
    host.slider_center_pct.setValue(50)
    host.slider_center_pct.setMinimumHeight(22)
    from gui.widgets_v2 import ValueEdit
    host.lbl_center_pct = ValueEdit(host.slider_center_pct, lambda v: f"{int(v)}%", role="valuepill")
    host.lbl_center_pct.setAlignment(Qt.AlignCenter)
    host.lbl_center_pct.setFixedWidth(44)
    host.lbl_center_pct.setFont(mono_font(11))
    srow = QHBoxLayout()
    srow.setContentsMargins(0, 0, 0, 0)
    srow.setSpacing(8)
    srow.addWidget(host.slider_center_pct, 1)
    srow.addWidget(host.lbl_center_pct)

    def _slider_to_spin(v):
        host.spin_center_pct.setValue(int(v))

    def _spin_to_slider(v):
        host.slider_center_pct.blockSignals(True)
        host.slider_center_pct.setValue(max(host.slider_center_pct.minimum(),
                                            min(host.slider_center_pct.maximum(), int(v))))
        host.slider_center_pct.blockSignals(False)
        host.lbl_center_pct.show_value(v)
    host.slider_center_pct.valueChanged.connect(_slider_to_spin)
    host.spin_center_pct.valueChanged.connect(_spin_to_slider)
    zl.addWidget(form_row("Center zone", srow))

    host.lbl_center_area = QLabel("—")
    host.lbl_center_area.setFont(mono_font(11))
    zl.addWidget(form_row("Center area", host.lbl_center_area, min_h=22))

    # Zone colors — advanced. One button per zone (with a swatch of its
    # colour); each opens the colour picker on that zone.
    host._zone_chips = ColorButtons(
        lambda: host._colors,
        [("arena", "Arena"), ("center_zone", "Center"), ("grid", "Grid")])
    host._zone_chips.picked.connect(host._open_zone_colors_dialog)
    zl.addWidget(host._zone_chips)
    host._advanced_widgets.append(host._zone_chips)

    host.lbl_zones = QLabel("No zones defined")
    host.lbl_zones.setWordWrap(True)
    theme.set_tone(host.lbl_zones, "faint", "font-size:11px;")
    zl.addWidget(host.lbl_zones)

    attach_info_box(zg, [
        ("Zone style", host.combo_zone_mode),
        ("Center zone", host.spin_center_pct),
        ("Colors", "Click Arena, Center or Grid to change the color that "
                   "zone is drawn in on the video."),
    ])
    return grp


def _on_zone_mode_changed(host):
    mode = host.combo_zone_mode.currentData()
    host.zone_drawer.set_zone_mode(mode)
    host.config["zone_mode"] = mode
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
