"""Customize Graphs dialog — per-graph style editor with live preview,
preset save/load, tabbed property panel (Basic / Fonts / Lines / Axes /
Extras), and a color picker matching the project's existing
swatches+More→QColorDialog pattern."""
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QFormLayout, QLabel, QPushButton,
    QListWidget, QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox, QLineEdit,
    QColorDialog, QInputDialog, QMessageBox, QGroupBox, QWidget, QSizePolicy,
    QScrollArea, QTabBar,
)

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

from gui.graph_style import (
    GRAPH_NAMES, GRAPH_FIELDS, BUILTIN_PRESETS, GraphStyleConfig,
    ACCENT_COLORS, default_style_for, resolve_style, resolve_token, resolve_field, speed_axis,
    time_axis, distance_axis, axis_title_style,
)

# ── choice lists ────────────────────────────────────────────────────────
CMAP_CHOICES = [
    "jet", "hot", "inferno", "magma", "viridis", "plasma", "cividis",
    "YlOrRd", "Reds", "Blues", "Greens", "Greys",
    "custom",
]
CUSTOM_CMAP_STOPS = ("cmap_c1", "cmap_c2", "cmap_c3", "cmap_c4", "cmap_c5")


def maze_shape_polys(plugin_key, arena_half, thickness_pct=30.0):
    """Canonical idealized maze outline for EPM (+) and Y-Maze (Y).

    Returns a list of vertex lists (Nx2), centered on (0,0) in math (y-up)
    coords. `thickness_pct` sets the arm half-width as a % of `arena_half`.
    Shared by the style-dialog preview and the real output renderer so both
    draw the exact same shape. Returns [] for other experiments."""
    import math
    L = float(arena_half)
    if plugin_key == "epm":
        # Plus: two crossed bars, 12-vertex outline.
        w = L * float(thickness_pct) / 100.0
        return [[
            (-w, -L), (w, -L), (w, -w), (L, -w), (L, w), (w, w),
            (w, L), (-w, L), (-w, w), (-L, w), (-L, -w), (-w, -w),
        ]]
    if plugin_key == "y_maze":
        # Three arms 120° apart meeting at a central triangular hub. Each arm
        # base is set back along its axis by `inset` so the arms touch only at
        # the triangle's corners instead of overlapping through the middle.
        w = L * float(thickness_pct) / 100.0
        inset = w / math.sqrt(3.0)
        tip = L * 1.02
        polys = []
        tri = []
        for ang in (90.0, 210.0, 330.0):
            a = math.radians(ang)
            dx, dy = math.cos(a), math.sin(a)
            px, py = -dy, dx
            polys.append([
                (dx * inset + px * w, dy * inset + py * w),
                (dx * tip + px * w,   dy * tip + py * w),
                (dx * tip - px * w,   dy * tip - py * w),
                (dx * inset - px * w, dy * inset - py * w),
            ])
            tri.append((dx * inset + px * w, dy * inset + py * w))
        polys.append(tri)
        return polys
    return []


def maze_canonical_dirs(plugin_key):
    """Canonical (idealized) arm directions used by maze_shape_polys, in
    math (y-up) unit vectors. EPM order is N, S, E, W; Y-Maze is the three
    120° arms (up, lower-left, lower-right)."""
    import math
    if plugin_key == "epm":
        return [(0.0, 1.0), (0.0, -1.0), (1.0, 0.0), (-1.0, 0.0)]
    if plugin_key == "y_maze":
        return [(math.cos(math.radians(a)), math.sin(math.radians(a)))
                for a in (90.0, 210.0, 330.0)]
    return []


# Set by the chart editor's "Export preview" toggle: draw with the palette
# exported files use ("light") instead of the app theme. None = app theme.
_FIG_MODE_OVERRIDE = None


def set_fig_mode_override(mode):
    global _FIG_MODE_OVERRIDE
    _FIG_MODE_OVERRIDE = mode


def _fig_mode():
    if _FIG_MODE_OVERRIDE:
        return _FIG_MODE_OVERRIDE
    from gui import theme
    return theme.mode()


def resolve_cmap(st):
    """Return a matplotlib Colormap for the given style dict. Honors the
    "custom" cmap choice by interpolating the first `cmap_custom_n`
    stops from cmap_c1..c5."""
    import matplotlib.pyplot as plt
    from matplotlib import colors as mcolors
    name = st.get("cmap", "jet")
    if name == "custom":
        n = max(2, min(len(CUSTOM_CMAP_STOPS),
                       int(st.get("cmap_custom_n", len(CUSTOM_CMAP_STOPS)))))
        stops = [st.get(k, "#FFFFFF") for k in CUSTOM_CMAP_STOPS[:n]]
        try:
            return mcolors.LinearSegmentedColormap.from_list(
                "user_cmap", stops, N=256
            )
        except Exception:
            return plt.get_cmap("jet")
    try:
        return plt.get_cmap(name)
    except Exception:
        return plt.get_cmap("jet")
FONT_FAMILIES = ["sans-serif", "serif", "monospace"]
LINESTYLE_CHOICES = [
    ("solid", "-"), ("dashed", "--"), ("dotted", ":"), ("dashdot", "-."),
]
MARKER_CHOICES = [
    ("none", "none"), ("circle", "o"), ("square", "s"),
    ("triangle", "^"), ("diamond", "D"), ("x", "x"), ("plus", "+"),
]
# Start/end pin markers — filled shapes only (no "none" / line-only).
PIN_MARKER_CHOICES = [
    ("circle", "o"), ("square", "s"), ("diamond", "D"),
    ("triangle up", "^"), ("triangle down", "v"),
    ("triangle left", "<"), ("triangle right", ">"),
    ("pentagon", "p"), ("hexagon", "h"), ("star", "*"),
    ("plus filled", "P"), ("x filled", "X"),
]
LEGEND_LOC_CHOICES = [
    "best", "upper right", "upper left", "lower left", "lower right",
    "center left", "center right", "upper center", "lower center", "center",
    "custom",
]
# For each named loc, give the natural anchor (bx, by) and the sign each
# axis should move when an "inset %" is applied. Inset always pulls the
# anchor INSIDE the axes (e.g. upper-right anchor goes toward 0.95, 0.95
# at inset 5%). "center" stays at (0.5, 0.5) regardless.
LEGEND_INSET_TABLE = {
    "upper right":  (1.0, 1.0, -1, -1),
    "upper left":   (0.0, 1.0,  1, -1),
    "lower left":   (0.0, 0.0,  1,  1),
    "lower right":  (1.0, 0.0, -1,  1),
    "center left":  (0.0, 0.5,  1,  0),
    "center right": (1.0, 0.5, -1,  0),
    "upper center": (0.5, 1.0,  0, -1),
    "lower center": (0.5, 0.0,  0,  1),
    "center":       (0.5, 0.5,  0,  0),
}


def apply_legend_labels(leg, st):
    """Show the user's renamed legend entries (style 'legend_labels',
    {default text: shown text}). The default texts are kept on the legend
    as `_orig_labels` so the chart editor knows which entry is which."""
    if leg is None:
        return leg
    texts = leg.get_texts()
    leg._orig_labels = [t.get_text() for t in texts]
    mapping = st.get("legend_labels") or {}
    if isinstance(mapping, dict):
        for t, orig in zip(texts, leg._orig_labels):
            new = mapping.get(orig)
            if isinstance(new, str) and new != orig:
                t.set_text(new)
    return leg


def _legend_kwargs_for(ax, st):
    """Build ax.legend(**kwargs) options from a style dict. Three modes:
      - "best": matplotlib auto-placement; no bbox.
      - "custom": legend_x/y_offset are absolute axes-fraction coords for
        the legend's lower-left corner (this is what drag writes).
      - named loc: anchor pulled `legend_inset_pct` percent inside the
        named edge so the legend never touches the axes wall.
    """
    loc_choice = st.get("legend_loc", "best")
    kwargs = dict(
        fontsize=float(st.get("legend_fontsize", 8)),
        # Legend resize handles (chart editor) scale the markers with the text.
        markerscale=float(st.get("legend_markerscale", 1.0) or 1.0),
        facecolor=st.get("legend_bg", "#FFFFFF"),
        labelcolor=st.get("legend_text_color") or st.get("text_color", "black"),
        edgecolor=st.get("grid_color", "#CCCCCC"),
        framealpha=0.95,
        fancybox=False,
    )
    if loc_choice == "custom":
        dx = float(st.get("legend_x_offset", 0.0))
        dy = float(st.get("legend_y_offset", 0.0))
        # The legend may sit anywhere on the figure, also outside the plot
        # area; only a wildly stale anchor is pulled back into view.
        dx = max(-1.0, min(2.0, dx))
        dy = max(-1.0, min(2.0, dy))
        kwargs["loc"] = "lower left"
        kwargs["bbox_to_anchor"] = (dx, dy)
        kwargs["bbox_transform"] = ax.transAxes
    elif loc_choice == "best":
        kwargs["loc"] = "best"
    elif loc_choice in LEGEND_INSET_TABLE:
        bx, by, sx, sy = LEGEND_INSET_TABLE[loc_choice]
        inset = max(0.0, float(st.get("legend_inset_pct", 0.0))) / 100.0
        kwargs["loc"] = loc_choice
        kwargs["bbox_to_anchor"] = (bx + sx * inset, by + sy * inset)
        kwargs["bbox_transform"] = ax.transAxes
    else:
        kwargs["loc"] = "best"
    return kwargs
GRID_AXIS_CHOICES = ["both", "x", "y"]

SWATCHES = [
    "#FFFFFF", "#16181B", "#1B2436", "#A9B4C6", "#E4D3AE", "#5DBB85",
    "#E8C547", "#D36BA6", "#E0695E", "#7FA6D9", "#E8A87C", "#8FC79A",
]


class _ColorButton(QPushButton):
    """Swatch + label; opens the project's non-native QColorDialog with
    live currentColorChanged previewing."""

    def __init__(self, initial_hex, on_change, parent=None):
        super().__init__(parent)
        self._on_change = on_change
        self._hex = initial_hex or "#000000"
        self.setFixedSize(60, 22)
        self._refresh()
        self.clicked.connect(self._pick)

    def set_hex(self, hex_str):
        if not hex_str:
            return
        self._hex = hex_str
        self._refresh()

    def hex(self):
        return self._hex

    def _refresh(self):
        self.setText(self._hex)
        c = QColor(self._hex)
        lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
        txt = "#000" if lum > 140 else "#FFF"
        # Scoped selector — without `QPushButton`, Qt cascades the
        # background into child widgets (e.g. the QColorDialog this
        # button parents), tinting the whole color picker.
        self.setStyleSheet(
            "QPushButton { "
            f"background:{self._hex}; color:{txt}; "
            "border:1px solid rgba(128,128,128,0.45); padding:0 4px; font-size:11px;"
            " }"
        )

    def _pick(self):
        initial = QColor(self._hex)
        # Parent the picker to the top-level window, not to self. A child
        # QColorDialog inherits the swatch button's stylesheet, which
        # turned the whole picker the button's color.
        owner = self.window() or self
        dlg = QColorDialog(initial, owner)
        dlg.setOption(QColorDialog.DontUseNativeDialog, True)

        def on_live(c):
            if not c.isValid():
                return
            self.set_hex(c.name())
            try:
                self._on_change(c.name())
            except Exception:
                pass

        dlg.currentColorChanged.connect(on_live)
        accepted = dlg.exec_() == QColorDialog.Accepted
        if not accepted:
            self.set_hex(initial.name())
            try:
                self._on_change(initial.name())
            except Exception:
                pass


class GraphStyleDialog(QDialog):
    """Edit per-graph styles with maximum freedom over fonts, lines,
    axes, ticks, grid, legend, and graph-specific extras."""

    def __init__(self, style_config, caps_provider, rerender_cb=None,
                 persist_cb=None, plugins=None, current_plugin_key=None,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Customize Graphs")
        self.resize(1180, 720)
        self.setMinimumSize(960, 600)
        self._cfg = style_config
        # Per-plugin descriptors: list of dicts with keys
        # {key, label, graph_names, caps_provider}. When None, fall back
        # to a single synthetic plugin built from the legacy caps_provider
        # so the dialog still works for callers that haven't migrated.
        if plugins:
            self._plugins = list(plugins)
        else:
            self._plugins = [{
                "key": "open_field",
                "label": "Open Field",
                "graph_names": list(GRAPH_NAMES),
                "caps_provider": caps_provider,
            }]
        # Map for fast lookup by plugin key.
        self._plugins_by_key = {p["key"]: p for p in self._plugins}
        self._current_plugin_key = (current_plugin_key
                                    if current_plugin_key in self._plugins_by_key
                                    else self._plugins[0]["key"])
        # Active plugin's caps + graph list (rebound on plugin switch).
        self._caps_provider = self._plugins_by_key[self._current_plugin_key]["caps_provider"]
        self._plugin_graph_names = list(
            self._plugins_by_key[self._current_plugin_key]["graph_names"]
        )
        # Parent's plugin key (if known) — gates the "Use real session"
        # preview to only the experiment that owns the live tracked data.
        self._parent_plugin_key = (parent._plugin_key()
                                   if hasattr(parent, "_plugin_key") else None)
        self._rerender = rerender_cb
        # Called after Save As / Delete so presets persist immediately,
        # independent of the OK/Cancel decision on style edits.
        self._persist = persist_cb
        self._backup = style_config.to_dict()
        self._live = False
        self._current = (self._plugin_graph_names[0]
                         if self._plugin_graph_names else GRAPH_NAMES[0])
        self._editors = {}
        # Mouse-drag wiring for layout artists (legend / title / colorbar
        # axes / cell labels). Re-attached each preview render.
        self._drag_cids = []
        self._drag_artists = {}
        self._drag_state = {"kind": None}
        # Custom-palette row refs (rebuilt per _select).
        self._palette_label = None
        self._palette_container = None
        # Parent ExperimentTab (or None). Used for "real session" preview
        # source + polygon-aware sample arena.
        self._parent_tab = parent

        self._sample_seed = 42
        self._using_real = False
        self._synth_sample = self._build_sample(self._sample_seed)
        self._sample = self._synth_sample

        # Debounce timers — rapid spinbox/color changes coalesce into one
        # preview redraw + one parent rerender per ~60 / 180 ms.
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(60)
        self._preview_timer.timeout.connect(self._refresh_preview)

        self._rerender_timer = QTimer(self)
        self._rerender_timer.setSingleShot(True)
        self._rerender_timer.setInterval(180)
        self._rerender_timer.timeout.connect(self._fire_rerender)

        self._build_ui()
        self._select(self._current)

    # ── UI build ─────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # Plugin tab bar — one tab per experiment plugin. Hidden when
        # only a single plugin was supplied (legacy callers).
        self.tabs_plugin = QTabBar()
        self.tabs_plugin.setExpanding(False)
        self.tabs_plugin.setDocumentMode(True)
        for p in self._plugins:
            self.tabs_plugin.addTab(p["label"])
        # Seed selection to match the requested plugin without firing the
        # change signal during construction.
        try:
            sel = next(i for i, p in enumerate(self._plugins)
                       if p["key"] == self._current_plugin_key)
        except StopIteration:
            sel = 0
        self.tabs_plugin.blockSignals(True)
        self.tabs_plugin.setCurrentIndex(sel)
        self.tabs_plugin.blockSignals(False)
        self.tabs_plugin.currentChanged.connect(self._on_plugin_tab_changed)
        if len(self._plugins) <= 1:
            self.tabs_plugin.setVisible(False)
        root.addWidget(self.tabs_plugin)

        # Top toolbar.
        top = QHBoxLayout()
        top.addWidget(QLabel("Preset:"))
        self.cmb_preset = QComboBox()
        self.cmb_preset.setMinimumWidth(160)
        self._reload_presets()
        self.cmb_preset.currentTextChanged.connect(self._on_preset_pick)
        top.addWidget(self.cmb_preset)

        btn_save = QPushButton("Save As…")
        btn_save.clicked.connect(self._save_preset_dialog)
        top.addWidget(btn_save)

        btn_del = QPushButton("Delete")
        btn_del.clicked.connect(self._delete_preset)
        top.addWidget(btn_del)

        top.addSpacing(12)
        self.btn_reset_graph = QPushButton("Reset graph")
        self.btn_reset_graph.setToolTip(
            "Restore the Light-preset defaults for the currently selected graph only."
        )
        self.btn_reset_graph.clicked.connect(self._reset_current_graph)
        top.addWidget(self.btn_reset_graph)

        top.addStretch()
        # Export current graph as SVG / PDF / PNG. Delegates to the parent
        # ExperimentTab's file dialog so the same code path serves the
        # right-click menu on the graph image.
        self.btn_export_graph = QPushButton("Export graph…")
        self.btn_export_graph.setToolTip(
            "Save the currently-selected graph as SVG / PDF / PNG."
        )
        self.btn_export_graph.clicked.connect(self._on_export_graph_clicked)
        top.addWidget(self.btn_export_graph)
        self.chk_live = QCheckBox("Live preview")
        self.chk_live.toggled.connect(self._on_live_toggle)
        top.addWidget(self.chk_live)
        self.btn_apply = QPushButton("Apply")
        self.btn_apply.clicked.connect(self._apply)
        top.addWidget(self.btn_apply)
        root.addLayout(top)

        # Middle: list | tabbed props | preview.
        mid = QHBoxLayout()
        mid.setSpacing(8)
        self.list_graphs = QListWidget()
        self.list_graphs.setFixedWidth(150)
        for name in self._plugin_graph_names:
            self.list_graphs.addItem(name)
        self.list_graphs.currentTextChanged.connect(self._select)
        mid.addWidget(self.list_graphs)

        # Flat accordion (collapsible groupboxes) instead of nested tabs.
        # Each section's title bar is a checkable strip — uncheck to fold.
        self.props_scroll = QScrollArea()
        self.props_scroll.setWidgetResizable(True)
        self.props_scroll.setFrameShape(QScrollArea.NoFrame)
        self.props_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        props_inner = QWidget()
        self.props_layout = QVBoxLayout(props_inner)
        self.props_layout.setSpacing(8)
        self.props_layout.setContentsMargins(4, 4, 4, 4)
        self._section_groups = {}
        self._section_forms = {}
        self._section_inners = {}
        for sect_name in ("Style", "Text", "Frame", "Overlays", "Layout"):
            gb = QGroupBox(sect_name)
            gb.setCheckable(True)
            gb.setChecked(True)
            gb.setStyleSheet(
                "QGroupBox { font-weight: bold; margin-top: 8px; "
                "border: 1px solid rgba(128,128,128,0.45); border-radius: 4px; padding: 6px; }"
                "QGroupBox::title { subcontrol-origin: margin; left: 8px; "
                "padding: 0 4px; }"
            )
            inner = QWidget()
            form = QFormLayout(inner)
            form.setSpacing(4)
            form.setContentsMargins(8, 4, 8, 4)
            form.setLabelAlignment(Qt.AlignRight)
            gb_layout = QVBoxLayout(gb)
            gb_layout.setContentsMargins(8, 14, 8, 8)
            gb_layout.addWidget(inner)
            gb.toggled.connect(inner.setVisible)
            self.props_layout.addWidget(gb)
            self._section_groups[sect_name] = gb
            self._section_forms[sect_name] = form
            self._section_inners[sect_name] = inner
        self.props_layout.addStretch()
        self.props_scroll.setWidget(props_inner)
        mid.addWidget(self.props_scroll, 1)

        # Preview.
        self.preview_box = QGroupBox("Preview")
        self.preview_box.setMinimumWidth(380)
        prev_lay = QVBoxLayout(self.preview_box)
        prev_lay.setContentsMargins(6, 6, 6, 6)

        sample_row = QHBoxLayout()
        self.chk_real = QCheckBox("Use real session")
        self.chk_real.setToolTip(
            "Preview against the active tracked session instead of synthetic.\n"
            "Disabled if no tracking has run yet."
        )
        self.chk_real.toggled.connect(self._on_real_toggle)
        # Probe parent for tracked data; disable if not available.
        has_real = self._maybe_real_sample() is not None
        self.chk_real.setEnabled(has_real)
        if not has_real:
            self.chk_real.setToolTip(self.chk_real.toolTip() + "\n(No tracked data found.)")
        sample_row.addWidget(self.chk_real)
        sample_row.addStretch()
        self.btn_regen = QPushButton("Regenerate sample")
        self.btn_regen.setFixedHeight(22)
        self.btn_regen.setToolTip("Roll a new mouse-like synthetic session.")
        self.btn_regen.clicked.connect(self._regen_sample)
        sample_row.addWidget(self.btn_regen)
        prev_lay.addLayout(sample_row)

        self._fig = plt.figure(figsize=(4.8, 4.0))
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setMinimumHeight(320)
        prev_lay.addWidget(self._canvas, 1)
        mid.addWidget(self.preview_box, 1)

        root.addLayout(mid, 1)

        # Bottom.
        bot = QHBoxLayout()
        bot.addStretch()
        ok = QPushButton("OK")
        ok.clicked.connect(self._accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        bot.addWidget(ok)
        bot.addWidget(cancel)
        root.addLayout(bot)

    # ── preset dropdown ──────────────────────────────────────────────────
    def _reload_presets(self):
        cur = self.cmb_preset.currentText() if self.cmb_preset.count() else ""
        self.cmb_preset.blockSignals(True)
        self.cmb_preset.clear()
        self.cmb_preset.addItem("(custom)")
        for name in self._cfg.all_preset_names():
            self.cmb_preset.addItem(name)
        if cur:
            idx = self.cmb_preset.findText(cur)
            if idx >= 0:
                self.cmb_preset.setCurrentIndex(idx)
        self.cmb_preset.blockSignals(False)

    def _on_plugin_tab_changed(self, index):
        """Switch the editor to the plugin at `index`. Rebuilds the graph
        list with the new plugin's `graph_names`, refreshes the caps
        provider, and reselects the first available graph. Style edits
        flow into the new plugin's bucket from this point on."""
        if index < 0 or index >= len(self._plugins):
            return
        plugin = self._plugins[index]
        self._current_plugin_key = plugin["key"]
        self._caps_provider = plugin["caps_provider"]
        self._plugin_graph_names = list(plugin["graph_names"])
        # Rebuild the synthetic sample so its arena shape matches the newly
        # selected experiment (+ / Y / square+objects). _build_sample reads
        # self._current_plugin_key, which we just updated.
        self._synth_sample = self._build_sample(self._sample_seed)
        # Reset graph list to the new plugin's names.
        self.list_graphs.blockSignals(True)
        self.list_graphs.clear()
        for gname in self._plugin_graph_names:
            self.list_graphs.addItem(gname)
        if self._plugin_graph_names:
            self.list_graphs.setCurrentRow(0)
            self._current = self._plugin_graph_names[0]
        self.list_graphs.blockSignals(False)
        # Real-session preview is only valid for the parent tab's plugin.
        if hasattr(self, "chk_real"):
            ok = (self._parent_plugin_key == self._current_plugin_key
                  and self._maybe_real_sample() is not None)
            self.chk_real.setEnabled(ok)
            if not ok:
                if self.chk_real.isChecked():
                    self.chk_real.setChecked(False)
                self._using_real = False
                self._sample = self._synth_sample
                if hasattr(self, "btn_regen"):
                    self.btn_regen.setEnabled(True)
        # Drop any (custom) preset hint when switching plugins.
        if hasattr(self, "cmb_preset"):
            self.cmb_preset.blockSignals(True)
            self.cmb_preset.setCurrentIndex(0)
            self.cmb_preset.blockSignals(False)
        if self._plugin_graph_names:
            self._select(self._current)

    def _on_preset_pick(self, name):
        if not name or name == "(custom)":
            return
        if self._cfg.apply_preset(name, plugin_key=self._current_plugin_key):
            self._select(self._current)
            if self._live and self._rerender:
                try:
                    self._rerender(None)
                except Exception:
                    pass

    def _save_preset_dialog(self):
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        name = (name or "").strip()
        if not ok or not name:
            return
        if name in BUILTIN_PRESETS:
            QMessageBox.warning(self, "Reserved",
                                "Built-in preset names cannot be overwritten.")
            return
        self._cfg.save_preset(name, plugin_key=self._current_plugin_key)
        self._reload_presets()
        idx = self.cmb_preset.findText(name)
        if idx >= 0:
            self.cmb_preset.setCurrentIndex(idx)
        self._persist_now()

    def _delete_preset(self):
        name = self.cmb_preset.currentText()
        if not name or name == "(custom)" or self._cfg.is_builtin(name):
            QMessageBox.information(self, "Delete preset",
                                    "Pick a custom preset to delete.")
            return
        if QMessageBox.question(self, "Delete preset",
                                f"Delete preset '{name}'?") != QMessageBox.Yes:
            return
        self._cfg.delete_preset(name)
        self._reload_presets()
        self._persist_now()

    def _persist_now(self):
        """Flush current preset list (and active styles) to disk so a later
        Cancel can't roll them away."""
        if self._persist:
            try:
                self._persist()
            except Exception:
                pass

    def _on_export_graph_clicked(self):
        """Open the parent tab's Save dialog for the currently-selected
        graph. Vector formats (SVG/PDF) are the publication path; PNG
        is offered too for parity with the live preview."""
        parent = self._parent_tab
        if parent is None or not hasattr(parent, "_export_current_graph_dialog"):
            return
        # Sync the parent's combo to whichever graph the user is
        # editing here, then trigger its export flow.
        try:
            combo = getattr(parent, "_combo_graph", None)
            if combo is not None and self._current:
                idx = combo.findText(self._current)
                if idx >= 0 and combo.currentIndex() != idx:
                    combo.setCurrentIndex(idx)
        except Exception:
            pass
        parent._export_current_graph_dialog()

    def _reset_current_graph(self):
        """Restore the Light-preset defaults for the active graph only.
        Other graphs (and other plugins' graphs) keep their current edits."""
        self._cfg.set_for(self._current_plugin_key, self._current,
                          default_style_for(self._current, self._current_plugin_key))
        self.cmb_preset.blockSignals(True)
        self.cmb_preset.setCurrentIndex(0)
        self.cmb_preset.blockSignals(False)
        self._select(self._current)
        if self._live and self._rerender:
            self._rerender_timer.start()

    # ── graph selection ──────────────────────────────────────────────────
    def _allowed_fields(self, name):
        base = set(GRAPH_FIELDS.get(name, set()))
        try:
            extra_caps = self._caps_provider(name) if self._caps_provider else None
        except Exception:
            extra_caps = None
        # extra_caps used to allow `grid` / `center_pct` per experiment
        # override; we honor by adding the matching families back.
        if extra_caps and "grid" in extra_caps:
            base.update({"grid", "grid_color", "grid_alpha",
                         "grid_linestyle", "grid_axis"})
        if extra_caps and "center_pct" in extra_caps:
            base.update({"show_center_pct", "center_pct_color",
                         "center_size_pct"})
        if extra_caps and "plus_thickness" in extra_caps:
            base.add("shape_thickness")
        return base

    def _select(self, name):
        if not name:
            return
        self._current = name
        items = self.list_graphs.findItems(name, Qt.MatchExactly)
        if items:
            self.list_graphs.blockSignals(True)
            self.list_graphs.setCurrentItem(items[0])
            self.list_graphs.blockSignals(False)

        allowed = self._allowed_fields(name)
        style = self._cfg.get_for(self._current_plugin_key, name)
        # Snapshot what differs from the Light-preset baseline so labels
        # get a leading dot to flag user-modified fields.
        baseline = default_style_for(name, self._current_plugin_key)
        self._diff_fields = {
            f for f in allowed
            if baseline.get(f) != style.get(f)
        }
        # Clear all section forms.
        for form in self._section_forms.values():
            while form.rowCount():
                form.removeRow(0)
        self._editors.clear()
        # Drop refs to widgets that just got torn down with the form.
        self._palette_label = None
        self._palette_container = None
        # Track row-label widgets so _commit can update their dot live.
        self._label_widgets = {}

        # Build each section.
        self._build_style(allowed, style)
        self._build_text(allowed, style)
        self._build_frame(allowed, style)
        self._build_overlays(allowed, style)
        self._build_layout(allowed, style)

        # Hide sections with no rows so users never stare at an empty group.
        for sect_name, form in self._section_forms.items():
            self._section_groups[sect_name].setVisible(form.rowCount() > 0)

        self._refresh_preview()

    # ── section builders ─────────────────────────────────────────────────
    # Field-to-section map (the part the user actually thinks about):
    #   Style    = overall plot appearance (bg, cmap, line/marker, bar, hist)
    #   Text     = anything with characters on screen (title, labels, fonts)
    #   Frame    = box around the plot (spines, ticks, grid, arena outline)
    #   Overlays = annotations on top (legend, colorbar, pins, zone overlay)

    def _build_style(self, allowed, style):
        form = self._section_forms["Style"]
        if "bg" in allowed:
            # When 'outer_bg' is also allowed, 'bg' fills the arena interior
            # only; otherwise it paints the whole figure (legacy behavior).
            label = "Area background" if "outer_bg" in allowed else "Background"
            self._add_color(form, "bg", label, style)
        if "outer_bg" in allowed:
            self._add_color(form, "outer_bg", "Outer background", style)
        if "cmap" in allowed:
            self._add_combo(form, "cmap", "Colormap", style, CMAP_CHOICES)
            if any(k in allowed for k in CUSTOM_CMAP_STOPS):
                self._add_palette_row(form, style, allowed)
        if "path_color" in allowed:
            self._add_color(form, "path_color", "Line / bar color", style)
        if "path_width" in allowed:
            self._add_spin(form, "path_width", "Line width", style, 0.1, 12.0, 0.1)
        if "linestyle" in allowed:
            self._add_pair_combo(form, "linestyle", "Line style", style, LINESTYLE_CHOICES)
        if "alpha" in allowed:
            self._add_spin(form, "alpha", "Opacity", style, 0.05, 1.0, 0.05)
        if "marker" in allowed:
            self._add_pair_combo(form, "marker", "Marker", style, MARKER_CHOICES)
        if "marker_size" in allowed:
            self._add_int_spin(form, "marker_size", "Marker size", style, 1, 30)
        if "bar_colors" in allowed:
            self._add_bar_colors(form, style)
        if "hist_edge_color" in allowed:
            self._add_color(form, "hist_edge_color", "Histogram edge", style)

    def _build_text(self, allowed, style):
        form = self._section_forms["Text"]
        if "font_family" in allowed:
            self._add_combo(form, "font_family", "Font family", style, FONT_FAMILIES)
        if "title" in allowed:
            self._add_text(form, "title", "Title", style)
        if "title_size" in allowed:
            self._add_int_spin(form, "title_size", "Title size", style, 6, 36)
        if "title_bold" in allowed:
            self._add_check(form, "title_bold", "Title bold", style)
        if "xlabel" in allowed:
            self._add_text(form, "xlabel", "X axis label", style)
        if "ylabel" in allowed:
            self._add_text(form, "ylabel", "Y axis label", style)
        if "label_size" in allowed:
            self._add_int_spin(form, "label_size", "Axis label size", style, 6, 32)
        if "label_bold" in allowed:
            self._add_check(form, "label_bold", "Axis label bold", style)
        if "tick_size" in allowed:
            self._add_int_spin(form, "tick_size", "Tick label size", style, 5, 24)
        if "tick_bold" in allowed:
            self._add_check(form, "tick_bold", "Tick label bold", style)
        if "colorbar_label" in allowed:
            self._add_text(form, "colorbar_label", "Colorbar label", style)

    def _build_frame(self, allowed, style):
        form = self._section_forms["Frame"]
        # Spines collapsed into a single row — 4 checkboxes side by side
        # instead of 4 separate form rows.
        spine_keys = [("spine_top", "Top"), ("spine_right", "Right"),
                      ("spine_bottom", "Bottom"), ("spine_left", "Left")]
        spine_keys = [(k, lbl) for k, lbl in spine_keys if k in allowed]
        if spine_keys:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            for key, label_txt in spine_keys:
                cb = QCheckBox(label_txt)
                cb.setChecked(bool(style.get(key, True)))
                cb.toggled.connect(
                    lambda v, f=key: self._commit(f, bool(v))
                )
                h.addWidget(cb)
                self._editors[key] = cb
            h.addStretch()
            form.addRow(self._row_label_widget("spine_top", "Spines"), row)
        if "spine_color" in allowed:
            self._add_color(form, "spine_color", "Spine color", style)
        if "spine_width" in allowed:
            self._add_spin(form, "spine_width", "Spine width", style, 0.1, 6.0, 0.1)
        if "tick_color" in allowed:
            self._add_color(form, "tick_color", "Tick color", style)
        if "show_ticks" in allowed:
            self._add_check(form, "show_ticks", "Show ticks", style)
        if "grid" in allowed:
            self._add_check(form, "grid", "Grid", style)
        if "grid_color" in allowed:
            self._add_color(form, "grid_color", "Grid color", style)
        if "grid_alpha" in allowed:
            self._add_spin(form, "grid_alpha", "Grid opacity", style, 0.05, 1.0, 0.05)
        if "grid_linestyle" in allowed:
            self._add_pair_combo(form, "grid_linestyle", "Grid style", style, LINESTYLE_CHOICES)
        if "grid_axis" in allowed:
            self._add_combo(form, "grid_axis", "Grid axis", style, GRID_AXIS_CHOICES)
        if "arena_color" in allowed:
            self._add_color(form, "arena_color", "Arena color", style)
        if "arena_width" in allowed:
            self._add_spin(form, "arena_width", "Arena width", style, 0.1, 8.0, 0.1)
        if "shape_thickness" in allowed:
            lbl = ("Arm thickness (%)" if self._current_plugin_key == "y_maze"
                   else "Plus thickness (%)")
            self._add_int_spin(form, "shape_thickness", lbl, style, 8, 48)

    def _build_overlays(self, allowed, style):
        form = self._section_forms["Overlays"]
        if "legend_show" in allowed:
            self._add_check(form, "legend_show", "Show legend", style)
        if "legend_loc" in allowed:
            self._add_combo(form, "legend_loc", "Legend position", style, LEGEND_LOC_CHOICES)
        if "legend_bg" in allowed:
            self._add_color(form, "legend_bg", "Legend bg", style)
        if "legend_fontsize" in allowed:
            self._add_int_spin(form, "legend_fontsize", "Legend font", style, 5, 24)
        if "legend_draggable" in allowed:
            self._add_check(form, "legend_draggable", "Draggable", style)
        if "legend_inset_pct" in allowed:
            self._add_spin(form, "legend_inset_pct",
                           "Inset from wall (%)", style, 0.0, 25.0, 0.5,
                           decimals=1)
        if "colorbar_show" in allowed:
            self._add_check(form, "colorbar_show", "Show colorbar", style)
        if "show_center_pct" in allowed:
            self._add_check(form, "show_center_pct", "Show center", style)
        if "center_pct_color" in allowed:
            self._add_color(form, "center_pct_color", "Center color", style)
        if "center_size_pct" in allowed:
            self._add_int_spin(form, "center_size_pct",
                               "Center size (% of arena)", style, 5, 100)
        if "pin_start_color" in allowed:
            self._add_color(form, "pin_start_color", "Start pin color", style)
        if "pin_start_marker" in allowed:
            self._add_pair_combo(form, "pin_start_marker", "Start pin shape",
                                 style, PIN_MARKER_CHOICES)
        if "pin_end_color" in allowed:
            self._add_color(form, "pin_end_color", "End pin color", style)
        if "pin_end_marker" in allowed:
            self._add_pair_combo(form, "pin_end_marker", "End pin shape",
                                 style, PIN_MARKER_CHOICES)
        if "pin_size" in allowed:
            self._add_int_spin(form, "pin_size", "Pin size", style, 20, 400)

    def _build_layout(self, allowed, style):
        form = self._section_forms["Layout"]
        # All values are OFFSETS from renderer defaults — 0 = no change,
        # ± nudges in either direction.
        if "title_pad" in allowed:
            self._add_spin(form, "title_pad", "Title Δ (pt)",
                           style, -20.0, 60.0, 0.5)
        if "colorbar_x" in allowed:
            self._add_spin(form, "colorbar_x", "Colorbar Δx (fig)",
                           style, -0.5, 0.5, 0.001, decimals=4)
        if "colorbar_y" in allowed:
            self._add_spin(form, "colorbar_y", "Colorbar Δy (fig)",
                           style, -0.5, 0.5, 0.001, decimals=4)
        if "colorbar_w" in allowed:
            self._add_spin(form, "colorbar_w", "Colorbar Δwidth (fig)",
                           style, -0.8, 0.5, 0.001, decimals=4)
        if "colorbar_h" in allowed:
            self._add_spin(form, "colorbar_h", "Colorbar Δheight (fig)",
                           style, -0.03, 0.3, 0.001, decimals=4)
        if "cell_label_dx" in allowed:
            self._add_int_spin(form, "cell_label_dx",
                               "Cell label Δx (px)", style, -200, 200)
        if "cell_label_dy" in allowed:
            self._add_int_spin(form, "cell_label_dy",
                               "Cell label Δy (px)", style, -200, 200)
        if "legend_x_offset" in allowed:
            self._add_spin(form, "legend_x_offset",
                           "Legend Δx (axes frac)",
                           style, -1.0, 1.0, 0.001, decimals=4)
        if "legend_y_offset" in allowed:
            self._add_spin(form, "legend_y_offset",
                           "Legend Δy (axes frac)",
                           style, -1.0, 1.0, 0.001, decimals=4)

    # ── editor primitives ────────────────────────────────────────────────
    def _row_label(self, field, text):
        """Prepend a dot when the field differs from the Light-preset
        baseline, so users can spot what they've changed at a glance."""
        diffs = getattr(self, "_diff_fields", set())
        prefix = "• " if field in diffs else ""
        return f"{prefix}{text}:"

    def _row_label_widget(self, field, label_text):
        """Build (and remember) the QLabel for a row so _commit can flip
        its diff dot without rebuilding the whole tab."""
        lbl = QLabel(self._row_label(field, label_text))
        self._label_widgets[field] = (lbl, label_text)
        return lbl

    def _refresh_field_label(self, field, value):
        pair = self._label_widgets.get(field)
        if pair is None:
            return
        lbl, original = pair
        baseline = default_style_for(self._current, self._current_plugin_key).get(field)
        if baseline != value:
            self._diff_fields.add(field)
        else:
            self._diff_fields.discard(field)
        lbl.setText(self._row_label(field, original))

    def _commit(self, field, value):
        s = self._cfg.get_for(self._current_plugin_key, self._current)
        s[field] = value
        # Show/hide the custom-palette row when the Colormap dropdown
        # switches between "custom" and a named cmap.
        if field == "cmap":
            is_custom = (value == "custom")
            lbl = getattr(self, "_palette_label", None)
            cont = getattr(self, "_palette_container", None)
            if lbl is not None:
                lbl.setVisible(is_custom)
            if cont is not None:
                cont.setVisible(is_custom)
        # Picking a named legend loc from the dropdown should land the
        # legend cleanly on that corner. Wipe any drag-set offsets so
        # the new loc isn't applied on top of a stale nudge. "custom"
        # is the exception — it *needs* the offsets to position itself.
        if field == "legend_loc" and value != "custom":
            s["legend_x_offset"] = 0.0
            s["legend_y_offset"] = 0.0
            for f in ("legend_x_offset", "legend_y_offset"):
                sp = self._editors.get(f)
                if sp is not None:
                    sp.blockSignals(True)
                    try:
                        sp.setValue(0.0)
                    finally:
                        sp.blockSignals(False)
                    self._refresh_field_label(f, 0.0)
        self._cfg.set_for(self._current_plugin_key, self._current, s)
        self.cmb_preset.blockSignals(True)
        self.cmb_preset.setCurrentIndex(0)
        self.cmb_preset.blockSignals(False)
        self._refresh_field_label(field, value)
        self._preview_timer.start()
        if self._live and self._rerender:
            self._rerender_timer.start()

    def _fire_rerender(self):
        if self._rerender:
            try:
                self._rerender(self._current)
            except Exception:
                pass

    def _add_color(self, form, field, label, style):
        btn = _ColorButton(resolve_field(field, style.get(field, "#000000"), _fig_mode()),
                           lambda hx, f=field: self._commit(f, hx), self)
        wrap = QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(4)
        for hx in SWATCHES:
            sw = QPushButton()
            sw.setFixedSize(18, 18)
            sw.setStyleSheet(f"background:{hx}; border:1px solid rgba(128,128,128,0.45);")
            sw.clicked.connect(lambda _=False, h=hx, b=btn, f=field:
                               (b.set_hex(h), self._commit(f, h)))
            wrap.addWidget(sw)
        wrap.addWidget(btn)
        wrap.addStretch()
        w = QWidget()
        w.setLayout(wrap)
        form.addRow(self._row_label_widget(field, label), w)
        self._editors[field] = btn

    def _add_palette_row(self, form, style, allowed):
        """Custom-colormap palette: one row with a count spinbox and up to
        len(CUSTOM_CMAP_STOPS) color swatches. Only visible when the
        Colormap dropdown is set to 'custom'."""
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)

        n_max = len(CUSTOM_CMAP_STOPS)
        cur_n = int(style.get("cmap_custom_n", n_max))
        cur_n = max(2, min(n_max, cur_n))

        n_spin = QSpinBox()
        n_spin.setRange(2, n_max)
        n_spin.setValue(cur_n)
        n_spin.setFixedWidth(46)
        n_spin.setToolTip("Number of colors in the gradient")
        h.addWidget(n_spin)

        swatch_btns = []
        for key in CUSTOM_CMAP_STOPS:
            btn = _ColorButton(style.get(key, "#FFFFFF"),
                               lambda hx, f=key: self._commit(f, hx), self)
            btn.setFixedSize(38, 22)
            h.addWidget(btn)
            swatch_btns.append(btn)
        h.addStretch()

        def _apply_count(v):
            v = max(2, min(n_max, int(v)))
            for i, b in enumerate(swatch_btns):
                b.setVisible(i < v)

        _apply_count(cur_n)
        n_spin.valueChanged.connect(
            lambda v: (self._commit("cmap_custom_n", int(v)),
                       _apply_count(int(v)))
        )

        label_w = self._row_label_widget("cmap_custom_n", "Custom palette")
        form.addRow(label_w, container)
        self._editors["cmap_custom_n"] = n_spin
        for key, btn in zip(CUSTOM_CMAP_STOPS, swatch_btns):
            self._editors[key] = btn

        # Show only when cmap == "custom"; _commit toggles on change.
        is_custom = style.get("cmap", "jet") == "custom"
        label_w.setVisible(is_custom)
        container.setVisible(is_custom)
        self._palette_label = label_w
        self._palette_container = container

    def _add_spin(self, form, field, label, style, lo, hi, step, decimals=2):
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setSingleStep(step)
        sp.setDecimals(decimals)
        try:
            sp.setValue(float(style.get(field, lo)))
        except Exception:
            sp.setValue(lo)
        sp.valueChanged.connect(lambda v, f=field: self._commit(f, float(v)))
        form.addRow(self._row_label_widget(field, label), sp)
        self._editors[field] = sp

    def _add_int_spin(self, form, field, label, style, lo, hi):
        sp = QSpinBox()
        sp.setRange(lo, hi)
        try:
            sp.setValue(int(style.get(field, lo)))
        except Exception:
            sp.setValue(lo)
        sp.valueChanged.connect(lambda v, f=field: self._commit(f, int(v)))
        form.addRow(self._row_label_widget(field, label), sp)
        self._editors[field] = sp

    def _add_combo(self, form, field, label, style, choices):
        cb = QComboBox()
        for c in choices:
            cb.addItem(c)
        cur = style.get(field, choices[0])
        idx = cb.findText(cur)
        if idx >= 0:
            cb.setCurrentIndex(idx)
        cb.currentTextChanged.connect(lambda v, f=field: self._commit(f, v))
        form.addRow(self._row_label_widget(field, label), cb)
        self._editors[field] = cb

    def _add_pair_combo(self, form, field, label, style, pairs):
        """For (display, value) pairs e.g. (\"dashed\", \"--\")."""
        cb = QComboBox()
        for disp, _ in pairs:
            cb.addItem(disp)
        cur = style.get(field, pairs[0][1])
        for i, (_, v) in enumerate(pairs):
            if v == cur:
                cb.setCurrentIndex(i)
                break
        def on_change(_=None, f=field, lst=pairs, w=cb):
            v = lst[w.currentIndex()][1]
            self._commit(f, v)
        cb.currentIndexChanged.connect(on_change)
        form.addRow(self._row_label_widget(field, label), cb)
        self._editors[field] = cb

    def _add_check(self, form, field, label, style):
        cb = QCheckBox()
        cb.setChecked(bool(style.get(field, False)))
        cb.toggled.connect(lambda v, f=field: self._commit(f, bool(v)))
        form.addRow(self._row_label_widget(field, label), cb)
        self._editors[field] = cb

    def _add_text(self, form, field, label, style):
        le = QLineEdit()
        le.setText(str(style.get(field, "")))
        # Live commit on every keystroke; _commit's QTimer debounce coalesces
        # bursts into one preview redraw per ~60 ms.
        le.textChanged.connect(lambda v, f=field: self._commit(f, v))
        form.addRow(self._row_label_widget(field, label), le)
        self._editors[field] = le

    def _add_bar_colors(self, form, style):
        """Editor for the 4 zone-bar colors."""
        cols = list(resolve_token(style.get("bar_colors") or ["@ac", "@ink3", "@warn", "@err"], "data"))
        baseline = default_style_for(self._current, self._current_plugin_key).get("bar_colors") or []
        labels = ["Center", "Periphery", "Undetected", "Outside"]
        for i, lbl in enumerate(labels):
            cur = cols[i] if i < len(cols) else "#888888"
            base = baseline[i] if i < len(baseline) else None
            prefix = "• " if base is not None and base != cur else ""
            def make_handler(idx):
                def h(hx):
                    s = self._cfg.get_for(self._current_plugin_key, self._current)
                    arr = list(s.get("bar_colors") or [])
                    while len(arr) < 4:
                        arr.append("#888888")
                    arr[idx] = hx
                    self._commit("bar_colors", arr)
                return h
            btn = _ColorButton(cur, make_handler(i), self)
            form.addRow(f"{prefix}Bar — {lbl}:", btn)
            self._editors[f"bar_colors[{i}]"] = btn

    # ── sample regen + builders ──────────────────────────────────────────
    def _regen_sample(self):
        if self._using_real:
            return
        import random
        self._sample_seed = random.randint(1, 10_000_000)
        self._synth_sample = self._build_sample(self._sample_seed)
        self._sample = self._synth_sample
        self._refresh_preview()

    def _on_real_toggle(self, on):
        if on:
            real = self._maybe_real_sample()
            if real is None:
                self.chk_real.setChecked(False)
                return
            self._using_real = True
            self._sample = real
            self.btn_regen.setEnabled(False)
        else:
            self._using_real = False
            self._sample = self._synth_sample
            self.btn_regen.setEnabled(True)
        self._refresh_preview()

    def _maybe_real_sample(self):
        """Build a sample dict from parent ExperimentTab's tracked session,
        mapped to preview coord space. Returns None if no usable data."""
        p = self._parent_tab
        if p is None:
            return None
        raw_df = getattr(p, "raw_df", None)
        if raw_df is None or len(raw_df) < 2:
            return None
        try:
            x_real = raw_df["X (px)"].dropna().values.astype(float)
            y_real = raw_df["Y (px)"].dropna().values.astype(float)
        except Exception:
            return None
        if x_real.size < 2:
            return None
        arena_half = 22.0
        x_min, x_max = float(x_real.min()), float(x_real.max())
        y_min, y_max = float(y_real.min()), float(y_real.max())
        span = max(x_max - x_min, y_max - y_min, 1e-6)
        s = 2 * arena_half / span
        cx = (x_min + x_max) / 2.0
        cy = (y_min + y_max) / 2.0
        xs = (x_real - cx) * s
        # Keep pixel-Y-down convention. The preview's `ax.set_ylim(...)` is
        # already inverted, so high pixel Y (= bottom of video) lands at
        # the bottom of the preview — matching the actual Trajectory render.
        # The earlier negation here flipped it twice and inverted the view.
        ys = (y_real - cy) * s

        fps = float(getattr(p, "fps", 30.0) or 30.0)
        n = xs.size
        dx = np.diff(xs, prepend=xs[0])
        dy = np.diff(ys, prepend=ys[0])
        step_d = np.sqrt(dx * dx + dy * dy)
        speeds = step_d * fps          # preview-box units — fallback only
        speed_unit = "cm/s"
        # Speed graphs must show the real tracked speeds (the positions above
        # are rescaled to fit the preview box, so their speeds have no unit).
        sp_col = next((c for c in raw_df.columns if str(c).startswith("Speed (")), None)
        if sp_col is not None:
            real = raw_df[sp_col].dropna().values.astype(float)
            if real.size >= 2:
                speeds = real
                speed_unit = str(sp_col).split("(")[-1].rstrip(")")

        metrics = getattr(p, "metrics", None) or {}
        cell_times = np.zeros(16)
        for cid in range(1, 17):
            try:
                cell_times[cid - 1] = float(metrics.get(f"Cell {cid} Time (s)", 0.0) or 0.0)
            except (TypeError, ValueError):
                pass
        if cell_times.sum() == 0.0:
            cell_size = (2 * arena_half) / 4.0
            col = np.clip(((xs + arena_half) / cell_size).astype(int), 0, 3)
            row = np.clip(((arena_half - ys) / cell_size).astype(int), 0, 3)
            for c_, r_ in zip(col, row):
                cell_times[r_ * 4 + c_] += 1.0 / fps

        zone_times = {"Center Zone": 0.0, "Periphery": 0.0,
                      "Undetected": 0.0, "Outside": 0.0}
        if "Zone" in raw_df.columns:
            z = raw_df["Zone"]
            zone_times["Center Zone"] = float((z == "center_zone").sum()) / fps
            zone_times["Periphery"]   = float((z == "periphery").sum()) / fps
            zone_times["Undetected"]  = float((z == "undetected").sum()) / fps
            zone_times["Outside"]     = float((z == "outside").sum()) / fps
        else:
            center_half = arena_half / 2.2
            in_center = (np.abs(xs) < center_half) & (np.abs(ys) < center_half)
            zone_times["Center Zone"] = float(in_center.sum()) / fps
            zone_times["Periphery"]   = float((~in_center).sum()) / fps

        bin_df = getattr(p, "bin_df", None)
        bin_dists = np.array([])
        bin_centers_min = np.array([])
        dist_unit = "a.u."     # preview-box units unless real bins exist
        if bin_df is not None and not bin_df.empty:
            try:
                dist_col = next((c for c in bin_df.columns
                                 if c.startswith("Distance")), None)
                if dist_col:
                    bin_dists = bin_df[dist_col].values.astype(float)
                    dist_unit = dist_col.split("(")[-1].rstrip(")")
                    start = bin_df["Bin Start (s)"].values.astype(float)
                    end = (bin_df["Bin End (s)"].values.astype(float)
                           if "Bin End (s)" in bin_df.columns else start)
                    # bin centres, like the Output graph
                    bin_centers_min = (start + end) / 2.0 / 60.0
            except Exception:
                pass
        if bin_dists.size == 0:
            n_bins = 8
            bin_size = max(1, n // n_bins)
            bin_dists = np.zeros(n_bins)
            bin_centers_min = np.zeros(n_bins)
            for i in range(n_bins):
                a = i * bin_size
                b = (i + 1) * bin_size if i < n_bins - 1 else n
                bin_dists[i] = float(step_d[a:b].sum())
                bin_centers_min[i] = (a + b) / 2.0 / fps / 60.0

        return {
            "xs": xs, "ys": ys, "speeds": speeds, "step_d": step_d,
            "speed_unit": speed_unit,
            "dist_unit": dist_unit,
            "fps": fps, "n": n, "arena_half": arena_half,
            "cell_times": cell_times,
            "zone_times": zone_times,
            "bin_dists": bin_dists,
            "bin_centers_min": bin_centers_min,
            "arena_poly": self._arena_poly_in_preview_space(
                s, cx, cy, flip_y=False,
            ),
            "center_pct": (100.0 * zone_times.get("Center", 0.0)
                           / max(1e-6, sum(zone_times.values()))),
        }

    def _arena_poly_in_preview_space(self, s=None, cx=None, cy=None,
                                      flip_y=True):
        """Map parent's arena polygon (or Y-Maze zone union) into the
        centered preview coord box. Returns Nx2 ndarray or None.

        flip_y=True (default, synth context): negate Y so the polygon
            lives in math-up convention, matching the synth path which
            uses positive Y as up. The preview's inverted ylim then
            displays both consistently.
        flip_y=False (real-session context): keep pixel-down convention.
            The real sample's xs/ys are also in pixel-down here, so both
            match. Inverted ylim displays them correctly oriented (high
            pixel Y at bottom of preview, matching the actual render).

        `s`, `cx`, `cy` None → derive from polygon's bbox (synth)."""
        p = self._parent_tab
        if p is None:
            return None
        poly_px = None
        try:
            _, arena, _, _ = p._graph_data()
            if arena and len(arena) >= 3:
                poly_px = np.array(arena, dtype=float)
        except Exception:
            poly_px = None
        if poly_px is None:
            try:
                vw, vh = p._graph_canvas_size()
                zlist = (p.zone_drawer.list_zones()
                         if hasattr(p, "zone_drawer") else [])
                pts = []
                for z in zlist:
                    geom = z.get("geometry") if isinstance(z, dict) else None
                    if not geom or len(geom) < 3:
                        continue
                    for (px_n, py_n) in geom:
                        pts.append((float(px_n) * vw, float(py_n) * vh))
                if len(pts) >= 3:
                    poly_px = np.array(pts, dtype=float)
            except Exception:
                poly_px = None
        if poly_px is None or len(poly_px) < 3:
            return None
        arena_half = 22.0
        if s is None or cx is None or cy is None:
            x_min, x_max = float(poly_px[:, 0].min()), float(poly_px[:, 0].max())
            y_min, y_max = float(poly_px[:, 1].min()), float(poly_px[:, 1].max())
            span = max(x_max - x_min, y_max - y_min, 1e-6)
            s = 2 * arena_half / span
            cx = (x_min + x_max) / 2.0
            cy = (y_min + y_max) / 2.0
        out = np.empty_like(poly_px)
        out[:, 0] = (poly_px[:, 0] - cx) * s
        out[:, 1] = (poly_px[:, 1] - cy) * s
        if flip_y:
            out[:, 1] = -out[:, 1]
        return out

    def _build_sample(self, seed):
        rng = np.random.default_rng(seed)
        arena_half = 22.0
        fps = 15.0
        n = 4500
        key = self._current_plugin_key
        synth_polys, synth_objs = self._synthetic_shape(key, arena_half)
        # Per-experiment movement model: path that respects how the animal
        # actually moves in THIS apparatus + the matching zone categories.
        # Each returns (xs, ys, zone_labels, zone_times{label: seconds}).
        if key == "epm":
            xs, ys, zone_labels, zone_times = self._model_epm(rng, n, arena_half, fps)
        elif key == "y_maze":
            xs, ys, zone_labels, zone_times = self._model_ymaze(rng, n, arena_half, fps)
        elif key == "nor":
            xs, ys, zone_labels, zone_times = self._model_nor(
                rng, n, arena_half, fps, synth_objs)
        else:
            xs, ys = self._animal_path(rng, n=n, arena_half=arena_half, habituate=True)
            zone_labels, zone_times = self._zones_open_field(xs, ys, arena_half, fps, rng)
        dx = np.diff(xs, prepend=xs[0])
        dy = np.diff(ys, prepend=ys[0])
        step_d = np.sqrt(dx * dx + dy * dy)
        speeds = step_d * fps
        # 4×4 cell times — only the OF Cell Time graph uses these.
        cell_size = (2 * arena_half) / 4.0
        col = np.clip(((xs + arena_half) / cell_size).astype(int), 0, 3)
        row = np.clip(((arena_half - ys) / cell_size).astype(int), 0, 3)
        cell_times = np.zeros(16)
        for c, r in zip(col, row):
            cell_times[r * 4 + c] += 1.0 / fps
        n_bins = 8
        bin_size = n // n_bins
        bin_dists = np.zeros(n_bins)
        bin_centers_min = np.zeros(n_bins)
        for i in range(n_bins):
            a = i * bin_size
            b = (i + 1) * bin_size if i < n_bins - 1 else n
            bin_dists[i] = float(step_d[a:b].sum())
            bin_centers_min[i] = (a + b) / 2.0 / fps / 60.0
        # FAKE-data sample → always the canonical synthetic shape for the
        # active experiment. The parent's real drawn outline only pairs with
        # the REAL tracked path in _maybe_real_sample.
        arena_poly = synth_polys[0] if synth_polys else None
        total = sum(zone_times.values()) or 1.0
        return {
            "xs": xs, "ys": ys, "speeds": speeds, "step_d": step_d,
            "fps": fps, "n": n, "arena_half": arena_half,
            "cell_times": cell_times,
            "zone_times": zone_times,
            "zone_labels": zone_labels,
            "bin_dists": bin_dists,
            "bin_centers_min": bin_centers_min,
            "arena_poly": arena_poly,
            "arena_polys": synth_polys,
            "objects": synth_objs,
            "_synthetic": True,
            "center_pct": 100.0 * zone_times.get("Center", 0.0) / total,
        }

    # ── per-experiment synthetic movement models ──────────────────────────
    def _zones_open_field(self, xs, ys, L, fps, rng):
        center_half = L / 2.2
        in_center = (np.abs(xs) < center_half) & (np.abs(ys) < center_half)
        return (["Center", "Periphery", "Undetected", "Outside"], {
            "Center":     float(in_center.sum()) / fps,
            "Periphery":  float((~in_center).sum()) / fps,
            "Undetected": float(rng.uniform(0, 3)),
            "Outside":    float(rng.uniform(0, 2)),
        })

    # Nominal plus-arm half-width the synthetic EPM path is generated at;
    # the reshape step rescales lateral to the displayed arm thickness.
    _EPM_NOMINAL_AW_FRAC = 0.30

    def _model_epm(self, rng, n, L, fps):
        """EPM: a clean, legible preview track of plus-maze exploration.

        The mouse spends most time in the two CLOSED (vertical) arms with
        deep runs, making briefer, shallower forays into the OPEN
        (horizontal) arms (anxiety). Same look as the Y-maze preview: each
        run follows its own smooth centre-line lane, rounded hairpin turns
        at the tips, gentle multi-bend curves, and wall padding so it never
        rides the walls."""
        import math
        # N, S = closed (vertical); E, W = open (horizontal)
        dirs = [np.array([0.0, -1.0]), np.array([0.0, 1.0]),
                np.array([1.0, 0.0]), np.array([-1.0, 0.0])]
        perps = [np.array([-d[1], d[0]]) for d in dirs]
        is_open = [False, False, True, True]
        aw = L * self._EPM_NOMINAL_AW_FRAC    # nominal arm half-width
        tip = L * 0.95

        xs = np.empty(n); ys = np.empty(n); i = 0
        lane = 0.0

        def emit(k, along, lateral):
            nonlocal i
            if i < n:
                w = dirs[k] * max(0.0, along) + perps[k] * lateral
                xs[i] = w[0]; ys[i] = w[1]; i += 1

        def lane_curve():
            return [(aw * float(rng.uniform(0.04, 0.10)),
                     float(rng.uniform(1.0, 2.6)),
                     float(rng.uniform(0.0, 2 * math.pi))) for _ in range(3)]

        def lat_at(u, center, curve):
            v = center
            for a, f, p in curve:
                v += a * math.sin(math.pi * f * u + p)
            return float(np.clip(v, -aw * 0.42, aw * 0.42))

        while i < n:
            # closed (vertical) arms chosen ~2x more often than open ones
            k = int(rng.choice(4, p=[0.34, 0.34, 0.16, 0.16]))
            depth = tip * (float(rng.uniform(0.30, 0.65)) if is_open[k]
                           else float(rng.uniform(0.80, 1.0)))
            base = aw * float(rng.uniform(0.007, 0.012))
            lane = float(np.clip(lane + rng.normal(0, aw * 0.09), -aw * 0.18, aw * 0.18))
            lane_out = lane
            lane_back = float(np.clip(-0.5 * lane_out + rng.normal(0, aw * 0.072),
                                      -aw * 0.18, aw * 0.18))
            curve_out = lane_curve()
            curve_back = lane_curve()
            turn_r = aw * float(rng.uniform(0.9, 1.5))
            d_out = max(depth - turn_r, depth * 0.4)

            # ── run OUT ──
            along = 0.0
            while along < d_out and i < n:
                along += base * float(rng.uniform(0.4, 1.7))
                emit(k, min(along, d_out),
                     lat_at(min(along, d_out) / depth, lane_out, curve_out))

            # ── rounded turn-around arc at the tip ──
            l0 = lat_at(d_out / depth, lane_out, curve_out)
            l1 = lat_at(d_out / depth, lane_back, curve_back)
            nturn = int(rng.integers(8, 16))
            for t in range(1, nturn + 1):
                if i >= n:
                    break
                th = math.pi * t / nturn
                emit(k, d_out + turn_r * math.sin(th),
                     l0 + (l1 - l0) * (1 - math.cos(th)) / 2)

            # ── run BACK ──
            along = d_out
            while along > 0.0 and i < n:
                along -= base * float(rng.uniform(0.4, 1.7))
                emit(k, max(along, 0.0),
                     lat_at(max(along, 0.0) / depth, lane_back, curve_back))
            lane = lane_back

            # ── brief open crossing through the centre ──
            for _ in range(int(rng.integers(1, 4))):
                if i >= n:
                    break
                emit(k, float(rng.uniform(0.0, aw * 0.3)),
                     lane_back * float(rng.uniform(0.0, 0.5)))

        xs, ys = xs[:n], ys[:n]
        inc = (np.abs(xs) <= aw) & (np.abs(ys) <= aw)
        horiz = (~inc) & (np.abs(xs) > np.abs(ys))   # open arms (E/W)
        vert = (~inc) & (~horiz)                     # closed arms (N/S)
        return xs, ys, ["Open arms", "Closed arms", "Center"], {
            "Open arms":   float(horiz.sum()) / fps,
            "Closed arms": float(vert.sum()) / fps,
            "Center":      float(inc.sum()) / fps,
        }

    # Nominal arm half-width the synthetic Y path is generated against. The
    # reshape step rescales the cross-arm offset from this to the displayed
    # arm thickness, so the centerline ribbon stays proportional.
    _YM_NOMINAL_AW_FRAC = 0.20

    def _model_ymaze(self, rng, n, L, fps):
        """Y-Maze: a clean, legible preview track of free exploration.

        The animal makes a series of out-and-back arm runs through the hub.
        Each run follows its own slightly different lateral 'lane' down the
        arm (and usually returns along the other side), so the overlaid runs
        read as a light bundle of lines along each arm — the way a real
        centroid track looks — rather than a dense scribble. Kept simple on
        purpose: this is only a preview for judging colours / line width.
        Arm choice carries a spontaneous-alternation bias (~65%) with
        occasional same-arm returns; run speed varies between trips."""
        import math
        angs = [90.0, 210.0, 330.0]
        dirs = [np.array([math.cos(math.radians(a)), math.sin(math.radians(a))])
                for a in angs]
        perps = [np.array([-d[1], d[0]]) for d in dirs]
        aw = L * self._YM_NOMINAL_AW_FRAC    # nominal arm half-width
        tip = L * 0.95                        # arm tip distance from hub

        xs = np.empty(n); ys = np.empty(n); i = 0
        recent = []                           # arm-visit history
        lane = 0.0                            # persistent lateral lane

        def emit(k, along, lateral):
            nonlocal i
            if i < n:
                w = dirs[k] * max(0.0, along) + perps[k] * lateral
                xs[i] = w[0]; ys[i] = w[1]; i += 1

        def lane_curve():
            """Small low-frequency random Fourier series describing how a
            run's lateral offset drifts along the arm. Keyed to distance
            (not frame count), so the line shows smooth gentle curves rather
            than a ruler-straight line or high-frequency shake."""
            return [(aw * float(rng.uniform(0.04, 0.10)),
                     float(rng.uniform(1.0, 2.6)),
                     float(rng.uniform(0.0, 2 * math.pi))) for _ in range(3)]

        def lat_at(u, center, curve):
            v = center
            for a, f, p in curve:
                v += a * math.sin(math.pi * f * u + p)
            # padded clip → path stays in the central band, never the walls
            return float(np.clip(v, -aw * 0.42, aw * 0.42))

        while i < n:
            # ── pick next arm: ~65% alternation, ~15% same-arm return, rest random ──
            last = recent[-1] if recent else None
            prev = recent[-2] if len(recent) >= 2 else None
            roll = rng.random()
            if roll < 0.65:
                opts = [a for a in range(3) if a != last and a != prev] \
                    or [a for a in range(3) if a != last] or [0, 1, 2]
                k = int(rng.choice(opts))
            elif roll < 0.80 and last is not None:
                k = last                                  # same-arm return
            else:
                k = int(rng.choice(3))
            recent.append(k)

            depth = tip * float(rng.uniform(0.80, 1.0))
            # Slow base stride → only a handful of clean laps fill the sample
            # (a sparse, uncluttered preview). Per-step speed still varies.
            base = aw * float(rng.uniform(0.007, 0.012))
            # this trip's lane out, and a usually-opposite lane back, each
            # with its own smooth lateral curve down the arm
            lane = float(np.clip(lane + rng.normal(0, aw * 0.09), -aw * 0.18, aw * 0.18))
            lane_out = lane
            lane_back = float(np.clip(-0.5 * lane_out + rng.normal(0, aw * 0.072),
                                      -aw * 0.18, aw * 0.18))
            curve_out = lane_curve()
            curve_back = lane_curve()

            # the out-run stops short of the tip by turn_r; a smooth
            # semicircular arc then bulges out to the tip and sweeps the
            # lateral over to the back-curve — a rounded hairpin that is
            # tangent-continuous with both runs (no flat cap, no corner)
            turn_r = aw * float(rng.uniform(0.9, 1.5))
            d_out = max(depth - turn_r, depth * 0.4)

            # ── run OUT, following its smooth lateral curve ──
            along = 0.0
            while along < d_out and i < n:
                along += base * float(rng.uniform(0.4, 1.7))
                emit(k, min(along, d_out),
                     lat_at(min(along, d_out) / depth, lane_out, curve_out))

            # ── rounded turn-around arc at the tip ──
            l0 = lat_at(d_out / depth, lane_out, curve_out)
            l1 = lat_at(d_out / depth, lane_back, curve_back)
            nturn = int(rng.integers(8, 16))
            for t in range(1, nturn + 1):
                if i >= n:
                    break
                th = math.pi * t / nturn
                emit(k, d_out + turn_r * math.sin(th),
                     l0 + (l1 - l0) * (1 - math.cos(th)) / 2)

            # ── run BACK, following its own curve ──
            along = d_out
            while along > 0.0 and i < n:
                along -= base * float(rng.uniform(0.4, 1.7))
                emit(k, max(along, 0.0),
                     lat_at(max(along, 0.0) / depth, lane_back, curve_back))
            lane = lane_back

            # ── brief open crossing through the hub ──
            for _ in range(int(rng.integers(1, 4))):
                if i >= n:
                    break
                emit(k, float(rng.uniform(0.0, aw * 0.3)),
                     lane_back * float(rng.uniform(0.0, 0.5)))

        xs, ys = xs[:n], ys[:n]
        labels = ["Arm A", "Arm B", "Arm C", "Neutral"]
        zt = {lab: 0.0 for lab in labels}
        r = np.hypot(xs, ys)
        dirs_arr = np.array(dirs)
        dots = dirs_arr @ np.vstack([xs, ys])        # (3, n)
        nearest = np.argmax(dots, axis=0)
        neutral = r <= aw
        for k in range(3):
            zt[labels[k]] = float(((nearest == k) & (~neutral)).sum()) / fps
        zt["Neutral"] = float(neutral.sum()) / fps
        return xs, ys, labels, zt

    def _model_nor(self, rng, n, L, fps, objs):
        """NOR: roam the square, approach + sniff BOTH objects (never through
        them), with more exploration of the novel object (B)."""
        if not objs:
            objs = [(-L * 0.42, L * 0.40, L * 0.13), (L * 0.42, L * 0.40, L * 0.13)]
        body = L * 0.06
        inner = L - body
        pos = np.array([0.0, 0.0])
        xs = np.empty(n); ys = np.empty(n); i = 0
        visit_p = np.array([0.40, 0.60])            # B (novel) preferred
        visit_p = visit_p / visit_p.sum()
        theta = float(rng.uniform(0, 2 * np.pi))
        while i < n:
            if rng.random() < 0.55:                  # go sniff an object
                k = int(rng.choice(len(objs), p=visit_p[:len(objs)]
                                    if len(objs) == 2 else None))
                ocx, ocy, orr = objs[k]
                tgt = np.array([ocx, ocy]); ring = orr * 1.5
                guard = 0
                while i < n and np.hypot(*(tgt - pos)) > ring and guard < 400:
                    d = tgt - pos; d = d / (np.hypot(*d) or 1.0)
                    pos = np.clip(pos + d * L * 0.05 * float(rng.normal(1, 0.2)),
                                  -inner, inner)
                    pos = self._push_out_circles(pos, objs)
                    xs[i] = pos[0]; ys[i] = pos[1]; i += 1; guard += 1
                sniff = int(rng.integers(15, 45)) * (2 if k == 1 else 1)
                ang = float(rng.uniform(0, 2 * np.pi))
                for _ in range(sniff):
                    if i >= n:
                        break
                    ang += float(rng.normal(0, 0.4))
                    rr = orr * float(rng.uniform(1.05, 1.5))
                    pos = np.clip(np.array([ocx + rr * np.cos(ang),
                                            ocy + rr * np.sin(ang)]), -inner, inner)
                    xs[i] = pos[0]; ys[i] = pos[1]; i += 1
            else:                                    # roam
                for _ in range(int(rng.integers(20, 60))):
                    if i >= n:
                        break
                    theta += float(rng.normal(0, 0.3))
                    pos = np.clip(pos + np.array([np.cos(theta), np.sin(theta)])
                                  * L * 0.045, -inner, inner)
                    pos = self._push_out_circles(pos, objs)
                    xs[i] = pos[0]; ys[i] = pos[1]; i += 1
        xs, ys = xs[:n], ys[:n]
        ax_, ay_, ar_ = objs[0]
        bx_, by_, br_ = objs[1]
        da = np.hypot(xs - ax_, ys - ay_)
        db = np.hypot(xs - bx_, ys - by_)
        near_a = da <= ar_ * 1.5
        near_b = (~near_a) & (db <= br_ * 1.5)
        expl = ~(near_a | near_b)
        return xs, ys, ["Object A", "Object B", "Exploring"], {
            "Object A":  float(near_a.sum()) / fps,
            "Object B":  float(near_b.sum()) / fps,
            "Exploring": float(expl.sum()) / fps,
        }

    @staticmethod
    def _scale_to_arms(xs, ys, dirs, aw0, w):
        """Map a synthetic Y path generated at nominal arm half-width `aw0`
        onto the displayed half-width `w` by SCALING each point's cross-arm
        (lateral) component while keeping its along-arm distance. This shrinks
        or grows the centerline ribbon with the chosen arm thickness, instead
        of pinning points to the walls (which smears the path wall-to-wall on
        thin arms). Points are assigned to whichever arm axis they project
        farthest along."""
        xs = np.asarray(xs, float).copy(); ys = np.asarray(ys, float).copy()
        dirs_arr = np.array([np.array(d, float) / (np.hypot(*d) or 1.0) for d in dirs])
        perps = np.array([[-d[1], d[0]] for d in dirs_arr])
        dots = dirs_arr @ np.vstack([xs, ys])         # (k, n) along each arm
        nearest = np.argmax(dots, axis=0)
        scale = (w / aw0) if aw0 else 1.0
        out_x = xs.copy(); out_y = ys.copy()
        for k in range(len(dirs_arr)):
            sel = nearest == k
            if not sel.any():
                continue
            along = xs[sel] * dirs_arr[k, 0] + ys[sel] * dirs_arr[k, 1]
            lateral = (xs[sel] * perps[k, 0] + ys[sel] * perps[k, 1]) * scale
            out_x[sel] = along * dirs_arr[k, 0] + lateral * perps[k, 0]
            out_y[sel] = along * dirs_arr[k, 1] + lateral * perps[k, 1]
        return out_x, out_y

    @staticmethod
    def _push_out_circles(pos, objs):
        """If `pos` is inside an object footprint, push it just outside the
        rim — mice go around/sniff objects, never through them."""
        for (cx, cy, r) in objs:
            d = pos - np.array([cx, cy])
            dist = float(np.hypot(*d))
            if dist < r * 1.02:
                u = d / (dist or 1.0)
                pos = np.array([cx, cy]) + u * r * 1.05
        return pos

    def _synthetic_shape(self, plugin_key, arena_half, thickness_pct=30.0):
        """Canonical preview geometry for an experiment when no real drawn
        arena exists. Returns (polys, objects):
          polys   = list of Nx2 vertex lists (one per fillable region), or None
          objects = list of (cx, cy, r) circles (NOR objects), or None
        Coords are centered on (0,0) in the same box as the synthetic path.
        `thickness_pct` sets the arm half-width (% of arena half) for + / Y."""
        L = float(arena_half)
        if plugin_key in ("epm", "y_maze"):
            return (maze_shape_polys(plugin_key, L, thickness_pct), None)
        if plugin_key == "nor":
            # Open-field square with two identical objects to explore.
            r = L * 0.13
            objs = [(-L * 0.42, L * 0.40, r), (L * 0.42, L * 0.40, r)]
            return ([[(-L, -L), (L, -L), (L, L), (-L, L)]], objs)
        # open_field / default: plain square.
        return ([[(-L, -L), (L, -L), (L, L), (-L, L)]], None)

    @staticmethod
    def _animal_path(rng, n=600, arena_half=22.0, habituate=True):
        # Tracked point is the mouse body centre — stays a body's half-width
        # away from the wall. Real OFT tracks never touch the outline.
        body_offset = arena_half * 0.06
        inner = arena_half - body_offset
        wall_buf = inner * 0.11
        x = float(rng.uniform(-inner * 0.4, inner * 0.4))
        y = float(rng.uniform(-inner * 0.4, inner * 0.4))
        theta = float(rng.uniform(0, 2 * np.pi))
        base_speed = 0.55
        xs = np.empty(n); ys = np.empty(n)
        transit_left = 0
        for i in range(n):
            decay = (1.0 - 0.45 * (i / max(1, n - 1))) if habituate else 1.0
            bs = base_speed * decay
            dx_wall = inner - abs(x)
            dy_wall = inner - abs(y)
            near_x = dx_wall < wall_buf
            near_y = dy_wall < wall_buf
            in_corner = near_x and near_y
            if transit_left > 0:
                theta += float(rng.normal(0, 0.04))
                speed = max(0.0, float(rng.normal(bs * 1.4, 0.15)))
                transit_left -= 1
            elif in_corner:
                theta += float(rng.normal(0, 0.65))
                if rng.random() < 0.30:
                    speed = 0.0
                else:
                    speed = max(0.0, float(rng.normal(0.18 * decay, 0.12)))
            elif near_x or near_y:
                if near_x:
                    target = np.pi / 2 if np.sin(theta) >= 0 else -np.pi / 2
                else:
                    target = 0.0 if np.cos(theta) >= 0 else np.pi
                diff = (target - theta + np.pi) % (2 * np.pi) - np.pi
                theta += 0.30 * diff + float(rng.normal(0, 0.20))
                if rng.random() < 0.05:
                    speed = 0.0
                else:
                    speed = max(0.0, float(rng.normal(bs * 0.95, 0.18)))
            else:
                if rng.random() < 0.008:
                    transit_left = int(rng.integers(20, 60))
                theta += float(rng.normal(0, 0.22))
                if rng.random() < 0.06:
                    speed = 0.0
                else:
                    speed = max(0.0, float(rng.normal(bs, 0.25)))
                r = float(np.hypot(x, y))
                if r > 1.0:
                    out_theta = float(np.arctan2(y, x))
                    diff_out = (out_theta - theta + np.pi) % (2 * np.pi) - np.pi
                    theta += 0.005 * diff_out
            nx = x + speed * float(np.cos(theta))
            ny = y + speed * float(np.sin(theta))
            if abs(nx) > inner:
                nx = inner * (1.0 if nx > 0 else -1.0)
                theta = np.pi - theta
                transit_left = 0
            if abs(ny) > inner:
                ny = inner * (1.0 if ny > 0 else -1.0)
                theta = -theta
                transit_left = 0
            x, y = nx, ny
            xs[i] = x; ys[i] = y
        return xs, ys

    # ── preview rendering ────────────────────────────────────────────────
    # Spatial graphs — ticks forced off (arena coords). Spines stay user-controlled.
    _GRIDLESS_GRAPHS = {"Trajectory", "Heatmap", "Cell Time"}

    def _apply_axes_style(self, ax, st, allowed):
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
        if self._current in self._GRIDLESS_GRAPHS:
            ax.set_xticks([]); ax.set_yticks([])
        elif "show_ticks" in allowed and not st.get("show_ticks", True):
            ax.set_xticks([]); ax.set_yticks([])
        else:
            tc = st.get("tick_color", "#333333")
            ts = int(st.get("tick_size", 9))
            ax.tick_params(colors=tc, labelsize=ts)
            if st.get("tick_bold"):
                for lab in ax.get_xticklabels() + ax.get_yticklabels():
                    lab.set_fontweight("bold")
        # Grid.
        if "grid" in allowed and st.get("grid"):
            ax.grid(True,
                    axis=st.get("grid_axis", "both"),
                    color=st.get("grid_color", "#BBBBBB"),
                    alpha=float(st.get("grid_alpha", 0.3)),
                    linestyle=st.get("grid_linestyle", "-"))

    def _apply_text_style(self, ax, st, allowed):
        fam = st.get("font_family", "sans-serif")
        if st.get("title"):
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

    def _maybe_legend(self, ax, st, allowed, handles_labels=None, handles=None):
        if "legend_show" not in allowed or not st.get("legend_show", True):
            return None
        kwargs = _legend_kwargs_for(ax, st)
        if handles is not None:
            leg = ax.legend(handles=handles, **kwargs)
        elif handles_labels:
            leg = ax.legend(*handles_labels, **kwargs)
        else:
            leg = ax.legend(**kwargs)
        apply_legend_labels(leg, st)
        # Note: matplotlib's built-in set_draggable is intentionally NOT
        # enabled here — the dialog owns drag via _setup_drag_handlers and
        # mpl's draggable would fight it. legend_draggable still controls
        # the production renderer (see _apply_legend).
        return leg

    def _refresh_preview(self):
        from matplotlib.patches import Rectangle, Polygon
        from matplotlib import colors as mcolors

        # Drag wiring is per-render — the artists get rebuilt from scratch,
        # so previous mpl event handlers must be detached before we attach
        # new ones at the end of this method.
        self._teardown_drag_handlers()
        self._drag_artists = {
            "legend": None, "cax": None, "cell_texts": None, "title": None,
        }

        def _shape_polys(arena_poly, arena_polys, arena_half):
            """Resolve the region polygon(s) to draw: an explicit multi-poly
            shape (+/Y), a single polygon, or a default square."""
            if arena_polys:
                return [p for p in arena_polys if p is not None and len(p) >= 3]
            if arena_poly is not None and len(arena_poly) >= 3:
                return [arena_poly]
            h = arena_half
            return [[(-h, -h), (h, -h), (h, h), (-h, h)]]

        def _add_arena_patch(ax, st, arena_poly, arena_half, arena_polys=None, **kw):
            """Outline each region polygon (square / + / Y)."""
            for poly in _shape_polys(arena_poly, arena_polys, arena_half):
                ax.add_patch(Polygon(
                    poly, closed=True, fill=False,
                    edgecolor=st["arena_color"],
                    linewidth=st["arena_width"],
                    **kw,
                ))

        def _add_area_fill(ax, fill_color, arena_poly, arena_half, arena_polys=None):
            """Fills each region interior with `fill_color` (zorder=0)."""
            for poly in _shape_polys(arena_poly, arena_polys, arena_half):
                ax.add_patch(Polygon(
                    poly, closed=True, facecolor=fill_color,
                    edgecolor="none", zorder=0,
                ))

        def _add_objects(ax, st, objects):
            """Draw NOR exploration objects as outlined circles."""
            if not objects:
                return
            from matplotlib.patches import Circle
            for (ocx, ocy, orad) in objects:
                ax.add_patch(Circle(
                    (ocx, ocy), orad, fill=False,
                    edgecolor=st["arena_color"],
                    linewidth=st["arena_width"], zorder=5,
                ))

        name = self._current
        st = resolve_style(self._cfg.get_for(self._current_plugin_key, name), _fig_mode())
        allowed = self._allowed_fields(name)
        # Speed graphs: chosen speed unit — values converted below, and the
        # speed-axis title carries the unit (sample / tracked speeds are cm/s).
        sp_factor, sp_unit = 1.0, "cm/s"
        t_factor, t_unit, d_factor, d_unit = 1.0, "s", 1.0, "cm"
        _smp = self._sample or {}
        if name in ("Speed", "Speed Histogram"):
            sp_factor, sp_unit, st = speed_axis(
                st, name, _smp.get("speed_unit", "cm/s"))
        # Time / distance units — the same rules the Output graphs use.
        if name == "Speed":
            t_factor, t_unit, st = time_axis(st, "xlabel")
        elif name in ("Speed Histogram", "Zone Time"):
            t_factor, t_unit, st = time_axis(st, "ylabel")
        elif name == "Habituation":
            d_factor, d_unit, st = distance_axis(st, "ylabel", _smp.get("dist_unit", "cm"))
            t_factor, t_unit, st = time_axis(st, "xlabel", "min", "Bin center")
        bg = st["bg"]
        # outer_bg paints fig + axes when present; bg fills inside the arena
        # polygon. When outer_bg isn't a capability (non-arena charts), bg
        # behaves like the legacy single-color background.
        outer_bg = st.get("outer_bg", bg) if "outer_bg" in allowed else bg
        smp = self._sample

        self._fig.clear()
        self._fig.patch.set_facecolor(outer_bg)
        ax = self._fig.add_subplot(111)
        ax.set_facecolor(outer_bg)

        cmap = resolve_cmap(st)

        arena_half = smp["arena_half"]
        arena_poly = smp.get("arena_poly")
        arena_polys = smp.get("arena_polys")
        objects = smp.get("objects")
        xs_p, ys_p = smp["xs"], smp["ys"]
        # EPM: re-shape the synthetic + live from the current graph's
        # thickness, and keep the fake path inside the + arms.
        if smp.get("_synthetic") and self._current_plugin_key in ("epm", "y_maze"):
            thick = float(st.get("shape_thickness", 30))
            pk = self._current_plugin_key
            arena_polys, objects = self._synthetic_shape(pk, arena_half, thick)
            arena_poly = arena_polys[0] if arena_polys else None
            w = arena_half * thick / 100.0
            if pk == "epm":
                dirs = [(0.0, -1.0), (0.0, 1.0), (1.0, 0.0), (-1.0, 0.0)]
                aw0 = arena_half * self._EPM_NOMINAL_AW_FRAC
                xs_p, ys_p = self._scale_to_arms(xs_p, ys_p, dirs, aw0, w)
            else:  # y_maze — rescale the centerline ribbon to the arm width
                import math
                dirs = [(math.cos(math.radians(a)), math.sin(math.radians(a)))
                        for a in (90.0, 210.0, 330.0)]
                aw0 = arena_half * self._YM_NOMINAL_AW_FRAC
                xs_p, ys_p = self._scale_to_arms(xs_p, ys_p, dirs, aw0, w)
        ls = st.get("linestyle", "-")
        mk = st.get("marker", "none")
        mk_plt = "" if mk == "none" else mk
        alpha = float(st.get("alpha", 0.9))

        if name == "Trajectory":
            from matplotlib.lines import Line2D
            if "outer_bg" in allowed:
                _add_area_fill(ax, bg, arena_poly, arena_half, arena_polys)
            ax.plot(xs_p, ys_p, color=st["path_color"],
                    linewidth=st["path_width"], alpha=alpha,
                    linestyle=ls, marker=mk_plt,
                    markersize=int(st.get("marker_size", 5)),
                    solid_capstyle="round", solid_joinstyle="round", zorder=2)
            _add_arena_patch(ax, st, arena_poly, arena_half, arena_polys, zorder=4)
            _add_objects(ax, st, objects)
            psz = int(st.get("pin_size", 160))
            pcs = st.get("pin_start_color", "#23C552")
            pce = st.get("pin_end_color", "#E5484D")
            psm = st.get("pin_start_marker", "o")
            pem = st.get("pin_end_marker", "o")
            total_s = float(smp["n"] - 1) / float(smp["fps"])
            ax.scatter([xs_p[0]], [ys_p[0]], s=psz, c=pcs, marker=psm,
                       edgecolors="white", linewidths=1.5, zorder=6)
            ax.scatter([xs_p[-1]], [ys_p[-1]], s=psz, c=pce, marker=pem,
                       edgecolors="white", linewidths=1.5, zorder=6)
            # Optional 4×4 grid overlay (OF grid mode in real renderer).
            if "grid" in allowed and st.get("grid"):
                gc = st.get("grid_color", "#BBBBBB")
                ga = float(st.get("grid_alpha", 0.5))
                gls = st.get("grid_linestyle", "-")
                for i in (1, 2, 3):
                    p = -arena_half + i * (arena_half / 2.0)
                    ax.plot([p, p], [-arena_half, arena_half], color=gc,
                            linewidth=0.8, alpha=ga, linestyle=gls, zorder=3)
                    ax.plot([-arena_half, arena_half], [p, p], color=gc,
                            linewidth=0.8, alpha=ga, linestyle=gls, zorder=3)
            # User-sized center square. Size shown in legend.
            center_shown = False
            center_col = st.get("center_pct_color", "#FFFFFF")
            if "show_center_pct" in allowed and st.get("show_center_pct"):
                frac = max(0.05, min(1.0,
                    float(st.get("center_size_pct", 45)) / 100.0))
                ch = arena_half * frac
                ax.add_patch(Rectangle(
                    (-ch, -ch), 2 * ch, 2 * ch, fill=False,
                    edgecolor=center_col, linewidth=1.8, linestyle="--",
                    zorder=5))
                center_shown = True
            ax.set_xlim(-arena_half - 3, arena_half + 3)
            ax.set_ylim(arena_half + 3, -arena_half - 3)
            ax.set_aspect("equal", adjustable="box")
            handles = [
                Line2D([], [], color=st["path_color"],
                       linewidth=st["path_width"], label="Trajectory"),
            ]
            if center_shown:
                size_pct = int(st.get("center_size_pct", 45))
                handles.append(Line2D([], [], color=center_col,
                                      linestyle="--", linewidth=1.8,
                                      label=f"Center {size_pct}%"))
            handles.extend([
                Line2D([], [], marker=psm, color="w",
                       markerfacecolor=pcs, markeredgecolor="white",
                       markersize=6, markeredgewidth=1.0, label="Start"),
                Line2D([], [], marker=pem, color="w",
                       markerfacecolor=pce, markeredgecolor="white",
                       markersize=6, markeredgewidth=1.0, label="End"),
            ])
            leg = self._maybe_legend(ax, st, allowed, handles=handles)
            self._drag_artists["legend"] = leg

        elif name == "Heatmap":
            fps = smp["fps"]
            # Grid size / blur / unit / fixed max from the style — same
            # math as the Output heatmap (gui.heatmap_grid).
            from gui import heatmap_grid
            bins = heatmap_grid.bins(st)
            hm_sec, _, _, total_s = heatmap_grid.seconds_grid(
                xs_p, ys_p, [-arena_half, arena_half],
                [-arena_half, arena_half], fps, st)
            # Mask bins outside the arena shape (Y / + / square) so the
            # heatmap only paints inside the detection area — no blue
            # colormap background bleeding into the corners.
            shape_polys = _shape_polys(arena_poly, arena_polys, arena_half)
            if shape_polys:
                from matplotlib.path import Path as _MplPath
                edges = np.linspace(-arena_half, arena_half, bins + 1)
                cen = 0.5 * (edges[:-1] + edges[1:])
                gx, gy = np.meshgrid(cen, cen)        # row=y, col=x
                pts = np.column_stack([gx.ravel(), gy.ravel()])
                inside = np.zeros(pts.shape[0], dtype=bool)
                for poly in shape_polys:
                    if len(poly) >= 3:
                        inside |= _MplPath(np.asarray(poly)).contains_points(pts)
                hm_sec[~inside.reshape(gx.shape)] = np.nan
            hm_sec, max_sec = heatmap_grid.scale(hm_sec, total_s, st)
            cm_smooth = mcolors.LinearSegmentedColormap.from_list(
                "cm_smooth", cmap(np.linspace(0, 1, 256)))
            cm_smooth.set_bad((1, 1, 1, 0))
            # Fill each shape polygon with the cmap-zero color first, smoothly
            # antialiased to the exact wall. Edge bins whose centre falls just
            # outside the polygon got NaN'd above (→ transparent), so this fill
            # shows through right up to the wall — no gap and no stair-stepped
            # boundary on the angled arms.
            base_color = cm_smooth(0.0)
            for poly in shape_polys:
                if len(poly) >= 3:
                    ax.add_patch(Polygon(np.asarray(poly), closed=True,
                                         facecolor=base_color, edgecolor="none",
                                         zorder=0, antialiased=True))
            hm_img = ax.imshow(
                      hm_sec, origin="upper",
                      extent=[-arena_half, arena_half, arena_half, -arena_half],
                      cmap=cm_smooth, interpolation=heatmap_grid.interpolation(st), aspect="auto",
                      vmin=0.0, vmax=max_sec if max_sec > 0 else 1.0, zorder=1)
            # Clip the heatmap image to the exact shape outline so its square
            # bins are cut smoothly at the (angled) walls — no stair-stepping.
            clip_polys = [np.asarray(p) for p in shape_polys if len(p) >= 3]
            if clip_polys:
                from matplotlib.path import Path as _MplPath
                verts = []; codes = []
                for poly in clip_polys:
                    verts.extend(list(poly)); verts.append(poly[0])
                    codes.extend([_MplPath.MOVETO]
                                 + [_MplPath.LINETO] * (len(poly) - 1)
                                 + [_MplPath.CLOSEPOLY])
                hm_img.set_clip_path(_MplPath(verts, codes),
                                     transform=ax.transData)
            _add_arena_patch(ax, st, arena_poly, arena_half, arena_polys)
            _add_objects(ax, st, objects)
            if "grid" in allowed and st.get("grid"):
                gc = st.get("grid_color", "#BBBBBB")
                ga = float(st.get("grid_alpha", 0.5))
                gls = st.get("grid_linestyle", "-")
                for i in (1, 2, 3):
                    p = -arena_half + i * (arena_half / 2.0)
                    ax.plot([p, p], [-arena_half, arena_half], color=gc,
                            linewidth=0.8, alpha=ga, linestyle=gls)
                    ax.plot([-arena_half, arena_half], [p, p], color=gc,
                            linewidth=0.8, alpha=ga, linestyle=gls)
            ax.set_xlim(-arena_half - 3, arena_half + 3)
            ax.set_ylim(arena_half + 3, -arena_half - 3)
            ax.set_aspect("equal", adjustable="box")
            cax = self._maybe_colorbar(ax, st, allowed, cm_smooth, vmax=max_sec,
                                       labels=heatmap_grid.tick_labels(max_sec, st),
                                       label=heatmap_grid.colorbar_label(st))
            self._drag_artists["cax"] = cax

        elif name == "Cell Time":
            ct = smp["cell_times"]
            max_t = float(ct.max()) if ct.size else 1.0
            norm_ct = mcolors.Normalize(vmin=0.0, vmax=max_t if max_t > 0 else 1.0)
            cell_texts = []
            for r in range(4):
                for c in range(4):
                    cid = r * 4 + c + 1
                    t = float(ct[r * 4 + c])
                    rgba = cmap(norm_ct(t))
                    rr, gg, bb, _ = rgba
                    text_color = ("white"
                                  if (0.299 * rr + 0.587 * gg + 0.114 * bb) < 0.5
                                  else "black")
                    ax.add_patch(Rectangle((c, 3 - r), 1, 1,
                                           facecolor=rgba,
                                           edgecolor="none", linewidth=0))
                    # In preview, each cell is 1 unit wide. Production uses
                    # pixel offsets — scale roughly so a px nudge visibly
                    # moves the label here too.
                    cdx = float(st.get("cell_label_dx", 0)) / 100.0
                    cdy = float(st.get("cell_label_dy", 0)) / 100.0
                    tx = ax.text(c + 0.5 + cdx, 3 - r + 0.5 + cdy,
                                 f"{cid}\n{t:.1f}s",
                                 ha="center", va="center", color=text_color,
                                 fontsize=int(st.get("cell_label_size", 9)),
                                 fontfamily=st.get("cell_label_font") or "monospace",
                                 fontweight="bold" if st.get("cell_label_bold") else "normal",
                                 linespacing=1.1)
                    cell_texts.append(tx)
            # Lines between cells: Gridlines style when on, else plain
            # dividers in the arena colour (matches the Output graph).
            if "grid" in allowed and st.get("grid"):
                gc = st.get("grid_color", st["arena_color"])
                ga = float(st.get("grid_alpha", 1.0))
                gls = st.get("grid_linestyle", "-")
                gax = st.get("grid_axis", "both")
            else:
                gc, ga, gls, gax = st["arena_color"], 1.0, "-", "both"
            for i in (1, 2, 3):
                if gax in ("both", "x"):
                    ax.plot([i, i], [0, 4], color=gc, alpha=ga, linestyle=gls,
                            linewidth=0.8, zorder=3)
                if gax in ("both", "y"):
                    ax.plot([0, 4], [i, i], color=gc, alpha=ga, linestyle=gls,
                            linewidth=0.8, zorder=3)
            ax.add_patch(Rectangle((0, 0), 4, 4, fill=False,
                                   edgecolor=st["arena_color"],
                                   linewidth=st["arena_width"], zorder=4))
            ax.set_xlim(-0.2, 4.2); ax.set_ylim(-0.2, 4.2)
            ax.set_aspect("equal", adjustable="box")
            cax = self._maybe_colorbar(ax, st, allowed, cmap, vmax=max_t,
                                       fmt=lambda v: f"~{v:.1f}s")
            self._drag_artists["cax"] = cax
            self._drag_artists["cell_texts"] = cell_texts

        elif name == "Speed":
            fps = smp["fps"]; speeds = smp["speeds"] * sp_factor
            t = np.arange(speeds.size) / fps * t_factor
            ax.plot(t, speeds, color=st["path_color"],
                    linewidth=max(0.3, st["path_width"] * 0.4),
                    alpha=alpha * 0.7, linestyle=ls,
                    marker=mk_plt,
                    markersize=int(st.get("marker_size", 5)))
            win = max(1, int(fps))
            if speeds.size > win:
                kernel = np.ones(win) / win
                smooth = np.convolve(speeds, kernel, mode="same")
                ax.plot(t, smooth, color=st["path_color"],
                        linewidth=st["path_width"], alpha=alpha,
                        linestyle=ls, label=f"{win}-frame avg")
                self._drag_artists["legend"] = self._maybe_legend(ax, st, allowed)

        elif name == "Speed Histogram":
            speeds = smp["speeds"] * sp_factor
            p99 = float(np.quantile(speeds, 0.99))
            upper = min(float(np.max(speeds)), p99 * 1.5 + 1e-6)
            # Bar height = time at that speed (same as the Output graph).
            ax.hist(speeds, bins=60, range=(0, upper),
                    weights=np.full(len(speeds), t_factor / float(smp["fps"])),
                    color=st["path_color"],
                    edgecolor=st.get("hist_edge_color", "#222222"))
            for v, lbl, c in (
                (float(np.median(speeds)),       "median", resolve_token(ACCENT_COLORS["stat_median"], "data")),
                (float(np.quantile(speeds, .9)), "P90",    resolve_token(ACCENT_COLORS["stat_p90"], "data")),
                (p99,                            "P99",    resolve_token(ACCENT_COLORS["stat_p99"], "data")),
            ):
                ax.axvline(v, color=c, linewidth=1.5, linestyle="--",
                           label=f"{lbl}: {v:.3g} {sp_unit}")
            self._drag_artists["legend"] = self._maybe_legend(ax, st, allowed)

        elif name == "Habituation":
            # Bars per time bin + linear fit — drawn like the Output graph.
            x_v = np.asarray(smp["bin_centers_min"], float) * t_factor
            y_v = np.asarray(smp["bin_dists"], float) * d_factor
            bw = (float(np.min(np.diff(x_v))) if x_v.size > 1 else t_factor)
            ax.bar(x_v, y_v, width=bw * 0.7, color=st["path_color"],
                   alpha=alpha, label="Distance per bin")
            if 0 < x_v.size <= 12 and y_v.max() > 0:
                for xv, yv in zip(x_v, y_v):
                    ax.text(xv, yv + y_v.max() * 0.015, f"{yv:.3g}", ha="center",
                            va="bottom", fontsize=int(st.get("tick_size", 9)),
                            color=st.get("tick_color", "#333"))
            if x_v.size >= 2:
                slope, intercept = np.polyfit(x_v, y_v, 1)
                ax.plot(x_v, slope * x_v + intercept,
                        color=resolve_token(ACCENT_COLORS["linfit"], "data"),
                        linestyle=(0, (6, 3)), linewidth=1.2,
                        label=f"slope {slope:+.3g} {d_unit}/{t_unit}")
            if y_v.size and y_v.max() > 0:
                ax.set_ylim(0, y_v.max() * 1.18)
            self._drag_artists["legend"] = self._maybe_legend(ax, st, allowed)

        elif name == "Zone Time":
            zt = smp["zone_times"]
            # Per-experiment categories (EPM open/closed/center, Y-Maze arms,
            # NOR objects, OF center/periphery) — fall back to dict order.
            labels = smp.get("zone_labels") or list(zt.keys())
            colors_b = list(st.get("bar_colors") or
                            ["#1B2436", "#8A8F95", "#86672E", "#B3382E"])
            while len(colors_b) < len(labels):
                colors_b.append("#888888")
            times = [zt.get(k, 0.0) * t_factor for k in labels]
            bars = ax.bar(labels, times, color=colors_b[:len(labels)], width=0.5)
            tc = st.get("tick_color", "#333333")
            top = max(times) if times else 0.0
            for b, t in zip(bars, times):
                if t > 0:
                    ax.text(b.get_x() + b.get_width() / 2,
                            b.get_height() + top * 0.02,
                            f"{t:.1f}s" if t_unit == "s" else f"{t:.2f} min",
                            ha="center", color=tc,
                            fontsize=int(st.get("tick_size", 9)))

        # Common cosmetics.
        self._apply_axes_style(ax, st, allowed)
        self._apply_text_style(ax, st, allowed)
        # Fixed margins instead of tight_layout — tight_layout reflows the
        # main axes every time the legend/colorbar/title moves, which made
        # the whole figure "wander" during drag. With explicit margins the
        # axes stays put and only the artist the user is moving moves.
        # When _maybe_colorbar already set its own subplots_adjust we
        # leave it alone (cbar margins are different from no-cbar).
        if self._drag_artists.get("cax") is None:
            try:
                self._fig.subplots_adjust(
                    left=0.10, right=0.96, top=0.92, bottom=0.10,
                )
            except Exception:
                pass
        # Title is set by _apply_text_style above; pick it up after so the
        # drag handler hits the real Text artist (only if a title is shown).
        if ax.title.get_text():
            self._drag_artists["title"] = ax.title
        self._setup_drag_handlers(ax)
        self._canvas.draw_idle()

    def _maybe_colorbar(self, ax, st, allowed, cmap, vmax=None, fmt=None,
                        labels=None, label=None):
        """`labels` = [left, right] tick texts (overrides fmt); `label` =
        colour-bar title (defaults to the style's colorbar_label)."""
        if "colorbar_show" not in allowed or not st.get("colorbar_show", True):
            return None
        try:
            from matplotlib import colors as mcolors
            if vmax is not None and vmax > 0:
                norm = mcolors.Normalize(vmin=0.0, vmax=vmax)
                sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
            else:
                sm = plt.cm.ScalarMappable(cmap=cmap)
            sm.set_array([])
            bx = 0.06 + float(st.get("colorbar_x", 0.0))
            by = 0.06 + float(st.get("colorbar_y", 0.0))
            bw = max(0.05, 0.88 + float(st.get("colorbar_w", 0.0)))
            bh = max(0.005, 0.04 + float(st.get("colorbar_h", 0.0)))
            cb_rect = [bx, by, bw, bh]
            cax = self._fig.add_axes(cb_rect)
            cbar = self._fig.colorbar(sm, cax=cax, orientation="horizontal")
            if vmax is not None and vmax > 0 and (fmt is not None or labels):
                cbar.set_ticks([0.0, vmax])
                cbar.set_ticklabels(labels or ["0s", fmt(vmax)])
                cbar.ax.tick_params(labelsize=10, length=0)
            else:
                cbar.set_ticks([])
            if label is None:
                label = st.get("colorbar_label") or ""
            if label:
                cbar.set_label(label, fontsize=int(st.get("tick_size", 9)),
                               color=st.get("tick_color", "#333333"))
            cbar.outline.set_visible(False)
            # Fixed margin: moving the colour bar must not resize the plot.
            bot_margin = 0.14
            self._fig.subplots_adjust(top=0.96, bottom=bot_margin, left=0.04, right=0.96)
            return cax
        except Exception:
            return None

    # ── Drag-to-edit layout artists ──────────────────────────────────────
    def _teardown_drag_handlers(self):
        """Detach mpl event handlers from the previous render. Called at
        the top of _refresh_preview before any new artist is drawn."""
        for cid in getattr(self, "_drag_cids", []):
            try:
                self._canvas.mpl_disconnect(cid)
            except Exception:
                pass
        self._drag_cids = []
        self._drag_state = {"kind": None}

    def _setup_drag_handlers(self, ax):
        """Hook button_press / motion / button_release on the canvas so
        the user can drag the legend, title, colorbar, or cell labels
        directly. On release, the corresponding Layout spinbox value is
        updated — which in turn rerenders the preview through _commit."""
        cv = self._canvas
        fig = self._fig
        state = self._drag_state
        artists = self._drag_artists

        def _hit_legend(ev):
            leg = artists.get("legend")
            if leg is None:
                return False
            try:
                hit, _ = leg.contains(ev)
            except Exception:
                return False
            return hit

        def _hit_title(ev):
            t = artists.get("title")
            if t is None or not t.get_text():
                return False
            try:
                hit, _ = t.contains(ev)
            except Exception:
                return False
            return hit

        def _hit_cell(ev):
            for tx in artists.get("cell_texts") or []:
                try:
                    hit, _ = tx.contains(ev)
                except Exception:
                    continue
                if hit:
                    return tx
            return None

        def _hit_cax(ev):
            cax = artists.get("cax")
            return cax is not None and ev.inaxes is cax

        def press(ev):
            if ev.button != 1 or ev.x is None:
                return
            # Legend first (sits on top of everything).
            if _hit_legend(ev):
                leg = artists["legend"]
                inv = ax.transAxes.inverted()
                bbox = leg.get_window_extent()
                # Drag always commits the legend into "custom" mode — the
                # lower-left of the legend in axes fraction is the truth.
                x0_ax, y0_ax = inv.transform((bbox.x0, bbox.y0))
                try:
                    leg.set_loc("lower left")
                except Exception:
                    try:
                        leg._loc = 3
                    except Exception:
                        pass
                leg.set_bbox_to_anchor((float(x0_ax), float(y0_ax)),
                                       transform=ax.transAxes)
                state["kind"] = "legend"
                state["anchor"] = (float(x0_ax), float(y0_ax))
                state["press"] = inv.transform((ev.x, ev.y))
                state["last_xy"] = state["anchor"]
                return
            if _hit_title(ev):
                t = artists["title"]
                state["kind"] = "title"
                state["press_pix_y"] = ev.y
                state["title_y_initial"] = t.get_position()[1]
                state["initial_pad"] = float(
                    self._cfg.get_for(self._current_plugin_key,
                                      self._current).get("title_pad", 0.0)
                )
                return
            cell = _hit_cell(ev)
            if cell is not None:
                state["kind"] = "cell"
                state["cell_press_data"] = (ev.xdata, ev.ydata)
                state["cell_anchors"] = [
                    tx.get_position() for tx in artists["cell_texts"]
                ]
                state["initial_dx"] = float(
                    self._cfg.get_for(self._current_plugin_key,
                                      self._current).get("cell_label_dx", 0.0)
                )
                state["initial_dy"] = float(
                    self._cfg.get_for(self._current_plugin_key,
                                      self._current).get("cell_label_dy", 0.0)
                )
                return
            if _hit_cax(ev):
                cax = artists["cax"]
                pos = cax.get_position()
                inv = fig.transFigure.inverted()
                state["kind"] = "cax"
                state["anchor"] = (pos.x0, pos.y0, pos.width, pos.height)
                state["press"] = inv.transform((ev.x, ev.y))
                return

        def motion(ev):
            kind = state.get("kind")
            if kind is None or ev.x is None:
                return
            if kind == "legend":
                leg = artists["legend"]
                inv = ax.transAxes.inverted()
                now = inv.transform((ev.x, ev.y))
                ddx = now[0] - state["press"][0]
                ddy = now[1] - state["press"][1]
                ax_x = max(0.0, min(1.0, state["anchor"][0] + ddx))
                ax_y = max(0.0, min(1.0, state["anchor"][1] + ddy))
                leg.set_bbox_to_anchor((ax_x, ax_y), transform=ax.transAxes)
                state["last_xy"] = (ax_x, ax_y)
            elif kind == "title":
                t = artists["title"]
                ax_h_pix = ax.get_position().height * fig.bbox.height
                if ax_h_pix <= 0:
                    return
                dy_pix = state["press_pix_y"] - ev.y   # mouse up → positive
                new_y = state["title_y_initial"] + dy_pix / ax_h_pix
                # Clamp the visible position AND derive live_pad from the
                # clamped y, so the spinbox value matches what the user
                # sees (otherwise release jumps to the unclamped pad).
                clamped_y = max(1.0, min(1.6, new_y))
                t.set_y(clamped_y)
                ax_h_pt = ax_h_pix * 72.0 / fig.dpi
                state["live_pad"] = (clamped_y - 1.0) * ax_h_pt - 6.0
            elif kind == "cell":
                if ev.xdata is None or ev.ydata is None:
                    return
                ddx = ev.xdata - state["cell_press_data"][0]
                ddy = ev.ydata - state["cell_press_data"][1]
                for tx, (ax0, ay0) in zip(artists["cell_texts"],
                                          state["cell_anchors"]):
                    tx.set_position((ax0 + ddx, ay0 + ddy))
                # Preview cells span 1 unit each; production uses px
                # offsets and the preview rescales by /100, so multiply by
                # 100 to round-trip.
                state["live_dx"] = state["initial_dx"] + ddx * 100.0
                state["live_dy"] = state["initial_dy"] + ddy * 100.0
            elif kind == "cax":
                cax = artists["cax"]
                inv = fig.transFigure.inverted()
                now = inv.transform((ev.x, ev.y))
                dx = now[0] - state["press"][0]
                dy = now[1] - state["press"][1]
                x0, y0, w, h = state["anchor"]
                # Clamp so the colorbar stays inside the figure.
                new_x = max(0.0, min(1.0 - w, x0 + dx))
                new_y = max(0.0, min(1.0 - h, y0 + dy))
                cax.set_position([new_x, new_y, w, h])
                state["last_xy"] = (new_x, new_y)
            cv.draw_idle()

        def release(ev):
            kind = state.get("kind")
            if kind is None:
                return
            try:
                if kind == "legend":
                    # Use the anchor we set during motion, not the
                    # canvas's window_extent (it can lag behind redraws).
                    ax_x, ax_y = state.get("last_xy", state["anchor"])
                    # Drag commits to "custom" mode so the dropdown shows
                    # the user that the offsets are now driving placement.
                    self._set_editor("legend_loc", "custom")
                    self._set_editor("legend_x_offset", round(float(ax_x), 4))
                    self._set_editor("legend_y_offset", round(float(ax_y), 4))
                elif kind == "title":
                    self._set_editor("title_pad",
                                     round(float(state.get("live_pad", 0.0)), 1))
                elif kind == "cell":
                    self._set_editor("cell_label_dx",
                                     int(round(state.get("live_dx", 0.0))))
                    self._set_editor("cell_label_dy",
                                     int(round(state.get("live_dy", 0.0))))
                elif kind == "cax":
                    new_x, new_y = state.get("last_xy",
                                             (state["anchor"][0],
                                              state["anchor"][1]))
                    self._set_editor("colorbar_x", round(new_x - 0.06, 4))
                    self._set_editor("colorbar_y", round(new_y - 0.06, 4))
            finally:
                state["kind"] = None

        self._drag_cids = [
            cv.mpl_connect("button_press_event", press),
            cv.mpl_connect("motion_notify_event", motion),
            cv.mpl_connect("button_release_event", release),
        ]

    def _set_editor(self, field, value):
        """Programmatically set the dialog editor for `field` to `value`.
        Routes to the right widget API (spinbox / combobox); the change
        signal then fires _commit, which writes the new value to the
        active style and (in live mode) triggers a preview rerender."""
        sp = self._editors.get(field)
        if sp is None:
            return
        try:
            if hasattr(sp, "setValue"):
                sp.setValue(value)
            elif hasattr(sp, "setCurrentText"):
                idx = sp.findText(str(value))
                if idx >= 0:
                    sp.setCurrentIndex(idx)
                else:
                    sp.setCurrentText(str(value))
        except Exception:
            pass

    # ── live preview / apply / accept ────────────────────────────────────
    def _on_live_toggle(self, on):
        self._live = bool(on)
        self.btn_apply.setEnabled(not self._live)
        if self._live and self._rerender:
            try:
                self._rerender(None)
            except Exception:
                pass

    def _apply(self):
        if self._rerender:
            try:
                self._rerender(None)
            except Exception:
                pass

    def _accept(self):
        self._preview_timer.stop()
        self._rerender_timer.stop()
        if self._rerender:
            try:
                self._rerender(None)
            except Exception:
                pass
        self._close_fig()
        self.accept()

    def reject(self):
        """Restore backup → rerender → close figure → super reject.
        Called by Cancel button, X-button (Qt default), and Esc key.

        Only the *active* per-graph styles are rolled back. Custom presets
        are a separate commitment (Save As / Delete persist immediately),
        so cancelling style edits must not wipe them."""
        if not getattr(self, "_closing", False):
            self._closing = True
            try:
                restored = GraphStyleConfig.from_dict(self._backup)
                # Restore every plugin's bucket — edits in any of the
                # plugin tabs were live mutations on self._cfg and need
                # rolling back on Cancel.
                self._cfg.plugins = restored.plugins
                # custom_presets intentionally NOT restored — Save As /
                # Delete are durable from the moment they happen.
                if self._rerender:
                    try:
                        self._rerender(None)
                    except Exception:
                        pass
            finally:
                self._close_fig()
        super().reject()

    def _close_fig(self):
        try:
            plt.close(self._fig)
        except Exception:
            pass
