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

    def _refresh_correction_buttons(self):
        """Fix / Next miss / Interpolate need tracked results; Clear needs at
        least one manual fix or interpolated frame."""
        has = bool(self.tracking_results)
        for b in (self.btn_fix, self.btn_next_miss, self.btn_interpolate):
            b.setEnabled(has)
        if not has and self.btn_fix.isChecked():
            self.btn_fix.setChecked(False)
        self.btn_clear_fixes.setEnabled(has and any(
            r.get("corrected") or r.get("interpolated")
            for r in (self._raw_results or self.tracking_results)))

    def _on_fix_toggled(self, checked):
        if checked:
            self.btn_excl.setChecked(False)
            self.zone_drawer.set_mode(ZoneDrawer.MODE_CORRECT)
        else:
            self.zone_drawer.set_mode(ZoneDrawer.MODE_IDLE)

    def _display_frame_size(self):
        """Width / height of the frame shown on the video (after crop /
        warp) — tracked x/y are in these pixels."""
        frame = (self._current_scrub_frame_bgr
                 if self._current_scrub_frame_bgr is not None else self._first_frame_bgr)
        if frame is not None:
            return frame.shape[1], frame.shape[0]
        return (self.video_w or 1), (self.video_h or 1)

    def _result_rows(self, idx):
        """The same frame in the shown (smoothed) results and in the raw
        results, so a fix survives a smoothing change."""
        rows = [self.tracking_results[idx]]
        raw = self._raw_results
        if raw and idx < len(raw) and raw[idx] is not rows[0]:
            rows.append(raw[idx])
        return rows

    def _on_correction_click(self, nx, ny):
        if not self.tracking_results:
            return
        slider_val = self.slider_scrub.value()
        rel_idx = self._slider_to_results_idx(slider_val)
        w, h = self._display_frame_size()
        for r in self._result_rows(rel_idx):
            if not r.get("corrected") and not r.get("interpolated"):
                r["orig_x"], r["orig_y"] = r.get("x"), r.get("y")   # for Clear
            r.pop("interpolated", None)
            r["x"] = nx * w
            r["y"] = ny * h
            r["corrected"] = True
        self.btn_clear_fixes.setEnabled(True)
        self._on_scrub(slider_val)
        self._corrections_changed()

    def _corrections_changed(self):
        """Recompute metrics / graphs once the user pauses fixing."""
        from PyQt5.QtCore import QTimer
        t = getattr(self, "_corrections_timer", None)
        if t is None:
            t = self._corrections_timer = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(600)
            t.timeout.connect(self._recompute_metrics_and_views)
        t.start()

    def _clear_fixes(self):
        if not self.tracking_results:
            return
        for rows in (self.tracking_results, self._raw_results or []):
            for r in rows:
                if r.pop("corrected", None) or r.pop("interpolated", None):
                    r["x"] = r.pop("orig_x", None)
                    r["y"] = r.pop("orig_y", None)
                r.pop("interpolated", None)
        # Re-smooth so the restored frames match the other ones.
        if self._raw_results:
            self.tracking_results = self._apply_smoothing(
                self._raw_results, self.spin_smooth.value())
        self._on_scrub(self.slider_scrub.value())
        self.btn_clear_fixes.setEnabled(False)
        self._corrections_changed()

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
            if smoothed[i].get("corrected"):
                continue                  # a manual fix is kept exactly
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

    def _interpolate_gaps(self, max_len=None):
        """Fill runs of missed frames with a straight line between the good
        frames on both sides. `max_len` (frames): longer runs are skipped."""
        if not self.tracking_results:
            return
        results = self.tracking_results
        n = len(results)
        filled = 0
        skipped = 0
        i = 0
        while i < n:
            if results[i].get("x") is None:
                j = i
                while j < n and results[j].get("x") is None:
                    j += 1
                prev = i - 1
                if max_len is not None and (j - i) > int(max_len):
                    skipped += 1            # longer than Max gap: leave missed
                elif prev >= 0 and j < n:
                    x0, y0 = results[prev]["x"], results[prev]["y"]
                    x1, y1 = results[j]["x"], results[j]["y"]
                    span = j - prev
                    for k in range(i, j):
                        t = (k - prev) / span
                        for r in self._result_rows(k):
                            if "orig_x" not in r:      # keep a removed point's original
                                r["orig_x"], r["orig_y"] = None, None   # for Clear
                            r.pop("corrected", None)
                            r["x"] = x0 + t * (x1 - x0)
                            r["y"] = y0 + t * (y1 - y0)
                            r["interpolated"] = True
                        filled += 1
                i = j
            else:
                i += 1
        self._on_scrub(self.slider_scrub.value())
        if filled:
            self.btn_clear_fixes.setEnabled(True)
            self._corrections_changed()
            self.lbl_track.setText(f"Interpolated {filled} missing frames"
                                   + (f" ({skipped} longer gap(s) left)" if skipped else ""))
            theme.set_tone(self.lbl_track, "warn", "font-size:11px;")
        else:
            self.lbl_track.setText("No gaps to interpolate")
            theme.set_tone(self.lbl_track, "faint", "font-size:11px;")
