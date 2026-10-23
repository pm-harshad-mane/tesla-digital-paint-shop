#!/usr/bin/env python3
"""Build a self-contained HTML preview of one or more Tesla wraps.

Usage: make_preview.py --model ID wrap.png [more.png ...] -o out.html
Embeds the viewer, the model template, the vehicle reference image and the wraps
(all as base64 data URLs) so the file works offline via file://.
"""
import argparse
import base64
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SKILL = HERE.parent
VIEWER = SKILL / "assets" / "viewer" / "wrap-viewer.html"
MODELS_JSON = SKILL / "references" / "models.json"
MAX_WRAPS = 10
WARN_BYTES = 25 * 1024 * 1024


def data_url(b: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(b).decode("ascii")


def template_dir(model_id: str) -> Path:
    from wrapkit import templates
    try:
        return Path(templates.ensure_template(model_id))
    except templates.TemplateError as e:
        sys.exit(f"error: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="model id from references/models.json")
    ap.add_argument("wraps", nargs="+", help="wrap PNG file(s), max 10")
    ap.add_argument("-o", "--out", required=True, help="output .html path")
    a = ap.parse_args()

    reg = json.loads(MODELS_JSON.read_text())
    ids = [m["id"] for m in reg["models"]]
    if a.model not in ids:
        sys.exit(f"error: unknown model '{a.model}'. Known: {', '.join(ids)}")
    if len(a.wraps) > MAX_WRAPS:
        sys.exit(f"error: {len(a.wraps)} wraps given; maximum is {MAX_WRAPS}")
    for w in a.wraps:
        if not os.path.isfile(w):
            sys.exit(f"error: file not found: {w}")

    d = template_dir(a.model)
    preload = {
        "model": a.model,
        "models": reg["models"],
        "limits": reg["limits"],
        "template": data_url((d / "template.png").read_bytes()),
        "vehicle_image": data_url((d / "vehicle_image.png").read_bytes()) if (d / "vehicle_image.png").exists() else None,
        "wraps": [],
    }
    for w in a.wraps:
        b = Path(w).read_bytes()
        preload["wraps"].append({"name": os.path.basename(w), "bytes": len(b), "data": data_url(b)})

    payload = json.dumps(preload, separators=(",", ":")).replace("</", "<\\/")
    html = VIEWER.read_text(encoding="utf-8")
    tag = "<script>window.__WRAP_PRELOAD__ = " + payload + ";</script>\n"
    i = html.find("</head>")
    if i < 0:
        sys.exit("error: viewer has no </head>")
    html = html[:i] + tag + html[i:]

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    size = out.stat().st_size
    if size > WARN_BYTES:
        print(f"warning: output is {size/1048576:.1f} MB (> 25 MB); browsers may be slow", file=sys.stderr)
    print(str(out.resolve()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
