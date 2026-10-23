#!/usr/bin/env python3
"""AI image mode: plan the images to generate for a vehicle and write a design-spec skeleton.

For each art region (background, both sides as one panorama, hood, trunk) it measures the
region's shape as seen on the car, picks the closest generation size, and writes:
  <out-dir>/ai_assets.json  assets to generate: file, aspect, size, composition rules
  <out-dir>/design.json     spec that cuts those images onto the template (+ text slots)
Fill in each asset's prompt, generate the images (see references/ai-image-mode.md), save them
under the listed file names, then run render_wrap.py on design.json.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wrapkit import compose, models, templates  # noqa: E402

# Common image-generation sizes; if the host tool takes other sizes, match the aspect ratio.
GEN_SIZES = [(1024, 1024), (1536, 1024), (1024, 1536)]

NO_TEXT = ("No text, letters, numbers, logos, watermarks or signatures anywhere in the image. "
           "No copyrighted characters or brand marks.")
COMPOSITION = {
    "background": "Seamless, even, low-contrast texture or atmosphere that works when cut into "
                  "pieces; no focal subject, nothing important near any edge.",
    "side": "Wide horizontal panorama seen from the side. The car's FRONT is at the RIGHT edge: "
            "motion and directional subjects travel or face to the right. Spread interest along "
            "the whole length (it wraps fender, doors and rear quarter); leave calm space for a "
            "wordmark.",
    "hood": "Seen from in front of the car, top of the image is toward the windshield. One bold, "
            "simple, centred hero subject on a background that fills the frame edge to edge.",
    "trunk": "Seen from behind the car, top of the image is toward the roof. Bold centred "
             "subject or emblem; calm area for a short wordmark.",
}


def _closest(aspect: float) -> tuple[int, int]:
    return min(GEN_SIZES, key=lambda s: abs(s[0] / s[1] - aspect))


def plan(model_id: str) -> tuple[list[dict], dict]:
    templates.ensure_template(model_id)
    w, h = models.canvas_size(model_id)
    ctx = compose._Ctx({"model": model_id}, None, [])
    regions = [("background", None)]
    side_groups = compose._select(ctx, "side_all", True)
    if side_groups:
        regions.append(("side", side_groups[0]))
    for name in ("hood", "trunk"):
        g = compose._select(ctx, name, False)
        if g:
            regions.append((name, g[0]))

    assets, layers = [], []
    for name, grp in regions:
        if grp is None:
            ew, eh = w, h
        else:
            rot = ctx.panel(grp[0]).get("upright_rotate", 0)
            ew, eh = compose._span_extent(ctx, grp, rot)
        aspect = ew / eh
        gen = _closest(aspect)
        gen_aspect = gen[0] / gen[1]
        # "cover" crops the generated image to the region's aspect: say exactly what survives.
        if aspect > gen_aspect:
            keep = gen_aspect / aspect
            safe = (f"Only the middle {keep:.0%} of the image HEIGHT survives the crop (about "
                    f"{(1 - keep) / 2:.0%} is cut at top and at bottom): put every important element "
                    "inside that horizontal band; the rest is background only.")
        else:
            keep = aspect / gen_aspect
            safe = (f"Only the middle {keep:.0%} of the image WIDTH survives the crop: put every "
                    "important element inside that vertical band.")
        if name != "background":
            safe += " Panel outlines then trim roughly another 10 % around the edges."
        assets.append({
            "id": name, "file": f"ai_{name}.png", "region_px": [round(ew), round(eh)],
            "aspect": round(aspect, 2), "generate_size": f"{gen[0]}x{gen[1]}",
            "kept_fraction": round(keep, 2),
            "composition": COMPOSITION[name] + " " + safe + " " + NO_TEXT, "prompt": "",
        })
        layer = {"type": "image", "src": f"ai_{name}.png", "fit": "cover"}
        if name == "side":
            layer.update(panel="side_all", fill_panel=True, image_front="right")
        elif name != "background":
            layer.update(panel=name, fill_panel=True)
        layers.append(layer)

    layers += [
        {"type": "text", "text": "WORDMARK", "panel": "side", "span": True, "font": "display",
         "color": "#ffffff", "stroke": {"color": "#000000", "width": 6}, "enabled": False,
         "comment": "Optional: real text goes in text layers (orientation-checked), never in AI images"},
        {"type": "text", "text": "NAME", "panel": "trunk", "font": "display", "color": "#ffffff",
         "stroke": {"color": "#000000", "width": 5}, "enabled": False},
    ]
    spec = {"name": "AI_Wrap", "model": model_id, "base_color": "#101010", "layers": layers}
    return assets, spec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="model id")
    ap.add_argument("--out-dir", type=Path, required=True, help="design folder to write into")
    a = ap.parse_args()
    assets, spec = plan(a.model)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    (a.out_dir / "ai_assets.json").write_text(json.dumps({"model": a.model, "assets": assets}, indent=1))
    design = a.out_dir / "design.json"
    if design.exists():
        print(f"design.json exists, not overwritten: {design}")
    else:
        design.write_text(json.dumps(spec, indent=1))
    for x in assets:
        print(f"{x['id']:10} {x['file']:16} region {x['region_px'][0]}x{x['region_px'][1]} "
              f"(aspect {x['aspect']}) -> generate {x['generate_size']}, keeps {x['kept_fraction']:.0%}")
    print(f"Plan: {a.out_dir / 'ai_assets.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
