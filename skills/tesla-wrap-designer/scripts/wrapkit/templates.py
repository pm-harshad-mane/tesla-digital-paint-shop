"""Fetch/cache Tesla templates and derive mask + panel artifacts."""
from __future__ import annotations

import io
import json
import os
import shutil
import ssl
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .models import SKILL_ROOT, canvas_size, raw_url

BUNDLED_DIR = SKILL_ROOT / "assets" / "templates"  # optional vendored templates (offline builds)
FILES = ("template.png", "vehicle_image.png")


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=d):
            pass
        return True
    except OSError:
        return False


def _cache_dir() -> Path:
    """First writable of: $TESLA_WRAP_CACHE, <skill>/.cache, ~/.cache, system temp.

    Skill folders are read-only on some platforms (e.g. uploaded skills), so never assume
    the skill directory is writable."""
    candidates = [Path(os.environ["TESLA_WRAP_CACHE"])] if os.environ.get("TESLA_WRAP_CACHE") else []
    candidates += [SKILL_ROOT / ".cache" / "templates",
                   Path.home() / ".cache" / "tesla-wrap-designer" / "templates",
                   Path(tempfile.gettempdir()) / "tesla-wrap-designer" / "templates"]
    for d in candidates:
        if _writable(d):
            return d
    raise TemplateError("No writable cache directory found; set TESLA_WRAP_CACHE to a writable folder")
PNG_SIG = b"\x89PNG\r\n\x1a\n"
MIN_PANEL_FRAC = 0.0005

_BOLD_FONTS = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)
_PALETTE = [
    (230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48),
    (145, 30, 180), (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212),
    (0, 128, 128), (220, 190, 255), (170, 110, 40), (255, 250, 200), (128, 0, 0),
    (170, 255, 195), (128, 128, 0), (255, 215, 180), (0, 0, 128), (128, 128, 128),
]


class TemplateError(RuntimeError):
    pass


CACHE_DIR = _cache_dir()


def _ssl_contexts() -> list:
    """Verified TLS contexts to try: default, certifi, then common system CA bundles (python.org macOS builds ship none)."""
    ctxs = [ssl.create_default_context()]
    try:
        import certifi
        ctxs.append(ssl.create_default_context(cafile=certifi.where()))
    except ImportError:
        pass
    for cafile in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"):
        if Path(cafile).exists():
            ctxs.append(ssl.create_default_context(cafile=cafile))
    return ctxs


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "tesla-wrap-designer/1.0"})
    last: Exception | None = None
    for ctx in _ssl_contexts():
        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                return r.read()
        except urllib.error.URLError as e:
            last = e
            if not isinstance(e.reason, ssl.SSLError):
                break
        except (OSError, TimeoutError) as e:
            last = e
            break
    raise TemplateError(
        f"Could not download {url}\n  ({last})\n"
        "If downloads are blocked, get template.png for this model from "
        "https://github.com/teslamotors/custom-wraps (the user can download it in a browser and "
        "attach it), then run: fetch_templates.py --model <id> --template <path/to/template.png>"
    ) from last


def _fetch_file(model_id: str, fname: str, dest: Path, size: tuple[int, int] | None) -> None:
    data = _download(raw_url(model_id, fname))
    if not data.startswith(PNG_SIG):
        raise TemplateError(f"{fname} for {model_id} is not a PNG (got {data[:16]!r})")
    if size is not None:
        got = Image.open(io.BytesIO(data)).size
        if got != size:
            raise TemplateError(f"{fname} for {model_id} is {got}, expected {size}")
    dest.write_bytes(data)


def _label(binary: np.ndarray) -> tuple[np.ndarray, int]:
    try:
        from scipy import ndimage
        return ndimage.label(binary)  # default structure = 4-connectivity
    except ImportError:
        return _label_uf(binary)


def _label_uf(binary: np.ndarray) -> tuple[np.ndarray, int]:
    """Two-pass run-based union-find labelling (4-connectivity), numpy-assisted."""
    h, w = binary.shape
    parent = [0]

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    labels = np.zeros((h, w), dtype=np.int32)
    prev_runs: list[tuple[int, int, int]] = []
    for y in range(h):
        row = binary[y]
        padded = np.concatenate(([0], row.astype(np.int8), [0]))
        d = np.diff(padded)
        starts = np.flatnonzero(d == 1)
        ends = np.flatnonzero(d == -1)
        cur_runs = []
        pi = 0
        for s, e in zip(starts.tolist(), ends.tolist()):
            while pi < len(prev_runs) and prev_runs[pi][1] <= s:
                pi += 1
            lab = 0
            j = pi
            while j < len(prev_runs) and prev_runs[j][0] < e:
                pl = prev_runs[j][2]
                if lab == 0:
                    lab = pl
                else:
                    ra, rb = find(lab), find(pl)
                    if ra != rb:
                        parent[max(ra, rb)] = min(ra, rb)
                j += 1
            if lab == 0:
                parent.append(len(parent))
                lab = len(parent) - 1
            labels[y, s:e] = lab
            cur_runs.append((s, e, lab))
        prev_runs = cur_runs
    roots = np.array([find(i) for i in range(len(parent))], dtype=np.int32)
    uniq, inv = np.unique(roots[1:], return_inverse=True)
    remap = np.concatenate(([0], inv + 1)).astype(np.int32)
    return remap[labels], len(uniq)


def _font(size: int):
    for p in _BOLD_FONTS:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


PANELS_SCHEMA = 2


def compute_panels(template: Image.Image) -> tuple[dict, np.ndarray]:
    rgba = np.asarray(template.convert("RGBA"))
    h, w = rgba.shape[:2]
    r, g, b, a = (rgba[..., i].astype(np.float32) for i in range(4))
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    binary = (a >= 128) & (luma >= 160)
    lab, n = _label(binary)
    areas = np.bincount(lab.ravel(), minlength=n + 1)
    min_area = MIN_PANEL_FRAC * w * h
    keep = [i for i in range(1, n + 1) if areas[i] >= min_area]
    keep.sort(key=lambda i: -areas[i])
    panel_map = np.zeros((h, w), dtype=np.int32)
    panels = []
    ys_all, xs_all = np.nonzero(lab)
    order = np.argsort(lab[ys_all, xs_all], kind="stable")
    ys_s, xs_s = ys_all[order], xs_all[order]
    bounds = np.concatenate(([0], np.cumsum(areas[1:]))) if n else np.array([0])
    for new_id, old in enumerate(keep, start=1):
        sl = slice(bounds[old - 1], bounds[old])
        ys, xs = ys_s[sl], xs_s[sl]
        panel_map[ys, xs] = new_id
        cx, cy = float(xs.mean()), float(ys.mean())
        dx, dy = xs - cx, ys - cy
        mxx, myy, mxy = float((dx * dx).mean()), float((dy * dy).mean()), float((dx * dy).mean())
        angle = float(np.degrees(0.5 * np.arctan2(2 * mxy, mxx - myy)))
        long_axis = "horizontal" if abs(angle) <= 45 else "vertical"
        panels.append({
            "id": new_id,
            "bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
            "area": int(areas[old]),
            "centroid": [round(cx, 1), round(cy, 1)],
            "angle_deg": round(angle, 2),
            "long_axis": long_axis,
            **_orientation(cx, cy, w, h, long_axis),
        })
    return {"schema": PANELS_SCHEMA, "canvas": [w, h], "panels": panels}, panel_map


def _orientation(cx: float, cy: float, w: int, h: int, long_axis: str) -> dict:
    """Classify a panel's UV region and the CCW rotation that makes art upright on the car.

    Derived from Tesla's own example wraps (e.g. "Ani"): on 1024x1024 layouts the front is at
    the top, hood art is rotated 180, left-column side panels +90, right-column -90, rear 0.
    On the 1024x768 Cybertruck layout the sides are the top/bottom bands (top one 180), the
    hood/front panels sit left (-90) and the rear sits right (+90).
    """
    if w != h:  # Cybertruck
        if long_axis == "horizontal":
            return {"region": "side", "upright_rotate": 180 if cy < h / 2 else 0}
        return ({"region": "front", "upright_rotate": -90} if cx < w / 2
                else {"region": "rear", "upright_rotate": 90})
    if cx < 0.3 * w:
        return {"region": "side", "upright_rotate": 90}
    if cx > 0.7 * w:
        return {"region": "side", "upright_rotate": -90}
    if long_axis == "vertical":  # A-pillars / roof rails in the centre column
        return {"region": "pillar", "upright_rotate": 90 if cx < w / 2 else -90}
    return ({"region": "front", "upright_rotate": 180} if cy < h / 2
            else {"region": "rear", "upright_rotate": 0})


def _overlay(template: Image.Image, info: dict, panel_map: np.ndarray) -> Image.Image:
    w, h = template.size
    base = np.zeros((h, w, 3), dtype=np.float32)
    base[:] = (0x22, 0x22, 0x22)
    tpl = template.convert("RGBA")
    white = np.full((h, w, 3), 255, dtype=np.float32)
    tarr = np.asarray(tpl).astype(np.float32)
    alpha = (tarr[..., 3:4] / 255.0)
    img = base * (1 - alpha) + tarr[..., :3] * alpha
    tint = np.zeros((h, w, 3), dtype=np.float32)
    msk = panel_map > 0
    for p in info["panels"]:
        col = np.array(_PALETTE[(p["id"] - 1) % len(_PALETTE)], dtype=np.float32)
        tint[panel_map == p["id"]] = col
    mixed = white * 0.4 + tint * 0.6
    mixed = mixed * (tarr[..., :3] / 255.0 * 0.25 + 0.75)
    img[msk] = mixed[msk]
    out = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(out)
    for p in info["panels"]:
        x0, y0, x1, y1 = p["bbox"]
        size = int(max(18, min(64, min(x1 - x0, y1 - y0) * 0.5)))
        d.text(tuple(p["centroid"]), str(p["id"]), font=_font(size), fill="white",
               anchor="mm", stroke_width=max(2, size // 8), stroke_fill="black")
    return out


def _derive(model_id: str, d: Path) -> None:
    template = Image.open(d / "template.png")
    template.load()
    if template.size != canvas_size(model_id):
        raise TemplateError(f"{model_id} template is {template.size}, expected {canvas_size(model_id)}")
    rgba = template.convert("RGBA")
    Image.fromarray((np.asarray(rgba)[..., 3] > 0).astype(np.uint8) * 255, "L").save(d / "mask.png")
    info, pmap = compute_panels(rgba)
    (d / "panels.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    pm_img = Image.fromarray(pmap.astype(np.uint8) if len(info["panels"]) < 255 else pmap.astype(np.int32))
    pm_img.save(d / "panels.png")
    _overlay(rgba, info, pmap).save(d / "panels_overlay.png")


def import_template(model_id: str, template: Path, vehicle_image: Path | None = None) -> Path:
    """Install a user-supplied template.png (e.g. downloaded manually) and derive artifacts."""
    size = canvas_size(model_id)
    data = Path(template).read_bytes()
    if not data.startswith(PNG_SIG):
        raise TemplateError(f"{template} is not a PNG")
    got = Image.open(io.BytesIO(data)).size
    if got != size:
        raise TemplateError(f"{template} is {got[0]}x{got[1]}, but {model_id} needs {size[0]}x{size[1]} "
                            "- is it the template for the right model?")
    d = CACHE_DIR / model_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "template.png").write_bytes(data)
    if vehicle_image:
        shutil.copyfile(vehicle_image, d / "vehicle_image.png")
    _derive(model_id, d)
    return d


def ensure_template(model_id: str, refresh: bool = False) -> Path:
    """Locate (cache → bundled assets → download) and derive template artifacts; return the dir.

    vehicle_image.png is optional (only used by previews); its absence is not an error."""
    size = canvas_size(model_id)
    d = CACHE_DIR / model_id
    d.mkdir(parents=True, exist_ok=True)
    fetched = refresh
    for fname in FILES:
        dest = d / fname
        bundled = BUNDLED_DIR / model_id / fname
        if dest.exists() and not refresh and not (
                bundled.exists() and bundled.read_bytes() != dest.read_bytes()):
            continue
        if bundled.exists() and not refresh:
            shutil.copyfile(bundled, dest)
        else:
            try:
                _fetch_file(model_id, fname, dest, size if fname == "template.png" else None)
            except TemplateError:
                if fname == "template.png":
                    raise
                continue
        fetched = True
    derived = ("mask.png", "panels.json", "panels.png", "panels_overlay.png")
    stale = (d / "panels.json").exists() and json.loads(
        (d / "panels.json").read_text(encoding="utf-8")).get("schema") != PANELS_SCHEMA
    if fetched or stale or any(not (d / n).exists() for n in derived):
        _derive(model_id, d)
    return d


def load_mask(model_id: str) -> Image.Image:
    return Image.open(ensure_template(model_id) / "mask.png").convert("L")


def load_panels(model_id: str) -> dict:
    return json.loads((ensure_template(model_id) / "panels.json").read_text(encoding="utf-8"))


def load_panel_map(model_id: str) -> np.ndarray:
    return np.asarray(Image.open(ensure_template(model_id) / "panels.png")).astype(np.int32)
