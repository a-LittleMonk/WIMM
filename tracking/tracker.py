import time
import threading
import queue as _queue
from collections import deque
import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from tracking.preprocessor import apply_preprocessing, get_mask, get_morph_kernel
from core import logger


class _FramePrefetcher:
    """Reads frames from a cv2.VideoCapture in a background thread, applies
    crop + perspective warp, and queues them. cv2.read() and cv2.warp
    release the GIL, so this stage runs in parallel with the tracker's
    main-thread compute. Sequential reads only — caller must position the
    cap before constructing."""
    _SENTINEL = object()

    def __init__(self, cap, crop_rect=None, homography=None, warp_size=None,
                 queue_size=12, frame_skip=1):
        self._cap = cap
        self._crop = crop_rect
        self._H = homography
        self._warp_size = warp_size
        self._frame_skip = max(1, int(frame_skip))
        self._q = _queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        try:
            while not self._stop.is_set():
                ret, frame = self._cap.read()
                if not ret:
                    self._q.put(self._SENTINEL)
                    return
                if self._crop:
                    cx, cy, cw, ch = self._crop
                    frame = frame[cy:cy + ch, cx:cx + cw]
                if self._H is not None and self._warp_size is not None:
                    frame = cv2.warpPerspective(frame, self._H, self._warp_size)
                while not self._stop.is_set():
                    try:
                        self._q.put(frame, timeout=0.1)
                        break
                    except _queue.Full:
                        continue
                # Skip the next (frame_skip - 1) frames using grab() — much
                # cheaper than read() because it decodes but doesn't copy
                # the frame to a Python buffer.
                for _ in range(self._frame_skip - 1):
                    if self._stop.is_set():
                        break
                    if not self._cap.grab():
                        self._q.put(self._SENTINEL)
                        return
        except Exception as e:
            logger.warn(f"FramePrefetcher loop crashed: {e}", source="tracker")
            try:
                self._q.put(self._SENTINEL)
            except Exception:
                # Queue likely closed during teardown — expected.
                pass

    def read(self):
        item = self._q.get()
        if item is self._SENTINEL:
            return False, None
        return True, item

    def stop(self):
        self._stop.set()
        try:
            while True:
                self._q.get_nowait()
        except _queue.Empty:
            pass
        self._thread.join(timeout=1.0)


def _apply_arena_and_morph(mask, arena, kernel_wh=None, arena_mask=None):
    if arena_mask is not None:
        mask = cv2.bitwise_and(mask, arena_mask)
    elif arena:
        h, w = mask.shape
        am = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(am, [np.array(arena, dtype=np.int32)], 255)
        mask = cv2.bitwise_and(mask, am)
    h, w = mask.shape
    if kernel_wh and kernel_wh[0] > 0 and kernel_wh[1] > 0:
        # RECT matches the default returned by get_morph_kernel — separable
        # in OpenCV, so a k×k rect runs ~2× faster than the equivalent
        # ellipse with no meaningful change to centroid / area / moments.
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, kernel_wh)
    else:
        kernel = get_morph_kernel(h, w)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


DEFAULT_MODEL_PARAMS = {
    "median": {
        "bg_sample_count": 120,
    },
    "mog2": {
        "history": 500, "varThreshold": 16.0, "detectShadows": False,
        "nMixtures": 5, "backgroundRatio": 0.9, "varThresholdGen": 9.0,
        "complexityReductionThreshold": 0.05,
        "varInit": 15.0, "varMin": 4.0, "varMax": 75.0,
        "shadowThreshold": 0.5, "shadowValue": 127,
        "learningRate": 0.0,
    },
    "knn": {
        "history": 500, "dist2Threshold": 400.0, "detectShadows": False,
        "kNNSamples": 2, "nSamples": 7,
        "shadowThreshold": 0.5, "shadowValue": 127,
        "learningRate": 0.0,
    },
    "cnt": {
        "minPixelStability": 15, "maxPixelStability": 900,
        "useHistory": True, "isParallel": True,
        "learningRate": 0.0,
    },
    "gsoc": {
        "mc": 0, "nSamples": 20, "replaceRate": 0.003,
        "propagationRate": 0.01, "hitsThreshold": 32,
        "alpha": 0.01, "beta": 0.0022,
        "blinkingSupressionDecay": 0.1, "blinkingSupressionMultiplier": 0.1,
        "noiseRemovalThresholdFacBG": 0.0004, "noiseRemovalThresholdFacFG": 0.0008,
        "learningRate": 0.0,
    },
    "lsbp": {
        "mc": 0, "nSamples": 20, "LSBPRadius": 16,
        "Tlower": 2.0, "Tupper": 32.0, "Tinc": 1.0, "Tdec": 0.05,
        "Rscale": 10.0, "Rincdec": 0.005,
        "noiseRemovalThresholdFacBG": 0.0004, "noiseRemovalThresholdFacFG": 0.0008,
        "LSBPthreshold": 8, "minCount": 2,
        "learningRate": 0.0,
    },
    "framediff": {
        "diff_threshold": 25, "use_running_avg": False, "running_avg_alpha": 0.05,
    },
    "hsv": {
        "channel": "V", "mode": "otsu",
        "manual_threshold": 80, "invert": True,
    },
}

DEFAULT_POST_PARAMS = {
    "min_blob_area": 150,
    "morph_kernel_w": 0,
    "morph_kernel_h": 0,
}


# Default (BGR): body=dark red, nose=green, tail=blue
_DEFAULT_BODY = (0, 0, 160)
_DEFAULT_NOSE = (0, 200, 0)
_DEFAULT_TAIL = (200, 100, 0)


def _draw_body(vis, body, style="dot", body_color=_DEFAULT_BODY,
               nose=None, tail=None,
               nose_color=_DEFAULT_NOSE, tail_color=_DEFAULT_TAIL):
    """Render tracking dots. style:
        "off"  — nothing
        "dot"  — body centroid only
        "ends" — body centroid + nose (green) + tail (blue) + axis line
    """
    if style in ("dot", "ends") and body is not None:
        x, y = int(body[0]), int(body[1])
        cv2.circle(vis, (x, y), 6, body_color, -1)
        cv2.circle(vis, (x, y), 8, body_color, 2)
    if style == "ends" and body is not None:
        if nose is not None and tail is not None:
            cv2.line(vis, (int(tail[0]), int(tail[1])),
                     (int(nose[0]), int(nose[1])), body_color, 1, cv2.LINE_AA)
        if nose is not None:
            nx, ny = int(nose[0]), int(nose[1])
            cv2.circle(vis, (nx, ny), 5, nose_color, -1)
            cv2.circle(vis, (nx, ny), 7, nose_color, 2)
        if tail is not None:
            tx, ty = int(tail[0]), int(tail[1])
            cv2.circle(vis, (tx, ty), 4, tail_color, -1)
            cv2.circle(vis, (tx, ty), 6, tail_color, 2)


class TrackerThread(QThread):
    progress = pyqtSignal(int)
    preview = pyqtSignal(object)
    body_pos = pyqtSignal(object)  # emits (x, y) pixels per detected frame, or None
    nose_pos = pyqtSignal(object)  # emits (x, y) pixels per detected frame, or None
    finished_tracking = pyqtSignal(list)
    error = pyqtSignal(str)
    status_msg = pyqtSignal(str)

    def __init__(self, video_path: str, arena=None, threshold: int = 25,
                 brightness: int = 0, contrast: float = 1.0, blur: int = 0,
                 gamma: float = 1.0, sharpen: int = 0, clahe_clip: int = 0,
                 model: str = "median", exclusion_mask=None, body_style: str = "dot",
                 max_blob_pct: int = 0,
                 proc_scale: float = 1.0,
                 colors: dict = None,
                 homography=None, warp_size=None,
                 model_params: dict = None, post_params: dict = None,
                 fps_override: float = 0.0,
                 trim_start_s: float = 0.0, trim_duration_s: float = 0.0,
                 crop_rect=None, frame_skip: int = 1,
                 smooth_window: int = 3,
                 enable_nose: bool = False):
        super().__init__()
        self.video_path = video_path
        self.arena = arena
        self.threshold = threshold
        self.brightness = brightness
        self.contrast = contrast
        self.blur = blur
        self.gamma = gamma
        self.sharpen = sharpen
        self.clahe_clip = clahe_clip
        self.model = model
        defaults = DEFAULT_MODEL_PARAMS.get(model, {})
        self.model_params = {**defaults, **(model_params or {})}
        self.post_params = {**DEFAULT_POST_PARAMS, **(post_params or {})}
        self._morph_kernel_wh = (
            int(self.post_params.get("morph_kernel_w", 0)),
            int(self.post_params.get("morph_kernel_h", 0)),
        )
        self.exclusion_mask = exclusion_mask.copy() if exclusion_mask is not None else None
        self.body_style = body_style
        self.max_blob_pct = max_blob_pct
        self.proc_scale = max(0.1, min(1.0, proc_scale))
        c = colors or {}
        self._c_body = c.get("body", _DEFAULT_BODY)
        self._c_nose = c.get("nose", _DEFAULT_NOSE)
        self._c_tail = c.get("tail", _DEFAULT_TAIL)
        self.homography = homography
        self.warp_size  = warp_size
        self.fps_override = max(0.0, float(fps_override))
        self.trim_start_s = max(0.0, float(trim_start_s))
        self.trim_duration_s = max(0.0, float(trim_duration_s))
        # crop_rect: tuple (x, y, w, h) in full-frame pixels, or None.
        # When set, every read frame is cropped before any processing —
        # tracker effectively sees a smaller video.
        self.crop_rect = crop_rect
        # frame_skip: process every Nth frame; the others are skipped (via
        # cap.grab) and later linearly interpolated. 1 = no skip.
        self.frame_skip = max(1, int(frame_skip))
        # smooth_window: rolling-median window on body/nose/tail coords
        # (post-processed). Must be odd ≥3 to fire; otherwise no-op.
        self.smooth_window = int(smooth_window)
        # Nose / tail detection toggle. When False (the default for OF /
        # Y-Maze / EPM, which use body-center metrics) the tracker skips
        # the mass-asymmetry scan, the leading-edge frame-diff and the
        # whole _resolve_nose state machine — saves ~2.5 ms/frame at
        # 640×480. NOR enables it by default (the angle filter needs the
        # nose heading). nose_x / nose_y / tail_x / tail_y come out as
        # None for every frame when off.
        self.enable_nose = bool(enable_nose)
        self._min_area = 0
        self._max_area = 0
        self._stop_flag = False
        self._last_preview_time = 0.0
        self._last_pos_emit_time = 0.0
        # Progress emit throttle — only fire when the integer percent
        # changes. Drops 18000 emits to at most 100 over a full run.
        self._last_progress_pct = -1
        self._reset_nose_state()

    def _reset_nose_state(self):
        """Reset per-session nose-tracking state. Call at start of each
        _track_* method."""
        self._prev_mask = None        # proc-scale binary mask from previous frame
        self._prev_body = None        # body centroid (proc-scale) prev frame
        self._prev_nose = None        # nose pt (proc-scale) prev frame
        self._prev_axis = None        # unit vector along major axis pointing toward prev nose
        self._velocity = np.zeros(2)  # EMA of body velocity (proc-scale px/frame)
        self._cum_rot = 0.0           # cumulative |angle change| since last flip
        self._prev_angle = None       # raw ellipse angle prev frame (deg)
        self._locked = False          # nose locked? freezes mass/motion flips
        self._mass_ema = 0.0          # smoothed mass-asym (kills per-frame flicker)
        self._mass_ema_init = False
        self._prev_conf = 0.0         # last frame's confidence

    def stop(self):
        self._stop_flag = True

    def _warp_frame(self, frame):
        if self.homography is None or self.warp_size is None:
            return frame
        return cv2.warpPerspective(frame, self.homography, self.warp_size)

    def _read(self, cap):
        """Read next frame from cap and apply crop if set."""
        _ret_internal, _frame_internal = cap.read()
        if _ret_internal and self.crop_rect:
            cx, cy, cw, ch = self.crop_rect
            _frame_internal = _frame_internal[cy:cy + ch, cx:cx + cw]
        return _ret_internal, _frame_internal

    def _scale_frame(self, frame):
        if self.proc_scale == 1.0:
            return frame
        return cv2.resize(frame, (self._pw, self._ph), interpolation=cv2.INTER_AREA)

    def _scale_pt(self, pt):
        if pt is None or self.proc_scale == 1.0:
            return pt
        return (pt[0] * self._up, pt[1] * self._up)

    def run(self):
        try:
            self._track()
        except Exception as e:
            self.error.emit(str(e))

    def _track(self):
        cv2.setUseOptimized(True)
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            self.error.emit("Cannot open video file.")
            return
        try:
            fps = self.fps_override if self.fps_override > 0 else (cap.get(cv2.CAP_PROP_FPS) or 30.0)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if self.crop_rect:
                fw = int(self.crop_rect[2])
                fh = int(self.crop_rect[3])
            # When perspective is on, every frame is warped to warp_size before
            # processing. All downstream coords + draws live in warp space, so
            # fw/fh must follow — otherwise _pw/_ph and _scale_pt skew the dots.
            if self.warp_size is not None:
                fw, fh = int(self.warp_size[0]), int(self.warp_size[1])

            # Apply session trimming (start + duration)
            self._start_frame = int(round(self.trim_start_s * fps))
            if self.trim_duration_s > 0:
                self._end_frame = min(total, self._start_frame + int(round(self.trim_duration_s * fps)))
            else:
                self._end_frame = total
            self._start_frame = max(0, min(self._start_frame, total))
            self._end_frame   = max(self._start_frame, self._end_frame)

            # Processing-resolution setup
            self._pw = max(1, int(fw * self.proc_scale))
            self._ph = max(1, int(fh * self.proc_scale))
            self._up = fw / self._pw   # coordinate scale-up factor = 1/proc_scale
            self._arena_proc = (
                [(int(x * self.proc_scale), int(y * self.proc_scale)) for x, y in self.arena]
                if self.arena else None
            )
            if self._arena_proc:
                self._arena_mask_proc = np.zeros((self._ph, self._pw), dtype=np.uint8)
                cv2.fillPoly(self._arena_mask_proc,
                             [np.array(self._arena_proc, dtype=np.int32)], 255)
            else:
                self._arena_mask_proc = None
            self._excl_proc = (
                cv2.resize(self.exclusion_mask, (self._pw, self._ph),
                           interpolation=cv2.INTER_NEAREST)
                if self.exclusion_mask is not None else None
            )
            # Pre-invert once. Every frame previously recomputed
            # cv2.bitwise_not on the same static mask — pure waste.
            self._excl_proc_inv = (
                cv2.bitwise_not(self._excl_proc)
                if self._excl_proc is not None else None
            )
            # Fused "allowed region" = arena ∩ ¬exclusion. Computed once;
            # every frame can now AND the foreground mask against this
            # single bitmap instead of doing two separate bitwise_and ops.
            # Cases:
            #   both set  → AND together
            #   arena only → arena_mask_proc
            #   excl only  → excl_proc_inv
            #   neither    → None (skip the AND entirely)
            if self._arena_mask_proc is not None and self._excl_proc_inv is not None:
                self._allowed_mask = cv2.bitwise_and(
                    self._arena_mask_proc, self._excl_proc_inv
                )
            elif self._arena_mask_proc is not None:
                self._allowed_mask = self._arena_mask_proc
            elif self._excl_proc_inv is not None:
                self._allowed_mask = self._excl_proc_inv
            else:
                self._allowed_mask = None
            self._min_area = max(1, int(self.post_params.get("min_blob_area", 150) * self.proc_scale ** 2))
            self._max_area = int(self._pw * self._ph * self.max_blob_pct / 100) if self.max_blob_pct > 0 else 0

            if total == 0:
                self.error.emit("Video has no frames.")
                return

            SUBTRACTOR_MODELS = {"mog2", "knn", "cnt", "gsoc", "lsbp"}
            # Use trimmed range as effective total
            total = self._end_frame - self._start_frame
            if total <= 0:
                self.error.emit("Trim range produces no frames.")
                return
            if self.model == "median":
                results = self._track_median(cap, fps, total)
            elif self.model in SUBTRACTOR_MODELS:
                sub = self._make_subtractor(self.model)
                if sub is None:
                    self.error.emit(
                        f"Model '{self.model}' unavailable. Install opencv-contrib-python."
                    )
                    return
                results = self._track_subtractor(cap, fps, total, sub, self.model.upper())
            elif self.model == "framediff":
                results = self._track_framediff(cap, fps, total)
            elif self.model == "hsv":
                results = self._track_hsv(cap, fps, total)
            else:
                results = self._track_median(cap, fps, total)

            if results is not None:
                # Rolling median kills single-frame outliers in body/nose/
                # tail coords without smoothing genuine motion. Window is
                # user-tunable via Step 5 (Off / 3 / 5 / 7 / 9).
                results = _median_filter_results(results, window=self.smooth_window)
                if self.frame_skip > 1:
                    results = self._interpolate_skipped(results, fps)
                self.finished_tracking.emit(results)
        finally:
            cap.release()

    def _interpolate_skipped(self, results, fps):
        """Densify a sparse result list (every frame_skip-th frame) by
        linearly interpolating x, y for the skipped frames in between.
        Returns a new list of length last_frame+1."""
        if not results:
            return results
        # Map frame -> result, find frame range.
        by_frame = {r["frame"]: r for r in results}
        sparse_idxs = sorted(by_frame.keys())
        total_n = sparse_idxs[-1] + 1
        keys = ("x", "y", "nose_x", "nose_y", "tail_x", "tail_y")
        carry_keys = ("ellipse_semi_major", "ellipse_semi_minor",
                      "ellipse_angle", "nose_confidence")
        dense = [None] * total_n
        for r in results:
            if 0 <= r["frame"] < total_n:
                dense[r["frame"]] = r
        for j in range(len(sparse_idxs) - 1):
            a_idx = sparse_idxs[j]
            b_idx = sparse_idxs[j + 1]
            if b_idx - a_idx <= 1:
                continue
            a = by_frame[a_idx]
            b = by_frame[b_idx]
            for k in range(a_idx + 1, b_idx):
                t = (k - a_idx) / (b_idx - a_idx)
                r = {"frame": k, "timestamp": k / fps}
                for key in keys:
                    va, vb = a.get(key), b.get(key)
                    if va is None or vb is None:
                        r[key] = va if va is not None else vb
                    else:
                        r[key] = va + (vb - va) * t
                # Ellipse params: carry from neighbor (don't interpolate).
                for key in carry_keys:
                    if key in a:
                        r[key] = a[key]
                # Mark as interpolated so downstream can distinguish.
                r["interpolated"] = True
                dense[k] = r
        # Replace any remaining Nones with empty packs.
        for i in range(total_n):
            if dense[i] is None:
                dense[i] = {
                    "frame": i, "timestamp": i / fps,
                    "x": None, "y": None,
                }
        return dense

    def _track_median(self, cap, fps, total):
        self.status_msg.emit("Building background model…")
        n_samples = min(int(self.model_params.get("bg_sample_count", 120)), total)
        indices = np.linspace(self._start_frame, self._start_frame + total - 1, n_samples, dtype=int)
        # Forward-only pass: seek once, then grab() to skip frames + read() at targets.
        # Avoids per-sample seeks (each forces H.264 keyframe decode + replay).
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(indices[0]))
        current = int(indices[0])
        bg_frames = []
        for i, frame_idx in enumerate(indices):
            if self._stop_flag:
                return None
            target = int(frame_idx)
            while current < target:
                if not cap.grab():
                    break
                current += 1
            ret, f = self._read(cap)
            if ret:
                current += 1
                f = self._warp_frame(f)
                bg_frames.append(self._scale_frame(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)))
            self._emit_progress(int(i / n_samples * 20))

        if not bg_frames:
            self.error.emit("Could not read frames to build background model.")
            return None

        raw_bg = np.median(bg_frames, axis=0).astype(np.uint8)
        proc_bg = apply_preprocessing(raw_bg, self.brightness, self.contrast, self.blur, self.gamma, self.sharpen, self.clahe_clip)

        cap.set(cv2.CAP_PROP_POS_FRAMES, self._start_frame)
        self.status_msg.emit(f"Tracking mouse… proc={self._pw}x{self._ph}")

        results = []
        idx = 0
        self._reset_nose_state()
        _t = time.perf_counter
        _acc = {"read": 0.0, "warp": 0.0, "scale": 0.0, "gray": 0.0, "prep": 0.0,
                "mask": 0.0, "excl": 0.0, "detect": 0.0, "preview": 0.0, "rest": 0.0}
        _N = 0
        # Background reader thread — overlaps cv2.read with our compute.
        prefetcher = _FramePrefetcher(
            cap, self.crop_rect, self.homography, self.warp_size,
            frame_skip=self.frame_skip,
        )
        try:
            while True:
                if self._stop_flag:
                    break
                if idx >= total:
                    break
                t0 = _t()
                ret, frame = prefetcher.read()
                if not ret:
                    break
                # _acc["read"] now also includes warp time (both happen in
                # the prefetcher thread). When the queue is full because the
                # prefetcher is faster than us, this drops to ~0.
                t1 = _t(); _acc["read"] += t1 - t0
                t2 = t1
                small = self._scale_frame(frame)
                t3 = _t(); _acc["scale"] += t3 - t2
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                t4 = _t(); _acc["gray"] += t4 - t3
                proc_gray = apply_preprocessing(gray, self.brightness, self.contrast, self.blur, self.gamma, self.sharpen, self.clahe_clip)
                t5 = _t(); _acc["prep"] += t5 - t4
                mask = get_mask(proc_gray, proc_bg, self.threshold, self._arena_proc,
                                arena_mask=self._allowed_mask)
                t6 = _t(); _acc["mask"] += t6 - t5
                t7 = _t(); _acc["excl"] += t7 - t6
                body, sma, smi, ang, end_a, end_b, mass_signed = self._detect_points(mask, small)
                if self.enable_nose:
                    nose, tail, conf = self._resolve_nose(
                        body, end_a, end_b, mass_signed, sma, smi, ang, mask
                    )
                else:
                    nose = tail = None
                    conf = 0.0
                t8 = _t(); _acc["detect"] += t8 - t7
                body_s = self._scale_pt(body)
                nose_s = self._scale_pt(nose)
                tail_s = self._scale_pt(tail)
                if sma is not None:
                    sma *= self._up
                    smi *= self._up
                results.append(_pack(idx, fps, body_s, sma, smi, ang,
                                     nose=nose_s, tail=tail_s, nose_conf=conf))
                t9 = _t()
                self._emit_preview(frame, body_s, nose=nose_s, tail=tail_s)
                t10 = _t(); _acc["preview"] += t10 - t9
                self._emit_progress(20 + int(idx / total * 80))
                idx += self.frame_skip
                _N += 1
                if _N == 200 and __debug__:
                    msg = "PROF " + " ".join(f"{k}={_acc[k]/_N*1000:.2f}ms" for k in _acc)
                    self.status_msg.emit(msg)
        finally:
            prefetcher.stop()
        return results

    def _make_subtractor(self, name):
        p = self.model_params
        try:
            if name == "mog2":
                sub = cv2.createBackgroundSubtractorMOG2(
                    history=int(p["history"]),
                    varThreshold=float(p["varThreshold"]),
                    detectShadows=bool(p["detectShadows"]),
                )
                sub.setNMixtures(int(p["nMixtures"]))
                sub.setBackgroundRatio(float(p["backgroundRatio"]))
                sub.setVarThresholdGen(float(p["varThresholdGen"]))
                sub.setComplexityReductionThreshold(float(p["complexityReductionThreshold"]))
                sub.setVarInit(float(p["varInit"]))
                sub.setVarMin(float(p["varMin"]))
                sub.setVarMax(float(p["varMax"]))
                sub.setShadowThreshold(float(p["shadowThreshold"]))
                sub.setShadowValue(int(p["shadowValue"]))
                return sub
            if name == "knn":
                sub = cv2.createBackgroundSubtractorKNN(
                    history=int(p["history"]),
                    dist2Threshold=float(p["dist2Threshold"]),
                    detectShadows=bool(p["detectShadows"]),
                )
                sub.setkNNSamples(int(p["kNNSamples"]))
                sub.setNSamples(int(p["nSamples"]))
                sub.setShadowThreshold(float(p["shadowThreshold"]))
                sub.setShadowValue(int(p["shadowValue"]))
                return sub
            if name == "cnt":
                return cv2.bgsegm.createBackgroundSubtractorCNT(
                    minPixelStability=int(p["minPixelStability"]),
                    useHistory=bool(p["useHistory"]),
                    maxPixelStability=int(p["maxPixelStability"]),
                    isParallel=bool(p["isParallel"]),
                )
            if name == "gsoc":
                return cv2.bgsegm.createBackgroundSubtractorGSOC(
                    mc=int(p["mc"]),
                    nSamples=int(p["nSamples"]),
                    replaceRate=float(p["replaceRate"]),
                    propagationRate=float(p["propagationRate"]),
                    hitsThreshold=int(p["hitsThreshold"]),
                    alpha=float(p["alpha"]),
                    beta=float(p["beta"]),
                    blinkingSupressionDecay=float(p["blinkingSupressionDecay"]),
                    blinkingSupressionMultiplier=float(p["blinkingSupressionMultiplier"]),
                    noiseRemovalThresholdFacBG=float(p["noiseRemovalThresholdFacBG"]),
                    noiseRemovalThresholdFacFG=float(p["noiseRemovalThresholdFacFG"]),
                )
            if name == "lsbp":
                return cv2.bgsegm.createBackgroundSubtractorLSBP(
                    mc=int(p["mc"]),
                    nSamples=int(p["nSamples"]),
                    LSBPRadius=int(p["LSBPRadius"]),
                    Tlower=float(p["Tlower"]),
                    Tupper=float(p["Tupper"]),
                    Tinc=float(p["Tinc"]),
                    Tdec=float(p["Tdec"]),
                    Rscale=float(p["Rscale"]),
                    Rincdec=float(p["Rincdec"]),
                    noiseRemovalThresholdFacBG=float(p["noiseRemovalThresholdFacBG"]),
                    noiseRemovalThresholdFacFG=float(p["noiseRemovalThresholdFacFG"]),
                    LSBPthreshold=int(p["LSBPthreshold"]),
                    minCount=int(p["minCount"]),
                )
        except (AttributeError, cv2.error, KeyError):
            return None

    def _track_subtractor(self, cap, fps, total, subtractor, label):
        self.status_msg.emit(f"{label} warming up…")
        n_warmup = min(200, total)
        indices = np.linspace(self._start_frame, self._start_frame + total - 1, n_warmup, dtype=int)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(indices[0]))
        current = int(indices[0])
        for i, frame_idx in enumerate(indices):
            if self._stop_flag:
                return None
            target = int(frame_idx)
            while current < target:
                if not cap.grab():
                    break
                current += 1
            ret, f = self._read(cap)
            if ret:
                current += 1
                f = self._warp_frame(f)
                gray = self._scale_frame(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))
                proc = apply_preprocessing(gray, self.brightness, self.contrast, self.blur, self.gamma, self.sharpen, self.clahe_clip)
                try:
                    subtractor.apply(proc, learningRate=0.05)
                except cv2.error:
                    subtractor.apply(proc)
            self._emit_progress(int(i / n_warmup * 20))

        cap.set(cv2.CAP_PROP_POS_FRAMES, self._start_frame)
        self.status_msg.emit(f"Tracking mouse ({label})…")

        smooth_body = deque(maxlen=5)
        results = []
        idx = 0
        self._reset_nose_state()
        prefetcher = _FramePrefetcher(
            cap, self.crop_rect, self.homography, self.warp_size,
            frame_skip=self.frame_skip,
        )
        try:
            while True:
                if self._stop_flag:
                    break
                if idx >= total:
                    break
                ret, frame = prefetcher.read()
                if not ret:
                    break
                small = self._scale_frame(frame)
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                proc_gray = apply_preprocessing(gray, self.brightness, self.contrast, self.blur, self.gamma, self.sharpen, self.clahe_clip)
                try:
                    raw_mask = subtractor.apply(
                        proc_gray, learningRate=float(self.model_params.get("learningRate", 0.0))
                    )
                except cv2.error:
                    raw_mask = subtractor.apply(proc_gray)
                mask = _apply_arena_and_morph(raw_mask, self._arena_proc, self._morph_kernel_wh,
                                              arena_mask=self._allowed_mask)
                body, sma, smi, ang, end_a, end_b, mass_signed = self._detect_points(mask, small)
                if self.enable_nose:
                    nose, tail, conf = self._resolve_nose(
                        body, end_a, end_b, mass_signed, sma, smi, ang, mask
                    )
                else:
                    nose = tail = None
                    conf = 0.0
                body_s = self._scale_pt(body)
                nose_s = self._scale_pt(nose)
                tail_s = self._scale_pt(tail)
                if sma is not None:
                    sma *= self._up
                    smi *= self._up

                if body_s:
                    smooth_body.append(body_s)
                s_body = (
                    sum(p[0] for p in smooth_body) / len(smooth_body),
                    sum(p[1] for p in smooth_body) / len(smooth_body),
                ) if smooth_body else None

                results.append(_pack(idx, fps, s_body, sma, smi, ang,
                                     nose=nose_s, tail=tail_s, nose_conf=conf))
                self._emit_preview(frame, s_body, nose=nose_s, tail=tail_s)
                self._emit_progress(20 + int(idx / total * 80))
                idx += self.frame_skip
        finally:
            prefetcher.stop()
        return results

    def _track_framediff(self, cap, fps, total):
        self.status_msg.emit("Frame-diff tracking…")
        cap.set(cv2.CAP_PROP_POS_FRAMES, self._start_frame)
        prev = None
        diff_thr = int(self.model_params.get("diff_threshold", 25))
        use_running = bool(self.model_params.get("use_running_avg", False))
        ra_alpha = float(self.model_params.get("running_avg_alpha", 0.05))
        running = None
        results = []
        idx = 0
        self._reset_nose_state()
        prefetcher = _FramePrefetcher(
            cap, self.crop_rect, self.homography, self.warp_size,
            frame_skip=self.frame_skip,
        )
        try:
            while True:
                if self._stop_flag:
                    break
                if idx >= total:
                    break
                ret, frame = prefetcher.read()
                if not ret:
                    break
                small = self._scale_frame(frame)
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                proc_gray = apply_preprocessing(
                    gray, self.brightness, self.contrast, self.blur,
                    self.gamma, self.sharpen, self.clahe_clip,
                )
                if use_running:
                    if running is None:
                        running = proc_gray.astype(np.float32)
                        results.append(_pack(idx, fps, None))
                        self._emit_preview(frame, None)
                        self._emit_progress(int(idx / total * 100))
                        idx += self.frame_skip
                        continue
                    cv2.accumulateWeighted(proc_gray, running, ra_alpha)
                    ref = cv2.convertScaleAbs(running)
                else:
                    if prev is None:
                        prev = proc_gray
                        results.append(_pack(idx, fps, None))
                        self._emit_preview(frame, None)
                        self._emit_progress(int(idx / total * 100))
                        idx += self.frame_skip
                        continue
                    ref = prev
                diff = cv2.absdiff(proc_gray, ref)
                _, raw_mask = cv2.threshold(diff, diff_thr, 255, cv2.THRESH_BINARY)
                mask = _apply_arena_and_morph(raw_mask, self._arena_proc, self._morph_kernel_wh,
                                              arena_mask=self._allowed_mask)
                if not use_running:
                    prev = proc_gray
                body, sma, smi, ang, end_a, end_b, mass_signed = self._detect_points(mask, small)
                if self.enable_nose:
                    nose, tail, conf = self._resolve_nose(
                        body, end_a, end_b, mass_signed, sma, smi, ang, mask
                    )
                else:
                    nose = tail = None
                    conf = 0.0
                body_s = self._scale_pt(body)
                nose_s = self._scale_pt(nose)
                tail_s = self._scale_pt(tail)
                if sma is not None:
                    sma *= self._up
                    smi *= self._up
                results.append(_pack(idx, fps, body_s, sma, smi, ang,
                                     nose=nose_s, tail=tail_s, nose_conf=conf))
                self._emit_preview(frame, body_s, nose=nose_s, tail=tail_s)
                self._emit_progress(int(idx / total * 100))
                idx += self.frame_skip
        finally:
            prefetcher.stop()
        return results

    def _track_hsv(self, cap, fps, total):
        self.status_msg.emit("HSV-threshold tracking…")
        cap.set(cv2.CAP_PROP_POS_FRAMES, self._start_frame)
        ch_idx = {"H": 0, "S": 1, "V": 2}.get(self.model_params.get("channel", "V"), 2)
        mode = self.model_params.get("mode", "otsu")
        manual_thr = int(self.model_params.get("manual_threshold", 80))
        invert = bool(self.model_params.get("invert", True))
        thr_type = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
        results = []
        idx = 0
        self._reset_nose_state()
        prefetcher = _FramePrefetcher(
            cap, self.crop_rect, self.homography, self.warp_size,
            frame_skip=self.frame_skip,
        )
        try:
            while True:
                if self._stop_flag:
                    break
                if idx >= total:
                    break
                ret, frame = prefetcher.read()
                if not ret:
                    break
                small = self._scale_frame(frame)
                hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
                ch = hsv[:, :, ch_idx]
                proc_ch = apply_preprocessing(
                    ch, self.brightness, self.contrast, self.blur,
                    self.gamma, self.sharpen, self.clahe_clip,
                )
                if mode == "otsu":
                    _, raw_mask = cv2.threshold(proc_ch, 0, 255, thr_type + cv2.THRESH_OTSU)
                else:
                    _, raw_mask = cv2.threshold(proc_ch, manual_thr, 255, thr_type)
                mask = _apply_arena_and_morph(raw_mask, self._arena_proc, self._morph_kernel_wh,
                                              arena_mask=self._allowed_mask)
                body, sma, smi, ang, end_a, end_b, mass_signed = self._detect_points(mask, small)
                if self.enable_nose:
                    nose, tail, conf = self._resolve_nose(
                        body, end_a, end_b, mass_signed, sma, smi, ang, mask
                    )
                else:
                    nose = tail = None
                    conf = 0.0
                body_s = self._scale_pt(body)
                nose_s = self._scale_pt(nose)
                tail_s = self._scale_pt(tail)
                if sma is not None:
                    sma *= self._up
                    smi *= self._up
                results.append(_pack(idx, fps, body_s, sma, smi, ang,
                                     nose=nose_s, tail=tail_s, nose_conf=conf))
                self._emit_preview(frame, body_s, nose=nose_s, tail=tail_s)
                self._emit_progress(int(idx / total * 100))
                idx += self.frame_skip
        finally:
            prefetcher.stop()
        return results

    def _detect_points(self, mask, frame_bgr=None):
        """Returns (body, semi_major, semi_minor, angle_deg, end_a, end_b,
        mass_signed). `body` is the blob centroid; ellipse params describe
        the body's orientation. end_a/end_b are the two endpoints along the
        major axis (proc-scale px). mass_signed: contour area on end_a side
        minus area on end_b side, normalized by total area. Positive ⇒ end_a
        side is heavier (hip side per the hip-heavier convention)."""
        _none = (None,) * 7
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return _none
        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)
        if area < self._min_area:
            return _none
        if self._max_area > 0 and area > self._max_area:
            return _none
        largest_hull = cv2.convexHull(largest)

        M = cv2.moments(largest_hull)
        if M["m00"] < 1e-6:
            return _none

        cx = M["m10"] / M["m00"]
        cy = M["m01"] / M["m00"]
        body = (cx, cy)

        angle = 0.5 * np.arctan2(2 * M["mu11"], M["mu20"] - M["mu02"])

        # Robust ellipse size from blob's covariance eigenvalues (~2σ).
        m00 = M["m00"]
        common = (M["mu20"] + M["mu02"]) / (2.0 * m00)
        delta = (((M["mu20"] - M["mu02"]) / (2.0 * m00)) ** 2 + (M["mu11"] / m00) ** 2) ** 0.5
        var_major = max(common + delta, 0)
        var_minor = max(common - delta, 0)
        semi_major = 2.0 * var_major ** 0.5
        semi_minor = 2.0 * var_minor ** 0.5
        angle_deg  = float(np.degrees(angle))

        # Major-axis unit vector + two endpoints at body ± semi_major.
        ux = float(np.cos(angle))
        uy = float(np.sin(angle))
        end_a = (cx + ux * semi_major, cy + uy * semi_major)
        end_b = (cx - ux * semi_major, cy - uy * semi_major)

        # Mass asymmetry: only computed when nose detection is enabled.
        # The scan iterates every foreground pixel in the contour bbox,
        # which is the single most expensive thing per frame — skipping
        # it for body-only experiments (OF / Y-Maze / EPM) buys back
        # most of the speed lost to the nose-resolution rewrite.
        mass_signed = 0.0
        if self.enable_nose:
            bx_x, bx_y, bx_w, bx_h = cv2.boundingRect(largest)
            if bx_w > 0 and bx_h > 0:
                sub = mask[bx_y:bx_y + bx_h, bx_x:bx_x + bx_w]
                ys_sub, xs_sub = np.nonzero(sub)
                if xs_sub.size > 0:
                    xs = xs_sub.astype(np.float32) + bx_x
                    ys = ys_sub.astype(np.float32) + bx_y
                    proj = (xs - cx) * ux + (ys - cy) * uy
                    n_a = int(np.count_nonzero(proj > 0))
                    n_b = int(np.count_nonzero(proj < 0))
                    total = n_a + n_b
                    if total > 0:
                        mass_signed = (n_a - n_b) / total

        return body, semi_major, semi_minor, angle_deg, end_a, end_b, mass_signed

    def _resolve_nose(self, body, end_a, end_b, mass_signed,
                      semi_major, semi_minor, angle_deg, mask):
        """Pick which endpoint is the nose using fused signals:
            - mass asymmetry (hip-heavier prior → lighter end is nose)
            - body-centroid motion (leading endpoint along velocity)
            - frame-diff leading edge (newly-occupied pixels are nose side)
            - temporal continuity (previous nose direction)
            - rotation gate (forbid flip unless body axis rotated enough)

        Returns (nose, tail, confidence) in proc-scale px (or None,None,0).
        Mutates session state: _prev_mask, _prev_body, _prev_nose,
        _prev_axis, _prev_angle, _cum_rot, _velocity, _locked."""
        if body is None or end_a is None or end_b is None:
            # Reset locked state when blob lost; keep prev_mask so leading-edge
            # signal can recover when blob reappears. Decay confidence so
            # hysteresis loosens if blob stays lost for a while.
            self._prev_body = None
            self._prev_conf *= 0.5
            return None, None, 0.0

        bx, by = body
        ax, ay = end_a
        bxp, byp = end_b

        # Unit dirs from body to each endpoint.
        dax, day = ax - bx, ay - by
        dbx, dby = bxp - bx, byp - by
        na = float(np.hypot(dax, day)) or 1.0
        nb = float(np.hypot(dbx, dby)) or 1.0
        dax, day = dax / na, day / na
        dbx, dby = dbx / nb, dby / nb

        # ── Velocity (EMA over body movements) ────────────────────────────
        if self._prev_body is not None:
            vx = bx - self._prev_body[0]
            vy = by - self._prev_body[1]
            self._velocity = 0.6 * self._velocity + 0.4 * np.array([vx, vy])
        v = self._velocity
        vmag = float(np.hypot(v[0], v[1]))

        # ── Leading-edge frame-diff ───────────────────────────────────────
        # Cropped to a padded bbox around the body — the leading-edge pixels
        # can only appear within ~1 body length of the centroid, so scanning
        # the full mask was waste. cv2.subtract replaces the
        # bitwise_and(mask, bitwise_not(prev)) idiom (one less intermediate
        # allocation, same result on uint8 masks).
        lead_dir = None
        lead_strength = 0.0
        if self._prev_mask is not None and mask.shape == self._prev_mask.shape:
            h_m, w_m = mask.shape
            half = int(semi_major * 1.6) + 8  # generous margin
            x0 = max(0, int(bx - half))
            y0 = max(0, int(by - half))
            x1 = min(w_m, int(bx + half) + 1)
            y1 = min(h_m, int(by + half) + 1)
            sub_cur  = mask[y0:y1, x0:x1]
            sub_prev = self._prev_mask[y0:y1, x0:x1]
            appeared = cv2.subtract(sub_cur, sub_prev)
            n_app = int(cv2.countNonZero(appeared))
            if n_app > 8:
                Ma = cv2.moments(appeared, binaryImage=True)
                if Ma["m00"] > 1e-6:
                    # Moments are in the sub-image frame; shift back to full
                    # mask coordinates before the body-relative math.
                    lcx = Ma["m10"] / Ma["m00"] + x0
                    lcy = Ma["m01"] / Ma["m00"] + y0
                    ldx, ldy = lcx - bx, lcy - by
                    lmag = float(np.hypot(ldx, ldy)) or 1.0
                    lead_dir = (ldx / lmag, ldy / lmag)
                    # Strength saturates with appeared area normalized by
                    # semi_major (so big blobs need proportionally more
                    # new pixels to count as strong).
                    lead_strength = min(1.0, n_app / max(20.0, semi_major * 4))

        # ── Rotation accumulator (cumulative since last flip) ─────────────
        if self._prev_angle is not None:
            d = angle_deg - self._prev_angle
            # Major axis is direction-ambiguous; wrap to [-90, 90].
            while d > 90:  d -= 180
            while d < -90: d += 180
            self._cum_rot += abs(d)
        self._prev_angle = angle_deg

        # ── Score each endpoint ───────────────────────────────────────────
        # Smooth mass_signed before scoring — single-frame noise (rearing,
        # grooming, curled blob) flips raw value but smoothed survives.
        if not self._mass_ema_init:
            self._mass_ema = float(mass_signed)
            self._mass_ema_init = True
        else:
            self._mass_ema = 0.75 * self._mass_ema + 0.25 * float(mass_signed)
        mass_smoothed = self._mass_ema

        # Mass: hip-heavier ⇒ end_a is hip if mass_smoothed>0 ⇒ nose is end_b.
        # → mass_score(a) = -mass_smoothed,  mass_score(b) = +mass_smoothed.
        mass_score_a = -mass_smoothed
        mass_score_b = +mass_smoothed

        # Motion: dot of unit endpoint dir with velocity (per-frame px).
        # Down-weight when slow (under ~1 px/frame velocity).
        v_weight = min(1.0, vmag / 2.0)
        if vmag > 1e-3:
            vhx, vhy = v[0] / vmag, v[1] / vmag
            motion_a = dax * vhx + day * vhy
            motion_b = dbx * vhx + dby * vhy
        else:
            motion_a = motion_b = 0.0

        # Leading edge.
        if lead_dir is not None:
            le_a = dax * lead_dir[0] + day * lead_dir[1]
            le_b = dbx * lead_dir[0] + dby * lead_dir[1]
        else:
            le_a = le_b = 0.0

        # Continuity: prefer endpoint aligned with prev nose direction
        # (axis from body to prev_nose, expressed as unit vector relative
        # to current body).
        cont_a = cont_b = 0.0
        if self._prev_axis is not None:
            pax, pay = self._prev_axis
            cont_a = dax * pax + day * pay
            cont_b = dbx * pax + dby * pay

        # Rotation gate: if locked and rotation hasn't accumulated past
        # threshold, kill the motion+leading-edge contributions (they're
        # the ones that flip during backward walk). Continuity + mass
        # remain to keep nose stable.
        ROT_THRESHOLD = 90.0  # deg of cumulative |delta| to allow flip
        gate_open = (not self._locked) or (self._cum_rot >= ROT_THRESHOLD)

        # Weights — mass + continuity are the persistent anchors; motion
        # + leading-edge boost confidence when consistent, gated to handle
        # backward walks. Continuity scales up sharply with prior confidence
        # so a well-established nose isn't dethroned by one noisy frame.
        W_MASS = 1.0
        W_CONT = 1.5 + 2.5 * self._prev_conf
        W_MOT  = 0.9 * v_weight * (1.0 if gate_open else 0.0)
        W_LE   = 0.8 * lead_strength * (1.0 if gate_open else 0.0)

        score_a = (W_MASS * mass_score_a + W_CONT * cont_a
                   + W_MOT * motion_a + W_LE * le_a)
        score_b = (W_MASS * mass_score_b + W_CONT * cont_b
                   + W_MOT * motion_b + W_LE * le_b)

        wsum = max(1e-6, W_MASS + W_CONT + W_MOT + W_LE)

        # Flip hysteresis: when previous nose was end_a (cont_a > cont_b),
        # require the b-side score to beat a by a margin before switching.
        # Margin scales with prior confidence — sticky when confident.
        FLIP_MARGIN = 0.15 * wsum * (0.4 + 0.6 * self._prev_conf)
        if self._prev_axis is not None:
            prev_choose_a = (cont_a >= cont_b)
            if prev_choose_a:
                if score_b > score_a + FLIP_MARGIN:
                    nose, tail = end_b, end_a
                    axis = (dbx, dby)
                else:
                    nose, tail = end_a, end_b
                    axis = (dax, day)
            else:
                if score_a > score_b + FLIP_MARGIN:
                    nose, tail = end_a, end_b
                    axis = (dax, day)
                else:
                    nose, tail = end_b, end_a
                    axis = (dbx, dby)
        else:
            if score_a >= score_b:
                nose, tail = end_a, end_b
                axis = (dax, day)
            else:
                nose, tail = end_b, end_a
                axis = (dbx, dby)

        # Confidence: margin between scores, normalized by max possible
        # weight sum so it lives in roughly [0, 1].
        confidence = min(1.0, abs(score_a - score_b) / wsum)
        self._prev_conf = confidence

        # Update lock + rotation accumulator. If nose flipped this frame,
        # reset cum_rot so future flips need a fresh full rotation.
        if self._prev_axis is not None:
            # Compare new axis to previous: if flipped (negative dot), reset.
            dot = axis[0] * self._prev_axis[0] + axis[1] * self._prev_axis[1]
            if dot < 0:
                self._cum_rot = 0.0

        # Lock once confident; release on big rotation (handled by gate).
        if confidence > 0.25:
            self._locked = True

        self._prev_body = body
        self._prev_nose = nose
        self._prev_axis = axis
        # Store the mask by reference, not by copy. Each frame the tracker
        # builds a fresh ndarray (cv2.morphologyEx / get_mask / cv2.bitwise_*
        # all return new arrays), so holding the previous reference doesn't
        # alias the next frame's buffer. Saves a full-mask allocation +
        # memcpy every frame (~0.5–1 ms on 640×480).
        self._prev_mask = mask
        return nose, tail, float(confidence)

    def _emit_progress(self, pct):
        """Throttle progress signal — emit only when the integer percent
        actually moves. The progress bar is integer-valued so the dropped
        emits are visually identical."""
        p = int(pct)
        if p != self._last_progress_pct:
            self._last_progress_pct = p
            self.progress.emit(p)

    def _emit_preview(self, frame, body, nose=None, tail=None):
        # body_pos / nose_pos are wired to the live-tracking HUD (cell
        # highlight). They were emitted every frame for "accurate cell
        # math", but the per-cell time + entry totals are RECOMPUTED from
        # raw_df after the run, so the live emit only drives the visible
        # highlight — 15 Hz is plenty for human eyes and halves the Qt
        # cross-thread queue overhead on a 30 fps source. The rendered
        # preview frame stays at 5 Hz (frame.copy + paint is heavier).
        now = time.time()
        emit_pos = (now - self._last_pos_emit_time) >= (1.0 / 15.0)
        if emit_pos:
            self._last_pos_emit_time = now
            try:
                self.body_pos.emit(tuple(body) if body else None)
                self.nose_pos.emit(tuple(nose) if nose else None)
            except Exception:
                # Signal emit fails when the receiver QObject has been torn
                # down mid-track. Expected on stop; not a real bug.
                pass
        if now - self._last_preview_time < 1 / 5:
            return
        self._last_preview_time = now
        vis = frame.copy()
        if self.body_style != "off" and body:
            _draw_body(vis, body, self.body_style,
                       body_color=self._c_body,
                       nose=nose, tail=tail,
                       nose_color=self._c_nose, tail_color=self._c_tail)
        self.preview.emit(vis)


def _median_filter_results(results, window=3, keys=("x", "y", "nose_x", "nose_y", "tail_x", "tail_y")):
    """Apply a centered window-N rolling median to listed coord keys.
    Single-frame outliers (1-frame jerks) get replaced by the median of
    their neighbors; smooth motion is preserved because the median equals
    the middle value when neighbors are similar. None values pass through.

    Mutates `results` in place and also returns it. Operates per-key
    independently so a missing nose doesn't corrupt body filtering.
    """
    if window < 3 or window % 2 == 0 or not results:
        return results
    half = window // 2
    n = len(results)
    for key in keys:
        # Build a parallel buffer first so the rolling window reads
        # un-mutated input (otherwise output of frame i feeds into the
        # window of frame i+1, which is not what we want).
        vals = [r.get(key) for r in results]
        out = list(vals)
        for i in range(n):
            if vals[i] is None:
                continue
            window_vals = [vals[j] for j in range(max(0, i - half), min(n, i + half + 1)) if vals[j] is not None]
            if len(window_vals) >= 2:
                window_vals.sort()
                out[i] = window_vals[len(window_vals) // 2]
        for i in range(n):
            if vals[i] is not None and out[i] != vals[i]:
                results[i][key] = out[i]
    return results


def _pack(idx, fps, body, sma=None, smi=None, ang=None,
          nose=None, tail=None, nose_conf=None):
    return {
        "frame":     idx,
        "timestamp": idx / fps,
        "x":         body[0] if body else None,
        "y":         body[1] if body else None,
        "ellipse_semi_major": sma,
        "ellipse_semi_minor": smi,
        "ellipse_angle":      ang,
        "nose_x":    nose[0] if nose else None,
        "nose_y":    nose[1] if nose else None,
        "tail_x":    tail[0] if tail else None,
        "tail_y":    tail[1] if tail else None,
        "nose_confidence": nose_conf,
    }
