"""YMazeExperiment plugin."""
from experiments.base import Experiment
from . import zones as ym_zones
from . import metrics as ym_metrics
from . import ui as ym_ui


class YMazeExperiment(Experiment):
    name = "Y-Maze"
    key = "y_maze"

    def graph_names(self):
        """Y-Maze: no 4×4 cell grid; adds Triplets (acceptable vs
        unacceptable alternations)."""
        from gui.graph_style import GRAPH_NAMES
        return [g for g in GRAPH_NAMES if g != "Cell Time"]

    def graph_caps(self, graph_name):
        """Expose the arm-thickness control on the shape-bearing graphs so
        the Customize-Graphs preview can re-shape the synthetic Y maze."""
        if graph_name in ("Trajectory", "Heatmap"):
            return {"plus_thickness"}
        return set()

    def canonical_arm_layout(self, host):
        """Map the 3 drawn arms onto the canonical Y (90°/210°/330°) by
        rotational order, so the output Trajectory/Heatmap render on the same
        idealized maze as the styling preview."""
        import math
        from gui.graph_style_dialog import maze_canonical_dirs
        zd = getattr(host, "zone_drawer", None)
        if zd is None:
            return None
        arms = []
        for name in ym_zones.ARM_NAMES:
            z = zd.get_zone(name)
            geom = z.get("geometry") if z else None
            if geom and len(geom) >= 3:
                arms.append([tuple(p) for p in geom])
        if len(arms) < 3:
            return None
        hub = getattr(host, "_ym_hub", None)
        if hub and len(hub) == 2:
            hub = (float(hub[0]), float(hub[1]))
        else:
            cs = [(sum(p[0] for p in g) / len(g),
                   sum(p[1] for p in g) / len(g)) for g in arms]
            hub = (sum(c[0] for c in cs) / len(cs),
                   sum(c[1] for c in cs) / len(cs))

        def _angle(g):  # math y-up angle of the arm centroid about the hub
            cx = sum(p[0] for p in g) / len(g)
            cy = sum(p[1] for p in g) / len(g)
            return math.atan2(-(cy - hub[1]), cx - hub[0])

        arms_sorted = sorted(arms, key=_angle)
        cdirs = sorted(maze_canonical_dirs("y_maze"),
                       key=lambda d: math.atan2(d[1], d[0]))
        return {"hub": hub,
                "arms": [{"poly": g, "cdir": cd}
                         for g, cd in zip(arms_sorted, cdirs)]}

    # ── Setup-card summaries ──────────────────────────────────────────
    def summary_geometry(self, host):
        zd = getattr(host, "zone_drawer", None)
        if zd is None:
            return "Not defined"
        n = sum(1 for a in ym_zones.ARM_NAMES
                if len((zd.get_zone(a) or {}).get("geometry") or []) >= 3)
        if not n:
            return "Not defined"
        mode = ("Y template" if host.rb_ym_template.isChecked()
                else "Manual")
        return f"{mode} · {n}/3 arms"

    def summary_zones(self, host):
        if not host.rb_ym_template.isChecked():
            return "arms drawn by hand"
        w = round(host.spin_ym_arm_width.value() * 100)
        nz = round(host.spin_ym_neutral_size.value() * 100)
        return f"arm {w}% · neutral {nz}%"

    def zones_schema(self, host):
        # Reflects current per-arm state; freshly built host has empty arms.
        geoms = ym_zones.get_arm_geoms(host)
        return ym_zones.build_schema_from_arms(geoms)

    def build_geometry_step(self, host):
        return ym_ui.build_geometry_step(host)

    def build_results_tabs(self, host, right_tabs):
        return ym_ui.build_results_tab(host)

    def summary_table_keys(self, metrics):
        return [
            "duration_s", "total_distance",
            "mean_speed", "max_speed", "median_speed",
            "p90_speed", "p99_speed",
            "mobility_time_s", "immobility_time_s",
            "tortuosity",
            "frames_detected", "total_frames", "detection_rate_pct",
            "unit",
            "entry_rule", "min_dwell_s",
            "latency_first_entry_s",
            "pause_count", "pause_total_s", "pause_mean_s", "pause_longest_s",
            "triplets_total_count",
            "triplets_acceptable_count",
            "triplets_unacceptable_count",
            "sar_count",
            "first_arm",
            "low_activity_flag",
            "alternation_pct",
        ]

    def populate_results_tab(self, host, metrics):
        """Fill the Y-Maze table with the key alternation + per-arm rows.
        Mirrors the summary line ordering in the Excel export."""
        if not hasattr(host, "_ym_table") or not metrics:
            return
        from PyQt5.QtWidgets import QTableWidgetItem
        from .zones import ARM_LABELS
        rows = [
            ("Entry rule",             metrics.get("entry_rule")),
            ("Min dwell (s)",          metrics.get("min_dwell_s")),
            ("Entry sequence",         metrics.get("entry_sequence")),
            ("All triplets",           metrics.get("triplets_all")),
            ("Acceptable triplets",    metrics.get("triplets_acceptable")),
            ("Unacceptable triplets",  metrics.get("triplets_unacceptable")),
            ("Total entries",          metrics.get("total_entries")),
            ("Triplets (total)",       metrics.get("triplets_total_count")),
            ("Triplets (acceptable)",  metrics.get("triplets_acceptable_count")),
            ("Triplets (unacceptable)",
                                       metrics.get("triplets_unacceptable_count")),
            ("Alternation (%)",        metrics.get("alternation_pct")),
            ("Alternations (count)",   metrics.get("alternations")),
            ("Same-Arm Returns (SAR)", metrics.get("sar_count")),
            ("First arm entered",      metrics.get("first_arm")),
            ("Low-activity flag (<8 entries)",
                                       metrics.get("low_activity_flag")),
            ("Latency to first entry (s)",
                                       metrics.get("latency_first_entry_s")),
        ]
        for name in ("arm_a", "arm_b", "arm_c"):
            rows.append((f"{ARM_LABELS[name]} entries",      metrics.get(f"entries_{name}")))
            rows.append((f"{ARM_LABELS[name]} entries (%)",  metrics.get(f"pct_entries_{name}")))
            rows.append((f"{ARM_LABELS[name]} time (s)",     metrics.get(f"time_{name}_s")))
            rows.append((f"{ARM_LABELS[name]} time (%)",     metrics.get(f"pct_time_{name}")))
            rows.append((f"{ARM_LABELS[name]} mean dwell (s)",
                                                             metrics.get(f"mean_dwell_{name}_s")))
        rows.append(("Neutral entries", metrics.get("entries_neutral_zone")))
        rows.append(("Neutral time (s)", metrics.get("time_neutral_zone_s")))
        # Filter out rows with no value (e.g. if a metric wasn't computed).
        rows = [(k, v) for k, v in rows if v is not None]
        t = host._ym_table
        t.setUpdatesEnabled(False)
        try:
            t.setRowCount(len(rows))
            for r, (k, v) in enumerate(rows):
                t.setItem(r, 0, QTableWidgetItem(str(k)))
                t.setItem(r, 1, QTableWidgetItem(str(v)))
        finally:
            t.setUpdatesEnabled(True)

    def compute_metrics(self, results, settings, fps, px_per_cm):
        # Convert arm normalized polygons to pixel polygons for metric calc.
        vw = settings.get("video_w") or 1
        vh = settings.get("video_h") or 1
        arms_norm = settings.get("arms_norm") or {}
        arms_px = {
            name: [(int(x * vw), int(y * vh)) for (x, y) in pts]
            for name, pts in arms_norm.items() if pts
        }
        neutral_norm = settings.get("neutral_norm") or []
        neutral_px = [(int(x * vw), int(y * vh)) for (x, y) in neutral_norm]
        ym_settings = dict(settings)
        ym_settings["arms"] = arms_px
        ym_settings["neutral"] = neutral_px
        return ym_metrics.compute(results, ym_settings, fps, px_per_cm)

    def zone_bar_data(self, host):
        # Per-arm + neutral, as share-of-total %.
        m = getattr(host, "metrics", None) or {}
        labels = ["Arm A", "Arm B", "Arm C", "Neutral"]
        times_s = [float(m.get(k, 0.0) or 0.0) for k in
                   ("time_arm_a_s", "time_arm_b_s", "time_arm_c_s",
                    "time_neutral_zone_s")]
        total = sum(times_s)
        values = [(t / total * 100.0) if total > 0 else 0.0 for t in times_s]
        colors = ["#E8A87C", "#7FA6D9", "#8FC79A", "#E4D3AE"]
        return (labels, values, colors, lambda v: f"{v:.1f}%",
                "Time per Arm (%)", "Share (%)")

    def export_columns(self):
        return list(ym_metrics.EXPORT_COLUMNS)

    def batch_schema(self):
        # Section-grouped layout for the combined "All Animals" master
        # sheet. See ym_metrics.BATCH_SCHEMA.
        return list(ym_metrics.BATCH_SCHEMA)

    @staticmethod
    def _collect_ym_state(host):
        """Single read of all Y-Maze geometry + UI state used by both
        contribute_to_snapshot (tracker payload) and snapshot_extras
        (per-video persistence). Centralizing here prevents the two paths
        from drifting. host is always a Y-Maze tab here, so all the
        ym_* widgets exist by the time these methods are called."""
        zd = host.zone_drawer
        arms_norm = {}
        for name in ym_zones.ARM_NAMES:
            z = zd.get_zone(name)
            arms_norm[name] = (list(z["geometry"])
                               if (z and z.get("geometry")) else [])
        nz = zd.get_zone("neutral_zone")
        neutral_norm = (list(nz["geometry"])
                        if (nz and nz.get("geometry")) else [])
        return {
            "arms_norm":     arms_norm,
            "neutral_norm":  neutral_norm,
            "entry_rule":    host.combo_ym_rule.currentData(),
            "min_dwell_s":   float(host.spin_min_dwell.value()),
            "ym_hub":        (tuple(host._ym_hub)
                              if getattr(host, "_ym_hub", None) is not None else None),
            "ym_endpoints":  ([tuple(p) for p in host._ym_endpoints]
                              if getattr(host, "_ym_endpoints", None) else None),
            "arm_length_cm": float(host.spin_ym_arm_length_cm.value()),
            "ym_mode":       ("template" if host.rb_ym_template.isChecked()
                              else "freehand"),
            "arm_width":     float(host.spin_ym_arm_width.value()),
        }

    def contribute_to_snapshot(self, host, snapshot):
        """Inject arm polygons + a tracker arena built from them so the
        run uses the user-defined Y-maze geometry instead of the OF
        auto-from-movement default."""
        zd = getattr(host, "zone_drawer", None)
        if zd is None:
            return
        state = self._collect_ym_state(host)
        snapshot["arms_norm"] = state["arms_norm"]
        snapshot["neutral_norm"] = state["neutral_norm"]
        snapshot["entry_rule"] = state["entry_rule"]
        snapshot["min_dwell_s"] = state["min_dwell_s"]
        if state["ym_hub"] is not None:
            snapshot["ym_hub"] = state["ym_hub"]
        if state["ym_endpoints"]:
            snapshot["ym_endpoints"] = state["ym_endpoints"]
        if state["arm_length_cm"]:
            snapshot["arm_length_cm"] = state["arm_length_cm"]
        # Perspective state — warp every tracker frame so arms appear at
        # canonical 120° angles. The plugin's build_tracking_homography
        # reads these to rebuild H at run time.
        snapshot["ym_perspective"] = bool(getattr(host, "_ym_perspective_on", False))
        if snapshot["ym_perspective"]:
            # Save the ORIGINAL (pre-warp) hub + endpoints so the tracker
            # can recompute the homography even if the live overlay has
            # been moved to canonical positions.
            orig_hub = getattr(host, "_ym_original_hub", None)
            orig_eps = getattr(host, "_ym_original_endpoints", None)
            if orig_hub and orig_eps:
                snapshot["ym_original_hub"] = tuple(orig_hub)
                snapshot["ym_original_endpoints"] = [tuple(p) for p in orig_eps]
        # Y-Maze never uses the OF arena/grid rendering — clear it so
        # apply_settings doesn't sync a polygon into zd.arena (which would
        # paint a giant "Arena" outline + the 4x4 cell grid on top of the
        # Y-maze view). The tracker arena is built on the fly from
        # arms_norm by _do_track_and_export's fallback.
        snapshot["arena"] = None
        snapshot["arena_auto_movement"] = False
        # Force-clear the live zone-drawer arena too so the change is
        # immediate without waiting for a subsequent video reload.
        if zd.arena is not None:
            zd.arena = None
            zd.update()

    # OF-specific keys to drop from the Y-maze Excel's Video Config.
    # cage_w_cm/cage_h_cm are OF cage dimensions (Y-maze uses arm_length_cm
    # instead); the rest are OF behaviors that don't apply here.
    _OF_ONLY_VIDEO_CONFIG_KEYS = (
        "cage_w_cm", "cage_h_cm", "cage_shape",
        "zone_mode", "center_pct",
        "arena_define_mode", "arena_pad_pct", "arena_auto_movement",
        "cell_min_dwell", "cell_min_dwell_s", "perspective", "arrow",
    )

    def filter_video_config(self, snapshot):
        out = dict(snapshot)
        for k in self._OF_ONLY_VIDEO_CONFIG_KEYS:
            out.pop(k, None)
        return out

    def live_overlay_label(self):
        return "Live arm overlay during tracking (slower)"

    def cell_highlight_toggle_specs(self, host):
        """Returns 'Hide X' toggles: checked = hidden, unchecked = shown.
        Defaults unchecked so post-tracking shows everything by default."""
        zd = host.zone_drawer
        return [
            ("Hide arm numbers (A,B,C,N)",
             lambda: not zd._arm_show_numbers,
             lambda hide: zd.set_arm_show_numbers(not hide)),
            ("Hide per-arm timer (SS.cc)",
             lambda: not zd._arm_show_timer,
             lambda hide: zd.set_arm_show_timer(not hide)),
            ("Hide per-arm entry count (#)",
             lambda: not zd._arm_show_entries,
             lambda hide: zd.set_arm_show_entries(not hide)),
        ]

    def preflight_zone_problem(self, snapshot):
        if len(snapshot.get("neutral_norm") or []) < 3:
            return "no neutral zone — draw N (arm entries are counted from it)"
        return None

    def preflight_auto_scale_warning(self, snapshot):
        arm_cm = float(snapshot.get("arm_length_cm") or 0)
        if arm_cm <= 0:
            return "auto-cal selected but arm length = 0"
        # Hub + endpoints must exist for spoke measurement.
        if not snapshot.get("ym_hub") or len(snapshot.get("ym_endpoints") or []) < 3:
            return "auto-cal selected but Y template (hub + 3 endpoints) not set"
        return None

    def build_tracking_homography(self, snapshot, video_size):
        """Build the Y-maze perspective-correction homography for the
        tracker. Maps the user's tilted hub + endpoints onto the canonical
        symmetric 120° Y, so every frame the tracker processes has the
        maze appearing top-down. Returns None when perspective is off."""
        if not snapshot.get("ym_perspective"):
            return None
        hub = snapshot.get("ym_original_hub") or snapshot.get("ym_hub")
        endpoints = (snapshot.get("ym_original_endpoints")
                     or snapshot.get("ym_endpoints"))
        if not hub or not endpoints or len(endpoints) < 3:
            return None
        return ym_zones.build_y_homography(hub, endpoints, video_size)

    def compute_auto_px_per_cm(self, snapshot, video_size):
        """Y-maze auto-cal: px/cm = average spoke pixel length / arm_length_cm.
        Spoke length = pixel distance from hub to each endpoint, averaged
        over the 3 spokes. Hub + endpoints are normalized coords in snapshot."""
        if not video_size:
            return None
        vw, vh = video_size
        hub = snapshot.get("ym_hub")
        endpoints = snapshot.get("ym_endpoints") or []
        arm_cm = float(snapshot.get("arm_length_cm") or 0.0)
        if not hub or len(endpoints) < 3 or arm_cm <= 0 or not vw or not vh:
            return None
        import math
        hub_px = (hub[0] * vw, hub[1] * vh)
        spokes = []
        for ep in endpoints[:3]:
            ex, ey = ep[0] * vw, ep[1] * vh
            spokes.append(math.hypot(ex - hub_px[0], ey - hub_px[1]))
        if not spokes:
            return None
        return (sum(spokes) / len(spokes)) / arm_cm

    def refresh_scale_step_visibility(self, host, calib_mode):
        """Hide OF cage W×H widget; mirror arm-length widget visibility to auto mode."""
        if hasattr(host, "_cage_size_widget"):
            host._cage_size_widget.setVisible(False)
        if hasattr(host, "lbl_calib_auto_hint"):
            host.lbl_calib_auto_hint.setVisible(False)
        if hasattr(host, "_ym_arm_length_widget"):
            host._ym_arm_length_widget.setVisible(calib_mode == "auto")

    def snapshot_extras(self, host):
        state = self._collect_ym_state(host)
        return {
            "arms_norm": state["arms_norm"],
            "entry_rule": state["entry_rule"],
            "min_dwell_s": state["min_dwell_s"],
            "ym_mode": state["ym_mode"],
            "arm_width": state["arm_width"],
            "ym_hub": state["ym_hub"],
            "ym_endpoints": state["ym_endpoints"],
        }

    def apply_extras(self, host, extras):
        if not isinstance(extras, dict):
            return
        zd = host.zone_drawer
        arms_norm = extras.get("arms_norm") or {}
        # Always seed all 3 arm zones (so handles render).
        for name in ym_zones.ARM_NAMES:
            z = ym_zones.empty_arm_zone(name)
            z["geometry"] = list(arms_norm.get(name) or [])
            zd.add_zone(z)
        if extras.get("entry_rule") and hasattr(host, "combo_ym_rule"):
            idx = host.combo_ym_rule.findData(extras["entry_rule"])
            if idx >= 0:
                host.combo_ym_rule.setCurrentIndex(idx)
        if extras.get("min_dwell_s") is not None:
            try:
                host.spin_min_dwell.setValue(float(extras["min_dwell_s"]))
            except Exception:
                pass
        if extras.get("ym_mode") == "template" and hasattr(host, "rb_ym_template"):
            host.rb_ym_template.setChecked(True)
        if extras.get("arm_width") is not None and hasattr(host, "spin_ym_arm_width"):
            try:
                host.spin_ym_arm_width.setValue(float(extras["arm_width"]))
            except Exception:
                pass
        if extras.get("ym_hub"):
            host._ym_hub = tuple(extras["ym_hub"])
        else:
            host._ym_hub = None
        if extras.get("ym_endpoints"):
            host._ym_endpoints = [tuple(p) for p in extras["ym_endpoints"]]
        else:
            host._ym_endpoints = None
        zd.emit_change("y-maze template restored")
