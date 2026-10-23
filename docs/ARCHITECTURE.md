# Tesla Digital Paint Shop — Architecture & Contracts

The deliverable is a portable Agent Skill at `skills/tesla-wrap-designer/` that turns a
theme idea ("Star Wars theme", "Happy birthday") into a Tesla Paint Shop wrap PNG that
passes Tesla's spec (https://github.com/teslamotors/custom-wraps), plus an HTML viewer to
validate it before upload.

## Hard rules (from Tesla spec + field experience)

| Rule | Value | Enforced by |
|---|---|---|
| Format | PNG (real PNG signature) | `validate.py` |
| Dimensions | Must equal the model's template canvas (1024×1024; Cybertruck 1024×768). Tesla allows 512–1024 but template size maps 1:1 to UVs | `finalize.py`, `validate.py` |
| File size | ≤ 1,000,000 bytes (we treat "1 MB" conservatively) | `finalize.py` compression ladder |
| Transparency | **Zero** transparent pixels. Output is saved as RGB (no alpha channel) or palette without tRNS. Transparent areas render **black** on the car | `finalize.py`, `validate.py` |
| Filename | `^[A-Za-z0-9_\- ]+\.png$`, total length incl. `.png` ≤ 30 | `wrapkit.naming` |
| Count | ≤ 10 wraps per USB `Wraps/` folder / per mobile upload | SKILL.md guidance |

Tesla's templates (pinned commit `references/models.json → source_ref`) are bundled in
`assets/templates/<model_id>/` and refreshed with `tools/update_templates.py`. Derived files
(mask, panels) go to a writable cache (`$TESLA_WRAP_CACHE` → `<skill>/.cache/templates` →
`~/.cache/tesla-wrap-designer` → temp dir). Fallbacks if a bundled file is missing: download
from GitHub, or import a user-supplied file with `fetch_templates.py --model ID --template FILE`.

## Layout

```
skills/tesla-wrap-designer/      # self-contained; zipped by tools/build_skill.py
  SKILL.md                     # workflow Claude follows (intake → design → render → validate → preview)
  requirements.txt             # Pillow, numpy (only hard deps)
  references/
    models.json                # model registry (ids, canvas, identification hints, limits)
    spec-rules.md              # the rules above, expanded
    intake-questions.md        # question script for model/year/trim/theme/refs
    design-spec.md             # JSON design-spec schema (layers)
    design-playbook.md         # theme recipes, panel-orientation tips, IP guidance
  scripts/
    wrapkit/                   # importable library (Pillow + numpy only; scipy optional)
      __init__.py
      models.py                # load models.json, lookup, canvas size
      templates.py             # fetch + cache template, derive mask & panels
      naming.py                # filename sanitizing / validation
      color.py                 # parse "#rgb", "#rrggbb", "#rrggbbaa", "rgb()", named colors
      fonts.py                 # resolve font aliases to system TTFs (macOS/Linux/Windows) w/ fallback
      motifs.py                # procedural generators (return RGBA numpy/PIL images of canvas size)
      compose.py               # design-spec → RGBA canvas (layer engine, blends, clips)
      svgrender.py             # optional SVG → PNG (cairosvg if installed, else headless Chrome)
      finalize.py              # flatten → opaque RGB, size to canvas, compress ≤ 1 MB
      validate.py              # all checks, returns report dict
    fetch_templates.py         # CLI
    render_wrap.py             # CLI: spec.json → final PNG (+ validation report)
    finalize_wrap.py           # CLI: any image (user art) → compliant PNG for a model
    validate_wrap.py           # CLI
    make_preview.py            # CLI: wrap(s) → self-contained preview HTML
    make_check.py              # CLI: art-on-template review image (seams + panel ids)
    selftest.py                # end-to-end smoke test over all models
  assets/
    viewer/wrap-viewer.html    # standalone validator/visualizer (no CDN, works offline + file://)
    examples/*.json            # example design specs (birthday, space-saga-inspired, cartoon-sky-inspired)
```

All CLIs: `python3 scripts/<cli>.py --help`, exit code 0 on success, non-zero on failure, and
print a final machine-readable JSON line prefixed with `RESULT ` where useful.

## Contract: `wrapkit.templates`

```python
CACHE_DIR: Path  # first writable cache location (see above)

def ensure_template(model_id: str, refresh: bool = False) -> Path:
    """Download template.png and vehicle_image.png for model_id (pinned ref) into
    CACHE_DIR/<model_id>/ if missing, then derive artifacts (idempotent). Returns the dir.
    Derived artifacts:
      template.png        original
      vehicle_image.png   original
      mask.png            L mode, 255 where template alpha > 0 (paintable / car surface)
      panels.json         {"canvas":[w,h], "panels":[{"id":int,"bbox":[x0,y0,x1,y1],
                            "area":int,"centroid":[cx,cy],"angle_deg":float,
                            "long_axis":"horizontal"|"vertical",
                            "region":"front"|"rear"|"side"|"pillar",
                            "upright_rotate":deg CCW}...], "schema":2}  sorted by area desc,
                            ids start at 1; tiny components (<0.05% of canvas) dropped.
      panels.png          L/I image with panel id per pixel (0 = none); 8-bit ok if <255 panels
      panels_overlay.png  RGB debug image: template on dark bg, each panel tinted + its id
                          drawn at centroid in large text — Claude views this to choose placements
    Panels = connected components (4-connectivity) of pixels that are opaque (alpha>=128) and
    light (luma >= 160); dark outline pixels separate panels."""

def load_mask(model_id) -> PIL.Image  # L
def load_panels(model_id) -> dict
def load_panel_map(model_id) -> numpy.ndarray  # int labels, shape (h, w)
```

## Contract: design spec (input to `compose.render_spec`)

```jsonc
{
  "name": "Birthday_Bash",            // used for default filename
  "model": "model3-2024-base",
  "seed": 42,                         // deterministic procedural art
  "base_color": "#101020",            // opaque floor under everything; also flatten color
  "layers": [ { "type": "...", ...common, ...type-specific } ]
}
```

Common layer keys (all optional): `opacity` (0–1, default 1), `blend`
(`normal|multiply|screen|overlay|add|soft_light`, default normal), `clip`
(`"all"` default | `"panels"` (mask.png) | `{"panels":[3,7]}` → only those panel ids, each dilated
by `clip_bleed` px default 6), `enabled` (bool).

Layer types:

| type | keys |
|---|---|
| `solid` | `color` |
| `gradient` | `kind: linear|radial|conic`, `stops: [[color, pos0..1], ...]`, `angle` (deg, linear), `center: [x,y]` (px), `radius` (px) |
| `noise` | `kind: clouds|nebula|marble|camo`, `colors: [..]`, `scale` (px feature size), `octaves`, `contrast` |
| `pattern` | `kind:` one of `stars, starfield, dots, halftone, stripes, checker, hex, confetti, bokeh, balloons, hearts, sparkles, rays, carbon, grid, waves, lightspeed, clouds_cartoon, polka`; `colors`, `density`, `size`, `angle`, plus kind-specific params documented in `design-spec.md` |
| `shape` | `kind: rect|ellipse|polygon|star|line|ring`, geometry (`box:[x,y,w,h]`, `points`, `center`, `radius`, `points_n`, `inner_ratio`, `width`), `fill`, `stroke:{color,width}`, `rotate` |
| `text` | `text`, `font` (alias `sans|sans-bold|serif|serif-bold|mono|display|rounded` or TTF path), `size` (px) or `fit_box:[x,y,w,h]` (auto-size), `color`, `stroke:{color,width}`, `shadow:{color,offset:[dx,dy],blur}`, `position:[x,y]` + `anchor` (PIL anchors, default `mm`), or `panel: id` (centred in panel bbox, auto-fit to 80% of panel long axis), `rotate` (deg CCW), `letter_spacing` |
| `image` | `src` (path), `fit: cover|contain|stretch|tile|none`, `box:[x,y,w,h]` or `panel: id`, `rotate`, `mask: none|circle|rounded|ellipse`, `feather` (px), `remove_bg` (bool: drop near-uniform border colour via flood), `tint` |
| `svg` | `src` path or `inline` SVG markup, `box` (default full canvas) — rasterised via `svgrender` |

Coordinates are pixels in template canvas space unless the value is a float string with `%`
(e.g. `"50%"`), which is relative to canvas width (x, w) / height (y, h).

```python
def render_spec(spec: dict, spec_dir: Path) -> PIL.Image.Image  # RGBA, template canvas size
```

## Contract: `wrapkit.finalize`

```python
def finalize(img: PIL.Image.Image, model_id: str, base_color=(16,16,16),
             fit="cover", max_bytes=1_000_000) -> tuple[bytes, dict]:
    """1) resize/crop to template canvas (fit cover|contain|stretch; contain pads with base_color)
       2) composite over opaque base_color → RGB (no alpha anywhere)
       3) encode PNG optimize=True, compress_level=9; if > max_bytes walk ladder:
          RGB posterize 7 → 6 → 5 bits (no banding), then quantize 256 colours (Floyd–Steinberg, MEDIANCUT/FASTOCTREE) → 192 → 128 → 64,
          then mild denoise (GaussianBlur 0.6) + 256 → 128; never change dimensions.
       Returns (png_bytes, info{steps, final_mode, bytes})."""
def write_wrap(png_bytes, out_dir, filename) -> Path   # validates/sanitises name first
```

## Contract: `wrapkit.validate`

```python
def validate_file(path, model_id: str | None) -> dict
# {"ok": bool, "file": str, "checks":[{"id","ok","severity":"error|warn|info","message","value"}]}
```
Checks: `png_signature`, `dimensions` (== template canvas if model given, else 512–1024 range),
`file_size`, `filename`, `transparency_any` (error if any pixel alpha < 255, incl. tRNS),
`transparency_in_panels` (count within mask), `black_in_panels` (warn if > 15% of panel pixels
are near-black luma < 12 — looks like a missing texture), `panel_coverage_uniform` (warn if any
panel > 95% one flat colour — informational), `colour_mode`.

## Contract: viewer + `make_preview.py`

`assets/viewer/wrap-viewer.html` is a single self-contained file (inline CSS/JS, no network
except optional template fetch from raw.githubusercontent.com, which serves CORS `*`).
`make_preview.py --model ID wrap.png [more.png] -o out.html` copies the viewer and injects,
before `</head>`:

```html
<script>window.__WRAP_PRELOAD__ = {
  "model": "model3", "models": [...models.json models...], "limits": {...},
  "template": "data:image/png;base64,...", "vehicle_image": "data:image/png;base64,...",
  "wraps": [{"name":"Birthday_Bash.png","bytes":812345,"data":"data:image/png;base64,..."}]
};</script>
```
Without preload the viewer works standalone: pick model (fetches template from GitHub raw at
pinned ref, or user drops a template file), then drag-drop wrap PNGs.

## Orientation (`upright_rotate`)

Derived from Tesla's own example wraps (e.g. "Ani"): on 1024² layouts the front is at the top;
hood/front art is rotated 180°, left-column side panels +90°, right-column −90°, rear 0°.
Cybertruck: top side band 180°, bottom 0°, front (left) −90°, rear (right) +90°.
`compose` applies it to `panel:`-placed text/images/SVG unless `rotate` is given.

## Output layout

`render_wrap.py --out-dir wraps` writes only wrap PNGs into `wraps/`; review artifacts
(`<stem>_check.png`, `<stem>_preview.html`, `--debug` composite) go to `wraps/review/` so the
folder can be copied to a USB `Wraps/` directory without uploading review images as wraps.

## Portability

The skill folder must work unmodified on Claude.ai, the Claude API (no network, read-only
skill dir), Claude Code / Agent SDK, ChatGPT (Skills; outputs in `/mnt/data`), OpenAI Codex
(`~/.agents/skills`), and other Agent Skills hosts. Rules:
- Only Pillow + numpy at runtime; scipy, cairosvg and Chrome are optional accelerators.
- Never assume the skill dir is writable (cache falls back to home or temp).
- Never assume network (templates are bundled).
- SKILL.md names no host-specific tools; `env_check.py` discovers capabilities and the
  output directory (e.g. `/mnt/user-data/outputs` when present).
- SVG: cairosvg → built-in `minisvg` → Chrome fallback (`TESLA_WRAP_SVG` to force).
- The repo root is also a Claude Code plugin + marketplace (`.claude-plugin/`).
