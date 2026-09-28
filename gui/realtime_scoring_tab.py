import os
import time
import string as _string
from collections import Counter
from datetime import datetime
import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QRadioButton, QButtonGroup, QFileDialog, QMessageBox, QShortcut,
    QInputDialog, QSizePolicy, QFrame, QComboBox,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QKeySequence
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from openpyxl import Workbook


from gui import theme


class RealtimeScoringTab(QWidget):
    DEFAULT_VALUES = [0, 1, 2, 3, 4, 5, 6]

    def __init__(self, config):
        super().__init__()
        self.config = config
        # Restore last-used values list (persisted) or fall back to defaults
        last = config.get("scoring_last_values")
        if isinstance(last, list) and last:
            self.values = list(last)
        else:
            self.values = list(self.DEFAULT_VALUES)
        self.selected_value = None
        self._chart_points = []
        self._export_points = []
        self.test_title = ""
        self._t_start = None
        self._next_export_sec = None
        self._t_paused = None
        self._segment_emitted = False
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._tick)

        self._build_ui()
        self._populate_preset_combo()
        # Show the preset chosen last time (its values are already restored
        # from scoring_last_values).
        last = self.config.get("scoring_preset")
        if last and self.combo_preset.findText(last) >= 0:
            self.combo_preset.setCurrentIndex(self.combo_preset.findText(last))
        self._refresh_radio_buttons()
        self._render_chart()
        self._bind_shortcuts()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Title display
        self.lbl_title = QLabel("Real-time Manual Scoring")
        self.lbl_title.setAlignment(Qt.AlignCenter)
        self.lbl_title.setStyleSheet("font-size: 18px; font-weight: bold;")
        root.addWidget(self.lbl_title)

        # Values input row
        vals_row = QHBoxLayout()
        vals_row.addWidget(QLabel("Values:"))
        self.input_values = QLineEdit(",".join(str(v) for v in self.values))
        self.input_values.setToolTip(
            "Comma-separated values. Numbers, letters, or words.\n"
            "Examples: 0,1,2,3,4,5,6 — or — A,B,C,D — or — Low,Med,High"
        )
        self.input_values.returnPressed.connect(self._apply_values)
        vals_row.addWidget(self.input_values, 1)
        self.btn_apply_values = QPushButton("Apply")
        self.btn_apply_values.setFixedWidth(70)
        self.btn_apply_values.clicked.connect(self._apply_values)
        vals_row.addWidget(self.btn_apply_values)
        self.btn_reset_values = QPushButton("Defaults")
        self.btn_reset_values.setFixedWidth(80)
        self.btn_reset_values.clicked.connect(self._reset_values_to_default)
        vals_row.addWidget(self.btn_reset_values)
        root.addLayout(vals_row)

        # Preset row
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self.combo_preset = QComboBox()
        self.combo_preset.setMinimumWidth(140)
        preset_row.addWidget(self.combo_preset, 1)
        self.btn_preset_load = QPushButton("Load")
        self.btn_preset_load.setFixedWidth(60)
        self.btn_preset_load.clicked.connect(self._load_preset)
        preset_row.addWidget(self.btn_preset_load)
        self.btn_preset_save = QPushButton("Save")
        self.btn_preset_save.setFixedWidth(60)
        self.btn_preset_save.clicked.connect(self._save_preset)
        preset_row.addWidget(self.btn_preset_save)
        self.btn_preset_del = QPushButton("Del")
        self.btn_preset_del.setFixedWidth(50)
        self.btn_preset_del.clicked.connect(self._delete_preset)
        preset_row.addWidget(self.btn_preset_del)
        root.addLayout(preset_row)

        # Chart — build once, mutate in place; colours follow the theme
        from gui.out_widgets import OutPanel
        self.figure = Figure(figsize=(6, 3))
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._ax = self.figure.add_subplot(111)
        self._ax.set_xlabel("Time (s)")
        self._ax.set_ylabel("Score")
        (self._line,) = self._ax.plot([], [], linewidth=1.4, drawstyle="steps-post")
        self._current_hline = self._ax.axhline(
            y=0, linewidth=1.0, linestyle="--", alpha=0.6, visible=False
        )
        self._apply_chart_theme()
        theme.notifier.changed.connect(lambda _m: self._apply_chart_theme())
        chart_panel = OutPanel()
        chart_panel.body.addWidget(self.canvas)
        root.addWidget(chart_panel, 1)

        # Per-value duration summary
        self.lbl_duration = QLabel("")
        self.lbl_duration.setAlignment(Qt.AlignCenter)
        theme.set_tone(self.lbl_duration, "muted", "font-size:11px;")
        root.addWidget(self.lbl_duration)

        # Radio buttons (current value selector)
        self.radio_row = QHBoxLayout()
        self.radio_row.setAlignment(Qt.AlignCenter)
        self.radio_group = QButtonGroup(self)
        self.radio_group.buttonClicked.connect(self._on_radio)
        radio_widget = QFrame()
        radio_widget.setLayout(self.radio_row)
        root.addWidget(radio_widget)

        hint = QLabel("Press 0–9 or A–Z to pick value (digits also pick by position: 1=1st, 2=2nd…)")
        hint.setAlignment(Qt.AlignCenter)
        theme.set_tone(hint, "faint", "font-size:11px;")
        root.addWidget(hint)

        # Output folder row
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output:"))
        self.lbl_output_dir = QLabel()
        theme.set_tone(self.lbl_output_dir, "muted", "font-size:11px;")
        self.lbl_output_dir.setTextInteractionFlags(Qt.TextSelectableByMouse)
        out_row.addWidget(self.lbl_output_dir, 1)
        self.btn_change_dir = QPushButton("Change…")
        self.btn_change_dir.setFixedWidth(80)
        self.btn_change_dir.clicked.connect(self._change_output_dir)
        out_row.addWidget(self.btn_change_dir)
        self.btn_open_dir = QPushButton("Open")
        self.btn_open_dir.setFixedWidth(60)
        self.btn_open_dir.setToolTip("Open output folder in file explorer")
        self.btn_open_dir.clicked.connect(self._open_output_dir)
        out_row.addWidget(self.btn_open_dir)
        root.addLayout(out_row)
        self._refresh_output_label()

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignCenter)
        self.btn_new = QPushButton("New")
        self.btn_new.setProperty("primary", True)
        self.btn_stop_resume = QPushButton("Stop")
        self.btn_reset = QPushButton("Reset")
        self.btn_export = QPushButton("Export")
        for b in (self.btn_new, self.btn_stop_resume, self.btn_reset, self.btn_export):
            b.setFixedHeight(34)
            b.setFixedWidth(110)
            b.setStyleSheet("font-weight: bold; font-size: 13px;")
            btn_row.addWidget(b)
        self.btn_stop_resume.setEnabled(False)
        self.btn_new.clicked.connect(self._on_new)
        self.btn_stop_resume.clicked.connect(self._on_stop_resume)
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_export.clicked.connect(self._on_export)
        root.addLayout(btn_row)

        self.lbl_status = QLabel("Idle. Press New to start.")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        theme.set_tone(self.lbl_status, "faint", "font-size:11px;")
        root.addWidget(self.lbl_status)

    def _apply_chart_theme(self):
        """Figure / axes / line colours from the active UI theme."""
        fig, ax = self.figure, self._ax
        fig.set_facecolor(theme.SURFACE)
        ax.set_facecolor(theme.SURFACE)
        ax.tick_params(colors=theme.TEXT_2)
        for sp in ax.spines.values():
            sp.set_edgecolor(theme.TEXT)
        ax.xaxis.label.set_color(theme.TEXT)
        ax.yaxis.label.set_color(theme.TEXT)
        ax.grid(True, color=theme.BORDER, linewidth=0.6)
        self._line.set_color(theme.ACCENT)
        self._current_hline.set_color(theme.WARN)
        self.canvas.draw_idle()

    def _bind_shortcuts(self):
        keys = list(_string.digits) + list(_string.ascii_uppercase)
        for k in keys:
            sc = QShortcut(QKeySequence(k), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda kk=k: self._select_by_key(kk))

    def _select_by_key(self, key):
        # 1) Exact label match (case-insensitive)
        for v in self.values:
            if str(v).upper() == key.upper():
                self._select_value(v)
                return
        # 2) Numeric value match
        try:
            n = int(key)
            for v in self.values:
                if v == n:
                    self._select_value(v)
                    return
        except ValueError:
            pass
        # 3) Index match: digit 1-9 picks 1st-9th value (for letter/word lists)
        if key.isdigit():
            i = int(key) - 1
            if 0 <= i < len(self.values):
                self._select_value(self.values[i])

    # ── Presets ───────────────────────────────────────────────────────────

    def _get_presets(self):
        p = self.config.get("scoring_presets")
        if not isinstance(p, dict):
            p = {}
        return p

    def _populate_preset_combo(self):
        self.combo_preset.blockSignals(True)
        self.combo_preset.clear()
        for name in sorted(self._get_presets().keys()):
            self.combo_preset.addItem(name)
        self.combo_preset.blockSignals(False)

    def _load_preset(self):
        name = self.combo_preset.currentText().strip()
        if not name:
            self._show("No preset selected", error=True)
            return
        presets = self._get_presets()
        if name not in presets:
            self._show(f"Preset '{name}' not found", error=True)
            return
        self.values = list(presets[name])
        self.input_values.setText(",".join(str(v) for v in self.values))
        self.selected_value = None
        self._refresh_radio_buttons()
        self._render_chart()
        self.config["scoring_preset"] = name
        self._persist_last_values()
        self._show(f"Loaded preset: {name}")

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if not ok:
            return
        name = name.strip()
        if not name:
            self._show("Preset name required", error=True)
            return
        presets = dict(self._get_presets())
        presets[name] = list(self.values)
        self.config["scoring_presets"] = presets
        self.config["scoring_preset"] = name
        self._save_config()
        self._populate_preset_combo()
        idx = self.combo_preset.findText(name)
        if idx >= 0:
            self.combo_preset.setCurrentIndex(idx)
        self._show(f"Saved preset: {name}")

    def _delete_preset(self):
        name = self.combo_preset.currentText().strip()
        if not name:
            return
        presets = dict(self._get_presets())
        if name not in presets:
            return
        if QMessageBox.question(
            self, "Delete preset", f"Delete preset '{name}'?",
            QMessageBox.Yes | QMessageBox.No
        ) != QMessageBox.Yes:
            return
        del presets[name]
        self.config["scoring_presets"] = presets
        if self.config.get("scoring_preset") == name:
            self.config.pop("scoring_preset", None)
        self._save_config()
        self._populate_preset_combo()
        self._show(f"Deleted preset: {name}")

    def _persist_last_values(self):
        self.config["scoring_last_values"] = list(self.values)
        self._save_config()

    def _save_config(self):
        win = self.window()
        if hasattr(win, "_save_config"):
            win._save_config()

    # ── Values handling ───────────────────────────────────────────────────

    def _apply_values(self):
        text = self.input_values.text().strip()
        if not text:
            self._show("Enter at least one value", error=True)
            return
        parts = [p.strip() for p in text.split(",") if p.strip()]
        out = []
        seen = set()
        for p in parts:
            try:
                n = float(p)
                v = int(n) if n == int(n) else n
            except ValueError:
                v = p  # keep as string (letter, word, etc.)
            if v not in seen:
                seen.add(v)
                out.append(v)
        if not out:
            self._show("No valid values", error=True)
            return
        self.values = out
        self.selected_value = None
        self._refresh_radio_buttons()
        self._render_chart()
        self._persist_last_values()
        self._show(f"Values set: {', '.join(str(v) for v in self.values)}")

    def _reset_values_to_default(self):
        self.values = list(self.DEFAULT_VALUES)
        self.input_values.setText(",".join(str(v) for v in self.values))
        self.selected_value = None
        self._refresh_radio_buttons()
        self._render_chart()
        self._persist_last_values()

    def _refresh_radio_buttons(self):
        # Clear existing
        for btn in self.radio_group.buttons():
            self.radio_group.removeButton(btn)
            btn.setParent(None)
        while self.radio_row.count():
            item = self.radio_row.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for v in self.values:
            rb = QRadioButton(str(v))
            rb.setStyleSheet("font-size: 14px; font-weight: 600;")
            rb._value = v
            self.radio_group.addButton(rb)
            self.radio_row.addWidget(rb)
        # Pre-select 0 if present, else first value
        default_val = 0 if 0 in self.values else (self.values[0] if self.values else None)
        if default_val is not None:
            self._select_value(default_val)

    def _on_radio(self, btn):
        self._record_value_change(btn._value)

    def _select_value(self, v):
        if v not in self.values:
            return
        for btn in self.radio_group.buttons():
            if btn._value == v:
                btn.setChecked(True)
                self._record_value_change(v)
                break

    def _record_value_change(self, v):
        prev = self.selected_value
        self.selected_value = v
        if self.timer.isActive() and self._t_start is not None and v != prev:
            elapsed = time.perf_counter() - self._t_start
            # Stamp old value at boundary so step-post draws sharp vertical
            if prev is not None:
                self._chart_points.append((elapsed, prev))
            self._chart_points.append((elapsed, v))
            # If prev never got credited in its segment, force a 1-sample export
            if prev is not None and not self._segment_emitted and self._next_export_sec is not None:
                self._export_points.append((self._next_export_sec, prev))
                self._next_export_sec += 1
            self._segment_emitted = False

    # ── Recording control ─────────────────────────────────────────────────

    def _on_new(self):
        title, ok = QInputDialog.getText(self, "New Test", "Enter test title:")
        if not ok:
            return
        self.test_title = title.strip()
        self.lbl_title.setText(self.test_title or "Real-time Manual Scoring")
        self._chart_points = []
        self._export_points = []
        self._next_export_sec = None
        self._segment_emitted = False
        self._t_start = None
        self._t_paused = None
        self.btn_stop_resume.setEnabled(True)
        self.btn_stop_resume.setText("Start")
        self._show("Ready. Press Start to begin recording.")
        self._render_chart()

    def _on_stop_resume(self):
        label = self.btn_stop_resume.text()
        if label == "Start":
            self._t_start = time.perf_counter()
            self._t_paused = None
            if self.selected_value is not None:
                self._chart_points.append((0.0, self.selected_value))
            self.timer.start()
            self.btn_stop_resume.setText("Stop")
            self._show("Recording… (1 sample/s exported, smooth visual)")
        elif label == "Stop":
            self.timer.stop()
            self._t_paused = time.perf_counter()
            self.btn_stop_resume.setText("Resume")
            n = len(self._export_points)
            self._show(f"Paused at {n}s. Press Resume to continue.")
        elif label == "Resume":
            if self._t_start is None or self._t_paused is None:
                return
            pause_duration = time.perf_counter() - self._t_paused
            self._t_start += pause_duration
            self._t_paused = None
            self.timer.start()
            self.btn_stop_resume.setText("Stop")
            self._show("Resumed.")

    def _on_reset(self):
        has_data = bool(self._export_points or self._chart_points)
        if has_data:
            if QMessageBox.question(
                self, "Reset", "Stop recording and clear data?",
                QMessageBox.Yes | QMessageBox.No
            ) != QMessageBox.Yes:
                return
        self.timer.stop()
        self.btn_stop_resume.setEnabled(False)
        self.btn_stop_resume.setText("Stop")
        self._chart_points = []
        self._export_points = []
        self._next_export_sec = None
        self._segment_emitted = False
        self._t_start = None
        self._t_paused = None
        self.test_title = ""
        self.lbl_title.setText("Real-time Manual Scoring")
        self.selected_value = None
        for btn in self.radio_group.buttons():
            btn.setAutoExclusive(False)
            btn.setChecked(False)
            btn.setAutoExclusive(True)
        self._current_hline.set_visible(False)
        self._show("Idle. Press New to start.")
        self._render_chart()

    def _tick(self):
        if self._t_start is None:
            return
        elapsed = time.perf_counter() - self._t_start
        if self.selected_value is not None:
            v = self.selected_value
            if self._next_export_sec is None:
                self._next_export_sec = int(elapsed) + 1
            while self._next_export_sec <= elapsed:
                self._export_points.append((self._next_export_sec, v))
                self._next_export_sec += 1
                self._segment_emitted = True
        self._render_chart()
        n = len(self._export_points)
        self._show(
            f"Recording… {elapsed:.1f}s ({n} exported)"
            f" — value: {self.selected_value if self.selected_value is not None else '—'}"
        )

    # ── Chart ─────────────────────────────────────────────────────────────

    def _render_chart(self):
        ax = self._ax
        if self.values:
            n = len(self.values)
            ax.set_ylim(-0.5, n - 0.5)
            ax.set_yticks(range(n))
            ax.set_yticklabels([str(v) for v in self.values])
        # Build display series: stored value-change points + live head
        pts = list(self._chart_points)
        if self.timer.isActive() and self._t_start is not None and self.selected_value is not None:
            elapsed = time.perf_counter() - self._t_start
            pts.append((elapsed, self.selected_value))
        idx_map = {v: i for i, v in enumerate(self.values)}
        if pts:
            xs = np.fromiter((p[0] for p in pts), dtype=float, count=len(pts))
            ys = np.fromiter((idx_map.get(p[1], 0) for p in pts), dtype=float, count=len(pts))
            self._line.set_data(xs, ys)
            ax.set_xlim(0, max(1.0, xs[-1] * 1.02))
        else:
            self._line.set_data([], [])
            ax.set_xlim(0, 1.0)
        # Current-value horizontal indicator
        if self.selected_value is not None and self.selected_value in idx_map:
            self._current_hline.set_ydata([idx_map[self.selected_value]] * 2)
            self._current_hline.set_visible(True)
        else:
            self._current_hline.set_visible(False)
        self.canvas.draw_idle()
        self._refresh_duration_label()

    def _refresh_duration_label(self):
        if not self._export_points:
            self.lbl_duration.setText("")
            return
        counts = Counter(v for _, v in self._export_points)
        parts = [f"<b>{v}:</b> {counts[v]}s" for v in self.values if v in counts]
        self.lbl_duration.setText(" · ".join(parts))

    # ── Export ────────────────────────────────────────────────────────────

    def _on_export(self):
        if not self._export_points:
            self._show("Nothing to export — record some data first.", error=True)
            return

        folder = self.config.get("scoring_output_folder") or self.config.get("output_folder")
        if not folder or not os.path.isdir(folder):
            folder = QFileDialog.getExistingDirectory(self, "Choose output folder")
            if not folder:
                return
            self.config["scoring_output_folder"] = folder
            self._save_config()
            self._refresh_output_label()

        title = self.test_title or "scoring"
        safe = "".join(c for c in title if c.isalnum() or c in (" ", "_", "-")).strip() or "scoring"
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(folder, f"{safe}-{ts}.xlsx")

        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "Scoring"
            ws.append(["Sample", "Score"])
            for t, v in self._export_points:
                ws.append([t, v])
            ws["A1"].font = ws["A1"].font.copy(bold=True)
            ws["B1"].font = ws["B1"].font.copy(bold=True)
            wb.save(path)
            self._show(f"Saved: {path}")
            from gui.notify import show_done
            show_done(self, "Scoring saved", f"{len(self._export_points)} sample(s).", path=path)
        except Exception as e:
            self._show(f"Save failed: {e}", error=True)

    # ── Output folder ─────────────────────────────────────────────────────

    def _current_output_dir(self):
        return self.config.get("scoring_output_folder") or self.config.get("output_folder") or ""

    def _refresh_output_label(self):
        path = self._current_output_dir()
        if path:
            self.lbl_output_dir.setText(path)
            theme.set_tone(self.lbl_output_dir, "muted", "font-size:11px;")
        else:
            self.lbl_output_dir.setText("(not set — will prompt on Export)")
            self.lbl_output_dir.setStyleSheet("color:#999; font-size:11px; font-style:italic;")

    def _change_output_dir(self):
        start = self._current_output_dir() or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Choose scoring output folder", start)
        if not folder:
            return
        self.config["scoring_output_folder"] = folder
        self._save_config()
        self._refresh_output_label()
        self._show(f"Output folder set: {folder}")

    def _open_output_dir(self):
        path = self._current_output_dir()
        if not path or not os.path.isdir(path):
            self._show("Output folder not set or missing", error=True)
            return
        try:
            os.startfile(path)  # Windows
        except AttributeError:
            import subprocess, sys
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, path])

    # ── Helpers ───────────────────────────────────────────────────────────

    def _show(self, msg, error=False):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet(
            f"color:{theme.ERR if error else theme.FAINT}; font-size:11px;"
        )
