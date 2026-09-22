"""Unit tests for the combined-export master-sheet writer.

Covers the schema-driven path (row 1 sparse section headers, row 2
column titles, row 3+ data) and the legacy fallback (single header
row, first-seen metric order).
"""
import os
import tempfile

import pytest
from openpyxl import load_workbook

from export.excel_export import export_combined


SCHEMA = [
    ("Experiment Metadata", ["Video", "Animal ID", "Group"]),
    ("Locomotion", ["Total Distance (cm)", "Average Speed (cm/s)"]),
    ("Region", ["Center Cells Time (s)", "Corner Cells Time (s)"]),
]


def _animals():
    return [
        {
            "animal_id": "A1",
            "metadata":  {"Animal ID": "A1", "Group": "Ctrl"},
            "metrics":   {
                "Total Distance (cm)": 120.5,
                "Average Speed (cm/s)": 4.02,
                "Center Cells Time (s)": 30.0,
                "Corner Cells Time (s)": 12.4,
            },
            "bin_df":    None,
            "graph_pngs": {},
        },
        {
            "animal_id": "A2",
            "metadata":  {"Animal ID": "A2", "Group": "Drug"},
            "metrics":   {
                "Total Distance (cm)": 88.1,
                # missing Average Speed deliberately
                "Center Cells Time (s)": 15.2,
                "Corner Cells Time (s)": 9.0,
            },
            "bin_df":    None,
            "graph_pngs": {},
        },
    ]


def test_combined_export_schema_layout():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "combined.xlsx")
        export_combined(out, _animals(), schema=SCHEMA)
        wb = load_workbook(out)
        assert "All Animals" in wb.sheetnames
        ws = wb["All Animals"]

        # Row 1: section headers in the first cell of each section.
        # Cells 1, 4, 6 are the section starts (sections of width 3/2/2).
        assert ws.cell(row=1, column=1).value == "Experiment Metadata"
        assert ws.cell(row=1, column=4).value == "Locomotion"
        assert ws.cell(row=1, column=6).value == "Region"

        # Row 2: column titles in the canonical order.
        assert ws.cell(row=2, column=1).value == "Video"
        assert ws.cell(row=2, column=2).value == "Animal ID"
        assert ws.cell(row=2, column=4).value == "Total Distance (cm)"
        assert ws.cell(row=2, column=7).value == "Corner Cells Time (s)"

        # Row 3+: data. Video = animal_id; missing metric = blank.
        assert ws.cell(row=3, column=1).value == "A1"
        assert ws.cell(row=3, column=2).value == "A1"
        assert ws.cell(row=3, column=3).value == "Ctrl"
        assert ws.cell(row=3, column=4).value == 120.5
        assert ws.cell(row=4, column=4).value == 88.1
        # openpyxl reads back blank cells as None.
        assert ws.cell(row=4, column=5).value in (None, "")

        # Freeze pane locks rows 1+2 in place.
        assert ws.freeze_panes == "A3"


def test_per_animal_cell_time_and_entries_share_row():
    """Cell N Time and Cell N Entries must land on the same row in the
    per-animal sheet (cols 1-2 vs 3-4), so a reader can read time and
    entries for the same cell horizontally."""
    # Build a synthetic animal whose schema includes paired cell columns.
    grid_pairs = []
    for cid in (1, 2, 3):
        grid_pairs.append(f"Cell {cid} Time (s)")
        grid_pairs.append(f"Cell {cid} Entries (#)")
    grid_schema = [
        ("Experiment Metadata", ["Video", "Animal ID"]),
        ("Spatial Grid", grid_pairs),
    ]
    animals = [{
        "animal_id": "A1",
        "metadata":  {"Animal ID": "A1"},
        "metrics":   {
            "Cell 1 Time (s)": 10.0, "Cell 1 Entries (#)": 3,
            "Cell 2 Time (s)": 20.0, "Cell 2 Entries (#)": 5,
            "Cell 3 Time (s)": 30.0, "Cell 3 Entries (#)": 7,
        },
        "bin_df": None, "graph_pngs": {},
    }]
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "combined_align.xlsx")
        export_combined(out, animals, schema=grid_schema)
        ws = load_workbook(out)["A1"]

        # Walk the sheet, find each Cell N Time label, and confirm
        # Cell N Entries is on the SAME row in col 3.
        for r in range(1, ws.max_row + 1):
            lbl = ws.cell(row=r, column=1).value
            if isinstance(lbl, str) and lbl.startswith("Cell ") and "Time" in lbl:
                cid = lbl.split()[1]
                pair = ws.cell(row=r, column=3).value
                assert pair == f"Cell {cid} Entries (#)", (
                    f"Cell {cid} Time/Entries split across rows: "
                    f"row {r} col 3 = {pair!r}"
                )


def test_per_animal_metrics_use_schema_sections():
    """When a schema is passed, the per-animal sheet's METRICS block
    is replaced by one mini-table per schema section."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "combined_sections.xlsx")
        export_combined(out, _animals(), schema=SCHEMA)
        wb = load_workbook(out)
        # Per-animal sheet name comes from animal_id.
        ws = wb["A1"]
        # Gather first-column banner labels (section headers go in col A).
        col_a_values = [
            ws.cell(row=r, column=1).value
            for r in range(1, ws.max_row + 1)
        ]
        # METADATA banner still present (built outside the schema loop).
        assert "METADATA" in col_a_values
        # Schema sections show up as banners (Experiment Metadata is
        # intentionally skipped — handled by METADATA above).
        assert "Locomotion" in col_a_values
        assert "Region" in col_a_values
        assert "Experiment Metadata" not in col_a_values


def test_value_cells_are_center_aligned_text_and_numeric():
    """All value cells — numeric and text — should land centered. The
    only cells that stay left-aligned are bold labels and section
    banners (which sit in fixed-position columns, not value columns)."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "combined_align.xlsx")
        export_combined(out, _animals(), schema=SCHEMA)
        ws = load_workbook(out)["All Animals"]

        # Numeric value (Total Distance, col 4 row 3).
        num = ws.cell(row=3, column=4)
        assert isinstance(num.value, (int, float))
        assert num.alignment.horizontal == "center"

        # Text value (Group "Ctrl", col 3 row 3) — also centered now.
        txt = ws.cell(row=3, column=3)
        assert isinstance(txt.value, str)
        assert txt.alignment.horizontal == "center"


def test_combined_export_legacy_layout_when_no_schema():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "combined_legacy.xlsx")
        export_combined(out, _animals(), schema=None)
        ws = load_workbook(out)["All Animals"]

        # Legacy mode: single header row (no section headers).
        # Row 1 holds the column titles.
        assert ws.cell(row=1, column=1).value == "Video"
        # First metric column is Total Distance (first-seen).
        # Data starts at row 2.
        assert ws.cell(row=2, column=1).value == "A1"
