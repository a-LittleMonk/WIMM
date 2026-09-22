"""Y-Maze zone schema. Three arms (A/B/C) as polygon zones.

Two creation modes:
  freehand: user clicks 4-6 corners per arm (polygon-edit start_edit)
  template: hub + 3 endpoints, app builds 3 rectangular arms with a
            given arm-width.
"""
import math

# Arm names — used as zone ids and metric keys.
ARM_NAMES = ["arm_a", "arm_b", "arm_c"]
ARM_LABELS = {"arm_a": "Arm A", "arm_b": "Arm B", "arm_c": "Arm C"}
ARM_COLORS = {"arm_a": "#FF7043", "arm_b": "#42A5F5", "arm_c": "#9CCC65"}


def default_y_template_geometry():
    """Default hub + 3 endpoint positions (normalized) for a fresh Y template.
    Hub centered, three arms at 12 / 8 / 4 o'clock (top / bot-left / bot-right)."""
    hub = (0.5, 0.5)
    endpoints = [
        (0.5,  0.15),   # Arm A — top
        (0.20, 0.78),   # Arm B — bottom-left
        (0.80, 0.78),   # Arm C — bottom-right
    ]
    return hub, endpoints


def y_template_overlay_zone(hub, endpoints):
    """Schema dict for the visible Y-template control overlay.
    Geometry layout: [hub, A_endpoint, B_endpoint, C_endpoint]. The
    zone-drawer renders this with shape=y_template (3 dashed spokes
    + labeled endpoint dots) and the points are draggable in idle mode."""
    return {
        "name": "y_template",
        "type": "polygon",
        "geometry": [tuple(hub)] + [tuple(p) for p in endpoints[:3]],
        "style": {
            "color": "#FFB74D",
            "thickness": 2,
            "dashed": True,
            "shape": "y_template",
            "endpoint_labels": ["A", "B", "C"],
        },
        "editable": True,
        "editor_hint": {"n_corners": 4},
    }


def empty_arm_zone(name):
    """Return a zone dict for an empty (unset) arm. Outline-only by
    default — the Y-maze overlay renderer fills the arm live only while
    the mouse is inside it."""
    return {
        "name": name,
        "type": "polygon",
        "geometry": [],
        "style": {
            "color": ARM_COLORS[name],
            "thickness": 2,
            "fill_alpha": 0,
            "dashed": False,
        },
        "editable": True,
        "editor_hint": {"n_corners": 4},
    }


def empty_neutral_zone():
    """Empty placeholder for the neutral zone in manual mode so the user
    can hit the N button and start drawing."""
    return {
        "name": "neutral_zone",
        "type": "polygon",
        "geometry": [],
        "style": {
            "color": NEUTRAL_DEFAULT_COLOR,
            "thickness": 2,
            "fill_alpha": 0,
            "dashed": False,
        },
        "editable": True,
        "editor_hint": {"n_corners": 4},
    }


def build_template_arms(hub, endpoints, arm_width_norm,
                         neutral_radius_norm=0.0, video_size=None):
    """Given hub (cx, cy) normalized and 3 endpoint (x, y) normalized
    points + arm_width as a fraction of min(vw, vh), return three
    rectangular polygons (4 corners each) in normalized coords.

    Geometry runs in PIXEL space so perpendiculars are truly perpendicular
    regardless of frame aspect ratio. Without video_size we fall back to
    norm-space math, which is only correct for square frames — pass it
    whenever vw and vh differ.

    neutral_radius_norm shrinks each arm from the hub end: arm starts at
    hub + unit*neutral_radius (the neutral-triangle vertex along that
    arm's spoke) instead of at the hub itself."""
    if not hub or len(endpoints) < 3 or arm_width_norm <= 0:
        return []
    if video_size and video_size[0] and video_size[1]:
        vw, vh = float(video_size[0]), float(video_size[1])
        base = min(vw, vh)
        cx_px, cy_px = hub[0] * vw, hub[1] * vh
        half_px = arm_width_norm * base / 2.0
        r_px = max(0.0, float(neutral_radius_norm)) * base
        arms = []
        for ep in endpoints[:3]:
            ex_px, ey_px = ep[0] * vw, ep[1] * vh
            dx, dy = ex_px - cx_px, ey_px - cy_px
            L = math.hypot(dx, dy)
            if L <= 1e-6:
                arms.append([])
                continue
            ux, uy = dx / L, dy / L
            sx, sy = cx_px + ux * r_px, cy_px + uy * r_px
            nx, ny = -uy, ux  # true perpendicular, pixel space
            corners_px = [
                (sx + nx * half_px, sy + ny * half_px),
                (ex_px + nx * half_px, ey_px + ny * half_px),
                (ex_px - nx * half_px, ey_px - ny * half_px),
                (sx - nx * half_px, sy - ny * half_px),
            ]
            arms.append([(c[0] / vw, c[1] / vh) for c in corners_px])
        return arms
    # Legacy square-frame path (kept for callers without video_size).
    cx, cy = hub
    half = arm_width_norm / 2.0
    r = max(0.0, float(neutral_radius_norm))
    arms = []
    for ep in endpoints[:3]:
        ex, ey = ep
        dx, dy = ex - cx, ey - cy
        L = math.hypot(dx, dy)
        if L <= 1e-6:
            arms.append([])
            continue
        ux, uy = dx / L, dy / L
        sx, sy = cx + ux * r, cy + uy * r
        nx, ny = -uy, ux
        c1 = (sx + nx * half, sy + ny * half)
        c2 = (ex + nx * half, ey + ny * half)
        c3 = (ex - nx * half, ey - ny * half)
        c4 = (sx - nx * half, sy - ny * half)
        arms.append([c1, c2, c3, c4])
    return arms


def canonical_y_geometry(video_size, margin_frac=0.08):
    """Canonical hub + 3 endpoints in normalized coords for a perfectly
    symmetric Y pointing up. Used as the destination of the perspective
    homography so the warped frame shows the maze with arms 120° apart.
    Output frame keeps the input (vw, vh) aspect — only the maze itself
    occupies a centered equilateral region sized by min(vw, vh)."""
    vw, vh = video_size
    if not vw or not vh:
        return None, None
    # Pixel offset from hub center to each canonical tip. Smaller margin
    # makes the maze fill more of the frame than the original default.
    L_px = min(vw, vh) * (0.5 - margin_frac)
    cx, cy = vw / 2.0, vh / 2.0
    import math
    # Top, lower-left, lower-right (image coords, y-down).
    tips = [
        (cx,                      cy - L_px),
        (cx - L_px * math.sin(math.radians(60)),
         cy + L_px * math.cos(math.radians(60))),
        (cx + L_px * math.sin(math.radians(60)),
         cy + L_px * math.cos(math.radians(60))),
    ]
    hub_norm = (cx / vw, cy / vh)
    tips_norm = [(x / vw, y / vh) for x, y in tips]
    return hub_norm, tips_norm


def build_y_homography(src_hub_norm, src_endpoints_norm, video_size):
    """src points (normalized) → canonical Y (pixels in `video_size`).
    Returns (H, (warp_w, warp_h)) or None on failure.

    Source endpoints are sorted by angle around the source hub and zipped
    against the canonical tips sorted the same way, so the mapping picks
    whichever source tip is most "upward" → canonical top, and so on.
    This keeps output orientation stable regardless of how the user's
    template is rotated in the camera frame."""
    import math
    import numpy as np
    import cv2
    if (not src_hub_norm or not src_endpoints_norm
            or len(src_endpoints_norm) < 3 or not video_size):
        return None
    vw, vh = video_size
    if not vw or not vh:
        return None
    hub_dst_norm, tips_dst_norm = canonical_y_geometry((vw, vh))
    if hub_dst_norm is None:
        return None
    cx_s, cy_s = src_hub_norm
    def _angle(p):
        return math.atan2(p[1] - cy_s, p[0] - cx_s)
    src_tips_sorted = sorted(src_endpoints_norm[:3], key=_angle)
    cx_d, cy_d = hub_dst_norm
    dst_tips_sorted = sorted(tips_dst_norm, key=lambda p: math.atan2(
        p[1] - cy_d, p[0] - cx_d))
    src_px = [(src_hub_norm[0] * vw, src_hub_norm[1] * vh)]
    src_px += [(p[0] * vw, p[1] * vh) for p in src_tips_sorted]
    dst_px = [(hub_dst_norm[0] * vw, hub_dst_norm[1] * vh)]
    dst_px += [(p[0] * vw, p[1] * vh) for p in dst_tips_sorted]
    src_arr = np.array(src_px, dtype=np.float32)
    dst_arr = np.array(dst_px, dtype=np.float32)
    try:
        H = cv2.getPerspectiveTransform(src_arr, dst_arr)
    except cv2.error:
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
    """Return intersection of infinite line (p1,p2) with infinite line
    (p3,p4). None if parallel."""
    x1, y1 = p1; x2, y2 = p2; x3, y3 = p3; x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-12:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def build_neutral_zone_geom(hub, endpoints, radius_norm, arm_width_norm,
                              video_size=None):
    """3-pronged Y polygon: union of 3 stub rectangles, each spanning
    from the hub out to the arm's start point (arm_width wide). The
    stubs overlap at the hub so the union has 3 prongs joined at narrow
    waists where adjacent stub side-walls cross.

    Geometry runs in PIXEL space when video_size is supplied so the stubs
    stay rectangular regardless of frame aspect; falls back to norm-space
    math (only correct for square frames) otherwise."""
    if (not hub or not endpoints or len(endpoints) < 3
            or radius_norm <= 0 or arm_width_norm <= 0):
        return []
    if video_size and video_size[0] and video_size[1]:
        vw, vh = float(video_size[0]), float(video_size[1])
        base = min(vw, vh)
        cx_px, cy_px = hub[0] * vw, hub[1] * vh
        half_px = arm_width_norm * base / 2.0
        r_px = radius_norm * base
        arms = []
        for ep in endpoints[:3]:
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
    for ep in endpoints[:3]:
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


NEUTRAL_DEFAULT_COLOR = "#BDBDBD"


def neutral_zone(hub, endpoints, radius_norm, arm_width_norm,
                 color=NEUTRAL_DEFAULT_COLOR, video_size=None):
    """Schema dict for the central neutral zone (drawn on top of arms)."""
    return {
        "name": "neutral_zone",
        "type": "polygon",
        "geometry": build_neutral_zone_geom(hub, endpoints, radius_norm,
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
                              neutral_radius_norm=0.0, pad_norm=0.04,
                              video_size=None):
    """Label point for each arm: midpoint along the arm length, offset
    perpendicular to the spoke by (half-width + pad). Side is chosen as
    the perpendicular that lands furthest from the OTHER two endpoints'
    centroid, so for a Y-maze the labels land on the outer side of each
    arm (away from the other two arms) instead of inside the Y triangle.
    Geometry runs in PIXEL space when video_size is supplied so the offset
    stays truly perpendicular on non-square frames. Clamped into
    [0.01, 0.99] so labels don't fall off the frame edge."""
    out = {}
    if not hub or not endpoints or len(endpoints) < 3 or arm_width_norm <= 0:
        return out
    eps = list(endpoints[:3])
    if video_size and video_size[0] and video_size[1]:
        vw, vh = float(video_size[0]), float(video_size[1])
        base = min(vw, vh)
        cx_px, cy_px = hub[0] * vw, hub[1] * vh
        half_px = arm_width_norm * base / 2.0
        r_px = max(0.0, float(neutral_radius_norm)) * base
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
            others = [eps_px[j] for j in range(3) if j != i]
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
    r = max(0.0, float(neutral_radius_norm))
    for i, (name, ep) in enumerate(zip(ARM_NAMES, eps)):
        ex, ey = ep
        dx, dy = ex - cx, ey - cy
        L = math.hypot(dx, dy)
        if L <= 1e-6:
            continue
        ux, uy = dx / L, dy / L
        sx, sy = cx + ux * r, cy + uy * r
        mx, my = (sx + ex) / 2.0, (sy + ey) / 2.0
        others = [eps[j] for j in range(3) if j != i]
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


def build_schema_from_arms(arm_geoms):
    """arm_geoms: dict name -> list of (x,y) norm. Returns schema list."""
    schema = []
    for name in ARM_NAMES:
        z = empty_arm_zone(name)
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
