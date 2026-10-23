#!/usr/bin/env python3
"""Build review images for a wrap:
  <stem>_check.png   left = art on the car surface with seams drawn, right = panel ids;
  <stem>_on_car.png  every sizeable panel rotated the way it appears on the car - any
                     lettering in it must read normally (catches upside-down/sideways text
                     in art that did not come from a design spec, e.g. user-supplied PNGs).

Note: hood/front art looks upside-down on the flat canvas by design (it is upright on the car)."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from wrapkit import orientation, templates  # noqa: E402
from wrapkit.fonts import resolve_font  # noqa: E402


def build(wrap_path: Path, model_id: str) -> Image.Image:
    d = templates.ensure_template(model_id)
    tpl = np.asarray(Image.open(d / "template.png").convert("RGBA")).astype(np.float32)
    art = np.asarray(Image.open(wrap_path).convert("RGB")).astype(np.float32)
    if art.shape[:2] != tpl.shape[:2]:
        raise SystemExit(f"ERROR: wrap is {art.shape[1]}x{art.shape[0]}, template is "
                         f"{tpl.shape[1]}x{tpl.shape[0]} - finalize it for {model_id} first")
    surface = tpl[..., 3] > 0
    seams = surface & (tpl[..., :3].mean(-1) < 100)

    left = art.copy()
    left[~surface] = (24, 24, 28)
    left[seams] = (255, 40, 40)

    right = art * 0.55 + 255 * 0.15
    right[~surface] *= 0.35
    right[seams] = (255, 255, 255)
    right_img = Image.fromarray(right.clip(0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(right_img)
    for p in templates.load_panels(model_id)["panels"]:
        x0, y0, x1, y1 = p["bbox"]
        size = int(max(16, min(56, min(x1 - x0, y1 - y0) * 0.45)))
        label = f'{p["id"]}' + {"front": "F", "rear": "R"}.get(p.get("region"), "")
        draw.text(tuple(p["centroid"]), label, font=resolve_font("sans-bold", size), fill="white",
                  anchor="mm", stroke_width=max(2, size // 8), stroke_fill="black")

    h, w = art.shape[:2]
    out = Image.new("RGB", (w * 2 + 16, h), (0, 0, 0))
    out.paste(Image.fromarray(left.astype(np.uint8)), (0, 0))
    out.paste(right_img, (w + 16, 0))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("wrap", type=Path, help="wrap PNG")
    ap.add_argument("--model", required=True, help="model id")
    ap.add_argument("-o", "--out", type=Path, help="output PNG (default <wrap dir>/review/<stem>_check.png)")
    ap.add_argument("--scale", type=float, default=0.5, help="output scale (default 0.5)")
    a = ap.parse_args()
    out = a.out or a.wrap.parent / "review" / f"{a.wrap.stem}_check.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img = build(a.wrap, a.model)
    if a.scale != 1:
        img = img.resize((int(img.width * a.scale), int(img.height * a.scale)), Image.LANCZOS)
    img.save(out)
    print(out)
    panels = {p["id"]: p for p in templates.load_panels(a.model)["panels"]}
    on_car = out.with_name(out.name.replace("_check.png", "") + "_on_car.png") \
        if out.name.endswith("_check.png") else out.with_name(out.stem + "_on_car.png")
    orientation.panel_views_sheet(Image.open(a.wrap), panels, templates.load_panel_map(a.model)).save(on_car)
    print(on_car)
    return 0


if __name__ == "__main__":
    sys.exit(main())
