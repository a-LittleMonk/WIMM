"""Plugin contract for an experiment type.

Each experiment owns its zone schema, a per-experiment geometry config
group, result tabs, metric computation, batch-export columns, and the
extra per-video state to persist beyond the shared snapshot.
"""
from typing import List, Tuple


class Experiment:
    name: str = "Experiment"
    key: str  = "experiment"

    # ── Zones ────────────────────────────────────────────────────────────
    def zones_schema(self, host) -> List[dict]:
        """Return the current zone schema list given host state.
        Pure read of host attributes — doesn't mutate the drawer."""
        return []

    # ── UI ───────────────────────────────────────────────────────────────
    def build_geometry_step(self, host):
        """Return a QGroupBox for Step 2 — Geometry. Replaces _step_geometry."""
        raise NotImplementedError

    def build_results_tabs(self, host, right_tabs):
        """Add experiment-specific tabs to the right_tabs / excel_tabs widget.
        Receives the host (ExperimentTab) and the QTabWidget to populate."""
        return None

    # ── Analysis ─────────────────────────────────────────────────────────
    def compute_metrics(self, results, settings, fps, px_per_cm) -> Tuple[dict, object, object]:
        """Returns (metrics_dict, raw_df, bin_df)."""
        raise NotImplementedError

    def export_columns(self) -> List[str]:
        """Order of summary columns for the batch Excel export."""
        return []

    def batch_schema(self):
        """Optional section-grouped column schema for the combined
        Excel master sheet. When provided, drives the row-1 / row-2 /
        row-3+ layout. Format: list of (section_name, [col, col, ...]).
        Return None to fall back to "first-seen-across-animals" order."""
        return None

    # ── Per-video state ──────────────────────────────────────────────────
    def snapshot_extras(self, host) -> dict:
        """Per-video state beyond the shared snapshot. E.g., OF needs
        cell_categories / cell_min_dwell, Y-Maze needs entry rule, arms."""
        return {}

    def apply_extras(self, host, extras: dict):
        """Restore experiment-specific state from snapshot_extras output."""
        return None

    # ── Snapshot hook ────────────────────────────────────────────────────
    def contribute_to_snapshot(self, host, snapshot: dict):
        """Mutate the shared per-video snapshot dict to add/override
        experiment-specific keys. Called from ExperimentTab.snapshot_settings
        after the base dict is built. Used by Y-Maze to inject arm polygons
        and synthesize a tracker arena from them."""
        return None

    # ── Export filtering ────────────────────────────────────────────────
    def filter_video_config(self, snapshot: dict) -> dict:
        """Return the dict of settings that should appear in the per-video
        Excel's Video Config sheet. Default: pass everything through.
        Plugins can drop keys that don't apply to their experiment."""
        return snapshot

    # ── Auto-calibration ────────────────────────────────────────────────
    def compute_auto_px_per_cm(self, snapshot, video_size):
        """Plugin-supplied auto-cal that converts geometry + real-world
        measurements into pixels-per-cm. Return a float or None. Reads
        from `snapshot` (per-video settings dict) so the same path works
        for the live tab and headless batch runs."""
        return None

    # ── Scale-step visibility ──────────────────────────────────────────
    def refresh_scale_step_visibility(self, host, calib_mode):
        """Show/hide experiment-specific Scale-step inputs for the given
        calib mode ('auto' | 'manual' | 'none'). OF shows cage W×H, Y-Maze
        shows arm-length. Called from ExperimentTab._refresh_calib_mode_visibility."""
        return None

    # ── Summary table ──────────────────────────────────────────────────
    def summary_table_keys(self, metrics):
        """Ordered list of metric keys to render in the Output → Summary
        table. Keys missing from the metrics dict are silently skipped.
        Return None to fall back to dict-iteration order (show every key)."""
        return None

    # ── Results-tab population ─────────────────────────────────────────
    def populate_results_tab(self, host, metrics):
        """Fill any experiment-specific results tab (built earlier by
        build_results_tabs) from the post-tracking metrics dict. Called
        from ExperimentTab._refresh_summary_table.

        Default: no-op."""
        return None

    # ── Preflight ──────────────────────────────────────────────────────
    def preflight_auto_scale_warning(self, snapshot):
        """Plugin-supplied warning for the batch pre-flight dialog when
        the user has picked auto-calibration. Return a string explaining
        what's missing for auto-cal to work, or None if everything is set.

        Default: None (no plugin-specific check)."""
        return None

    # ── View popup contributions ───────────────────────────────────────
    def live_overlay_label(self):
        """Label for the 'Live overlay during tracking' checkbox shown in
        Step 5. Each experiment names it after its primary live element
        (cell highlight, arm fill, etc.)."""
        return "Live overlay during tracking (slower)"

    def cell_highlight_toggle_specs(self, host):
        """Per-experiment toggles appended below the generic Cell-highlight
        rows (Color / Opacity / Live overlay / Min dwell) in the View popup.

        Return a list of (label, getter, setter) where:
          label   — checkbox text
          getter  — callable() -> initial bool
          setter  — callable(bool) called on toggle

        Default: no extra rows."""
        return []

    # ── Output graph decoration ────────────────────────────────────────
    def decorate_graph(self, host, graph_name: str, ax, arena_px):
        """Optional hook for plugins to draw experiment-specific overlays
        on top of an output graph (e.g., NOR object footprints + zones).

        Called from ExperimentTab._make_trajectory_fig and
        _make_heatmap_fig after the main paint, before legend assembly.
        `arena_px` is the arena polygon in pixel coords (graph axes are
        pixel-aligned). Default: no-op.

        Plugins should add matplotlib artists directly to `ax`. Return
        an optional list of legend handles to extend the graph legend
        (or None to skip)."""
        return None

    def canonical_arm_layout(self, host):
        """Geometry for remapping the real tracked path onto a canonical
        idealized maze (EPM +, Y-Maze Y) so the output Trajectory/Heatmap
        match the styling preview. Return None to disable (Open-Field / NOR
        use their real arena unchanged).

        When provided, return:
            {
              "hub":  (nx, ny),                       # normalized hub point
              "arms": [ {"poly": [(nx,ny), ...],      # arm polygon, normalized
                         "cdir": (dx, dy)}, ... ],    # canonical dir (math y-up)
            }
        `cdir` must use the same canonical directions as
        gui.graph_style_dialog.maze_canonical_dirs(self.key)."""
        return None

    def zone_bar_data(self, host):
        """Per-experiment categories for the 'Zone Time' bar chart. Return
        (labels, values, default_colors, value_fmt, title, ylabel) or None to
        use the Open-Field default (Center / Periphery / Undetected / Outside).

        Lives on the plugin because each paradigm has its own zones: EPM =
        open/closed/center, Y-Maze = arms, NOR = objects. `value_fmt` is a
        callable v->str. `title`/`ylabel` may be None to keep the styled
        defaults."""
        return None

    # ── Output graphs catalog ──────────────────────────────────────────
    def graph_names(self) -> List[str]:
        """Ordered list of GRAPH_NAMES this experiment produces. Drives
        which tabs the Customize-Graphs dialog shows for this plugin, and
        which graphs the Output tab builds. Default: every shared graph
        except Triplets (Y-Maze only)."""
        from gui.graph_style import GRAPH_NAMES
        return [g for g in GRAPH_NAMES if g != "Triplets"]

    def graph_caps(self, graph_name: str) -> set:
        """Optional capability flags appended to the GRAPH_FIELDS allow-
        list for `graph_name`. Recognized flags:
            'grid'        — exposes grid_* fields
            'center_pct'  — exposes show_center_pct / center_pct_color /
                            center_size_pct
        Default: no extras."""
        return set()

    # ── Nose detection default ─────────────────────────────────────────
    def default_enable_nose(self) -> bool:
        """Whether the per-experiment Step 5 "Nose detection" checkbox is
        on by default for this paradigm. NOR overrides to True (its angle
        filter wants the nose heading); OF / Y-Maze / EPM keep the body-
        center-only fast path and let the user opt in if they want nose
        columns in the Raw Data export."""
        return False

    # ── Perspective correction ─────────────────────────────────────────
    def build_tracking_homography(self, snapshot: dict, video_size):
        """Return (H, (warp_w, warp_h)) for the tracker to warp every
        frame before processing, or None to use the default cage-based
        homography. Y-Maze maps hub + 3 endpoints onto a canonical 120°
        Y so the warped frame removes camera tilt."""
        return None
