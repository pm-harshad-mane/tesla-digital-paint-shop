#!/usr/bin/env python3
"""Report what this environment can do for the skill: Python deps, SVG backend, template
source (bundled / cached / downloadable) and the recommended output directory.
Prints a final `RESULT {json}` line. Exit 1 only if Pillow or numpy is missing."""
import importlib
import json
import os
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Folders that platforms expose to the user for downloads, most specific first.
OUTPUT_DIR_CANDIDATES = ("/mnt/user-data/outputs", "/mnt/outputs")


def _version(mod: str):
    try:
        return getattr(importlib.import_module(mod), "__version__", "installed")
    except ImportError:
        return None


def _svg_backend() -> str:
    forced = os.environ.get("TESLA_WRAP_SVG")
    if forced:
        return f"{forced} (forced by TESLA_WRAP_SVG)"
    if _version("cairosvg"):
        return "cairosvg"
    try:
        importlib.import_module("wrapkit.minisvg")
        return "built-in (minisvg)"
    except ImportError:
        pass
    from wrapkit import svgrender
    return "chrome" if svgrender._find_chrome() else "none - avoid svg layers"


def _templates() -> dict:
    from wrapkit import models, templates
    ids = models.model_ids()
    bundled = [m for m in ids if (templates.BUNDLED_DIR / m / "template.png").exists()]
    cached = [m for m in ids if (templates.CACHE_DIR / m / "template.png").exists()]
    if len(bundled) == len(ids):
        source = "bundled (offline ready)"
    else:
        try:
            templates._download(models.raw_url(ids[0], "template.png"))
            source = "download OK"
        except templates.TemplateError:
            source = "download BLOCKED - ask the user to attach template.png (see SKILL.md step 2)"
    return {"source": source, "bundled": len(bundled), "cached": len(cached), "models": len(ids),
            "cache_dir": str(templates.CACHE_DIR)}


def _out_dir() -> str:
    for d in OUTPUT_DIR_CANDIDATES:
        if os.path.isdir(d) and os.access(d, os.W_OK):
            return d
    return str(Path.cwd() / "wraps")


def main() -> int:
    info = {"python": platform.python_version(), "pillow": _version("PIL"), "numpy": _version("numpy"),
            "scipy": _version("scipy")}
    ok = bool(info["pillow"] and info["numpy"])
    if ok:
        info["svg_backend"] = _svg_backend()
        info["templates"] = _templates()
    info["out_dir"] = _out_dir()

    print(f"Python {info['python']} | Pillow {info['pillow'] or 'MISSING'} | numpy {info['numpy'] or 'MISSING'}"
          f" | scipy {info['scipy'] or '-'}")
    if not ok:
        print("Install dependencies: pip install -r requirements.txt (Pillow, numpy)")
    else:
        t = info["templates"]
        print(f"SVG backend: {info['svg_backend']}")
        print(f"Templates: {t['source']} | bundled {t['bundled']}/{t['models']} | cached {t['cached']}"
              f" | cache dir {t['cache_dir']}")
    print(f"Output dir: {info['out_dir']}")
    print("RESULT " + json.dumps(info))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
