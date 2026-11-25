"""App defaults that change measured numbers."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication  # noqa: E402

from experiments import registry  # noqa: E402

APP = QApplication.instance() or QApplication([])


def test_tracking_smoothing_defaults_to_3_frames():
    """Unsmoothed tracks made distance / speed 5-9 % too high on the
    benchmark videos and split long pauses; 3 frames is the tracker's own
    default. Holds for a new video and for a saved one without the value."""
    tab = registry.tab_class("open_field", "tab")({})
    assert tab.snapshot_settings()["smooth_window"] == 3
    tab.spin_smooth_window.setValue(1)
    tab.apply_settings({})
    assert tab.spin_smooth_window.value() == 3
