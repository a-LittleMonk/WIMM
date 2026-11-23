"""NORExperiment plugin — wires the NOR-specific UI, metrics, and zone
schema into the generic Experiment contract. NOR's arena is a square
cage (no center/periphery analysis) and the primary signal is nose-in-
interaction-zone time."""
from experiments.base import Experiment
from experiments.open_field.experiment import OpenFieldExperiment

from . import zones as nor_zones
from . import metrics as nor_metrics
from . import ui as nor_ui


class NORExperiment(Experiment):
    name = "Novel Object"
    key = "nor"
    family = "nor"
    results_title = "NOR"
    role_labels = None          # None → nor_zones.ROLE_LABELS

    # Reused for OF-style square-cage px/cm + cage-size widget logic.
    _of_helper = OpenFieldExperiment()

    def default_enable_nose(self) -> bool:
        """NOR's angle filter (nose pointing at the object) is on the
        critical path for the discrimination index, so nose detection
        defaults to ON for this paradigm. Users can still untick the
        Step 5 checkbox if they don't need angle filtering."""
        return True

    def graph_caps(self, graph_name):
        """NOR shares OF's 4×4 grid + center overlay on the same graphs."""
        return self._of_helper.graph_caps(graph_name)

    def zone_bar_data(self, host):
        # NOR readout: nose-interaction time per object (label with role when
        # familiar/novel has been assigned).
        m = getattr(host, "metrics", None) or {}

        def _label(obj_id, default):
            name = m.get(f"{obj_id}_name") or default
            role = m.get(f"{obj_id}_role")
            return f"{name} ({role})" if role in ("familiar", "novel") else name

        labels = [_label("object_a", "Object A"), _label("object_b", "Object B")]
        values = [
            float(m.get("object_a_total_time_s", 0.0) or 0.0),
            float(m.get("object_b_total_time_s", 0.0) or 0.0),
        ]
        colors = ["#E8A87C", "#7FA6D9"]
        return (labels, values, colors, lambda v: f"{v:.1f}s",
                "Object Exploration Time", "Time (s)")

    # ── Zones ────────────────────────────────────────────────────────────
    # ── Setup-card summaries ──────────────────────────────────────────
    def summary_zones(self, host):
        objs = getattr(host, "_nor_objects", {}) or {}
        placed = sum(1 for st in objs.values()
                     if st.get("center_norm") or st.get("custom_geom_norm"))
        roles = [st.get("role") for st in objs.values()]
        text = f"{placed}/2 objects"
        if "novel" in roles and "familiar" in roles:
            text += " · roles set"
        return text

    def zones_schema(self, host):
        return nor_zones.build_schema(host)

    # ── UI ───────────────────────────────────────────────────────────────
    def build_geometry_step(self, host):
        return nor_ui.build_geometry_step(host)

    def build_results_tabs(self, host, right_tabs):
        return nor_ui.build_results_tab(host)

    def live_overlay_label(self):
        return "Live object overlay during tracking (slower)"

    def cell_highlight_toggle_specs(self, host):
        """Reuse the zone_drawer's _arm_show_* slots for NOR labels."""
        zd = host.zone_drawer
        return [
            ("Hide object names",
             lambda: not zd._arm_show_numbers,
             lambda hide: zd.set_arm_show_numbers(not hide)),
            ("Hide per-object timer (SS.cc)",
             lambda: not zd._arm_show_timer,
             lambda hide: zd.set_arm_show_timer(not hide)),
            ("Hide per-object entry count (#)",
             lambda: not zd._arm_show_entries,
             lambda hide: zd.set_arm_show_entries(not hide)),
        ]

    # ── Analysis ─────────────────────────────────────────────────────────
    def compute_metrics(self, results, settings, fps, px_per_cm):
        # Convert normalized object geometry → pixels so metrics.compute
        # can use matplotlib Path point-in-polygon directly.
        vw = settings.get("video_w") or 1
        vh = settings.get("video_h") or 1
        objects_norm = settings.get("objects_norm") or {}
        objects_px = {}
        for obj_id, st in objects_norm.items():
            footprint_norm = st.get("footprint_norm") or []
            zone_norm = st.get("zone_norm") or []
            objects_px[obj_id] = {
                "name": st.get("name", nor_zones.OBJECT_LABELS.get(obj_id, obj_id)),
                "role": st.get("role", "none"),
                "color": st.get("color"),
                "footprint_px": [(x * vw, y * vh) for (x, y) in footprint_norm],
                "zone_px":      [(x * vw, y * vh) for (x, y) in zone_norm],
            }
        # Callers (tab + batch) pass the arena already in pixels.
        arena_px = [(float(x), float(y)) for (x, y) in (settings.get("arena") or [])]
        s = dict(settings)
        s["objects"] = objects_px
        s["arena_px"] = arena_px
        return nor_metrics.compute(results, s, fps, px_per_cm)

    def export_columns(self):
        return list(nor_metrics.EXPORT_COLUMNS)

    def batch_schema(self):
        return list(nor_metrics.BATCH_SCHEMA)

    def summary_table_keys(self, metrics):
        return [
            "duration_s", "total_distance",
            "mean_speed", "max_speed", "median_speed",
            "mobility_time_s", "immobility_time_s",
            "frames_detected", "total_frames", "detection_rate_pct",
            "unit",
            "min_dwell_s", "angle_enabled", "angle_max_deg",
            "object_a_name", "object_a_role",
            "object_a_total_time_s", "object_a_entries",
            "object_a_latency_first_s",
            "object_a_bouts_count", "object_a_mean_bout_s",
            "object_a_longest_bout_s",
            "object_b_name", "object_b_role",
            "object_b_total_time_s", "object_b_entries",
            "object_b_latency_first_s",
            "object_b_bouts_count", "object_b_mean_bout_s",
            "object_b_longest_bout_s",
            "familiar_time_s", "novel_time_s",
            "discrimination_index", "preference_pct_novel",
            "arena_entries", "arena_total_time_s",
            "pause_count", "pause_total_s",
        ]

    def populate_results_tab(self, host, metrics):
        """Fill the NOR table with per-object stats + DI."""
        if not hasattr(host, "_nor_table") or not metrics:
            return
        from PyQt5.QtWidgets import QTableWidgetItem
        rows = []
        for obj_id in nor_zones.OBJECT_NAMES:
            label = metrics.get(f"{obj_id}_name", nor_zones.OBJECT_LABELS[obj_id])
            role = metrics.get(f"{obj_id}_role", "—")
            rows.append((f"{label} (role)", role))
            rows.append((f"{label} — total time (s)",
                         metrics.get(f"{obj_id}_total_time_s")))
            rows.append((f"{label} — entries",
                         metrics.get(f"{obj_id}_entries")))
            rows.append((f"{label} — latency first (s)",
                         metrics.get(f"{obj_id}_latency_first_s")))
            rows.append((f"{label} — bouts",
                         metrics.get(f"{obj_id}_bouts_count")))
            rows.append((f"{label} — mean bout (s)",
                         metrics.get(f"{obj_id}_mean_bout_s")))
            rows.append((f"{label} — longest bout (s)",
                         metrics.get(f"{obj_id}_longest_bout_s")))
        rows.append(("Familiar time (s)", metrics.get("familiar_time_s")))
        rows.append(("Novel time (s)", metrics.get("novel_time_s")))
        rows.append(("Discrimination Index",
                     metrics.get("discrimination_index")))
        rows.append(("Preference for Novel (%)",
                     metrics.get("preference_pct_novel")))
        rows.append(("Arena entries", metrics.get("arena_entries")))
        rows.append(("Arena total time (s)",
                     metrics.get("arena_total_time_s")))
        rows.append(("Min dwell (s)", metrics.get("min_dwell_s")))
        rows.append(("Angle filter enabled", metrics.get("angle_enabled")))
        rows.append(("Angle max (deg)", metrics.get("angle_max_deg")))
        rows = [(k, v) for k, v in rows if v is not None]
        t = host._nor_table
        t.setUpdatesEnabled(False)
        try:
            t.setRowCount(len(rows))
            for r, (k, v) in enumerate(rows):
                t.setItem(r, 0, QTableWidgetItem(str(k)))
                t.setItem(r, 1, QTableWidgetItem(str(v)))
        finally:
            t.setUpdatesEnabled(True)

    # ── Per-video persistence ────────────────────────────────────────────
    def snapshot_extras(self, host):
        return {
            "objects":         _objects_for_persist(host),
            "angle_enabled":   bool(getattr(host, "_nor_angle_enabled", False)),
            "angle_max_deg":   float(getattr(host, "_nor_angle_max_deg", 45.0)),
        }

    def apply_extras(self, host, extras):
        if not isinstance(extras, dict):
            return
        objs = extras.get("objects") or {}
        if not hasattr(host, "_nor_objects"):
            host._nor_objects = {
                oid: nor_zones.default_object_state(oid)
                for oid in nor_zones.OBJECT_NAMES
            }
        for obj_id in nor_zones.OBJECT_NAMES:
            saved = objs.get(obj_id) or {}
            target = host._nor_objects[obj_id]
            for key in ("name", "role", "shape", "size_cm", "padding_cm",
                        "color", "center_norm", "custom_geom_norm"):
                if key in saved:
                    target[key] = saved[key]
        host._nor_angle_enabled = bool(extras.get("angle_enabled", False))
        host._nor_angle_max_deg = float(extras.get("angle_max_deg", 45.0))
        # Sync widgets if they exist yet.
        if hasattr(host, "_nor_widgets"):
            for obj_id, w in host._nor_widgets.items():
                st = host._nor_objects[obj_id]
                w["name"].setText(st.get("name", nor_zones.OBJECT_LABELS[obj_id]))
                idx = w["role"].findData(st.get("role", "none"))
                if idx >= 0:
                    w["role"].setCurrentIndex(idx)
                idx = w["shape"].findData(st.get("shape", "circle"))
                if idx >= 0:
                    w["shape"].setCurrentIndex(idx)
                w["size"].setValue(float(st.get("size_cm", 5.0)))
                w["padding"].setValue(float(st.get("padding_cm", 2.0)))
            if hasattr(host, "chk_nor_angle"):
                host.chk_nor_angle.setChecked(host._nor_angle_enabled)
            if hasattr(host, "spin_nor_angle"):
                host.spin_nor_angle.setValue(host._nor_angle_max_deg)
        if getattr(host, "zone_drawer", None) is not None:
            from . import ui as nor_ui
            nor_ui._refresh_zones(host)              # draw this video's objects
        # Push the freshly restored geometry into the zone_drawer.
        nor_ui._refresh_zones(host)
        nor_ui._refresh_status(host)

    # ── Snapshot hook (tracker payload) ──────────────────────────────────
    def contribute_to_snapshot(self, host, snapshot):
        """Inject NOR object polygons + angle settings into the per-video
        snapshot so the metrics compute path has the geometry it needs.
        Footprint + zone are computed once here using the current px/cm
        so downstream callers (including headless batch) don't re-read
        host widgets."""
        states = getattr(host, "_nor_objects", {}) or {}
        px_per_cm = nor_zones._resolve_px_per_cm(host)
        video_size = (getattr(host, "video_w", None) or 0,
                      getattr(host, "video_h", None) or 0)
        objects_norm = {}
        for obj_id in nor_zones.OBJECT_NAMES:
            st = states.get(obj_id) or nor_zones.default_object_state(obj_id)
            footprint = nor_zones.build_footprint_norm(st, px_per_cm, video_size)
            zone = nor_zones.build_zone_norm(footprint, st, px_per_cm, video_size)
            objects_norm[obj_id] = {
                "name": st.get("name", nor_zones.OBJECT_LABELS[obj_id]),
                "role": st.get("role", "none"),
                "shape": st.get("shape", "circle"),
                "size_cm": float(st.get("size_cm") or 0),
                "padding_cm": float(st.get("padding_cm") or 0),
                "color": st.get("color"),
                "center_norm": st.get("center_norm"),
                "custom_geom_norm": list(st.get("custom_geom_norm") or []),
                "footprint_norm": list(footprint),
                "zone_norm": list(zone),
            }
        snapshot["objects_norm"] = objects_norm
        snapshot["angle_enabled"] = bool(getattr(host, "_nor_angle_enabled", False))
        snapshot["angle_max_deg"] = float(getattr(host, "_nor_angle_max_deg", 45.0))
        # Inject the square-cage size for auto-cal (shared scale_step builds
        # spin_cage_w but the base snapshot doesn't read it — each plugin
        # is expected to surface its own cage dimensions, same as OF does).
        if hasattr(host, "spin_cage_w"):
            side = float(host.spin_cage_w.value() or 0)
            snapshot["cage_w_cm"] = side
            snapshot["cage_h_cm"] = side
        # Force square shape for the OF auto-cal helper this plugin reuses.
        snapshot["cage_shape"] = "square"
        # Surface the shared Step-5 min_dwell into the snapshot so
        # metrics.compute (and the post-track Recompute on min_dwell change)
        # picks up the live value instead of falling back to the default.
        if hasattr(host, "spin_min_dwell"):
            snapshot["min_dwell_s"] = float(host.spin_min_dwell.value())

    # OF-only snapshot keys to drop from the NOR Excel's Video Config sheet.
    _OF_ONLY_VIDEO_CONFIG_KEYS = (
        "cell_categories", "cell_min_dwell", "cell_min_dwell_s",
        "zone_mode", "center_pct",
    )

    def filter_video_config(self, snapshot):
        out = dict(snapshot)
        for k in self._OF_ONLY_VIDEO_CONFIG_KEYS:
            out.pop(k, None)
        return out

    # ── Auto-calibration (reuse OF square cage formula) ──────────────────
    def compute_auto_px_per_cm(self, snapshot, video_size):
        # Force shape=square for the helper since NOR cage is always square.
        snap2 = dict(snapshot or {})
        snap2["cage_shape"] = "square"
        return self._of_helper.compute_auto_px_per_cm(snap2, video_size)

    def preflight_auto_scale_warning(self, snapshot):
        cage_w = float(snapshot.get("cage_w_cm") or 0)
        if cage_w <= 0:
            return "auto-cal selected but cage side length = 0"
        return None

    def refresh_scale_step_visibility(self, host, calib_mode):
        """NOR shows the OF cage W spinbox only; cage H stays hidden
        (square cage)."""
        if hasattr(host, "_cage_size_widget"):
            host._cage_size_widget.setVisible(calib_mode == "auto")
        if hasattr(host, "lbl_calib_auto_hint"):
            host.lbl_calib_auto_hint.setVisible(False)

    # ── Output graph decoration ──────────────────────────────────────────
    def decorate_graph(self, host, graph_name, ax, arena_px):
        """Paint each object's footprint (filled) + interaction zone
        (dashed outline) + a small role/name label on Trajectory and
        Heatmap. Returns legend handles for the trajectory graph (heatmap
        has no legend so the host ignores the return)."""
        if graph_name not in ("Trajectory", "Heatmap"):
            return None
        from matplotlib.patches import Polygon
        from matplotlib.lines import Line2D
        vw = getattr(host, "video_w", None) or 0
        vh = getattr(host, "video_h", None) or 0
        if not vw or not vh:
            return None
        states = getattr(host, "_nor_objects", {}) or {}
        px_per_cm = nor_zones._resolve_px_per_cm(host)
        legend_handles = []
        for obj_id in nor_zones.OBJECT_NAMES:
            st = states.get(obj_id) or nor_zones.default_object_state(obj_id)
            footprint_norm = nor_zones.build_footprint_norm(
                st, px_per_cm, (vw, vh))
            zone_norm = nor_zones.build_zone_norm(
                footprint_norm, st, px_per_cm, (vw, vh))
            if not footprint_norm:
                continue
            color = st.get("color") or nor_zones.OBJECT_COLORS.get(obj_id, "#FFFFFF")
            to_graph = getattr(host, "to_graph_space", lambda pts: pts)
            footprint_px = to_graph([(x * vw, y * vh) for (x, y) in footprint_norm])
            ax.add_patch(Polygon(
                footprint_px, closed=True,
                facecolor=color, edgecolor=color,
                alpha=0.55, linewidth=1.4, zorder=4.5,
            ))
            if zone_norm:
                zone_px = to_graph([(x * vw, y * vh) for (x, y) in zone_norm])
                ax.add_patch(Polygon(
                    zone_px, closed=True,
                    facecolor="none", edgecolor=color,
                    linestyle="--", linewidth=1.2, alpha=0.9, zorder=5,
                ))
            cx = sum(p[0] for p in footprint_px) / len(footprint_px)
            cy = sum(p[1] for p in footprint_px) / len(footprint_px)
            name = st.get("name") or nor_zones.OBJECT_LABELS[obj_id]
            role = (getattr(self, "role_labels", None) or nor_zones.ROLE_LABELS).get(
                st.get("role", "none"), "—")
            label_txt = name if role == "—" else f"{name} ({role})"
            ax.text(cx, cy, label_txt,
                    color="white", fontsize=9, ha="center", va="center",
                    fontweight="bold",
                    bbox=dict(facecolor=color, edgecolor="none",
                              alpha=0.85, pad=2.0, boxstyle="round,pad=0.3"),
                    zorder=6)
            legend_handles.append(Line2D(
                [], [], marker="s", color="w",
                markerfacecolor=color, markeredgecolor=color,
                markersize=9, label=label_txt,
            ))
        return legend_handles or None


# ── Helpers ──────────────────────────────────────────────────────────────

def _objects_for_persist(host):
    """Strip transient widget refs; serialize only the data fields."""
    objs = getattr(host, "_nor_objects", {}) or {}
    out = {}
    for obj_id, st in objs.items():
        out[obj_id] = {
            "name": st.get("name"),
            "role": st.get("role"),
            "shape": st.get("shape"),
            "size_cm": st.get("size_cm"),
            "padding_cm": st.get("padding_cm"),
            "color": st.get("color"),
            "center_norm": st.get("center_norm"),
            "custom_geom_norm": list(st.get("custom_geom_norm") or []),
        }
    return out
