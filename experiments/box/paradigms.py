"""The box-family tests. Each one only declares its settings, zones and
main results; everything else comes from BoxExperiment.

Box space: u runs left → right, v top → bottom, both 0 … 1 across the
arena the user outlined. Physical sizes in cm are turned into box units
with the apparatus size from the Scale card (dims = (W, H) cm).
"""
import math

from core.kinematics import time_at

from .base import BoxExperiment, ParamSpec as P
from .engine import ZoneDef, OUT, committed_sequence
from . import geometry as geo

_LAYOUT = [("h", "Side by side"), ("v", "Stacked")]


def _strip(lo, hi, layout):
    """Band of the box between lo and hi along the layout axis."""
    return geo.rect(lo, 0, hi, 1) if layout == "h" else geo.rect(0, lo, 1, hi)


def _pt(a, b, layout):
    """(along, across) → (u, v)."""
    return (a, b) if layout == "h" else (b, a)


def _ratio(a, b):
    return round((a - b) / (a + b), 3) if (a + b) > 0 else None


def _transitions(stats, names):
    seq = [z for z in committed_sequence(stats) if z in names]
    return sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])


# ═══ Conditioned place preference ═══════════════════════════════════════
class PlacePreference(BoxExperiment):
    key = "cpp"
    name = "Place Preference"
    results_title = "CPP"
    arena_hint = "Click the 4 corners of the whole apparatus (all compartments)."
    scale = ("rect", 60.0, 30.0)
    PARAMS = [
        P("n_comp", "Compartments", "choice", 3,
          [(3, "3 (with neutral)"), (2, "2")],
          tip="Two compartments, or two with a neutral middle compartment."),
        P("neutral_pct", "Neutral width", "pct", 20, lo=5, hi=50,
          tip="Width of the middle compartment as % of the apparatus length.",
          show_if=lambda p: int(p["n_comp"]) == 3),
        P("layout", "Layout", "choice", "h", _LAYOUT,
          tip="Compartments side by side or stacked, as seen in the video."),
        P("paired", "Drug-paired", "choice", "A", per_video=True, options=
          [("A", "Compartment A"), ("B", "Compartment B")],
          tip="Which compartment was paired with the drug / stimulus. "
              "A is the left (or top) one."),
    ]
    COLORS = {"A": ("A", "#E8A87C"), "B": ("B", "#7FA6D9"),
              "N": ("Neutral", "#A9B4C6")}

    def zones(self, p, dims, c):
        lay = p["layout"]
        if int(p["n_comp"]) == 3:
            w = float(p["neutral_pct"]) / 100.0
            a, b = (1 - w) / 2, (1 + w) / 2
        else:
            a = b = 0.5
        zs = [ZoneDef("A", "Compartment A", _strip(0, a, lay), "compartment",
                      color=c["A"], label_pos=_pt(a / 2, 0.5, lay))]
        if int(p["n_comp"]) == 3:
            zs.append(ZoneDef("N", "Neutral", _strip(a, b, lay), "compartment",
                              color=c["N"], label_pos=_pt(0.5, 0.5, lay)))
        zs.append(ZoneDef("B", "Compartment B", _strip(b, 1, lay), "compartment",
                          color=c["B"], label_pos=_pt((1 + b) / 2, 0.5, lay)))
        return zs

    def main_keys(self, p):
        return ["Time in Paired (s)", "Time in Unpaired (s)",
                "% Time in Paired", "Preference Score (s)",
                "Entries into Paired (#)", "Entries into Unpaired (#)",
                "Latency to Paired (s)", "Paired Compartment"]

    def primary(self, ctx, m, p, dims):
        pa = "Compartment A" if p["paired"] == "A" else "Compartment B"
        un = "Compartment B" if p["paired"] == "A" else "Compartment A"
        tp = m.get(f"Time in {pa} (s)", 0.0)
        tu = m.get(f"Time in {un} (s)", 0.0)
        return {
            "Paired Compartment": pa,
            "Time in Paired (s)": tp,
            "Time in Unpaired (s)": tu,
            "% Time in Paired": round(100 * tp / (tp + tu), 2) if (tp + tu) > 0 else None,
            "Preference Score (s)": round(tp - tu, 3),
            "Entries into Paired (#)": m.get(f"Entries into {pa} (#)", 0),
            "Entries into Unpaired (#)": m.get(f"Entries into {un} (#)", 0),
            "Latency to Paired (s)": m.get(f"Latency to {pa} (s)"),
        }

    def zones_summary(self, p):
        return f"{p['n_comp']} compartments · paired {p['paired']}"


# ═══ Light–dark box ═════════════════════════════════════════════════════
class LightDark(BoxExperiment):
    key = "light_dark"
    name = "Light–Dark Box"
    results_title = "Light–Dark"
    arena_hint = "Click the 4 corners of the whole box (light + dark side)."
    scale = ("rect", 45.0, 27.0)
    PARAMS = [
        P("dark_pct", "Dark side", "pct", 33, lo=15, hi=60,
          tip="Size of the dark compartment as % of the box length "
              "(standard: one third)."),
        P("dark_side", "Dark side is", "choice", "R",
          [("R", "Right"), ("L", "Left"), ("T", "Top"), ("B", "Bottom")]),
        P("lost_dark", "Count lost frames as dark", "toggle", False,
          tip="When the camera cannot see inside the dark side, frames where "
              "the mouse is not detected are counted as time in the dark."),
    ]
    COLORS = {"light": ("Light", "#E8C547"), "dark": ("Dark", "#5B6B8C")}

    def zones(self, p, dims, c):
        d = float(p["dark_pct"]) / 100.0
        side = p["dark_side"]
        lay = "h" if side in ("L", "R") else "v"
        if side in ("R", "B"):
            light, dark = (0, 1 - d), (1 - d, 1)
        else:
            dark, light = (0, d), (d, 1)
        return [
            ZoneDef("light", "Light", _strip(*light, lay), "side",
                    color=c["light"], label_pos=_pt(sum(light) / 2, 0.5, lay)),
            ZoneDef("dark", "Dark", _strip(*dark, lay), "side",
                    color=c["dark"], label_pos=_pt(sum(dark) / 2, 0.5, lay),
                    fill_alpha=70),
        ]

    def engine_settings(self, p):
        return {"_undetected_as": {"side": "dark"}} if p.get("lost_dark") else {}

    def main_keys(self, p):
        return ["Time in Light (s)", "% Time in Light", "Time in Dark (s)",
                "Transitions (#)", "Latency to Dark (s)", "Latency to Light (s)",
                "Entries into Light (#)"]

    def primary(self, ctx, m, p, dims):
        return {"Transitions (#)": _transitions(ctx["stats"]["side"], {"light", "dark"})}

    def zones_summary(self, p):
        names = {"R": "right", "L": "left", "T": "top", "B": "bottom"}
        return f"dark {p['dark_pct']}% · {names[p['dark_side']]}"


# ═══ Three-chamber social test ══════════════════════════════════════════
class ThreeChamber(BoxExperiment):
    key = "three_chamber"
    name = "Three-Chamber Social"
    results_title = "Social"
    arena_hint = "Click the 4 corners of the whole three-chamber box."
    scale = ("rect", 60.0, 40.0)
    uses_nose = True
    PARAMS = [
        P("phase", "Phase", "choice", "soc",
          [("soc", "Sociability"), ("nov", "Social novelty")],
          tip="Sociability: stranger mouse vs empty cup. Social novelty: "
              "novel mouse vs familiar mouse."),
        P("target_side", "Stranger / novel in", "choice", "L", per_video=True, options=
          [("L", "Left / top"), ("R", "Right / bottom")],
          tip="Chamber holding the stranger (sociability) or novel mouse."),
        P("center_pct", "Center chamber", "pct", 33, lo=15, hi=50,
          tip="Width of the middle chamber as % of the box length."),
        P("layout", "Layout", "choice", "h", _LAYOUT),
        P("cup_pos", "Cups placed", "choice", "mid",
          [("mid", "Chamber middle"), ("c1", "Top / left corners"),
           ("c2", "Bottom / right corners")],
          tip="Where the two cups stand in the side chambers."),
        P("cup_cm", "Cup diameter", "cm", 10.0, lo=2, hi=30),
        P("sniff_cm", "Sniff zone", "cm", 3.0, lo=0.5, hi=10,
          tip="How far around the cup counts as sniffing (nose position; "
              "usually 2–3 cm)."),
    ]
    COLORS = {"target": ("Target", "#E8A87C"),
              "other": ("Other", "#7FA6D9"),
              "center": ("Center", "#A9B4C6")}

    @staticmethod
    def roles(p):
        return ("Stranger", "Empty") if p["phase"] == "soc" else ("Novel", "Familiar")

    def zones(self, p, dims, c):
        lay = p["layout"]
        w = float(p["center_pct"]) / 100.0
        a, b = (1 - w) / 2, (1 + w) / 2
        T, O = self.roles(p)
        left_is_target = p["target_side"] == "L"
        lt, rt = ((T, "target"), (O, "other")) if left_is_target else ((O, "other"), (T, "target"))
        zs = [
            ZoneDef("left", f"{lt[0]} Chamber", _strip(0, a, lay), "chamber",
                    color=c[lt[1]], label_pos=_pt(a / 2, 0.12, lay)),
            ZoneDef("center", "Center Chamber", _strip(a, b, lay), "chamber",
                    color=c["center"], label_pos=_pt(0.5, 0.12, lay)),
            ZoneDef("right", f"{rt[0]} Chamber", _strip(b, 1, lay), "chamber",
                    color=c[rt[1]], label_pos=_pt((1 + b) / 2, 0.12, lay)),
        ]
        W, H = dims
        L_along, L_across = (W, H) if lay == "h" else (H, W)
        r_cup = float(p["cup_cm"]) / 2.0
        r = r_cup + float(p["sniff_cm"])
        ra, rc = r / L_along, r / L_across           # radius in box units
        gap_a = (r_cup + 1.0) / L_along
        gap_c = (r_cup + 1.0) / L_across
        if p["cup_pos"] == "mid":
            centers = [(a / 2, 0.5), ((1 + b) / 2, 0.5)]
        elif p["cup_pos"] == "c1":
            centers = [(gap_a, gap_c), (1 - gap_a, gap_c)]
        else:
            centers = [(gap_a, 1 - gap_c), (1 - gap_a, 1 - gap_c)]
        for (zid, (role, ck)), (ca, cc) in zip((("cup_left", lt), ("cup_right", rt)), centers):
            cu, cv = _pt(ca, cc, lay)
            ru, rv = (ra, rc) if lay == "h" else (rc, ra)
            poly = geo.ellipse(cu, cv, ru, rv)
            zs.append(ZoneDef(zid, f"{role} sniff zone", poly, "sniff", point="nose",
                              color=c[ck], dashed=True, fill_alpha=0,
                              label_pos=(cu, min(0.95, cv + rv + 0.04))))
        return zs

    def main_keys(self, p):
        T, O = self.roles(p)
        idx = "Sociability Index" if p["phase"] == "soc" else "Social Novelty Index"
        return [f"Time in {T} Chamber (s)", f"Time in {O} Chamber (s)",
                "Time in Center Chamber (s)",
                f"Time in {T} sniff zone (s)", f"Time in {O} sniff zone (s)",
                f"{idx} (chamber)", f"{idx} (sniffing)",
                f"Entries into {T} Chamber (#)", f"Entries into {O} Chamber (#)",
                f"Latency to {T} sniff zone (s)", "Phase"]

    def primary(self, ctx, m, p, dims):
        T, O = self.roles(p)
        idx = "Sociability Index" if p["phase"] == "soc" else "Social Novelty Index"
        return {
            "Phase": "Sociability" if p["phase"] == "soc" else "Social novelty",
            f"{idx} (chamber)": _ratio(m.get(f"Time in {T} Chamber (s)", 0.0),
                                       m.get(f"Time in {O} Chamber (s)", 0.0)),
            f"{idx} (sniffing)": _ratio(m.get(f"Time in {T} sniff zone (s)", 0.0),
                                        m.get(f"Time in {O} sniff zone (s)", 0.0)),
        }

    def zones_summary(self, p):
        T, _O = self.roles(p)
        side = "left" if p["target_side"] == "L" else "right"
        return f"{T.lower()} {side} · sniff {p['sniff_cm']:g} cm"


# ═══ Elevated zero maze ═════════════════════════════════════════════════
_KIND = [("open", "Open"), ("closed", "Closed")]


class ZeroMaze(BoxExperiment):
    key = "zero_maze"
    name = "Elevated Zero Maze"
    results_title = "Zero Maze"
    arena_hint = "Click the 4 corners of the square around the ring's outer edge."
    scale = ("square", 50.0, "Outer diameter")
    PARAMS = [
        P("ring_pct", "Ring width", "pct", 15, lo=5, hi=45,
          tip="Width of the runway as % of the ring radius."),
        P("rotation", "Rotation", "deg", 0, lo=0, hi=89,
          tip="Turn the four sections to line up with the real open / closed "
              "boundaries. 0° = sections centred top, right, bottom, left."),
        P("k_top", "Top section", "choice", "open", _KIND),
        P("k_right", "Right section", "choice", "closed", _KIND),
        P("k_bottom", "Bottom section", "choice", "open", _KIND),
        P("k_left", "Left section", "choice", "closed", _KIND),
    ]
    COLORS = {"open": ("Open", "#E8A87C"), "closed": ("Closed", "#7FA6D9")}
    _SECTIONS = (("top", "Top", 90), ("right", "Right", 0),
                 ("bottom", "Bottom", 270), ("left", "Left", 180))

    def zones(self, p, dims, c):
        r_out = 0.5
        r_in = 0.5 * (1 - float(p["ring_pct"]) / 100.0)
        rot = float(p["rotation"])
        zs = []
        for sid, lab, mid in self._SECTIONS:
            kind = p[f"k_{sid}"]
            a0, a1 = mid - rot - 45, mid - rot + 45
            lm = math.radians(mid - rot)
            rl = (r_in + r_out) / 2
            zs.append(ZoneDef(
                sid, f"{lab} ({kind})", geo.sector(0.5, 0.5, r_in, r_out, a0, a1),
                "ring", color=c[kind], kind=kind,
                test=geo.radial(0.5, 0.5, r_in, r_out, a0, a1),
                dashed=(kind == "open"), fill_alpha=25 if kind == "open" else 55,
                label_pos=(0.5 + rl * math.cos(lm), 0.5 - rl * math.sin(lm))))
        return zs

    def main_keys(self, p):
        return ["Time in Open (s)", "Time in Closed (s)", "% Time in Open",
                "Entries into Open (#)", "Entries into Closed (#)",
                "% Open Entries", "Latency to Open (s)", "Open / Closed Crossings (#)"]

    def primary(self, ctx, m, p, dims):
        zs = self.zones(p, dims, self.default_colors())
        st = ctx["stats"]["ring"]
        opn = [z for z in zs if z.kind == "open"]
        cls = [z for z in zs if z.kind == "closed"]
        t_o = sum(m.get(f"Time in {z.label} (s)", 0.0) for z in opn)
        t_c = sum(m.get(f"Time in {z.label} (s)", 0.0) for z in cls)
        e_o = sum(m.get(f"Entries into {z.label} (#)", 0) for z in opn)
        e_c = sum(m.get(f"Entries into {z.label} (#)", 0) for z in cls)
        lats = [m.get(f"Latency to {z.label} (s)") for z in opn]
        lats = [x for x in lats if isinstance(x, (int, float))]
        kinds = {z.name: z.kind for z in zs}
        seq = [kinds[z] for z in committed_sequence(st) if z in kinds]
        dur = ctx["duration"]
        return {
            "Time in Open (s)": round(t_o, 3),
            "Time in Closed (s)": round(t_c, 3),
            "% Time in Open": round(100 * t_o / dur, 2) if dur > 0 else 0.0,
            "Entries into Open (#)": e_o,
            "Entries into Closed (#)": e_c,
            "% Open Entries": round(100 * e_o / (e_o + e_c), 2) if (e_o + e_c) else 0.0,
            "Latency to Open (s)": min(lats) if lats else "never",
            "Open / Closed Crossings (#)":
                sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1]),
        }

    def zones_summary(self, p):
        n_open = sum(1 for s, _l, _m in self._SECTIONS if p[f"k_{s}"] == "open")
        return f"{n_open} open · {4 - n_open} closed · ring {p['ring_pct']}%"


# ═══ Morris water maze ══════════════════════════════════════════════════
class WaterMaze(BoxExperiment):
    key = "water_maze"
    name = "Morris Water Maze"
    results_title = "Water Maze"
    arena_hint = "Click the 4 corners of the square around the pool's edge."
    scale = ("square", 120.0, "Pool diameter")
    PARAMS = [
        P("target", "Platform quadrant", "choice", "NE", per_video=True, options=
          [("NE", "NE (top right)"), ("NW", "NW (top left)"),
           ("SW", "SW (bottom left)"), ("SE", "SE (bottom right)")]),
        P("plat_dist", "Platform position", "pct", 50, lo=15, hi=85,
          tip="Distance of the platform centre from the pool centre, as % "
              "of the pool radius."),
        P("plat_cm", "Platform diameter", "cm", 10.0, lo=4, hi=25),
        P("wall_pct", "Wall zone", "pct", 10, lo=3, hi=30,
          tip="Ring along the wall used for thigmotaxis, as % of the radius."),
        P("trial", "Trial type", "choice", "train", per_video=True, options=
          [("train", "Training"), ("probe", "Probe")],
          tip="Training: platform present. Probe: platform removed — "
              "platform crossings and target-quadrant time matter."),
    ]
    COLORS = {"target": ("Target", "#E8A87C"),
              "quad": ("Quadrants", "#7FA6D9"),
              "platform": ("Platform", "#3FA34D"), "wall": ("Wall", "#A9B4C6")}
    _QUADS = (("NE", 0), ("NW", 90), ("SW", 180), ("SE", 270))

    def _platform(self, p, dims):
        D = dims[0] or 120.0
        ang = {"NE": 45, "NW": 135, "SW": 225, "SE": 315}[p["target"]]
        d = 0.5 * float(p["plat_dist"]) / 100.0
        cu = 0.5 + d * math.cos(math.radians(ang))
        cv = 0.5 - d * math.sin(math.radians(ang))
        return cu, cv, float(p["plat_cm"]) / 2.0 / D

    def zones(self, p, dims, c):
        zs = []
        for q, a0 in self._QUADS:
            ck = "target" if q == p["target"] else "quad"
            am = math.radians(a0 + 45)
            zs.append(ZoneDef(q, f"{q} quadrant", geo.sector(0.5, 0.5, 0, 0.5, a0, a0 + 90),
                              "quadrant", color=c[ck],
                              test=geo.radial(0.5, 0.5, 0, 0.5, a0, a0 + 90),
                              fill_alpha=35 if ck == "target" else 12,
                              label_pos=(0.5 + 0.3 * math.cos(am), 0.5 - 0.3 * math.sin(am))))
        cu, cv, r = self._platform(p, dims)
        zs.append(ZoneDef("platform", "Platform", geo.ellipse(cu, cv, r, r, 32), "platform",
                          color=c["platform"], test=geo.radial(cu, cv, 0, r),
                          fill_alpha=60 if p["trial"] == "train" else 0,
                          dashed=p["trial"] == "probe", dwell=False,
                          label_pos=(cu, min(0.97, cv + r + 0.03))))
        r_in = 0.5 * (1 - float(p["wall_pct"]) / 100.0)
        zs.append(ZoneDef("wall", "Wall zone", geo.annulus(0.5, 0.5, r_in, 0.5), "wall",
                          color=c["wall"], test=geo.radial(0.5, 0.5, r_in, 0.5),
                          dashed=True, fill_alpha=0, label_pos=(0.5, 0.03)))
        return zs

    def main_keys(self, p):
        return ["Latency to Platform (s)", "Path Length to Platform (cm)",
                "Path Length to Platform (px)", "Entries into Platform (#)",
                "Time in Target Quadrant (s)", "% Time in Target Quadrant",
                "Mean Distance to Platform (cm)", "Time in Wall zone (s)",
                "% Time in Wall zone", "Trial Type"]

    def primary(self, ctx, m, p, dims):
        import numpy as np
        st = ctx["stats"]["platform"]
        f0 = st.first.get("platform")
        df = ctx["df"]
        unit = ctx["unit"]
        out = {"Trial Type": "Training" if p["trial"] == "train" else "Probe"}
        if f0 is not None and "step_dist" in df:
            out[f"Path Length to Platform ({unit})"] = round(
                float(df["step_dist"].iloc[:f0 + 1].sum(skipna=True)), 2)
        else:
            out[f"Path Length to Platform ({unit})"] = "never"
        tq = m.get(f"Time in {p['target']} quadrant (s)", 0.0)
        in_pool = sum(m.get(f"Time in {q} quadrant (s)", 0.0) for q, _a in self._QUADS)
        out["Time in Target Quadrant (s)"] = tq
        out["% Time in Target Quadrant"] = round(100 * tq / in_pool, 2) if in_pool > 0 else 0.0
        D = dims[0] or 120.0
        cu, cv, _r = self._platform(p, dims)
        bu, bv = ctx["body_uv"]
        d = np.hypot(np.asarray(bu) - cu, np.asarray(bv) - cv) * D
        d = d[~np.isnan(d)]
        out["Mean Distance to Platform (cm)"] = round(float(d.mean()), 2) if d.size else None
        return out

    def zones_summary(self, p):
        return f"platform {p['target']} · {'training' if p['trial'] == 'train' else 'probe'}"


# ═══ T-maze ═════════════════════════════════════════════════════════════
class TMaze(BoxExperiment):
    key = "t_maze"
    name = "T-Maze"
    results_title = "T-Maze"
    arena_hint = ("Click the 4 corners of the rectangle around the whole T "
                  "(cross-bar ends and the start-arm end).")
    scale = ("rect", 70.0, 50.0)
    PARAMS = [
        P("orient", "Start arm", "choice", "down",
          [("down", "Bottom"), ("up", "Top"),
           ("left", "Left"), ("right", "Right")],
          tip="Where the start arm is in the video. Left / right goal arms "
              "are named from the mouse's point of view running up the start arm."),
        P("arm_pct", "Arm width", "pct", 15, lo=5, hi=45,
          tip="Runway width as % of the shorter side of the outline."),
    ]
    COLORS = {"left": ("Left arm", "#E8A87C"), "right": ("Right arm", "#7FA6D9"),
              "start": ("Start arm", "#8FC79A"), "junction": ("Junction", "#A9B4C6")}

    @staticmethod
    def _map(o):
        return {"down": lambda u, v: (u, v), "up": lambda u, v: (1 - u, 1 - v),
                "left": lambda u, v: (1 - v, u), "right": lambda u, v: (v, 1 - u)}[o]

    def zones(self, p, dims, c):
        W, H = dims
        o = p["orient"]
        Wc, Hc = (W, H) if o in ("down", "up") else (H, W)
        w = float(p["arm_pct"]) / 100.0 * min(W, H)
        hu, hv = w / (2 * Wc), w / Hc
        m = self._map(o)

        def poly(r):
            return [m(u, v) for u, v in r]
        canon = {
            "left": geo.rect(0, 0, 0.5 - hu, hv),
            "right": geo.rect(0.5 + hu, 0, 1, hv),
            "junction": geo.rect(0.5 - hu, 0, 0.5 + hu, hv),
            "start": geo.rect(0.5 - hu, hv, 0.5 + hu, 1),
        }
        lpos = {"left": (0.2, hv / 2), "right": (0.8, hv / 2),
                "junction": (0.5, hv / 2), "start": (0.5, (1 + hv) / 2)}
        out = []
        for zid in ("junction", "left", "right", "start"):
            out.append(ZoneDef(zid, self.COLORS[zid][0], poly(canon[zid]), "arm",
                               color=c[zid], label_pos=m(*lpos[zid]),
                               fill_alpha=20 if zid == "junction" else 40))
        return out

    def main_keys(self, p):
        return ["First Choice", "Latency to First Choice (s)", "Goal-Arm Choices (#)",
                "Alternations (#)", "Alternation (%)", "Choice Sequence",
                "Entries into Left arm (#)", "Entries into Right arm (#)"]

    def primary(self, ctx, m, p, dims):
        st = ctx["stats"]["arm"]
        visits = [(z, s) for z, s, _e in st.visits if z in ("left", "right")]
        seq = [z for z, _s in visits]
        alt = sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])
        first = visits[0] if visits else None
        return {
            "First Choice": ("Left" if first[0] == "left" else "Right") if first else "none",
            "Latency to First Choice (s)":
                round(time_at(ctx["df"], first[1], ctx["fps"]) + ctx["trim_start"], 3) if first else "never",
            "Goal-Arm Choices (#)": len(seq),
            "Alternations (#)": alt,
            "Alternation (%)": round(100 * alt / (len(seq) - 1), 2) if len(seq) > 1 else None,
            "Choice Sequence": "".join("L" if z == "left" else "R" for z in seq),
        }

    def zones_summary(self, p):
        names = {"down": "bottom", "up": "top", "left": "left", "right": "right"}
        return f"start {names[p['orient']]} · arm {p['arm_pct']}%"


# ═══ Radial arm maze ════════════════════════════════════════════════════
class RadialMaze(BoxExperiment):
    key = "radial_maze"
    name = "Radial Arm Maze"
    results_title = "Radial Maze"
    arena_hint = "Click the 4 corners of the square around the arm tips."
    scale = ("square", 100.0, "Tip-to-tip diameter")
    PARAMS = [
        P("n_arms", "Arms", "choice", 8,
          [(4, "4"), (6, "6"), (8, "8"), (12, "12")]),
        P("arm_pct", "Arm width", "pct", 10, lo=3, hi=30,
          tip="Arm width as % of the tip-to-tip diameter."),
        P("hub_pct", "Centre size", "pct", 25, lo=8, hi=60,
          tip="Radius of the central platform as % of the maze radius."),
        P("rotation", "Rotation", "deg", 0, lo=0, hi=89,
          tip="Turn the arms to line up with the real maze. Arm 1 starts at the "
              "top; arms are numbered clockwise."),
        P("baited", "Baited arms", "multi", [], options="n_arms", per_video=True,
          tip="Optional. Pick the baited arms to count reference-memory errors "
              "(entries into never-baited arms). Leave empty when every arm is baited."),
    ]
    COLORS = {"arm": ("Arms", "#7FA6D9"), "baited": ("Baited", "#E8A87C"),
              "centre": ("Centre", "#A9B4C6")}

    def zones(self, p, dims, c):
        n = int(p["n_arms"])
        r_hub = 0.5 * float(p["hub_pct"]) / 100.0
        hw = float(p["arm_pct"]) / 100.0 / 2.0
        rot = float(p["rotation"])
        baited = set(int(x) for x in (p.get("baited") or []))
        zs = [ZoneDef("centre", "Centre", geo.regular_polygon(0.5, 0.5, r_hub, max(n, 8), 90 - rot),
                      "arm", color=c["centre"], test=geo.radial(0.5, 0.5, 0, r_hub),
                      fill_alpha=20, label_pos=(0.5, 0.5))]
        for k in range(1, n + 1):
            ang = 90 - rot - (k - 1) * 360.0 / n
            ck = "baited" if k in baited else "arm"
            tip = 0.5 * 0.86
            zs.append(ZoneDef(f"arm{k}", f"Arm {k}", geo.bar(0.5, 0.5, ang, r_hub, 0.5, hw),
                              "arm", color=c[ck],
                              label_pos=(0.5 + tip * math.cos(math.radians(ang)),
                                         0.5 - tip * math.sin(math.radians(ang)))))
        return zs

    def main_keys(self, p):
        n = int(p["n_arms"])
        return ["Total Arm Entries (#)", "Working Memory Errors (#)",
                "Reference Memory Errors (#)", "Entries Before First Repeat (#)",
                f"Different Arms in First {n} Entries (#)", "Time to Visit All Arms (s)",
                "Arm Entry Sequence"]

    def primary(self, ctx, m, p, dims):
        n = int(p["n_arms"])
        baited = set(int(x) for x in (p.get("baited") or [])) or set(range(1, n + 1))
        st = ctx["stats"]["arm"]
        seq = [(int(z[3:]), s) for z, s, _e in st.visits if z.startswith("arm")]
        arms = [a for a, _s in seq]
        seen, wm, rm, first_rep, t_all = set(), 0, 0, None, None
        for i, (a, s) in enumerate(seq):
            if a not in baited:
                rm += 1
            elif a in seen:
                wm += 1
            if a in seen and first_rep is None:
                first_rep = i
            seen.add(a)
            if t_all is None and baited <= seen:
                t_all = round(time_at(ctx["df"], s, ctx["fps"]) + ctx["trim_start"], 3)
        all_baited = len(baited) == n
        return {
            "Total Arm Entries (#)": len(arms),
            "Working Memory Errors (#)": wm,
            "Reference Memory Errors (#)": None if all_baited else rm,
            "Entries Before First Repeat (#)": first_rep if first_rep is not None else len(arms),
            f"Different Arms in First {n} Entries (#)": len(set(arms[:n])),
            "Time to Visit All Arms (s)": t_all if t_all is not None else "never",
            "Arm Entry Sequence": "-".join(str(a) for a in arms),
        }

    def zones_summary(self, p):
        b = len(p.get("baited") or [])
        return f"{p['n_arms']} arms" + (f" · {b} baited" if b else "")


ALL = (PlacePreference, LightDark, ThreeChamber, ZeroMaze, WaterMaze, TMaze, RadialMaze)
