"""Turn any image into a Tesla-compliant opaque PNG of the exact template canvas size."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from .models import canvas_size
from .naming import sanitize

MAX_BYTES = 1_000_000


def _parse_color(c) -> tuple[int, int, int]:
    if isinstance(c, str):
        s = c.strip().lstrip("#")
        if len(s) in (3, 4):
            s = "".join(ch * 2 for ch in s)
        if len(s) >= 6:
            return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
        raise ValueError(f"Bad colour '{c}'")
    return tuple(int(v) for v in c[:3])


def _fit(img: Image.Image, size: tuple[int, int], fit: str, base: tuple[int, int, int]) -> Image.Image:
    if img.size == size:
        return img
    if fit == "stretch":
        return img.resize(size, Image.LANCZOS)
    if fit == "cover":
        return ImageOps.fit(img, size, Image.LANCZOS)
    if fit == "contain":
        scale = min(size[0] / img.width, size[1] / img.height)
        nw, nh = max(1, round(img.width * scale)), max(1, round(img.height * scale))
        res = img.resize((nw, nh), Image.LANCZOS)
        canvas = Image.new("RGBA", size, base + (255,))
        canvas.alpha_composite(res, ((size[0] - nw) // 2, (size[1] - nh) // 2))
        return canvas
    raise ValueError(f"fit must be cover|contain|stretch, got '{fit}'")


def _encode(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True, compress_level=9)
    return buf.getvalue()


def _quant(img: Image.Image, colors: int, method) -> Image.Image:
    q = img.quantize(colors=colors, method=method, dither=Image.FLOYDSTEINBERG)
    q.info.pop("transparency", None)
    return q


def finalize(img: Image.Image, model_id: str, base_color=(16, 16, 16),
             fit: str = "cover", max_bytes: int = MAX_BYTES) -> tuple[bytes, dict]:
    """Resize to the model canvas, flatten onto base_color, and compress to <= max_bytes.

    Returns (png_bytes, info) where info has steps, final_mode, bytes, size, ok.
    """
    size = canvas_size(model_id)
    base = _parse_color(base_color)
    rgba = _fit(img.convert("RGBA"), size, fit, base)
    bg = Image.new("RGBA", size, base + (255,))
    bg.alpha_composite(rgba)
    rgb = bg.convert("RGB")

    steps: list[str] = []
    data = _encode(rgb)
    steps.append(f"rgb png: {len(data)} bytes")
    final_mode = "RGB"

    # Gentlest first: dropping low bits keeps RGB gradients smooth, palettes band visibly.
    for bits in (7, 6, 5):
        if len(data) <= max_bytes:
            break
        data = _encode(ImageOps.posterize(rgb, bits))
        steps.append(f"rgb posterize {bits}-bit: {len(data)} bytes")

    ladder = [(None, 256), (None, 192), (None, 128), (None, 64),
              ("blur", 256), ("blur", 128), ("blur", 64), ("blur", 32)]
    if len(data) > max_bytes:
        blurred = None
        for pre, colors in ladder:
            src = rgb
            if pre == "blur":
                blurred = blurred or rgb.filter(ImageFilter.GaussianBlur(0.6))
                src = blurred
            method = Image.MEDIANCUT if colors >= 128 or pre else Image.FASTOCTREE
            q = _quant(src, colors, method)
            data = _encode(q)
            final_mode = "P"
            steps.append(f"{'blur+' if pre else ''}quantize {colors}: {len(data)} bytes")
            if len(data) <= max_bytes:
                break

    out = Image.open(io.BytesIO(data))
    assert out.size == size
    info = {"steps": steps, "final_mode": final_mode, "bytes": len(data),
            "size": list(size), "ok": len(data) <= max_bytes}
    return data, info


def write_wrap(png_bytes: bytes, out_dir, filename: str) -> Path:
    """Write png_bytes into out_dir under a sanitised, Tesla-safe filename."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / sanitize(filename)
    path.write_bytes(png_bytes)
    return path
