"""SVG -> RGBA Image via cairosvg, the pure-Python minisvg, or headless Chrome/Chromium.

Order: cairosvg (if importable) -> minisvg -> Chrome (only when minisvg raises UnsupportedSVG).
Force one with env TESLA_WRAP_SVG=cairo|mini|chrome.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import warnings
from pathlib import Path

from PIL import Image

from . import minisvg

_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome",
]


def _find_chrome() -> str | None:
    for c in _CHROME_CANDIDATES:
        if os.path.isabs(c):
            if os.path.isfile(c):
                return c
        elif shutil.which(c):
            return shutil.which(c)
    return None


def _read(svg_text_or_path) -> str:
    s = str(svg_text_or_path)
    if "<svg" not in s[:2000].lower() and len(s) < 1024 and os.path.isfile(s):
        return Path(s).read_text(encoding="utf-8")
    return s


def _force_size(svg: str, w: int, h: int) -> str:
    """Ensure root <svg> has a viewBox and width/height filling the target box."""
    m = re.search(r"<svg\b[^>]*>", svg, re.I | re.S)
    if not m:
        raise ValueError("Not an SVG document (no <svg> element)")
    tag = m.group(0)
    new = tag
    if "viewbox" not in tag.lower():
        mw = re.search(r'\swidth="([\d.]+)', tag)
        mh = re.search(r'\sheight="([\d.]+)', tag)
        if mw and mh:
            new = new[:-1] + f' viewBox="0 0 {mw.group(1)} {mh.group(1)}">'
    par = re.search(r'\spreserveAspectRatio="([^"]*)"', new)
    new = re.sub(r'\s(width|height|preserveAspectRatio)="[^"]*"', "", new)
    new = new[:-1] + f' width="{w}" height="{h}" preserveAspectRatio="{par.group(1) if par else "xMidYMid meet"}">'
    if "xmlns=" not in new:
        new = new.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return svg.replace(tag, new, 1)


def _render_cairo(svg: str, w: int, h: int) -> Image.Image:
    import io

    import cairosvg  # type: ignore
    png = cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=w, output_height=h)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def _cairo_available() -> bool:
    try:
        import cairosvg  # type: ignore  # noqa: F401
        return True
    except (ImportError, OSError):  # OSError: libcairo missing
        return False


def render_svg(svg_text_or_path, size) -> Image.Image:
    """Rasterise SVG to an RGBA image of exactly size=(w, h)."""
    w, h = int(size[0]), int(size[1])
    raw = _read(svg_text_or_path)
    minisvg.reject_dtd(raw)  # XXE / entity-expansion guard for every backend
    backend = os.environ.get("TESLA_WRAP_SVG", "").strip().lower()
    if backend in ("cairo", "cairosvg"):
        return _render_cairo(_force_size(raw, w, h), w, h)
    if backend in ("mini", "minisvg"):
        return minisvg.render(raw, (w, h), lenient=True)
    if backend == "chrome":
        return _render_chrome(_force_size(raw, w, h), w, h)
    if _cairo_available():
        return _render_cairo(_force_size(raw, w, h), w, h)
    try:
        return minisvg.render(raw, (w, h))
    except minisvg.UnsupportedSVG as e:
        if not _find_chrome():
            warnings.warn(f"SVG uses unsupported features ({e}) and no Chrome was found; "
                          f"rendering best-effort with minisvg", stacklevel=2)
            return minisvg.render(raw, (w, h), lenient=True)
    return _render_chrome(_force_size(raw, w, h), w, h)


def _render_chrome(svg: str, w: int, h: int) -> Image.Image:
    chrome = _find_chrome()
    if not chrome:
        raise RuntimeError("SVG layers need cairosvg (pip install cairosvg) or Google Chrome/Chromium "
                           "installed; neither was found.")
    with tempfile.TemporaryDirectory(prefix="wrapsvg_") as td:
        html = Path(td, "page.html")
        out = Path(td, "out.png")
        html.write_text(
            f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; "
            f"img-src data: file:; style-src 'unsafe-inline'; font-src data: file:\">"
            f"<style>html,body{{margin:0;padding:0;"
            f"background:transparent;overflow:hidden}}svg{{display:block}}</style></head>"
            f"<body>{svg}</body></html>", encoding="utf-8")
        cmd = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
               "--disable-background-networking", "--no-first-run",
               "--default-background-color=00000000", f"--user-data-dir={td}/profile",
               f"--window-size={w},{h}", f"--screenshot={out}", f"file://{html}"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd.insert(1, "--no-sandbox")  # Chrome refuses to start sandboxed as root (containers)
        try:
            subprocess.run(cmd, check=False, timeout=60, capture_output=True)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("Headless Chrome timed out rendering SVG") from e
        if not out.exists():
            raise RuntimeError("Headless Chrome produced no screenshot for SVG")
        img = Image.open(out).convert("RGBA")
        img.load()
    if img.size != (w, h):
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        canvas.paste(img.crop((0, 0, min(w, img.width), min(h, img.height))), (0, 0))
        img = canvas
    return img
