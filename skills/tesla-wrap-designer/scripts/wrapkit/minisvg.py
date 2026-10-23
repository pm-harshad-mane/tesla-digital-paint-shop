"""Pure-Python SVG renderer (Pillow + numpy + stdlib XML) for flat illustrations.

Fallback for sandboxes without cairosvg/Chrome. Covers g/path/rect/circle/ellipse/line/polyline/
polygon/text/use, linear+radial gradients, transforms, strokes (caps/joins/dashes), clipPath with
simple shapes and feGaussianBlur. Anything else raises UnsupportedSVG (or is skipped with a
warning when lenient=True). DOCTYPE/ENTITY declarations are rejected and nothing external is
ever fetched.
"""
from __future__ import annotations

import math
import os
import re
import warnings
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .color import parse_color
from .fonts import ALIASES, resolve_font


class UnsupportedSVG(Exception):
    """SVG uses a feature minisvg cannot render faithfully."""


class UnsafeSVG(ValueError):
    """SVG contains a DTD/entity declaration or is too complex."""


SS = 4               # vertical samples per pixel (horizontal coverage is analytic)
TS = 3               # text tile supersampling
MAX_NODES = 100_000
_DTD = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.I)
_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_INH = {"fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit",
        "stroke-dasharray", "stroke-dashoffset", "fill-opacity", "stroke-opacity", "fill-rule",
        "clip-rule", "color", "visibility", "font-family", "font-size", "font-weight", "font-style",
        "text-anchor"}
_PROPS = _INH | {"opacity", "display", "filter", "clip-path", "mask", "transform", "stop-color",
                 "stop-opacity", "marker-start", "marker-mid", "marker-end"}
_SHAPES = {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon"}
_SKIP = {"defs", "clipPath", "linearGradient", "radialGradient", "mask", "filter", "style", "title",
         "desc", "metadata", "marker", "pattern", "symbol", "script", "namedview", "sodipodi:namedview"}
_UNSUP = {"image", "foreignObject", "textPath", "pattern", "mask"}


def reject_dtd(svg) -> None:
    """Raise UnsafeSVG if the document declares a DOCTYPE or ENTITY (XXE / billion-laughs)."""
    b = svg if isinstance(svg, bytes) else str(svg).encode("utf-8", "replace")
    if _DTD.search(b):
        raise UnsafeSVG("SVG with DOCTYPE/ENTITY declarations is rejected for security reasons")


# ---------------------------------------------------------------- matrices (a,b,c,d,e,f)
_I = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _mul(m, n):
    """m applied after n."""
    return (m[0] * n[0] + m[2] * n[1], m[1] * n[0] + m[3] * n[1],
            m[0] * n[2] + m[2] * n[3], m[1] * n[2] + m[3] * n[3],
            m[0] * n[4] + m[2] * n[5] + m[4], m[1] * n[4] + m[3] * n[5] + m[5])


def _inv(m):
    det = m[0] * m[3] - m[1] * m[2]
    if abs(det) < 1e-18:
        return None
    a, b, c, d = m[3] / det, -m[1] / det, -m[2] / det, m[0] / det
    return (a, b, c, d, -(a * m[4] + c * m[5]), -(b * m[4] + d * m[5]))


def _apply(m, p):
    return np.stack((m[0] * p[:, 0] + m[2] * p[:, 1] + m[4], m[1] * p[:, 0] + m[3] * p[:, 1] + m[5]), 1)


def _mscale(m):
    return max(math.hypot(m[0], m[1]), math.hypot(m[2], m[3]), 1e-9)


def _parse_transform(s):
    m = _I
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        v = [float(x) for x in _NUM.findall(args)]
        if name == "matrix" and len(v) == 6:
            t = tuple(v)
        elif name == "translate" and v:
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0.0)
        elif name == "scale" and v:
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "rotate" and v:
            a = math.radians(v[0])
            c, s_ = math.cos(a), math.sin(a)
            t = (c, s_, -s_, c, 0, 0)
            if len(v) == 3:
                t = _mul(_mul((1, 0, 0, 1, v[1], v[2]), t), (1, 0, 0, 1, -v[1], -v[2]))
        elif name == "skewX" and v:
            t = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == "skewY" and v:
            t = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            continue
        m = _mul(m, t)
    return m


def _vb_matrix(vb, w, h, par):
    """Matrix mapping viewBox (x,y,vw,vh) into a w*h box per preserveAspectRatio."""
    vx, vy, vw, vh = vb
    if vw <= 0 or vh <= 0:
        return _I
    parts = (par or "xMidYMid meet").split()
    align = parts[0] if parts else "xMidYMid"
    sx, sy = w / vw, h / vh
    if align == "none":
        return (sx, 0, 0, sy, -vx * sx, -vy * sy)
    s = max(sx, sy) if len(parts) > 1 and parts[1] == "slice" else min(sx, sy)
    fx = {"xMin": 0.0, "xMid": 0.5, "xMax": 1.0}.get(align[:4], 0.5)
    fy = {"YMin": 0.0, "YMid": 0.5, "YMax": 1.0}.get(align[4:], 0.5)
    return (s, 0, 0, s, (w - vw * s) * fx - vx * s, (h - vh * s) * fy - vy * s)


# ---------------------------------------------------------------- lengths / strings
def _len(v, ref=0.0, default=0.0, em=16.0):
    if v is None:
        return default
    m = re.match(r"\s*(" + _NUM.pattern + r")\s*([a-z%]*)", str(v))
    if not m:
        return default
    n, u = float(m.group(1)), m.group(2)
    f = {"": 1, "px": 1, "pt": 4 / 3, "pc": 16, "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96,
         "em": em, "ex": em / 2}.get(u)
    return n * ref / 100 if u == "%" else n * (f if f is not None else 1)


def _frac(v, default):
    """Opacity-like number or percent -> 0..1 float."""
    if v is None:
        return default
    try:
        s = str(v).strip()
        return max(0.0, min(1.0, float(s[:-1]) / 100 if s.endswith("%") else float(s)))
    except ValueError:
        return default


def _url_id(v):
    m = re.match(r"\s*url\(\s*['\"]?#([^)'\"\s]+)['\"]?\s*\)", v or "")
    return m.group(1) if m else None


def _tag(el):
    return el.tag.split("}")[-1] if isinstance(el.tag, str) else ""


def _href(el):
    h = el.get("{http://www.w3.org/1999/xlink}href") or el.get("href") or ""
    return h[1:] if h.startswith("#") else None


# ---------------------------------------------------------------- path geometry
def _arc_cubics(x1, y1, rx, ry, phi, fa, fs, x2, y2):
    """SVG elliptical arc -> list of cubic (c1, c2, end) tuples; None means draw a straight line."""
    if x1 == x2 and y1 == y2:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return None
    ph = math.radians(phi % 360)
    cp, sp = math.cos(ph), math.sin(ph)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = x1p * x1p / (rx * rx) + y1p * y1p / (ry * ry)
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, (rx * rx * ry * ry - den) / den)) if den else 0.0
    if fa == fs:
        co = -co
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx, cy = cp * cxp - sp * cyp + (x1 + x2) / 2, sp * cxp + cp * cyp + (y1 + y2) / 2

    def ang(ux, uy, vx, vy):
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)

    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
    th1 = ang(1, 0, ux, uy)
    dth = ang(ux, uy, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not fs and dth > 0:
        dth -= 2 * math.pi
    elif fs and dth < 0:
        dth += 2 * math.pi
    n = max(1, math.ceil(abs(dth) / (math.pi / 2) - 1e-9))
    dl = dth / n
    t = 4 / 3 * math.tan(dl / 4)

    def mp(x, y):
        return (cx + rx * x * cp - ry * y * sp, cy + rx * x * sp + ry * y * cp)

    out = []
    for i in range(n):
        a1 = th1 + i * dl
        a2 = a1 + dl
        c1, s1, c2, s2 = math.cos(a1), math.sin(a1), math.cos(a2), math.sin(a2)
        out.append((mp(c1 - t * s1, s1 + t * c1), mp(c2 + t * s2, s2 - t * c2), mp(c2, s2)))
    return out


def _cubic_pts(p0, p1, p2, p3, tol):
    p0, p1, p2, p3 = (np.asarray(p, float) for p in (p0, p1, p2, p3))
    dd = max(np.hypot(*(p0 - 2 * p1 + p2)), np.hypot(*(p1 - 2 * p2 + p3)))
    n = int(max(1, min(256, math.ceil(math.sqrt(0.75 * dd / tol)))))
    t = (np.arange(1, n + 1) / n)[:, None]
    u = 1 - t
    return (u ** 3 * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t ** 3 * p3).tolist()


def _quad_pts(p0, p1, p2, tol):
    p0, p1, p2 = (np.asarray(p, float) for p in (p0, p1, p2))
    dd = np.hypot(*(p0 - 2 * p1 + p2))
    n = int(max(1, min(256, math.ceil(math.sqrt(0.25 * dd / tol)))))
    t = (np.arange(1, n + 1) / n)[:, None]
    return ((1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t * t * p2).tolist()


_ARGC = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}


def _path_tokens(d):
    """Yield (cmd, args); stops quietly at the first malformed token (as browsers do)."""
    i, n, cmd = 0, len(d), None
    sep = " \t\r\n,"
    while True:
        while i < n and d[i] in sep:
            i += 1
        if i >= n:
            return
        ch = d[i]
        if ch.isalpha():
            if ch.upper() not in _ARGC:
                return
            cmd = ch
            i += 1
            if cmd in "Zz":
                yield cmd, []
                continue
        elif cmd is None or cmd in "Zz":
            return
        args = []
        for j in range(_ARGC[cmd.upper()]):
            while i < n and d[i] in sep:
                i += 1
            if cmd in "Aa" and j in (3, 4):
                if i >= n or d[i] not in "01":
                    return
                args.append(float(d[i]))
                i += 1
                continue
            m = _NUM.match(d, i)
            if not m:
                return
            args.append(float(m.group(0)))
            i = m.end()
        yield cmd, args
        if cmd == "M":
            cmd = "L"
        elif cmd == "m":
            cmd = "l"


def _parse_path(d, tol):
    """Path data -> [(Nx2 array, closed)] flattened to tolerance tol (user units)."""
    subs, P, closed = [], [], False
    cx = cy = sx = sy = 0.0
    lc = None            # last control point (for S/T)
    prev = ""
    fresh = False        # after Z: next drawing command starts a new subpath at (sx, sy)

    def flush(c):
        nonlocal P
        if len(P) >= 2:
            subs.append((np.array(P, float), c))
        P = []

    for cmd, a in _path_tokens(d):
        up, rel = cmd.upper(), cmd.islower()
        if up == "M":
            flush(False)
            cx, cy = (cx + a[0], cy + a[1]) if rel else (a[0], a[1])
            sx, sy = cx, cy
            P = [(cx, cy)]
            lc, fresh = None, False
        elif up == "Z":
            if P:
                flush(True)
            cx, cy = sx, sy
            lc, fresh = None, True
        else:
            if fresh or not P:
                P = [(cx, cy)]
                sx, sy = cx, cy
                fresh = False
            ox, oy = (cx, cy) if rel else (0.0, 0.0)
            if up == "L":
                cx, cy = ox + a[0], oy + a[1]
                P.append((cx, cy))
                lc = None
            elif up == "H":
                cx = (cx if rel else 0.0) + a[0]
                P.append((cx, cy))
                lc = None
            elif up == "V":
                cy = (cy if rel else 0.0) + a[0]
                P.append((cx, cy))
                lc = None
            elif up == "C":
                c1, c2, e = (ox + a[0], oy + a[1]), (ox + a[2], oy + a[3]), (ox + a[4], oy + a[5])
                P += _cubic_pts((cx, cy), c1, c2, e, tol)
                lc, (cx, cy) = c2, e
            elif up == "S":
                c1 = (2 * cx - lc[0], 2 * cy - lc[1]) if lc and prev in "CcSs" else (cx, cy)
                c2, e = (ox + a[0], oy + a[1]), (ox + a[2], oy + a[3])
                P += _cubic_pts((cx, cy), c1, c2, e, tol)
                lc, (cx, cy) = c2, e
            elif up == "Q":
                c1, e = (ox + a[0], oy + a[1]), (ox + a[2], oy + a[3])
                P += _quad_pts((cx, cy), c1, e, tol)
                lc, (cx, cy) = c1, e
            elif up == "T":
                c1 = (2 * cx - lc[0], 2 * cy - lc[1]) if lc and prev in "QqTt" else (cx, cy)
                e = (ox + a[0], oy + a[1])
                P += _quad_pts((cx, cy), c1, e, tol)
                lc, (cx, cy) = c1, e
            elif up == "A":
                e = (ox + a[5], oy + a[6])
                cub = _arc_cubics(cx, cy, a[0], a[1], a[2], int(a[3]), int(a[4]), e[0], e[1])
                if cub is None:
                    P.append(e)
                else:
                    p0 = (cx, cy)
                    for c1, c2, en in cub:
                        P += _cubic_pts(p0, c1, c2, en, tol)
                        p0 = en
                cx, cy = e
                lc = None
        prev = cmd
    flush(False)
    return subs


def _rect_path(x, y, w, h, rx, ry):
    if rx <= 0 or ry <= 0:
        return f"M{x},{y}H{x + w}V{y + h}H{x}Z"
    return (f"M{x + rx},{y}H{x + w - rx}A{rx},{ry} 0 0 1 {x + w},{y + ry}V{y + h - ry}"
            f"A{rx},{ry} 0 0 1 {x + w - rx},{y + h}H{x + rx}A{rx},{ry} 0 0 1 {x},{y + h - ry}"
            f"V{y + ry}A{rx},{ry} 0 0 1 {x + rx},{y}Z")


def _ellipse_path(cx, cy, rx, ry):
    return (f"M{cx + rx},{cy}A{rx},{ry} 0 1 1 {cx - rx},{cy}A{rx},{ry} 0 1 1 {cx + rx},{cy}Z")


# ---------------------------------------------------------------- stroking
def _circle(c, r, n):
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.stack((c[0] + r * np.cos(t), c[1] + r * np.sin(t)), 1)


def _dash_pieces(pts, closed, dash, offset):
    if closed:
        pts = np.vstack((pts, pts[:1]))
    seg = np.hypot(*(pts[1:] - pts[:-1]).T)
    cum = np.concatenate(([0.0], np.cumsum(seg)))
    total = cum[-1]
    pat = dash * 2 if len(dash) % 2 else dash
    per = sum(pat)
    if per <= 0 or total / per * len(pat) > 50000:
        return [(pts, False)]
    out, pos, i = [], -(offset % per), 0
    while pos < total:
        ln = pat[i % len(pat)]
        if i % 2 == 0 and pos + ln > 0:
            s, e = max(pos, 0.0), min(pos + ln, total)
            if e > s:
                inner = (cum > s) & (cum < e)
                xs = np.concatenate(([s], cum[inner], [e]))
                out.append((np.stack((np.interp(xs, cum, pts[:, 0]), np.interp(xs, cum, pts[:, 1])), 1), False))
        pos += ln
        i += 1
    return out


def _stroke_polys(subs, hw, cap, join, miter, dash, offset, nseg):
    """Stroke outline as many positively-wound pieces (union via nonzero fill), in user space."""
    quads, others = [], []
    for pts, closed in subs:
        pieces = _dash_pieces(pts, closed, dash, offset) if dash else [(pts, closed)]
        for p, cl in pieces:
            keep = np.concatenate(([True], np.hypot(*(p[1:] - p[:-1]).T) > 1e-9))
            p = p[keep]
            if cl and len(p) > 1 and np.allclose(p[0], p[-1]):
                p = p[:-1]
            if len(p) == 1:
                if cap == "round":
                    others.append(_circle(p[0], hw, nseg))
                elif cap == "square":
                    others.append(p[0] + hw * np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]]))
                continue
            q = np.vstack((p, p[:1])) if cl else p
            d = q[1:] - q[:-1]
            ln = np.hypot(d[:, 0], d[:, 1])
            u = d / ln[:, None]
            nrm = np.stack((-u[:, 1], u[:, 0]), 1) * hw
            a, b = q[:-1], q[1:]
            quads.append(np.stack((a + nrm, b + nrm, b - nrm, a - nrm), 1))
            # joins
            if cl:
                u0, u1, n0, n1, v = np.roll(u, 1, 0), u, np.roll(nrm, 1, 0), nrm, a
            else:
                u0, u1, n0, n1, v = u[:-1], u[1:], nrm[:-1], nrm[1:], b[:-1]
            if len(v):
                cr = u0[:, 0] * u1[:, 1] - u0[:, 1] * u1[:, 0]
                dt = (u0 * u1).sum(1)
                th = np.arctan2(cr, dt)
                s = np.where(cr > 0, -1.0, 1.0)[:, None]
                oa, ob = v + s * n0, v + s * n1
                act = np.abs(th) > 1e-3
                if act.any():
                    quads.append(np.stack((v, oa, ob, ob), 1)[act])        # bevel wedge
                    for k in np.nonzero(act & (np.abs(th) > 0.1))[0]:
                        if join == "round":
                            others.append(_circle(v[k], hw, nseg))
                        elif join == "miter":
                            if 1 / max(math.cos(th[k] / 2), 1e-9) <= miter:
                                tip = v[k] + s[k] * (n0[k] + n1[k]) / (1 + dt[k])
                                others.append(np.array([v[k], oa[k], tip, ob[k]]))
            if not cl:
                for pt, uu, nn in ((p[0], -u[0], -nrm[0]), (p[-1], u[-1], nrm[-1])):
                    if cap == "round":
                        others.append(_circle(pt, hw, nseg))
                    elif cap == "square":
                        others.append(np.array([pt + nn, pt + nn + uu * hw, pt - nn + uu * hw, pt - nn]))
    return quads, others


def _orient(polys):
    """Make every polygon positively wound so a nonzero fill is their union."""
    out = []
    for P in polys:
        if P.ndim == 3:
            x, y = P[..., 0], P[..., 1]
            ar = (x * np.roll(y, -1, 1) - np.roll(x, -1, 1) * y).sum(1)
            P = P.copy()
            P[ar < 0] = P[ar < 0][:, ::-1]
        else:
            ar = (P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1]).sum()
            if ar < 0:
                P = P[::-1]
        out.append(P)
    return out


# ---------------------------------------------------------------- rasterising
def _raster(polys, evenodd, W, H, ss=SS):
    """Coverage mask (float32 0..1) for polygons in device px; returns (cov, x0, y0) or None."""
    A, B = [], []
    for P in polys:
        if P.ndim == 3:
            if P.size:
                A.append(P.reshape(-1, 2))
                B.append(np.roll(P, -1, 1).reshape(-1, 2))
        elif len(P) >= 2:
            A.append(P)
            B.append(np.roll(P, -1, 0))
    if not A:
        return None
    A, B = np.concatenate(A), np.concatenate(B)
    ok = np.isfinite(A).all(1) & np.isfinite(B).all(1)
    A, B = A[ok], B[ok]
    if not len(A):
        return None
    lo, hi = np.minimum(A.min(0), B.min(0)), np.maximum(A.max(0), B.max(0))
    x0, y0 = max(0, int(math.floor(lo[0]))), max(0, int(math.floor(lo[1])))
    x1, y1 = min(W, int(math.ceil(hi[0]))), min(H, int(math.ceil(hi[1])))
    if x1 <= x0 or y1 <= y0:
        return None
    w, h = x1 - x0, y1 - y0
    ax, ay, bx, by = A[:, 0] - x0, A[:, 1] - y0, B[:, 0] - x0, B[:, 1] - y0
    keep = by != ay
    ax, ay, bx, by = ax[keep], ay[keep], bx[keep], by[keep]
    up = by > ay
    ey0, ey1 = np.where(up, ay, by), np.where(up, by, ay)
    ex = np.where(up, ax, bx)
    slope = (bx - ax) / (by - ay)
    sgn = np.where(up, 1, -1)
    out = np.zeros((h, w), np.float32)
    strip = max(1, min(h, 1_500_000 // (w * ss + 1)))
    stride = w + 2
    for ys in range(0, h, strip):
        ye = min(h, ys + strip)
        k0 = np.maximum(np.ceil(ey0 * ss - 0.5), ys * ss).astype(np.int64)
        k1 = np.minimum(np.ceil(ey1 * ss - 0.5), ye * ss).astype(np.int64)
        cnt = np.maximum(k1 - k0, 0)
        tot = int(cnt.sum())
        if tot == 0:
            continue
        eid = np.repeat(np.arange(len(cnt)), cnt)
        rows = k0[eid] + (np.arange(tot) - np.repeat(np.cumsum(cnt) - cnt, cnt))
        x = ex[eid] + ((rows + 0.5) / ss - ey0[eid]) * slope[eid]
        x = np.clip(x, 0, w)
        rl = rows - ys * ss
        order = np.argsort(rl * (w + 2.0) + x, kind="stable")
        rl, x, sg = rl[order], x[order], sgn[eid][order]
        wind = np.cumsum(sg)
        inside = (wind & 1) == 1 if evenodd else wind != 0
        sel = np.nonzero(inside[:-1] & (rl[:-1] == rl[1:]))[0]
        if not len(sel):
            continue
        xa, xb, r = x[sel], x[sel + 1], rl[sel]
        ia, ib = r * stride + np.floor(xa).astype(np.int64) + 1, r * stride + np.floor(xb).astype(np.int64) + 1
        n = (ye - ys) * ss * stride
        Ac = np.bincount(ia, minlength=n) - np.bincount(ib, minlength=n)
        Bc = np.bincount(ia, -xa, n) + np.bincount(ib, xb, n)
        Ac = np.cumsum(Ac.reshape(-1, stride), 1)
        Bc = np.cumsum(Bc.reshape(-1, stride), 1)
        C = Ac * np.arange(stride) + Bc
        cov = (C[:, 1:w + 1] - C[:, :w]).reshape(ye - ys, ss, w).sum(1) / ss
        out[ys:ye] = np.clip(cov, 0, 1)
    return out, x0, y0


# ---------------------------------------------------------------- the renderer
class _Gradient:
    def __init__(self, kind, units, matrix, coords, spread, offs, cols):
        self.kind, self.units, self.matrix, self.c = kind, units, matrix, coords
        self.spread, self.offs, self.cols = spread, offs, cols


class _Renderer:
    def __init__(self, root, W, H, lenient):
        self.root, self.W, self.H, self.lenient = root, W, H, lenient
        self.ids = {e.get("id"): e for e in root.iter() if e.get("id")}
        self.css = self._parse_css()
        self.n = 0
        self.depth = 0
        self.grads: dict = {}
        self.vw, self.vh = float(W), float(H)

    # ---- helpers
    def unsupported(self, msg):
        if self.lenient:
            warnings.warn(f"minisvg: skipping unsupported feature: {msg}", stacklevel=2)
            return
        raise UnsupportedSVG(msg)

    def _parse_css(self):
        rules = []
        for st in self.root.iter():
            if _tag(st) != "style":
                continue
            txt = re.sub(r"/\*.*?\*/", "", st.text or "", flags=re.S)
            for sel, body in re.findall(r"([^{}@]+)\{([^}]*)\}", txt):
                decl = self._decls(body)
                for s in sel.split(","):
                    s = s.strip()
                    m = re.fullmatch(r"(\*|[\w-]+)?(?:\.([\w-]+))?(?:#([\w-]+))?", s)
                    if m and s:
                        rules.append((m.groups(), decl))
                    elif s:
                        warnings.warn(f"minisvg: unsupported CSS selector {s!r} ignored", stacklevel=2)
        return rules

    @staticmethod
    def _decls(s):
        d = {}
        for part in s.split(";"):
            if ":" in part:
                k, v = part.split(":", 1)
                d[k.strip()] = re.sub(r"\s*!important\s*$", "", v.strip())
        return d

    def declared(self, el):
        d = {k.split("}")[-1]: v for k, v in el.attrib.items() if k not in ("style", "class")}
        cls = (el.get("class") or "").split()
        for (tg, c, i), decl in self.css:
            if (tg in (None, "*", _tag(el))) and (c is None or c in cls) and (i is None or i == el.get("id")):
                d.update(decl)
        d.update(self._decls(el.get("style", "")))
        return d

    def length(self, el, name, ref, default=0.0):
        return _len(el.get(name), ref, default)

    # ---- paint
    def color(self, val, st):
        v = (val or "").strip()
        if v.lower() == "currentcolor":
            v = st.get("color", "black")
        if v.lower() in ("none", "transparent", ""):
            return None
        try:
            r, g, b, a = parse_color(v)
        except ValueError:
            return None
        return r / 255, g / 255, b / 255, a / 255

    def paint(self, val, op, st, bbox):
        """-> ('solid', premult rgba) | ('grad', _Gradient, bbox) | None."""
        v = (val or "").strip()
        if v.startswith("url("):
            gid = _url_id(v)
            el = self.ids.get(gid)
            if el is not None and _tag(el) == "pattern":
                self.unsupported("pattern fill")
                return None
            g = self.gradient(gid) if el is not None else None
            if g is not None:
                return ("grad", g, bbox, op) if g.kind != "solid" else self.paint_solid(g.cols[0], op)
            fb = v[v.find(")") + 1:].strip()
            return self.paint(fb, op, st, bbox) if fb else None
        c = self.color(v, st)
        return self.paint_solid(c, op) if c else None

    @staticmethod
    def paint_solid(c, op):
        a = c[3] * op
        return ("solid", np.array([c[0] * a, c[1] * a, c[2] * a, a], np.float32))

    def gradient(self, gid):
        if gid in self.grads:
            return self.grads[gid]
        el = self.ids.get(gid)
        chain, e = [], el
        while e is not None and _tag(e) in ("linearGradient", "radialGradient") and e not in chain and len(chain) < 10:
            chain.append(e)
            e = self.ids.get(_href(e))
        if not chain:
            return None

        def attr(n, dv=None):
            return next((c.get(n) for c in chain if c.get(n) is not None), dv)

        stops_el = next((c for c in chain if any(_tag(s) == "stop" for s in c)), None)
        offs, cols, last = [], [], 0.0
        for s in (stops_el if stops_el is not None else []):
            if _tag(s) != "stop":
                continue
            d = self.declared(s)
            o = d.get("offset", "0").strip()
            o = float(o[:-1]) / 100 if o.endswith("%") else float(_NUM.match(o).group(0)) if _NUM.match(o) else 0.0
            last = max(last, min(1.0, max(0.0, o)))
            c = self.color(d.get("stop-color", "black"), d) or (0, 0, 0, 0)
            offs.append(last)
            cols.append((c[0], c[1], c[2], c[3] * _frac(d.get("stop-opacity"), 1.0)))
        if not cols:
            self.grads[gid] = None
            return None
        units = attr("gradientUnits", "objectBoundingBox")
        obb = units == "objectBoundingBox"

        def co(n, dv, ref):
            v = attr(n)
            if v is None:
                v = dv
            if obb:
                s = str(v).strip()
                return float(s[:-1]) / 100 if s.endswith("%") else _len(s)
            return _len(v, ref)

        vw, vh = self.vw, self.vh
        if _tag(chain[0]) == "linearGradient":
            c = dict(x1=co("x1", "0%", vw), y1=co("y1", "0%", vh), x2=co("x2", "100%", vw), y2=co("y2", "0%", vh))
            kind = "linear"
        else:
            r = co("r", "50%", math.sqrt((vw * vw + vh * vh) / 2))
            cx, cy = co("cx", "50%", vw), co("cy", "50%", vh)
            c = dict(cx=cx, cy=cy, r=r, fx=co("fx", cx, vw) if attr("fx") is not None else cx,
                     fy=co("fy", cy, vh) if attr("fy") is not None else cy)
            kind = "radial"
        offs = np.maximum.accumulate(np.array(offs)) + np.arange(len(offs)) * 1e-9
        g = _Gradient("solid" if len(cols) == 1 else kind, units, _parse_transform(attr("gradientTransform")),
                      c, attr("spreadMethod", "pad"), offs, np.array(cols, np.float32))
        self.grads[gid] = g
        return g

    def grad_pixels(self, g, bbox, ctm, x0, y0, w, h):
        """Premultiplied (h,w,4) gradient colours at pixel centres."""
        m = _mul(ctm, g.matrix)
        if g.units == "objectBoundingBox":
            bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
            if bw <= 0 or bh <= 0:
                return None
            m = _mul(m, (bw, 0, 0, bh, bbox[0], bbox[1]))
        iv = _inv(m)
        if iv is None:
            return None
        X, Y = np.meshgrid(np.arange(x0, x0 + w) + 0.5, np.arange(y0, y0 + h) + 0.5)
        gx, gy = iv[0] * X + iv[2] * Y + iv[4], iv[1] * X + iv[3] * Y + iv[5]
        c = g.c
        if g.kind == "linear":
            dx, dy = c["x2"] - c["x1"], c["y2"] - c["y1"]
            den = dx * dx + dy * dy
            t = ((gx - c["x1"]) * dx + (gy - c["y1"]) * dy) / den if den > 0 else np.zeros_like(gx)
        else:
            r = c["r"]
            fx, fy = c["fx"], c["fy"]
            fd = math.hypot(fx - c["cx"], fy - c["cy"])
            if fd > 0.999 * r > 0:
                k = 0.999 * r / fd
                fx, fy = c["cx"] + (fx - c["cx"]) * k, c["cy"] + (fy - c["cy"]) * k
            dx, dy = gx - fx, gy - fy
            ex, ey = fx - c["cx"], fy - c["cy"]
            a = dx * dx + dy * dy
            b = dx * ex + dy * ey
            c0 = ex * ex + ey * ey - r * r
            s = (-b + np.sqrt(np.maximum(b * b - a * c0, 0))) / np.maximum(a, 1e-12)
            t = np.where(a > 1e-12, 1 / np.maximum(s, 1e-12), 0.0)
        if g.spread == "reflect":
            u = np.mod(t, 2.0)
            t = np.where(u > 1, 2 - u, u)
        elif g.spread == "repeat":
            t = np.mod(t, 1.0)
        t = np.clip(t, 0, 1)
        col = np.stack([np.interp(t, g.offs, g.cols[:, i]) for i in range(4)], -1).astype(np.float32)
        col[..., :3] *= col[..., 3:4]
        return col

    def blend(self, cv, cov, x0, y0, p, ctm):
        """Composite coverage with a paint onto the premultiplied canvas."""
        h, w = cov.shape
        reg = cv[y0:y0 + h, x0:x0 + w]
        if p[0] == "solid":
            src = cov[..., None] * p[1]
        else:
            _, g, bbox, op = p
            col = self.grad_pixels(g, bbox, ctm, x0, y0, w, h)
            if col is None:
                return
            src = cov[..., None] * col * op
        reg *= 1 - src[..., 3:4]
        reg += src

    # ---- tree
    def run(self, base):
        cv = np.zeros((self.H, self.W, 4), np.float32)
        self.node(self.root, {}, base, cv, root=True)
        return cv

    def node(self, el, pst, ctm, cv, root=False):
        tag = _tag(el)
        if not tag or tag in _SKIP:
            return
        self.n += 1
        if self.n > MAX_NODES:
            raise UnsafeSVG("SVG too complex")
        if tag in _UNSUP:
            return self.unsupported(f"<{tag}> element")
        own = self.declared(el)
        if own.get("display") == "none":
            return
        st = {k: v for k, v in pst.items() if k in _INH}
        st.update({k: v for k, v in own.items() if k in _PROPS})
        if own.get("transform"):
            ctm = _mul(ctm, _parse_transform(own["transform"]))
        mask = st.get("mask")
        if mask and mask != "none":
            self.unsupported("mask")
        op = _frac(st.get("opacity"), 1.0)
        flt, clip = st.get("filter", "none"), st.get("clip-path", "none")
        both = st.get("fill", "black") != "none" and st.get("stroke", "none") != "none"
        layer = flt != "none" or clip != "none" or (op < 1 and (tag not in _SHAPES and tag != "text" or both))
        tgt = np.zeros_like(cv) if layer else cv
        dop = 1.0 if layer else op
        if tag in _SHAPES:
            self.shape(tag, el, st, ctm, tgt, dop)
        elif tag == "text":
            self.text(el, st, ctm, tgt, dop)
        elif tag == "use":
            self.use(el, st, ctm, tgt)
        elif tag == "switch":
            for ch in el:
                if _tag(ch):
                    self.node(ch, st, ctm, tgt)
                    break
        elif tag in ("g", "a", "svg"):
            if tag == "svg" and not root:
                ctm = self.nested_svg(el, ctm)
            for ch in el:
                self.node(ch, st, ctm, tgt)
        if layer:
            if flt != "none":
                self.filter(flt, tgt, ctm)
            if clip != "none":
                m = self.clip_mask(clip, ctm)
                if m is not None:
                    tgt *= m[..., None]
            if op < 1:
                tgt *= op
            cv *= 1 - tgt[..., 3:4]
            cv += tgt

    def nested_svg(self, el, ctm):
        x, y = self.length(el, "x", self.vw), self.length(el, "y", self.vh)
        w, h = self.length(el, "width", self.vw, self.vw), self.length(el, "height", self.vh, self.vh)
        ctm = _mul(ctm, (1, 0, 0, 1, x, y))
        vb = [float(v) for v in _NUM.findall(el.get("viewBox", ""))]
        if len(vb) == 4:
            ctm = _mul(ctm, _vb_matrix(vb, w, h, el.get("preserveAspectRatio")))
        return ctm

    def use(self, el, st, ctm, cv):
        ref = self.ids.get(_href(el))
        if ref is None:
            return
        self.depth += 1
        if self.depth > 24:
            raise UnsafeSVG("use nesting too deep")
        try:
            ctm = _mul(ctm, (1, 0, 0, 1, self.length(el, "x", self.vw), self.length(el, "y", self.vh)))
            if _tag(ref) in ("symbol", "svg"):
                vb = [float(v) for v in _NUM.findall(ref.get("viewBox", ""))]
                if len(vb) == 4:
                    w = self.length(el, "width", self.vw, self.vw)
                    h = self.length(el, "height", self.vh, self.vh)
                    ctm = _mul(ctm, _vb_matrix(vb, w, h, ref.get("preserveAspectRatio")))
                own = self.declared(ref)
                st2 = {k: v for k, v in st.items() if k in _INH}
                st2.update({k: v for k, v in own.items() if k in _INH})
                for ch in ref:
                    self.node(ch, st2, ctm, cv)
            else:
                self.node(ref, st, ctm, cv)
        finally:
            self.depth -= 1

    # ---- shapes
    def geometry(self, tag, el, tol):
        vw, vh = self.vw, self.vh
        g = lambda n, ref, d=0.0: _len(el.get(n), ref, d)  # noqa: E731
        if tag == "path":
            return _parse_path(el.get("d", ""), tol)
        if tag == "rect":
            x, y, w, h = g("x", vw), g("y", vh), g("width", vw), g("height", vh)
            if w <= 0 or h <= 0:
                return []
            rx, ry = el.get("rx"), el.get("ry")
            rx = _len(rx, vw) if rx is not None else (_len(ry, vh) if ry is not None else 0.0)
            ry = _len(el.get("ry"), vh) if el.get("ry") is not None else rx
            return _parse_path(_rect_path(x, y, w, h, min(rx, w / 2), min(ry, h / 2)), tol)
        if tag in ("circle", "ellipse"):
            if tag == "circle":
                rx = ry = g("r", math.sqrt((vw * vw + vh * vh) / 2))
            else:
                rx, ry = g("rx", vw), g("ry", vh)
            if rx <= 0 or ry <= 0:
                return []
            return _parse_path(_ellipse_path(g("cx", vw), g("cy", vh), rx, ry), tol)
        if tag == "line":
            return [(np.array([[g("x1", vw), g("y1", vh)], [g("x2", vw), g("y2", vh)]]), False)]
        nums = [float(v) for v in _NUM.findall(el.get("points", ""))]
        pts = np.array(nums[:len(nums) // 2 * 2], float).reshape(-1, 2)
        return [(pts, tag == "polygon")] if len(pts) >= 2 else []

    def shape(self, tag, el, st, ctm, cv, op):
        if st.get("visibility") in ("hidden", "collapse"):
            return
        sc = _mscale(ctm)
        subs = self.geometry(tag, el, 0.05 / sc)
        if not subs:
            return
        allp = np.concatenate([p for p, _ in subs])
        bbox = (*allp.min(0), *allp.max(0))
        fp = self.paint(st.get("fill", "black"), _frac(st.get("fill-opacity"), 1.0) * op, st, bbox)
        if fp:
            polys = [_apply(ctm, p) for p, _ in subs if len(p) >= 3]
            r = _raster(polys, st.get("fill-rule") == "evenodd", self.W, self.H)
            if r:
                self.blend(cv, r[0], r[1], r[2], fp, ctm)
        sw = _len(st.get("stroke-width"), self.vw, 1.0)
        sp = self.paint(st.get("stroke", "none"), _frac(st.get("stroke-opacity"), 1.0) * op, st, bbox)
        if sp and sw > 0:
            self.stroke(subs, sw, st, ctm, cv, sp)

    def stroke(self, subs, sw, st, ctm, cv, sp):
        dash = None
        da = st.get("stroke-dasharray", "none")
        if da != "none":
            dash = [abs(_len(v, self.vw)) for v in re.split(r"[\s,]+", da.strip()) if v]
            if not dash or sum(dash) <= 0:
                dash = None
        sc = _mscale(ctm)
        nseg = int(max(12, min(72, 4 * math.sqrt(sw * sc / 2 + 1) * 2)))
        quads, others = _stroke_polys(
            subs, sw / 2, st.get("stroke-linecap", "butt"), st.get("stroke-linejoin", "miter"),
            float(st.get("stroke-miterlimit", 4) or 4), dash, _len(st.get("stroke-dashoffset"), self.vw), nseg)
        polys = [_apply(ctm, q.reshape(-1, 2)).reshape(q.shape) for q in quads if len(q)]
        polys += [_apply(ctm, o) for o in others]
        r = _raster(_orient(polys), False, self.W, self.H)
        if r:
            self.blend(cv, r[0], r[1], r[2], sp, ctm)

    # ---- clip / filter
    def clip_mask(self, ref, ctm):
        el = self.ids.get(_url_id(ref))
        if el is None or _tag(el) != "clipPath":
            return None
        if el.get("clipPathUnits") == "objectBoundingBox" or el.get("clip-path"):
            self.unsupported("clipPath with objectBoundingBox units or nested clip-path")
            return None
        m = _mul(ctm, _parse_transform(el.get("transform")))
        mask = np.zeros((self.H, self.W), np.float32)
        for ch in el:
            tag, e = _tag(ch), ch
            own = self.declared(ch)
            cm = _mul(m, _parse_transform(own.get("transform")))
            if tag == "use":
                e = self.ids.get(_href(ch))
                if e is None:
                    continue
                cm = _mul(cm, (1, 0, 0, 1, self.length(ch, "x", self.vw), self.length(ch, "y", self.vh)))
                cm = _mul(cm, _parse_transform(self.declared(e).get("transform")))
                tag = _tag(e)
                own = {**self.declared(e), **{k: v for k, v in own.items() if k in ("display", "clip-rule")}}
            if tag not in _SHAPES:
                if tag:
                    self.unsupported(f"<{tag}> inside clipPath")
                continue
            if own.get("display") == "none" or own.get("visibility") == "hidden":
                continue
            subs = self.geometry(tag, e, 0.05 / _mscale(cm))
            r = _raster([_apply(cm, p) for p, _ in subs if len(p) >= 3], own.get("clip-rule") == "evenodd",
                        self.W, self.H)
            if r:
                c, x0, y0 = r
                reg = mask[y0:y0 + c.shape[0], x0:x0 + c.shape[1]]
                np.maximum(reg, c, out=reg)
        return mask

    def filter(self, flt, layer, ctm):
        sig = None
        fid = _url_id(flt)
        mb = re.match(r"\s*blur\(\s*([^)]+)\)", flt)
        if mb:
            sig = (_len(mb.group(1)),) * 2
        elif fid and self.ids.get(fid) is not None:
            for p in self.ids[fid]:
                t = _tag(p)
                if t == "feGaussianBlur" and sig is None:
                    v = [float(x) for x in _NUM.findall(p.get("stdDeviation", "0"))] or [0.0]
                    sig = (v[0], v[-1])
                elif t.startswith("fe") and t != "feGaussianBlur":
                    warnings.warn(f"minisvg: filter primitive <{t}> ignored", stacklevel=2)
        else:
            warnings.warn(f"minisvg: unsupported filter {flt!r} ignored", stacklevel=2)
        if not sig or max(sig) <= 0:
            return
        sx, sy = sig[0] * math.hypot(ctm[0], ctm[1]), sig[1] * math.hypot(ctm[2], ctm[3])
        im = Image.fromarray((np.clip(layer, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA")
        im = im.filter(ImageFilter.GaussianBlur((max(sx, 0.01), max(sy, 0.01))))
        layer[...] = np.asarray(im, np.float32) / 255

    # ---- text
    @staticmethod
    def font_for(st, fs):
        fam = [f.strip().strip("'\"").lower() for f in st.get("font-family", "sans-serif").split(",")]
        w = str(st.get("font-weight", "normal")).lower()
        bold = w in ("bold", "bolder") or (w.isdigit() and int(w) >= 600)
        key = "sans"
        for f in fam:
            if "mono" in f or "courier" in f or "menlo" in f or "consolas" in f:
                key = "mono"
            elif f in ("impact", "display", "fantasy", "anton", "bebas neue") or "black" in f:
                key = "display"
            elif "rounded" in f or "comic" in f or "chalk" in f or "cursive" in f:
                key = "rounded"
            elif "serif" in f and "sans" not in f or f in ("georgia", "times", "times new roman"):
                key = "serif"
            elif f in ("sans-serif", "arial", "helvetica", "verdana", "system-ui", "inter"):
                key = "sans"
            else:
                continue
            break
        if bold and key + "-bold" in ALIASES:
            key += "-bold"
        return resolve_font(key, fs)

    def text(self, el, st, ctm, cv, op):
        if st.get("visibility") in ("hidden", "collapse"):
            return
        runs = []   # [text, style, abs_x or None, abs_y or None, dx, dy]

        def walk(e, pst, first):
            own = self.declared(e)
            s = {k: v for k, v in pst.items() if k in _INH}
            s.update({k: v for k, v in own.items() if k in _PROPS})
            if own.get("display") == "none":
                return
            ax, ay = (_NUM.findall(e.get("x", "")) or [None])[0], (_NUM.findall(e.get("y", "")) or [None])[0]
            dx, dy = (_NUM.findall(e.get("dx", "")) or [0])[0], (_NUM.findall(e.get("dy", "")) or [0])[0]
            pend = [ax, ay, float(dx), float(dy)]
            for txt, child in [(e.text, None)] + [(None, c) for c in e]:
                if child is None:
                    if txt and txt.strip() or (txt and runs):
                        runs.append([re.sub(r"\s+", " ", txt), s, *pend])
                        pend[:] = [None, None, 0.0, 0.0]
                else:
                    if _tag(child) == "tspan":
                        walk(child, s, False)
                    elif _tag(child) in ("textPath",):
                        self.unsupported("textPath")
                    if child.tail and (child.tail.strip() or runs):
                        runs.append([re.sub(r"\s+", " ", child.tail), s, None, None, 0.0, 0.0])

        walk(el, st, True)
        if not runs:
            return
        runs[0][0] = runs[0][0].lstrip()
        runs[-1][0] = runs[-1][0].rstrip()
        # lay out chunks: pen positions + anchor shift
        px = py = 0.0
        chunks, cur = [], None
        for r in runs:
            t, s, ax, ay, dx, dy = r
            if ax is not None or cur is None:
                cur = {"x": float(ax) if ax is not None else px, "items": [], "anchor": s.get("text-anchor", "start")}
                chunks.append(cur)
                if ax is not None:
                    px = cur["x"]
            if ay is not None:
                py = float(ay)
            px, py = px + dx, py + dy
            fs = _len(s.get("font-size"), 16, 16.0)
            sc = _mscale(ctm)
            size = max(1, int(round(fs * sc * TS)))
            if size > 6000:
                return self.unsupported("text too large")
            font = self.font_for(s, size)
            k = size / fs
            wd = font.getlength(t) / k if t else 0.0
            cur["items"].append((t, s, px, py, font, k, fs, wd))
            px += wd
        for ch in chunks:
            tot = sum(i[7] for i in ch["items"])
            sh = {"middle": tot / 2, "end": tot}.get(ch["anchor"], 0.0)
            for t, s, x, y, font, k, fs, wd in ch["items"]:
                if t.strip():
                    self.draw_text(t, s, x - sh, y, font, k, fs, wd, ctm, cv, op)

    def draw_text(self, t, s, x, y, font, k, fs, wd, ctm, cv, op):
        sw = _len(s.get("stroke-width"), self.vw, 1.0) if s.get("stroke", "none") != "none" else 0.0
        spx = int(round(sw / 2 * k)) if sw else 0
        l, tp, r, b = font.getbbox(t, anchor="ls", stroke_width=spx)
        pad = 2
        tw, th = int(r - l) + 2 * pad, int(b - tp) + 2 * pad
        ox, oy = -l + pad, -tp + pad
        if tw * th > 40_000_000:
            return
        tiles = []
        for stroke_w in ([spx] if spx else []) + [0]:
            im = Image.new("L", (tw, th), 0)
            ImageDraw.Draw(im).text((ox, oy), t, font=font, fill=255, anchor="ls", stroke_width=stroke_w)
            tiles.append(im)
        italic = s.get("font-style") in ("italic", "oblique")
        m = _mul(ctm, (1, 0, 0, 1, x, y))
        if italic:
            m = _mul(m, (1, 0, math.tan(math.radians(12)) * -1, 1, 0, 0))
        # tile px -> user (relative to baseline origin) -> device
        t2d = _mul(m, (1 / k, 0, 0, 1 / k, -ox / k, -oy / k))
        corners = _apply(t2d, np.array([[0, 0], [tw, 0], [tw, th], [0, th]], float))
        x0, y0 = max(0, int(math.floor(corners[:, 0].min()))), max(0, int(math.floor(corners[:, 1].min())))
        x1, y1 = min(self.W, int(math.ceil(corners[:, 0].max()))), min(self.H, int(math.ceil(corners[:, 1].max())))
        if x1 <= x0 or y1 <= y0:
            return
        iv = _inv(t2d)
        if iv is None:
            return
        # output (TS-scaled region) -> device -> tile
        o2t = _mul(iv, (1 / TS, 0, 0, 1 / TS, x0, y0))
        w, h = x1 - x0, y1 - y0
        bbox = (x, y - fs * 0.8, x + wd, y + fs * 0.25)
        for i, im in enumerate(tiles):
            is_stroke = bool(spx) and i == 0
            out = im.transform((w * TS, h * TS), Image.AFFINE, (o2t[0], o2t[2], o2t[4], o2t[1], o2t[3], o2t[5]),
                               Image.BILINEAR)
            cov = np.asarray(out, np.float32).reshape(h, TS, w, TS).mean((1, 3)) / 255
            if is_stroke:
                inner = np.asarray(tiles[1].transform((w * TS, h * TS), Image.AFFINE,
                                                      (o2t[0], o2t[2], o2t[4], o2t[1], o2t[3], o2t[5]),
                                                      Image.BILINEAR), np.float32)
                cov = np.clip(cov - inner.reshape(h, TS, w, TS).mean((1, 3)) / 255, 0, 1)
                p = self.paint(s.get("stroke"), _frac(s.get("stroke-opacity"), 1.0) * op, s, bbox)
            else:
                p = self.paint(s.get("fill", "black"), _frac(s.get("fill-opacity"), 1.0) * op, s, bbox)
            if p:
                self.blend(cv, cov, x0, y0, p, ctm)
        # stroke ring is drawn first above; fill is drawn over it (inner half kept as fill colour)


def render(svg_text_or_path, size, lenient=False) -> Image.Image:
    """Rasterise an SVG with the pure-Python renderer to an RGBA image of size=(w, h)."""
    w, h = int(size[0]), int(size[1])
    if not (0 < w <= 16384 and 0 < h <= 16384):
        raise ValueError(f"Bad render size {size!r}")
    s = str(svg_text_or_path)
    if "<svg" not in s[:4000].lower() and len(s) < 1024 and os.path.isfile(s):
        s = open(s, encoding="utf-8").read()
    reject_dtd(s)
    s = re.sub(r"^\s*<\?xml[^>]*\?>", "", s)
    try:
        root = ET.fromstring(s.encode("utf-8"))
    except ET.ParseError as e:
        raise ValueError(f"Invalid SVG XML: {e}") from e
    if _tag(root) != "svg":
        raise ValueError("Not an SVG document (no <svg> element)")
    vb = [float(v) for v in _NUM.findall(root.get("viewBox", ""))]
    if len(vb) != 4:
        rw, rh = root.get("width", ""), root.get("height", "")
        okw, okh = _NUM.match(rw) and "%" not in rw, _NUM.match(rh) and "%" not in rh
        vb = [0, 0, _len(rw), _len(rh)] if okw and okh else [0, 0, w, h]
    base = _vb_matrix(vb, w, h, root.get("preserveAspectRatio"))
    r = _Renderer(root, w, h, lenient)
    r.vw, r.vh = vb[2], vb[3]
    cv = r.run(base)
    a = cv[..., 3:4]
    rgb = np.where(a > 1e-6, cv[..., :3] / np.maximum(a, 1e-6), 0)
    out = np.concatenate((rgb, a), -1)
    return Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA")
