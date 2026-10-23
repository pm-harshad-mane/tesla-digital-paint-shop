#!/usr/bin/env python3
"""Convert any image into a Tesla-compliant wrap PNG (opaque, exact canvas size, <= 1 MB)."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image  # noqa: E402

from wrapkit import finalize, naming, templates, validate  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", help="input image (PNG/JPEG/WebP...)")
    ap.add_argument("--model", required=True, help="model id (see fetch_templates.py --list)")
    ap.add_argument("--name", help="output wrap name (default: input file stem)")
    ap.add_argument("--out-dir", default="./wraps")
    ap.add_argument("--fit", choices=["cover", "contain", "stretch"], default="cover")
    ap.add_argument("--base-color", default="#101010", help="flatten/pad colour (default #101010)")
    a = ap.parse_args()

    try:
        templates.ensure_template(a.model)
        img = Image.open(a.input)
        img.load()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    data, info = finalize.finalize(img, a.model, base_color=a.base_color, fit=a.fit)
    fname = naming.sanitize(a.name or Path(a.input).stem)
    path = finalize.write_wrap(data, a.out_dir, fname)
    print(f"Wrote {path} ({info['bytes']:,} bytes, mode {info['final_mode']})")
    for s in info["steps"]:
        print(f"  - {s}")
    report = validate.validate_file(path, a.model)
    for c in report["checks"]:
        print(f"  [{'PASS' if c['ok'] else c['severity'].upper():5}] {c['id']:24} {c['message']}")
    print("RESULT " + json.dumps({"ok": report["ok"], "file": str(path), "bytes": info["bytes"], "steps": info["steps"]}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
