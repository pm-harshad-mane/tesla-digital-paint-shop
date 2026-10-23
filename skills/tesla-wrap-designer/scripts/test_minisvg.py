#!/usr/bin/env python3
"""Compare wrapkit.minisvg against headless Chrome on representative LLM-style SVGs.

Run: python3 scripts/test_minisvg.py [--out DIR]
Chrome comparison is skipped (minisvg still must render non-empty) when Chrome is absent.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wrapkit import minisvg, svgrender  # noqa: E402

SIZE = (1024, 1024)
MIN_IOU = 0.95
DEFAULT_OUT = Path("/private/tmp/claude-502/-Users-harshadmane-Desktop-GitHub-tesla-digital-paint-shop/"
                   "cb3573ad-9fff-4d30-8ef6-d64a754ad328/scratchpad/minisvg")

UNICORN = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">
<defs>
 <linearGradient id="mane" x1="0" y1="0" x2="1" y2="1">
  <stop offset="0" stop-color="#ff6ec7"/><stop offset="0.5" stop-color="#a770ff"/><stop offset="1" stop-color="#4dd0ff"/>
 </linearGradient>
 <radialGradient id="face" cx="45%" cy="40%" r="65%"><stop offset="0%" stop-color="#ffffff"/><stop offset="100%" stop-color="#e6dcff"/></radialGradient>
 <linearGradient id="horn" gradientUnits="userSpaceOnUse" x1="250" y1="20" x2="270" y2="110">
  <stop offset="0" stop-color="#fff3a0"/><stop offset="1" stop-color="#ffb347"/></linearGradient>
</defs>
<path d="M120 120 C60 130 40 220 80 300 C100 340 60 360 40 380 C120 390 190 350 200 300 Z" fill="url(#mane)"/>
<path d="M150 90 C100 60 70 120 110 160 S120 240 100 270 C140 290 160 250 170 200 Z" fill="url(#mane)" opacity="0.9"/>
<path d="M170 110 C170 60 230 40 280 70 C330 100 350 170 340 230 C335 290 300 340 240 350 L190 360 C150 350 140 300 150 250 C160 200 165 160 170 110 Z"
      fill="url(#face)" stroke="#9b7fd6" stroke-width="4" stroke-linejoin="round"/>
<polygon points="250,80 270,15 285,85" fill="url(#horn)" stroke="#e08a1e" stroke-width="3" stroke-linejoin="round"/>
<path d="M205 90 Q215 40 235 85 Z" fill="#f2c8ff" stroke="#9b7fd6" stroke-width="3"/>
<ellipse cx="255" cy="160" rx="22" ry="28" fill="#fff"/>
<circle cx="260" cy="165" r="15" fill="#3b2a6e"/><circle cx="265" cy="158" r="5" fill="#fff"/>
<path d="M232 128 Q252 112 276 126" fill="none" stroke="#3b2a6e" stroke-width="5" stroke-linecap="round"/>
<ellipse cx="300" cy="260" rx="38" ry="28" fill="#ffd1ec" fill-opacity="0.9"/>
<circle cx="288" cy="262" r="5" fill="#b0508a"/><circle cx="312" cy="262" r="5" fill="#b0508a"/>
<path d="M270 300 Q300 322 330 295" fill="none" stroke="#b0508a" stroke-width="4" stroke-linecap="round"/>
<circle cx="215" cy="215" r="14" fill="#ff9ecb" opacity="0.6"/>
<g fill="#ffe66d" stroke="#d8a800" stroke-width="2"><polygon points="90,60 96,78 115,78 100,89 106,107 90,96 74,107 80,89 65,78 84,78"/></g>
</svg>"""

STARFIGHTER = """<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
<rect width="512" height="512" fill="#0b1026"/>
<g fill="#1c2a4f" fill-rule="evenodd" stroke="#8fb3ff" stroke-width="3" stroke-linejoin="miter">
 <path d="M256 40 L300 200 L420 150 L470 300 L360 330 L330 460 L256 420 L182 460 L152 330 L42 300 L92 150 L212 200 Z
          M256 140 m-30 0 a30 30 0 1 0 60 0 a30 30 0 1 0 -60 0 Z
          M256 300 l-40 60 h80 Z"/>
</g>
<path d="M120 250 a60 60 0 0 1 120 0" fill="none" stroke="#ff5252" stroke-width="6" stroke-linecap="round"/>
<path d="M392 250 a60 60 0 0 0 -120 0" fill="none" stroke="#ff5252" stroke-width="6" stroke-linecap="round" stroke-dasharray="14 8"/>
<path d="M60 460 A200 200 0 0 0 452 460" fill="none" stroke="#4dd0ff" stroke-width="4"/>
<path d="M60 40 a40 40 0 1 1 80 0 a40 40 0 0 1 -80 0" fill="#ffd166" fill-rule="nonzero"/>
<g stroke="#ffffff" stroke-width="2"><line x1="20" y1="20" x2="70" y2="90"/><polyline points="440,40 470,90 500,60 480,20" fill="none"/></g>
<rect x="206" y="470" width="100" height="24" rx="12" ry="12" fill="#ff8a3d"/>
</svg>"""

CAKE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">
<rect width="400" height="300" fill="#fff4e0"/>
<ellipse cx="200" cy="260" rx="150" ry="22" fill="#d9c3a0"/>
<rect x="80" y="170" width="240" height="85" rx="10" fill="#f6a6c1" stroke="#c4577f" stroke-width="3"/>
<rect x="100" y="110" width="200" height="65" rx="10" fill="#fff" stroke="#c4577f" stroke-width="3"/>
<path d="M80 190 q20 25 40 0 q20 25 40 0 q20 25 40 0 q20 25 40 0 q20 25 40 0 q20 25 40 0" fill="none" stroke="#fff" stroke-width="8" stroke-linecap="round"/>
<g stroke="#e63946" stroke-width="6" stroke-linecap="round"><line x1="150" y1="110" x2="150" y2="75"/><line x1="200" y1="110" x2="200" y2="75"/><line x1="250" y1="110" x2="250" y2="75"/></g>
<g fill="#ffb703"><path d="M150 72 q-8 -14 0 -22 q8 8 0 22z"/><path d="M200 72 q-8 -14 0 -22 q8 8 0 22z"/><path d="M250 72 q-8 -14 0 -22 q8 8 0 22z"/></g>
<text x="200" y="150" font-family="Arial, Helvetica, sans-serif" font-size="26" font-weight="bold" text-anchor="middle" fill="#c4577f">Happy Birthday</text>
<text x="200" y="40" font-family="Georgia, serif" font-size="30" text-anchor="middle" fill="#2b2d42">Make a wish!</text>
<text x="20" y="290" font-family="monospace" font-size="14" fill="#555">age: 7</text>
<text x="380" y="290" font-family="sans-serif" font-size="14" text-anchor="end" fill="#555">cake.svg</text>
</svg>"""

TRANSFORMS = """<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 300 300" preserveAspectRatio="xMidYMid meet" width="300" height="300">
<defs>
 <g id="petal"><path d="M0 0 C-12 -20 -12 -45 0 -60 C12 -45 12 -20 0 0 Z" fill="#ff7aa2" stroke="#b8325f" stroke-width="2"/></g>
 <linearGradient id="g1" x1="0" x2="1" y1="0" y2="0"><stop offset="0" stop-color="#2ec4b6"/><stop offset="1" stop-color="#3a86ff"/></linearGradient>
 <linearGradient id="g2" xlink:href="#g1" gradientTransform="rotate(90)"/>
 <clipPath id="cp"><circle cx="0" cy="0" r="28"/></clipPath>
 <filter id="blur"><feGaussianBlur stdDeviation="4"/></filter>
</defs>
<g transform="translate(150 150)">
 <use xlink:href="#petal"/>
 <use xlink:href="#petal" transform="rotate(45)"/><use xlink:href="#petal" transform="rotate(90)"/>
 <use xlink:href="#petal" transform="rotate(135)"/><use xlink:href="#petal" transform="rotate(180)"/>
 <use xlink:href="#petal" transform="rotate(225)"/><use xlink:href="#petal" transform="rotate(270)"/>
 <use xlink:href="#petal" transform="rotate(315)"/>
 <g clip-path="url(#cp)"><rect x="-40" y="-40" width="80" height="80" fill="url(#g2)"/><rect x="-40" y="-5" width="80" height="10" fill="#fff" opacity="0.5"/></g>
</g>
<g transform="translate(40 40) scale(1.5 0.8) skewX(20)"><rect width="40" height="30" fill="url(#g1)"/></g>
<g transform="translate(230 50) rotate(30 20 20)" opacity="0.6"><rect width="40" height="40" fill="#ffbe0b"/><circle cx="40" cy="40" r="15" fill="#fb5607"/></g>
<g transform="matrix(1 0 0 1 20 240)"><g transform="skewY(-10)"><rect width="60" height="30" fill="#8338ec" rx="5"/></g></g>
<circle cx="250" cy="250" r="22" fill="#ef476f" filter="url(#blur)"/>
<rect x="100" y="100" width="20" height="20" fill="red" display="none"/>
<rect x="110" y="260" width="80" height="20" style="fill:#06d6a0;stroke:#073b4c;stroke-width:3;stroke-dasharray:10 5"/>
</svg>"""

PLANET = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">
<defs>
 <radialGradient id="sky" cx="50%" cy="50%" r="75%"><stop offset="0" stop-color="#1b1f4b"/><stop offset="1" stop-color="#05060f"/></radialGradient>
 <radialGradient id="planet" cx="35%" cy="30%" r="75%" fx="30%" fy="25%">
  <stop offset="0" stop-color="#ffd59e"/><stop offset="0.45" stop-color="#e2673a"/><stop offset="1" stop-color="#3a0f2e"/></radialGradient>
 <radialGradient id="glow" cx="200" cy="200" r="150" gradientUnits="userSpaceOnUse">
  <stop offset="0.6" stop-color="#ff9a5a" stop-opacity="0.6"/><stop offset="1" stop-color="#ff9a5a" stop-opacity="0"/></radialGradient>
 <linearGradient id="ring" x1="0" y1="0" x2="1" y2="0" spreadMethod="reflect"><stop offset="0" stop-color="#f7e1b5"/><stop offset="0.5" stop-color="#b58a5a"/><stop offset="1" stop-color="#f7e1b5"/></linearGradient>
</defs>
<rect width="400" height="400" fill="url(#sky)"/>
<circle cx="200" cy="200" r="150" fill="url(#glow)"/>
<g fill="#fff"><circle cx="40" cy="50" r="2"/><circle cx="350" cy="80" r="1.5"/><circle cx="90" cy="330" r="2.5"/><circle cx="330" cy="340" r="2"/><circle cx="60" cy="180" r="1.2"/></g>
<path d="M60 230 A150 40 -15 0 1 340 170" fill="none" stroke="url(#ring)" stroke-width="14" opacity="0.8"/>
<circle cx="200" cy="200" r="100" fill="url(#planet)"/>
<path d="M60 230 A150 40 -15 0 0 340 170" fill="none" stroke="url(#ring)" stroke-width="14" opacity="0.9"/>
<circle cx="150" cy="170" r="18" fill="#000" fill-opacity="0.12"/><circle cx="235" cy="240" r="26" fill="#000" fill-opacity="0.1"/>
</svg>"""

CASES = {"unicorn": UNICORN, "starfighter": STARFIGHTER, "cake": CAKE, "transforms": TRANSFORMS, "planet": PLANET}


def metrics(a: Image.Image, b: Image.Image):
    x, y = np.asarray(a, np.float32), np.asarray(b, np.float32)
    mad = float(np.abs(x - y).mean())
    ma, mb = x[..., 3] > 128, y[..., 3] > 128
    union = (ma | mb).sum()
    return mad, float((ma & mb).sum() / union) if union else 1.0


def side_by_side(mini, chrome, path: Path):
    w, h = mini.size
    bg = Image.new("RGBA", (w * 3, h), (255, 255, 255, 255))
    for i, im in enumerate((mini, chrome)):
        if im is not None:
            tile = Image.new("RGBA", (w, h), (200, 200, 200, 255))
            tile.alpha_composite(im)
            bg.alpha_composite(tile, (i * w, 0))
    if chrome is not None:
        d = np.abs(np.asarray(mini, np.int16) - np.asarray(chrome, np.int16)).max(-1).clip(0, 255).astype(np.uint8)
        bg.paste(Image.fromarray(255 - d).convert("RGBA"), (2 * w, 0))
    bg.convert("RGB").resize((w * 3 // 2, h // 2), Image.LANCZOS).save(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    have_chrome = svgrender._find_chrome() is not None
    if not have_chrome:
        print("Chrome not found: comparison skipped, checking minisvg output only")
    fails = 0
    for name, svg in CASES.items():
        t = time.time()
        mini = minisvg.render(svg, SIZE)
        dt = time.time() - t
        if np.asarray(mini)[..., 3].max() == 0:
            print(f"FAIL {name}: empty render")
            fails += 1
            continue
        chrome = None
        line = f"{name:12s} mini {dt:5.2f}s"
        if have_chrome:
            chrome = svgrender._render_chrome(svgrender._force_size(svg, *SIZE), *SIZE)
            mad, iou = metrics(mini, chrome)
            ok = iou >= MIN_IOU
            fails += not ok
            line += f"  MAD {mad:6.2f}  IoU {iou:.4f}  {'ok' if ok else 'FAIL'}"
        side_by_side(mini, chrome, out / f"{name}.png")
        print(line)
    # security: entity declarations must be rejected
    try:
        minisvg.render('<!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="http://www.w3.org/2000/svg"/>', (8, 8))
        print("FAIL: DOCTYPE accepted")
        fails += 1
    except minisvg.UnsafeSVG:
        print("DOCTYPE rejected: ok")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
