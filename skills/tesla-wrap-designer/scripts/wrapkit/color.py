"""Colour parsing: hex, rgb()/rgba(), CSS names, tuples."""
from __future__ import annotations

import re

from PIL import ImageColor

_FUNC = re.compile(r"^(rgba?)\((.*)\)$", re.I)


def _chan(v: str) -> float:
    v = v.strip()
    return float(v[:-1]) * 2.55 if v.endswith("%") else float(v)


def parse_color(value, default_alpha: int = 255) -> tuple[int, int, int, int]:
    """Return (r, g, b, a) ints 0-255 from a string or tuple/list."""
    if isinstance(value, (tuple, list)):
        v = [int(round(float(x))) for x in value]
        if len(v) == 3:
            v.append(default_alpha)
        if len(v) != 4:
            raise ValueError(f"Bad colour tuple: {value!r}")
        return tuple(max(0, min(255, x)) for x in v)  # type: ignore[return-value]
    if not isinstance(value, str):
        raise ValueError(f"Unsupported colour value: {value!r}")
    s = value.strip()
    m = _FUNC.match(s)
    if m:
        parts = [p for p in re.split(r"[,\s/]+", m.group(2).strip()) if p]
        if len(parts) not in (3, 4):
            raise ValueError(f"Bad colour: {value!r}")
        rgb = [int(round(_chan(p))) for p in parts[:3]]
        a = default_alpha
        if len(parts) == 4:
            a = parts[3]
            a = int(round(float(a[:-1]) * 2.55)) if a.endswith("%") else int(round(float(a) * 255))
        return tuple(max(0, min(255, x)) for x in (*rgb, a))  # type: ignore[return-value]
    try:
        c = ImageColor.getcolor(s, "RGBA")
    except ValueError as e:
        raise ValueError(f"Unknown colour {value!r} (use #rrggbb, rgb(), or a CSS name)") from e
    if len(s) in (4, 7) and s.startswith("#"):
        return (c[0], c[1], c[2], default_alpha)
    return tuple(c)  # type: ignore[return-value]


def parse_rgb(value) -> tuple[int, int, int]:
    return parse_color(value)[:3]
