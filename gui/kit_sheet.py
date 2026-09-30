"""Preview window for the instrument control kit.

Run:  python -m gui.kit_sheet        (from the project folder)
Every control in both states, on the real glass pane + aurora backdrop.
The header toggle switches light / dark.
"""
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QPushButton, QVBoxLayout, QWidget,
)

from gui import theme
from gui.backdrop import AuroraBackdrop
from gui.kit import LampToggle, MeasureField, ScaleControl
from gui.redesign_widgets import SegmentedControl, ThemeToggle


def _label(text, role):
    lb = QLabel(text)
    lb.setProperty("role", role)
    return lb


def _section(title, caption):
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(10)
    v.addWidget(_label(title, "kit-section"))
    cap = _label(caption, "kit-caption")
    cap.setWordWrap(True)
    v.addWidget(cap)
    return box, v


def _button(text, **props):
    b = QPushButton(text)
    for k, val in props.items():
        b.setProperty(k, val)
    return b


def _form_row(grid, row, label, widget, note=None):
    grid.addWidget(_label(label, "kit-label"), row, 0, Qt.AlignVCenter)
    grid.addWidget(widget, row, 1)
    if note is not None:
        grid.addWidget(note, row + 1, 1)


def build_sheet():
    sheet = QWidget()
    sheet.setObjectName("KitSheet")
    grid = QGridLayout(sheet)
    grid.setContentsMargins(28, 24, 28, 28)
    grid.setHorizontalSpacing(44)
    grid.setVerticalSpacing(30)

    # Buttons
    box, v = _section("Buttons", "One primary action per panel. Labels say exactly what happens.")
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(_button("Run tracking", primary=True))
    row.addWidget(_button("Load video…"))
    row.addWidget(_button("Reset view", ghost=True))
    row.addWidget(_button("Delete run", danger=True))
    dis = _button("Export results")
    dis.setEnabled(False)
    row.addWidget(dis)
    dis_p = _button("Run tracking", primary=True)
    dis_p.setEnabled(False)
    row.addWidget(dis_p)
    row.addStretch(1)
    v.addLayout(row)
    v.addStretch(1)
    grid.addWidget(box, 0, 0, 1, 2)

    # Fields
    box, v = _section("Fields", "Numbers are right-aligned with their unit. Invalid values say why.")
    f = QGridLayout()
    f.setHorizontalSpacing(14)
    f.setVerticalSpacing(8)
    f.setColumnMinimumWidth(0, 110)
    animal = QLineEdit("M08")
    animal.setPlaceholderText("e.g. M08")
    _form_row(f, 0, "Animal ID", animal)
    _form_row(f, 1, "Arena width", MeasureField(45.0, 1, 500, 0.5, 1, "cm"))
    fps = MeasureField(0, 0, 240, 1, 0, "fps")
    fps.set_error("Frame rate must be above 0")
    _form_row(f, 2, "Frame rate", fps, _label("Frame rate must be above 0 fps", "kit-error"))
    shape = QComboBox()
    shape.addItems(["Square", "Circle", "Custom polygon"])
    _form_row(f, 4, "Arena shape", shape)
    v.addLayout(f)
    v.addStretch(1)
    grid.addWidget(box, 1, 0)

    # Toggles
    box, v = _section("Toggles", "The lamp lights when the option is on.")
    v.addWidget(LampToggle("Auto-detect arena", True))
    v.addWidget(LampToggle("Show trail", False))
    v.addWidget(LampToggle("Subtract background", True))
    off = LampToggle("GPU acceleration (not available)", False)
    off.setEnabled(False)
    v.addWidget(off)
    v.addStretch(1)
    grid.addWidget(box, 1, 1)

    # Choices
    box, v = _section("Choices", "Checkboxes for independent options, segments for one-of-few.")
    c1 = QCheckBox("Include center zone in export")
    c1.setChecked(True)
    v.addWidget(c1)
    v.addWidget(QCheckBox("Save annotated video"))
    seg_row = QHBoxLayout()
    seg_row.addWidget(_label("Tracking point", "kit-label"))
    seg = SegmentedControl(["Centroid", "Nose", "Tail base"], 0)
    seg.setFixedHeight(28)
    seg_row.addWidget(seg)
    seg_row.addStretch(1)
    v.addLayout(seg_row)
    chips = QHBoxLayout()
    chips.setSpacing(6)
    for name, on in (("Arena", True), ("Zones", True), ("Trail", False), ("Heatmap", False)):
        ch = QCheckBox(name)
        ch.setProperty("chip", True)
        ch.setChecked(on)
        chips.addWidget(ch)
    chips.addStretch(1)
    v.addLayout(chips)
    v.addStretch(1)
    grid.addWidget(box, 2, 0)

    # Scales
    box, v = _section("Scales", "Calibrated sliders; type an exact value in the box.")
    v.addWidget(_label("Center zone size", "kit-label"))
    v.addWidget(ScaleControl(50, 0, 100, "%", major=25, minor=5))
    v.addWidget(_label("Detection sensitivity", "kit-label"))
    v.addWidget(ScaleControl(25, 0, 50, "", major=10, minor=2))
    v.addStretch(1)
    grid.addWidget(box, 2, 1)
    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)
    grid.setRowStretch(3, 1)  # spare height collects below the sections
    return sheet


class KitWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Control kit — preview")
        backdrop = AuroraBackdrop()
        outer = QVBoxLayout(backdrop)
        outer.setContentsMargins(24, 16, 24, 24)
        outer.setSpacing(14)
        top = QHBoxLayout()
        title = QLabel("Control kit")
        title.setStyleSheet("font-size: 18px; font-weight: 700; background: transparent;")
        top.addWidget(title)
        top.addStretch(1)
        self.toggle = ThemeToggle(1 if theme.mode() == "dark" else 0)
        self.toggle.changed.connect(
            lambda i: theme.apply_theme(QApplication.instance(), "dark" if i else "light"))
        top.addWidget(self.toggle)
        outer.addLayout(top)
        pane = QWidget()
        pane.setObjectName("Pane")
        pv = QVBoxLayout(pane)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.addWidget(build_sheet())
        outer.addWidget(pane, 1)
        self.setCentralWidget(backdrop)
        self.resize(1080, 760)


def main():
    from gui.main_window import load_config
    app = QApplication(sys.argv)
    config = load_config()
    theme.load_aurora(config)
    theme.register_bundled_fonts()
    theme.load_fonts(config)
    theme.apply_theme(app, config.get("theme", "dark"))
    w = KitWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
