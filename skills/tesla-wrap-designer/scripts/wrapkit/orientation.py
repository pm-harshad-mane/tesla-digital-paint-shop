"""Verify that text (and other hero elements) will read upright on the car.

Each panel's `upright_rotate` (panels.json) is the CCW rotation that makes content upright on
the car. An element is correct when its applied rotation matches the panel's upright_rotate.
`reads_on_car_sheet` un-rotates each element by its panel's upright_rotate, showing it the way
it will appear on the car: text in that image must read normally, left to right.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from .compose import MIN_TEXT_PX, SMALL_TEXT_PX
from .fonts import resolve_font

TOLERANCE = 15  # degrees; small tilts are treated as intentional styling
MIN_ON_PANEL = 0.9


def _diff(a: float, b: float) -> float:
    return (a - b + 180) % 360 - 180


def _verdict(d: float) -> str:
    d = abs(d)
    if d <= TOLERANCE:
        return "upright"
    if d >= 180 - TOLERANCE:
        return "UPSIDE-DOWN"
    if 90 - TOLERANCE <= d <= 90 + TOLERANCE:
        return "SIDEWAYS"
    return f"TILTED {d:.0f}deg"


def check(placements: list[dict], panels: dict[int, dict]) -> list[dict]:
    """Return one result per placement: {ok, severity, message, expected, verdict, ...}."""
    out = []
    for p in placements:
        is_text = p["kind"] == "text"
        name = f'layer {p["layer"]} {p["kind"]} "{str(p["label"])[:40]}"'.replace("\n", " ")
        pid = p.get("panel")
        if pid is None or pid not in panels:
            out.append({**p, "ok": not is_text, "severity": "error" if is_text else "warn",
                        "verdict": "OFF-CAR", "expected": None,
                        "message": f"{name} does not land on any car panel (it will not be visible)"})
            continue
        panel = panels[pid]
        expected = float(panel.get("upright_rotate", 0))
        verdict = _verdict(_diff(p["rotate"], expected))
        ok = verdict == "upright"
        msgs = [f"{name} on panel {pid} ({panel.get('region', '?')}): rotate {p['rotate']:.0f}, "
                f"needs {expected:.0f} -> {verdict}"]
        if p["on_panel_frac"] < MIN_ON_PANEL and not p.get("fills_panel"):
            msgs.append(f"only {p['on_panel_frac']:.0%} inside the panel - it crosses a seam")
            ok = False
        x0, y0, x1, y1 = p["bbox"]
        tall = min(x1 - x0, y1 - y0)
        severity = "info" if ok else ("error" if is_text else "warn")
        if is_text and tall < MIN_TEXT_PX:
            msgs.append(f"only {tall} px tall - unreadable on the car; use a bigger panel")
            ok, severity = False, "error"
        elif is_text and tall < SMALL_TEXT_PX and ok:
            msgs.append(f"only {tall} px tall - small on the car; consider a bigger panel or shorter text")
            ok, severity = False, "warn"
        if not ok and not is_text:
            msgs.append("check it in the orientation sheet if it contains lettering or a face")
        out.append({**p, "ok": ok, "severity": severity, "verdict": verdict, "expected": expected,
                    "message": "; ".join(msgs)})
    return out


def front_hint(expected: float, square: bool = True) -> str:
    """Where the car's front is in the as-on-car view (the UV crop rotated by -expected).
    The car's front is the top of the canvas on 1024x1024 layouts and the left on Cybertruck."""
    uv_front = 90 if square else 180  # direction of the car's front in UV, degrees CCW from +x
    d = round(uv_front - expected) % 360
    return {90: "front ^", 270: "front v", 0: "front >", 180: "< front"}.get(d, "")


def _caption_tile(img: Image.Image, caption: str, good: bool, width: int) -> Image.Image:
    img = img.copy()
    img.thumbnail((width, width), Image.LANCZOS)
    font = resolve_font("sans-bold", 15)
    tile = Image.new("RGB", (width, img.height + 30), (24, 24, 28))
    tile.paste(img, ((width - img.width) // 2, 30))
    d = ImageDraw.Draw(tile)
    d.rectangle((0, 0, width, 26), fill=(30, 120, 60) if good else (170, 40, 40))
    d.text((6, 13), caption, font=font, fill="white", anchor="lm")
    return tile


def _grid(tiles: list[Image.Image], cols: int, width: int) -> Image.Image:
    rows = [tiles[i:i + cols] for i in range(0, len(tiles), cols)]
    heights = [max(t.height for t in r) for r in rows]
    sheet = Image.new("RGB", (cols * (width + 8) + 8, sum(heights) + 8 * (len(rows) + 1)), (0, 0, 0))
    y = 8
    for r, h in zip(rows, heights):
        for i, t in enumerate(r):
            sheet.paste(t, (8 + i * (width + 8), y))
        y += h + 8
    return sheet


def _as_on_car(wrap: Image.Image, bbox, expected: float, pad: int = 14) -> Image.Image:
    x0, y0, x1, y1 = bbox
    crop = wrap.crop((max(0, x0 - pad), max(0, y0 - pad), min(wrap.width, x1 + pad), min(wrap.height, y1 + pad)))
    return crop.rotate(-expected, resample=Image.BICUBIC, expand=True, fillcolor=(24, 24, 28))


def reads_on_car_sheet(wrap: Image.Image, results: list[dict], width: int = 320) -> Image.Image | None:
    """Each placed element as it will appear on the car. Text must read normally."""
    wrap = wrap.convert("RGB")
    square = wrap.width == wrap.height
    tiles = []
    for r in results:
        if r.get("expected") is None:
            continue
        label = str(r["label"]).replace("\n", " ")[:22]
        cap = f'{"OK" if r["ok"] else r["verdict"]} | p{r["panel"]} {front_hint(r["expected"], square)} | {label}'
        tiles.append(_caption_tile(_as_on_car(wrap, r["bbox"], r["expected"]), cap, r["ok"], width))
    return _grid(tiles, min(4, len(tiles)), width) if tiles else None


def panel_views_sheet(wrap: Image.Image, panels: dict[int, dict], panel_map: np.ndarray | None = None,
                      min_area_frac: float = 0.01, width: int = 300) -> Image.Image:
    """Every sizeable panel rotated the way it appears on the car (for art without a spec,
    e.g. user-supplied PNGs): any lettering visible here must read normally."""
    wrap = wrap.convert("RGB")
    square = wrap.width == wrap.height
    total = wrap.width * wrap.height
    tiles = []
    for pid, p in sorted(panels.items()):
        if p["area"] < min_area_frac * total:
            continue
        cap = f'panel {pid} ({p.get("region", "?")}) {front_hint(float(p.get("upright_rotate", 0)), square)}'
        src = wrap
        if panel_map is not None:  # dim neighbouring panels so only this panel is judged
            arr = np.asarray(wrap).astype(np.float32)
            arr[panel_map != pid] *= 0.2
            src = Image.fromarray(arr.astype(np.uint8))
        tiles.append(_caption_tile(_as_on_car(src, p["bbox"], float(p.get("upright_rotate", 0)), 4),
                                   cap, True, width))
    return _grid(tiles, 4, width)
