"""NORTab — thin subclass of OpenFieldTab that swaps the experiment
plugin to NORExperiment. The plugin owns the geometry pane, results
tab, metrics, and zone schema; this class only adds the live nose-in-
zone bookkeeping that depends on per-frame tracker emissions.

NORBatchTab is the equivalent thin subclass of ExperimentBatchTab (via
OpenFieldBatchTab) — same generic shell, different embedded tab class."""
from PyQt5.QtCore import QObject, QEvent, Qt

from gui.open_field_tab import OpenFieldTab
from gui.experiment_batch_tab import ExperimentBatchTab
from experiments.nor import NORExperiment
from experiments.nor.zones import (
    OBJECT_NAMES, SHAPE_CUSTOM, footprint_name,
)
from experiments.nor.nor_overlay import (
    paint_nor_overlay, point_to_object, HANDLE_RADIUS_PX,
)


class NORTab(OpenFieldTab):
    def __init__(self, config):
        super().__init__(config, experiment=NORExperiment())
        # Add NOR results tab. Insert right after Summary (index 1) so the
        # user lands on it after the at-a-glance Summary view.
        try:
            tab = self.experiment.build_results_tabs(self, self._excel_tabs)
            if tab is not None and hasattr(self, "_excel_tabs"):
                self._excel_tabs.insertTab(1, tab, "NOR")
        except Exception:
            pass
        # Live per-object tracking state. Mirrors the YM pattern: pending
        # → confirmed via shared spin_min_dwell so the live counts match
        # what post-tracking metrics produce.
        self._nor_current_obj = None
        self._nor_last_committed_obj = None
        self._nor_object_entries = {n: 0 for n in OBJECT_NAMES}
        self._nor_object_times = {n: 0.0 for n in OBJECT_NAMES}
        self._nor_pending_obj = None
        self._nor_pending_frames = 0
        # Latest body pos cached so the angle filter has a heading source
        # when a nose_pos event fires.
        self._nor_last_body_xy = None
        # Register NOR overlay with the shared zone drawer.
        zd = self.zone_drawer
        zd.set_overlay_renderer(
            lambda p, ox, oy, dw, dh: paint_nor_overlay(self, zd, p, ox, oy, dw, dh)
        )
        # Install center-handle drag filter so the user can move a placed
        # object by grabbing its center dot. Stored as an attribute so
        # the filter object outlives this __init__ call.
        self._nor_handle_filter = _NORHandleDragFilter(self)
        zd.installEventFilter(self._nor_handle_filter)
        # NOR cage is always square — collapse the Width × Height widget
        # to a single "Side:" spinbox. Also rescue a stale 0 default from
        # config so auto-cal isn't blocked on first run.
        self._install_nor_square_cage_widget()
        # NOR-only default for the View ▾ popup body marker. Nose-based
        # detection means the user wants to see nose + center + tail to
        # verify which point drives in-zone counting.
        if hasattr(self, "combo_body_style"):
            i = self.combo_body_style.findData("ends")
            if i >= 0:
                self.combo_body_style.setCurrentIndex(i)

    # ── Live tracking signals ────────────────────────────────────────────
    def _on_tracking_body_pos(self, body_xy):
        """Cache body pos for the angle filter + drive the live body dot.
        Per-object accounting happens on nose_pos events instead, so the
        OF cell-highlight logic in the base class is skipped here."""
        self._nor_last_body_xy = body_xy
        zd = self.zone_drawer
        if body_xy is None or not (self.video_w and self.video_h):
            zd.set_body_pos_norm(None)
            zd.update()
            return
        x_px, y_px = body_xy
        zd.set_body_pos_norm((x_px / float(self.video_w),
                               y_px / float(self.video_h)))
        zd.update()

    def _on_tracking_nose_pos(self, nose_xy):
        """Per-frame nose pos from the tracker. Drives the in-zone
        debounce + entry counter + cumulative time."""
        # Honor the live-overlay opt-out (same speed contract as YM).
        if self._tracking_active and not self._live_cell_overlay:
            return
        zd = self.zone_drawer
        if nose_xy is None or not (self.video_w and self.video_h):
            self._nor_current_obj = None
            zd.update()
            return
        nx_px, ny_px = nose_xy
        nx = nx_px / float(self.video_w)
        ny = ny_px / float(self.video_h)
        obj = point_to_object(zd, nx, ny)
        # Optional angle filter — drop the obj if heading isn't aimed at it.
        if obj is not None and getattr(self, "_nor_angle_enabled", False):
            if not self._nose_facing_object(obj, nose_xy):
                obj = None
        fps = self.fps or 30.0
        dt = 1.0 / fps
        min_dwell = float(self.spin_min_dwell.value())
        min_frames = max(1, int(round(min_dwell * fps))) if min_dwell > 0 else 1
        if obj == self._nor_pending_obj:
            self._nor_pending_frames += 1
        else:
            self._nor_pending_obj = obj
            self._nor_pending_frames = 1
        if self._nor_pending_frames < min_frames:
            zd.update()
            return
        if obj != self._nor_current_obj:
            self._nor_current_obj = obj
            if obj is not None:
                if obj != self._nor_last_committed_obj:
                    self._nor_object_entries[obj] = (
                        self._nor_object_entries.get(obj, 0) + 1
                    )
                    self._nor_last_committed_obj = obj
                self._nor_object_times[obj] = (
                    self._nor_object_times.get(obj, 0.0)
                    + self._nor_pending_frames * dt
                )
        elif self._nor_pending_frames == min_frames:
            if obj is not None:
                self._nor_object_times[obj] = (
                    self._nor_object_times.get(obj, 0.0)
                    + self._nor_pending_frames * dt
                )
        else:
            if obj is not None:
                self._nor_object_times[obj] = (
                    self._nor_object_times.get(obj, 0.0) + dt
                )
        zd.update()

    def _nose_facing_object(self, obj_id, nose_xy):
        """Angle filter — True when (body→nose) heading is within
        _nor_angle_max_deg of (body→object_center)."""
        import math
        body = self._nor_last_body_xy
        if body is None or nose_xy is None:
            return True  # no heading info → don't gate
        zd = self.zone_drawer
        from experiments.nor.zones import zone_name
        z = zd.get_zone(zone_name(obj_id))
        if not z or not z.get("geometry"):
            return True
        geom = z["geometry"]
        cx_n = sum(p[0] for p in geom) / len(geom)
        cy_n = sum(p[1] for p in geom) / len(geom)
        tx = cx_n * float(self.video_w)
        ty = cy_n * float(self.video_h)
        bx, by = body
        nx, ny = nose_xy
        hx, hy = nx - bx, ny - by
        h_len = math.hypot(hx, hy)
        if h_len <= 1e-6:
            return True
        dx, dy = tx - bx, ty - by
        d_len = math.hypot(dx, dy)
        if d_len <= 1e-6:
            return True
        cos_a = (hx * dx + hy * dy) / (h_len * d_len)
        cos_a = max(-1.0, min(1.0, cos_a))
        ang = math.degrees(math.acos(cos_a))
        return ang <= float(getattr(self, "_nor_angle_max_deg", 45.0))

    def begin_tracking(self):
        """Reset live NOR stats at the start of every run."""
        super().begin_tracking()
        self._nor_current_obj = None
        self._nor_last_committed_obj = None
        self._nor_object_entries = {n: 0 for n in OBJECT_NAMES}
        self._nor_object_times = {n: 0.0 for n in OBJECT_NAMES}
        self._nor_pending_obj = None
        self._nor_pending_frames = 0
        self._nor_last_body_xy = None

    def _push_cell_state_for_frame(self, frame_idx):
        """NOR scrub: replay nose-in-zone over frames [0..idx] so per-
        object counters match what live would have shown, even when live
        overlay was off during tracking. Reads nose_x/nose_y from results."""
        import math
        zd = self.zone_drawer
        if not self.tracking_results:
            zd.set_body_pos_norm(None)
            self._nor_object_entries = {n: 0 for n in OBJECT_NAMES}
            self._nor_object_times = {n: 0.0 for n in OBJECT_NAMES}
            self._nor_current_obj = None
            zd.update()
            return
        rel_idx = self._slider_to_results_idx(frame_idx)
        r = self.tracking_results[rel_idx]
        bx, by = r.get("x"), r.get("y")
        if bx is not None and by is not None and self.video_w and self.video_h:
            zd.set_body_pos_norm((bx / float(self.video_w),
                                   by / float(self.video_h)))
        else:
            zd.set_body_pos_norm(None)
        fps = self.fps or 30.0
        dt = 1.0 / fps
        min_dwell = float(self.spin_min_dwell.value())
        min_frames = max(1, int(round(min_dwell * fps))) if min_dwell > 0 else 1
        angle_on = bool(getattr(self, "_nor_angle_enabled", False))
        angle_max = float(getattr(self, "_nor_angle_max_deg", 45.0))
        # Precompute object zone centroids in pixel coords (for angle filter).
        from experiments.nor.zones import zone_name
        centroids_px = {}
        for obj_id in OBJECT_NAMES:
            z = zd.get_zone(zone_name(obj_id))
            if z and z.get("geometry"):
                geom = z["geometry"]
                cx = sum(p[0] for p in geom) / len(geom)
                cy = sum(p[1] for p in geom) / len(geom)
                centroids_px[obj_id] = (cx * float(self.video_w or 1),
                                        cy * float(self.video_h or 1))
        entries = {n: 0 for n in OBJECT_NAMES}
        times = {n: 0.0 for n in OBJECT_NAMES}
        pending = None
        pending_frames = 0
        current = None
        last_committed = None
        vw = float(self.video_w or 1)
        vh = float(self.video_h or 1)
        for k in range(rel_idx + 1):
            rk = self.tracking_results[k]
            nxp = rk.get("nose_x")
            nyp = rk.get("nose_y")
            if nxp is None or nyp is None:
                obj = None
            else:
                obj = point_to_object(zd, nxp / vw, nyp / vh)
                if obj is not None and angle_on:
                    bxk = rk.get("x")
                    byk = rk.get("y")
                    cx, cy = centroids_px.get(obj, (None, None))
                    if (bxk is not None and byk is not None
                            and cx is not None and cy is not None):
                        hx, hy = nxp - bxk, nyp - byk
                        h_len = math.hypot(hx, hy)
                        dx, dy = cx - bxk, cy - byk
                        d_len = math.hypot(dx, dy)
                        if h_len > 1e-6 and d_len > 1e-6:
                            cos_a = (hx * dx + hy * dy) / (h_len * d_len)
                            cos_a = max(-1.0, min(1.0, cos_a))
                            ang = math.degrees(math.acos(cos_a))
                            if ang > angle_max:
                                obj = None
            if obj == pending:
                pending_frames += 1
            else:
                pending = obj
                pending_frames = 1
            if pending_frames < min_frames:
                continue
            if obj != current:
                current = obj
                if obj is not None:
                    if obj != last_committed:
                        entries[obj] = entries.get(obj, 0) + 1
                        last_committed = obj
                    times[obj] = times.get(obj, 0.0) + pending_frames * dt
            elif pending_frames == min_frames:
                if obj is not None:
                    times[obj] = times.get(obj, 0.0) + pending_frames * dt
            else:
                if obj is not None:
                    times[obj] = times.get(obj, 0.0) + dt
        self._nor_object_entries = entries
        self._nor_object_times = times
        self._nor_current_obj = current
        zd.update()


    def _install_nor_square_cage_widget(self):
        """Reshape the shared cage-size widget for a square cage. The OF
        base builds 'Width: [W] × Height: [H]' and only collapses to
        'Side:' when its own combo_cage_shape is set to square — which
        NOR never builds. We force the square layout here so the user
        sees one cm input."""
        if hasattr(self, "lbl_cage_w"):
            self.lbl_cage_w.setText("Side:")
        if hasattr(self, "lbl_cage_x"):
            self.lbl_cage_x.setVisible(False)
        if hasattr(self, "lbl_cage_h"):
            self.lbl_cage_h.setVisible(False)
        if hasattr(self, "spin_cage_h"):
            self.spin_cage_h.setVisible(False)
        # Force a sensible default when config carries 0 (or the spin
        # was never seeded). Keeps the auto-cal preflight from blocking
        # the very first run with "cage side length = 0".
        if hasattr(self, "spin_cage_w") and float(self.spin_cage_w.value()) <= 0:
            self.spin_cage_w.setValue(float(self.config.get("cage_w_cm") or 30.0))
        # Keep height mirrored to width so any downstream code that still
        # reads cage_h_cm gets the square value instead of 0.
        if hasattr(self, "spin_cage_w") and hasattr(self, "spin_cage_h"):
            try:
                self.spin_cage_w.valueChanged.connect(
                    lambda v: self.spin_cage_h.setValue(float(v))
                )
                self.spin_cage_h.setValue(float(self.spin_cage_w.value()))
            except Exception:
                pass


class _NORHandleDragFilter(QObject):
    """Qt event filter installed on the zone_drawer that lets the user
    grab an object's center dot and drag it across the preview. Only
    active when the drawer is in IDLE mode (no other tool selected) so
    it never steals clicks from arena-draw / calibration / placement.

    Supports both placement modes:
      * standard shapes (circle/square/triangle) — translates by
        updating `state["center_norm"]` to the cursor's normalized pos.
      * custom polygon — translates every vertex in `custom_geom_norm`
        by the cursor delta, preserving the shape the user drew.
    """
    GRAB_RADIUS_PX = HANDLE_RADIUS_PX + 4  # forgiving hit zone

    def __init__(self, tab):
        super().__init__(tab)
        self._tab = tab
        self._dragging = None        # obj_id while drag is active
        self._drag_kind = None       # "standard" | "custom"
        self._drag_last_norm = None  # for custom-shape per-vertex delta

    def eventFilter(self, obj, event):
        zd = self._tab.zone_drawer
        if obj is not zd:
            return False
        et = event.type()
        if et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if zd.mode != zd.MODE_IDLE:
                return False
            # Priority 1 — first click of a standard-shape placement.
            # (Custom-shape placement uses MODE_POLY → handled by the
            # zone_drawer itself, not by this filter.)
            placing = getattr(self._tab, "_nor_placing", None)
            if placing:
                state = self._tab._nor_objects.get(placing) or {}
                if state.get("shape") != SHAPE_CUSTOM:
                    from experiments.nor.ui import finish_place_standard
                    norm = zd._widget_to_norm(event.pos())
                    finish_place_standard(self._tab, norm[0], norm[1])
                    return True
                return False
            # Priority 2 — grab the center handle of an existing object.
            hit = self._hit_test(event.pos())
            if hit is None:
                return False
            self._dragging = hit
            state = self._tab._nor_objects.get(hit) or {}
            self._drag_kind = ("custom" if state.get("shape") == SHAPE_CUSTOM
                               else "standard")
            self._drag_last_norm = zd._widget_to_norm(event.pos())
            zd.setCursor(Qt.ClosedHandCursor)
            return True
        if et == QEvent.MouseMove and self._dragging is not None:
            self._apply_drag(zd._widget_to_norm(event.pos()))
            return True
        if et == QEvent.MouseButtonRelease and self._dragging is not None:
            self._dragging = None
            self._drag_kind = None
            self._drag_last_norm = None
            zd.setCursor(Qt.ArrowCursor)
            zd.emit_change("nor object moved")
            return True
        return False

    def _hit_test(self, widget_pos):
        """Return obj_id whose center handle contains widget_pos, else
        None. Uses the same centroid + radius the overlay renderer uses."""
        zd = self._tab.zone_drawer
        ox, oy, dw, dh = zd._get_disp_rect()
        px, py = widget_pos.x(), widget_pos.y()
        r2 = self.GRAB_RADIUS_PX * self.GRAB_RADIUS_PX
        # Iterate B first then A so the topmost-painted handle wins overlap.
        for obj_id in reversed(OBJECT_NAMES):
            fp = zd.get_zone(footprint_name(obj_id))
            if not fp or len(fp.get("geometry") or []) < 3:
                continue
            geom = fp["geometry"]
            cx_n = sum(p[0] for p in geom) / len(geom)
            cy_n = sum(p[1] for p in geom) / len(geom)
            hx, hy = zd._norm_to_disp((cx_n, cy_n), ox, oy, dw, dh)
            if (px - hx) ** 2 + (py - hy) ** 2 <= r2:
                return obj_id
        return None

    def _apply_drag(self, cur_norm):
        """Translate the dragging object's geometry to follow cur_norm.
        Refreshes only the dragged object's zones — the other object's
        geometry is unchanged on a drag, so recomputing it every
        mouseMove was wasted work and made the drag feel laggy."""
        from experiments.nor.ui import _refresh_object_zones
        obj_id = self._dragging
        state = self._tab._nor_objects.get(obj_id)
        if not state:
            return
        if self._drag_kind == "standard":
            state["center_norm"] = (float(cur_norm[0]), float(cur_norm[1]))
        else:  # custom polygon — translate every vertex by the delta
            last = self._drag_last_norm or cur_norm
            dx = float(cur_norm[0]) - float(last[0])
            dy = float(cur_norm[1]) - float(last[1])
            state["custom_geom_norm"] = [
                (x + dx, y + dy) for (x, y) in (state.get("custom_geom_norm") or [])
            ]
        self._drag_last_norm = cur_norm
        _refresh_object_zones(self._tab, obj_id)


class NORBatchTab(ExperimentBatchTab):
    embedded_tab_class = NORTab
