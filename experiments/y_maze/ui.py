"""Y-Maze geometry step.

The host (a YMazeTab / OpenFieldTab subclass) gives us:
  zone_drawer (ZoneDrawer), _group, _btn, _sep, _row, _advanced_widgets,
  combo_zone_mode (we hide it), spin_center_pct (we hide it).
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton, QButtonGroup,
    QDoubleSpinBox, QPushButton, QComboBox, QButtonGroup, QColorDialog,
    QCheckBox,
)

from .zones import (
    ARM_NAMES, ARM_LABELS, ARM_COLORS, NEUTRAL_DEFAULT_COLOR,
    build_template_arms, build_schema_from_arms, build_arm_label_positions,
    empty_arm_zone, empty_neutral_zone,
    default_y_template_geometry, y_template_overlay_zone,
    neutral_zone,
)


def build_geometry_step(host):
    grp = host._group("Step 2 — Y-Maze geometry", status_id="geometry")
    layout = QVBoxLayout(grp)
    layout.setSpacing(4)

    # ── Mode picker (Y-template default; Manual second)
    mode_row = QHBoxLayout()
    mode_row.addWidget(QLabel("Mode:"))
    host.rb_ym_template = QRadioButton("Y-template")
    host.rb_ym_freehand = QRadioButton("Manual")
    host.rb_ym_template.setChecked(True)
    host._ym_mode_grp = QButtonGroup(grp)
    host._ym_mode_grp.addButton(host.rb_ym_template, 0)
    host._ym_mode_grp.addButton(host.rb_ym_freehand, 1)
    for rb in (host.rb_ym_template, host.rb_ym_freehand):
        rb.setStyleSheet("font-size:11px;")
        mode_row.addWidget(rb)
    mode_row.addStretch()
    layout.addLayout(mode_row)

    # ── Manual controls (4 compact buttons: A/B/C/N + clear)
    host._ym_freehand_widget = QWidget()
    fh = QVBoxLayout(host._ym_freehand_widget)
    fh.setContentsMargins(0, 0, 0, 0)
    fh.setSpacing(4)
    btn_row = QHBoxLayout()
    btn_row.setSpacing(4)
    host.btn_ym_arm_a = host._btn("A", width=40)
    host.btn_ym_arm_b = host._btn("B", width=40)
    host.btn_ym_arm_c = host._btn("C", width=40)
    host.btn_ym_arm_n = host._btn("N", width=40)
    host.btn_ym_arm_a.setToolTip("Define Arm A — click to start drawing the polygon")
    host.btn_ym_arm_b.setToolTip("Define Arm B — click to start drawing the polygon")
    host.btn_ym_arm_c.setToolTip("Define Arm C — click to start drawing the polygon")
    host.btn_ym_arm_n.setToolTip("Define Neutral zone — click to start drawing the polygon")
    host.btn_ym_arm_a.clicked.connect(lambda: _start_arm_edit(host, "arm_a"))
    host.btn_ym_arm_b.clicked.connect(lambda: _start_arm_edit(host, "arm_b"))
    host.btn_ym_arm_c.clicked.connect(lambda: _start_arm_edit(host, "arm_c"))
    host.btn_ym_arm_n.clicked.connect(lambda: _start_arm_edit(host, "neutral_zone"))
    btn_row.addWidget(host.btn_ym_arm_a)
    btn_row.addWidget(host.btn_ym_arm_b)
    btn_row.addWidget(host.btn_ym_arm_c)
    btn_row.addWidget(host.btn_ym_arm_n)
    btn_row.addStretch()
    fh.addLayout(btn_row)

    corners_row = QHBoxLayout()
    corners_row.addWidget(QLabel("Corners per arm:"))
    host.spin_ym_corners = QComboBox()
    host.spin_ym_corners.addItems(["4", "5", "6"])
    host.spin_ym_corners.setCurrentIndex(0)
    host.spin_ym_corners.setFixedWidth(60)
    host.spin_ym_corners.setFixedHeight(24)
    corners_row.addWidget(host.spin_ym_corners)
    corners_row.addStretch()
    fh.addLayout(corners_row)
    layout.addWidget(host._ym_freehand_widget)

    # ── Template controls
    host._ym_template_widget = QWidget()
    tmpl = QVBoxLayout(host._ym_template_widget)
    tmpl.setContentsMargins(0, 0, 0, 0)
    tmpl.setSpacing(4)
    # Auto-detect runs the moment template mode is entered (or on video
    # load) — no manual button needed. Hub + endpoints are draggable on
    # the preview to fine-tune the auto-placement.
    tmpl_row = QHBoxLayout()
    tmpl_row.addWidget(QLabel("Arm width:"))
    host.spin_ym_arm_width = QDoubleSpinBox()
    host.spin_ym_arm_width.setRange(0.01, 0.95)
    host.spin_ym_arm_width.setDecimals(2)
    host.spin_ym_arm_width.setSingleStep(0.01)
    host.spin_ym_arm_width.setValue(0.10)
    host.spin_ym_arm_width.setSuffix(" w")
    host.spin_ym_arm_width.setFixedWidth(85)
    host.spin_ym_arm_width.setFixedHeight(24)
    host.spin_ym_arm_width.setToolTip(
        "Arm width as a fraction of frame width. Rebuilds arms when changed."
    )
    host.spin_ym_arm_width.valueChanged.connect(lambda _: _rebuild_template(host))
    tmpl_row.addWidget(host.spin_ym_arm_width)
    tmpl_row.addStretch()
    tmpl.addLayout(tmpl_row)

    # Arm length (cm) for calibration lives in Step 3 (Scale step) — see
    # YMazeTab.__init__ where it replaces the OF cage-size widget there.

    # Perspective correction — warp every frame so the maze appears as
    # a perfect 120° Y from straight overhead. Eliminates camera tilt
    # so px/cm is uniform across the frame.
    persp_row = QHBoxLayout()
    host.chk_ym_perspective = QCheckBox("Perspective correction")
    host.chk_ym_perspective.setToolTip(
        "Warp every frame so the maze appears straight-overhead with arms "
        "at canonical 120° angles. Requires Define Y to be set first."
    )
    host.chk_ym_perspective.toggled.connect(
        lambda on: _on_ym_perspective_toggled(host, on)
    )
    persp_row.addWidget(host.chk_ym_perspective)
    persp_row.addStretch()
    tmpl.addLayout(persp_row)

    # Neutral zone size — central hub area where arms meet. Set to 0 to
    # disable. Same units as arm width (fraction of frame width).
    neutral_row = QHBoxLayout()
    neutral_row.addWidget(QLabel("Neutral zone:"))
    host.spin_ym_neutral_size = QDoubleSpinBox()
    host.spin_ym_neutral_size.setRange(0.0, 0.50)
    host.spin_ym_neutral_size.setDecimals(2)
    host.spin_ym_neutral_size.setSingleStep(0.01)
    host.spin_ym_neutral_size.setValue(0.06)
    host.spin_ym_neutral_size.setSuffix(" r")
    host.spin_ym_neutral_size.setSpecialValueText("Off")
    host.spin_ym_neutral_size.setFixedWidth(85)
    host.spin_ym_neutral_size.setFixedHeight(24)
    host.spin_ym_neutral_size.setToolTip(
        "Radius of the central neutral zone (fraction of frame width). "
        "Where the three arms meet at the hub. Set to 0 to disable."
    )
    host.spin_ym_neutral_size.valueChanged.connect(
        lambda _: _rebuild_template(host)
    )
    neutral_row.addWidget(host.spin_ym_neutral_size)
    neutral_row.addStretch()
    tmpl.addLayout(neutral_row)

    layout.addWidget(host._ym_template_widget)

    host.rb_ym_freehand.toggled.connect(lambda on: _on_ym_mode_changed(host))
    _on_ym_mode_changed(host)

    # ── Clear
    clear_row = QHBoxLayout()
    host.btn_ym_clear = host._btn("Clear arms", width=90)
    host.btn_ym_clear.clicked.connect(lambda: _clear_arms(host))
    clear_row.addWidget(host.btn_ym_clear)
    clear_row.addStretch()
    layout.addLayout(clear_row)

    layout.addWidget(host._sep())

    # ── Zone colors (detection areas + neutral zone)
    host._ym_colors = {
        "arm_a": ARM_COLORS["arm_a"],
        "arm_b": ARM_COLORS["arm_b"],
        "arm_c": ARM_COLORS["arm_c"],
        "neutral_zone": NEUTRAL_DEFAULT_COLOR,
    }
    host._ym_color_btns = {}
    color_label = QLabel("Zone colors:")
    color_label.setStyleSheet("font-size:11px; color:#bbb;")
    layout.addWidget(color_label)
    color_row = QHBoxLayout()
    color_row.setSpacing(4)
    for key, lbl in (("arm_a", "A"), ("arm_b", "B"), ("arm_c", "C"),
                     ("neutral_zone", "N")):
        btn = QPushButton(lbl)
        btn.setFixedSize(34, 24)
        btn.setToolTip(f"Pick color for {lbl}")
        btn.clicked.connect(lambda _=False, k=key: _pick_zone_color(host, k))
        host._ym_color_btns[key] = btn
        color_row.addWidget(btn)
    color_row.addStretch()
    layout.addLayout(color_row)
    _refresh_color_swatches(host)

    layout.addWidget(host._sep())

    # ── Entry rule + min dwell
    rule_row = QHBoxLayout()
    rule_row.addWidget(QLabel("Entry rule:"))
    host.combo_ym_rule = QComboBox()
    host.combo_ym_rule.addItem("Body center", "body")
    host.combo_ym_rule.setFixedHeight(24)
    rule_row.addWidget(host.combo_ym_rule)
    rule_row.addStretch()
    layout.addLayout(rule_row)

    # Min-dwell control moved to Step 5 — single source of truth for OF + Y-Maze.

    # ── Status
    host.lbl_ym_zones = QLabel("No arms defined")
    host.lbl_ym_zones.setWordWrap(True)
    host.lbl_ym_zones.setStyleSheet("color:#888; font-size:11px;")
    layout.addWidget(host.lbl_ym_zones)

    # Seed empty arm zones into the drawer the moment it exists. The
    # drawer is created later in _build_preview_tab, so we use a small
    # poll via QTimer to wire up after construction completes.
    from PyQt5.QtCore import QTimer

    def _wire():
        zd = getattr(host, "zone_drawer", None)
        if zd is None:
            QTimer.singleShot(0, _wire)
            return
        for name in ARM_NAMES:
            zd.add_zone(empty_arm_zone(name))
        # Seed an empty neutral zone too so the N button (manual mode) has
        # something to edit out of the box.
        zd.add_zone(empty_neutral_zone())
        try:
            zd.zones_changed.connect(lambda: _refresh_ym_label(host))
        except Exception:
            pass
    QTimer.singleShot(0, _wire)

    return grp


def _on_ym_mode_changed(host):
    fh = host.rb_ym_freehand.isChecked()
    host._ym_freehand_widget.setVisible(fh)
    host._ym_template_widget.setVisible(not fh)
    zd = getattr(host, "zone_drawer", None)
    if zd is None:
        return
    if fh:
        # Leaving template mode — hide the Y overlay (geometry stays cached
        # on host so re-entering template restores the same Y). Re-seed an
        # empty neutral zone so the manual-mode N button has a fresh target.
        zd.remove_zone("y_template")
        zd.add_zone(empty_neutral_zone())
        zd.emit_change("y-template hidden")
    else:
        # Entering template mode — show the default (or last) Y immediately.
        _start_template(host)


def _start_arm_edit(host, arm_name):
    n = int(host.spin_ym_corners.currentText())
    host.zone_drawer.start_edit(arm_name, n_corners=n)


def _start_template(host):
    """Auto-detect the Y-maze in the current preview frame and install
    hub + 3 endpoint dots labeled A/B/C. Falls back to a default centered
    Y if detection fails. Hub + endpoints are draggable; arms rebuild live."""
    zd = host.zone_drawer
    # If the user has already placed/dragged a template in this session,
    # keep their geometry — re-clicking Define Y should not wipe their
    # adjustments. Run auto-detect only on a fresh template.
    hub = getattr(host, "_ym_hub", None)
    endpoints = getattr(host, "_ym_endpoints", None)
    if not hub or not endpoints or len(endpoints) < 3:
        from .auto_detect import detect_y_shape
        frame = (getattr(host, "_preview_bg_raw", None)
                 if getattr(host, "_preview_bg_raw", None) is not None
                 else getattr(host, "_first_frame_bgr", None))
        detected = detect_y_shape(frame) if frame is not None else None
        if detected is not None:
            hub, endpoints = detected
        else:
            hub, endpoints = default_y_template_geometry()
    host._ym_hub = tuple(hub)
    host._ym_endpoints = [tuple(p) for p in endpoints[:3]]
    # Ensure we're in idle mode so the corners are immediately draggable.
    try:
        zd.set_mode(zd.MODE_IDLE)
    except Exception:
        pass
    zd.add_zone(y_template_overlay_zone(host._ym_hub, host._ym_endpoints))
    _rebuild_template(host)
    # Wire the drag handler exactly once. Listen to BOTH:
    #   zones_changing — fires on every mousemove during a vertex drag
    #                    so the arm rectangles follow the hub/endpoint live.
    #   zones_changed  — fires on drag release; covers programmatic
    #                    geometry edits (set_zone, schema replace, etc.).
    handler = _template_drag_handler(host)
    for sig in (zd.zones_changing, zd.zones_changed):
        try:
            sig.disconnect(handler)
        except Exception:
            pass
        sig.connect(handler)


def _template_drag_handler(host):
    """Returns a closure (cached on host) that re-syncs hub/endpoints from
    the y_template overlay zone after a vertex drag."""
    if hasattr(host, "_ym_template_handler"):
        return host._ym_template_handler

    def handler():
        zd = host.zone_drawer
        z = zd.get_zone("y_template")
        if not z:
            return
        geom = z.get("geometry") or []
        if len(geom) < 4:
            return
        new_hub = tuple(geom[0])
        new_endpoints = [tuple(p) for p in geom[1:4]]
        if (new_hub == getattr(host, "_ym_hub", None)
                and new_endpoints == getattr(host, "_ym_endpoints", None)):
            return  # zones_changed fired but template points unchanged
        host._ym_hub = new_hub
        host._ym_endpoints = new_endpoints
        _rebuild_template(host)

    host._ym_template_handler = handler
    return handler


def _rebuild_template(host):
    hub = getattr(host, "_ym_hub", None)
    endpoints = getattr(host, "_ym_endpoints", None)
    if not hub or not endpoints:
        return
    arm_w = float(host.spin_ym_arm_width.value())
    neutral_r = (float(host.spin_ym_neutral_size.value())
                 if hasattr(host, "spin_ym_neutral_size") else 0.0)
    # Pass current frame size so arm rectangles + neutral stay truly
    # perpendicular in pixel space (the norm-space math is only correct
    # for square frames).
    vsize = (getattr(host, "video_w", None), getattr(host, "video_h", None))
    if not (vsize[0] and vsize[1]):
        vsize = None
    arms = build_template_arms(hub, endpoints, arm_w, neutral_r,
                                video_size=vsize)
    geoms = {name: arms[i] for i, name in enumerate(ARM_NAMES)}
    schema = build_schema_from_arms(geoms)
    colors = getattr(host, "_ym_colors", {})
    label_positions = build_arm_label_positions(hub, endpoints, arm_w,
                                                neutral_r,
                                                video_size=vsize)
    for z in schema:
        z["style"]["color"] = colors.get(z["name"], z["style"]["color"])
        lpos = label_positions.get(z["name"])
        if lpos is not None:
            z["style"]["label_pos"] = lpos
    zd = host.zone_drawer
    for name in ARM_NAMES:
        zd.remove_zone(name)
    for z in schema:
        zd.add_zone(z)
    # Neutral Y polygon — drawn on top of arms; 0 = disabled.
    zd.remove_zone("neutral_zone")
    if neutral_r > 0:
        nz = neutral_zone(hub, endpoints, neutral_r, arm_w,
                          color=colors.get("neutral_zone",
                                           NEUTRAL_DEFAULT_COLOR),
                          video_size=vsize)
        # Place the Neutral label in the LARGEST angular gap between the
        # three arms, at a distance past the arm-tip radius. That puts it
        # in the empty triangular wedge outside the Y, so it can never
        # overlap an arm regardless of the Y's rotation.
        import math as _m
        angles = sorted(
            _m.atan2(ep[1] - hub[1], ep[0] - hub[0]) for ep in endpoints[:3]
        )
        # Wrap-around gaps; pick the largest.
        gaps = [
            (angles[1] - angles[0], (angles[0] + angles[1]) / 2.0),
            (angles[2] - angles[1], (angles[1] + angles[2]) / 2.0),
            (2 * _m.pi - (angles[2] - angles[0]),
             (angles[2] + angles[0] + 2 * _m.pi) / 2.0),
        ]
        _, bisector = max(gaps, key=lambda g: g[0])
        max_spoke = max(_m.hypot(ep[0] - hub[0], ep[1] - hub[1])
                        for ep in endpoints[:3])
        # Place the label inside the gap wedge, ~60% of the spoke length
        # out from the hub. The gap direction has no arm so we don't need
        # to clear the tip radius — keeps the label well inside the frame.
        r_label = max_spoke * 0.6
        nx = hub[0] + r_label * _m.cos(bisector)
        ny = hub[1] + r_label * _m.sin(bisector)
        nz["style"]["label_pos"] = (max(0.01, min(0.99, nx)),
                                    max(0.01, min(0.99, ny)))
        zd.add_zone(nz)
    zd.emit_change("y-maze arms set from template")


def _pick_zone_color(host, key):
    """Open color picker for one of the arm zones or the neutral zone.
    Updates host._ym_colors and rebuilds template so the change shows live."""
    initial = QColor(host._ym_colors.get(key, "#FFFFFF"))
    c = QColorDialog.getColor(initial, host, f"Pick color: {key}")
    if not c.isValid():
        return
    host._ym_colors[key] = c.name()
    _refresh_color_swatches(host)
    # Also patch any existing zone with this name so freehand-mode arms
    # update immediately (template mode rebuilds them via _rebuild_template).
    zd = getattr(host, "zone_drawer", None)
    if zd is not None:
        z = zd.get_zone(key)
        if z is not None:
            z["style"]["color"] = c.name()
        zd.update()
    _rebuild_template(host)


def _refresh_color_swatches(host):
    """Paint each color-picker button with its current color so the user
    can see what's set without opening the dialog."""
    btns = getattr(host, "_ym_color_btns", {})
    for key, btn in btns.items():
        c = host._ym_colors.get(key, "#FFFFFF")
        text_c = "#000" if _is_light(c) else "#fff"
        btn.setStyleSheet(
            f"QPushButton {{ background:{c}; color:{text_c}; "
            f"border:1px solid #555; border-radius:3px; font-weight:bold; }}"
        )


def _is_light(hex_color):
    """True if the given #RRGGBB is light enough that black text reads well."""
    try:
        c = QColor(hex_color)
        # Rec. 601 luminance, 0–255.
        return (c.red() * 299 + c.green() * 587 + c.blue() * 114) / 1000 > 140
    except Exception:
        return False


def _on_ym_perspective_toggled(host, on):
    """Toggle the Y-maze perspective correction. ON: compute homography
    from current hub + endpoints, warp preview, move the template to
    canonical positions (arms appear as a symmetric 120° Y). OFF: restore
    the original hub + endpoints from before the toggle."""
    from .zones import (
        build_y_homography, canonical_y_geometry,
    )
    if on:
        hub = getattr(host, "_ym_hub", None)
        endpoints = getattr(host, "_ym_endpoints", None)
        if not hub or not endpoints or len(endpoints) < 3:
            host.chk_ym_perspective.blockSignals(True)
            host.chk_ym_perspective.setChecked(False)
            host.chk_ym_perspective.blockSignals(False)
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(
                host, "Perspective correction",
                "Click 'Define Y' first so the template knows where the "
                "hub + arm tips are. Then toggle perspective correction."
            )
            return
        # Use the LIVE video size (so far that's what the tracker sees).
        vw = getattr(host, "video_w", None) or 1
        vh = getattr(host, "video_h", None) or 1
        result = build_y_homography(hub, endpoints, (vw, vh))
        if result is None:
            host.chk_ym_perspective.blockSignals(True)
            host.chk_ym_perspective.setChecked(False)
            host.chk_ym_perspective.blockSignals(False)
            return
        H, warp_size = result
        # Save originals so we can revert exactly.
        host._ym_original_hub = tuple(hub)
        host._ym_original_endpoints = [tuple(p) for p in endpoints[:3]]
        host._ym_perspective_on = True
        host._H = H
        host._perspective_on = True
        if hasattr(host, "_native_video_size"):
            host._native_video_size = (host.video_w, host.video_h)
        host.video_w, host.video_h = warp_size
        # Save so _load_video_path can restore warp_size after the
        # post-tracking video reload — otherwise video_w/h reset to
        # native and _H stops fitting the target rect.
        host._perspective_warp_size = tuple(warp_size)
        # Swap the live overlay to canonical positions so the preview
        # (which is now warped) shows the arms where they actually land.
        canon_hub, canon_tips = canonical_y_geometry(warp_size)
        host._ym_hub = canon_hub
        host._ym_endpoints = canon_tips
        _rebuild_template(host)
        # Repaint preview with the warped frame.
        if getattr(host, "_first_frame_bgr", None) is not None:
            warped = _warp_frame(host, host._first_frame_bgr)
            if warped is not None:
                host.zone_drawer.set_frame(warped)
    else:
        # Revert. Restore originals if they were saved.
        orig_hub = getattr(host, "_ym_original_hub", None)
        orig_eps = getattr(host, "_ym_original_endpoints", None)
        if orig_hub and orig_eps:
            host._ym_hub = tuple(orig_hub)
            host._ym_endpoints = [tuple(p) for p in orig_eps]
        host._ym_original_hub = None
        host._ym_original_endpoints = None
        host._ym_perspective_on = False
        host._H = None
        host._perspective_on = False
        host._perspective_warp_size = None
        if getattr(host, "_native_video_size", None):
            host.video_w, host.video_h = host._native_video_size
            host._native_video_size = None
        _rebuild_template(host)
        if getattr(host, "_first_frame_bgr", None) is not None:
            host.zone_drawer.set_frame(host._first_frame_bgr)
    host.zone_drawer.update()


def _warp_frame(host, frame_bgr):
    """Apply host._H to `frame_bgr`. Returns the warped frame or None."""
    import cv2
    H = getattr(host, "_H", None)
    if H is None or frame_bgr is None:
        return None
    vw, vh = host.video_w, host.video_h
    if not vw or not vh:
        return None
    return cv2.warpPerspective(frame_bgr, H, (int(vw), int(vh)))


def _clear_arms(host):
    zd = host.zone_drawer
    for name in ARM_NAMES:
        z = empty_arm_zone(name)
        zd.add_zone(z)
    zd.remove_zone("y_template")
    zd.remove_zone("neutral_zone")
    host._ym_hub = None
    host._ym_endpoints = None
    zd.emit_change("y-maze arms cleared")


def _refresh_ym_label(host):
    zd = host.zone_drawer
    lbl = getattr(host, "lbl_ym_zones", None)
    if lbl is None:
        return
    defined = []
    for name in ARM_NAMES:
        z = zd.get_zone(name)
        if z and len(z.get("geometry") or []) >= 3:
            defined.append(ARM_LABELS[name])
    if defined:
        lbl.setText(" | ".join(defined) + " defined")
        lbl.setStyleSheet("color:#4CAF50; font-size:11px;")
        host.set_step_status("geometry", "ok" if len(defined) == 3 else "warn")
    else:
        lbl.setText("No arms defined")
        lbl.setStyleSheet("color:#888; font-size:11px;")
        host.set_step_status("geometry", "blocked")


def build_results_tab(host):
    """Y-Maze results tab: arm-entry summary + alternation %."""
    from PyQt5.QtWidgets import (
        QTableWidget, QTableWidgetItem, QHeaderView,
    )
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(8, 8, 8, 8)
    v.setSpacing(6)

    v.addWidget(QLabel(
        "Y-Maze summary. Spontaneous alternation = consecutive triplets "
        "of distinct arms / (total entries - 2) × 100."
    ))

    from gui.table_copy import enable_excel_copy
    host._ym_table = QTableWidget()
    host._ym_table.setEditTriggers(QTableWidget.NoEditTriggers)
    host._ym_table.setColumnCount(2)
    host._ym_table.setHorizontalHeaderLabels(["Metric", "Value"])
    host._ym_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    enable_excel_copy(host._ym_table)
    v.addWidget(host._ym_table, 1)
    return w


