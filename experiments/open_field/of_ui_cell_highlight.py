"""Cell-highlight overlay controls.

The widget the user uses to pick the live cell-fill color, opacity, and
to toggle the per-cell number/timer/entries text. Hooks into the
zone_drawer's overlay state via host helpers.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QSlider, QCheckBox, QColorDialog,
)


def _build_cell_highlight_controls(host):
    """Build the cell-highlight section for the View popup.

    Returns a QWidget (matches the peer overlay rows in _build_view_popup_widgets).
    Row order: Color → Opacity → plugin-contributed Hide toggles. Live
    overlay and Min dwell both live in Step 5 Analysis."""
    container = QWidget()
    grid = QGridLayout(container)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(6)
    grid.setVerticalSpacing(4)

    # Row 0 — Color: preset swatches + More
    grid.addWidget(QLabel("Color:"), 0, 0)
    sw_row = QHBoxLayout()
    sw_row.setSpacing(2)
    for hex_c in host.CELL_HIGHLIGHT_PRESETS:
        sw = QPushButton()
        sw.setFixedSize(20, 20)
        sw.setCursor(Qt.PointingHandCursor)
        sw.setStyleSheet(
            f"background-color:{hex_c}; border:1px solid #555; border-radius:3px;"
        )
        sw.setToolTip(hex_c)
        sw.clicked.connect(
            lambda _=False, c=hex_c: host.zone_drawer.set_cell_highlight_color(c)
        )
        sw_row.addWidget(sw)
    more_btn = QPushButton("More…")
    more_btn.setFixedHeight(20)
    more_btn.setFixedWidth(54)
    more_btn.clicked.connect(host._pick_cell_highlight_color)
    sw_row.addWidget(more_btn)
    sw_row.addStretch()
    sw_widget = QWidget()
    sw_widget.setLayout(sw_row)
    grid.addWidget(sw_widget, 0, 1)

    # Row 1 — Opacity
    grid.addWidget(QLabel("Opacity:"), 1, 0)
    opacity = QSlider(Qt.Horizontal)
    opacity.setRange(0, 255)
    opacity.setValue(100)
    opacity.valueChanged.connect(host.zone_drawer.set_cell_highlight_alpha)
    grid.addWidget(opacity, 1, 1)

    # Rows 2+ — plugin-contributed Hide toggles (default unchecked).
    exp = getattr(host, "experiment", None)
    specs = exp.cell_highlight_toggle_specs(host) if exp is not None else []
    for i, (label, getter, setter) in enumerate(specs):
        chk = QCheckBox(label)
        try:
            chk.setChecked(bool(getter()))
        except Exception:
            chk.setChecked(False)
        chk.toggled.connect(setter)
        grid.addWidget(chk, 2 + i, 0, 1, 2)

    return container


def _pick_cell_highlight_color(host):
    cur = QColor(host.zone_drawer._cell_highlight_color)
    c = QColorDialog.getColor(cur, host, "Cell highlight color")
    if c.isValid():
        host.zone_drawer.set_cell_highlight_color(c.name())


def _on_cell_timer_toggled(host, on):
    host.zone_drawer.set_cell_show_timer(on)
    # Refresh times for current scrub frame.
    if host.tracking_results:
        host._push_cell_state_for_frame(host.slider_scrub.value())


def _on_cell_entries_toggled(host, on):
    host.zone_drawer.set_cell_show_entries(on)
    if host.tracking_results:
        host._push_cell_state_for_frame(host.slider_scrub.value())


def _on_live_overlay_toggled(host, on):
    host._live_cell_overlay = bool(on)
