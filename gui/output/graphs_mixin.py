"""GraphsMixin — all matplotlib figure builders for the Output → Graphs
tab + style helpers + the SVG / PDF / PNG export hook surfaces.

Mixed into ExperimentTab. Method signatures and behavior are unchanged
from the previous in-line implementation; only the file home has moved.

Reuses host attrs / methods:
    self.raw_df, self.metrics, self.bin_df, self.fps, self.config,
    self.experiment, self.zone_drawer, self.video_w, self.video_h,
    self._graph_style, self._plugin_key, self._graph_data,
    self._graph_canvas_size, self._grid_cell_quad_px, self._combo_graph,
    self._graph_lbl, self._graph_pixmaps, self._graph_png_bytes,
    self._graph_scroll, self._graph_selector_widget, self.lbl_graph_hint,
    self._batch_owner (optional).
"""
import os
import re
from io import BytesIO

import numpy as np
import cv2

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox

from core import logger
from gui import heatmap_grid, theme
from gui.graph_style import (
    DEFAULT_CAPS as GRAPH_DEFAULT_CAPS,
    ACCENT_COLORS as GRAPH_ACCENTS,
    resolve_style, resolve_token, speed_axis, time_axis, distance_axis,
    axis_title_style,
)


class GraphsMixin:
    def _make_graph_builders(self, x, y, arena):
        """Return {graph_name: callable -> matplotlib.Figure} for the
        current session. Shared by _populate_graph_tab (raster preview)
        and _export_graph_to_path (vector SVG / PDF / PNG export) so
        both paths produce byte-identical figures."""
        def _traj_fig():
            panels = self._canon_panels(
                x, y, self._gstyle("Trajectory").get("shape_thickness", 30))
            if panels is not None:
                return self._make_dual_trajectory_fig(x, y, panels)
            return self._make_trajectory_fig(x, y, arena)

        def _heat_fig():
            panels = self._canon_panels(
                x, y, self._gstyle("Heatmap").get("shape_thickness", 30))
            if panels is not None:
                return self._make_dual_heatmap_fig(x, y, panels)
            return self._make_heatmap_fig(x, y, arena)

        raw = {
            "Trajectory":      _traj_fig,
            "Heatmap":         _heat_fig,
            "Cell Time":       lambda: self._make_cell_time_heatmap_fig(arena),
            "Speed":           lambda: self._make_speed_fig(),
            "Speed Histogram": lambda: self._make_speed_histogram_fig(),
            "Habituation":     lambda: self._make_habituation_fig(),
            "Zone Time":       lambda: self._make_zone_bar_fig(),
            "Triplets":        lambda: self._make_triplets_fig(),
        }

        # Chart-editor drag positions (title / axis titles / plot area) on
        # every figure — screen, Excel images and file exports alike.
        from gui.graph_style import apply_layout_overrides

        def positioned(name, build):
            def run():
                fig = build()
                if fig is not None:
                    try:
                        apply_layout_overrides(fig, self._gstyle(name))
                    except Exception as e:
                        logger.warn(f"layout overrides failed for '{name}': {e}",
                                    source="graphs")
                return fig
            return run

        return {name: positioned(name, build) for name, build in raw.items()}

    # ── Vector graph export (SVG / PDF / PNG) ────────────────────────────

    EXPORT_FORMATS = {
        ".svg": ("svg", "Scalable Vector Graphics"),
        ".pdf": ("pdf", "Portable Document"),
        ".png": ("png", "Portable Network Graphics"),
    }

    def _export_graph_to_path(self, graph_name, out_path):
        """Render `graph_name` to disk. Format inferred from extension —
        .svg / .pdf / .png. Builds a fresh figure (doesn't reuse the
        cached pixmap, which is raster-only). Returns True on success."""
        import os as _os
        ext = _os.path.splitext(out_path)[1].lower()
        if ext not in self.EXPORT_FORMATS:
            logger.warn(f"Unknown export extension: {ext}", source="graphs")
            return False
        if self.raw_df is None or len(self.raw_df) == 0:
            logger.warn("Export: no tracked data yet", source="graphs")
            return False
        x = self.raw_df["X (px)"].dropna().values
        y = self.raw_df["Y (px)"].dropna().values
        if len(x) < 2:
            logger.warn("Export: not enough data points", source="graphs")
            return False
        try:
            # light palette, white / transparent ground — same as the preview
            fig = self._build_export_figure(graph_name)
        except Exception as e:
            logger.warn(f"Export: build failed for '{graph_name}': {e}",
                        source="graphs")
            return False
        if fig is None:
            logger.warn(f"Export: builder declined '{graph_name}' "
                        "(missing zone mode / no data)", source="graphs")
            return False
        try:
            fmt = self.EXPORT_FORMATS[ext][0]
            # bbox_inches="tight" keeps colorbar / legend inside the page
            # even when the user dragged them outside the axes.
            fig.savefig(out_path, format=fmt, dpi=self.EXPORT_DPI, bbox_inches="tight")
        except Exception as e:
            logger.warn(f"Export: savefig failed for '{graph_name}': {e}",
                        source="graphs")
            return False
        finally:
            import matplotlib.pyplot as plt
            plt.close(fig)
        logger.info(f"Exported '{graph_name}' → {out_path}", source="graphs")
        return True

    def _export_current_graph_dialog(self):
        """File-dialog launcher. Used by the graph-tab right-click menu
        and (from the dialog side) by GraphStyleDialog's Export button."""
        if self.raw_df is None:
            QMessageBox.information(self, "Export graph",
                                    "Run tracking first.")
            return
        name = (self._combo_graph.currentText()
                if hasattr(self, "_combo_graph") else "")
        if not name:
            QMessageBox.information(self, "Export graph",
                                    "No graph selected.")
            return
        out_folder = self.config.get("output_folder") or ""
        default = os.path.join(out_folder, f"{name}.svg") if out_folder else f"{name}.svg"
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export {name}", default,
            "SVG (*.svg);;PDF (*.pdf);;PNG (*.png)"
        )
        if not path:
            return
        from gui.notify import show_done
        if self._export_graph_to_path(name, path):
            show_done(self, f"{name} graph exported", path=path)
        else:
            show_done(self, "Graph export failed",
                      "Could not write the graph file. See Logs for details.", kind="err")

    def _populate_graph_tab(self, only=None):
        """Build (or refresh) the graphs.

        only=None        → full rebuild, all graphs (default).
        only={"Habituation", ...} → partial rebuild; other graphs keep
                their existing pixmaps. Used by selective recompute when
                only a narrow-impact knob (e.g. move threshold) changed."""
        x = self.raw_df["X (px)"].dropna().values
        y = self.raw_df["Y (px)"].dropna().values
        _, arena, _, _ = self._graph_data()

        full = only is None
        if full:
            self._graph_pixmaps = {}
            self._graph_png_bytes = {}
            self._graph_screen_stale = set()
        else:
            stale = getattr(self, "_graph_screen_stale", None)
            if stale:
                stale.difference_update(only)

        # Single source of truth for build order + builder lambdas. Shared
        # with _export_graph_to_path so vector exports build the same figs.
        builders = self._make_graph_builders(x, y, arena)
        targets = list(builders.keys()) if full else [n for n in builders if n in only]

        if len(x) > 1:
            for name in targets:
                try:
                    fig = builders[name]()
                except Exception as e:
                    logger.warn(f"Graph '{name}' failed to build: {e}",
                                   source="graphs")
                    continue
                if fig is None:
                    # Builder declined this graph (no data, missing zone
                    # mode, etc.). Drop any stale pixmap so a partial
                    # rebuild doesn't keep an outdated cache entry.
                    self._graph_pixmaps.pop(name, None)
                    self._graph_png_bytes.pop(name, None)
                    continue
                try:
                    pix, png = self._fig_to_pixmap_and_bytes(fig)
                except Exception as e:
                    logger.warn(f"Graph '{name}' failed to rasterize: {e}",
                                   source="graphs")
                    continue
                # On-screen figure follows the app theme; the PNG bytes
                # embedded in Excel / saved beside it use the export look
                # (light palette on a white or transparent background).
                self._force_fig_mode = "export"
                try:
                    fig_l = builders[name]()
                    if fig_l is not None:
                        _p, png = self._fig_to_pixmap_and_bytes(fig_l)
                except Exception as e:
                    logger.warn(f"Export render of '{name}' failed: {e}", source="graphs")
                finally:
                    self._force_fig_mode = None
                self._graph_pixmaps[name] = pix
                self._graph_png_bytes[name] = png

        # Combo: preserve current selection if still valid; otherwise pick
        # the first available graph. Rebuild list only on full pass or
        # when the available set changed (cheap check).
        cur_name = self._combo_graph.currentText()
        wanted_names = list(self._graph_pixmaps)
        existing_names = [self._combo_graph.itemText(i)
                          for i in range(self._combo_graph.count())]
        if full or wanted_names != existing_names:
            self._combo_graph.blockSignals(True)
            self._combo_graph.clear()
            for name in wanted_names:
                self._combo_graph.addItem(name)
            idx = self._combo_graph.findText(cur_name)
            if idx >= 0:
                self._combo_graph.setCurrentIndex(idx)
            self._combo_graph.blockSignals(False)

        if self._graph_pixmaps:
            # If the currently-shown graph was one of the rebuilt ones,
            # repaint it. Otherwise nothing needed (other graphs' pixmaps
            # are unchanged in the cache).
            shown = self._combo_graph.currentText()
            if not shown and self._combo_graph.count() > 0:
                self._combo_graph.setCurrentIndex(0)
                shown = self._combo_graph.currentText()
            if shown and shown in self._graph_pixmaps:
                if full or shown in targets:
                    self._graph_lbl.setPixmap(self._graph_pixmaps[shown])

        self.lbl_graph_hint.setVisible(False)
        self._graph_selector_widget.setVisible(True)
        self._graph_scroll.setVisible(True)
        if hasattr(self, "_rebuild_graph_list"):
            self._rebuild_graph_list()
        if hasattr(self, "_fill_graph_preset_combo"):
            self._fill_graph_preset_combo()     # Customize… may have changed it

    def _on_theme_graphs(self, _mode):
        """Theme switched. Only the on-screen pictures follow the theme (the
        export PNGs use the fixed export look), so nothing is rebuilt here —
        that used to redraw every graph twice and made the switch take ~1 s.
        The graph on screen is redrawn once the cross-fade has finished; the
        others are redrawn when they are opened."""
        if self.raw_df is None or not getattr(self, "_graph_pixmaps", None):
            return
        self._graph_screen_stale = set(self._graph_pixmaps)
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(self.THEME_GRAPH_DELAY_MS, self._refresh_shown_graph_if_stale)

    THEME_GRAPH_DELAY_MS = 340      # just after the theme cross-fade

    def _refresh_shown_graph_if_stale(self):
        name = self._combo_graph.currentText() if hasattr(self, "_combo_graph") else ""
        if name:
            self._ensure_screen_graph(name)

    def _ensure_screen_graph(self, name):
        """Redraw graph `name` for the current theme when a theme switch left
        its on-screen picture outdated. Returns the (fresh) pixmap or None."""
        stale = getattr(self, "_graph_screen_stale", None)
        if not stale or name not in stale:
            return self._graph_pixmaps.get(name)
        stale.discard(name)
        try:
            if self.raw_df is None:
                return None
            x = self.raw_df["X (px)"].dropna().values
            y = self.raw_df["Y (px)"].dropna().values
            if len(x) < 2:
                return None
            _, arena, _, _ = self._graph_data()
            fig = self._make_graph_builders(x, y, arena)[name]()
            if fig is None:
                return self._graph_pixmaps.get(name)
            pix = self._fig_to_pixmap_and_bytes(fig)[0]
        except Exception as e:
            logger.warn(f"graph theme refresh failed for '{name}': {e}", source="graphs")
            return self._graph_pixmaps.get(name)
        self._graph_pixmaps[name] = pix
        if self._combo_graph.currentText() == name:
            self._graph_lbl.setPixmap(pix)
        return pix

    # ── Export preview (exactly what the saved files look like) ───────────

    EXPORT_DPI = 200

    def _build_export_figure(self, graph_name):
        """Figure for `graph_name` in the export look: export preset, light
        palette, white / transparent ground. Same builder the SVG / PDF / PNG
        export and the Excel images use. None when it cannot be drawn."""
        if self.raw_df is None or len(self.raw_df) == 0:
            return None
        x = self.raw_df["X (px)"].dropna().values
        y = self.raw_df["Y (px)"].dropna().values
        if len(x) < 2:
            return None
        _, arena, _, _ = self._graph_data()
        builder = self._make_graph_builders(x, y, arena).get(graph_name)
        if builder is None:
            return None
        self._force_fig_mode = "export"
        try:
            return builder()
        finally:
            self._force_fig_mode = None

    def _render_export_png(self, graph_name, dpi=None):
        """PNG bytes of `graph_name` exactly as Export writes it, or None."""
        import matplotlib.pyplot as plt
        try:
            fig = self._build_export_figure(graph_name)
        except Exception as e:
            logger.warn(f"Export preview: build failed for '{graph_name}': {e}", source="graphs")
            return None
        if fig is None:
            return None
        buf = BytesIO()
        try:
            fig.savefig(buf, format="png", dpi=dpi or self.EXPORT_DPI, bbox_inches="tight")
        finally:
            plt.close(fig)
        return buf.getvalue()

    def _open_export_preview(self):
        """Popup showing the selected graph exactly as it will be exported."""
        if self.raw_df is None or not self._combo_graph.currentText():
            QMessageBox.information(self, "Export preview", "Run tracking first.")
            return
        from gui.export_preview import ExportPreviewDialog
        names = [self._combo_graph.itemText(i) for i in range(self._combo_graph.count())]
        dlg = ExportPreviewDialog(self, names, self._combo_graph.currentText())
        dlg.exec_()

    # ── Tracking Issues tab → gui/output/tracking_issues_mixin.py

    # ── Output tab population → gui/output/output_tabs_mixin.py

    # ── graph styling ─────────────────────────────────────────────────────

    def _graph_style_caps(self, name):
        """Which style fields apply for a given graph in *this* experiment.
        Delegates to the experiment plugin's `graph_caps(name)` so per-
        plugin caps (grid for OF/NOR, center_pct for OF Trajectory, none
        for EPM/Y-Maze) live with the plugin instead of branching here."""
        caps = set(GRAPH_DEFAULT_CAPS.get(name, set()))
        caps.discard("grid")
        try:
            extra = self.experiment.graph_caps(name) if self.experiment else set()
        except Exception as e:
            logger.warn(f"graph_caps({name}) failed: {e}", source="plugin")
            extra = set()
        if extra:
            caps.update(extra)
        return caps

    def _set_export_bg(self, choice):
        """Output → Graphs 'White | Transparent': background of exported
        graph files and Excel images. Saved in config["export_bg"]."""
        from gui.graph_style import set_export_bg
        set_export_bg(choice)
        self.config["export_bg"] = choice
        owner = getattr(self, "_batch_owner", None)
        if owner is not None and isinstance(getattr(owner, "config", None), dict):
            owner.config["export_bg"] = choice
            if hasattr(owner, "_save_config"):
                owner._save_config()
        try:
            if self.raw_df is not None and self._graph_pixmaps:
                self._populate_graph_tab()      # refresh the Excel images
        except Exception as e:
            logger.warn(f"export background refresh failed: {e}", source="graphs")

    def _fig_mode(self):
        """Palette used for figures: the UI theme, or "light" while building
        files / Excel images."""
        return getattr(self, "_force_fig_mode", None) or theme.mode()

    def _gstyle(self, name):
        """Return active style dict for a graph (full, never None) with
        theme tokens ("@ink", "@ac" …) resolved to colours."""
        return resolve_style(self._graph_style.get_for(self._plugin_key(), name),
                             self._fig_mode())

    def _plugin_key(self):
        return getattr(self.experiment, "key", None) or "open_field"

    def _plugin_family(self):
        exp = getattr(self, "experiment", None)
        return (getattr(exp, "fam", None) or getattr(exp, "key", None)
                or "open_field")

    # Canonical maze size the remapped output is built in (arbitrary units;
    # scaled to fit the graph frame). Matches the preview's arena_half feel.
    _CANON_L = 100.0

    def _canon_panels(self, x, y, thickness):
        """For EPM / Y-Maze, build the data for a side-by-side Raw vs Aligned
        spatial graph. Returns (raw_polys_px, cx_px, cy_px, canon_polys_px):

          raw_polys_px  — the real drawn arm polygons (pixel coords) for the
                          Raw panel outline/mask.
          cx_px, cy_px  — the path remapped onto the canonical idealized maze
                          (arms at `thickness`%), in matching pixel coords.
          canon_polys_px— the canonical maze outline (pixel coords).

        Returns None when the active experiment has no arm layout (OF/NOR)."""
        exp = getattr(self, "experiment", None)
        layout = exp.canonical_arm_layout(self) if exp is not None else None
        if not layout or not layout.get("arms"):
            return None
        import math
        from gui.graph_style_dialog import maze_shape_polys
        vw, vh = self._graph_canvas_size()
        L = self._CANON_L
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        hub_px = np.array([layout["hub"][0] * vw, layout["hub"][1] * vh],
                          dtype=float)
        # Project in a y-UP frame (image y is down → negate) so the across-arm
        # handedness matches the canonical math frame. Mixing image-y (down)
        # with canonical-y (up) mirrored the path left↔right.
        rel = np.column_stack([x - hub_px[0], -(y - hub_px[1])])

        raw_polys, ds, perps, lens, aws, cdirs, cperps, tri = (
            [], [], [], [], [], [], [], [])
        for arm in layout["arms"]:
            poly_img = np.array([(p[0] * vw, p[1] * vh) for p in arm["poly"]],
                                dtype=float)
            raw_polys.append([tuple(pt) for pt in poly_img])
            poly_up = np.column_stack([poly_img[:, 0] - hub_px[0],
                                       -(poly_img[:, 1] - hub_px[1])])
            cen = poly_up.mean(axis=0)
            d = cen / (np.hypot(*cen) or 1.0)
            perp = np.array([-d[1], d[0]])
            w = float(np.abs(poly_up @ perp).max()) or 1.0
            lens.append(float((poly_up @ d).max()) or 1.0)
            aws.append(w)
            ds.append(d); perps.append(perp)
            D = np.array(arm["cdir"], dtype=float)
            D = D / (np.hypot(*D) or 1.0)
            cdirs.append(D); cperps.append(np.array([-D[1], D[0]]))
            # Raw-space analog of the canonical centre-zone corner (the arm's
            # +side base corner), mapped back to image coords.
            corner = d * (w / math.sqrt(3.0)) + perp * w
            tri.append((hub_px[0] + corner[0], hub_px[1] - corner[1]))
        ds = np.array(ds); perps = np.array(perps)

        # Assign each point to the arm it projects farthest along.
        nearest = np.argmax(rel @ ds.T, axis=1)
        halfw = L * float(thickness) / 100.0
        cx = np.zeros(len(x)); cy = np.zeros(len(y))
        for k in range(len(ds)):
            sel = nearest == k
            if not sel.any():
                continue
            af = np.clip((rel[sel] @ ds[k]) / lens[k], 0.0, 1.05)
            lf = np.clip((rel[sel] @ perps[k]) / aws[k], -1.0, 1.0)
            cx[sel] = cdirs[k][0] * (af * L) + cperps[k][0] * (lf * halfw)
            cy[sel] = cdirs[k][1] * (af * L) + cperps[k][1] * (lf * halfw)

        # Canonical (y-up) → graph-frame pixels (y-down), centered.
        scale = 0.45 * min(vw, vh) / L
        cx_px = vw / 2.0 + cx * scale
        cy_px = vh / 2.0 - cy * scale
        canon_polys = [
            [(vw / 2.0 + px * scale, vh / 2.0 - py * scale) for (px, py) in poly]
            for poly in maze_shape_polys(self._plugin_key(), L, thickness)
        ]
        # Centre zone for the Raw panel — sort the per-arm corners by angle so
        # the polygon never self-intersects (triangle for Y-Maze's 3 arms,
        # quad for EPM's 4). Drawn with the same fill/outline as the arms.
        if len(tri) >= 3:
            ccx = sum(t[0] for t in tri) / len(tri)
            ccy = sum(t[1] for t in tri) / len(tri)
            tri_sorted = sorted(tri, key=lambda t: math.atan2(t[1] - ccy,
                                                              t[0] - ccx))
            raw_polys.append(tri_sorted)
        return raw_polys, cx_px, cy_px, canon_polys

    # ── side-by-side Raw vs Aligned spatial graphs (EPM / Y-Maze) ──────────
    def _draw_spatial_traj(self, ax, x, y, polys, st):
        """Draw a trajectory (path + region outline + start/end pins, cropped
        to the region bbox) onto `ax`. `polys` are the region polygons in
        pixel coords (real arms for Raw, canonical maze for Aligned)."""
        from matplotlib.patches import Polygon
        polys = [p for p in polys if len(p) >= 3]
        for poly in polys:
            ax.add_patch(Polygon(poly, facecolor=st["bg"], edgecolor="none",
                                 closed=True, zorder=0))
        mk = st.get("marker", "none")
        ax.plot(x, y, color=st["path_color"], linewidth=st["path_width"],
                alpha=float(st.get("alpha", 0.9)),
                linestyle=st.get("linestyle", "-"),
                marker=("" if mk == "none" else mk),
                markersize=int(st.get("marker_size", 5)),
                solid_capstyle="round", solid_joinstyle="round", zorder=2)
        for poly in polys:
            ax.add_patch(Polygon(poly, linewidth=st["arena_width"],
                                 edgecolor=st["arena_color"], facecolor="none",
                                 closed=True, zorder=4))
        if len(x):
            ax.scatter([x[0]], [y[0]], s=int(st.get("pin_size", 160)),
                       c=st.get("pin_start_color", "#23C552"),
                       marker=st.get("pin_start_marker", "o"),
                       edgecolors="white", linewidths=1.5, zorder=6)
            ax.scatter([x[-1]], [y[-1]], s=int(st.get("pin_size", 160)),
                       c=st.get("pin_end_color", "#E5484D"),
                       marker=st.get("pin_end_marker", "o"),
                       edgecolors="white", linewidths=1.5, zorder=6)
        if polys:
            arr = np.array([pt for poly in polys for pt in poly], dtype=float)
            x0, x1 = float(arr[:, 0].min()), float(arr[:, 0].max())
            y0, y1 = float(arr[:, 1].min()), float(arr[:, 1].max())
            px, py = (x1 - x0) * 0.08, (y1 - y0) * 0.08
            ax.set_xlim(x0 - px, x1 + px)
            ax.set_ylim(y1 + py, y0 - py)   # inverted (image coords)
        ax.set_aspect("equal", adjustable="box")

    def _masked_heatmap(self, x, y, polys, st, vw, vh, fps):
        """(seconds grid masked to `polys`, xedges, yedges, total_s)."""
        from matplotlib.path import Path
        mask = [np.asarray(p, dtype=float) for p in polys if len(p) >= 3]
        hm_sec, xe, ye, total_s = heatmap_grid.seconds_grid(
            x, y, [0, vw], [0, vh], fps, st)
        if mask:
            xc = 0.5 * (xe[:-1] + xe[1:]); yc = 0.5 * (ye[:-1] + ye[1:])
            xx, yy = np.meshgrid(xc, yc, indexing="xy")
            pts = np.column_stack([xx.ravel(), yy.ravel()])
            inside = np.zeros(pts.shape[0], dtype=bool)
            for poly in mask:
                try:
                    inside |= Path(poly).contains_points(pts)
                except Exception:
                    continue
            hm_sec = np.where(inside.reshape(xx.shape), hm_sec, np.nan)
        return hm_sec, xe, ye, total_s

    def _draw_spatial_heatmap(self, ax, x, y, polys, st, vw, vh, fps, vmax=None):
        """Draw a masked, clipped heatmap onto `ax`, cropped to the region
        bbox. Returns (image, vmax). `vmax` = shared peak (heatmap_grid.peak
        units) so several panels use one colour scale. Mirrors
        _make_heatmap_fig."""
        from matplotlib.patches import Polygon
        from matplotlib.path import Path
        from matplotlib import colors as mcolors
        from gui.graph_style_dialog import resolve_cmap
        mask = [np.asarray(p, dtype=float) for p in polys if len(p) >= 3]
        hm_sec, xe, ye, total_s = self._masked_heatmap(x, y, polys, st, vw, vh, fps)
        hm_sec, max_sec = heatmap_grid.scale(hm_sec, total_s, st, ref_peak=vmax)
        base = resolve_cmap(st)
        cmap = mcolors.LinearSegmentedColormap.from_list(
            "cmap_mask", base(np.linspace(0, 1, 256)))
        cmap.set_bad((1, 1, 1, 0))
        base_color = cmap(0.0)
        for poly in mask:
            ax.add_patch(Polygon(poly, closed=True, facecolor=base_color,
                                 edgecolor="none", zorder=0, antialiased=True))
        im = ax.imshow(hm_sec, origin="upper", extent=[0, vw, vh, 0],
                       cmap=cmap, interpolation=heatmap_grid.interpolation(st),
                       aspect="auto",
                       vmin=0.0, vmax=max_sec if max_sec > 0 else 1.0, zorder=1)
        if mask:
            verts = []; codes = []
            for poly in mask:
                verts.extend(list(poly)); verts.append(poly[0])
                codes.extend([Path.MOVETO] + [Path.LINETO] * (len(poly) - 1)
                             + [Path.CLOSEPOLY])
            im.set_clip_path(Path(verts, codes), transform=ax.transData)
        for poly in mask:
            ax.add_patch(Polygon(poly, linewidth=st["arena_width"],
                                 edgecolor=st["arena_color"], facecolor="none",
                                 closed=True, zorder=2))
        if mask:
            arr = np.vstack(mask)
            x0, x1 = float(arr[:, 0].min()), float(arr[:, 0].max())
            y0, y1 = float(arr[:, 1].min()), float(arr[:, 1].max())
            px, py = (x1 - x0) * 0.05, (y1 - y0) * 0.05
            ax.set_xlim(x0 - px, x1 + px)
            ax.set_ylim(y1 + py, y0 - py)
        ax.set_aspect("equal", adjustable="box")
        return im, max_sec

    def _panel_title(self, ax, st, text):
        ax.set_title(text, fontsize=int(st.get("title_size", 12)),
                     fontweight="bold" if st.get("title_bold") else "normal",
                     fontfamily=st.get("font_family", "sans-serif"))

    def _make_dual_trajectory_fig(self, raw_x, raw_y, panels):
        """Side-by-side Raw (real coords) vs Aligned (canonical maze)."""
        import matplotlib.pyplot as plt
        raw_polys, cx, cy, canon_polys = panels
        st = self._gstyle("Trajectory")
        thick = int(st.get("shape_thickness", 30))
        outer_bg = st.get("outer_bg", st["bg"])
        fig, (axL, axR) = plt.subplots(1, 2, figsize=(12, 6), facecolor=outer_bg)
        for ax, X, Y, pl, title in (
                (axL, raw_x, raw_y, raw_polys, "Raw"),
                (axR, cx, cy, canon_polys, f"Aligned ({thick}%)")):
            ax.set_facecolor(outer_bg)
            self._draw_spatial_traj(ax, X, Y, pl, st)
            self._apply_style_axes(ax, "Trajectory", st)
            self._panel_title(ax, st, title)
        self._match_panel_limits((axL, axR), raw_polys + canon_polys)
        fig.tight_layout()
        return fig

    def _match_panel_limits(self, axes, all_polys, pad=0.06):
        """Give every panel the same coordinate window (union of all region
        polygons, image-y inverted) so the Raw and Aligned panels render at
        an identical scale and size."""
        pts = np.array([pt for poly in all_polys
                        for pt in poly if len(poly) >= 3], dtype=float)
        if pts.size == 0:
            return
        x0, x1 = float(pts[:, 0].min()), float(pts[:, 0].max())
        y0, y1 = float(pts[:, 1].min()), float(pts[:, 1].max())
        px = (x1 - x0) * pad or 1.0
        py = (y1 - y0) * pad or 1.0
        for ax in axes:
            ax.set_xlim(x0 - px, x1 + px)
            ax.set_ylim(y1 + py, y0 - py)
            ax.set_aspect("equal", adjustable="box")

    def _make_dual_heatmap_fig(self, raw_x, raw_y, panels):
        """Side-by-side Raw vs Aligned heatmap, shared color scale + bar."""
        import matplotlib.pyplot as plt
        raw_polys, cx, cy, canon_polys = panels
        st = self._gstyle("Heatmap")
        thick = int(st.get("shape_thickness", 30))
        vw, vh = self._graph_canvas_size()
        fps = float(self.fps or 30.0)
        outer_bg = st.get("outer_bg", "white")
        # First pass: find a shared vmax so both panels share the color scale.
        def _peak(x, y, polys):
            hm, _xe, _ye, total_s = self._masked_heatmap(x, y, polys, st, vw, vh, fps)
            return heatmap_grid.peak(hm, total_s, st)
        vmax = max(_peak(raw_x, raw_y, raw_polys), _peak(cx, cy, canon_polys))
        fig, (axL, axR) = plt.subplots(1, 2, figsize=(12, 6), facecolor=outer_bg)
        im = None
        top = 0.0
        for ax, X, Y, pl, title in (
                (axL, raw_x, raw_y, raw_polys, "Raw"),
                (axR, cx, cy, canon_polys, f"Aligned ({thick}%)")):
            ax.set_facecolor(outer_bg)
            im, top = self._draw_spatial_heatmap(ax, X, Y, pl, st, vw, vh, fps,
                                                 vmax=vmax)
            self._apply_style_axes(ax, "Heatmap", st)
            self._panel_title(ax, st, title)
        self._match_panel_limits((axL, axR), raw_polys + canon_polys)
        if st.get("colorbar_show", True) and im is not None and top > 0:
            cbar = fig.colorbar(im, ax=[axL, axR], orientation="horizontal",
                                fraction=0.05, pad=0.06)
            cbar.set_ticks([0.0, top])
            cbar.set_ticklabels(heatmap_grid.tick_labels(top, st))
            cbar.ax.tick_params(labelsize=10, length=0)
            cbar.outline.set_visible(False)
            lbl = heatmap_grid.colorbar_label(st)
            if lbl:
                cbar.set_label(lbl, fontsize=int(st.get("tick_size", 9)),
                               color=st.get("tick_color", "#333333"))
        else:
            fig.tight_layout()
        return fig

    def _center_polygon_for_trajectory(self, arena, size_pct):
        """Square centered in the arena, sized by `size_pct` (1..100) as a
        linear fraction of the arena's width/height. Uses bilinear
        interpolation on the 4 corners so the box stays aligned with the
        arena even when it's tilted. Returns None for non-quad arenas."""
        if not arena or len(arena) != 4:
            return None
        try:
            frac = max(0.01, min(1.0, float(size_pct) / 100.0))
        except (TypeError, ValueError):
            frac = 0.45
        lo = 0.5 - frac / 2.0
        hi = 0.5 + frac / 2.0
        p0, p1, p2, p3 = arena
        def _pt(u, v):
            top = (p0[0] + u * (p1[0] - p0[0]),
                   p0[1] + u * (p1[1] - p0[1]))
            bot = (p3[0] + u * (p2[0] - p3[0]),
                   p3[1] + u * (p2[1] - p3[1]))
            return (top[0] + v * (bot[0] - top[0]),
                    top[1] + v * (bot[1] - top[1]))
        return [_pt(lo, lo), _pt(hi, lo), _pt(hi, hi), _pt(lo, hi)]


    # ── True-shape spatial graphs (square arena → square graph) ───────────

    def _arena_phys_ratio(self):
        """Height / width of the real arena, or None when unknown.

        Square cage → 1. Rectangle with auto-calibration from the cage size
        → the entered H / W. Otherwise the arena as drawn (mean of opposite
        edges). Only for Open Field / NOR (EPM and Y-Maze draw a canonical
        maze)."""
        if self._plugin_family() not in ("open_field", "nor", "box"):
            return None
        if self._plugin_family() == "nor":
            return 1.0                  # the NOR cage is always square
        if self._plugin_family() == "box":
            # Apparatus size from the Scale card (square tests: W == H).
            try:
                w = float(self.spin_cage_w.value())
                h = float(self.spin_cage_h.value())
                if self.experiment.scale[0] == "square":
                    return 1.0
                if w > 0 and h > 0:
                    return h / w
            except Exception:
                pass
        combo = getattr(self, "combo_cage_shape", None)
        shape = (combo.currentData() if combo is not None
                 else self.config.get("cage_shape", "rectangle"))
        if shape == "square":
            return 1.0
        calib = self._calib_mode() if hasattr(self, "_calib_mode") else "auto"
        if shape == "rectangle" and calib == "auto":
            try:
                w = float(self.spin_cage_w.value())
                h = float(self.spin_cage_h.value())
                if w > 0 and h > 0:
                    return h / w
            except Exception:
                pass
        # Measured from the arena corners in the original video.
        zd = getattr(self, "zone_drawer", None)
        if getattr(self, "_perspective_on", False) and getattr(self, "_original_arena", None):
            quad = self._original_arena
            vw, vh = (getattr(self, "_native_video_size", None)
                      or (self.video_w, self.video_h))
        else:
            quad = getattr(zd, "arena", None)
            vw, vh = self.video_w, self.video_h
        if not quad or len(quad) != 4 or not vw or not vh:
            return None
        pts = [(float(x) * vw, float(y) * vh) for x, y in quad]
        tl = min(pts, key=lambda p: p[0] + p[1])
        br = max(pts, key=lambda p: p[0] + p[1])
        tr = max(pts, key=lambda p: p[0] - p[1])
        bl = min(pts, key=lambda p: p[0] - p[1])
        d = lambda a, b: float(np.hypot(a[0] - b[0], a[1] - b[1]))
        w = (d(tl, tr) + d(bl, br)) / 2.0
        h = (d(tl, bl) + d(tr, br)) / 2.0
        return h / w if w > 0 and h > 0 else None

    def _true_shape(self, fig, ax, width_in=6.0):
        """Draw the arena with its real proportions — a square arena becomes
        a square plot even when the video frame is not square — and size
        the figure to match so the saved picture has no empty side bands."""
        ratio = self._arena_phys_ratio()
        if ratio is None:
            return
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        bw, bh = abs(x1 - x0), abs(y1 - y0)
        if bw <= 0 or bh <= 0:
            return
        ax.set_aspect(ratio * bw / bh, adjustable="box")
        # New figure height = same top / bottom margins (in inches) + a plot
        # area of the arena's shape. Other axes (the colour bar) keep their
        # distance from the bottom edge, so no gap opens above them.
        W, H0 = fig.get_figwidth(), fig.get_figheight()
        sp = fig.subplotpars
        top_in, bot_in = (1.0 - sp.top) * H0, sp.bottom * H0
        plot_w_in = max(0.5, (sp.right - sp.left) * W)
        H = max(1.0, top_in + bot_in + plot_w_in * ratio)
        others = [(a, a.get_position()) for a in fig.axes if a is not ax]
        fig.set_size_inches(W, H)
        fig.subplots_adjust(bottom=bot_in / H, top=1.0 - top_in / H)
        for a, pos in others:
            a.set_position([pos.x0, pos.y0 * H0 / H, pos.width, pos.height * H0 / H])

    @staticmethod
    def _text_color_for_bg(bg_hex):
        """Pick black/white text for readability on a given bg color."""
        try:
            c = QColor(bg_hex)
            if not c.isValid():
                return "black"
            lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
            return "black" if lum > 140 else "white"
        except Exception:
            return "black"

    def _style_allowed(self, name):
        """Fields the active experiment exposes for `name`. Combines the
        graph's GRAPH_FIELDS allow-list with experiment caps (e.g. grid,
        center_pct)."""
        from gui.graph_style import GRAPH_FIELDS
        base = set(GRAPH_FIELDS.get(name, set()))
        caps = self._graph_style_caps(name)
        if "grid" in caps:
            base.update({"grid", "grid_color", "grid_alpha",
                         "grid_linestyle", "grid_axis"})
        if "center_pct" in caps:
            base.update({"show_center_pct", "center_pct_color",
                         "center_size_pct"})
        return base

    # Spatial graphs whose arena coordinates aren't meaningful — ticks
    # are forced off regardless of style. Spines remain user-controlled.
    _GRIDLESS_GRAPHS = {"Trajectory", "Heatmap", "Cell Time"}

    def _apply_style_axes(self, ax, name, st):
        allowed = self._style_allowed(name)
        for side, key in (("top", "spine_top"), ("right", "spine_right"),
                          ("bottom", "spine_bottom"), ("left", "spine_left")):
            sp = ax.spines.get(side)
            if sp is None:
                continue
            visible = bool(st.get(key, True)) if key in allowed else True
            sp.set_visible(visible)
            if visible:
                sp.set_edgecolor(st.get("spine_color", "#777777"))
                sp.set_linewidth(float(st.get("spine_width", 1.0)))
        self._cm_axes_on = False
        if name in self._GRIDLESS_GRAPHS:
            if self._cm_ticks_ok(name) and self._apply_cm_ticks(ax, st):
                self._cm_axes_on = True
            else:
                ax.set_xticks([]); ax.set_yticks([])
        elif "show_ticks" in allowed and not st.get("show_ticks", True):
            ax.set_xticks([]); ax.set_yticks([])
        else:
            ax.tick_params(colors=st.get("tick_color", "#333333"),
                           labelsize=int(st.get("tick_size", 9)),
                           direction="out", length=4, width=1)
            self._mono_ticks(ax)
            if st.get("tick_bold"):
                for lab in ax.get_xticklabels() + ax.get_yticklabels():
                    lab.set_fontweight("bold")
        if "grid" in allowed and st.get("grid"):
            ax.grid(True,
                    axis=st.get("grid_axis", "both"),
                    color=st.get("grid_color", "#BBBBBB"),
                    alpha=float(st.get("grid_alpha", 0.3)),
                    linestyle=st.get("grid_linestyle", "-"))

    def _mono_ticks(self, ax):
        try:
            ax.tick_params(labelfontfamily=theme.mono_family())
        except Exception:
            for lab in ax.get_xticklabels() + ax.get_yticklabels():
                lab.set_fontfamily(theme.mono_family())

    def _cm_ticks_ok(self, name):
        """Spatial graphs get cm rulers when the arena is calibrated (Open
        Field / NOR — EPM and Y-Maze plot in canonical maze units)."""
        return (name in self._GRIDLESS_GRAPHS
                and self._plugin_family() in ("open_field", "nor", "box"))

    def _apply_cm_ticks(self, ax, st):
        """X / Y ticks in cm measured from the arena's top-left corner.

        Graph coordinates live in the (possibly perspective-warped) space
        where the arena fills the frame, so the physical size comes from the
        calibrated arena dimensions and is mapped onto the arena bbox."""
        try:
            _, arena, _, _ = self._graph_data()
        except Exception:
            return False
        try:
            dims = self._arena_dims_cm()     # fresh — same on screen and in files
        except Exception:
            dims = getattr(getattr(self, "zone_drawer", None), "cage_dims_cm", None)
        if not (arena and len(arena) >= 3 and dims):
            return False
        w_cm, h_cm = float(dims[0]), float(dims[1])
        if w_cm <= 0 or h_cm <= 0:
            return False
        arr = np.array(arena, dtype=float)
        x0, x1 = float(arr[:, 0].min()), float(arr[:, 0].max())
        y0, y1 = float(arr[:, 1].min()), float(arr[:, 1].max())
        step = 10 if max(w_cm, h_cm) >= 25 else (5 if max(w_cm, h_cm) >= 12 else 2)
        xs = np.arange(0.0, w_cm + 1e-6, step)
        ys = np.arange(0.0, h_cm + 1e-6, step)
        ax.set_xticks(x0 + xs / w_cm * (x1 - x0))
        ax.set_xticklabels([f"{c:g}" for c in xs])
        ax.set_yticks(y0 + ys / h_cm * (y1 - y0))
        ax.set_yticklabels([f"{c:g}" for c in ys])
        ax.tick_params(colors=st.get("tick_color", "#333333"),
                       labelsize=int(st.get("tick_size", 9)),
                       direction="out", length=4, width=1)
        self._mono_ticks(ax)
        col = st.get("text_color", st.get("tick_color", "#333333"))
        fam = st.get("font_family", "sans-serif")
        if not st.get("xlabel"):
            ax.set_xlabel("X (cm)", color=col, fontsize=int(st.get("label_size", 10)), fontfamily=fam)
        if not st.get("ylabel"):
            ax.set_ylabel("Y (cm)", color=col, fontsize=int(st.get("label_size", 10)), fontfamily=fam)
        return True

    def _apply_style_text(self, ax, name, st):
        allowed = self._style_allowed(name)
        fam = st.get("font_family", "sans-serif")
        if st.get("title"):
            # title_pad is an OFFSET added to matplotlib's default pad (~6).
            title_pad = 6.0 + float(st.get("title_pad", 0.0))
            ax.set_title(st["title"], fontsize=int(st.get("title_size", 12)),
                         fontweight="bold" if st.get("title_bold") else "normal",
                         fontfamily=fam,
                         color=st.get("title_color") or st.get("text_color", "black"),
                         pad=title_pad)   # may go negative: title dragged down into the plot
        for axis, setter in (("xlabel", ax.set_xlabel), ("ylabel", ax.set_ylabel)):
            if axis in allowed and st.get(axis):
                size, bold, color = axis_title_style(st, axis)
                setter(st[axis], fontsize=size, fontfamily=fam, color=color,
                       fontweight="bold" if bold else "normal")

    def _apply_legend(self, ax, name, st, handles=None):
        from gui.graph_style_dialog import _legend_kwargs_for, apply_legend_labels
        allowed = self._style_allowed(name)
        if "legend_show" not in allowed or not st.get("legend_show", True):
            return None
        kwargs = _legend_kwargs_for(ax, st)
        if handles is not None:
            leg = ax.legend(handles=handles, **kwargs)
        else:
            leg = ax.legend(**kwargs)
        apply_legend_labels(leg, st)
        if leg is not None and st.get("legend_draggable"):
            try:
                leg.set_draggable(True)
            except Exception:
                pass
        return leg

    def _save_graph_style_to_config(self):
        try:
            d = self._graph_style.to_dict()
            self.config["graph_style"] = d
            # When this tab is embedded inside an ExperimentBatchTab, the
            # batch tab holds the live MainWindow config dict; our own
            # self.config is a detached cfg_copy and self.window() does NOT
            # reach MainWindow. Push the dict through the back-ref instead.
            owner = getattr(self, "_batch_owner", None)
            if owner is not None:
                if isinstance(getattr(owner, "config", None), dict):
                    owner.config["graph_style"] = d
                if hasattr(owner, "_save_config"):
                    owner._save_config()
                    return
            win = self.window()
            if hasattr(win, "_save_config"):
                win._save_config()
        except Exception:
            pass

    def _open_graph_style_dialog(self):
        from gui.chart_editor import ChartEditor

        def rerender(_name=None):
            try:
                if self.raw_df is not None:
                    self._populate_graph_tab()
            except Exception:
                pass

        plugins = self._collect_graph_style_plugins()
        dlg = ChartEditor(self._graph_style, self._graph_style_caps,
                               rerender_cb=rerender,
                               persist_cb=self._save_graph_style_to_config,
                               plugins=plugins,
                               current_plugin_key=self._plugin_key(),
                               parent=self)
        if dlg.exec_() == QDialog.Accepted:
            self._save_graph_style_to_config()
            rerender()
        else:
            # Backup was restored by the dialog; still rerender.
            rerender()

    def _collect_graph_style_plugins(self):
        """Build the plugin descriptor list the dialog needs. One entry per
        experiment plugin: (key, label, graph_names, caps_provider). The
        active experiment uses this tab's own caps so center/grid checks
        still react to live state; other plugins use their own contracts."""
        from experiments.open_field.experiment import OpenFieldExperiment
        from experiments.nor.experiment import NORExperiment
        from experiments.epm.experiment import EPMExperiment
        from experiments.y_maze.experiment import YMazeExperiment

        active_key = self._plugin_key()
        entries = []
        exps = []
        for plugin_cls in (OpenFieldExperiment, NORExperiment,
                           EPMExperiment, YMazeExperiment):
            try:
                exps.append(plugin_cls())
            except Exception:
                continue
        # Registry tests (NOL, box tests) list themselves when active, so
        # edits are saved under their own key instead of Open Field's.
        if active_key not in {e.key for e in exps} and getattr(self, "experiment", None):
            exps.append(self.experiment)
        for exp in exps:
            if exp.key == active_key:
                caps_fn = self._graph_style_caps
            else:
                caps_fn = exp.graph_caps
            try:
                names = list(exp.graph_names())
            except Exception:
                from gui.graph_style import GRAPH_NAMES
                names = list(GRAPH_NAMES)
            entries.append({
                "key": exp.key,
                "family": exp.fam,
                "label": exp.name,
                "graph_names": names,
                "caps_provider": caps_fn,
            })
        return entries

    # ── plot generators ───────────────────────────────────────────────────

    def _make_trajectory_fig(self, x, y, arena, shape_polys=None):
        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon

        vw, vh = self._graph_canvas_size()
        fps = float(self.fps or 30.0)
        total_s = max(1, len(x) - 1) / fps

        st = self._gstyle("Trajectory")
        outer_bg = st.get("outer_bg", st["bg"])
        fig, ax = plt.subplots(figsize=(6, 6 * vh / vw), facecolor=outer_bg)
        ax.set_facecolor(outer_bg)

        # Region polygons to fill/outline: canonical maze shape (EPM/Y-Maze
        # remapped) when given, else the real arena polygon.
        fill_polys = ([p for p in shape_polys if len(p) >= 3] if shape_polys
                      else ([arena] if (arena and len(arena) >= 3) else []))

        # Area background — fill inside region polygon(s) only (zorder=0 so
        # the trajectory + outline paint on top).
        for poly in fill_polys:
            ax.add_patch(Polygon(poly, facecolor=st["bg"], edgecolor="none",
                                 closed=True, zorder=0))

        mk = st.get("marker", "none")
        mk_plt = "" if mk == "none" else mk
        ax.plot(x, y, color=st["path_color"], linewidth=st["path_width"],
                alpha=float(st.get("alpha", 0.9)),
                linestyle=st.get("linestyle", "-"),
                marker=mk_plt,
                markersize=int(st.get("marker_size", 5)),
                solid_capstyle="round", solid_joinstyle="round", zorder=2)

        edge_color = st["arena_color"]
        for poly in fill_polys:
            ax.add_patch(Polygon(poly, linewidth=st["arena_width"],
                                 edgecolor=edge_color, facecolor="none",
                                 closed=True, zorder=4))

        # Start / end pin dots — labels live in the legend now, not on canvas.
        psz = int(st.get("pin_size", 160))
        pcs = st.get("pin_start_color", "#23C552")
        pce = st.get("pin_end_color", "#E5484D")
        psm = st.get("pin_start_marker", "o")
        pem = st.get("pin_end_marker", "o")
        ax.scatter([x[0]], [y[0]], s=psz, c=pcs, marker=psm,
                   edgecolors=st["bg"], linewidths=1.0, zorder=6)
        ax.scatter([x[-1]], [y[-1]], s=psz, c=pce, marker=pem,
                   edgecolors=st["bg"], linewidths=1.0, zorder=6)

        # Optional 4×4 grid overlay (OF grid zone-mode only).
        caps = self._graph_style_caps("Trajectory")
        if ("grid" in caps and st.get("grid", False)
                and arena and len(arena) == 4
                and hasattr(self, "zone_drawer")
                and getattr(self.zone_drawer, "zone_mode", None) == "grid"):
            gc = st.get("grid_color", "#BBBBBB")
            ga = float(st.get("grid_alpha", 0.5))
            gls = st.get("grid_linestyle", "-")
            p0, p1, p2, p3 = arena
            for i in range(1, 4):
                t = i / 4.0
                top = (p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1]))
                bot = (p3[0] + t * (p2[0] - p3[0]), p3[1] + t * (p2[1] - p3[1]))
                lft = (p0[0] + t * (p3[0] - p0[0]), p0[1] + t * (p3[1] - p0[1]))
                rgt = (p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1]))
                ax.plot([top[0], bot[0]], [top[1], bot[1]],
                        color=gc, linewidth=0.8, alpha=ga, linestyle=gls, zorder=3)
                ax.plot([lft[0], rgt[0]], [lft[1], rgt[1]],
                        color=gc, linewidth=0.8, alpha=ga, linestyle=gls, zorder=3)

        # Optional center square — user-sized. Size shown in legend.
        center_shown = False
        center_col = st.get("center_pct_color", "#FFFFFF")
        if "center_pct" in caps and st.get("show_center_pct", False):
            center_poly = None
            size_txt = int(st.get("center_size_pct", 50))
            if self._plugin_key() == "open_field":
                # the real center zone the user drew / sized in the Zones card
                try:
                    _cz = self._graph_data()[2]
                    if _cz and len(_cz) >= 3:
                        center_poly = _cz
                        size_txt = int(self.spin_center_pct.value())
                except Exception:
                    center_poly = None
            if center_poly is None:
                center_poly = self._center_polygon_for_trajectory(
                    arena, st.get("center_size_pct", 50))
            if center_poly is not None:
                fillc = QColor(center_col)
                ax.add_patch(Polygon(
                    center_poly, closed=True, fill=True,
                    facecolor=(fillc.redF(), fillc.greenF(), fillc.blueF(), 0.06),
                    edgecolor=center_col, linewidth=1.0, linestyle=(0, (4, 3)),
                    zorder=5))
                center_shown = True

        # Plugin overlay hook (NOR draws object footprints + zones here).
        plugin_handles = None
        try:
            exp = getattr(self, "experiment", None)
            if exp is not None:
                plugin_handles = exp.decorate_graph(self, "Trajectory", ax, arena)
        except Exception as e:
            logger.warn(f"decorate_graph(Trajectory) failed: {e}", source="plugin")
            plugin_handles = None

        # Tight crop to the region bbox (canonical shape or real arena), or
        # the full frame when neither is available.
        if fill_polys:
            arr = np.array([pt for poly in fill_polys for pt in poly],
                           dtype=float)
            x_min, x_max = float(arr[:, 0].min()), float(arr[:, 0].max())
            y_min, y_max = float(arr[:, 1].min()), float(arr[:, 1].max())
            pad_x = (x_max - x_min) * 0.08
            pad_y = (y_max - y_min) * 0.08
            ax.set_xlim(x_min - pad_x, x_max + pad_x)
            ax.set_ylim(y_max + pad_y, y_min - pad_y)
        else:
            ax.set_xlim(0, vw)
            ax.set_ylim(vh, 0)

        self._apply_style_axes(ax, "Trajectory", st)
        self._apply_style_text(ax, "Trajectory", st)
        # Legend handles — Start / End times + Center % (when enabled).
        from matplotlib.lines import Line2D
        handles = [
            Line2D([], [], color=st["path_color"],
                   linewidth=st["path_width"], label="Trajectory"),
        ]
        if center_shown:
            size_pct = int(st.get("center_size_pct", 45))
            handles.append(Line2D([], [], color=center_col, linestyle=(0, (4, 3)),
                                  linewidth=1.0,
                                  label=f"Center {size_txt}%"))
        handles.extend([
            Line2D([], [], marker=psm, color=st["bg"],
                   markerfacecolor=pcs, markeredgecolor=st["bg"],
                   markersize=6, markeredgewidth=1.0, label="Start"),
            Line2D([], [], marker=pem, color=st["bg"],
                   markerfacecolor=pce, markeredgecolor=st["bg"],
                   markersize=6, markeredgewidth=1.0, label="End"),
        ])
        if plugin_handles:
            handles.extend(plugin_handles)
        self._apply_legend(ax, "Trajectory", st, handles=handles)
        ax.set_aspect("equal", adjustable="box")
        if not shape_polys:
            self._true_shape(fig, ax)
        fig.tight_layout()
        return fig

    def _make_heatmap_fig(self, x, y, arena, shape_polys=None):
        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon
        from matplotlib.path import Path
        from matplotlib import colors as mcolors

        vw, vh = self._graph_canvas_size()
        fps = float(self.fps or 30.0)

        # Collect mask polygons in pixel coords. Canonical maze shape (EPM/
        # Y-Maze remapped) takes precedence; then arena (OF); then extra
        # zones (e.g. Y-Maze arm zones, normalized geom).
        mask_polys_px = []
        if shape_polys:
            mask_polys_px = [np.array(p, dtype=float) for p in shape_polys
                             if len(p) >= 3]
        elif arena and len(arena) >= 3:
            mask_polys_px.append(np.array(arena, dtype=float))
        else:
            try:
                zlist = self.zone_drawer.list_zones() if hasattr(self, "zone_drawer") else []
            except Exception:
                zlist = []
            for z in zlist:
                if not isinstance(z, dict):
                    continue
                # Skip Y-maze control overlays (hub + endpoint dots). Their
                # 4-point geometry connects into a polygon covering the
                # entire inter-arm triangle, which would mask-in regions the
                # mouse never visited.
                style = z.get("style") or {}
                if style.get("shape") == "y_template":
                    continue
                geom = z.get("geometry")
                if not geom or len(geom) < 3:
                    continue
                poly = np.array(
                    [(float(px) * vw, float(py) * vh) for (px, py) in geom],
                    dtype=float,
                )
                mask_polys_px.append(poly)

        # 2D histogram of body positions → seconds per square, blurred.
        # Grid size / blur / unit / fixed max come from the graph style
        # (Customize graphs → Data); see gui.heatmap_grid. Blur is applied
        # BEFORE masking (no NaN propagation).
        st = self._gstyle("Heatmap")
        hm_sec, xedges, yedges, total_s = heatmap_grid.seconds_grid(
            x, y, [0, vw], [0, vh], fps, st)

        # Mask bins outside the tracked region → NaN so they render as the
        # axes facecolor (white). Done AFTER smoothing so the blur stays
        # confined to the tracked region.
        if mask_polys_px:
            xc = 0.5 * (xedges[:-1] + xedges[1:])
            yc = 0.5 * (yedges[:-1] + yedges[1:])
            xx, yy = np.meshgrid(xc, yc, indexing="xy")
            pts = np.column_stack([xx.ravel(), yy.ravel()])
            inside_any = np.zeros(pts.shape[0], dtype=bool)
            for poly in mask_polys_px:
                try:
                    inside_any |= Path(poly).contains_points(pts)
                except Exception:
                    continue
            inside = inside_any.reshape(xx.shape)
            hm_disp = np.where(inside, hm_sec, np.nan)
        else:
            hm_disp = hm_sec

        hm_disp, max_sec = heatmap_grid.scale(hm_disp, total_s, st)

        outer_bg = st.get("outer_bg", "white")
        fig, ax = plt.subplots(figsize=(6, 6 * vh / vw), facecolor=outer_bg)
        ax.set_facecolor(outer_bg)

        # Build cmap with NaN → transparent, without mutating the global.
        from gui.graph_style_dialog import resolve_cmap
        base = resolve_cmap(st)
        cmap = mcolors.LinearSegmentedColormap.from_list(
            "cmap_mask", base(np.linspace(0, 1, 256))
        )
        cmap.set_bad((1, 1, 1, 0))

        # Fill each mask polygon with the cmap-zero color BEFORE imshow so
        # angled arm edges read as a smooth antialiased polygon instead of
        # stair-step bin squares. Bin centers just outside the arm get NaN'd
        # by the mask above and render transparent, letting this fill show
        # through right up to the polygon edge.
        base_color = cmap(0.0)
        for poly in mask_polys_px:
            ax.add_patch(Polygon(poly, closed=True, facecolor=base_color,
                                 edgecolor="none", zorder=0,
                                 antialiased=True))

        im = ax.imshow(
            hm_disp, origin="upper", extent=[0, vw, vh, 0],
            cmap=cmap, interpolation=heatmap_grid.interpolation(st), aspect="auto",
            vmin=0.0, vmax=max_sec if max_sec > 0 else 1.0,
            zorder=1,
        )
        # Clip the heatmap image to the exact mask outline so its square bins
        # are cut smoothly at angled (e.g. Y-maze) walls — no stair-stepping.
        if mask_polys_px:
            verts = []; codes = []
            for poly in mask_polys_px:
                poly = np.asarray(poly)
                verts.extend(list(poly)); verts.append(poly[0])
                codes.extend([Path.MOVETO] + [Path.LINETO] * (len(poly) - 1)
                             + [Path.CLOSEPOLY])
            im.set_clip_path(Path(verts, codes), transform=ax.transData)

        edge_color = st["arena_color"]
        for poly in mask_polys_px:
            ax.add_patch(Polygon(poly, linewidth=st["arena_width"], edgecolor=edge_color,
                                 facecolor="none", closed=True, zorder=2))

        # 4×4 grid lines (OF grid mode only). Respects user `grid` cap+toggle.
        grid_allowed = "grid" in self._graph_style_caps("Heatmap")
        grid_on = bool(st.get("grid", False))
        if (grid_allowed and grid_on
                and arena and len(arena) == 4
                and hasattr(self, "zone_drawer")
                and getattr(self.zone_drawer, "zone_mode", None) == "grid"):
            gc = st.get("grid_color", edge_color)
            ga = float(st.get("grid_alpha", 0.7))
            gls = st.get("grid_linestyle", "-")
            p0, p1, p2, p3 = arena
            for i in range(1, 4):
                t = i / 4.0
                top = (p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1]))
                bot = (p3[0] + t * (p2[0] - p3[0]), p3[1] + t * (p2[1] - p3[1]))
                lft = (p0[0] + t * (p3[0] - p0[0]), p0[1] + t * (p3[1] - p0[1]))
                rgt = (p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1]))
                ax.plot([top[0], bot[0]], [top[1], bot[1]],
                        color=gc, linewidth=0.8, alpha=ga, linestyle=gls)
                ax.plot([lft[0], rgt[0]], [lft[1], rgt[1]],
                        color=gc, linewidth=0.8, alpha=ga, linestyle=gls)

        # Plugin overlay hook (NOR draws object footprints + zones here).
        try:
            exp = getattr(self, "experiment", None)
            if exp is not None:
                exp.decorate_graph(self, "Heatmap", ax, arena)
        except Exception as e:
            logger.warn(f"decorate_graph(Heatmap) failed: {e}", source="plugin")

        # Tight crop to mask bbox (background outside is plain white).
        if mask_polys_px:
            all_pts = np.vstack(mask_polys_px)
            x_min, x_max = float(all_pts[:, 0].min()), float(all_pts[:, 0].max())
            y_min, y_max = float(all_pts[:, 1].min()), float(all_pts[:, 1].max())
            pad_x = (x_max - x_min) * 0.05
            pad_y = (y_max - y_min) * 0.05
            ax.set_xlim(x_min - pad_x, x_max + pad_x)
            ax.set_ylim(y_max + pad_y, y_min - pad_y)  # inverted (image coords)

        self._apply_style_axes(ax, "Heatmap", st)
        self._apply_style_text(ax, "Heatmap", st)

        # Horizontal colorbar at bottom — user toggle + position/size.
        if st.get("colorbar_show", True):
            try:
                # Base rect + user offsets. Clamps keep the bar inside the
                # figure and avoid zero/negative width or height.
                bx = 0.06 + float(st.get("colorbar_x", 0.0))
                by = 0.06 + float(st.get("colorbar_y", 0.0))
                bw = max(0.05, 0.88 + float(st.get("colorbar_w", 0.0)))
                bh = max(0.005, 0.04 + float(st.get("colorbar_h", 0.0)))
                cb_rect = [bx, by, bw, bh]
                cax = fig.add_axes(cb_rect)
                cbar = fig.colorbar(im, cax=cax, orientation="horizontal")
                cbar.set_ticks([0.0, max_sec if max_sec > 0 else 1.0])
                cbar.set_ticklabels(heatmap_grid.tick_labels(max_sec, st))
                cbar.ax.tick_params(labelsize=int(st.get("tick_size", 9)), length=0,
                                    colors=st.get("tick_color", "#333333"))
                try:
                    cbar.ax.tick_params(labelfontfamily=theme.mono_family())
                except Exception:
                    pass
                cbar.outline.set_visible(False)
                lbl = heatmap_grid.colorbar_label(st)
                if lbl:
                    cbar.set_label(lbl,
                                   fontsize=int(st.get("tick_size", 9)),
                                   color=st.get("text_color", "#333333"))
                # Reserve a bit more bottom margin when the bar sits low so
                # the imshow axes don't overlap it.
                # Fixed margin: moving the colour bar must not resize the plot
                # (the plot area is sized by its own chart-editor handles).
                bot_margin = 0.14
                if getattr(self, '_cm_axes_on', False):
                    bot_margin = max(bot_margin, 0.27)   # room for the X (cm) ruler
                fig.subplots_adjust(top=0.96, bottom=bot_margin,
                                    left=0.11 if getattr(self, '_cm_axes_on', False) else 0.04,
                                    right=0.96)
            except Exception:
                pass

        if mask_polys_px and not shape_polys:
            self._true_shape(fig, ax)
        return fig

    def _cell_divider_style(self, name, st, fallback_color):
        """(color, alpha, linestyle, axis) for Cell Time's between-cell
        lines: the user's gridline style when Gridlines is on, else plain
        solid dividers in the arena colour. axis: 'both' / 'x' (vertical
        lines) / 'y' (horizontal lines)."""
        if "grid" in self._graph_style_caps(name) and st.get("grid", False):
            return (st.get("grid_color", fallback_color),
                    float(st.get("grid_alpha", 1.0)),
                    st.get("grid_linestyle", "-"),
                    st.get("grid_axis", "both"))
        return fallback_color, 1.0, "-", "both"

    def _make_cell_time_heatmap_fig(self, arena):
        """Per-cell aggregate-time heatmap. Each grid cell is filled with a
        uniform color proportional to its total time-in-cell (debounced —
        matches the Excel 'Cell N Time (s)' numbers). Only applies in OF
        grid zone-mode with a 4-corner arena. Returns None otherwise so the
        graph loop skips it gracefully."""
        if not (arena and len(arena) == 4):
            return None
        if not (hasattr(self, "zone_drawer")
                and getattr(self.zone_drawer, "zone_mode", None) == "grid"):
            return None
        metrics = getattr(self, "metrics", None) or {}

        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon
        from matplotlib import colors as mcolors

        # Collect per-cell times (1..16). Missing keys default to 0.
        times = {}
        for cid in range(1, 17):
            try:
                times[cid] = float(metrics.get(f"Cell {cid} Time (s)", 0.0) or 0.0)
            except (TypeError, ValueError):
                times[cid] = 0.0
        max_sec = max(times.values()) if times else 0.0

        # Bbox of arena for tight crop.
        arr = np.array(arena, dtype=float)
        x_min, x_max = float(arr[:, 0].min()), float(arr[:, 0].max())
        y_min, y_max = float(arr[:, 1].min()), float(arr[:, 1].max())

        st = self._gstyle("Cell Time")
        outer_bg = st.get("outer_bg", "white")
        vw, vh = self._graph_canvas_size()
        fig, ax = plt.subplots(figsize=(6, 6 * vh / vw), facecolor=outer_bg)
        ax.set_facecolor(outer_bg)

        # Sequential colormap from style. Default YlOrRd reads brightness as
        # magnitude — no rainbow noise. resolve_cmap honors a user's custom
        # palette (cmap_c1..c5 stops) when cmap == "custom".
        from gui.graph_style_dialog import resolve_cmap
        base = resolve_cmap(st)
        cmap = mcolors.LinearSegmentedColormap.from_list(
            "cells_cmap", base(np.linspace(0, 1, 256))
        )
        norm = mcolors.Normalize(vmin=0.0, vmax=max_sec if max_sec > 0 else 1.0)

        # Fill each cell with its color + write the time label.
        edge_color = st["arena_color"]
        arena_w = st["arena_width"]
        for row in range(4):
            for col in range(4):
                cid = row * 4 + col + 1
                t = times.get(cid, 0.0)
                quad = self._grid_cell_quad_px(arena, row, col)
                ax.add_patch(Polygon(quad, closed=True,
                                     facecolor=cmap(norm(t)),
                                     edgecolor="none", linewidth=0))
                # Cell number + time label, centered (with optional offset).
                cx = sum(p[0] for p in quad) / 4.0
                cy = sum(p[1] for p in quad) / 4.0
                cx += float(st.get("cell_label_dx", 0))
                cy += float(st.get("cell_label_dy", 0))
                # Pick text color based on background brightness for contrast.
                r, g, b, _ = cmap(norm(t))
                text_color = "#FFFFFF" if (0.299*r + 0.587*g + 0.114*b) < 0.5 else "#1C2127"
                ax.text(cx, cy, f"{cid}\n{t:.1f}s",
                        ha="center", va="center", color=text_color,
                        fontsize=int(st.get("cell_label_size", 9)),
                        fontweight="bold" if st.get("cell_label_bold") else "normal",
                        linespacing=1.1,
                        fontfamily=st.get("cell_label_font") or theme.mono_family())

        # Lines between the cells — Plot area → Gridlines styles them;
        # off = the plain thin dividers in the arena colour.
        gc, ga, gls, gax = self._cell_divider_style("Cell Time", st, edge_color)
        # Same corner order (TL, TR, BR, BL) the cells are built from.
        p0, p1, p2, p3 = self.zone_drawer._sorted_corners(arena)
        for i in range(1, 4):
            f = i / 4.0
            top = (p0[0] + f * (p1[0] - p0[0]), p0[1] + f * (p1[1] - p0[1]))
            bot = (p3[0] + f * (p2[0] - p3[0]), p3[1] + f * (p2[1] - p3[1]))
            lft = (p0[0] + f * (p3[0] - p0[0]), p0[1] + f * (p3[1] - p0[1]))
            rgt = (p1[0] + f * (p2[0] - p1[0]), p1[1] + f * (p2[1] - p1[1]))
            for a, b, want in ((top, bot, gax in ("both", "x")),
                               (lft, rgt, gax in ("both", "y"))):
                if not want:
                    continue
                ax.plot([a[0], b[0]], [a[1], b[1]], color=gc, alpha=ga,
                        linestyle=gls, linewidth=1.0, zorder=3)

        # Arena outline on top.
        ax.add_patch(Polygon(arena, closed=True, facecolor="none",
                             edgecolor=edge_color, linewidth=arena_w, zorder=4))

        # Tight crop.
        pad_x = (x_max - x_min) * 0.05
        pad_y = (y_max - y_min) * 0.05
        ax.set_xlim(x_min - pad_x, x_max + pad_x)
        ax.set_ylim(y_max + pad_y, y_min - pad_y)  # inverted for image coords

        self._apply_style_axes(ax, "Cell Time", st)
        self._apply_style_text(ax, "Cell Time", st)

        # Bottom colorbar — user toggle + position/size.
        if st.get("colorbar_show", True):
            try:
                sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
                sm.set_array([])
                bx = 0.06 + float(st.get("colorbar_x", 0.0))
                by = 0.06 + float(st.get("colorbar_y", 0.0))
                bw = max(0.05, 0.88 + float(st.get("colorbar_w", 0.0)))
                bh = max(0.005, 0.04 + float(st.get("colorbar_h", 0.0)))
                cb_rect = [bx, by, bw, bh]
                cax = fig.add_axes(cb_rect)
                cbar = fig.colorbar(sm, cax=cax, orientation="horizontal")
                cbar.set_ticks([0.0, max_sec if max_sec > 0 else 1.0])
                cbar.set_ticklabels(["0s", (f"{max_sec:.2f}s" if max_sec < 1 else f"{max_sec:.1f}s")])
                cbar.ax.tick_params(labelsize=int(st.get("tick_size", 9)), length=0,
                                    colors=st.get("tick_color", "#333333"))
                try:
                    cbar.ax.tick_params(labelfontfamily=theme.mono_family())
                except Exception:
                    pass
                cbar.outline.set_visible(False)
                lbl = st.get("colorbar_label") or ""
                if lbl:
                    cbar.set_label(lbl,
                                   fontsize=int(st.get("tick_size", 9)),
                                   color=st.get("tick_color", "#333333"))
                # Fixed margin: moving the colour bar must not resize the plot
                # (the plot area is sized by its own chart-editor handles).
                bot_margin = 0.14
                if getattr(self, '_cm_axes_on', False):
                    bot_margin = max(bot_margin, 0.27)   # room for the X (cm) ruler
                fig.subplots_adjust(top=0.96, bottom=bot_margin,
                                    left=0.11 if getattr(self, '_cm_axes_on', False) else 0.04,
                                    right=0.96)
            except Exception:
                pass

        self._true_shape(fig, ax)
        return fig

    def _make_zone_bar_fig(self):
        import matplotlib.pyplot as plt
        st = self._gstyle("Zone Time")
        fps = self.fps or 30

        # Per-experiment categories live on the plugin (EPM open/closed/center,
        # Y-Maze arms, NOR objects). Default = Open-Field center/periphery.
        bar_title = bar_ylabel = None
        spec = None
        exp = getattr(self, "experiment", None)
        if exp is not None and hasattr(exp, "zone_bar_data"):
            try:
                spec = exp.zone_bar_data(self)
            except Exception as e:
                logger.warn(f"zone_bar_data failed: {e}", source="plugin")
                spec = None
        if spec:
            labels, values, default_colors, value_fmt, bar_title, bar_ylabel = spec
        else:
            df = self.raw_df
            zones  = ["center_zone", "periphery", "undetected", "outside"]
            labels = ["Center Zone", "Periphery", "Undetected", "Outside"]
            default_colors = resolve_token(["@ac", "@ink3", "@warn", "@err"], "data")
            values = [(df["Zone"] == z).sum() / fps for z in zones]
            value_fmt = lambda v: f"{v:.1f}s"

        # Chosen time unit — only for bars measured in seconds (the plugin's
        # axis title says "(s)"; Y-Maze bars are shares in %).
        if bar_ylabel is None or re.search(r"\(s\)\s*$", bar_ylabel):
            if bar_ylabel is not None:
                st = dict(st, ylabel=bar_ylabel)
            tfac, t_unit, st = time_axis(st, "ylabel")
            if bar_ylabel is not None:
                bar_ylabel = st["ylabel"]
            values = [v * tfac for v in values]
            value_fmt = ((lambda v: f"{v:.1f}s") if t_unit == "s"
                         else (lambda v: f"{v:.2f} min"))

        colors = list(st.get("bar_colors") or default_colors)
        while len(colors) < len(labels):
            colors.append("#888888")

        tc = st.get("tick_color", self._text_color_for_bg(st["bg"]))
        fig, ax = plt.subplots(figsize=(6, 3.4), facecolor=st["bg"])
        ax.set_facecolor(st["bg"])
        bars = ax.bar(labels, values, color=colors[:len(labels)], width=0.4)
        # Headroom for labels above the tallest bar.
        max_v = max(values) if values else 0.0
        if max_v > 0:
            ax.set_ylim(0, max_v * 1.18)
        for bar, v in zip(bars, values):
            if v > 0:
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + (max_v * 0.02 if max_v else 0.3),
                        value_fmt(v), ha="center", color=tc,
                        fontsize=int(st.get("tick_size", 9)),
                        fontfamily=theme.mono_family())
        self._apply_style_axes(ax, "Zone Time", st)
        self._apply_style_text(ax, "Zone Time", st)
        if bar_title:
            ax.set_title(bar_title, color=tc,
                         fontsize=int(st.get("title_size", 12)))
        if bar_ylabel:
            size, bold, color = axis_title_style(st, "ylabel")
            ax.set_ylabel(bar_ylabel, color=color, fontsize=size,
                          fontweight="bold" if bold else "normal")
        fig.tight_layout()
        return fig

    def _make_triplets_fig(self):
        """Y-maze only: Acceptable vs Unacceptable triplet share. Returns
        None for non-Y-maze experiments so the builder loop skips it."""
        if getattr(self.experiment, "key", None) != "y_maze":
            return None
        import matplotlib.pyplot as plt
        st = self._gstyle("Triplets")
        m = getattr(self, "metrics", None) or {}
        ok = int(m.get("triplets_acceptable_count", 0) or 0)
        bad = int(m.get("triplets_unacceptable_count", 0) or 0)
        total = ok + bad
        if total <= 0:
            return None
        ok_pct = ok / total * 100.0
        bad_pct = bad / total * 100.0
        labels = ["Acceptable", "Unacceptable"]
        values = [ok_pct, bad_pct]
        counts = [ok, bad]
        default_colors = ["#4CAF50", "#E5484D"]
        colors = list(st.get("bar_colors") or default_colors)
        while len(colors) < len(labels):
            colors.append("#888888")
        tc = st.get("tick_color", self._text_color_for_bg(st["bg"]))
        fig, ax = plt.subplots(figsize=(5, 3), facecolor=st["bg"])
        ax.set_facecolor(st["bg"])
        bars = ax.bar(labels, values, color=colors[:len(labels)], width=0.5)
        ax.set_ylim(0, max(100.0, max(values) * 1.18))
        for bar, v, c in zip(bars, values, counts):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 2.0,
                    f"{v:.1f}%\n(n={c})", ha="center", color=tc,
                    fontsize=int(st.get("tick_size", 9)))
        self._apply_style_axes(ax, "Triplets", st)
        self._apply_style_text(ax, "Triplets", st)
        fig.tight_layout()
        return fig

    def _make_speed_fig(self):
        import matplotlib.pyplot as plt
        st = self._gstyle("Speed")
        df = self.raw_df
        fps = self.fps or 30
        px_per_cm = self._get_px_per_cm()

        x = df["X (px)"].values.astype(float)
        y = df["Y (px)"].values.astype(float)
        t = df["Time (s)"].values.astype(float)

        dist_px = np.sqrt(np.diff(x)**2 + np.diff(y)**2)
        speed = dist_px * fps
        calibrated = bool(px_per_cm and px_per_cm > 0)
        if calibrated:
            speed = speed / px_per_cm
        # Chosen speed unit (Customize graphs → Speed unit); axis title follows.
        factor, sp_unit, st = speed_axis(st, "Speed", "cm/s" if calibrated else "px/s")
        speed = speed * factor
        tfac, _t_unit, st = time_axis(st, "xlabel")      # chosen time unit

        time = t[1:] * tfac
        fig, ax = plt.subplots(figsize=(8, 3), facecolor=st["bg"])
        ax.set_facecolor(st["bg"])
        ls = st.get("linestyle", "-")
        mk = st.get("marker", "none")
        mk_plt = "" if mk == "none" else mk
        alpha = float(st.get("alpha", 0.9))
        ax.plot(time, speed, color=st["path_color"],
                linewidth=max(0.3, st["path_width"] * 0.6),
                alpha=alpha * 0.45, linestyle=ls,
                marker=mk_plt, markersize=int(st.get("marker_size", 5)))
        win = max(1, int(fps))
        if len(speed) > win:
            kernel = np.ones(win) / win
            speed_filled = np.where(np.isnan(speed), 0.0, speed)
            smooth = np.convolve(speed_filled, kernel, mode="same")
            ax.plot(time, smooth, color=st["path_color"],
                    linewidth=st["path_width"], alpha=alpha,
                    linestyle=ls, label=f"{win}-frame avg")
        # Movement threshold (dashed) — same units as the curve.
        try:
            thr = float(self.spin_movement_thr.value())
        except Exception:
            thr = 0.0
        if thr > 0 and len(time):
            thr = thr * factor               # threshold is set in cm/s
            wc = resolve_token("@warn", "data")
            ax.axhline(thr, color=wc, linestyle=(0, (5, 3)), linewidth=1.0)
            ax.text(float(time.max()), thr, f"move threshold {thr:.3g} {sp_unit}",
                    ha="right", va="bottom", color=wc, fontsize=9)
        # Axis titles (with units) are filled in by speed_axis / time_axis.
        self._apply_style_axes(ax, "Speed", st)
        self._apply_style_text(ax, "Speed", st)
        self._apply_legend(ax, "Speed", st)
        fig.tight_layout()
        return fig

    def _make_speed_histogram_fig(self):
        """Histogram of per-frame speeds with median / P90 / P99 lines."""
        import matplotlib.pyplot as plt
        st = self._gstyle("Speed Histogram")
        df = self.raw_df
        unit_col = next((c for c in df.columns if c.startswith("Speed")), None)
        if unit_col is None:
            return None
        speeds = df[unit_col].dropna().values
        if len(speeds) < 2:
            return None
        unit = unit_col.split("(")[-1].rstrip(")")  # e.g. "cm/s"
        # Chosen speed unit (Customize graphs → Speed unit); axis title follows.
        factor, unit, st = speed_axis(st, "Speed Histogram", unit)
        speeds = speeds * factor
        tfac, _t_unit, st = time_axis(st, "ylabel")      # bar height = time
        med = float(np.median(speeds))
        p90 = float(np.quantile(speeds, 0.90))
        p99 = float(np.quantile(speeds, 0.99))
        fig, ax = plt.subplots(figsize=(8, 3.5), facecolor=st["bg"])
        ax.set_facecolor(st["bg"])
        upper = min(float(np.max(speeds)), p99 * 1.5 + 1e-6)
        fps_h = float(self.fps or 30.0)
        ax.hist(speeds, bins=60, range=(0, upper), color=st["path_color"],
                weights=np.full(len(speeds), tfac / fps_h),
                edgecolor=st.get("hist_edge_color", "#222222"), linewidth=0.5)
        mode_h = "data"                 # same stat-line colours on screen and in files
        for v, lbl, c in (
            (med, "median", resolve_token(GRAPH_ACCENTS["stat_median"], mode_h)),
            (p90, "P90",    resolve_token(GRAPH_ACCENTS["stat_p90"], mode_h)),
            (p99, "P99",    resolve_token(GRAPH_ACCENTS["stat_p99"], mode_h)),
        ):
            ax.axvline(v, color=c, linewidth=1.0, linestyle=(0, (4, 3)),
                       label=f"{lbl}: {v:.3g} {unit}")
            ax.text(v, ax.get_ylim()[1] * 0.97, f" {lbl} {v:.3g}", color=c,
                    fontsize=9, ha="left", va="top")
        self._apply_style_axes(ax, "Speed Histogram", st)
        self._apply_style_text(ax, "Speed Histogram", st)
        self._apply_legend(ax, "Speed Histogram", st)
        fig.tight_layout()
        return fig

    def _make_habituation_fig(self):
        """Per-bin distance + linear-fit slope. Habituation = how much
        movement declines across the session."""
        import matplotlib.pyplot as plt
        st = self._gstyle("Habituation")
        if self.bin_df is None or self.bin_df.empty:
            return None
        df = self.bin_df
        dist_col = next((c for c in df.columns if c.startswith("Distance")), None)
        if dist_col is None:
            return None
        unit = dist_col.split("(")[-1].rstrip(")")  # e.g. "cm"
        # Chosen units: distance on y, time on x (bins are stored in s / cm).
        dfac, unit, st = distance_axis(st, "ylabel", unit)
        tfac, t_unit, st = time_axis(st, "xlabel", "s", "Bin center")
        x_start = df["Bin Start (s)"].values.astype(float) * tfac
        if "Bin End (s)" in df.columns:
            bin_w = (df["Bin End (s)"].values.astype(float) * tfac - x_start)
        else:
            bin_w = np.full(len(x_start), (x_start[1] - x_start[0]) if len(x_start) > 1 else tfac)
        x_vals = x_start + bin_w / 2.0            # bin centres
        y_vals = df[dist_col].values.astype(float) * dfac
        fig, ax = plt.subplots(figsize=(8, 3.5), facecolor=st["bg"])
        ax.set_facecolor(st["bg"])
        bar_col = st["path_color"]
        ax.bar(x_vals, y_vals, width=bin_w * 0.7, color=bar_col,
               alpha=float(st.get("alpha", 0.9)))
        if len(x_vals) <= 12:
            for xv, yv in zip(x_vals, y_vals):
                ax.text(xv, yv + max(y_vals) * 0.015, f"{yv:.3g}", ha="center",
                        va="bottom", fontsize=int(st.get("tick_size", 9)),
                        color=st.get("tick_color", "#333"),
                        fontfamily=theme.mono_family())
        if len(x_vals) >= 2:
            slope, intercept = np.polyfit(x_vals, y_vals, 1)
            fit = slope * x_vals + intercept
            # Per minute, as in the Excel "Habituation Slope (…/min)".
            per_min = slope * tfac * 60.0
            ax.plot(x_vals, fit, color=resolve_token(GRAPH_ACCENTS["linfit"], "data"),
                    linestyle=(0, (6, 3)), linewidth=1.2,
                    label=f"slope {per_min:+.3g} {unit}/min")
        ax.set_ylim(0, max(y_vals) * 1.18 if len(y_vals) and max(y_vals) > 0 else 1)
        self._apply_style_axes(ax, "Habituation", st)
        self._apply_style_text(ax, "Habituation", st)
        self._apply_legend(ax, "Habituation", st)
        fig.tight_layout()
        return fig


    @staticmethod
    def _fig_to_pixmap_and_bytes(fig):
        import matplotlib.pyplot as plt
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        png_bytes = buf.getvalue()
        pix = QPixmap()
        pix.loadFromData(png_bytes)
        plt.close(fig)
        return pix, png_bytes

