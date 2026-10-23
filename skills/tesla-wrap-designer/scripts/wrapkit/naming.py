"""Wrap filename rules: ^[A-Za-z0-9_\\- ]+\\.png$, at most 30 chars including '.png'."""
from __future__ import annotations

import re

from .models import limits

_LIM = limits()
FILENAME_RE = re.compile(_LIM["filename_regex"])
MAX_CHARS = int(_LIM["filename_max_chars"])
FALLBACK = "Wrap.png"


def is_valid(filename: str) -> bool:
    return bool(FILENAME_RE.match(filename)) and len(filename) <= MAX_CHARS


def sanitize(name: str) -> str:
    """Return a Tesla-safe filename (always ending in .png, <= 30 chars)."""
    name = (name or "").strip()
    if name.lower().endswith(".png"):
        name = name[:-4]
    name = re.sub(r"[^A-Za-z0-9_\- ]", "_", name)
    name = re.sub(r"_{2,}", "_", name)
    name = re.sub(r" {2,}", " ", name)
    name = name.strip(" _-")
    name = name[: MAX_CHARS - 4].strip(" _-")
    if not name:
        return FALLBACK
    out = name + ".png"
    return out if is_valid(out) else FALLBACK
