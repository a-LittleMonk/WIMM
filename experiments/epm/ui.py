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

from gui.info_box import attach_info_box
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


from gui import theme


def build_geometry_step(host):
    """Arena card (define plus-maze, redraw / clear, manual arm buttons,
    perspective) and Zones card (arm width, center zone, open/closed arm
    labels, colours, status) — same structure as Open Field."""
    from experiments import common_ui as cu
    from gui.widgets_v2 import form_row

    # Per-host kind + custom-name state. Seeded from defaults; persists
    # across template rebuilds.
    if not hasattr(host, "_epm_arm_kinds"):
        host._epm_arm_kinds = dict(DEFAULT_ARM_KINDS)
    if not hasattr(host, "_epm_arm_custom_names"):
        host._epm_arm_custom_names = {n: "" for n in ARM_NAMES}

    # ═══ Arena card ═══════════════════════════════════════════════════
    grp, layout = cu.arena_card(host)

    host.rb_epm_template = cu.hidden(QRadioButton("Plus-template", grp))
    host.rb_epm_freehand = cu.hidden(QRadioButton("Manual", grp))
    host.rb_epm_template.setChecked(True)
    host._epm_mode_grp = QButtonGroup(grp)
    host._epm_mode_grp.addButton(host.rb_epm_template, 0)
    host._epm_mode_grp.addButton(host.rb_epm_freehand, 1)

    def _redraw(key):
        if key == "template":
            host._epm_hub = None          # back to the default plus
            host._epm_endpoints = None
            host.rb_epm_template.setChecked(True)
            _start_template(host)
        else:
            host.rb_epm_freehand.setChecked(True)
            _start_arm_edit(host, "arm_n")

    row, _b, _r, clear_btn = cu.define_row(
        host,
        [("Plus template", "template",
          lambda: (host.rb_epm_template.setChecked(True), _start_template(host)),
          "Places a plus shape; drag the center and the four arm tips "
          "onto the maze."),
         ("Manual — draw arms", "manual",
          lambda: host.rb_epm_freehand.setChecked(True),
          "Draw arms N, S, E, W and the center zone yourself.")],
        on_clear=lambda: _clear_arms(host),
        attr="btn_epm_define", on_redraw=_redraw)
    layout.addLayout(row)
    host.btn_epm_clear = clear_btn

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
    fh.addWidget(form_row("Draw", btn_row))
    host.spin_epm_corners = QComboBox()
    host.spin_epm_corners.addItems(["4", "5", "6"])
    host.spin_epm_corners.setCurrentIndex(0)
    host.spin_epm_corners.setFixedWidth(60)
    fh.addWidget(form_row("Corners / arm", host.spin_epm_corners))
    layout.addWidget(host._epm_freehand_widget)

    # Perspective (+ Adjust…) — Full view only.
    host.btn_epm_perspective_adjust = host._btn("Adjust…", width=70)
    host.btn_epm_perspective_adjust.setFixedHeight(24)
    host.btn_epm_perspective_adjust.setToolTip(
        "Re-open the perspective tool to fine-tune the corners")
    host.btn_epm_perspective_adjust.setEnabled(False)
    host.btn_epm_perspective_adjust.clicked.connect(
        lambda: _open_perspective_dialog(host, reapply=True))
    host._epm_persp_widget = cu.perspective_switch(
        host, "chk_epm_perspective",
        lambda on: _on_epm_perspective_toggled(host, on),
        "Open the perspective tool: drag four corners over the maze; the "
        "grid shows how it maps to a straight-overhead view.",
        extra=host.btn_epm_perspective_adjust)
    layout.addWidget(host._epm_persp_widget)

    # ═══ Zones card ═══════════════════════════════════════════════════
    zg, zl = cu.zones_card(host)

    host._epm_template_widget = QWidget()
    tmpl = QVBoxLayout(host._epm_template_widget)
    tmpl.setContentsMargins(0, 0, 0, 0)
    tmpl.setSpacing(7)
    host.spin_epm_arm_width = QDoubleSpinBox()
    host.spin_epm_arm_width.setRange(0.01, 0.95)
    host.spin_epm_arm_width.setDecimals(2)
    host.spin_epm_arm_width.setSingleStep(0.01)
    host.spin_epm_arm_width.setValue(0.10)
    host.spin_epm_arm_width.valueChanged.connect(
        lambda _: _rebuild_template(host))
    tmpl.addWidget(cu.pct_slider(
        host, "Arm width", host.spin_epm_arm_width, 1, 40, scale=100,
        tip="Arm width as % of the shorter video side. Rebuilds the arms."))
    host.spin_epm_center_size = QDoubleSpinBox()
    # Always > 0: arm entries are counted from the center square.
    host.spin_epm_center_size.setRange(0.02, 0.50)
    host.spin_epm_center_size.setDecimals(2)
    host.spin_epm_center_size.setSingleStep(0.01)
    host.spin_epm_center_size.setValue(0.06)
    host.spin_epm_center_size.valueChanged.connect(
        lambda _: _rebuild_template(host))
    tmpl.addWidget(cu.pct_slider(
        host, "Center zone", host.spin_epm_center_size, 2, 30, scale=100,
        tip="Size of the center square where the arms meet, as % of the "
            "video width. An arm entry counts when the mouse goes from here "
            "into an arm."))
    zl.addWidget(host._epm_template_widget)

    # Open / closed label per arm (EPM's own zone feature).
    host._epm_kind_combos = {}
    host._epm_name_edits = {}
    for name in ARM_NAMES:
        r = QHBoxLayout()
        r.setContentsMargins(0, 0, 0, 0)
        r.setSpacing(6)
        combo = QComboBox()
        for text, key in KIND_CHOICES:
            combo.addItem(text, key)
        cur_kind = host._epm_arm_kinds.get(name, DEFAULT_ARM_KINDS[name])
        idx = combo.findData(cur_kind)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.setFixedWidth(95)
        combo.currentIndexChanged.connect(
            lambda _i, n=name: _on_kind_changed(host, n))
        host._epm_kind_combos[name] = combo
        r.addWidget(combo)
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("custom name")
        name_edit.setText(host._epm_arm_custom_names.get(name, ""))
        name_edit.editingFinished.connect(lambda n=name: _on_name_edit(host, n))
        name_edit.setVisible(cur_kind == "custom")
        host._epm_name_edits[name] = name_edit
        r.addWidget(name_edit, 1)
        zl.addWidget(form_row(ARM_LABELS[name], r))

    # Zone colours — Full view only.
    host._epm_colors = {
        n: KIND_COLORS[host._epm_arm_kinds[n]] for n in ARM_NAMES
    }
    host._epm_colors["center_zone"] = CENTER_DEFAULT_COLOR
    host._epm_color_btns = {}
    host._epm_zone_chips = cu.color_buttons(
        host, lambda: host._epm_colors,
        [("arm_n", "N"), ("arm_s", "S"), ("arm_e", "E"), ("arm_w", "W"),
         ("center_zone", "Center")],
        lambda k: _pick_zone_color(host, k))
    zl.addWidget(host._epm_zone_chips)

    # Entry rule: always body center (data holder for saved configs).
    host.combo_epm_rule = cu.hidden(QComboBox(zg))
    host.combo_epm_rule.addItem("Body center", "body")

    host.lbl_epm_zones = cu.status_label("No arms defined")
    zl.addWidget(host.lbl_epm_zones)

    host.rb_epm_freehand.toggled.connect(lambda on: _on_epm_mode_changed(host))
    _on_epm_mode_changed(host)
    for g in (grp, zg):
        g.toggled.connect(lambda _on: _apply_epm_mode_visibility(host))

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

    attach_info_box(grp, [
        ("Plus template", "Drag the center and the four arm tips onto the maze."),
        ("Manual", "Draw arms N, S, E, W and the center zone yourself."),
        ("Correct perspective", host.chk_epm_perspective),
        ("Adjust…", host.btn_epm_perspective_adjust),
    ])
    attach_info_box(zg, [
        ("Arm width", "Arm width as % of the shorter video side."),
        ("Center zone", "Center size as % of the shorter video side; 0 = off."),
        ("Arm labels", "Mark each arm Open or Closed (or a custom name)."),
        ("Colors", "Click a zone to change the colour it is drawn in."),
    ])
    return grp


def _apply_epm_mode_visibility(host):
    fh = host.rb_epm_freehand.isChecked()
    a = host._epm_freehand_widget.parentWidget()
    z = host._epm_template_widget.parentWidget()
    open_a = a.isChecked() if hasattr(a, "isChecked") else True
    open_z = z.isChecked() if hasattr(z, "isChecked") else True
    host._epm_freehand_widget.setVisible(fh and open_a)
    host._epm_template_widget.setVisible((not fh) and open_z)
    for n, edit in getattr(host, "_epm_name_edits", {}).items():
        edit.setVisible(open_z and host._epm_arm_kinds.get(n) == "custom")


def _on_epm_mode_changed(host):
    fh = host.rb_epm_freehand.isChecked()
    _apply_epm_mode_visibility(host)
    from experiments import common_ui as cu
    cu.set_define_mode(host, "manual" if fh else "template", "btn_epm_define")
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
    if getattr(host, "_epm_restoring", False):
        return                     # restoring a video's saved shapes
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
    chips = getattr(host, "_epm_zone_chips", None)
    if chips is not None:
        chips.refresh()
    btns = getattr(host, "_epm_color_btns", {})
    for key, btn in btns.items():
        c = host._epm_colors.get(key, "#FFFFFF")
        text_c = "#000" if _is_light(c) else "#fff"
        btn.setStyleSheet(
            f"QPushButton {{ background:{c}; color:{text_c}; "
            f"border:1px solid #D3D8DE; border-radius:3px; font-weight:bold; }}"
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
            theme.set_tone(lbl, "ok", "font-size:11px;")
            host.set_step_status("geometry", "ok")
        else:
            theme.set_tone(lbl, "warn", "font-size:11px;")
            host.set_step_status("geometry", "warn")
    else:
        lbl.setText("No arms defined")
        theme.set_tone(lbl, "faint", "font-size:11px;")
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
