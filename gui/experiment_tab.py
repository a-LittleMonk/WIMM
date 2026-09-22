"""ExperimentTab — base class for per-experiment configuration tabs.

Houses the generic shell (video load, scrub, zones, calibration, perspective,
preview, smoothing, exclusion brush, presets, Excel/Graphs tabs, status badges,
shared shortcuts). Open-Field-specific bits (cell info, grid drawing, cell
highlight controls, _step_geometry_of) currently live inline as methods —
they are factored out into a OpenFieldTab subclass + experiments/open_field/
modules in the next phase. Y-Maze plugs in via the `experiment` argument.
"""
import os
import json
from io import BytesIO
import cv2
import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGroupBox, QPushButton,
    QLabel, QSpinBox, QDoubleSpinBox, QProgressBar, QFileDialog,
    QSizePolicy, QFrame, QMessageBox, QSlider, QScrollArea, QComboBox,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QInputDialog, QShortcut, QColorDialog, QDialog, QLineEdit, QFormLayout,
    QSplitter,
)
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QPixmap, QKeySequence, QColor, QImage
from gui.zone_drawer import ZoneDrawer
from tracking.tracker import TrackerThread, DEFAULT_MODEL_PARAMS, DEFAULT_POST_PARAMS
from tracking.preprocessor import (
    BgBuilderThread, apply_preprocessing, apply_preprocessing_bgr,
    get_mask, make_overlay, make_mask_view
)
from export.excel_export import export_results
from gui.graph_style import (
    GraphStyleConfig,
    DEFAULT_CAPS as GRAPH_DEFAULT_CAPS,
    ACCENT_COLORS as GRAPH_ACCENTS,
)

PRESETS_PATH = os.path.join(os.path.expanduser("~"), ".mice_tracker_presets.json")


class _FitLabel(QLabel):
    """QLabel that scales its source pixmap to its widget size while
    preserving aspect ratio. Re-fits on every resize."""
    def __init__(self):
        super().__init__()
        self._src = None
        self.setMinimumSize(1, 1)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

    def setPixmap(self, pix):
        self._src = pix
        self._refit()

    def _refit(self):
        if self._src is None or self._src.isNull():
            super().clear()
            return
        super().setPixmap(self._src.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refit()

from core.io.video_export import VideoExportThread as _VideoExportThread
from core import logger


# Legacy combo-index → string-key migration tables. Kept here so old
# saved configs / presets (where these fields were saved as ints) still
# load on a current build. New saves write the string/float directly.
_LEGACY_MODEL_ORDER  = ["median", "mog2", "knn", "cnt", "gsoc", "lsbp",
                         "framediff", "hsv"]
_LEGACY_PROC_SCALES  = [1.0, 0.75, 0.5, 0.25]
_LEGACY_BODY_STYLES  = ["off", "dot", "ends"]


def _migrate_combo_value(value, legacy_list, default):
    """Accept either the new direct value or a legacy int index; return
    the canonical value. Out-of-range ints fall back to `default`."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        if 0 <= value < len(legacy_list):
            return legacy_list[value]
        return default
    return value if value is not None else default


DEFAULT_COLORS = {
    "body":         "#A00000",
    "nose":         "#00C800",
    "tail":         "#0064C8",
    "arena":        "#3CA0FF",
    "center_zone":  "#3CDC64",
    "grid":         "#96C8FF",
    "detection":    "#8C0000",
}


def _upgrade_legacy_colors(d):
    """Migrate older configs:
    - 'center' → 'center_zone' rename
    - drop obsolete 'tail_attach' key (legacy appendage marker — current
      'tail' key is the caudal endpoint of the body axis, not the same)
    Mutates and returns d."""
    if isinstance(d, dict):
        if "center" in d and "center_zone" not in d:
            d["center_zone"] = d.pop("center")
        d.pop("tail_attach", None)
    return d


def _hex_to_bgr(hex_str):
    h = hex_str.lstrip("#")
    return (int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16))

from gui.output import (
    ScrubMixin, CorrectionsMixin, IssuesMixin, OutputTabsMixin, GraphsMixin,
)


# Method-resolution order: mixins first so their implementations are picked
# up via inheritance, then QWidget supplies the Qt machinery. Each mixin
# only adds methods; no __init__ so MRO stays clean.
class ExperimentTab(ScrubMixin, CorrectionsMixin, IssuesMixin,
                    OutputTabsMixin, GraphsMixin, QWidget):
    # Emitted after a successful _recompute_metrics_and_views — lets
    # the batch tab refresh its per-video cache so swap-away/back
    # reflects post-edit metrics.
    metrics_changed = pyqtSignal()

    def __init__(self, config, experiment=None):
        super().__init__()
        self.config = config
        # Plugin object — defaults to Open Field. Subclasses (Y-Maze)
        # pass their own. Set early so _build_ui can call into it.
        if experiment is None:
            from experiments.open_field import OpenFieldExperiment
            experiment = OpenFieldExperiment()
        self.experiment = experiment
        self.video_path = None
        self.fps = None
        self._auto_fps = None
        self.bin_df = None
        self.video_w = None
        self.setAcceptDrops(True)
        self.video_h = None
        self.tracking_results = None
        self._raw_results = None
        self._perspective_on = False
        self._H = None                  # 3×3 homography or None
        self._original_arena = None     # backup when perspective active
        self._bg_builder = None
        # Keep refs to in-flight bg builders so they aren't GC'd mid-run
        # (destroying a running QThread crashes the app on rapid reloads).
        self._bg_builders_active = []
        # Cached scrub cv2.VideoCapture. Reused across _on_scrub calls so a
        # 60s slider drag doesn't reopen the file 60×. Reopens only when
        # video_path changes (see _get_scrub_cap).
        self._scrub_cap = None
        self._scrub_cap_path = None
        self._first_frame_bgr = None
        self._current_scrub_frame_bgr = None
        # Auto-from-movement state: when True, the next tracking run skips
        # the arena (whole frame is the detection area), and the arena is
        # built live from the bounding box of the mouse's path.
        self._arena_auto_movement = False
        # Live cell overlay during tracking — off by default for speed.
        # When off, cell numbers / timer / entries are temporarily hidden
        # during a tracking run so the tracker doesn't pay for repaints
        # and per-frame cell-id math. The data is still computed on scrub.
        self._live_cell_overlay = False
        self._tracking_active = False
        self._cell_show_state_backup = None
        # Last-picked define-arena mode: "manual" | "contrast" | "movement".
        # Stored per video and reflected in the dropdown button label.
        self._arena_define_mode = None
        # Per-video crop rect (x, y, w, h) in original-frame pixels, or None.
        # Set externally by the batch tab from settings BEFORE _load_video_path.
        # When set, every read frame is cropped — display, scrub, everything.
        self._crop_rect = None
        self._preview_bg_raw = None
        self._preview_active = False
        self._preview_mode = "overlay"
        self.metrics = None
        self.raw_df = None
        self._presets = self._load_presets_file()
        saved_colors = config.get("colors", {}) if isinstance(config.get("colors"), dict) else {}
        self._colors = {**DEFAULT_COLORS, **_upgrade_legacy_colors(dict(saved_colors))}
        # User-customizable graph styles (per-graph, with named presets).
        gs = config.get("graph_style")
        self._graph_style = GraphStyleConfig.from_dict(gs) if isinstance(gs, dict) else GraphStyleConfig()
        self._color_buttons = {}
        self.overlay_alpha = int(config.get("overlay_alpha", 55))
        # Simple-vs-Full view: list of widgets that hide in Simple mode.
        # Populated as each step builds.
        self._simple_mode = bool(config.get("simple_mode", True))
        self._advanced_widgets = []
        # Debounce timer for live-recompute spinboxes (Move threshold, Time
        # bin, Cell min dwell). Coalesces rapid clicks into one recompute.
        # `_metrics_dirty_pending` accumulates the affected graph names; the
        # timer fires a narrow recompute when it expires. Set to None to
        # request a full recompute.
        self._metrics_dirty_pending = set()
        self._metrics_debounce = QTimer(self)
        self._metrics_debounce.setSingleShot(True)
        self._metrics_debounce.setInterval(150)
        self._metrics_debounce.timeout.connect(self._fire_debounced_recompute)
        self._build_ui()
        self._setup_shortcuts()
        # zone_mode is OF-specific (controls the 4x4 cell grid). Only honor
        # the saved app-config default for OF; everyone else stays on the
        # ZoneDrawer's own default ("center_zone") and never sees the grid.
        if getattr(getattr(self, "experiment", None), "key", None) == "open_field":
            self.zone_drawer.set_zone_mode(
                self.config.get("zone_mode", "center_zone")
            )
        self.zone_drawer.set_zone_colors(self._colors)
        # Apply global body-style default (set via launcher → Extra features).
        # Any per-tab/batch-group override loaded later still wins; this is
        # just the baseline so the first session matches the user's choice.
        try:
            gbs = self.config.get("body_style")
            if gbs is not None and hasattr(self, "combo_body_style"):
                i = self.combo_body_style.findData(gbs)
                if i >= 0:
                    self.combo_body_style.setCurrentIndex(i)
        except Exception as e:
            logger.warn(f"body_style init failed: {e}", source="ui")
        self._apply_simple_mode()

        last = self.config.get("last_video")
        if last and os.path.exists(last):
            QTimer.singleShot(0, lambda p=last: self._load_video_path(p))

    def update_config(self, config):
        self.config = config

    def _bgr(self, name):
        return _hex_to_bgr(self._colors.get(name, DEFAULT_COLORS.get(name, "#FFFFFF")))

    # ── Settings snapshot / apply (for per-video overrides) ──────────────

    def snapshot_settings(self) -> dict:
        zd = self.zone_drawer
        out = {
            "threshold":    self.spin_threshold.value(),
            "brightness":   self.slider_brightness.value(),
            "contrast":     self.slider_contrast.value(),
            "blur":         self.slider_blur.value(),
            "gamma":        self.slider_gamma.value(),
            "sharpen":      self.slider_sharpen.value(),
            "clahe":        self.spin_clahe.value(),
            "max_blob":     self.spin_max_blob.value(),
            # Saved as the combo's data value (float for proc_scale, string
            # key for model) — NOT the list index. Renaming a combo item no
            # longer silently corrupts saved configs. Legacy int values are
            # still accepted on read; see _apply_settings_body.
            "proc_scale":   self.combo_proc_scale.currentData(),
            "model":        self.combo_model.currentData() or "median",
            "model_params": {m: dict(p) for m, p in self._model_params.items()},
            "post_params":  dict(self._post_params),
            "body_style":   self.combo_body_style.currentData() or "dot",
            "ellipse":      self.chk_ellipse.isChecked(),
            "trail":        self.chk_trail.isChecked(),
            "trail_len":    self.spin_trail_len.value(),
            "trail_fade":   self.chk_trail_fade.isChecked(),
            "brush_radius": self.spin_brush.value(),
            "colors":       dict(self._colors),
            "overlay_alpha": self.overlay_alpha,
            "smooth":       self.spin_smooth.value(),
            "zone_mode":    (self.combo_zone_mode.currentData()
                             if hasattr(self, "combo_zone_mode") else "center_zone"),
            "cage_shape":   (self.combo_cage_shape.currentData()
                             if hasattr(self, "combo_cage_shape") else "rectangle"),
            "perspective":  (self.chk_perspective.isChecked()
                             if hasattr(self, "chk_perspective") else False),
            "fps_override": self.spin_fps_override.value(),
            "movement_thr": self.spin_movement_thr.value(),
            "bin_size":     self.spin_bin_size.value(),
            "trim_start":   self.spin_trim_start.value(),
            "trim_duration": self.spin_trim_duration.value(),
            "center_pct":   (self.spin_center_pct.value()
                             if hasattr(self, "spin_center_pct") else 25),
            "calib_mode":   (self._calib_mode()
                             if hasattr(self, "rb_calib_auto") else None),
            "calib_p1":     zd.calib_p1,
            "calib_p2":     zd.calib_p2,
            "calib_cm":     self.spin_cm.value(),
            "arena":        list(zd.arena) if zd.arena else None,
            # When perspective is on, zd.arena is the post-warp full-frame
            # quad, NOT the user's drawn polygon. Save the user's original
            # polygon separately so reload + batch tracking can rebuild
            # the homography.
            "original_arena": (
                list(self._original_arena)
                if (self._perspective_on and self._original_arena) else None
            ),
            "center_zone":  list(zd.center_zone) if zd.center_zone else None,
            "exclusion_mask": (zd.exclusion_mask.copy()
                               if zd.exclusion_mask is not None else None),
            # Generic per-tab keys live here. Experiment-specific keys
            # (OF cell categories / cage / arena-movement; Y-Maze arms,
            # hub, perspective) get injected below via contribute_to_snapshot.
            "cell_min_dwell_s": self._cell_min_dwell_s(),
            "frame_skip": int(self.spin_frame_skip.value()),
            "smooth_window": int(self.spin_smooth_window.value()) if hasattr(self, "spin_smooth_window") else 3,
            "enable_nose": (bool(self.chk_enable_nose.isChecked())
                            if hasattr(self, "chk_enable_nose") else False),
            "metadata": {
                "Animal ID": self.edit_meta_id.text(),
                "Group":     self.edit_meta_group.text(),
                "Sex":       self.combo_meta_sex.currentText(),
                "Date":      self.edit_meta_date.text(),
                "Trial":     self.edit_meta_trial.text(),
                "Notes":     self.edit_meta_notes.text(),
            },
        }
        # Let the experiment plugin inject its own keys + override defaults.
        # Y-Maze uses this to set s["arena"] = convex hull of arms and force
        # arena_auto_movement=False so tracking uses the user-defined arms
        # instead of the OF auto-from-movement default.
        exp = getattr(self, "experiment", None)
        if exp is not None and hasattr(exp, "contribute_to_snapshot"):
            try:
                exp.contribute_to_snapshot(self, out)
            except Exception as e:
                logger.warn(f"contribute_to_snapshot failed "
                            f"({getattr(exp, 'key', '?')}): {e}",
                            source="plugin")
        return out

    def apply_settings(self, s: dict):
        if not isinstance(s, dict):
            return
        # Block signals on widgets whose handlers mutate cross-video state or
        # touch disk while we're swapping in the new video's settings.
        # Some widgets are OF-only (perspective, zone-mode, cage-shape,
        # center-%); skip them when the experiment didn't build them.
        _candidate_block = [
            "chk_perspective", "combo_zone_mode", "combo_cage_shape",
            "combo_proc_scale", "combo_model", "combo_body_style",
            "combo_meta_sex", "spin_fps_override", "spin_movement_thr",
            "spin_bin_size", "spin_smooth", "spin_threshold",
            "spin_clahe", "spin_brush", "spin_trail_len",
            "slider_brightness", "slider_contrast", "slider_blur",
            "slider_gamma", "slider_sharpen", "spin_cm",
            "spin_center_pct", "spin_max_blob",
            "edit_meta_id", "edit_meta_group", "edit_meta_date",
            "edit_meta_trial", "edit_meta_notes",
        ]
        _block = [getattr(self, n) for n in _candidate_block if hasattr(self, n)]
        _prev_blocked = [w.blockSignals(True) for w in _block]
        try:
            self._apply_settings_body(s)
        finally:
            for w, prev in zip(_block, _prev_blocked):
                w.blockSignals(prev)
        # Refresh dependent UI now that signals are unblocked. Without this
        # the preview keeps showing the raw frame until the user nudges a
        # slider, since blockSignals suppressed the valueChanged → preview
        # cascade during the apply.
        self._update_calib_status()
        if hasattr(self, "_refresh_zones_label"):
            self._refresh_zones_label()
        if hasattr(self, "_update_run_button"):
            self._update_run_button()
        try:
            self._update_preview()
        except Exception as e:
            logger.warn(f"apply_settings update_preview: {e}", source="ui")

    def _apply_settings_body(self, s: dict):
        self.slider_brightness.setValue(s.get("brightness", 0))
        self.slider_contrast.setValue(s.get("contrast", 100))
        self.slider_blur.setValue(s.get("blur", 0))
        self.slider_gamma.setValue(s.get("gamma", 100))
        self.slider_sharpen.setValue(s.get("sharpen", 0))
        self.spin_clahe.setValue(s.get("clahe", 0))
        self.spin_threshold.setValue(s.get("threshold", 25))
        self.spin_max_blob.setValue(s.get("max_blob", 0))
        if "proc_scale" in s:
            v = _migrate_combo_value(s["proc_scale"], _LEGACY_PROC_SCALES, 1.0)
            idx = self.combo_proc_scale.findData(v)
            self.combo_proc_scale.setCurrentIndex(idx if idx >= 0 else 0)
        if "model" in s:
            v = _migrate_combo_value(s["model"], _LEGACY_MODEL_ORDER, "median")
            idx = self.combo_model.findData(v)
            self.combo_model.setCurrentIndex(idx if idx >= 0 else 0)
        if isinstance(s.get("model_params"), dict):
            for m, defaults in DEFAULT_MODEL_PARAMS.items():
                self._model_params[m] = {**defaults, **s["model_params"].get(m, {})}
        if isinstance(s.get("post_params"), dict):
            self._post_params = {**DEFAULT_POST_PARAMS, **s["post_params"]}
        if "body_style" in s:
            v = _migrate_combo_value(s["body_style"], _LEGACY_BODY_STYLES, "dot")
            idx = self.combo_body_style.findData(v)
            self.combo_body_style.setCurrentIndex(idx if idx >= 0 else 1)
        self.chk_ellipse.setChecked(s.get("ellipse", False))
        self.chk_trail.setChecked(s.get("trail", False))
        self.spin_trail_len.setValue(s.get("trail_len", 0))
        self.chk_trail_fade.setChecked(s.get("trail_fade", False))
        self.spin_brush.setValue(s.get("brush_radius", 20))
        if isinstance(s.get("colors"), dict):
            self._colors = {**DEFAULT_COLORS, **_upgrade_legacy_colors(dict(s["colors"]))}
        if "overlay_alpha" in s:
            self.overlay_alpha = int(s["overlay_alpha"])
        self.spin_smooth.setValue(s.get("smooth", 0))
        if "zone_mode" in s and hasattr(self, "combo_zone_mode"):
            i = self.combo_zone_mode.findData(s["zone_mode"])
            if i >= 0:
                self.combo_zone_mode.setCurrentIndex(i)
        if "cage_shape" in s and hasattr(self, "combo_cage_shape"):
            i = self.combo_cage_shape.findData(s["cage_shape"])
            if i >= 0:
                self.combo_cage_shape.setCurrentIndex(i)
        if "perspective" in s and hasattr(self, "chk_perspective"):
            self.chk_perspective.setChecked(bool(s["perspective"]))
        self.spin_fps_override.setValue(float(s.get("fps_override", 0.0)))
        self.spin_movement_thr.setValue(float(s.get("movement_thr", 0.0)))
        self.spin_bin_size.setValue(float(s.get("bin_size", 0.0)))
        self.spin_trim_start.setValue(float(s.get("trim_start", 0.0)))
        self.spin_trim_duration.setValue(float(s.get("trim_duration", 0.0)))
        if hasattr(self, "spin_center_pct"):
            mode_default = 25 if self.zone_drawer.zone_mode == "grid" else 50
            self.spin_center_pct.setValue(int(s.get("center_pct", mode_default)))
        zd = self.zone_drawer
        zd.calib_p1 = s.get("calib_p1")
        zd.calib_p2 = s.get("calib_p2")
        if "calib_cm" in s:
            self.spin_cm.setValue(float(s["calib_cm"]))
        # Y-Maze / EPM never use the OF arena polygon — keep zd.arena = None
        # so the base paintEvent doesn't draw the "Arena" outline + 4x4 grid +
        # cell numbers over the maze view.
        exp_key = getattr(getattr(self, "experiment", None), "key", None)
        if exp_key in ("y_maze", "epm"):
            zd.arena = None
        else:
            zd.arena = list(s["arena"]) if s.get("arena") else None
        # Legacy fallback: older snapshots used "center" key.
        _cz = s.get("center_zone", s.get("center"))
        zd.center_zone = list(_cz) if _cz else None
        mask = s.get("exclusion_mask")
        expected_shape = (zd._video_h, zd._video_w)
        if (mask is not None and getattr(mask, "shape", None) == expected_shape
                and zd._video_h > 1 and zd._video_w > 1):
            zd.exclusion_mask = mask.copy()
        elif zd._video_h > 1 and zd._video_w > 1:
            zd.exclusion_mask = np.zeros(expected_shape, dtype=np.uint8)
        else:
            zd.exclusion_mask = None
        zd._excl_cache = None
        zd.update()
        m = s.get("metadata") or {}
        self.edit_meta_id.setText(m.get("Animal ID", ""))
        self.edit_meta_group.setText(m.get("Group", ""))
        i = self.combo_meta_sex.findText(m.get("Sex", ""))
        if i >= 0:
            self.combo_meta_sex.setCurrentIndex(i)
        self.edit_meta_date.setText(m.get("Date", ""))
        self.edit_meta_trial.setText(m.get("Trial", ""))
        self.edit_meta_notes.setText(m.get("Notes", ""))
        # Per-video cell category labels + min-dwell.
        cats = s.get("cell_categories")
        if cats and hasattr(self, "set_cell_categories"):
            self.set_cell_categories(cats)
        # Accept both new (cell_min_dwell_s) and legacy (cell_min_dwell) keys
        # so saved video settings from earlier versions still load.
        v = s.get("cell_min_dwell_s", s.get("cell_min_dwell"))
        if v is not None:
            self.spin_min_dwell.setValue(float(v))
        if hasattr(self, "spin_cage_w") and s.get("cage_w_cm") is not None:
            self.spin_cage_w.setValue(float(s["cage_w_cm"]))
        if hasattr(self, "spin_cage_h") and s.get("cage_h_cm") is not None:
            self.spin_cage_h.setValue(float(s["cage_h_cm"]))
        self._arena_auto_movement = bool(s.get("arena_auto_movement", False))
        if hasattr(self, "spin_arena_pad_pct") and s.get("arena_pad_pct") is not None:
            self.spin_arena_pad_pct.setValue(float(s["arena_pad_pct"]))
        # Default to Off (1 = every frame) when the video has no saved value,
        # so a fresh video never inherits the previous video's skip setting.
        self.spin_frame_skip.setValue(int(s["frame_skip"])
                                      if s.get("frame_skip") is not None else 1)
        if hasattr(self, "spin_smooth_window"):
            self.spin_smooth_window.setValue(int(s["smooth_window"])
                                             if s.get("smooth_window") is not None
                                             else 1)   # Off when unsaved
        if hasattr(self, "chk_enable_nose"):
            # Per-video flag wins; missing snapshot → plugin default.
            if "enable_nose" in s:
                self.chk_enable_nose.setChecked(bool(s["enable_nose"]))
            else:
                exp = getattr(self, "experiment", None)
                default = (exp.default_enable_nose()
                           if exp is not None
                           and hasattr(exp, "default_enable_nose") else False)
                self.chk_enable_nose.setChecked(bool(default))
        # Restore the dropdown label from the per-video define-arena mode.
        self._arena_define_mode = s.get("arena_define_mode")
        if hasattr(self, "btn_define_arena"):
            label_map = {
                "manual":   "Manual — click 4 corners",
                "contrast": "Auto — from contrast (now)",
                "movement": "Auto — from movement (next run)",
            }
            label = label_map.get(self._arena_define_mode)
            self.btn_define_arena.setText(
                f"{label} ▾" if label else "Define arena ▾"
            )
        if hasattr(self, "_refresh_arena_mode_chip"):
            self._refresh_arena_mode_chip()
        # Restore calibration mode (radio). Suppress handler so the change
        # doesn't re-trigger save / recompute mid-apply.
        if hasattr(self, "rb_calib_auto"):
            self._suppress_calib_mode = True
            try:
                saved_mode = s.get("calib_mode")
                if saved_mode is None:
                    # Legacy snapshot: infer from drawn line, else default to auto.
                    if s.get("calib_p1") and s.get("calib_p2"):
                        saved_mode = "manual"
                    else:
                        saved_mode = "auto"
                if saved_mode == "manual":
                    self.rb_calib_manual.setChecked(True)
                elif saved_mode == "none":
                    self.rb_calib_none.setChecked(True)
                else:
                    self.rb_calib_auto.setChecked(True)
            finally:
                self._suppress_calib_mode = False
        if hasattr(self, "_refresh_cage_size_inputs"):
            self._refresh_cage_size_inputs()
        if hasattr(self, "_refresh_calib_mode_visibility"):
            self._refresh_calib_mode_visibility()
        # Drive perspective state manually (signal was blocked above). Must run
        # after arena is set so the homography uses this video's corners.
        want_persp = bool(s.get("perspective", False))
        # Prefer the explicitly saved original polygon; fall back to whatever
        # is currently in zd.arena (older snapshots without "original_arena").
        original = s.get("original_arena") or (
            list(zd.arena) if zd.arena else None
        )
        if want_persp and original:
            # Restore the user's drawn polygon as the arena before warping.
            zd.arena = list(original)
            self._original_arena = list(original)
            self._compute_homography()
            if self._H is not None:
                zd.arena = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
                zd.set_perspective_locked(True)
                self._perspective_on = True
                # Coordinate space becomes the warp target (matters for
                # square cage with non-square video).
                target = self._warp_target_size()
                if target:
                    self.video_w, self.video_h = target
            else:
                self._original_arena = None
                self._perspective_on = False
                zd.set_perspective_locked(False)
        else:
            self._original_arena = None
            self._H = None
            self._perspective_on = False
            zd.set_perspective_locked(False)

    # ── _open_corrections_popup lives in gui/output/corrections_mixin.py

    def _open_view_popup(self):
        """Show the overlay-options popup (body / ellipse / trail /
        smooth + dot colors + cell highlight controls)."""
        if self._view_popup is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("View options")
            dlg.setWindowFlags(dlg.windowFlags() | Qt.Tool)
            v = QVBoxLayout(dlg)
            v.setContentsMargins(10, 10, 10, 10)
            v.setSpacing(6)
            v.addWidget(self._body_style_widget)
            v.addWidget(self.chk_ellipse)
            v.addWidget(self._trail_row_widget)
            v.addWidget(self._smooth_row_widget)
            if hasattr(self, "_legend_widget"):
                sep = QFrame()
                sep.setFrameShape(QFrame.HLine)
                sep.setStyleSheet("color:#444;")
                v.addWidget(sep)
                v.addWidget(QLabel("Dot colors:"))
                v.addWidget(self._legend_widget)
            # Cell highlight section — OF-only; subclass provides builder.
            if hasattr(self, "_build_cell_highlight_controls"):
                sep2 = QFrame()
                sep2.setFrameShape(QFrame.HLine)
                sep2.setStyleSheet("color:#444;")
                v.addWidget(sep2)
                v.addWidget(QLabel("Cell highlight:"))
                v.addWidget(self._build_cell_highlight_controls())
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(dlg.close)
            v.addWidget(close_btn)
            self._view_popup = dlg
        # Position near the View button (top of the preview area).
        self._view_popup.show()
        self._view_popup.raise_()
        self._view_popup.activateWindow()


    def _on_fps_override_changed(self, val):
        if val > 0:
            self.fps = val
        else:
            self.fps = self._auto_fps if hasattr(self, "_auto_fps") and self._auto_fps else (self.fps or 30.0)
        if getattr(self, "tracking_results", None):
            self._recompute_metrics_and_views()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                if u.toLocalFile().lower().endswith((".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv")):
                    e.acceptProposedAction()
                    return
        e.ignore()

    def dragMoveEvent(self, e):
        self.dragEnterEvent(e)

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p and os.path.isfile(p):
                self._load_video_path(p)
                self._push_recent(p)
                e.acceptProposedAction()
                return

    def _movement_threshold(self) -> float:
        if hasattr(self, "spin_movement_thr"):
            return float(self.spin_movement_thr.value())
        return 0.0

    def _bin_size_s(self) -> float:
        if hasattr(self, "spin_bin_size"):
            return float(self.spin_bin_size.value())
        return 0.0

    def _trim_start_s(self) -> float:
        if hasattr(self, "spin_trim_start"):
            return float(self.spin_trim_start.value())
        return 0.0

    def _trim_duration_s(self) -> float:
        if hasattr(self, "spin_trim_duration"):
            return float(self.spin_trim_duration.value())
        return 0.0

    def _trim_start_frame(self) -> int:
        """Source-frame index where the trim window begins. Used to convert
        the scrub slider's source-frame value to a trim-relative index into
        `tracking_results` (which the tracker emits starting at 0)."""
        if not self.fps or self.fps <= 0:
            return 0
        return max(0, int(round(self._trim_start_s() * self.fps)))

    def _slider_to_results_idx(self, slider_val) -> int:
        """Map a slider value (source-frame coords) to its index in
        tracking_results. Clamps to a valid range."""
        if not self.tracking_results:
            return 0
        rel = int(slider_val) - self._trim_start_frame()
        return max(0, min(len(self.tracking_results) - 1, rel))

    def _fps_override(self) -> float:
        if hasattr(self, "spin_fps_override") and self.spin_fps_override.value() > 0:
            return float(self.spin_fps_override.value())
        return 0.0

    def _metadata(self) -> dict:
        meta = {}
        for key, attr in (("Animal ID", "edit_meta_id"),
                          ("Group", "edit_meta_group"),
                          ("Sex", "combo_meta_sex"),
                          ("Date", "edit_meta_date"),
                          ("Trial", "edit_meta_trial"),
                          ("Notes", "edit_meta_notes")):
            w = getattr(self, attr, None)
            if w is None:
                continue
            if hasattr(w, "currentText"):
                meta[key] = w.currentText()
            elif hasattr(w, "toPlainText"):
                meta[key] = w.toPlainText()
            else:
                meta[key] = w.text()
        return meta

    def _make_color_button(self, key, size=14):
        btn = QPushButton()
        btn.setFixedSize(size, size)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"background-color: {self._colors[key]}; border: 1px solid #555; border-radius: 2px;"
        )
        btn.setToolTip(f"Click to change {key} color")
        btn.clicked.connect(lambda _=False, k=key: self._pick_color(k))
        self._color_buttons[key] = btn
        return btn

    ZONE_COLOR_PRESETS = [
        "#E53935", "#FB8C00", "#FDD835", "#43A047", "#00ACC1",
        "#1E88E5", "#8E24AA", "#EC407A", "#FFFFFF", "#9E9E9E",
    ]

    def _open_zone_colors_dialog(self):
        self._open_colors_dialog(
            (("arena", "Arena"), ("center_zone", "Center Zone"), ("grid", "Grid")),
            "Zone Colors",
        )

    def _open_dot_colors_dialog(self):
        keys = (("body", "Body"),)
        self._open_colors_dialog(keys, "Dot Colors")

    def _open_colors_dialog(self, keys, title):
        backup = {k: self._colors[k] for k, _ in keys}

        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        main = QVBoxLayout(dlg)
        main.setSpacing(8)

        first_key = keys[0][0]
        current_key = [first_key]
        sel_buttons = {}

        def restyle():
            for kk, b in sel_buttons.items():
                border = "2px solid #FFF" if kk == current_key[0] else "1px solid #555"
                b.setStyleSheet(
                    f"QPushButton {{ background-color: {self._colors[kk]}; color: #000;"
                    f" border: {border}; border-radius: 3px; padding: 2px 6px; }}"
                )

        def apply(hex_c):
            self._apply_color_live(current_key[0], QColor(hex_c))
            restyle()

        def select(k):
            current_key[0] = k
            restyle()

        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("Edit:"))
        for key, name in keys:
            b = QPushButton(name)
            b.setFixedHeight(24)
            b.setFixedWidth(80)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: select(k))
            sel_buttons[key] = b
            sel_row.addWidget(b)
        sel_row.addStretch()
        main.addLayout(sel_row)

        swatch_grid = QHBoxLayout()
        swatch_grid.setSpacing(4)
        swatch_grid.addWidget(QLabel("Color:"))
        for hex_c in self.ZONE_COLOR_PRESETS:
            sw = QPushButton()
            sw.setFixedSize(22, 22)
            sw.setCursor(Qt.PointingHandCursor)
            sw.setStyleSheet(
                f"background-color: {hex_c}; border: 1px solid #555; border-radius: 3px;"
            )
            sw.setToolTip(hex_c)
            sw.clicked.connect(lambda _=False, c=hex_c: apply(c))
            swatch_grid.addWidget(sw)
        more_btn = QPushButton("More…")
        more_btn.setFixedHeight(22)
        more_btn.setFixedWidth(60)

        def open_full_picker():
            initial = QColor(self._colors[current_key[0]])
            dlg2 = QColorDialog(initial, dlg)
            dlg2.setOption(QColorDialog.DontUseNativeDialog, True)
            dlg2.currentColorChanged.connect(lambda c: apply(c.name()) if c.isValid() else None)
            if dlg2.exec_() != QColorDialog.Accepted:
                apply(initial.name())
        more_btn.clicked.connect(open_full_picker)
        swatch_grid.addWidget(more_btn)
        swatch_grid.addStretch()
        main.addLayout(swatch_grid)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.setFixedHeight(24)
        ok_btn.setFixedWidth(70)
        cancel_btn.setFixedHeight(24)
        cancel_btn.setFixedWidth(70)
        ok_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        main.addLayout(btn_row)

        select(first_key)
        accepted = dlg.exec_() == QDialog.Accepted
        if not accepted:
            for k, hex_c in backup.items():
                self._apply_color_live(k, QColor(hex_c))
        self.config["colors"] = dict(self._colors)
        win = self.window()
        if hasattr(win, "_save_config"):
            win._save_config()

    def _pick_color(self, key):
        backup_color = self._colors[key]
        backup_alpha = self.overlay_alpha if key == "detection" else None
        initial = QColor(backup_color)
        if key == "detection":
            initial.setAlpha(int(self.overlay_alpha * 255 / 100))
        dlg = QColorDialog(initial, self)
        dlg.setWindowTitle(f"Pick {key} color")
        if key == "detection":
            dlg.setOption(QColorDialog.ShowAlphaChannel, True)
        dlg.currentColorChanged.connect(lambda c, k=key: self._apply_color_live(k, c))
        accepted = dlg.exec_() == QColorDialog.Accepted
        if not accepted:
            restored = QColor(backup_color)
            if backup_alpha is not None:
                restored.setAlpha(int(backup_alpha * 255 / 100))
            self._apply_color_live(key, restored)
        self.config["colors"] = dict(self._colors)
        if key == "detection":
            self.config["overlay_alpha"] = self.overlay_alpha
        win = self.window()
        if hasattr(win, "_save_config"):
            win._save_config()

    def _apply_color_live(self, key, qcolor):
        if not qcolor.isValid():
            return
        hex_str = qcolor.name()
        self._colors[key] = hex_str
        if key == "detection":
            self.overlay_alpha = int(qcolor.alpha() * 100 / 255)
        btn = self._color_buttons.get(key)
        if btn:
            btn.setStyleSheet(
                f"background-color: {hex_str}; border: 1px solid #555; border-radius: 2px;"
            )
        if key in ("arena", "center_zone", "grid"):
            self.zone_drawer.set_zone_colors(self._colors)
        elif key == "detection":
            if self._preview_active:
                self._update_preview()
            else:
                self._render_current_frame()
        else:
            if self._preview_active:
                self._update_preview()
            else:
                self._render_current_frame()

    PARAM_SCHEMA = {
        # Median
        "bg_sample_count":              ("int",   30, 500, 1, "frames"),
        # Common BG-subtractor
        "history":                      ("int",   50, 5000, 1, "frames"),
        "learningRate":                 ("float", 0.0, 1.0, 0.001, ""),
        "detectShadows":                ("bool",),
        "shadowThreshold":              ("float", 0.0, 1.0, 0.01, ""),
        "shadowValue":                  ("int",   0, 255, 1, ""),
        # MOG2
        "varThreshold":                 ("float", 1.0, 500.0, 0.5, ""),
        "nMixtures":                    ("int",   1, 20, 1, ""),
        "backgroundRatio":              ("float", 0.0, 1.0, 0.01, ""),
        "varThresholdGen":              ("float", 1.0, 200.0, 0.5, ""),
        "complexityReductionThreshold": ("float", 0.0, 1.0, 0.001, ""),
        "varInit":                      ("float", 1.0, 200.0, 0.5, ""),
        "varMin":                       ("float", 1.0, 200.0, 0.5, ""),
        "varMax":                       ("float", 1.0, 500.0, 0.5, ""),
        # KNN
        "dist2Threshold":               ("float", 1.0, 5000.0, 1.0, ""),
        "kNNSamples":                   ("int",   1, 50, 1, ""),
        "nSamples":                     ("int",   1, 200, 1, ""),
        # CNT
        "minPixelStability":            ("int",   1, 1000, 1, "frames"),
        "maxPixelStability":            ("int",   1, 100000, 1, "frames"),
        "useHistory":                   ("bool",),
        "isParallel":                   ("bool",),
        # GSOC/LSBP common
        "mc":                           ("choice", ["None", "LK"]),
        "replaceRate":                  ("float", 0.0001, 1.0, 0.0001, ""),
        "propagationRate":              ("float", 0.0001, 1.0, 0.0001, ""),
        "hitsThreshold":                ("int",   1, 200, 1, ""),
        "alpha":                        ("float", 0.0, 1.0, 0.001, ""),
        "beta":                         ("float", 0.0, 1.0, 0.0001, ""),
        "blinkingSupressionDecay":      ("float", 0.0, 1.0, 0.001, ""),
        "blinkingSupressionMultiplier": ("float", 0.0, 1.0, 0.001, ""),
        "noiseRemovalThresholdFacBG":   ("float", 0.0, 1.0, 0.0001, ""),
        "noiseRemovalThresholdFacFG":   ("float", 0.0, 1.0, 0.0001, ""),
        # LSBP
        "LSBPRadius":                   ("int",   1, 100, 1, ""),
        "Tlower":                       ("float", 0.0, 100.0, 0.1, ""),
        "Tupper":                       ("float", 0.0, 100.0, 0.1, ""),
        "Tinc":                         ("float", 0.0, 10.0, 0.1, ""),
        "Tdec":                         ("float", 0.0, 10.0, 0.01, ""),
        "Rscale":                       ("float", 0.0, 100.0, 0.5, ""),
        "Rincdec":                      ("float", 0.0, 1.0, 0.001, ""),
        "LSBPthreshold":                ("int",   1, 100, 1, ""),
        "minCount":                     ("int",   1, 50, 1, ""),
        # Frame Diff
        "diff_threshold":               ("int",   1, 255, 1, ""),
        "use_running_avg":              ("bool",),
        "running_avg_alpha":            ("float", 0.001, 1.0, 0.001, ""),
        # HSV
        "channel":                      ("choice", ["H", "S", "V"]),
        "mode":                         ("choice", ["otsu", "manual"]),
        "manual_threshold":             ("int",   0, 255, 1, ""),
        "invert":                       ("bool",),
        # Post-process
        "min_blob_area":                ("int",   1, 10000, 1, "px"),
        "morph_kernel_w":               ("int",   0, 50, 1, "px (0=auto)"),
        "morph_kernel_h":               ("int",   0, 50, 1, "px (0=auto)"),
    }

    def _update_model_tuning_button(self):
        if not hasattr(self, "btn_model_tuning"):
            return
        self.btn_model_tuning.setEnabled(True)

    def _make_param_widget(self, name, value):
        spec = self.PARAM_SCHEMA.get(name)
        if spec is None:
            return None, None
        kind = spec[0]
        if kind == "int":
            _, lo, hi, step, suffix = spec
            sb = QSpinBox()
            sb.setRange(int(lo), int(hi))
            sb.setSingleStep(int(step))
            if suffix:
                sb.setSuffix(f" {suffix}")
            sb.setValue(int(value))
            return sb, lambda w=sb: w.value()
        if kind == "float":
            _, lo, hi, step, suffix = spec
            sb = QDoubleSpinBox()
            sb.setRange(float(lo), float(hi))
            sb.setSingleStep(float(step))
            decimals = max(0, -int(round(np.log10(step)))) if step < 1 else 2
            sb.setDecimals(decimals)
            if suffix:
                sb.setSuffix(f" {suffix}")
            sb.setValue(float(value))
            return sb, lambda w=sb: w.value()
        if kind == "bool":
            cb = QCheckBox()
            cb.setChecked(bool(value))
            return cb, lambda w=cb: w.isChecked()
        if kind == "choice":
            _, opts = spec
            cb = QComboBox()
            for o in opts:
                cb.addItem(str(o), o)
            i = cb.findData(value)
            if i < 0:
                i = 0
            cb.setCurrentIndex(i)
            return cb, lambda w=cb: w.currentData()
        return None, None

    def _open_model_tuning_dialog(self):
        model = self.combo_model.currentData()
        params = self._model_params[model]
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Model Tuning — {self.combo_model.currentText()}")
        outer = QVBoxLayout(dlg)
        outer.setSpacing(6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        v = QVBoxLayout(host)
        v.setSpacing(6)

        getters = {}

        def add_section(title, items, store):
            lbl = QLabel(f"<b>{title}</b>")
            lbl.setStyleSheet("font-size:11px; color:#ddd;")
            v.addWidget(lbl)
            for key, val in items:
                w, getter = self._make_param_widget(key, val)
                if w is None:
                    continue
                row = QHBoxLayout()
                k_lbl = QLabel(key + ":")
                k_lbl.setFixedWidth(180)
                k_lbl.setStyleSheet("font-size:11px;")
                row.addWidget(k_lbl)
                row.addWidget(w, 1)
                v.addLayout(row)
                getters[(store, key)] = getter
            v.addWidget(self._sep())

        add_section(f"Model — {model}", list(params.items()), "model")
        add_section("Post-process", list(self._post_params.items()), "post")

        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        reset_btn = QPushButton("Reset defaults")
        reset_btn.setFixedHeight(24)
        reset_btn.setFixedWidth(110)
        ok_btn = QPushButton("OK")
        ok_btn.setFixedHeight(24)
        ok_btn.setFixedWidth(70)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(24)
        cancel_btn.setFixedWidth(70)

        def do_reset():
            self._model_params[model] = dict(DEFAULT_MODEL_PARAMS[model])
            self._post_params = dict(DEFAULT_POST_PARAMS)
            dlg.accept()
            self._save_tuning_to_config()
            self._open_model_tuning_dialog()

        reset_btn.clicked.connect(do_reset)
        ok_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        outer.addLayout(btn_row)

        dlg.resize(440, 520)
        if dlg.exec_() == QDialog.Accepted:
            for (store, key), getter in getters.items():
                if store == "model":
                    self._model_params[model][key] = getter()
                else:
                    self._post_params[key] = getter()
            self._save_tuning_to_config()

    def _save_tuning_to_config(self):
        self.config["model_params"] = {m: dict(p) for m, p in self._model_params.items()}
        self.config["post_params"] = dict(self._post_params)
        win = self.window()
        if hasattr(win, "_save_config"):
            win._save_config()

    # ── Simple / Full view ────────────────────────────────────────────────

    def set_simple_mode(self, simple: bool):
        """Toggle between Simple (essentials only) and Full views.
        Persists to config and flips visibility of every widget marked
        advanced during build."""
        self._simple_mode = bool(simple)
        self.config["simple_mode"] = self._simple_mode
        win = self.window()
        if hasattr(win, "_save_config"):
            win._save_config()
        self._apply_simple_mode()

    def _apply_simple_mode(self):
        show = not self._simple_mode  # advanced shown only in Full
        for w in getattr(self, "_advanced_widgets", []):
            try:
                w.setVisible(show)
            except RuntimeError:
                # Widget already deleted by Qt; drop silently.
                pass

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidget(self._build_controls())
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFixedWidth(312)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll, 0)

        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self._build_preview_tab(), "Video Preview")
        self._graph_widget = self._build_graph_tab()
        self.right_tabs.addTab(self._build_excel_tab(), "Excel Output")
        root.addWidget(self.right_tabs, 1)

    def _build_view_popup_widgets(self):
        """Construct the overlay widgets shown inside the View ▾ popup
        (body marker, ellipse, trail, smooth). They live as orphans until
        `_open_view_popup` reparents them into the dialog. Created here —
        under the preview-tab section — because they belong with the
        preview / view feature, not with tracker analysis."""
        self._body_style_widget = QWidget()
        body_row = QHBoxLayout(self._body_style_widget)
        body_row.setContentsMargins(0, 0, 0, 0)
        body_row.addWidget(QLabel("Body marker:"))
        self.combo_body_style = QComboBox()
        self.combo_body_style.addItem("Off", "off")
        self.combo_body_style.addItem("Dot (center only)", "dot")
        self.combo_body_style.addItem("Center + Nose + Tail", "ends")
        self.combo_body_style.setCurrentIndex(1)
        self.combo_body_style.setFixedHeight(24)
        self.combo_body_style.currentIndexChanged.connect(
            lambda: self._on_scrub(self.slider_scrub.value())
        )
        body_row.addWidget(self.combo_body_style)

        def _overlay_chk(label):
            c = QCheckBox(label)
            c.setStyleSheet("font-size:11px;")
            c.toggled.connect(lambda: self._on_scrub(self.slider_scrub.value()))
            return c

        self.chk_ellipse = _overlay_chk("Bounding ellipse")
        self.chk_trail   = _overlay_chk("Trail:")

        self._trail_row_widget = QWidget()
        trail_row = QHBoxLayout(self._trail_row_widget)
        trail_row.setContentsMargins(0, 0, 0, 0)
        trail_row.addWidget(self.chk_trail)
        self.spin_trail_len = QSpinBox()
        self.spin_trail_len.setRange(0, 100000)
        self.spin_trail_len.setValue(0)  # "All frames" by default
        self.spin_trail_len.setSuffix(" frames")
        self.spin_trail_len.setSpecialValueText("All frames")
        self.spin_trail_len.setFixedWidth(95)
        self.spin_trail_len.setFixedHeight(24)
        self.spin_trail_len.setToolTip("Trail length in frames. Set to 0 for full path.")
        self.spin_trail_len.valueChanged.connect(
            lambda: self._on_scrub(self.slider_scrub.value())
        )
        trail_row.addWidget(self.spin_trail_len)
        self.chk_trail_fade = QCheckBox("Fade")
        self.chk_trail_fade.setChecked(False)
        self.chk_trail_fade.setToolTip(
            "On: older trail segments dimmer/thinner.\n"
            "Off (default): solid body-color trail throughout."
        )
        self.chk_trail_fade.toggled.connect(
            lambda: self._on_scrub(self.slider_scrub.value())
        )
        trail_row.addWidget(self.chk_trail_fade)

        self._smooth_row_widget = QWidget()
        smooth_row = QHBoxLayout(self._smooth_row_widget)
        smooth_row.setContentsMargins(0, 0, 0, 0)
        smooth_row.addWidget(QLabel("Smooth path:"))
        self.spin_smooth = QSpinBox()
        self.spin_smooth.setRange(0, 30)
        self.spin_smooth.setValue(0)
        self.spin_smooth.setSuffix(" frames")
        self.spin_smooth.setSpecialValueText("Off")
        self.spin_smooth.setFixedWidth(85)
        self.spin_smooth.setFixedHeight(24)
        self.spin_smooth.setToolTip(
            "Moving-average window over the body-center track.\n"
            "Reduces frame-to-frame jitter. 0 = off."
        )
        self.spin_smooth.valueChanged.connect(self._on_smooth_changed)
        smooth_row.addWidget(self.spin_smooth)

    def _build_preview_tab(self):
        # Build the View popup's overlay widgets first so they're ready
        # before the user clicks View ▾.
        self._build_view_popup_widgets()

        w = QWidget()
        vlay = QVBoxLayout(w)
        vlay.setContentsMargins(0, 0, 0, 4)
        vlay.setSpacing(4)

        self.zone_drawer = ZoneDrawer()
        self.zone_drawer.zones_changed.connect(self._on_zones_changed)
        self.zone_drawer.exclusion_changed.connect(self._on_exclusion_changed)
        self.zone_drawer.point_clicked.connect(self._on_correction_click)
        vlay.addWidget(self.zone_drawer, 1)

        # Manual correction toolbar — collapsed into a single launcher that
        # opens a movable popup (so the user can dock it next to the video).
        self._fix_widget = QWidget()
        fix_row = QHBoxLayout(self._fix_widget)
        fix_row.setContentsMargins(6, 0, 6, 0)
        fix_row.setSpacing(6)

        # Create the correction buttons as orphans; they get re-parented into
        # the popup the first time it's opened.
        self.btn_fix = QPushButton("✎  Fix Position")
        self.btn_fix.setFixedHeight(26)
        self.btn_fix.setToolTip(
            "Fix Position — scrub to a frame, then click on the video to "
            "override the tracked position"
        )
        self.btn_fix.setCheckable(True)
        self.btn_fix.setEnabled(False)
        self.btn_fix.toggled.connect(self._on_fix_toggled)

        self.btn_clear_fixes = QPushButton("✕  Clear all fixes")
        self.btn_clear_fixes.setFixedHeight(26)
        self.btn_clear_fixes.setToolTip("Wipe every manual override")
        self.btn_clear_fixes.setEnabled(False)
        self.btn_clear_fixes.clicked.connect(self._clear_fixes)

        self.btn_next_miss = QPushButton("⏭  Next miss")
        self.btn_next_miss.setFixedHeight(26)
        self.btn_next_miss.setToolTip("Jump scrubber to next frame with no detection")
        self.btn_next_miss.setEnabled(False)
        self.btn_next_miss.clicked.connect(self._jump_next_miss)

        self.btn_interpolate = QPushButton("↔  Interpolate")
        self.btn_interpolate.setFixedHeight(26)
        self.btn_interpolate.setToolTip(
            "Linearly fill detection gaps between valid frames"
        )
        self.btn_interpolate.setEnabled(False)
        self.btn_interpolate.clicked.connect(self._interpolate_gaps)

        # Corrections popup is launched from the main menu bar (View →
        # Corrections…); no button under the video.
        self._corrections_popup = None  # lazy

        # "View" button — opens a popup with overlay options
        # (body marker / ellipse / trail / smooth).
        self.btn_view_popup = QPushButton("View ▾")
        self.btn_view_popup.setFixedHeight(26)
        self.btn_view_popup.setToolTip(
            "Overlay options: body marker, ellipse, trail, smooth"
        )
        self.btn_view_popup.clicked.connect(self._open_view_popup)
        self._view_popup = None  # lazy

        # Backwards-compat: some code paths still reference _adv_fix_widget.
        # It's now a no-op invisible container.
        self._adv_fix_widget = QWidget()
        self._adv_fix_widget.setVisible(False)
        # _fix_widget (the legacy launcher row container) is kept for
        # backwards-compat with Simple-mode logic but is no longer visible.
        self._fix_widget.setVisible(False)

        scrub_row = QHBoxLayout()
        scrub_row.setContentsMargins(6, 0, 6, 0)
        scrub_row.setSpacing(4)
        self.btn_step_prev = self._btn("◀", width=24)
        self.btn_step_prev.setEnabled(False)
        self.btn_step_prev.clicked.connect(
            lambda: self.slider_scrub.setValue(max(0, self.slider_scrub.value() - 1))
        )
        self.slider_scrub = QSlider(Qt.Horizontal)
        self.slider_scrub.setMinimum(0)
        self.slider_scrub.setMaximum(0)
        self.slider_scrub.setEnabled(False)
        self.slider_scrub.setToolTip(
            "Shortcuts:\n"
            "← / →  step 1 frame\n"
            "Shift+← / →  step 10\n"
            "Ctrl+← / →  step 100\n"
            "Home / End  first / last\n"
            "N  next missed frame\n"
            "D  toggle Preview Detection\n"
            "E  toggle View Effects"
        )
        self.slider_scrub.valueChanged.connect(self._on_scrub)
        self.btn_step_next = self._btn("▶", width=24)
        self.btn_step_next.setEnabled(False)
        self.btn_step_next.clicked.connect(
            lambda: self.slider_scrub.setValue(min(self.slider_scrub.maximum(), self.slider_scrub.value() + 1))
        )
        scrub_row.addWidget(self.btn_step_prev)
        scrub_row.addWidget(self.slider_scrub, 1)
        scrub_row.addWidget(self.btn_step_next)
        vlay.addLayout(scrub_row)

        # Footer: centered time/duration label, with a small View ▾ button
        # pinned to the right.
        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(6, 0, 6, 0)
        footer_row.setSpacing(4)
        self.lbl_scrub = QLabel("—")
        self.lbl_scrub.setAlignment(Qt.AlignCenter)
        self.lbl_scrub.setStyleSheet("color:#888; font-size:11px;")
        # Shrink the View button to a compact size on the right.
        self.btn_view_popup.setFixedSize(70, 22)
        self.btn_view_popup.setText("View ▾")
        footer_row.addStretch(1)
        footer_row.addWidget(self.lbl_scrub)
        footer_row.addStretch(1)
        footer_row.addWidget(self.btn_view_popup)
        vlay.addLayout(footer_row)

        # Overlay controls (body style / ellipse / trail / smooth)
        # now live in the configuration pane only.

        # Legend / dot-color controls live in the View popup, not under the
        # video. Built here so the widget exists; the popup re-parents it.
        self._legend_widget = self._build_legend()
        return w

    def _build_legend(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(6, 0, 6, 2)
        h.setSpacing(4)
        def lbl(text, css="color:#aaa; font-size:10px;"):
            l = QLabel(text)
            l.setStyleSheet(css)
            return l
        h.addWidget(lbl("<b>Dots:</b>", "color:#ccc; font-size:10px;"))
        self.btn_dot_colors = QPushButton("Colors")
        self.btn_dot_colors.setFixedHeight(20)
        self.btn_dot_colors.setFixedWidth(60)
        self.btn_dot_colors.setCursor(Qt.PointingHandCursor)
        self.btn_dot_colors.setToolTip("Pick the body-marker color")
        self.btn_dot_colors.clicked.connect(self._open_dot_colors_dialog)
        h.addWidget(self.btn_dot_colors)
        h.addSpacing(8)
        h.addWidget(lbl("<b>Status:</b>", "color:#ccc; font-size:10px;"))
        h.addWidget(lbl("<span style='color:#FFFF00'>■</span> Corrected"))
        h.addSpacing(4)
        h.addWidget(lbl("<span style='color:#FF64C8'>■</span> Interpolated"))
        h.addStretch()
        return w

    def _build_graph_tab(self):
        w = QWidget()
        vlay = QVBoxLayout(w)
        vlay.setContentsMargins(8, 8, 8, 8)
        vlay.setSpacing(6)

        self._graph_selector_row = QHBoxLayout()
        self._combo_graph = QComboBox()
        self._combo_graph.setFixedHeight(24)
        self._combo_graph.currentIndexChanged.connect(self._on_graph_select)
        self._graph_selector_row.addWidget(QLabel("Show:"))
        self._graph_selector_row.addWidget(self._combo_graph)
        self._graph_selector_row.addStretch()
        selector_widget = QWidget()
        selector_widget.setLayout(self._graph_selector_row)
        # Customize Graphs lives in the View menu now (View → Customize graphs…).
        selector_widget.setVisible(True)
        self._graph_selector_widget = selector_widget
        vlay.addWidget(selector_widget)

        self.lbl_graph_hint = QLabel("Run tracking first to see graphical output.")
        self.lbl_graph_hint.setAlignment(Qt.AlignCenter)
        self.lbl_graph_hint.setStyleSheet("color:#888; font-size:12px;")
        vlay.addWidget(self.lbl_graph_hint)

        self._graph_scroll = QScrollArea()
        self._graph_scroll.setWidgetResizable(True)
        self._graph_scroll.setFrameShape(QFrame.NoFrame)
        self._graph_scroll.setVisible(False)
        self._graph_lbl = _FitLabel()
        self._graph_scroll.setWidget(self._graph_lbl)
        # Right-click → Save as SVG / PDF / PNG.
        self._graph_lbl.setContextMenuPolicy(Qt.CustomContextMenu)
        self._graph_lbl.customContextMenuRequested.connect(
            lambda _pos: self._export_current_graph_dialog()
        )
        self._graph_lbl.setToolTip("Right-click to export as SVG / PDF / PNG.")
        vlay.addWidget(self._graph_scroll, 1)
        # Spacer to keep selector pinned to top when scroll is hidden.
        vlay.addStretch(0)

        self._graph_pixmaps = {}
        return w

    # Preset that tags the standard 4×4 layout: corners, edges (perimeter
    # non-corner), middle (inner 2×2).

    def _build_excel_tab(self):
        w = QWidget()
        vlay = QVBoxLayout(w)
        vlay.setContentsMargins(4, 4, 4, 4)
        vlay.setSpacing(4)

        # Metric toolbar: Move threshold + Time bin. Both recompute live —
        # they don't change tracked frames, only metric output. Wrapped so
        # the toolbar is hidden in Simple mode.
        metric_widget = QWidget()
        metric_row = QHBoxLayout(metric_widget)
        metric_row.setContentsMargins(0, 0, 0, 0)
        metric_row.setSpacing(6)
        metric_row.addWidget(QLabel("Move threshold:"))
        self.spin_movement_thr = QDoubleSpinBox()
        self.spin_movement_thr.setRange(0.0, 100.0)
        self.spin_movement_thr.setDecimals(2)
        self.spin_movement_thr.setSingleStep(0.1)
        self.spin_movement_thr.setValue(0.0)
        # Suffix is set to cm/s or px/s depending on calibration state.
        # _refresh_move_threshold_suffix() keeps it in sync.
        self.spin_movement_thr.setSuffix(" cm/s")
        self.spin_movement_thr.setSpecialValueText("Off")
        self.spin_movement_thr.setFixedWidth(105)
        self.spin_movement_thr.setFixedHeight(24)
        self.spin_movement_thr.setToolTip(
            "Speed below this counts as immobile.\n"
            "Units track calibration: cm/s if scale-bar is drawn, else px/s."
            "\n0 = off (every frame counts as moving)."
        )
        # Move threshold affects: metrics dict + bin_df (via _bin_metrics).
        # Graphs affected: Habituation only (reads bin_df).
        self.spin_movement_thr.valueChanged.connect(
            lambda _: self._schedule_narrow_recompute({"Habituation"})
        )
        metric_row.addWidget(self.spin_movement_thr)
        # Sync suffix once at build; later calls happen on each recompute.
        try:
            self._refresh_move_threshold_suffix()
        except Exception:
            pass

        metric_row.addSpacing(12)
        metric_row.addWidget(QLabel("Time bin:"))
        self.spin_bin_size = QDoubleSpinBox()
        self.spin_bin_size.setRange(0.0, 3600.0)
        self.spin_bin_size.setDecimals(1)
        self.spin_bin_size.setSingleStep(30.0)
        self.spin_bin_size.setValue(0.0)
        self.spin_bin_size.setSuffix(" s")
        self.spin_bin_size.setSpecialValueText("Off")
        self.spin_bin_size.setFixedWidth(95)
        self.spin_bin_size.setFixedHeight(24)
        self.spin_bin_size.setToolTip(
            "Bin size for per-bin metrics. 0 = off (no bin breakdown).\n"
            "Common: 60 (1 min), 300 (5 min)."
        )
        # Time bin affects: bin_df + Habituation slope / first-bin summary
        # metrics. Graphs affected: Habituation only.
        self.spin_bin_size.valueChanged.connect(
            lambda _: self._schedule_narrow_recompute({"Habituation"})
        )
        metric_row.addWidget(self.spin_bin_size)
        metric_row.addStretch()
        vlay.addWidget(metric_widget)
        self._advanced_widgets.append(metric_widget)

        # Annotated-video export widgets — created here as headless attrs;
        # the batch tab's Export tab reparents them.
        self._export_video_thread = None

        # Centered hint above tabs — used to be the only thing shown before
        # tracking; now demoted to invisible by default since each data tab
        # carries its own placeholder.
        self.lbl_excel_hint = QLabel("")
        self.lbl_excel_hint.setVisible(False)

        self._excel_tabs = QTabWidget()

        # ── Summary tab: placeholder until tracking populates the table.
        summary_wrap = QWidget()
        sv = QVBoxLayout(summary_wrap)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(0)
        self.lbl_summary_placeholder = QLabel(
            "Run tracking first to see the data output."
        )
        self.lbl_summary_placeholder.setAlignment(Qt.AlignCenter)
        self.lbl_summary_placeholder.setStyleSheet("color:#888; font-size:12px;")
        sv.addWidget(self.lbl_summary_placeholder, 1)
        from gui.table_copy import enable_excel_copy
        self._table_summary = QTableWidget()
        self._table_summary.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table_summary.setColumnCount(2)
        self._table_summary.setHorizontalHeaderLabels(["Metric", "Value"])
        self._table_summary.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table_summary.setVisible(False)
        enable_excel_copy(self._table_summary)
        sv.addWidget(self._table_summary, 1)
        self._excel_tabs.addTab(summary_wrap, "Summary")

        # ── Raw Data tab: placeholder until tracking populates the table.
        raw_wrap = QWidget()
        rv = QVBoxLayout(raw_wrap)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        self.lbl_raw_placeholder = QLabel(
            "Run tracking first to see the data output."
        )
        self.lbl_raw_placeholder.setAlignment(Qt.AlignCenter)
        self.lbl_raw_placeholder.setStyleSheet("color:#888; font-size:12px;")
        rv.addWidget(self.lbl_raw_placeholder, 1)
        self._table_raw = QTableWidget()
        self._table_raw.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table_raw.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table_raw.setVisible(False)
        enable_excel_copy(self._table_raw)
        rv.addWidget(self._table_raw, 1)
        self._excel_tabs.addTab(raw_wrap, "Raw Data")

        self._excel_tabs.addTab(self._graph_widget, "Graphs")
        # Tracking Issues — glitch detector + table + mini map + actions.
        self._excel_tabs.addTab(self._build_tracking_issues_tab(),
                                "Tracking Issues")
        # Cell-Info tab is OF-specific (4×4 grid region labeling). YMazeTab
        # inherits the OF mixin so the method exists, but the tab is
        # irrelevant for Y-Maze — gate on experiment key.
        exp = getattr(self, "experiment", None)
        if (hasattr(self, "_build_cell_info_tab")
                and exp is not None and exp.key == "open_field"):
            self._excel_tabs.addTab(self._build_cell_info_tab(), "Cell Info")

        # Video Config tab — mirrors the Excel "Video Config" sheet.
        vc_wrap = QWidget()
        vcv = QVBoxLayout(vc_wrap)
        vcv.setContentsMargins(0, 0, 0, 0)
        vcv.setSpacing(0)
        self._table_video_config = QTableWidget()
        self._table_video_config.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table_video_config.setColumnCount(2)
        self._table_video_config.setHorizontalHeaderLabels(["Setting", "Value"])
        self._table_video_config.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table_video_config.verticalHeader().setVisible(False)
        enable_excel_copy(self._table_video_config)
        vcv.addWidget(self._table_video_config, 1)
        self._excel_tabs.addTab(vc_wrap, "Video Config")

        vlay.addWidget(self._excel_tabs, 1)

        self.lbl_excel_note = QLabel("")
        self.lbl_excel_note.setStyleSheet("color:#888; font-size:10px;")
        self.lbl_excel_note.setVisible(False)
        vlay.addWidget(self.lbl_excel_note)

        vlay.addWidget(self._build_export_bar())
        return w

    def _build_controls(self):
        panel = QFrame()
        panel.setMinimumWidth(280)
        panel.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self._step_source())
        layout.addWidget(self._step_geometry())
        layout.addWidget(self._step_scale())
        layout.addWidget(self._step_detection())
        layout.addWidget(self._step_analysis())
        layout.addStretch()
        return panel

    def _step_source(self):
        from gui.steps.source_step import build_source_step
        return build_source_step(self)

    def _step_geometry(self):
        # Dispatch through the experiment plugin so subclasses (Y-Maze) can
        # swap the whole geometry pane without editing this class.
        return self.experiment.build_geometry_step(self)

    def _step_scale(self):
        from gui.steps.scale_step import build_scale_step
        return build_scale_step(self)

    def _step_detection(self):
        from gui.steps.detection_step import build_detection_step
        return build_detection_step(self)

    def _step_analysis(self):
        from gui.steps.analysis_step import build_analysis_step
        return build_analysis_step(self)

    def _build_export_bar(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(4, 4, 4, 4)
        h.setSpacing(8)
        self.btn_export = self._btn("Export to Excel", width=130)
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export)
        self.lbl_export = QLabel("")
        self.lbl_export.setWordWrap(True)
        self.lbl_export.setStyleSheet("color:#888; font-size:11px;")
        h.addWidget(self.btn_export)
        h.addWidget(self.lbl_export, 1)
        return w

    # ── Step 1 ────────────────────────────────────────────────────────────

    def _push_recent(self, path):
        recents = list(self.config.get("recent_videos", []))
        recents = [p for p in recents if p != path and os.path.exists(p)]
        recents.insert(0, path)
        recents = recents[:2]
        self.config["recent_videos"] = recents
        self.config["last_video"] = path
        win = self.window()
        if hasattr(win, "_save_config"):
            win._save_config()
        self._refresh_recent_buttons()

    def _refresh_recent_buttons(self):
        recents = self.config.get("recent_videos", []) if hasattr(self, "config") else []
        for i, btn in enumerate(self._recent_btns):
            if i < len(recents):
                p = recents[i]
                btn.setText(f"⏵ {os.path.basename(p)}")
                btn.setToolTip(p)
                btn.setProperty("path", p)
                btn.setVisible(True)
            else:
                btn.setVisible(False)

    def _open_recent(self, btn):
        p = btn.property("path")
        if p:
            self._load_video_path(p)

    def _load_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Video", "",
            "Video Files (*.mp4 *.avi *.mov *.mkv *.wmv *.m4v)"
        )
        if not path:
            return
        self._load_video_path(path)

    def reload_video(self):
        if self.video_path and os.path.exists(self.video_path):
            self._load_video_path(self.video_path)

    def _load_video_path(self, path):
        if not os.path.exists(path):
            QMessageBox.warning(self, "Error", f"Video file not found:\n{path}")
            return
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            QMessageBox.warning(self, "Error", "Cannot open this video file.")
            return
        self._auto_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        # honor manual override if set
        override = self._fps_override()
        self.fps = override if override > 0 else self._auto_fps
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._total_frames = frame_count
        native_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        native_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.video_w = native_w
        self.video_h = native_h
        # Plugins that manage perspective (Y-Maze, EPM) baked a specific
        # warp output size into _H. Restore it so video_w/h match the
        # rect _H targets — otherwise scrub frames come out unwarped or
        # garbled after the post-tracking reload.
        if getattr(self, "_perspective_on", False) and getattr(
                self, "_H", None) is not None:
            sz = getattr(self, "_perspective_warp_size", None)
            if sz and sz[0] and sz[1]:
                self.video_w, self.video_h = int(sz[0]), int(sz[1])
                # Refresh native cache so the OFF branch later restores
                # the truly-native dims, not the just-overwritten ones.
                self._native_video_size = (native_w, native_h)
        duration = frame_count / self.fps
        ret, frame = cap.read()
        cap.release()
        if not ret:
            QMessageBox.warning(self, "Error", "Cannot read frames from this video.")
            return
        # Apply per-video crop if set — everything downstream sees the
        # cropped frame as the "video".
        if self._crop_rect is not None:
            cx, cy, cw, ch = self._crop_rect
            frame = frame[cy:cy + ch, cx:cx + cw]
            self.video_w, self.video_h = cw, ch

        # Drop the prior scrub cap before swapping video — the new path will
        # build a fresh cap on the next _on_scrub call.
        self._release_scrub_cap()
        self.video_path = path
        self._first_frame_bgr = frame.copy()
        self._preview_bg_raw = None
        self._preview_active = False
        self.btn_preview.setChecked(False)
        self.btn_preview.setEnabled(False)
        self.btn_preview_mode.setEnabled(False)
        self.zone_drawer.set_frame(frame)

        self.slider_scrub.setMaximum(max(0, frame_count - 1))
        self.slider_scrub.setValue(0)
        self.slider_scrub.setEnabled(True)
        self.btn_step_prev.setEnabled(True)
        self.btn_step_next.setEnabled(True)
        self._update_scrub_label(0, frame_count)

        name = os.path.basename(path)
        self.lbl_video.setText(
            f"{name}\n{self.video_w}×{self.video_h}  |  {self.fps:.1f} fps  |  {duration:.1f}s"
        )
        # Only log on a real new-video load, not when the same path is being
        # re-loaded into the embedded preview after a run finishes.
        if path != getattr(self, "_last_logged_video_path", None):
            logger.info(
                f"Loaded video: {name} | {self.video_w}x{self.video_h} | "
                f"{self.fps:.2f} fps (auto={self._auto_fps:.2f}) | {frame_count} frames | "
                f"{duration:.2f}s | crop={self._crop_rect} | path={path}",
                source="video",
            )
            self._last_logged_video_path = path
        if hasattr(self, "lbl_fps_detected"):
            self.lbl_fps_detected.setText(f"{self.fps:.1f}")
        if hasattr(self, "lbl_resolution"):
            self.lbl_resolution.setText(f"{self.video_w} × {self.video_h}")
        for name in ("btn_calib", "btn_arena", "btn_auto_arena",
                     "btn_excl", "btn_view_processed"):
            btn = getattr(self, name, None)
            if btn is not None:
                btn.setEnabled(True)
        # Plugins (Y-Maze, EPM) own their own perspective state through
        # their dedicated checkboxes + saved hub/endpoints. The OF reset
        # below would clear `_H` after every video reload (including the
        # post-tracking re-load), breaking those plugins' warp. Skip it
        # for plugin keys that manage perspective independently.
        exp_key = getattr(getattr(self, "experiment", None), "key", None)
        plugin_owns_perspective = exp_key in ("y_maze", "epm")
        if (self._perspective_on and hasattr(self, "chk_perspective")
                and not plugin_owns_perspective):
            self.chk_perspective.blockSignals(True)
            self.chk_perspective.setChecked(False)
            self.chk_perspective.blockSignals(False)
            self._perspective_on = False
            self._H = None
            self._original_arena = None
            self.zone_drawer.set_perspective_locked(False)
        if hasattr(self, "chk_perspective") and not plugin_owns_perspective:
            self.chk_perspective.setEnabled(False)
        self._update_run_button()
        self.set_step_status("source", "ok")
        self.set_step_status("detection", "ok")

        # Build preview background asynchronously
        self.lbl_adjust.setText("Building preview background…")
        self.lbl_adjust.setStyleSheet("color:#888; font-size:11px;")
        # Defensively probe the cached thread — its C++ side may have been
        # deleted by deleteLater() in _cleanup_bg_builder, in which case any
        # method call on the Python wrapper raises RuntimeError.
        prev = self._bg_builder
        if prev is not None:
            try:
                still_running = prev.isRunning()
            except RuntimeError:
                # C++ object already gone — drop the dangling reference.
                self._bg_builder = None
                still_running = False
            if still_running:
                # Don't .terminate() — terminating a thread mid-OpenCV read is
                # undefined and crashes the app. Disconnect its signal so its
                # result is ignored; the thread keeps running in the active
                # list until it finishes naturally.
                try:
                    prev.done.disconnect()
                except Exception:
                    pass
        builder = BgBuilderThread(path, n_samples=20)
        self._bg_builders_active.append(builder)
        builder.done.connect(self._on_preview_bg_ready)
        builder.finished.connect(lambda b=builder: self._cleanup_bg_builder(b))
        self._bg_builder = builder
        builder.start()

        self._push_recent(path)

        # Default new videos to "Auto — from movement": skip arena setup
        # now and let the next tracking run build the polygon from the
        # mouse's positions. Only fires when there's no arena currently
        # on the drawer. In batch flow this runs again post-apply_settings
        # in _load_into_embedded (which is the authoritative gate after
        # per-video state restore); here it covers standalone load paths
        # like the startup auto-load of the last opened video.
        zd = getattr(self, "zone_drawer", None)
        exp_key = getattr(getattr(self, "experiment", None), "key", None)
        # OF / NOR default to a centered premade square so the user always
        # opens to a usable arena. Y-Maze / EPM use their own geometry
        # (arms / plus template) and are skipped. Auto-from-movement
        # remains available behind the Extra features toggle and wins
        # over the square when enabled.
        if zd is not None and zd.arena is None:
            if (exp_key in ("open_field", "nor")
                    and not self.config.get("enable_auto_movement_arena", False)):
                try:
                    self._apply_premade_square_arena()
                    self._arena_define_mode = "square"
                    if hasattr(self, "btn_define_arena"):
                        try:
                            self.btn_define_arena.setText(
                                "Premade square arena ▾"
                            )
                        except RuntimeError:
                            pass
                    if hasattr(self, "_refresh_arena_mode_chip"):
                        try:
                            self._refresh_arena_mode_chip()
                        except RuntimeError:
                            pass
                except Exception:
                    pass
            elif (exp_key != "y_maze"
                    and self.config.get("enable_auto_movement_arena", False)):
                self._arena_auto_movement = True
                self._arena_define_mode = "movement"
                if hasattr(self, "btn_define_arena"):
                    try:
                        self.btn_define_arena.setText(
                            "Auto — from movement (next run) ▾"
                        )
                    except RuntimeError:
                        pass
                if hasattr(self, "_refresh_arena_mode_chip"):
                    try:
                        self._refresh_arena_mode_chip()
                    except RuntimeError:
                        pass
                if hasattr(self, "lbl_zones"):
                    self.lbl_zones.setText(
                        "Auto-from-movement queued — run tracking; arena "
                        "will form from the mouse's path."
                    )

    def _cleanup_bg_builder(self, builder):
        try:
            self._bg_builders_active.remove(builder)
        except ValueError:
            pass
        # Drop the cached reference so we don't probe a deleted C++ object
        # next time _load_video_path runs.
        if self._bg_builder is builder:
            self._bg_builder = None
        builder.deleteLater()

    # ── Step 2 ────────────────────────────────────────────────────────────

    def _start_draw_calib(self):
        if self.zone_drawer.calib_p1 or self.zone_drawer.calib_p2:
            self.zone_drawer.calib_p1 = None
            self.zone_drawer.calib_p2 = None
            self.btn_clear_calib.setEnabled(False)
            self.lbl_calib.setText("Not calibrated — distances will be in pixels")
            self.lbl_calib.setStyleSheet("color:#888; font-size:11px;")
        self.zone_drawer.set_mode(ZoneDrawer.MODE_CALIB)

    def _clear_calib(self):
        self.zone_drawer.clear_calibration()
        self.btn_clear_calib.setEnabled(False)
        self.lbl_calib.setText("Not calibrated — distances will be in pixels")
        self.lbl_calib.setStyleSheet("color:#888; font-size:11px;")

    def _update_calib_status(self):
        mode = self._calib_mode() if hasattr(self, "rb_calib_auto") else None
        if mode == "none":
            self.lbl_calib.setText("Calibration off — distances will be in pixels")
            self.lbl_calib.setStyleSheet("color:#888; font-size:11px;")
            if hasattr(self, "btn_clear_calib"):
                self.btn_clear_calib.setEnabled(False)
            self.set_step_status("scale", "warn")
            return
        if mode in ("manual", None):
            if self.zone_drawer.calib_p1 and self.zone_drawer.calib_p2:
                pxcm = self.zone_drawer.get_pixels_per_cm(self.spin_cm.value())
                if pxcm:
                    self.lbl_calib.setText(f"Calibrated (line): {pxcm:.2f} px/cm")
                    self.lbl_calib.setStyleSheet("color:#4CAF50; font-size:11px;")
                    self.btn_clear_calib.setEnabled(True)
                    self.set_step_status("scale", "ok")
                    return
        if mode in ("auto", None):
            auto = self._auto_px_per_cm()
            if auto:
                self.lbl_calib.setText(f"Auto-calibrated from cage: {auto:.2f} px/cm")
                self.lbl_calib.setStyleSheet("color:#3CA0FF; font-size:11px;")
                self.set_step_status("scale", "ok")
                return
        self.lbl_calib.setText("Not calibrated — distances will be in pixels")
        self.lbl_calib.setStyleSheet("color:#888; font-size:11px;")
        self.set_step_status("scale", "warn")

    def _on_calib_cm_changed(self, _v=None):
        self._update_calib_status()
        # Keep the Move-threshold suffix (cm/s vs px/s) in sync regardless
        # of whether tracking has run yet — calibration just toggled.
        try:
            self._refresh_move_threshold_suffix()
        except Exception:
            pass
        if self.tracking_results:
            self._recompute_metrics_and_views()

    def _calib_mode(self):
        """Return the active calibration source: 'auto' / 'manual' / 'none'."""
        if hasattr(self, "rb_calib_manual") and self.rb_calib_manual.isChecked():
            return "manual"
        if hasattr(self, "rb_calib_none") and self.rb_calib_none.isChecked():
            return "none"
        return "auto"

    def _on_calib_mode_changed(self, btn=None, checked=False):
        # buttonToggled fires twice (one off, one on) — react to the on event.
        if btn is not None and not checked:
            return
        if getattr(self, "_suppress_calib_mode", False):
            return
        self.config["calib_mode"] = self._calib_mode()
        win = self.window()
        if hasattr(win, "_save_config"):
            win._save_config()
        self._refresh_calib_mode_visibility()
        self._update_calib_status()
        self._recompute_metrics_and_views()

    def _refresh_calib_mode_visibility(self):
        """Show only the sub-panel for the selected calibration mode.
        Cage-size / arm-length widget visibility is delegated to the
        experiment plugin (refresh_scale_step_visibility)."""
        if not hasattr(self, "_calib_auto_widget"):
            return
        mode = self._calib_mode()
        self._calib_auto_widget.setVisible(mode == "auto")
        self._calib_manual_widget.setVisible(mode == "manual")
        exp = getattr(self, "experiment", None)
        if exp is not None:
            try:
                exp.refresh_scale_step_visibility(self, mode)
            except Exception as e:
                logger.warn(f"refresh_scale_step_visibility failed "
                            f"({getattr(exp, 'key', '?')}): {e}",
                            source="plugin")

    def _refresh_arena_mode_chip(self):
        # Padding only applies to auto-from-movement (which itself is
        # gated behind the Extra features toggle).
        if hasattr(self, "_arena_pad_widget"):
            self._arena_pad_widget.setVisible(
                self._arena_define_mode == "movement"
            )

    # ── Step 3 ────────────────────────────────────────────────────────────

    def _start_draw_arena(self):
        if self.zone_drawer.arena:
            self.zone_drawer.arena = None
            self.zone_drawer.center_zone = None
            self.btn_clear_arena.setEnabled(False)
            self._refresh_zones_label()
            self._update_run_button()
        self.zone_drawer.set_mode(ZoneDrawer.MODE_ARENA)

    def _apply_premade_square_arena(self):
        """Drop a centered square arena (80% of min(video_w, video_h)) onto
        the zone drawer. User adjusts corners by drag if the square
        doesn't fit."""
        w = float(self.video_w or 0)
        h = float(self.video_h or 0)
        if w <= 0 or h <= 0:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Premade square arena",
                "No video loaded. Open a video first."
            )
            return
        side = 0.8 * min(w, h)
        hx = (side / 2.0) / w   # half-side as fraction of width
        hy = (side / 2.0) / h   # half-side as fraction of height
        arena = [
            (0.5 - hx, 0.5 - hy),
            (0.5 + hx, 0.5 - hy),
            (0.5 + hx, 0.5 + hy),
            (0.5 - hx, 0.5 + hy),
        ]
        self.zone_drawer.arena = arena
        self.zone_drawer.set_mode(ZoneDrawer.MODE_IDLE)
        self.zone_drawer.emit_change("arena set from premade square")
        self.zone_drawer.update()

    def _clear_arena(self):
        self.zone_drawer.clear_arena()
        self.btn_clear_arena.setEnabled(False)
        self._refresh_zones_label()
        self._update_run_button()

    _OVERLAY_FLAGS = (
        "_cell_show_numbers", "_cell_show_timer", "_cell_show_entries",
        "_arm_show_numbers", "_arm_show_timer", "_arm_show_entries",
    )

    def _on_live_overlay_toggled(self, on):
        """Default handler for the Step 5 Live-overlay checkbox. OF mixin
        overrides via of_ui_cell_highlight.py (same behavior). Centralizing
        here means non-OF experiments don't crash if they skip the mixin."""
        self._live_cell_overlay = bool(on)

    def _cell_min_dwell_s(self):
        """Default min-dwell reader. OF mixin overrides via of_ui_cell_info
        to read host.spin_min_dwell. Base provides 0.0 so the unified Step 5
        snapshot_settings call doesn't crash on a hypothetical non-OF
        experiment that skips the mixin."""
        return (float(self.spin_min_dwell.value())
                if hasattr(self, "spin_min_dwell") else 0.0)

    def begin_tracking(self):
        """Batch tab calls this just before tracker.run().

        Live overlay ON  → force all show flags True (override popup Hide
                           prefs so the user sees everything live).
        Live overlay OFF → force all show flags False (skip per-paint cost).
        end_tracking restores the user's popup Hide prefs either way."""
        self._tracking_active = True
        zd = self.zone_drawer
        self._cell_show_state_backup = {
            k: getattr(zd, k) for k in self._OVERLAY_FLAGS
            if hasattr(zd, k)
        }
        forced = bool(self._live_cell_overlay)
        for k in self._cell_show_state_backup:
            setattr(zd, k, forced)
        if not forced:
            zd.set_body_pos_norm(None)

    def end_tracking(self):
        """Batch tab calls this after tracker.run() returns. Restores the
        user's popup Hide prefs (saved before tracking)."""
        self._tracking_active = False
        if self._cell_show_state_backup is not None:
            zd = self.zone_drawer
            for k, v in self._cell_show_state_backup.items():
                setattr(zd, k, v)
            self._cell_show_state_backup = None
            zd.update()

    def _enable_auto_movement_arena(self):
        """User picked 'Auto from movement'. Flag set; the next tracking
        run will skip the arena and build it live from mouse positions."""
        self._arena_auto_movement = True
        # Clear any existing arena so the user sees fresh state.
        self.zone_drawer.arena = None
        self.zone_drawer.center_zone = None
        self.zone_drawer.update()
        self._refresh_zones_label()
        self._update_run_button()
        self.lbl_zones.setText(
            "Auto-from-movement queued — run tracking; arena will form "
            "from the mouse's path."
        )
        # Notify the batch tab (if any) so its per-video setting is updated.
        try:
            self.zone_drawer.emit_change("arena cleared — auto-from-movement queued")
        except Exception:
            pass

    def auto_movement_pending(self):
        """Public flag the batch tab reads before each track."""
        return bool(self._arena_auto_movement)

    def auto_arena_padding_pct(self):
        if hasattr(self, "spin_arena_pad_pct"):
            return float(self.spin_arena_pad_pct.value())
        return 5.0

    @staticmethod
    def _fit_quad_from_points(pts):
        """Return 4 (x, y) corners that approximate the convex hull of `pts`.
        Uses iterative cv2.approxPolyDP — the more bumpy the hull, the larger
        the simplification epsilon needs to be to land exactly on 4 vertices.
        Falls back to the rotated min-area rectangle if a 4-point fit can't
        be reached. `pts` is an (N, 2) numpy float32 array."""
        if len(pts) < 4:
            return None
        try:
            hull = cv2.convexHull(pts)
        except Exception as e:
            logger.warn(f"convexHull failed (n={len(pts)}): {e}", source="arena")
            return None
        if hull is None or len(hull) < 4:
            return None
        if len(hull) == 4:
            return hull.reshape(-1, 2)
        peri = cv2.arcLength(hull, True)
        # Binary-search epsilon — find the smallest one that yields exactly
        # 4 vertices.
        lo, hi = 0.001, 0.5
        best = None
        for _ in range(40):
            eps = (lo + hi) / 2.0 * peri
            approx = cv2.approxPolyDP(hull, eps, True)
            n = len(approx)
            if n == 4:
                best = approx.reshape(-1, 2)
                break
            if n > 4:
                lo = (lo + hi) / 2.0
            else:
                hi = (lo + hi) / 2.0
        if best is None:
            # Fall back to rotated min-area rectangle.
            (cx, cy), (w, h), ang = cv2.minAreaRect(pts)
            return cv2.boxPoints(((cx, cy), (w, h), ang)).astype(np.float32)
        return best.astype(np.float32)

    @staticmethod
    def _expand_quad(quad, pad_frac):
        """Expand a 4-point quad outward from its centroid by `pad_frac`
        (e.g. 0.05 = +5%). Returns same shape as input."""
        if pad_frac <= 0:
            return quad
        cx = float(np.mean(quad[:, 0]))
        cy = float(np.mean(quad[:, 1]))
        scale = 1.0 + pad_frac
        out = quad.copy()
        out[:, 0] = cx + (quad[:, 0] - cx) * scale
        out[:, 1] = cy + (quad[:, 1] - cy) * scale
        return out

    def commit_auto_movement_arena(self, points_px, frame_w, frame_h):
        """Build a 4-sided polygon from `points_px` (convex-hull ≈ quad),
        expand by the user's padding %, set as the arena, clear the flag."""
        if not points_px:
            self._arena_auto_movement = False
            return None
        try:
            pts = np.array(points_px, dtype=np.float32)
            quad = self._fit_quad_from_points(pts)
            if quad is None:
                self._arena_auto_movement = False
                return None
            pad = self.auto_arena_padding_pct() / 100.0
            quad = self._expand_quad(quad, pad)
            quad[:, 0] = np.clip(quad[:, 0], 0, frame_w - 1)
            quad[:, 1] = np.clip(quad[:, 1], 0, frame_h - 1)
            arena_norm = [(float(x) / frame_w, float(y) / frame_h)
                          for x, y in quad]
            self.zone_drawer.arena = arena_norm
            self._compute_center()
            # Make sure handles render after the commit — mode → IDLE.
            self.zone_drawer.set_mode(ZoneDrawer.MODE_IDLE)
            self.zone_drawer.emit_change("arena committed from movement (auto)")
            self.zone_drawer.update()
            self._arena_auto_movement = False
            return arena_norm
        except Exception:
            import traceback
            traceback.print_exc()
            self._arena_auto_movement = False
            return None

    @staticmethod
    def _sort_quad_screen(pts):
        TL = min(pts, key=lambda p: p[0] + p[1])
        BR = max(pts, key=lambda p: p[0] + p[1])
        TR = max(pts, key=lambda p: p[0] - p[1])
        BL = min(pts, key=lambda p: p[0] - p[1])
        return [TL, TR, BR, BL]

    def _warp_target_size(self):
        if not self.video_w or not self.video_h:
            return None
        if self.config.get("cage_shape", "rectangle") == "square":
            S = min(self.video_w, self.video_h)
            return (S, S)
        return (self.video_w, self.video_h)

    def _build_homography(self, arena_norm):
        if not arena_norm or not self.video_w or not self.video_h:
            return None
        target = self._warp_target_size()
        if not target:
            return None
        TW, TH = target
        pts_px = [(nx * self.video_w, ny * self.video_h) for nx, ny in arena_norm]
        src = np.array(self._sort_quad_screen(pts_px), dtype=np.float32)
        dst = np.array([(0, 0), (TW, 0), (TW, TH), (0, TH)], dtype=np.float32)
        try:
            return cv2.getPerspectiveTransform(src, dst)
        except cv2.error:
            return None

    def _compute_homography(self):
        self._H = self._build_homography(self._original_arena)

    def _persistent_homography(self):
        """Homography from current arena → axis-aligned target, regardless of toggle state."""
        if self._H is not None:
            return self._H
        return self._build_homography(self.zone_drawer.arena)

    def _on_cage_shape_changed(self):
        shape = self.combo_cage_shape.currentData()
        self.config["cage_shape"] = shape
        win = self.window()
        if hasattr(win, "_save_config"):
            win._save_config()
        if self._perspective_on:
            self._compute_homography()
            if self._first_frame_bgr is not None:
                self._on_scrub(self.slider_scrub.value())
        self._refresh_cage_size_inputs()
        if hasattr(self, "_refresh_calib_mode_visibility"):
            self._refresh_calib_mode_visibility()
        self._update_calib_status()
        self._recompute_metrics_and_views()

    def _on_cage_size_changed(self, _v=None):
        # Persist + refresh derived calibration state.
        self.config["cage_w_cm"] = float(self.spin_cage_w.value())
        self.config["cage_h_cm"] = float(self.spin_cage_h.value())
        win = self.window()
        if hasattr(win, "_save_config"):
            win._save_config()
        self._update_calib_status()
        self._recompute_metrics_and_views()

    def _refresh_cage_size_inputs(self):
        """Adjust per-shape labels for cage size inputs. Whether the size
        widget is shown at all is decided by `_refresh_calib_mode_visibility`
        (mode=auto and shape!=custom)."""
        if not hasattr(self, "combo_cage_shape") or not hasattr(self, "_cage_size_widget"):
            return
        shape = self.combo_cage_shape.currentData()
        if shape == "square":
            # One value (side). Sync H to W.
            self.lbl_cage_w.setText("Side:")
            self.lbl_cage_x.setVisible(False)
            self.lbl_cage_h.setVisible(False)
            self.spin_cage_h.setVisible(False)
            try:
                self.spin_cage_h.blockSignals(True)
                self.spin_cage_h.setValue(self.spin_cage_w.value())
            finally:
                self.spin_cage_h.blockSignals(False)
        else:  # rectangle / custom
            self.lbl_cage_w.setText("Width:")
            self.lbl_cage_x.setVisible(True)
            self.lbl_cage_h.setVisible(True)
            self.spin_cage_h.setVisible(True)

    def _auto_px_per_cm(self):
        """Delegate auto-calibration to the experiment plugin so each
        experiment owns its own geometry → px/cm formula. Same path used
        in headless batch runs, just sourced from the live snapshot here."""
        exp = getattr(self, "experiment", None)
        if exp is None:
            return None
        video_size = (getattr(self, "video_w", None),
                      getattr(self, "video_h", None))
        try:
            snapshot = self.snapshot_settings()
            return exp.compute_auto_px_per_cm(snapshot, video_size)
        except Exception as e:
            logger.warn(f"compute_auto_px_per_cm failed: {e}", source="plugin")
            return None

    def _build_plugin_settings(self, arena_px, center_px):
        """Settings dict consumed by experiment plugins' compute_metrics.
        Mirrors what ExperimentBatchTab._do_track_and_export builds for the
        headless path so the live tab + batch share one contract."""
        s = dict(self.snapshot_settings())
        s["arena"]            = arena_px
        s["center_zone"]      = center_px
        s["video_w"]          = self.video_w
        s["video_h"]          = self.video_h
        s["movement_threshold"] = float(s.get("movement_thr", 0.0))
        s["bin_size_s"]         = float(s.get("bin_size", 0.0))
        s["cell_min_dwell_s"]   = float(s.get("cell_min_dwell_s",
                                                s.get("cell_min_dwell", 0.2)))
        s["trim_start_s"]       = float(s.get("trim_start", 0.0))
        return s

    def _graph_data(self):
        """Returns (results, arena_pixels, center_pixels, px_per_cm) in warped (undistorted) space."""
        results = self.tracking_results
        arena = self.zone_drawer.get_arena_pixels()
        center = self.zone_drawer.get_center_pixels()
        px_per_cm = self._get_px_per_cm()

        if self._perspective_on or not results:
            return results, arena, center, px_per_cm
        H = self._persistent_homography()
        if H is None:
            return results, arena, center, px_per_cm

        def warp_pts(pts_list):
            if not pts_list:
                return pts_list
            arr = np.array([[[float(p[0]), float(p[1])]] for p in pts_list], dtype=np.float32)
            w = cv2.perspectiveTransform(arr, H)
            return [(float(p[0][0]), float(p[0][1])) for p in w]

        warped_results = []
        for r in results:
            nr = dict(r)
            if nr.get("x") is not None and nr.get("y") is not None:
                p = np.array([[[float(nr["x"]), float(nr["y"])]]], dtype=np.float32)
                w = cv2.perspectiveTransform(p, H)[0, 0]
                nr["x"] = float(w[0])
                nr["y"] = float(w[1])
            warped_results.append(nr)

        warped_arena = warp_pts(arena)
        warped_center = warp_pts(center)

        warped_px_per_cm = px_per_cm
        if (px_per_cm and self.zone_drawer.calib_p1 and self.zone_drawer.calib_p2
                and self.spin_cm.value() > 0):
            p1 = self.zone_drawer.calib_p1
            p2 = self.zone_drawer.calib_p2
            calib_pts = warp_pts([
                (p1[0] * self.video_w, p1[1] * self.video_h),
                (p2[0] * self.video_w, p2[1] * self.video_h),
            ])
            dist = ((calib_pts[1][0] - calib_pts[0][0]) ** 2 +
                    (calib_pts[1][1] - calib_pts[0][1]) ** 2) ** 0.5
            warped_px_per_cm = dist / self.spin_cm.value()

        return warped_results, warped_arena, warped_center, warped_px_per_cm

    def _graph_canvas_size(self):
        """Returns (W, H) used by trajectory/heatmap plots — warped target if available."""
        target = self._warp_target_size()
        if target is not None and (self._perspective_on or self.zone_drawer.arena is not None):
            return target
        return (self.video_w or 640, self.video_h or 480)

    def _warp(self, frame):
        if self._H is None or frame is None:
            return frame
        target = self._warp_target_size()
        if not target:
            return frame
        return cv2.warpPerspective(frame, self._H, target)

    def _on_perspective_toggled(self, checked):
        if checked:
            if not self.zone_drawer.arena:
                self.chk_perspective.blockSignals(True)
                self.chk_perspective.setChecked(False)
                self.chk_perspective.blockSignals(False)
                return
            self._original_arena = list(self.zone_drawer.arena)
            self._compute_homography()
            if self._H is None:
                self.chk_perspective.blockSignals(True)
                self.chk_perspective.setChecked(False)
                self.chk_perspective.blockSignals(False)
                return
            self.zone_drawer.arena = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
            self.zone_drawer.set_perspective_locked(True)
            self._perspective_on = True
            # The active coordinate space becomes the warp target — body
            # coords from the tracker will be in (warp_w, warp_h). All code
            # that normalizes by video_w/video_h must use these dims.
            self._native_video_size = (self.video_w, self.video_h)
            target = self._warp_target_size()
            if target:
                self.video_w, self.video_h = target
        else:
            if self._original_arena is not None:
                self.zone_drawer.arena = list(self._original_arena)
            self._original_arena = None
            self._H = None
            self.zone_drawer.set_perspective_locked(False)
            self._perspective_on = False
            # Restore the pre-perspective video size.
            if hasattr(self, "_native_video_size") and self._native_video_size:
                self.video_w, self.video_h = self._native_video_size
                self._native_video_size = None
        self._compute_center()
        if self._first_frame_bgr is not None:
            self._on_scrub(self.slider_scrub.value())

    def _on_zones_changed(self):
        self._update_calib_status()
        self._compute_center()
        self._refresh_zones_label()
        self._update_run_button()
        zd = self.zone_drawer
        a = zd.arena
        c = zd.center_zone
        model_label = (self.combo_model.currentText()
                       if hasattr(self, "combo_model") else "n/a")
        model_key = (self.combo_model.currentData()
                     if hasattr(self, "combo_model") else "n/a")
        reason = getattr(zd, "_last_change_reason", "unspecified")
        logger.info(
            f"Zone changed → {reason} | arena_corners={len(a) if a else 0} | "
            f"center_corners={len(c) if c else 0} | zone_mode={zd.zone_mode} | "
            f"tracking_model={model_label} ({model_key})",
            source="zones",
        )
        # Reset so subsequent unattributed emits don't reuse the old reason.
        zd._last_change_reason = "unspecified"
        # Enable perspective toggle only when arena is defined and not already on
        if not self._perspective_on and hasattr(self, "chk_perspective"):
            self.chk_perspective.setEnabled(self.zone_drawer.arena is not None)
        if self._preview_active:
            self._update_preview()
        # Refresh on-frame live overlay numbers (body position, per-cell time/
        # entries) so they reflect the new zone polygon without waiting for a
        # scrub event.
        if self.tracking_results:
            try:
                self._push_cell_state_for_frame(self.slider_scrub.value())
            except Exception:
                pass

    def _refresh_zones_label(self):
        # Y-Maze owns its own status label; bail out cleanly for non-OF.
        if not hasattr(self, "lbl_zones"):
            return
        parts = []
        if self.zone_drawer.arena:
            parts.append("Arena defined")
            if hasattr(self, "btn_clear_arena"):
                self.btn_clear_arena.setEnabled(True)
        if self.zone_drawer.zone_mode == "grid" and self.zone_drawer.arena:
            parts.append("Grid 4×4")
        if self.zone_drawer.center_zone and hasattr(self, "spin_center_pct"):
            parts.append(f"Center Zone {self.spin_center_pct.value()}%")
        if parts:
            self.lbl_zones.setText("  |  ".join(parts))
            self.lbl_zones.setStyleSheet("color:#4CAF50; font-size:11px;")
        else:
            self.lbl_zones.setText("No zones defined")
            self.lbl_zones.setStyleSheet("color:#888; font-size:11px;")
        if self.zone_drawer.arena:
            self.set_step_status("geometry", "ok")
        elif getattr(self, "_arena_auto_movement", False):
            self.set_step_status("geometry", "warn")
        else:
            self.set_step_status("geometry", "blocked")

    # ── Step 4 — Adjust & Preview ─────────────────────────────────────────

    def _on_preview_bg_ready(self, bg):
        # The bg builder reads frames straight from the file (no crop). If a
        # crop is active we must crop the bg to match the displayed frames,
        # otherwise cv2.absdiff() in _update_preview blows up on size mismatch.
        if bg is not None and self._crop_rect is not None:
            cx, cy, cw, ch = self._crop_rect
            bg = bg[cy:cy + ch, cx:cx + cw]
        self._preview_bg_raw = bg
        if bg is not None:
            self.btn_preview.setEnabled(True)
            self.lbl_adjust.setText("Adjust sliders then click Preview Detection.")
            self.lbl_adjust.setStyleSheet("color:#888; font-size:11px;")
            if not self.tracking_results and not getattr(self, "_suppress_auto_preview", False):
                self.btn_preview.setChecked(True)
        else:
            self.lbl_adjust.setText("Preview unavailable for this video.")

    def _on_preview_toggled(self, checked):
        self._preview_active = checked
        self.btn_preview_mode.setEnabled(checked)
        if checked:
            self.btn_preview.setText("Preview ON")
            self._update_preview()
        else:
            self.btn_preview.setText("Preview Detection")
            self._on_scrub(self.slider_scrub.value())

    def _on_preview_mode_toggled(self, checked):
        self._preview_mode = "mask" if checked else "overlay"
        self._update_preview()

    def _get_processed_frame_bgr(self, frame):
        return apply_preprocessing_bgr(
            frame,
            brightness=self.slider_brightness.value(),
            contrast=self.slider_contrast.value() / 100.0,
            blur=self.slider_blur.value(),
            gamma=self.slider_gamma.value() / 100.0,
            sharpen=self.slider_sharpen.value(),
            clahe_clip=self.spin_clahe.value(),
        )

    def _render_current_frame(self):
        """Re-display cached frame with effects + tracking overlay. No disk read."""
        frame = self._current_scrub_frame_bgr if self._current_scrub_frame_bgr is not None else self._first_frame_bgr
        if frame is None:
            return
        display = self._get_processed_frame_bgr(frame) if self.btn_view_processed.isChecked() else frame.copy()
        if self.tracking_results:
            rel_idx = self._slider_to_results_idx(self.slider_scrub.value())
            r = self.tracking_results[rel_idx]
            if r.get("corrected"):
                xv, yv = r.get("x"), r.get("y")
                if xv is not None:
                    cv2.circle(display, (int(xv), int(yv)), 8, (0, 255, 255), -1)
                    cv2.circle(display, (int(xv), int(yv)), 10, (0, 200, 200), 2)
            elif r.get("interpolated"):
                xv, yv = r.get("x"), r.get("y")
                if xv is not None:
                    cv2.circle(display, (int(xv), int(yv)), 7, (200, 100, 255), -1)
                    cv2.circle(display, (int(xv), int(yv)), 9, (170, 70, 220), 2)
            else:
                self._draw_body_on_frame(display, r, rel_idx)
        self.zone_drawer.set_frame(display)

    def _update_preview(self):
        if not self._preview_active:
            if self.btn_view_processed.isChecked():
                self._render_current_frame()
            return
        current = self._current_scrub_frame_bgr if self._current_scrub_frame_bgr is not None else self._first_frame_bgr
        if current is None or self._preview_bg_raw is None:
            return

        brightness = self.slider_brightness.value()
        contrast   = self.slider_contrast.value() / 100.0
        blur       = self.slider_blur.value()
        gamma      = self.slider_gamma.value() / 100.0
        sharpen    = self.slider_sharpen.value()
        clahe_clip = self.spin_clahe.value()
        threshold  = self.spin_threshold.value()
        arena      = self.zone_drawer.get_arena_pixels()

        gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
        bg_raw = self._warp(self._preview_bg_raw) if self._H is not None else self._preview_bg_raw
        proc_frame = apply_preprocessing(gray, brightness, contrast, blur, gamma, sharpen, clahe_clip)
        proc_bg    = apply_preprocessing(bg_raw, brightness, contrast, blur, gamma, sharpen, clahe_clip)
        mask = get_mask(proc_frame, proc_bg, threshold, arena)
        exc = self.zone_drawer.get_exclusion_mask()
        if exc is not None and exc.any():
            mask = cv2.bitwise_and(mask, cv2.bitwise_not(exc))

        base = self._get_processed_frame_bgr(current) if self.btn_view_processed.isChecked() else current
        if self._preview_mode == "overlay":
            display = make_overlay(base, mask, self._bgr("detection"),
                                   self.overlay_alpha / 100.0)
        else:
            display = make_mask_view(mask)

        self.zone_drawer.set_frame(display)

    def _reset_sliders(self):
        self.slider_brightness.setValue(0)
        self.slider_contrast.setValue(100)
        self.slider_blur.setValue(0)
        self.slider_gamma.setValue(100)
        self.slider_sharpen.setValue(0)
        self.spin_clahe.setValue(0)
        self.spin_threshold.setValue(25)

    # ── presets ───────────────────────────────────────────────────────────

    def _load_presets_file(self):
        if os.path.exists(PRESETS_PATH):
            try:
                with open(PRESETS_PATH) as f:
                    return json.load(f)
            except Exception as e:
                logger.warn(f"Presets file unreadable ({PRESETS_PATH}): {e}",
                            source="presets")
        return {}

    def _save_presets_file(self):
        with open(PRESETS_PATH, "w") as f:
            json.dump(self._presets, f, indent=2)

    def _populate_preset_combo(self):
        self.combo_preset.blockSignals(True)
        self.combo_preset.clear()
        self.combo_preset.addItem("— select preset —")
        for name in sorted(self._presets):
            self.combo_preset.addItem(name)
        self.combo_preset.blockSignals(False)

    def _save_preset(self):
        current = self.combo_preset.currentText()
        default = "" if current == "— select preset —" else current
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:", text=default)
        if not ok or not name.strip():
            return
        name = name.strip()
        preset = {
            "brightness":   self.slider_brightness.value(),
            "contrast":     self.slider_contrast.value(),
            "blur":         self.slider_blur.value(),
            "gamma":        self.slider_gamma.value(),
            "sharpen":      self.slider_sharpen.value(),
            "clahe":        self.spin_clahe.value(),
            "threshold":    self.spin_threshold.value(),
            "max_blob":     self.spin_max_blob.value(),
            "proc_scale":   self.combo_proc_scale.currentData(),
            "frame_skip":   int(self.spin_frame_skip.value()),
            "smooth_window": int(self.spin_smooth_window.value()) if hasattr(self, "spin_smooth_window") else 3,
            "model":        self.combo_model.currentData() or "median",
            "model_params": {m: dict(p) for m, p in self._model_params.items()},
            "post_params":  dict(self._post_params),
            "body_style":   self.combo_body_style.currentData() or "dot",
            "ellipse":      self.chk_ellipse.isChecked(),
            "trail":        self.chk_trail.isChecked(),
            "trail_len":    self.spin_trail_len.value(),
            "trail_fade":   self.chk_trail_fade.isChecked(),
            "brush_radius": self.spin_brush.value(),
            "colors":       dict(self._colors),
            "overlay_alpha": self.overlay_alpha,
            "smooth":       self.spin_smooth.value(),
        }
        # OF-only widgets — skip when running under Y-Maze (or any future
        # experiment that doesn't expose them).
        if hasattr(self, "combo_zone_mode"):
            preset["zone_mode"] = self.combo_zone_mode.currentData()
        if hasattr(self, "combo_cage_shape"):
            preset["cage_shape"] = self.combo_cage_shape.currentData()
        if hasattr(self, "chk_perspective"):
            preset["perspective"] = self.chk_perspective.isChecked()
        self._presets[name] = preset
        self._save_presets_file()
        self._populate_preset_combo()
        idx = self.combo_preset.findText(name)
        if idx >= 0:
            self.combo_preset.setCurrentIndex(idx)

    def _load_preset(self):
        name = self.combo_preset.currentText()
        if name == "— select preset —" or name not in self._presets:
            return
        p = self._presets[name]
        self.slider_brightness.setValue(p.get("brightness", 0))
        self.slider_contrast.setValue(p.get("contrast", 100))
        self.slider_blur.setValue(p.get("blur", 0))
        self.slider_gamma.setValue(p.get("gamma", 100))
        self.slider_sharpen.setValue(p.get("sharpen", 0))
        self.spin_clahe.setValue(p.get("clahe", 0))
        self.spin_threshold.setValue(p.get("threshold", 25))
        self.spin_max_blob.setValue(p.get("max_blob", 0))
        if "proc_scale" in p:
            v = _migrate_combo_value(p["proc_scale"], _LEGACY_PROC_SCALES, 1.0)
            idx = self.combo_proc_scale.findData(v)
            self.combo_proc_scale.setCurrentIndex(idx if idx >= 0 else 0)
        if "frame_skip" in p:
            self.spin_frame_skip.setValue(int(p["frame_skip"]))
        if "smooth_window" in p and hasattr(self, "spin_smooth_window"):
            self.spin_smooth_window.setValue(int(p["smooth_window"]))
        if "model" in p:
            v = _migrate_combo_value(p["model"], _LEGACY_MODEL_ORDER, "median")
            idx = self.combo_model.findData(v)
            self.combo_model.setCurrentIndex(idx if idx >= 0 else 0)
        if isinstance(p.get("model_params"), dict):
            for m, defaults in DEFAULT_MODEL_PARAMS.items():
                self._model_params[m] = {**defaults, **p["model_params"].get(m, {})}
        if isinstance(p.get("post_params"), dict):
            self._post_params = {**DEFAULT_POST_PARAMS, **p["post_params"]}
        if "body_style" in p:
            v = _migrate_combo_value(p["body_style"], _LEGACY_BODY_STYLES, "dot")
            idx = self.combo_body_style.findData(v)
            self.combo_body_style.setCurrentIndex(idx if idx >= 0 else 1)
        if "ellipse" in p:
            self.chk_ellipse.setChecked(p["ellipse"])
        if "trail" in p:
            self.chk_trail.setChecked(p["trail"])
        if "trail_len" in p:
            self.spin_trail_len.setValue(p["trail_len"])
        if "trail_fade" in p:
            self.chk_trail_fade.setChecked(p["trail_fade"])
        if "brush_radius" in p:
            self.spin_brush.setValue(p["brush_radius"])
        if "overlay_alpha" in p:
            self.overlay_alpha = int(p["overlay_alpha"])
            if self._preview_active:
                self._update_preview()
        if "smooth" in p:
            self.spin_smooth.setValue(p["smooth"])
        if "zone_mode" in p and hasattr(self, "combo_zone_mode"):
            i = self.combo_zone_mode.findData(p["zone_mode"])
            if i >= 0:
                self.combo_zone_mode.setCurrentIndex(i)
        if "cage_shape" in p and hasattr(self, "combo_cage_shape"):
            i = self.combo_cage_shape.findData(p["cage_shape"])
            if i >= 0:
                self.combo_cage_shape.setCurrentIndex(i)
        if "perspective" in p and hasattr(self, "chk_perspective"):
            self.chk_perspective.setChecked(bool(p["perspective"]))
        if isinstance(p.get("colors"), dict):
            self._colors = {**DEFAULT_COLORS, **_upgrade_legacy_colors(dict(p["colors"]))}
            for key, btn in self._color_buttons.items():
                btn.setStyleSheet(
                    f"background-color: {self._colors[key]}; border: 1px solid #555; border-radius: 2px;"
                )
            self.zone_drawer.set_zone_colors(self._colors)
            self.config["colors"] = dict(self._colors)
            win = self.window()
            if hasattr(win, "_save_config"):
                win._save_config()
            self._on_scrub(self.slider_scrub.value())

    def _delete_preset(self):
        name = self.combo_preset.currentText()
        if name == "— select preset —" or name not in self._presets:
            return
        reply = QMessageBox.question(self, "Delete Preset",
                                     f'Delete preset "{name}"?',
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            del self._presets[name]
            self._save_presets_file()
            self._populate_preset_combo()

    # ── Step 5 ────────────────────────────────────────────────────────────

    def _update_run_button(self):
        ready = self.video_path is not None and self.zone_drawer.arena is not None
        self.set_step_status("analysis", "ok" if ready else "blocked")

    def _on_tracking_preview(self, frame):
        self.zone_drawer.set_frame(frame)

    def _on_tracking_body_pos(self, body_xy):
        """Live tracker emits per-frame body pixel coords. Updates the cell
        highlight + accumulates per-cell time + de-bounced entries."""
        # Live cell overlay defaults OFF for speed. Skip all cell math and
        # repaints during the run — same data is recomputed on scrub later.
        if self._tracking_active and not self._live_cell_overlay:
            return
        zd = self.zone_drawer
        if body_xy is None or not (self.video_w and self.video_h):
            zd.set_body_pos_norm(None)
            return
        x_px, y_px = body_xy
        zd.set_body_pos_norm((x_px / float(self.video_w),
                               y_px / float(self.video_h)))
        cid = zd._current_cell_id()
        if cid is None:
            return
        fps = self.fps or 30.0
        dt = 1.0 / fps
        min_dwell = self._cell_min_dwell_s()
        min_frames = max(1, int(round(min_dwell * fps))) if min_dwell > 0 else 1
        # Track how long the body has been in the current "pending" cell.
        if cid == getattr(self, "_live_pending_cid", None):
            self._live_pending_frames = getattr(self, "_live_pending_frames", 0) + 1
        else:
            # Cell changed before confirmation — discard the brief visit.
            self._live_pending_cid = cid
            self._live_pending_frames = 1
        if self._live_pending_frames < min_frames:
            return  # not yet confirmed; don't touch time or entries
        # Confirmed.
        if cid != getattr(self, "_live_confirmed_cid", None):
            # Just confirmed — count one entry, flush all the pending dwell
            # into the time bucket at once.
            self._live_cell_entries[cid] = (
                self._live_cell_entries.get(cid, 0) + 1
            )
            zd.set_cell_entries(self._live_cell_entries)
            self._live_cell_times[cid] = (
                self._live_cell_times.get(cid, 0.0)
                + self._live_pending_frames * dt
            )
            self._live_confirmed_cid = cid
        elif self._live_pending_frames == min_frames:
            # Re-entry to the same confirmed cell just crossed the threshold —
            # flush the accumulated pending dwell in one shot (the per-frame
            # branch below only adds dt and would lose min_frames-1 frames).
            self._live_cell_times[cid] = (
                self._live_cell_times.get(cid, 0.0)
                + self._live_pending_frames * dt
            )
        else:
            # Already credited — add this single frame's dwell.
            self._live_cell_times[cid] = (
                self._live_cell_times.get(cid, 0.0) + dt
            )
        zd.set_cell_times(self._live_cell_times)

    def _reload_first_frame(self):
        if self._first_frame_bgr is not None:
            self.zone_drawer.set_frame(self._first_frame_bgr)

    # ── Step 6 ────────────────────────────────────────────────────────────

    def _export(self):
        output_folder = self.config.get("output_folder")
        if not output_folder:
            QMessageBox.warning(self, "No Output Folder",
                                "Go to Settings → Set Output Folder first.")
            return

        px_per_cm = None
        if self.zone_drawer.calib_p1 and self.zone_drawer.calib_p2:
            px_per_cm = self.zone_drawer.get_pixels_per_cm(self.spin_cm.value())

        arena = self.zone_drawer.get_arena_pixels()
        center = self.zone_drawer.get_center_pixels()

        try:
            plugin_settings = self._build_plugin_settings(arena, center)
            metrics, raw_df, bin_df = self.experiment.compute_metrics(
                self.tracking_results, plugin_settings, self.fps, px_per_cm,
            )
            video_name = os.path.splitext(os.path.basename(self.video_path))[0]
            out_path = os.path.join(output_folder, f"{video_name}_open_field.xlsx")
            export_results(
                metrics=metrics,
                raw_df=raw_df,
                output_path=out_path,
                video_name=video_name,
                arena=arena,
                video_size=(self.video_w, self.video_h),
                graph_images=getattr(self, "_graph_png_bytes", None),
                bin_df=bin_df,
                metadata=self._metadata(),
                write_csv=True,
                video_config=(self.experiment.filter_video_config(self.snapshot_settings())
                              if self.experiment is not None
                              else self.snapshot_settings()),
            )
            self.lbl_export.setText(f"Saved:\n{out_path}\n(+ CSV companions)")
            self.lbl_export.setStyleSheet("color:#4CAF50; font-size:11px;")
        except Exception as e:
            QMessageBox.warning(self, "Export Error", str(e))
            self.lbl_export.setStyleSheet("color:#f44336; font-size:11px;")

    # ── exclusion brush ───────────────────────────────────────────────────

    def _on_excl_toggled(self, checked):
        if checked:
            self.btn_fix.setChecked(False)
            self.zone_drawer.set_mode(ZoneDrawer.MODE_EXCLUDE)
            self.btn_clear_excl.setEnabled(True)
        else:
            self.zone_drawer.set_mode(ZoneDrawer.MODE_IDLE)

    def _clear_exclusions(self):
        self.zone_drawer.clear_exclusions()
        if self._preview_active:
            self._update_preview()

    def _on_exclusion_changed(self):
        if self._preview_active:
            self._update_preview()

    # ── manual correction ─────────────────────────────────────────────────

    # ── _on_fix_toggled / _on_correction_click / _clear_fixes /
    #    _apply_smoothing / _on_smooth_changed live in
    #    gui/output/corrections_mixin.py

    def _schedule_narrow_recompute(self, graph_names):
        """Queue a debounced recompute that touches only the given graphs.
        Multiple calls before the timer fires accumulate the union. Pass
        None to demote the next fire to a full recompute."""
        if graph_names is None:
            self._metrics_dirty_pending = None
        elif self._metrics_dirty_pending is not None:
            self._metrics_dirty_pending |= set(graph_names)
        self._metrics_debounce.start()

    def _fire_debounced_recompute(self):
        dirty = self._metrics_dirty_pending
        # Reset for the next batch BEFORE running — guards against any
        # re-entry from inside the recompute path.
        self._metrics_dirty_pending = set()
        if not dirty:
            self._recompute_metrics_and_views()
        else:
            self._recompute_metrics_and_views(dirty=dirty)

    def _refresh_move_threshold_suffix(self):
        """Keep the Move-threshold spinbox suffix in sync with calibration.
        cm/s when scale-bar drawn, px/s otherwise."""
        if not hasattr(self, "spin_movement_thr"):
            return
        try:
            calibrated = bool(self._get_px_per_cm())
        except Exception:
            calibrated = False
        want = " cm/s" if calibrated else " px/s"
        if self.spin_movement_thr.suffix() != want:
            self.spin_movement_thr.setSuffix(want)

    def _recompute_metrics_and_views(self, dirty=None, raw_cols=None,
                                      refresh_tracking_issues=None):
        """Recompute metrics + refresh views.

        dirty=None       → full rebuild (default; safe baseline).
        dirty={"Habituation", ...} → selective: rebuild only the named
            graphs, refresh summary.
        raw_cols=None    → no Raw Data table refresh on the narrow path
            (used by Move threshold / Time bin / Cell dwell — those don't
            change raw_df contents).
        raw_cols=["Zone", "Cell"] → only refresh those columns in the Raw
            Data table (used by arena edits — position/speed columns are
            unchanged, only zone classification flips).
        refresh_tracking_issues=None → auto: rebuild on full pass, skip on
            narrow pass.
        refresh_tracking_issues=True → force rebuild (e.g. arena change
            invalidates the outside-arena detector)."""
        if not self.tracking_results:
            return
        # If a wider event triggered a full recompute while a narrow one
        # was still queued, drop the pending narrow request — the full
        # pass already covers it.
        if dirty is None and hasattr(self, "_metrics_debounce"):
            try:
                self._metrics_debounce.stop()
                self._metrics_dirty_pending = set()
            except Exception:
                pass
        try:
            results, arena, center, px_per_cm = self._graph_data()
            self._refresh_move_threshold_suffix()
            plugin_settings = self._build_plugin_settings(arena, center)
            self.metrics, self.raw_df, self.bin_df = self.experiment.compute_metrics(
                results, plugin_settings, self.fps, px_per_cm,
            )
            if dirty is None:
                self._populate_graph_tab()
                self._populate_excel_tab()
                self._populate_tracking_issues_tab()
            else:
                self._populate_graph_tab(only=dirty)
                self._refresh_summary_table()
                if raw_cols:
                    # Surgical column-only refresh in the Raw Data table —
                    # avoids the ~150ms cost of refilling all 5000 rows.
                    self._refresh_raw_data_columns(raw_cols)
                # Tracking Issues: auto = skip (narrow knobs don't affect
                # its inputs). Caller can force True when they do (arena).
                if refresh_tracking_issues:
                    self._populate_tracking_issues_tab()
        except Exception as e:
            import traceback
            logger.warn(
                f"_recompute_metrics_and_views failed: {e}\n{traceback.format_exc()}",
                source="metrics",
            )
        # Notify outside listeners (batch tab refreshes its cache).
        try:
            self.metrics_changed.emit()
        except Exception:
            pass

    # ── _jump_next_miss / _interpolate_gaps live in
    #    gui/output/corrections_mixin.py

    # ── scrub ─────────────────────────────────────────────────────────────

    def _draw_body_on_frame(self, frame, r, frame_idx=None,
                            body_style=None,
                            draw_ellipse=None, draw_trail=None,
                            trail_len=None, trail_fade=None,
                            results_override=None):
        """Thin wrapper. When override params are None, current widget state
        is used (live preview). Export thread passes explicit flags."""
        from core.tracking.draw import draw_body_overlay
        draw_body_overlay(
            frame, r, frame_idx=frame_idx,
            results=results_override if results_override is not None else self.tracking_results,
            style=body_style if body_style is not None else self.combo_body_style.currentData(),
            do_ellipse=draw_ellipse if draw_ellipse is not None else self.chk_ellipse.isChecked(),
            do_trail=draw_trail if draw_trail is not None else self.chk_trail.isChecked(),
            trail_len=trail_len if trail_len is not None else self.spin_trail_len.value(),
            trail_fade=trail_fade if trail_fade is not None else self.chk_trail_fade.isChecked(),
            color_fn=self._bgr,
        )

    # ── scrub seek / cap cache / slider shortcuts: gui/output/scrub_mixin.py
    # ── output tabs ───────────────────────────────────────────────────────

    def _get_px_per_cm(self):
        mode = self._calib_mode() if hasattr(self, "rb_calib_auto") else None
        if mode == "none":
            return None
        if mode in ("manual", None):
            if self.zone_drawer.calib_p1 and self.zone_drawer.calib_p2:
                pxcm = self.zone_drawer.get_pixels_per_cm(self.spin_cm.value())
                if pxcm:
                    return pxcm
            if mode == "manual":
                return None
        # mode == "auto" or legacy fallback.
        return self._auto_px_per_cm()

    # ── Graph builders + style + SVG/PDF export
    #    → gui/output/graphs_mixin.py

    # ── helpers ───────────────────────────────────────────────────────────

    def _slider_row(self, parent_layout, label, min_v, max_v, default, fmt_fn,
                    step=1):
        row = QHBoxLayout()
        row.setSpacing(2)
        lbl = QLabel(label)
        lbl.setFixedWidth(68)
        lbl.setStyleSheet("font-size:11px;")
        slider = QSlider(Qt.Horizontal)
        slider.setRange(min_v, max_v)
        slider.setValue(default)
        slider.setSingleStep(step)
        slider.setPageStep(max(step, 10))
        val_lbl = QLabel(fmt_fn(default))
        val_lbl.setFixedWidth(38)
        val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        val_lbl.setStyleSheet("font-size:11px;")
        slider.valueChanged.connect(lambda v: val_lbl.setText(fmt_fn(v)))
        slider.valueChanged.connect(self._update_preview)

        # Nudge buttons: ±1 step on either side of the slider.
        def _make_nudge(arrow, delta, tip):
            b = QPushButton(arrow)
            b.setFixedSize(16, 16)
            b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            b.setFocusPolicy(Qt.NoFocus)
            b.setAutoRepeat(True)
            b.setAutoRepeatDelay(300)
            b.setAutoRepeatInterval(60)
            b.setStyleSheet(
                "QPushButton { padding:0; margin:0; font-size:9px; }"
            )
            b.setToolTip(tip)
            b.clicked.connect(
                lambda _=False, s=slider, d=delta: s.setValue(
                    max(s.minimum(), min(s.maximum(), s.value() + d))
                )
            )
            return b

        btn_dec = _make_nudge("◀", -step, f"Decrease by {step}")
        btn_inc = _make_nudge("▶", +step, f"Increase by {step}")

        row.addWidget(lbl)
        row.addWidget(btn_dec)
        row.addWidget(slider)
        row.addWidget(btn_inc)
        row.addWidget(val_lbl)
        parent_layout.addLayout(row)
        return slider, val_lbl

    def _group(self, title, status_id=None, optional=False):
        g = QGroupBox()
        g.setFont(QFont("Arial", 9, QFont.Bold))
        g.setCheckable(True)
        g.setChecked(True)
        g._base_title = title
        g._status_id = status_id
        g._optional = optional
        # Optional steps default to neutral; required steps start blocked
        # until their gating condition is met.
        g._status = "warn" if optional else "blocked"
        self._update_group_title(g)
        g.setStyleSheet(
            "QGroupBox {"
            "  margin-top: 14px;"
            "  border: 1px solid #555;"
            "  border-radius: 4px;"
            "  padding: 8px 6px 6px 6px;"
            "}"
            "QGroupBox:!checked {"
            "  border: 1px solid transparent;"
            "  padding: 0px;"
            "}"
            "QGroupBox::title {"
            "  subcontrol-origin: margin;"
            "  subcontrol-position: top left;"
            "  left: 8px;"
            "  padding: 0 6px;"
            "}"
            "QGroupBox::indicator { width: 0px; height: 0px; margin: 0; }"
        )
        g.toggled.connect(lambda checked, gb=g: self._toggle_group(gb, checked))
        if status_id:
            if not hasattr(self, "_step_groups"):
                self._step_groups = {}
            self._step_groups[status_id] = g
        return g

    @staticmethod
    def _status_glyph(status):
        return {"ok": "✓", "warn": "⚠", "blocked": "✗"}.get(status, "")

    def _update_group_title(self, gb):
        arrow = "▼" if gb.isChecked() else "▶"
        glyph = self._status_glyph(getattr(gb, "_status", ""))
        parts = [arrow]
        if glyph:
            parts.append(glyph)
        parts.append(gb._base_title)
        title = "  ".join(parts)
        if getattr(gb, "_optional", False):
            title += "  (optional)"
        gb.setTitle(title)

    def set_step_status(self, step_id, status):
        if not hasattr(self, "_step_groups"):
            return
        gb = self._step_groups.get(step_id)
        if gb is None:
            return
        gb._status = status
        self._update_group_title(gb)

    def _toggle_group(self, gb, checked):
        self._update_group_title(gb)
        for child in gb.children():
            if isinstance(child, QWidget):
                child.setVisible(checked)
        if checked:
            gb.setMaximumHeight(16777215)
        else:
            # Title sits in the margin area; padding/border collapse via CSS.
            gb.setMaximumHeight(gb.fontMetrics().height() + 6)

    def _sep(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Plain)
        line.setStyleSheet("color:#444; background-color:#444; max-height:1px;")
        return line

    @staticmethod
    def _btn(label, width=None):
        b = QPushButton(label)
        b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        b.setFixedHeight(24)
        if width:
            b.setFixedWidth(width)
        return b

    @staticmethod
    def _row(*widgets):
        row = QHBoxLayout()
        for w in widgets:
            row.addWidget(w)
        row.addStretch()
        return row
