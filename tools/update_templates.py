#!/usr/bin/env python3
"""Refresh the bundled Tesla templates in skills/tesla-wrap-designer/assets/templates/
from teslamotors/custom-wraps at the commit pinned in references/models.json.

To pick up a newer upstream commit: update `source_ref` (and add any new models) in
models.json, run this script, re-check references/panel-guide.md against the regenerated
panels_overlay.png files, then run scripts/selftest.py.
"""
import shutil
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "tesla-wrap-designer"
sys.path.insert(0, str(SKILL / "scripts"))

from wrapkit import models, templates  # noqa: E402


def main() -> int:
    for mid in models.model_ids():
        cache = templates.CACHE_DIR / mid
        cache.mkdir(parents=True, exist_ok=True)
        dest = templates.BUNDLED_DIR / mid
        dest.mkdir(parents=True, exist_ok=True)
        for fname in templates.FILES:
            templates._fetch_file(mid, fname, cache / fname,
                                  models.canvas_size(mid) if fname == "template.png" else None)
            shutil.copyfile(cache / fname, dest / fname)
        templates._derive(mid, cache)
        print(f"OK  {mid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
