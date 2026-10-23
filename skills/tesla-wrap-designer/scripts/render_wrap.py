#!/usr/bin/env python3
"""Render a JSON design spec into a Tesla-compliant wrap PNG (compose -> finalize -> validate)."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image  # noqa: E402

import make_check  # noqa: E402
from wrapkit import compose, finalize, naming, orientation, templates, validate  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("spec", help="design spec JSON file")
    ap.add_argument("--model", help="override the spec's model id")
    ap.add_argument("--out-dir", default="./wraps", help="output folder (default ./wraps)")
    ap.add_argument("--name", help="output name (default: spec name); sanitised to Tesla rules")
    ap.add_argument("--no-validate", action="store_true", help="skip validation")
    ap.add_argument("--preview", action="store_true", help="also build an HTML preview via make_preview.py")
    ap.add_argument("--debug", action="store_true", help="also save the un-finalized composite as <stem>_composite.png")
    a = ap.parse_args()

    spec_path = Path(a.spec).resolve()
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot read spec: {e}", file=sys.stderr)
        return 2
    if a.model:
        spec["model"] = a.model
    model = spec.get("model")
    if not model:
        print("ERROR: spec has no 'model' (pass --model)", file=sys.stderr)
        return 2

    t0 = time.time()
    try:
        templates.ensure_template(model)
        img = compose.render_spec(spec, spec_path.parent)
    except (KeyError, ValueError, FileNotFoundError, RuntimeError, templates.TemplateError) as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    warnings = list(compose.LAST_WARNINGS)
    placements = list(compose.LAST_PLACEMENTS)
    t_render = time.time() - t0

    base = spec.get("base_color", "#101010")
    data, info = finalize.finalize(img, model, base_color=_base(base))
    filename = naming.sanitize(a.name or spec.get("name") or spec_path.stem)
    out_dir = Path(a.out_dir)
    path = finalize.write_wrap(data, out_dir, filename)
    stem = path.stem
    # Review artifacts live apart from the wraps so copying out_dir to a USB "Wraps" folder is safe.
    review = out_dir / "review"
    review.mkdir(parents=True, exist_ok=True)
    if a.debug:
        img.save(review / f"{stem}_composite.png")
    check = review / f"{stem}_check.png"
    chk = make_check.build(path, model)
    chk.resize((chk.width // 2, chk.height // 2), Image.LANCZOS).save(check)
    print(f"Check image: {check}")

    panels = {p["id"]: p for p in templates.load_panels(model)["panels"]}
    orient = orientation.check(placements, panels)
    orient_img = review / f"{stem}_orientation.png"
    sheet = orientation.reads_on_car_sheet(Image.open(path), orient)
    if sheet is not None:
        sheet.save(orient_img)
        print(f"Orientation sheet (elements as they appear on the car): {orient_img}")

    print(f"Rendered {path.name} for {model} in {t_render:.1f}s -> {path}")
    print(f"Size: {info['bytes']:,} bytes ({info['final_mode']}); " + "; ".join(info["steps"]))
    for w in warnings:
        print(f"WARNING: {w}")

    ok = info["ok"]
    for r in orient:
        mark = "PASS" if r["ok"] else ("FAIL" if r["severity"] == "error" else "WARN")
        print(f"  [{mark}] text_orientation: {r['message']}")
    if any(not r["ok"] and r["severity"] == "error" for r in orient):
        ok = False
        print("Orientation: FAILED - fix `rotate`/placement so text reads upright on the car")
    if not a.no_validate:
        rep = validate.validate_file(path, model)
        ok = ok and rep["ok"]
        for c in rep["checks"]:
            mark = "PASS" if c["ok"] else ("FAIL" if c["severity"] == "error" else "WARN")
            print(f"  [{mark}] {c['id']}: {c['message']}")
        print("Validation:", "OK" if rep["ok"] else "FAILED")

    if a.preview:
        mp = Path(__file__).resolve().parent / "make_preview.py"
        if mp.exists():
            prev = review / f"{stem}_preview.html"
            r = subprocess.run([sys.executable, str(mp), "--model", model, str(path), "-o", str(prev)],
                               capture_output=True, text=True)
            if r.returncode == 0:
                print(f"Preview: {prev}")
            else:
                print(f"WARNING: preview failed: {r.stderr.strip() or r.stdout.strip()}")
        else:
            print("WARNING: make_preview.py not found; skipped preview")

    print("RESULT " + json.dumps({"path": str(path), "bytes": info["bytes"], "ok": bool(ok), "model": model,
                                   "check": str(check),
                                   "orientation": str(orient_img) if sheet is not None else None,
                                   "orientation_errors": sum(1 for r in orient if not r["ok"] and r["severity"] == "error"),
                                   "warnings": warnings}))
    return 0 if ok else 1


def _base(c):
    from wrapkit.color import parse_color
    return parse_color(c)[:3]


if __name__ == "__main__":
    sys.exit(main())
