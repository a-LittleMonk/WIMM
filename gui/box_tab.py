"""BoxTab — the screen for every box-family test (place preference,
light–dark, three-chamber, zero maze, water maze, T-maze, radial maze).

Thin subclass of OpenFieldTab like NORTab / EPMTab: the experiment plugin
owns the setup cards, zones and metrics; this class adds the live zone
overlay (current zone highlighted, per-zone time + entry count, same
min-dwell rule as the results) and the Scale-card labels.
"""
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QPen

from gui.open_field_tab import OpenFieldTab
from gui.experiment_batch_tab import ExperimentBatchTab
from experiments.box import engine, geometry as geo
from experiments.box.ui import ZONE_PREFIX, refresh_zones


class BoxTab(OpenFieldTab):
    def __init__(self, config, experiment):
        super().__init__(config, experiment=experiment)
        exp = self.experiment
        try:
            tab = exp.build_results_tabs(self, self._excel_tabs)
            if tab is not None and hasattr(self, "_excel_tabs"):
                self._excel_tabs.insertTab(1, tab, exp.results_title)
        except Exception:
            pass
        self._reset_live()
        self._box_replay_cache = None
        zd = self.zone_drawer
        zd.set_overlay_renderer(
            lambda p, ox, oy, dw, dh: paint_box_overlay(self, zd, p, ox, oy, dw, dh))
        self._install_box_scale()
        if exp.uses_nose and hasattr(self, "combo_body_style"):
            i = self.combo_body_style.findData("ends")
            if i >= 0:
                self.combo_body_style.setCurrentIndex(i)

    # ── Scale card ────────────────────────────────────────────────────
    def _cfg_key(self, dim):
        return f"{self.experiment.key}_cage_{dim}_cm"

    def _install_box_scale(self):
        exp = self.experiment
        if not hasattr(self, "spin_cage_w"):
            return
        kind = exp.scale[0]
        w0 = float(self.config.get(self._cfg_key("w")) or exp.scale[1])
        h0 = (w0 if kind == "square"
              else float(self.config.get(self._cfg_key("h")) or exp.scale[2]))
        for spin, val in ((self.spin_cage_w, w0), (self.spin_cage_h, h0)):
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)
        if kind == "square":
            self.lbl_cage_w.setText(exp.scale[2])
            for w in ("lbl_cage_x", "lbl_cage_h", "spin_cage_h"):
                if hasattr(self, w):
                    getattr(self, w).setVisible(False)
                    getattr(self, w)._keep_hidden = True
        else:
            self.lbl_cage_w.setText("Width")
            self.lbl_cage_h.setText("Height")

    def _on_cage_size_changed(self, _v=None):
        """Per-test apparatus size (kept apart from Open Field's cage)."""
        if self.experiment.scale[0] == "square":
            self.spin_cage_h.blockSignals(True)
            self.spin_cage_h.setValue(self.spin_cage_w.value())
            self.spin_cage_h.blockSignals(False)
        self.config[self._cfg_key("w")] = float(self.spin_cage_w.value())
        self.config[self._cfg_key("h")] = float(self.spin_cage_h.value())
        win = self.window()
        if hasattr(win, "_save_config"):
            win._save_config()
        self._update_calib_status()
        refresh_zones(self, self.experiment)
        self._recompute_metrics_and_views()

    # ── Live overlay state ────────────────────────────────────────────
    def _reset_live(self):
        self._box_cur = {}           # layer -> current zone
        self._box_pending = {}       # layer -> (zone, frames)
        self._box_last = {}          # layer -> last committed zone
        self._box_times = {}
        self._box_entries = {}

    def begin_tracking(self):
        super().begin_tracking()
        self._reset_live()

    def _zone_at(self, nx, ny, layer):
        H = getattr(self, "_box_H_norm", None)
        if H is None:
            return None
        u, v = geo.to_box(H, [nx], [ny])
        for z in getattr(self, "_box_zone_defs", []) or []:
            if z.layer == layer and bool(z.contains(u, v)[0]):
                return z.name
        return engine.OUT

    def _live_step(self, xy, point):
        zd = self.zone_drawer
        if not (self.video_w and self.video_h):
            return
        layers = [z.layer for z in (getattr(self, "_box_zone_defs", []) or [])
                  if z.point == point]
        if not layers:
            return
        fps = self.fps or 30.0
        dt = 1.0 / fps
        md = float(self.spin_min_dwell.value()) if hasattr(self, "spin_min_dwell") else 0.0
        min_frames = max(1, int(round(md * fps))) if md > 0 else 1
        dwell = {z.layer: z.dwell for z in self._box_zone_defs}
        fill = self._undetected_as()
        for layer in dict.fromkeys(layers):
            mf = min_frames if dwell[layer] else 1
            if xy is None:
                zone = fill.get(layer)
            else:
                zone = self._zone_at(xy[0] / float(self.video_w),
                                     xy[1] / float(self.video_h), layer)
            pz, pf = self._box_pending.get(layer, (None, 0))
            pf = pf + 1 if zone == pz else 1
            self._box_pending[layer] = (zone, pf)
            if pf < mf or zone is None:
                continue
            if zone != self._box_cur.get(layer):
                self._box_cur[layer] = zone
                if zone != self._box_last.get(layer):
                    self._box_entries[zone] = self._box_entries.get(zone, 0) + 1
                    self._box_last[layer] = zone
                self._box_times[zone] = self._box_times.get(zone, 0.0) + pf * dt
            elif pf == mf:
                self._box_times[zone] = self._box_times.get(zone, 0.0) + pf * dt
            else:
                self._box_times[zone] = self._box_times.get(zone, 0.0) + dt
        zd.update()

    def _undetected_as(self):
        """Layer -> zone that frames with no detection count as (e.g.
        Light–Dark's "Count lost frames as dark"), same as the results."""
        exp = self.experiment
        return exp.engine_settings(exp.params_of(self)).get("_undetected_as") or {}

    def _on_tracking_body_pos(self, body_xy):
        zd = self.zone_drawer
        if body_xy is None or not (self.video_w and self.video_h):
            zd.set_body_pos_norm(None)
        else:
            zd.set_body_pos_norm((body_xy[0] / float(self.video_w),
                                  body_xy[1] / float(self.video_h)))
        if self._tracking_active and not self._live_cell_overlay:
            zd.update()
            return
        self._live_step(body_xy, "body")

    def _on_tracking_nose_pos(self, nose_xy):
        if self._tracking_active and not self._live_cell_overlay:
            return
        self._live_step(nose_xy, "nose")

    # ── Scrub replay (exact, cached) ──────────────────────────────────
    def _replay_tables(self):
        res = self.tracking_results
        zones = getattr(self, "_box_zone_defs", []) or []
        H = getattr(self, "_box_H_norm", None)
        if not res or not zones or H is None or not (self.video_w and self.video_h):
            return None
        fps = self.fps or 30.0
        md = float(self.spin_min_dwell.value()) if hasattr(self, "spin_min_dwell") else 0.0
        min_frames = max(1, int(round(md * fps))) if md > 0 else 1
        key = (id(res), len(res), min_frames, tuple(np.round(H, 6).ravel()),
               tuple((z.name, z.layer, len(z.poly)) for z in zones),
               tuple(sorted((getattr(self, "_box_params", {}) or {}).items(), key=str)))
        c = self._box_replay_cache
        if c is not None and c["key"] == key:
            return c
        vw, vh = float(self.video_w), float(self.video_h)

        def col(name, fb=None):
            out = np.full(len(res), np.nan)
            for i, r in enumerate(res):
                val = r.get(name)
                if val is None and fb is not None:
                    val = r.get(fb)
                if val is not None:
                    out[i] = float(val)
            return out
        bx, by = col("x") / vw, col("y") / vh
        nx, ny = col("nose_x", "x") / vw, col("nose_y", "y") / vh
        dt = 1.0 / fps
        tables = {"key": key, "layers": {}}
        fill = self._undetected_as()
        for layer in dict.fromkeys(z.layer for z in zones):
            lz = [z for z in zones if z.layer == layer]
            xs, ys = (nx, ny) if lz[0].point == "nose" else (bx, by)
            u, v = geo.to_box(H, xs, ys)
            raw = engine.classify(u, v, lz)
            if fill.get(layer):
                raw = [fill[layer] if r is None else r for r in raw]
            st = engine.layer_stats(raw, [z.name for z in lz],
                                   min_frames if lz[0].dwell else 1)
            seq = np.array(st.seq, dtype=object)
            cum_t, cum_e = {}, {}
            for z in lz:
                cum_t[z.name] = np.cumsum(seq == z.name) * dt
                starts = np.zeros(len(res))
                for zn, s, _e in st.visits:
                    if zn == z.name:
                        starts[s] = 1
                cum_e[z.name] = np.cumsum(starts)
            tables["layers"][layer] = {"seq": st.seq, "t": cum_t, "e": cum_e}
        self._box_replay_cache = tables
        return tables

    def _push_cell_state_for_frame(self, frame_idx):
        zd = self.zone_drawer
        if not self.tracking_results:
            zd.set_body_pos_norm(None)
            self._reset_live()
            zd.update()
            return
        idx = self._slider_to_results_idx(frame_idx)
        r = self.tracking_results[idx]
        if r.get("x") is not None and self.video_w and self.video_h:
            zd.set_body_pos_norm((r["x"] / float(self.video_w),
                                  r["y"] / float(self.video_h)))
        else:
            zd.set_body_pos_norm(None)
        t = self._replay_tables()
        self._reset_live()
        if t is not None:
            for layer, d in t["layers"].items():
                self._box_cur[layer] = d["seq"][idx]
                for name, arr in d["t"].items():
                    self._box_times[name] = float(arr[idx])
                for name, arr in d["e"].items():
                    self._box_entries[name] = int(arr[idx])
        zd.update()


def paint_box_overlay(host, zd, painter, ox, oy, dw, dh):
    """Current zone filled stronger; every zone labelled with its name and
    live time / entry count (each part hideable from the View popup)."""
    zones = getattr(host, "_box_zone_defs", []) or []
    if not zones:
        return
    cur = set(v for v in (getattr(host, "_box_cur", {}) or {}).values() if v)
    show_names = bool(getattr(zd, "_arm_show_numbers", True))
    show_entries = bool(getattr(zd, "_arm_show_entries", True))
    show_timer = bool(getattr(zd, "_arm_show_timer", True))
    times = getattr(host, "_box_times", {}) or {}
    entries = getattr(host, "_box_entries", {}) or {}
    font = QFont("Arial", 9, QFont.Bold)
    painter.setFont(font)
    fm = painter.fontMetrics()
    for z in zones:
        dz = zd.get_zone(ZONE_PREFIX + z.name)
        if not dz or len(dz.get("geometry") or []) < 3:
            continue
        color = QColor(z.color)
        pts = [zd._norm_to_disp(p, ox, oy, dw, dh) for p in dz["geometry"]]
        if z.name in cur:
            hi = QColor(color)
            hi.setAlpha(110)
            painter.setPen(Qt.NoPen)
            painter.setBrush(hi)
            zd._draw_polygon(painter, [(int(x), int(y)) for x, y in pts])
        lp = dz["style"].get("box_label_pos")
        if lp:
            lx, ly = zd._norm_to_disp(lp, ox, oy, dw, dh)
        else:
            lx = sum(p[0] for p in pts) / len(pts)
            ly = sum(p[1] for p in pts) / len(pts)
        y = ly
        if show_names:
            tw = fm.horizontalAdvance(z.label)
            painter.setPen(QColor(0, 0, 0, 200))
            painter.drawText(int(lx - tw / 2) + 1, int(y) + 1, z.label)
            painter.setPen(color)
            painter.drawText(int(lx - tw / 2), int(y), z.label)
            y += fm.height() + 1
        parts = []
        if show_entries:
            parts.append(f"#{int(entries.get(z.name, 0))}")
        if show_timer:
            parts.append(f"{float(times.get(z.name, 0.0)):.2f}s")
        if parts:
            text = "  ".join(parts)
            tw = fm.horizontalAdvance(text)
            painter.setPen(QColor(0, 0, 0, 200))
            painter.drawText(int(lx - tw / 2) + 1, int(y) + 1, text)
            painter.setPen(color)
            painter.drawText(int(lx - tw / 2), int(y), text)


# ── One screen + batch class per box test ───────────────────────────────
def _make(exp_cls):
    tab_name = exp_cls.__name__ + "Tab"
    batch_name = exp_cls.__name__ + "BatchTab"

    def __init__(self, config):
        BoxTab.__init__(self, config, experiment=exp_cls())
    tab_cls = type(tab_name, (BoxTab,), {"__init__": __init__,
                                         "__module__": __name__})
    batch_cls = type(batch_name, (ExperimentBatchTab,),
                     {"embedded_tab_class": tab_cls, "__module__": __name__})
    globals()[tab_name] = tab_cls
    globals()[batch_name] = batch_cls
    return tab_cls, batch_cls


from experiments.box.paradigms import ALL as _ALL  # noqa: E402

from experiments.custom.experiment import CustomExperiment  # noqa: E402

BOX_TABS = {cls.key: _make(cls) for cls in (*_ALL, CustomExperiment)}
