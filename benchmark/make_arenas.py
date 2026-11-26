"""Synthetic top-down camera frames of rodent behaviour arenas, for the
WIMM help pages. Each frame: 1280x720, arena seen from above, one or more
mice, light sensor noise + vignette so it reads like a tracking video."""
import math
import os
import random
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 1280, 720
SS = 3                     # supersampling factor
OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
os.makedirs(OUT, exist_ok=True)

BENCH = (46, 47, 49)
FLOOR = (196, 197, 192)
FLOOR_DARK = (150, 151, 148)
WALL = (92, 93, 96)
WALL_TOP = (128, 129, 132)
BLACK_MOUSE = (28, 27, 29)
WHITE_MOUSE = (236, 232, 226)


def S(v):
    return v * SS


def P(pts):
    return [(S(x), S(y)) for x, y in pts]


class Frame:
    def __init__(self, bg=BENCH, seed=0):
        self.img = Image.new("RGB", (S(W), S(H)), bg)
        self.d = ImageDraw.Draw(self.img)
        self.rng = random.Random(seed)

    # ── primitives (final-pixel coordinates)
    def poly(self, pts, fill, outline=None, width=0):
        self.d.polygon(P(pts), fill=fill, outline=outline, width=int(S(width)) if width else 0)

    def rect(self, x0, y0, x1, y1, fill, outline=None, width=0, r=0):
        box = [S(x0), S(y0), S(x1), S(y1)]
        if r:
            self.d.rounded_rectangle(box, S(r), fill=fill, outline=outline, width=S(width))
        else:
            self.d.rectangle(box, fill=fill, outline=outline, width=S(width))

    def circle(self, cx, cy, r, fill, outline=None, width=0):
        self.d.ellipse([S(cx - r), S(cy - r), S(cx + r), S(cy + r)], fill=fill,
                       outline=outline, width=int(S(width)) if width else 0)

    def line(self, pts, fill, width):
        self.d.line(P(pts), fill=fill, width=int(round(S(width))), joint="curve")
        for x, y in (pts[0], pts[-1]):
            self.circle(x, y, width / 2, fill)

    def walls(self, pts, width=12, closed=True):
        """A wall drawn as a thick dark band with a lighter top edge."""
        pts = list(pts) + ([pts[0]] if closed else [])
        self.line(pts, WALL, width)
        self.line(pts, WALL_TOP, max(2, width * 0.35))

    def floor_texture(self, box, strength=6):
        """Subtle mottling on an arena floor inside box (x0,y0,x1,y1)."""
        x0, y0, x1, y1 = [S(v) for v in box]
        w, h = x1 - x0, y1 - y0
        noise = np.random.default_rng(self.rng.randint(0, 1 << 30)).normal(0, 1, (h // 15 + 2, w // 15 + 2))
        tex = Image.fromarray(np.uint8(np.clip(128 + noise * strength * 2.2, 0, 255))).resize(
            (w, h), Image.BICUBIC).convert("L")
        region = self.img.crop((x0, y0, x1, y1))
        arr = np.asarray(region).astype(np.float32)
        t = (np.asarray(tex).astype(np.float32) - 128)[..., None] / 3
        mask = (arr.sum(axis=2) > 300)[..., None]          # only light floor
        arr = np.where(mask, arr + t, arr)
        self.img.paste(Image.fromarray(np.uint8(np.clip(arr, 0, 255))), (x0, y0))

    # ── objects
    def mouse(self, x, y, angle, size=1.0, color=BLACK_MOUSE, tail_curl=0.6, shadow=True):
        """Top view of a mouse centred at (x, y), heading `angle` degrees
        (0 = right, 90 = down). size 1.0 ≈ 78 px nose-to-rump."""
        k = S(size)
        box = int(260 * k)
        layer = Image.new("RGBA", (box, box), (0, 0, 0, 0))
        g = ImageDraw.Draw(layer)
        c = box / 2

        def e(cx, cy, rx, ry, fill):
            g.ellipse([c + (cx - rx) * k, c + (cy - ry) * k, c + (cx + rx) * k, c + (cy + ry) * k], fill=fill)

        white = color[0] > 128
        ear = (228, 178, 176) if white else (52, 48, 50)
        tail_c = (222, 176, 170) if white else (70, 64, 66)
        # tail: tapered curve from the rump
        pts = []
        for i in range(26):
            t = i / 25
            tx = -36 - t * 64
            ty = math.sin(t * math.pi * 1.1) * 16 * tail_curl * (1 + t)
            pts.append((c + tx * k, c + ty * k))
        for i in range(len(pts) - 1):
            wdt = (4.2 - 3.0 * i / len(pts)) * k
            g.line([pts[i], pts[i + 1]], fill=tail_c + (255,), width=max(1, int(wdt)))
        # body
        e(-12, 0, 27, 18.5, color + (255,))
        e(10, 0, 22, 15.5, color + (255,))
        e(29, 0, 13, 11, color + (255,))
        g.polygon([(c + 36 * k, c - 7 * k), (c + 49 * k, c), (c + 36 * k, c + 7 * k)], fill=color + (255,))
        # ears + eyes
        e(25, -11, 6.5, 6, ear + (255,))
        e(25, 11, 6.5, 6, ear + (255,))
        eye = (170, 40, 50) if white else (8, 8, 8)
        e(36, -5.5, 1.8, 1.8, eye + (255,))
        e(36, 5.5, 1.8, 1.8, eye + (255,))
        # soft fur highlight along the back
        hl = Image.new("RGBA", (box, box), (0, 0, 0, 0))
        hg = ImageDraw.Draw(hl)
        tone = (255, 255, 255, 34) if not white else (0, 0, 0, 16)
        hg.ellipse([c - 30 * k, c - 8 * k, c + 22 * k, c + 6 * k], fill=tone)
        hl = hl.filter(ImageFilter.GaussianBlur(4 * k))
        layer = Image.alpha_composite(layer, hl)
        rot = layer.rotate(-angle, resample=Image.BICUBIC, expand=False)
        ox, oy = int(S(x) - box / 2), int(S(y) - box / 2)
        if shadow:
            a = np.asarray(rot)[..., 3]
            sh = Image.fromarray((a * 0.45).astype(np.uint8)).filter(ImageFilter.GaussianBlur(5 * k))
            self.img.paste((0, 0, 0), (ox + int(3 * k), oy + int(4 * k)), sh)
        self.img.paste(rot, (ox, oy), rot)

    def cylinder(self, cx, cy, r, col=(70, 110, 160)):
        self.circle(cx + 3, cy + 5, r, (120, 120, 117))
        self.circle(cx, cy, r, tuple(int(v * 0.7) for v in col))
        self.circle(cx - r * 0.12, cy - r * 0.12, r * 0.8, col)
        self.circle(cx - r * 0.3, cy - r * 0.3, r * 0.25, tuple(min(255, v + 60) for v in col))

    def block(self, cx, cy, s, col=(190, 120, 60)):
        self.rect(cx - s + 4, cy - s + 5, cx + s + 4, cy + s + 5, (90, 90, 90))
        self.rect(cx - s, cy - s, cx + s, cy + s, tuple(int(v * 0.75) for v in col), r=3)
        self.rect(cx - s + 4, cy - s + 4, cx + s - 4, cy + s - 4, col, r=2)

    def wire_cup(self, cx, cy, r):
        self.circle(cx, cy, r, (150, 152, 150))
        for i in range(24):
            a = i / 24 * math.tau
            self.line([(cx + math.cos(a) * r * 0.25, cy + math.sin(a) * r * 0.25),
                       (cx + math.cos(a) * r, cy + math.sin(a) * r)], (70, 72, 74), 2)
        self.circle(cx, cy, r, None, (60, 62, 64), 4)
        self.circle(cx, cy, r * 0.25, (110, 112, 114))

    def finish(self, name, seed=0):
        img = self.img.resize((W, H), Image.LANCZOS)
        arr = np.asarray(img).astype(np.float32)
        yy, xx = np.mgrid[0:H, 0:W]
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
        vign = 1 - 0.22 * np.clip(r - 0.35, 0, None) ** 1.5
        arr *= vign[..., None]
        noise = np.random.default_rng(seed).normal(0, 3.2, (H, W, 1))
        arr += noise
        arr = 0.92 * arr + 0.08 * arr.mean(axis=2, keepdims=True)   # slight desaturation
        out = Image.fromarray(np.uint8(np.clip(arr, 0, 255))).filter(ImageFilter.GaussianBlur(0.45))
        path = os.path.join(OUT, name + ".png")
        out.save(path, optimize=True)
        return path


def arm_poly(cx, cy, angle, length, width, start=0):
    a = math.radians(angle)
    dx, dy = math.cos(a), math.sin(a)
    nx, ny = -dy, dx
    hw = width / 2
    p0 = (cx + dx * start, cy + dy * start)
    p1 = (cx + dx * length, cy + dy * length)
    return [(p0[0] + nx * hw, p0[1] + ny * hw), (p1[0] + nx * hw, p1[1] + ny * hw),
            (p1[0] - nx * hw, p1[1] - ny * hw), (p0[0] - nx * hw, p0[1] - ny * hw)]


def open_field():
    f = Frame(seed=1)
    x0, y0, s = 370, 90, 540
    f.rect(x0, y0, x0 + s, y0 + s, FLOOR)
    f.floor_texture((x0, y0, x0 + s, y0 + s))
    f.walls([(x0, y0), (x0 + s, y0), (x0 + s, y0 + s), (x0, y0 + s)], 16)
    f.mouse(x0 + 150, y0 + 400, -35, 1.25)
    return f.finish("01_open_field", 1)


def y_maze():
    f = Frame(seed=2)
    cx, cy, L, w = 640, 410, 300, 86
    hw = w / 2
    arms = [-90, 30, 150]
    rc = hw / math.sin(math.radians(60))      # centre → inner corner
    outline = []
    for a in arms:
        ar = math.radians(a)
        dx, dy = math.cos(ar), math.sin(ar)
        cprev = math.radians(a - 60)
        outline.append((cx + rc * math.cos(cprev), cy + rc * math.sin(cprev)))
        ex, ey = cx + dx * L, cy + dy * L
        outline.append((ex + dy * hw, ey - dx * hw))      # side toward a-90
        outline.append((ex - dy * hw, ey + dx * hw))      # side toward a+90
    f.poly(outline, FLOOR)
    f.floor_texture((0, 0, W, H))
    f.walls(outline, 14)
    a = math.radians(30)
    f.mouse(cx + 170 * math.cos(a), cy + 170 * math.sin(a), 30 + 180, 1.0)
    return f.finish("02_y_maze", 2)


def novel_object():
    f = Frame(seed=3)
    x0, y0, s = 370, 90, 540
    f.rect(x0, y0, x0 + s, y0 + s, FLOOR)
    f.floor_texture((x0, y0, x0 + s, y0 + s))
    f.cylinder(x0 + 150, y0 + 150, 34, (80, 120, 170))
    f.block(x0 + 390, y0 + 390, 30, (196, 128, 64))
    f.walls([(x0, y0), (x0 + s, y0), (x0 + s, y0 + s), (x0, y0 + s)], 16)
    f.mouse(x0 + 320, y0 + 320, 45, 1.15)
    return f.finish("03_novel_object", 3)


def elevated_plus():
    f = Frame(bg=(24, 25, 27), seed=4)
    cx, cy, L, w = 640, 360, 330, 66
    # open arms (left/right) — no walls, rim only
    for a in (0, 180):
        f.poly(arm_poly(cx, cy, a, L, w, w / 2), (205, 205, 200))
    # closed arms (up/down) — high walls
    for a in (90, 270):
        q = arm_poly(cx, cy, a, L * 0.98 if a == 90 else L * 0.98, w, w / 2)
        q = arm_poly(cx, cy, a, 330 if a == 90 else 330, w, w / 2)
    for a in (90, -90):
        Lc = 320
        f.poly(arm_poly(cx, cy, a, Lc, w, w / 2), (185, 185, 182))
    f.rect(cx - w / 2, cy - w / 2, cx + w / 2, cy + w / 2, (205, 205, 200))
    f.floor_texture((0, 0, W, H), 4)
    # closed-arm walls (thick, fading — tall walls seen from above)
    for sgn in (-1, 1):
        y_end = cy + sgn * 330 if False else cy + sgn * 320
        for xw in (cx - w / 2, cx + w / 2):
            f.line([(xw, cy + sgn * w / 2), (xw, y_end)], WALL, 18)
            f.line([(xw, cy + sgn * w / 2), (xw, y_end)], WALL_TOP, 6)
        f.line([(cx - w / 2, y_end), (cx + w / 2, y_end)], WALL, 18)
        f.line([(cx - w / 2, y_end), (cx + w / 2, y_end)], WALL_TOP, 6)
    # small lip on the open arms
    for sgn in (-1, 1):
        for yy in (cy - w / 2, cy + w / 2):
            f.line([(cx + sgn * w / 2, yy), (cx + sgn * L, yy)], (150, 150, 148), 3)
    f.mouse(cx + 150, cy, 180 + 8, 0.82)
    return f.finish("04_elevated_plus", 4)


def object_location():
    f = Frame(seed=5)
    x0, y0, s = 370, 90, 540
    f.rect(x0, y0, x0 + s, y0 + s, FLOOR)
    f.floor_texture((x0, y0, x0 + s, y0 + s))
    # visual cue on the north wall
    for i in range(7):
        f.rect(x0 + 170 + i * 30, y0 + 10, x0 + 185 + i * 30, y0 + 40, (40, 40, 42))
    f.cylinder(x0 + 140, y0 + 150, 32, (90, 140, 110))
    f.cylinder(x0 + 400, y0 + 400, 32, (90, 140, 110))      # moved object
    f.circle(x0 + 400, y0 + 150, 32, None, (150, 150, 146), 2)   # its old place, faint mark
    f.walls([(x0, y0), (x0 + s, y0), (x0 + s, y0 + s), (x0, y0 + s)], 16)
    f.mouse(x0 + 330, y0 + 340, 40, 1.15)
    return f.finish("05_object_location", 5)


def three_chamber():
    f = Frame(seed=6)
    x0, y0, w, h = 190, 160, 900, 400
    f.rect(x0, y0, x0 + w, y0 + h, FLOOR)
    f.floor_texture((x0, y0, x0 + w, y0 + h))
    f.walls([(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)], 14)
    door = 90
    for xx in (x0 + w / 3, x0 + 2 * w / 3):
        f.walls([(xx, y0), (xx, y0 + h / 2 - door / 2)], 12, closed=False)
        f.walls([(xx, y0 + h / 2 + door / 2), (xx, y0 + h)], 12, closed=False)
    f.wire_cup(x0 + w / 6, y0 + h / 2, 62)
    f.mouse(x0 + w / 6 - 4, y0 + h / 2 + 2, 120, 0.72, color=(70, 66, 64), shadow=False)  # stranger under cup
    for i in range(24):      # redraw cup bars over the stranger
        a = i / 24 * math.tau
        r = 62
        f.line([(x0 + w / 6 + math.cos(a) * r * 0.25, y0 + h / 2 + math.sin(a) * r * 0.25),
                (x0 + w / 6 + math.cos(a) * r, y0 + h / 2 + math.sin(a) * r)], (110, 112, 114), 2)
    f.circle(x0 + w / 6, y0 + h / 2, 62, None, (60, 62, 64), 4)
    f.wire_cup(x0 + 5 * w / 6, y0 + h / 2, 62)
    f.mouse(x0 + w / 3 - 60, y0 + h / 2 + 60, 200, 1.0)
    return f.finish("06_three_chamber", 6)


def place_preference():
    f = Frame(seed=7)
    x0, y0, h = 170, 170, 380
    cw, mid = 380, 180
    xs = [x0, x0 + cw, x0 + cw + mid, x0 + 2 * cw + mid]
    # chamber A: grid-rod floor; B (middle): plain; C: perforated floor
    f.rect(xs[0], y0, xs[1], y0 + h, (175, 176, 172))
    for i in range(int(cw / 18)):
        f.line([(xs[0] + 9 + i * 18, y0), (xs[0] + 9 + i * 18, y0 + h)], (120, 121, 118), 5)
    f.rect(xs[1], y0 + 80, xs[2], y0 + h - 80, FLOOR)
    f.rect(xs[2], y0, xs[3], y0 + h, (215, 214, 208))
    for i in range(14):
        for j in range(14):
            f.circle(xs[2] + 16 + i * 26.5 + (j % 2) * 13, y0 + 14 + j * 27, 4, (160, 160, 156))
    f.floor_texture((x0, y0, xs[3], y0 + h), 4)
    f.walls([(xs[0], y0), (xs[1], y0), (xs[1], y0 + 80), (xs[2], y0 + 80), (xs[2], y0),
             (xs[3], y0), (xs[3], y0 + h), (xs[2], y0 + h), (xs[2], y0 + h - 80),
             (xs[1], y0 + h - 80), (xs[1], y0 + h), (xs[0], y0 + h)], 14)
    for xx in (xs[1], xs[2]):    # guillotine doors (open)
        f.walls([(xx, y0 + 80), (xx, y0 + 140)], 10, closed=False)
        f.walls([(xx, y0 + h - 140), (xx, y0 + h - 80)], 10, closed=False)
    f.mouse(xs[2] + 150, y0 + 220, -20, 1.0)
    return f.finish("07_place_preference", 7)


def light_dark():
    f = Frame(seed=8)
    x0, y0, w, h = 260, 140, 760, 440
    split = x0 + w * 0.6
    f.rect(x0, y0, split, y0 + h, (226, 226, 220))
    f.floor_texture((x0, y0, int(split), y0 + h), 4)
    f.rect(split, y0, x0 + w, y0 + h, (30, 30, 32))      # covered dark side (lid)
    for i in range(8):
        f.line([(split + 20, y0 + 30 + i * 55), (x0 + w - 20, y0 + 30 + i * 55)], (40, 40, 43), 2)
    f.walls([(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)], 16)
    f.walls([(split, y0), (split, y0 + h / 2 - 45)], 14, closed=False)
    f.walls([(split, y0 + h / 2 + 45), (split, y0 + h)], 14, closed=False)
    # bright light pool
    f.mouse(split - 120, y0 + h / 2 + 30, -160, 1.15)
    return f.finish("08_light_dark_box", 8)


def zero_maze():
    f = Frame(bg=(24, 25, 27), seed=9)
    cx, cy, R, w = 640, 360, 280, 64
    f.circle(cx, cy, R + w / 2, (200, 200, 196))
    f.circle(cx, cy, R - w / 2, (24, 25, 27))
    f.floor_texture((0, 0, W, H), 4)
    # two closed quadrants with inner + outer walls
    for start in (20, 200):
        for rr in (R - w / 2, R + w / 2):
            box = [S(cx - rr), S(cy - rr), S(cx + rr), S(cy + rr)]
            f.d.arc(box, start, start + 140, fill=WALL, width=int(S(16)))
            f.d.arc(box, start, start + 140, fill=WALL_TOP, width=S(5))
    a = math.radians(150)
    f.mouse(cx + R * math.cos(a), cy + R * math.sin(a), 150 + 90 + 10, 0.85)
    return f.finish("09_zero_maze", 9)


def t_maze():
    f = Frame(seed=10)
    w = 84
    top, left, right = 150, 250, 1030
    stem_x, bottom = 640, 640
    outline = [(left, top), (right, top), (right, top + w), (stem_x + w / 2, top + w),
               (stem_x + w / 2, bottom), (stem_x - w / 2, bottom), (stem_x - w / 2, top + w), (left, top + w)]
    f.poly(outline, FLOOR)
    f.floor_texture((0, 0, W, H))
    f.walls(outline, 14)
    f.circle(left + 40, top + w / 2, 12, (230, 230, 224), (120, 120, 118), 2)    # reward wells
    f.circle(right - 40, top + w / 2, 12, (230, 230, 224), (120, 120, 118), 2)
    f.mouse(stem_x, top + w + 120, -90, 1.0)
    return f.finish("10_t_maze", 10)


def radial_arm():
    f = Frame(bg=(28, 29, 31), seed=11)
    cx, cy, L, w = 640, 360, 330, 54
    hub = 70
    for i in range(8):
        f.poly(arm_poly(cx, cy, i * 45 + 22.5, L, w, hub * 0.8), FLOOR)
    oct_ = [(cx + hub * math.cos(math.radians(i * 45)), cy + hub * math.sin(math.radians(i * 45))) for i in range(8)]
    f.poly(oct_, FLOOR)
    f.floor_texture((0, 0, W, H), 4)
    for i in range(8):
        q = arm_poly(cx, cy, i * 45 + 22.5, L, w, hub * 0.85)
        f.walls([q[0], q[1]], 6, closed=False)
        f.walls([q[3], q[2]], 6, closed=False)
        f.walls([q[1], q[2]], 6, closed=False)
        a = math.radians(i * 45 + 22.5)
        f.circle(cx + math.cos(a) * (L - 22), cy + math.sin(a) * (L - 22), 9, (232, 232, 226), (120, 120, 118), 2)
    a = math.radians(3 * 45 + 22.5)
    f.mouse(cx + math.cos(a) * 170, cy + math.sin(a) * 170, 3 * 45 + 22.5, 0.82)
    return f.finish("11_radial_arm_maze", 11)


def water_maze():
    f = Frame(bg=(36, 37, 40), seed=12)
    cx, cy, R = 640, 360, 330
    f.circle(cx, cy, R + 16, (140, 142, 146))           # pool rim
    f.circle(cx, cy, R, (206, 210, 214))                # opaque water
    f.floor_texture((cx - R, cy - R, cx + R, cy + R), 5)
    # faint quadrant lines are virtual — the hidden platform shows only faintly
    f.circle(cx + 140, cy - 120, 26, (198, 202, 206), (190, 194, 198), 2)
    mx, my = cx - 120, cy + 90
    for i, rr in enumerate((70, 55, 42)):               # ripples behind the swimmer
        f.d.arc([S(mx - 40 - rr), S(my + 25 - rr), S(mx - 40 + rr), S(my + 25 + rr)],
                180 + 20, 360 - 60, fill=(225, 228, 232), width=S(2))
    f.mouse(mx, my, -35, 1.0, tail_curl=0.2)
    return f.finish("12_water_maze", 12)


if __name__ == "__main__":
    for fn in (open_field, y_maze, novel_object, elevated_plus, object_location, three_chamber,
               place_preference, light_dark, zero_maze, t_maze, radial_arm, water_maze):
        print(fn())
