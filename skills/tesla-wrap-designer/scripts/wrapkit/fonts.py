"""Font alias resolution across macOS / Linux / Windows."""
from __future__ import annotations

import os
from functools import lru_cache

from PIL import ImageFont

_MAC = ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts",
        os.path.expanduser("~/Library/Fonts")]
_LIN = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation",
        "/usr/share/fonts/truetype/noto", "/usr/share/fonts/truetype", "/usr/share/fonts/TTF",
        "/usr/share/fonts/dejavu", "/usr/share/fonts/liberation", "/usr/share/fonts/opentype/noto"]
_WIN = ["C:/Windows/Fonts"]
DIRS = _MAC + _LIN + _WIN

ALIASES: dict[str, list[str]] = {
    "sans": ["Helvetica.ttc", "Arial.ttf", "arial.ttf", "LiberationSans-Regular.ttf",
             "DejaVuSans.ttf", "NotoSans-Regular.ttf"],
    "sans-bold": ["Arial Bold.ttf", "arialbd.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf",
                  "NotoSans-Bold.ttf", "Helvetica.ttc"],
    "serif": ["Georgia.ttf", "georgia.ttf", "Times New Roman.ttf", "times.ttf",
              "LiberationSerif-Regular.ttf", "DejaVuSerif.ttf", "NotoSerif-Regular.ttf"],
    "serif-bold": ["Georgia Bold.ttf", "georgiab.ttf", "Times New Roman Bold.ttf", "timesbd.ttf",
                   "LiberationSerif-Bold.ttf", "DejaVuSerif-Bold.ttf", "NotoSerif-Bold.ttf"],
    "mono": ["Menlo.ttc", "Courier New.ttf", "cour.ttf", "LiberationMono-Regular.ttf",
             "DejaVuSansMono.ttf", "NotoSansMono-Regular.ttf"],
    "display": ["Impact.ttf", "impact.ttf", "Arial Black.ttf", "ariblk.ttf", "Avenir Next Condensed.ttc",
                "HelveticaNeue.ttc", "LiberationSansNarrow-Bold.ttf", "DejaVuSansCondensed-Bold.ttf",
                "DejaVuSans-Bold.ttf"],
    "rounded": ["Arial Rounded Bold.ttf", "ARLRDBD.TTF", "Chalkboard.ttc", "Comic Sans MS Bold.ttf",
                "comicbd.ttf", "Verdana Bold.ttf", "verdanab.ttf", "DejaVuSans-Bold.ttf",
                "NotoSans-Bold.ttf"],
}
_BOLD_INDEX = {"Helvetica.ttc": 1, "Menlo.ttc": 0}


def _find(name: str) -> str | None:
    for d in DIRS:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def _load(path: str, size: int, index: int = 0):
    try:
        return ImageFont.truetype(path, size, index=index)
    except Exception:
        return None


@lru_cache(maxsize=256)
def _resolve(key: str, size: int):
    if key in ALIASES:
        for name in ALIASES[key]:
            p = _find(name)
            if not p:
                continue
            idx = 1 if (key.endswith("bold") and name == "Helvetica.ttc") else 0
            f = _load(p, size, idx)
            if f:
                return f
    else:
        p = os.path.expanduser(key)
        if os.path.isfile(p):
            f = _load(p, size)
            if f:
                return f
        else:
            p2 = _find(key)
            if p2 and (f := _load(p2, size)):
                return f
            raise FileNotFoundError(f"Font not found: {key!r} (aliases: {', '.join(ALIASES)})")
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def resolve_font(alias_or_path: str = "sans", size: int = 48):
    """Return a PIL font for an alias or TTF/TTC path; falls back to PIL default."""
    return _resolve(str(alias_or_path or "sans"), max(1, int(round(size))))


def list_available() -> dict[str, str]:
    """Map each alias to the file it resolves to (or 'PIL default')."""
    out = {}
    for key, names in ALIASES.items():
        out[key] = next((p for n in names if (p := _find(n))), "PIL default")
    return out


if __name__ == "__main__":
    for k, v in list_available().items():
        print(f"{k:11s} {v}")
