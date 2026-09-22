"""Output-tab mixins for ExperimentTab.

ExperimentTab grew to 5300+ lines mixing geometry setup, video preview,
graph rendering, tracking-issues detection, manual corrections, and Excel
output into one class. This package extracts cohesive slices as mixin
classes that ExperimentTab inherits; method signatures are unchanged so
no call site updates are needed.

Current split:
    scrub_mixin.ScrubMixin             — scrub seek, slider, cv2 cap cache
    corrections_mixin.CorrectionsMixin — fix position, interpolate, smooth

Planned (separate commits):
    graphs_mixin.GraphsMixin           — _make_*_fig + style helpers
    tracking_issues_mixin.IssuesMixin  — glitch detector + tab
    output_tabs_mixin.OutputTabsMixin  — Summary/Raw/VideoConfig tables
"""

from .scrub_mixin import ScrubMixin
from .corrections_mixin import CorrectionsMixin
from .tracking_issues_mixin import IssuesMixin
from .output_tabs_mixin import OutputTabsMixin
from .graphs_mixin import GraphsMixin

__all__ = ["ScrubMixin", "CorrectionsMixin", "IssuesMixin",
           "OutputTabsMixin", "GraphsMixin"]
