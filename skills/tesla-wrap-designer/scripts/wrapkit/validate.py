"""Validate a wrap PNG against Tesla Paint Shop rules."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from .models import canvas_size, limits
from .naming import FILENAME_RE, MAX_CHARS

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _chk(checks: list, cid: str, ok: bool, message: str, value=None, severity: str | None = None) -> None:
    sev = severity or ("info" if ok else "error")
    checks.append({"id": cid, "ok": bool(ok), "severity": sev, "message": message, "value": value})


def _alpha(img: Image.Image) -> np.ndarray | None:
    """Alpha channel (uint8) if the image can carry transparency, else None."""
    if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
        return np.asarray(img.convert("RGBA"))[..., 3]
    return None


def validate_file(path, model_id: str | None) -> dict:
    """Run every check; returns {"ok", "file", "checks": [...]}. ok is False if any error-severity check failed."""
    p = Path(path)
    lim = limits()
    checks: list[dict] = []

    head = b""
    size_bytes = 0
    try:
        size_bytes = p.stat().st_size
        with open(p, "rb") as f:
            head = f.read(8)
    except OSError as e:
        _chk(checks, "png_signature", False, f"Cannot read file: {e}")
        return {"ok": False, "file": str(p), "checks": checks}

    _chk(checks, "png_signature", head == PNG_SIG,
         "Valid PNG signature" if head == PNG_SIG else "File is not a real PNG (bad signature)")

    max_bytes = int(lim["max_bytes"])
    _chk(checks, "file_size", size_bytes <= max_bytes,
         f"{size_bytes:,} bytes (limit {max_bytes:,})", size_bytes)

    name = p.name
    name_ok = bool(FILENAME_RE.match(name)) and len(name) <= MAX_CHARS
    why = []
    if not FILENAME_RE.match(name):
        why.append("allowed characters: A-Z a-z 0-9 _ - space, and .png extension")
    if len(name) > MAX_CHARS:
        why.append(f"{len(name)} chars > {MAX_CHARS}")
    _chk(checks, "filename", name_ok, f"'{name}' OK" if name_ok else f"'{name}' invalid: " + "; ".join(why), name)

    img = None
    if head == PNG_SIG:
        try:
            img = Image.open(p)
            img.load()
        except Exception as e:
            img = None
            _chk(checks, "dimensions", False, f"PNG could not be decoded: {e}")
    if img is None:
        if head != PNG_SIG:
            _chk(checks, "dimensions", False, "Skipped: not a decodable PNG")
        return {"ok": False, "file": str(p), "checks": checks}

    w, h = img.size
    if model_id:
        cw, ch = canvas_size(model_id)
        ok = (w, h) == (cw, ch)
        _chk(checks, "dimensions", ok, f"{w}x{h}" + ("" if ok else f" but model '{model_id}' needs {cw}x{ch}"), [w, h])
    else:
        lo, hi = int(lim["min_side"]), int(lim["max_side"])
        ok = lo <= w <= hi and lo <= h <= hi
        _chk(checks, "dimensions", ok, f"{w}x{h}" + ("" if ok else f" outside {lo}-{hi} px range"), [w, h])

    alpha = _alpha(img)
    n_transparent = int((alpha < 255).sum()) if alpha is not None else 0
    _chk(checks, "transparency_any", n_transparent == 0,
         "No transparent pixels" if n_transparent == 0
         else f"{n_transparent:,} pixels have alpha < 255 (render black on the car)", n_transparent)

    mode = img.mode
    has_alpha_channel = alpha is not None
    _chk(checks, "colour_mode", not has_alpha_channel,
         f"mode {mode}" + (" (alpha/tRNS present; finalize strips it)" if has_alpha_channel else ""),
         mode, severity="info" if not has_alpha_channel else "warn")

    if model_id and img.size == canvas_size(model_id):
        from . import templates
        mask = np.asarray(templates.load_mask(model_id)) > 0
        pmap = templates.load_panel_map(model_id)
        in_mask = int(((alpha < 255) & mask).sum()) if alpha is not None else 0
        _chk(checks, "transparency_in_panels", in_mask == 0,
             "No transparency on the car surface" if in_mask == 0
             else f"{in_mask:,} transparent pixels on paintable area", in_mask)

        rgb = np.asarray(img.convert("RGBA"))[..., :3].astype(np.float32)
        luma = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
        pm = pmap > 0
        total = int(pm.sum())
        dark = int(((luma < 12) & pm).sum())
        frac = dark / total if total else 0.0
        _chk(checks, "black_in_panels", frac <= 0.15,
             f"{frac:.1%} of panel pixels are near-black" + ("" if frac <= 0.15 else " (missing texture?)"),
             round(frac, 4), severity="info" if frac <= 0.15 else "warn")

        flat = []
        rgb_u8 = rgb.astype(np.uint8)
        for pid in np.unique(pmap[pm]):
            px = rgb_u8[pmap == pid]
            if len(px) == 0:
                continue
            keys = (px[:, 0].astype(np.int32) << 16) | (px[:, 1].astype(np.int32) << 8) | px[:, 2]
            if np.unique(keys, return_counts=True)[1].max() / len(keys) > 0.95:
                flat.append(int(pid))
        _chk(checks, "panel_coverage_uniform", not flat,
             "No panel is a flat single colour" if not flat else f"Panels > 95% one flat colour: {flat}",
             flat, severity="info")
    else:
        why = "no model given" if not model_id else "dimensions mismatch"
        for cid in ("transparency_in_panels", "black_in_panels", "panel_coverage_uniform"):
            _chk(checks, cid, True, f"Skipped ({why})", None, severity="info")

    ok_all = all(c["ok"] or c["severity"] != "error" for c in checks)
    return {"ok": ok_all, "file": str(p), "checks": checks}
