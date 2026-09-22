"""EPM geometry step.

Mirrors Y-Maze's UI but with 4 arms (N/S/E/W) + center zone + per-arm
kind dropdown (Open/Closed/Neutral/Custom) + custom-name field.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton, QButtonGroup,
    QDoubleSpinBox, QPushButton, QComboBox, QColorDialog, QCheckBox,
    QLineEdit,
)

from .zones import (
    ARM_NAMES, ARM_LABELS, KIND_COLORS, CENTER_DEFAULT_COLOR,
    DEFAULT_ARM_KINDS, KIND_STYLE,
    build_template_arms, build_schema_from_arms, build_arm_label_positions,
    empty_arm_zone, empty_center_zone,
    default_plus_template_geometry, plus_template_overlay_zone,
    center_zone,
)


KIND_CHOICES = [
    ("Open",    "open"),
    ("Closed",  "closed"),
    ("Custom",  "custom"),
]


def build_geometry_step(host):
    grp = host._group("Step 2 — Elevated Plus Maze geometry",
                       status_id="geometry")
    layout = QVBoxLayout(grp)
    layout.setSpacing(4)

    # Per-host kind + custom-name state. Seeded from defaults; persists
    # across template rebuilds.
    if not hasattr(host, "_epm_arm_kinds"):
        host._epm_arm_kinds = dict(DEFAULT_ARM_KINDS)
    if not hasattr(host, "_epm_arm_custom_names"):
        host._epm_arm_custom_names = {n: "" for n in ARM_NAMES}

    # ── Mode picker
    mode_row = QHBoxLayout()
    mode_row.addWidget(QLabel("Mode:"))
    host.rb_epm_template = QRadioButton("Plus-template")
    host.rb_epm_freehand = QRadioButton("Manual")
    host.rb_epm_template.setChecked(True)
    host._epm_mode_grp = QButtonGroup(grp)
    host._epm_mode_grp.addButton(host.rb_epm_template, 0)
    host._epm_mode_grp.addButton(host.rb_epm_freehand, 1)
    for rb in (host.rb_epm_template, host.rb_epm_freehand):
        rb.setStyleSheet("font-size:11px;")
        mode_row.addWidget(rb)
    mode_row.addStretch()
    layout.addLayout(mode_row)

    # ── Manual freehand controls — 5 buttons (N/S/E/W + Center) + corners
    host._epm_freehand_widget = QWidget()
    fh = QVBoxLayout(host._epm_freehand_widget)
    fh.setContentsMargins(0, 0, 0, 0)
    fh.setSpacing(4)
    btn_row = QHBoxLayout()
    btn_row.setSpacing(4)
    host.btn_epm_arm_n = host._btn("N", width=40)
    host.btn_epm_arm_s = host._btn("S", width=40)
    host.btn_epm_arm_e = host._btn("E", width=40)
    host.btn_epm_arm_w = host._btn("W", width=40)
    host.btn_epm_center = host._btn("Center", width=60)
    host.btn_epm_arm_n.clicked.connect(lambda: _start_arm_edit(host, "arm_n"))
    host.btn_epm_arm_s.clicked.connect(lambda: _start_arm_edit(host, "arm_s"))
    host.btn_epm_arm_e.clicked.connect(lambda: _start_arm_edit(host, "arm_e"))
    host.btn_epm_arm_w.clicked.connect(lambda: _start_arm_edit(host, "arm_w"))
    host.btn_epm_center.clicked.connect(
        lambda: _start_arm_edit(host, "center_zone"))
    for b in (host.btn_epm_arm_n, host.btn_epm_arm_s,
              host.btn_epm_arm_e, host.btn_epm_arm_w, host.btn_epm_center):
        btn_row.addWidget(b)
    btn_row.addStretch()
    fh.addLayout(btn_row)

    corners_row = QHBoxLayout()
    corners_row.addWidget(QLabel("Corners per arm:"))
    host.spin_epm_corners = QComboBox()
    host.spin_epm_corners.addItems(["4", "5", "6"])
    host.spin_epm_corners.setCurrentIndex(0)
    host.spin_epm_corners.setFixedWidth(60)
    host.spin_epm_corners.setFixedHeight(24)
    corners_row.addWidget(host.spin_epm_corners)
    corners_row.addStretch()
    fh.addLayout(corners_row)
    layout.addWidget(host._epm_freehand_widget)

    # ── Template controls
    host._epm_template_widget = QWidget()
    tmpl = QVBoxLayout(host._epm_template_widget)
    tmpl.setContentsMargins(0, 0, 0, 0)
    tmpl.setSpacing(4)
    tmpl_row = QHBoxLayout()
    tmpl_row.addWidget(QLabel("Arm width:"))
    host.spin_epm_arm_width = QDoubleSpinBox()
    host.spin_epm_arm_width.setRange(0.01, 0.95)
    host.spin_epm_arm_width.setDecimals(2)
    host.spin_epm_arm_width.setSingleStep(0.01)
    host.spin_epm_arm_width.setValue(0.10)
    host.spin_epm_arm_width.setSuffix(" w")
    host.spin_epm_arm_width.setFixedWidth(85)
    host.spin_epm_arm_width.setFixedHeight(24)
    host.spin_epm_arm_width.setToolTip(
        "Arm width as a fraction of frame width. Rebuilds arms when changed."
    )
    host.spin_epm_arm_width.valueChanged.connect(
        lambda _: _rebuild_template(host))
    tmpl_row.addWidget(host.spin_epm_arm_width)
    tmpl_row.addStretch()
    tmpl.addLayout(tmpl_row)

    # Perspective correction — opens a manual dialog (quad + gridlines).
    persp_row = QHBoxLayout()
    host.chk_epm_perspective = QCheckBox("Perspective correction")
    host.chk_epm_perspective.setToolTip(
        "Open the manual perspective tool. Drag four corners over the maze "
        "area in the video; the cyan grid shows how it maps to a rectangle."
    )
    host.chk_epm_perspective.toggled.connect(
        lambda on: _on_epm_perspective_toggled(host, on)
    )
    persp_row.addWidget(host.chk_epm_perspective)
    host.btn_epm_perspective_adjust = host._btn("Adjust…", width=70)
    host.btn_epm_perspective_adjust.setToolTip(
        "Re-open the manual perspective tool to fine-tune the corners"
    )
    host.btn_epm_perspective_adjust.setEnabled(False)
    host.btn_epm_perspective_adjust.clicked.connect(
        lambda: _open_perspective_dialog(host, reapply=True)
    )
    persp_row.addWidget(host.btn_epm_perspective_adjust)
    persp_row.addStretch()
    tmpl.addLayout(persp_row)

    # Center-zone size.
    center_row = QHBoxLayout()
    center_row.addWidget(QLabel("Center zone:"))
    host.spin_epm_center_size = QDoubleSpinBox()
    host.spin_epm_center_size.setRange(0.0, 0.50)
    host.spin_epm_center_size.setDecimals(2)
    host.spin_epm_center_size.setSingleStep(0.01)
    host.spin_epm_center_size.setValue(0.06)
    host.spin_epm_center_size.setSuffix(" r")
    host.spin_epm_center_size.setSpecialValueText("Off")
    host.spin_epm_center_size.setFixedWidth(85)
    host.spin_epm_center_size.setFixedHeight(24)
    host.spin_epm_center_size.setToolTip(
        "Radius of the central plus-shaped center zone (fraction of frame "
        "width). Where the four arms meet at the hub. Set to 0 to disable."
    )
    host.spin_epm_center_size.valueChanged.connect(
        lambda _: _rebuild_template(host)
    )
    center_row.addWidget(host.spin_epm_center_size)
    center_row.addStretch()
    tmpl.addLayout(center_row)

    layout.addWidget(host._epm_template_widget)

    host.rb_epm_freehand.toggled.connect(lambda on: _on_epm_mode_changed(host))
    _on_epm_mode_changed(host)

    # ── Clear arms
    clear_row = QHBoxLayout()
    host.btn_epm_clear = host._btn("Clear arms", width=90)
    host.btn_epm_clear.clicked.connect(lambda: _clear_arms(host))
    clear_row.addWidget(host.btn_epm_clear)
    clear_row.addStretch()
    layout.addLayout(clear_row)

    layout.addWidget(host._sep())

    # ── Per-arm kind dropdown + custom name field
    host._epm_kind_combos = {}
    host._epm_name_edits = {}
    kind_label = QLabel("Arm labels:")
    kind_label.setStyleSheet("font-size:11px; color:#bbb;")
    layout.addWidget(kind_label)
    for name in ARM_NAMES:
        row = QHBoxLayout()
        row.setSpacing(4)
        lbl = QLabel(ARM_LABELS[name] + ":")
        lbl.setFixedWidth(48)
        lbl.setStyleSheet("font-size:11px;")
        row.addWidget(lbl)
        combo = QComboBox()
        for text, key in KIND_CHOICES:
            combo.addItem(text, key)
        # Set current to host kind.
        cur_kind = host._epm_arm_kinds.get(name, DEFAULT_ARM_KINDS[name])
        idx = combo.findData(cur_kind)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.setFixedHeight(24)
        combo.setFixedWidth(85)
        combo.currentIndexChanged.connect(
            lambda _i, n=name: _on_kind_changed(host, n)
        )
        host._epm_kind_combos[name] = combo
        row.addWidget(combo)
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("custom name")
        name_edit.setFixedHeight(24)
        name_edit.setText(host._epm_arm_custom_names.get(name, ""))
        name_edit.editingFinished.connect(
            lambda n=name: _on_name_edit(host, n)
        )
        # Only visible when kind == "custom".
        name_edit.setVisible(cur_kind == "custom")
        host._epm_name_edits[name] = name_edit
        row.addWidget(name_edit, 1)
        layout.addLayout(row)

    layout.addWidget(host._sep())

    # ── Zone color overrides (still useful for fine-tuning).
    host._epm_colors = {
        n: KIND_COLORS[host._epm_arm_kinds[n]] for n in ARM_NAMES
    }
    host._epm_colors["center_zone"] = CENTER_DEFAULT_COLOR
    host._epm_color_btns = {}
    color_label = QLabel("Zone colors:")
    color_label.setStyleSheet("font-size:11px; color:#bbb;")
    layout.addWidget(color_label)
    color_row = QHBoxLayout()
    color_row.setSpacing(4)
    for key, lbl in (("arm_n", "N"), ("arm_s", "S"),
                     ("arm_e", "E"), ("arm_w", "W"),
                     ("center_zone", "C")):
        btn = QPushButton(lbl)
        btn.setFixedSize(34, 24)
        btn.setToolTip(f"Pick color for {lbl}")
        btn.clicked.connect(lambda _=False, k=key: _pick_zone_color(host, k))
        host._epm_color_btns[key] = btn
        color_row.addWidget(btn)
    color_row.addStretch()
    layout.addLayout(color_row)
    _refresh_color_swatches(host)

    layout.addWidget(host._sep())

    # ── Entry rule (min-dwell lives in Step 5 like Y-Maze).
    rule_row = QHBoxLayout()
    rule_row.addWidget(QLabel("Entry rule:"))
    host.combo_epm_rule = QComboBox()
    host.combo_epm_rule.addItem("Body center", "body")
    host.combo_epm_rule.setFixedHeight(24)
    rule_row.addWidget(host.combo_epm_rule)
    rule_row.addStretch()
    layout.addLayout(rule_row)

    # ── Status label
    host.lbl_epm_zones = QLabel("No arms defined")
    host.lbl_epm_zones.setWordWrap(True)
    host.lbl_epm_zones.setStyleSheet("color:#888; font-size:11px;")
    layout.addWidget(host.lbl_epm_zones)

    # Seed empty zones once zone_drawer exists.
    from PyQt5.QtCore import QTimer

    def _wire():
        zd = getattr(host, "zone_drawer", None)
        if zd is None:
            QTimer.singleShot(0, _wire)
            return
        for name in ARM_NAMES:
            zd.add_zone(empty_arm_zone(name, host._epm_arm_kinds[name]))
        zd.add_zone(empty_center_zone())
        try:
            zd.zones_changed.connect(lambda: _refresh_epm_label(host))
        except Exception:
            pass
    QTimer.singleShot(0, _wire)

    return grp


def _on_epm_mode_changed(host):
    fh = host.rb_epm_freehand.isChecked()
    host._epm_freehand_widget.setVisible(fh)
    host._epm_template_widget.setVisible(not fh)
    zd = getattr(host, "zone_drawer", None)
    if zd is None:
        return
    if fh:
        zd.remove_zone("epm_template")
        zd.add_zone(empty_center_zone())
        zd.emit_change("epm-template hidden")
    else:
        _start_template(host)


def _start_arm_edit(host, zone_name):
    n = int(host.spin_epm_corners.currentText())
    host.zone_drawer.start_edit(zone_name, n_corners=n)


def _start_template(host):
    zd = host.zone_drawer
    hub = getattr(host, "_epm_hub", None)
    endpoints = getattr(host, "_epm_endpoints", None)
    if not hub or not endpoints or len(endpoints) < 4:
        hub, endpoints = default_plus_template_geometry()
    host._epm_hub = tuple(hub)
    host._epm_endpoints = [tuple(p) for p in endpoints[:4]]
    try:
        zd.set_mode(zd.MODE_IDLE)
    except Exception:
        pass
    zd.add_zone(plus_template_overlay_zone(host._epm_hub, host._epm_endpoints))
    _rebuild_template(host)
    handler = _template_drag_handler(host)
    for sig in (zd.zones_changing, zd.zones_changed):
        try:
            sig.disconnect(handler)
        except Exception:
            pass
        sig.connect(handler)


def _template_drag_handler(host):
    if hasattr(host, "_epm_template_handler"):
        return host._epm_template_handler

    def handler():
        zd = host.zone_drawer
        z = zd.get_zone("epm_template")
        if not z:
            return
        geom = z.get("geometry") or []
        if len(geom) < 5:
            return
        new_hub = tuple(geom[0])
        new_endpoints = [tuple(p) for p in geom[1:5]]
        if (new_hub == getattr(host, "_epm_hub", None)
                and new_endpoints == getattr(host, "_epm_endpoints", None)):
            return
        host._epm_hub = new_hub
        host._epm_endpoints = new_endpoints
        _rebuild_template(host)

    host._epm_template_handler = handler
    return handler


def _rebuild_template(host):
    hub = getattr(host, "_epm_hub", None)
    endpoints = getattr(host, "_epm_endpoints", None)
    if not hub or not endpoints:
        return
    arm_w = float(host.spin_epm_arm_width.value())
    center_r = (float(host.spin_epm_center_size.value())
                if hasattr(host, "spin_epm_center_size") else 0.0)
    vsize = (getattr(host, "video_w", None), getattr(host, "video_h", None))
    if not (vsize[0] and vsize[1]):
        vsize = None
    arms = build_template_arms(hub, endpoints, arm_w, center_r,
                                video_size=vsize)
    geoms = {name: arms[i] for i, name in enumerate(ARM_NAMES)}
    schema = build_schema_from_arms(geoms, arm_kinds=host._epm_arm_kinds)
    colors = getattr(host, "_epm_colors", {})
    label_positions = build_arm_label_positions(hub, endpoints, arm_w,
                                                center_r, video_size=vsize)
    for z in schema:
        # Apply user color override on top of kind color.
        z["style"]["color"] = colors.get(z["name"], z["style"]["color"])
        lpos = label_positions.get(z["name"])
        if lpos is not None:
            z["style"]["label_pos"] = lpos
    zd = host.zone_drawer
    for name in ARM_NAMES:
        zd.remove_zone(name)
    for z in schema:
        zd.add_zone(z)
    zd.remove_zone("center_zone")
    if center_r > 0:
        cz = center_zone(hub, endpoints, center_r, arm_w,
                         color=colors.get("center_zone", CENTER_DEFAULT_COLOR),
                         video_size=vsize)
        # Place "Center" label inline with hub for clarity.
        cz["style"]["label_pos"] = (max(0.01, min(0.99, hub[0])),
                                    max(0.01, min(0.99, hub[1])))
        zd.add_zone(cz)
    zd.emit_change("epm arms set from template")


def _on_kind_changed(host, name):
    combo = host._epm_kind_combos.get(name)
    if combo is None:
        return
    kind = combo.currentData()
    host._epm_arm_kinds[name] = kind
    # Reset user color override to new kind's default so the visual
    # switches immediately (user can override again via picker).
    host._epm_colors[name] = KIND_COLORS.get(kind, KIND_COLORS["closed"])
    _refresh_color_swatches(host)
    # Toggle the custom-name field visibility. Clear stale name when
    # leaving custom so it doesn't silently survive on the metric.
    edit = host._epm_name_edits.get(name)
    if edit is not None:
        edit.setVisible(kind == "custom")
        if kind != "custom":
            edit.blockSignals(True)
            edit.clear()
            edit.blockSignals(False)
            host._epm_arm_custom_names[name] = ""
    # Update zone style fields in place — drives overlay paint.
    zd = getattr(host, "zone_drawer", None)
    if zd is not None:
        z = zd.get_zone(name)
        if z is not None:
            style = z["style"]
            style["color"] = host._epm_colors[name]
            style["epm_kind"] = kind
            kstyle = KIND_STYLE.get(kind, KIND_STYLE["closed"])
            style["dashed"] = kstyle["dashed"]
            style["fill_alpha"] = kstyle["fill_alpha"]
        zd.update()
    # Rebuild template so colors propagate consistently.
    _rebuild_template(host)


def _on_name_edit(host, name):
    edit = host._epm_name_edits.get(name)
    if edit is None:
        return
    host._epm_arm_custom_names[name] = edit.text().strip()
    zd = getattr(host, "zone_drawer", None)
    if zd is not None:
        zd.update()


def _pick_zone_color(host, key):
    initial = QColor(host._epm_colors.get(key, "#FFFFFF"))
    c = QColorDialog.getColor(initial, host, f"Pick color: {key}")
    if not c.isValid():
        return
    host._epm_colors[key] = c.name()
    _refresh_color_swatches(host)
    zd = getattr(host, "zone_drawer", None)
    if zd is not None:
        z = zd.get_zone(key)
        if z is not None:
            z["style"]["color"] = c.name()
        zd.update()
    _rebuild_template(host)


def _refresh_color_swatches(host):
    btns = getattr(host, "_epm_color_btns", {})
    for key, btn in btns.items():
        c = host._epm_colors.get(key, "#FFFFFF")
        text_c = "#000" if _is_light(c) else "#fff"
        btn.setStyleSheet(
            f"QPushButton {{ background:{c}; color:{text_c}; "
            f"border:1px solid #555; border-radius:3px; font-weight:bold; }}"
        )


def _is_light(hex_color):
    try:
        c = QColor(hex_color)
        return (c.red() * 299 + c.green() * 587 + c.blue() * 114) / 1000 > 140
    except Exception:
        return False


def _on_epm_perspective_toggled(host, on):
    """Checkbox toggle: ON opens the manual dialog. OFF restores native
    video size + the pre-perspective template state."""
    if on:
        if not _open_perspective_dialog(host, reapply=False):
            # Dialog cancelled or no frame yet — revert the checkbox.
            host.chk_epm_perspective.blockSignals(True)
            host.chk_epm_perspective.setChecked(False)
            host.chk_epm_perspective.blockSignals(False)
            host.btn_epm_perspective_adjust.setEnabled(False)
            return
        host.btn_epm_perspective_adjust.setEnabled(True)
    else:
        _revert_perspective(host)
        host.btn_epm_perspective_adjust.setEnabled(False)


def _open_perspective_dialog(host, reapply):
    """Show the PerspectiveDialog. Returns True if applied, False on cancel.
    `reapply=True` means perspective is already on and we're fine-tuning —
    in that case we revert the existing warp first so the dialog operates
    on the native frame, then apply the new corners."""
    from .perspective_dialog import PerspectiveDialog
    from .zones import canonical_plus_geometry
    from PyQt5.QtWidgets import QMessageBox

    if reapply and getattr(host, "_epm_perspective_on", False):
        # Tear down current warp so dialog sees the original frame.
        _revert_perspective(host, _emit_rebuild=False)

    frame = (getattr(host, "_first_frame_bgr", None)
             if getattr(host, "_first_frame_bgr", None) is not None
             else getattr(host, "_current_scrub_frame_bgr", None))
    if frame is None:
        QMessageBox.information(
            host, "Perspective correction",
            "Load a video first so the perspective tool has a frame to work on."
        )
        return False

    initial = getattr(host, "_epm_perspective_state", None)
    vw = getattr(host, "video_w", None) or frame.shape[1]
    vh = getattr(host, "video_h", None) or frame.shape[0]
    dlg = PerspectiveDialog(
        frame, initial_state=initial,
        video_size=(vw, vh), parent=host,
    )
    if dlg.exec_() != dlg.Accepted:
        return False
    H, warp_size = dlg.result_homography()
    if H is None:
        return False
    host._epm_perspective_state = dlg.result_state()

    # Save the pre-perspective template so OFF can restore it.
    if not getattr(host, "_epm_perspective_on", False):
        host._epm_original_hub = (tuple(host._epm_hub)
                                  if getattr(host, "_epm_hub", None) else None)
        host._epm_original_endpoints = (
            [tuple(p) for p in host._epm_endpoints]
            if getattr(host, "_epm_endpoints", None) else None
        )
        if hasattr(host, "_native_video_size"):
            host._native_video_size = (host.video_w, host.video_h)

    host._epm_perspective_on = True
    host._H = H
    host._perspective_on = True
    host.video_w, host.video_h = warp_size
    # Save so _load_video_path can restore warp_size after the post-tracking
    # reload — otherwise video_w/h get reset to native and _H stops fitting.
    host._perspective_warp_size = tuple(warp_size)
    # Snap the EPM template to canonical positions inside the new square
    # warp space so the plus visibly lines up with the grid.
    canon_hub, canon_tips = canonical_plus_geometry(warp_size)
    if canon_hub:
        host._epm_hub = canon_hub
        host._epm_endpoints = canon_tips

    # Refresh cached scrub frame BEFORE rebuild (so zones_changed →
    # _update_preview sees a frame that matches the new warp size).
    if (hasattr(host, "_on_scrub")
            and getattr(host, "slider_scrub", None) is not None):
        try:
            host._on_scrub(host.slider_scrub.value())
        except Exception:
            pass
    elif getattr(host, "_first_frame_bgr", None) is not None:
        warped = _warp_frame(host, host._first_frame_bgr)
        if warped is not None:
            host.zone_drawer.set_frame(warped)
    _rebuild_template(host)
    host.zone_drawer.update()
    return True


def _revert_perspective(host, _emit_rebuild=True):
    """Tear down active perspective: restore native video size + the
    pre-perspective template. Caller flips the checkbox separately."""
    orig_hub = getattr(host, "_epm_original_hub", None)
    orig_eps = getattr(host, "_epm_original_endpoints", None)
    if orig_hub and orig_eps:
        host._epm_hub = tuple(orig_hub)
        host._epm_endpoints = [tuple(p) for p in orig_eps]
    host._epm_original_hub = None
    host._epm_original_endpoints = None
    host._epm_perspective_on = False
    host._H = None
    host._perspective_on = False
    host._perspective_warp_size = None
    if getattr(host, "_native_video_size", None):
        host.video_w, host.video_h = host._native_video_size
        host._native_video_size = None
    if (hasattr(host, "_on_scrub")
            and getattr(host, "slider_scrub", None) is not None):
        try:
            host._on_scrub(host.slider_scrub.value())
        except Exception:
            pass
    elif getattr(host, "_first_frame_bgr", None) is not None:
        host.zone_drawer.set_frame(host._first_frame_bgr)
    if _emit_rebuild:
        _rebuild_template(host)
        host.zone_drawer.update()


def _warp_frame(host, frame_bgr):
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
        z = empty_arm_zone(name, host._epm_arm_kinds[name])
        zd.add_zone(z)
    zd.remove_zone("epm_template")
    zd.remove_zone("center_zone")
    zd.add_zone(empty_center_zone())
    host._epm_hub = None
    host._epm_endpoints = None
    zd.emit_change("epm arms cleared")


def _refresh_epm_label(host):
    zd = host.zone_drawer
    lbl = getattr(host, "lbl_epm_zones", None)
    if lbl is None:
        return
    defined = []
    for name in ARM_NAMES:
        z = zd.get_zone(name)
        if z and len(z.get("geometry") or []) >= 3:
            defined.append(ARM_LABELS[name])
    n_open = sum(1 for n in ARM_NAMES
                 if host._epm_arm_kinds.get(n) == "open")
    n_closed = sum(1 for n in ARM_NAMES
                   if host._epm_arm_kinds.get(n) == "closed")
    if defined:
        text = " | ".join(defined) + f" defined ({n_open} open, {n_closed} closed)"
        lbl.setText(text)
        if len(defined) == 4 and n_open > 0 and n_closed > 0:
            lbl.setStyleSheet("color:#4CAF50; font-size:11px;")
            host.set_step_status("geometry", "ok")
        else:
            lbl.setStyleSheet("color:#FFB300; font-size:11px;")
            host.set_step_status("geometry", "warn")
    else:
        lbl.setText("No arms defined")
        lbl.setStyleSheet("color:#888; font-size:11px;")
        host.set_step_status("geometry", "blocked")


def build_results_tab(host):
    from PyQt5.QtWidgets import (
        QTableWidget, QHeaderView,
    )
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(8, 8, 8, 8)
    v.setSpacing(6)
    v.addWidget(QLabel(
        "EPM summary. Open / closed / center aggregation based on per-arm "
        "kind labels set in Step 2."
    ))
    from gui.table_copy import enable_excel_copy
    host._epm_table = QTableWidget()
    host._epm_table.setEditTriggers(QTableWidget.NoEditTriggers)
    host._epm_table.setColumnCount(2)
    host._epm_table.setHorizontalHeaderLabels(["Metric", "Value"])
    host._epm_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    enable_excel_copy(host._epm_table)
    v.addWidget(host._epm_table, 1)
    return w
