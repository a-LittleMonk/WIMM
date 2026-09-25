"""CorrectionsMixin — manual tracking-fix tools.

Mixed into ExperimentTab. Owns:
    - the Corrections popup launcher (Fix / Clear / Next-miss / Interpolate),
    - Fix Position click → override tracked X/Y for the current frame,
    - Clear-fixes (drop corrected + interpolated flags),
    - Next-miss seek,
    - Interpolate missing frames,
    - Smoothing toggle (re-applies to _raw_results).

Reuses host attrs:
    self.tracking_results, self._raw_results, self.slider_scrub,
    self.video_w, self.video_h, self.btn_excl, self.btn_fix,
    self.btn_clear_fixes, self.btn_next_miss, self.btn_interpolate,
    self.spin_smooth, self.lbl_track, self.zone_drawer,
    self._corrections_popup, self._slider_to_results_idx,
    self._trim_start_frame, self._on_scrub,
    self._recompute_metrics_and_views.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QFrame, QLabel, QPushButton

from gui.zone_drawer import ZoneDrawer


from gui import theme


class CorrectionsMixin:
    def _open_corrections_popup(self):
        """Show the manual-corrections popup (Fix / Clear / Next miss /
        Interpolate). Non-modal, draggable, can sit next to the video.
        When the screen has a Frame corrections panel, show that instead."""
        show_panel = getattr(self, "_show_corrections_panel", None)
        if show_panel is not None:
            show_panel()
            return
        if self._corrections_popup is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("Corrections")
            dlg.setWindowFlags(dlg.windowFlags() | Qt.Tool)
            v = QVBoxLayout(dlg)
            v.setContentsMargins(10, 10, 10, 10)
            v.setSpacing(6)
            v.addWidget(QLabel("Manual tracking corrections:"))
            v.addWidget(self.btn_fix)
            v.addWidget(self.btn_clear_fixes)
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setProperty("role", "hline")
            v.addWidget(sep)
            v.addWidget(self.btn_next_miss)
            v.addWidget(self.btn_interpolate)
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(dlg.close)
            v.addWidget(close_btn)
            self._corrections_popup = dlg
        self._corrections_popup.show()
        self._corrections_popup.raise_()
        self._corrections_popup.activateWindow()

    def _on_fix_toggled(self, checked):
        if checked:
            self.btn_excl.setChecked(False)
            self.zone_drawer.set_mode(ZoneDrawer.MODE_CORRECT)
        else:
            self.zone_drawer.set_mode(ZoneDrawer.MODE_IDLE)

    def _on_correction_click(self, nx, ny):
        if not self.tracking_results:
            return
        slider_val = self.slider_scrub.value()
        rel_idx = self._slider_to_results_idx(slider_val)
        x_px = nx * (self.video_w or 1)
        y_px = ny * (self.video_h or 1)
        r = self.tracking_results[rel_idx]
        r["x"] = x_px
        r["y"] = y_px
        r["corrected"] = True
        self._on_scrub(slider_val)

    def _clear_fixes(self):
        if not self.tracking_results:
            return
        for r in self.tracking_results:
            r.pop("corrected", None)
            if r.pop("interpolated", None):
                r["x"] = None
                r["y"] = None
        self._on_scrub(self.slider_scrub.value())
        self.btn_clear_fixes.setEnabled(False)

    def _apply_smoothing(self, raw, window):
        if not raw:
            return []
        if window <= 1:
            return [dict(r) for r in raw]
        keys = ("x", "y")
        n = len(raw)
        half = window // 2
        smoothed = [dict(r) for r in raw]
        for i in range(n):
            for k in keys:
                if smoothed[i].get(k) is None:
                    continue
                acc, count = 0.0, 0
                for j in range(max(0, i - half), min(n, i + half + 1)):
                    v = raw[j].get(k)
                    if v is not None:
                        acc += v
                        count += 1
                if count:
                    smoothed[i][k] = acc / count
        return smoothed

    def _on_smooth_changed(self, _value):
        if not self._raw_results:
            return
        self.tracking_results = self._apply_smoothing(
            self._raw_results, self.spin_smooth.value()
        )
        self._on_scrub(self.slider_scrub.value())
        self._recompute_metrics_and_views()

    def _jump_next_miss(self):
        if not self.tracking_results:
            return
        n = len(self.tracking_results)
        offset = self._trim_start_frame()
        cur_rel = self._slider_to_results_idx(self.slider_scrub.value())
        start = cur_rel + 1
        for i in list(range(start, n)) + list(range(0, start)):
            if self.tracking_results[i].get("x") is None:
                self.slider_scrub.setValue(i + offset)
                return

    def _interpolate_gaps(self):
        if not self.tracking_results:
            return
        results = self.tracking_results
        n = len(results)
        filled = 0
        i = 0
        while i < n:
            if results[i].get("x") is None:
                j = i
                while j < n and results[j].get("x") is None:
                    j += 1
                prev = i - 1
                if prev >= 0 and j < n:
                    x0, y0 = results[prev]["x"], results[prev]["y"]
                    x1, y1 = results[j]["x"], results[j]["y"]
                    span = j - prev
                    for k in range(i, j):
                        t = (k - prev) / span
                        results[k]["x"] = x0 + t * (x1 - x0)
                        results[k]["y"] = y0 + t * (y1 - y0)
                        results[k]["interpolated"] = True
                        filled += 1
                i = j
            else:
                i += 1
        self.btn_clear_fixes.setEnabled(True)
        self._on_scrub(self.slider_scrub.value())
        if filled:
            self.lbl_track.setText(f"Interpolated {filled} missing frames")
            theme.set_tone(self.lbl_track, "warn", "font-size:11px;")
        else:
            self.lbl_track.setText("No gaps to interpolate")
            theme.set_tone(self.lbl_track, "faint", "font-size:11px;")
