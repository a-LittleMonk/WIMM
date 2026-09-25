"""Elevated Plus Maze zone schema. Four arms (N/S/E/W) as polygon zones
plus a central zone auto-derived from arm intersection.

Two creation modes (mirror of Y-Maze):
  freehand: user clicks polygon corners per arm.
  template: hub + 4 endpoints, app builds 4 rectangular arms with a
            given arm-width and an auto-derived center polygon.

Each arm has a "kind" — open / closed / neutral / custom — that drives
its outline + fill style (open = dashed outline, closed = filled).
"""
import math

# Arm names — used as zone ids and metric keys. Order is canonical N/S/E/W
# so kind defaults and aggregation are stable.
ARM_NAMES = ["arm_n", "arm_s", "arm_e", "arm_w"]
ARM_LABELS = {"arm_n": "Arm N", "arm_s": "Arm S",
              "arm_e": "Arm E", "arm_w": "Arm W"}

# Default kinds: vertical = Open, horizontal = Closed. User can flip per arm.
DEFAULT_ARM_KINDS = {
    "arm_n": "open", "arm_s": "open",
    "arm_e": "closed", "arm_w": "closed",
}

# Kind colors. Center polygon uses neutral grey.
KIND_COLORS = {
    "open":    "#7FA6D9",  # blue
    "closed":  "#E8A87C",  # orange
    "neutral": "#8FC79A",  # green
    "custom":  "#BA68C8",  # purple
}
CENTER_DEFAULT_COLOR = "#A9B4C6"

# Style per kind: open = dashed outline only; closed = solid outline + fill.
KIND_STYLE = {
    "open":    {"dashed": True,  "fill_alpha": 0.0},
    "closed":  {"dashed": False, "fill_alpha": 0.18},
    "neutral": {"dashed": False, "fill_alpha": 0.0},
    "custom":  {"dashed": False, "fill_alpha": 0.10},
}


def default_plus_template_geometry():
    """Default hub + 4 endpoint positions (normalized) for a fresh template.
    Hub centered, arms at N/S/E/W positions inside the frame margins."""
    hub = (0.5, 0.5)
    endpoints = [
        (0.5,  0.12),   # arm_n
        (0.5,  0.88),   # arm_s
        (0.88, 0.5),    # arm_e
        (0.12, 0.5),    # arm_w
    ]
    return hub, endpoints


def plus_template_overlay_zone(hub, endpoints):
    """Schema dict for the visible plus-template control overlay.
    Geometry layout: [hub, N_ep, S_ep, E_ep, W_ep]. The zone-drawer
    renders this with shape=y_template (reused — generic spoke renderer)
    and the points are draggable in idle mode."""
    return {
        "name": "epm_template",
        "type": "polygon",
        "geometry": [tuple(hub)] + [tuple(p) for p in endpoints[:4]],
        "style": {
            "color": "#E4D3AE",
            "thickness": 2,
            "dashed": True,
            "shape": "y_template",
            "endpoint_labels": ["N", "S", "E", "W"],
        },
        "editable": True,
        "editor_hint": {"n_corners": 5},
    }


def empty_arm_zone(name, kind="closed"):
    """Return a zone dict for an empty (unset) arm. Style derives from kind."""
    color = KIND_COLORS.get(kind, KIND_COLORS["closed"])
    style = KIND_STYLE.get(kind, KIND_STYLE["closed"])
    return {
        "name": name,
        "type": "polygon",
        "geometry": [],
        "style": {
            "color": color,
            "thickness": 2,
            "fill_alpha": style["fill_alpha"],
            "dashed": style["dashed"],
            "epm_kind": kind,
        },
        "editable": True,
        "editor_hint": {"n_corners": 4},
    }


def empty_center_zone():
    return {
        "name": "center_zone",
        "type": "polygon",
        "geometry": [],
        "style": {
            "color": CENTER_DEFAULT_COLOR,
            "thickness": 2,
            "fill_alpha": 0,
            "dashed": False,
        },
        "editable": True,
        "editor_hint": {"n_corners": 4},
    }


def build_template_arms(hub, endpoints, arm_width_norm,
                         center_radius_norm=0.0, video_size=None):
    """Given hub + 4 endpoints (normalized) + arm_width as a fraction of
    min(vw, vh), return four rectangular polygons (4 corners each) in
    normalized coords.

    Geometry runs in PIXEL space when video_size supplied so perpendiculars
    are truly perpendicular regardless of frame aspect ratio.

    center_radius_norm shrinks each arm from the hub end: arm starts at
    hub + unit*center_radius (the center-square edge along that arm's
    spoke) instead of at the hub itself."""
    if not hub or len(endpoints) < 4 or arm_width_norm <= 0:
        return []
    if video_size and video_size[0] and video_size[1]:
        vw, vh = float(video_size[0]), float(video_size[1])
        base = min(vw, vh)
        cx_px, cy_px = hub[0] * vw, hub[1] * vh
        half_px = arm_width_norm * base / 2.0
        r_px = max(0.0, float(center_radius_norm)) * base
        arms = []
        for ep in endpoints[:4]:
            ex_px, ey_px = ep[0] * vw, ep[1] * vh
            dx, dy = ex_px - cx_px, ey_px - cy_px
            L = math.hypot(dx, dy)
            if L <= 1e-6:
                arms.append([])
                continue
            ux, uy = dx / L, dy / L
            sx, sy = cx_px + ux * r_px, cy_px + uy * r_px
            nx, ny = -uy, ux
            corners_px = [
                (sx + nx * half_px, sy + ny * half_px),
                (ex_px + nx * half_px, ey_px + ny * half_px),
                (ex_px - nx * half_px, ey_px - ny * half_px),
                (sx - nx * half_px, sy - ny * half_px),
            ]
            arms.append([(c[0] / vw, c[1] / vh) for c in corners_px])
        return arms
    # Legacy square-frame fallback.
    cx, cy = hub
    half = arm_width_norm / 2.0
    r = max(0.0, float(center_radius_norm))
    arms = []
    for ep in endpoints[:4]:
        ex, ey = ep
        dx, dy = ex - cx, ey - cy
        L = math.hypot(dx, dy)
        if L <= 1e-6:
            arms.append([])
            continue
        ux, uy = dx / L, dy / L
        sx, sy = cx + ux * r, cy + uy * r
        nx, ny = -uy, ux
        arms.append([
            (sx + nx * half, sy + ny * half),
            (ex + nx * half, ey + ny * half),
            (ex - nx * half, ey - ny * half),
            (sx - nx * half, sy - ny * half),
        ])
    return arms


def canonical_plus_geometry(video_size, margin_frac=0.08):
    """Canonical hub + 4 endpoints in normalized coords for a perfectly
    symmetric plus pointing N/S/E/W. Used as the destination of the
    perspective homography so the warped frame shows the maze with arms
    90° apart."""
    vw, vh = video_size
    if not vw or not vh:
        return None, None
    L_px = min(vw, vh) * (0.5 - margin_frac)
    cx, cy = vw / 2.0, vh / 2.0
    tips = [
        (cx,         cy - L_px),  # N
        (cx,         cy + L_px),  # S
        (cx + L_px,  cy),         # E
        (cx - L_px,  cy),         # W
    ]
    hub_norm = (cx / vw, cy / vh)
    tips_norm = [(x / vw, y / vh) for x, y in tips]
    return hub_norm, tips_norm


def build_plus_homography(src_hub_norm, src_endpoints_norm, video_size):
    """src points (normalized) -> canonical plus (pixels in `video_size`).
    Returns (H, (warp_w, warp_h)) or None on failure.

    Source endpoints sorted by angle around the source hub and zipped
    against the canonical tips sorted the same way, so whichever source
    tip is most "upward" maps to canonical N, and so on. Orientation
    stable regardless of how the user's template is rotated."""
    import numpy as np
    import cv2
    if (not src_hub_norm or not src_endpoints_norm
            or len(src_endpoints_norm) < 4 or not video_size):
        return None
    vw, vh = video_size
    if not vw or not vh:
        return None
    hub_dst_norm, tips_dst_norm = canonical_plus_geometry((vw, vh))
    if hub_dst_norm is None:
        return None
    cx_s, cy_s = src_hub_norm

    def _angle(p):
        return math.atan2(p[1] - cy_s, p[0] - cx_s)

    src_tips_sorted = sorted(src_endpoints_norm[:4], key=_angle)
    cx_d, cy_d = hub_dst_norm
    dst_tips_sorted = sorted(tips_dst_norm, key=lambda p: math.atan2(
        p[1] - cy_d, p[0] - cx_d))
    # 5-point correspondence (hub + 4 tips). cv2.findHomography handles >4.
    src_px = [(src_hub_norm[0] * vw, src_hub_norm[1] * vh)]
    src_px += [(p[0] * vw, p[1] * vh) for p in src_tips_sorted]
    dst_px = [(hub_dst_norm[0] * vw, hub_dst_norm[1] * vh)]
    dst_px += [(p[0] * vw, p[1] * vh) for p in dst_tips_sorted]
    src_arr = np.array(src_px, dtype=np.float32)
    dst_arr = np.array(dst_px, dtype=np.float32)
    try:
        H, _ = cv2.findHomography(src_arr, dst_arr)
    except cv2.error:
        return None
    if H is None:
        return None
    return H, (int(vw), int(vh))


def convex_hull(points):
    """Andrew's monotone-chain convex hull. Returns CCW-ordered points."""
    pts = sorted({(float(p[0]), float(p[1])) for p in points})
    if len(pts) <= 2:
        return list(pts)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _line_intersect(p1, p2, p3, p4):
    x1, y1 = p1; x2, y2 = p2; x3, y3 = p3; x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-12:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def build_center_zone_geom(hub, endpoints, radius_norm, arm_width_norm,
                            video_size=None):
    """Center polygon: union of 4 stub rectangles, one per arm, each
    spanning from the hub out to the arm's start point (arm_width wide).
    The stubs overlap at the hub so the union has 4 prongs joined at narrow
    waists where adjacent stub side-walls cross.

    For a true plus shape (N/S vs E/W perpendicular), the result reduces
    to a central square plus four short prongs along each arm — visually
    correct as the "shared crossing region" between arms."""
    if (not hub or not endpoints or len(endpoints) < 4
            or radius_norm <= 0 or arm_width_norm <= 0):
        return []
    if video_size and video_size[0] and video_size[1]:
        vw, vh = float(video_size[0]), float(video_size[1])
        base = min(vw, vh)
        cx_px, cy_px = hub[0] * vw, hub[1] * vh
        half_px = arm_width_norm * base / 2.0
        r_px = radius_norm * base
        arms = []
        for ep in endpoints[:4]:
            ex_px, ey_px = ep[0] * vw, ep[1] * vh
            dx, dy = ex_px - cx_px, ey_px - cy_px
            L = math.hypot(dx, dy)
            if L <= 1e-6:
                return []
            ux, uy = dx / L, dy / L
            sx, sy = cx_px + ux * r_px, cy_px + uy * r_px
            nx, ny = -uy, ux
            arms.append({
                "angle": math.atan2(uy, ux),
                "s1": (cx_px + nx * half_px, cy_px + ny * half_px),
                "s2": (sx + nx * half_px, sy + ny * half_px),
                "s3": (sx - nx * half_px, sy - ny * half_px),
                "s4": (cx_px - nx * half_px, cy_px - ny * half_px),
            })
        arms.sort(key=lambda a: a["angle"])
        poly_px = []
        n = len(arms)
        for i in range(n):
            arm = arms[i]
            prev_arm = arms[(i - 1) % n]
            kink = _line_intersect(arm["s4"], arm["s3"],
                                   prev_arm["s1"], prev_arm["s2"])
            poly_px.append(kink if kink is not None else arm["s4"])
            poly_px.append(arm["s3"])
            poly_px.append(arm["s2"])
        return [(p[0] / vw, p[1] / vh) for p in poly_px]
    # Legacy square-frame path.
    cx, cy = hub
    half = arm_width_norm / 2.0
    arms = []
    for ep in endpoints[:4]:
        ex, ey = ep
        dx, dy = ex - cx, ey - cy
        L = math.hypot(dx, dy)
        if L <= 1e-6:
            return []
        ux, uy = dx / L, dy / L
        sx, sy = cx + ux * radius_norm, cy + uy * radius_norm
        nx, ny = -uy, ux
        arms.append({
            "angle": math.atan2(uy, ux),
            "s1": (cx + nx * half, cy + ny * half),
            "s2": (sx + nx * half, sy + ny * half),
            "s3": (sx - nx * half, sy - ny * half),
            "s4": (cx - nx * half, cy - ny * half),
        })
    arms.sort(key=lambda a: a["angle"])
    poly = []
    n = len(arms)
    for i in range(n):
        arm = arms[i]
        prev_arm = arms[(i - 1) % n]
        kink = _line_intersect(arm["s4"], arm["s3"],
                               prev_arm["s1"], prev_arm["s2"])
        poly.append(kink if kink is not None else arm["s4"])
        poly.append(arm["s3"])
        poly.append(arm["s2"])
    return poly


def center_zone(hub, endpoints, radius_norm, arm_width_norm,
                 color=CENTER_DEFAULT_COLOR, video_size=None):
    """Schema dict for the central plus-zone (drawn on top of arms)."""
    return {
        "name": "center_zone",
        "type": "polygon",
        "geometry": build_center_zone_geom(hub, endpoints, radius_norm,
                                           arm_width_norm,
                                           video_size=video_size),
        "style": {
            "color": color,
            "thickness": 2,
            "fill_alpha": 0,
            "dashed": False,
        },
        "editable": False,
    }


def build_arm_label_positions(hub, endpoints, arm_width_norm,
                              center_radius_norm=0.0, pad_norm=0.04,
                              video_size=None):
    """Label point for each arm: midpoint along the arm length, offset
    perpendicular to the spoke by (half-width + pad). Side chosen as the
    perpendicular that lands furthest from the OTHER three endpoints'
    centroid, so labels land OUTSIDE the plus shape.

    Clamped to [0.01, 0.99] so labels stay on-frame."""
    out = {}
    if (not hub or not endpoints or len(endpoints) < 4
            or arm_width_norm <= 0):
        return out
    eps = list(endpoints[:4])
    if video_size and video_size[0] and video_size[1]:
        vw, vh = float(video_size[0]), float(video_size[1])
        base = min(vw, vh)
        cx_px, cy_px = hub[0] * vw, hub[1] * vh
        half_px = arm_width_norm * base / 2.0
        r_px = max(0.0, float(center_radius_norm)) * base
        pad_px = pad_norm * base
        eps_px = [(p[0] * vw, p[1] * vh) for p in eps]
        for i, (name, (ex_px, ey_px)) in enumerate(zip(ARM_NAMES, eps_px)):
            dx, dy = ex_px - cx_px, ey_px - cy_px
            L = math.hypot(dx, dy)
            if L <= 1e-6:
                continue
            ux, uy = dx / L, dy / L
            sx, sy = cx_px + ux * r_px, cy_px + uy * r_px
            mx, my = (sx + ex_px) / 2.0, (sy + ey_px) / 2.0
            others = [eps_px[j] for j in range(4) if j != i]
            ox = sum(p[0] for p in others) / len(others)
            oy = sum(p[1] for p in others) / len(others)
            offset = half_px + pad_px
            cand_a = (mx + (-uy) * offset, my + ux * offset)
            cand_b = (mx + uy * offset,    my + (-ux) * offset)
            da = (cand_a[0] - ox) ** 2 + (cand_a[1] - oy) ** 2
            db = (cand_b[0] - ox) ** 2 + (cand_b[1] - oy) ** 2
            chosen = cand_a if da >= db else cand_b
            lx = max(0.01, min(0.99, chosen[0] / vw))
            ly = max(0.01, min(0.99, chosen[1] / vh))
            out[name] = (lx, ly)
        return out
    # Legacy square-frame path.
    cx, cy = hub
    half = arm_width_norm / 2.0
    r = max(0.0, float(center_radius_norm))
    for i, (name, ep) in enumerate(zip(ARM_NAMES, eps)):
        ex, ey = ep
        dx, dy = ex - cx, ey - cy
        L = math.hypot(dx, dy)
        if L <= 1e-6:
            continue
        ux, uy = dx / L, dy / L
        sx, sy = cx + ux * r, cy + uy * r
        mx, my = (sx + ex) / 2.0, (sy + ey) / 2.0
        others = [eps[j] for j in range(4) if j != i]
        ox = sum(p[0] for p in others) / len(others)
        oy = sum(p[1] for p in others) / len(others)
        offset = half + pad_norm
        cand_a = (mx + (-uy) * offset, my + ux * offset)
        cand_b = (mx + uy * offset,    my + (-ux) * offset)
        da = (cand_a[0] - ox) ** 2 + (cand_a[1] - oy) ** 2
        db = (cand_b[0] - ox) ** 2 + (cand_b[1] - oy) ** 2
        chosen = cand_a if da >= db else cand_b
        lx = max(0.01, min(0.99, chosen[0]))
        ly = max(0.01, min(0.99, chosen[1]))
        out[name] = (lx, ly)
    return out


def build_schema_from_arms(arm_geoms, arm_kinds=None):
    """arm_geoms: dict name -> list of (x,y) norm. Returns schema list."""
    arm_kinds = arm_kinds or DEFAULT_ARM_KINDS
    schema = []
    for name in ARM_NAMES:
        kind = arm_kinds.get(name, DEFAULT_ARM_KINDS[name])
        z = empty_arm_zone(name, kind)
        z["geometry"] = list(arm_geoms.get(name) or [])
        schema.append(z)
    return schema


def get_arm_geoms(host):
    """Read arm geometries from the host's zone_drawer extra zones."""
    out = {}
    zd = getattr(host, "zone_drawer", None)
    if zd is None:
        return out
    for name in ARM_NAMES:
        z = zd.get_zone(name)
        out[name] = list(z["geometry"]) if (z and z.get("geometry")) else []
    return out


def aggregate_kind_membership(arm_kinds):
    """Return dict kind -> list of arm names assigned to that kind.
    Used by metrics to roll up per-arm counters into open/closed totals."""
    out = {}
    for name in ARM_NAMES:
        k = arm_kinds.get(name, DEFAULT_ARM_KINDS.get(name, "neutral"))
        out.setdefault(k, []).append(name)
    return out
