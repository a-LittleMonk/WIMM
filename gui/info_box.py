"""Per-card help text, shown in the Help window (header → Help).

Step builders call `attach_info_box(grp, entries)` with each parameter's
title and its explanation (a widget's tooltip, or a plain string). The
text is moved out of the tooltip and recorded under the card's name; no
button is added to the card. `collect_help()` captures everything
registered while an experiment tab is being built, which is how the Help
window gathers each experiment's text.
"""

_collector = None      # list of (card_name, [(title, text), ...]) while collecting


class collect_help:
    """Context manager: records every attach_info_box call made inside."""

    def __enter__(self):
        global _collector
        self._prev = _collector
        _collector = self.items = []
        return self

    def __exit__(self, *exc):
        global _collector
        _collector = self._prev
        return False


def attach_info_box(grp, entries):
    """Record help text for the card `grp`.

    entries: list of (title, source) where source is a widget (its
    tooltip text is moved into Help and cleared) or a plain string.
    Entries with no text are skipped.
    """
    items = []
    for title, src in entries:
        if isinstance(src, str):
            text = src
        else:
            text = src.toolTip()
            src.setToolTip("")
        if text and text.strip():
            items.append((title, text))
    if not items:
        return None
    name = getattr(grp, "_help_name", None) or grp.title() or "General"
    grp._help_items = getattr(grp, "_help_items", []) + items
    if _collector is not None:
        _collector.append((name, items))
    return None
