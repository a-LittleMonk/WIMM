"""Batch source rule (1.0.1): one ★ source video; every other video follows
it except the shared settings the user changed on that video ("own" keys),
and the run popup lists those differences."""
from gui.experiment_batch_tab import shared_changes, follow_source, batch_differences

ARENA_A = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
ARENA_B = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]


def test_shared_changes_finds_only_edited_shared_keys():
    before = {"threshold": 25, "smooth": 3, "arena": ARENA_A}
    after = {"threshold": 30, "smooth": 3, "arena": ARENA_B}
    assert shared_changes(before, after) == {"threshold"}   # arena is per video


def test_shared_changes_ignores_keys_missing_before():
    # A brand-new video has no saved value: filling defaults is not an edit.
    assert shared_changes({}, {"threshold": 25}) == set()


def test_shared_changes_handles_unorderable_values():
    import numpy as np
    before = {"colors": {"a": np.array([1, 2])}, "model_params": {"k": 1}}
    after = {"colors": {"a": np.array([1, 2])}, "model_params": {"k": 2}}
    assert shared_changes(before, after) == {"model_params"}


def test_follow_source_keeps_own_values_and_per_video_keys():
    src = {"threshold": 25, "smooth": 3, "arena": ARENA_A}
    own = {"threshold": 30, "smooth": 1, "arena": ARENA_B}
    out = follow_source(src, own, own_keys={"threshold"})
    assert out["threshold"] == 30      # changed on this video → kept
    assert out["smooth"] == 3          # not changed here → follows source
    assert out["arena"] == ARENA_B     # per-video geometry never copied


def test_follow_source_copies_are_independent():
    src = {"model_params": {"k": 1}}
    out = follow_source(src, {}, set())
    out["model_params"]["k"] = 99
    assert src["model_params"]["k"] == 1


def test_batch_differences_lists_only_real_differences():
    src = {"threshold": 25, "smooth": 3}
    settings = {
        "src.mp4": src,
        "a.mp4": {"threshold": 30, "smooth": 3},
        "b.mp4": {"threshold": 25, "smooth": 3},   # own key but same value
        "c.mp4": {"threshold": 25, "smooth": 3},
    }
    own = {"a.mp4": {"threshold"}, "b.mp4": {"threshold"}, "c.mp4": set()}
    diffs = batch_differences("src.mp4", ["src.mp4", "a.mp4", "b.mp4", "c.mp4"], settings, own)
    assert diffs == [("a.mp4", [("threshold", 25, 30)])]


def test_copy_groups_hold_only_per_video_settings():
    from gui.experiment_batch_tab import APPLY_FIELD_GROUPS, APPLY_DEFAULTS_ON, PER_VIDEO_KEYS
    keys = {k for _, ks in APPLY_FIELD_GROUPS for k in ks}
    assert keys <= PER_VIDEO_KEYS                 # shared settings follow the ★ source instead
    assert "metadata" in keys
    assert APPLY_DEFAULTS_ON <= {label for label, _ in APPLY_FIELD_GROUPS}


def test_copy_fields_keeps_each_animal_id():
    from gui.experiment_batch_tab import copy_fields
    src = {"arena": ARENA_A, "metadata": {"Animal ID": "m1", "Group": "Drug", "Sex": "M"}}
    tgt = {"arena": ARENA_B, "metadata": {"Animal ID": "m7", "Group": ""}}
    out = copy_fields(src, tgt, {"arena", "metadata"})
    assert out["arena"] == ARENA_A
    assert out["metadata"] == {"Animal ID": "m7", "Group": "Drug", "Sex": "M"}
    out["arena"][0][0] = 0.5
    assert src["arena"][0][0] == 0.1                # deep copy


def test_nose_marker_option_only_with_nose_detection():
    from PyQt5.QtWidgets import QApplication, QComboBox
    from gui.experiment_tab import set_nose_marker_option
    app = QApplication.instance() or QApplication([])
    c = QComboBox()
    for label, data in (("Off", "off"), ("Center", "dot"), ("Center + nose + tail", "ends")):
        c.addItem(label, data)
    c.setCurrentIndex(2)
    set_nose_marker_option(c, False)            # Y-maze / open field: no nose
    assert c.view().isRowHidden(2) and c.currentData() == "dot"
    set_nose_marker_option(c, True)             # NOR / nose detection on
    assert not c.view().isRowHidden(2)
    c.setCurrentIndex(2)
    assert c.currentData() == "ends"
