"""Photoshop-style panels for the experiment screen.

PanelHost is an embedded QMainWindow: the preview (video / Output / Export)
is its fixed centre, and Queue / Configuration / Measurements / Speed /
Center-periphery / Missed frames / Frame corrections are dock
panels the user can drag to any side, stack as tabs, pop out as floating
windows, or close. View → Panels (main window) lists them for re-opening.
The arrangement is saved per experiment in config["panel_layout"].
"""
import base64

from PyQt5.QtCore import QByteArray, QEvent, QSize, Qt, QTimer
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

    def set_compact(self, on):
        """Narrow mode: icon-only header buttons, no pop-out button."""
        self.header.set_compact(on)
        self.b_float.setVisible(not on)
        self.header.layout().invalidate()
        self.header.updateGeometry()
        # Qt raises the dock's own minimum width to its title bar's; put back
        # the configured value so the narrower header can take effect.
        self.setMinimumWidth(getattr(self, "cfg_min_w", 0))
        # QDockWidget caches its title-bar size; flipping a feature flag
        # forces it to re-measure.

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
        self._narrow = False       # narrow mode (see _set_narrow)
        self._full_need = None     # layout minimum measured before narrowing
        self.narrow_hooks = []     # callables(bool) for widgets outside the docks
        self._fell_back = False   # True → showing the default layout, don't overwrite the saved one
        self._folded_state = None  # arrangement before panels were folded into tabs
        self._fold_stage = 0       # 0 none · 1 right side tabbed · 2 left side too
        self._fold_need = None     # layout minimum measured before folding

    # Qt squeezes docks on top of each other when the window is smaller
    # than their combined minimum — so the window may not get that small, and
    # when even the whole screen is too small the panels fold into tabs.
    FRAME_MARGIN = 40   # window title bar / borders, not part of availableGeometry

    def _update_window_minimum(self):
        win = self.window()
        if win is self or not self.isVisible():
            return
        base = self._base_minimum(win)
        need = self.minimumSizeHint()
        extra_w = max(0, win.width() - self.width())    # header, footer, margins
        extra_h = max(0, win.height() - self.height())
        screen = win.screen().availableGeometry() if win.screen() else None
        if screen is not None:
            avail_w = screen.width() - extra_w
            avail_h = screen.height() - extra_h - self.FRAME_MARGIN
            # A saved arrangement that cannot fit this screen (made on a bigger
            # monitor / scale) would make Qt stack the panels on top of each
            # other — fall back to the default arrangement, once, unsaved.
            if ((need.width() > avail_w or need.height() > avail_h)
                    and not self._fell_back and self._default_state is not None):
                self._fell_back = True
                for p in self.panels:
                    p.setFloating(False)
                    p.show()
                self.restoreState(self._default_state)
                self._min_timer.start()
                return
            # Still too big → narrow mode: shrink chrome (icon-only buttons,
            # fewer read-outs) so every panel stays visible on one screen.
            if (need.width() > avail_w or need.height() > avail_h) and not self._narrow:
                self._full_need = QSize(need)
                self._set_narrow(True)
                QTimer.singleShot(0, self._remeasure_docks)
                return
            # Even narrow mode does not fit this screen → stack the panels of
            # each column as tabs (Qt would otherwise draw them on top of
            # each other). Not saved; undone when there is room again.
            if (need.width() > avail_w or need.height() > avail_h) and self._narrow \
                    and self._fold_stage < 2:
                if self._folded_state is None:
                    self._fold_need = QSize(need)
                self._fold_panels()
                self._min_timer.start()
                return
            if self._folded_state is not None and self._fold_need is not None \
                    and self._fold_need.width() <= avail_w and self._fold_need.height() <= avail_h:
                self._unfold_panels()
                self._min_timer.start()
                return
            if self._narrow and self._folded_state is None and self._full_need is not None \
                    and self._full_need.width() <= avail_w and self._full_need.height() <= avail_h:
                self._set_narrow(False)
                QTimer.singleShot(0, self._remeasure_docks)
                return
        w, h = need.width() + extra_w, need.height() + extra_h
        if screen is not None:
            w, h = min(w, screen.width()), min(h, screen.height() - self.FRAME_MARGIN)
        win.setMinimumSize(max(w, base.width()), max(h, base.height()))

    FOLD_WIDTH = {int(Qt.LeftDockWidgetArea): 300, int(Qt.RightDockWidgetArea): 250}

    def _fold_panels(self):
        """Tab together the docked panels that share a side. Stage 1 folds
        the right / top / bottom sides; stage 2 (only if that is still too
        big for the screen) the left side as well."""
        if self._folded_state is None:
            self._folded_state = self.saveState()
        self._fold_stage += 1
        left = int(Qt.LeftDockWidgetArea)
        by_area = {}
        for p in self.panels:
            if not p.isFloating() and not p.isHidden():
                by_area.setdefault(int(self.dockWidgetArea(p)), []).append(p)
        for area, group in by_area.items():
            if area == left and self._fold_stage < 2:
                continue
            if len(group) < 2:
                continue
            for other in group[1:]:
                self.tabifyDockWidget(group[0], other)
            group[0].raise_()
            w = self.FOLD_WIDTH.get(area)
            if w:
                self.resizeDocks([group[0]], [w], Qt.Horizontal)

    def _unfold_panels(self):
        state, self._folded_state = self._folded_state, None
        self._fold_stage = 0
        if state is not None:
            self.restoreState(state)

    def event(self, e):
        # A panel's or the preview's content changed size (video loaded,
        # buttons appeared, a step expanded …) → re-check the window minimum,
        # so a non-maximised window never ends up smaller than its panels.
        if e.type() == QEvent.LayoutRequest:
            self._min_timer.start()
        return super().event(e)

    def _set_narrow(self, on):
        self._narrow = bool(on)
        for p in self.panels:
            p.set_compact(self._narrow)
        for fn in self.narrow_hooks:
            try:
                fn(self._narrow)
            except Exception:
                pass

    def _remeasure_docks(self):
        """After the headers have re-laid-out, make each dock re-read its
        title-bar size (Qt caches it) and the host its dock minimums."""
        for p in self.panels:
            p.setTitleBarWidget(None)
            p.setTitleBarWidget(p.header)
            p.header.show()
        self.restoreState(self.saveState())
        self._min_timer.start()

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

    def add_panel(self, key, title, body, header, area, min_width=None, min_height=None):
        p = Panel(key, title, body, header, self)
        p.cfg_min_w = min_width or 0
        if min_width:
            p.setMinimumWidth(min_width)
        # An explicit minimum on the holder replaces the content's own (larger)
        # minimumSizeHint, so the panels can be squeezed onto small / scaled
        # screens instead of stacking on top of each other.
        if min_width or min_height:
            p.holder.setMinimumSize(min_width or 0, min_height or 0)
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

    def refresh_layout(self):
        """Force Qt to fully redo the dock geometry, preserving the current
        arrangement — the same effect as the user closing and reopening a
        panel (the known workaround for QMainWindowLayout sometimes leaving
        stale / overlapping dock geometry after the central widget's content
        changes size, e.g. right after a video loads and the Configuration
        panel's rows go from placeholder to real values). Call this after
        any such bulk content change."""
        self.restoreState(self.saveState())
        self._min_timer.start()

    def reset_layout(self):
        self._fell_back = False
        self._folded_state = None
        self._fold_stage = 0
        if self._default_state is not None:
            for p in self.panels:
                p.setFloating(False)
                p.show()
            self.restoreState(self._default_state)
            self._save_state()

    def _save_state(self):
        if self._fell_back or self._folded_state is not None:
            return
        data = {"panels": self._keys(),
                "state": base64.b64encode(bytes(self.saveState())).decode("ascii")}
        layouts = self._config.setdefault("panel_layout", {})
        if layouts.get(self._key) != data:
            layouts[self._key] = data
            try:
                self._save_config()
            except Exception:
                pass
