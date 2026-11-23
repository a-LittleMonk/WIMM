"""core.video: impossible container fps is corrected, and exact seeking
lands on the asked frame even when the decoder's own jump lands early
and frames are unevenly spaced (both seen in real lab videos)."""
import cv2
import pytest

from core.video import probe, seek_exact


class _FakeCap:
    """Decoder whose jumps land `early` frames before the target, with a
    5 s gap in the timestamps after frame 1000."""

    def __init__(self, n=3000, fps_reported=29.74, count_reported=None, early=146):
        self.n, self.early = n, early
        self.fps_reported = fps_reported
        self.count_reported = count_reported or n
        self.ts = [i * 32.0 + (5000.0 if i > 1000 else 0.0) for i in range(n)]
        self.pos = 0                  # next frame to decode
        self.last = -1                # frame just decoded

    def set(self, prop, v):
        if prop == cv2.CAP_PROP_POS_FRAMES:
            self.pos = max(0, int(v) - (self.early if v > 0 else 0))

    def get(self, prop):
        if prop == cv2.CAP_PROP_FPS:
            return self.fps_reported
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return self.count_reported
        if prop == cv2.CAP_PROP_POS_MSEC:
            return self.ts[self.last] if self.last >= 0 else 0.0
        if prop == cv2.CAP_PROP_POS_FRAMES:
            return self.pos
        return 0.0

    def grab(self):
        if self.pos >= self.n:
            return False
        self.last, self.pos = self.pos, self.pos + 1
        return True


def test_seek_lands_on_the_asked_frame():
    cap = _FakeCap()
    for target in (1, 600, 1001, 2149, 2999):
        seek_exact(cap, target, cap.ts)
        assert cap.pos == target       # next read returns `target`


def test_impossible_fps_is_measured_from_timestamps():
    cap = _FakeCap(n=600, fps_reported=1000.0, count_reported=20000, early=0)
    fps, n = probe(cap)
    assert fps == pytest.approx(31.25)          # 32 ms per frame
    assert n == pytest.approx(625, abs=2)        # 20000 frames @1000 fps = 20 s
