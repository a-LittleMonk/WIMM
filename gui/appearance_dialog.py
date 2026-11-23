"""View → Appearance: edit the aurora backdrop for light and dark mode.

Per mode the user picks a background colour, how many gradient colours to
blend (1..theme.AURORA_MAX), and each colour's shade and strength — or starts
from a preset. Edits preview live; Cancel restores what was there before.
"""
from PyQt5.QtCore import QEvent, QObject, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication, QColorDialog, QComboBox, QCompleter, QTabWidget, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QSpinBox, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from gui import theme
from gui.backdrop import paint_aurora
from gui.redesign_widgets import SegmentedControl

_MODES = ("light", "dark")


class ColorSwatch(QPushButton):
    """Button showing a colour; click opens the colour picker."""
    colorChanged = pyqtSignal(str)

    def __init__(self, color="#000000", title="Choose colour", parent=None):
        super().__init__(parent)
        self._title = title
        self.setFixedSize(46, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._pick)
        self.set_color(color)

    def color(self):
        return self._color

    def set_color(self, color):
        self._color = QColor(color).name().upper()
        self.setToolTip(self._color)
        self.setStyleSheet(
            f"QPushButton {{ background: {self._color}; border: 1px solid rgba(128,128,128,120);"
            f" border-radius: 6px; }}"
            f"QPushButton:hover {{ border: 2px solid {theme.ACCENT}; }}")

    def _pick(self):
        c = QColorDialog.getColor(QColor(self._color), self, self._title)
        if c.isValid():
            self.set_color(c.name())
            self.colorChanged.emit(self._color)


def keep_popup_on_screen(popup, anchor):
    """Move / shrink a popup window so it lies fully inside the available
    area of the monitor its anchor widget is on. Below the anchor if it
    fits, else above, else as much as the screen allows. (Qt sometimes
    opened the font list partly off-screen — e.g. a monitor placed left of
    the main one.)"""
    if popup is None or anchor is None or not popup.isVisible():
        return
    from PyQt5.QtGui import QGuiApplication
    top_left = anchor.mapToGlobal(anchor.rect().topLeft())
    a = QRect(top_left, anchor.size())                  # anchor, global
    screen = (QGuiApplication.screenAt(a.center())
              or anchor.window().windowHandle() and anchor.window().windowHandle().screen()
              or QGuiApplication.primaryScreen())
    avail = screen.availableGeometry()
    g = popup.frameGeometry()
    w = min(g.width(), avail.width())
    h = min(g.height(), avail.height())
    if a.bottom() + h <= avail.bottom():
        y = a.bottom() + 1                               # below
    elif a.top() - h >= avail.top():
        y = a.top() - h                                  # above
    else:
        y = avail.bottom() - h + 1                       # as low as fits
    x = min(max(a.left(), avail.left()), avail.right() - w + 1)
    y = min(max(y, avail.top()), avail.bottom() - h + 1)
    if (w, h) != (g.width(), g.height()):
        popup.resize(w - (g.width() - popup.width()), h - (g.height() - popup.height()))
    if (x, y) != (g.x(), g.y()):
        popup.move(x, y)


class _PopupShowWatcher(QObject):
    """Re-places a popup on screen every time it is shown."""

    def __init__(self, popup, anchor):
        super().__init__(popup)
        self._popup, self._anchor = popup, anchor
        popup.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show:
            QTimer.singleShot(0, lambda: keep_popup_on_screen(self._popup, self._anchor))
        return False


class FontPicker(QComboBox):
    """Office-style font box: type to search (matches anywhere in the name),
    short scrollable list, Enter / click picks. Unknown names revert."""

    VISIBLE = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMaxVisibleItems(self.VISIBLE)
        # Fusion shows every item unless the popup is a plain list view.
        self.setStyleSheet("QComboBox { combobox-popup: 0; }")
        row_css = "QListView::item { min-height: 24px; padding-left: 6px; }"
        self.setItemDelegate(QStyledItemDelegate(self))  # honours row_css
        self.view().setStyleSheet(row_css)
        comp = QCompleter(self.model(), self)
        comp.setCompletionMode(QCompleter.PopupCompletion)
        comp.setFilterMode(Qt.MatchContains)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setMaxVisibleItems(self.VISIBLE)
        comp.popup().setStyleSheet(row_css)
        comp.activated[str].connect(self._pick_text)
        self.setCompleter(comp)
        # The type-to-search list: keep it on screen too.
        _PopupShowWatcher(comp.popup(), self)
        self.lineEdit().editingFinished.connect(lambda: self._pick_text(self.currentText()))
        self.lineEdit().setPlaceholderText("Type a font name…")

    def showPopup(self):
        super().showPopup()
        keep_popup_on_screen(self.view().window(), self)

    def _pick_text(self, text):
        want = text.strip().lower()
        for i in range(self.count()):
            if self.itemText(i).lower() == want and self.itemText(i):
                if i != self.currentIndex():
                    self.setCurrentIndex(i)
                else:
                    self.setEditText(self.itemText(i))
                return
        self.setEditText(self.itemText(self.currentIndex()))  # no such font


class AuroraPreview(QWidget):
    """Backdrop sample with a pane floating on it, as the app will look."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self._spec = None
        self._mode = "dark"

    def set_spec(self, spec, mode):
        self._spec = spec
        self._mode = mode
        self.update()

    def paintEvent(self, _e):
        if not self._spec:
            return
        p = QPainter(self)
        paint_aurora(p, self.width(), self.height(), self._spec)
        pc, pa = theme.panel_of(self._mode, self._spec)
        fill = QColor(pc)
        fill.setAlphaF(pa)
        rim = QColor("#FFFFFF")
        rim.setAlphaF(0.85 if self._mode == "light" else 0.18)
        pane = QRectF(self.width() * 0.08, 18, self.width() * 0.84, self.height() - 36)
        p.setPen(QPen(rim, 1))
        p.setBrush(fill)
        p.drawRoundedRect(pane, 12, 12)
        p.setPen(QColor("#1C1737" if self._mode == "light" else "#EEEAFB"))
        p.drawText(pane.adjusted(16, 12, -16, -12), Qt.AlignLeft | Qt.AlignTop, "Panel")
        p.end()


class AppearanceDialog(QDialog):
    def __init__(self, config, save_config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Appearance")
        self.setMinimumWidth(460)
        self._config = config
        self._save_config = save_config
        self._original = {m: theme.copy_spec(theme.AURORA[m]) for m in _MODES}
        self._specs = {m: theme.copy_spec(theme.AURORA[m]) for m in _MODES}
        # The colour preset each mode started from — "Reset colours" goes
        # back to it (not to the built-in default). Remembered in config so
        # it survives closing the window.
        saved = config.get("aurora_preset") if isinstance(config.get("aurora_preset"), dict) else {}
        self._base_preset = {}
        for m in _MODES:
            match = next((n for n, p in theme.AURORA_PRESETS[m].items()
                          if theme.copy_spec(p) == self._specs[m]), None)
            name = match or saved.get(m)
            self._base_preset[m] = name if name in theme.AURORA_PRESETS[m] else None
        self._mode = theme.mode()
        self._loading = False
        # Restyling the whole app takes ~0.2 s — do it once edits pause.
        self._restyle = QTimer(self)
        self._restyle.setSingleShot(True)
        self._restyle.setInterval(150)
        self._restyle.timeout.connect(self._apply_live)

        outer = QVBoxLayout(self)
        outer.setSpacing(12)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        colours = QWidget()
        root = QVBoxLayout(colours)
        root.setContentsMargins(12, 14, 12, 8)
        root.setSpacing(12)
        self.tabs.addTab(colours, "Colours")

        top = QHBoxLayout()
        top.addWidget(QLabel("Edit palette for"))
        self.seg = SegmentedControl(["Light mode", "Dark mode"], _MODES.index(self._mode))
        for b in self.seg._btns:
            b.setMinimumWidth(96)  # room for the bold checked label
        self.seg.changed.connect(self._on_mode)
        top.addWidget(self.seg)
        top.addStretch(1)
        root.addLayout(top)

        self.preview = AuroraPreview()
        root.addWidget(self.preview)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        self.cmb_preset = QComboBox()
        self.cmb_preset.activated.connect(self._on_preset)
        form.addRow("Preset", self.cmb_preset)
        self.sw_base = ColorSwatch(title="Background colour")
        self.sw_base.colorChanged.connect(self._on_base)
        form.addRow("Background", self.sw_base)
        self.spn_count = QSpinBox()
        self.spn_count.setRange(1, theme.AURORA_MAX)
        self.spn_count.setFixedWidth(70)
        self.spn_count.valueChanged.connect(self._on_count)
        form.addRow("Gradient colours", self.spn_count)
        panel_row = QHBoxLayout()
        panel_row.setSpacing(8)
        self.sw_panel = ColorSwatch(title="Panel colour")
        self.sw_panel.colorChanged.connect(self._on_panel_color)
        self.sld_panel = QSlider(Qt.Horizontal)
        self.sld_panel.setRange(0, 100)
        self.sld_panel.setToolTip("Panel opacity — lower shows more of the background")
        self.lbl_panel = QLabel()
        self.lbl_panel.setFixedWidth(36)
        self.lbl_panel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.sld_panel.valueChanged.connect(self._on_panel_opacity)
        self.btn_panel_auto = QPushButton("Match palette")
        self.btn_panel_auto.setToolTip("Tint panels from the gradient colours automatically")
        self.btn_panel_auto.clicked.connect(self._on_panel_auto)
        panel_row.addWidget(self.sw_panel)
        panel_row.addWidget(QLabel("Opacity"))
        panel_row.addWidget(self.sld_panel, 1)
        panel_row.addWidget(self.lbl_panel)
        panel_row.addWidget(self.btn_panel_auto)
        form.addRow("Panels", panel_row)
        acc_row = QHBoxLayout()
        acc_row.setSpacing(8)
        self.sw_accent = ColorSwatch(title="Highlight colour")
        self.sw_accent.colorChanged.connect(self._on_accent)
        self.lbl_accent_hint = QLabel()
        self.lbl_accent_hint.setWordWrap(True)
        theme.set_tone(self.lbl_accent_hint, "warn")
        acc_row.addWidget(self.sw_accent)
        acc_row.addWidget(self.lbl_accent_hint, 1)
        form.addRow("Highlight", acc_row)
        root.addLayout(form)

        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(6)
        root.addLayout(self.rows_box)
        self._rows = []
        for i in range(theme.AURORA_MAX):
            self._rows.append(self._make_row(i))

        root.addStretch(1)
        reset_row = QHBoxLayout()
        b_reset = QPushButton("Reset colours")
        b_reset.clicked.connect(self._on_reset)
        reset_row.addWidget(b_reset)
        reset_row.addStretch(1)
        root.addLayout(reset_row)
        btns = QHBoxLayout()
        btns.addStretch(1)
        b_cancel = QPushButton("Cancel")
        b_cancel.clicked.connect(self.reject)
        btns.addWidget(b_cancel)
        b_save = QPushButton("Save")
        b_save.setProperty("primary", True)
        b_save.setDefault(True)
        b_save.clicked.connect(self.accept)
        btns.addWidget(b_save)
        outer.addLayout(btns)

        self._load_mode()

    # ── rows ─────────────────────────────────────────────────────────────
    def _make_row(self, i):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(f"Colour {i + 1}")
        lbl.setFixedWidth(64)
        sw = ColorSwatch(title=f"Gradient colour {i + 1}")
        sw.colorChanged.connect(lambda c, k=i: self._on_row_color(k, c))
        sld = QSlider(Qt.Horizontal)
        sld.setRange(0, 100)
        sld.setToolTip("Strength")
        val = QLabel()
        val.setFixedWidth(36)
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sld.valueChanged.connect(lambda v, k=i, lab=val: self._on_row_strength(k, v, lab))
        h.addWidget(lbl)
        h.addWidget(sw)
        h.addWidget(QLabel("Strength"))
        h.addWidget(sld, 1)
        h.addWidget(val)
        self.rows_box.addWidget(w)
        return w, sw, sld, val

    # ── state ────────────────────────────────────────────────────────────
    def _spec(self):
        return self._specs[self._mode]

    def _load_mode(self):
        self._loading = True
        spec = self._spec()
        self.cmb_preset.clear()
        self.cmb_preset.addItems(list(theme.AURORA_PRESETS[self._mode]) + ["Custom"])
        self._sync_preset_label()
        self.sw_base.set_color(spec["base"])
        self.spn_count.setValue(len(spec["colors"]))
        self._load_panel()
        for i, (w, sw, sld, val) in enumerate(self._rows):
            on = i < len(spec["colors"])
            w.setVisible(on)
            if on:
                c, a = spec["colors"][i]
                sw.set_color(c)
                sld.setValue(round(a * 100))
                val.setText(f"{round(a * 100)}%")
        self._loading = False
        self._changed()

    def _sync_preset_label(self):
        spec = self._spec()
        name = next((n for n, p in theme.AURORA_PRESETS[self._mode].items()
                     if theme.copy_spec(p) == spec), "Custom")
        self.cmb_preset.setCurrentText(name)

    def _load_panel(self):
        was = self._loading
        self._loading = True
        pc, pa = theme.panel_of(self._mode, self._spec())
        self.sw_panel.set_color(pc)
        self.sld_panel.setValue(round(pa * 100))
        self.lbl_panel.setText(f"{round(pa * 100)}%")
        self.btn_panel_auto.setEnabled(bool(self._spec().get("panel")))
        acc = theme.accent_of(self._mode, self._spec())
        self.sw_accent.set_color(acc)
        # Accent is also used as text colour on the panels — check it reads.
        seen = theme._mix(self._spec()["base"], pc, pa)
        low = theme.contrast(acc, seen) < 3.0
        self.lbl_accent_hint.setText(
            "Low contrast with the panels — highlighted text may be hard to read." if low else "")
        self._loading = was

    def _changed(self):
        self.preview.set_spec(self._spec(), self._mode)
        if not self._loading:
            self._sync_preset_label()
            self._load_panel()  # auto panel follows gradient edits
        # Live preview on the main window when editing the mode it shows.
        theme.set_aurora(self._mode, self._spec())
        theme.notifier.aurora_changed.emit()
        if self._mode == theme.mode():
            self._restyle.start()

    def _apply_live(self):
        theme.apply_theme(QApplication.instance())

    # ── handlers ─────────────────────────────────────────────────────────
    def _on_mode(self, index):
        self._mode = _MODES[index]
        self._load_mode()

    def _on_preset(self, index):
        name = self.cmb_preset.itemText(index)
        preset = theme.AURORA_PRESETS[self._mode].get(name)
        if preset:
            self._base_preset[self._mode] = name
            self._specs[self._mode] = theme.copy_spec(preset)
            self._load_mode()

    def _on_panel_color(self, color):
        self._spec()["panel"] = [color, self.sld_panel.value() / 100.0]
        self._changed()

    def _on_panel_opacity(self, v):
        self.lbl_panel.setText(f"{v}%")
        if self._loading:
            return
        self._spec()["panel"] = [self.sw_panel.color(), v / 100.0]
        self._changed()

    def _on_accent(self, color):
        self._spec()["accent"] = color
        self._changed()

    def _on_panel_auto(self):
        self._spec().pop("panel", None)
        self._changed()

    def _on_base(self, color):
        self._spec()["base"] = color
        self._changed()

    def _on_count(self, n):
        if self._loading:
            return
        colors = self._spec()["colors"]
        while len(colors) < n:
            # New colour: repeat an existing hue so the look stays coherent.
            c, a = colors[len(colors) % max(1, len(colors))] if colors else ("#6D4BE6", 0.4)
            colors.append([c, a])
            w, sw, sld, val = self._rows[len(colors) - 1]
            self._loading = True
            sw.set_color(c)
            sld.setValue(round(a * 100))
            val.setText(f"{round(a * 100)}%")
            self._loading = False
        del colors[n:]
        for i, row in enumerate(self._rows):
            row[0].setVisible(i < n)
        self._changed()

    def _on_row_color(self, i, color):
        self._spec()["colors"][i][0] = color
        self._changed()

    def _on_row_strength(self, i, v, lab):
        lab.setText(f"{v}%")
        if self._loading:
            return
        self._spec()["colors"][i][1] = v / 100.0
        self._changed()

    def _on_reset(self):
        preset = theme.AURORA_PRESETS[self._mode].get(self._base_preset.get(self._mode))
        self._specs[self._mode] = (theme.copy_spec(preset) if preset
                                   else theme.aurora_default(self._mode))
        self._load_mode()

    # ── close ────────────────────────────────────────────────────────────
    def accept(self):
        for m in _MODES:
            theme.set_aurora(m, self._specs[m])
        self._config["aurora"] = {m: theme.copy_spec(theme.AURORA[m]) for m in _MODES}
        self._config["aurora_preset"] = {m: n for m, n in self._base_preset.items() if n}
        self._save_config()
        self._restyle.stop()
        # Re-apply so panels and base colours pick up the saved palette.
        theme.apply_theme(QApplication.instance())
        super().accept()

    def reject(self):
        for m in _MODES:
            theme.set_aurora(m, self._original[m])
        self._restyle.stop()
        theme.apply_theme(QApplication.instance())
        super().reject()
