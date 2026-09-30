import os
import json
from html import escape
from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QAction, QFileDialog, QStatusBar, QMessageBox,
    QPushButton, QShortcut, QStackedWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QApplication, QAbstractSpinBox, QSlider, QComboBox,
    QDialog, QGroupBox, QFormLayout, QLineEdit, QCheckBox, QMenu, QMenuBar,
    QToolButton,
)
from tracking.tracker import DEFAULT_MODEL_PARAMS
from PyQt5.QtCore import Qt, QObject, QEvent, QTimer
from PyQt5.QtGui import QKeySequence
from gui.openfield_batch_tab import OpenFieldBatchTab
from gui.y_maze_tab import YMazeBatchTab
from gui.nor_tab import NORBatchTab
from gui.epm_tab import EPMBatchTab
from gui.realtime_scoring_tab import RealtimeScoringTab
from gui.log_dialog import LogDialog
from core import logger
from gui import theme
from gui.backdrop import AuroraBackdrop
from gui.launcher import LOGO_OUTLINE, BrandColumn, TestGrid, tinted_svg_pixmap
from gui.redesign_widgets import SegmentedControl, StatusPill, ThemeToggle


class _NoScrollFilter(QObject):
    """Always block mouse-wheel value changes on spinboxes / sliders.
    Use ↑/↓ keys or click+drag instead. Drop-downs (QComboBox) are NOT
    blocked: the wheel steps through the choices of a closed drop-down and
    scrolls an open drop-down's list (the popup list is a child of the
    combo, so blocking combos also froze long lists like the font list)."""
    _BLOCK_TYPES = (QAbstractSpinBox, QSlider)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            w = obj
            for _ in range(4):
                if w is None:
                    break
                if isinstance(w, self._BLOCK_TYPES):
                    event.ignore()
                    return True
                w = w.parent() if hasattr(w, "parent") else None
        return super().eventFilter(obj, event)


class _StayOpenMenuFilter(QObject):
    """Toggling a checkable entry (e.g. a panel in View ▸ Panels) keeps the
    menu open, so several panels can be shown / hidden in one go."""

    def eventFilter(self, menu, event):
        if (event.type() == QEvent.MouseButtonRelease
                and event.button() == Qt.LeftButton and isinstance(menu, QMenu)):
            act = menu.actionAt(event.pos())
            if act is not None and act.isCheckable() and act.isEnabled():
                act.trigger()
                return True
        return False


CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".mice_tracker.json")


def load_config():
    """Read ~/.mice_tracker.json (empty dict when missing / unreadable)."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


class FooterBar(QWidget):
    """26 px footer: Output ‹path› · Backup ‹path› ⟶ model · detection · mode."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FooterBar")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(16)
        self.ic = QLabel()
        self.lbl_out = QLabel()
        self.dot_bk = QLabel()
        self.dot_bk.setFixedSize(6, 6)
        self.lbl_bk = QLabel()
        left1 = QHBoxLayout()
        left1.setSpacing(6)
        left1.addWidget(self.ic)
        left1.addWidget(self.lbl_out)
        left2 = QHBoxLayout()
        left2.setSpacing(6)
        left2.addWidget(self.dot_bk)
        left2.addWidget(self.lbl_bk)
        h.addLayout(left1)
        h.addLayout(left2)
        h.addStretch(1)
        self.lbl_model = QLabel()
        self.dot_det = QLabel()
        self.dot_det.setFixedSize(6, 6)
        self.lbl_det = QLabel()
        self.lbl_mode = QLabel()
        right2 = QHBoxLayout()
        right2.setSpacing(6)
        right2.addWidget(self.dot_det)
        right2.addWidget(self.lbl_det)
        for w in (self.lbl_out, self.lbl_bk, self.lbl_model, self.lbl_det, self.lbl_mode):
            w.setTextFormat(Qt.RichText)
        h.addWidget(self.lbl_model)
        h.addLayout(right2)
        h.addWidget(self.lbl_mode)

    @staticmethod
    def _mono(text, color):
        return (f"<span style=\"font-family:'{theme.mono_family()}'; color:{color}\">"
                f"{escape(text)}</span>")

    def set_paths(self, output, backup):
        from gui import icons
        self.ic.setPixmap(icons.pixmap("folder", 12, theme.TEXT_2))
        self.lbl_out.setText(f"Output&nbsp;&nbsp;{self._mono(output, theme.TEXT)}")
        self.dot_bk.setStyleSheet(
            f"background:{theme.WARN if not backup else theme.OK}; border-radius:3px;")
        self.lbl_bk.setText(f"Backup&nbsp;&nbsp;{self._mono(backup or 'Not set', theme.TEXT if backup else theme.FAINT)}")

    def set_run(self, model, det_pct, mode_text):
        vis = model is not None
        self.lbl_model.setVisible(vis)
        self.dot_det.setVisible(vis and det_pct is not None)
        self.lbl_det.setVisible(vis and det_pct is not None)
        if vis:
            self.lbl_model.setText(self._mono(model, theme.TEXT_2))
        if det_pct is not None:
            col = theme.OK if det_pct >= 90 else theme.WARN
            self.dot_det.setStyleSheet(f"background:{col}; border-radius:3px;")
            self.lbl_det.setText(self._mono(f"detection {det_pct:.1f} %", theme.TEXT_2))
        self.lbl_mode.setText(mode_text)
        self.lbl_mode.setVisible(bool(mode_text))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = self._load_config()
        self._check_output_folder()
        self._no_scroll_filter = _NoScrollFilter()
        QApplication.instance().installEventFilter(self._no_scroll_filter)
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle("Mice Tracker")
        self.setMinimumSize(900, 560)

        # The View / Settings menus live inside the app header (redesign v2),
        # so they use their own QMenuBar instead of the window's native one.
        self._menubar = QMenuBar()
        self._menubar.setObjectName("HeaderMenu")
        self._menubar.setNativeMenuBar(False)
        # Home — Ctrl+H, also reachable by clicking the brand in the header.
        act_home = QAction("Home", self)
        act_home.setShortcut(QKeySequence("Ctrl+H"))
        act_home.triggered.connect(self._show_launcher)
        self.addAction(act_home)
        # View menu — log viewer + future view-related actions.
        self.view_menu = self._menubar.addMenu("View")
        # Settings menu — rebuilt per experiment; last on the toolbar.
        self.settings_menu = self._menubar.addMenu("Settings")
        act_logs = QAction("Logs…", self)
        act_logs.setShortcut(QKeySequence("Ctrl+L"))
        act_logs.triggered.connect(self._open_log_dialog)
        self.view_menu.addAction(act_logs)
        act_corrections = QAction("Tracking corrections…", self)
        act_corrections.setShortcut(QKeySequence("Ctrl+K"))
        act_corrections.setToolTip(
            "Open the manual-corrections popup for the active experiment tab"
        )
        act_corrections.triggered.connect(self._open_corrections_for_active_tab)
        self.view_menu.addAction(act_corrections)
        act_customize = QAction("Customize graphs…", self)
        act_customize.setShortcut(QKeySequence("Ctrl+G"))
        act_customize.setToolTip(
            "Edit per-graph colors, widths, labels, colormap, grid, and presets"
        )
        act_customize.triggered.connect(self._open_graph_style_for_active_tab)
        self.view_menu.addAction(act_customize)
        self.view_menu.addSeparator()
        # Panels ▸ — show / hide the current test's movable panels.
        self.panels_menu = self.view_menu.addMenu("Panels")
        self.panels_menu.aboutToShow.connect(self._fill_panels_menu)
        self._stay_open_filter = _StayOpenMenuFilter(self)
        self.panels_menu.installEventFilter(self._stay_open_filter)
        act_appearance = QAction("Appearance…", self)
        act_appearance.setToolTip("Background palette for light and dark mode")
        act_appearance.triggered.connect(self._open_appearance)
        self.view_menu.addAction(act_appearance)
        self.act_simple_mode = QAction("Simple mode", self, checkable=True)
        self.act_simple_mode.setChecked(bool(self.config.get("simple_mode", True)))
        self.act_simple_mode.toggled.connect(self._on_simple_mode_toggled)
        self._log_dialog = None
        logger.info("Application started", source="app")

        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()  # no tab switching — only one experiment at a time
        self.of_tab = OpenFieldBatchTab(self.config)
        self.tabs.addTab(self.of_tab, "Open Field")
        # Y-Maze uses the same plugin pattern as OF; built lazily on first open
        # (heavy embedded tab construction).
        self.ym_tab = None
        # NOR (Novel Object Recognition) — same lazy-construction pattern.
        self.nor_tab = None
        # EPM (Elevated Plus Maze) — lazy too.
        self.epm_tab = None
        self.scoring_tab = RealtimeScoringTab(self.config)
        self.tabs.addTab(self.scoring_tab, "Real-time Scoring")

        corner = QWidget()
        corner_lay = QHBoxLayout(corner)
        corner_lay.setContentsMargins(0, 0, 0, 0)
        corner_lay.setSpacing(4)
        home_btn = QPushButton("Home")
        home_btn.setFixedHeight(26)
        home_btn.setToolTip("Return to launcher (Ctrl+H)")
        home_btn.clicked.connect(self._show_launcher)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedHeight(26)
        refresh_btn.setToolTip("Restart app — picks up code changes (F5)")
        refresh_btn.clicked.connect(self._refresh_app)
        corner_lay.addWidget(home_btn)
        corner_lay.addWidget(refresh_btn)
        self.tabs.setCornerWidget(corner, Qt.TopRightCorner)
        self.tabs.setDocumentMode(True)
        QShortcut(QKeySequence("F5"), self, activated=self._refresh_app)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_launcher())  # index 0
        self.stack.addWidget(self.tabs)               # index 1
        central = AuroraBackdrop()
        cv = QVBoxLayout(central)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self._build_header())
        cv.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.stack.currentChanged.connect(self._sync_header)
        self.tabs.currentChanged.connect(self._sync_header)
        self.stack.setCurrentIndex(0)
        self._build_launcher_menu()

        # Footer: output / backup on the left; model · detection · mode on the right.
        self.status_bar = QStatusBar()
        self.status_bar.setSizeGripEnabled(False)
        self.footer = FooterBar()
        self.status_bar.addWidget(self.footer, 1)
        self.setStatusBar(self.status_bar)
        self._refresh_status()
        self._footer_timer = QTimer(self)
        self._footer_timer.setInterval(600)
        self._footer_timer.timeout.connect(self._refresh_footer_run)
        self._footer_timer.start()
        theme.notifier.changed.connect(self._refresh_status)
        theme.notifier.changed.connect(self._refresh_brand)
        self._sync_header()

    # (menu name, launcher-card name, enabled, opener attribute)
    _TESTS = [
        ("Open Field",           "Open Field",                True,  "_open_open_field"),
        ("Real-time Scoring",    "Real-time\nManual Scoring", True,  "_open_scoring"),
        ("Y-Maze",               "Y-Maze",                    True,  "_open_y_maze"),
        ("Novel Object",         "Novel Object",              True,  "_open_nor"),
        ("Elevated Plus",        "Elevated Plus",             True,  "_open_epm"),
        ("Forced Swim",          "Forced Swim",               False, None),
        ("Three Chamber",        "Three Chamber",             False, None),
    ]

    def _build_header(self):
        """App header from the redesign: brand · test picker · View/Settings ·
        tracking pill · Simple/Full · light/dark · Logs."""
        self.header = QWidget()
        self.header.setObjectName("AppHeader")
        self.header.setAttribute(Qt.WA_StyledBackground, True)
        self.header.setFixedHeight(48)
        h = QHBoxLayout(self.header)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(10)

        # Brand — click to go Home.
        brand = QWidget()
        brand.setCursor(Qt.PointingHandCursor)
        brand.setToolTip("Home (Ctrl+H)")
        brand.mousePressEvent = lambda _e: self._show_launcher()
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(9)
        self.brand_mark = QLabel()
        self.brand_mark.setObjectName("BrandMark")
        self.brand_mark.setFixedSize(26, 26)
        self.brand_mark.setAlignment(Qt.AlignCenter)
        bl.addWidget(self.brand_mark)
        names = QVBoxLayout()
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(1)
        name = QLabel("Mice Tracker")
        name.setObjectName("BrandName")
        tag = QLabel("BEHAVIOR LAB")
        tag.setObjectName("BrandTag")
        names.addWidget(name)
        names.addWidget(tag)
        bl.addLayout(names)
        h.addWidget(brand)
        self._refresh_brand()

        sep = QFrame()
        sep.setObjectName("HeaderSep")
        sep.setFixedSize(1, 22)
        h.addWidget(sep)

        # Output-folder crumb (shown while a test is open).
        self.crumb_sep = QLabel("›")
        self.crumb_sep.setObjectName("CrumbSep")
        self.lbl_crumb = QLabel("")
        self.lbl_crumb.setObjectName("Crumb")
        h.addWidget(self.crumb_sep)
        h.addWidget(self.lbl_crumb)

        # A QMenuBar in a plain layout reports a tiny size hint and collapses
        # into the "»" overflow button — size it from its items.
        fm = self._menubar.fontMetrics()
        menus_w = sum(fm.horizontalAdvance(a.text()) + 24 for a in self._menubar.actions())
        # Height = the items' own height, so View / Settings sit centred in
        # the header instead of at the top of a taller, empty bar.
        self._menubar.setFixedSize(menus_w + 8, self._menubar.sizeHint().height())
        h.addWidget(self._menubar, 0, Qt.AlignVCenter)
        h.addStretch(1)

        self.pill = StatusPill()
        h.addWidget(self.pill)
        self.seg_mode = SegmentedControl(
            ["Simple", "Full"], 0 if self.act_simple_mode.isChecked() else 1)
        self.seg_mode.changed.connect(lambda i: self.act_simple_mode.setChecked(i == 0))
        self.act_simple_mode.toggled.connect(
            lambda on: self.seg_mode.set_index(0 if on else 1))
        h.addWidget(self.seg_mode)
        self.seg_theme = ThemeToggle(1 if theme.mode() == "dark" else 0)
        self.seg_theme.changed.connect(self._on_theme_toggled)
        h.addWidget(self.seg_theme)
        b_logs = QPushButton("Logs")
        b_logs.setFixedHeight(28)
        b_logs.clicked.connect(self._open_log_dialog)
        h.addWidget(b_logs)
        b_help = QPushButton("Help")
        b_help.setFixedHeight(28)
        b_help.setToolTip("Explanation of every setting, per experiment (F1)")
        b_help.clicked.connect(self._open_help)
        h.addWidget(b_help)
        QShortcut(QKeySequence("F1"), self, activated=self._open_help)
        return self.header

    def _open_help(self):
        """Help window, opened on the tab of the experiment being used."""
        from gui.help_dialog import HelpDialog
        current = self.tabs.currentWidget() if self.stack.currentIndex() == 1 else None
        title = {
            id(self.of_tab): "Open Field",
            id(self.ym_tab): "Y-Maze",
            id(self.nor_tab): "Novel Object",
            id(self.epm_tab): "Elevated Plus",
        }.get(id(current), "Open Field") if current is not None else "Open Field"
        if getattr(self, "_help_dialog", None) is None:
            self._help_dialog = HelpDialog(self.config, self)
        self._help_dialog.show_tab(title)

    def _refresh_brand(self, *_):
        self.brand_mark.setPixmap(tinted_svg_pixmap(LOGO_OUTLINE, 26, theme.TEXT))

    def _current_panel_host(self):
        if self.stack.currentIndex() != 1:
            return None
        return getattr(self.tabs.currentWidget(), "panel_host", None)

    def _fill_panels_menu(self):
        m = self.panels_menu
        m.clear()
        host = self._current_panel_host()
        if host is None:
            on_tool = self.stack.currentIndex() == 1
            a = m.addAction("This screen has no movable panels" if on_tool
                            else "Open a test to arrange its panels")
            a.setEnabled(False)
            return
        for p in host.panels:
            m.addAction(p.toggleViewAction())
        m.addSeparator()
        m.addAction("Reset panel layout", host.reset_layout)

    def _open_appearance(self):
        from gui.appearance_dialog import AppearanceDialog
        AppearanceDialog(self.config, self._save_config, self).exec_()

    def _on_theme_toggled(self, index):
        new_mode = "dark" if index == 1 else "light"
        self.config["theme"] = new_mode
        self._save_config()
        theme.apply_theme(QApplication.instance(), new_mode)

    def _sync_header(self, *_):
        on_tool = self.stack.currentIndex() == 1
        self.crumb_sep.setVisible(on_tool)
        self.lbl_crumb.setVisible(on_tool)
        if on_tool:
            self._refresh_crumb()

    def _refresh_crumb(self):
        folder = self.config.get("output_folder") or ""
        self.lbl_crumb.setText(os.path.basename(os.path.normpath(folder)) if folder else "no output folder")

    def _build_launcher(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        self.brand_column = BrandColumn()
        h.addWidget(self.brand_column, 0)

        tests = []
        for i, (_menu, card, enabled, opener) in enumerate(self._TESTS, start=1):
            cb = getattr(self, opener) if (enabled and opener) else None
            label = card if enabled else f"{card} (coming soon)"
            tests.append((f"{i:02d}", label, enabled, cb))
        self.test_grid = TestGrid(tests)
        h.addWidget(self.test_grid, 1)

        self.brand_column.set_narrow(self.width() < BrandColumn.NARROW_BREAKPOINT)
        return w

    def resizeEvent(self, event):
        super().resizeEvent(event)
        bc = getattr(self, "brand_column", None)
        if bc is not None:
            bc.set_narrow(self.width() < BrandColumn.NARROW_BREAKPOINT)

    def _open_open_field(self):
        self.tabs.setCurrentWidget(self.of_tab)
        self.stack.setCurrentIndex(1)
        self._build_open_field_menu()

    def _open_y_maze(self):
        if self.ym_tab is None:
            self.ym_tab = YMazeBatchTab(self.config)
            self.tabs.addTab(self.ym_tab, "Y-Maze")
        self.tabs.setCurrentWidget(self.ym_tab)
        self.stack.setCurrentIndex(1)
        self._build_y_maze_menu()

    def _open_nor(self):
        if self.nor_tab is None:
            self.nor_tab = NORBatchTab(self.config)
            self.tabs.addTab(self.nor_tab, "Novel Object")
        self.tabs.setCurrentWidget(self.nor_tab)
        self.stack.setCurrentIndex(1)
        self._build_nor_menu()

    def _open_epm(self):
        if self.epm_tab is None:
            self.epm_tab = EPMBatchTab(self.config)
            self.tabs.addTab(self.epm_tab, "Elevated Plus")
        self.tabs.setCurrentWidget(self.epm_tab)
        self.stack.setCurrentIndex(1)
        self._build_epm_menu()

    def _open_scoring(self):
        self.tabs.setCurrentWidget(self.scoring_tab)
        self.stack.setCurrentIndex(1)
        self._build_scoring_menu()

    def set_tracking_status(self, text):
        self.pill.show_text(text)

    def _show_launcher(self):
        self.stack.setCurrentIndex(0)
        self._build_launcher_menu()

    def _build_launcher_menu(self):
        self.settings_menu.clear()
        self.settings_menu.setEnabled(True)
        act_extra = QAction("Extra features…", self)
        act_extra.triggered.connect(self._open_extra_features_dialog)
        self.settings_menu.addAction(act_extra)

    def _add_nav_actions(self):
        act_refresh = QAction("Refresh app", self)
        act_refresh.setShortcut(QKeySequence("F5"))
        act_refresh.triggered.connect(self._refresh_app)
        self.settings_menu.addAction(act_refresh)

        self.settings_menu.addSeparator()

    def _build_open_field_menu(self):
        self.settings_menu.clear()
        self.settings_menu.setEnabled(True)
        self._add_nav_actions()

        act = QAction("Set Output Folder…", self)
        act.triggered.connect(self._pick_output_folder)
        self.settings_menu.addAction(act)

        act_bk = QAction("Set Backup Folder…", self)
        act_bk.setToolTip(
            "Where the autosave Excel goes after each tracking run.\n"
            "Leave unset to skip the autosave."
        )
        act_bk.triggered.connect(self._pick_backup_folder)
        self.settings_menu.addAction(act_bk)

    def _on_simple_mode_toggled(self, checked):
        self.config["simple_mode"] = bool(checked)
        for attr in ("of_tab", "ym_tab", "nor_tab", "epm_tab"):
            tab = getattr(self, attr, None)
            if tab is None:
                continue
            embedded = getattr(tab, "embedded_tab", None)
            if embedded is not None and hasattr(embedded, "set_simple_mode"):
                embedded.set_simple_mode(bool(checked))
            elif hasattr(tab, "set_simple_mode"):
                tab.set_simple_mode(bool(checked))
        self._save_config()

    def _build_y_maze_menu(self):
        self.settings_menu.clear()
        self.settings_menu.setEnabled(True)
        self._add_nav_actions()

        act = QAction("Set Output Folder…", self)
        act.triggered.connect(self._pick_output_folder)
        self.settings_menu.addAction(act)

        act_bk = QAction("Set Backup Folder…", self)
        act_bk.setToolTip(
            "Where the autosave Excel goes after each tracking run.\n"
            "Leave unset to skip the autosave."
        )
        act_bk.triggered.connect(self._pick_backup_folder)
        self.settings_menu.addAction(act_bk)

    def _build_nor_menu(self):
        self.settings_menu.clear()
        self.settings_menu.setEnabled(True)
        self._add_nav_actions()

        act = QAction("Set Output Folder…", self)
        act.triggered.connect(self._pick_output_folder)
        self.settings_menu.addAction(act)

        act_bk = QAction("Set Backup Folder…", self)
        act_bk.setToolTip(
            "Where the autosave Excel goes after each tracking run.\n"
            "Leave unset to skip the autosave."
        )
        act_bk.triggered.connect(self._pick_backup_folder)
        self.settings_menu.addAction(act_bk)

    def _build_epm_menu(self):
        self.settings_menu.clear()
        self.settings_menu.setEnabled(True)
        self._add_nav_actions()

        act = QAction("Set Output Folder…", self)
        act.triggered.connect(self._pick_output_folder)
        self.settings_menu.addAction(act)

        act_bk = QAction("Set Backup Folder…", self)
        act_bk.setToolTip(
            "Where the autosave Excel goes after each tracking run.\n"
            "Leave unset to skip the autosave."
        )
        act_bk.triggered.connect(self._pick_backup_folder)
        self.settings_menu.addAction(act_bk)

    def _open_extra_features_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Extra features")
        outer = QVBoxLayout(dlg)
        outer.setSpacing(10)
        outer.setContentsMargins(12, 12, 12, 12)

        # ── Body-parts overlay style ─────────────────────────────────────
        body_box = QGroupBox("Video overlay — body parts")
        body_lay = QVBoxLayout(body_box)
        body_lay.setSpacing(4)
        body_note = QLabel(
            "What to draw on the tracked mouse in the video preview. "
            "'Off' shows only the bare detection point (default)."
        )
        body_note.setWordWrap(True)
        body_note.setProperty("role", "muted")
        body_lay.addWidget(body_note)

        body_row = QHBoxLayout()
        body_row.addWidget(QLabel("Style:"))
        cmb_body = QComboBox()
        # Same values as the View popover's "Body marker → Show" combo.
        cmb_body.addItem("Off",                  "off")
        cmb_body.addItem("Center",               "dot")
        cmb_body.addItem("Center + nose + tail", "ends")
        cmb_body.setFixedHeight(24)
        current = self.config.get("body_style", "dot")
        # Older configs stored this launcher's previous values.
        current = {"dots": "dot", "skeleton": "ends",
                   "dots+skeleton": "ends"}.get(current, current)
        idx = cmb_body.findData(current)
        if idx >= 0:
            cmb_body.setCurrentIndex(idx)
        cmb_body.currentIndexChanged.connect(
            lambda: self._apply_body_style(cmb_body.currentData())
        )
        body_row.addWidget(cmb_body, 1)
        body_lay.addLayout(body_row)
        outer.addWidget(body_box)

        # ── Experimental / parked features ───────────────────────────────
        exp_box = QGroupBox("Experimental features")
        e_lay = QVBoxLayout(exp_box)
        e_lay.setSpacing(4)
        e_note = QLabel(
            "Features that are off by default. Enable here to bring them "
            "back into the per-experiment UI."
        )
        e_note.setWordWrap(True)
        e_note.setProperty("role", "muted")
        e_lay.addWidget(e_note)
        chk_auto_mv = QCheckBox("Enable 'Auto arena from movement'")
        chk_auto_mv.setToolTip(
            "Adds the 'Auto — from movement (next run)' option to the "
            "Define arena dropdown. The arena polygon is built from the "
            "convex hull of the mouse's path after tracking."
        )
        chk_auto_mv.setChecked(
            bool(self.config.get("enable_auto_movement_arena", False))
        )

        def _toggle_auto_movement(on):
            self.config["enable_auto_movement_arena"] = bool(on)
            self._save_config()
        chk_auto_mv.toggled.connect(_toggle_auto_movement)
        e_lay.addWidget(chk_auto_mv)
        outer.addWidget(exp_box)

        # ── Tracking models (preview, parked) ────────────────────────────
        models_box = QGroupBox("Tracking models (preview)")
        m_lay = QVBoxLayout(models_box)
        m_lay.setSpacing(4)
        m_note = QLabel(
            "Alternative tracking models with their default tunings. "
            "Pick one in the Tracking step's Model drop-down."
        )
        m_note.setWordWrap(True)
        m_note.setProperty("role", "muted")
        m_lay.addWidget(m_note)
        btn_models = QPushButton("Open models preview…")
        btn_models.setFixedHeight(24)
        btn_models.clicked.connect(self._open_tracking_models_dialog)
        m_lay.addWidget(btn_models)
        outer.addWidget(models_box)

        outer.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(24)
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(dlg.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)

        dlg.resize(420, 280)
        dlg.exec_()

    def _apply_body_style(self, style):
        """Persist body-style choice + propagate to any open experiment tabs."""
        self.config["body_style"] = str(style)
        self._save_config()
        # Push into any already-loaded experiment tabs so the change is live.
        for attr in ("of_tab", "ym_tab", "nor_tab", "epm_tab"):
            tab = getattr(self, attr, None)
            if tab is None:
                continue
            target = getattr(tab, "embedded_tab", None) or tab
            cmb = getattr(target, "combo_body_style", None)
            if cmb is None:
                continue
            i = cmb.findData(style)
            if i >= 0 and i != cmb.currentIndex():
                cmb.setCurrentIndex(i)

    def _open_tracking_models_dialog(self):
        pretty = {
            "mog2": "MOG2 (Adaptive)", "knn": "KNN", "cnt": "CNT (Fast)",
            "gsoc": "GSOC", "lsbp": "LSBP",
            "framediff": "Frame Diff", "hsv": "HSV Threshold",
        }
        dlg = QDialog(self)
        dlg.setWindowTitle("Tracking models (preview)")
        outer = QVBoxLayout(dlg)
        outer.setSpacing(8)
        outer.setContentsMargins(12, 12, 12, 12)

        note = QLabel(
            "Pick a model to see its default parameters. To use one, choose "
            "it in the Tracking step's Model drop-down."
        )
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        outer.addWidget(note)

        pick_row = QHBoxLayout()
        pick_row.addWidget(QLabel("Model:"))
        combo = QComboBox()
        combo.setFixedHeight(24)
        for key, label in pretty.items():
            combo.addItem(label, key)
        pick_row.addWidget(combo, 1)
        outer.addLayout(pick_row)

        # Param panel — rebuilt when combo changes.
        param_host = QGroupBox()
        param_host.setEnabled(False)
        param_host.setStyleSheet("QGroupBox { font-size:11px; }")
        param_layout = QFormLayout(param_host)
        param_layout.setSpacing(4)
        param_layout.setContentsMargins(8, 8, 8, 8)
        outer.addWidget(param_host, 1)

        def _show(idx):
            # Clear previous rows.
            while param_layout.rowCount():
                param_layout.removeRow(0)
            key = combo.itemData(idx)
            params = DEFAULT_MODEL_PARAMS.get(key, {})
            if not params:
                param_layout.addRow(QLabel("(no tunable parameters)"))
                return
            for k, v in params.items():
                le = QLineEdit(str(v))
                le.setReadOnly(True)
                le.setFixedHeight(22)
                k_lbl = QLabel(k)
                k_lbl.setStyleSheet("font-size:11px;")
                param_layout.addRow(k_lbl, le)

        combo.currentIndexChanged.connect(_show)
        _show(0)

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(24)
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(dlg.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)

        dlg.resize(380, 320)
        dlg.exec_()

    def _build_scoring_menu(self):
        self.settings_menu.clear()
        self.settings_menu.setEnabled(True)
        self._add_nav_actions()

        act_dir = QAction("Set Scoring Output Folder…", self)
        act_dir.triggered.connect(self.scoring_tab._change_output_dir)
        self.settings_menu.addAction(act_dir)

        act_clear = QAction("Clear all scoring presets…", self)
        act_clear.triggered.connect(self._clear_scoring_presets)
        self.settings_menu.addAction(act_clear)

    def _clear_scoring_presets(self):
        if QMessageBox.question(
            self, "Clear presets",
            "Delete all saved scoring presets?",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return
        self.config["scoring_presets"] = {}
        self._save_config()
        if hasattr(self.scoring_tab, "_populate_preset_combo"):
            self.scoring_tab._populate_preset_combo()

    def _check_output_folder(self):
        if not self.config.get("output_folder"):
            QMessageBox.information(
                None, "Welcome",
                "Please choose a folder where results (Excel files, plots) will be saved."
            )
            folder = QFileDialog.getExistingDirectory(None, "Choose Output Folder")
            if folder:
                self.config["output_folder"] = folder
                self._save_config()

    def _pick_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.config["output_folder"] = folder
            self._save_config()
            self._refresh_status()
            if hasattr(self.of_tab, "_refresh_output_label"):
                self.of_tab._refresh_output_label()
            elif hasattr(self.of_tab, "update_config"):
                self.of_tab.update_config(self.config)

    def _pick_backup_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Backup Folder")
        if folder:
            self.config["backup_folder"] = folder
            self._save_config()
            self._refresh_status()
            for attr in ("of_tab", "ym_tab", "nor_tab", "epm_tab"):
                tab = getattr(self, attr, None)
                if tab is not None and hasattr(tab, "_refresh_output_label"):
                    tab._refresh_output_label()

    def _open_corrections_for_active_tab(self):
        """Open the corrections popup on whichever experiment tab is active."""
        current = self.tabs.currentWidget()
        target = getattr(current, "embedded_tab", None) or current
        if hasattr(target, "_open_corrections_popup"):
            target._open_corrections_popup()
        else:
            QMessageBox.information(
                self, "Tracking corrections",
                "Manual corrections aren't available on this tab."
            )

    def _open_graph_style_for_active_tab(self):
        """Open Customize Graphs on whichever experiment tab is active."""
        current = self.tabs.currentWidget()
        target = getattr(current, "embedded_tab", None) or current
        if hasattr(target, "_open_graph_style_dialog"):
            target._open_graph_style_dialog()
        else:
            QMessageBox.information(
                self, "Customize graphs",
                "Graph styling isn't available on this tab."
            )

    def _open_log_dialog(self):
        if self._log_dialog is None or not self._log_dialog.isVisible():
            self._log_dialog = LogDialog(self)
            self._log_dialog.setModal(False)
            self._log_dialog.show()
        else:
            self._log_dialog.raise_()
            self._log_dialog.activateWindow()

    def _refresh_app(self):
        import sys, subprocess
        from PyQt5.QtWidgets import QApplication
        self._save_config()
        script = os.path.abspath(sys.argv[0])
        args = [sys.executable, script] + sys.argv[1:]
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(args, creationflags=creationflags, close_fds=True)
        QApplication.quit()

    def _refresh_status(self, *_):
        folder = self.config.get("output_folder") or "Not set — go to Settings to configure"
        self.footer.set_paths(folder, self.config.get("backup_folder") or "")
        if hasattr(self, "lbl_crumb"):
            self._refresh_crumb()
        self._refresh_footer_run()

    def _refresh_footer_run(self):
        """Right-hand footer: tracking model · detection rate · Simple/Full."""
        et = None
        if hasattr(self, "stack") and self.stack.currentIndex() == 1:
            et = getattr(self.tabs.currentWidget(), "embedded_tab", None)
        if et is None or not hasattr(et, "combo_model"):
            self.footer.set_run(None, None, "")
            return
        try:
            skip = et.spin_frame_skip.value()
            model = (f"{et.combo_model.currentText()} · {et.combo_proc_scale.currentText().split()[0]}"
                     f" · skip {'off' if skip <= 1 else str(skip) + '×'}")
            det = None
            res = et.tracking_results
            if res:
                det = 100.0 * sum(1 for r in res if r.get("x") is not None) / len(res)
            mode = "Simple mode" if self.config.get("simple_mode", True) else "Full mode"
        except Exception:
            self.footer.set_run(None, None, "")
            return
        self.footer.set_run(model, det, mode)

    def _load_config(self):
        return load_config()

    def _save_config(self):
        with open(CONFIG_PATH, "w") as f:
            json.dump(self.config, f, indent=2)
