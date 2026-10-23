#!/usr/bin/env python3
"""Validate wrap PNGs against Tesla Paint Shop rules. Exit 1 if any file has an error."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wrapkit import templates, validate  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="+", help="wrap PNG file(s)")
    ap.add_argument("--model", help="model id (enables canvas and panel checks)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    a = ap.parse_args()

    if a.model:
        try:
            templates.ensure_template(a.model)
        except (KeyError, templates.TemplateError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2

    reports = [validate.validate_file(f, a.model) for f in a.files]
    if a.json:
        print(json.dumps(reports if len(reports) > 1 else reports[0], indent=2))
    else:
        for r in reports:
            print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['file']}")
            for c in r["checks"]:
                tag = "ok" if c["ok"] else c["severity"]
                print(f"   {tag:5} {c['id']:24} {c['message']}")
    return 0 if all(r["ok"] for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
