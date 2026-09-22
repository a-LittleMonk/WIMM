"""OutputTabsMixin — Output panel population (Summary, Raw Data, Video
Config tables + the small _on_graph_select dispatch).

Mixed into ExperimentTab. Doesn't BUILD the tab widgets (those are still
built inline in _build_excel_tab so the tab order + lazy creation stays
co-located with the rest of _build_ui). It only POPULATES them from
self.metrics / self.raw_df after each tracking run or recompute.

Reuses host attrs / methods:
    self.metrics, self.raw_df, self.experiment, self.video_w, self.video_h,
    self._table_summary, self._table_raw, self._table_video_config,
    self.lbl_summary_placeholder, self.lbl_raw_placeholder, self.lbl_excel_note,
    self.lbl_excel_hint, self._excel_tabs, self._combo_graph,
    self._graph_pixmaps, self._graph_lbl, self.snapshot_settings,
    self._refresh_cell_aggregation.
"""
from PyQt5.QtWidgets import QTableWidgetItem

from core import logger


class OutputTabsMixin:
    def _on_graph_select(self, index):
        name = self._combo_graph.itemText(index)
        pix = self._graph_pixmaps.get(name)
        if pix:
            self._graph_lbl.setPixmap(pix)

    def _refresh_raw_data_columns(self, col_names):
        """Surgically rewrite the given columns in the Raw Data table from
        the current raw_df. Skips columns that aren't currently shown
        (e.g. 'Cell' when not in OF grid mode) and skips silently if the
        table hasn't been built yet."""
        if not hasattr(self, "_table_raw") or self.raw_df is None:
            return
        df = self.raw_df.head(5000)
        # Map header → column index in the table.
        headers = {self._table_raw.horizontalHeaderItem(c).text(): c
                   for c in range(self._table_raw.columnCount())
                   if self._table_raw.horizontalHeaderItem(c) is not None}
        targets = [(name, headers[name]) for name in col_names
                   if name in headers and name in df.columns]
        if not targets:
            return
        self._table_raw.setUpdatesEnabled(False)
        self._table_raw.setSortingEnabled(False)
        try:
            for name, c in targets:
                series = df[name].values
                for r, val in enumerate(series):
                    try:
                        text = ("" if val != val
                                else (f"{val:.3f}" if isinstance(val, float)
                                      else str(val)))
                    except Exception:
                        text = str(val)
                    self._table_raw.setItem(r, c, QTableWidgetItem(text))
        finally:
            self._table_raw.setUpdatesEnabled(True)

    def _refresh_summary_table(self):
        """Fast refill of the Summary metrics table + cell aggregation +
        Video Config table. Doesn't touch Raw Data (slow). Used by every
        selective recompute path (Move threshold / Time bin / Cell min
        dwell / Arena edits) so all post-track-adjustable settings stay in
        sync across the Output panel."""
        metrics = self.metrics or {}
        if hasattr(self, "lbl_summary_placeholder"):
            self.lbl_summary_placeholder.setVisible(False)
            self._table_summary.setVisible(True)
        # Plugin picks the ordered subset of metric keys for the Summary
        # table. None → fall back to dict-iteration order (every key).
        exp = getattr(self, "experiment", None)
        keys = exp.summary_table_keys(metrics) if exp is not None else None
        if keys is not None:
            # Render every key from the plugin's ordered list. Missing
            # keys still get a row so the layout is stable across runs;
            # the value shows as "None" so the user can see what wasn't
            # computed instead of the row silently disappearing.
            rows = [(k, metrics.get(k)) for k in keys]
        else:
            rows = list(metrics.items())
        self._table_summary.setUpdatesEnabled(False)
        self._table_summary.setSortingEnabled(False)
        try:
            self._table_summary.setRowCount(len(rows))
            for row, (k, v) in enumerate(rows):
                self._table_summary.setItem(row, 0, QTableWidgetItem(str(k)))
                self._table_summary.setItem(row, 1, QTableWidgetItem(str(v)))
        finally:
            self._table_summary.setUpdatesEnabled(True)
        try:
            self._refresh_cell_aggregation()
        except Exception as e:
            logger.warn(f"refresh_cell_aggregation failed: {e}", source="ui")
        # Let the experiment plugin fill any custom results tab it built
        # (Y-Maze table, future experiments, etc.) from the same metrics dict.
        exp = getattr(self, "experiment", None)
        if exp is not None:
            try:
                exp.populate_results_tab(self, metrics)
            except Exception as e:
                logger.warn(f"populate_results_tab failed "
                            f"({getattr(exp, 'key', '?')}): {e}",
                            source="plugin")
        # Video Config table reads snapshot_settings() which always reflects
        # current widget values — refresh it here so e.g. Cell min dwell /
        # Move threshold updates show in the Output → Video Config tab
        # without waiting for a full recompute.
        try:
            self._populate_video_config_table()
        except Exception as e:
            logger.warn(f"populate_video_config_table failed: {e}",
                        source="ui")

    def _populate_excel_tab(self):
        # Hide placeholders, show real tables.
        if hasattr(self, "lbl_raw_placeholder"):
            self.lbl_raw_placeholder.setVisible(False)
            self._table_raw.setVisible(True)
        # Summary + cell aggregation + Video Config — all in the helper.
        self._refresh_summary_table()

        df = self.raw_df
        display = df.head(5000)
        cols = list(display.columns)
        self._table_raw.setUpdatesEnabled(False)
        self._table_raw.setSortingEnabled(False)
        try:
            self._table_raw.setRowCount(len(display))
            self._table_raw.setColumnCount(len(cols))
            self._table_raw.setHorizontalHeaderLabels(cols)
            # Cache iloc rows once — repeated .iloc[r] inside the loop is slow.
            rows = display.itertuples(index=False, name=None)
            for r, row in enumerate(rows):
                for c, val in enumerate(row):
                    try:
                        text = "" if val != val else (f"{val:.3f}" if isinstance(val, float) else str(val))
                    except Exception:
                        text = str(val)
                    self._table_raw.setItem(r, c, QTableWidgetItem(text))
        finally:
            self._table_raw.setUpdatesEnabled(True)
        if len(df) > 5000:
            self.lbl_excel_note.setText(
                f"Showing first 5000 of {len(df)} frames. Export Excel for full data."
            )
            self.lbl_excel_note.setVisible(True)
        else:
            self.lbl_excel_note.setVisible(False)

        self._excel_tabs.setVisible(True)
        self.lbl_excel_hint.setVisible(False)

    def _populate_video_config_table(self):
        """Fill the Output → Video Config tab from current settings snapshot."""
        if not hasattr(self, "_table_video_config"):
            return
        try:
            from export.excel_export import _video_config_rows
        except Exception as e:
            logger.warn(f"_video_config_rows import failed: {e}", source="ui")
            return
        try:
            settings = self.snapshot_settings()
        except Exception as e:
            logger.warn(f"snapshot_settings for video config failed: {e}",
                        source="ui")
            return
        vw = getattr(self, "video_w", 0)
        vh = getattr(self, "video_h", 0)
        rows = _video_config_rows(settings, (vw, vh) if vw and vh else None)
        t = self._table_video_config
        t.setUpdatesEnabled(False)
        t.setSortingEnabled(False)
        try:
            t.setRowCount(len(rows))
            for r, (label, value) in enumerate(rows):
                t.setItem(r, 0, QTableWidgetItem(str(label)))
                t.setItem(r, 1, QTableWidgetItem("" if value is None else str(value)))
        finally:
            t.setUpdatesEnabled(True)
