"""Annotated-video export QThread.

Renders a copy of the source video with zone outlines, body overlays, cell
highlights and trail burned in. The owner argument is a duck-typed object
(typically OpenFieldTab) exposing the video path, transforms, drawing
helpers, and current widget state.
"""
import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal


class VideoExportThread(QThread):
    """Render an annotated copy of the loaded video. Reads frames in
    [start_frame, end_frame], applies the current crop / homography /
    preprocessing, draws zone outlines + body overlays per the View popup
    state, and writes mp4 via cv2.VideoWriter."""

    progress = pyqtSignal(int)
    error = pyqtSignal(str)
    done = pyqtSignal(str)

    def __init__(self, owner, output_path, start_frame, end_frame, flags=None):
        super().__init__()
        self.owner = owner
        self.output_path = output_path
        self.start_frame = max(0, int(start_frame))
        self.end_frame = max(self.start_frame, int(end_frame))
        # Per-overlay include flags. Missing keys fall back to True (live-preview
        # parity) — caller passes the dict from the Export tab checkboxes.
        self.flags = dict(flags or {})
        self._stop = False

    def _flag(self, key, default=True):
        return bool(self.flags.get(key, default))

    def stop(self):
        self._stop = True

    def run(self):
        of = self.owner
        try:
            cap = cv2.VideoCapture(of.video_path)
            if not cap.isOpened():
                self.error.emit("Cannot open the source video.")
                return
            fps = of.fps or cap.get(cv2.CAP_PROP_FPS) or 30.0

            # Output frame size — apply crop, then warp target if perspective on.
            if of._crop_rect is not None:
                _, _, cw, ch = of._crop_rect
                w, h = int(cw), int(ch)
            else:
                w = int(of.video_w or cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(of.video_h or cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if of._H is not None:
                target = of._warp_target_size()
                if target:
                    w, h = int(target[0]), int(target[1])

            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(self.output_path, fourcc, fps, (w, h))
            if not writer.isOpened():
                cap.release()
                self.error.emit("Cannot open the output video for writing.")
                return

            cap.set(cv2.CAP_PROP_POS_FRAMES, self.start_frame)
            total = max(1, self.end_frame - self.start_frame + 1)
            # Pull flag values once.
            view_effects = self._flag("view_effects",
                                      bool(of.btn_view_processed.isChecked()))
            do_arena     = self._flag("arena", True)
            # Legacy key "center" still accepted if "center_zone" is missing.
            do_center    = self._flag("center_zone", self._flag("center", True))
            do_grid      = self._flag("grid", True)
            do_exclusion = self._flag("exclusion", True)
            export_body_style = self.flags.get("body_style")
            do_body      = self._flag("body",
                                      True if export_body_style is None
                                      else export_body_style != "off")
            do_ellipse   = self._flag("ellipse", bool(of.chk_ellipse.isChecked()))
            do_trail     = self._flag("trail", bool(of.chk_trail.isChecked()))
            do_trail_fade = self._flag("trail_fade", bool(of.chk_trail_fade.isChecked()))
            trail_n      = int(self.flags.get("trail_len",
                                              of.spin_trail_len.value()))
            do_cell_hi   = self._flag("cell_highlight", True)
            do_cell_num  = self._flag("cell_numbers", True)
            do_cell_tim  = self._flag("cell_timer", True)
            do_cell_ent  = self._flag("cell_entries", True)
            any_cell_overlay = do_cell_hi or do_cell_num or do_cell_tim or do_cell_ent
            # Body style: prefer the export panel's own dropdown; fall back
            # to the View popup's live combo. "off" / unchecked → render none.
            if not do_body:
                body_style = "none"
            elif export_body_style is not None:
                body_style = export_body_style
            else:
                body_style = of.combo_body_style.currentData()

            # Optional path smoothing for the export — uses the unsmoothed raw
            # results so it's independent of whatever smoothing the live
            # preview is using.
            smooth_n = int(self.flags.get("smooth_n", 0) or 0)
            base_results = of._raw_results or of.tracking_results
            if smooth_n > 0 and base_results:
                results_for_export = of._apply_smoothing(base_results, smooth_n)
            else:
                results_for_export = of.tracking_results

            # Pre-compute per-frame cell ids and set up running counters
            # (debounced by min-dwell — same logic as _compute_cell_times_through).
            cids_seq = of._build_cell_id_sequence() if any_cell_overlay else []
            fps_eff = of.fps or fps or 30.0
            dt = 1.0 / fps_eff
            min_dwell = of._cell_min_dwell_s()
            min_frames = max(1, int(round(min_dwell * fps_eff))) if min_dwell > 0 else 1
            cell_times = {}
            cell_entries = {}
            pending_cid = None
            pending_frames = 0
            confirmed_cid = None
            # Center 'C' running counter — only used in grid mode (center mode
            # already gets 'C' through cids_seq).
            c_in_seq = []
            if any_cell_overlay and of.zone_drawer.zone_mode == "grid":
                center_px = of.zone_drawer.get_center_pixels()
                if center_px and len(center_px) >= 3:
                    c_poly = np.array(center_px, dtype=np.float32)
                    for r in results_for_export:
                        x, y = r.get("x"), r.get("y")
                        if x is None or y is None:
                            c_in_seq.append(False)
                        else:
                            c_in_seq.append(
                                cv2.pointPolygonTest(c_poly, (float(x), float(y)), False) >= 0
                            )
            c_pending = 0
            c_confirmed = False

            for i in range(self.start_frame, self.end_frame + 1):
                if self._stop:
                    break
                ret, frame = cap.read()
                if not ret:
                    break
                # tracking_results / cids_seq / c_in_seq are trim-relative
                # (length = trimmed frame count, indexed from 0). Map the
                # source-frame index `i` to its trim-relative slot.
                rel_i = i - self.start_frame
                # Update running cell state (always — cheap, lets us draw the
                # "active cell" highlight without re-walking history).
                if any_cell_overlay and cids_seq:
                    cid_now = cids_seq[rel_i] if 0 <= rel_i < len(cids_seq) else None
                    if cid_now == pending_cid:
                        pending_frames += 1
                    else:
                        pending_cid = cid_now
                        pending_frames = 1
                    if pending_frames >= min_frames and cid_now is not None:
                        if cid_now != confirmed_cid:
                            cell_entries[cid_now] = cell_entries.get(cid_now, 0) + 1
                            cell_times[cid_now] = cell_times.get(cid_now, 0.0) + pending_frames * dt
                            confirmed_cid = cid_now
                        elif pending_frames == min_frames:
                            # Re-entry to same confirmed cell just crossed the
                            # threshold — credit the pending dwell in bulk.
                            cell_times[cid_now] = cell_times.get(cid_now, 0.0) + pending_frames * dt
                        else:
                            cell_times[cid_now] = cell_times.get(cid_now, 0.0) + dt
                # Center polygon ('C') in grid mode — parallel debounce.
                if c_in_seq:
                    in_c = c_in_seq[rel_i] if 0 <= rel_i < len(c_in_seq) else False
                    if in_c:
                        c_pending += 1
                        if c_pending >= min_frames:
                            if not c_confirmed:
                                cell_entries["C"] = cell_entries.get("C", 0) + 1
                                cell_times["C"] = cell_times.get("C", 0.0) + c_pending * dt
                                c_confirmed = True
                            else:
                                cell_times["C"] = cell_times.get("C", 0.0) + dt
                    else:
                        c_pending = 0
                        c_confirmed = False
                # Crop → warp → preprocessing — same chain as the live preview.
                if of._crop_rect is not None:
                    cx, cy, cw, ch = of._crop_rect
                    frame = frame[cy:cy + ch, cx:cx + cw]
                if of._H is not None:
                    frame = of._warp(frame)
                if view_effects:
                    frame = of._get_processed_frame_bgr(frame)
                else:
                    frame = frame.copy()
                # Burn-in overlays.
                of._draw_zones_on_frame_cv2(
                    frame,
                    draw_arena=do_arena,
                    draw_center=do_center,
                    draw_grid=do_grid,
                    draw_exclusion=do_exclusion,
                )
                if any_cell_overlay:
                    of._draw_cell_overlay_cv2(
                        frame, confirmed_cid, cell_times, cell_entries,
                        draw_highlight=do_cell_hi,
                        draw_numbers=do_cell_num,
                        draw_timer=do_cell_tim,
                        draw_entries=do_cell_ent,
                    )
                if results_for_export and 0 <= rel_i < len(results_for_export):
                    r = results_for_export[rel_i]
                    of._draw_body_on_frame(
                        frame, r, rel_i,
                        body_style=body_style,
                        draw_ellipse=do_ellipse,
                        draw_trail=do_trail,
                        trail_len=trail_n,
                        trail_fade=do_trail_fade,
                        results_override=results_for_export,
                    )
                # Make sure the frame matches writer resolution (defensive).
                if frame.shape[1] != w or frame.shape[0] != h:
                    frame = cv2.resize(frame, (w, h))
                writer.write(frame)
                done_n = i - self.start_frame + 1
                self.progress.emit(int(100 * done_n / total))
            cap.release()
            writer.release()
            if self._stop:
                self.error.emit("Cancelled.")
                return
            self.done.emit(self.output_path)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))
