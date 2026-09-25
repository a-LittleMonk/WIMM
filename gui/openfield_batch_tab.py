"""OpenFieldBatchTab — thin OF-flavored subclass of ExperimentBatchTab.

The shared / generic batch shell (queue runner, video list, trim/crop,
result cards, Apply-To dialog, combined-Excel export, annotated-video
render) lives in gui/experiment_batch_tab.py.

Re-exports module-level helpers (status codes, dialog classes, video-row
classes) so historical importers keep working.
"""
from gui.experiment_batch_tab import (
    ExperimentBatchTab,
    # Status / styling
    STATUS_NEEDS, STATUS_READY, STATUS_RUNNING, STATUS_DONE, STATUS_ERROR,
    STATUS_ICONS,
    APPLY_FIELD_GROUPS, APPLY_DEFAULTS_ON,
    VIDEO_EXTS,
    # Dialog / widget classes (not user-public but referenced by tests / imports).
    ElidingLabel, _RangeSlider, _CropFrameLabel, TrimCropDialog,
    ApplyToDialog, _Spinner, VideoRow, ResultCard, ExcelPreviewDialog,
)
from gui.open_field_tab import OpenFieldTab


class OpenFieldBatchTab(ExperimentBatchTab):
    """Open-Field-flavored batch tab. Pins embedded_tab_class to OpenFieldTab."""
    embedded_tab_class = OpenFieldTab
