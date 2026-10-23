"""Design-spec -> RGBA canvas layer engine. See references/design-spec.md."""
from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from . import motifs
from .color import parse_color
from .fonts import resolve_font

LAST_WARNINGS: list[str] = []
# Where each text/image/svg element landed: used by wrapkit.orientation to verify that
# text reads upright on the car. Filled by render_spec.
LAST_PLACEMENTS: list[dict] = []

SPEC_KEYS = {"name", "model", "seed", "base_color", "layers", "size", "description", "notes", "comment"}
COMMON = {"type", "opacity", "blend", "clip", "clip_bleed", "enabled", "name", "comment"}
BLENDS = ("normal", "multiply", "screen", "overlay", "add", "soft_light")
LAYER_TYPES = ("solid", "gradient", "noise", "pattern", "shape", "text", "image", "svg")
LAYER_KEYS = {
    "solid": {"color"},
    "gradient": {"kind", "stops", "colors", "angle", "center", "radius"},
    "shape": {"kind", "box", "points", "center", "radius", "points_n", "inner_ratio", "width", "fill",
              "stroke", "rotate", "corner", "blur", "glow", "color", "from", "to"},
    "text": {"text", "font", "size", "fit_box", "color", "stroke", "shadow", "glow", "position", "anchor",
             "panel", "span", "panel_fill", "rotate", "letter_spacing", "line_spacing", "align", "gradient"},
    "image": {"src", "fit", "box", "panel", "span", "panel_fill", "rotate", "mask", "feather", "remove_bg",
              "tolerance", "tint", "tint_strength", "corner"},
    "svg": {"src", "inline", "box", "panel", "span", "panel_fill", "rotate", "recolor"},
}


class _Ctx:
    def __init__(self, spec, spec_dir, warnings):
        self.spec_dir = Path(spec_dir or ".")
        self.warn = warnings
        self.model = spec.get("model")
        self.seed = int(spec.get("seed", 0))
        self._panels = self._map = self._mask = None
        if self.model:
            from . import models
            self.W, self.H = models.canvas_size(self.model)
        elif spec.get("size"):
            self.W, self.H = (int(v) for v in spec["size"])
        else:
            raise ValueError("Spec needs a 'model' (or an explicit 'size': [w, h])")
        self._clip_cache = {}

    def panel_data(self):
        if self._panels is None:
            from . import templates
            self._panels = {p["id"]: p for p in templates.load_panels(self.model)["panels"]}
            self._map = templates.load_panel_map(self.model)
            self._mask = np.asarray(templates.load_mask(self.model).convert("L")) > 127
        return self._panels, self._map, self._mask

    def panel(self, pid):
        panels = self.panel_data()[0]
        pid = int(pid)
        if pid not in panels:
            raise ValueError(f"Unknown panel id {pid} for {self.model}; valid ids: {sorted(panels)}")
        return panels[pid]

    def x(self, v):
        return motifs._num(v, self.W)

    def y(self, v):
        return motifs._num(v, self.H)

    def box(self, b):
        return self.x(b[0]), self.y(b[1]), self.x(b[2]), self.y(b[3])

    def pt(self, p):
        return self.x(p[0]), self.y(p[1])

    def path(self, src):
        """Resolve a spec file reference. `lib:<name>` means the skill's bundled illustration
        library (assets/illustrations/<name>.svg), so specs stay portable across installs."""
        if str(src).startswith("lib:"):
            from .models import SKILL_ROOT
            name = str(src)[4:]
            p = SKILL_ROOT / "assets" / "illustrations" / (name if name.endswith(".svg") else name + ".svg")
            if not p.exists():
                raise FileNotFoundError(f"No illustration {name!r} in {p.parent}")
            return p
        p = Path(str(src)).expanduser()
        if not p.is_absolute():
            p = self.spec_dir / p
        if not p.exists():
            raise FileNotFoundError(f"File not found: {src} (looked in {p})")
        return p


def _dilate(m: np.ndarray, r: int) -> np.ndarray:
    if r <= 0:
        return m
    out = m.copy()
    for d in range(1, r + 1):
        out[:, d:] |= m[:, :-d]
        out[:, :-d] |= m[:, d:]
    m2 = out.copy()
    for d in range(1, r + 1):
        out[d:, :] |= m2[:-d, :]
        out[:-d, :] |= m2[d:, :]
    return out


def _clip_mask(ctx: _Ctx, layer):
    clip = layer.get("clip", "all")
    if clip in (None, "all"):
        return None
    bleed = int(layer.get("clip_bleed", 6))
    if clip == "panels":
        key = ("panels",)
        if key not in ctx._clip_cache:
            ctx._clip_cache[key] = ctx.panel_data()[2].astype(np.float32)
        return ctx._clip_cache[key]
    if isinstance(clip, dict) and "panels" in clip:
        ids = tuple(sorted(int(i) for i in clip["panels"]))
        key = (ids, bleed)
        if key not in ctx._clip_cache:
            panels, pmap, _ = ctx.panel_data()
            for i in ids:
                if i not in panels:
                    ctx.warn.append(f"clip: unknown panel id {i}")
            ctx._clip_cache[key] = _dilate(np.isin(pmap, ids), bleed).astype(np.float32)
        return ctx._clip_cache[key]
    raise ValueError(f"Bad clip value {clip!r}: use \"all\", \"panels\" or {{\"panels\": [ids]}}")


# ---------------------------------------------------------------- blending

def _blend_fn(mode, cd, cs):
    if mode == "normal":
        return cs
    if mode == "multiply":
        return cd * cs
    if mode == "screen":
        return 1 - (1 - cd) * (1 - cs)
    if mode == "add":
        return np.minimum(1.0, cd + cs)
    if mode == "overlay":
        return np.where(cd < 0.5, 2 * cd * cs, 1 - 2 * (1 - cd) * (1 - cs))
    if mode == "soft_light":
        g = np.where(cd <= 0.25, ((16 * cd - 12) * cd + 4) * cd, np.sqrt(cd))
        return np.where(cs <= 0.5, cd - (1 - 2 * cs) * cd * (1 - cd), cd + (2 * cs - 1) * (g - cd))
    raise ValueError(f"Unknown blend mode {mode!r}; use one of {', '.join(BLENDS)}")


def _composite(dst: np.ndarray, src: np.ndarray, mode: str) -> np.ndarray:
    sa, da = src[..., 3:4], dst[..., 3:4]
    oa = sa + da * (1 - sa)
    cd, cs = dst[..., :3], src[..., :3]
    b = _blend_fn(mode, cd, cs)
    num = (1 - sa) * da * cd + sa * (1 - da) * cs + sa * da * b
    return np.concatenate([num / np.maximum(oa, 1e-6), oa], -1)


def _arr(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("RGBA"), dtype=np.float32) / 255.0


# ---------------------------------------------------------------- layer renderers

def _solid(ctx, L):
    return Image.new("RGBA", (ctx.W, ctx.H), parse_color(L.get("color", "#000000")))


def _stops(L):
    stops = L.get("stops")
    if stops is None:
        cs = L.get("colors")
        if not cs:
            raise ValueError("gradient layer needs 'stops': [[color, pos], ...] (or 'colors': [...])")
        stops = [[c, i / max(1, len(cs) - 1)] for i, c in enumerate(cs)]
    pos, cols = [], []
    for s in stops:
        if isinstance(s, str):
            raise ValueError("gradient stops must be [color, position] pairs")
        cols.append(parse_color(s[0]))
        pos.append(float(s[1]))
    order = np.argsort(pos)
    return np.array(cols, np.float32)[order] / 255.0, np.array(pos, np.float32)[order]


def _gradient(ctx, L):
    W, H = ctx.W, ctx.H
    kind = L.get("kind", "linear")
    cols, pos = _stops(L)
    Y, X = np.mgrid[0:H, 0:W].astype(np.float32)
    X += 0.5
    Y += 0.5
    if kind == "linear":
        a = math.radians(float(L.get("angle", 90)))
        c, s = math.cos(a), math.sin(a)
        ext = abs(W * c) + abs(H * s)
        t = ((X - W / 2) * c + (Y - H / 2) * s) / ext + 0.5
    elif kind == "radial":
        cx, cy = ctx.pt(L["center"]) if L.get("center") else (W / 2, H / 2)
        r = ctx.x(L["radius"]) if L.get("radius") is not None else math.hypot(max(cx, W - cx), max(cy, H - cy))
        t = np.hypot(X - cx, Y - cy) / max(r, 1e-6)
    elif kind == "conic":
        cx, cy = ctx.pt(L["center"]) if L.get("center") else (W / 2, H / 2)
        t = ((np.arctan2(Y - cy, X - cx) - math.radians(float(L.get("angle", 0)))) / math.tau) % 1.0
    else:
        raise ValueError(f"Unknown gradient kind {kind!r}: linear|radial|conic")
    out = np.empty((H, W, 4), np.float32)
    for c in range(4):
        out[..., c] = np.interp(t, pos, cols[:, c])
    return motifs._to_img(out)


def _motif_params(ctx, L, extra_skip=()):
    p = {k: v for k, v in L.items() if k not in COMMON and k not in extra_skip}
    for k in ("center",):
        if p.get(k) is not None:
            p[k] = list(ctx.pt(p[k]))
    return p


def _procedural(ctx, L, idx, kind_type):
    kind = L.get("kind")
    if not kind:
        raise ValueError(f"{kind_type} layer needs 'kind'")
    p = _motif_params(ctx, L, ("kind",))
    allowed = motifs.allowed_keys(kind_type, kind)
    for k in p:
        if k not in allowed:
            ctx.warn.append(f"layer {idx} ({kind_type}/{kind}): unknown key '{k}' ignored")
    seed = int(L.get("seed", ctx.seed * 7919 + idx * 1009))
    fn = motifs.render_pattern if kind_type == "pattern" else motifs.render_noise
    return fn(kind, (ctx.W, ctx.H), p, seed)


# ---- shapes

def _rot_pts(pts, cx, cy, deg):
    if not deg:
        return pts
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [(cx + (x - cx) * c + (y - cy) * s, cy - (x - cx) * s + (y - cy) * c) for x, y in pts]


def _ellipse_pts(cx, cy, rx, ry, n=96):
    return [(cx + rx * math.cos(t), cy + ry * math.sin(t)) for t in np.linspace(0, math.tau, n, endpoint=False)]


def _shape(ctx, L, idx):
    W, H = ctx.W, ctx.H
    ss = 2
    kind = L.get("kind", "rect")
    rot = float(L.get("rotate", 0))
    fill = L.get("fill", L.get("color"))
    stroke = L.get("stroke")
    fm = Image.new("L", (W * ss, H * ss), 0)
    sm = Image.new("L", (W * ss, H * ss), 0)
    fd, sd = ImageDraw.Draw(fm), ImageDraw.Draw(sm)
    sw = float(stroke.get("width", 2)) * ss if stroke else 0
    closed = True
    ring_inner = None
    if kind == "rect":
        x, y, w, h = ctx.box(L.get("box", ["0%", "0%", "100%", "100%"]))
        cx, cy = x + w / 2, y + h / 2
        cr = ctx.x(L["corner"]) if L.get("corner") else 0
        if cr > 0 and rot == 0:
            fd.rounded_rectangle([x * ss, y * ss, (x + w) * ss, (y + h) * ss], radius=cr * ss, fill=255)
            sd.rounded_rectangle([x * ss, y * ss, (x + w) * ss, (y + h) * ss], radius=cr * ss, outline=255,
                                 width=max(1, int(sw)))
            pts = None
        else:
            pts = _rot_pts([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], cx, cy, rot)
    elif kind == "ellipse":
        if L.get("box"):
            x, y, w, h = ctx.box(L["box"])
            cx, cy, rx, ry = x + w / 2, y + h / 2, w / 2, h / 2
        else:
            cx, cy = ctx.pt(L.get("center", ["50%", "50%"]))
            r = L.get("radius", 50)
            rx, ry = (ctx.x(r[0]), ctx.x(r[1])) if isinstance(r, (list, tuple)) else (ctx.x(r),) * 2
        pts = _rot_pts(_ellipse_pts(cx, cy, rx, ry, 128), cx, cy, rot)
    elif kind == "polygon":
        pts = [ctx.pt(p) for p in L["points"]]
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        pts = _rot_pts(pts, cx, cy, rot)
    elif kind == "star":
        cx, cy = ctx.pt(L.get("center", ["50%", "50%"]))
        R = ctx.x(L.get("radius", 100))
        pts = motifs._star_poly(cx, cy, R, R * float(L.get("inner_ratio", 0.45)), int(L.get("points_n", 5)),
                                -math.radians(rot))
    elif kind == "line":
        if L.get("points"):
            pts = [ctx.pt(p) for p in L["points"]]
        elif L.get("from") and L.get("to"):
            pts = [ctx.pt(L["from"]), ctx.pt(L["to"])]
        else:
            raise ValueError("line shape needs 'points': [[x,y],[x,y],...] (or 'from' and 'to')")
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        pts = _rot_pts(pts, cx, cy, rot)
        wd = max(1, ctx.x(L.get("width", 6)) * ss)
        sd.line([(a * ss, b * ss) for a, b in pts], fill=255, width=int(round(wd)), joint="curve")
        r = wd / 2
        for a, b in (pts[0], pts[-1]):
            sd.ellipse([a * ss - r, b * ss - r, a * ss + r, b * ss + r], fill=255)
        closed = False
        pts = None
        fill = fill or (stroke or {}).get("color")
        stroke = None if not stroke or L.get("fill") is None and L.get("color") is None else stroke
        if fill is None:
            fill = "#ffffff"
        fm = sm
        sm = Image.new("L", fm.size, 0)
    elif kind == "ring":
        cx, cy = ctx.pt(L.get("center", ["50%", "50%"]))
        R = ctx.x(L.get("radius", 100))
        wd = ctx.x(L.get("width", 10))
        fd.ellipse([(cx - R) * ss, (cy - R) * ss, (cx + R) * ss, (cy + R) * ss], fill=255)
        fd.ellipse([(cx - R + wd) * ss, (cy - R + wd) * ss, (cx + R - wd) * ss, (cy + R - wd) * ss], fill=0)
        pts = None
    else:
        raise ValueError(f"Unknown shape kind {kind!r}: rect|ellipse|polygon|star|line|ring")
    if pts:
        sp = [(a * ss, b * ss) for a, b in pts]
        fd.polygon(sp, fill=255)
        if sw:
            sd.line(sp + [sp[0]], fill=255, width=int(round(sw)), joint="curve")
    blur = float(L.get("blur", 0))
    if blur > 0:
        fm = fm.filter(ImageFilter.GaussianBlur(blur * ss))
        sm = sm.filter(ImageFilter.GaussianBlur(blur * ss))
    big = Image.new("RGBA", fm.size, (0, 0, 0, 0))
    glow = L.get("glow")
    if glow:
        union = ImageChops.lighter(fm, sm)
        gm = union.filter(ImageFilter.GaussianBlur(float(glow.get("radius", 20)) * ss))
        gs = float(glow.get("strength", 1.0))
        if gs != 1.0:
            gm = gm.point(lambda v: min(255, int(v * gs)))
        gc = parse_color(glow.get("color", fill or "#ffffff"))
        big.paste(Image.new("RGBA", fm.size, gc), (0, 0), gm)
    if fill is not None:
        big = Image.alpha_composite(big, _solid_with_mask(fm, parse_color(fill)))
    if stroke and sw:
        big = Image.alpha_composite(big, _solid_with_mask(sm, parse_color(stroke.get("color", "#ffffff"))))
    return big.resize((W, H), Image.LANCZOS)


def _solid_with_mask(mask: Image.Image, color):
    c = Image.new("RGBA", mask.size, color)
    a = ImageChops.multiply(mask, Image.new("L", mask.size, color[3]))
    c.putalpha(a)
    return c


# ---- placement helpers

def _anchor_frac(anchor):
    a = (anchor or "mm") + "m"
    h = {"l": 0.0, "m": 0.5, "r": 1.0}.get(a[0], 0.5)
    v = {"t": 0.0, "m": 0.5, "b": 1.0, "s": 1.0}.get(a[1], 0.5)
    return h, v


def _paste_rotated(canvas: Image.Image, patch: Image.Image, anchor_px, target, rot):
    """Rotate patch (CCW deg) about anchor_px and paste so the anchor lands on target."""
    ax, ay = anchor_px
    if rot:
        cx, cy = patch.width / 2, patch.height / 2
        patch = patch.rotate(rot, resample=Image.BICUBIC, expand=True)
        a = math.radians(rot)
        dx, dy = ax - cx, ay - cy
        rx = dx * math.cos(a) + dy * math.sin(a)
        ry = -dx * math.sin(a) + dy * math.cos(a)
        ax, ay = patch.width / 2 + rx, patch.height / 2 + ry
    motifs._paste(canvas, patch, int(round(target[0] - ax)), int(round(target[1] - ay)))


def _score(P):
    x0, y0, x1, y1 = P["bbox"]
    return P["area"] * P["area"] / max(1, (x1 - x0) * (y1 - y0))


def _select(ctx, name, span):
    """Resolve a panel selector (largest|hood|trunk|front|rear|side|pillar) into groups of ids."""
    panels = list(ctx.panel_data()[0].values())
    name = name.lower()
    if name in ("hood", "trunk"):
        # Hood / trunk lid: the sizeable front / rear panel nearest the canvas centre
        # (bumpers sit at the outer edges of every template layout).
        cand = [p for p in panels if p.get("region") == ("front" if name == "hood" else "rear")]
        if not cand:
            return []
        big = max(p["area"] for p in cand)
        cand = [p for p in cand if p["area"] >= 0.3 * big]
        cx, cy = ctx.W / 2, ctx.H / 2
        best = min(cand, key=lambda p: (p["centroid"][0] - cx) ** 2 + (p["centroid"][1] - cy) ** 2)
        return [[best["id"]]]
    if name == "largest":
        cand = panels
    elif name in ("front", "rear", "side", "pillar"):
        cand = [p for p in panels if p.get("region") == name]
    else:
        raise ValueError(f"Unknown panel selector {name!r}: use ids or largest|hood|trunk|front|rear|side|pillar")
    if not cand:
        return []
    by_rot: dict = {}
    for p in cand:
        by_rot.setdefault(p.get("upright_rotate", 0), []).append(p)
    if name != "side":
        by_rot = {0: sorted(cand, key=_score, reverse=True)}
    groups = []
    for ps in by_rot.values():
        ps = sorted(ps, key=_score, reverse=True)
        best = _score(ps[0])
        keep = [p for p in ps if _score(p) >= 0.5 * best] if span else ps[:1]
        groups.append([p["id"] for p in keep])
    return groups


def _panel_groups(ctx, L):
    """Panel-id groups for a layer: one per panel, or merged groups when span is true."""
    p = L.get("panel")
    if p is None:
        return None
    items = p if isinstance(p, (list, tuple)) else [p]
    span = bool(L.get("span"))
    ids, groups = [], []
    for it in items:
        if isinstance(it, str) and not it.strip().lstrip("-").isdigit():
            groups.extend(_select(ctx, it, span))
        else:
            ids.append(int(it))
    known = ctx.panel_data()[0]
    good = [i for i in ids if i in known]
    for i in ids:
        if i not in known:
            ctx.warn.append(f"panel {i} does not exist on {ctx.model}; skipped (use selectors like \"side\" for portable specs)")
    if good:
        groups = ([good] if span else [[i] for i in good]) + groups
    return groups


def _interior_point(ctx, P, cx, cy):
    """A point deep inside the panel (curved panels' centroids can fall outside them):
    erode the panel until one more step would empty it, then take the remaining pixel
    nearest the centroid."""
    key = ("interior", P["id"])
    if key not in ctx._clip_cache:
        x0, y0, x1, y1 = P["bbox"]
        m = np.zeros((y1 - y0 + 2, x1 - x0 + 2), bool)
        m[1:-1, 1:-1] = ctx.panel_data()[1][y0:y1, x0:x1] == P["id"]
        while True:
            nxt = ~_dilate(~m, 2)
            if not nxt.any():
                break
            m = nxt
        ys, xs = np.nonzero(m)
        i = int(np.argmin((xs + x0 - 1 - cx) ** 2 + (ys + y0 - 1 - cy) ** 2))
        ctx._clip_cache[key] = (float(xs[i] + x0 - 1), float(ys[i] + y0 - 1))
    return ctx._clip_cache[key]


def _panel_frame(ctx, group, rot_override, fill):
    """(cx, cy, frame_w, frame_h, rot) of a panel (or merged group) in its rotated (upright) space."""
    Ps = [ctx.panel(i) for i in group]
    P = Ps[0]
    x0, y0 = min(p["bbox"][0] for p in Ps), min(p["bbox"][1] for p in Ps)
    x1, y1 = max(p["bbox"][2] for p in Ps), max(p["bbox"][3] for p in Ps)
    tot = sum(p["area"] for p in Ps)
    cx = sum(p["centroid"][0] * p["area"] for p in Ps) / tot
    cy = sum(p["centroid"][1] * p["area"] for p in Ps) / tot
    if len(Ps) > 1:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    else:
        cx, cy = _interior_point(ctx, P, cx, cy)
    rot = float(rot_override if rot_override is not None else P.get("upright_rotate", 0))
    ex = 2 * min(cx - x0, x1 - cx)
    ey = 2 * min(cy - y0, y1 - cy)
    ex, ey = max(ex, 4), max(ey, 4)
    r = abs(rot) % 180
    if abs(r - 90) < 1e-3:
        fw, fh = ey, ex
    elif r < 1e-3:
        fw, fh = ex, ey
    else:
        a = math.radians(rot)
        fw, fh = ex, ey
    return cx, cy, fw * fill, fh * fill, rot


# ---- text

def _gradient_img(size, colors):
    w, h = size
    cols = np.array([parse_color(c) for c in colors], np.float32)
    t = np.linspace(0, 1, h)
    pos = np.linspace(0, 1, len(cols))
    col = np.stack([np.interp(t, pos, cols[:, c]) for c in range(4)], -1)
    arr = np.repeat(col[:, None, :], w, axis=1)
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def _render_text(L, size_px, ss, stroke_w):
    """Return ((RGBA block at scale ss, effect margin), ink_w, ink_h in px) or (None, 0, 0)."""
    text = str(L.get("text", ""))
    lines = text.split("\n")
    font = resolve_font(L.get("font", "sans-bold"), size_px * ss)
    spacing = float(L.get("letter_spacing", 0)) * ss
    asc, desc = font.getmetrics()
    lh = (asc + desc) * float(L.get("line_spacing", 1.05))

    def line_w(s):
        if not spacing:
            return font.getlength(s)
        return sum(font.getlength(ch) for ch in s) + spacing * max(0, len(s) - 1)

    widths = [line_w(s) for s in lines]
    pad = int(size_px * ss * 0.4 + stroke_w * ss * 2 + 8)
    Wm = int(max(widths) + 2 * pad)
    Hm = int(lh * len(lines) + 2 * pad)
    fm = Image.new("L", (Wm, Hm), 0)
    om = Image.new("L", (Wm, Hm), 0)
    fd, od = ImageDraw.Draw(fm), ImageDraw.Draw(om)
    align = L.get("align", "center")
    sw = int(round(stroke_w * ss))
    for i, s in enumerate(lines):
        x = pad + {"left": 0, "center": (max(widths) - widths[i]) / 2, "right": max(widths) - widths[i]}[align]
        y = pad + i * lh
        if spacing:
            for ch in s:
                fd.text((x, y), ch, font=font, fill=255)
                od.text((x, y), ch, font=font, fill=255, stroke_width=sw)
                x += font.getlength(ch) + spacing
        else:
            fd.text((x, y), s, font=font, fill=255)
            od.text((x, y), s, font=font, fill=255, stroke_width=sw)
    bbox = ImageChops.lighter(fm, om).getbbox()
    if not bbox:
        return None, 0, 0
    fm, om = fm.crop(bbox), om.crop(bbox)
    col = L.get("color", "#ffffff")
    if L.get("gradient"):
        fill_img = _gradient_img(fm.size, L["gradient"])
        fill_img.putalpha(ImageChops.multiply(fill_img.getchannel("A"), fm))
    else:
        fill_img = _solid_with_mask(fm, parse_color(col))
    block = Image.new("RGBA", fm.size, (0, 0, 0, 0))
    stroke = L.get("stroke")
    if stroke and sw:
        block = Image.alpha_composite(block, _solid_with_mask(om, parse_color(stroke.get("color", "#000000"))))
    block = Image.alpha_composite(block, fill_img)
    full_alpha = om
    # effects (glow, shadow) padded around the ink
    shadow, glow = L.get("shadow"), L.get("glow")
    m = 0
    if shadow:
        m = max(m, int((float(shadow.get("blur", 4)) * 3 + max(abs(v) for v in shadow.get("offset", [4, 4]))) * ss))
    if glow:
        m = max(m, int(float(glow.get("radius", 16)) * 3 * ss))
    if m:
        out = Image.new("RGBA", (block.width + 2 * m, block.height + 2 * m), (0, 0, 0, 0))
        amask = Image.new("L", out.size, 0)
        amask.paste(full_alpha, (m, m))
        if glow:
            g = amask.filter(ImageFilter.GaussianBlur(float(glow.get("radius", 16)) * ss))
            gs = float(glow.get("strength", 1.0))
            g = g.point(lambda v: min(255, int(v * gs * 1.6)))
            out = Image.alpha_composite(out, _solid_with_mask(g, parse_color(glow.get("color", col))))
        if shadow:
            ox, oy = shadow.get("offset", [4, 4])
            sm = Image.new("L", out.size, 0)
            sm.paste(full_alpha, (m + int(ox * ss), m + int(oy * ss)))
            sm = sm.filter(ImageFilter.GaussianBlur(float(shadow.get("blur", 4)) * ss))
            out = Image.alpha_composite(out, _solid_with_mask(sm, parse_color(shadow.get("color", "#00000099"))))
        out = Image.alpha_composite(out, _pad_img(block, out.size, m))
        return (out, m), block.width / ss, block.height / ss
    return (block, 0), block.width / ss, block.height / ss


MIN_TEXT_PX = 18  # smaller lettering is unreadable in the car's 3D view; such copies are skipped
SMALL_TEXT_PX = 28  # below this, text is drawn but flagged as hard to read


def _record(ctx, idx, kind, label, part, rot, group=None):
    """Remember where an element landed (bbox, dominant panel, applied rotation)."""
    a = np.asarray(part.getchannel("A")) > 76
    if not a.any():
        return
    ys, xs = np.nonzero(a)
    entry = {"layer": idx, "kind": kind, "label": label, "rotate": float(rot or 0) % 360,
             "bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
             "panel": None, "group": list(group) if group else None, "on_panel_frac": 0.0}
    if ctx.model:
        ids = ctx.panel_data()[1][a]
        hit = ids[ids > 0]
        if hit.size:
            entry["panel"] = int(np.bincount(hit).argmax())
            home = list(group) if group and len(group) > 1 else [entry["panel"]]
            # seam lines between spanned panels belong to the span
            covered = np.isin(ids, home) | ((ids == 0) & bool(group and len(group) > 1))
            entry["on_panel_frac"] = round(float(covered.mean()), 3)
    LAST_PLACEMENTS.append(entry)


def _pad_img(img, size, m):
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    out.paste(img, (m, m))
    return out


def _text(ctx, L, idx):
    ss = 2
    stroke_w = float((L.get("stroke") or {}).get("width", 0)) if L.get("stroke") else 0
    canvas = Image.new("RGBA", (ctx.W, ctx.H), (0, 0, 0, 0))
    if not str(L.get("text", "")).strip():
        ctx.warn.append(f"layer {idx}: text layer has empty text")
        return canvas
    hf, vf = _anchor_frac(L.get("anchor", "mm"))
    rot_given = L.get("rotate")

    def fit(target_w, target_h, rot):
        a = math.radians(rot or 0)
        c, s = abs(math.cos(a)), abs(math.sin(a))
        size = 100.0
        res = None
        for _ in range(3):
            res, iw, ih = _render_text(L, size, ss, stroke_w)
            if res is None:
                return None, size
            rw, rh = iw * c + ih * s, iw * s + ih * c
            k = min(target_w / max(rw, 1), target_h / max(rh, 1))
            if abs(k - 1) < 0.01:
                break
            size = max(4.0, size * k)
        return res, size

    def draw(res, rot, tx, ty):
        img, m = res
        inner_w, inner_h = img.width - 2 * m, img.height - 2 * m
        ax = m + hf * inner_w
        ay = m + vf * inner_h
        big = img
        # rotate at supersampled scale, then downsample
        if rot:
            cx, cy = big.width / 2, big.height / 2
            rotated = big.rotate(rot, resample=Image.BICUBIC, expand=True)
            a = math.radians(rot)
            dx, dy = ax - cx, ay - cy
            ax = rotated.width / 2 + dx * math.cos(a) + dy * math.sin(a)
            ay = rotated.height / 2 - dx * math.sin(a) + dy * math.cos(a)
            big = rotated
        small = big.resize((max(1, round(big.width / ss)), max(1, round(big.height / ss))), Image.LANCZOS)
        part = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        motifs._paste(part, small, int(round(tx - ax / ss)), int(round(ty - ay / ss)))
        return part

    groups = _panel_groups(ctx, L)
    if groups is not None:
        panel_fill = float(L.get("panel_fill", 0.8))
        _, pmap, _ = ctx.panel_data()
        for grp in groups:
            cx, cy, fw, fh, rot = _panel_frame(ctx, grp, rot_given, panel_fill)
            if L.get("size"):
                res = _render_text(L, float(L["size"]), ss, stroke_w)[0]
            else:
                res, size = fit(fw, fh, 0)
            if res is None:
                continue
            part = draw(res, rot, cx, cy)
            area = np.isin(pmap, grp)
            if len(grp) > 1:  # deliberate span: close the seam gaps between the panels
                area = ~_dilate(~_dilate(area, 8), 8)
            pm = ~_dilate(~area, 6)  # keep a 6 px margin from the outer seams
            if not L.get("size"):
                a = np.asarray(part.getchannel("A")) > 76
                tot = a.sum()
                tries = 0
                while tot and (a & pm).sum() / tot < 0.995 and tries < 25:
                    size *= 0.93
                    res = _render_text(L, size, ss, stroke_w)[0]
                    part = draw(res, rot, cx, cy)
                    a = np.asarray(part.getchannel("A")) > 76
                    tot = a.sum()
                    tries += 1
            a = np.asarray(part.getchannel("A")) > 76
            if not a.any():
                continue
            ys, xs = np.nonzero(a)
            thickness = min(xs.max() - xs.min(), ys.max() - ys.min()) + 1
            label = str(L["text"]).replace("\n", " ")
            if (a & pm).sum() / a.sum() < 0.995:
                ctx.warn.append(f"SKIPPED TEXT layer {idx} '{label}' on panel(s) {grp}: it does not fit "
                                "inside the panel (letters would be cut by a seam). Use a larger panel, "
                                "shorter text or a line break.")
                continue
            if thickness < MIN_TEXT_PX:
                ctx.warn.append(f"SKIPPED TEXT layer {idx} '{label}' on panel(s) {grp}: only {thickness} px "
                                "tall there, unreadable on the car. Use a larger panel or shorter text.")
                continue
            _record(ctx, idx, "text", L["text"], part, rot, grp)
            canvas = Image.alpha_composite(canvas, part)
        return canvas
    rot = float(rot_given or 0)
    if L.get("fit_box"):
        x, y, w, h = ctx.box(L["fit_box"])
        res, _ = fit(w, h, 0)
        if res is None:
            return canvas
        part = draw(res, rot, x + w / 2, y + h / 2)
    else:
        size = float(L.get("size", 120))
        res = _render_text(L, size, ss, stroke_w)[0]
        if res is None:
            return canvas
        px, py = ctx.pt(L.get("position", ["50%", "50%"]))
        part = draw(res, rot, px, py)
    _record(ctx, idx, "text", L["text"], part, rot)
    return part


# ---- image / svg

def _flood_remove_bg(img: Image.Image, tol: float) -> Image.Image:
    a = np.asarray(img.convert("RGBA")).astype(np.float32)
    rgb, alpha = a[..., :3], a[..., 3]
    h, w = alpha.shape
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bc = np.median(border, axis=0)
    cand = (np.sqrt(((rgb - bc) ** 2).sum(-1)) <= tol) | (alpha < 8)
    seed = np.zeros_like(cand)
    seed[0], seed[-1], seed[:, 0], seed[:, -1] = cand[0], cand[-1], cand[:, 0], cand[:, -1]
    for _ in range(80):
        before = seed.sum()
        for axis in (1, 0):
            c = cand if axis == 1 else cand.T
            s = seed if axis == 1 else seed.T
            rid = np.cumsum(~c, axis=1)
            key = (np.arange(c.shape[0])[:, None] * (c.shape[1] + 1) + rid).ravel()
            hit = np.bincount(key, weights=(s & c).ravel().astype(np.float64), minlength=key.max() + 1) > 0
            filled = (c.ravel() & hit[key]).reshape(c.shape)
            if axis == 1:
                seed = filled
            else:
                seed = filled.T
        if seed.sum() == before:
            break
    am = Image.fromarray(((~seed) * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(0.8))
    out = img.convert("RGBA")
    out.putalpha(ImageChops.multiply(out.getchannel("A"), am))
    return out


def _apply_mask(tile: Image.Image, mode, feather, corner):
    w, h = tile.size
    ss = 3
    m = Image.new("L", (w * ss, h * ss), 0)
    d = ImageDraw.Draw(m)
    if mode == "circle":
        r = min(w, h) * ss / 2
        d.ellipse([w * ss / 2 - r, h * ss / 2 - r, w * ss / 2 + r, h * ss / 2 + r], fill=255)
    elif mode == "ellipse":
        d.ellipse([0, 0, w * ss - 1, h * ss - 1], fill=255)
    elif mode == "rounded":
        d.rounded_rectangle([0, 0, w * ss - 1, h * ss - 1], radius=(corner or min(w, h) * 0.14) * ss, fill=255)
    elif mode in (None, "none"):
        m = Image.new("L", (w * ss, h * ss), 255)
    else:
        raise ValueError(f"Unknown image mask {mode!r}: none|circle|rounded|ellipse")
    m = m.resize((w, h), Image.LANCZOS)
    if feather and feather > 0:
        pad = int(feather * 2) + 2
        mp = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
        mp.paste(m, (pad, pad))
        mp = mp.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(feather / 2))
        m = mp.crop((pad, pad, pad + w, pad + h))
    out = tile.copy()
    out.putalpha(ImageChops.multiply(out.getchannel("A"), m))
    return out


def _fit_tile(src: Image.Image, tw, th, fit):
    tw, th = max(1, int(round(tw))), max(1, int(round(th)))
    sw, sh = src.size
    if fit == "stretch":
        return src.resize((tw, th), Image.LANCZOS)
    if fit == "cover":
        k = max(tw / sw, th / sh)
        r = src.resize((max(1, round(sw * k)), max(1, round(sh * k))), Image.LANCZOS)
        l, t = (r.width - tw) // 2, (r.height - th) // 2
        return r.crop((l, t, l + tw, t + th))
    if fit == "contain":
        k = min(tw / sw, th / sh)
        return src.resize((max(1, round(sw * k)), max(1, round(sh * k))), Image.LANCZOS)
    if fit == "none":
        return src
    if fit == "tile":
        t = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        for yy in range(0, th, sh):
            for xx in range(0, tw, sw):
                t.paste(src, (xx, yy))
        return t
    raise ValueError(f"Unknown image fit {fit!r}: cover|contain|stretch|tile|none")


def _tint(img: Image.Image, color, strength):
    c = np.array(parse_color(color)[:3], np.float32) / 255
    a = _arr(img)
    lum = (a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114)[..., None]
    tinted = lum * c[None, None, :]
    a[..., :3] = a[..., :3] * (1 - strength) + tinted * strength
    return motifs._to_img(a)


def _place_visual(ctx, L, idx, kind, make_tile):
    """Shared placement for image/svg: make_tile(w, h) -> RGBA tile, placed in box or panel(s)."""
    canvas = Image.new("RGBA", (ctx.W, ctx.H), (0, 0, 0, 0))
    rot_given = L.get("rotate")
    label = L.get("src") or f"inline {kind}"
    groups = _panel_groups(ctx, L)
    if groups is not None:
        pmap = ctx.panel_data()[1]
        for grp in groups:
            fill = float(L.get("panel_fill", 1.0))
            area = np.isin(pmap, grp)
            if len(grp) > 1:
                area = ~_dilate(~_dilate(area, 8), 8)
            inside = ~_dilate(~area, 4)
            # Shrink until the art sits inside the panel (irregular panels such as wheel
            # arches would otherwise cut it at a seam), like panel-placed text.
            for _ in range(12):
                cx, cy, fw, fh, rot = _panel_frame(ctx, grp, rot_given, fill)
                tile = make_tile(fw, fh)
                part = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                _paste_rotated(part, tile, (tile.width / 2, tile.height / 2), (cx, cy), rot)
                a = np.asarray(part.getchannel("A")) > 76
                if not a.any() or (a & inside).sum() / a.sum() >= 0.97:
                    break
                fill *= 0.9
            _record(ctx, idx, kind, label, part, rot, grp)
            canvas = Image.alpha_composite(canvas, part)
        return canvas
    x, y, w, h = ctx.box(L.get("box", ["0%", "0%", "100%", "100%"]))
    tile = make_tile(w, h)
    _paste_rotated(canvas, tile, (tile.width / 2, tile.height / 2), (x + w / 2, y + h / 2), float(rot_given or 0))
    if L.get("box"):  # full-canvas backgrounds are not hero elements
        _record(ctx, idx, kind, label, canvas, rot_given)
    return canvas


def _image(ctx, L, idx):
    if not L.get("src"):
        raise ValueError(f"layer {idx}: image layer needs 'src'")
    src = Image.open(ctx.path(L["src"])).convert("RGBA")
    if L.get("remove_bg"):
        src = _flood_remove_bg(src, float(L.get("tolerance", 28)))
    fit = L.get("fit", "cover")

    def make(tw, th):
        tile = _fit_tile(src, tw, th, fit)
        tile = _apply_mask(tile, L.get("mask"), float(L.get("feather", 0)), ctx.x(L["corner"]) if L.get("corner") else None) \
            if (L.get("mask") not in (None, "none") or L.get("feather")) else tile
        if L.get("tint"):
            tile = _tint(tile, L["tint"], float(L.get("tint_strength", 1.0)))
        return tile
    return _place_visual(ctx, L, idx, "image", make)


def _svg(ctx, L, idx):
    from .svgrender import render_svg
    if L.get("inline"):
        data = L["inline"]
    elif L.get("src"):
        data = ctx.path(L["src"]).read_text(encoding="utf-8")
    else:
        raise ValueError(f"layer {idx}: svg layer needs 'src' or 'inline'")
    for old, new in (L.get("recolor") or {}).items():  # e.g. {"#3a7bd5": "#ff2a6d"}
        if old.lower() not in data.lower():
            ctx.warn.append(f"layer {idx}: recolor source {old} not found in the SVG")
        data = re.sub(re.escape(old), new, data, flags=re.I)
    return _place_visual(ctx, L, idx, "svg", lambda tw, th: render_svg(data, (max(1, round(tw)), max(1, round(th)))))


# ---------------------------------------------------------------- engine

def render_spec(spec: dict, spec_dir=None, warnings: list | None = None) -> Image.Image:
    """Render a design spec to an opaque-base RGBA canvas. Warnings go to LAST_WARNINGS (and `warnings`)."""
    LAST_WARNINGS.clear()
    LAST_PLACEMENTS.clear()
    warn = LAST_WARNINGS
    for k in spec:
        if k not in SPEC_KEYS:
            warn.append(f"spec: unknown top-level key '{k}' ignored")
    ctx = _Ctx(spec, spec_dir, warn)
    base = parse_color(spec.get("base_color", "#101010"))
    dst = np.empty((ctx.H, ctx.W, 4), np.float32)
    dst[...] = np.array([base[0], base[1], base[2], 255], np.float32) / 255.0
    layers = spec.get("layers", [])
    if not layers:
        warn.append("spec has no layers; output is just base_color")
    for idx, L in enumerate(layers):
        if L.get("enabled", True) is False:
            continue
        t = L.get("type")
        if t not in LAYER_TYPES:
            raise ValueError(f"layer {idx}: unknown layer type {t!r}. Valid types: {', '.join(LAYER_TYPES)}. "
                             f"(Did you mean 'pattern' with a 'kind'?)")
        if t in LAYER_KEYS:
            for k in L:
                if k not in COMMON and k not in LAYER_KEYS[t]:
                    warn.append(f"layer {idx} ({t}): unknown key '{k}' ignored")
        mode = L.get("blend", "normal")
        if mode not in BLENDS:
            raise ValueError(f"layer {idx}: unknown blend {mode!r}; use one of {', '.join(BLENDS)}")
        if t == "solid":
            img = _solid(ctx, L)
        elif t == "gradient":
            img = _gradient(ctx, L)
        elif t in ("noise", "pattern"):
            img = _procedural(ctx, L, idx, t)
        elif t == "shape":
            img = _shape(ctx, L, idx)
        elif t == "text":
            img = _text(ctx, L, idx)
        elif t == "image":
            img = _image(ctx, L, idx)
        else:
            img = _svg(ctx, L, idx)
        src = _arr(img)
        src[..., 3] *= float(L.get("opacity", 1.0))
        cm = _clip_mask(ctx, L)
        if cm is not None:
            src[..., 3] *= cm
        dst = _composite(dst, src, mode)
    out = np.clip(dst * 255 + 0.5, 0, 255).astype(np.uint8)
    out[..., 3] = 255
    if warnings is not None:
        warnings.extend(warn)
    return Image.fromarray(out, "RGBA")
