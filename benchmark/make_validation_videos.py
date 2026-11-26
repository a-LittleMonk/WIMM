"""WIMM validation videos with exactly known answers.

Each video: 30.000 s, 30 fps (900 frames), 1280x720, drawn on the same
synthetic arenas as arena_screenshots/make_arenas.py. One mouse follows a
scripted path, so its position on every frame is known exactly, and every
result (zone time, entries, latency, distance, ...) is computed from that
script, not from WIMM. The Excel next to each video is the benchmark.

Run inside a folder made by this script -> rebuilds that folder's test.
    python make_validation_videos.py            (this folder's test)
    python make_validation_videos.py --all      (all 12, into ./)
    python make_validation_videos.py open_field (one test, into ./)
    add --graphs to only redraw the Output graphs folder
Needs numpy, pillow, opencv-python, openpyxl (WIMM's .venv has them).
"""
import math
import os
import sys
import tempfile

import cv2
import numpy as np
from PIL import Image, ImageFilter
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "..", "arena_screenshots"),
           os.path.join(HERE, "..", "..", "arena_screenshots")):
    if os.path.exists(os.path.join(_p, "make_arenas.py")):
        sys.path.insert(0, _p)
        break
_argv, sys.argv = sys.argv, [sys.argv[0], tempfile.mkdtemp()]  # make_arenas makes its OUT dir on import
import make_arenas as MA                                          # noqa: E402
sys.argv = _argv

FPS = 30
N = 900                      # 30.000 s
DT = 1.0 / FPS
W, H, SS = MA.W, MA.H, MA.SS


# ═══ Background: the arena with the test mouse left out ═════════════════
def render_background(arena_fn, test_call):
    """Run a make_arenas drawing function, skipping its `test_call`-th
    mouse() call (1-based). Returns (clean RGB float image before noise /
    vignette, size and colour of the skipped mouse)."""
    orig_mouse, orig_finish = MA.Frame.mouse, MA.Frame.finish
    state = {"n": 0, "skipped": None, "img": None}

    def mouse(self, x, y, angle, size=1.0, color=MA.BLACK_MOUSE, tail_curl=0.6, shadow=True):
        state["n"] += 1
        if state["n"] == test_call:
            state["skipped"] = dict(size=size, color=color, tail_curl=tail_curl)
        else:
            orig_mouse(self, x, y, angle, size, color, tail_curl, shadow)

    def finish(self, name, seed=0):
        state["img"] = np.asarray(self.img.resize((W, H), Image.LANCZOS)).astype(np.float32)

    MA.Frame.mouse, MA.Frame.finish = mouse, finish
    try:
        arena_fn()
    finally:
        MA.Frame.mouse, MA.Frame.finish = orig_mouse, orig_finish
    return state["img"], state["skipped"]


def zero_maze_bg():
    """make_arenas.zero_maze with the closed walls on two 90° quadrants
    (top and bottom), as WIMM's zero-maze zones are four equal quadrants."""
    f = MA.Frame(bg=(24, 25, 27), seed=9)
    cx, cy, R, w = 640, 360, 280, 64
    f.circle(cx, cy, R + w / 2, (200, 200, 196))
    f.circle(cx, cy, R - w / 2, (24, 25, 27))
    f.floor_texture((0, 0, W, H), 4)
    for start in (45, 225):
        for rr in (R - w / 2, R + w / 2):
            box = [MA.S(cx - rr), MA.S(cy - rr), MA.S(cx + rr), MA.S(cy + rr)]
            f.d.arc(box, start, start + 90, fill=MA.WALL, width=int(MA.S(16)))
            f.d.arc(box, start, start + 90, fill=MA.WALL_TOP, width=MA.S(5))
    f.mouse(0, 0, 0, 0.85)
    f.finish("zero")


def water_maze_bg():
    """make_arenas.water_maze without the static ripples, platform moved onto
    the NE diagonal (WIMM places the platform on the quadrant diagonal)."""
    f = MA.Frame(bg=(36, 37, 40), seed=12)
    cx, cy, R = 640, 360, 330
    f.circle(cx, cy, R + 16, (140, 142, 146))
    f.circle(cx, cy, R, (206, 210, 214))
    f.floor_texture((cx - R, cy - R, cx + R, cy + R), 5)
    px, py = WM_PLAT
    f.circle(px, py, 26, (198, 202, 206), (190, 194, 198), 2)
    f.mouse(0, 0, 0, 1.0, tail_curl=0.2)
    f.finish("water")


# ═══ Mouse sprite (exact sub-pixel placement, alpha by black/white matting) ═
class Sprite:
    def __init__(self, size, color, tail_curl):
        self.size, self.color, self.curl = size, color, tail_curl
        self.cw = int(math.ceil(260 * size)) + 16
        self.cache = {}
        # body point = centre of the body (tail and shadow excluded), along
        # the heading axis, measured once at heading 0
        a, _ = self._render(0, 0.0, 0.0)
        ys, xs = np.nonzero(a > 0.5)
        c = self.cw / 2
        keep = xs - c > -39 * size
        self.body_off = float(xs[keep].mean() - c)
        self.body_off_y = float(ys[keep].mean() - c)
        self.nose = 49 * size - self.body_off           # body point -> nose tip
        self.tail = -39 * size - self.body_off          # body point -> tail base

    def _render(self, angle, ox, oy):
        out = []
        for bg in ((0, 0, 0), (255, 255, 255)):
            f = MA.Frame.__new__(MA.Frame)
            f.img = Image.new("RGB", (self.cw * SS, self.cw * SS), bg)
            f.d = None
            f.rng = None
            MA.Frame.mouse(f, self.cw / 2 + ox, self.cw / 2 + oy, angle, self.size,
                           self.color, self.curl, True)
            out.append(np.asarray(f.img.resize((self.cw, self.cw), Image.LANCZOS)).astype(np.float32))
        blk, wht = out
        alpha = np.clip(1 - (wht - blk).mean(axis=2) / 255.0, 0, 1)
        return alpha, np.clip(blk, 0, 255)

    def get(self, angle, fx, fy):
        key = (angle, fx, fy)
        if key not in self.cache:
            self.cache[key] = self._render(angle, fx / SS, fy / SS)
        return self.cache[key]

    def draw(self, img, x, y, heading):
        """Put the mouse so its body point lands on (x, y). `heading` is an
        integer number of degrees (0 = right, 90 = down)."""
        th = math.radians(heading)
        # sprite centre = body point minus the rotated body offset
        cx = x - (self.body_off * math.cos(th) - self.body_off_y * math.sin(th))
        cy = y - (self.body_off * math.sin(th) + self.body_off_y * math.cos(th))
        tx, ty = cx - self.cw / 2, cy - self.cw / 2
        ix, iy = math.floor(tx), math.floor(ty)
        fx, fy = int(round((tx - ix) * SS)), int(round((ty - iy) * SS))
        if fx == SS:
            ix, fx = ix + 1, 0
        if fy == SS:
            iy, fy = iy + 1, 0
        a, pre = self.get(heading, fx, fy)
        h, w = a.shape
        x0, y0, x1, y1 = max(ix, 0), max(iy, 0), min(ix + w, W), min(iy + h, H)
        sa = a[y0 - iy:y1 - iy, x0 - ix:x1 - ix, None]
        sp = pre[y0 - iy:y1 - iy, x0 - ix:x1 - ix]
        img[y0:y1, x0:x1] = img[y0:y1, x0:x1] * (1 - sa) + sp


def finish_frame(img, k, vign, seed):
    """Same camera look as make_arenas.Frame.finish (vignette, sensor noise,
    desaturation, slight blur), with fresh noise on every frame."""
    arr = img * vign[..., None]
    arr = arr + np.random.default_rng(seed * 100000 + k).normal(0, 3.2, (H, W, 1)).astype(np.float32)
    arr = 0.92 * arr + 0.08 * arr.mean(axis=2, keepdims=True)
    out = Image.fromarray(np.uint8(np.clip(arr, 0, 255))).filter(ImageFilter.GaussianBlur(0.45))
    return np.asarray(out)


def vignette():
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    return (1 - 0.22 * np.clip(r - 0.35, 0, None) ** 1.5).astype(np.float32)


# ═══ Scripted path ══════════════════════════════════════════════════════
class Path:
    """Body-point position per frame. Moves are at constant speed along
    straight lines / arcs; holds keep the mouse perfectly still."""

    def __init__(self, x, y, ppc, heading=0.0):
        self.ppc = ppc
        self.pts = [(float(x), float(y))]
        self.face = [None]
        self.h0 = heading

    @property
    def pos(self):
        return self.pts[-1]

    def hold(self, sec, face=None):
        """Stay still for `sec` s; `face` = point (x, y) to turn the head to."""
        for _ in range(int(round(sec * FPS))):
            self.pts.append(self.pos)
            self.face.append(face)
        return self

    def _poly(self, poly, speed_cmps):
        poly = [self.pos] + [(float(a), float(b)) for a, b in poly]
        seg = [math.dist(poly[i], poly[i + 1]) for i in range(len(poly) - 1)]
        L = sum(seg)
        n = max(1, math.ceil(L / (speed_cmps * self.ppc / FPS)))
        cum = np.concatenate([[0], np.cumsum(seg)])
        for i in range(1, n + 1):
            s = L * i / n
            j = min(int(np.searchsorted(cum, s, side="right")) - 1, len(seg) - 1)
            t = (s - cum[j]) / seg[j] if seg[j] else 0
            p, q = poly[j], poly[j + 1]
            self.pts.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
            self.face.append(None)
        return self

    def go(self, *pts, speed=20.0):
        """Walk through the given points (cm/s)."""
        return self._poly(pts, speed)

    def arc(self, cx, cy, r, a_to, speed=15.0):
        """Walk along a circle (image angles in degrees, y down) from the
        current angle to `a_to` (may be > 360 or negative for direction)."""
        x, y = self.pos
        a0 = math.degrees(math.atan2(y - cy, x - cx))
        if abs(math.hypot(x - cx, y - cy) - r) > 0.5:
            raise ValueError("arc must start on its circle")
        a0 += 360 * round((a_to - a0) / 360)          # start angle nearest the target (sweeps < 180°)
        n = max(2, int(abs(a_to - a0) * 4))
        pts = [(cx + r * math.cos(math.radians(a0 + (a_to - a0) * i / n)),
                cy + r * math.sin(math.radians(a0 + (a_to - a0) * i / n))) for i in range(1, n + 1)]
        return self._poly(pts, speed)

    def done(self):
        """Pad with stillness to exactly 900 frames."""
        if len(self.pts) > N:
            raise ValueError(f"script is {len(self.pts) / FPS:.2f} s, longer than 30 s")
        self.hold((N - len(self.pts)) / FPS, self.face[-1])
        assert len(self.pts) == N
        xy = np.array(self.pts)
        # heading: direction of travel when moving, else towards `face`, else
        # unchanged; turns at most 20° per frame; whole degrees.
        hd = np.zeros(N)
        cur = self.h0
        for i in range(N):
            tgt = None
            if i + 1 < N and math.dist(xy[i], xy[i + 1]) > 1e-9:
                tgt = math.degrees(math.atan2(xy[i + 1][1] - xy[i][1], xy[i + 1][0] - xy[i][0]))
            elif self.face[i] is not None:
                fx, fy = self.face[i]
                tgt = math.degrees(math.atan2(fy - xy[i][1], fx - xy[i][0]))
            elif i > 0 and math.dist(xy[i], xy[i - 1]) > 1e-9:
                tgt = math.degrees(math.atan2(xy[i][1] - xy[i - 1][1], xy[i][0] - xy[i - 1][0]))
            if tgt is not None:
                d = (tgt - cur + 180) % 360 - 180
                cur += max(-20.0, min(20.0, d))
            hd[i] = round(cur) % 360
        return xy, hd


# ═══ Ground truth ═══════════════════════════════════════════════════════
def runs(labels):
    """[(label, start, end_exclusive)] for consecutive equal labels."""
    out, s = [], 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[s]:
            out.append((labels[s], s, i))
            s = i
    return out


def r3(v):
    return round(float(v), 3)


class Truth:
    def __init__(self, xy, hd, sprite, ppc):
        self.xy, self.hd, self.ppc = xy, hd, ppc
        th = np.radians(hd)
        self.nose = xy + sprite.nose * np.c_[np.cos(th), np.sin(th)]
        self.tail = xy + sprite.tail * np.c_[np.cos(th), np.sin(th)]
        self.step = np.r_[0.0, np.hypot(*np.diff(xy, axis=0).T)]
        self.moving = self.step > 1e-9
        self.layers = {}            # layer -> (labels, [zone names in order])
        self.zfun = {}              # layer -> zone functions (for drawing outlines)
        self.rows = []              # benchmark rows: (section, measure, value, unit, how)

    def add(self, section, measure, value, unit="", how=""):
        self.rows.append((section, measure, value, unit, how))

    def layer(self, name, zones, point="body"):
        """zones: [(zone name, f(x, y) -> bool)], first match wins; '' = none."""
        P = self.xy if point == "body" else self.nose
        lab = []
        for x, y in P:
            lab.append(next((z for z, f in zones if f(x, y)), ""))
        self.layers[name] = (lab, [z for z, _ in zones])
        self.zfun[name] = zones
        return lab

    def zone_stats(self, layer, section, point_txt="body centre"):
        lab, names = self.layers[layer]
        rr = runs(lab)
        for z in names:
            fr = sum(1 for v in lab if v == z)
            ent = sum(1 for v, s, e in rr if v == z)
            first = next((s for v, s, e in rr if v == z), None)
            self.add(section, f"Time in {z} (s)", r3(fr * DT), "s", f"frames with the {point_txt} in {z} / 30")
            self.add(section, f"% Time in {z}", round(100 * fr / N, 2), "%", "of 30 s")
            self.add(section, f"Entries into {z} (#)", ent, "#",
                     "separate visits (a visit that starts on frame 0 counts)")
            self.add(section, f"Latency to {z} (s)", r3(first * DT) if first is not None else "never", "s",
                     "time of the first frame inside")
            self.add(section, f"Mean Visit in {z} (s)", r3(fr * DT / ent) if ent else 0.0, "s", "time / entries")
        return rr

    def visits(self, layer):
        lab, names = self.layers[layer]
        return [(v, s, e) for v, s, e in runs(lab) if v]

    def locomotion(self):
        px = float(self.step.sum())
        mv = int(self.moving[1:].sum())
        still_runs = [e - s for v, s, e in runs(list(self.moving[1:])) if not v]   # in steps
        pauses = [n for n in still_runs if n >= FPS]
        sp = self.step[1:] * FPS / self.ppc
        S = "Locomotion"
        self.add(S, "Duration (s)", 30.0, "s", "900 frames at 30 fps")
        self.add(S, "Total Frames", N, "#", "")
        self.add(S, "Total Distance (cm)", r3(px / self.ppc), "cm", "sum of frame-to-frame steps of the body centre")
        self.add(S, "Total Distance (px)", r3(px), "px", "")
        self.add(S, "Average Speed (cm/s)", r3(px / self.ppc / ((N - 1) * DT)), "cm/s",
                 "mean of the 899 frame-to-frame speeds")
        self.add(S, "Max Speed (cm/s)", r3(sp.max()), "cm/s", "fastest scripted walking speed")
        self.add(S, "Mean Speed When Mobile (cm/s)", r3(sp[sp > 0].mean()), "cm/s", "")
        self.add(S, "Mobility Time (s)", r3(mv * DT), "s",
                 "steps where the mouse moves (scripted speed is always >= 10 cm/s, so any movement threshold "
                 "between 1 and 9 cm/s gives this)")
        self.add(S, "Immobility Time (s)", r3((N - 1 - mv) * DT), "s", "steps where the mouse is perfectly still")
        self.add(S, "Pause Count (#)", len(pauses), "#", "still periods of >= 1 s")
        self.add(S, "Total Time in Pauses (s)", r3(sum(pauses) * DT), "s", "")
        self.add(S, "Longest Pause (s)", r3(max(pauses) * DT) if pauses else 0.0, "s", "")


# ═══ Geometry helpers ═══════════════════════════════════════════════════
def in_rect(x0, y0, x1, y1):
    return lambda x, y: x0 <= x <= x1 and y0 <= y <= y1


def in_circle(cx, cy, r):
    return lambda x, y: math.hypot(x - cx, y - cy) <= r


def in_bar(cx, cy, ang_img, r0, r1, hw):
    """Arm-shaped strip from the centre outwards (image angle)."""
    ux, uy = math.cos(math.radians(ang_img)), math.sin(math.radians(ang_img))

    def f(x, y):
        a = (x - cx) * ux + (y - cy) * uy
        b = -(x - cx) * uy + (y - cy) * ux
        return r0 <= a <= r1 and abs(b) <= hw
    return f


def in_poly(poly):
    def f(x, y):
        inside, n = False, len(poly)
        for i in range(n):
            (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
        return inside
    return f


def ring_sector(cx, cy, r_in, r_out, a0, a1):
    """Image-angle sector [a0, a1) of a ring (degrees, y down)."""
    def f(x, y):
        d = math.hypot(x - cx, y - cy)
        a = (math.degrees(math.atan2(y - cy, x - cx)) - a0) % 360
        return r_in <= d <= r_out and a < (a1 - a0)
    return f


def towards(p, q, d):
    """Point at distance d from p, in the direction of q."""
    L = math.dist(p, q)
    return (p[0] + (q[0] - p[0]) * d / L, p[1] + (q[1] - p[1]) * d / L)


# ═══ The 12 tests ═══════════════════════════════════════════════════════
# Each returns (path, settings rows, zone rows, extra-measures function).
# settings rows: (setting, value) — what to set in WIMM so its zones are
# the zones used here. Pixel coordinates are in the 1280x720 video.

GRID_OF = (370, 90, 910, 630)     # square arena used by OF / NOR / NOL (4 x 4 cells)


def t_open_field():
    x0, y0, s, ppc = 370, 90, 540, 13.5              # 40 x 40 cm
    c0, c1 = (x0 + s * 0.25, y0 + s * 0.25), (x0 + s * 0.75, y0 + s * 0.75)
    band = 2 * ppc                                  # WIMM's fixed band
    # waypoints keep the nose off the walls: along a wall at 40 px, round
    # corners, and never stop facing a wall
    p = Path(410, 450, ppc, -90)
    p.hold(2).go((410, 200)).arc(480, 200, 70, 270, speed=20).go((720, 130)).hold(1.5)
    p.go((640, 360), speed=15).hold(3).go((570, 300), speed=10).hold(1.5)
    p.go((450, 520)).go((580, 585)).go((760, 590)).hold(2)
    p.go((700, 420), speed=15).hold(2).go((840, 300)).go((840, 180), speed=12).hold(1.5)
    p.go((610, 290), speed=15)
    center = in_rect(*c0, *c1)

    def extra(T):
        T.layer("zone", [("Center Zone", center), ("Periphery", in_rect(x0, y0, x0 + s, y0 + s))])
        T.zone_stats("zone", "Center vs Periphery")
        th = [min(x - x0, x0 + s - x, y - y0, y0 + s - y) < band for x, y in T.xy]
        T.add("Thigmotaxis", "Thigmotaxis Time (s)", r3(sum(th) * DT), "s",
              "body centre within 2 cm of the arena outline")
        T.add("Thigmotaxis", "Thigmotaxis %", round(100 * sum(th) / N, 1), "%", "")
    settings = [("Experiment", "Open Field"),
                ("Arena corners (px)", f"({x0},{y0}) ({x0+s},{y0}) ({x0+s},{y0+s}) ({x0},{y0+s})  — wall centre-lines"),
                ("Arena size", "40 x 40 cm  → 13.5 px/cm"),
                ("Center zone", "50 %  (auto-drawn, half the side)"),
                ("Thigmotaxis band", "2 cm (fixed in WIMM, no setting)"),
                ("Movement threshold", "2 cm/s")]
    zones = [("Center Zone", f"x {c0[0]:.0f}–{c1[0]:.0f}, y {c0[1]:.0f}–{c1[1]:.0f}"),
             ("Periphery", "rest of the arena")]
    return MA.open_field, 1, p, settings, zones, extra


YC, YL, YW = (640, 410), 300, 86
Y_ARMS = {"Arm A": -90, "Arm B": 150, "Arm C": 30}      # A top, B bottom-left, C bottom-right


def t_y_maze():
    ppc = 8.6                                        # arm width 86 px = 10 cm
    cx, cy = YC
    deep = {k: (cx + 215 * math.cos(math.radians(a)), cy + 215 * math.sin(math.radians(a)))
            for k, a in Y_ARMS.items()}
    seq = ["A", "B", "C", "A", "C", "B", "A", "B", "C", "B"]
    p = Path(*deep["Arm A"], ppc, 90)
    p.hold(1.5)
    for a in seq[1:]:
        p.go((cx, cy), deep[f"Arm {a}"], speed=25).hold(0.6)
    r0 = (YW / 2) / math.tan(math.radians(60))       # hub triangle edge, 24.8 px from centre

    def extra(T):
        T.layer("arm", [(k, in_bar(cx, cy, a, r0, YL, YW / 2)) for k, a in Y_ARMS.items()])
        T.zone_stats("arm", "Arms")
        arms = [v[-1] for v, s, e in T.visits("arm")]
        trip = [arms[i:i + 3] for i in range(len(arms) - 2)]
        alt = sum(1 for t in trip if len(set(t)) == 3)
        S = "Alternation"
        T.add(S, "Arm Entry Sequence", "".join(arms), "", "")
        T.add(S, "Total Arm Entries (#)", len(arms), "#", "the first arm (start) counts")
        T.add(S, "Spontaneous Alternations (#)", alt, "#", "triplets of 3 different consecutive arms")
        T.add(S, "Possible Alternations (#)", len(trip), "#", "entries − 2")
        T.add(S, "Spontaneous Alternation (%)", round(100 * alt / len(trip), 2), "%", "")
        T.add(S, "Alternate Arm Returns (#)", sum(1 for i in range(2, len(arms)) if arms[i] == arms[i - 2]), "#",
              "X-Y-X")
        T.add(S, "Same Arm Returns (#)", sum(1 for i in range(1, len(arms)) if arms[i] == arms[i - 1]), "#", "X-X")
    settings = [("Experiment", "Y-Maze"),
                ("Arm template hub (px)", f"({cx},{cy})"),
                ("Arm ends (px)", "A (640,110)  B (380.2,560)  C (899.8,560)"),
                ("Arm width", "86 px (10 cm)"),
                ("Scale", "8.6 px/cm  (e.g. calibration line (597,110)–(683,110) = 10 cm, the end of arm A)"),
                ("Entry rule", "Body center"), ("Min dwell", "0 s")]
    zones = [(k, f"strip at image angle {a}°, from {r0:.1f} to 300 px from the hub, 86 px wide")
             for k, a in Y_ARMS.items()]
    return MA.y_maze, 1, p, settings, zones, extra


def _object_test(objs, novel, roles, ppc=13.5):
    """objs: {name: (shape, cx, cy, half-size px)}; zone = footprint + 2 cm."""
    pad = 2 * ppc

    def zone(o):
        sh, cx, cy, h = o
        return in_circle(cx, cy, h + pad) if sh == "circle" else in_rect(cx - h - pad, cy - h - pad,
                                                                         cx + h + pad, cy + h + pad)

    def extra(T):
        T.layer("obj", [(n, zone(o)) for n, o in objs.items()], point="nose")
        T.zone_stats("obj", "Object exploration (nose)", "nose tip")
        lab = T.layers["obj"][0]
        t = {n: sum(1 for v in lab if v == n) * DT for n in objs}
        nv = t[novel]
        fm = sum(v for k, v in t.items() if k != novel)
        S = "Main results"
        T.add(S, f"{roles[1]} exploration (s)", r3(nv), "s", "nose in the object's zone")
        T.add(S, f"{roles[0]} exploration (s)", r3(fm), "s", "")
        T.add(S, "Total exploration (s)", r3(nv + fm), "s", "")
        T.add(S, "Discrimination Index", round((nv - fm) / (nv + fm), 4), "",
              f"({roles[1]} − {roles[0]}) / total")
        T.add(S, f"Preference % {roles[1]}", round(100 * nv / (nv + fm), 2), "%", "")
        for n in objs:
            T.add(S, f"Exploration bouts {n} (#)", sum(1 for v, s, e in T.visits("obj") if v == n), "#", "")
    return extra


def t_novel_object():
    ppc = 13.5
    cyl, blk = (520, 240), (760, 480)
    objs = {"Object 1 (cylinder)": ("circle", *cyl, 34), "Object 2 (block)": ("square", *blk, 30)}
    p = Path(470, 520, ppc, -45)
    p.hold(1.5).go(towards(cyl, (470, 520), 100), speed=15).hold(3, cyl)
    p.go((450, 550)).go((640, 555)).go(towards(blk, (640, 480), 100), speed=12).hold(4, blk)
    p.go((640, 555)).go((835, 555)).go(towards(blk, (760, 600), 100), speed=12).hold(3, blk)
    p.go((835, 555)).go((835, 300)).go(towards(cyl, (620, 240), 100), speed=12).hold(2, cyl)
    p.go((640, 165)).go((835, 165)).go((835, 300)).go(towards(blk, (760, 380), 100), speed=12).hold(2.5, blk)
    p.go((835, 400), speed=15)
    settings = [("Experiment", "Novel Object Recognition"),
                ("Arena corners (px)", "(370,90) (910,90) (910,630) (370,630)"),
                ("Arena size", "40 x 40 cm → 13.5 px/cm"),
                ("Object 1", "circle, centre (520,240), size 5.0 cm (68 px), role Familiar"),
                ("Object 2", "square, centre (760,480), size 4.4 cm (60 px), role Novel"),
                ("Interaction zone padding", "2 cm"), ("Head-angle rule", "off"), ("Min dwell", "0 s")]
    zones = [("Object 1 zone", "nose within 61 px (4.5 cm) of (520,240)"),
             ("Object 2 zone", "nose inside square (703,423)–(817,537)")]
    return MA.novel_object, 1, p, settings, zones, _object_test(objs, "Object 2 (block)", ("Familiar", "Novel"))


def t_object_location():
    ppc = 13.5
    st, mv = (510, 240), (770, 490)
    objs = {"Stationary object": ("circle", *st, 32), "Moved object": ("circle", *mv, 32)}
    p = Path(430, 580, ppc, -60)
    p.hold(1.5).go(towards(mv, (640, 600), 98), speed=15).hold(3.5, mv)
    p.go((640, 555)).go((450, 555)).go(towards(st, (420, 380), 98), speed=12).hold(2, st)
    p.go((450, 420)).go((640, 420)).go(towards(mv, (640, 490), 98), speed=12).hold(2.5, mv)
    p.go((640, 380)).go((835, 380)).go(towards(mv, (870, 560), 98), speed=12).hold(2, mv)
    p.go((835, 300)).go((640, 165)).go(towards(st, (640, 160), 98), speed=12).hold(1.5, st)
    p.go((650, 300), speed=15)
    settings = [("Experiment", "Novel Object Location"),
                ("Arena corners (px)", "(370,90) (910,90) (910,630) (370,630)"),
                ("Arena size", "40 x 40 cm → 13.5 px/cm"),
                ("Object 1", "circle, centre (510,240), size 4.7 cm (64 px), role Stationary"),
                ("Object 2", "circle, centre (770,490), size 4.7 cm (64 px), role Moved"),
                ("Interaction zone padding", "2 cm"), ("Head-angle rule", "off"), ("Min dwell", "0 s")]
    zones = [("Stationary zone", "nose within 59 px of (510,240)"),
             ("Moved zone", "nose within 59 px of (770,490)")]
    return MA.object_location, 1, p, settings, zones, _object_test(objs, "Moved object", ("Stationary", "Moved"))


def t_epm():
    ppc, cx, cy, hw = 13.2, 640, 360, 33             # arm width 66 px = 5 cm
    p = Path(cx, cy, ppc, -90)
    p.hold(1.5).go((cx, cy - 220), speed=15).hold(3)
    p.go((cx, cy), (cx + 230, cy), speed=15).hold(1.5)
    p.go((cx, cy), speed=18).hold(1.5).go((cx, cy + 230), speed=15).hold(4)
    p.go((cx, cy), (cx - 200, cy), speed=15).hold(2)
    p.go((cx, cy), (cx, cy - 180), speed=18)

    def extra(T):
        T.layer("arm", [("Center", in_rect(cx - hw, cy - hw, cx + hw, cy + hw)),
                        ("Open arm right", in_rect(cx + hw, cy - hw, cx + 330, cy + hw)),
                        ("Open arm left", in_rect(cx - 330, cy - hw, cx - hw, cy + hw)),
                        ("Closed arm top", in_rect(cx - hw, cy - 320, cx + hw, cy - hw)),
                        ("Closed arm bottom", in_rect(cx - hw, cy + hw, cx + hw, cy + 320))])
        T.zone_stats("arm", "Arms")
        lab = T.layers["arm"][0]
        vis = [v for v, s, e in T.visits("arm") if v != "Center"]
        to = sum(1 for v in lab if v.startswith("Open")) * DT
        tc = sum(1 for v in lab if v.startswith("Closed")) * DT
        eo = sum(1 for v in vis if v.startswith("Open"))
        ec = len(vis) - eo
        first_open = next(s for v, s, e in T.visits("arm") if v.startswith("Open"))
        S = "Main results"
        T.add(S, "Time in Open Arms (s)", r3(to), "s", "")
        T.add(S, "Time in Closed Arms (s)", r3(tc), "s", "")
        T.add(S, "% Time Open (of arm time)", round(100 * to / (to + tc), 2), "%", "open / (open + closed)")
        T.add(S, "Open Arm Entries (#)", eo, "#", "")
        T.add(S, "Closed Arm Entries (#)", ec, "#", "")
        T.add(S, "% Open Entries", round(100 * eo / (eo + ec), 2), "%", "")
        T.add(S, "Total Arm Entries (#)", eo + ec, "#", "")
        T.add(S, "Latency to First Open Entry (s)", r3(first_open * DT), "s", "")
        T.add(S, "Entry Sequence", "-".join(vis), "", "")
    settings = [("Experiment", "Elevated Plus Maze"),
                ("Plus template hub (px)", f"({cx},{cy})"),
                ("Arm ends (px)", "open right (970,360), open left (310,360), closed top (640,40), closed bottom (640,680)"),
                ("Arm width", "66 px (5 cm)"), ("Center", "66 x 66 px square"),
                ("Scale", "13.2 px/cm (arm width 66 px = 5 cm)"),
                ("Perspective", "none (camera straight above)"),
                ("Entry rule", "Body center"), ("Min dwell", "0 s")]
    zones = [("Center", "x 607–673, y 327–393"), ("Open arms", "|y−360| ≤ 33, 33 < |x−640| ≤ 330"),
             ("Closed arms", "|x−640| ≤ 33, 33 < |y−360| ≤ 320")]
    return MA.elevated_plus, 1, p, settings, zones, extra


def t_three_chamber():
    x0, y0, w, h, ppc = 190, 160, 900, 400, 15.0      # 60 x 26.67 cm
    a, b = x0 + 0.335 * w, x0 + 0.665 * w            # WIMM center chamber 33 %
    cupL, cupR = (x0 + w / 6, y0 + h / 2), (x0 + 5 * w / 6, y0 + h / 2)
    sniff = (8.3 / 2 + 3) * ppc                      # cup 8.3 cm + 3 cm
    door_l, door_r = (490, 360), (790, 360)
    p = Path(640, 360, ppc, 180)
    # Sniff spots straight through the doors, on the line to each cup: the
    # nose crosses a sniff-zone edge once per approach / leave, never grazes it.
    sL, sR = towards(cupL, door_l, 128), towards(cupR, door_r, 128)
    p.hold(3).go(sL, speed=12).hold(4, cupL)
    p.go((640, 360), speed=15).hold(2)
    p.go(sR, speed=12).hold(3, cupR)
    p.go((640, 360), speed=15).hold(1.5)
    p.go(sL, speed=12).hold(3, cupL)
    p.go((640, 360), speed=15)

    def extra(T):
        T.layer("chamber", [("Stranger Chamber", in_rect(x0, y0, a, y0 + h)),
                            ("Center Chamber", in_rect(a, y0, b, y0 + h)),
                            ("Empty Chamber", in_rect(b, y0, x0 + w, y0 + h))])
        T.zone_stats("chamber", "Chambers (body centre)")
        T.layer("sniff", [("Stranger sniff zone", in_circle(*cupL, sniff)),
                          ("Empty sniff zone", in_circle(*cupR, sniff))], point="nose")
        T.zone_stats("sniff", "Sniff zones (nose tip)", "nose tip")
        L1, L2 = T.layers["chamber"][0], T.layers["sniff"][0]
        ts, te = (sum(1 for v in L1 if v == k) * DT for k in ("Stranger Chamber", "Empty Chamber"))
        ns, ne = (sum(1 for v in L2 if v == k) * DT for k in ("Stranger sniff zone", "Empty sniff zone"))
        T.add("Main results", "Sociability Index (chamber)", round((ts - te) / (ts + te), 3), "",
              "(stranger − empty) / (stranger + empty)")
        T.add("Main results", "Sociability Index (sniffing)", round((ns - ne) / (ns + ne), 3), "", "")
    settings = [("Experiment", "Three-Chamber Social"),
                ("Box corners (px)", f"({x0},{y0}) ({x0+w},{y0}) ({x0+w},{y0+h}) ({x0},{y0+h})"),
                ("Apparatus size", "60 x 26.67 cm (15 px/cm)"),
                ("Phase", "Sociability"), ("Stranger in", "Left"), ("Center chamber", "33 %"),
                ("Layout", "Side by side"), ("Cups placed", "Chamber middle"),
                ("Cup diameter", "8.3 cm"), ("Sniff zone", "3 cm"), ("Min dwell", "0 s")]
    zones = [("Stranger chamber", f"x {x0}–{a:.1f}"), ("Center chamber", f"x {a:.1f}–{b:.1f}"),
             ("Empty chamber", f"x {b:.1f}–{x0+w}"),
             ("Sniff zones", f"nose within {sniff:.2f} px of a cup centre {cupL} / {cupR}")]
    return MA.three_chamber, 2, p, settings, zones, extra


def t_place_preference():
    x0, y0, L, h = 170, 170, 940, 380
    ppc = L / 60.0
    a, b = x0 + 0.405 * L, x0 + 0.595 * L            # neutral 19 %
    p = Path(640, 360, ppc, 180)
    p.hold(2).go((550, 360), (360, 300), speed=15).hold(5).go((300, 470), speed=10).hold(3)
    p.go((550, 360), (730, 360), (920, 290), speed=18).hold(4)
    p.go((730, 360), (640, 360), speed=15).hold(1.5).go((550, 360), (400, 420), speed=15)

    def extra(T):
        T.layer("comp", [("Compartment A", in_rect(x0, y0, a, y0 + h)),
                         ("Neutral", in_rect(a, y0, b, y0 + h)),
                         ("Compartment B", in_rect(b, y0, x0 + L, y0 + h))])
        T.zone_stats("comp", "Compartments")
        lab = T.layers["comp"][0]
        tp = sum(1 for v in lab if v == "Compartment A") * DT
        tu = sum(1 for v in lab if v == "Compartment B") * DT
        S = "Main results"
        T.add(S, "Paired Compartment", "Compartment A", "", "")
        T.add(S, "Time in Paired (s)", r3(tp), "s", "")
        T.add(S, "Time in Unpaired (s)", r3(tu), "s", "")
        T.add(S, "% Time in Paired", round(100 * tp / (tp + tu), 2), "%", "paired / (paired + unpaired)")
        T.add(S, "Preference Score (s)", r3(tp - tu), "s", "paired − unpaired")
    settings = [("Experiment", "Place Preference"),
                ("Apparatus corners (px)", f"({x0},{y0}) ({x0+L},{y0}) ({x0+L},{y0+h}) ({x0},{y0+h})"),
                ("Apparatus size", "60 x 24.26 cm (15.667 px/cm)"),
                ("Compartments", "3 (with neutral)"), ("Neutral width", "19 %"),
                ("Layout", "Side by side"), ("Drug-paired", "Compartment A"), ("Min dwell", "0 s")]
    zones = [("Compartment A", f"x {x0}–{a:.1f}"), ("Neutral", f"x {a:.1f}–{b:.1f}"),
             ("Compartment B", f"x {b:.1f}–{x0+L}")]
    return MA.place_preference, 1, p, settings, zones, extra


def t_light_dark():
    x0, y0, w, h = 260, 140, 760, 440
    ppc = w / 45.0
    split = x0 + 0.6 * w
    door = (split, 360)
    p = Path(420, 250, ppc, 90)
    p.hold(1.5).go((600, 450), speed=15).go(door, (880, 250), speed=15).hold(4).go((900, 480), speed=10).hold(3)
    p.go(door, (450, 470), speed=18).hold(3).go((560, 220), speed=12).hold(2)
    p.go(door, (870, 360), speed=18)

    def extra(T):
        T.layer("side", [("Light", in_rect(x0, y0, split, y0 + h)),
                         ("Dark", in_rect(split, y0, x0 + w, y0 + h))])
        T.zone_stats("side", "Sides")
        vis = T.visits("side")
        T.add("Main results", "Transitions (#)", len(vis) - 1, "#", "light↔dark changes")
        lab = T.layers["side"][0]
        dl = sum(T.step[i] for i in range(1, N) if lab[i] == "Light" and lab[i - 1] == "Light") / ppc
        T.add("Main results", "Distance in Light (cm)", r3(dl), "cm",
              "the only part a camera can see — the mouse is black on the dark side")
    settings = [("Experiment", "Light–Dark Box"),
                ("Box corners (px)", f"({x0},{y0}) ({x0+w},{y0}) ({x0+w},{y0+h}) ({x0},{y0+h})"),
                ("Box size", "45 x 26.05 cm (16.889 px/cm)"),
                ("Dark side", "40 %"), ("Dark side is", "Right"),
                ("Count lost frames as dark", "ON (black mouse on black floor is not visible)"),
                ("Min dwell", "0 s")]
    zones = [("Light", f"x {x0}–{split:.0f}"), ("Dark", f"x {split:.0f}–{x0+w}")]
    return MA.light_dark, 1, p, settings, zones, extra


def t_zero_maze():
    cx, cy, R = 640, 360, 280
    r_out = 312.0
    r_in = r_out * (1 - 0.21)
    ppc = 2 * r_out / 50.0
    start = (cx + R * math.cos(math.radians(90)), cy + R * math.sin(math.radians(90)))
    p = Path(*start, ppc, 180)
    p.hold(2).arc(cx, cy, R, 175, speed=14).hold(2.5).arc(cx, cy, R, 255, speed=14).hold(3)
    p.arc(cx, cy, R, 335, speed=14).hold(1.5).arc(cx, cy, R, 430, speed=14).hold(2)
    p.arc(cx, cy, R, 365, speed=16).hold(1.5).arc(cx, cy, R, 450, speed=14)
    # image angles (y down): right −45..45 open, bottom 45..135 closed,
    # left 135..225 open, top 225..315 closed
    secs = [("Right (open)", -45), ("Bottom (closed)", 45), ("Left (open)", 135), ("Top (closed)", 225)]

    def extra(T):
        T.layer("ring", [(n, ring_sector(cx, cy, r_in, r_out, a0, a0 + 90)) for n, a0 in secs])
        T.zone_stats("ring", "Sections")
        lab = T.layers["ring"][0]
        vis = T.visits("ring")
        to = sum(1 for v in lab if "open" in v) * DT
        eo = sum(1 for v, s, e in vis if "open" in v)
        ec = len(vis) - eo
        kinds = [v.split("(")[1] for v, s, e in vis]
        S = "Main results"
        T.add(S, "Time in Open (s)", r3(to), "s", "")
        T.add(S, "Time in Closed (s)", r3(30 - to), "s", "")
        T.add(S, "% Time in Open", round(100 * to / 30, 2), "%", "")
        T.add(S, "Entries into Open (#)", eo, "#", "")
        T.add(S, "Entries into Closed (#)", ec, "#", "start section counts")
        T.add(S, "% Open Entries", round(100 * eo / (eo + ec), 2), "%", "")
        T.add(S, "Latency to Open (s)", r3(next(s for v, s, e in vis if "open" in v) * DT), "s", "")
        T.add(S, "Open / Closed Crossings (#)", sum(1 for i in range(1, len(kinds)) if kinds[i] != kinds[i - 1]),
              "#", "")
    settings = [("Experiment", "Elevated Zero Maze"),
                ("Outline corners (px)", "(328,48) (952,48) (952,672) (328,672) — square around the ring's outer edge"),
                ("Outer diameter", "50 cm (12.48 px/cm)"), ("Ring width", "21 %"), ("Rotation", "0°"),
                ("Top section", "Closed"), ("Right section", "Open"),
                ("Bottom section", "Closed"), ("Left section", "Open"), ("Min dwell", "0 s")]
    zones = [(n, f"ring {r_in:.1f}–{r_out:.0f} px, image angles {a0}°–{a0+90}° (y down)") for n, a0 in secs]
    return zero_maze_bg, 1, p, settings, zones, extra


def t_t_maze():
    L, R, top, bottom = 250, 1030, 150, 640
    ppc = (R - L) / 70.0
    wa = 0.17 * (bottom - top)                       # arm width 17 % of the short side
    jl, jr, ybar = 640 - wa / 2, 640 + wa / 2, top + wa
    p = Path(640, 560, ppc, -90)
    p.hold(1.5).go((640, 192), (330, 192), speed=20).hold(2)
    p.go((640, 192), (950, 192), speed=20).hold(2)
    p.go((640, 192), (640, 470), speed=20).hold(1.5)
    p.go((640, 192), (950, 192), speed=20).hold(1.5)
    p.go((640, 192), (330, 192), speed=20)

    def extra(T):
        T.layer("arm", [("Junction", in_rect(jl, top, jr, ybar)), ("Left arm", in_rect(L, top, jl, ybar)),
                        ("Right arm", in_rect(jr, top, R, ybar)), ("Start arm", in_rect(jl, ybar, jr, bottom))])
        T.zone_stats("arm", "Arms")
        ch = [(v, s) for v, s, e in T.visits("arm") if v in ("Left arm", "Right arm")]
        seq = "".join(v[0] for v, s in ch)
        alt = sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])
        S = "Main results"
        T.add(S, "First Choice", "Left" if seq[0] == "L" else "Right", "", "")
        T.add(S, "Latency to First Choice (s)", r3(ch[0][1] * DT), "s", "")
        T.add(S, "Goal-Arm Choices (#)", len(seq), "#", "")
        T.add(S, "Alternations (#)", alt, "#", "")
        T.add(S, "Alternation (%)", round(100 * alt / (len(seq) - 1), 2), "%", "")
        T.add(S, "Choice Sequence", seq, "", "")
    settings = [("Experiment", "T-Maze"),
                ("Outline corners (px)", f"({L},{top}) ({R},{top}) ({R},{bottom}) ({L},{bottom})"),
                ("Apparatus size", "70 x 43.97 cm (11.143 px/cm)"),
                ("Start arm", "Bottom"), ("Arm width", "17 %"), ("Min dwell", "0 s")]
    zones = [("Junction", f"x {jl:.2f}–{jr:.2f}, y {top}–{ybar:.2f}"), ("Left arm", f"x {L}–{jl:.2f}"),
             ("Right arm", f"x {jr:.2f}–{R}"), ("Start arm", f"y {ybar:.2f}–{bottom}")]
    return MA.t_maze, 1, p, settings, zones, extra


def t_radial():
    cx, cy, half = 640, 360, 330
    ppc = 2 * half / 100.0
    rot, n = 22.5, 8
    r_hub = half * 0.21
    hw = 0.08 * 2 * half / 2
    start = r_hub * math.cos(math.radians(180 / n))
    ang = {k: -(90 - rot - (k - 1) * 360 / n) for k in range(1, n + 1)}   # image angle of arm k
    deep = {k: (cx + 225 * math.cos(math.radians(a)), cy + 225 * math.sin(math.radians(a)))
            for k, a in ang.items()}
    order = [1, 3, 5, 7, 3, 2, 8, 6, 4]
    p = Path(cx, cy, ppc, -90).hold(1.5)
    for i, k in enumerate(order):
        p.go(deep[k], speed=30).hold(0.4)
        p.go((cx, cy), speed=30)
    hub_poly = [(cx + r_hub * math.cos(math.radians(-(90 - rot - 180 / n) - j * 45)),
                 cy + r_hub * math.sin(math.radians(-(90 - rot - 180 / n) - j * 45))) for j in range(n)]

    def extra(T):
        T.layer("arm", [("Centre", in_poly(hub_poly))] +
                [(f"Arm {k}", in_bar(cx, cy, ang[k], start, half, hw)) for k in range(1, n + 1)])
        T.zone_stats("arm", "Arms")
        vis = [(int(v[4:]), s) for v, s, e in T.visits("arm") if v.startswith("Arm")]
        arms = [a for a, s in vis]
        seen, wm, first_rep, t_all = set(), 0, None, None
        for i, (a, s) in enumerate(vis):
            if a in seen:
                wm += 1
                if first_rep is None:
                    first_rep = i
            seen.add(a)
            if t_all is None and len(seen) == n:
                t_all = r3(s * DT)
        S = "Main results"
        T.add(S, "Total Arm Entries (#)", len(arms), "#", "")
        T.add(S, "Working Memory Errors (#)", wm, "#", "re-entries into an arm already visited")
        T.add(S, "Entries Before First Repeat (#)", first_rep, "#", "")
        T.add(S, "Different Arms in First 8 Entries (#)", len(set(arms[:n])), "#", "")
        T.add(S, "Time to Visit All Arms (s)", t_all if t_all is not None else "never", "s", "")
        T.add(S, "Arm Entry Sequence", "-".join(map(str, arms)), "", "")
    settings = [("Experiment", "Radial Arm Maze"),
                ("Outline corners (px)", "(310,30) (970,30) (970,690) (310,690) — square around the arm tips"),
                ("Tip-to-tip diameter", "100 cm (6.6 px/cm)"), ("Arms", "8"), ("Arm width", "8 %"),
                ("Centre size", "21 %"), ("Rotation", "22.5° (arm 1 = upper right, numbered clockwise)"),
                ("Baited arms", "none selected (all baited)"), ("Min dwell", "0 s")]
    zones = [("Centre", f"regular octagon, radius {r_hub:.1f} px")] + \
            [(f"Arm {k}", f"image angle {ang[k] % 360:.1f}°, {start:.1f}–330 px from centre, {2*hw:.1f} px wide")
             for k in range(1, n + 1)]
    return MA.radial_arm, 1, p, settings, zones, extra


_d = 0.5 * 0.56 * 660
WM_PLAT = (640 + _d * math.cos(math.radians(45)), 360 - _d * math.sin(math.radians(45)))


def t_water_maze():
    cx, cy, Rp = 640, 360, 330
    ppc = 2 * Rp / 120.0
    pr = 9.5 / 2 * ppc
    r_wall = Rp * 0.9
    a0 = 120
    p = Path(cx + 312 * math.cos(math.radians(a0)), cy + 312 * math.sin(math.radians(a0)), ppc, 210)
    p.arc(cx, cy, 312, 215, speed=20).go((560, 400), (720, 560), (880, 420), speed=20)
    p.go((700, 330), (560, 200), (660, 120), speed=20).go(WM_PLAT, speed=15)
    quads = [("NE quadrant", lambda x, y: x >= cx and y < cy), ("NW quadrant", lambda x, y: x < cx and y < cy),
             ("SW quadrant", lambda x, y: x < cx and y >= cy), ("SE quadrant", lambda x, y: x >= cx and y >= cy)]

    def extra(T):
        T.layer("quad", quads)
        T.zone_stats("quad", "Quadrants")
        T.layer("platform", [("Platform", in_circle(*WM_PLAT, pr))])
        T.zone_stats("platform", "Platform")
        T.layer("wall", [("Wall zone", lambda x, y: r_wall <= math.hypot(x - cx, y - cy) <= Rp)])
        T.zone_stats("wall", "Wall zone (thigmotaxis)")
        f0 = T.layers["platform"][0].index("Platform")
        d = np.hypot(T.xy[:, 0] - WM_PLAT[0], T.xy[:, 1] - WM_PLAT[1]) / ppc
        tq = sum(1 for v in T.layers["quad"][0] if v == "NE quadrant") * DT
        S = "Main results"
        T.add(S, "Latency to Platform (s)", r3(f0 * DT), "s", "first frame with the body centre on the platform")
        T.add(S, "Path Length to Platform (cm)", r3(T.step[:f0 + 1].sum() / ppc), "cm", "")
        T.add(S, "Time in Target Quadrant (s)", r3(tq), "s", "NE")
        T.add(S, "% Time in Target Quadrant", round(100 * tq / 30, 2), "%", "")
        T.add(S, "Mean Distance to Platform (cm)", round(float(d.mean()), 2), "cm", "all 900 frames")
    settings = [("Experiment", "Morris Water Maze"),
                ("Outline corners (px)", "(310,30) (970,30) (970,690) (310,690) — square around the pool edge"),
                ("Pool diameter", "120 cm (5.5 px/cm)"), ("Platform quadrant", "NE"),
                ("Platform position", "56 %"), ("Platform diameter", "9.5 cm"),
                ("Wall zone", "10 %"), ("Trial type", "Training"), ("Min dwell", "0 s")]
    zones = [("Quadrants", "split by the lines x = 640 and y = 360"),
             ("Platform", f"circle at ({WM_PLAT[0]:.1f}, {WM_PLAT[1]:.1f}), radius {pr:.2f} px"),
             ("Wall zone", f"{r_wall:.0f}–{Rp} px from the pool centre")]
    return water_maze_bg, 1, p, settings, zones, extra


TESTS = {
    "open_field": ("01_Open_Field", t_open_field),
    "y_maze": ("02_Y_Maze", t_y_maze),
    "novel_object": ("03_Novel_Object", t_novel_object),
    "elevated_plus": ("04_Elevated_Plus_Maze", t_epm),
    "object_location": ("05_Object_Location", t_object_location),
    "three_chamber": ("06_Three_Chamber", t_three_chamber),
    "place_preference": ("07_Place_Preference", t_place_preference),
    "light_dark": ("08_Light_Dark_Box", t_light_dark),
    "zero_maze": ("09_Zero_Maze", t_zero_maze),
    "t_maze": ("10_T_Maze", t_t_maze),
    "radial_arm": ("11_Radial_Arm_Maze", t_radial),
    "water_maze": ("12_Water_Maze", t_water_maze),
}


# ═══ Output graphs (true versions of WIMM's graphs) ═════════════════════
GRAPHS_BY_TEST = {   # same graph set WIMM shows for each experiment
    "open_field": ["Trajectory", "Heatmap", "Cell Time", "Speed", "Speed Histogram", "Habituation", "Zone Time"],
    "novel_object": ["Trajectory", "Heatmap", "Cell Time", "Speed", "Speed Histogram", "Habituation", "Zone Time"],
    "object_location": ["Trajectory", "Heatmap", "Cell Time", "Speed", "Speed Histogram", "Habituation",
                        "Zone Time"],
    "y_maze": ["Trajectory", "Heatmap", "Speed", "Speed Histogram", "Habituation", "Zone Time", "Triplets"],
}
DEFAULT_GRAPHS = ["Trajectory", "Heatmap", "Speed", "Speed Histogram", "Habituation", "Zone Time"]
HAB_BIN_S = 5.0


def make_graphs(T, bg, key, out):
    """One PNG per graph, drawn from the exact scripted path (body centre)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(out, exist_ok=True)
    names = GRAPHS_BY_TEST.get(key, DEFAULT_GRAPHS)
    img = np.uint8(np.clip(bg, 0, 255))
    x, y = T.xy[:, 0], T.xy[:, 1]
    t = np.arange(N) * DT
    speed = T.step * FPS / T.ppc                   # cm/s; speed[k] = step from frame k-1 to k
    first = list(T.layers)[0]
    # zone outlines from the exact zone rules, sampled every 2 px
    gx, gy = np.meshgrid(np.arange(0, W, 2) + 0.5, np.arange(0, H, 2) + 0.5)
    outlines = []
    for layer, zones in T.zfun.items():
        for zname, f in zones:
            outlines.append((zname, np.vectorize(f)(gx, gy).astype(float)))
    colors = plt.rcParams["axes.prop_cycle"].by_key()["color"]

    def frame_axes(title):
        fig, ax = plt.subplots(figsize=(10, 5.8))
        ax.imshow(img)
        ax.set_xlim(0, W)
        ax.set_ylim(H, 0)
        ax.set_axis_off()
        ax.set_title(title)
        return fig, ax

    def draw_zones(ax):
        for i, (zname, m) in enumerate(outlines):
            if m.any():
                c = colors[i % len(colors)]
                ax.contour(gx, gy, m, levels=[0.5], colors=[c], linewidths=1.2)
                yy, xx = np.nonzero(m)
                ax.text(gx[0, int(np.median(xx))], gy[int(np.median(yy)), 0], zname, fontsize=7, color=c,
                        ha="center", va="center",
                        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.6))

    def save(fig, name):
        fig.savefig(os.path.join(out, f"{name}.png"), dpi=150, bbox_inches="tight")
        plt.close(fig)

    for name in names:
        if name == "Trajectory":
            fig, ax = frame_axes("Trajectory (true body-centre path)")
            draw_zones(ax)
            ax.plot(x, y, color="#1f77b4", lw=1.2)
            ax.plot(x[0], y[0], "o", color="#2ca02c", ms=7, label="start")
            ax.plot(x[-1], y[-1], "s", color="#d62728", ms=7, label="end")
            ax.legend(loc="lower right", fontsize=8)
            save(fig, name)
        elif name == "Heatmap":
            b = 8
            hg, _, _ = np.histogram2d(y, x, bins=[H // b, W // b], range=[[0, H], [0, W]])
            hg = cv2.GaussianBlur(hg * DT, (0, 0), 1.5)
            fig, ax = frame_axes("Heatmap (time spent, s per 8x8 px cell, smoothed)")
            im = ax.imshow(np.ma.masked_less(hg, hg.max() * 0.01), extent=(0, W, H, 0), cmap="inferno",
                           alpha=0.75, interpolation="bilinear")
            draw_zones(ax)
            fig.colorbar(im, ax=ax, fraction=0.03, label="s")
            save(fig, name)
        elif name == "Cell Time":
            x0, y0, x1, y1 = GRID_OF
            cw, ch = (x1 - x0) / 4, (y1 - y0) / 4
            ci = np.clip(((x - x0) // cw).astype(int), 0, 3)
            cj = np.clip(((y - y0) // ch).astype(int), 0, 3)
            grid = np.zeros((4, 4))
            np.add.at(grid, (cj, ci), DT)
            fig, ax = plt.subplots(figsize=(6, 5.4))
            im = ax.imshow(grid, cmap="viridis")
            for j in range(4):
                for i in range(4):
                    ax.text(i, j, f"Cell {j * 4 + i + 1}\n{grid[j, i]:.2f} s", ha="center", va="center",
                            fontsize=8, color="white" if grid[j, i] < grid.max() * 0.6 else "black")
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_title("Cell Time (4 x 4 grid, raw time, no min dwell)")
            fig.colorbar(im, ax=ax, label="s")
            save(fig, name)
        elif name == "Speed":
            fig, ax = plt.subplots(figsize=(10, 3.6))
            ax.plot(t[1:], speed[1:], lw=1)
            ax.set_xlabel("Time (s)")
            ax.set_ylabel("Speed (cm/s)")
            ax.set_xlim(0, 30)
            ax.set_title("Speed over time (true, frame to frame)")
            ax.grid(alpha=0.3)
            save(fig, name)
        elif name == "Speed Histogram":
            sp = speed[1:]
            fig, ax = plt.subplots(figsize=(7, 4))
            ax.hist(sp, bins=40, color="#7FA6D9", edgecolor="white")
            for v, lab, c in zip(np.percentile(sp, [50, 90, 99]), ("median", "P90", "P99"),
                                 ("#2ca02c", "#ff7f0e", "#d62728")):
                ax.axvline(v, color=c, ls="--", lw=1.2, label=f"{lab} {v:.2f} cm/s")
            ax.set_xlabel("Speed (cm/s)")
            ax.set_ylabel("Frames")
            ax.set_title("Speed histogram (899 frame-to-frame speeds)")
            ax.legend(fontsize=8)
            save(fig, name)
        elif name == "Habituation":
            nb, fb = int(30 / HAB_BIN_S), int(HAB_BIN_S * FPS)
            d = [T.step[max(1, i * fb):(i + 1) * fb].sum() / T.ppc for i in range(nb)]
            mid = (np.arange(nb) + 0.5) * HAB_BIN_S
            slope, icpt = np.polyfit(mid / 60, d, 1)
            fig, ax = plt.subplots(figsize=(7, 4))
            ax.bar(mid, d, width=HAB_BIN_S * 0.8, color="#7FA6D9")
            ax.plot(mid, icpt + slope * mid / 60, color="#d62728", lw=1.5, label=f"slope {slope:.1f} cm/min")
            for mx, v in zip(mid, d):
                ax.text(mx, v, f"{v:.1f}", ha="center", va="bottom", fontsize=8)
            ax.set_xlabel("Time (s)")
            ax.set_ylabel("Distance (cm)")
            ax.set_title(f"Habituation (distance per {HAB_BIN_S:g} s bin)")
            ax.legend(fontsize=8)
            save(fig, name)
        elif name == "Zone Time":
            layers = list(T.layers)
            fig, axes = plt.subplots(1, len(layers), figsize=(5.5 * len(layers), 4.2), squeeze=False)
            for ax, layer in zip(axes[0], layers):
                lab, zn = T.layers[layer]
                v = [sum(1 for q in lab if q == z) * DT for z in zn]
                bars = ax.bar(range(len(zn)), v, color=[colors[i % len(colors)] for i in range(len(zn))])
                for bb, val in zip(bars, v):
                    ax.text(bb.get_x() + bb.get_width() / 2, val, f"{val:.2f}", ha="center", va="bottom",
                            fontsize=8)
                ax.set_xticks(range(len(zn)))
                ax.set_xticklabels(zn, rotation=30, ha="right", fontsize=8)
                ax.set_ylabel("Time (s)")
                ax.set_title(f"Zone Time — {layer}")
            fig.tight_layout()
            save(fig, name)
        elif name == "Triplets":
            arms = [v[-1] for v, s, e in T.visits(first)]
            trip = ["".join(arms[i:i + 3]) for i in range(len(arms) - 2)]
            ok = [len(set(q)) == 3 for q in trip]
            fig, ax = plt.subplots(figsize=(max(6, len(trip) * 0.9), 2.6))
            for i, (q, good) in enumerate(zip(trip, ok)):
                ax.add_patch(plt.Rectangle((i, 0), 0.9, 1, color="#3FA34D" if good else "#D9534F"))
                ax.text(i + 0.45, 0.5, q, ha="center", va="center", color="white", fontsize=11, weight="bold")
            ax.set_xlim(-0.1, len(trip))
            ax.set_ylim(0, 1)
            ax.set_axis_off()
            ax.set_title(f"Triplets — {sum(ok)} alternations (green) of {len(trip)} "
                         f"({100 * sum(ok) / len(trip):.1f} %)")
            save(fig, name)


# ═══ Output ═════════════════════════════════════════════════════════════
def write_excel(path, name, T, settings, zones):
    wb = Workbook()
    hdr = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="2F4F6F")

    def sheet(ws, head, rows, widths):
        ws.append(head)
        for c in ws[1]:
            c.font, c.fill = hdr, fill
        for r in rows:
            ws.append(list(r))
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"

    ws = wb.active
    ws.title = "Benchmark"
    sheet(ws, ["Section", "Measure", "True value", "Unit", "How it is defined"], T.rows, [26, 40, 16, 7, 80])
    sheet(wb.create_sheet("WIMM settings"), ["Setting", "Value"], settings, [30, 110])
    sheet(wb.create_sheet("Zones"), ["Zone", "Exact definition (video pixels)"], zones, [24, 110])
    vrows = []
    for layer in T.layers:
        for v, s, e in T.visits(layer):
            vrows.append((layer, v, s, e - 1, r3(s * DT), r3(e * DT), r3((e - s) * DT)))
    sheet(wb.create_sheet("Visits"), ["Layer", "Zone", "First frame", "Last frame", "Enter (s)", "Leave (s)",
                                      "Duration (s)"], vrows, [10, 24, 11, 11, 10, 10, 12])
    ws = wb.create_sheet("Per frame")
    head = ["Frame", "Time (s)", "Body X (px)", "Body Y (px)", "Nose X (px)", "Nose Y (px)",
            "Tail-base X (px)", "Tail-base Y (px)", "Heading (deg)", "Step (px)", "Step (cm)", "Moving"]
    head += [f"Zone: {k}" for k in T.layers]
    rows = []
    for i in range(N):
        r = [i, r3(i * DT), round(T.xy[i, 0], 3), round(T.xy[i, 1], 3), round(T.nose[i, 0], 3),
             round(T.nose[i, 1], 3), round(T.tail[i, 0], 3), round(T.tail[i, 1], 3), int(T.hd[i]),
             round(T.step[i], 4), round(T.step[i] / T.ppc, 4), bool(T.moving[i])]
        rows.append(r + [T.layers[k][0][i] for k in T.layers])
    sheet(ws, head, rows, [7, 8] + [12] * 10 + [18] * len(T.layers))
    notes = [
        ("What this is", f"Benchmark for {name}: the mouse follows a script, so these values are exact."),
        ("Video", "30.000 s, 30 fps, 900 frames (frame k is at k/30 s), 1280 x 720, mp4v."),
        ("Tracking point", "Body centre = centre of the drawn body without tail and shadow. "
                           "Nose = tip of the snout. Both are listed per frame."),
        ("Zone rule", "A frame belongs to a zone when the point is inside it; no minimum dwell. "
                      "Set Min dwell = 0 in WIMM. Times are frame counts / 30."),
        ("Expected differences", "A tracker finds the blob centre, not the exact body centre, and video "
                                 "compression adds noise: expect zone times within ~1–3 frames (0.03–0.1 s) per "
                                 "boundary crossing, and a slightly larger distance (jitter adds length while still)."),
        ("Re-make", "make_validation_videos.py in this folder rebuilds the video and this file."),
    ]
    sheet(wb.create_sheet("Read me"), ["Item", "Note"], notes, [22, 120])
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                c.alignment = Alignment(vertical="top", wrap_text=ws.title in ("Read me", "WIMM settings"))
    wb.save(path)


def self_check(T):
    for name, (lab, zs) in T.layers.items():
        tot = sum(sum(1 for v in lab if v == z) for z in zs) + sum(1 for v in lab if not v)
        assert tot == N, name
    assert abs(T.step.sum() - sum(math.dist(T.xy[i], T.xy[i + 1]) for i in range(N - 1))) < 1e-6


def build(key, out_root, graphs_only=False):
    folder, fn = TESTS[key]
    arena_fn, test_call, path, settings, zones, extra = fn()
    bg, m = render_background(arena_fn, test_call)
    sprite = Sprite(m["size"], m["color"], m["tail_curl"])
    xy, hd = path.done()
    T = Truth(xy, hd, sprite, path.ppc)
    T.locomotion()
    extra(T)
    self_check(T)
    out = os.path.join(out_root, folder)
    os.makedirs(out, exist_ok=True)
    make_graphs(T, bg, key, os.path.join(out, "Output graphs"))
    if graphs_only:
        print("graphs", folder)
        return
    vid = os.path.join(out, f"{folder}.mp4")
    vw = cv2.VideoWriter(vid, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    vign = vignette()
    seed = list(TESTS).index(key) + 1
    for k in range(N):
        img = bg.copy()
        sprite.draw(img, xy[k, 0], xy[k, 1], int(hd[k]))
        vw.write(cv2.cvtColor(finish_frame(img, k, vign, seed), cv2.COLOR_RGB2BGR))
    vw.release()
    if int(cv2.VideoCapture(vid).get(cv2.CAP_PROP_FRAME_COUNT)) != N:
        raise RuntimeError(f"{vid}: frame count is not {N}")
    write_excel(os.path.join(out, f"{folder}_benchmark.xlsx"), folder, T, settings, zones)
    print("done", folder)


if __name__ == "__main__":
    args = sys.argv[1:]
    g = "--graphs" in args             # graphs only, keep the video / Excel
    args = [a for a in args if a != "--graphs"]
    here_key = next((k for k, (f, _) in TESTS.items() if f == os.path.basename(HERE)), None)
    if args == ["--all"]:
        for k in TESTS:
            build(k, HERE, g)
    elif args:
        for k in args:
            build(k, HERE, g)
    elif here_key:
        build(here_key, os.path.dirname(HERE), g)
    else:
        print(__doc__)
