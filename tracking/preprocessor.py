import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal


_lut_cache    = {}   # gamma  -> uint8 LUT
_clahe_cache  = {}   # clip_limit -> CLAHE object
_kernel_cache = {}   # (h, w) -> morph kernel


def _gamma_lut(gamma: float) -> np.ndarray:
    if gamma not in _lut_cache:
        inv = 1.0 / max(gamma, 0.01)
        _lut_cache[gamma] = ((np.arange(256) / 255.0) ** inv * 255).astype(np.uint8)
    return _lut_cache[gamma]


def _get_clahe(clip_limit: int):
    if clip_limit not in _clahe_cache:
        _clahe_cache[clip_limit] = cv2.createCLAHE(
            clipLimit=float(clip_limit), tileGridSize=(8, 8)
        )
    return _clahe_cache[clip_limit]


def get_morph_kernel(h: int, w: int) -> np.ndarray:
    """Default per-frame structuring element. MORPH_RECT is separable in
    OpenCV (erode/dilate become two 1-D passes), so a k×k rect kernel
    runs ~2× faster than the k×k ELLIPSE we used before. Tracking only
    cares about blob area / centroid / second moments — none of which
    notice the slightly squarer mask corners RECT produces."""
    key = (h, w)
    if key not in _kernel_cache:
        k = max(3, int(min(h, w) * 0.015))
        k = k if k % 2 == 1 else k + 1
        _kernel_cache[key] = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    return _kernel_cache[key]


def apply_preprocessing(gray: np.ndarray, brightness: int, contrast: float, blur: int,
                        gamma: float = 1.0, sharpen: int = 0, clahe_clip: int = 0) -> np.ndarray:
    if (brightness == 0 and contrast == 1.0 and blur == 0
            and gamma == 1.0 and sharpen == 0 and clahe_clip == 0):
        return gray
    out = cv2.convertScaleAbs(gray, alpha=contrast, beta=brightness)
    if blur > 0:
        k = blur * 2 + 1
        out = cv2.GaussianBlur(out, (k, k), 0)
    if gamma != 1.0:
        out = cv2.LUT(out, _gamma_lut(gamma))
    if clahe_clip > 0:
        out = _get_clahe(clahe_clip).apply(out)
    if sharpen > 0:
        blurred = cv2.GaussianBlur(out, (0, 0), 1.5)
        out = cv2.addWeighted(out, 1.0 + sharpen / 5.0, blurred, -sharpen / 5.0, 0)
    return out


def apply_preprocessing_bgr(frame: np.ndarray, brightness: int, contrast: float, blur: int,
                             gamma: float = 1.0, sharpen: int = 0, clahe_clip: int = 0) -> np.ndarray:
    out = cv2.convertScaleAbs(frame, alpha=contrast, beta=brightness)
    if blur > 0:
        k = blur * 2 + 1
        out = cv2.GaussianBlur(out, (k, k), 0)
    if gamma != 1.0:
        out = cv2.LUT(out, _gamma_lut(gamma))
    if clahe_clip > 0:
        lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l = _get_clahe(clahe_clip).apply(l)
        out = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
    if sharpen > 0:
        blurred = cv2.GaussianBlur(out, (0, 0), 1.5)
        out = cv2.addWeighted(out, 1.0 + sharpen / 5.0, blurred, -sharpen / 5.0, 0)
    return out


def get_mask(proc_gray: np.ndarray, proc_bg: np.ndarray, threshold: int, arena=None,
             arena_mask: np.ndarray = None) -> np.ndarray:
    diff = cv2.absdiff(proc_bg, proc_gray)
    _, mask = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)
    if arena_mask is not None:
        mask = cv2.bitwise_and(mask, arena_mask)
    elif arena:
        h, w = mask.shape
        am = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(am, [np.array(arena, dtype=np.int32)], 255)
        mask = cv2.bitwise_and(mask, am)
    h, w = mask.shape
    kernel = get_morph_kernel(h, w)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def make_overlay(frame_bgr: np.ndarray, mask: np.ndarray, color_bgr=(0, 0, 140), alpha: float = 0.55) -> np.ndarray:
    a = max(0.0, min(1.0, alpha))
    mf = (mask.astype(np.float32) / 255.0) * a
    mf3 = cv2.merge([mf, mf, mf])
    color_arr = np.zeros_like(frame_bgr, dtype=np.float32)
    color_arr[:] = color_bgr
    overlay = (frame_bgr.astype(np.float32) * (1.0 - mf3) + color_arr * mf3).astype(np.uint8)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        cv2.drawContours(overlay, contours, -1, color_bgr, 2, cv2.LINE_AA)
        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) > 150:
            M = cv2.moments(largest)
            if M["m00"] > 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
                cv2.circle(overlay, (cx, cy), 14, color_bgr, 2)
                cv2.circle(overlay, (cx, cy), 4, color_bgr, -1)
    cv2.putText(overlay, "Overlay", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
    return overlay


def make_mask_view(mask: np.ndarray) -> np.ndarray:
    view = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    cv2.putText(view, "Detection Mask", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 2)
    return view


class BgBuilderThread(QThread):
    """Samples frames across the video to build a median background (no mouse)."""
    done = pyqtSignal(object)

    def __init__(self, video_path: str, n_samples: int = 20):
        super().__init__()
        self.video_path = video_path
        self.n_samples = n_samples

    def run(self):
        try:
            cap = cv2.VideoCapture(self.video_path)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            n = min(self.n_samples, total)
            indices = np.linspace(0, total - 1, n, dtype=int)
            frames = []
            for idx in indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
                ret, f = cap.read()
                if ret:
                    frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))
            cap.release()
            if frames:
                bg = np.median(frames, axis=0).astype(np.uint8)
                self.done.emit(bg)
            else:
                self.done.emit(None)
        except Exception:
            self.done.emit(None)
