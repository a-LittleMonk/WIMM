"""Shared building blocks for the experiment setup cards.

Every experiment builds its setup from the same two cards, laid out the
same way (Open Field is the reference):

  Arena — how the apparatus is defined: a "Define arena" dropdown,
          Redraw, a × clear button, then (Full view only) perspective and
          other apparatus options.
  Zones — the experiment's own zones: size sliders, per-zone options,
          zone colours (Full view only) and a one-line status.

Experiments only supply their own menu entries, zone controls and
handlers; the card titles, control types and layout come from here.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QMenu, QSlider, QSpinBox,
)

from gui import theme


# ── Cards ──────────────────────────────────────────────────────────────
def arena_card(host):
    grp = host._group("Arena", status_id="geometry", name="Arena")
    return grp, QVBoxLayout(grp)


def zones_card(host):
    grp = host._group("Zones", status_id="zones", name="Zones")
    return grp, QVBoxLayout(grp)


# ── Arena row: [Define arena ▾] [Redraw] [×] ───────────────────────────
def define_row(host, items, on_clear, attr="btn_define_arena",
               on_redraw=None, video_gated=True):
    """Build the Define-arena dropdown row.

    items: [(label, mode_key, fn, tooltip_or_None), ...]
    on_redraw(mode_key): re-run the current mode; defaults to calling the
        item's fn again.
    Returns (layout, define_btn, redraw_btn, clear_btn). The dropdown text
    shows the chosen mode; `host._<attr>_mode` holds its key.
    """
    from gui.widgets_v2 import ArenaModeButton, IconButton
    btn = ArenaModeButton()
    btn.setText("Define arena")
    menu = QMenu(btn)
    actions = {}
    mode_attr = f"_{attr}_mode"

    def choose(key):
        label, fn, _tip = actions[key]
        setattr(host, mode_attr, key)
        btn.setText(label)
        fn()

    for label, key, fn, tip in items:
        act = menu.addAction(label)
        if tip:
            act.setToolTip(tip)
        actions[key] = (label, fn, tip)
        act.triggered.connect(lambda _=False, k=key: choose(k))
    btn.setMenu(menu)

    def redraw():
        key = getattr(host, mode_attr, None) or items[0][1]
        if on_redraw is not None:
            setattr(host, mode_attr, key)
            btn.setText(actions[key][0])
            on_redraw(key)
        else:
            choose(key)

    redraw_btn = host._btn("Redraw")
    redraw_btn.setFixedHeight(28)
    redraw_btn.clicked.connect(redraw)
    clear_btn = IconButton("x", 11, "FAINT", "TEXT", "Clear arena", 28)
    clear_btn.clicked.connect(on_clear)
    btn.follow(redraw_btn)
    btn.follow(clear_btn)
    if video_gated:
        btn.setEnabled(False)
        gated = getattr(host, "_video_gated", None)
        if gated is None:
            gated = host._video_gated = []
        gated.append(btn)

    row = QHBoxLayout()
    row.setSpacing(6)
    row.addWidget(btn, 1)
    row.addWidget(redraw_btn)
    row.addWidget(clear_btn)
    setattr(host, attr, btn)
    host.__dict__.setdefault("_define_actions", {})[attr] = actions
    return row, btn, redraw_btn, clear_btn


def set_define_mode(host, key, attr="btn_define_arena"):
    """Show `key` as the chosen mode without running it (used on load)."""
    btn = getattr(host, attr, None)
    actions = getattr(host, "_define_actions", {}).get(attr, {})
    if btn is None or key not in actions:
        return
    setattr(host, f"_{attr}_mode", key)
    btn.setText(actions[key][0])


# ── Value slider: [====o====]  [ 50% ] ────────────────────────────────
def pct_slider(host, label, spin, lo, hi, scale=1.0, off_at_zero=False,
               tip=None, suffix="%"):
    """Visible slider + value pill driving a hidden spin box (the data
    holder other code reads/writes). `scale` converts spin units to the
    shown % (e.g. 100 for a 0–1 fraction). Returns a form row."""
    from gui.widgets_v2 import ValueEdit, form_row, mono_font
    spin.hide()
    spin._keep_hidden = True
    slider = QSlider(Qt.Horizontal)
    slider.setRange(int(lo), int(hi))
    slider.setMinimumHeight(22)

    def fmt(pct):
        return "Off" if (off_at_zero and pct <= 0) else f"{pct}{suffix}"
    pill = ValueEdit(slider, fmt, role="valuepill")
    pill.setAlignment(Qt.AlignCenter)
    pill.setFixedWidth(44)
    pill.setProperty("role", "valuepill")
    pill.setFont(mono_font(11))

    def show(v):
        pct = int(round(float(v) * scale))
        slider.blockSignals(True)
        slider.setValue(max(slider.minimum(), min(slider.maximum(), pct)))
        slider.blockSignals(False)
        pill.show_value(pct)

    def to_spin(v):
        val = v / float(scale)
        # QSpinBox (box tests) takes whole numbers only; QDoubleSpinBox
        # (Y-Maze / EPM fractions) keeps the decimal.
        spin.setValue(int(round(val)) if isinstance(spin, QSpinBox) else val)

    slider.valueChanged.connect(to_spin)
    spin.valueChanged.connect(show)
    show(spin.value())
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(slider, 1)
    row.addWidget(pill)
    row.addWidget(spin)          # hidden; keeps it parented to the card
    w = form_row(label, row)
    if tip:
        w.setToolTip(tip)
        slider.setToolTip(tip)
    return w


# ── Perspective switch (Full view only) ────────────────────────────────
def perspective_switch(host, attr, on_toggled, tip, extra=None):
    """'Correct perspective' switch in the Arena card, Full view only.
    `extra` is an optional widget shown beside it (e.g. EPM's Adjust…)."""
    from gui.widgets_v2 import SwitchBox
    sw = SwitchBox("Correct perspective")
    sw.setToolTip(tip)
    sw.toggled.connect(on_toggled)
    setattr(host, attr, sw)
    wrap = QWidget()
    h = QHBoxLayout(wrap)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    h.addWidget(sw, 1)
    if extra is not None:
        h.addWidget(extra)
    advanced(host, wrap)
    return wrap


# ── Zone colours (Full view only) ──────────────────────────────────────
def color_buttons(host, get_colors, items, on_pick):
    """Zone-colour buttons (Full view only). More than three zones wrap
    onto rows of up to three so labels are never cut off."""
    from gui.widgets_v2 import ColorButtons
    if len(items) <= 3:
        w = ColorButtons(get_colors, items)
        w.picked.connect(on_pick)
        advanced(host, w)
        return w
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(4)
    rows = []
    for i in range(0, len(items), 3):
        r = ColorButtons(get_colors, items[i:i + 3])
        r.picked.connect(on_pick)
        v.addWidget(r)
        rows.append(r)
    box.refresh = lambda: [r.refresh() for r in rows]
    advanced(host, box)
    return box


# ── Misc ───────────────────────────────────────────────────────────────
def status_label(text):
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    theme.set_tone(lbl, "faint", "font-size:11px;")
    return lbl


def hidden(widget):
    """Keep a data-holder widget (old radio/combos other code reads)
    parented but never shown."""
    widget.hide()
    widget._keep_hidden = True
    return widget


def advanced(host, widget):
    """Show `widget` only in the Full view (like Open Field's advanced
    controls)."""
    lst = getattr(host, "_advanced_widgets", None)
    if lst is not None:
        lst.append(widget)
    return widget
