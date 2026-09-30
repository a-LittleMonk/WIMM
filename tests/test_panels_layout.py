"""PanelHost must keep every panel on screen: when the docks cannot fit the
screen it switches to "narrow mode" (icon-only header buttons) instead of
letting Qt stack the panels on top of each other, and switches back when
there is room again. Runs headless (offscreen Qt)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt5")
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow, QWidget

from gui import theme
from gui.panels import PanelHost
from gui.widgets_v2 import IconTextButton, PaneHeader


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    theme.apply_theme(a, "dark")
    return a


def _host(n_panels, min_w):
    win = QMainWindow()
    host = PanelHost(QLabel("centre"), {}, "T", lambda: None)
    win.setCentralWidget(host)
    buttons = []
    for i in range(n_panels):
        hdr = PaneHeader("queue", f"Panel {i}")
        b = hdr.add_right(IconTextButton("plus", "Add something", 11, height=26))
        buttons.append(b)
        host.add_panel(f"p{i}", f"Panel {i}", QWidget(), hdr, Qt.LeftDockWidgetArea, min_w, 60)
    host.finish()
    return win, host, buttons


def _avail(win):
    return win.screen().availableGeometry()


def test_narrow_mode_when_docks_do_not_fit(app):
    screen_w = QApplication.primaryScreen().availableGeometry().width()
    # Enough panels that their combined minimum width exceeds the screen.
    win, host, buttons = _host(n_panels=8, min_w=screen_w // 4)
    win.show()
    host._update_window_minimum()
    app.processEvents()
    host._update_window_minimum()
    assert host._narrow
    assert all(b.text() == "" and b.toolTip() == "Add something" for b in buttons)
    assert all(not p.b_float.isVisibleTo(p) for p in host.panels)
    win.close()


def test_normal_mode_when_docks_fit(app):
    win, host, buttons = _host(n_panels=2, min_w=100)
    win.show()
    host._update_window_minimum()
    app.processEvents()
    assert not host._narrow
    assert all(b.text() == "Add something" for b in buttons)
    win.close()


def test_narrow_mode_reverts_when_there_is_room(app):
    win, host, buttons = _host(n_panels=2, min_w=100)
    win.show()
    host._full_need = host.minimumSizeHint()      # pretend we narrowed earlier
    host._set_narrow(True)
    host._update_window_minimum()
    app.processEvents()
    assert not host._narrow
    assert all(b.text() == "Add something" for b in buttons)
    win.close()


def test_default_layout_used_when_saved_one_cannot_fit(app):
    win, host, _ = _host(n_panels=8, min_w=QApplication.primaryScreen().availableGeometry().width() // 4)
    win.show()
    host._update_window_minimum()
    assert host._fell_back           # falls back to the default arrangement once
    saved = {}
    host._config = saved
    host._save_config = lambda: saved.setdefault("called", True)
    host._save_state()
    assert "called" not in saved     # ...and never overwrites the user's saved layout
    win.close()
