"""Zones-card designer for the Custom experiment.

[Add ▾] [Remove] · Save design… · Load design…
zone list
settings of the selected zone (name, body/nose, position %, size cm …)
measures to report (checkboxes)

Every change goes through experiments.box.ui._set, so the zones on the
video, the overlay and the results update exactly like the built-in box
tests.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QMessageBox, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from experiments.box import geometry as geo
from experiments.box import ui as box_ui
from gui import theme
from .experiment import MEASURES, SHAPE_LABELS, SHAPES, default_zone

_POS = "%"


_MENU_TEXT = {"circle": "Circle  —  drag from the centre",
              "square": "Square  —  drag corner to corner",
              "rectangle": "Rectangle  —  drag corner to corner",
              "polygon": "Custom shape  —  click corners, double-click to finish",
              "line": "Line  —  drag from start to end"}


def _start_drawing(host, exp, shape):
    zd = getattr(host, "zone_drawer", None)
    if zd is None or not zd.arena or geo.box_homography(zd.arena) is None:
        QMessageBox.information(host, "Add zone", "Define the arena first: the zones are "
                                "placed and measured inside it.")
        return
    host._cx_drawing = shape
    zd.start_shape(shape)


def drawn_outline(kind, p0, p1, video_size, n=48):
    """Outline (normalized video points) of a circle / square / rectangle
    exactly as drawn on screen: circle = centre p0 through p1, square /
    rectangle = corner p0 to corner p1. Built in video pixels so a circle
    stays round whatever the frame's aspect."""
    import math
    vw, vh = float(video_size[0]) or 1.0, float(video_size[1]) or 1.0
    ax, ay, bx, by = p0[0] * vw, p0[1] * vh, p1[0] * vw, p1[1] * vh
    if kind == "circle":
        r = math.hypot(bx - ax, by - ay)
        pts = [(ax + r * math.cos(2 * math.pi * k / n), ay + r * math.sin(2 * math.pi * k / n))
               for k in range(n)]
    else:
        if kind == "square":
            side = max(abs(bx - ax), abs(by - ay))
            bx = ax + (side if bx >= ax else -side)
            by = ay + (side if by >= ay else -side)
        pts = [(ax, ay), (bx, ay), (bx, by), (ax, by)]
    return [(x / vw, y / vh) for x, y in pts]


def outline_size_cm(pts_box, dims):
    """(width, height) cm of a box-space outline's bounding box."""
    us = [p[0] for p in pts_box]
    vs = [p[1] for p in pts_box]
    return ((max(us) - min(us)) * float(dims[0]), (max(vs) - min(vs)) * float(dims[1]))


def zone_from_drawing(kind, pts_norm, arena, dims, n, names=(), video_size=(1, 1)):
    """New zone dict from a shape drawn on the video (normalized video
    points). The zone keeps exactly the drawn outline ("pts", in box
    space); lines keep their two ends (% of the arena)."""
    H = geo.box_homography(arena)
    if H is None or not pts_norm:
        return None
    if kind in ("circle", "square", "rectangle"):
        pts_norm = drawn_outline(kind, pts_norm[0], pts_norm[1], video_size)
    u, v = geo.to_box(H, [p[0] for p in pts_norm], [p[1] for p in pts_norm])
    z = default_zone(kind, n, names)

    def pct(a):
        return round(float(a) * 100.0, 2)

    if kind == "line":
        z.update(x=pct(u[0]), y=pct(v[0]), x2=pct(u[1]), y2=pct(v[1]))
        return z
    z["pts"] = [[round(float(a), 5), round(float(b), 5)] for a, b in zip(u, v)]
    z["x"], z["y"] = pct(sum(u) / len(u)), pct(sum(v) / len(v))      # centre, for the panel
    w_cm, h_cm = outline_size_cm(z["pts"], dims)
    z["w"], z["h"] = round(w_cm, 2), round(h_cm, 2)
    return z


def _on_drawn(host, exp, kind, pts):
    if getattr(host, "_cx_drawing", None) != kind:
        return                                    # someone else's drawing
    host._cx_drawing = None
    zones = _zones(host, exp)
    zd = host.zone_drawer
    z = zone_from_drawing(kind, pts, zd.arena, exp.dims_of(host),
                          len(zones) + 1, {zz.get("name") for zz in zones},
                          video_size=(zd._video_w, zd._video_h))
    if z is None:
        return
    zones.append(z)
    _commit(host, exp, zones)
    refresh_designer(host, exp, select=len(zones) - 1)


def _item_text(z):
    return f"{z.get('name')}   ·   {SHAPE_LABELS.get(z.get('shape'), '')}"


def _dot(color):
    """Small round colour swatch for the zone list."""
    from PyQt5.QtGui import QIcon, QPainter, QPixmap
    pm = QPixmap(24, 24)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color or "#888888"))
    p.drawEllipse(4, 4, 16, 16)
    p.end()
    return QIcon(pm)


def _zones(host, exp):
    return exp.params_of(host)["zones"]


def _commit(host, exp, zones):
    host._cx_dirty = True
    box_ui._set(host, exp, "zones", zones)
    if any(z.get("point") == "nose" for z in zones) and hasattr(host, "chk_enable_nose"):
        host.chk_enable_nose.setChecked(True)   # nose zones need nose tracking


def build_designer(host, exp):
    from gui.widgets_v2 import caps_label, link_button
    pl = host._box_params_widget.layout()
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(6)

    host._cx_locked_note = QLabel(
        "Saved experiment: its zones and measures are fixed. Draw the arena for "
        "this video, then drag a zone if it needs to fit the video better.")
    host._cx_locked_note.setWordWrap(True)
    theme.set_tone(host._cx_locked_note, "faint", "font-size:11px;")
    v.addWidget(host._cx_locked_note)

    host._cx_edit_row = QWidget()
    row = QHBoxLayout(host._cx_edit_row)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    add = QToolButton()
    add.setText("Add  ▾")
    add.setPopupMode(QToolButton.InstantPopup)
    add.setToolButtonStyle(Qt.ToolButtonTextOnly)
    menu = QMenu(add)
    for shape in SHAPES:
        menu.addAction(_MENU_TEXT[shape], lambda s=shape: _start_drawing(host, exp, s))
    add.setMenu(menu)
    add.setToolTip("Draw a new zone or crossing line on the video")
    row.addWidget(add)
    rm = QPushButton("Remove")
    rm.setToolTip("Remove the selected zone")
    rm.clicked.connect(lambda: _remove(host, exp))
    row.addWidget(rm)
    row.addStretch(1)
    save = link_button("Export…", "Save this design to a file (to share it)")
    save.clicked.connect(lambda: _save(host, exp))
    load = link_button("Import…", "Load a design from a file")
    load.clicked.connect(lambda: _load(host, exp))
    row.addWidget(save)
    row.addWidget(load)
    v.addWidget(host._cx_edit_row)

    host._cx_list = QListWidget()
    host._cx_list.setMaximumHeight(112)
    host._cx_list.currentRowChanged.connect(lambda _r: _show_form(host, exp))
    v.addWidget(host._cx_list)

    host._cx_form = QWidget()
    host._cx_form_lay = QGridLayout(host._cx_form)
    host._cx_form_lay.setContentsMargins(0, 2, 0, 2)
    host._cx_form_lay.setHorizontalSpacing(8)
    host._cx_form_lay.setVerticalSpacing(4)
    v.addWidget(host._cx_form)

    host._cx_measure_box = QWidget()
    mv = QVBoxLayout(host._cx_measure_box)
    mv.setContentsMargins(0, 4, 0, 0)
    mv.setSpacing(4)
    mv.addWidget(caps_label("Measure"))
    mg = QGridLayout()
    mg.setHorizontalSpacing(10)
    mg.setVerticalSpacing(2)
    host._cx_measures = {}
    for i, (key, label, _on, tip) in enumerate(MEASURES):
        cb = QCheckBox(label)
        cb.setToolTip(tip)
        cb.toggled.connect(lambda _on, h=host, e=exp: _measures_changed(h, e))
        host._cx_measures[key] = cb
        mg.addWidget(cb, i // 2, i % 2)
    mv.addLayout(mg)
    host._cx_save_btn = QPushButton("Save experiment…")
    host._cx_save_btn.setProperty("primary", True)
    host._cx_save_btn.setToolTip("Save this design under a name. It is then listed on "
                                 "the start page, ready to use on every video.")
    host._cx_save_btn.clicked.connect(lambda: save_experiment(host, exp))
    mv.addSpacing(4)
    mv.addWidget(host._cx_save_btn)
    v.addWidget(host._cx_measure_box)
    pl.addWidget(w)
    from PyQt5.QtCore import QTimer

    def wire():
        zd = getattr(host, "zone_drawer", None)
        if zd is None:                 # built before the video panel exists
            QTimer.singleShot(0, wire)
            return
        zd.zones_changed.connect(lambda *_a: _after_drag(host, exp))
        zd.shape_drawn.connect(lambda kind, pts: _on_drawn(host, exp, kind, pts))
    wire()
    if getattr(host, "lbl_box_zones", None) is not None:
        host.lbl_box_zones.hide()        # the zone list replaces this status line
        host.lbl_box_zones._keep_hidden = True
    _apply_mode(host, exp)
    refresh_designer(host, exp)


def _apply_mode(host, exp):
    locked = bool(getattr(exp, "locked", False))
    host._cx_locked_note.setVisible(locked)
    host._cx_edit_row.setVisible(not locked)
    host._cx_measure_box.setVisible(not locked)


def load_design(host, exp, zones, measures, name=None, path=None, locked=False):
    """Put a design into this tab: a new / edited design (locked=False) or
    a saved experiment in use (locked=True: zones and measures fixed, zones
    can only be moved to fit the video)."""
    exp.locked = bool(locked)
    exp.name = name or "Custom Experiment"
    host._cx_name, host._cx_path = name, path
    host._box_params = dict(exp.params_of(host), zones=[dict(z) for z in zones],
                            measures=list(measures))
    box_ui.refresh_zones(host, exp)
    if hasattr(host, "_cx_list"):
        _apply_mode(host, exp)
        refresh_designer(host, exp, select=0)
    host._cx_dirty = False


def save_experiment(host, exp):
    """Ask for a name and save the design to the experiment library."""
    from PyQt5.QtWidgets import QInputDialog
    from . import library
    p = exp.params_of(host)
    name, ok = QInputDialog.getText(host, "Save experiment", "Experiment name:",
                                    text=getattr(host, "_cx_name", None) or "")
    name = (name or "").strip()
    if not ok or not name:
        return None
    path = getattr(host, "_cx_path", None)
    import os
    if path is None and library.find(name):
        ans = QMessageBox.question(host, "Save experiment",
                                   f"An experiment called '{name}' already exists. Replace it?")
        if ans != QMessageBox.Yes:
            return None
    try:
        path = library.save(name, p["zones"], p["measures"], path=path)
    except (OSError, ValueError) as e:
        QMessageBox.warning(host, "Save experiment", f"Could not save the experiment:\n{e}")
        return None
    host._cx_name, host._cx_path, host._cx_dirty = name, path, False
    exp.name = name
    QMessageBox.information(host, "Save experiment",
                            f"'{name}' is saved. Open it from the start page "
                            "(Open an experiment) to use it on your videos.")
    return path


def refresh_designer(host, exp, select=None):
    """Fill list + checkboxes from the current design (after load / undo)."""
    if not hasattr(host, "_cx_list"):
        return
    p = exp.params_of(host)
    lst = host._cx_list
    cur = lst.currentRow() if select is None else select
    lst.blockSignals(True)
    lst.clear()
    for z in p["zones"]:
        it = QListWidgetItem(_dot(z.get("color")), _item_text(z))
        lst.addItem(it)
    lst.blockSignals(False)
    if lst.count():
        lst.setCurrentRow(max(0, min(cur, lst.count() - 1)))
    for key, cb in host._cx_measures.items():
        cb.blockSignals(True)
        cb.setChecked(key in p["measures"])
        cb.blockSignals(False)
    has_line = any(z.get("shape") == "line" for z in p["zones"])
    host._cx_measures["crossings"].setEnabled(has_line)
    _show_form(host, exp)


def _after_drag(host, exp):
    """A zone was moved on the video: show its new position in the fields."""
    if getattr(host, "_cx_dragged", False):
        host._cx_dragged = False
        _show_form(host, exp)


def _measures_changed(host, exp):
    host._cx_dirty = True
    box_ui._set(host, exp, "measures",
                [k for k, cb in host._cx_measures.items() if cb.isChecked()])


def _remove(host, exp):
    i = host._cx_list.currentRow()
    zones = _zones(host, exp)
    if 0 <= i < len(zones):
        zones.pop(i)
        _commit(host, exp, zones)
        refresh_designer(host, exp, select=max(0, i - 1))


def _update(host, exp, i, **changes):
    zones = _zones(host, exp)
    if not (0 <= i < len(zones)):
        return
    zones[i].update(changes)
    _commit(host, exp, zones)
    if "name" in changes or "color" in changes:
        it = host._cx_list.item(i)
        if it is not None:
            it.setText(_item_text(zones[i]))
            it.setIcon(_dot(zones[i].get("color")))


def _spin(value, lo, hi, suffix, step=1.0, decimals=1):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setSuffix(suffix)
    s.setValue(float(value))
    s.setKeyboardTracking(False)      # apply on Enter / arrows, not per keystroke
    return s


def _show_form(host, exp):
    lay = host._cx_form_lay
    while lay.count():
        item = lay.takeAt(0)
        if item.widget() is not None:
            item.widget().deleteLater()
    i = host._cx_list.currentRow()
    zones = _zones(host, exp)
    if not (0 <= i < len(zones)):
        host._cx_form.setVisible(False)
        return
    host._cx_form.setVisible(True)
    z = zones[i]
    shape = z.get("shape")
    r = 0

    def add_row(label, widget, tip=""):
        nonlocal r
        lb = QLabel(label)
        theme.set_tone(lb, "text2")
        lay.addWidget(lb, r, 0)
        lay.addWidget(widget, r, 1)
        if tip:
            widget.setToolTip(tip)
        r += 1

    locked = bool(getattr(exp, "locked", False))
    name = QLineEdit(z.get("name", ""))
    name.editingFinished.connect(
        lambda: _update(host, exp, i, name=name.text().strip() or SHAPE_LABELS[shape]))
    if not locked:
        add_row("Name", name, "Shown in the results and on the video")

    color = QPushButton()
    color.setFixedSize(46, 20)
    color.setStyleSheet(f"background:{z.get('color')}; border-radius:4px;")

    def pick():
        c = QColorDialog.getColor(QColor(z.get("color", "#FFFFFF")), host, "Zone colour")
        if c.isValid():
            color.setStyleSheet(f"background:{c.name()}; border-radius:4px;")
            _update(host, exp, i, color=c.name())
    color.clicked.connect(pick)
    if not locked:
        add_row("Colour", color)

    if shape != "line" and not locked:
        pt = QComboBox()
        pt.addItem("Body centre", "body")
        pt.addItem("Nose", "nose")
        pt.setCurrentIndex(max(0, pt.findData(z.get("point", "body"))))
        pt.currentIndexChanged.connect(lambda _k: _update(host, exp, i, point=pt.currentData()))
        add_row("Counts by", pt, "Which point must be inside the zone.\n"
                                 "Nose zones turn nose tracking on.")

    def num(label, key, lo, hi, suffix, tip="", step=1.0):
        s = _spin(z.get(key, 0.0), lo, hi, suffix, step)
        s.valueChanged.connect(lambda val, k=key: _update(host, exp, i, **{k: float(val)}))
        add_row(label, s, tip)

    pos_tip = "Position across the arena: 0 = left / top edge, 100 = right / bottom edge"
    if shape == "line":
        num("Start X", "x", 0, 100, _POS, pos_tip)
        num("Start Y", "y", 0, 100, _POS, pos_tip)
        num("End X", "x2", 0, 100, _POS, pos_tip)
        num("End Y", "y2", 0, 100, _POS, pos_tip)
    elif z.get("pts"):
        # Drawn outline: keep its exact shape; the centre moves it as a whole.
        pts = z["pts"]
        cu = sum(p[0] for p in pts) / len(pts) * 100.0
        cv = sum(p[1] for p in pts) / len(pts) * 100.0

        def move(axis, val):
            """Slide the outline on the video (not in arena coordinates), so
            it keeps exactly the drawn shape even on a tilted arena."""
            zs = _zones(host, exp)
            pz = zs[i]["pts"]
            H = geo.box_homography(host.zone_drawer.arena)
            if H is None:
                return
            c = [sum(p[0] for p in pz) / len(pz), sum(p[1] for p in pz) / len(pz)]
            target = list(c)
            target[axis] = float(val) / 100.0
            (cx, cy), (tx, ty) = geo.from_box(H, [tuple(c), tuple(target)])
            vid = geo.from_box(H, pz)
            u, v = geo.to_box(H, [x + tx - cx for x, _y in vid], [y + ty - cy for _x, y in vid])
            _update(host, exp, i, pts=[[round(float(a), 5), round(float(b), 5)]
                                       for a, b in zip(u, v)])
        for label, axis, val in (("Centre X", 0, cu), ("Centre Y", 1, cv)):
            sp = _spin(val, -50, 150, _POS)
            sp.valueChanged.connect(lambda v, a=axis: move(a, v))
            add_row(label, sp, pos_tip)
        w_cm, h_cm = outline_size_cm(pts, exp.dims_of(host))
        size = QLabel(f"{w_cm:.1f} × {h_cm:.1f} cm")
        theme.set_tone(size, "text2")
        add_row("Size", size, "Size of the drawn shape (width × height). Draw it again to resize.")
        hint = QLabel("Drag it on the video to move it"
                      + (" · drag a corner to reshape it."
                         if shape == "polygon" and not locked else "."))
        hint.setWordWrap(True)
        theme.set_tone(hint, "faint", "font-size:11px;")
        lay.addWidget(hint, r, 0, 1, 2)
        r += 1
    else:
        num("Centre X", "x", 0, 100, _POS, pos_tip)
        num("Centre Y", "y", 0, 100, _POS, pos_tip)
        if locked:
            pass                                      # size is part of the design
        elif shape == "circle":
            num("Diameter", "w", 0.5, 500, " cm", step=0.5)
        elif shape == "square":
            num("Side", "w", 0.5, 500, " cm", step=0.5)
        else:
            num("Width", "w", 0.5, 500, " cm", step=0.5)
            num("Height", "h", 0.5, 500, " cm", step=0.5)
    lay.setColumnStretch(1, 1)


def _save(host, exp):
    path, _f = QFileDialog.getSaveFileName(host, "Save custom design", "custom_design.json",
                                           "Design files (*.json)")
    if not path:
        return
    try:
        exp.save_design(path, exp.design_of(host))
    except OSError as e:
        QMessageBox.warning(host, "Save design", f"Could not save the design:\n{e}")


def _load(host, exp):
    path, _f = QFileDialog.getOpenFileName(host, "Load custom design", "",
                                           "Design files (*.json)")
    if not path:
        return
    try:
        zones, measures = exp.load_design(path)
    except (OSError, ValueError) as e:
        QMessageBox.warning(host, "Load design", f"Could not load the design:\n{e}")
        return
    host._box_params = dict(exp.params_of(host), zones=zones, measures=measures)
    _commit(host, exp, zones)
    refresh_designer(host, exp, select=0)
