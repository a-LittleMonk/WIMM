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
import math
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

from core.app_paths import PRESETS_PATH, ensure_dir as _ensure_dir   # inside the app folder
_TUNING_RESET = 2   # Model-tuning dialog result: Reset pressed (reopen with new values)
# Reserved combo entries — never stored as real entries in self._presets.
DEFAULT_PRESET_NAME = "Default"


from gui import theme


class _FitLabel(QLabel):
    """QLabel that scales its source pixmap to its widget size while
    preserving aspect ratio. Re-fits on every resize."""
    def __init__(self):
        super().__init__()
        self._src = None
        self.setMinimumSize(1, 1)
        self.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
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
    "body":         "#F70004",      # body marker: red filled dot
    "nose":         "#5DBB85",
    "tail":         "#A9B4C6",
    "arena":        "#A9B4C6",
    "center_zone":  "#C9D1DE",
    "grid":         "#7F8A9C",
    "detection":    "#D64034",
    "trail":        "#E4D3AE",
}

# Defaults of the previous look — a saved colour that still equals one of
# these was never customised, so it is dropped and picks up the new default.
_OLD_DEFAULT_COLORS = {
    "body": "#A00000", "nose": "#00C800", "tail": "#0064C8",
    "arena": "#3CA0FF", "center_zone": "#3CDC64", "grid": "#96C8FF",
    "detection": "#8C0000",
}


def _upgrade_legacy_colors(d):
    """Migrate older configs:
    - 'center' → 'center_zone' rename
    - drop obsolete 'tail_attach' key (legacy appendage marker — current
      'tail' key is the caudal endpoint of the body axis, not the same)
    - colours still at the previous defaults → new redesign defaults
    Mutates and returns d."""
    if isinstance(d, dict):
        if "center" in d and "center_zone" not in d:
            d["center_zone"] = d.pop("center")
        d.pop("tail_attach", None)
        for key, old in _OLD_DEFAULT_COLORS.items():
            if str(d.get(key, "")).upper() == old.upper():
                d.pop(key, None)
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
        # Set once a video's own saved settings are applied — those win
        # over the remembered Detection preset at start-up.
        self._settings_applied = False
        self._build_ui()
        QTimer.singleShot(0, self._restore_last_preset)
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
            # Values the launcher used to store before it matched this combo.
            gbs = {"dots": "dot", "skeleton": "ends", "dots+skeleton": "ends"}.get(gbs, gbs)
            if gbs is not None and hasattr(self, "combo_body_style"):
                i = self.combo_body_style.findData(gbs)
                if i >= 0:
                    self.combo_body_style.setCurrentIndex(i)
        except Exception as e:
            logger.warn(f"body_style init failed: {e}", source="ui")
        self._apply_simple_mode()
        # Remembered View settings. Deferred one tick so experiment
        # subclasses (NOR picks "Center + nose + tail") set their defaults
        # first; a saved choice then wins.
        self._view_save_timer = QTimer(self)
        self._view_save_timer.setSingleShot(True)
        self._view_save_timer.setInterval(300)
        self._view_save_timer.timeout.connect(self._save_view_prefs)
        self._view_prefs_ready = False
        QTimer.singleShot(0, self._init_view_prefs)

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
            "low_contrast": bool(self.chk_low_contrast.isChecked()),
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
            "marker_shape": self.combo_marker_shape.currentData() or "dot",
            "marker_size":  int(self.spin_marker_size.value()),
            "marker_tag":   self.chk_marker_tag.isChecked(),
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
        # The test's own per-video state (arm shapes, objects, template
        # handles …) so switching videos can put it back (apply_settings).
        if exp is not None and hasattr(exp, "snapshot_extras"):
            try:
                for k, v in (exp.snapshot_extras(self) or {}).items():
                    out.setdefault(k, v)
            except Exception as e:
                # Without them the test's own shapes (arms, objects …) are not
                # saved and the previous video's would be reused — fail loudly.
                logger.error(f"snapshot_extras failed ({getattr(exp, 'key', '?')}): {e}",
                             source="plugin")
                raise
        if exp is not None and hasattr(exp, "contribute_to_snapshot"):
            try:
                exp.contribute_to_snapshot(self, out)
            except Exception as e:
                logger.error(f"contribute_to_snapshot failed "
                             f"({getattr(exp, 'key', '?')}): {e}",
                             source="plugin")
                raise
        return out

    def apply_settings(self, s: dict):
        if not isinstance(s, dict):
            return
        self._settings_applied = True
        # Block signals on widgets whose handlers mutate cross-video state or
        # touch disk while we're swapping in the new video's settings.
        # Some widgets are OF-only (perspective, zone-mode, cage-shape,
        # center-%); skip them when the experiment didn't build them.
        _candidate_block = [
            "chk_perspective", "combo_zone_mode", "combo_cage_shape",
            "combo_proc_scale", "combo_model", "combo_body_style",
            "combo_marker_shape", "spin_marker_size", "chk_marker_tag",
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
        self._apply_view_prefs()
        # The test's own state for this video (Y-Maze / EPM arms, NOR
        # objects, box zones …) — before, switching videos kept showing the
        # previous video's shapes and then saved them over this one's.
        exp = getattr(self, "experiment", None)
        if exp is not None and hasattr(exp, "apply_extras"):
            try:
                exp.apply_extras(self, s)
            except Exception as e:
                # caller (_load_into_embedded) reports it and keeps the old video
                logger.error(f"apply_extras failed ({getattr(exp, 'key', '?')}): {e}",
                             source="plugin")
                raise
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
        self.chk_low_contrast.setChecked(bool(s.get("low_contrast", False)))
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
        self._apply_marker_settings(s)
        self.chk_ellipse.setChecked(s.get("ellipse", False))
        self.chk_trail.setChecked(s.get("trail", True))
        self.spin_trail_len.setValue(s.get("trail_len", 0))
        self.chk_trail_fade.setChecked(s.get("trail_fade", True))
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
                zd.set_perspective_corners_editable(True)
                self._perspective_on = True
                # Coordinate space becomes the warp target (matters for
                # square cage with non-square video).
                self._native_video_size = (self.video_w, self.video_h)
                target = self._warp_target_size()
                if target:
                    self.video_w, self.video_h = target
            else:
                self._original_arena = None
                self._perspective_on = False
                zd.set_perspective_locked(False)
                zd.set_perspective_corners_editable(False)
        else:
            self._original_arena = None
            self._H = None
            self._perspective_on = False
            zd.set_perspective_locked(False)
            zd.set_perspective_corners_editable(False)

    # ── _open_corrections_popup lives in gui/output/corrections_mixin.py

    def _apply_marker_settings(self, s):
        """Body-marker shape / size / info tag from a settings snapshot."""
        if "marker_shape" in s:
            i = self.combo_marker_shape.findData(s["marker_shape"])
            if i >= 0:
                self.combo_marker_shape.setCurrentIndex(i)
        if "marker_size" in s:
            self.spin_marker_size.setValue(int(s["marker_size"]))
        if "marker_tag" in s:
            self.chk_marker_tag.setChecked(bool(s["marker_tag"]))
        self.zone_drawer.set_layer("marker", self.chk_marker_tag.isChecked()
                                   and self.combo_body_style.currentData() != "off")

    def _on_body_marker_changed(self, *_):
        """Body marker style / shape / size / info tag changed."""
        zd = getattr(self, "zone_drawer", None)
        if zd is not None:
            # The Qt info tag is only shown with a visible marker.
            zd.set_layer("marker", self.chk_marker_tag.isChecked()
                         and self.combo_body_style.currentData() != "off")
        legend = getattr(self, "_video_legend", None)
        if legend is not None:
            legend.update()
        if hasattr(self, "slider_scrub"):
            self._on_scrub(self.slider_scrub.value())

    # ── Remembered View settings ─────────────────────────────────────────
    # Stored per experiment in the app config under "view_prefs". They are
    # display choices, so they win over the overlay values saved with each
    # video's settings snapshot.

    def _view_prefs_key(self):
        return getattr(getattr(self, "experiment", None), "key", None) or "default"

    def _live_config_owner(self):
        """Object holding the app's real config dict + _save_config. Inside
        a batch tab this tab is parent-less with a *copy* of the config, so
        go through the batch tab's back-ref; otherwise use the window."""
        for owner in (getattr(self, "_batch_owner", None), self.window()):
            if owner is not None and isinstance(getattr(owner, "config", None), dict)                     and owner is not self:
                return owner
        return None

    def _persist_config(self, key, value):
        """Write to this tab's config AND the app's real config, then save
        it to disk."""
        self.config[key] = value
        owner = self._live_config_owner()
        if owner is None:
            return
        owner.config[key] = value
        for target in (owner, owner.window()):
            if hasattr(target, "_save_config"):
                target._save_config()
                return

    def _collect_view_prefs(self):
        zd = self.zone_drawer
        chrome = getattr(self, "_chrome", None)
        return {
            "arena":        bool(zd.layers.get("arena", True)),
            "zones":        bool(zd.layers.get("zones", True)),
            "heat":         bool(chrome.layers.want_heat) if chrome else False,
            "trail":        self.chk_trail.isChecked(),
            "trail_seg":    int(getattr(self, "_trail_seg_idx", 0)),
            "trail_fade":   self.chk_trail_fade.isChecked(),
            "ellipse":      self.chk_ellipse.isChecked(),
            "body_style":   self.combo_body_style.currentData() or "dot",
            "marker_shape": self.combo_marker_shape.currentData() or "dot",
            "marker_size":  int(self.spin_marker_size.value()),
            "marker_tag":   self.chk_marker_tag.isChecked(),
            "body_color":   self._colors.get("body"),
            "cell_hl_color": zd._cell_highlight_color,
            "cell_hl_alpha": int(zd._cell_highlight_alpha),
            "cell_numbers": bool(zd._cell_show_numbers),
            "cell_timer":   bool(zd._cell_show_timer),
            "cell_entries": bool(zd._cell_show_entries),
            "play_speed":   float(getattr(self, "_play_speed", 1.0)),
        }

    def _stored_view_prefs(self):
        owner = self._live_config_owner()
        src = owner.config if owner is not None else self.config
        allp = src.get("view_prefs") or self.config.get("view_prefs") or {}
        p = allp.get(self._view_prefs_key())
        return p if isinstance(p, dict) else None

    def _apply_view_prefs(self, p=None):
        """Re-apply the remembered View settings (no-op if none saved)."""
        if not getattr(self, "_view_prefs_ready", False) and p is None:
            return
        p = p if p is not None else self._stored_view_prefs()
        if not p:
            return
        zd = self.zone_drawer
        chrome = getattr(self, "_chrome", None)
        if chrome is not None:
            chrome.layers.want_heat = bool(p.get("heat", False))
            for k in ("arena", "zones"):
                if k in p:
                    chrome.layers.set_chip(k, p[k])
            chrome.layers.refresh_enabled()
        if "trail" in p:
            self.chk_trail.setChecked(bool(p["trail"]))
        if "trail_fade" in p:
            self.chk_trail_fade.setChecked(bool(p["trail_fade"]))
        if "ellipse" in p:
            self.chk_ellipse.setChecked(bool(p["ellipse"]))
        i = self.combo_body_style.findData(p.get("body_style"))
        if i >= 0:
            self.combo_body_style.setCurrentIndex(i)
        self._apply_marker_settings(p)
        if p.get("body_color"):
            self._colors["body"] = p["body_color"]
            btn = self._color_buttons.get("body")
            if btn is not None:
                btn.setStyleSheet(
                    f"background-color: {p['body_color']}; border: 1px solid rgba(0,0,0,0.18); border-radius: 2px;")
        if p.get("cell_hl_color"):
            zd.set_cell_highlight_color(p["cell_hl_color"])
        if "cell_hl_alpha" in p:
            zd.set_cell_highlight_alpha(int(p["cell_hl_alpha"]))
        for key, setter in (("cell_numbers", zd.set_cell_show_numbers),
                            ("cell_timer", zd.set_cell_show_timer),
                            ("cell_entries", zd.set_cell_show_entries)):
            if key in p:
                setter(bool(p[key]))
        if p.get("play_speed") in self.PLAY_SPEEDS:
            self._play_speed = float(p["play_speed"])
            self.seg_play_speed.set_index(self.PLAY_SPEEDS.index(self._play_speed))
        self._trail_seg_idx = int(p.get("trail_seg", 0))
        seg = getattr(self, "_trail_seg", None)
        if seg is not None:
            seg.set_index(self._trail_seg_idx)
        self._sync_trail_len()
        legend = getattr(self, "_video_legend", None)
        if legend is not None:
            legend.update()
        if hasattr(self, "slider_scrub"):
            self._on_scrub(self.slider_scrub.value())

    def _init_view_prefs(self):
        self._view_prefs_ready = True
        self._apply_view_prefs()
        for sig in (self.combo_body_style.currentIndexChanged,
                    self.combo_marker_shape.currentIndexChanged,
                    self.spin_marker_size.valueChanged,
                    self.chk_marker_tag.toggled, self.chk_ellipse.toggled,
                    self.chk_trail.toggled, self.chk_trail_fade.toggled,
                    self.zone_drawer.view_changed):
            sig.connect(self._schedule_view_save)
        # Any save queued while applying is just the same values again.
        self._view_save_timer.stop()

    def _schedule_view_save(self, *_):
        if getattr(self, "_view_prefs_ready", False):
            self._view_save_timer.start()

    def _save_view_prefs(self):
        owner = self._live_config_owner()
        src = owner.config if owner is not None else self.config
        allp = dict(src.get("view_prefs") or {})
        allp[self._view_prefs_key()] = self._collect_view_prefs()
        self._persist_config("view_prefs", allp)

    def _sync_trail_len(self):
        """Trail "60 s" / "10 s" → frames at this video's fps."""
        idx = int(getattr(self, "_trail_seg_idx", 0))
        if not hasattr(self, "spin_trail_len"):
            return
        fps = float(self.fps or 30.0)
        self.spin_trail_len.setValue((0, int(fps * 60), int(fps * 10))[max(0, min(2, idx))])

    def _open_view_popup(self):
        """Open the View popover (overlay options) on the video canvas."""
        chrome = getattr(self, "_chrome", None)
        if chrome is not None:
            chrome._open_view()

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
            f"background-color: {self._colors[key]}; border: 1px solid rgba(0,0,0,0.18); border-radius: 2px;"
        )
        btn.setToolTip(f"Click to change {key} color")
        btn.clicked.connect(lambda _=False, k=key: self._pick_color(k))
        self._color_buttons[key] = btn
        return btn

    ZONE_COLOR_PRESETS = [
        "#E0695E", "#E8A87C", "#E8C547", "#5DBB85", "#7FD1D9",
        "#7FA6D9", "#A98BD9", "#D36BA6", "#FFFFFF", "#A9B4C6",
    ]

    def _open_zone_colors_dialog(self, start_key="arena"):
        self._open_colors_dialog(
            (("arena", "Arena"), ("center_zone", "Center Zone"), ("grid", "Grid")),
            "Zone Colors", start_key=start_key,
        )

    def _open_dot_colors_dialog(self):
        keys = (("body", "Body"),)
        self._open_colors_dialog(keys, "Dot Colors")

    def _open_colors_dialog(self, keys, title, start_key=None):
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
                border = f"2px solid {theme.ACCENT}" if kk == current_key[0] else "1px solid rgba(0,0,0,0.18)"
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
                f"background-color: {hex_c}; border: 1px solid rgba(0,0,0,0.18); border-radius: 3px;"
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

        select(start_key if start_key in dict(keys) else first_key)
        accepted = dlg.exec_() == QDialog.Accepted
        if not accepted:
            for k, hex_c in backup.items():
                self._apply_color_live(k, QColor(hex_c))
        self._persist_config("colors", dict(self._colors))
        self._schedule_view_save()

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
        if key == "detection":
            self._persist_config("overlay_alpha", self.overlay_alpha)
        self._persist_config("colors", dict(self._colors))
        self._schedule_view_save()

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
                f"background-color: {hex_str}; border: 1px solid rgba(0,0,0,0.18); border-radius: 2px;"
            )
        if key == "body" and getattr(self, "_video_legend", None) is not None:
            self._video_legend.update()
        if key in ("arena", "center_zone", "grid"):
            self.zone_drawer.set_zone_colors(self._colors)
            if getattr(self, "_zone_chips", None) is not None:
                self._zone_chips.update()        # button swatches
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
            theme.set_tone(lbl, "text2", "font-size:11px;")
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
        v.addStretch(1)      # extra height goes below the rows, not between them

        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        # Reset goes back to the selected Detection preset's values for this
        # model when that preset has them, else to the built-in defaults.
        sel = self._selected_preset() or {}
        preset_model = (sel.get("model_params") or {}).get(model)
        preset_post = sel.get("post_params")
        from_preset = isinstance(preset_model, dict) or isinstance(preset_post, dict)
        reset_btn = QPushButton("Reset to preset" if from_preset else "Reset defaults")
        reset_btn.setToolTip(
            f"Back to the values saved in preset “{self.combo_preset.currentText()}”"
            if from_preset else "Back to the built-in default values")
        reset_btn.setFixedHeight(24)
        reset_btn.setFixedWidth(120)
        ok_btn = QPushButton("OK")
        ok_btn.setFixedHeight(24)
        ok_btn.setFixedWidth(70)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(24)
        cancel_btn.setFixedWidth(70)

        def do_reset():
            self._model_params[model] = {**DEFAULT_MODEL_PARAMS[model],
                                         **(preset_model if isinstance(preset_model, dict) else {})}
            self._post_params = {**DEFAULT_POST_PARAMS,
                                 **(preset_post if isinstance(preset_post, dict) else {})}
            # Close with a dedicated code (not Accepted): the old field
            # values must NOT be written back over the reset — that used to
            # undo every Reset. The dialog reopens below with the new values.
            dlg.done(_TUNING_RESET)

        reset_btn.clicked.connect(do_reset)
        ok_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        outer.addLayout(btn_row)

        # Fit the dialog to its rows (scrolls only when they don't fit).
        m = outer.contentsMargins()
        fit_h = (host.sizeHint().height() + btn_row.sizeHint().height()
                 + outer.spacing() + m.top() + m.bottom())
        dlg.resize(440, min(fit_h, 520))
        result = dlg.exec_()
        if result == QDialog.Accepted:
            for (store, key), getter in getters.items():
                if store == "model":
                    self._model_params[model][key] = getter()
                else:
                    self._post_params[key] = getter()
            self._save_tuning_to_config()
        elif result == _TUNING_RESET:
            self._save_tuning_to_config()
            self._open_model_tuning_dialog()      # show the reset values

    def _save_tuning_to_config(self):
        self._persist_config("model_params", {m: dict(p) for m, p in self._model_params.items()})
        self._persist_config("post_params", dict(self._post_params))

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

    @staticmethod
    def _card_open(w):
        """False when `w` lives inside a collapsed accordion card."""
        from gui.step_card import StepGroup
        p = w.parentWidget()
        while p is not None:
            if isinstance(p, StepGroup):
                return p.isChecked()
            p = p.parentWidget()
        return True

    def _apply_simple_mode(self):
        show = not self._simple_mode  # advanced shown only in Full
        for w in getattr(self, "_advanced_widgets", []):
            try:
                w.setVisible(show and self._card_open(w))
            except RuntimeError:
                # Widget already deleted by Qt; drop silently.
                pass

    # ── Redesign panels: transport / speed timeline / measurements ─────────

    def _toggle_play(self):
        if self._play_timer.isActive():
            self._play_timer.stop()
            self.btn_play.set_icon_name("play")
            return
        if not self.slider_scrub.isEnabled():
            return
        if self.slider_scrub.value() >= self.slider_scrub.maximum():
            self.slider_scrub.setValue(self.slider_scrub.minimum())
        self._play_anchor()
        self._play_timer.start(10)
        self.btn_play.set_icon_name("pause")

    PLAY_SPEEDS = (0.5, 1.0, 1.5, 2.0)

    def _play_anchor(self):
        """Clock-based playback: remember when / where playing (re)started."""
        import time
        self._play_t0 = time.perf_counter()
        self._play_f0 = self.slider_scrub.value()
        self._play_last = self._play_f0

    def _on_play_speed(self, i):
        self._play_speed = self.PLAY_SPEEDS[i]
        if self._play_timer.isActive():
            self._play_anchor()
        self._schedule_view_save()

    def _play_tick(self):
        """Show the frame the clock says we should be on. If drawing falls
        behind, frames are skipped so playback keeps true speed."""
        import time
        cur = self.slider_scrub.value()
        if cur >= self.slider_scrub.maximum():
            self._play_timer.stop()
            self.btn_play.set_icon_name("play")
            return
        if cur != getattr(self, "_play_last", cur):
            self._play_anchor()          # user stepped / seeked meanwhile
        fps = float(self.fps or 30.0)
        speed = float(getattr(self, "_play_speed", 1.0))
        target = self._play_f0 + int((time.perf_counter() - self._play_t0) * fps * speed)
        if target <= cur:
            return
        target = min(self.slider_scrub.maximum(), target)
        self._play_last = target
        self.slider_scrub.setValue(target)

    def _sync_redesign_reset(self):
        """Video cleared / results dropped: blank the redesign panels."""
        try:
            if self._play_timer.isActive():
                self._play_timer.stop()
                self.btn_play.set_icon_name("play")
            for b in (self.btn_step_first, self.btn_step_prev, self.btn_play,
                      self.btn_step_next, self.btn_step_last):
                b.setEnabled(False)
            self.lbl_frame.setText("")
            self.measure_panel.clear()
            # Drop the previous video's issue marks / count.
            self._issues_df = None
            self._refresh_issue_marks()
            if self._issues_popup is not None:
                self._issues_popup.hide()
        except Exception:
            pass

    def _speed_col(self):
        df = getattr(self, "raw_df", None)
        if df is None:
            return None, ""
        for c in df.columns:
            if str(c).startswith("Speed ("):
                return c, str(c)[7:-1] if str(c).endswith(")") else "cm/s"
        return None, ""

    def _refresh_redesign_data(self):
        """Feed the session sidebar from the latest results."""
        try:
            has = bool(self.tracking_results)
            for b in (self.btn_step_first, self.btn_step_prev, self.btn_play,
                      self.btn_step_next, self.btn_step_last):
                b.setEnabled(self.slider_scrub.isEnabled())
            self.btn_export.setEnabled(has)
            if not has:
                self.measure_panel.clear()
                return
            n = len(self.tracking_results)
            xs = [r.get("x") is not None for r in self.tracking_results]
            self._refresh_heat()
            dur = n / float(self.fps or 30.0)
            det_rate = 100.0 * sum(1 for x in xs if x) / float(n)
            self.measure_panel.set_session(self.metrics, dur,
                                           extra=[("Detection rate", f"{det_rate:.1f}", "%")])
            self._refresh_occupancy(dur)
            self._sync_redesign(self.slider_scrub.value())
        except Exception as e:
            logger.warn(f"redesign panel refresh failed: {e}", source="ui")

    def _sync_redesign(self, value=None):
        """Per-scrub update: playhead, frame label and current-frame readout."""
        try:
            if value is None:
                value = self.slider_scrub.value()
            lo, hi = self.slider_scrub.minimum(), self.slider_scrub.maximum()
            self.lbl_frame.setText(f"{int(value)} / {int(hi)}")
            if not self.tracking_results or self.raw_df is None:
                self.measure_panel.set_frame(None)
                self.zone_drawer.set_marker_info(None)
                return
            i = self._slider_to_results_idx(value)
            df = self.raw_df
            if i >= len(df):
                return
            fps = float(self.fps or 30.0)
            s = int(i / fps)
            tm = f"{s // 60:02d}:{s % 60:02d}.{int((i / fps % 1) * 10)}"
            r = self.tracking_results[i]
            det = r.get("x") is not None
            pxcm = self._get_px_per_cm()
            if det:
                if pxcm:
                    pos, pu = f"{r['x'] / pxcm:.1f}, {r['y'] / pxcm:.1f}", "cm"
                else:
                    pos, pu = f"{r['x']:.0f}, {r['y']:.0f}", "px"
            else:
                pos, pu = "—", ""
            col, unit = self._speed_col()
            sp = df[col].iloc[i] if col is not None else float("nan")
            sp_txt = "—" if sp != sp else f"{sp:.1f}"
            zone = str(df["Zone"].iloc[i]) if "Zone" in df.columns else "—"
            zone = zone.replace("_", " ")
            step_col = next((c for c in df.columns if str(c).startswith("Step Distance")), None)
            cum_txt, cum_unit, cum_frac = "—", "", 0.0
            if step_col is not None:
                steps = np.nan_to_num(df[step_col].to_numpy(dtype=float))
                cs = np.cumsum(steps)
                tot = float(cs[-1]) if len(cs) else 0.0
                in_cm = "cm" in str(step_col)
                div = 100.0 if in_cm else 1.0
                cum_txt = f"{cs[i] / div:.2f}"
                cum_unit = "m" if in_cm else "px"
                cum_frac = (cs[i] / tot) if tot > 0 else 0.0
            if det and self.video_w and self.video_h:
                aid = self.edit_meta_id.text().strip() or "—"
                xy = pos.replace(",", " ").split() if pu else []
                self.zone_drawer.set_marker_info({
                    "norm": (r["x"] / float(self.video_w), r["y"] / float(self.video_h)),
                    "lines": [f"{aid} · {sp_txt} {unit}".strip(),
                              (f"x {xy[0]}  y {xy[1]}" if len(xy) == 2 else "")],
                })
            else:
                self.zone_drawer.set_marker_info(None)
            # heading from the recent displacement (or nose→tail when known)
            heading = None
            if det:
                nx, ny = r.get("nose_x"), r.get("nose_y")
                tx, ty = r.get("tail_x"), r.get("tail_y")
                if nx is not None and tx is not None:
                    heading = (-math.degrees(math.atan2(ny - ty, nx - tx))) % 360.0
                else:
                    for j in range(max(0, i - 3), i):
                        pr = self.tracking_results[j]
                        if pr.get("x") is not None:
                            dx, dy = r["x"] - pr["x"], r["y"] - pr["y"]
                            if (dx * dx + dy * dy) ** 0.5 > 0.5:
                                heading = (-math.degrees(math.atan2(dy, dx))) % 360.0
                            break
            thr = float(self.spin_movement_thr.value()) if hasattr(self, "spin_movement_thr") else 0.0
            moving = (sp > thr) if (sp == sp and thr > 0) else None
            win = None
            if col is not None:
                vals = np.nan_to_num(df[col].to_numpy(dtype=float))
                nw = max(2, int(30 * fps))
                w0, w1 = max(0, i - nw), min(len(vals) - 1, i + nw)
                if w1 > w0:
                    stp = max(1, (w1 - w0) // 120)
                    seg = vals[w0:w1 + 1:stp]
                    win = {"values": [float(x) for x in seg], "max": float(seg.max()),
                           "mid": (i - w0) / float(w1 - w0)}
            self.measure_panel.set_frame({
                "time": tm, "pos": pos, "pos_unit": pu, "speed": sp_txt,
                "speed_unit": unit, "zone": zone, "detected": det,
                "zone_center": "center" in zone.lower(),
                "heading": heading, "moving": moving, "window": win,
                "conf": (float(r["nose_confidence"]) if r.get("nose_confidence") is not None else None),
                "cum": cum_txt, "cum_unit": cum_unit, "cum_frac": cum_frac,
            })
        except Exception as e:
            logger.warn(f"redesign frame sync failed: {e}", source="ui")
    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidget(self._build_controls())
        scroll.setWidgetResizable(True)
        # As-needed: if the pane is ever narrower than its content the user
        # can scroll instead of losing controls off the edge.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFixedWidth(312)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll, 0)

        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self._build_preview_tab(), "Video Preview")
        self._graph_widget = self._build_graph_tab()
        # Scrollable so its wide tables never force the window wider
        # (a tab widget reserves room for its largest page).
        out_scroll = QScrollArea()
        out_scroll.setWidgetResizable(True)
        out_scroll.setFrameShape(QFrame.NoFrame)
        out_scroll.setWidget(self._build_excel_tab())
        self.right_tabs.addTab(out_scroll, "Excel Output")
        root.addWidget(self.right_tabs, 1)

    def _build_view_popup_widgets(self):
        """Construct the overlay controls shown in the View popover (body
        marker, ellipse, trail, smooth). They live as orphans until the
        popover reparents them. Created here — under the preview-tab
        section — because they belong with the preview / view feature."""
        from gui.widgets_v2 import SwitchBox
        from core.tracking.draw import MARKER_SHAPES
        # Body marker = the one control that decides whether a marker is
        # drawn on the mouse (no separate "Marker" layer chip any more).
        self.combo_body_style = QComboBox()
        self.combo_body_style.addItem("Off", "off")
        self.combo_body_style.addItem("Center", "dot")
        self.combo_body_style.addItem("Center + nose + tail", "ends")
        self.combo_body_style.setCurrentIndex(1)
        self.combo_body_style.currentIndexChanged.connect(self._on_body_marker_changed)

        self.combo_marker_shape = QComboBox()
        for key, label in MARKER_SHAPES:
            self.combo_marker_shape.addItem(label, key)
        self.combo_marker_shape.setCurrentIndex(
            max(0, self.combo_marker_shape.findData("dot")))   # default: filled dot
        self.combo_marker_shape.currentIndexChanged.connect(self._on_body_marker_changed)

        self.spin_marker_size = QSpinBox()
        self.spin_marker_size.setRange(2, 60)
        self.spin_marker_size.setValue(5)
        self.spin_marker_size.setSuffix(" px")
        self.spin_marker_size.setToolTip(
            "Marker radius, in pixels of a 640 px wide video\n"
            "(scaled up for larger videos).")
        self.spin_marker_size.valueChanged.connect(self._on_body_marker_changed)

        self.btn_marker_color = QPushButton()
        self.btn_marker_color.setFixedSize(40, 20)
        self.btn_marker_color.setCursor(Qt.PointingHandCursor)
        self.btn_marker_color.setToolTip("Pick the body-marker color")
        self.btn_marker_color.setStyleSheet(
            f"background-color: {self._colors['body']}; border: 1px solid rgba(0,0,0,0.18); border-radius: 2px;"
        )
        self.btn_marker_color.clicked.connect(lambda: self._pick_color("body"))
        self._color_buttons["body"] = self.btn_marker_color

        self.chk_marker_tag = SwitchBox("Info tag next to marker")
        self.chk_marker_tag.setChecked(True)
        self.chk_marker_tag.setToolTip("Animal ID, speed and position beside the marker.")
        self.chk_marker_tag.toggled.connect(self._on_body_marker_changed)

        self.chk_ellipse = SwitchBox("Bounding ellipse")
        self.chk_ellipse.toggled.connect(lambda: self._on_scrub(self.slider_scrub.value()))
        # Trail on/off: "Show trail" switch in the View popover (Trail & path).
        self.chk_trail = SwitchBox("Show trail")
        self.chk_trail.setChecked(True)
        self.chk_trail.toggled.connect(lambda: self._on_scrub(self.slider_scrub.value()))

        self.spin_trail_len = QSpinBox()
        self.spin_trail_len.setRange(0, 100000)
        self.spin_trail_len.setValue(0)  # "All frames" by default
        self.spin_trail_len.setSuffix(" frames")
        self.spin_trail_len.setSpecialValueText("All frames")
        self.spin_trail_len.setToolTip("Trail length in frames. Set to 0 for full path.")
        self.spin_trail_len.valueChanged.connect(
            lambda: self._on_scrub(self.slider_scrub.value())
        )
        self.chk_trail_fade = SwitchBox("Fade older segments")
        self.chk_trail_fade.setChecked(True)
        self.chk_trail_fade.setToolTip(
            "On: older trail segments dimmer/thinner.\n"
            "Off: solid body-color trail throughout."
        )
        self.chk_trail_fade.toggled.connect(
            lambda: self._on_scrub(self.slider_scrub.value())
        )

        self.spin_smooth = QSpinBox()
        self.spin_smooth.setRange(0, 30)
        self.spin_smooth.setValue(0)
        self.spin_smooth.setSuffix(" frames")
        self.spin_smooth.setSpecialValueText("Off")
        self.spin_smooth.setToolTip(
            "Moving-average window over the body-center track.\n"
            "Reduces frame-to-frame jitter. 0 = off."
        )
        self.spin_smooth.valueChanged.connect(self._on_smooth_changed)

    def _build_preview_tab(self):
        # Build the View popup's overlay widgets first so they're ready
        # before the user clicks View ▾.
        self._build_view_popup_widgets()

        w = QWidget()
        vlay = QVBoxLayout(w)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        self.zone_drawer = ZoneDrawer()
        self.zone_drawer.zones_changed.connect(self._on_zones_changed)
        # Arena corners stay adjustable after perspective correction (only
        # switched on by this tab's own perspective toggle / restore — EPM
        # and Y-Maze lock the drawer with their own warps).
        self.zone_drawer.perspective_corner_dragged.connect(
            self._on_perspective_corner_dragged)
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

        # ── Transport: buttons, time, frame, actions, speed timeline, scrubber
        from gui.widgets_v2 import IconButton, KeyedButton, SegTabs
        from gui.redesign_widgets import TimeTicks
        card = QFrame()
        card.setObjectName("TransportCard")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(14, 10, 14, 10)
        cv.setSpacing(0)

        row1 = QHBoxLayout()
        row1.setSpacing(12)
        grp = QFrame()
        grp.setObjectName("TransportGroup")
        gh = QHBoxLayout(grp)
        gh.setContentsMargins(2, 2, 2, 2)
        gh.setSpacing(2)
        self.btn_step_first = IconButton("first", 12, "TEXT_2", "TEXT", "First frame (Home)", 28)
        self.btn_step_first.clicked.connect(
            lambda: self.slider_scrub.setValue(self.slider_scrub.minimum())
        )
        self.btn_step_prev = IconButton("prev", 12, "TEXT_2", "TEXT",
                                        "Step 1 (←) · Shift 10 · Ctrl 100", 28)
        self.btn_step_prev.clicked.connect(
            lambda: self.slider_scrub.setValue(max(self.slider_scrub.minimum(), self.slider_scrub.value() - 1))
        )
        self.btn_play = IconButton("play", 12, "ON_ACCENT", "ON_ACCENT", "Play / pause (Space)",
                                   28, "primary")
        self.btn_play.setFixedSize(38, 28)
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_step_next = IconButton("next", 12, "TEXT_2", "TEXT", "Step 1 (→)", 28)
        self.btn_step_next.clicked.connect(
            lambda: self.slider_scrub.setValue(min(self.slider_scrub.maximum(), self.slider_scrub.value() + 1))
        )
        self.btn_step_last = IconButton("last", 12, "TEXT_2", "TEXT", "Last frame (End)", 28)
        self.btn_step_last.clicked.connect(
            lambda: self.slider_scrub.setValue(self.slider_scrub.maximum())
        )
        for b in (self.btn_step_first, self.btn_step_prev, self.btn_play,
                  self.btn_step_next, self.btn_step_last):
            b.setEnabled(False)
            gh.addWidget(b)
        row1.addWidget(grp)

        # Playback speed.
        self._play_speed = 1.0
        self.seg_play_speed = SegTabs(["0.5×", "1×", "1.5×", "2×"], current=1)
        self.seg_play_speed.setToolTip("Playback speed")
        self.seg_play_speed.setFixedHeight(28)
        self.seg_play_speed.changed.connect(self._on_play_speed)
        row1.addWidget(self.seg_play_speed)

        self.lbl_scrub = QLabel("—")
        self.lbl_scrub.setProperty("role", "scrub")
        self.lbl_total = QLabel("")
        self.lbl_total.setProperty("role", "scrubtotal")
        tbox = QHBoxLayout()
        tbox.setSpacing(6)
        tbox.addWidget(self.lbl_scrub, 0, Qt.AlignBottom)
        tbox.addWidget(self.lbl_total, 0, Qt.AlignBottom)
        row1.addLayout(tbox)

        fblock = QFrame()
        fblock.setObjectName("FrameBlock")
        fv = QVBoxLayout(fblock)
        fv.setContentsMargins(12, 0, 0, 0)
        fv.setSpacing(1)
        fcap = QLabel("FRAME")
        fcap.setProperty("role", "cellcap")
        self.lbl_frame = QLabel("")
        self.lbl_frame.setProperty("role", "frame")
        fv.addWidget(fcap)
        fv.addWidget(self.lbl_frame)
        row1.addWidget(fblock)
        row1.addStretch(1)

        # Tracking issues: red marks on the frame slider + this popup button.
        self.btn_issues = KeyedButton("Tracking issues", "", lead="dot")
        self.btn_issues.setToolTip("Open the tracking-issues window: every flagged "
                                   "frame, why it was flagged, and fixes")
        self.btn_issues.setEnabled(False)
        self.btn_issues.clicked.connect(self._open_tracking_issues_popup)
        row1.addWidget(self.btn_issues)
        # Next miss (N) and Corrections (Ctrl+K) are keyboard / menu only.
        self.btn_view_popup.hide()   # the View button lives in the canvas toolbar
        cv.addLayout(row1)
        cv.addSpacing(8)
        # Parts hidden one by one when the bar gets narrow (least useful
        # first), so the preview never forces the window to be wide.
        self._transport_row = row1
        self._transport_card = card
        self._transport_droppable = [fblock, self.lbl_total,
                                     self.seg_play_speed, self.btn_issues]
        self._transport_fitting = False
        card.setMinimumWidth(240)
        card.installEventFilter(self)

        from gui.redesign_widgets import IssueSlider
        self.slider_scrub = IssueSlider()   # red marks = tracking issues
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
            "D  toggle Detected area\n"
            "M  toggle Show mask\n"
            "E  toggle View Effects"
        )
        self.slider_scrub.valueChanged.connect(self._on_scrub)
        srow = QHBoxLayout()
        srow.setContentsMargins(0, 2, 0, 0)
        srow.addWidget(self.slider_scrub)
        cv.addLayout(srow)
        self.time_ticks = TimeTicks()
        trow = QHBoxLayout()
        trow.setContentsMargins(0, 2, 0, 0)
        trow.addWidget(self.time_ticks)
        cv.addLayout(trow)
        vlay.addWidget(card)

        self._play_timer = QTimer(self)
        self._play_timer.setTimerType(Qt.PreciseTimer)
        self._play_timer.timeout.connect(self._play_tick)
        # Overlay controls (body style / ellipse / trail / smooth)
        # now live in the configuration pane only.

        # Legend / dot-color controls live in the View popup, not under the
        # video. Built here so the widget exists; the popup re-parents it.
        self._legend_widget = self._build_legend()

        # Floating canvas chrome (tools / layers / View / legend) + sidebar.
        from gui.redesign_widgets import MeasurementsPanel
        from gui.canvas_chrome import attach_canvas_chrome
        attach_canvas_chrome(self)
        self.measure_panel = MeasurementsPanel()
        outer = QWidget()
        oh = QHBoxLayout(outer)
        oh.setContentsMargins(0, 0, 0, 0)
        oh.setSpacing(0)
        oh.addWidget(w, 1)
        oh.addWidget(self.measure_panel)
        return outer

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        if obj is getattr(self, "_transport_card", None) and event.type() == QEvent.Resize:
            self._fit_transport()
        return super().eventFilter(obj, event)

    def _fit_transport(self):
        """Show as many transport parts as fit the bar's current width."""
        card = getattr(self, "_transport_card", None)
        if card is None or self._transport_fitting:
            return
        self._transport_fitting = True
        try:
            row = self._transport_row
            m = card.contentsMargins()
            lm = card.layout().contentsMargins()
            avail = card.width() - m.left() - m.right() - lm.left() - lm.right()
            items = self._transport_droppable
            # Show everything, then drop parts until the row fits.
            for wd in items:
                wd.setHidden(False)
            # btn_issues only shows when it has a reason to (results loaded).
            for wd in items:
                row.invalidate()
                if row.minimumSize().width() <= avail:
                    break
                wd.setHidden(True)
        finally:
            self._transport_fitting = False

    def _build_legend(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(6, 0, 6, 2)
        h.setSpacing(4)
        def lbl(text, tone="faint"):
            l = QLabel(text)
            theme.set_tone(l, tone, "font-size:10px;")
            return l
        h.addWidget(lbl("<b>Dots:</b>", "text2"))
        self.btn_dot_colors = QPushButton("Colors")
        self.btn_dot_colors.setFixedHeight(20)
        self.btn_dot_colors.setFixedWidth(60)
        self.btn_dot_colors.setCursor(Qt.PointingHandCursor)
        self.btn_dot_colors.setToolTip("Pick the body-marker color")
        self.btn_dot_colors.clicked.connect(self._open_dot_colors_dialog)
        h.addWidget(self.btn_dot_colors)
        h.addSpacing(8)
        h.addWidget(lbl("<b>Status:</b>", "text2"))
        h.addWidget(lbl("<span style='color:#E8C547'>■</span> Corrected"))
        h.addSpacing(4)
        h.addWidget(lbl("<span style='color:#D36BA6'>■</span> Interpolated"))
        h.addStretch()
        return w

    # graph name → (panel title, list description)
    _GRAPH_INFO = {
        "Trajectory":      ("Trajectory", "Path · start / end"),
        "Heatmap":         ("Occupancy heatmap", "Occupancy · 2 cm bins"),
        "Cell Time":       ("Time per grid cell", "Grid 4×4 · s per cell"),
        "Speed":           ("Speed over time", "Speed over time"),
        "Speed Histogram": ("Speed distribution", "Distribution · 1 cm/s bins"),
        "Habituation":     ("Habituation", "Distance per time bin"),
        "Zone Time":       ("Zone time", "Center vs periphery"),
        "Triplets":        ("Triplet quality", "Arm-entry triplets"),
    }

    def _build_graph_tab(self):
        from gui.out_widgets import OutPanel
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)

        # hidden data holder: the combo keeps the list of available graphs
        self._combo_graph = QComboBox(w)
        self._combo_graph.hide()
        self._combo_graph.currentIndexChanged.connect(self._on_graph_select)

        # left: graph list
        left = OutPanel()
        left.setMinimumWidth(130)       # shrinks when the preview is narrow
        left.setMaximumWidth(200)
        self._graph_list_lay = QVBoxLayout()
        self._graph_list_lay.setContentsMargins(4, 4, 4, 4)
        self._graph_list_lay.setSpacing(0)
        left.body.addLayout(self._graph_list_lay)
        left.body.addStretch(1)
        self._graph_selector_widget = left
        self._graph_items = []

        self.lbl_graph_hint = QLabel("Run tracking first to see graphical output.")
        self.lbl_graph_hint.setAlignment(Qt.AlignCenter)
        theme.set_tone(self.lbl_graph_hint, "faint", "font-size:12px;")

        # right: figure panel
        right = OutPanel("")
        right.bar.show()
        right.setMaximumWidth(820)
        self._graph_title = right.title
        b_cust = right.add_button("Customize…  Ctrl+G", lambda: self._open_graph_style_dialog())
        b_cust.setToolTip("Edit per-graph colors, widths, labels, colormap, grid, and presets")
        seg = QFrame()
        seg.setObjectName("ExportSeg")
        sh = QHBoxLayout(seg)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.setSpacing(0)
        for ext in ("SVG", "PDF", "PNG"):
            b = QPushButton(ext)
            b.setProperty("segbtn", True)
            b.setFixedHeight(22)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, e=ext.lower(): self._export_graph_fmt(e))
            sh.addWidget(b)
        right._bar_layout.addWidget(seg)
        # Background of exported files + Excel images.
        from gui.graph_style import set_export_bg
        from gui.redesign_widgets import SegmentedControl
        bg_choice = self.config.get("export_bg", "white")
        set_export_bg(bg_choice)
        bg_lbl = QLabel("Export background")
        theme.set_tone(bg_lbl, "faint", "font-size: 11px;")
        right._bar_layout.addSpacing(10)
        right._bar_layout.addWidget(bg_lbl)
        self.seg_export_bg = SegmentedControl(["White", "Transparent"],
                                              1 if bg_choice == "transparent" else 0)
        self.seg_export_bg.setToolTip("Background of saved SVG / PDF / PNG files and Excel images")
        self.seg_export_bg.changed.connect(
            lambda i: self._set_export_bg("transparent" if i else "white"))
        right._bar_layout.addWidget(self.seg_export_bg)

        # Preset strip: which graph-style preset the graphs (on screen and
        # in every export) are drawn with, plus the Export preview popup.
        right.body.addWidget(self._build_graph_preset_bar())

        self._graph_scroll = right          # toggled by _populate_graph_tab
        self._graph_lbl = _FitLabel()
        self._graph_lbl.setMinimumHeight(320)
        self._graph_lbl.setContextMenuPolicy(Qt.CustomContextMenu)
        self._graph_lbl.customContextMenuRequested.connect(
            lambda _pos: self._export_current_graph_dialog()
        )
        self._graph_lbl.setToolTip("Right-click to export as SVG / PDF / PNG.")
        fig_box = QWidget()
        fv = QVBoxLayout(fig_box)
        fv.setContentsMargins(20, 16, 20, 8)
        fv.setSpacing(0)
        fv.addWidget(self._graph_lbl, 1)
        self._graph_caption = QLabel("")
        self._graph_caption.setWordWrap(True)
        self._graph_caption.setObjectName("GraphCaption")
        theme.set_tone(self._graph_caption, "text2", "font-size:11px;")
        fv.addSpacing(8)
        fv.addWidget(self._graph_caption)
        right.body.addWidget(fig_box, 1)
        right.hide()

        col = QVBoxLayout()
        col.addWidget(self.lbl_graph_hint)
        col.addWidget(left)
        hl.addLayout(col, 0)
        hl.addWidget(right, 1)
        left.hide()

        self._graph_pixmaps = {}
        return w

    def _build_graph_preset_bar(self):
        bar = QWidget()
        bar.setObjectName("GraphPresetBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 8, 14, 0)
        h.setSpacing(8)
        lbl = QLabel("Preset")
        theme.set_tone(lbl, "text2", "font-size: 11px;")
        h.addWidget(lbl)

        tab = self

        class _PresetCombo(QComboBox):
            def showPopup(self):            # pick up presets made meanwhile
                tab._fill_graph_preset_combo()
                super().showPopup()

        self.combo_graph_preset = _PresetCombo()
        self.combo_graph_preset.setMinimumWidth(150)
        self.combo_graph_preset.setToolTip(
            "Graph-style preset used for these graphs and for every exported "
            "graph (SVG / PDF / PNG files and Excel images). Make presets in "
            "Customize… (Ctrl+G).")
        self.combo_graph_preset.activated.connect(
            lambda _i: self._choose_graph_preset(self.combo_graph_preset.currentText()))
        h.addWidget(self.combo_graph_preset)
        self.lbl_graph_preset_state = QLabel("")
        h.addWidget(self.lbl_graph_preset_state)
        h.addSpacing(6)
        self.btn_export_preview = QPushButton("Export preview")
        self.btn_export_preview.setFixedHeight(24)
        self.btn_export_preview.setCursor(Qt.PointingHandCursor)
        self.btn_export_preview.setToolTip(
            "Open the selected graph exactly as it will be exported — export "
            "colours and background, independent of light / dark mode")
        self.btn_export_preview.clicked.connect(self._open_export_preview)
        h.addWidget(self.btn_export_preview)
        h.addStretch(1)
        self._fill_graph_preset_combo()
        # set_tone bakes the colour in — re-tone (cheap) when the theme flips.
        theme.notifier.changed.connect(lambda _m: theme.set_tone(
            self.lbl_graph_preset_state, "warn", "font-size: 11px;"))
        return bar

    def _fill_graph_preset_combo(self):
        """Show the active preset (and whether the graphs were changed since)."""
        combo = getattr(self, "combo_graph_preset", None)
        gs = getattr(self, "_graph_style", None)
        if combo is None or gs is None:
            return
        names = gs.all_preset_names()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(names)
        combo.setCurrentText(gs.active_preset)
        combo.blockSignals(False)
        modified = gs.is_modified()
        self.lbl_graph_preset_state.setText("● modified" if modified else "")
        theme.set_tone(self.lbl_graph_preset_state, "warn", "font-size: 11px;")
        self.lbl_graph_preset_state.setToolTip(
            "The graphs were changed in Customize… after this preset was "
            "loaded. Save them as a preset there to keep them." if modified else "")

    def _choose_graph_preset(self, name):
        """Load preset `name` into the graphs and use it for exports too.
        Returns False when the user cancels (unsaved graph changes)."""
        gs = getattr(self, "_graph_style", None)
        if gs is None or not name:
            return False
        if name == gs.active_preset and not gs.is_modified():
            self._fill_graph_preset_combo()
            return True
        if gs.is_modified():
            ans = QMessageBox.question(
                self, "Switch graph preset",
                "Your graph changes are not saved in a preset.\n\n"
                f"Load preset “{name}” and discard them?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                self._fill_graph_preset_combo()
                return False
        gs.apply_preset(name)
        owner = getattr(self, "_batch_owner", None)
        if owner is not None and isinstance(getattr(owner, "config", None), dict):
            owner.config["export_graph_preset"] = name
        self.config["export_graph_preset"] = name
        self._save_graph_style_to_config()
        if owner is not None and hasattr(owner, "_fill_export_presets"):
            owner._fill_export_presets()
        self._fill_graph_preset_combo()
        try:
            if self.raw_df is not None:
                self._populate_graph_tab()
        except Exception as e:
            logger.warn(f"graph preset refresh failed: {e}", source="graphs")
        return True

    def _rebuild_graph_list(self):
        """(Re)create the left-hand graph buttons from the combo entries."""
        lay = self._graph_list_lay
        while lay.count():
            it = lay.takeAt(0)
            wd = it.widget()
            if wd is not None:
                wd.setParent(None)
                wd.deleteLater()
        self._graph_items = []
        for i in range(self._combo_graph.count()):
            name = self._combo_graph.itemText(i)
            title, desc = self._GRAPH_INFO.get(name, (name, ""))
            from gui.widgets_v2 import LayoutButton
            b = LayoutButton()
            b.setProperty("graphitem", True)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            lay_b = QVBoxLayout(b)
            lay_b.setContentsMargins(10, 7, 10, 7)
            lay_b.setSpacing(0)
            t1 = QLabel(name)
            t1.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            t1.setProperty("role", "graphname")
            lay_b.addWidget(t1)
            if desc:
                t2 = QLabel(desc)
                t2.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                t2.setProperty("role", "graphdesc")
                lay_b.addWidget(t2)
            b.clicked.connect(lambda _=False, k=i: self._combo_graph.setCurrentIndex(k))
            lay.addWidget(b)
            self._graph_items.append(b)
        self._sync_graph_panel(self._combo_graph.currentText())

    def _sync_graph_panel(self, name):
        for i, b in enumerate(getattr(self, "_graph_items", [])):
            b.setChecked(i == self._combo_graph.currentIndex())
        title = self._GRAPH_INFO.get(name, (name, ""))[0]
        if hasattr(self, "_graph_title"):
            self._graph_title.setText(title)
            self._graph_caption.setText(self._graph_caption_text(name))

    def _graph_caption_text(self, name):
        m = self.metrics or {}
        fps = float(self.fps or 30.0)
        n = len(self.tracking_results) if self.tracking_results else 0
        dur = n / fps if n else 0.0
        dist = m.get("Total Distance (cm)")
        dims = getattr(self.zone_drawer, "cage_dims_cm", None)
        pct = self.spin_center_pct.value() if hasattr(self, "spin_center_pct") else None
        if name == "Trajectory":
            bits = f"Body-centroid path over {dur:.0f} s"
            if dims:
                bits += f" in a {dims[0]:g} × {dims[1]:g} cm arena"
            bits += "."
            if pct:
                bits += f" Dashed square: center zone ({pct} % of arena side)."
            if isinstance(dist, (int, float)):
                bits += f" Total distance {dist:.1f} cm."
            return bits
        if name == "Heatmap":
            vmax = getattr(self, "_heat_vmax", 0.0)
            return ("Cumulative time per bin, square-root colour scale (viridis)."
                    + (f" Max {vmax:.1f} s per bin." if vmax else ""))
        if name == "Cell Time":
            return "Time spent in each of the 16 grid cells."
        if name == "Speed":
            return ("Instantaneous body-centroid speed. Dashed: movement threshold "
                    "used for mobility / immobility time.")
        if name == "Speed Histogram":
            med, p90, p99 = m.get("Median Speed (cm/s)"), m.get("P90 Speed (cm/s)"), m.get("P99 Speed (cm/s)")
            tail = (f" Median {med}, P90 {p90}, P99 {p99} cm/s." if med is not None else "")
            return "Time spent per speed bin." + tail
        if name == "Habituation":
            b = self.spin_bin_size.value() if hasattr(self, "spin_bin_size") else 0
            return (f"Distance travelled per {b:g} s bin. " if b else "Distance travelled per time bin. ") + \
                   "A negative slope indicates within-session habituation."
        if name == "Zone Time":
            return "Time in the center zone, periphery, and thigmotaxis band."
        return ""

    def _export_graph_fmt(self, ext):
        """SVG / PDF / PNG buttons of the graph panel."""
        name = self._combo_graph.currentText()
        if self.raw_df is None or not name:
            return
        out_folder = self.config.get("output_folder") or ""
        default = os.path.join(out_folder, f"{name}.{ext}") if out_folder else f"{name}.{ext}"
        path, _ = QFileDialog.getSaveFileName(self, f"Export {name}", default,
                                              f"{ext.upper()} (*.{ext})")
        if not path:
            return
        from gui.notify import show_done
        if self._export_graph_to_path(name, path):
            show_done(self, f"{name} graph exported", path=path)
        else:
            show_done(self, "Graph export failed",
                      "Could not write the graph file. See Logs for details.", kind="err")

    # Preset that tags the standard 4×4 layout: corners, edges (perimeter
    # non-corner), middle (inner 2×2).

    def _build_excel_tab(self):
        from gui.out_widgets import OutPanel, SubTabHeader, copy_table_all, padded
        from gui.table_copy import enable_excel_copy
        w = QWidget()
        vlay = QVBoxLayout(w)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        # Analysis read-out (edited in the Analysis card) shown on the right
        # of the sub-tab strip.
        self.lbl_out_thr = QLabel("")
        self.lbl_out_bin = QLabel("")
        for lb in (self.lbl_out_thr, self.lbl_out_bin):
            lb.setTextFormat(Qt.RichText)
            theme.set_tone(lb, "text2", "font-size:11px;")
        btn_edit_metrics = QPushButton("Edit")
        btn_edit_metrics.setFixedHeight(24)
        btn_edit_metrics.setToolTip("Open the Analysis card")
        btn_edit_metrics.clicked.connect(self._open_analysis_card)
        self._out_metric_widgets = (self.lbl_out_thr, self.lbl_out_bin, btn_edit_metrics)

        # Annotated-video export widgets — created here as headless attrs;
        # the batch tab's Export tab reparents them.
        self._export_video_thread = None

        # Centered hint above tabs — used to be the only thing shown before
        # tracking; now demoted to invisible by default since each data tab
        # carries its own placeholder.
        self.lbl_excel_hint = QLabel("")
        self.lbl_excel_hint.setVisible(False)

        self._excel_tabs = QTabWidget()
        self._excel_tabs.setObjectName("ExcelTabs")

        def _table(cols):
            tb = QTableWidget()
            tb.setProperty("out", True)
            tb.setEditTriggers(QTableWidget.NoEditTriggers)
            tb.setShowGrid(False)
            tb.setFrameShape(QFrame.NoFrame)
            tb.verticalHeader().setVisible(False)
            tb.verticalHeader().setDefaultSectionSize(30)
            if cols:
                tb.setColumnCount(len(cols))
                tb.setHorizontalHeaderLabels(cols)
            enable_excel_copy(tb)
            return tb

        # ── Summary tab: grouped metrics (label · value · unit)
        summary_wrap = QWidget()
        sv = QVBoxLayout(summary_wrap)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(0)
        self.lbl_summary_placeholder = QLabel(
            "Run tracking first to see the data output."
        )
        self.lbl_summary_placeholder.setAlignment(Qt.AlignCenter)
        theme.set_tone(self.lbl_summary_placeholder, "faint", "font-size:12px;")
        sv.addWidget(self.lbl_summary_placeholder, 1)
        self._table_summary = _table(None)
        self._table_summary.setColumnCount(3)
        self._table_summary.horizontalHeader().setVisible(False)
        self._table_summary.setVisible(False)
        self._summary_panel = OutPanel("Summary")
        self._build_unit_selectors(self._summary_panel)
        self._summary_panel.add_button("Copy table", lambda: copy_table_all(self._table_summary, False))
        self._summary_panel.body.addWidget(self._table_summary)
        self._summary_panel.setMaximumWidth(880)
        self._summary_panel.hide()
        sv.addWidget(self._summary_panel, 0)
        sv.addStretch(1)
        self._excel_tabs.addTab(padded(summary_wrap), "Summary")

        # ── Raw Data tab
        raw_wrap = QWidget()
        rv = QVBoxLayout(raw_wrap)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        self.lbl_raw_placeholder = QLabel(
            "Run tracking first to see the data output."
        )
        self.lbl_raw_placeholder.setAlignment(Qt.AlignCenter)
        theme.set_tone(self.lbl_raw_placeholder, "faint", "font-size:12px;")
        rv.addWidget(self.lbl_raw_placeholder, 1)
        self._table_raw = _table(None)
        self._table_raw.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table_raw.verticalHeader().setDefaultSectionSize(28)
        self._table_raw.setVisible(False)
        self._raw_panel = OutPanel("Raw data")
        self._raw_panel.add_button("Copy table", lambda: copy_table_all(self._table_raw))
        self._raw_panel.body.addWidget(self._table_raw)
        self._raw_panel.hide()
        rv.addWidget(self._raw_panel, 1)
        self._excel_tabs.addTab(padded(raw_wrap), "Raw data")

        self._excel_tabs.addTab(padded(self._graph_widget), "Graphs")
        # Tracking Issues — glitch detector + table + mini map + actions.
        # Shown in a popup from the preview (Tracking issues button), not here.
        self._issues_widget = self._build_tracking_issues_tab()
        self._issues_popup = None
        # Cell-Info tab is OF-specific (4×4 grid region labeling). YMazeTab
        # inherits the OF mixin so the method exists, but the tab is
        # irrelevant for Y-Maze — gate on experiment key.
        exp = getattr(self, "experiment", None)
        if (hasattr(self, "_build_cell_info_tab")
                and exp is not None and exp.key == "open_field"):
            self._excel_tabs.addTab(padded(self._build_cell_info_tab()), "Cell info")

        # Video Config tab — mirrors the Excel "Video Config" sheet.
        self._table_video_config = _table(["Setting", "Value"])
        self._table_video_config.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table_video_config.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._table_video_config.verticalHeader().setDefaultSectionSize(28)
        vc_panel = OutPanel()
        vc_panel.body.addWidget(self._table_video_config)
        vc_panel.setMaximumWidth(720)
        vc_wrap = QWidget()
        vcv = QVBoxLayout(vc_wrap)
        vcv.setContentsMargins(0, 0, 0, 0)
        vcv.addWidget(vc_panel, 1)
        self._excel_tabs.addTab(padded(vc_wrap), "Video config")

        self._out_header = SubTabHeader(self._excel_tabs, self._out_metric_widgets)
        vlay.addWidget(self._out_header)
        vlay.addWidget(self._excel_tabs, 1)

        self.lbl_excel_note = QLabel("")
        theme.set_tone(self.lbl_excel_note, "faint", "font-size:10px;")
        self.lbl_excel_note.setContentsMargins(16, 4, 16, 4)
        self.lbl_excel_note.setVisible(False)
        vlay.addWidget(self.lbl_excel_note)

        vlay.addWidget(self._build_export_bar())
        theme.notifier.changed.connect(self._on_theme_output)
        theme.notifier.changed.connect(self._on_theme_graphs)
        return w

    def _on_theme_output(self, _mode):
        """Table items bake colours at population time — repopulate."""
        try:
            if self.metrics:
                self._refresh_summary_table()
        except Exception:
            pass

    def _build_controls(self):
        panel = QFrame()
        panel.setMinimumWidth(250)
        panel.setFrameShape(QFrame.NoFrame)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # Each step builder registers its accordion card(s) via _group() in
        # display order (some steps create two: Video+Animal, Arena+Zones,
        # Tracking+Analysis).
        self._cards = []
        self._step_source()
        self._step_geometry()
        self._step_scale()
        self._step_detection()
        self._step_analysis()
        default_open = {"geometry": True, "zones": True, "detection": True}
        for i, g in enumerate(self._cards, start=1):
            g._header.set_number(i)
            lay = g.layout()
            if lay is not None:
                lay.setContentsMargins(48, 0, 14, 4)
                lay.setSpacing(7)
            layout.addWidget(g)
            g.setChecked(default_open.get(g._status_id, False))
            g._header.set_open(g.isChecked())
        layout.addStretch()
        # Plain on/off checkboxes inside the cards (Y-Maze / EPM / NOR
        # builders, Nose etc.) get the switch look; SwitchBox paints its own.
        from gui.widgets_v2 import SwitchBox
        for card in self._cards:
            for cb in card.findChildren(QCheckBox):
                if not isinstance(cb, SwitchBox) and not cb.property("chip"):
                    cb.setProperty("switch", True)
        self._step_summary_timer = QTimer(self)
        self._step_summary_timer.setInterval(400)
        self._step_summary_timer.timeout.connect(self._refresh_step_cards)
        self._step_summary_timer.start()
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
        w.setObjectName("OutFooter")
        w.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(w)
        h.setContentsMargins(16, 8, 16, 8)
        h.setSpacing(8)
        self.lbl_export = QLabel("Autosaved to backup after each run")
        self.lbl_export.setWordWrap(True)
        theme.set_tone(self.lbl_export, "text2", "font-size:11px;")
        self.btn_export = QPushButton("Export to Excel")
        self.btn_export.setFixedHeight(28)
        self.btn_export.setProperty("primary", True)
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export)
        h.addWidget(self.lbl_export, 1)
        h.addWidget(self.btn_export)
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


    def _load_video_path(self, path):
        if not os.path.exists(path):
            QMessageBox.warning(self, "Error", f"Video file not found:\n{path}")
            return
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            QMessageBox.warning(self, "Error", "Cannot open this video file.")
            return
        from core.video import probe, warm_frame_times
        raw_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        self._auto_fps, frame_count = probe(cap)
        if self._auto_fps > 0 and abs(self._auto_fps - raw_fps) > 0.5:
            logger.warn(f"{os.path.basename(path)}: file reports {raw_fps:g} fps; "
                        f"using {self._auto_fps:.2f} fps measured from frame times",
                        source="video")
        warm_frame_times(path)          # exact scrub jumps (core.video)
        # honor manual override if set
        override = self._fps_override()
        if self._auto_fps <= 0:
            from core.video import FPS_UNKNOWN
            logger.warn(f"{os.path.basename(path)}: file reports {raw_fps:g} fps; "
                        "real rate unknown", source="video")
            if override <= 0:
                QMessageBox.warning(self, "Frame rate unknown", FPS_UNKNOWN)
        # 30 only drives the preview until an override is set; tracking refuses
        self.fps = override if override > 0 else (self._auto_fps or 30.0)
        self._sync_trail_len()
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
        for sw in (self.btn_preview, self.btn_preview_mode):
            sw.blockSignals(True)
            sw.setChecked(False)
            sw.blockSignals(False)
            sw.setEnabled(False)
        self.zone_drawer.set_frame(frame)

        self.slider_scrub.setMaximum(max(0, frame_count - 1))
        self.slider_scrub.setValue(0)
        self.slider_scrub.setEnabled(True)
        self.btn_step_prev.setEnabled(True)
        self.btn_step_next.setEnabled(True)
        self._refresh_redesign_data()
        self._update_scrub_label(0, frame_count)

        name = os.path.basename(path)
        self.lbl_video.setText(name)
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
            self.lbl_fps_detected.setText(f"{self.fps:.2f} fps")
        if hasattr(self, "lbl_resolution"):
            self.lbl_resolution.setText(f"{self.video_w} × {self.video_h} px")
        for name in ("btn_calib", "btn_arena", "btn_auto_arena",
                     "btn_excl", "btn_view_processed"):
            btn = getattr(self, name, None)
            if btn is not None:
                btn.setEnabled(True)
        # Define-arena buttons built by experiments.common_ui.define_row.
        for btn in getattr(self, "_video_gated", []):
            try:
                btn.setEnabled(True)
            except RuntimeError:
                pass
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
            self.zone_drawer.set_perspective_corners_editable(False)
        if hasattr(self, "chk_perspective") and not plugin_owns_perspective:
            self.chk_perspective.setEnabled(False)
        self._update_run_button()
        self.set_step_status("source", "ok")
        self.set_step_status("detection", "ok")

        # Build preview background asynchronously
        self.lbl_adjust.setText("Building preview background…")
        theme.set_tone(self.lbl_adjust, "faint", "font-size:11px;")
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
            _fam = getattr(getattr(self, "experiment", None), "fam", exp_key)
            if (_fam in ("open_field", "nor", "box")
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
            theme.set_tone(self.lbl_calib, "faint", "font-size:11px;")
        self.zone_drawer.set_mode(ZoneDrawer.MODE_CALIB)

    def _clear_calib(self):
        self.zone_drawer.clear_calibration()
        self.btn_clear_calib.setEnabled(False)
        self.lbl_calib.setText("Not calibrated — distances will be in pixels")
        theme.set_tone(self.lbl_calib, "faint", "font-size:11px;")

    def _update_calib_status(self):
        mode = self._calib_mode() if hasattr(self, "rb_calib_auto") else None
        if mode == "none":
            self.lbl_calib.setText("Calibration off — distances will be in pixels")
            theme.set_tone(self.lbl_calib, "faint", "font-size:11px;")
            if hasattr(self, "btn_clear_calib"):
                self.btn_clear_calib.setEnabled(False)
            self.set_step_status("scale", "warn")
            return
        if mode in ("manual", None):
            if (self.zone_drawer.calib_p1 and self.zone_drawer.calib_p2
                    and self.spin_cm.value() <= 0):
                self.lbl_calib.setText("Enter the real length of the line in cm — "
                                       "0 is not a length. Runs are refused until then.")
                theme.set_tone(self.lbl_calib, "err", "font-size:11px;")
                self.set_step_status("scale", "warn")
                return
            if self.zone_drawer.calib_p1 and self.zone_drawer.calib_p2:
                pxcm = self.zone_drawer.get_pixels_per_cm(self.spin_cm.value())
                if pxcm:
                    self.lbl_calib.setText(f"Calibrated (line): {pxcm:.2f} px/cm")
                    theme.set_tone(self.lbl_calib, "ok", "font-size:11px;")
                    self.btn_clear_calib.setEnabled(True)
                    self.set_step_status("scale", "ok")
                    return
        if mode in ("auto", None):
            auto = self._auto_px_per_cm()
            if auto:
                self.lbl_calib.setText(f"Auto-calibrated from cage: {auto:.2f} px/cm")
                theme.set_tone(self.lbl_calib, "accent", "font-size:11px;")
                self.set_step_status("scale", "ok")
                return
        self.lbl_calib.setText("Not calibrated — distances will be in pixels")
        theme.set_tone(self.lbl_calib, "faint", "font-size:11px;")
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
        self._persist_config("calib_mode", self._calib_mode())
        if self._calib_mode() != "manual":
            # Leaving Manual: stop any line in progress and drop the drawn
            # line so only the selected mode's calibration is in play.
            zd = self.zone_drawer
            if zd.mode == ZoneDrawer.MODE_CALIB:
                zd.set_mode(ZoneDrawer.MODE_IDLE)
            if zd.calib_p1 or zd.calib_p2:
                zd.clear_calibration()
            self.btn_clear_calib.setEnabled(False)
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
        card = getattr(self, "_step_groups", {}).get("scale")
        is_open = card is None or card.isChecked()
        self._calib_auto_widget.setVisible(is_open and mode == "auto")
        self._calib_manual_widget.setVisible(is_open and mode == "manual")
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

    def _cage_shape(self):
        """The apparatus shape this test uses (NOR: always square; box
        tests: their own; Open Field: the Scale card choice)."""
        exp = getattr(self, "experiment", None)
        fam = getattr(exp, "fam", None)
        if fam == "nor":
            return "square"
        if fam == "box":
            return "square" if exp.scale[0] == "square" else "rectangle"
        return self.config.get("cage_shape", "rectangle")

    def _warp_target_size(self):
        from experiments.open_field.experiment import warp_target_size
        w = float(self.spin_cage_w.value()) if hasattr(self, "spin_cage_w") else 0.0
        h = float(self.spin_cage_h.value()) if hasattr(self, "spin_cage_h") else 0.0
        return warp_target_size(self.video_w, self.video_h, self._cage_shape(), w, h)

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

    def _on_cage_shape_changed(self):
        shape = self.combo_cage_shape.currentData()
        self._persist_config("cage_shape", shape)
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
        self._persist_config("cage_w_cm", float(self.spin_cage_w.value()))
        self._persist_config("cage_h_cm", float(self.spin_cage_h.value()))
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
            self.lbl_cage_w.setText("Side")
            self.lbl_cage_x.setVisible(False)
            self.lbl_cage_h.setVisible(False)
            self.spin_cage_h.setVisible(False)
            try:
                self.spin_cage_h.blockSignals(True)
                self.spin_cage_h.setValue(self.spin_cage_w.value())
            finally:
                self.spin_cage_h.blockSignals(False)
        else:  # rectangle / custom
            self.lbl_cage_w.setText("Width")
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

    def to_graph_space(self, pts_list):
        """Video-pixel points -> the space the graphs are drawn in. Graphs
        use the tracker's own space (see _graph_data), so this is the
        identity; kept for plugins that call it."""
        return pts_list

    def _graph_data(self):
        """Returns (results, arena_pixels, center_pixels, px_per_cm) in the
        space the tracker reports — the straightened frame when perspective
        is on, the raw frame otherwise. Never reshaped when perspective is
        off: batch and every export use these same positions, so the
        numbers must match."""
        return (self.tracking_results, self.zone_drawer.get_arena_pixels(),
                self.zone_drawer.get_center_pixels(), self._get_px_per_cm())

    def _graph_canvas_size(self):
        """Returns (W, H) used by trajectory/heatmap plots — warped target if available."""
        target = self._warp_target_size() if self._perspective_on else None
        if target is not None:
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
            self.zone_drawer.set_perspective_corners_editable(True)
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
            self.zone_drawer.set_perspective_corners_editable(False)
            self._perspective_on = False
            # Restore the pre-perspective video size.
            if hasattr(self, "_native_video_size") and self._native_video_size:
                self.video_w, self.video_h = self._native_video_size
                self._native_video_size = None
        self._compute_center()
        if self._first_frame_bgr is not None:
            self._on_scrub(self.slider_scrub.value())

    def _on_perspective_corner_dragged(self, idx, nx, ny):
        """A corner handle was dragged in the perspective-corrected view.
        Map the drop point back to the original video (inverse warp), move
        that corner of the original arena, and re-warp — the corrected view
        keeps showing the arena as the full frame."""
        zd = self.zone_drawer
        full = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        if not (self._perspective_on and self._H is not None
                and self._original_arena and len(self._original_arena) == 4):
            zd.arena = full
            zd.update()
            return
        NW, NH = (getattr(self, "_native_video_size", None)
                  or (self.video_w, self.video_h))
        TW, TH = self.video_w, self.video_h          # warped (current) space
        try:
            inv = np.linalg.inv(self._H)
            p = cv2.perspectiveTransform(
                np.array([[[nx * TW, ny * TH]]], dtype=np.float32), inv)[0, 0]
        except (np.linalg.LinAlgError, cv2.error):
            zd.arena = full
            zd.update()
            return
        # Warped corner idx ↔ original corner in TL, TR, BR, BL order (the
        # order _build_homography maps onto the full frame).
        quad = self._sort_quad_screen(
            [(x * NW, y * NH) for x, y in self._original_arena])
        quad = [(float(x), float(y)) for x, y in quad]
        quad[idx] = (min(max(float(p[0]), 0.0), NW), min(max(float(p[1]), 0.0), NH))
        src = np.array(quad, dtype=np.float32)
        target = self._warp_target_size() or (TW, TH)
        dst = np.array([(0, 0), (target[0], 0), (target[0], target[1]),
                        (0, target[1])], dtype=np.float32)
        H = None
        if cv2.isContourConvex(src.reshape(-1, 1, 2)) and \
                abs(cv2.contourArea(src)) > 100:
            try:
                H = cv2.getPerspectiveTransform(src, dst)
            except cv2.error:
                H = None
        zd.arena = full
        if H is None:          # folded / collapsed quad — keep the old one
            zd.update()
            return
        self._original_arena = [(x / NW, y / NH) for x, y in quad]
        self._H = H
        self._compute_center()
        if self._first_frame_bgr is not None:
            self._on_scrub(self.slider_scrub.value())
        zd.emit_change("perspective arena corner adjusted")

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
            theme.set_tone(self.lbl_zones, "ok", "font-size:11px;")
        else:
            self.lbl_zones.setText("No zones defined")
            theme.set_tone(self.lbl_zones, "faint", "font-size:11px;")
        if self.zone_drawer.arena:
            self.set_step_status("geometry", "ok")
        elif getattr(self, "_arena_auto_movement", False):
            # Arena is built from movement during the run — a valid choice.
            self.set_step_status("geometry", "ok")
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
            self.btn_preview_mode.setEnabled(True)
            self.lbl_adjust.setText("Adjust sliders, then turn on Detected area or Show mask.")
            theme.set_tone(self.lbl_adjust, "faint", "font-size:11px;")
            if not self.tracking_results and not getattr(self, "_suppress_auto_preview", False):
                self.btn_preview.setChecked(True)
        else:
            self.lbl_adjust.setText("Preview unavailable for this video.")

    def _on_preview_toggled(self, _checked=None):
        """Detected area / Show mask changed — each works on its own. The
        detection preview renders while either is on."""
        self._preview_mode = "mask" if self.btn_preview_mode.isChecked() else "overlay"
        self._preview_active = (self.btn_preview.isChecked()
                                or self.btn_preview_mode.isChecked())
        if self._preview_active:
            self._update_preview()
        else:
            self._on_scrub(self.slider_scrub.value())

    def _on_preview_mode_toggled(self, _checked=None):
        self._on_preview_toggled()

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
        self._draw_tracked_point(display)
        self.zone_drawer.set_frame(display)

    def _draw_tracked_point(self, display):
        """Draw the tracked point of the current frame (body marker, or the
        hand-fixed / interpolated marker) onto `display` (BGR, in place)."""
        if display is None or getattr(display, "ndim", 3) != 3:
            return
        if self.tracking_results:
            rel_idx = self._slider_to_results_idx(self.slider_scrub.value())
            r = self.tracking_results[rel_idx]
            if r.get("corrected"):
                xv, yv = r.get("x"), r.get("y")
                if xv is not None:
                    cv2.circle(display, (int(xv), int(yv)), 8, (71, 197, 232), -1)
                    cv2.circle(display, (int(xv), int(yv)), 10, (40, 150, 190), 2)
            elif r.get("interpolated"):
                xv, yv = r.get("x"), r.get("y")
                if xv is not None:
                    cv2.circle(display, (int(xv), int(yv)), 7, (166, 107, 211), -1)
                    cv2.circle(display, (int(xv), int(yv)), 9, (130, 70, 170), 2)
            else:
                self._draw_body_on_frame(display, r, rel_idx)

    def _detection_mask(self, frame_bgr):
        """What the current Detection settings find on `frame_bgr`
        (uint8 mask), or None while the preview background isn't ready."""
        if frame_bgr is None or self._preview_bg_raw is None:
            return None
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        bg_raw = self._warp(self._preview_bg_raw) if self._H is not None else self._preview_bg_raw
        if bg_raw.shape[:2] != gray.shape[:2]:
            return None
        args = (self.slider_brightness.value(), self.slider_contrast.value() / 100.0,
                self.slider_blur.value(), self.slider_gamma.value() / 100.0,
                self.slider_sharpen.value(), self.spin_clahe.value())
        proc_frame = apply_preprocessing(gray, *args)
        proc_bg = apply_preprocessing(bg_raw, *args)
        mask = get_mask(proc_frame, proc_bg, self.spin_threshold.value(),
                        self.zone_drawer.get_arena_pixels())
        exc = self.zone_drawer.get_exclusion_mask()
        if exc is not None and exc.any():
            mask = cv2.bitwise_and(mask, cv2.bitwise_not(exc))
        return mask

    def _update_preview(self):
        if not self._preview_active:
            if self.btn_view_processed.isChecked():
                self._render_current_frame()
            return
        current = self._current_scrub_frame_bgr if self._current_scrub_frame_bgr is not None else self._first_frame_bgr
        if current is None or self._preview_bg_raw is None:
            return

        mask = self._detection_mask(current)
        if mask is None:
            self._render_current_frame()
            return

        # Show mask → the black-and-white mask is the picture; otherwise the
        # (processed) frame. Detected area → highlight drawn on top of it.
        if self.btn_preview_mode.isChecked():
            base = make_mask_view(mask)
        else:
            base = self._get_processed_frame_bgr(current) if self.btn_view_processed.isChecked() else current
        if self.btn_preview.isChecked():
            display = make_overlay(base, mask, self._bgr("detection"),
                                   self.overlay_alpha / 100.0)
        else:
            display = base
        # After a run, show the tracked point on top of the detected area,
        # so detection problems and tracking glitches can be told apart.
        self._draw_tracked_point(display)
        self.zone_drawer.set_frame(display)

    _LAST_PRESET_KEY = "detection_preset_by_test"   # config: {test key: preset name}

    def _remember_preset(self, name):
        """Remember the Detection preset last chosen for this test, so the
        app shows it again next time it opens."""
        key = getattr(getattr(self, "experiment", None), "key", None) or "open_field"
        d = dict(self.config.get(self._LAST_PRESET_KEY) or {})
        if d.get(key) != name:
            d[key] = name
            self._persist_config(self._LAST_PRESET_KEY, d)

    def _restore_last_preset(self):
        """Start-up: select the preset last chosen for this test and load
        its values — unless a video's own saved settings were already
        applied (those are that video's real settings)."""
        combo = getattr(self, "combo_preset", None)
        if combo is None:
            return
        key = getattr(getattr(self, "experiment", None), "key", None) or "open_field"
        name = (self.config.get(self._LAST_PRESET_KEY) or {}).get(key)
        idx = combo.findText(name) if name else -1
        if idx < 0:
            return
        combo.setCurrentIndex(idx)
        if name != DEFAULT_PRESET_NAME and not self._settings_applied:
            self._load_preset(remember=False)

    def _selected_preset(self):
        """The saved preset chosen in the Detection card, or None when
        Default (or nothing known) is selected."""
        combo = getattr(self, "combo_preset", None)
        name = combo.currentText() if combo is not None else ""
        if name and name != DEFAULT_PRESET_NAME and name in self._presets:
            return self._presets[name]
        return None

    def _reset_to_preset(self):
        """Reset = back to the preset you started from: the selected saved
        preset, or the built-in defaults when Default is selected."""
        if self._selected_preset() is not None:
            self._load_preset()
        else:
            self._reset_sliders()

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
        from core.app_paths import read_json
        return read_json(PRESETS_PATH)

    def _save_presets_file(self):
        from core.app_paths import write_json
        write_json(PRESETS_PATH, self._presets)

    def _populate_preset_combo(self):
        self.combo_preset.blockSignals(True)
        self.combo_preset.clear()
        self.combo_preset.addItem(DEFAULT_PRESET_NAME)
        for name in sorted(self._presets):
            self.combo_preset.addItem(name)
        self.combo_preset.blockSignals(False)

    def _collect_current_preset(self):
        """Snapshot every Detection-step control into a preset dict —
        the same shape already stored in self._presets / the presets file."""
        preset = {
            "brightness":   self.slider_brightness.value(),
            "contrast":     self.slider_contrast.value(),
            "blur":         self.slider_blur.value(),
            "gamma":        self.slider_gamma.value(),
            "sharpen":      self.slider_sharpen.value(),
            "clahe":        self.spin_clahe.value(),
            "threshold":    self.spin_threshold.value(),
            "low_contrast": bool(self.chk_low_contrast.isChecked()),
            "max_blob":     self.spin_max_blob.value(),
            "proc_scale":   self.combo_proc_scale.currentData(),
            "frame_skip":   int(self.spin_frame_skip.value()),
            "smooth_window": int(self.spin_smooth_window.value()) if hasattr(self, "spin_smooth_window") else 3,
            "model":        self.combo_model.currentData() or "median",
            "model_params": {m: dict(p) for m, p in self._model_params.items()},
            "post_params":  dict(self._post_params),
            "body_style":   self.combo_body_style.currentData() or "dot",
            "marker_shape": self.combo_marker_shape.currentData() or "dot",
            "marker_size":  int(self.spin_marker_size.value()),
            "marker_tag":   self.chk_marker_tag.isChecked(),
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
        return preset

    def _save_preset(self):
        current = self.combo_preset.currentText()
        if current != DEFAULT_PRESET_NAME and current in self._presets:
            # An existing custom preset is selected — Save overwrites it in
            # place, keeping its name, without asking for a new name.
            self._presets[current] = self._collect_current_preset()
            self._save_presets_file()
            self._populate_preset_combo()
            idx = self.combo_preset.findText(current)
            if idx >= 0:
                self.combo_preset.setCurrentIndex(idx)
            self._remember_preset(current)
            return
        # Default (or nothing recognized) is selected — Save always creates
        # a new named preset; Default itself is never overwritten.
        default_text = "" if current == DEFAULT_PRESET_NAME else current
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:", text=default_text)
        if not ok or not name.strip():
            return
        name = name.strip()
        if name.lower() == DEFAULT_PRESET_NAME.lower():
            QMessageBox.warning(
                self, "Save Preset",
                f'"{DEFAULT_PRESET_NAME}" is reserved and cannot be overwritten. '
                "Please choose a different name."
            )
            return
        self._presets[name] = self._collect_current_preset()
        self._save_presets_file()
        self._populate_preset_combo()
        idx = self.combo_preset.findText(name)
        if idx >= 0:
            self.combo_preset.setCurrentIndex(idx)
        self._remember_preset(name)

    def _load_preset(self, remember=True):
        name = self.combo_preset.currentText()
        if remember:
            self._remember_preset(name)
        if name == DEFAULT_PRESET_NAME:
            self._reset_sliders()
            return
        if name not in self._presets:
            return
        p = self._presets[name]
        self.slider_brightness.setValue(p.get("brightness", 0))
        self.slider_contrast.setValue(p.get("contrast", 100))
        self.slider_blur.setValue(p.get("blur", 0))
        self.slider_gamma.setValue(p.get("gamma", 100))
        self.slider_sharpen.setValue(p.get("sharpen", 0))
        self.spin_clahe.setValue(p.get("clahe", 0))
        self.spin_threshold.setValue(p.get("threshold", 25))
        self.chk_low_contrast.setChecked(bool(p.get("low_contrast", False)))
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
        self._apply_marker_settings(p)
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
                    f"background-color: {self._colors[key]}; border: 1px solid rgba(0,0,0,0.18); border-radius: 2px;"
                )
            self.zone_drawer.set_zone_colors(self._colors)
            self._persist_config("colors", dict(self._colors))
        self._apply_view_prefs()
        self._on_scrub(self.slider_scrub.value())

    def _delete_preset(self):
        name = self.combo_preset.currentText()
        if name == DEFAULT_PRESET_NAME or name not in self._presets:
            return
        reply = QMessageBox.question(self, "Delete Preset",
                                     f'Delete preset "{name}"?',
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            del self._presets[name]
            self._save_presets_file()
            self._populate_preset_combo()
            self._remember_preset(DEFAULT_PRESET_NAME)

    def _export_preset(self):
        """Write the selected custom preset to a standalone .json file —
        reuses the exact dict already stored in self._presets, just wrapped
        with its name so Load/Import can restore it as-is elsewhere."""
        name = self.combo_preset.currentText()
        if name == DEFAULT_PRESET_NAME or name not in self._presets:
            QMessageBox.information(
                self, "Export Preset",
                "Select an existing custom preset to export."
            )
            return
        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip() or "preset"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Preset", f"{safe_name}.json", "Preset files (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            with open(path, "w") as f:
                json.dump({"name": name, "preset": self._presets[name]}, f, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "Export Preset", f"Could not write preset file:\n{e}")

    def _import_preset(self):
        """Import a preset .json file (written by _export_preset) into the
        local presets store, reusing the existing Load/apply path."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Preset", "", "Preset files (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Import Preset", f"Could not read preset file:\n{e}")
            return
        name = data.get("name") if isinstance(data, dict) else None
        preset = data.get("preset") if isinstance(data, dict) else None
        if not name or not isinstance(preset, dict):
            QMessageBox.warning(
                self, "Import Preset",
                "This file doesn't look like a valid exported preset."
            )
            return
        name = str(name).strip()
        if name.lower() == DEFAULT_PRESET_NAME.lower():
            QMessageBox.warning(
                self, "Import Preset",
                f'"{DEFAULT_PRESET_NAME}" is reserved and cannot be imported as a preset name.'
            )
            return
        if name in self._presets:
            reply = QMessageBox.question(
                self, "Import Preset",
                f'A preset named "{name}" already exists. Overwrite it?',
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        self._presets[name] = preset
        self._save_presets_file()
        self._populate_preset_combo()
        idx = self.combo_preset.findText(name)
        if idx >= 0:
            self.combo_preset.setCurrentIndex(idx)
        self._load_preset()

    # ── Step 5 ────────────────────────────────────────────────────────────

    def _update_run_button(self):
        ready = self.video_path is not None and (
            self.zone_drawer.arena is not None
            or getattr(self, "_arena_auto_movement", False))
        self.set_step_status("analysis", "ok" if ready else "blocked")


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


    # ── Step 6 ────────────────────────────────────────────────────────────

    def _export(self):
        from core.app_paths import app_dir
        start = self.config.get("output_folder") or ""
        output_folder = QFileDialog.getExistingDirectory(
            self, "Export to…", start if os.path.isdir(start) else app_dir())
        if not output_folder:
            return
        self.config["output_folder"] = output_folder

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
            fkey = (getattr(self.experiment, "file_key", None)
                    or getattr(self.experiment, "key", "open_field"))
            out_path = os.path.join(output_folder, f"{video_name}_{fkey}.xlsx")
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
                test_name=(getattr(self.experiment, "report_title", None)
                           or f"{getattr(self.experiment, 'name', 'Open Field')} Test"),
                video_config=(self.experiment.filter_video_config(self.snapshot_settings())
                              if self.experiment is not None
                              else self.snapshot_settings()),
            )
            self.lbl_export.setText(f"Saved:\n{out_path}\n(+ CSV companions)")
            theme.set_tone(self.lbl_export, "ok", "font-size:11px;")
            from gui.notify import show_done
            show_done(self, "Excel file saved",
                      "CSV copies of the data were saved next to it.", path=out_path)
            from gui.notify import show_notices
            show_notices(self)
        except Exception as e:
            theme.set_tone(self.lbl_export, "err", "font-size:11px;")
            from gui.notify import show_done, explain_error
            title = ("CSV copy not saved"
                     if str(e).startswith("The Excel file was saved")
                     else "Excel export failed")
            show_done(self, title, explain_error(e), kind="err")

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
            self._metrics_ok = True
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
            # The shown numbers are now older than the settings: exports
            # check this flag and refuse to pass them off as current.
            self._metrics_ok = False
            logger.error(
                f"_recompute_metrics_and_views failed: {e}\n{traceback.format_exc()}",
                source="metrics",
            )
        self._refresh_redesign_data()
        # Notify outside listeners (batch tab refreshes its cache).
        try:
            self.metrics_changed.emit()
        except Exception:
            pass

    # ── _jump_next_miss / _interpolate_gaps live in
    #    gui/output/corrections_mixin.py

    # ── scrub ─────────────────────────────────────────────────────────────

    def _marker_tag_lines(self, i):
        """Two-line info tag of the marker at results index `i`:
        "<animal> · <speed> <unit>" / "x <x>  y <y>" (None when undetected)."""
        res, df = self.tracking_results, self.raw_df
        if df is None or not res or not (0 <= i < len(res)) or i >= len(df):
            return None
        r = res[i]
        if r.get("x") is None:
            return None
        col, unit = self._speed_col()
        sp = df[col].iloc[i] if col is not None else float("nan")
        sp_txt = "—" if sp != sp else f"{sp:.1f}"
        pxcm = self._get_px_per_cm()
        # Measured from the arena's top-left corner, like the graphs.
        arena = self.zone_drawer.get_arena_pixels()
        ox, oy = (min(arena, key=lambda p: p[0] + p[1])
                  if arena and not self._perspective_on else (0.0, 0.0))
        if pxcm:
            xy = f"x {(r['x'] - ox) / pxcm:.1f}  y {(r['y'] - oy) / pxcm:.1f}"
        else:
            xy = f"x {r['x'] - ox:.0f}  y {r['y'] - oy:.0f}"
        aid = self.edit_meta_id.text().strip() or "—"
        return [f"{aid} · {sp_txt} {unit}".strip(), xy]

    def _draw_body_on_frame(self, frame, r, frame_idx=None,
                            body_style=None,
                            draw_ellipse=None, draw_trail=None,
                            trail_len=None, trail_fade=None,
                            results_override=None, tag_lines=None):
        """Thin wrapper. When override params are None, current widget state
        is used (live preview). Export thread passes explicit flags."""
        from core.tracking.draw import draw_body_overlay
        draw_body_overlay(
            frame, r, frame_idx=frame_idx,
            results=results_override if results_override is not None else self.tracking_results,
            style=body_style if body_style is not None else self.combo_body_style.currentData(),
            shape=self.combo_marker_shape.currentData() or "dot",
            size=int(self.spin_marker_size.value()),
            do_ellipse=draw_ellipse if draw_ellipse is not None else self.chk_ellipse.isChecked(),
            do_trail=draw_trail if draw_trail is not None else self.chk_trail.isChecked(),
            trail_len=trail_len if trail_len is not None else self.spin_trail_len.value(),
            trail_fade=trail_fade if trail_fade is not None else self.chk_trail_fade.isChecked(),
            color_fn=self._bgr,
            tag_lines=tag_lines,
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
        """`label | slider | value` row (74 px / flex / 38 px mono)."""
        from PyQt5.QtWidgets import QGridLayout
        row = QGridLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setHorizontalSpacing(8)
        row.setColumnMinimumWidth(0, 74)
        row.setColumnStretch(1, 1)
        lbl = QLabel(label)
        theme.set_tone(lbl, "text2")
        slider = QSlider(Qt.Horizontal)
        slider.setRange(min_v, max_v)
        slider.setValue(default)
        slider.setSingleStep(step)
        slider.setPageStep(max(step, 10))
        slider.setMinimumHeight(22)
        from gui.widgets_v2 import ValueEdit
        # ×-scaled sliders store hundredths: typing 1.2 means 120.
        val_lbl = ValueEdit(slider, fmt_fn,
                            (lambda n: n * 100) if "×" in fmt_fn(default) else (lambda n: n))
        val_lbl.setFixedWidth(42)
        slider.valueChanged.connect(self._update_preview)
        row.addWidget(lbl, 0, 0)
        row.addWidget(slider, 0, 1)
        row.addWidget(val_lbl, 0, 2)
        parent_layout.addLayout(row)
        return slider, val_lbl

    def _group(self, title, status_id=None, optional=False, icon=None, name=None):
        """Accordion card body. Returns a StepGroup (QGroupBox-compatible);
        the header (icon · title · summary · status dot) floats over its top."""
        import re
        from gui.step_card import StepGroup, StepHeader, HeaderPlacer, STEP_META
        g = StepGroup()
        g._base_title = title
        g._status_id = status_id
        g._optional = optional
        # Optional steps default to neutral; required steps start blocked
        # until their gating condition is met.
        g._status = "warn" if optional else "blocked"
        g.setObjectName("StepGroup")  # styled in theme.py
        m = re.match(r"\s*Step\s+(\d+)\s*[—–-]\s*(.+)", title)
        meta_icon, meta_name = STEP_META.get(status_id, ("config", None))
        g._help_name = name or (m.group(2) if m else title)
        g._header = StepHeader(g, icon or meta_icon, g._help_name)
        g._header.clicked.connect(lambda gb=g: gb.setChecked(not gb.isChecked()))
        HeaderPlacer(g, g._header)
        g.toggled.connect(lambda checked, gb=g: self._toggle_group(gb, checked))
        if not hasattr(self, "_cards"):
            self._cards = []
        self._cards.append(g)
        if status_id:
            if not hasattr(self, "_step_groups"):
                self._step_groups = {}
            self._step_groups[status_id] = g
        return g


    def _update_group_title(self, gb):
        # Title lives in the card header now — just sync its state.
        hdr = getattr(gb, "_header", None)
        if hdr is not None:
            hdr.set_open(gb.isChecked())

    def set_step_status(self, step_id, status):
        if not hasattr(self, "_step_groups"):
            return
        gb = self._step_groups.get(step_id)
        if gb is None:
            return
        gb._status = status
        self._update_group_title(gb)

    def _toggle_group(self, gb, checked):
        from gui.step_card import HEADER_H
        self._update_group_title(gb)
        hdr = getattr(gb, "_header", None)
        for child in gb.children():
            if (isinstance(child, QWidget) and child is not hdr
                    and not getattr(child, "_keep_hidden", False)):
                child.setVisible(checked)
        if checked:
            gb.setMaximumHeight(16777215)
            # re-hide widgets that belong to the Full view only
            self._apply_simple_mode()
            # …and sub-panels that only show for the selected mode
            if gb is getattr(self, "_step_groups", {}).get("scale"):
                self._refresh_calib_mode_visibility()
            pad = getattr(self, "_arena_pad_widget", None)
            if pad is not None and pad.parent() is gb:
                self._refresh_arena_mode_chip()
        else:
            gb.setMaximumHeight(HEADER_H + 1)

    # ── accordion card summaries / status dots ───────────────────────────

    def _summary_source(self):
        if not self.video_path:
            return "No video loaded"
        parts = []
        if self.fps:
            parts.append(f"{float(self.fps):.2f} fps")
        if self.video_w:
            parts.append(f"{self.video_w}×{self.video_h}")
        tf = int(getattr(self, "_total_frames", 0) or 0)
        if tf and self.fps:
            d = tf / float(self.fps)
            parts.append(f"{int(d // 60):02d}:{int(d % 60):02d}")
        return " · ".join(parts) or os.path.basename(self.video_path)

    def _summary_animal(self):
        sex = self.combo_meta_sex.currentText().strip()[:1]
        trial = self.edit_meta_trial.text().strip()
        vals = [self.edit_meta_id.text().strip(), self.edit_meta_group.text().strip(),
                sex, f"trial {trial}" if trial else ""]
        return " · ".join(v for v in vals if v) or "No metadata"

    def _summary_geometry(self):
        zd = self.zone_drawer
        if not zd.arena and not getattr(self, "_arena_auto_movement", False):
            return "Not defined"
        modes = {"manual": "Manual · 4 corners", "square": "Premade square",
                 "movement": "Auto · from movement", "contrast": "Auto · contrast"}
        text = modes.get(getattr(self, "_arena_define_mode", None), "Defined")
        shape = getattr(self, "combo_cage_shape", None)
        if shape is not None:
            text += f" · {shape.currentText().lower()}"
        return text

    def _summary_zones(self):
        mode = getattr(self, "combo_zone_mode", None)
        pct = getattr(self, "spin_center_pct", None)
        if mode is None or pct is None:
            return ""
        return f"{mode.currentText()} · {pct.value()}%"

    def _summary_scale(self):
        mode = self._calib_mode()
        if mode == "none":
            return "pixels (uncalibrated)"
        ppc = self._get_px_per_cm()
        if mode == "manual":
            return f"line · {self.spin_cm.value():.1f} cm"
        return f"{ppc:.2f} px/cm · from cage" if ppc else "auto · needs arena"

    def _summary_detection(self):
        preset = self.combo_preset.currentText().strip() or "Default"
        return f"sens {self.spin_threshold.value()} · preset {preset}"

    def _summary_analysis(self):
        model = self.combo_model.currentText()
        scale = self.combo_proc_scale.currentText().split()[0]
        sm = self.spin_smooth_window.value()
        return f"{model} · {scale} · smooth {sm}" if sm > 1 else f"{model} · {scale}"

    def _summary_metrics(self):
        thr = self.spin_movement_thr.value()
        thr_t = "off" if thr <= 0 else f"{thr:.2f}{self.spin_movement_thr.suffix()}"
        b = self.spin_bin_size.value()
        return f"{thr_t} · bin {b:g} s" if b > 0 else f"{thr_t} · no bins"

    def _card_status(self, g):
        """Status dot of a config card:
        red    — no video, or a required setting of this step is missing
                 (or only partly done, e.g. 2 of 3 Y-Maze arms);
        orange — required part is fine but an optional setting is not set;
        green  — everything set."""
        sid = g._status_id
        if not self.video_path:
            return "blocked"
        if sid == "source":
            return "ok"
        if sid == "animal":                       # all fields optional
            fields = [self.edit_meta_id.text(), self.edit_meta_group.text(),
                      self.combo_meta_sex.currentText(), self.edit_meta_trial.text(),
                      self.edit_meta_date.text(), self.edit_meta_notes.text()]
            return "ok" if any(f.strip() for f in fields) else "warn"
        if sid in ("geometry", "zones"):
            geo = self._step_groups.get("geometry")
            status = geo._status if geo is not None else "blocked"
            return "ok" if status == "ok" else "blocked"
        if sid == "scale":                        # optional step
            return "ok" if g._status == "ok" else "warn"
        if sid == "metrics":                      # Move threshold / Time bin are optional
            off = (self.spin_movement_thr.value() <= 0
                   or self.spin_bin_size.value() <= 0)
            return "warn" if off else "ok"
        return "ok" if g._status == "ok" else "blocked"

    def _open_analysis_card(self):
        g = getattr(self, "_step_groups", {}).get("metrics")
        if g is not None:
            g.setChecked(True)

    def _refresh_step_extras(self):
        """Small derived read-outs that live inside cards / the Output bar."""
        if hasattr(self, "lbl_trim_val"):
            st = self._trim_start_s()
            du = self._trim_duration_s()
            tf = int(getattr(self, "_total_frames", 0) or 0)
            total = (tf / float(self.fps)) if (tf and self.fps) else 0.0
            end = (st + du) if du > 0 else total
            self.lbl_trim_val.setText(f"{st:.1f} s → {end:.1f} s" if self.video_path else "—")
        if hasattr(self, "lbl_center_area") and hasattr(self, "spin_cage_w"):
            pct = self.spin_center_pct.value() / 100.0
            if self._calib_mode() == "none" or not self.zone_drawer.arena:
                self.lbl_center_area.setText("—")
            else:
                w = self.spin_cage_w.value()
                h = w if self.combo_cage_shape.currentData() == "square" else self.spin_cage_h.value()
                self.lbl_center_area.setText(f"{w * pct:.1f} × {h * pct:.1f} cm")
        if hasattr(self, "lbl_out_thr"):
            thr = self.spin_movement_thr.value()
            unit = self.spin_movement_thr.suffix().strip()
            thr_t = "off" if thr <= 0 else f"{thr:.2f} {unit}"
            b = self.spin_bin_size.value()
            mono = theme.mono_family()
            span = lambda s: f"<span style=\"font-family:'{mono}'; color:{theme.TEXT}\">{s}</span>"
            self.lbl_out_thr.setText(f"Move threshold {span(thr_t)}")
            self.lbl_out_bin.setText(f"Time bin {span('off' if b <= 0 else f'{b:g} s')}")
        if hasattr(self, "_zone_chips"):
            self._zone_chips.update()
        try:
            self._refresh_canvas_extras()
        except Exception:
            pass

    def _arena_dims_cm(self, ppc=None):
        """(width, height) of the arena in cm, or None when not calibrated.
        Computed fresh (the graphs need it before the canvas label exists)."""
        zd = self.zone_drawer
        vw, vh = self.video_w or 0, self.video_h or 0
        if ppc is None:
            ppc = self._get_px_per_cm() if self.video_path else None
        if not (zd.arena and len(zd.arena) == 4 and vw and vh and ppc):
            return None
        pts = [(x * vw, y * vh) for x, y in zd.arena]
        TL, TR, BR, BL = zd._sorted_corners(pts)
        wpx = ((TR[0] - TL[0]) ** 2 + (TR[1] - TL[1]) ** 2) ** 0.5
        hpx = ((BL[0] - TL[0]) ** 2 + (BL[1] - TL[1]) ** 2) ** 0.5
        return (round(wpx / ppc, 1), round(hpx / ppc, 1))

    def _refresh_canvas_extras(self):
        """Arena label / ruler dimensions / legend summary for the canvas."""
        zd = self.zone_drawer
        ppc = self._get_px_per_cm() if self.video_path else None
        label, dims = "", None
        if zd.arena:
            label = "ARENA"
            dims = self._arena_dims_cm(ppc)
            if dims:
                label = f"ARENA · {dims[0]:.1f} × {dims[1]:.1f} cm"
        pct = self.spin_center_pct.value() if hasattr(self, "spin_center_pct") else None
        zd.set_arena_dims(label, dims, pct)
        info = (f"{ppc:.2f} px/cm" if ppc else "px") + \
               f" · {self.combo_model.currentText()} · sens {self.spin_threshold.value()}"
        legend = getattr(self, "_video_legend", None)
        if legend is not None:
            legend.set_info(info)
        chrome = getattr(self, "_chrome", None)
        if chrome is not None:
            chrome.refresh()

    def _refresh_occupancy(self, dur):
        """Feed the sidebar occupancy block (mini heat-map + % bars)."""
        zd = self.zone_drawer
        grid = getattr(self, "_heat_grid", None)
        if grid is None:
            self.measure_panel.set_occupancy(None)
            return
        m = self.metrics or {}
        center_rel = None
        if zd.arena and zd.center_zone:
            ax = [p[0] for p in zd.arena]
            ay = [p[1] for p in zd.arena]
            cx = [p[0] for p in zd.center_zone]
            cy = [p[1] for p in zd.center_zone]
            w = max(ax) - min(ax) or 1.0
            h = max(ay) - min(ay) or 1.0
            center_rel = ((min(cx) - min(ax)) / w, (min(cy) - min(ay)) / h,
                          (max(cx) - min(ax)) / w, (max(cy) - min(ay)) / h)
        pc = m.get("% Time in Center Zone")
        mob = m.get("Mobility Time (s)")
        wall = m.get("Thigmotaxis %")
        dims = zd.cage_dims_cm
        bin_text = f" / {dims[0] / 20.0:.1f} cm" if dims else ""
        self.measure_panel.set_occupancy(
            grid=grid, vmax=self._heat_vmax, center_rel=center_rel,
            pct_center=float(pc) if isinstance(pc, (int, float)) else None,
            pct_mobile=(100.0 * float(mob) / dur) if isinstance(mob, (int, float)) and dur else None,
            pct_wall=float(wall) if isinstance(wall, (int, float)) else None,
            bin_text=bin_text)

    def _refresh_heat(self):
        """Occupancy grid (20 × 20 over the arena bbox) for the canvas heat
        layer and the sidebar mini-map."""
        from gui.colormaps import heat_rgba
        zd = self.zone_drawer
        self._heat_grid, self._heat_vmax = None, 0.0
        vw, vh = self.video_w or 0, self.video_h or 0
        if not (self.tracking_results and zd.arena and vw and vh):
            zd.set_heat(None, None)
            return
        pts = [(x * vw, y * vh) for x, y in zd.arena]
        x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
        y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
        xs = [r["x"] for r in self.tracking_results if r.get("x") is not None]
        ys = [r["y"] for r in self.tracking_results if r.get("x") is not None]
        if not xs or x1 <= x0 or y1 <= y0:
            zd.set_heat(None, None)
            return
        grid, _, _ = np.histogram2d(ys, xs, bins=[20, 20], range=[[y0, y1], [x0, x1]])
        grid = grid / float(self.fps or 30.0)
        self._heat_grid = grid
        rgba, self._heat_vmax = heat_rgba(grid)
        img = QImage(rgba.tobytes(), 20, 20, 80, QImage.Format_RGBA8888).copy()
        zd.set_heat(img, (x0 / vw, y0 / vh, x1 / vw, y1 / vh))

    def _refresh_step_cards(self):
        cards = getattr(self, "_cards", [])
        if cards and not cards[0].isVisible():
            return                       # this experiment's tab isn't on screen
        self._refresh_step_extras()
        for g in getattr(self, "_cards", []):
            try:
                # Experiment plugin may describe its own Arena / Zones card;
                # None falls back to the shared (Open Field) summary.
                text = None
                pfn = getattr(getattr(self, "experiment", None),
                              f"summary_{g._status_id}", None)
                if pfn is not None:
                    text = pfn(self)
                fn = getattr(self, f"_summary_{g._status_id}", None)
                if text is None and fn is not None:
                    text = fn()
                if text is not None:
                    g._header.set_summary(text)
                g._header.set_status(self._card_status(g))
            except Exception:
                pass

    def _sep(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Plain)
        line.setProperty("role", "hline")
        line.setFixedHeight(1)
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
