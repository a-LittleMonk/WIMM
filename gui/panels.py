"""Photoshop-style panels for the experiment screen.

PanelHost is an embedded QMainWindow: the preview (video / Output / Export)
is its fixed centre, and Queue / Configuration / Measurements / Speed /
Center-periphery / Missed frames / Frame corrections are dock
panels the user can drag to any side, stack as tabs, pop out as floating
windows, or close. View → Panels (main window) lists them for re-opening.
The arrangement is saved per experiment in config["panel_layout"].
"""
import base64

from PyQt5.QtCore import QByteArray, Qt, QTimer
from PyQt5.QtWidgets import QDockWidget, QFrame, QMainWindow, QVBoxLayout, QWidget

from gui.widgets_v2 import IconButton


def _repolish(w):
    st = w.style()
    st.unpolish(w)
    st.polish(w)
    w.update()


class Panel(QDockWidget):
    """One movable panel. `header` (a PaneHeader) becomes the drag handle;
    pop-out and close buttons are appended to it."""

    def __init__(self, key, title, body, header, parent=None):
        super().__init__(title, parent)
        self.setObjectName(f"panel_{key}")  # saveState() keys on this
        self.key = key
        self.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
                         | QDockWidget.DockWidgetClosable)
        self.header = header
        header.setProperty("panel", True)
        body.setProperty("panel", True)
        # Panel actions (Add, Apply to…) | divider | window buttons.
        div = QFrame()
        div.setObjectName("PanelDivider")
        div.setFixedSize(1, 16)
        self.b_float = IconButton("popout", 12, "FAINT", "TEXT", "Pop out / dock panel", 22)
        self.b_float.clicked.connect(lambda: self.setFloating(not self.isFloating()))
        self.b_close = IconButton("x", 12, "FAINT", "TEXT", "Close panel (reopen from View → Panels)", 22)
        self.b_close.clicked.connect(self.close)
        header.add_right(div)
        header.add_right(self.b_float)
        header.add_right(self.b_close)
        header.setToolTip("Drag to move this panel")
        header.setCursor(Qt.OpenHandCursor)
        self.setTitleBarWidget(header)
        # The holder draws the panel card and keeps a gap under the header.
        self.holder = QWidget()
        self.holder.setObjectName("PanelBody")
        self.holder.setAttribute(Qt.WA_StyledBackground, True)
        hl = QVBoxLayout(self.holder)
        hl.setContentsMargins(0, 10, 0, 0)
        hl.setSpacing(0)
        hl.addWidget(body)
        self.setWidget(self.holder)
        self.topLevelChanged.connect(self._on_floating)

    def _on_floating(self, floating):
        # Floating windows have no aurora behind them — use solid fills.
        for w in (self.header, self.holder):
            w.setProperty("floating", bool(floating))
            _repolish(w)


class PanelHost(QMainWindow):
    def __init__(self, central, config, layout_key, save_config, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelHost")  # transparent in theme.py
        self.setWindowFlags(Qt.Widget)
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks
                            | QMainWindow.AllowTabbedDocks)
        self.setCentralWidget(central)
        self._config = config
        self._key = layout_key
        self._save_config = save_config
        self.panels = []
        self._default_state = None
        self._saver = QTimer(self)
        self._saver.setSingleShot(True)
        self._saver.setInterval(600)
        self._saver.timeout.connect(self._save_state)
        self._min_timer = QTimer(self)
        self._min_timer.setSingleShot(True)
        self._min_timer.setInterval(50)
        self._min_timer.timeout.connect(self._update_window_minimum)

    # Qt squeezes docks on top of each other when the window is smaller
    # than their combined minimum — so the window may not get that small.
    def _update_window_minimum(self):
        win = self.window()
        if win is self or not self.isVisible():
            return
        base = self._base_minimum(win)
        need = self.minimumSizeHint()
        extra_w = max(0, win.width() - self.width())    # header, footer, margins
        extra_h = max(0, win.height() - self.height())
        w, h = need.width() + extra_w, need.height() + extra_h
        screen = win.screen().availableGeometry() if win.screen() else None
        if screen is not None:
            w, h = min(w, screen.width()), min(h, screen.height())
        win.setMinimumSize(max(w, base.width()), max(h, base.height()))

    @staticmethod
    def _base_minimum(win):
        # The window's own minimum (set by MainWindow) — never go below it.
        if not hasattr(win, "_panel_base_min"):
            win._panel_base_min = win.minimumSize()
        return win._panel_base_min

    def showEvent(self, e):
        super().showEvent(e)
        self._min_timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        win = self.window()
        if win is not self:
            win.setMinimumSize(self._base_minimum(win))   # launcher etc.

    def add_panel(self, key, title, body, header, area, min_width=None):
        p = Panel(key, title, body, header, self)
        if min_width:
            p.setMinimumWidth(min_width)
        self.addDockWidget(area, p)
        for sig in (p.dockLocationChanged, p.topLevelChanged, p.visibilityChanged):
            sig.connect(lambda *_: self._saver.start())
            sig.connect(lambda *_: self._min_timer.start())
        self.panels.append(p)
        return p

    def finish(self, sizes=None, heights=None):
        """Call after all panels are added: sets default widths / heights,
        remembers the default arrangement, then restores the user's saved one."""
        if sizes:
            self.resizeDocks([p for p, _ in sizes], [w for _, w in sizes], Qt.Horizontal)
        if heights:
            self.resizeDocks([p for p, _ in heights], [h for _, h in heights], Qt.Vertical)
        self._default_state = self.saveState()
        saved = (self._config.get("panel_layout") or {}).get(self._key)
        # A layout saved with a different set of panels (older version) would
        # scatter the new ones — start from the default arrangement instead.
        if isinstance(saved, dict) and saved.get("panels") == self._keys():
            try:
                self.restoreState(QByteArray(base64.b64decode(saved["state"])))
            except Exception:
                pass

    def _keys(self):
        return [p.key for p in self.panels]

    def reset_layout(self):
        if self._default_state is not None:
            for p in self.panels:
                p.setFloating(False)
                p.show()
            self.restoreState(self._default_state)
            self._save_state()

    def _save_state(self):
        data = {"panels": self._keys(),
                "state": base64.b64encode(bytes(self.saveState())).decode("ascii")}
        layouts = self._config.setdefault("panel_layout", {})
        if layouts.get(self._key) != data:
            layouts[self._key] = data
            try:
                self._save_config()
            except Exception:
                pass
