#!/usr/bin/env python3
"""End-to-end smoke test: every model through fetch, finalize and validate, plus negative tests."""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from wrapkit import finalize, models, naming, templates, validate  # noqa: E402

failures: list[str] = []


def check(cond: bool, label: str) -> None:
    if not cond:
        failures.append(label)
        print(f"  FAIL: {label}")


def failed_ids(report: dict) -> set[str]:
    return {c["id"] for c in report["checks"] if not c["ok"] and c["severity"] == "error"}


def busy_image(size: tuple[int, int], seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    w, h = size
    arr = rng.integers(0, 256, (h, w, 4), dtype=np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    arr[..., 0] = (arr[..., 0] * 0.7 + 90 * np.sin(xx / 17.0) + 90).clip(0, 255)
    arr[..., 3] = 255
    holes = ((xx // 64 + yy // 64) % 3 == 0) | (np.hypot(xx - w / 2, yy - h / 2) < 150)
    arr[holes, 3] = 0
    arr[(xx % 97 < 8) & (yy % 89 < 8), 3] = 128
    return Image.fromarray(arr, "RGBA")


def main() -> int:
    t0 = time.time()
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, m in enumerate(models.list_models()):
            mid = m["id"]
            print(f"[{mid}]")
            try:
                templates.ensure_template(mid)
            except Exception as e:
                check(False, f"{mid}: ensure_template: {e}")
                continue
            panels = templates.load_panels(mid)["panels"]
            check(len(panels) > 0, f"{mid}: panels detected")
            check(templates.load_panel_map(mid).shape == (m["canvas"][1], m["canvas"][0]), f"{mid}: panel map shape")
            img = busy_image(tuple(m["canvas"]), i)
            data, info = finalize.finalize(img, mid)
            path = finalize.write_wrap(data, tmp, f"Selftest {mid}")
            rep = validate.validate_file(path, mid)
            check(rep["ok"], f"{mid}: validate ok ({failed_ids(rep)})")
            check(info["bytes"] <= 1_000_000 and info["ok"], f"{mid}: size {info['bytes']}")
            check(Image.open(path).size == tuple(m["canvas"]), f"{mid}: size preserved")
            rows.append((mid, len(panels), info["bytes"], info["final_mode"], len(info["steps"])))

        mid = "model3"
        w, h = models.canvas_size(mid)
        rep = validate.validate_file(Path(tmp) / "Selftest model3.png", mid)
        check(rep["ok"], "baseline file valid")

        tr = Path(tmp) / "Transparent.png"
        Image.new("RGBA", (w, h), (255, 0, 0, 0)).save(tr)
        check("transparency_any" in failed_ids(validate.validate_file(tr, mid)), "RGBA transparency must fail")

        trns = Path(tmp) / "Trns.png"
        Image.new("P", (w, h), 0).save(trns, transparency=0)
        check("transparency_any" in failed_ids(validate.validate_file(trns, mid)), "tRNS transparency must fail")

        big = Path(tmp) / "Big.png"
        noise = np.random.default_rng(1).integers(0, 256, (h, w, 3), dtype=np.uint8)
        Image.fromarray(noise, "RGB").save(big, compress_level=1)
        check("file_size" in failed_ids(validate.validate_file(big, mid)), "oversized must fail")

        bad = Path(tmp) / "bad@name!.png"
        Image.new("RGB", (w, h), (9, 9, 9)).save(bad)
        check("filename" in failed_ids(validate.validate_file(bad, mid)), "bad filename must fail")
        long_ = Path(tmp) / ("A" * 30 + ".png")
        Image.new("RGB", (w, h), (9, 9, 9)).save(long_)
        check("filename" in failed_ids(validate.validate_file(long_, mid)), "over-long filename must fail")

        wrong = Path(tmp) / "Wrong.png"
        Image.new("RGB", (512, 512), (9, 9, 9)).save(wrong)
        check("dimensions" in failed_ids(validate.validate_file(wrong, mid)), "wrong dims must fail")

        fake = Path(tmp) / "Fake.png"
        fake.write_bytes(b"not a png at all")
        check("png_signature" in failed_ids(validate.validate_file(fake, mid)), "fake PNG must fail")

        check(naming.sanitize("Star Wars: Théme/2024!!") == "Star Wars_ Th_me_2024.png", "sanitize basic")
        s = naming.sanitize("x" * 80)
        check(naming.is_valid(s), "sanitize long")
        check(naming.sanitize("???") == "Wrap.png", "sanitize fallback")

        m = np.zeros((300, 300), dtype=bool)
        m[10:50, 10:200] = True
        m[100:250, 120:130] = True
        m[40:120, 125:128] = True
        t = time.time()
        lab, n = templates._label_uf(np.pad(np.kron(np.random.default_rng(2).random((256, 256)) > 0.4,
                                                    np.ones((4, 4), bool)), 0))
        check(time.time() - t < 10, "union-find fallback speed")
        lab2, n2 = templates._label_uf(m)
        check(n2 == 1, f"union-find connectivity (got {n2})")

    print("\nmodel                      panels     bytes mode ladder-steps")
    for r in rows:
        print(f"{r[0]:26} {r[1]:6} {r[2]:9,} {r[3]:4} {r[4]}")
    print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'ALL PASSED'} ({time.time() - t0:.1f}s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
