---
name: tesla-wrap-designer
description: Design Tesla Paint Shop custom wraps (car skins/liveries) from a theme idea or reference images. Asks model and year, renders a spec-valid PNG, validates it, and builds an HTML preview.
---

# Tesla Wrap Designer

Use this skill whenever someone wants a custom wrap / skin / livery for the Tesla Paint Shop
(Toybox → Paint Shop → Wraps), e.g. "Star Wars theme", "Simpsons cartoon theme",
"Happy birthday", or wants an existing wrap PNG checked or fixed. Supports Model 3, Model Y,
Model Y L, Model S, Model X and Cybertruck. Needs Python 3.10+ with Pillow and numpy;
network is optional.

`SKILL_DIR` below means the directory containing this SKILL.md. Run every script as
`python3 SKILL_DIR/scripts/<name>.py …`; they work from any working directory and never write
inside `SKILL_DIR` unless it is writable.

**Non-negotiables** (details in `references/spec-rules.md`):
PNG · exact template canvas (1024×1024; **Cybertruck 1024×768**) · ≤ 1,000,000 bytes ·
**zero transparent pixels** (they render black on the car) · filename `[A-Za-z0-9_- ]`,
≤ 30 chars incl `.png`. Never hand over a file that has not passed validation.

## Workflow

### 0. Environment check (once per session)
```bash
python3 SKILL_DIR/scripts/env_check.py
```
It reports Python/Pillow/numpy, the SVG backend, where templates come from (bundled, cached,
or downloadable) and the recommended output directory (`OUT_DIR` below — the platform's
user-visible outputs folder if there is one, else `./wraps`). If Pillow/numpy are missing
and package installs are allowed: `pip install -r SKILL_DIR/requirements.txt`.

### 1. Intake — ask before drawing
Follow `references/intake-questions.md`. Resolve **one exact template id** from
`references/models.json` before any rendering. Ask with whatever the platform offers (a
structured question tool if available, otherwise a short numbered list in one message);
skip anything already answered and batch the rest into one or two rounds. Capture: model id,
style direction, exact text, palette, reference images (+ place vs inspire, and placement),
number of variants. Franchise themes get the homage approach in
`references/design-playbook.md` (original art, no copyrighted characters/logos) — say it once.

### 2. Get and study the template
```bash
python3 SKILL_DIR/scripts/fetch_templates.py --model <id>
```
Templates for every model are bundled with the skill. (Only if a bundled file is missing does
it download from Tesla's GitHub; if that is blocked too, ask the user to download `template.png` for
their model from `https://github.com/teslamotors/custom-wraps/tree/master/<id>` and attach
it, then run `fetch_templates.py --model <id> --template <attached file>`.)
The command prints the template folder. **View** its `panels_overlay.png` and read
`panels.json` (panel ids by area, bbox, `region`, `upright_rotate`). Hero panels per model:
`references/panel-guide.md`.

### 3. Write the design spec
Create `OUT_DIR/<Name>/design.json` (copy user images beside it).
Schema: `references/design-spec.md` · starting points: `assets/examples/*.json` ·
composition rules and theme recipes: `references/design-playbook.md`.
- Layers 1–2 cover the whole canvas (gradient / noise / pattern).
- Heroes (text, emblems, user photos) inside single large panels, mirrored on both sides;
  prefer region selectors (`"panel": "front"`, `"side"`) over raw coordinates.
- One text layer per door panel — never `span` text across the door seam.
- Illustrations: original inline SVG in an `svg` layer (works everywhere; see backends below).

### 4. Render, validate, inspect
```bash
python3 SKILL_DIR/scripts/render_wrap.py OUT_DIR/<Name>/design.json --out-dir OUT_DIR --preview
```
Composes → finalizes (flatten to opaque RGB, compress ≤ 1 MB) → validates → writes
`OUT_DIR/<File>.png` and review files in `OUT_DIR/review/` (`<stem>_check.png`,
`<stem>_preview.html`). The last line is `RESULT {json}` (path, bytes, ok, check, warnings).
Then **critically review before showing the user** (view the images):
1. The wrap PNG — attractive, on-theme, text spelled correctly?
2. `review/<stem>_check.png` (left: art on the car surface, seams in red; right: panel ids,
   F/R = front/rear) — heroes inside panels, text along the body, nothing cut at seams.
   Hood/front art is **upside-down on the flat PNG by design** (upright on the car).
3. Validation lines — all PASS; investigate any WARN.
Iterate on the spec, not on pixels. Typical: 2–3 renders.

### 5. User-supplied finished art
```bash
python3 SKILL_DIR/scripts/finalize_wrap.py input.png --model <id> --name "My Wrap" --out-dir OUT_DIR
python3 SKILL_DIR/scripts/make_check.py OUT_DIR/My_Wrap.png --model <id>
```
Resizes to the template, flattens transparency, compresses, renames and validates. Warn that
art not drawn on the template crosses seams unpredictably; offer a layered rebuild.

### 6. Deliver
Give the user the PNG(s), a validation summary (dimensions, bytes, 0 transparent pixels), the
preview HTML (open it in any browser), a note that hood art looks upside-down in the flat file
by design, and the upload steps — copy **only the PNGs**, never `review/`:
- **USB:** exFAT / FAT32 / MS-DOS FAT / ext3 / ext4 (not NTFS) → folder `Wraps` at the root →
  up to 10 PNGs → no map/firmware update files on the drive.
- **Tesla app (v4.59.0+):** Creations → Wrap → Upload (up to 10).
- **In the car:** Toybox → Paint Shop → Wraps tab.
Offer one variant (colourway or layout) as a next step.

## Reference
| Script | Purpose |
|---|---|
| `env_check.py` | Capabilities, template source, output dir |
| `fetch_templates.py --model ID [--template FILE] / --all / --list` | Template → mask, panels, overlay |
| `render_wrap.py spec.json [--preview] [--debug]` | Design spec → compliant PNG + check image |
| `finalize_wrap.py img --model ID` | Any image → compliant PNG |
| `validate_wrap.py *.png --model ID [--json]` | Spec validation (exit 1 on error) |
| `make_check.py wrap.png --model ID` | Art-on-template review image |
| `make_preview.py --model ID *.png -o out.html` | Self-contained HTML viewer with the wraps embedded |
| `selftest.py` | End-to-end test over all models (needs templates) |

`assets/viewer/wrap-viewer.html` also works standalone in a browser: pick a model, drop PNGs →
spec checks, template outlines, car-surface mask, transparency/black risk map, Paint Shop tile
and a tiltable flat-sheet view (Tesla publishes no 3D meshes).

**SVG backends:** cairosvg if installed → built-in pure-Python renderer (default; no extra
dependencies) → headless Chrome only for features the built-in renderer cannot draw. Force one
with env `TESLA_WRAP_SVG=mini|cairo|chrome`.

**Cache location:** `$TESLA_WRAP_CACHE`, else `SKILL_DIR/.cache` if writable, else
`~/.cache/tesla-wrap-designer`, else the system temp dir.

## Troubleshooting
- **Template download blocked:** see step 2 (user attaches `template.png`).
- **> 1 MB after compression:** lower noise contrast/density; avoid full-canvas photos.
- **Text vertical or upside-down on the car:** place it with `panel:` (auto `upright_rotate`)
  or set `rotate` to that panel's `upright_rotate`.
- **Text cut at a door seam:** one text layer per door panel.
