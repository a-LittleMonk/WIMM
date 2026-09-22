"""OF UI builders.

Plugin entry points that delegate into `of_methods` where the physical
code lives (moved from OpenFieldTab during the ExperimentTab refactor —
Phase 2)."""
from . import of_methods as _ofm


def build_geometry_step(host):
    return _ofm._step_geometry_of(host)


def build_cell_info_tab(host):
    return _ofm._build_cell_info_tab(host)
