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
ARM_COLORS = {"arm_a": "#E8A87C", "arm_b": "#7FA6D9", "arm_c": "#8FC79A"}


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
            "color": "#E4D3AE",
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


def _y_layout_px(hub, endpoints, arm_width_norm, neutral_radius_norm, video_size):
    """Y-maze built like the real apparatus, in pixel space:

    * centre = a triangle with one side per arm; its corners are where the
      walls of neighbouring arms meet (pushed outwards when the Neutral
      size asks for a bigger centre);
    * each arm runs from its side of the triangle to its tip, so arms and
      centre share their corners — no gaps, no overlaps.

    Returns (arms in endpoint order, triangle) as pixel points, or None."""
    if not hub or len(endpoints) < 3 or arm_width_norm <= 0:
        return None
    vw, vh = (float(video_size[0]), float(video_size[1])) if (
        video_size and video_size[0] and video_size[1]) else (1.0, 1.0)
    base = min(vw, vh)
    hx, hy = hub[0] * vw, hub[1] * vh
    h = arm_width_norm * base / 2.0
    arms = []
    for ep in endpoints[:3]:
        ex, ey = ep[0] * vw, ep[1] * vh
        L = math.hypot(ex - hx, ey - hy)
        if L <= 1e-6:
            return None
        u = ((ex - hx) / L, (ey - hy) / L)
        arms.append({"u": u, "n": (-u[1], u[0]), "e": (ex, ey),
                     "ang": math.atan2(u[1], u[0])})
    order = sorted(range(3), key=lambda i: arms[i]["ang"])

    def wall_meet(i, j):
        """Corner where arm i's wall facing arm j meets arm j's wall facing i."""
        ai, aj = arms[i], arms[j]
        si = 1.0 if (aj["u"][0] * ai["n"][0] + aj["u"][1] * ai["n"][1]) >= 0 else -1.0
        sj = 1.0 if (ai["u"][0] * aj["n"][0] + ai["u"][1] * aj["n"][1]) >= 0 else -1.0
        a11, a12 = si * ai["n"][0], si * ai["n"][1]
        a21, a22 = sj * aj["n"][0], sj * aj["n"][1]
        det = a11 * a22 - a12 * a21
        if abs(det) < 1e-9:
            return None
        x = (h * a22 - a12 * h) / det
        y = (a11 * h - h * a21) / det
        return (hx + x, hy + y)

    corners = {}
    for k in range(3):
        i, j = order[k], order[(k + 1) % 3]
        c = wall_meet(i, j)
        if c is None:
            return None
        corners[(i, j)] = corners[(j, i)] = c

    def side_of(i):
        others = [j for j in range(3) if j != i]
        return corners[(i, others[0])], corners[(i, others[1])]

    def dist_to_line(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1e-9
        return abs(dx * (p[1] - a[1]) - dy * (p[0] - a[0])) / L

    # Bigger centre on request: scale the corners out from the hub so the
    # closest side sits at the Neutral-size distance.
    r = max(0.0, float(neutral_radius_norm)) * base
    near = min(dist_to_line((hx, hy), *side_of(i)) for i in range(3))
    sc = max(1.0, r / near) if near > 1e-9 else 1.0
    for key, (cx, cy) in list(corners.items()):
        corners[key] = (hx + (cx - hx) * sc, hy + (cy - hy) * sc)

    def meet_line(p, d, a, b):
        """Point where the ray p + t·d crosses line a–b."""
        ex, ey = b[0] - a[0], b[1] - a[1]
        det = d[0] * ey - d[1] * ex
        if abs(det) < 1e-12:
            return p
        t = ((a[0] - p[0]) * ey - (a[1] - p[1]) * ex) / det
        return (p[0] + t * d[0], p[1] + t * d[1])

    out_arms = []
    for i, a in enumerate(arms):
        (nx, ny), (ux, uy) = a["n"], a["u"]
        s1, s2 = side_of(i)
        plus = meet_line((hx + nx * h, hy + ny * h), (ux, uy), s1, s2)
        minus = meet_line((hx - nx * h, hy - ny * h), (ux, uy), s1, s2)
        ex, ey = a["e"]
        out_arms.append([plus, (ex + nx * h, ey + ny * h),
                         (ex - nx * h, ey - ny * h), minus])
    tri = [corners[(order[k], order[(k + 1) % 3])] for k in range(3)]
    return out_arms, tri, (vw, vh)


def build_template_arms(hub, endpoints, arm_width_norm,
                         neutral_radius_norm=0.0, video_size=None):
    """Three arm outlines (4 corners each, normalized coords, endpoint
    order). Each arm starts on its side of the centre triangle (see
    _y_layout_px) and is arm_width wide (fraction of min(vw, vh)).
    Computed in pixel space when video_size is given."""
    lay = _y_layout_px(hub, endpoints, arm_width_norm, neutral_radius_norm, video_size)
    if lay is None:
        return []
    arms, _tri, (vw, vh) = lay
    return [[(x / vw, y / vh) for x, y in arm] for arm in arms]


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


def build_neutral_zone_geom(hub, endpoints, radius_norm, arm_width_norm,
                              video_size=None):
    """Centre (neutral) zone: a triangle with one side per arm, the arms
    starting on its sides (see _y_layout_px). radius_norm makes it bigger
    than the natural meeting point of the arm walls."""
    lay = _y_layout_px(hub, endpoints, arm_width_norm, radius_norm, video_size)
    if lay is None:
        return []
    _arms, tri, (vw, vh) = lay
    return [(x / vw, y / vh) for x, y in tri]


NEUTRAL_DEFAULT_COLOR = "#A9B4C6"


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
        "editable": True,          # corners can be dragged like the arms'
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
