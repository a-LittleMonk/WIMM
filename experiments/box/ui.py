"""Setup cards for box-family tests — built only from experiments.common_ui
so they match Open Field (and every other test) control for control.

Arena card: Define arena ▾ · Redraw · ×, a one-line hint naming what to
            outline for this apparatus, Correct perspective (Full view).
Zones card: the test's own settings (sliders / dropdowns / switches),
            zone colours (Full view), one-line status.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QSpinBox, QDoubleSpinBox,
    QPushButton, QLabel, QColorDialog, QTableWidget, QTableWidgetItem,
    QHeaderView,
)
from PyQt5.QtGui import QColor

from gui import theme
from gui.info_box import attach_info_box
from experiments import common_ui as cu
from . import geometry as geo

ZONE_PREFIX = "box_"


def _ensure_state(host, exp):
    if not isinstance(getattr(host, "_box_params", None), dict):
        host._box_params = exp.defaults()
    if not isinstance(getattr(host, "_box_colors", None), dict):
        host._box_colors = exp.default_colors()


# ── Cards ──────────────────────────────────────────────────────────────
def build_geometry_step(host, exp):
    from gui.widgets_v2 import form_row, SwitchBox
    _ensure_state(host, exp)

    # ═══ Arena card — identical to Open Field / NOR ═══════════════════
    grp, layout = cu.arena_card(host)

    def _mode(key, fn):
        def run():
            if key != "movement":
                host._arena_auto_movement = False
            host._arena_define_mode = key
            if hasattr(host, "_refresh_arena_mode_chip"):
                try:
                    host._refresh_arena_mode_chip()
                except Exception:
                    pass
            fn()
        return run

    items = [
        ("Manual — click 4 corners", "manual",
         _mode("manual", host._start_draw_arena), None),
        ("Premade square arena", "square",
         _mode("square", host._apply_premade_square_arena),
         "Drop a centered square; drag the corners onto the apparatus."),
    ]
    row, btn, redraw_btn, clear_btn = cu.define_row(
        host, items, on_clear=host._clear_arena, attr="btn_define_arena")
    layout.addLayout(row)
    host.btn_arena = btn
    host.btn_auto_arena = btn
    host.btn_redraw_arena = redraw_btn
    host.btn_clear_arena = clear_btn
    host.lbl_box_arena_hint = cu.status_label(exp.arena_hint)
    layout.addWidget(host.lbl_box_arena_hint)

    cu.perspective_switch(
        host, "chk_perspective", host._on_perspective_toggled,
        "Warp video so the arena outline becomes a true rectangle.\n"
        "Use when the camera is at an angle. Requires the arena first.")
    host.chk_perspective.setEnabled(False)
    host._perspective_widget = host.chk_perspective
    layout.addWidget(host.chk_perspective.parentWidget())

    # ═══ Zones card — the test's own settings ═════════════════════════
    zg, zl = cu.zones_card(host)
    host._box_params_widget = QWidget()
    pl = QVBoxLayout(host._box_params_widget)
    pl.setContentsMargins(0, 0, 0, 0)
    pl.setSpacing(7)
    host._box_widgets = {}
    host._box_rows = {}
    info = []
    for spec in exp.PARAMS:
        if spec.per_video and "per animal" not in spec.tip:
            spec.tip = ((spec.tip + " ") if spec.tip else "") + (
                "Set per animal: in Run all this stays with each video "
                "(counterbalancing) instead of being copied.")
        w, row_w = _param_widget(host, exp, spec, form_row, SwitchBox)
        host._box_widgets[spec.key] = w
        host._box_rows[spec.key] = row_w
        pl.addWidget(row_w)
        if spec.tip:
            info.append((spec.label, spec.tip))
    zl.addWidget(host._box_params_widget)

    if exp.COLORS:
        host._box_zone_chips = cu.color_buttons(
            host, lambda: host._box_colors,
            [(k, v[0]) for k, v in exp.COLORS.items()],
            lambda k: _pick_color(host, exp, k))
        zl.addWidget(host._box_zone_chips)
        info.append(("Colors", "Click a zone to change the colour it is "
                               "drawn in."))

    host.lbl_box_zones = cu.status_label("Define the arena first")
    zl.addWidget(host.lbl_box_zones)
    if exp.EDITABLE_ZONES:
        from gui.widgets_v2 import link_button
        host.btn_box_reset_shape = link_button(
            "Reset shape", "Undo the corners you dragged on the video")
        host.btn_box_reset_shape.clicked.connect(lambda: _set(host, exp, "zone_edits", {}))
        hint = cu.status_label("Drag any corner on the video to fit the real maze.")
        zl.addWidget(hint)
        zl.addWidget(host.btn_box_reset_shape, 0, Qt.AlignLeft)

    attach_info_box(grp, [
        ("Define arena", exp.arena_hint),
        ("Correct perspective", host.chk_perspective),
    ])
    attach_info_box(zg, info)

    for g in (grp, zg):
        g.toggled.connect(lambda _on: _apply_visibility(host, exp))
    _apply_visibility(host, exp)

    from PyQt5.QtCore import QTimer

    def _wire():
        zd = getattr(host, "zone_drawer", None)
        if zd is None:
            QTimer.singleShot(0, _wire)
            return
        for sig in (zd.zones_changed, zd.zones_changing):
            try:
                sig.connect(lambda: refresh_zones(host, exp))
            except Exception:
                pass
        refresh_zones(host, exp)
    QTimer.singleShot(0, _wire)
    return grp


def _param_widget(host, exp, spec, form_row, SwitchBox):
    p = host._box_params
    val = p.get(spec.key, spec.default)
    if spec.kind in ("pct", "deg"):
        spin = QSpinBox()
        spin.setRange(int(spec.lo), int(spec.hi))
        spin.setValue(int(val))
        spin.valueChanged.connect(lambda v, k=spec.key: _set(host, exp, k, int(v)))
        row = cu.pct_slider(host, spec.label, spin, spec.lo, spec.hi,
                            tip=spec.tip, suffix="°" if spec.kind == "deg" else "%")
        return spin, row
    if spec.kind == "choice":
        combo = QComboBox()
        for value, text in spec.options:
            combo.addItem(text, value)
        i = combo.findData(val)
        combo.setCurrentIndex(max(0, i))
        combo.currentIndexChanged.connect(
            lambda _i, k=spec.key, c=combo: _set(host, exp, k, c.currentData()))
        row = form_row(spec.label, combo)
        if spec.tip:
            combo.setToolTip(spec.tip)
        return combo, row
    if spec.kind == "cm":
        spin = QDoubleSpinBox()
        spin.setRange(float(spec.lo), float(spec.hi))
        spin.setDecimals(1)
        spin.setSingleStep(0.5)
        spin.setSuffix(" cm")
        spin.setValue(float(val))
        spin.valueChanged.connect(lambda v, k=spec.key: _set(host, exp, k, float(v)))
        row = form_row(spec.label, spin)
        if spec.tip:
            spin.setToolTip(spec.tip)
        return spin, row
    if spec.kind == "toggle":
        sw = SwitchBox(spec.label)
        sw.setChecked(bool(val))
        sw.toggled.connect(lambda on, k=spec.key: _set(host, exp, k, bool(on)))
        if spec.tip:
            sw.setToolTip(spec.tip)
        return sw, sw
    if spec.kind == "multi":
        from PyQt5.QtWidgets import QGridLayout
        box = QWidget()
        h = QGridLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setHorizontalSpacing(3)
        h.setVerticalSpacing(3)
        box._buttons = []
        row = form_row(spec.label, box)
        if spec.tip:
            box.setToolTip(spec.tip)
        _rebuild_multi(host, exp, spec, box)
        return box, row
    raise ValueError(f"unknown param kind {spec.kind}")


def _multi_count(exp, spec, p):
    n = spec.options
    if isinstance(n, str):
        n = int(p.get(n, 0) or 0)
    return int(n or 0)


def _rebuild_multi(host, exp, spec, box):
    p = host._box_params
    n = _multi_count(exp, spec, p)
    chosen = set(int(x) for x in (p.get(spec.key) or []) if int(x) <= n)
    if len(box._buttons) == n:
        for i, b in enumerate(box._buttons, start=1):
            b.blockSignals(True)
            b.setChecked(i in chosen)
            b.blockSignals(False)
        return
    lay = box.layout()
    for b in box._buttons:
        lay.removeWidget(b)
        b.deleteLater()
    box._buttons = []
    per_row = 6
    for i in range(1, n + 1):
        b = QPushButton(str(i))
        b.setCheckable(True)
        b.setChecked(i in chosen)
        b.setFixedSize(26, 24)
        b.setProperty("chip", True)
        b.setToolTip(f"Arm {i} baited")
        b.toggled.connect(lambda _on, k=spec.key, bx=box: _set(
            host, exp, k, [j for j, bb in enumerate(bx._buttons, 1) if bb.isChecked()]))
        lay.addWidget(b, (i - 1) // per_row, (i - 1) % per_row)
        box._buttons.append(b)
    lay.setColumnStretch(per_row, 1)


def _set(host, exp, key, value):
    host._box_params[key] = value
    if getattr(host, "_box_syncing", False):
        return
    # A setting that rebuilds the layout (arm count, width, rotation …)
    # replaces hand-adjusted corners; per-animal choices (baited arms) don't.
    spec = next((s for s in exp.PARAMS if s.key == key), None)
    if spec is not None and not spec.per_video and host._box_params.get("zone_edits"):
        host._box_params["zone_edits"] = {}
    # Dependent multi-selectors (e.g. baited arms follow the arm count).
    for spec in exp.PARAMS:
        if spec.kind == "multi" and spec.options == key:
            _rebuild_multi(host, exp, spec, host._box_widgets[spec.key])
    _apply_visibility(host, exp)
    refresh_zones(host, exp)
    zd = getattr(host, "zone_drawer", None)
    if zd is not None:
        zd.emit_change(f"box setting {key}")
    if getattr(host, "tracking_results", None):
        try:
            host._recompute_metrics_and_views()
        except Exception:
            pass


def _apply_visibility(host, exp):
    zones_card = host._box_params_widget.parentWidget()
    open_z = zones_card.isChecked() if hasattr(zones_card, "isChecked") else True
    p = host._box_params
    for spec in exp.PARAMS:
        row = host._box_rows.get(spec.key)
        if row is None:
            continue
        show = open_z and (spec.show_if is None or bool(spec.show_if(p)))
        row.setVisible(show)


def sync_widgets(host, exp):
    """Push host._box_params into the widgets (after loading a video).
    Widget signals still fire (so sliders follow their hidden spins) but
    _set only stores the value while syncing."""
    if not hasattr(host, "_box_widgets"):
        return
    p = dict(host._box_params)
    host._box_syncing = True
    try:
        for spec in exp.PARAMS:
            w = host._box_widgets.get(spec.key)
            if w is None:
                continue
            v = p.get(spec.key, spec.default)
            if spec.kind in ("pct", "deg"):
                w.setValue(int(v))
            elif spec.kind == "choice":
                w.setCurrentIndex(max(0, w.findData(v)))
            elif spec.kind == "cm":
                w.setValue(float(v))
            elif spec.kind == "toggle":
                w.setChecked(bool(v))
        host._box_params = p
        for spec in exp.PARAMS:
            if spec.kind == "multi":
                _rebuild_multi(host, exp, spec, host._box_widgets[spec.key])
    finally:
        host._box_syncing = False
    if getattr(host, "_box_zone_chips", None) is not None:
        host._box_zone_chips.refresh()
    _apply_visibility(host, exp)


def _pick_color(host, exp, key):
    c = QColorDialog.getColor(QColor(host._box_colors.get(key, "#FFFFFF")),
                              host, "Zone colour")
    if not c.isValid():
        return
    host._box_colors[key] = c.name()
    host._box_zone_chips.refresh()
    refresh_zones(host, exp)


# ── Zones on the video ─────────────────────────────────────────────────
def refresh_zones(host, exp):
    """Recompute the test's zones from the current arena and draw them."""
    zd = getattr(host, "zone_drawer", None)
    if zd is None:
        return
    H = geo.box_homography(zd.arena) if zd.arena else None
    zones = exp.zone_defs_for_host(host) if H is not None else []
    keep = set()
    for z in zones:
        name = ZONE_PREFIX + z.name
        keep.add(name)
        geom = geo.from_box(H, z.poly)
        lp = geo.from_box(H, [z.label_pos])[0] if z.label_pos else None
        zd.add_zone({
            "name": name,
            "type": "polygon",
            "geometry": geom,
            "editable": bool(z.editable),
            "movable": bool(z.movable),
            "style": {
                "color": z.color, "thickness": 2,
                "fill_alpha": int(z.fill_alpha), "dashed": bool(z.dashed),
                "label_text": "",
                "box_label": z.label, "box_layer": z.layer,
                "box_label_pos": lp,
            },
        })
    for old in [zz.get("name") for zz in getattr(zd, "_extra_zones", [])]:
        if old and old.startswith(ZONE_PREFIX) and old not in keep:
            zd.remove_zone(old)
    host._box_zone_defs = zones
    host._box_H_norm = H
    lbl = getattr(host, "lbl_box_zones", None)
    if lbl is not None:
        if H is None:
            lbl.setText("Define the arena first")
            theme.set_tone(lbl, "faint", "font-size:11px;")
        else:
            labels = [z.label for z in zones if z.layer == zones[0].layer] if zones else []
            if not labels:
                lbl.setText("No zones")
            elif len(labels) <= 4:
                lbl.setText(" · ".join(labels))
            else:
                lbl.setText(f"{len(zones)} zones on the arena")
            theme.set_tone(lbl, "ok", "font-size:11px;")
    if hasattr(host, "set_step_status"):
        host.set_step_status("geometry", "ok" if H is not None else "blocked")
    zd.update()


# ── Results tab ────────────────────────────────────────────────────────
def build_results_tab(host, exp):
    from gui.table_copy import enable_excel_copy
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(8, 8, 8, 8)
    v.setSpacing(6)
    note = QLabel(f"{exp.name} — main results, then time / entries per zone.")
    note.setWordWrap(True)
    v.addWidget(note)
    host._box_table = QTableWidget()
    host._box_table.setEditTriggers(QTableWidget.NoEditTriggers)
    host._box_table.setColumnCount(2)
    host._box_table.setHorizontalHeaderLabels(["Metric", "Value"])
    host._box_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    enable_excel_copy(host._box_table)
    v.addWidget(host._box_table, 1)
    return w


def populate_results(host, exp, metrics):
    t = getattr(host, "_box_table", None)
    if t is None or not metrics:
        return
    p = exp.params_of(host)
    keys = list(exp.main_keys(p))
    for z in exp.zone_defs_for_host(host):
        keys += [f"Time in {z.label} (s)", f"% Time in {z.label}",
                 f"Entries into {z.label} (#)", f"Latency to {z.label} (s)"]
    rows = [(k, metrics.get(k)) for k in keys if k in metrics]
    t.setUpdatesEnabled(False)
    try:
        t.setRowCount(len(rows))
        for r, (k, val) in enumerate(rows):
            t.setItem(r, 0, QTableWidgetItem(str(k)))
            t.setItem(r, 1, QTableWidgetItem("" if val is None else str(val)))
    finally:
        t.setUpdatesEnabled(True)
