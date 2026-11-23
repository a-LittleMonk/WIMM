"""Geometry for box-family experiments.

Every box-family test is set up the same way: the user defines the arena
(4 corners around the apparatus, exactly like Open Field) and the test's
zones are calculated inside it. Zones are described in "box space"
(u, v) ∈ [0, 1]²: u runs left → right along the arena's top edge, v runs
top → bottom. A homography maps box space onto the arena quad, so zones
stay correct under camera tilt and for non-square frames: a circle in box
space is a physical circle when the box is a physical square.
"""
import math

import numpy as np


# ── Arena corners ──────────────────────────────────────────────────────
def sort_quad(pts):
    """Return the 4 corners as (TL, TR, BR, BL) — same convention the
    output graphs use (TL = min x+y, BR = max x+y, TR = max x−y,
    BL = min x−y)."""
    pts = [(float(p[0]), float(p[1])) for p in pts]
    tl = min(pts, key=lambda p: p[0] + p[1])
    br = max(pts, key=lambda p: p[0] + p[1])
    tr = max(pts, key=lambda p: p[0] - p[1])
    bl = min(pts, key=lambda p: p[0] - p[1])
    return [tl, tr, br, bl]


def box_homography(quad):
    """3×3 homography mapping box space (u, v) → the quad's coordinates
    (pixels or normalized video coords, whatever the quad is in). None if
    the quad is not a usable 4-corner polygon."""
    if not quad or len(quad) != 4:
        return None
    q = sort_quad(quad)
    if len({(round(x, 6), round(y, 6)) for x, y in q}) < 4:
        return None
    src = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    a = []
    b = []
    for (u, v), (x, y) in zip(src, q):
        a.append([u, v, 1, 0, 0, 0, -u * x, -v * x])
        a.append([0, 0, 0, u, v, 1, -u * y, -v * y])
        b.extend([x, y])
    try:
        h = np.linalg.solve(np.array(a, float), np.array(b, float))
    except np.linalg.LinAlgError:
        return None
    return np.append(h, 1.0).reshape(3, 3)


def apply_h(H, pts):
    """Map an (N, 2) array (or list of pairs) through H."""
    arr = np.asarray(pts, dtype=float).reshape(-1, 2)
    ones = np.ones((arr.shape[0], 1))
    out = np.hstack([arr, ones]) @ H.T
    w = out[:, 2:3]
    w[np.abs(w) < 1e-12] = 1e-12
    return out[:, :2] / w


def to_box(H, xs, ys):
    """Points in quad coordinates → box space. NaNs stay NaN."""
    xs = np.asarray(xs, float)
    ys = np.asarray(ys, float)
    u = np.full(xs.shape, np.nan)
    v = np.full(xs.shape, np.nan)
    ok = ~(np.isnan(xs) | np.isnan(ys))
    if ok.any():
        uv = apply_h(np.linalg.inv(H), np.stack([xs[ok], ys[ok]], axis=1))
        u[ok] = uv[:, 0]
        v[ok] = uv[:, 1]
    return u, v


def from_box(H, poly_uv):
    """Box-space polygon → quad coordinates (list of tuples)."""
    if poly_uv is None or len(poly_uv) == 0:
        return []
    return [tuple(p) for p in apply_h(H, poly_uv)]


# ── Shapes in box space ────────────────────────────────────────────────
def rect(u0, v0, u1, v1):
    return [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]


def ellipse(cu, cv, ru, rv, n=48):
    return [(cu + ru * math.cos(2 * math.pi * k / n),
             cv + rv * math.sin(2 * math.pi * k / n)) for k in range(n)]


def sector(cu, cv, r_in, r_out, a0, a1, n=24):
    """Ring sector (or pie slice when r_in == 0) between angles a0 → a1
    (degrees, 0 = right, counter-clockwise on screen = decreasing v)."""
    pts = []
    for k in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * k / n)
        pts.append((cu + r_out * math.cos(a), cv - r_out * math.sin(a)))
    if r_in <= 0:
        pts.append((cu, cv))
    else:
        for k in range(n, -1, -1):
            a = math.radians(a0 + (a1 - a0) * k / n)
            pts.append((cu + r_in * math.cos(a), cv - r_in * math.sin(a)))
    return pts


def annulus(cu, cv, r_in, r_out, n=48):
    """Ring as one drawable outline (outer loop, then inner loop reversed;
    drawn with odd-even fill so the hole stays empty). Membership must use
    the radial test (see `radial`), not a polygon test."""
    outer = ellipse(cu, cv, r_out, r_out, n)
    inner = ellipse(cu, cv, r_in, r_in, n)
    # Both loops start at angle 0, so the joining seam is a radial line.
    return outer + [outer[0], inner[0]] + inner[:0:-1] + [inner[0]]


def bar(cu, cv, angle_deg, r0, r1, half_w):
    """Rectangle along direction `angle_deg` from radius r0 to r1 with
    half-width half_w (radial-maze arm)."""
    a = math.radians(angle_deg)
    dx, dy = math.cos(a), -math.sin(a)
    px, py = -dy, dx
    return [
        (cu + dx * r0 + px * half_w, cv + dy * r0 + py * half_w),
        (cu + dx * r1 + px * half_w, cv + dy * r1 + py * half_w),
        (cu + dx * r1 - px * half_w, cv + dy * r1 - py * half_w),
        (cu + dx * r0 - px * half_w, cv + dy * r0 - py * half_w),
    ]


def regular_polygon(cu, cv, r, n, rot_deg=0.0):
    return [(cu + r * math.cos(math.radians(rot_deg + 360.0 * k / n)),
             cv - r * math.sin(math.radians(rot_deg + 360.0 * k / n)))
            for k in range(n)]


# ── Membership ─────────────────────────────────────────────────────────
def in_polygon(u, v, poly):
    """Vectorised point-in-polygon (even-odd) in box space."""
    from matplotlib.path import Path
    u = np.asarray(u, float)
    v = np.asarray(v, float)
    out = np.zeros(u.shape, bool)
    ok = ~(np.isnan(u) | np.isnan(v))
    if ok.any() and poly and len(poly) >= 3:
        out[ok] = Path(np.asarray(poly, float)).contains_points(
            np.stack([u[ok], v[ok]], axis=1))
    return out


def radial(cu, cv, r_in, r_out, a0=None, a1=None):
    """Membership test for discs / rings / ring sectors (angles in
    degrees as in `sector`). Returns f(u, v) -> bool array."""
    def f(u, v):
        u = np.asarray(u, float)
        v = np.asarray(v, float)
        r = np.hypot(u - cu, v - cv)
        m = (r >= r_in) & (r < r_out)
        if a0 is not None:
            ang = np.degrees(np.arctan2(-(v - cv), u - cu)) % 360.0
            lo, hi = a0 % 360.0, a1 % 360.0
            if lo <= hi:
                m &= (ang >= lo) & (ang < hi)
            else:
                m &= (ang >= lo) | (ang < hi)
        return m & ~(np.isnan(u) | np.isnan(v))
    return f
