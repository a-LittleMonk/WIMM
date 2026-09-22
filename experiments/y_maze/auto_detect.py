"""Auto-detect a Y-maze shape in a frame. Returns hub + 3 arm-endpoint
positions in normalized coords. Used by the geometry-step "Define Y"
button so the user doesn't have to nudge a default template into place."""
import math

import cv2
import numpy as np


def detect_y_shape(frame_bgr):
    """Inspect `frame_bgr` and try to find a 3-armed Y.

    Returns (hub_norm, endpoints_norm) on success — hub_norm is (x, y) in
    [0, 1] and endpoints_norm is a list of three (x, y) tuples in [0, 1].
    Returns None when the frame is too dim or the contour isn't Y-shaped
    enough to be confident."""
    if frame_bgr is None or frame_bgr.size == 0:
        return None
    h, w = frame_bgr.shape[:2]
    # Accept BGR or grayscale.
    if frame_bgr.ndim == 2:
        gray = frame_bgr
    elif frame_bgr.shape[2] == 1:
        gray = frame_bgr[:, :, 0]
    else:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    # Otsu picks an arbitrary polarity — try both and keep the better Y.
    _, base_mask = cv2.threshold(gray, 0, 255,
                                 cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    best = None
    for invert in (False, True):
        mask = base_mask if not invert else cv2.bitwise_not(base_mask)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        result = _detect_in_mask(mask, w, h)
        if result is None:
            continue
        if best is None or result[0] > best[0]:
            best = result
    if best is None:
        return None
    _, hub_norm, endpoints_norm = best
    return hub_norm, endpoints_norm


def _detect_in_mask(mask, w, h):
    """Detect (score, hub_norm, endpoints_norm) on one polarity mask."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    area = float(cv2.contourArea(contour))
    if area < (w * h) * 0.03 or area > (w * h) * 0.92:
        return None

    # ── Hub: pick the inscribed-circle peak (distance transform maxima).
    # That's the point inside the maze with the maximum clearance from
    # the outer boundary — for a Y, it sits near the junction of the
    # arms. Much more stable than the contour centroid when one arm is
    # longer than the others or the threshold caught extra pixels.
    dt = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    _, _, _, max_loc = cv2.minMaxLoc(dt)
    hub_x, hub_y = float(max_loc[0]), float(max_loc[1])

    # ── Arm tips: bin the contour points by angle from the hub, take
    # the max radius per bin, then find local maxima in that radial
    # profile. Each arm shows up as a clear peak; valleys between arms
    # have short radii. Robust to bumpy contours and asymmetric arms.
    points = contour.reshape(-1, 2).astype(np.float64)
    dxs = points[:, 0] - hub_x
    dys = points[:, 1] - hub_y
    angles = np.arctan2(dys, dxs)
    dists = np.hypot(dxs, dys)

    n_bins = 72  # 5° resolution
    bin_max_dist = np.zeros(n_bins, dtype=np.float64)
    bin_max_idx = np.full(n_bins, -1, dtype=np.int64)
    # angles are in [-pi, pi); shift to [0, 2pi) for bin indexing.
    shifted = (angles + math.pi) % (2 * math.pi)
    bin_id = np.minimum((shifted / (2 * math.pi) * n_bins).astype(int),
                        n_bins - 1)
    for i, b in enumerate(bin_id):
        if dists[i] > bin_max_dist[b]:
            bin_max_dist[b] = dists[i]
            bin_max_idx[b] = i

    # Circular smoothing — averages each bin with ±2 neighbors so spurious
    # single-bin spikes don't register as peaks.
    smooth = np.zeros(n_bins, dtype=np.float64)
    half = 2
    for i in range(n_bins):
        acc = 0.0
        n = 0
        for j in range(-half, half + 1):
            v = bin_max_dist[(i + j) % n_bins]
            if v > 0:
                acc += v
                n += 1
        smooth[i] = acc / max(n, 1)

    # Local maxima in the circular profile.
    peaks = []
    for i in range(n_bins):
        lo = smooth[(i - 1) % n_bins]
        hi = smooth[(i + 1) % n_bins]
        if smooth[i] >= lo and smooth[i] >= hi and smooth[i] > 0:
            peaks.append((smooth[i], i))
    peaks.sort(reverse=True)

    # Greedy: pick the highest peak, then the next-highest that's ≥ 60°
    # away from every already-picked peak. Need 3.
    min_sep = int(n_bins * 60 / 360)
    chosen_bins = []
    for _, b in peaks:
        ok = True
        for cb in chosen_bins:
            diff = abs(b - cb)
            diff = min(diff, n_bins - diff)
            if diff < min_sep:
                ok = False
                break
        if ok:
            chosen_bins.append(b)
            if len(chosen_bins) >= 3:
                break
    if len(chosen_bins) < 3:
        return None

    # ── Refine each tip: walk along the arm spoke from the hub in the
    # peak's direction and find the farthest INSIDE-mask pixel. This
    # corrects when the angular bin's max-radius contour point is a side
    # bulge rather than the actual arm endpoint.
    H, W = mask.shape
    endpoints_px = []
    for b in chosen_bins:
        bin_angle = (b + 0.5) / n_bins * (2 * math.pi) - math.pi
        ux, uy = math.cos(bin_angle), math.sin(bin_angle)
        # Step out along the ray until we leave the mask, then step back
        # along nearby angles to find the maximum-reaching pixel.
        best_x, best_y, best_r = hub_x, hub_y, 0.0
        # Sweep a ±5° fan around the peak direction so we find the actual
        # furthest tip even if the peak angle is slightly off-axis.
        max_radius = math.hypot(W, H)
        for da_deg in range(-5, 6):
            ang = bin_angle + math.radians(da_deg)
            sx, sy = math.cos(ang), math.sin(ang)
            r = 0.0
            last_in_r = 0.0
            last_in_x, last_in_y = hub_x, hub_y
            step = 1.5
            while r < max_radius:
                px = int(round(hub_x + sx * r))
                py = int(round(hub_y + sy * r))
                if px < 0 or py < 0 or px >= W or py >= H:
                    break
                if mask[py, px] > 0:
                    last_in_r = r
                    last_in_x, last_in_y = px, py
                r += step
            if last_in_r > best_r:
                best_r = last_in_r
                best_x, best_y = last_in_x, last_in_y
        endpoints_px.append((best_x, best_y))

    # Y-ness score: tip distances should be reasonably similar (penalize
    # huge asymmetry) and angular spread should be near 120° each gap.
    spoke_angles = sorted(
        math.atan2(ey - hub_y, ex - hub_x) for ex, ey in endpoints_px
    )
    gaps = []
    for i in range(3):
        gap = (spoke_angles[(i + 1) % 3] - spoke_angles[i]) % (2 * math.pi)
        gaps.append(gap)
    ideal = 2 * math.pi / 3
    angular_err = sum((g - ideal) ** 2 for g in gaps)
    spoke_lens = [math.hypot(ex - hub_x, ey - hub_y) for ex, ey in endpoints_px]
    mean_len = sum(spoke_lens) / 3.0
    if mean_len <= 0:
        return None
    len_var = sum((L - mean_len) ** 2 for L in spoke_lens) / 3.0
    len_pen = len_var / (mean_len * mean_len)
    score = (area / (w * h)) - 0.5 * angular_err - 0.5 * len_pen

    hub_norm = (hub_x / w, hub_y / h)
    endpoints_norm = [(ex / w, ey / h) for ex, ey in endpoints_px]
    # Sort by angle so A/B/C assignment is stable across re-runs.
    endpoints_norm.sort(
        key=lambda p: math.atan2(p[1] - hub_norm[1], p[0] - hub_norm[0])
    )
    return score, hub_norm, endpoints_norm
