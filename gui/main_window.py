import os
import json
from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QAction, QFileDialog, QStatusBar, QMessageBox,
    QPushButton, QShortcut, QStackedWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QGridLayout, QApplication, QAbstractSpinBox, QSlider, QComboBox,
    QDialog, QGroupBox, QFormLayout, QLineEdit, QCheckBox,
)
from tracking.tracker import DEFAULT_MODEL_PARAMS
from PyQt5.QtCore import Qt, QObject, QEvent
from PyQt5.QtGui import QKeySequence
from gui.openfield_batch_tab import OpenFieldBatchTab
from gui.y_maze_tab import YMazeBatchTab
from gui.nor_tab import NORBatchTab
from gui.epm_tab import EPMBatchTab
from gui.realtime_scoring_tab import RealtimeScoringTab
from gui.log_dialog import LogDialog
from core import logger


class _NoScrollFilter(QObject):
    """Always block mouse-wheel value changes on spinboxes / sliders / combos.
    Use ↑/↓ keys or click+drag instead."""
    _BLOCK_TYPES = (QAbstractSpinBox, QSlider, QComboBox)

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

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".mice_tracker.json")


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
        self.setMinimumSize(1000, 700)

        # Settings menu — rebuilt per experiment
        self.settings_menu = self.menuBar().addMenu("Settings")
        # View menu — log viewer + future view-related actions.
        self.view_menu = self.menuBar().addMenu("View")
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
        self.act_simple_mode = QAction("Simple mode", self, checkable=True)
        self.act_simple_mode.setChecked(bool(self.config.get("simple_mode", True)))
        self.act_simple_mode.toggled.connect(self._on_simple_mode_toggled)
        self.view_menu.addAction(self.act_simple_mode)
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
        home_btn = QPushButton("🏠 Home")
        home_btn.setFixedHeight(22)
        home_btn.setToolTip("Return to launcher")
        home_btn.clicked.connect(self._show_launcher)
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.setFixedHeight(22)
        refresh_btn.setToolTip("Restart app — picks up code changes (F5)")
        refresh_btn.clicked.connect(self._refresh_app)
        corner_lay.addWidget(home_btn)
        corner_lay.addWidget(refresh_btn)
        self.tabs.setCornerWidget(corner, Qt.TopRightCorner)
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #555; border-radius: 2px; }"
        )
        QShortcut(QKeySequence("F5"), self, activated=self._refresh_app)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_launcher())  # index 0
        self.stack.addWidget(self.tabs)               # index 1
        self.setCentralWidget(self.stack)
        self.stack.setCurrentIndex(0)
        self._build_launcher_menu()

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._refresh_status()

    def _build_launcher(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(40, 40, 40, 40)
        v.setSpacing(20)

        title = QLabel("Mice Tracker")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 28px; font-weight: bold;")
        subtitle = QLabel("Choose a behavioral test")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 13px; color: #888;")
        v.addWidget(title)
        v.addWidget(subtitle)
        v.addSpacing(20)

        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setAlignment(Qt.AlignCenter)

        tests = [
            ("Open Field",                  True,  self._open_open_field),
            ("Real-time\nManual Scoring",   True,  self._open_scoring),
            ("Y-Maze",                      True,  self._open_y_maze),
            ("Novel Object",                True,  self._open_nor),
            ("Elevated Plus",               True,  self._open_epm),
            ("Forced Swim",                 False, None),
            ("Three Chamber",               False, None),
        ]
        for i, (name, enabled, slot) in enumerate(tests):
            btn = QPushButton(name if enabled else f"{name}\n(coming soon)")
            btn.setFixedSize(180, 80)
            btn.setEnabled(enabled)
            btn.setStyleSheet(
                "QPushButton { font-size: 13px; font-weight: bold; }"
                "QPushButton:disabled { color: #666; }"
            )
            if slot:
                btn.clicked.connect(slot)
            grid.addWidget(btn, i // 3, i % 3)

        grid_wrap = QWidget()
        grid_wrap.setLayout(grid)
        v.addWidget(grid_wrap, 0, Qt.AlignCenter)
        v.addStretch()
        return w

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
        act_home = QAction("🏠 Home", self)
        act_home.setShortcut(QKeySequence("Ctrl+H"))
        act_home.triggered.connect(self._show_launcher)
        self.settings_menu.addAction(act_home)

        act_refresh = QAction("⟳ Refresh App", self)
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
        body_note.setStyleSheet("font-size:11px; color:#aaa;")
        body_lay.addWidget(body_note)

        body_row = QHBoxLayout()
        body_row.addWidget(QLabel("Style:"))
        cmb_body = QComboBox()
        cmb_body.addItem("Off (just detection point)", "off")
        cmb_body.addItem("Dots",                       "dots")
        cmb_body.addItem("Skeleton",                   "skeleton")
        cmb_body.addItem("Dots + Skeleton",            "dots+skeleton")
        cmb_body.setFixedHeight(24)
        current = self.config.get("body_style", "off")
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
        e_note.setStyleSheet("font-size:11px; color:#aaa;")
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
            "Disabled for now — for review only."
        )
        m_note.setWordWrap(True)
        m_note.setStyleSheet("font-size:11px; color:#aaa;")
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
            "Pick a model to see its default parameters. Disabled — for review."
        )
        note.setWordWrap(True)
        note.setStyleSheet("font-size:11px; color:#aaa;")
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
        param_host.setStyleSheet("QGroupBox { color:#ccc; font-size:11px; }")
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

    def _refresh_status(self):
        folder = self.config.get("output_folder", "Not set — go to Settings to configure")
        backup = self.config.get("backup_folder") or "Not set"
        self.status_bar.showMessage(f"Output: {folder}    |    Backup: {backup}")

    def _load_config(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_config(self):
        with open(CONFIG_PATH, "w") as f:
            json.dump(self.config, f, indent=2)
