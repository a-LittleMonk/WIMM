"""Output tab: every sub-tab button opens the page with its own name, also
in experiments that add their results tab (Y-Maze, EPM, NOR, box tests)
after the button strip was built."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication  # noqa: E402

from experiments import registry  # noqa: E402

APP = QApplication.instance() or QApplication([])


@pytest.mark.parametrize("key", ["y_maze", "epm", "nor", "nol"])
def test_summary_shows_readable_names(key):
    """Y-Maze / EPM / NOR keep internal names (total_distance); the Summary
    tab must show the Excel names, and none of them under 'Center zone'."""
    tab = registry.tab_class(key, "tab")({})
    tab.metrics = {"duration_s": 30.0, "total_distance": 452.59, "mean_speed": 15.1,
                   "unit": "cm", "min_dwell_s": 0.0, "latency_first_entry_s": 0.0,
                   "total_entries": 10, "pause_mean_s": 2.5}
    tab._refresh_summary_table()
    tb = tab._table_summary
    labels = [tb.item(r, 0).text() for r in range(tb.rowCount()) if tb.item(r, 0)]
    assert not [t for t in labels if "_" in t], labels
    assert "Total Distance" in labels
    rec = labels.index("RECORDING")
    nxt = next(i for i in range(rec + 1, len(labels)) if labels[i] == labels[i].upper())
    assert not [t for t in labels[rec + 1:nxt] if "pause" in t.lower()]   # pauses have their own heading
    if "CENTER ZONE" in labels:                     # EPM has a real centre square
        i = labels.index("CENTER ZONE") + 1
        under = []
        while i < len(labels) and labels[i] != labels[i].upper():
            under.append(labels[i])
            i += 1
        assert all("center" in t.lower() for t in under), under


@pytest.mark.parametrize("key", registry.KEYS)
def test_output_panels_use_the_full_width(key):
    """No width cap on Summary / Graphs / Video config: a cap left a large
    empty strip on the right of wide windows."""
    tab = registry.tab_class(key, "tab")({})
    page = tab._excel_tabs.parentWidget()
    page.setParent(None)
    page.resize(1800, 900)
    for i in range(tab._excel_tabs.count()):
        tab._excel_tabs.setCurrentIndex(i)
        content = tab._excel_tabs.widget(i)
        assert content.maximumWidth() >= 16777215
    assert tab._summary_panel.maximumWidth() >= 16777215
    assert tab._graph_scroll.maximumWidth() >= 16777215


@pytest.mark.parametrize("key", registry.KEYS)
def test_each_button_opens_its_own_tab(key):
    tab = registry.tab_class(key, "tab")({})
    tabs, btns = tab._excel_tabs, tab._out_header._btns
    assert [b.text() for b in btns] == [tabs.tabText(i) for i in range(tabs.count())]
    for i, b in enumerate(btns):
        b.click()
        assert tabs.tabText(tabs.currentIndex()) == b.text()
        assert [x.isChecked() for x in btns] == [j == i for j in range(len(btns))]
