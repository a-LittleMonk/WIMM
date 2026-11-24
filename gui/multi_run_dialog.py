"""Multi-Run sweep dialog.

Re-runs tracking on a single video while sweeping one or more variables.
Tick values for as many variables as you like; the dialog then runs either
every combination (full grid) or each variable on its own against the
current baseline. Produces a comparison xlsx via export_multi_run.
"""
import itertools
import os
from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QComboBox, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QProgressBar, QStackedWidget, QWidget, QMessageBox,
    QFileDialog, QApplication,
)

from core import logger


# Catalog of swept variables. Categorical types render as a checklist;
# numeric types render as a comma-separated text field.
SWEPT_VARS = [
    ("model",        "Tracking model",        "categorical",
        [(0, "median"), (1, "mog2"), (2, "knn"), (3, "cnt"),
         (4, "gsoc"), (5, "lsbp"), (6, "framediff"), (7, "hsv")], None),
    ("proc_scale",   "Processing scale",      "categorical",
        [(0, "100%"), (1, "75%"), (2, "50%"), (3, "25%")], None),
    ("threshold",    "Threshold",             "int",   None, "20, 25, 30, 35"),
    ("brightness",   "Brightness",            "int",   None, "-20, 0, 20"),
    ("contrast",     "Contrast (%)",          "int",   None, "80, 100, 120, 150"),
    ("blur",         "Blur",                  "int",   None, "0, 1, 3, 5"),
    ("gamma",        "Gamma (%)",             "int",   None, "80, 100, 120"),
    ("sharpen",      "Sharpen",               "int",   None, "0, 1, 3"),
    ("clahe",        "CLAHE clip",            "int",   None, "0, 2, 4"),
    ("max_blob",     "Max blob (%)",          "int",   None, "0, 5, 10"),
    ("smooth",       "Smoothing",             "int",   None, "0, 1, 3, 5"),
    ("frame_skip",   "Frame skip",            "int",   None, "1, 2, 3, 4, 5, 6, 7, 8, 9, 10"),
    ("fps_override", "FPS override",          "float", None, "0, 24, 30, 60"),
    ("movement_thr", "Movement thr (cm/s)",   "float", None, "0, 1, 2"),
    ("bin_size",     "Time bin (s)",          "float", None, "0, 30, 60"),
    ("center_pct",   "Center zone (%)",       "int",   None, "20, 25, 33, 50"),
    ("trim_start",   "Trim start (s)",        "float", None, "0, 5, 10"),
    ("trim_duration","Trim duration (s)",     "float", None, "0, 30, 60"),
]


from gui import theme


# Above this many runs, ask before starting.
_CONFIRM_RUNS = 30

_MODE_GRID = 0      # every combination of the ticked values
_MODE_SINGLE = 1    # each variable alone; others stay at baseline


def _var_by_key(key):
    for entry in SWEPT_VARS:
        if entry[0] == key:
            return entry
    return None


class MultiRunDialog(QDialog):
    """Tick values for one or more variables, run the tracker passes, write xlsx."""

    def __init__(self, batch_tab, parent=None):
        super().__init__(parent)
        self.batch_tab = batch_tab
        self.setWindowTitle("Multi-Run — sweep settings")
        self.setModal(True)
        self.resize(600, 600)
        self._cancel = False
        # Remembered ticks per variable: key -> {"checked": set, "extras": str}
        self._picks = {}
        self._cur_key = None
        self._building = False
        self._build_ui()
        self._refresh_video_label()
        self._on_var_change(0)

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setSpacing(8)
        outer.setContentsMargins(12, 12, 12, 12)

        info = QLabel(
            "Re-runs the currently loaded video several times. Pick a variable, "
            "tick its values, then pick another variable and do the same. "
            "Every setting you don't sweep stays at the current snapshot."
        )
        info.setWordWrap(True)
        theme.set_tone(info, "faint", "font-size:11px;")
        outer.addWidget(info)

        form = QFormLayout()
        form.setSpacing(6)

        self.lbl_video = QLabel("(no video loaded)")
        theme.set_tone(self.lbl_video, "text2", "")
        form.addRow("Video:", self.lbl_video)

        self.combo_var = QComboBox()
        for key, label, vtype, _opts, _def in SWEPT_VARS:
            self.combo_var.addItem(label, key)
        self.combo_var.currentIndexChanged.connect(self._on_var_change)
        form.addRow("Variable:", self.combo_var)

        # Two value-input modes stacked: numeric (checklist + extras) and categorical (checklist).
        self.value_stack = QStackedWidget()

        self.list_numeric = QListWidget()
        self.list_numeric.setSelectionMode(QListWidget.NoSelection)
        self.list_numeric.setMaximumHeight(130)
        self.list_numeric.itemChanged.connect(self._on_picks_changed)
        self.edit_extras = QLineEdit()
        self.edit_extras.setPlaceholderText("Extra values (optional), e.g. 12, 18")
        self.edit_extras.textChanged.connect(self._on_picks_changed)
        num_wrap = QWidget()
        nv = QVBoxLayout(num_wrap)
        nv.setContentsMargins(0, 0, 0, 0)
        nv.setSpacing(4)
        nv.addWidget(self.list_numeric)
        nv.addWidget(self.edit_extras)
        self.value_stack.addWidget(num_wrap)

        self.list_values = QListWidget()
        self.list_values.setSelectionMode(QListWidget.NoSelection)
        self.list_values.setMaximumHeight(160)
        self.list_values.itemChanged.connect(self._on_picks_changed)
        list_wrap = QWidget()
        lv = QVBoxLayout(list_wrap)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.list_values)
        self.value_stack.addWidget(list_wrap)
        form.addRow("Values:", self.value_stack)

        outer.addLayout(form)

        # Sweep plan: every variable that has at least one ticked value.
        plan_box = QGroupBox("Sweep plan")
        pv = QVBoxLayout(plan_box)
        pv.setSpacing(4)
        self.list_plan = QListWidget()
        self.list_plan.setMaximumHeight(110)
        self.list_plan.itemDoubleClicked.connect(self._on_plan_double_click)
        pv.addWidget(self.list_plan)

        plan_row = QHBoxLayout()
        plan_row.addWidget(QLabel("Combine:"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("All combinations", _MODE_GRID)
        self.combo_mode.addItem("One variable at a time", _MODE_SINGLE)
        self.combo_mode.currentIndexChanged.connect(self._refresh_plan)
        plan_row.addWidget(self.combo_mode)
        plan_row.addStretch()
        btn_remove = QPushButton("Remove")
        btn_remove.setFixedHeight(24)
        btn_remove.clicked.connect(self._remove_selected)
        btn_clear = QPushButton("Clear all")
        btn_clear.setFixedHeight(24)
        btn_clear.clicked.connect(self._clear_all)
        plan_row.addWidget(btn_remove)
        plan_row.addWidget(btn_clear)
        pv.addLayout(plan_row)

        self.lbl_count = QLabel("")
        theme.set_tone(self.lbl_count, "text2", "font-size:11px;")
        pv.addWidget(self.lbl_count)
        outer.addWidget(plan_box)

        # Output folder line.
        of_row = QHBoxLayout()
        self.edit_out = QLineEdit(self.batch_tab.config.get("output_folder", ""))
        btn_browse = QPushButton("Browse…")
        btn_browse.setFixedHeight(24)
        btn_browse.clicked.connect(self._pick_out)
        of_row.addWidget(QLabel("Output folder:"))
        of_row.addWidget(self.edit_out, 1)
        of_row.addWidget(btn_browse)
        outer.addLayout(of_row)

        # Progress.
        self.lbl_status = QLabel("")
        theme.set_tone(self.lbl_status, "text2", "font-size:11px;")
        self.lbl_status.setWordWrap(True)
        outer.addWidget(self.lbl_status)
        self.progress_total = QProgressBar()
        self.progress_total.setFormat("Variant %v / %m")
        outer.addWidget(self.progress_total)
        self.progress_one = QProgressBar()
        self.progress_one.setFormat("This run %p%")
        outer.addWidget(self.progress_one)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_run = QPushButton("Run sweep")
        self.btn_run.setFixedHeight(28)
        self.btn_run.clicked.connect(self._on_run)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setFixedHeight(28)
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.btn_run)
        btn_row.addWidget(self.btn_cancel)
        outer.addLayout(btn_row)

        self._refresh_plan()

    def _refresh_video_label(self):
        path = getattr(self.batch_tab, "_embedded_loaded_path", None)
        if path:
            self.lbl_video.setText(os.path.basename(path))
        else:
            self.lbl_video.setText("(no video loaded — open one first)")

    # ── Per-variable ticks ────────────────────────────────────────────
    def _save_current_picks(self):
        """Store the ticks shown on screen for the current variable."""
        key = self._cur_key
        if key is None:
            return
        vtype = _var_by_key(key)[2]
        lst = self.list_values if vtype == "categorical" else self.list_numeric
        checked = set()
        for i in range(lst.count()):
            it = lst.item(i)
            if it.checkState() == Qt.Checked:
                checked.add(it.data(Qt.UserRole))
        extras = "" if vtype == "categorical" else (self.edit_extras.text() or "").strip()
        if checked or extras:
            self._picks[key] = {"checked": checked, "extras": extras}
        else:
            self._picks.pop(key, None)

    def _on_picks_changed(self, *_):
        if self._building:
            return
        self._save_current_picks()
        self._refresh_plan()

    def _on_var_change(self, idx):
        self._save_current_picks()
        key, label, vtype, opts, default = SWEPT_VARS[idx]
        self._cur_key = key
        saved = self._picks.get(key) or {"checked": set(), "extras": ""}
        self._building = True
        try:
            if vtype == "categorical":
                self.value_stack.setCurrentIndex(1)
                self.list_values.clear()
                for opt_val, opt_label in opts:
                    it = QListWidgetItem(f"{opt_label}")
                    it.setData(Qt.UserRole, opt_val)
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(Qt.Checked if opt_val in saved["checked"]
                                     else Qt.Unchecked)
                    self.list_values.addItem(it)
            else:
                self.value_stack.setCurrentIndex(0)
                self.list_numeric.clear()
                self.edit_extras.setText(saved["extras"])
                for v in _preset_values(vtype, default):
                    it = QListWidgetItem(str(v))
                    it.setData(Qt.UserRole, v)
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(Qt.Checked if v in saved["checked"]
                                     else Qt.Unchecked)
                    self.list_numeric.addItem(it)
        finally:
            self._building = False
        self._refresh_plan()

    # ── Plan ──────────────────────────────────────────────────────────
    def _values_for(self, key, strict=False):
        """Ordered [(value, label)] for one variable from its remembered ticks.

        With strict=True an unparsable extra value raises RuntimeError;
        otherwise it is skipped (used for the live preview).
        """
        _k, label, vtype, opts, default = _var_by_key(key)
        saved = self._picks.get(key)
        if not saved:
            return []
        if vtype == "categorical":
            return [(v, lbl) for v, lbl in opts if v in saved["checked"]]
        out, seen = [], set()
        for v in _preset_values(vtype, default):
            if v in saved["checked"] and v not in seen:
                seen.add(v)
                out.append((v, str(v)))
        for p in [s.strip() for s in saved["extras"].split(",") if s.strip()]:
            try:
                v = int(p) if vtype == "int" else float(p)
            except ValueError:
                try:
                    v = float(p)
                except ValueError:
                    if strict:
                        raise RuntimeError(f"{label}: could not parse '{p}' as a number")
                    continue
            if v not in seen:
                seen.add(v)
                out.append((v, str(v)))
        return out

    def _plan(self, strict=False):
        """[(key, label, [(value, value_label), ...]), ...] in catalog order."""
        plan = []
        for key, label, _vt, _o, _d in SWEPT_VARS:
            vals = self._values_for(key, strict=strict)
            if vals:
                plan.append((key, label, vals))
        return plan

    def _refresh_plan(self, *_):
        self.list_plan.clear()
        plan = self._plan()
        for key, label, vals in plan:
            it = QListWidgetItem(f"{label}:  " + ", ".join(vl for _v, vl in vals))
            it.setData(Qt.UserRole, key)
            self.list_plan.addItem(it)
        mode = self.combo_mode.currentData()
        n = len(variant_specs(plan, mode))
        if not plan:
            self.lbl_count.setText("Nothing ticked yet.")
        elif mode == _MODE_GRID and len(plan) > 1:
            sizes = " × ".join(str(len(v)) for _k, _l, v in plan)
            self.lbl_count.setText(f"{sizes} = {n} runs")
        else:
            self.lbl_count.setText(f"{n} run{'s' if n != 1 else ''}")

    def _on_plan_double_click(self, item):
        idx = self.combo_var.findData(item.data(Qt.UserRole))
        if idx >= 0:
            self.combo_var.setCurrentIndex(idx)

    def _remove_selected(self):
        item = self.list_plan.currentItem()
        if item is None:
            return
        key = item.data(Qt.UserRole)
        self._picks.pop(key, None)
        if key == self._cur_key:
            self._cur_key = None   # don't re-save the on-screen ticks
            self._on_var_change(self.combo_var.currentIndex())
        else:
            self._refresh_plan()

    def _clear_all(self):
        self._picks.clear()
        self._cur_key = None
        self._on_var_change(self.combo_var.currentIndex())

    def _pick_out(self):
        folder = QFileDialog.getExistingDirectory(self, "Output folder")
        if folder:
            self.edit_out.setText(folder)

    # ── Run ───────────────────────────────────────────────────────────
    def _on_cancel(self):
        if self.btn_run.isEnabled():
            self.reject()
        else:
            self._cancel = True
            self.lbl_status.setText("Cancelling after current variant…")

    def _on_run(self):
        path = getattr(self.batch_tab, "_embedded_loaded_path", None)
        if not path:
            QMessageBox.warning(self, "Multi-Run", "Load a video first.")
            return
        self._save_current_picks()
        try:
            plan = self._plan(strict=True)
        except RuntimeError as e:
            QMessageBox.warning(self, "Multi-Run", str(e))
            return
        if not plan:
            QMessageBox.warning(self, "Multi-Run",
                                "Tick at least one value to sweep.")
            return
        mode = self.combo_mode.currentData()
        specs = variant_specs(plan, mode)
        if len(specs) > _CONFIRM_RUNS:
            ans = QMessageBox.question(
                self, "Multi-Run",
                f"This will track the video {len(specs)} times, which may take "
                "a long time. Continue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return
        out_folder = (self.edit_out.text() or "").strip()
        if not out_folder or not os.path.isdir(out_folder):
            QMessageBox.warning(self, "Multi-Run",
                                "Pick a valid output folder.")
            return

        # Pull a FRESH snapshot from the embedded panel — bypasses any
        # stale entry in video_settings so live slider values always count.
        base = None
        et = getattr(self.batch_tab, "embedded_tab", None)
        if (et is not None and hasattr(et, "snapshot_settings")
                and getattr(self.batch_tab, "_embedded_loaded_path", None) == path):
            try:
                base = dict(et.snapshot_settings())
                # Mirror back into video_settings so the rest of the app sees
                # the same baseline (matches the regular Run flow).
                self.batch_tab.video_settings[path] = dict(base)
            except Exception:
                base = None
        if base is None:
            base = dict(self.batch_tab.video_settings.get(path) or {})
        # EPM / Y-Maze have no arena: their arms are the zones (the
        # variant run builds the tracker region from them).
        exp = getattr(et, "experiment", None) if et is not None else None
        needs_arena = getattr(exp, "fam", "open_field") in ("open_field", "nor", "box")
        if needs_arena and not base.get("arena"):
            QMessageBox.warning(self, "Multi-Run",
                                "Define an arena for this video before sweeping.")
            return
        if not needs_arena and not self.batch_tab._has_arena(path):
            QMessageBox.warning(self, "Multi-Run",
                                "Draw the maze arms for this video before sweeping.")
            return

        swept = [(key, label) for key, label, _vals in plan]
        multi = len(swept) > 1

        self._cancel = False
        self.btn_run.setEnabled(False)
        self.btn_cancel.setText("Stop")
        self.progress_total.setRange(0, len(specs))
        self.progress_total.setValue(0)
        self.progress_one.setRange(0, 100)
        self.progress_one.setValue(0)

        logger.info(
            f"Multi-Run start: mode={'grid' if mode == _MODE_GRID else 'single'} "
            f"vars={[(k, [v for v, _ in vals]) for k, _l, vals in plan]} "
            f"runs={len(specs)}",
            source="multirun",
        )

        variants = []
        for i, spec in enumerate(specs, start=1):
            if self._cancel:
                break
            desc = ", ".join(f"{lbl} = {vl}" for _k, lbl, _v, vl in spec)
            self.lbl_status.setText(f"Running {i}/{len(specs)} — {desc}")
            QApplication.processEvents()
            s = dict(base)
            for key, _lbl, val, _vl in spec:
                s[key] = val
            self.progress_one.setValue(0)
            try:
                result = self.batch_tab._track_for_multirun(
                    path, s,
                    progress_cb=lambda p: (self.progress_one.setValue(p),
                                           QApplication.processEvents()),
                )
            except Exception as e:
                logger.error(f"Multi-Run variant failed ({desc}): {e}",
                             source="multirun")
                QMessageBox.warning(self, "Multi-Run",
                                    f"Variant {desc} failed: {e}\n"
                                    "Continuing with remaining variants.")
                self.progress_total.setValue(i)
                continue
            variants.append({
                "label":    variant_label(i, spec, multi),
                "value":    None if multi else spec[0][2],
                "values":   {k: vl for k, _l, _v, vl in spec},
                "settings": s,
                "result":   result,
            })
            self.progress_total.setValue(i)

        if not variants:
            self.btn_run.setEnabled(True)
            self.btn_cancel.setText("Cancel")
            self.lbl_status.setText("No successful runs.")
            return

        # Write xlsx.
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        video_name = os.path.splitext(os.path.basename(path))[0]
        key_part = "+".join(k for k, _l in swept)
        if len(key_part) > 60:
            key_part = f"{len(swept)}vars"
        out_path = os.path.join(
            out_folder, f"multirun_{video_name}_{key_part}_{ts}.xlsx"
        )
        try:
            from export.excel_export import export_multi_run
            export_multi_run(
                output_path=out_path,
                video_name=video_name,
                swept_key=[k for k, _l in swept],
                swept_label=[l for _k, l in swept],
                base_settings=base,
                variants=variants,
            )
            self.lbl_status.setText(f"Saved: {out_path}")
            logger.info(f"Multi-Run wrote {out_path}", source="multirun")
            from gui.notify import show_notices
            show_notices(self)
            from gui.notify import show_done
            show_done(self, "Multi-run complete",
                      f"{len(variants)} variant(s) compared in one workbook.", path=out_path)
        except Exception as e:
            logger.error(f"Multi-Run export failed: {e}", source="multirun")
            from gui.notify import show_done
            show_done(self, "Multi-run export failed", str(e), kind="err")
        finally:
            self.btn_run.setEnabled(True)
            self.btn_cancel.setText("Close")


# ── Pure helpers (no Qt; unit-testable) ──────────────────────────────
def _preset_values(vtype, default):
    """Parse the comma-separated preset string for a numeric variable."""
    cast = int if vtype == "int" else float
    out = []
    for p in [s.strip() for s in (default or "").split(",") if s.strip()]:
        try:
            out.append(cast(p))
        except ValueError:
            try:
                out.append(float(p))
            except ValueError:
                continue
    return out


def variant_specs(plan, mode):
    """Expand a plan into runs; each run is a list of (key, label, value, value_label).

    plan = [(key, label, [(value, value_label), ...]), ...]
    """
    if not plan:
        return []
    if mode == _MODE_SINGLE:
        return [[(key, label, v, vl)] for key, label, vals in plan for v, vl in vals]
    axes = [[(key, label, v, vl) for v, vl in vals] for key, label, vals in plan]
    return [list(combo) for combo in itertools.product(*axes)]


def variant_label(i, spec, multi):
    """Column/sheet label for one run."""
    if not multi:
        return str(spec[0][3])
    return f"Run {i}: " + ", ".join(f"{k}={vl}" for k, _l, _v, vl in spec)
