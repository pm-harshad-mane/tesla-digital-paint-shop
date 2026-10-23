#!/usr/bin/env python3
"""AI image mode: generate one artwork image through an OpenAI-compatible Images API.

Only for AI image mode, after the user explicitly enabled it for this request. Prefer the
host's own image-generation tool when the platform has one; use this script when the user
has configured an API key instead.

  OPENAI_API_KEY=... python3 generate_image.py --prompt "..." --size 1536x1024 --out ai_side.png

Configuration (environment only; the key is never printed or written anywhere):
  OPENAI_API_KEY             required
  OPENAI_BASE_URL            optional, default https://api.openai.com/v1 (any compatible endpoint)
  TESLA_WRAP_IMAGE_MODEL     optional, default gpt-image-2
The prompt is sent to that provider: never include personal data the user did not approve.
"""
import argparse
import base64
import io
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image  # noqa: E402

from wrapkit.templates import _ssl_contexts  # noqa: E402

DEFAULT_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-image-2"
SIZES = ("1024x1024", "1536x1024", "1024x1536")
MAX_PROMPT = 4000


def _endpoint(base: str) -> str:
    u = urlparse(base)
    if u.scheme != "https" and u.hostname not in ("localhost", "127.0.0.1"):
        sys.exit("ERROR: OPENAI_BASE_URL must use https (http is allowed only for localhost)")
    return base.rstrip("/") + "/images/generations"


def _post(url: str, body: dict, key: str) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    contexts = _ssl_contexts() if url.startswith("https") else [None]
    last = None
    for ctx in contexts:
        try:
            with urllib.request.urlopen(req, timeout=300, context=ctx) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            sys.exit(f"ERROR: image API returned HTTP {e.code}: {detail}")
        except urllib.error.URLError as e:
            last = e
            if "CERTIFICATE" not in str(e.reason).upper():
                break
    sys.exit(f"ERROR: could not reach the image API: {last}")


def _image_bytes(resp: dict) -> bytes:
    try:
        item = resp["data"][0]
    except (KeyError, IndexError, TypeError):
        sys.exit("ERROR: unexpected API response (no data[0])")
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        u = item["url"]
        if not u.startswith("https://"):
            sys.exit("ERROR: refusing to download a non-https image URL")
        with urllib.request.urlopen(u, timeout=120, context=_ssl_contexts()[0]) as r:
            return r.read()
    sys.exit("ERROR: API response has neither b64_json nor url")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt", required=True, help="image prompt (no text/logos/personal data)")
    ap.add_argument("--size", default="1536x1024", choices=SIZES)
    ap.add_argument("--quality", default="high", help="provider quality setting (default high)")
    ap.add_argument("--out", type=Path, required=True, help="output PNG path")
    ap.add_argument("--dry-run", action="store_true", help="print the request (without the key) and exit")
    a = ap.parse_args()

    if len(a.prompt) > MAX_PROMPT:
        sys.exit(f"ERROR: prompt is {len(a.prompt)} chars; keep it under {MAX_PROMPT}")
    model = os.environ.get("TESLA_WRAP_IMAGE_MODEL", DEFAULT_MODEL)
    url = _endpoint(os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE))
    body = {"model": model, "prompt": a.prompt, "size": a.size, "n": 1, "quality": a.quality}
    if a.dry_run:
        print(f"POST {url}\n{json.dumps(body, indent=1)}")
        return 0
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("ERROR: OPENAI_API_KEY is not set. Ask the user to set it in their environment "
                 "(never paste keys into the chat), use the platform's own image tool, or have "
                 "the user generate the images and attach them.")

    data = _image_bytes(_post(url, body, key))
    img = Image.open(io.BytesIO(data))
    img.load()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(a.out, "PNG")
    print(f"Saved {a.out} ({img.width}x{img.height}) from {model}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
