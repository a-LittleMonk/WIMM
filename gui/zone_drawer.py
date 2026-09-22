import cv2
import numpy as np
from PyQt5.QtWidgets import QLabel
from PyQt5.QtCore import Qt, pyqtSignal, QPoint
from PyQt5.QtGui import QPainter, QPen, QColor, QPixmap, QImage, QFont, QPainterPath, QBrush


def ndarray_to_pixmap(arr: np.ndarray) -> QPixmap:
    rgb = arr[:, :, ::-1].copy()
    h, w, ch = rgb.shape
    img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
    return QPixmap.fromImage(img)


# ── Zone schema spec ─────────────────────────────────────────────────────
# A zone is a dict:
#   name: unique str id ("arena", "arm_a", ...)
#   type: "polygon" | "circle" | "line" | "paint"
#   geometry: depends on type:
#     polygon: list of (x, y) normalized 0..1
#     circle:  (cx, cy, r)  — cx/cy normalized, r normalized to width
#     line:    ((x1, y1), (x2, y2))
#     paint:   numpy mask (H×W uint8) — same size as frame
#   style: dict — color (hex), thickness (int), fill_alpha (0..255),
#                  label_text (str), dashed (bool)
#   editable: bool
#   editor_hint: dict — type-specific (polygon: n_corners=4)
DEFAULT_STYLE = {
    "color": "#3CA0FF",
    "thickness": 2,
    "fill_alpha": 0,
    "label_text": "",
    "dashed": False,
}


class ZoneDrawer(QLabel):
    zones_changed     = pyqtSignal()
    # Fires on every mouseMoveEvent while a polygon vertex is being
    # dragged — for handlers that need to redraw dependent geometry live
    # (e.g. Y-Maze arms following the hub/endpoint drag). Distinct from
    # zones_changed so the heavyweight handlers (autosave, logger) only
    # fire on drag release.
    zones_changing    = pyqtSignal()
    exclusion_changed = pyqtSignal()
    point_clicked     = pyqtSignal(float, float)   # norm x, norm y — correction mode

    MODE_IDLE    = None
    MODE_CALIB   = "calibration"
    MODE_ARENA   = "arena"
    MODE_EXCLUDE = "exclude"
    MODE_CORRECT = "correct"
    MODE_POLY    = "poly"     # generic polygon-edit (extra zone)

    # Magnifier loupe — shown while the user is placing or dragging zone
    # points so corners can be hit accurately on detailed video frames.
    LOUPE_D = 140              # diameter in widget px
    LOUPE_ZOOM = 4             # source pixels are LOUPE_D / LOUPE_ZOOM wide

    # Most recent reason for zones_changed — readable by handlers.
    _last_change_reason = "unspecified"

    def emit_change(self, reason: str = "unspecified") -> None:
        """Set a human-readable reason then emit zones_changed."""
        self._last_change_reason = reason or "unspecified"
        self.zones_changed.emit()

    def __init__(self):
        super().__init__()
        # Small minimum so the widget can shrink with the splitter pane.
        # The pixmap is scaled to fit in paintEvent (KeepAspectRatio), so
        # the actual frame always fills whatever space the widget gets.
        self.setMinimumSize(160, 120)
        from PyQt5.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: #1e1e1e; border: 1px solid #555;")
        self.setText("Load a video to begin")
        self.setFont(QFont("Arial", 13))
        self.setMouseTracking(True)

        self.mode      = self.MODE_IDLE
        self._base_pixmap = None
        self._video_w  = 1
        self._video_h  = 1

        # calibration (drag-based)
        self.calib_p1  = None
        self.calib_p2  = None
        self._drag_start = None
        self._drag_end   = None

        # arena
        self.arena  = None
        self.center_zone = None
        self.zone_mode = "center_zone"   # "center_zone" | "grid"
        # Experiment-specific overlay renderers — set by the OF plugin so
        # the 4x4 grid + cell numbers / timers / entries live in OF code,
        # not in the shared base. Non-OF experiments leave them unset.
        self._overlay_renderer = None    # (painter, ox, oy, dw, dh) → None
        self._grid_renderer = None       # (painter, ox, oy, dw, dh) → None
        self._colors = {"arena": "#3CA0FF", "center_zone": "#3CDC64", "grid": "#96C8FF"}
        self._arena_clicks = []
        self._mouse_pos    = None
        self._dragging_corner = None   # index into self.arena being dragged
        self._corner_grab_px  = 12     # widget-pixel radius for grabbing a handle
        # Norm position of the handle when a drag began. Used to constrain the
        # drag to horizontal / vertical / 45° lines while Shift is held.
        self._drag_anchor_norm = None
        self._perspective_locked = False   # disables corner editing when perspective on

        # exclusion brush
        self.brush_radius  = 20          # video pixels
        self.exclusion_mask = None       # np.uint8 array, video-sized
        self._excl_cache    = None       # cached QImage of the mask overlay

        # ── Cell highlight (green fill where the mouse is right now) ──
        self._cell_highlight_pos = None        # normalized (x, y) or None
        self._cell_highlight_color = "#3CDC64" # default green
        self._cell_highlight_alpha = 100       # 0..255
        self._cell_show_numbers = True
        self._cell_show_timer = True
        self._cell_show_entries = True
        # Y-Maze arm overlay show flags (parallel set for arm/neutral labels,
        # per-arm timer text, per-arm entry-count text in paint_ym_overlay).
        self._arm_show_numbers = True
        self._arm_show_timer = True
        self._arm_show_entries = True
        # Per-cell cumulative time. Keys: 1..16 for grid, "C" for center mode.
        self._cell_times = {}
        # Per-cell cumulative entry counts.
        self._cell_entries = {}

        # ── Schema-driven extra zones (plugins push into these) ──
        # Original OF zones (arena/center/grid/calib/excl) keep their own
        # state above; this list is for plugin-added zones (Y-Maze arms,
        # circle objects, etc.).
        self._extra_zones = []           # list of zone dicts
        self._editing_zone = None        # name of zone in MODE_POLY
        self._poly_clicks = []           # in-progress clicks for polygon edit
        self._poly_n_corners = 4         # how many corners to collect
        self._dragging_extra = None      # (zone_name, vertex_idx) when dragging
        # Set to zone_name while the user is dragging that zone's label.
        # Updates style.label_pos_override; paint reads override first and
        # falls back to auto-positioned style.label_pos.
        self._dragging_label = None

    # ── public API ────────────────────────────────────────────────────────

    def set_frame(self, frame: np.ndarray):
        self._video_h, self._video_w = frame.shape[:2]
        self._base_pixmap = ndarray_to_pixmap(frame)
        self.setText("")
        # Init exclusion mask if missing or wrong size
        if (self.exclusion_mask is None or
                self.exclusion_mask.shape != (self._video_h, self._video_w)):
            self.exclusion_mask = np.zeros((self._video_h, self._video_w), dtype=np.uint8)
            self._excl_cache = None
        self.update()

    def set_mode(self, mode):
        self.mode = mode
        self._drag_start   = None
        self._drag_end     = None
        self._arena_clicks = []
        self._mouse_pos    = None
        if mode in (self.MODE_CALIB, self.MODE_ARENA,
                    self.MODE_EXCLUDE, self.MODE_CORRECT):
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        self.update()

    def set_overlay_renderer(self, fn):
        """Register the function called from paintEvent to draw experiment-
        specific overlays on top of the base scene (cell highlight + cell
        numbers/timers/entries in OF). Pass None to disable."""
        self._overlay_renderer = fn
        self.update()

    def set_grid_renderer(self, fn):
        """Register the function called from paintEvent to draw experiment-
        specific overlays ON TOP of the arena polygon (the OF 4x4 grid
        lines). Pass None to disable."""
        self._grid_renderer = fn
        self.update()

    def set_zone_mode(self, mode):
        # Legacy "center" coerced to "center_zone" for old saved configs.
        if mode == "center":
            mode = "center_zone"
        self.zone_mode = mode if mode in ("center_zone", "grid") else "center_zone"
        self.update()

    # Legacy alias — older code paths may still touch .center. Mirrors
    # .center_zone so loaded JSON / older callers keep working.
    @property
    def center(self):
        return self.center_zone

    @center.setter
    def center(self, value):
        self.center_zone = value

    @staticmethod
    def _snap_to_rectangle(pts):
        """Fit a rotated rectangle to the 4 user clicks. Returns 4 corners (normalized)."""
        arr = np.array(pts, dtype=np.float32)
        rect = cv2.minAreaRect(arr)            # ((cx, cy), (w, h), angle)
        box = cv2.boxPoints(rect)               # 4 corners (float32)
        return [(float(p[0]), float(p[1])) for p in box]

    def set_perspective_locked(self, locked: bool):
        self._perspective_locked = bool(locked)
        self.update()

    def set_zone_colors(self, colors: dict):
        # Legacy: incoming dict may use "center"; upgrade to "center_zone".
        if "center" in colors and "center_zone" not in colors:
            colors = {**colors, "center_zone": colors["center"]}
        for k in ("arena", "center_zone", "grid"):
            if k in colors:
                self._colors[k] = colors[k]
        self.update()

    @staticmethod
    def _sorted_corners(pts):
        """Returns (TL, TR, BR, BL) for screen coords (y-down)."""
        TL = min(pts, key=lambda p: p[0] + p[1])
        BR = max(pts, key=lambda p: p[0] + p[1])
        TR = max(pts, key=lambda p: p[0] - p[1])
        BL = min(pts, key=lambda p: p[0] - p[1])
        return TL, TR, BR, BL

    def get_arena_pixels(self):
        if not self.arena:
            return None
        return [(int(x * self._video_w), int(y * self._video_h)) for x, y in self.arena]

    def get_center_pixels(self):
        if not self.center_zone:
            return None
        return [(int(x * self._video_w), int(y * self._video_h)) for x, y in self.center_zone]

    def get_pixels_per_cm(self, real_cm: float):
        if not (self.calib_p1 and self.calib_p2) or real_cm <= 0:
            return None
        x1 = self.calib_p1[0] * self._video_w
        y1 = self.calib_p1[1] * self._video_h
        x2 = self.calib_p2[0] * self._video_w
        y2 = self.calib_p2[1] * self._video_h
        return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 / real_cm

    def get_exclusion_mask(self):
        return self.exclusion_mask

    # ── Cell highlight API ───────────────────────────────────────────────
    def set_body_pos_norm(self, xy):
        """Update where the body currently is (normalized 0..1 coords).
        Pass None to clear the highlight."""
        self._cell_highlight_pos = xy
        self.update()

    def set_cell_highlight_color(self, hex_color: str):
        self._cell_highlight_color = hex_color
        self.update()

    def set_cell_highlight_alpha(self, alpha: int):
        self._cell_highlight_alpha = max(0, min(255, int(alpha)))
        self.update()

    def set_cell_show_numbers(self, on: bool):
        self._cell_show_numbers = bool(on)
        self.update()

    def set_cell_show_timer(self, on: bool):
        self._cell_show_timer = bool(on)
        self.update()

    def set_cell_show_entries(self, on: bool):
        self._cell_show_entries = bool(on)
        self.update()

    def set_arm_show_numbers(self, on: bool):
        self._arm_show_numbers = bool(on)
        self.update()

    def set_arm_show_timer(self, on: bool):
        self._arm_show_timer = bool(on)
        self.update()

    def set_arm_show_entries(self, on: bool):
        self._arm_show_entries = bool(on)
        self.update()

    def set_cell_times(self, times: dict):
        """Pass a dict of cell_id → seconds (cumulative)."""
        self._cell_times = dict(times or {})
        self.update()

    def set_cell_entries(self, entries: dict):
        """Pass a dict of cell_id → entry count (cumulative)."""
        self._cell_entries = dict(entries or {})
        self.update()

    def reset_cell_times(self):
        self._cell_times = {}
        self._cell_entries = {}
        self.update()

    def _grid_cell_corners(self, ox, oy, dw, dh, row, col):
        """Return display-pixel corners (TL, TR, BR, BL) of grid cell at
        (row, col) ∈ [0..3]^2. Uses the arena's 4 corners with bilinear
        interpolation."""
        if not self.arena:
            return None
        corners = [self._norm_to_disp(p, ox, oy, dw, dh) for p in self.arena]
        TL, TR, BR, BL = self._sorted_corners(corners)
        def bilin(u, v):
            top    = (TL[0] + (TR[0] - TL[0]) * u, TL[1] + (TR[1] - TL[1]) * u)
            bot    = (BL[0] + (BR[0] - BL[0]) * u, BL[1] + (BR[1] - BL[1]) * u)
            return (top[0] + (bot[0] - top[0]) * v, top[1] + (bot[1] - top[1]) * v)
        u0, u1 = col / 4.0, (col + 1) / 4.0
        v0, v1 = row / 4.0, (row + 1) / 4.0
        return [bilin(u0, v0), bilin(u1, v0), bilin(u1, v1), bilin(u0, v1)]

    def _body_uv_in_arena(self):
        """Return (u, v) in [0,1]^2 — the body's bilinear coords inside the
        arena quad. None if no arena or no body or outside the arena."""
        if not self.arena or self._cell_highlight_pos is None:
            return None
        # Map arena quad → unit square via cv2 perspective transform.
        try:
            arena_pts = np.array([
                (p[0] * self._video_w, p[1] * self._video_h) for p in
                self._sorted_corners(self.arena)
            ], dtype=np.float32)
            unit_pts = np.array([(0, 0), (1, 0), (1, 1), (0, 1)], dtype=np.float32)
            M = cv2.getPerspectiveTransform(arena_pts, unit_pts)
            bx_norm, by_norm = self._cell_highlight_pos
            pt = np.array([[[bx_norm * self._video_w, by_norm * self._video_h]]],
                          dtype=np.float32)
            uv = cv2.perspectiveTransform(pt, M)[0][0]
            u, v = float(uv[0]), float(uv[1])
            if 0.0 <= u <= 1.0 and 0.0 <= v <= 1.0:
                return u, v
        except Exception:
            pass
        return None

    def _current_cell_id(self):
        """Returns the active cell id ('1'..'16' for grid, 'C' for center
        mode if inside center polygon, else None)."""
        uv = self._body_uv_in_arena()
        if uv is None:
            return None
        u, v = uv
        if self.zone_mode == "grid":
            col = max(0, min(3, int(u * 4)))
            row = max(0, min(3, int(v * 4)))
            return str(row * 4 + col + 1)  # 1..16, top-left → bottom-right
        # center_zone mode — check if inside center polygon
        if self.center_zone:
            try:
                poly = np.array([
                    (p[0] * self._video_w, p[1] * self._video_h) for p in self.center_zone
                ], dtype=np.float32)
                pt = (self._cell_highlight_pos[0] * self._video_w,
                      self._cell_highlight_pos[1] * self._video_h)
                if cv2.pointPolygonTest(poly, pt, False) >= 0:
                    return "C"
            except Exception:
                pass
        return None

    def clear_calibration(self):
        self.calib_p1 = None
        self.calib_p2 = None
        self.update()

    def clear_arena(self):
        self.arena  = None
        self.center_zone = None
        self.update()

    def clear_exclusions(self):
        if self.exclusion_mask is not None:
            self.exclusion_mask[:] = 0
        self._excl_cache = None
        self.update()

    # ── Schema-driven zone API (plugin-friendly) ─────────────────────────

    def set_zone_schema(self, schema_list):
        """Replace all extra zones with the given list of zone dicts.
        OF-native zones (arena/center/grid/calib/excl) are untouched."""
        self._extra_zones = []
        for z in (schema_list or []):
            self.add_zone(z)
        self.update()
        self.emit_change("schema replaced")

    def add_zone(self, zone):
        """Add or replace a zone (matched by name). Style fields fill in
        from defaults."""
        if not isinstance(zone, dict) or "name" not in zone:
            return
        z = dict(zone)
        style = dict(DEFAULT_STYLE)
        style.update(z.get("style", {}) or {})
        z["style"] = style
        z.setdefault("type", "polygon")
        z.setdefault("editable", True)
        z.setdefault("editor_hint", {})
        # Replace any existing zone with the same name.
        self._extra_zones = [zz for zz in self._extra_zones if zz.get("name") != z["name"]]
        self._extra_zones.append(z)
        self.update()

    def remove_zone(self, name):
        before = len(self._extra_zones)
        self._extra_zones = [z for z in self._extra_zones if z.get("name") != name]
        if len(self._extra_zones) != before:
            self.update()

    def clear_extra_zones(self):
        if self._extra_zones:
            self._extra_zones = []
            self.update()

    def get_zone(self, name):
        for z in self._extra_zones:
            if z.get("name") == name:
                return z
        return None

    def list_zones(self):
        return list(self._extra_zones)

    def start_edit(self, zone_name, n_corners=4):
        """Enter polygon-edit mode for a named extra zone. The user clicks
        n_corners points; the geometry is committed when done."""
        z = self.get_zone(zone_name)
        if z is None:
            # Auto-create empty polygon zone.
            z = {"name": zone_name, "type": "polygon", "geometry": [],
                 "style": dict(DEFAULT_STYLE), "editable": True}
            self.add_zone(z)
        self._editing_zone = zone_name
        self._poly_n_corners = max(3, int(n_corners))
        self._poly_clicks = []
        self.mode = self.MODE_POLY
        self.setCursor(Qt.CrossCursor)
        self.update()

    def stop_edit(self):
        self._editing_zone = None
        self._poly_clicks = []
        if self.mode == self.MODE_POLY:
            self.set_mode(self.MODE_IDLE)

    # ── mouse ─────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if self._base_pixmap is None:
            return
        # Idle-mode corner drag (when no tool is active and arena exists)
        if (self.mode == self.MODE_IDLE and self.arena and
                event.button() == Qt.LeftButton and not self._perspective_locked):
            ox, oy, dw, dh = self._get_disp_rect()
            r2 = self._corner_grab_px * self._corner_grab_px
            for i, p in enumerate(self.arena):
                hx, hy = self._norm_to_disp(p, ox, oy, dw, dh)
                if (event.pos().x() - hx) ** 2 + (event.pos().y() - hy) ** 2 <= r2:
                    self._dragging_corner = i
                    self._drag_anchor_norm = tuple(p)
                    return
        # Idle-mode label drag (extra polygon zones with a paint-stamped
        # _label_rect). Checked BEFORE corner drag so a label sitting near
        # a vertex still grabs the label cleanly.
        if (self.mode == self.MODE_IDLE and self._extra_zones and
                event.button() == Qt.LeftButton):
            px, py = event.pos().x(), event.pos().y()
            for z in self._extra_zones:
                style = z.get("style") or {}
                rect = style.get("_label_rect")
                if rect and len(rect) == 4:
                    rx, ry, rw, rh = rect
                    if rx <= px <= rx + rw and ry <= py <= ry + rh:
                        self._dragging_label = z["name"]
                        return
        # Idle-mode corner drag for extra polygon zones.
        if (self.mode == self.MODE_IDLE and self._extra_zones and
                event.button() == Qt.LeftButton):
            ox, oy, dw, dh = self._get_disp_rect()
            r2 = self._corner_grab_px * self._corner_grab_px
            for z in self._extra_zones:
                if z.get("type") != "polygon" or not z.get("editable", True):
                    continue
                geom = z.get("geometry") or []
                for i, p in enumerate(geom):
                    hx, hy = self._norm_to_disp(p, ox, oy, dw, dh)
                    if (event.pos().x() - hx) ** 2 + (event.pos().y() - hy) ** 2 <= r2:
                        self._dragging_extra = (z["name"], i)
                        self._drag_anchor_norm = tuple(p)
                        return
        # Polygon-edit click collection (extra zone)
        if self.mode == self.MODE_POLY and self._editing_zone:
            pt = self._widget_to_norm(event.pos())
            self._poly_clicks.append(pt)
            if len(self._poly_clicks) >= self._poly_n_corners:
                z = self.get_zone(self._editing_zone)
                if z is not None:
                    z["geometry"] = list(self._poly_clicks)
                self._poly_clicks = []
                self._editing_zone = None
                self.set_mode(self.MODE_IDLE)
                self.emit_change("extra polygon drawn (manual)")
            else:
                self.update()
            return
        if self.mode == self.MODE_ARENA:
            pt = self._widget_to_norm(event.pos())
            self._arena_clicks.append(pt)
            if len(self._arena_clicks) == 4:
                self.arena = list(self._arena_clicks)
                self._arena_clicks = []
                self._mouse_pos = None
                self.set_mode(self.MODE_IDLE)
                self.emit_change("arena drawn (manual, 4-click)")
            else:
                self.update()
        elif self.mode == self.MODE_CALIB:
            self._drag_start = event.pos()
            self._drag_end   = event.pos()
        elif self.mode == self.MODE_EXCLUDE:
            erase = event.button() == Qt.RightButton
            self._paint_exclusion(self._widget_to_norm(event.pos()), erase=erase)
        elif self.mode == self.MODE_CORRECT:
            norm = self._widget_to_norm(event.pos())
            self.point_clicked.emit(norm[0], norm[1])

    def _drag_norm(self, event):
        """Norm point for the active handle drag. While Shift is held, snap
        the motion to the nearest horizontal / vertical / 45° line through the
        handle's start position. Snapping is computed in widget pixels so the
        angles look right on screen regardless of the frame's aspect ratio."""
        if (event.modifiers() & Qt.ShiftModifier) and self._drag_anchor_norm is not None:
            import math
            ox, oy, dw, dh = self._get_disp_rect()
            ax, ay = self._norm_to_disp(self._drag_anchor_norm, ox, oy, dw, dh)
            dx, dy = event.pos().x() - ax, event.pos().y() - ay
            if dx or dy:
                step = math.pi / 4  # 45° increments → H, V, and diagonals
                snapped = round(math.atan2(dy, dx) / step) * step
                ux, uy = math.cos(snapped), math.sin(snapped)
                proj = dx * ux + dy * uy   # project cursor onto the snapped axis
                return self._widget_to_norm(
                    QPoint(int(round(ax + proj * ux)), int(round(ay + proj * uy)))
                )
        return self._widget_to_norm(event.pos())

    def mouseMoveEvent(self, event):
        self._mouse_pos = event.pos()
        if self._dragging_corner is not None:
            arena_list = list(self.arena)
            arena_list[self._dragging_corner] = self._drag_norm(event)
            self.arena = arena_list
            self.update()
            return
        if self._dragging_extra is not None:
            zname, vidx = self._dragging_extra
            z = self.get_zone(zname)
            if z is not None:
                geom = list(z.get("geometry") or [])
                if 0 <= vidx < len(geom):
                    geom[vidx] = self._drag_norm(event)
                    z["geometry"] = geom
                    self.update()
                    # Lightweight signal so dependent geometry (Y-Maze arms
                    # tied to the y_template handles) rebuilds live during
                    # the drag. Heavyweight handlers (autosave / logger)
                    # stay on zones_changed which fires on release.
                    self.zones_changing.emit()
            return
        if self._dragging_label is not None:
            z = self.get_zone(self._dragging_label)
            if z is not None:
                z["style"]["label_pos_override"] = self._widget_to_norm(event.pos())
                self.update()
            return
        # Cursor hint: show pointing-hand near a corner in idle mode
        if self.mode == self.MODE_IDLE and self.arena:
            ox, oy, dw, dh = self._get_disp_rect()
            r2 = self._corner_grab_px * self._corner_grab_px
            near = any(
                (event.pos().x() - hx) ** 2 + (event.pos().y() - hy) ** 2 <= r2
                for hx, hy in (self._norm_to_disp(p, ox, oy, dw, dh) for p in self.arena)
            )
            self.setCursor(Qt.PointingHandCursor if near else Qt.ArrowCursor)
        if self.mode == self.MODE_ARENA:
            self.update()
        elif self.mode == self.MODE_CALIB and self._drag_start:
            self._drag_end = event.pos()
            self.update()
        elif self.mode == self.MODE_EXCLUDE:
            self.update()   # repaint brush preview
            if event.buttons() & Qt.LeftButton:
                self._paint_exclusion(self._widget_to_norm(event.pos()), erase=False)
            elif event.buttons() & Qt.RightButton:
                self._paint_exclusion(self._widget_to_norm(event.pos()), erase=True)
        elif self.mode == self.MODE_CORRECT:
            self.update()
        elif self.mode == self.MODE_POLY:
            # Repaint so the rubber-band line + magnifier follow the cursor
            # during polygon-corner placement.
            self.update()

    def mouseReleaseEvent(self, event):
        if self._dragging_corner is not None:
            self._dragging_corner = None
            self._drag_anchor_norm = None
            self.emit_change("arena corner dragged")
            self.update()
            return
        if self._dragging_extra is not None:
            self._dragging_extra = None
            self._drag_anchor_norm = None
            self.emit_change("extra zone vertex dragged")
            self.update()
            return
        if self._dragging_label is not None:
            self._dragging_label = None
            self.emit_change("zone label moved")
            self.update()
            return
        if self.mode == self.MODE_CALIB and self._drag_start:
            self._drag_end = event.pos()
            self.calib_p1 = self._widget_to_norm(self._drag_start)
            self.calib_p2 = self._widget_to_norm(self._drag_end)
            self._drag_start = None
            self._drag_end   = None
            self.set_mode(self.MODE_IDLE)
            self.emit_change("calibration line drawn (manual)")

    # ── painting ──────────────────────────────────────────────────────────

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._base_pixmap is None:
            return

        ox, oy, dw, dh = self._get_disp_rect()
        painter = QPainter(self)
        scaled = self._base_pixmap.scaled(dw, dh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter.drawPixmap(ox, oy, scaled)

        # Exclusion mask overlay (semi-transparent red)
        if self.exclusion_mask is not None and self.exclusion_mask.any():
            if self._excl_cache is None:
                h, w = self.exclusion_mask.shape
                rgba = np.zeros((h, w, 4), dtype=np.uint8)
                rgba[self.exclusion_mask > 0] = [60, 60, 220, 110]
                self._excl_cache = QImage(
                    rgba.tobytes(), w, h, 4 * w, QImage.Format_RGBA8888
                ).copy()
            exc_scaled = self._excl_cache.scaled(
                dw, dh, Qt.IgnoreAspectRatio, Qt.FastTransformation
            )
            painter.drawImage(ox, oy, exc_scaled)

        # ── Experiment-specific overlays (cell highlight, cell numbers /
        # timers / entries, center HUD). OF registers a renderer via
        # set_overlay_renderer in OpenFieldTab.__init__; non-OF experiments
        # leave it unset and get none of this drawn.
        if self._overlay_renderer is not None:
            try:
                self._overlay_renderer(painter, ox, oy, dw, dh)
            except Exception:
                pass

        # ── Extra schema-driven zones (plugins) ──
        if self._extra_zones:
            for z in self._extra_zones:
                self._paint_extra_zone(painter, z, ox, oy, dw, dh)

        # Calibration line
        if self.calib_p1 and self.calib_p2:
            painter.setPen(QPen(QColor(255, 200, 0), 2))
            painter.setBrush(QColor(255, 200, 0))
            dp1 = self._norm_to_disp(self.calib_p1, ox, oy, dw, dh)
            dp2 = self._norm_to_disp(self.calib_p2, ox, oy, dw, dh)
            painter.drawLine(*dp1, *dp2)
            painter.drawEllipse(dp1[0] - 4, dp1[1] - 4, 8, 8)
            painter.drawEllipse(dp2[0] - 4, dp2[1] - 4, 8, 8)

        # Completed arena polygon
        if self.arena:
            arena_color = QColor(self._colors["arena"])
            pts = [self._norm_to_disp(p, ox, oy, dw, dh) for p in self.arena]
            painter.setPen(QPen(arena_color, 2))
            painter.setBrush(Qt.NoBrush)
            self._draw_polygon(painter, pts)
            painter.setFont(QFont("Arial", 9, QFont.Bold))
            painter.setPen(arena_color)
            painter.drawText(pts[0][0] + 4, pts[0][1] - 6, "Arena")
            # Editable handles in idle mode
            if self.mode == self.MODE_IDLE and not self._perspective_locked:
                painter.setPen(QPen(arena_color, 2))
                painter.setBrush(QColor(255, 255, 255))
                for i, (hx, hy) in enumerate(pts):
                    if self._dragging_corner == i:
                        painter.setBrush(arena_color)
                    else:
                        painter.setBrush(QColor(255, 255, 255))
                    painter.drawEllipse(hx - 5, hy - 5, 10, 10)

        # ── Grid lines hook (drawn on top of the arena outline). OF binds
        # paint_of_grid_lines here; other experiments leave it unset.
        if self._grid_renderer is not None:
            try:
                self._grid_renderer(painter, ox, oy, dw, dh)
            except Exception:
                pass

        # Center zone polygon
        if self.center_zone:
            center_color = QColor(self._colors["center_zone"])
            pts = [self._norm_to_disp(p, ox, oy, dw, dh) for p in self.center_zone]
            painter.setPen(QPen(center_color, 2))
            painter.setBrush(Qt.NoBrush)
            self._draw_polygon(painter, pts)
            painter.setFont(QFont("Arial", 9, QFont.Bold))
            painter.setPen(center_color)
            painter.drawText(pts[0][0] + 4, pts[0][1] - 6, "Center")

        # Arena corner preview
        if self.mode == self.MODE_ARENA and self._arena_clicks:
            n   = len(self._arena_clicks)
            col = QColor(self._colors["arena"])
            pts = [self._norm_to_disp(p, ox, oy, dw, dh) for p in self._arena_clicks]
            painter.setPen(QPen(col, 2))
            painter.setBrush(col)
            for px, py in pts:
                painter.drawEllipse(px - 4, py - 4, 8, 8)
            for i in range(n - 1):
                painter.drawLine(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
            if self._mouse_pos:
                mx, my = self._mouse_pos.x(), self._mouse_pos.y()
                painter.setPen(QPen(col, 2, Qt.DashLine))
                painter.setBrush(Qt.NoBrush)
                # Always draw the rubber-band line from the last click to
                # the cursor — and, once there are ≥2 clicks, also a closing
                # line from the cursor back to the first click. So:
                #   1 click  → 1 dot + 1 dashed line
                #   2 clicks → triangle (2 solid + 2 dashed sides)
                #   3 clicks → quad (3 solid + 2 dashed sides)
                painter.drawLine(pts[-1][0], pts[-1][1], mx, my)
                if n >= 2:
                    painter.drawLine(mx, my, pts[0][0], pts[0][1])

        # Calibration rubber band
        if self.mode == self.MODE_CALIB and self._drag_start and self._drag_end:
            painter.setPen(QPen(QColor(255, 200, 0), 2, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(
                self._drag_start.x(), self._drag_start.y(),
                self._drag_end.x(),   self._drag_end.y()
            )

        # Exclusion brush cursor preview
        if self.mode == self.MODE_EXCLUDE and self._mouse_pos:
            r_disp = max(2, int(self.brush_radius * dw / max(self._video_w, 1)))
            mx, my = self._mouse_pos.x(), self._mouse_pos.y()
            painter.setPen(QPen(QColor(220, 60, 60, 200), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(mx - r_disp, my - r_disp, r_disp * 2, r_disp * 2)

        # Correction mode crosshair
        if self.mode == self.MODE_CORRECT and self._mouse_pos:
            mx, my = self._mouse_pos.x(), self._mouse_pos.y()
            painter.setPen(QPen(QColor(0, 255, 200, 200), 1, Qt.DashLine))
            painter.drawLine(mx - 12, my, mx + 12, my)
            painter.drawLine(mx, my - 12, mx, my + 12)

        # Polygon-edit (extra zone) live preview
        if self.mode == self.MODE_POLY and self._poly_clicks:
            col = QColor("#FFB74D")
            pts = [self._norm_to_disp(p, ox, oy, dw, dh) for p in self._poly_clicks]
            painter.setPen(QPen(col, 2))
            painter.setBrush(col)
            for px, py in pts:
                painter.drawEllipse(px - 4, py - 4, 8, 8)
            for i in range(len(pts) - 1):
                painter.drawLine(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
            if self._mouse_pos:
                mx, my = self._mouse_pos.x(), self._mouse_pos.y()
                painter.setPen(QPen(col, 2, Qt.DashLine))
                painter.setBrush(Qt.NoBrush)
                painter.drawLine(pts[-1][0], pts[-1][1], mx, my)
                if len(pts) >= 2:
                    painter.drawLine(mx, my, pts[0][0], pts[0][1])

        # Instruction overlay
        n_clicks = len(self._arena_clicks)
        n_poly_clicks = len(self._poly_clicks)
        poly_msg = None
        if self.mode == self.MODE_POLY and self._editing_zone:
            poly_msg = (f"Define '{self._editing_zone}' — corner "
                        f"{n_poly_clicks + 1} of {self._poly_n_corners}")
        instructions = {
            self.MODE_CALIB:      "Click and drag to draw the calibration line",
            self.MODE_ARENA:      f"Click corner {n_clicks + 1} of 4",
            self.MODE_EXCLUDE:    "Paint to mark exclusion areas  |  right-click: erase",
            self.MODE_CORRECT:    "Click to set correct mouse position for this frame",
            self.MODE_POLY:       poly_msg,
        }
        msg = instructions.get(self.mode)
        if msg:
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Arial", 10))
            painter.drawText(ox + 6, oy + dh - 8, msg)

        # Magnifier loupe — only drawn while the user is placing/dragging
        # zone points so corners can be hit precisely.
        self._paint_loupe(painter, ox, oy, dw, dh)

        painter.end()

    def _should_show_loupe(self) -> bool:
        """True when the user is actively placing or dragging zone points."""
        if self._base_pixmap is None or self._mouse_pos is None:
            return False
        if self.mode in (self.MODE_CALIB, self.MODE_ARENA,
                          self.MODE_POLY, self.MODE_CORRECT):
            return True
        if (self._dragging_corner is not None
                or self._dragging_extra is not None):
            return True
        return False

    def _paint_loupe(self, painter, ox, oy, dw, dh):
        if not self._should_show_loupe():
            return
        # Restrict the loupe to mouse positions inside the displayed frame
        # rect — outside the image there's nothing useful to magnify.
        mx, my = self._mouse_pos.x(), self._mouse_pos.y()
        if not (ox <= mx <= ox + dw and oy <= my <= oy + dh):
            return
        # Mouse → video pixel.
        nx = (mx - ox) / max(1, dw)
        ny = (my - oy) / max(1, dh)
        src_fx = nx * self._video_w
        src_fy = ny * self._video_h
        d = self.LOUPE_D
        src_size = max(2, d // self.LOUPE_ZOOM)
        # Default position: above-right of cursor. Flip / clamp to stay
        # inside the widget.
        offset = 28
        lx = mx + offset
        ly = my - offset - d
        if lx + d > self.width() - 6:
            lx = mx - offset - d
        if ly < 6:
            ly = my + offset
        lx = max(6, min(self.width() - d - 6, lx))
        ly = max(6, min(self.height() - d - 6, ly))
        from PyQt5.QtCore import QRect
        src_rect = QRect(int(src_fx - src_size / 2),
                          int(src_fy - src_size / 2),
                          int(src_size), int(src_size))
        dst_rect = QRect(int(lx), int(ly), d, d)
        # Circular clip + zoomed source.
        path = QPainterPath()
        path.addEllipse(int(lx), int(ly), d, d)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(int(lx), int(ly), d, d, QColor(0, 0, 0))
        try:
            painter.drawPixmap(dst_rect, self._base_pixmap, src_rect)
        except Exception:
            pass
        painter.restore()
        # Ring border + crosshair + center dot.
        painter.setPen(QPen(QColor(255, 200, 0), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(int(lx), int(ly), d, d)
        ccx = int(lx + d / 2)
        ccy = int(ly + d / 2)
        painter.setPen(QPen(QColor(255, 60, 60), 1))
        painter.drawLine(ccx - 14, ccy, ccx + 14, ccy)
        painter.drawLine(ccx, ccy - 14, ccx, ccy + 14)
        painter.setBrush(QColor(255, 60, 60))
        painter.drawEllipse(ccx - 2, ccy - 2, 4, 4)

    def _draw_polygon(self, painter, pts):
        path = QPainterPath()
        path.moveTo(pts[0][0], pts[0][1])
        for x, y in pts[1:]:
            path.lineTo(x, y)
        path.closeSubpath()
        painter.drawPath(path)

    def _paint_extra_zone(self, painter, z, ox, oy, dw, dh):
        """Render a single schema-driven extra zone."""
        style = z.get("style", DEFAULT_STYLE)
        zcolor = QColor(style.get("color", "#3CA0FF"))
        thick = max(1, int(style.get("thickness", 2)))
        fill_a = max(0, min(255, int(style.get("fill_alpha", 0))))
        dashed = bool(style.get("dashed", False))
        label = str(style.get("label_text", ""))
        ztype = z.get("type", "polygon")
        geom = z.get("geometry")
        pen_style = Qt.DashLine if dashed else Qt.SolidLine

        if (ztype == "polygon" and style.get("shape") == "y_template"
                and geom and len(geom) >= 4):
            # Hub + N endpoints. Y-Maze uses N=3, EPM uses N=4. Render as
            # N dashed spokes + labeled endpoint dots (no closing polygon).
            n_pts = len(geom)
            pts = [self._norm_to_disp(p, ox, oy, dw, dh) for p in geom[:n_pts]]
            hub = pts[0]
            ends = pts[1:]
            n_ends = len(ends)
            labels = style.get("endpoint_labels") or ["A", "B", "C"]
            painter.setPen(QPen(zcolor, thick, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            for ex, ey in ends:
                painter.drawLine(hub[0], hub[1], ex, ey)
            painter.setPen(QPen(zcolor, 1))
            painter.setBrush(zcolor)
            painter.drawEllipse(hub[0] - 6, hub[1] - 6, 12, 12)
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            for (ex, ey), lab in zip(ends, labels[:n_ends]):
                painter.setPen(QPen(zcolor, 1))
                painter.setBrush(QColor(255, 255, 255))
                painter.drawEllipse(ex - 6, ey - 6, 12, 12)
                painter.setPen(zcolor)
                painter.drawText(ex + 10, ey + 5, str(lab))
            if self.mode == self.MODE_IDLE and z.get("editable", True):
                painter.setPen(QPen(zcolor, 1))
                painter.setBrush(QColor(255, 255, 255, 0))
                for hx, hy in pts:
                    painter.drawEllipse(hx - 7, hy - 7, 14, 14)
            return
        if ztype == "polygon" and geom and len(geom) >= 2:
            pts = [self._norm_to_disp(p, ox, oy, dw, dh) for p in geom]
            if fill_a > 0:
                fc = QColor(zcolor); fc.setAlpha(fill_a)
                painter.setPen(Qt.NoPen)
                painter.setBrush(fc)
                if len(pts) >= 3:
                    self._draw_polygon(painter, pts)
            painter.setPen(QPen(zcolor, thick, pen_style))
            painter.setBrush(Qt.NoBrush)
            if len(pts) >= 3:
                self._draw_polygon(painter, pts)
            else:
                painter.drawLine(pts[0][0], pts[0][1], pts[1][0], pts[1][1])
            if label:
                painter.setFont(QFont("Arial", 9, QFont.Bold))
                painter.setPen(zcolor)
                lpos = style.get("label_pos")
                if lpos and len(lpos) == 2:
                    lx, ly = self._norm_to_disp(lpos, ox, oy, dw, dh)
                    painter.drawText(lx, ly, label)
                else:
                    painter.drawText(pts[0][0] + 4, pts[0][1] - 6, label)
            # Editable handles in idle mode
            if self.mode == self.MODE_IDLE and z.get("editable", True):
                painter.setPen(QPen(zcolor, 1))
                painter.setBrush(QColor(255, 255, 255))
                for hx, hy in pts:
                    painter.drawEllipse(hx - 4, hy - 4, 8, 8)
        elif ztype == "circle" and geom:
            cx, cy, r = geom
            cxd, cyd = self._norm_to_disp((cx, cy), ox, oy, dw, dh)
            rd = int(r * dw)
            if fill_a > 0:
                fc = QColor(zcolor); fc.setAlpha(fill_a)
                painter.setPen(Qt.NoPen)
                painter.setBrush(fc)
                painter.drawEllipse(cxd - rd, cyd - rd, rd * 2, rd * 2)
            painter.setPen(QPen(zcolor, thick, pen_style))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(cxd - rd, cyd - rd, rd * 2, rd * 2)
            if label:
                painter.setFont(QFont("Arial", 9, QFont.Bold))
                painter.setPen(zcolor)
                painter.drawText(cxd - rd + 4, cyd - rd - 4, label)
        elif ztype == "line" and geom:
            (x1, y1), (x2, y2) = geom
            d1 = self._norm_to_disp((x1, y1), ox, oy, dw, dh)
            d2 = self._norm_to_disp((x2, y2), ox, oy, dw, dh)
            painter.setPen(QPen(zcolor, thick, pen_style))
            painter.drawLine(d1[0], d1[1], d2[0], d2[1])

    # ── exclusion helpers ─────────────────────────────────────────────────

    def _paint_exclusion(self, norm, erase=False):
        if self.exclusion_mask is None:
            return
        h, w = self.exclusion_mask.shape
        px = int(np.clip(norm[0] * w, 0, w - 1))
        py = int(np.clip(norm[1] * h, 0, h - 1))
        r  = self.brush_radius
        yy, xx = np.ogrid[:h, :w]
        circle = (xx - px) ** 2 + (yy - py) ** 2 <= r * r
        self.exclusion_mask[circle] = 0 if erase else 255
        self._excl_cache = None
        self.exclusion_changed.emit()
        self.update()

    # ── coordinate helpers ────────────────────────────────────────────────

    def _get_disp_rect(self):
        if self._base_pixmap is None:
            return (0, 0, self.width(), self.height())
        lw, lh = self.width(), self.height()
        pw, ph = self._base_pixmap.width(), self._base_pixmap.height()
        if pw == 0 or ph == 0:
            return (0, 0, lw, lh)
        scale = min(lw / pw, lh / ph)
        dw, dh = int(pw * scale), int(ph * scale)
        ox, oy = (lw - dw) // 2, (lh - dh) // 2
        return ox, oy, dw, dh

    def _widget_to_norm(self, qpoint):
        ox, oy, dw, dh = self._get_disp_rect()
        nx = max(0.0, min(1.0, (qpoint.x() - ox) / dw))
        ny = max(0.0, min(1.0, (qpoint.y() - oy) / dh))
        return (nx, ny)

    def _norm_to_disp(self, norm, ox, oy, dw, dh):
        return (int(ox + norm[0] * dw), int(oy + norm[1] * dh))
