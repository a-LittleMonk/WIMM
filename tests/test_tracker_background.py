"""Tracker background: a mouse that sits still for most of the video must
not become part of the background, and a lighting change must not."""
import numpy as np

from tracking.preprocessor import build_background, match_level


def _frames(floor, mouse, still_frac, n=60, size=120):
    """Mouse = 10×10 square; still at (20, 20) for `still_frac` of frames,
    elsewhere otherwise."""
    out = []
    for i in range(n):
        f = np.full((size, size), floor, np.uint8)
        if i < n * still_frac:
            y, x = 20, 20
        else:
            y, x = 60 + (i % 5) * 8, 30 + (i % 7) * 10
        f[y:y + 10, x:x + 10] = mouse
        out.append(f)
    return out


def test_frozen_light_mouse_stays_out_of_background():
    bg, _ = build_background(_frames(40, 230, 0.7))
    assert abs(int(bg[25, 25]) - 40) < 5          # median would give 230


def test_frozen_dark_mouse_stays_out_of_background():
    bg, _ = build_background(_frames(200, 30, 0.7))
    assert abs(int(bg[25, 25]) - 200) < 5


def test_flicker_is_matched_to_the_floor_level():
    f = np.full((80, 80), 180, np.uint8)
    f[30:40, 30:40] = 30                          # dark mouse
    brighter = np.clip(f.astype(int) * 1.15, 0, 255).astype(np.uint8)
    m = match_level(brighter, 180.0)
    assert abs(int(m[5, 5]) - 180) <= 1           # floor back to the background level


def test_low_contrast_joins_the_pieces_of_a_pale_mouse():
    """Head, body edge and tail-base pieces near each other become one
    mouse; a speck far away is left out."""
    import cv2
    from tracking.tracker import _merge_fragments
    m = np.zeros((200, 200), np.uint8)
    for x, y, w, h in ((60, 90, 30, 20), (95, 92, 12, 10), (40, 95, 10, 8)):   # mouse pieces
        m[y:y + h, x:x + w] = 255
    m[10:16, 180:186] = 255                                                     # far speck
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    pts, area = _merge_fragments(cs, radius=40, min_piece=20)
    x, y, w, h = cv2.boundingRect(pts)
    assert (x, x + w) == (40, 107) and y >= 90          # all three pieces, no speck
    assert area > 600


def test_low_contrast_switch_doubles_sensitivity_and_off_changes_nothing():
    from tracking.tracker import TrackerThread
    assert TrackerThread("v.mp4", threshold=25).threshold == 25
    assert TrackerThread("v.mp4", threshold=25, low_contrast=True).threshold == 12
