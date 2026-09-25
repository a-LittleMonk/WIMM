"""ScrubMixin — video scrub seek, slider, frame stepping, cv2 cap cache.

Mixed into ExperimentTab. Reuses host attrs:
    self.video_path, self.fps, self.slider_scrub, self.btn_preview,
    self.btn_view_processed, self.lbl_scrub, self._crop_rect,
    self._preview_active, self._current_scrub_frame_bgr,
    self._first_frame_bgr, self._scrub_cap, self._scrub_cap_path,
    self._total_frames, self._update_preview, self._render_current_frame,
    self._push_cell_state_for_frame, self._warp, self._trim_start_s,
    self._trim_duration_s, self._jump_next_miss.
"""
import cv2
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QShortcut

from core import logger


class ScrubMixin:
    def _get_scrub_cap(self):
        """Cached cv2.VideoCapture for scrub seeks. Reuses the same cap
        across _on_scrub calls — a long slider drag no longer reopens
        the video on every value change. Reopens automatically when
        self.video_path changes."""
        path = self.video_path
        if not path:
            return None
        cap = self._scrub_cap
        if (cap is not None and self._scrub_cap_path == path
                and cap.isOpened()):
            return cap
        if cap is not None:
            try:
                cap.release()
            except Exception:
                logger.warn("scrub cap release failed", source="video")
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            self._scrub_cap = None
            self._scrub_cap_path = None
            return None
        self._scrub_cap = cap
        self._scrub_cap_path = path
        return cap

    def _release_scrub_cap(self):
        cap = self._scrub_cap
        if cap is not None:
            try:
                cap.release()
            except Exception:
                logger.warn("scrub cap release failed", source="video")
        self._scrub_cap = None
        self._scrub_cap_path = None

    def _on_scrub(self, value):
        if not self.video_path:
            return
        cap = self._get_scrub_cap()
        if cap is None:
            return
        # Playing / stepping forward: read on from where the decoder is
        # instead of seeking (a seek re-decodes from the last keyframe,
        # which is what made playback crawl).
        pos = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        ahead = value - pos
        if 0 <= ahead <= 30:
            for _ in range(ahead):
                cap.grab()
        else:
            cap.set(cv2.CAP_PROP_POS_FRAMES, value)
        ret, frame = cap.read()
        if ret:
            if self._crop_rect is not None:
                cx, cy, cw, ch = self._crop_rect
                frame = frame[cy:cy + ch, cx:cx + cw]
            self._current_scrub_frame_bgr = self._warp(frame).copy()
            if self._preview_active:
                self._update_preview()
            else:
                self._render_current_frame()
        self._update_scrub_label(value, self.slider_scrub.maximum() + 1)
        if hasattr(self, "_sync_redesign"):
            self._sync_redesign(value)
        # Push body position + cumulative cell-time to the zone drawer.
        self._push_cell_state_for_frame(value)

    def apply_trim_to_scrub(self):
        """Clamp the scrub slider's range to the current trim window so the
        user can only scrub within frames that will actually be tracked.
        Also seeks to and displays the trim-start frame."""
        if not self.video_path or self.fps is None or self.fps <= 0:
            return
        # Use cached frame count from _load_video_path; fall back to a probe
        # if it wasn't set (defensive — should always be set after a load).
        total = int(getattr(self, "_total_frames", 0) or 0)
        if total <= 0:
            cap = self._get_scrub_cap()
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) if cap else 0
        start_s = self._trim_start_s()
        dur_s   = self._trim_duration_s()
        start_f = max(0, int(round(start_s * self.fps)))
        end_f   = total - 1
        if dur_s > 0:
            end_f = min(total - 1, start_f + int(round(dur_s * self.fps)) - 1)
        if end_f < start_f:
            end_f = start_f
        # blockSignals so range change doesn't trigger _on_scrub mid-update.
        self.slider_scrub.blockSignals(True)
        self.slider_scrub.setMinimum(start_f)
        self.slider_scrub.setMaximum(end_f)
        cur = self.slider_scrub.value()
        if cur < start_f or cur > end_f:
            self.slider_scrub.setValue(start_f)
            cur = start_f
        self.slider_scrub.blockSignals(False)
        self._update_scrub_label()
        # Seek to (and display) the current frame, which after a trim change
        # is the trim-start frame. Without this the preview keeps showing
        # the previous (full-video) first frame.
        try:
            self._on_scrub(cur)
            # Promote the trim-start frame to "first frame" so any later
            # fallback (e.g. _render_current_frame when no scrub) uses it.
            if self._current_scrub_frame_bgr is not None:
                self._first_frame_bgr = self._current_scrub_frame_bgr.copy()
        except Exception as e:
            logger.warn(f"apply_trim_to_scrub seek failed: {e}",
                        source="scrub")

    def _setup_shortcuts(self):
        bind = lambda keys, fn: QShortcut(QKeySequence(keys), self,
                                          activated=fn)
        bind(Qt.Key_Left,         lambda: self._step_scrub(-1))
        bind(Qt.Key_Right,        lambda: self._step_scrub(1))
        bind("Shift+Left",        lambda: self._step_scrub(-10))
        bind("Shift+Right",       lambda: self._step_scrub(10))
        bind("Ctrl+Left",         lambda: self._step_scrub(-100))
        bind("Ctrl+Right",        lambda: self._step_scrub(100))
        bind(Qt.Key_Home,         lambda: self.slider_scrub.setValue(0))
        bind(Qt.Key_End,          lambda: self.slider_scrub.setValue(
            self.slider_scrub.maximum()))
        bind("N",                 self._jump_next_miss)
        bind("E",                 lambda: (self.btn_view_processed.toggle()
            if self.btn_view_processed.isEnabled() else None))
        bind("D",                 lambda: (self.btn_preview.toggle()
            if self.btn_preview.isEnabled() else None))

    def _step_scrub(self, delta):
        if not self.slider_scrub.isEnabled():
            return
        new_val = max(0, min(self.slider_scrub.maximum(),
                             self.slider_scrub.value() + delta))
        self.slider_scrub.setValue(new_val)

    def _update_scrub_label(self, frame_idx=None, total_frames=None):
        # Show position relative to the slider's CURRENT range, so the label
        # automatically tracks any trim window the slider was clamped to.
        fps = self.fps or 30
        lo = self.slider_scrub.minimum()
        hi = self.slider_scrub.maximum()
        cur = (self.slider_scrub.value() - lo) / fps
        tot = (hi - lo + 1) / fps
        def fmt(s):
            m, sec = divmod(max(0.0, s), 60)
            return f"{int(m):02d}:{sec:04.1f}"
        self.lbl_scrub.setText(fmt(cur))
        if hasattr(self, "lbl_total"):
            self.lbl_total.setText(f"/ {fmt(tot)}")
        if hasattr(self, "time_ticks"):
            self.time_ticks.set_duration(tot)
