"""NOR Step 2 geometry pane + results tab.

Step 2 layout:
  ── Arena (delegates to host._start_draw_arena etc — same UX as OF) ──
  ── Object A: [name] [role] [shape] [Place] [size cm] [padding cm] [color] ──
  ── Object B: same ──
  ── Direction filter: [✓ Require nose facing] [angle deg] ──
  ── Clear objects ──
"""
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QDoubleSpinBox, QSpinBox, QPushButton, QToolButton, QMenu, QCheckBox,
    QColorDialog, QFrame,
)

from gui.info_box import attach_info_box
from .zones import (
    OBJECT_NAMES, OBJECT_LABELS, OBJECT_COLORS,
    SHAPE_CIRCLE, SHAPE_SQUARE, SHAPE_TRIANGLE, SHAPE_CUSTOM,
    SHAPE_LABELS, ROLE_NONE, ROLE_FAMILIAR, ROLE_NOVEL, ROLE_LABELS,
    CUSTOM_MIN_CORNERS, CUSTOM_MAX_CORNERS,
    default_object_state, build_schema,
    footprint_name, zone_name, empty_footprint_zone, empty_zone,
)


from gui import theme


def build_geometry_step(host):
    """Build the NOR geometry group. Returns a QGroupBox to drop into
    the Step 2 column of the tab.

    Side effects: seeds host._nor_objects with default state, registers
    a zones-changed bridge that rebuilds the schema whenever px/cm or
    video size changes, wires the per-object widgets to host attributes
    so apply_extras/snapshot_extras can round-trip the state.
    """
    if not hasattr(host, "_nor_objects"):
        host._nor_objects = {
            obj_id: default_object_state(obj_id) for obj_id in OBJECT_NAMES
        }
    host._nor_placing = None        # None | obj_id (set during click-to-place)
    host._nor_angle_enabled = False
    host._nor_angle_max_deg = 45.0

    grp = host._group("Step 2 — NOR geometry", status_id="geometry")
    layout = QVBoxLayout(grp)
    layout.setSpacing(4)

    # ── Arena (delegates to existing host methods) ──────────────────────
    from gui.widgets_v2 import ArenaModeButton, IconButton, SwitchBox
    arena_btn = ArenaModeButton()
    arena_btn.setText("Define arena")
    arena_menu = QMenu(arena_btn)

    def _arena_action(label, mode_key, fn):
        arena_menu.addAction(
            label,
            lambda: (_set_arena_mode(host, mode_key), arena_btn.setText(label), fn())
        )
    _arena_action("Manual — click 4 corners", "manual", host._start_draw_arena)
    _arena_action("Premade square arena", "square", host._apply_premade_square_arena)
    # "Auto — from movement (next run)" is gated behind an Extra Features
    # toggle (off by default). Re-enable from launcher → Settings → Extra
    # features.
    if host.config.get("enable_auto_movement_arena", False):
        _arena_action("Auto — from movement (next run)", "movement",
                      host._enable_auto_movement_arena)
    arena_btn.setMenu(arena_menu)
    host.btn_define_arena = arena_btn
    host.btn_arena = arena_btn
    host.btn_auto_arena = arena_btn
    btn_clear_arena = IconButton("x", 11, "FAINT", "TEXT", "Clear arena", 28)
    btn_clear_arena.clicked.connect(host._clear_arena)
    host.btn_clear_arena = btn_clear_arena
    arena_btn.follow(btn_clear_arena)
    arow = QHBoxLayout()
    arow.setSpacing(6)
    arow.addWidget(arena_btn, 1)
    arow.addWidget(btn_clear_arena)
    layout.addLayout(arow)

    # ── Perspective correction (warp arena → axis-aligned rect) ────────
    # Base ExperimentTab owns the toggle handler (_on_perspective_toggled)
    # and auto-enables the checkbox once the arena is drawn. Same hookup
    # OF uses — we just place the widget here so NOR has it on Step 2.
    host.chk_perspective = SwitchBox("Correct perspective")
    host.chk_perspective.setToolTip(
        "Warp video so the arena trapezoid becomes a true axis-aligned "
        "rectangle.\nUse when camera is at an angle. Improves distance / "
        "speed accuracy.\nRequires arena to be drawn first. Toggle off to "
        "return to original view."
    )
    host.chk_perspective.setEnabled(False)
    host.chk_perspective.toggled.connect(host._on_perspective_toggled)
    host._perspective_widget = host.chk_perspective
    layout.addWidget(host.chk_perspective)

    layout.addWidget(host._sep())

    # ── Object A + B blocks ─────────────────────────────────────────────
    host._nor_widgets = {}
    for obj_id in OBJECT_NAMES:
        layout.addWidget(_build_object_block(host, obj_id))
        layout.addWidget(host._sep())

    # ── Direction filter ────────────────────────────────────────────────
    angle_row = QHBoxLayout()
    chk = SwitchBox("Require nose facing object")
    chk.setToolTip(
        "Only count nose-in-zone frames when the nose also points toward "
        "the object center within the angle threshold. Helps reject "
        "frames where the mouse merely passes through the zone facing "
        "away from the object."
    )
    chk.toggled.connect(lambda on: _on_angle_toggled(host, on))
    host.chk_nor_angle = chk
    angle_row.addWidget(chk)
    spin = QDoubleSpinBox()
    spin.setRange(5.0, 180.0)
    spin.setDecimals(0)
    spin.setSingleStep(5.0)
    spin.setValue(45.0)
    spin.setSuffix(" °")
    spin.setFixedWidth(80)
    spin.setFixedHeight(24)
    spin.setEnabled(False)
    spin.valueChanged.connect(lambda v: setattr(host, "_nor_angle_max_deg", float(v)))
    host.spin_nor_angle = spin
    angle_row.addWidget(spin)
    angle_row.addStretch()
    layout.addLayout(angle_row)

    # ── Clear all objects ───────────────────────────────────────────────
    clear_row = QHBoxLayout()
    btn_clear_objs = host._btn("Clear objects", width=110)
    btn_clear_objs.clicked.connect(lambda: _clear_objects(host))
    clear_row.addWidget(btn_clear_objs)
    clear_row.addStretch()
    layout.addLayout(clear_row)

    # ── Status label ────────────────────────────────────────────────────
    host.lbl_nor_status = QLabel("Define arena + place both objects")
    host.lbl_nor_status.setWordWrap(True)
    theme.set_tone(host.lbl_nor_status, "faint", "font-size:11px;")
    layout.addWidget(host.lbl_nor_status)

    # ── Wire deferred init (zone_drawer is built later) ─────────────────
    def _wire():
        zd = getattr(host, "zone_drawer", None)
        if zd is None:
            QTimer.singleShot(0, _wire)
            return
        # Seed empty footprint + interaction zones so the user can see
        # them light up as soon as they place an object.
        for obj_id in OBJECT_NAMES:
            color = host._nor_objects[obj_id].get("color", OBJECT_COLORS[obj_id])
            zd.add_zone(empty_footprint_zone(obj_id, color))
            zd.add_zone(empty_zone(obj_id, color))
        try:
            zd.zones_changed.connect(lambda: _on_zones_changed(host))
        except Exception:
            pass
        # Rebuild NOR zones whenever scale inputs change (manual cm,
        # auto-cal cage W) so cm-based sizes stay accurate after calibration.
        for attr in ("spin_cm", "spin_cage_w", "spin_cage_h"):
            spin = getattr(host, attr, None)
            if spin is not None:
                try:
                    spin.valueChanged.connect(lambda _v: _refresh_zones(host))
                except Exception:
                    pass
        _refresh_zones(host)
        _refresh_status(host)
    QTimer.singleShot(0, _wire)

    _info = [("Correct perspective", host.chk_perspective)]
    for obj_id in OBJECT_NAMES:
        _w = host._nor_widgets[obj_id]
        _lbl = OBJECT_LABELS[obj_id]
        _info += [
            (f"{_lbl} — Name", _w["name"]),
            (f"{_lbl} — Role", _w["role"]),
            (f"{_lbl} — Place", _w["place"]),
            (f"{_lbl} — Size", _w["size"]),
            (f"{_lbl} — Pad", _w["padding"]),
            (f"{_lbl} — Corners", _w["corners"]),
        ]
    _info.append(("Require nose facing object", chk))
    attach_info_box(grp, _info)
    return grp


def _build_object_block(host, obj_id):
    """One QWidget for a single object slot — name, role, shape, place,
    size, padding, color. All widgets stored under host._nor_widgets[obj_id]."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(3)

    header = QLabel(OBJECT_LABELS[obj_id])
    theme.set_tone(header, "faint", "font-size:11px; font-weight:bold;")
    v.addWidget(header)

    state = host._nor_objects[obj_id]

    # Row 1: name + role
    row1 = QHBoxLayout()
    row1.setSpacing(4)
    name_edit = QLineEdit(state.get("name", OBJECT_LABELS[obj_id]))
    name_edit.setFixedHeight(24)
    name_edit.setMaximumWidth(140)
    name_edit.setToolTip("Object label — appears on overlay + Excel columns.")
    name_edit.textChanged.connect(lambda t, oid=obj_id: _on_name_changed(host, oid, t))
    row1.addWidget(QLabel("Name:"))
    row1.addWidget(name_edit)

    role_combo = QComboBox()
    role_combo.setFixedHeight(24)
    for key, lbl in ROLE_LABELS.items():
        role_combo.addItem(lbl, key)
    idx = role_combo.findData(state.get("role", ROLE_NONE))
    if idx >= 0:
        role_combo.setCurrentIndex(idx)
    role_combo.setToolTip(
        "Role tag — Familiar/Novel drives the Discrimination Index."
    )
    role_combo.currentIndexChanged.connect(
        lambda _i, oid=obj_id, c=role_combo: _on_role_changed(host, oid, c.currentData())
    )
    row1.addWidget(QLabel("Role:"))
    row1.addWidget(role_combo)
    row1.addStretch()
    v.addLayout(row1)

    # Row 2: shape combo + place button
    row2 = QHBoxLayout()
    row2.setSpacing(4)
    shape_combo = QComboBox()
    shape_combo.setFixedHeight(24)
    for key, lbl in SHAPE_LABELS.items():
        shape_combo.addItem(lbl, key)
    idx = shape_combo.findData(state.get("shape", SHAPE_CIRCLE))
    if idx >= 0:
        shape_combo.setCurrentIndex(idx)
    shape_combo.currentIndexChanged.connect(
        lambda _i, oid=obj_id, c=shape_combo: _on_shape_changed(host, oid, c.currentData())
    )
    row2.addWidget(QLabel("Shape:"))
    row2.addWidget(shape_combo)

    place_btn = QPushButton("Place")
    place_btn.setFixedHeight(24)
    place_btn.setFixedWidth(70)
    place_btn.setToolTip(
        "Click to enter placement mode, then click on the preview to put "
        "the object at that point."
    )
    place_btn.clicked.connect(lambda _=False, oid=obj_id: _start_place(host, oid))
    row2.addWidget(place_btn)
    row2.addStretch()
    v.addLayout(row2)

    # Row 3: size + padding + corners (corners only visible for Custom)
    row3 = QHBoxLayout()
    row3.setSpacing(4)
    size_spin = QDoubleSpinBox()
    size_spin.setRange(0.1, 100.0)
    size_spin.setDecimals(1)
    size_spin.setSingleStep(0.5)
    size_spin.setValue(float(state.get("size_cm", 5.0)))
    size_spin.setSuffix(" cm")
    size_spin.setFixedWidth(85)
    size_spin.setFixedHeight(24)
    size_spin.setToolTip("Diameter (circle) or side length (square/triangle), in cm.")
    size_spin.valueChanged.connect(
        lambda v, oid=obj_id: _on_size_changed(host, oid, float(v))
    )
    row3.addWidget(QLabel("Size:"))
    row3.addWidget(size_spin)

    pad_spin = QDoubleSpinBox()
    pad_spin.setRange(0.0, 50.0)
    pad_spin.setDecimals(1)
    pad_spin.setSingleStep(0.5)
    pad_spin.setValue(float(state.get("padding_cm", 2.0)))
    pad_spin.setSuffix(" cm")
    pad_spin.setFixedWidth(85)
    pad_spin.setFixedHeight(24)
    pad_spin.setToolTip(
        "Interaction zone padding — outward inflation of the object "
        "footprint in cm. Defines the nose-in-zone region."
    )
    pad_spin.valueChanged.connect(
        lambda v, oid=obj_id: _on_padding_changed(host, oid, float(v))
    )
    row3.addWidget(QLabel("Pad:"))
    row3.addWidget(pad_spin)
    row3.addStretch()
    v.addLayout(row3)

    # Row 4: corners (custom) + color picker
    row4 = QHBoxLayout()
    row4.setSpacing(4)
    corners_combo = QComboBox()
    for n in range(CUSTOM_MIN_CORNERS, CUSTOM_MAX_CORNERS + 1):
        corners_combo.addItem(str(n), n)
    corners_combo.setCurrentIndex(1)  # default 4 corners
    corners_combo.setFixedHeight(24)
    corners_combo.setFixedWidth(55)
    corners_combo.setToolTip("Number of corners when shape = Custom.")
    row4.addWidget(QLabel("Corners:"))
    row4.addWidget(corners_combo)

    color_btn = QPushButton("Color")
    color_btn.setFixedSize(60, 24)
    color_btn.setToolTip(f"Pick color for {OBJECT_LABELS[obj_id]}")
    color_btn.clicked.connect(lambda _=False, oid=obj_id: _pick_color(host, oid))
    row4.addWidget(color_btn)
    row4.addStretch()
    v.addLayout(row4)

    host._nor_widgets[obj_id] = {
        "name": name_edit,
        "role": role_combo,
        "shape": shape_combo,
        "place": place_btn,
        "size": size_spin,
        "padding": pad_spin,
        "corners": corners_combo,
        "color": color_btn,
    }
    _refresh_color_swatch(host, obj_id)
    _refresh_shape_visibility(host, obj_id)
    return w


# ── Handlers ───────────────────────────────────────────────────────────

def _set_arena_mode(host, mode_key):
    """Stash the arena define-mode the same way OF's geometry step does
    (so apply_settings / snapshot have a value to read)."""
    if mode_key != "movement":
        host._arena_auto_movement = False
    host._arena_define_mode = mode_key
    if hasattr(host, "_refresh_arena_mode_chip"):
        try:
            host._refresh_arena_mode_chip()
        except Exception:
            pass


def _on_name_changed(host, obj_id, text):
    host._nor_objects[obj_id]["name"] = text or OBJECT_LABELS[obj_id]
    _refresh_zones(host)


def _on_role_changed(host, obj_id, role):
    host._nor_objects[obj_id]["role"] = role
    _refresh_status(host)


def _on_shape_changed(host, obj_id, shape):
    host._nor_objects[obj_id]["shape"] = shape
    _refresh_shape_visibility(host, obj_id)
    _refresh_zones(host)


def _on_size_changed(host, obj_id, size_cm):
    host._nor_objects[obj_id]["size_cm"] = size_cm
    _refresh_zones(host)


def _on_padding_changed(host, obj_id, padding_cm):
    host._nor_objects[obj_id]["padding_cm"] = padding_cm
    _refresh_zones(host)


def _on_angle_toggled(host, on):
    host._nor_angle_enabled = bool(on)
    host.spin_nor_angle.setEnabled(bool(on))


def _refresh_shape_visibility(host, obj_id):
    """Custom shape needs the corners combo + uses freehand placement;
    standard shapes get one-click placement and use size_cm."""
    widgets = host._nor_widgets.get(obj_id) or {}
    shape = host._nor_objects[obj_id].get("shape", SHAPE_CIRCLE)
    is_custom = (shape == SHAPE_CUSTOM)
    if "corners" in widgets:
        widgets["corners"].setVisible(is_custom)
    if "size" in widgets:
        # Size still useful as a hint but doesn't drive geometry for
        # custom — disable instead of hide to keep layout stable.
        widgets["size"].setEnabled(not is_custom)


def _pick_color(host, obj_id):
    state = host._nor_objects[obj_id]
    initial = QColor(state.get("color", OBJECT_COLORS[obj_id]))
    c = QColorDialog.getColor(initial, host, f"Pick color: {OBJECT_LABELS[obj_id]}")
    if not c.isValid():
        return
    state["color"] = c.name()
    _refresh_color_swatch(host, obj_id)
    _refresh_zones(host)


def _refresh_color_swatch(host, obj_id):
    widgets = host._nor_widgets.get(obj_id) or {}
    btn = widgets.get("color")
    if btn is None:
        return
    c = host._nor_objects[obj_id].get("color", OBJECT_COLORS[obj_id])
    qc = QColor(c)
    text_c = "#000" if (qc.red() * 299 + qc.green() * 587 + qc.blue() * 114) / 1000 > 140 else "#fff"
    btn.setStyleSheet(
        f"QPushButton {{ background:{c}; color:{text_c}; "
        f"border:1px solid #D3D8DE; border-radius:3px; font-weight:bold; }}"
    )


def _start_place(host, obj_id):
    """Enter placement mode for `obj_id`. Standard shapes capture one
    click via the NORTab event filter; Custom shape opens MODE_POLY to
    capture N corners."""
    state = host._nor_objects[obj_id]
    zd = getattr(host, "zone_drawer", None)
    if zd is None:
        return
    if state.get("shape") == SHAPE_CUSTOM:
        n = int((host._nor_widgets[obj_id]["corners"]).currentData() or 4)
        from .zones import custom_edit_zone
        zd.add_zone(custom_edit_zone(obj_id, state.get("color", "#FFF"), n))
        zd.start_edit(footprint_name(obj_id), n_corners=n)
        host._nor_placing = obj_id
        host.lbl_nor_status.setText(
            f"Click {n} corners on the preview for "
            f"{state.get('name', OBJECT_LABELS[obj_id])}"
        )
        return
    # Standard shape: stay in IDLE mode (so no teal MODE_CORRECT crosshair
    # — that's the "second cursor" the user saw). NORTab's event filter
    # picks up the click when host._nor_placing is set.
    # If a previous placement was abandoned (user clicked another Place
    # without completing the first), pop its override cursor so we don't
    # stack overrides that never get cleared.
    if getattr(host, "_nor_placing", None) is not None:
        try:
            from PyQt5.QtWidgets import QApplication
            QApplication.restoreOverrideCursor()
        except Exception:
            pass
    host._nor_placing = obj_id
    # Use an APPLICATION override cursor — per-widget setCursor() is
    # overwritten by zone_drawer.mouseMoveEvent on every mouse move,
    # so a regular setCursor wouldn't stick. The override sits on top
    # of all per-widget cursors and survives until restoreOverrideCursor.
    try:
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.CrossCursor)
    except Exception:
        pass
    host.lbl_nor_status.setText(
        f"Click on the preview to place "
        f"{state.get('name', OBJECT_LABELS[obj_id])}"
    )


def finish_place_standard(host, nx, ny):
    """Commit a standard-shape placement: store center, exit placement
    mode, rebuild that object's zones. Called by NORTab's event filter
    on the first click after _start_place."""
    obj_id = host._nor_placing
    if not obj_id:
        return
    host._nor_objects[obj_id]["center_norm"] = (float(nx), float(ny))
    host._nor_placing = None
    try:
        from PyQt5.QtWidgets import QApplication
        QApplication.restoreOverrideCursor()
    except Exception:
        pass
    _refresh_object_zones(host, obj_id)
    _refresh_status(host)


def _on_zones_changed(host):
    """Bridge: (a) when a custom-shape footprint edit completes, the
    editor geometry sits in the footprint zone — copy it into state and
    rebuild the matching interaction zone; (b) whenever calibration or
    arena geometry changes, rebuild all NOR zones so cm-based sizes pick
    up the new px/cm."""
    zd = host.zone_drawer
    reason = getattr(zd, "_last_change_reason", "") or ""

    # ── (a) Custom-shape placement finalize.
    if host._nor_placing:
        obj_id = host._nor_placing
        state = host._nor_objects.get(obj_id) or {}
        if state.get("shape") == SHAPE_CUSTOM:
            z = zd.get_zone(footprint_name(obj_id))
            geom = list((z or {}).get("geometry") or [])
            if len(geom) >= CUSTOM_MIN_CORNERS:
                state["custom_geom_norm"] = geom
                host._nor_placing = None
                _refresh_zones(host)
                _refresh_status(host)
                return

    # ── (b) Calibration / arena change → rebuild cm-driven geometry.
    # Guard against the rebuild's own "unspecified" emit (add_zone fires
    # zones_changed with no reason) to avoid an infinite loop.
    triggers = ("calib", "arena", "perspective", "scale", "cage")
    if any(t in reason.lower() for t in triggers):
        _refresh_zones(host)


def _clear_objects(host):
    """Reset both objects to default state (preserving role + name so the
    user doesn't have to re-type after a wipe — only geometry gets
    cleared)."""
    zd = getattr(host, "zone_drawer", None)
    for obj_id in OBJECT_NAMES:
        st = host._nor_objects[obj_id]
        st["center_norm"] = None
        st["custom_geom_norm"] = []
        if zd is not None:
            color = st.get("color", OBJECT_COLORS[obj_id])
            zd.add_zone(empty_footprint_zone(obj_id, color))
            zd.add_zone(empty_zone(obj_id, color))
    host._nor_placing = None
    _refresh_status(host)
    if zd is not None:
        zd.emit_change("nor objects cleared")


def _refresh_zones(host):
    """Rebuild + push every NOR zone schema from current state. Cheap
    enough to call on every UI change (color / size / padding / calib)."""
    zd = getattr(host, "zone_drawer", None)
    if zd is None:
        return
    schema = build_schema(host)
    for z in schema:
        zd.add_zone(z)
    zd.update()


def _refresh_object_zones(host, obj_id):
    """Rebuild only the named object's footprint + interaction zone.
    Used during drag so we don't recompute the other object's geometry
    on every mouseMove event — keeps the drag smooth."""
    zd = getattr(host, "zone_drawer", None)
    if zd is None:
        return
    from .zones import (
        build_footprint_norm, build_zone_norm, _resolve_px_per_cm,
        empty_footprint_zone, empty_zone, OBJECT_COLORS,
    )
    state = host._nor_objects.get(obj_id) or {}
    color = state.get("color", OBJECT_COLORS.get(obj_id, "#FFF"))
    px_per_cm = _resolve_px_per_cm(host)
    video_size = (getattr(host, "video_w", None) or 0,
                  getattr(host, "video_h", None) or 0)
    footprint = build_footprint_norm(state, px_per_cm, video_size)
    zone = build_zone_norm(footprint, state, px_per_cm, video_size)
    fz = empty_footprint_zone(obj_id, color)
    fz["geometry"] = footprint
    zz = empty_zone(obj_id, color)
    zz["geometry"] = zone
    zd.add_zone(fz)
    zd.add_zone(zz)
    zd.update()


def _refresh_status(host):
    """Update the bottom status line + the step-status chip."""
    objs = host._nor_objects
    placed = 0
    for obj_id in OBJECT_NAMES:
        st = objs[obj_id]
        if st.get("shape") == SHAPE_CUSTOM:
            if len(st.get("custom_geom_norm") or []) >= CUSTOM_MIN_CORNERS:
                placed += 1
        elif st.get("center_norm"):
            placed += 1
    lbl = getattr(host, "lbl_nor_status", None)
    if lbl is None:
        return
    if placed == 0:
        lbl.setText("Define arena + place both objects")
        theme.set_tone(lbl, "faint", "font-size:11px;")
        host.set_step_status("geometry", "blocked")
    elif placed == 1:
        lbl.setText("1 / 2 objects placed")
        theme.set_tone(lbl, "warn", "font-size:11px;")
        host.set_step_status("geometry", "warn")
    else:
        roles = {objs[oid].get("role") for oid in OBJECT_NAMES}
        msg = "Both objects placed"
        if ROLE_FAMILIAR in roles and ROLE_NOVEL in roles:
            msg += " — DI ready"
        lbl.setText(msg)
        theme.set_tone(lbl, "ok", "font-size:11px;")
        host.set_step_status("geometry", "ok")


# ── Results tab ─────────────────────────────────────────────────────────

def build_results_tab(host):
    """NOR per-object summary table — populated post-tracking via
    NORExperiment.populate_results_tab."""
    from PyQt5.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
    from gui.table_copy import enable_excel_copy

    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(8, 8, 8, 8)
    v.setSpacing(6)
    v.addWidget(QLabel(
        "NOR summary. Discrimination Index = (Novel − Familiar) / "
        "(Novel + Familiar). Only populated when both objects have a role."
    ))
    host._nor_table = QTableWidget()
    host._nor_table.setEditTriggers(QTableWidget.NoEditTriggers)
    host._nor_table.setColumnCount(2)
    host._nor_table.setHorizontalHeaderLabels(["Metric", "Value"])
    host._nor_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    enable_excel_copy(host._nor_table)
    v.addWidget(host._nor_table, 1)
    return w
