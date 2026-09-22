"""OF metrics — thin wrapper over analysis.open_field.compute_metrics."""
from analysis.open_field import compute_metrics as _of_compute


def compute(results, settings, fps, px_per_cm):
    """Plugin-style entry. settings: dict with arena, center_zone, zone_mode,
    movement_threshold, bin_size_s, pause_min_dur_s, thigmotaxis_band_cm,
    cell_min_dwell_s. Legacy key 'center' still accepted."""
    return _of_compute(
        results,
        arena=settings.get("arena"),
        center_zone=settings.get("center_zone", settings.get("center")),
        px_per_cm=px_per_cm,
        fps=fps,
        movement_threshold=settings.get("movement_threshold", 0.0),
        bin_size_s=settings.get("bin_size_s", 0.0),
        zone_mode=settings.get("zone_mode", "center_zone"),
        pause_min_dur_s=settings.get("pause_min_dur_s", 1.0),
        thigmotaxis_band_cm=settings.get("thigmotaxis_band_cm", 2.0),
        cell_min_dwell_s=settings.get("cell_min_dwell_s", 0.2),
        trim_start_s=settings.get("trim_start_s", 0.0),
    )


# Order of summary columns for batch Excel export.
EXPORT_COLUMNS = [
    "Animal ID", "Group", "Sex", "Date", "Trial",
    "duration_s", "total_distance_cm", "mean_speed_cmps",
    "max_speed_cmps", "time_in_center_zone_s", "time_in_periphery_s",
    "center_zone_entries", "center_cells_time_s", "center_cells_entries",
    "thigmotaxis_pct", "pause_count", "pause_total_s", "Notes",
]


# Combined-export master-sheet schema. Drives the "All Animals" sheet
# layout in export.excel_export.export_combined:
#   Row 1 = section headers (sparse — only the first cell of each
#           section group is labelled)
#   Row 2 = column titles
#   Row 3+ = one row per video
#
# Order is canonical (matches compute_metrics output order). Missing
# metrics for a particular video render as blank cells; metrics not in
# the schema are silently dropped from the master sheet (per-video
# Summary sheet still shows everything).
def _cell_columns():
    """Interleaved per-cell columns: Cell 1 Time, Cell 1 Entries,
    Cell 2 Time, Cell 2 Entries, … Cell 16 Entries. Easier to read
    side-by-side than all-Times-then-all-Entries."""
    out = []
    for cid in range(1, 17):
        out.append(f"Cell {cid} Time (s)")
        out.append(f"Cell {cid} Entries (#)")
    return out


BATCH_SCHEMA = [
    ("Experiment Metadata", [
        "Video", "Animal ID", "Group", "Sex", "Date", "Trial", "Notes",
    ]),
    ("Recording / Tracking Quality", [
        "Duration (s)", "Total Frames", "Frames Detected", "Detection Rate (%)",
    ]),
    ("Global Locomotion", [
        "Total Distance (cm)",
        "Average Speed (cm/s)", "Median Speed (cm/s)", "Max Speed (cm/s)",
        "P90 Speed (cm/s)", "P99 Speed (cm/s)",
    ]),
    ("Mobility / Immobility", [
        "Movement Threshold (cm/s)",
        "Mobility Time (s)", "Immobility Time (s)",
        "Mean Speed When Mobile (cm/s)",
    ]),
    ("Advanced Path", [
        "Tortuosity",
    ]),
    ("Center vs Periphery", [
        "Time in Center Zone (s)", "Time in Periphery (s)",
        "% Time in Center Zone", "% Time in Periphery",
        "Center Zone Entries (#)",
        "Latency to First Center Zone Entry (s)",
        "Mean Center Zone Dwell (s)", "Longest Center Zone Dwell (s)",
        "Mean Inter-Entry Interval (s)",
    ]),
    ("Thigmotaxis", [
        "Thigmotaxis Band", "Thigmotaxis Time (s)", "Thigmotaxis %",
    ]),
    ("Pauses / Freezing", [
        "Pause Threshold (cm/s)", "Min Pause Duration (s)",
        "Pause Count (#)",
        "Mean Pause Duration (s)", "Longest Pause (s)",
        "Total Time in Pauses (s)",
    ]),
    ("Spatial Grid / Region Aggregates", [
        # Region aggregates first, then per-cell. Pairs are kept even
        # so the per-animal sheet's "2 pairs per row" layout puts each
        # cell's Time + Entries on the same row instead of staggering
        # them. Min-Dwell sits last (it's a single non-paired column
        # so it must come after the paired blocks).
        "Corner Cells Time (s)", "Corner Cells Entries (#)",
        "Center Cells Time (s)", "Center Cells Entries (#)",
        "Side Cells Time (s)",   "Side Cells Entries (#)",
    ] + _cell_columns() + [
        "Cell Entry Min-Dwell (s)",
    ]),
    ("Habituation", [
        "Habituation Slope (cm/min)",
        "First-Bin Distance (cm)", "Last-Bin Distance (cm)",
        "Habituation Last/First (%)",
    ]),
]
