"""User-customizable graph styling.

Per-graph style config (one entry per graph name) plus named presets.
ExperimentTab loads/saves through the main app config JSON.
"""
from copy import deepcopy

GRAPH_NAMES = [
    "Trajectory", "Heatmap", "Cell Time",
    "Speed", "Speed Histogram", "Habituation", "Zone Time", "Triplets",
]

# Accent colors used by stats overlays (median/P90/P99 markers, linear-fit
# line). Centralized here so dialog preview and real renderer never drift.
ACCENT_COLORS = {
    "stat_median": "#3CDC64",
    "stat_p90":    "#FFD740",
    "stat_p99":    "#FF6464",
    "linfit":      "#FF8844",
}

# Style sections — group related fields. The dialog organizes its tabs
# around these. DEFAULT_CAPS lists the *sections* each graph enables.
SECTION_FIELDS = {
    "basic":   ["bg", "outer_bg", "title", "xlabel", "ylabel"],
    "fonts":   ["font_family", "title_size", "title_bold",
                "label_size", "label_bold", "tick_size", "tick_bold"],
    "lines":   ["path_color", "path_width", "linestyle", "alpha",
                "marker", "marker_size"],
    "axes":    ["spine_top", "spine_right", "spine_bottom", "spine_left",
                "spine_color", "spine_width", "tick_color", "show_ticks",
                "grid", "grid_color", "grid_alpha", "grid_linestyle", "grid_axis",
                "arena_color", "arena_width", "cmap",
                "cmap_custom_n",
                "cmap_c1", "cmap_c2", "cmap_c3", "cmap_c4", "cmap_c5"],
    "extras":  ["legend_show", "legend_loc", "legend_bg", "legend_fontsize",
                "legend_draggable", "legend_inset_pct",
                "pin_start_color", "pin_end_color",
                "pin_start_marker", "pin_end_marker", "pin_size",
                "bar_colors", "hist_edge_color",
                "colorbar_show", "colorbar_label",
                "show_center_pct", "center_pct_color", "center_size_pct"],
    "layout":  ["title_pad",
                "colorbar_x", "colorbar_y", "colorbar_w", "colorbar_h",
                "cell_label_dx", "cell_label_dy",
                "legend_x_offset", "legend_y_offset"],
}

# Sections each graph supports. Dialog tab visibility uses this.
DEFAULT_CAPS = {
    "Trajectory":      {"basic", "fonts", "lines", "axes", "extras", "layout"},
    "Heatmap":         {"basic", "fonts", "axes", "extras", "layout"},
    "Cell Time":       {"basic", "fonts", "axes", "extras", "layout"},
    "Speed":           {"basic", "fonts", "lines", "axes", "extras", "layout"},
    "Speed Histogram": {"basic", "fonts", "lines", "axes", "extras", "layout"},
    "Habituation":     {"basic", "fonts", "lines", "axes", "extras", "layout"},
    "Zone Time":       {"basic", "fonts", "axes", "extras", "layout"},
    "Triplets":        {"basic", "fonts", "axes", "extras", "layout"},
}

# Per-graph field allow-list inside each section. Fields not listed here
# are hidden in the dialog. ExperimentTab subclasses may further filter
# (e.g. only OF allows `grid` on Heatmap / Cell Time).
GRAPH_FIELDS = {
    "Trajectory":      {"bg", "outer_bg", "title",
                        "font_family", "title_size", "title_bold",
                        "path_color", "path_width", "linestyle", "alpha",
                        "marker", "marker_size",
                        "spine_top", "spine_right", "spine_bottom", "spine_left",
                        "spine_color", "spine_width",
                        "arena_color", "arena_width",
                        "pin_start_color", "pin_end_color",
                        "pin_start_marker", "pin_end_marker", "pin_size",
                        "legend_show", "legend_loc", "legend_bg",
                        "legend_fontsize", "legend_draggable", "legend_inset_pct",
                        "title_pad", "legend_x_offset", "legend_y_offset"},
    "Heatmap":         {"outer_bg", "title",
                        "font_family", "title_size", "title_bold",
                        "spine_top", "spine_right", "spine_bottom", "spine_left",
                        "spine_color", "spine_width",
                        "grid", "grid_color", "grid_alpha", "grid_linestyle",
                        "arena_color", "arena_width", "cmap",
                        "cmap_custom_n",
                        "cmap_c1", "cmap_c2", "cmap_c3", "cmap_c4", "cmap_c5",
                        "colorbar_show", "colorbar_label",
                        "title_pad",
                        "colorbar_x", "colorbar_y", "colorbar_w", "colorbar_h"},
    "Cell Time":       {"outer_bg", "title",
                        "font_family", "title_size", "title_bold",
                        "spine_top", "spine_right", "spine_bottom", "spine_left",
                        "spine_color", "spine_width",
                        "arena_color", "arena_width", "cmap",
                        "cmap_custom_n",
                        "cmap_c1", "cmap_c2", "cmap_c3", "cmap_c4", "cmap_c5",
                        "colorbar_show", "colorbar_label",
                        "title_pad",
                        "colorbar_x", "colorbar_y", "colorbar_w", "colorbar_h",
                        "cell_label_dx", "cell_label_dy"},
    "Speed":           {"bg", "title", "xlabel", "ylabel",
                        "font_family", "title_size", "title_bold",
                        "label_size", "label_bold", "tick_size", "tick_bold",
                        "path_color", "path_width", "linestyle", "alpha",
                        "marker", "marker_size",
                        "spine_top", "spine_right", "spine_bottom", "spine_left",
                        "spine_color", "spine_width", "tick_color", "show_ticks",
                        "grid", "grid_color", "grid_alpha", "grid_linestyle", "grid_axis",
                        "legend_show", "legend_loc", "legend_bg",
                        "legend_fontsize", "legend_draggable", "legend_inset_pct",
                        "title_pad", "legend_x_offset", "legend_y_offset"},
    "Speed Histogram": {"bg", "title", "xlabel", "ylabel",
                        "font_family", "title_size", "title_bold",
                        "label_size", "label_bold", "tick_size", "tick_bold",
                        "path_color",
                        "spine_top", "spine_right", "spine_bottom", "spine_left",
                        "spine_color", "spine_width", "tick_color", "show_ticks",
                        "grid", "grid_color", "grid_alpha", "grid_linestyle", "grid_axis",
                        "hist_edge_color",
                        "legend_show", "legend_loc", "legend_bg",
                        "legend_fontsize", "legend_draggable", "legend_inset_pct",
                        "title_pad", "legend_x_offset", "legend_y_offset"},
    "Habituation":     {"bg", "title", "xlabel", "ylabel",
                        "font_family", "title_size", "title_bold",
                        "label_size", "label_bold", "tick_size", "tick_bold",
                        "path_color", "path_width", "linestyle", "alpha",
                        "marker", "marker_size",
                        "spine_top", "spine_right", "spine_bottom", "spine_left",
                        "spine_color", "spine_width", "tick_color", "show_ticks",
                        "grid", "grid_color", "grid_alpha", "grid_linestyle", "grid_axis",
                        "legend_show", "legend_loc", "legend_bg",
                        "legend_fontsize", "legend_draggable", "legend_inset_pct",
                        "title_pad", "legend_x_offset", "legend_y_offset"},
    "Zone Time":       {"bg", "title", "ylabel",
                        "font_family", "title_size", "title_bold",
                        "label_size", "label_bold", "tick_size", "tick_bold",
                        "spine_top", "spine_right", "spine_bottom", "spine_left",
                        "spine_color", "spine_width", "tick_color", "show_ticks",
                        "grid", "grid_color", "grid_alpha", "grid_linestyle", "grid_axis",
                        "bar_colors",
                        "title_pad"},
    "Triplets":        {"bg", "title", "ylabel",
                        "font_family", "title_size", "title_bold",
                        "label_size", "label_bold", "tick_size", "tick_bold",
                        "spine_top", "spine_right", "spine_bottom", "spine_left",
                        "spine_color", "spine_width", "tick_color", "show_ticks",
                        "grid", "grid_color", "grid_alpha", "grid_linestyle", "grid_axis",
                        "bar_colors",
                        "title_pad"},
}


def _style(**overrides):
    base = {
        # basic
        "bg":              "white",
        "outer_bg":        "white",
        "title":           "",
        "xlabel":          "",
        "ylabel":          "",
        # fonts
        "font_family":     "sans-serif",
        "title_size":      12,
        "title_bold":      False,
        "label_size":      10,
        "label_bold":      False,
        "tick_size":       9,
        "tick_bold":       False,
        # lines
        "path_color":      "#7A2E8E",
        "path_width":      2.2,
        "linestyle":       "-",          # one of: -, --, :, -.
        "alpha":           0.9,
        "marker":          "none",       # none, o, s, ^, D, x, +
        "marker_size":     5,
        # axes
        "spine_top":       True,
        "spine_right":     True,
        "spine_bottom":    True,
        "spine_left":      True,
        "spine_color":     "#777777",
        "spine_width":     1.0,
        "tick_color":      "#333333",
        "show_ticks":      True,
        "grid":            False,
        "grid_color":      "#BBBBBB",
        "grid_alpha":      0.3,
        "grid_linestyle":  "-",
        "grid_axis":       "both",       # x, y, both
        "arena_color":     "#FF9F4A",
        "arena_width":     1.5,
        # Arm thickness of the synthetic shape preview (EPM +, Y-Maze Y),
        # as a % of the arena half-extent. Only surfaced when the experiment
        # plugin advertises the 'plus_thickness' graph cap.
        "shape_thickness": 30,
        # Default cmap: perceptually uniform, colorblind-safe, publication
        # standard. "jet" survives only as a user opt-in via Customize Graphs.
        "cmap":            "viridis",
        # Custom-palette stops. Only used when cmap == "custom". The
        # `cmap_custom_n` field decides how many of c1..c5 actually count.
        "cmap_custom_n":   5,
        "cmap_c1":         "#000000",
        "cmap_c2":         "#6B0000",
        "cmap_c3":         "#FF6400",
        "cmap_c4":         "#FFC800",
        "cmap_c5":         "#FFFFFF",
        # extras
        "legend_show":      True,
        "legend_loc":       "best",
        "legend_bg":        "#FFFFFF",
        "legend_fontsize":  8,
        "legend_draggable": True,
        # % distance the legend keeps from the axes wall when a named loc
        # (upper right, lower left, etc.) is in use. Ignored for "best"
        # and "custom" locs.
        "legend_inset_pct": 2.0,
        "pin_start_color":  "#23C552",
        "pin_end_color":    "#E5484D",
        "pin_start_marker": "o",
        "pin_end_marker":   "o",
        "pin_size":         160,
        "bar_colors":       ["#4CAF50", "#2196F3", "#9E9E9E", "#FF5722"],
        "hist_edge_color":  "#222222",
        "colorbar_show":    True,
        "colorbar_label":   "",
        "show_center_pct":  False,
        "center_pct_color": "#FFFFFF",
        "center_size_pct":  45,   # % of arena width/height. 100 = whole arena.
        # layout — all values are OFFSETS from the renderer's defaults.
        # 0 = no change; negative pulls closer/smaller, positive pushes
        # farther/bigger. Bases live in the renderer (see _apply_style_text,
        # _make_heatmap_fig, _make_cell_time_heatmap_fig, _apply_legend).
        "title_pad":         0.0,   # pt offset from matplotlib default (~6)
        "colorbar_x":        0.0,   # fig-fraction offset from base 0.06
        "colorbar_y":        0.0,   # fig-fraction offset from base 0.06
        "colorbar_w":        0.0,   # fig-fraction offset from base 0.88
        "colorbar_h":        0.0,   # fig-fraction offset from base 0.04
        "cell_label_dx":     0,     # px offset of cell text (Cell Time)
        "cell_label_dy":     0,     # px offset of cell text (Cell Time)
        "legend_x_offset":   0.0,   # axes-fraction offset for legend
        "legend_y_offset":   0.0,   # axes-fraction offset for legend
    }
    base.update(overrides)
    return base


# Built-in presets. Each is a dict { graph_name → style_dict }.
LIGHT_PRESET = {
    "Trajectory":      _style(title="Trajectory",
                              spine_top=False, spine_right=False,
                              spine_bottom=False, spine_left=False,
                              show_ticks=False),
    "Heatmap":         _style(cmap="viridis", title="Heatmap",
                              spine_top=False, spine_right=False,
                              spine_bottom=False, spine_left=False,
                              show_ticks=False, colorbar_show=True,
                              colorbar_label="seconds"),
    "Cell Time":       _style(cmap="YlOrRd", title="Cell Time",
                              arena_color="#888888", arena_width=1.2,
                              spine_top=False, spine_right=False,
                              spine_bottom=False, spine_left=False,
                              show_ticks=False,
                              colorbar_show=True, colorbar_label="seconds"),
    "Speed":           _style(path_color="#1A6EA8", path_width=1.0,
                              title="Speed over Time",
                              xlabel="Time (s)", ylabel="Speed (cm/s)",
                              grid=True),
    "Speed Histogram": _style(path_color="#1A6EA8",
                              title="Speed distribution",
                              xlabel="Speed", ylabel="Frame count",
                              grid=True, hist_edge_color="#1A4F72"),
    "Habituation":     _style(path_color="#1A6EA8", path_width=1.5,
                              marker="o", marker_size=5,
                              title="Habituation curve",
                              xlabel="Time (min)", ylabel="Distance",
                              grid=True),
    "Zone Time":       _style(title="Time per Zone",
                              ylabel="Time (s)", grid=True),
    "Triplets":        _style(title="Triplet quality",
                              ylabel="Share (%)", grid=True,
                              bar_colors=["#4CAF50", "#E5484D"]),
}

PUBLICATION_PRESET = {
    "Trajectory":      _style(title="Trajectory", path_color="#333333",
                              path_width=1.2, arena_color="#000000",
                              arena_width=1.0,
                              spine_top=False, spine_right=False,
                              spine_bottom=False, spine_left=False,
                              show_ticks=False,
                              title_size=11, title_bold=True),
    "Heatmap":         _style(cmap="Greys", title="Heatmap",
                              arena_color="#000000", arena_width=1.0,
                              spine_top=False, spine_right=False,
                              spine_bottom=False, spine_left=False,
                              show_ticks=False, title_bold=True),
    "Cell Time":       _style(cmap="Greys", title="Cell Time",
                              arena_color="#000000", arena_width=1.0,
                              title_bold=True),
    "Speed":           _style(path_color="#000000", path_width=0.8,
                              title="Speed", xlabel="Time (s)",
                              ylabel="Speed (cm/s)", grid=False,
                              spine_top=False, spine_right=False,
                              title_bold=True, label_bold=True),
    "Speed Histogram": _style(path_color="#444444", hist_edge_color="#000000",
                              title="Speed distribution", xlabel="Speed",
                              ylabel="Frame count", grid=False,
                              spine_top=False, spine_right=False,
                              title_bold=True, label_bold=True),
    "Habituation":     _style(path_color="#000000", path_width=1.0,
                              marker="o", marker_size=4,
                              title="Habituation", xlabel="Time (min)",
                              ylabel="Distance", grid=False,
                              spine_top=False, spine_right=False,
                              title_bold=True, label_bold=True),
    "Zone Time":       _style(title="Time per Zone", ylabel="Time (s)",
                              grid=False, spine_top=False, spine_right=False,
                              bar_colors=["#444444", "#777777", "#999999", "#BBBBBB"],
                              title_bold=True, label_bold=True),
    "Triplets":        _style(title="Triplet quality", ylabel="Share (%)",
                              grid=False, spine_top=False, spine_right=False,
                              bar_colors=["#333333", "#999999"],
                              title_bold=True, label_bold=True),
}

# No built-in presets surfaced in the UI. LIGHT_PRESET is still used
# internally by default_style_for() to seed sensible per-graph defaults.
BUILTIN_PRESETS = {}


# Per-plugin baseline overrides layered on top of the shared Light-preset
# defaults. Keyed by plugin → field → value, applied to every graph in that
# plugin's bucket (fields the graph doesn't expose are simply ignored).
# Y-Maze arms read much thinner than the EPM plus, so its synthetic shape
# (and the fake mouse track confined to it) defaults to a 10% arm thickness.
PLUGIN_GRAPH_DEFAULTS = {
    "y_maze": {"shape_thickness": 10},
    "epm":    {"shape_thickness": 10},
}


def default_style_for(name: str, plugin_key: str = None) -> dict:
    """Return the Light preset entry for a graph (full dict, never None),
    with any per-plugin baseline overrides applied."""
    base = deepcopy(LIGHT_PRESET.get(name, _style(title=name)))
    overrides = PLUGIN_GRAPH_DEFAULTS.get(plugin_key) if plugin_key else None
    if overrides:
        base.update(overrides)
    return base


# Default fallback plugin key used when a caller queries a graph for a
# plugin that hasn't been seeded yet (legacy single-bucket configs land
# here on first read).
_DEFAULT_PLUGIN_KEY = "open_field"


class GraphStyleConfig:
    """Holds per-plugin active styles + named custom presets.

    Each experiment plugin (open_field / nor / epm / y_maze / …) gets its
    own bucket so editing OF Trajectory leaves EPM Trajectory untouched.
    Custom presets are shared across plugins — applying a preset writes
    only into the plugin bucket the dialog is currently focused on.

    Serialization shape (current):
        {
          "plugins": {
            plugin_key: { graph_name: style_dict, ... },
            ...
          },
          "custom_presets": { preset_name: { graph_name: style_dict, ... } }
        }

    Legacy shape ({"active": {...}, "custom_presets": {...}}) is still
    accepted by from_dict — the legacy `active` block is copied into
    every known plugin bucket so an existing user keeps their tweaks
    across all experiments on first load.
    """

    def __init__(self):
        self.plugins = {}        # plugin_key → {graph_name: style}
        self.custom_presets = {}  # preset_name → {graph_name: style}

    # ── bucket helpers ───────────────────────────────────────────────────
    def _ensure_plugin(self, plugin_key: str) -> dict:
        key = plugin_key or _DEFAULT_PLUGIN_KEY
        bucket = self.plugins.get(key)
        if bucket is None:
            bucket = {name: default_style_for(name, key) for name in GRAPH_NAMES}
            self.plugins[key] = bucket
        return bucket

    def known_plugins(self):
        return list(self.plugins.keys())

    # ── style access ─────────────────────────────────────────────────────
    def get_for(self, plugin_key: str, graph_name: str) -> dict:
        bucket = self._ensure_plugin(plugin_key)
        s = bucket.get(graph_name)
        if s is None:
            s = default_style_for(graph_name, plugin_key)
            bucket[graph_name] = s
        return {**default_style_for(graph_name, plugin_key), **s}

    def set_for(self, plugin_key: str, graph_name: str, style: dict) -> None:
        bucket = self._ensure_plugin(plugin_key)
        bucket[graph_name] = {**default_style_for(graph_name, plugin_key), **style}

    # Legacy single-bucket shim — defers to the default plugin so old
    # callers that haven't been migrated still work without crashing.
    @property
    def active(self) -> dict:
        return self._ensure_plugin(_DEFAULT_PLUGIN_KEY)

    @active.setter
    def active(self, value) -> None:
        if isinstance(value, dict):
            self.plugins[_DEFAULT_PLUGIN_KEY] = {
                name: {**default_style_for(name), **value.get(name, {})}
                for name in set(value.keys()) | set(GRAPH_NAMES)
            }

    def get(self, graph_name: str) -> dict:
        return self.get_for(_DEFAULT_PLUGIN_KEY, graph_name)

    def set(self, graph_name: str, style: dict) -> None:
        self.set_for(_DEFAULT_PLUGIN_KEY, graph_name, style)

    # ── presets ──────────────────────────────────────────────────────────
    def all_preset_names(self):
        return list(BUILTIN_PRESETS.keys()) + list(self.custom_presets.keys())

    def preset(self, name: str):
        if name in BUILTIN_PRESETS:
            return deepcopy(BUILTIN_PRESETS[name])
        return deepcopy(self.custom_presets.get(name)) if name in self.custom_presets else None

    def is_builtin(self, name: str) -> bool:
        return name in BUILTIN_PRESETS

    def apply_preset(self, name: str, plugin_key: str = None) -> bool:
        """Apply preset `name` to the plugin's bucket (default plugin if
        not specified). Returns True on success."""
        p = self.preset(name)
        if p is None:
            return False
        pkey = plugin_key or _DEFAULT_PLUGIN_KEY
        bucket = self._ensure_plugin(pkey)
        for gname in GRAPH_NAMES:
            bucket[gname] = {**default_style_for(gname, pkey), **p.get(gname, {})}
        return True

    def save_preset(self, name: str, plugin_key: str = None) -> None:
        """Snapshot the focused plugin's active styles under `name`.
        Built-in names are blocked. Presets are stored as a flat
        {graph: style} dict so they can be re-applied to any plugin."""
        if not name or name in BUILTIN_PRESETS:
            return
        bucket = self._ensure_plugin(plugin_key or _DEFAULT_PLUGIN_KEY)
        self.custom_presets[name] = deepcopy(bucket)

    def delete_preset(self, name: str) -> bool:
        if name in BUILTIN_PRESETS:
            return False
        if name in self.custom_presets:
            del self.custom_presets[name]
            return True
        return False

    # ── (de)serialize ───────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "plugins": {k: deepcopy(v) for k, v in self.plugins.items()},
            "custom_presets": deepcopy(self.custom_presets),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GraphStyleConfig":
        cfg = cls()
        if not isinstance(d, dict):
            return cfg

        def _clean_bucket(raw, pkey=None):
            out = {}
            if not isinstance(raw, dict):
                return out
            for gname in GRAPH_NAMES:
                s = raw.get(gname)
                if isinstance(s, dict):
                    out[gname] = {**default_style_for(gname, pkey), **s}
            return out

        plugins_blob = d.get("plugins")
        if isinstance(plugins_blob, dict):
            for pkey, pdata in plugins_blob.items():
                cleaned = _clean_bucket(pdata, pkey)
                if cleaned:
                    cfg.plugins[pkey] = cleaned

        # Legacy shape: a single top-level "active" → migrate by copying
        # into every plugin bucket the user has so existing tweaks aren't
        # lost the first time the new shape is loaded.
        legacy_active = d.get("active")
        if isinstance(legacy_active, dict) and not plugins_blob:
            for pkey in ("open_field", "nor", "epm", "y_maze"):
                cfg.plugins[pkey] = _clean_bucket(legacy_active, pkey)

        presets = d.get("custom_presets")
        if isinstance(presets, dict):
            for pname, pdata in presets.items():
                if not isinstance(pdata, dict) or pname in BUILTIN_PRESETS:
                    continue
                cfg.custom_presets[pname] = _clean_bucket(pdata)
        return cfg
