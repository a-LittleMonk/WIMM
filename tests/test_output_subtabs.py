"""Output tab: every sub-tab button opens the page with its own name, also
in experiments that add their results tab (Y-Maze, EPM, NOR, box tests)
after the button strip was built."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication  # noqa: E402

from experiments import registry  # noqa: E402

APP = QApplication.instance() or QApplication([])


@pytest.mark.parametrize("key", registry.KEYS)
def test_each_button_opens_its_own_tab(key):
    tab = registry.tab_class(key, "tab")({})
    tabs, btns = tab._excel_tabs, tab._out_header._btns
    assert [b.text() for b in btns] == [tabs.tabText(i) for i in range(tabs.count())]
    for i, b in enumerate(btns):
        b.click()
        assert tabs.tabText(tabs.currentIndex()) == b.text()
        assert [x.isChecked() for x in btns] == [j == i for j in range(len(btns))]
