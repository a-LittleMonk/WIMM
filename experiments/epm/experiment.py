"""EPMExperiment plugin."""
from experiments.base import Experiment
from . import zones as epm_zones
from . import metrics as epm_metrics
from . import ui as epm_ui


class EPMExperiment(Experiment):
    name = "Elevated Plus Maze"
    key = "epm"

    # Snapshot keys dropped from the per-video Video Config sheet because
    # they're OF-only (cage dims, arena modes, etc).
    _OF_ONLY_VIDEO_CONFIG_KEYS = (
        "cage_w_cm", "cage_h_cm", "cage_shape",
        "zone_mode", "center_pct",
        "arena_define_mode", "arena_pad_pct", "arena_auto_movement",
        "cell_min_dwell", "cell_min_dwell_s", "perspective", "arrow",
    )

    def graph_names(self):
        """EPM has no 4×4 cell grid — exclude Cell Time. Triplets is
        Y-Maze only."""
        from gui.graph_style import GRAPH_NAMES
        return [g for g in GRAPH_NAMES if g not in ("Cell Time", "Triplets")]

    def graph_caps(self, graph_name):
        """Expose the plus-arm thickness control on the shape-bearing graphs
        so the Customize-Graphs preview can re-shape the synthetic + maze."""
        if graph_name in ("Trajectory", "Heatmap"):
            return {"plus_thickness"}
        return set()

    def canonical_arm_layout(self, host):
        """Map the drawn arms onto the canonical plus: closed (vertical) arms
        → N/S, open (horizontal) arms → E/W. Lets the output Trajectory/
        Heatmap render on the same idealized + as the styling preview."""
        zd = getattr(host, "zone_drawer", None)
        if zd is None:
            return None
        arms = []
        for name in epm_zones.ARM_NAMES:
            z = zd.get_zone(name)
            geom = z.get("geometry") if z else None
            if not geom or len(geom) < 3:
                continue
            kind = (z.get("style") or {}).get("epm_kind", "closed")
            cx = sum(p[0] for p in geom) / len(geom)
            cy = sum(p[1] for p in geom) / len(geom)
            arms.append({"poly": [tuple(p) for p in geom],
                         "kind": kind, "cx": cx, "cy": cy})
        if len(arms) < 2:
            return None
        cz = zd.get_zone("center_zone")
        czg = cz.get("geometry") if cz else None
        if czg and len(czg) >= 3:
            hub = (sum(p[0] for p in czg) / len(czg),
                   sum(p[1] for p in czg) / len(czg))
        else:
            hub = (sum(a["cx"] for a in arms) / len(arms),
                   sum(a["cy"] for a in arms) / len(arms))
        out = []
        # Closed → vertical: the higher one (smaller image y) is N, other S.
        closed = sorted([a for a in arms if a["kind"] == "closed"],
                        key=lambda a: a["cy"])
        for a, d in zip(closed, [(0.0, 1.0), (0.0, -1.0)]):
            out.append({"poly": a["poly"], "cdir": d})
        # Open → horizontal: the leftmost (smaller image x) is W, other E.
        opens = sorted([a for a in arms if a["kind"] == "open"],
                       key=lambda a: a["cx"])
        for a, d in zip(opens, [(-1.0, 0.0), (1.0, 0.0)]):
            out.append({"poly": a["poly"], "cdir": d})
        if not out:
            return None
        return {"hub": hub, "arms": out}

    def zone_bar_data(self, host):
        # The EPM readout: time in open vs closed arms vs center.
        m = getattr(host, "metrics", None) or {}
        labels = ["Open arms", "Closed arms", "Center"]
        values = [
            float(m.get("time_open_total_s", 0.0) or 0.0),
            float(m.get("time_closed_total_s", 0.0) or 0.0),
            float(m.get("time_center_s", 0.0) or 0.0),
        ]
        colors = ["#E8A87C", "#7FA6D9", "#E4D3AE"]
        return (labels, values, colors, lambda v: f"{v:.1f}s",
                "Time per Arm Type", "Time (s)")

    # ── Setup-card summaries ──────────────────────────────────────────
    def summary_geometry(self, host):
        from . import zones as _z
        zd = getattr(host, "zone_drawer", None)
        if zd is None:
            return "Not defined"
        n = sum(1 for a in _z.ARM_NAMES
                if len((zd.get_zone(a) or {}).get("geometry") or []) >= 3)
        if not n:
            return "Not defined"
        mode = ("Plus template" if host.rb_epm_template.isChecked()
                else "Manual")
        return f"{mode} · {n}/4 arms"

    def summary_zones(self, host):
        kinds = list(getattr(host, "_epm_arm_kinds", {}).values())
        return f"{kinds.count('open')} open · {kinds.count('closed')} closed"

    def zones_schema(self, host):
        geoms = epm_zones.get_arm_geoms(host)
        arm_kinds = getattr(host, "_epm_arm_kinds", None)
        return epm_zones.build_schema_from_arms(geoms, arm_kinds=arm_kinds)

    def build_geometry_step(self, host):
        return epm_ui.build_geometry_step(host)

    def build_results_tabs(self, host, right_tabs):
        return epm_ui.build_results_tab(host)

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
            "latency_first_open_entry_s",
            "latency_first_entry_s",
            "pause_count", "pause_total_s", "pause_mean_s", "pause_longest_s",
            "first_arm",
            "low_activity_flag",
            "total_entries",
            "entries_open_total", "entries_closed_total", "entries_center",
            "time_open_total_s", "time_closed_total_s", "time_center_s",
            "pct_time_open_of_arms", "pct_time_closed_of_arms", "pct_time_center",
            "pct_entries_open", "pct_entries_closed",
        ]

    def populate_results_tab(self, host, metrics):
        if not hasattr(host, "_epm_table") or not metrics:
            return
        from PyQt5.QtWidgets import QTableWidgetItem
        from .zones import ARM_LABELS
        rows = [
            ("Entry rule",                metrics.get("entry_rule")),
            ("Min dwell (s)",             metrics.get("min_dwell_s")),
            ("Entry sequence",            metrics.get("entry_sequence")),
            ("Total entries",             metrics.get("total_entries")),
            ("Open-arm entries (total)",  metrics.get("entries_open_total")),
            ("Closed-arm entries (total)", metrics.get("entries_closed_total")),
            ("Center entries",            metrics.get("entries_center")),
            ("Time open arms (s)",        metrics.get("time_open_total_s")),
            ("Time closed arms (s)",      metrics.get("time_closed_total_s")),
            ("Time center (s)",           metrics.get("time_center_s")),
            ("Open arms time (% of arm time)",   metrics.get("pct_time_open_of_arms")),
            ("Closed arms time (% of arm time)", metrics.get("pct_time_closed_of_arms")),
            ("Center time (% of session)",       metrics.get("pct_time_center")),
            ("Open entries (% of arm entries)",  metrics.get("pct_entries_open")),
            ("Closed entries (% of arm entries)", metrics.get("pct_entries_closed")),
            ("Latency to first open entry (s)",
                                          metrics.get("latency_first_open_entry_s")),
            ("Latency to first entry (s)", metrics.get("latency_first_entry_s")),
            ("First arm entered",         metrics.get("first_arm")),
            ("Low-activity flag (<10 open+closed)",
                                          metrics.get("low_activity_flag")),
        ]
        for name in epm_zones.ARM_NAMES:
            lbl = ARM_LABELS[name]
            kind = metrics.get(f"kind_{name}") or ""
            tag = f" ({kind})" if kind else ""
            rows.append((f"{lbl}{tag} entries",      metrics.get(f"entries_{name}")))
            rows.append((f"{lbl}{tag} entries (%)",  metrics.get(f"pct_entries_{name}")))
            rows.append((f"{lbl}{tag} time (s)",     metrics.get(f"time_{name}_s")))
            rows.append((f"{lbl}{tag} time (%)",     metrics.get(f"pct_time_{name}")))
            rows.append((f"{lbl}{tag} mean dwell (s)",
                                                     metrics.get(f"mean_dwell_{name}_s")))
        rows = [(k, v) for k, v in rows if v is not None]
        t = host._epm_table
        t.setUpdatesEnabled(False)
        try:
            t.setRowCount(len(rows))
            for r, (k, v) in enumerate(rows):
                t.setItem(r, 0, QTableWidgetItem(str(k)))
                t.setItem(r, 1, QTableWidgetItem(str(v)))
        finally:
            t.setUpdatesEnabled(True)

    def compute_metrics(self, results, settings, fps, px_per_cm):
        vw = settings.get("video_w") or 1
        vh = settings.get("video_h") or 1
        arms_norm = settings.get("arms_norm") or {}
        arms_px = {
            name: [(int(x * vw), int(y * vh)) for (x, y) in pts]
            for name, pts in arms_norm.items() if pts
        }
        center_norm = settings.get("center_norm") or []
        center_px = [(int(x * vw), int(y * vh)) for (x, y) in center_norm]
        epm_settings = dict(settings)
        epm_settings["arms"] = arms_px
        epm_settings["center"] = center_px
        return epm_metrics.compute(results, epm_settings, fps, px_per_cm)

    def export_columns(self):
        return list(epm_metrics.EXPORT_COLUMNS)

    def batch_schema(self):
        return list(epm_metrics.BATCH_SCHEMA)

    @staticmethod
    def _collect_epm_state(host):
        """Centralized read of all EPM geometry + UI state. Used by
        contribute_to_snapshot (tracker payload) and snapshot_extras
        (per-video persistence)."""
        zd = host.zone_drawer
        arms_norm = {}
        for name in epm_zones.ARM_NAMES:
            z = zd.get_zone(name)
            arms_norm[name] = (list(z["geometry"])
                               if (z and z.get("geometry")) else [])
        cz = zd.get_zone("center_zone")
        center_norm = (list(cz["geometry"])
                       if (cz and cz.get("geometry")) else [])
        return {
            "arms_norm":     arms_norm,
            "center_norm":   center_norm,
            "arm_kinds":     dict(getattr(host, "_epm_arm_kinds", {})),
            "arm_custom_names": dict(getattr(host, "_epm_arm_custom_names", {})),
            "entry_rule":    host.combo_epm_rule.currentData(),
            "min_dwell_s":   float(host.spin_min_dwell.value()),
            "epm_hub":       (tuple(host._epm_hub)
                              if getattr(host, "_epm_hub", None) is not None else None),
            "epm_endpoints": ([tuple(p) for p in host._epm_endpoints]
                              if getattr(host, "_epm_endpoints", None) else None),
            "arm_length_cm": float(host.spin_epm_arm_length_cm.value())
                             if hasattr(host, "spin_epm_arm_length_cm") else 30.0,
            "epm_mode":      ("template" if host.rb_epm_template.isChecked()
                              else "freehand"),
            "arm_width":     float(host.spin_epm_arm_width.value())
                             if hasattr(host, "spin_epm_arm_width") else 0.10,
            "center_size":   float(host.spin_epm_center_size.value())
                             if hasattr(host, "spin_epm_center_size") else 0.06,
        }

    def contribute_to_snapshot(self, host, snapshot):
        zd = getattr(host, "zone_drawer", None)
        if zd is None:
            return
        state = self._collect_epm_state(host)
        snapshot["arms_norm"] = state["arms_norm"]
        snapshot["center_norm"] = state["center_norm"]
        snapshot["arm_kinds"] = state["arm_kinds"]
        snapshot["arm_custom_names"] = state["arm_custom_names"]
        snapshot["entry_rule"] = state["entry_rule"]
        snapshot["min_dwell_s"] = state["min_dwell_s"]
        if state["epm_hub"] is not None:
            snapshot["epm_hub"] = state["epm_hub"]
        if state["epm_endpoints"]:
            snapshot["epm_endpoints"] = state["epm_endpoints"]
        if state["arm_length_cm"]:
            snapshot["arm_length_cm"] = state["arm_length_cm"]
        snapshot["epm_perspective"] = bool(
            getattr(host, "_epm_perspective_on", False))
        if snapshot["epm_perspective"]:
            orig_hub = getattr(host, "_epm_original_hub", None)
            orig_eps = getattr(host, "_epm_original_endpoints", None)
            if orig_hub and orig_eps:
                snapshot["epm_original_hub"] = tuple(orig_hub)
                snapshot["epm_original_endpoints"] = [tuple(p) for p in orig_eps]
            # Persist the EXACT homography the user applied via the perspective
            # dialog (+ its square output size). This is the single source of
            # truth: tracking and the post-tracking preview both rebuild from
            # it, so what the user configures == what gets tracked == what the
            # preview shows. (build_plus_homography from the Step-2 template is
            # only a fallback for older snapshots that predate this key.)
            H = getattr(host, "_H", None)
            if H is not None:
                try:
                    snapshot["epm_homography"] = [
                        [float(v) for v in row] for row in H
                    ]
                except Exception:
                    pass
            ws = getattr(host, "_perspective_warp_size", None)
            if ws:
                snapshot["epm_warp_size"] = [int(ws[0]), int(ws[1])]
        # EPM never uses the OF arena polygon — clear it so the base
        # paintEvent doesn't draw the giant arena + 4×4 grid over the
        # plus-maze view.
        snapshot["arena"] = None
        snapshot["arena_auto_movement"] = False
        if zd.arena is not None:
            zd.arena = None
            zd.update()

    def filter_video_config(self, snapshot):
        out = dict(snapshot)
        for k in self._OF_ONLY_VIDEO_CONFIG_KEYS:
            out.pop(k, None)
        return out

    def live_overlay_label(self):
        return "Live arm overlay during tracking (slower)"

    def cell_highlight_toggle_specs(self, host):
        zd = host.zone_drawer
        return [
            ("Hide arm labels (N,S,E,W,C)",
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
        if len(snapshot.get("center_norm") or []) < 3:
            return "no center zone — draw the center (arm entries are counted from it)"
        return None

    def preflight_auto_scale_warning(self, snapshot):
        arm_cm = float(snapshot.get("arm_length_cm") or 0)
        if arm_cm <= 0:
            return "auto-cal selected but arm length = 0"
        if not snapshot.get("epm_hub") or len(snapshot.get("epm_endpoints") or []) < 4:
            return "auto-cal selected but EPM template (hub + 4 endpoints) not set"
        return None

    def build_tracking_homography(self, snapshot, video_size):
        if not snapshot.get("epm_perspective"):
            return None
        # Prefer the exact homography the user applied in the perspective
        # dialog — it's what they saw corrected, and the EPM zones were snapped
        # into its (square) warp space. build_plus_homography below is only a
        # fallback for snapshots saved before epm_homography was persisted.
        H_saved = snapshot.get("epm_homography")
        ws = snapshot.get("epm_warp_size")
        if H_saved is not None and ws and len(ws) == 2 and ws[0] and ws[1]:
            import numpy as np
            try:
                return np.array(H_saved, dtype=np.float64), (int(ws[0]), int(ws[1]))
            except Exception:
                pass
        hub = snapshot.get("epm_original_hub") or snapshot.get("epm_hub")
        endpoints = (snapshot.get("epm_original_endpoints")
                     or snapshot.get("epm_endpoints"))
        if not hub or not endpoints or len(endpoints) < 4:
            return None
        return epm_zones.build_plus_homography(hub, endpoints, video_size)

    def compute_auto_px_per_cm(self, snapshot, video_size):
        """EPM auto-cal: px/cm = mean spoke length (hub→endpoint) / arm_length_cm.
        Averaged over 4 spokes."""
        if not video_size:
            return None
        vw, vh = video_size
        hub = snapshot.get("epm_hub")
        endpoints = snapshot.get("epm_endpoints") or []
        arm_cm = float(snapshot.get("arm_length_cm") or 0.0)
        if not hub or len(endpoints) < 4 or arm_cm <= 0 or not vw or not vh:
            return None
        import math
        hub_px = (hub[0] * vw, hub[1] * vh)
        spokes = []
        for ep in endpoints[:4]:
            ex, ey = ep[0] * vw, ep[1] * vh
            spokes.append(math.hypot(ex - hub_px[0], ey - hub_px[1]))
        if not spokes:
            return None
        return (sum(spokes) / len(spokes)) / arm_cm

    def refresh_scale_step_visibility(self, host, calib_mode):
        if hasattr(host, "_cage_size_widget"):
            host._cage_size_widget.setVisible(False)
        if hasattr(host, "lbl_calib_auto_hint"):
            host.lbl_calib_auto_hint.setVisible(False)
        if hasattr(host, "_epm_arm_length_widget"):
            host._epm_arm_length_widget.setVisible(calib_mode == "auto")

    def snapshot_extras(self, host):
        state = self._collect_epm_state(host)
        return {
            "arms_norm":         state["arms_norm"],
            "center_norm":       state["center_norm"],
            "arm_kinds":         state["arm_kinds"],
            "arm_custom_names":  state["arm_custom_names"],
            "entry_rule":        state["entry_rule"],
            "min_dwell_s":       state["min_dwell_s"],
            "epm_mode":          state["epm_mode"],
            "arm_width":         state["arm_width"],
            "center_size":       state["center_size"],
            "epm_hub":           state["epm_hub"],
            "epm_endpoints":     state["epm_endpoints"],
        }

    def apply_extras(self, host, extras):
        if not isinstance(extras, dict):
            return
        host._epm_restoring = True
        try:
            self._apply_extras(host, extras)
        finally:
            host._epm_restoring = False
        zd = host.zone_drawer
        # Saved arm / centre shapes last, exactly as saved.
        arm_names_norm = extras.get("arms_norm") or {}
        for name in epm_zones.ARM_NAMES:
            kind = (getattr(host, "_epm_arm_kinds", None) or
                    epm_zones.DEFAULT_ARM_KINDS).get(name,
                                                     epm_zones.DEFAULT_ARM_KINDS[name])
            z = epm_zones.empty_arm_zone(name, kind)
            z["geometry"] = list(arm_names_norm.get(name) or [])
            zd.add_zone(z)
        if extras.get("center_norm"):
            cz = epm_zones.empty_center_zone()
            cz["geometry"] = list(extras["center_norm"])
            zd.add_zone(cz)
        zd.emit_change("epm template restored")

    def _apply_extras(self, host, extras):
        zd = host.zone_drawer
        arm_kinds = extras.get("arm_kinds") or {}
        if arm_kinds:
            host._epm_arm_kinds = {
                n: arm_kinds.get(n, epm_zones.DEFAULT_ARM_KINDS[n])
                for n in epm_zones.ARM_NAMES
            }
            # Sync UI dropdowns if present.
            combos = getattr(host, "_epm_kind_combos", {})
            for n, combo in combos.items():
                idx = combo.findData(host._epm_arm_kinds[n])
                if idx >= 0:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(idx)
                    combo.blockSignals(False)
        arm_names_norm = extras.get("arms_norm") or {}
        for name in epm_zones.ARM_NAMES:
            kind = (getattr(host, "_epm_arm_kinds", None) or
                    epm_zones.DEFAULT_ARM_KINDS).get(name,
                                                     epm_zones.DEFAULT_ARM_KINDS[name])
            z = epm_zones.empty_arm_zone(name, kind)
            z["geometry"] = list(arm_names_norm.get(name) or [])
            zd.add_zone(z)
        if extras.get("center_norm"):
            cz = epm_zones.empty_center_zone()
            cz["geometry"] = list(extras["center_norm"])
            zd.add_zone(cz)
        custom_names = extras.get("arm_custom_names") or {}
        if custom_names:
            host._epm_arm_custom_names = {
                n: custom_names.get(n, "") for n in epm_zones.ARM_NAMES
            }
            edits = getattr(host, "_epm_name_edits", {})
            for n, edit in edits.items():
                edit.blockSignals(True)
                edit.setText(host._epm_arm_custom_names.get(n, ""))
                edit.setVisible(
                    host._epm_arm_kinds.get(n) == "custom"
                )
                edit.blockSignals(False)
        if extras.get("entry_rule") and hasattr(host, "combo_epm_rule"):
            idx = host.combo_epm_rule.findData(extras["entry_rule"])
            if idx >= 0:
                host.combo_epm_rule.setCurrentIndex(idx)
        if extras.get("min_dwell_s") is not None:
            try:
                host.spin_min_dwell.setValue(float(extras["min_dwell_s"]))
            except Exception:
                pass
        if extras.get("epm_mode") == "template" and hasattr(host, "rb_epm_template"):
            host.rb_epm_template.setChecked(True)
        if extras.get("arm_width") is not None and hasattr(host, "spin_epm_arm_width"):
            try:
                host.spin_epm_arm_width.setValue(float(extras["arm_width"]))
            except Exception:
                pass
        if extras.get("center_size") is not None and hasattr(host, "spin_epm_center_size"):
            try:
                host.spin_epm_center_size.setValue(float(extras["center_size"]))
            except Exception:
                pass
        if extras.get("epm_hub"):
            host._epm_hub = tuple(extras["epm_hub"])
        else:
            host._epm_hub = None
        if extras.get("epm_endpoints"):
            host._epm_endpoints = [tuple(p) for p in extras["epm_endpoints"]]
        else:
            host._epm_endpoints = None
        if (getattr(host, "rb_epm_template", None) is not None and host.rb_epm_template.isChecked()
                and host._epm_hub and host._epm_endpoints):
            from .ui import _start_template
            _start_template(host)              # hub / tip handles (no rebuild now)
