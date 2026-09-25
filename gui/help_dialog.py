"""Help window (header → Help, F1): one tab per experiment, each listing
its configuration cards in order with every parameter's explanation.

The text is whatever the step builders register through
`gui.info_box.attach_info_box`. To gather it for an experiment we build
that experiment's tab once, off-screen, inside `collect_help()`, then keep
the text and throw the tab away — so Help always matches the real UI.
"""
from html import escape

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication, QDialog, QLabel, QScrollArea, QTabWidget, QVBoxLayout,
)

from core import logger
from gui import theme

# (tab title, module, class) — order of the tabs in the window.
EXPERIMENTS = (
    ("Open Field",    "gui.open_field_tab", "OpenFieldTab"),
    ("Y-Maze",        "gui.y_maze_tab",     "YMazeTab"),
    ("Novel Object",  "gui.nor_tab",        "NORTab"),
    ("Elevated Plus", "gui.epm_tab",        "EPMTab"),
)

_cache = {}   # title -> list of (card_name, [(title, text), ...])


def _gather(title, module, cls_name, config):
    if title in _cache:
        return _cache[title]
    import importlib
    from gui.info_box import collect_help
    cfg = dict(config or {})
    for k in ("last_video", "recent_videos"):
        cfg.pop(k, None)
    cards = []
    try:
        cls = getattr(importlib.import_module(module), cls_name)
        with collect_help() as c:
            tab = cls(cfg)
        # Merge repeated cards, keep first-seen order.
        order, merged = [], {}
        for name, items in c.items:
            if name not in merged:
                order.append(name)
                merged[name] = []
            merged[name].extend(items)
        # Same order as the cards appear on screen.
        ui = [getattr(g, "_help_name", None) for g in getattr(tab, "_cards", [])]
        order.sort(key=lambda nm: ui.index(nm) if nm in ui else len(ui))
        cards = [(n, merged[n]) for n in order]
        tab.hide()
        QTimer.singleShot(3000, tab.deleteLater)   # after its own deferred init
    except Exception as e:
        logger.warn(f"help: could not gather {title}: {e}", source="ui")
    _cache[title] = cards
    return cards


def _page_html(title, cards):
    if not cards:
        return f"<p>No help text available for {escape(title)}.</p>"
    parts = [
        f"<p style='color:{theme.TEXT_2}; margin:0 0 10px 0;'>Settings in each "
        f"configuration card, in the order they appear: "
        f"{escape(' → '.join(n for n, _ in cards))}.</p>"
    ]
    for name, items in cards:
        parts.append(f"<h3 style='margin:14px 0 6px 0;'>{escape(name)}</h3>")
        for t, text in items:
            body = escape(text).replace("\n", "<br>")
            parts.append(f"<p style='margin:0 0 8px 0;'><b>{escape(t)}</b><br>{body}</p>")
    return "".join(parts)


class HelpDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help")
        self.resize(720, 640)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for title, module, cls_name in EXPERIMENTS:
                cards = _gather(title, module, cls_name, config)
                lbl = QLabel(_page_html(title, cards))
                lbl.setTextFormat(Qt.RichText)
                lbl.setWordWrap(True)
                lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
                lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
                lbl.setContentsMargins(6, 6, 6, 6)
                sc = QScrollArea()
                sc.setWidgetResizable(True)
                sc.setWidget(lbl)
                self.tabs.addTab(sc, title)
        finally:
            QApplication.restoreOverrideCursor()

    def show_tab(self, title):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == title:
                self.tabs.setCurrentIndex(i)
                break
        self.show()
        self.raise_()
        self.activateWindow()
