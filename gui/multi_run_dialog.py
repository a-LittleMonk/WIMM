"""Multi-Run sweep dialog.

Re-runs tracking on a single video with one swept variable, holding every
other setting locked. Produces a comparison xlsx via export_multi_run.
"""
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
    ("body_style",   "Body style",            "categorical",
        [(0, "off"), (1, "dots"), (2, "skeleton"), (3, "dots+skeleton")], None),
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


class MultiRunDialog(QDialog):
    """Pick one swept variable + values, run N tracker passes, write xlsx."""

    def __init__(self, batch_tab, parent=None):
        super().__init__(parent)
        self.batch_tab = batch_tab
        self.setWindowTitle("Multi-Run — sweep one variable")
        self.setModal(True)
        self.resize(560, 480)
        self._cancel = False
        self._build_ui()
        self._refresh_video_label()
        self._on_var_change(0)

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setSpacing(8)
        outer.setContentsMargins(12, 12, 12, 12)

        info = QLabel(
            "Re-runs the currently loaded video N times. Every setting except the "
            "chosen variable is locked to the current snapshot."
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
        form.addRow("Swept variable:", self.combo_var)

        # Two value-input modes stacked: numeric (checklist + extras) and categorical (checklist).
        self.value_stack = QStackedWidget()

        # Numeric: preset checklist + optional extras field.
        self.list_numeric = QListWidget()
        self.list_numeric.setSelectionMode(QListWidget.NoSelection)
        self.edit_extras = QLineEdit()
        self.edit_extras.setPlaceholderText("Extra values (optional), e.g. 12, 18")
        num_wrap = QWidget()
        nv = QVBoxLayout(num_wrap)
        nv.setContentsMargins(0, 0, 0, 0)
        nv.setSpacing(4)
        nv.addWidget(self.list_numeric)
        nv.addWidget(self.edit_extras)
        self.value_stack.addWidget(num_wrap)

        self.list_values = QListWidget()
        self.list_values.setSelectionMode(QListWidget.NoSelection)
        list_wrap = QWidget()
        lv = QVBoxLayout(list_wrap)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.list_values)
        self.value_stack.addWidget(list_wrap)
        form.addRow("Values:", self.value_stack)

        outer.addLayout(form)

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

    def _refresh_video_label(self):
        path = getattr(self.batch_tab, "_embedded_loaded_path", None)
        if path:
            self.lbl_video.setText(os.path.basename(path))
        else:
            self.lbl_video.setText("(no video loaded — open one first)")

    def _on_var_change(self, idx):
        key, label, vtype, opts, default = SWEPT_VARS[idx]
        if vtype == "categorical":
            self.value_stack.setCurrentIndex(1)
            self.list_values.clear()
            for opt_val, opt_label in opts:
                it = QListWidgetItem(f"{opt_label}")
                it.setData(Qt.UserRole, opt_val)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Unchecked)
                self.list_values.addItem(it)
        else:
            self.value_stack.setCurrentIndex(0)
            self.list_numeric.clear()
            self.edit_extras.clear()
            cast = int if vtype == "int" else float
            for p in [s.strip() for s in (default or "").split(",") if s.strip()]:
                try:
                    v = cast(p)
                except ValueError:
                    try:
                        v = float(p)
                    except ValueError:
                        continue
                it = QListWidgetItem(str(v))
                it.setData(Qt.UserRole, v)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Unchecked)
                self.list_numeric.addItem(it)

    def _pick_out(self):
        folder = QFileDialog.getExistingDirectory(self, "Output folder")
        if folder:
            self.edit_out.setText(folder)

    # ── Run ───────────────────────────────────────────────────────────
    def _parse_values(self):
        idx = self.combo_var.currentIndex()
        key, label, vtype, opts, _default = SWEPT_VARS[idx]
        if vtype == "categorical":
            picked = []
            for i in range(self.list_values.count()):
                it = self.list_values.item(i)
                if it.checkState() == Qt.Checked:
                    val = it.data(Qt.UserRole)
                    picked.append((val, it.text()))
            return key, label, vtype, picked
        # numeric: checked presets + parsed extras, dedup preserving order
        out = []
        seen = set()
        for i in range(self.list_numeric.count()):
            it = self.list_numeric.item(i)
            if it.checkState() == Qt.Checked:
                v = it.data(Qt.UserRole)
                if v not in seen:
                    seen.add(v)
                    out.append((v, str(v)))
        extras = (self.edit_extras.text() or "").strip()
        if extras:
            for p in [s.strip() for s in extras.split(",") if s.strip()]:
                try:
                    v = int(p) if vtype == "int" else float(p)
                except ValueError:
                    try:
                        v = float(p)
                    except ValueError:
                        raise RuntimeError(f"Could not parse '{p}' as a number")
                if v not in seen:
                    seen.add(v)
                    out.append((v, str(v)))
        return key, label, vtype, out

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
        try:
            key, label, vtype, value_pairs = self._parse_values()
        except RuntimeError as e:
            QMessageBox.warning(self, "Multi-Run", str(e))
            return
        if not value_pairs:
            QMessageBox.warning(self, "Multi-Run",
                                "Pick at least one value to sweep.")
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
        if not base.get("arena"):
            QMessageBox.warning(self, "Multi-Run",
                                "Define an arena for this video before sweeping.")
            return

        self._cancel = False
        self.btn_run.setEnabled(False)
        self.btn_cancel.setText("Stop")
        self.progress_total.setRange(0, len(value_pairs))
        self.progress_total.setValue(0)
        self.progress_one.setRange(0, 100)
        self.progress_one.setValue(0)

        logger.info(
            f"Multi-Run start: var={key} values={[v for v,_ in value_pairs]}",
            source="multirun",
        )

        variants = []
        for i, (val, val_label) in enumerate(value_pairs, start=1):
            if self._cancel:
                break
            self.lbl_status.setText(f"Running {i}/{len(value_pairs)} — {label} = {val_label}")
            QApplication.processEvents()
            s = dict(base)
            s[key] = val
            self.progress_one.setValue(0)
            try:
                result = self.batch_tab._track_for_multirun(
                    path, s,
                    progress_cb=lambda p: (self.progress_one.setValue(p),
                                           QApplication.processEvents()),
                )
            except Exception as e:
                logger.error(f"Multi-Run variant failed ({key}={val}): {e}",
                             source="multirun")
                QMessageBox.warning(self, "Multi-Run",
                                    f"Variant {key}={val_label} failed: {e}\n"
                                    "Continuing with remaining variants.")
                self.progress_total.setValue(i)
                continue
            variants.append({
                "label":    val_label,
                "value":    val,
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
        out_path = os.path.join(
            out_folder, f"multirun_{video_name}_{key}_{ts}.xlsx"
        )
        try:
            from export.excel_export import export_multi_run
            export_multi_run(
                output_path=out_path,
                video_name=video_name,
                swept_key=key,
                swept_label=label,
                base_settings=base,
                variants=variants,
            )
            self.lbl_status.setText(f"Saved: {out_path}")
            logger.info(f"Multi-Run wrote {out_path}", source="multirun")
            QMessageBox.information(
                self, "Multi-Run complete",
                f"Wrote {len(variants)} variant(s) to:\n{out_path}"
            )
        except Exception as e:
            logger.error(f"Multi-Run export failed: {e}", source="multirun")
            QMessageBox.warning(self, "Multi-Run", f"Export failed: {e}")
        finally:
            self.btn_run.setEnabled(True)
            self.btn_cancel.setText("Close")
