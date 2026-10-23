# AI image mode (optional, opt-in per request)

By default every wrap is **code-drawn**: Claude writes a design spec (gradients, patterns,
SVG illustrations, text) and the engine renders it. That is offline, deterministic and
private.

**AI image mode** instead has an image-generation model paint the artwork (painterly scenes,
photoreal textures, rich illustration). The skill then cuts those images onto the template's
panels, adds text itself, and validates everything as usual.

## Consent: ask on every new wrap request

At intake, for **every new wrap request** (never carry the answer over from an earlier
request), ask:

> **Design mode?** (a) Code-drawn, the default: offline and precise. (b) AI image mode:
> an image model paints the artwork for a richer, more illustrated look. Your design prompt
> is sent to an image provider, it may cost credits, and results vary between runs.

Use AI image mode **only after the user explicitly picks (b)**. Then tell them which image
source will be used (below). If they don't answer, or are unsure, use code-drawn.

## Image sources, in order of preference

1. **The platform's own image-generation tool**, if this session has one (e.g. ChatGPT's
   image generation, or an image tool or MCP connector the user has installed). Request each
   asset at the planned size or aspect ratio.
2. **`scripts/generate_image.py`**, an OpenAI-compatible Images API client. Use it only if
   `OPENAI_API_KEY` is already set in the environment. Never ask the user to paste a key into
   the chat. Model: `TESLA_WRAP_IMAGE_MODEL` (default `gpt-image-2`). Check the request with
   `--dry-run` first if unsure.
3. **User-supplied:** give the user the prompts and sizes from the plan, they generate the
   images in any tool they like, and attach the results.

If none of these is available, say so and fall back to code-drawn mode. Claude cannot
produce raster images itself.

## Workflow

1. **Plan the assets:**
   ```bash
   python3 SKILL_DIR/scripts/plan_ai_assets.py --model <id> --out-dir OUT_DIR/<Name>
   ```
   This writes `ai_assets.json` and a ready `design.json`. Each asset has a region size,
   aspect ratio, generation size, kept fraction and composition rules:
   - `ai_background.png`: fills the whole canvas, under everything.
   - `ai_side.png`: **one panorama for both sides**, cut across fender, doors and quarter
     panel (`"panel": "side_all", "fill_panel": true`). It is mirrored on the side where the
     car faces the other way, so its front always points to the car's front.
   - `ai_hood.png`, `ai_trunk.png`: fill their panels.
2. **Write prompts** (fill `prompt` in `ai_assets.json`). Each prompt combines:
   - **Shared style line** (identical in every prompt for a consistent look): medium,
     palette with hex codes, lighting, era or mood. E.g. *"cinematic digital matte painting,
     deep indigo #0b1230 and violet #5b2a86 with gold #ffd84a accents, volumetric light,
     high detail"*.
   - **The asset's subject**, following the concept from `art-direction.md`.
   - **The asset's `composition` text**, copied verbatim. It says which part of the image
     survives the crop, where the car's front is, and forbids text and logos.
   - For franchise themes, describe original elements and never name the franchise,
     characters or brands in the prompt (image models will copy them).
3. **Generate** each asset at its `generate_size` (or that aspect ratio) and save it under
   the planned file name next to `design.json`. Look at every image before using it;
   regenerate if it has text, watermarks, artefacts, or the subject is outside the kept band.
4. **Text and finishing touches:** enable or adjust the text layers in `design.json`
   (wordmarks, names), and add code-drawn accents if needed (glows, stripes, an SVG emblem).
   All lettering stays in `text` layers, which are orientation-checked. Lettering inside AI
   images can come out garbled, and mirrored on one side.
5. **Render and review** exactly as in SKILL.md step 4, including the orientation sheet and
   the design critique. If a subject sits badly in its panel, shift the crop window with
   `"focus": [fx, fy]` (0–1; default `[0.5, 0.5]`) before regenerating.

## Layer options used by this mode

| Key | Meaning |
|---|---|
| `"panel": "side_all"` | all side panels, one merged group per side of the car |
| `"fill_panel": true` | cover the whole panel (group) and cut the image along its outline, instead of fitting it inside |
| `"image_front": "right"` | the image's subject faces right; mirror it where the car's front is on the left |
| `"focus": [fx, fy]` | where the `cover` crop window sits within the image |

## Quality and safety notes

- The whole file must still be ≤ 1 MB. Photographic detail compresses poorly, so the
  finalizer may drop colour depth. Prefer painterly or illustrative styles with smooth areas
  over noisy photo textures.
- Image providers apply their own content policies; a refused prompt needs rewording, not
  workarounds.
- Don't send personal data (names, photos of people, licence plates) to a provider unless
  the user explicitly agreed. Names belong in text layers, which never leave the machine.
