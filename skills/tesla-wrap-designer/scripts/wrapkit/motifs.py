"""Procedural motif and noise generators. Pure Pillow + numpy, deterministic by seed.

Every generator returns an RGBA PIL image of the requested canvas size.
Use render_pattern(kind, size, params, seed) / render_noise(kind, size, params, seed).
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .color import parse_color

SS = 2  # supersampling factor for drawn shapes

PALETTES = {
    "party": ["#ff4d6d", "#ffd23f", "#3bceac", "#4cc9f0", "#b388ff", "#ff9f1c", "#ffffff"],
    "stars": ["#ffd54a", "#ffffff", "#ff8fab"],
    "white_stars": ["#ffffff", "#cfe3ff", "#fff1cf", "#ffd6e8"],
}

COMMON_KEYS = {"colors", "density", "size", "angle", "seed", "bg", "count"}


# ---------------------------------------------------------------- helpers

def _smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0 if e1 != e0 else 1e-6), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _cols(colors, default):
    cs = colors if colors else default
    if isinstance(cs, str):
        cs = [cs]
    return np.array([parse_color(c) for c in cs], dtype=np.float32) / 255.0


def _num(v, length):
    if isinstance(v, str) and v.strip().endswith("%"):
        return float(v.strip()[:-1]) / 100.0 * length
    return float(v)


def _pt(v, W, H, default):
    if v is None:
        return default
    return (_num(v[0], W), _num(v[1], H))


def _to_img(arr) -> Image.Image:
    a = np.clip(arr * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(a, "RGBA")


def _from_img(img) -> np.ndarray:
    return np.asarray(img.convert("RGBA"), dtype=np.float32) / 255.0


def _over(dst, src):
    """Straight-alpha float RGBA 'over' compositing."""
    sa = src[..., 3:4]
    da = dst[..., 3:4]
    oa = sa + da * (1 - sa)
    rgb = (src[..., :3] * sa + dst[..., :3] * da * (1 - sa)) / np.maximum(oa, 1e-6)
    return np.concatenate([rgb, oa], -1)


def _ramp(t, cols, pos=None):
    cols = np.asarray(cols, dtype=np.float32)
    n = len(cols)
    if n == 1:
        return np.broadcast_to(cols[0], t.shape + (4,)).copy()
    pos = np.linspace(0, 1, n) if pos is None else np.asarray(pos, dtype=np.float32)
    out = np.empty(t.shape + (4,), np.float32)
    for c in range(4):
        out[..., c] = np.interp(t, pos, cols[:, c])
    return out


def _hash(ix, iy, seed, salt=0):
    with np.errstate(over="ignore"):
        h = (np.asarray(ix).astype(np.int64).astype(np.uint32) * np.uint32(374761393)
             + np.asarray(iy).astype(np.int64).astype(np.uint32) * np.uint32(668265263)
             + np.uint32((seed * 2246822519 + salt * 3266489917) % (2 ** 32)))
        h = (h ^ (h >> np.uint32(13))) * np.uint32(1274126177)
        h = h ^ (h >> np.uint32(16))
    return h.astype(np.float32) / np.float32(4294967295.0)


def _finish(layer: Image.Image, W, H, p) -> Image.Image:
    if layer.size != (W, H):
        layer = layer.resize((W, H), Image.LANCZOS)
    bg = p.get("bg")
    if bg:
        base = Image.new("RGBA", (W, H), parse_color(bg))
        layer = Image.alpha_composite(base, layer)
    return layer


def _paste(base: Image.Image, patch: Image.Image, x: int, y: int):
    """alpha-composite patch onto base at (x, y), clipping at the borders."""
    bw, bh = base.size
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(bw, x + patch.width), min(bh, y + patch.height)
    if x1 <= x0 or y1 <= y0:
        return
    crop = patch.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    region = base.crop((x0, y0, x1, y1))
    base.paste(Image.alpha_composite(region, crop), (x0, y0))


def _count(p, W, H, per_area, default_density=1.0):
    if p.get("count") is not None:
        return int(p["count"])
    return max(1, int(round(float(p.get("density", default_density)) * W * H / per_area)))


def _rgba8(c):
    return tuple(int(round(x * 255)) for x in c)


# ---------------------------------------------------------------- noise

def _value_noise(W, H, rng, scale):
    scale = max(1.5, float(scale))
    gw, gh = int(W / scale) + 3, int(H / scale) + 3
    G = rng.random((gh, gw), dtype=np.float32)
    x = np.arange(W, dtype=np.float32) / scale
    y = np.arange(H, dtype=np.float32) / scale
    ix, iy = x.astype(np.int32), y.astype(np.int32)
    fx, fy = x - ix, y - iy
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    A = G[:, ix] * (1 - fx) + G[:, ix + 1] * fx
    return A[iy] * (1 - fy)[:, None] + A[iy + 1] * fy[:, None]


def fbm(W, H, rng, scale=200.0, octaves=5, persistence=0.5, lacunarity=2.0, normalize=True):
    """Fractal value noise, shape (H, W), float32 in 0..1 (percentile-stretched)."""
    total = np.zeros((H, W), np.float32)
    amp, s, norm = 1.0, float(scale), 0.0
    for _ in range(max(1, int(octaves))):
        total += amp * _value_noise(W, H, rng, s)
        norm += amp
        amp *= persistence
        s /= lacunarity
        if s < 2:
            break
    total /= norm
    if normalize:
        lo, hi = np.percentile(total[::4, ::4], [1, 99])
        total = np.clip((total - lo) / max(hi - lo, 1e-6), 0, 1)
    return total


def _warp(field, dx, dy, amp):
    H, W = field.shape
    Y, X = np.mgrid[0:H, 0:W]
    xi = np.clip(X + ((dx - 0.5) * 2 * amp).astype(np.int32), 0, W - 1)
    yi = np.clip(Y + ((dy - 0.5) * 2 * amp).astype(np.int32), 0, H - 1)
    return field[yi, xi]


def _noise_clouds(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#3b6fb6", "#ffffff"])
    t = fbm(W, H, rng, p.get("scale", 220), p.get("octaves", 5))
    t = np.clip((t - 0.5) * float(p.get("contrast", 1.6)) + 0.5, 0, 1)
    return _ramp(t, cols)


def _noise_nebula(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#05010f", "#3b1a8c", "#c2307f", "#ff8a3d", "#4cd0ff"])
    scale = float(p.get("scale", 280))
    octv = int(p.get("octaves", 6))
    contrast = float(p.get("contrast", 1.0))
    bg, tint = cols[0], cols[1:] if len(cols) > 1 else cols
    base = fbm(W, H, rng, scale, octv)
    for _ in range(2):
        dx = fbm(W, H, rng, scale * 0.9, 3)
        dy = fbm(W, H, rng, scale * 0.9, 3)
        base = _warp(base, dx, dy, scale * 0.45)
    hue = _warp(fbm(W, H, rng, scale * 1.6, 3), fbm(W, H, rng, scale, 3), fbm(W, H, rng, scale, 3), scale * 0.5)
    dust = fbm(W, H, rng, scale * 0.7, 5)
    inten = _smooth(0.28, 0.9, base) ** 1.35
    inten = np.clip(inten * contrast * 1.25, 0, 1.4)
    core = _smooth(0.65, 1.0, base) ** 2
    ramp_t = np.clip(0.15 + 0.7 * hue + 0.25 * core, 0, 1)
    col = _ramp(ramp_t, tint)[..., :3]
    col = col * (1.0 - 0.55 * _smooth(0.55, 0.85, dust) * _smooth(0.2, 0.6, base))[..., None]
    rgb = bg[:3][None, None, :] + col * inten[..., None]
    rgb = rgb + core[..., None] * 0.35 * np.array([1, 0.9, 0.85], np.float32)
    out = np.empty((H, W, 4), np.float32)
    out[..., :3] = np.clip(rgb, 0, 1)
    out[..., 3] = np.clip(bg[3] + (1 - bg[3]) * np.clip(inten + core, 0, 1), 0, 1)
    return out


def _noise_marble(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#f6f3ee", "#9a9aa6", "#23232b"])
    scale = float(p.get("scale", 320))
    turb = float(p.get("turbulence", 5.0))
    n = fbm(W, H, rng, scale * 0.6, int(p.get("octaves", 6)), normalize=False)
    Y, X = np.mgrid[0:H, 0:W].astype(np.float32)
    ang = math.radians(float(p.get("angle", 35)))
    u = (X * math.cos(ang) + Y * math.sin(ang)) / scale
    v = np.sin((u * 2.2 + (n - 0.5) * turb) * math.pi)
    vein = 1.0 - np.abs(v)
    sharp = float(p.get("contrast", 1.0)) * 6.0
    vein = np.clip(vein, 0, 1) ** sharp
    cloud = fbm(W, H, rng, scale * 0.9, 4)
    t = np.clip(0.2 * cloud + 0.8 * (1 - vein) * 0.0 + vein * 0.9, 0, 1)
    t = 1 - t
    return _ramp(t, cols)


def _noise_camo(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#4b5320", "#8a8d5b", "#2e3319", "#c2b280"])
    scale = float(p.get("scale", 120))
    n = fbm(W, H, rng, scale, int(p.get("octaves", 3)), 0.45)
    # distinct quantile thresholds so every colour gets a fair share
    k = len(cols)
    qs = np.quantile(n[::3, ::3], np.linspace(0, 1, k + 1)[1:-1]) if k > 1 else []
    out = np.broadcast_to(cols[0], (H, W, 4)).copy()
    e = 0.012
    for i, q in enumerate(qs):
        m = _smooth(q - e, q + e, n)[..., None]
        out = out * (1 - m) + cols[i + 1] * m
    return out


NOISE_DEFAULTS = {
    "clouds": {"scale": 220, "octaves": 5, "contrast": 1.6},
    "nebula": {"scale": 280, "octaves": 6, "contrast": 1.0},
    "marble": {"scale": 320, "octaves": 6, "contrast": 1.0, "turbulence": 5.0, "angle": 35},
    "camo": {"scale": 120, "octaves": 3},
}
_NOISE_FN = {"clouds": _noise_clouds, "nebula": _noise_nebula, "marble": _noise_marble, "camo": _noise_camo}
NOISE_KINDS = list(_NOISE_FN)


def render_noise(kind, size, params=None, seed=0) -> Image.Image:
    if kind not in _NOISE_FN:
        raise ValueError(f"Unknown noise kind {kind!r}. Choose from: {', '.join(NOISE_KINDS)}")
    p = dict(params or {})
    W, H = int(size[0]), int(size[1])
    rng = np.random.default_rng(int(p.get("seed", seed)))
    return _finish(_to_img(_NOISE_FN[kind](W, H, rng, p)), W, H, p)


# ---------------------------------------------------------------- shape helpers

def _star_poly(cx, cy, R, r, n, rot):
    pts = []
    for i in range(n * 2):
        a = rot + i * math.pi / n
        rad = R if i % 2 == 0 else r
        pts.append((cx + rad * math.sin(a), cy - rad * math.cos(a)))
    return pts


def _rand_cols(rng, cols, n):
    return cols[rng.integers(0, len(cols), n)]


# ---------------------------------------------------------------- scatter patterns (PIL @2x)

def _canvas(W, H):
    img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _p_stars(W, H, rng, p):
    cols = _cols(p.get("colors"), PALETTES["stars"])
    size = float(p.get("size", 26))
    n = _count(p, W, H, (size * 3.4) ** 2)
    pts_n, inner = int(p.get("points", 5)), float(p.get("inner_ratio", 0.45))
    img, d = _canvas(W, H)
    for i in range(n):
        R = size * rng.uniform(0.45, 1.25) * SS
        cx, cy = rng.uniform(0, W * SS), rng.uniform(0, H * SS)
        c = _rgba8(cols[rng.integers(len(cols))])
        d.polygon(_star_poly(cx, cy, R, R * inner, pts_n, rng.uniform(-0.5, 0.5)), fill=c)
    return img


def _p_dots(W, H, rng, p):
    cols = _cols(p.get("colors"), PALETTES["party"])
    size = float(p.get("size", 14))
    n = _count(p, W, H, (size * 4.0) ** 2)
    img, d = _canvas(W, H)
    for _ in range(n):
        r = size * rng.uniform(0.3, 1.2) * SS
        cx, cy = rng.uniform(0, W * SS), rng.uniform(0, H * SS)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_rgba8(cols[rng.integers(len(cols))]))
    return img


def _p_confetti(W, H, rng, p):
    cols = _cols(p.get("colors"), PALETTES["party"])
    size = float(p.get("size", 20))
    n = _count(p, W, H, size * size * 5.5)
    img, d = _canvas(W, H)
    for _ in range(n):
        cx, cy = rng.uniform(0, W * SS), rng.uniform(0, H * SS)
        c = cols[rng.integers(len(cols))]
        fill = _rgba8(c)
        s = size * rng.uniform(0.55, 1.2) * SS
        kind = rng.random()
        rot = rng.uniform(0, math.tau)
        co, si = math.cos(rot), math.sin(rot)

        def tf(pts):
            return [(cx + x * co - y * si, cy + x * si + y * co) for x, y in pts]

        if kind < 0.5:
            w = s * rng.uniform(0.3, 0.9)
            pts = tf([(-s / 2, -w / 2), (s / 2, -w / 2), (s / 2, w / 2), (-s / 2, w / 2)])
            d.polygon(pts, fill=fill)
        elif kind < 0.65:
            r = s * 0.28
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
        elif kind < 0.82:
            pts = []
            amp, k = s * 0.22, rng.uniform(1.2, 2.2)
            for i in range(17):
                t = i / 16
                pts.append((-s * 0.7 + t * s * 1.4, math.sin(t * k * math.tau) * amp))
            d.line(tf(pts), fill=fill, width=max(2, int(s * 0.17)), joint="curve")
        else:
            pts = tf([(0, -s * 0.5), (s * 0.45, s * 0.35), (-s * 0.45, s * 0.35)])
            d.polygon(pts, fill=fill)
    return img


def _p_hearts(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#ff4d6d", "#ff8fab", "#ffb3c6", "#c9184a", "#ffffff"])
    size = float(p.get("size", 34))
    n = _count(p, W, H, (size * 3.6) ** 2)
    t = np.linspace(0, math.tau, 64)
    hx = 16 * np.sin(t) ** 3
    hy = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))
    img, d = _canvas(W, H)
    gloss = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(gloss)
    for _ in range(n):
        s = size * rng.uniform(0.5, 1.2) * SS / 17.0
        cx, cy = rng.uniform(0, W * SS), rng.uniform(0, H * SS)
        rot = math.radians(rng.uniform(-28, 28))
        co, si = math.cos(rot), math.sin(rot)
        pts = [(cx + (x * co - y * si) * s, cy + (x * si + y * co) * s) for x, y in zip(hx, hy)]
        d.polygon(pts, fill=_rgba8(cols[rng.integers(len(cols))]))
        gx, gy = -7.5, -6.5
        gc = (cx + (gx * co - gy * si) * s, cy + (gx * si + gy * co) * s)
        rr = 2.6 * s
        gd.ellipse([gc[0] - rr, gc[1] - rr * 0.7, gc[0] + rr, gc[1] + rr * 0.7], fill=(255, 255, 255, 95))
    return Image.alpha_composite(img, gloss)


def _p_clouds_cartoon(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#ffffff", "#dcefff", "#9fd2f4"])
    fill, shade, outline = (_rgba8(cols[i % len(cols)]) for i in range(3))
    size = float(p.get("size", 300))
    n = _count(p, W, H, size * size * 1.5)
    ow = float(p.get("outline", 7)) * SS
    img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    placed = []
    for _ in range(n):
        wc = size * rng.uniform(0.55, 1.4)
        for _try in range(25):
            cx, cy = rng.uniform(0, W), rng.uniform(0, H)
            if all((cx - px) ** 2 + (cy - py) ** 2 > ((wc + pw) * 0.42) ** 2 for px, py, pw in placed):
                break
        placed.append((cx, cy, wc))
        pw_, ph_ = int((wc * 1.5) * SS), int((wc * 0.95) * SS)
        # bumps along a flat baseline
        k = int(rng.integers(3, 6))
        xs = np.linspace(-0.36, 0.36, k) * wc * SS
        prof = np.sin(np.linspace(0.25, math.pi - 0.25, k)) * rng.uniform(0.85, 1.15, k)
        base_y = ph_ * 0.78
        ccx = pw_ / 2
        circles = []
        for x, pr in zip(xs, prof):
            r = wc * SS * (0.11 + 0.11 * pr)
            circles.append((ccx + x, base_y - r * 0.82, r))
        r0 = circles[0][2]
        r1 = circles[-1][2]
        masks = {}
        for name, grow in (("f", 0.0), ("o", ow)):
            m = Image.new("L", (pw_, ph_), 0)
            md = ImageDraw.Draw(m)
            for x, y, r in circles:
                md.ellipse([x - r - grow, y - r - grow, x + r + grow, y + r + grow], fill=255)
            md.rounded_rectangle([circles[0][0] - r0 * 0.2 - grow, base_y - r0 * 0.9 - grow,
                                  circles[-1][0] + r1 * 0.2 + grow, base_y + grow], radius=r0 * 0.9, fill=255)
            md.rectangle([0, base_y + (grow if name == "o" else 0), pw_, ph_], fill=0)
            masks[name] = m
        fm = masks["f"]
        shifted = Image.new("L", fm.size, 0)
        shifted.paste(fm, (0, -int(wc * SS * 0.10)))
        shade_m = Image.fromarray((np.asarray(fm, np.float32) * (1 - np.asarray(shifted, np.float32) / 255)).astype(np.uint8))
        om = masks["o"].filter(ImageFilter.GaussianBlur(0.8 * SS))
        patch = Image.new("RGBA", fm.size, (0, 0, 0, 0))
        patch.paste(Image.new("RGBA", fm.size, outline), (0, 0), om)
        patch.paste(Image.new("RGBA", fm.size, fill), (0, 0), fm)
        patch.paste(Image.new("RGBA", fm.size, shade), (0, 0), shade_m)
        _paste(img, patch, int(cx * SS - pw_ / 2), int(cy * SS - base_y))
    return img


def _stamp_add(acc, x, y, col, core_s, glow_s, glow_a, spike_len=0.0, spike_a=0.0, diag=False):
    H, W, _ = acc.shape
    half = int(max(3.2 * glow_s, spike_len, 3 * core_s)) + 2
    x0, x1 = int(x) - half, int(x) + half + 1
    y0, y1 = int(y) - half, int(y) + half + 1
    cx0, cx1, cy0, cy1 = max(0, x0), min(W, x1), max(0, y0), min(H, y1)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    xx = (np.arange(cx0, cx1, dtype=np.float32) - x)[None, :]
    yy = (np.arange(cy0, cy1, dtype=np.float32) - y)[:, None]
    r2 = xx * xx + yy * yy
    v = np.exp(-r2 / (2 * core_s ** 2)) + glow_a * np.exp(-r2 / (2 * glow_s ** 2))
    if spike_len > 0:
        sw = max(0.55, core_s * 0.5)
        hs = np.exp(-np.abs(xx) / (spike_len * 0.28)) * np.exp(-yy * yy / (2 * sw * sw))
        vs = np.exp(-np.abs(yy) / (spike_len * 0.28)) * np.exp(-xx * xx / (2 * sw * sw))
        v = v + spike_a * (hs + vs)
    acc[cy0:cy1, cx0:cx1] += v[..., None] * col[None, None, :3]


def _acc_to_rgba(acc):
    a = np.clip(acc.max(-1), 0, 1)
    rgb = np.clip(acc / np.maximum(a, 1e-6)[..., None], 0, 1)
    return np.dstack([rgb, a]).astype(np.float32)


def _splat(acc, xs, ys, cols, br):
    H, W, _ = acc.shape
    x0, y0 = np.floor(xs).astype(int), np.floor(ys).astype(int)
    fx, fy = xs - x0, ys - y0
    for dx, dy, w in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)),
                      (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
        xi, yi = np.clip(x0 + dx, 0, W - 1), np.clip(y0 + dy, 0, H - 1)
        for c in range(3):
            np.add.at(acc[..., c], (yi, xi), cols[:, c] * br * w)


def _p_starfield(W, H, rng, p):
    cols = _cols(p.get("colors"), PALETTES["white_stars"])
    dens = float(p.get("density", 1.0))
    size = float(p.get("size", 5))
    A = W * H / 1048576.0
    acc = np.zeros((H, W, 3), np.float32)
    nt = int(p.get("count", 2600 * A * dens))
    _splat(acc, rng.uniform(0, W - 1.01, nt), rng.uniform(0, H - 1.01, nt),
           _rand_cols(rng, cols, nt), 0.35 + 0.9 * rng.random(nt) ** 2.2)
    nm = int(380 * A * dens)
    for _ in range(nm):
        r = rng.uniform(0.7, 1.3) * max(1.0, size * 0.28)
        _stamp_add(acc, rng.uniform(0, W), rng.uniform(0, H), cols[rng.integers(len(cols))],
                   r * 0.6, r * 2.6, 0.35, 0, 0)
    nb = int(26 * A * dens)
    for _ in range(nb):
        r = rng.uniform(0.7, 1.2) * size * 0.4
        _stamp_add(acc, rng.uniform(0, W), rng.uniform(0, H), cols[rng.integers(len(cols))],
                   r * 0.7, r * 3.2, 0.35, size * rng.uniform(4, 9), 0.9)
    return _to_img(_acc_to_rgba(acc))


def _p_sparkles(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#ffffff", "#ffe9a8", "#ffd1f0", "#bfe8ff"])
    size = float(p.get("size", 22))
    n = _count(p, W, H, (size * 4.5) ** 2)
    acc = np.zeros((H, W, 3), np.float32)
    for _ in range(n):
        R = size * rng.uniform(0.35, 1.2)
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        c = cols[rng.integers(len(cols))]
        half = int(R * 3) + 2
        x0, x1, y0, y1 = int(x) - half, int(x) + half + 1, int(y) - half, int(y) + half + 1
        cx0, cx1, cy0, cy1 = max(0, x0), min(W, x1), max(0, y0), min(H, y1)
        if cx1 <= cx0 or cy1 <= cy0:
            continue
        xx = np.abs(np.arange(cx0, cx1, dtype=np.float32) - x)[None, :]
        yy = np.abs(np.arange(cy0, cy1, dtype=np.float32) - y)[:, None]
        s = (xx / R) ** 0.62 + (yy / R) ** 0.62
        shape = _smooth(1.0, 0.82, s)
        glow = 0.55 * np.exp(-(xx ** 2 + yy ** 2) / (2 * (0.38 * R) ** 2))
        v = shape + glow
        acc[cy0:cy1, cx0:cx1] += v[..., None] * c[None, None, :3] + (shape ** 3)[..., None] * 0.6
    return _to_img(_acc_to_rgba(acc))


def _p_bokeh(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#ff9ad5", "#ffd166", "#7bdff2", "#b8a1ff", "#ffffff"])
    size = float(p.get("size", 70))
    n = _count(p, W, H, (size * 2.6) ** 2)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for _ in range(n):
        r = size * (0.25 + 0.75 * rng.random() ** 1.5)
        cx, cy = rng.uniform(-r * 0.3, W + r * 0.3), rng.uniform(-r * 0.3, H + r * 0.3)
        c = cols[rng.integers(len(cols))]
        a = rng.uniform(0.18, 0.5)
        half = int(r) + 3
        g = np.arange(-half, half + 1, dtype=np.float32)
        dist = np.sqrt(g[None, :] ** 2 + g[:, None] ** 2) / r
        disc = _smooth(1.0 + 1.2 / r, 1.0 - 1.2 / r, dist)
        rim = 0.55 + 0.45 * _smooth(0.65, 0.97, dist)
        al = disc * rim * a
        patch = np.dstack([np.broadcast_to(c[:3], al.shape + (3,)), al])
        _paste(img, _to_img(patch.astype(np.float32)), int(cx) - half, int(cy) - half)
    return img


def _balloon_patch(R, col, rng):
    ss = 3
    a, b = 0.8 * R * ss, R * ss
    pw, ph = int(2.5 * a), int(2.0 * b + 0.5 * R * ss)
    cx, cy = pw / 2, b * 1.12
    t = np.linspace(0, math.tau, 120)
    pts = [(cx + a * math.sin(u) * (1 + 0.12 * math.cos(u)), cy - b * math.cos(u)) for u in t]
    m = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(m).polygon(pts, fill=255)
    yy, xx = np.mgrid[0:ph, 0:pw].astype(np.float32)
    nx, ny = (xx - cx) / a, (yy - cy) / b
    r2 = np.clip(nx ** 2 + ny ** 2, 0, 1)
    nz = np.sqrt(1 - r2)
    L = np.array([-0.45, -0.55, 0.7], np.float32)
    L /= np.linalg.norm(L)
    diff = np.clip(nx * L[0] + ny * L[1] + nz * L[2], 0, 1)
    light = 0.58 + 0.5 * diff
    light *= 1 - 0.28 * r2 ** 2
    hl = np.exp(-((nx + 0.4) ** 2 + (ny + 0.42) ** 2) / (2 * 0.13 ** 2)) * 0.55
    ell = _smooth(1.0, 0.8, np.sqrt(((nx + 0.45) / 0.09) ** 2 + ((ny + 0.5) / 0.2) ** 2))
    rgb = col[:3][None, None, :] * light[..., None] + hl[..., None] + ell[..., None] * 0.5
    arr = np.dstack([np.clip(rgb, 0, 1), np.asarray(m, np.float32) / 255]).astype(np.float32)
    patch = _to_img(arr)
    kd = ImageDraw.Draw(patch)
    kb = cy + b * 0.98
    kc = _rgba8(np.append(col[:3] * 0.72, 1.0))
    kw, kh = 0.11 * R * ss, 0.17 * R * ss
    kd.polygon([(cx, kb - kh * 0.5), (cx - kw, kb + kh), (cx + kw, kb + kh)], fill=kc)
    patch = patch.resize((pw // ss, ph // ss), Image.LANCZOS)
    return patch, (cx / ss, kb / ss + kh / ss)


def _p_balloons(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#ff3b5c", "#ffcc00", "#2ec4b6", "#4361ee", "#b5179e", "#ff8c1a"])
    size = float(p.get("size", 80))
    n = _count(p, W, H, (size * 3.2) ** 2)
    slen = float(p.get("string_length", 2.6))
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    strings = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    sd = ImageDraw.Draw(strings)
    sc = parse_color(p.get("string_color", "#f2f2f2"))
    items = []
    for _ in range(n):
        R = size * rng.uniform(0.65, 1.2)
        items.append((R, rng.uniform(0, W), rng.uniform(0, H), cols[rng.integers(len(cols))]))
    items.sort(key=lambda t: t[0])
    patches = []
    for R, x, y, c in items:
        patch, knot = _balloon_patch(R, c, rng)
        px, py = int(x - patch.width / 2), int(y - knot[1] * 0.45)
        kx, ky = px + knot[0], py + knot[1]
        L = R * slen * rng.uniform(0.8, 1.2)
        ph0 = rng.uniform(0, math.tau)
        sway = rng.uniform(0.05, 0.14) * R
        pts = []
        for i in range(30):
            t = i / 29
            pts.append(((kx + math.sin(t * 5.2 + ph0) * sway * t) * SS, (ky + t * L) * SS))
        sd.line(pts, fill=sc, width=max(2, int(1.7 * SS)), joint="curve")
        patches.append((patch, px, py))
    img = strings.resize((W, H), Image.LANCZOS)
    for patch, px, py in patches:
        _paste(img, patch, px, py)
    return img


# ---------------------------------------------------------------- lattice / analytic patterns

def _xy(W, H):
    Y, X = np.mgrid[0:H, 0:W].astype(np.float32)
    return X + 0.5, Y + 0.5


def _rot(X, Y, ang_deg, cx=0.0, cy=0.0):
    a = math.radians(ang_deg)
    c, s = math.cos(a), math.sin(a)
    return (X - cx) * c + (Y - cy) * s, -(X - cx) * s + (Y - cy) * c


def _cell_mix(cols, idx, edge_blend, prev_idx):
    return cols[prev_idx] * (1 - edge_blend[..., None]) + cols[idx] * edge_blend[..., None]


def _p_stripes(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#ff4d6d", "#ffffff"])
    width = float(p.get("width", p.get("size", 40)))
    X, Y = _xy(W, H)
    u, _ = _rot(X, Y, float(p.get("angle", 45)))
    u = u / width + float(p.get("offset", 0))
    k = np.floor(u).astype(np.int32)
    f = u - k
    n = len(cols)
    bl = np.clip(f * width, 0, 1)
    out = cols[k % n] * bl[..., None] + cols[(k - 1) % n] * (1 - bl)[..., None]
    return out


def _p_checker(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#111111", "#ffffff"])
    size = float(p.get("size", 64))
    s2 = 2
    X, Y = _xy(W * s2, H * s2)
    X, Y = X / s2, Y / s2
    u, v = _rot(X, Y, float(p.get("angle", 0)))
    m = ((np.floor(u / size) + np.floor(v / size)) % 2).astype(np.float32)
    m = m.reshape(H, s2, W, s2).mean((1, 3))
    return cols[0] * (1 - m)[..., None] + cols[1 % len(cols)] * m[..., None]


def _lattice(W, H, spacing, angle, stagger):
    X, Y = _xy(W, H)
    u, v = _rot(X, Y, angle)
    row = np.floor(v / spacing)
    off = (row % 2) * spacing * 0.5 if stagger else 0.0
    col = np.floor((u + off) / spacing)
    cu = (col + 0.5) * spacing - off
    cv = (row + 0.5) * spacing
    d = np.hypot(u - cu, v - cv)
    a = -math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    ix = cu * c + cv * s
    iy = -cu * s + cv * c
    return d, ix, iy, row, col


def _p_polka(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#ff4d6d", "#ffd23f"])
    sp = float(p.get("spacing", p.get("size", 56)))
    r = float(p.get("radius", sp * 0.3))
    d, _, _, row, col = _lattice(W, H, sp, float(p.get("angle", 20)), True)
    m = np.clip(r - d + 0.5, 0, 1)
    idx = ((row + col) % len(cols)).astype(np.int32) if len(cols) > 1 else np.zeros(d.shape, np.int32)
    out = cols[idx].copy()
    out[..., 3] *= m
    return out


def _p_halftone(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#ff4d6d"])
    sp = float(p.get("spacing", p.get("size", 18)))
    d, ix, iy, _, _ = _lattice(W, H, sp, float(p.get("angle", 45)), False)
    fade = p.get("fade", "linear")
    if fade == "radial":
        cx, cy = _pt(p.get("center"), W, H, (W / 2, H / 2))
        t = np.hypot(ix - cx, iy - cy) / math.hypot(max(cx, W - cx), max(cy, H - cy))
    else:
        a = math.radians(float(p.get("fade_angle", 90)))
        proj = ix * math.cos(a) + iy * math.sin(a)
        corners = [0, W * math.cos(a), H * math.sin(a), W * math.cos(a) + H * math.sin(a)]
        t = (proj - min(corners)) / max(max(corners) - min(corners), 1)
    t = np.clip(t, 0, 1)
    if p.get("invert"):
        t = 1 - t
    r = sp * 0.74 * np.sqrt(t) * float(p.get("max_radius", 1.0))
    m = np.clip(r - d + 0.5, 0, 1)
    out = np.broadcast_to(cols[0], d.shape + (4,)).copy()
    if len(cols) > 1:
        out = _ramp(t, cols)
    out[..., 3] *= m
    return out


def _p_hex(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#0f2742", "#16406b", "#1d5f9a", "#2a82c9"])
    R = float(p.get("size", 44))
    lw = float(p.get("line", 2.5))
    lc = np.array(parse_color(p.get("line_color", "#7fd1ff")), np.float32) / 255
    X, Y = _xy(W, H)
    u, v = _rot(X, Y, float(p.get("angle", 0)))
    q = (2 / 3 * u) / R
    r = (-1 / 3 * u + math.sqrt(3) / 3 * v) / R
    x, z = q, r
    y = -x - z
    rx, ry, rz = np.round(x), np.round(y), np.round(z)
    dx, dy, dz = np.abs(rx - x), np.abs(ry - y), np.abs(rz - z)
    fx = (dx > dy) & (dx > dz)
    fy = (~fx) & (dy > dz)
    rx = np.where(fx, -ry - rz, rx)
    rz = np.where(~fx & ~fy, -rx - ry, rz)
    cu = R * 1.5 * rx
    cv = R * math.sqrt(3) * (rz + rx / 2)
    du, dv = u - cu, v - cv
    ap = R * math.sqrt(3) / 2
    h = np.maximum.reduce([np.abs(dv), np.abs(0.8660254 * du + 0.5 * dv), np.abs(0.8660254 * du - 0.5 * dv)])
    hv = _hash(rx, rz, int(p.get("seed", 0)) + 7)
    idx = (hv * len(cols)).astype(np.int32) % len(cols)
    fill = cols[idx].copy()
    fill *= (0.85 + 0.3 * _hash(rx, rz, 3))[..., None].astype(np.float32).clip(0, 1.3)
    fill[..., 3] = cols[idx][..., 3]
    edge = np.clip((h - (ap - lw)) / 1.0 + 0.5, 0, 1) * np.clip((ap + 0.5 - h) * 0 + 1, 0, 1)
    edge = _smooth(ap - lw - 0.5, ap - lw + 0.5, h)
    if lw <= 0:
        edge = edge * 0
    out = fill * (1 - edge[..., None]) + lc[None, None, :] * edge[..., None]
    out[..., 3] = np.where(edge > 0, np.maximum(fill[..., 3], edge * lc[3]), fill[..., 3])
    return np.clip(out, 0, 1)


def _p_rays(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#ffd23f", "#ffb703"])
    n = int(p.get("rays", 24)) * 2
    cx, cy = _pt(p.get("center"), W, H, (W / 2, H / 2))
    X, Y = _xy(W, H)
    dx, dy = X - cx, Y - cy
    th = (np.arctan2(dy, dx) + math.radians(float(p.get("angle", 0)))) / math.tau * n
    r = np.hypot(dx, dy)
    k = np.floor(th).astype(np.int32)
    f = th - k
    bl = np.clip(f * r * math.tau / n, 0, 1)
    m = len(cols) if len(cols) > 1 else 2
    c0 = cols[k % len(cols)]
    c1 = cols[(k - 1) % len(cols)]
    if len(cols) == 1:
        c1 = c1.copy()
        c1[..., 3] = 0
        c0 = np.where(((k % 2) == 0)[..., None], cols[0], np.concatenate([cols[0][:3], [0]])[None, None, :]).astype(np.float32)
        c1 = np.where(((k % 2) == 1)[..., None], cols[0], np.concatenate([cols[0][:3], [0]])[None, None, :]).astype(np.float32)
    out = c0 * bl[..., None] + c1 * (1 - bl)[..., None]
    fade = float(p.get("fade", 0.0))
    if fade > 0:
        out[..., 3] *= 1 - fade * np.clip(r / math.hypot(max(cx, W - cx), max(cy, H - cy)), 0, 1)
    return out


def _p_carbon(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#0e0f11", "#3d434c"])
    s = float(p.get("size", 12))
    X, Y = _xy(W, H)
    u, v = _rot(X, Y, float(p.get("angle", 0)))
    u, v = u / s, v / s
    i, j = np.floor(u), np.floor(v)
    fx, fy = u - i, v - j
    ph = ((i - j) % 4)
    horiz = ph < 2
    q = np.where(horiz, (ph + fx) / 2, (ph - 2 + fy) / 2)
    cross = np.where(horiz, fy, fx)
    env = np.sin(np.pi * np.clip(q, 0, 1)) ** 0.6
    prof = 0.3 + 0.7 * np.sin(np.pi * cross) ** 0.8
    b = np.clip(env * prof, 0, 1)
    b = np.where(horiz, b, b * 0.82)
    sheen = float(p.get("sheen", 0.3))
    if sheen > 0:
        band = np.exp(-(((X + Y) / (W + H) - 0.45) / 0.18) ** 2)
        b = np.clip(b * (1 + sheen * 1.4 * band), 0, 1)
    return _ramp(b, cols[:2] if len(cols) >= 2 else np.vstack([cols[0] * 0.3, cols[0]]))


def _p_grid(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#38bdf8", "#ffffff"])
    sp = float(p.get("spacing", p.get("size", 64)))
    lw = float(p.get("line", 2))
    major = int(p.get("major", 0))
    X, Y = _xy(W, H)
    u, v = _rot(X, Y, float(p.get("angle", 0)))
    out = np.zeros((H, W, 4), np.float32)

    def lines(coord, step, width):
        d = np.abs(((coord + step / 2) % step) - step / 2)
        return np.clip(width / 2 + 0.5 - d, 0, 1)

    m = np.maximum(lines(u, sp, lw), lines(v, sp, lw))
    out[...] = cols[0]
    out[..., 3] = m * cols[0][3]
    if major > 0:
        M = np.maximum(lines(u, sp * major, lw * 2), lines(v, sp * major, lw * 2))
        c1 = cols[1 % len(cols)]
        out = _over(out, np.dstack([np.broadcast_to(c1[:3], (H, W, 3)), M * c1[3]]).astype(np.float32))
    return out


def _p_waves(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#0077b6", "#00b4d8", "#48cae4", "#90e0ef", "#caf0f8"])
    nb = int(p.get("bands", len(cols)))
    amp = float(p.get("amplitude", 36))
    wl = float(p.get("wavelength", 340))
    X, Y = _xy(W, H)
    u, v = _rot(X, Y, float(p.get("angle", 0)), W / 2, H / 2)
    v = v + H / 2
    u = u + W / 2
    out = np.zeros((H, W, 4), np.float32)
    start = float(p.get("start", 0.25))
    for k in range(nb):
        y0 = H * (start + (1 - start) * k / nb)
        ph = rng.uniform(0, math.tau)
        curve = y0 + amp * np.sin(u / wl * math.tau + ph) + 0.35 * amp * np.sin(u / (wl * 0.43) * math.tau + ph * 2)
        m = np.clip(v - curve + 0.5, 0, 1)
        c = cols[k % len(cols)]
        src = np.dstack([np.broadcast_to(c[:3], (H, W, 3)), m * c[3]]).astype(np.float32)
        out = _over(out, src)
    return out


def _p_lightspeed(W, H, rng, p):
    cols = _cols(p.get("colors"), ["#ffffff", "#bfe0ff", "#8fb4ff", "#e3d6ff"])
    cx, cy = _pt(p.get("center"), W, H, (W / 2, H / 2))
    dens = float(p.get("density", 1.0))
    width = float(p.get("width", 1.3))
    length = float(p.get("length", 0.55))
    clear = float(p.get("clear_center", min(W, H) * 0.05))
    X, Y = _xy(W, H)
    dx, dy = X - cx, Y - cy
    r = np.hypot(dx, dy)
    th = np.arctan2(dy, dx) + math.pi
    rmax = math.hypot(max(cx, W - cx), max(cy, H - cy))
    acc = np.zeros((H, W, 3), np.float32)
    layers = [(int(520 * dens), 1.0), (int(260 * dens), 1.6), (int(120 * dens), 2.4)]
    for li, (N, wmul) in enumerate(layers):
        pos = th / math.tau * N
        b = np.floor(pos).astype(np.int32) % N
        off = _hash(b, 0, int(p.get("seed", 0)) + li, 11)
        rel = (pos - np.floor(pos)) - (0.12 + 0.76 * off)
        dist = np.abs(rel) * (math.tau / N) * r
        r0 = (0.06 + 0.8 * _hash(b, 1, li, 12) ** 1.4) * rmax
        ln = (0.15 + length * _hash(b, 2, li, 13)) * (r0 + 0.12 * rmax)
        r1 = r0 + ln
        tt = np.clip((r - r0) / np.maximum(ln, 1), 0, 1)
        along = tt ** 1.7 * (1 - _smooth(0.92, 1.0, tt))
        w = width * wmul * (0.6 + 0.9 * (r / rmax)) * (0.5 + _hash(b, 3, li, 14))
        prof = np.exp(-(dist / w) ** 2 * 1.6)
        bright = (0.45 + 0.55 * _hash(b, 4, li, 15))
        val = prof * along * bright * _smooth(clear * 0.5, clear * 1.8, r)
        ci = (_hash(b, 5, li, 16) * len(cols)).astype(np.int32) % len(cols)
        acc += val[..., None] * cols[ci][..., :3]
    glow = float(p.get("glow", 0.35))
    if glow > 0:
        g = np.exp(-(r / (rmax * 0.09)) ** 2)
        acc += (glow * g)[..., None] * cols[0][None, None, :3] * 0.8
    return _acc_to_rgba(acc)


# kind -> (function, kind-specific defaults, drawn@SS?)
PATTERNS: dict = {
    "stars": (_p_stars, {"points": 5, "inner_ratio": 0.45}, True),
    "starfield": (_p_starfield, {}, False),
    "dots": (_p_dots, {}, True),
    "halftone": (_p_halftone, {"spacing": 18, "fade": "linear", "fade_angle": 90, "invert": False,
                               "max_radius": 1.0, "center": None}, False),
    "stripes": (_p_stripes, {"width": 40, "offset": 0}, False),
    "checker": (_p_checker, {}, False),
    "hex": (_p_hex, {"line": 2.5, "line_color": "#7fd1ff"}, False),
    "confetti": (_p_confetti, {}, True),
    "bokeh": (_p_bokeh, {}, False),
    "balloons": (_p_balloons, {"string_length": 2.6, "string_color": "#f2f2f2"}, False),
    "hearts": (_p_hearts, {}, True),
    "sparkles": (_p_sparkles, {}, False),
    "rays": (_p_rays, {"rays": 24, "center": None, "fade": 0.0}, False),
    "carbon": (_p_carbon, {"sheen": 0.3}, False),
    "grid": (_p_grid, {"spacing": 64, "line": 2, "major": 0}, False),
    "waves": (_p_waves, {"bands": 5, "amplitude": 36, "wavelength": 340, "start": 0.25}, False),
    "lightspeed": (_p_lightspeed, {"center": None, "width": 1.3, "length": 0.55, "clear_center": None,
                                   "glow": 0.35}, False),
    "clouds_cartoon": (_p_clouds_cartoon, {"outline": 7}, True),
    "polka": (_p_polka, {"spacing": 56, "radius": None}, False),
}
PATTERN_KINDS = list(PATTERNS)


def allowed_keys(layer_type: str, kind: str) -> set:
    """Keys (besides common layer keys) accepted by a pattern/noise kind."""
    if layer_type == "noise":
        return {"kind", "colors", "scale", "octaves", "contrast", "turbulence", "angle", "seed", "bg"}
    keys = set(COMMON_KEYS) | {"kind", "spacing", "radius", "width", "line", "offset"}
    if kind in PATTERNS:
        keys |= set(PATTERNS[kind][1])
    return keys


def render_pattern(kind, size, params=None, seed=0) -> Image.Image:
    if kind not in PATTERNS:
        raise ValueError(f"Unknown pattern kind {kind!r}. Choose from: {', '.join(PATTERN_KINDS)}")
    p = dict(params or {})
    W, H = int(size[0]), int(size[1])
    rng = np.random.default_rng(int(p.get("seed", seed)) + sum(map(ord, kind)) * 7919)
    fn, _, drawn = PATTERNS[kind]
    out = fn(W, H, rng, p)
    if isinstance(out, np.ndarray):
        out = _to_img(out)
    return _finish(out, W, H, p)
