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
≤ 30 chars incl `.png` · **every piece of text reads upright on the car — never upside-down
or sideways**. Never hand over a file that has not passed validation and the text-orientation
check (step 4.3).

**Design quality bar:** every wrap must be creative, polished and genuinely impressive, like
the work of a professional livery designer, never a generic template with the theme name typed
on it. Follow `references/art-direction.md`: a concept first, layered depth and lighting,
strong focal points, professional typography and illustrations, and a scored self-critique.
Never deliver a draft that has not passed that critique.

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

**Design mode: ask on every new wrap request, never assume.** Offer (a) **Code-drawn**
(default, local) or (b) **AI image mode**: the host platform's own image-generation model
paints the artwork; results vary. AI image mode uses only the host's built-in image
generation, never an external API or key. If this session has none, say AI mode isn't
available on this platform and continue code-drawn. Use the exact wording and rules in
`references/ai-image-mode.md`. AI image mode needs the
user's explicit "yes" for *this* request; a previous request's answer does not carry over.
No answer, or unsure → code-drawn.

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

### 3. Art direction, then the design spec
*(AI image mode: do the art direction below, then follow `references/ai-image-mode.md`.
It plans the images with `plan_ai_assets.py`, then you generate them and render the
generated `design.json` with step 4. All quality, orientation and validation checks apply
unchanged.)*

First read `references/art-direction.md` and decide the **concept**: a big idea in one
sentence, 3 mood words, a 60/30/10 palette with hex codes, one focal point per view (hood,
each side, trunk) and the direction of motion. Share it with the user in 2–3 lines. When the
brief is open, propose 2 distinct directions. Examples are scaffolding only: never ship one
unchanged; personalise it to the brief.

Then create `OUT_DIR/<Name>/design.json` (copy user images beside it).
Schema: `references/design-spec.md` · starting points: `assets/examples/*.json` ·
composition rules and theme recipes: `references/design-playbook.md`.
- Layers 1–2 cover the whole canvas (gradient / noise / pattern); build 4–6 depth planes
  in total (field → atmosphere → motifs → accents → heroes → glows/highlights).
- Heroes (text, emblems, user photos) inside single large panels, mirrored on both sides;
  prefer region selectors (`"panel": "hood"`, `"trunk"`, `"side"`) over raw coordinates.
- Side text: `"panel": "side"` (one panel per side), or `"span": true` to run one phrase across
  the front + rear door of a side (adjacent on the car, so it reads across the door gap like a
  real livery). Never span panels that are not neighbours on the car.
- Place text with `panel:` (ids or `"hood"`, `"trunk"`, `"side"`) and **omit `rotate`**: the
  engine applies each panel's `upright_rotate`. Only set `rotate` by hand when placing by
  `position`, and then it must equal the `upright_rotate` of the panel under the text.
- Put lettering in `text` layers, not inside SVG/images, so it can be checked automatically.
- Illustrations: start from the polished components in `assets/illustrations/` (recolour,
  combine, extend) or draw original inline SVG to the same standard: bold silhouettes, a
  consistent style, and base colour + shadow + highlight on every shape. No clip-art. Put a
  side hero illustration on the rear quarters, not just text.

### 4. Render, validate, inspect
```bash
python3 SKILL_DIR/scripts/render_wrap.py OUT_DIR/<Name>/design.json --out-dir OUT_DIR --preview
```
Composes → finalizes (flatten to opaque RGB, compress ≤ 1 MB) → validates → writes
`OUT_DIR/<File>.png` and review files in `OUT_DIR/review/` (`<stem>_check.png`,
`<stem>_preview.html`, `<stem>_orientation.png`). The last line is `RESULT {json}` (path,
bytes, ok, check, orientation, orientation_errors, warnings).
Then **critically review before showing the user** (view the images):
1. The wrap PNG — attractive, on-theme, text spelled correctly?
2. `review/<stem>_check.png` (left: art on the car surface, seams in red; right: panel ids,
   F/R = front/rear) — heroes inside panels, text along the body, nothing cut at seams.
   Hood/front art is **upside-down on the flat PNG by design** (upright on the car).
3. **Text orientation — mandatory, every render.** Text that would be unreadable (< 18 px) or
   cut by a seam is not drawn at all: look for `SKIPPED TEXT` warnings and re-place it.
   Each `text_orientation` line must be PASS
   (the render fails on upside-down, sideways or off-car text). Then view
   `review/<stem>_orientation.png`: it shows every text/image/SVG element rotated the way it
   appears on the car. Every word must read normally, left to right, not mirrored. Image/SVG
   elements get WARN when rotated unusually: if they contain lettering or a face, they must
   look upright in this sheet too.
4. Validation lines — all PASS; investigate any WARN.
5. **Design critique** — score the 8 criteria in `references/art-direction.md` §5 honestly.
   Ship when every score is ≥ 4; otherwise fix the two weakest criteria and re-render (up to
   5 rounds). If the bar is still not met, deliver the best round and say which criteria fall
   short and why.
Iterate on the spec, not on pixels. Typical: 2–4 renders. In the delivery message, state
explicitly that text orientation was checked (e.g. "all 4 text elements verified upright").

### 5. User-supplied finished art
```bash
python3 SKILL_DIR/scripts/finalize_wrap.py input.png --model <id> --name "My Wrap" --out-dir OUT_DIR
python3 SKILL_DIR/scripts/make_check.py OUT_DIR/My_Wrap.png --model <id>
```
`make_check.py` also writes `review/<stem>_on_car.png`: every panel rotated the way it appears
on the car. **View it and confirm any lettering in the user's art reads upright**; if not,
tell the user which panel is wrong and offer to fix it (rebuild as a layered design).
Resizes to the template, flattens transparency, compresses, renames and validates. Warn that
art not drawn on the template crosses seams unpredictably; offer a layered rebuild.

### 6. Deliver
Give the user the PNG(s), a 2–3 line design rationale (concept, palette, focal points), a
validation summary (dimensions, bytes, 0 transparent pixels), the
preview HTML (open it in any browser), a note that hood art looks upside-down in the flat file
by design, and the upload steps — copy **only the PNGs**, never `review/`:
- **USB:** exFAT / FAT32 / MS-DOS FAT / ext3 / ext4 (not NTFS) → folder `Wraps` at the root →
  up to 10 PNGs → no map/firmware update files on the drive.
- **Tesla app (v4.59.0+):** Creations → Wrap → Upload (up to 10).
- **In the car:** Toybox → Paint Shop → Wraps tab.
Offer one meaningfully different alternative direction (new concept or layout, not just a
recolour) as a next step.

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
| `plan_ai_assets.py --model ID --out-dir DIR` | AI image mode: asset sizes/prompts + design.json |
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
- **`text_orientation` FAIL:** remove the manual `rotate` and place the text with `panel:`,
  or set `rotate` to the `upright_rotate` the message says it needs.
- **`SKIPPED TEXT` warning:** the panel is too thin/curved for that text. Use a line break,
  shorter text, or a bigger panel (`"side"`, `"hood"`, door ids from `references/panel-guide.md`).
