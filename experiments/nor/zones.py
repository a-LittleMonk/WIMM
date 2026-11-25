"""NOR (Novel Object Recognition) zone schema.

Two objects (A, B) inside a square arena. Each object has:
  - footprint polygon (shape = circle / square / triangle / custom)
  - interaction zone = every point within `padding_cm` of the footprint

The arena outline is shown but never filled (per spec). Only the
interaction zones get a live fill when the nose is inside.

Geometry is stored normalized (0..1) so it survives video-size changes.
Shape builders take size in cm + px_per_cm + video_size so the user can
tweak the cm number without re-placing the object.
"""
import math

# Object slot identifiers (fixed — two objects per NOR run).
OBJECT_NAMES = ["object_a", "object_b"]
OBJECT_LABELS = {"object_a": "Object A", "object_b": "Object B"}
OBJECT_COLORS = {"object_a": "#E8A87C", "object_b": "#7FA6D9"}

# Per-object zone name suffixes — footprint = visible object outline,
# zone = inflated interaction circle/polygon (the one that fills live).
def footprint_name(obj_id):
    return f"{obj_id}_footprint"


def zone_name(obj_id):
    return f"{obj_id}_zone"


ROLE_NONE = "none"
ROLE_FAMILIAR = "familiar"
ROLE_NOVEL = "novel"
ROLE_LABELS = {
    ROLE_NONE: "—",
    ROLE_FAMILIAR: "Familiar",
    ROLE_NOVEL: "Novel",
}

SHAPE_CIRCLE = "circle"
SHAPE_SQUARE = "square"
SHAPE_TRIANGLE = "triangle"
SHAPE_CUSTOM = "custom"
SHAPE_LABELS = {
    SHAPE_CIRCLE: "Circle",
    SHAPE_SQUARE: "Square",
    SHAPE_TRIANGLE: "Triangle",
    SHAPE_CUSTOM: "Custom",
}

# Custom-polygon corner bounds (matches Y-Maze freehand pattern).
CUSTOM_MIN_CORNERS = 3
CUSTOM_MAX_CORNERS = 8


def default_object_state(obj_id):
    """Default per-object dict used when host first wires the plugin."""
    return {
        "name": OBJECT_LABELS[obj_id],
        "role": ROLE_NONE,
        "shape": SHAPE_CIRCLE,
        "size_cm": 5.0,        # diameter for circle, side for square/triangle
        "padding_cm": 2.0,     # outward inflation for the interaction zone
        "color": OBJECT_COLORS[obj_id],
        "center_norm": None,   # (x, y) — set once user clicks on preview
        "custom_geom_norm": [],  # only used when shape == "custom"
    }


def _circle_polygon(cx, cy, r, n=48):
    """Approximate a circle as an n-sided polygon (smooth enough at 48)."""
    return [
        (cx + r * math.cos(2 * math.pi * i / n),
         cy + r * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]


def _square_polygon(cx, cy, side):
    half = side / 2.0
    return [
        (cx - half, cy - half),
        (cx + half, cy - half),
        (cx + half, cy + half),
        (cx - half, cy + half),
    ]


def _triangle_polygon(cx, cy, side):
    """Equilateral triangle, point-up, centered on (cx, cy)."""
    # Circumradius R = side / sqrt(3); place vertices at angles 90, 210, 330.
    R = side / math.sqrt(3)
    return [
        (cx + R * math.cos(math.radians(a)),
         cy + R * math.sin(math.radians(a)))
        for a in (-90, 30, 150)
    ]


def _scale_polygon(poly_px, factor):
    """Uniform scale around centroid. Exact inflation for circles/regular
    polygons; approximate (halo, not true Minkowski) for arbitrary
    convex/concave shapes. Acceptable for an interaction-zone halo —
    user controls padding cm directly."""
    if not poly_px:
        return []
    cx = sum(p[0] for p in poly_px) / len(poly_px)
    cy = sum(p[1] for p in poly_px) / len(poly_px)
    return [(cx + (x - cx) * factor, cy + (y - cy) * factor)
            for x, y in poly_px]


def _px_to_norm(poly_px, vw, vh):
    return [(x / vw, y / vh) for x, y in poly_px]


def build_footprint_norm(state, px_per_cm, video_size):
    """Build the object footprint polygon in NORMALIZED coords.

    Reads `state["shape"]`, `state["size_cm"]`, `state["center_norm"]`,
    and `state["custom_geom_norm"]`. Returns [] if center is unset or
    px_per_cm missing (custom shape only needs `custom_geom_norm`).
    """
    if not state:
        return []
    shape = state.get("shape", SHAPE_CIRCLE)
    if shape == SHAPE_CUSTOM:
        # Custom polygon is captured directly in normalized coords by the
        # zone-drawer freehand editor — size_cm doesn't apply.
        return list(state.get("custom_geom_norm") or [])
    if not video_size:
        return []
    vw, vh = video_size
    if not vw or not vh:
        return []
    center = state.get("center_norm")
    if not center:
        return []
    cx_px = float(center[0]) * vw
    cy_px = float(center[1]) * vh
    size_cm = float(state.get("size_cm") or 0)
    if size_cm <= 0:
        return []
    # Fallback when calibration isn't drawn yet: size the shape as a
    # fraction of the frame so the user can still see what they placed.
    # When px_per_cm becomes known (calib line / auto-cal), zones rebuild
    # at the real cm size — see ui._refresh_zones wiring.
    if not px_per_cm:
        base = min(vw, vh)
        # Heuristic: 5 cm ≈ 8% of frame, so 1 cm ≈ 1.6% of frame.
        size_px = (size_cm / 5.0) * base * 0.08
    else:
        size_px = size_cm * px_per_cm
    if shape == SHAPE_CIRCLE:
        poly_px = _circle_polygon(cx_px, cy_px, size_px / 2.0)
    elif shape == SHAPE_SQUARE:
        poly_px = _square_polygon(cx_px, cy_px, size_px)
    elif shape == SHAPE_TRIANGLE:
        poly_px = _triangle_polygon(cx_px, cy_px, size_px)
    else:
        return []
    return _px_to_norm(poly_px, vw, vh)


def build_zone_norm(footprint_norm, state, px_per_cm, video_size):
    """Inflate the footprint outward by `padding_cm` → the interaction
    zone. Returns the original footprint if padding is 0 (so nose
    must touch the object itself to count)."""
    if not footprint_norm:
        return []
    padding_cm = float(state.get("padding_cm") or 0)
    if padding_cm <= 0 or not video_size:
        return list(footprint_norm)
    vw, vh = video_size
    if not vw or not vh:
        return list(footprint_norm)
    poly_px = [(x * vw, y * vh) for x, y in footprint_norm]
    cx = sum(p[0] for p in poly_px) / len(poly_px)
    cy = sum(p[1] for p in poly_px) / len(poly_px)
    mean_r = sum(math.hypot(x - cx, y - cy) for x, y in poly_px) / len(poly_px)
    if mean_r <= 0:
        return list(footprint_norm)
    # Same fallback as build_footprint_norm so the halo stays visible
    # before calibration is drawn.
    if not px_per_cm:
        base = min(vw, vh)
        padding_px = (padding_cm / 5.0) * base * 0.08
    else:
        padding_px = padding_cm * px_per_cm
    if _is_convex(poly_px):
        return _px_to_norm(_offset_convex(poly_px, padding_px), vw, vh)
    # shortcut: a concave custom outline is scaled around its centre, so its
    # padding is only approximate; offset it exactly if custom shapes matter.
    factor = (mean_r + padding_px) / mean_r
    return _px_to_norm(_scale_polygon(poly_px, factor), vw, vh)


def _signed_area(poly):
    return sum(poly[i][0] * poly[i - 1][1] - poly[i - 1][0] * poly[i][1]
               for i in range(len(poly))) / 2.0


def _is_convex(poly):
    n = len(poly)
    if n < 3:
        return False
    signs = set()
    for i in range(n):
        (x0, y0), (x1, y1), (x2, y2) = poly[i - 1], poly[i], poly[(i + 1) % n]
        c = (x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1)
        if abs(c) > 1e-9:
            signs.add(c > 0)
    return len(signs) == 1


def _offset_convex(poly, d, step_deg=5.0):
    """Every point within `d` of a convex polygon: each side pushed out by
    exactly d, joined by round corners. (Scaling around the centre would
    give squares / triangles less than d along their sides.)"""
    sgn = -1.0 if _signed_area(poly) > 0 else 1.0     # outward side of each edge
    n = len(poly)
    normals = []
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        L = math.hypot(x1 - x0, y1 - y0) or 1.0
        normals.append((sgn * (y1 - y0) / L, -sgn * (x1 - x0) / L))
    out = []
    for i in range(n):
        x, y = poly[i]
        a0 = math.atan2(normals[i - 1][1], normals[i - 1][0])
        a1 = math.atan2(normals[i][1], normals[i][0])
        turn = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi    # corner turn, < 180°
        k = max(1, int(math.ceil(abs(math.degrees(turn)) / step_deg)))
        for j in range(k + 1):
            a = a0 + turn * j / k
            out.append((x + d * math.cos(a), y + d * math.sin(a)))
    return out


def empty_footprint_zone(obj_id, color):
    """Schema dict for the visible object outline (no fill)."""
    return {
        "name": footprint_name(obj_id),
        "type": "polygon",
        "geometry": [],
        "style": {
            "color": color,
            "thickness": 2,
            "fill_alpha": 0,
            "dashed": False,
        },
        "editable": False,  # rebuilt from state, not edited directly
    }


def empty_zone(obj_id, color):
    """Schema dict for the interaction zone (filled when nose inside).

    Dashed outline so the user can visually tell the interaction zone
    from the object footprint outline.
    """
    return {
        "name": zone_name(obj_id),
        "type": "polygon",
        "geometry": [],
        "style": {
            "color": color,
            "thickness": 1,
            "fill_alpha": 0,        # painted live by nor_overlay
            "dashed": True,
        },
        "editable": False,
    }


def custom_edit_zone(obj_id, color, n_corners):
    """Editor placeholder used by the freehand custom shape — the user
    clicks `n_corners` points on the preview and they get stored as
    `state["custom_geom_norm"]`. The shape itself is rebuilt by
    `build_footprint_norm` from that geometry."""
    return {
        "name": footprint_name(obj_id),
        "type": "polygon",
        "geometry": [],
        "style": {
            "color": color,
            "thickness": 2,
            "fill_alpha": 0,
            "dashed": False,
        },
        "editable": True,
        "editor_hint": {"n_corners": int(n_corners)},
    }


def build_schema(host):
    """Return the full zone schema (footprint + interaction zone) for both
    objects, given host state. Used by NORExperiment.zones_schema."""
    schema = []
    states = getattr(host, "_nor_objects", None) or {}
    px_per_cm = _resolve_px_per_cm(host)
    video_size = (getattr(host, "video_w", None) or 0,
                  getattr(host, "video_h", None) or 0)
    for obj_id in OBJECT_NAMES:
        st = states.get(obj_id) or default_object_state(obj_id)
        color = st.get("color", OBJECT_COLORS[obj_id])
        footprint = build_footprint_norm(st, px_per_cm, video_size)
        zone = build_zone_norm(footprint, st, px_per_cm, video_size)
        fz = empty_footprint_zone(obj_id, color)
        fz["geometry"] = footprint
        zz = empty_zone(obj_id, color)
        zz["geometry"] = zone
        schema.append(fz)
        schema.append(zz)
    return schema


def _resolve_px_per_cm(host):
    """Best-effort px/cm read from the host. Tries manual calibration
    line first; falls back to square-cage auto-cal computed directly
    from arena + cage_w_cm. Returns None if neither path resolves.

    Critically does NOT call host.snapshot_settings() — that path goes
    through contribute_to_snapshot which rebuilds zone geometry, so
    calling it from inside a drag handler triggers a recompute storm.
    """
    zd = getattr(host, "zone_drawer", None)
    if zd is None:
        return None
    # Manual calibration line.
    if getattr(zd, "calib_p1", None) and getattr(zd, "calib_p2", None):
        try:
            spin = getattr(host, "spin_cm", None)
            if spin is not None:
                return zd.get_pixels_per_cm(spin.value())
        except Exception:
            pass
    # Square-cage auto-cal: average pixel side length / cm side length.
    arena_norm = getattr(zd, "arena", None)
    if not arena_norm or len(arena_norm) < 4:
        return None
    vw = getattr(host, "video_w", None) or 0
    vh = getattr(host, "video_h", None) or 0
    if not vw or not vh:
        return None
    spin_w = getattr(host, "spin_cage_w", None)
    if spin_w is None:
        return None
    side_cm = float(spin_w.value() or 0)
    if side_cm <= 0:
        return None
    pts_px = [(x * vw, y * vh) for (x, y) in arena_norm]
    TL = min(pts_px, key=lambda p: p[0] + p[1])
    BR = max(pts_px, key=lambda p: p[0] + p[1])
    TR = max(pts_px, key=lambda p: p[0] - p[1])
    BL = min(pts_px, key=lambda p: p[0] - p[1])
    width_px  = (math.hypot(TR[0] - TL[0], TR[1] - TL[1])
                 + math.hypot(BR[0] - BL[0], BR[1] - BL[1])) / 2.0
    height_px = (math.hypot(BL[0] - TL[0], BL[1] - TL[1])
                 + math.hypot(BR[0] - TR[0], BR[1] - TR[1])) / 2.0
    return ((width_px + height_px) / 2.0) / side_cm
