#!/usr/bin/env python3
"""Fetch Tesla wrap templates into the local cache and derive masks/panels."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wrapkit import models, templates  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", action="append", default=[], metavar="ID", help="model id (repeatable)")
    ap.add_argument("--all", action="store_true", help="fetch every model")
    ap.add_argument("--refresh", action="store_true", help="re-download even if cached")
    ap.add_argument("--list", action="store_true", help="print the model table and exit")
    ap.add_argument("--template", type=Path, help="use this local template.png instead of downloading "
                    "(requires exactly one --model)")
    ap.add_argument("--vehicle-image", type=Path, help="optional local vehicle_image.png (with --template)")
    a = ap.parse_args()

    if a.list:
        print(f"{'id':26} {'name':11} {'years':10} {'canvas':10} variant")
        for m in models.list_models():
            print(f"{m['id']:26} {m['name']:11} {m['years']:10} {m['canvas'][0]}x{m['canvas'][1]:<5} {m['variant']}")
        return 0

    ids = models.model_ids() if a.all else a.model
    if not ids:
        ap.error("give --model ID (repeatable), --all, or --list")
    if a.template:
        if len(ids) != 1:
            ap.error("--template needs exactly one --model")
        try:
            templates.import_template(ids[0], a.template, a.vehicle_image)
        except (KeyError, OSError, templates.TemplateError) as e:
            print(f"FAIL {ids[0]}: {e}", file=sys.stderr)
            return 1
    rc = 0
    for mid in ids:
        try:
            d = templates.ensure_template(mid, refresh=a.refresh)
            n = len(templates.load_panels(mid)["panels"])
            print(f"OK   {mid:26} {n:3d} panels  {d}")
            print(f"     overlay: {d / 'panels_overlay.png'}")
        except (KeyError, templates.TemplateError) as e:
            print(f"FAIL {mid}: {e}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
