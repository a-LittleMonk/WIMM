"""Preview | Output | Export tab header with the animal-metadata chips
(redesign v2). Replaces the native QTabBar of the embedded tab widget."""
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from gui import icons, theme
from gui.widgets_v2 import mono_font


class _Chip(QLabel):
    """`Caption value` chip; value optionally mono."""

    def __init__(self, caption, mono=False, parent=None):
        super().__init__(parent)
        self._cap, self._mono = caption, mono
        self.setTextFormat(Qt.RichText)
        self.setObjectName("MetaChip")
        self.setFixedHeight(22)

    def set_value(self, value):
        if not value:
            self.hide()
            return
        fam = f"font-family:'{theme.mono_family()}';" if self._mono else ""
        self.setText(f"<span style='color:{theme.FAINT}'>{self._cap}</span>&nbsp;&nbsp;"
                     f"<span style=\"{fam} color:{theme.TEXT}; font-weight:500\">{value}</span>")
        self.show()


class MainTabHeader(QWidget):
    def __init__(self, tabs, embedded, parent=None):
        super().__init__(parent)
        self.setObjectName("MainTabHeader")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(40)
        self._tabs, self._et = tabs, embedded
        tabs.tabBar().hide()
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 0, 12, 0)
        h.setSpacing(2)
        self._btns = []
        for i in range(tabs.count()):
            b = QPushButton(tabs.tabText(i))
            b.setCheckable(True)
            b.setProperty("maintab", True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, k=i: tabs.setCurrentIndex(k))
            h.addWidget(b)
            self._btns.append(b)
        h.addStretch(1)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.c_animal = _Chip("Animal", True)
        self.c_group = _Chip("Group")
        self.c_sex = _Chip("Sex")
        self.c_trial = _Chip("Trial", True)
        for c in (self.c_animal, self.c_group, self.c_sex, self.c_trial):
            chips.addWidget(c)
        self.c_state = QLabel()
        self.c_state.setObjectName("TrackedChip")
        self.c_state.setFixedHeight(22)
        chips.addWidget(self.c_state)
        h.addLayout(chips)
        tabs.currentChanged.connect(self._sync)
        self._sync(tabs.currentIndex())
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        theme.notifier.changed.connect(lambda _m: self.refresh())
        self.refresh()

    def _sync(self, idx):
        for i, b in enumerate(self._btns):
            b.setChecked(i == idx)

    def refresh(self):
        et = self._et
        try:
            self.c_animal.set_value(et.edit_meta_id.text().strip())
            self.c_group.set_value(et.edit_meta_group.text().strip())
            self.c_sex.set_value(et.combo_meta_sex.currentText().strip()[:1])
            self.c_trial.set_value(et.edit_meta_trial.text().strip())
            tracked = bool(et.tracking_results)
        except Exception:
            return
        self.c_state.setVisible(tracked)
        if tracked:
            self.c_state.setText(
                f"<span style='color:{theme.OK}; font-weight:600'>✓&nbsp;&nbsp;Tracked</span>")
