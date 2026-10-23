# Intake questions

Ask only what the request has not already answered. If the platform has a structured
question tool (e.g. multiple-choice prompts), use it — max ~4 questions per round, 2–4
options each, always allowing a free-text answer. Otherwise send one short message with
numbered questions and lettered options so the user can reply "1b, 2a, …".
Never start rendering until **model template** is unambiguous — a wrong template means the
art lands on the wrong panels.

## Round 1 — vehicle (mandatory)

**Q1. Which Tesla?** Options: Model 3 · Model Y · Model S / Model X · Cybertruck
(If "Model S / Model X", follow up with which one.)

**Q2. Year / generation / trim** — ask with options specific to the Q1 answer:

| Model | Options → template id |
|---|---|
| Model 3 | 2017–2023 → `model3` · 2024+ (Highland) Standard/Premium → `model3-2024-base` · 2024+ Performance → `model3-2024-performance` |
| Model Y | 2020–2024 → `modely` · 2025+ Standard → `modely-2025-base` · 2025+ Premium/Long Range → `modely-2025-premium` · 2025+ Performance → `modely-2025-performance` · Model Y L (6-seat) → `modely-l` |
| Model S | 2021+ (incl. non-Plaid 2025 — verify) → `models-2021` · 2025+ Plaid → `models-2025-plaid` · pre-2021 → **not supported by Tesla** |
| Model X | 2021+ → `modelx-2021` · pre-2021 → **not supported by Tesla** |
| Cybertruck | single template → `cybertruck` (1024×768 canvas) |

If the user is unsure, use the `identify` hints in `models.json` (e.g. Highland has no fog
lights and slim headlights; 2025+ Model Y has a full-width front light bar). If still unsure,
ask them to check **Controls → Software** on the touchscreen (shows model, trim and model
year) or the Tesla app's vehicle details, or offer to render for both candidate templates.

## Round 2 — design brief (one round where possible)

**Q3. Style direction** for their theme, e.g. for "Star Wars": Space battle / starfield ·
Clean racing-stripe livery · Retro poster art · Minimal monochrome. Tailor options to the theme.

**Q4. Text on the car?** None · Name / message (ask for exact text) · Date / number.
Collect exact spelling, capitalisation, and language.

**Q5. Colour palette** — offer 3 palettes that fit the theme (show hex in description) or
"match my car paint colour" (then ask which paint).

**Q6. Reference images** (only if they mentioned images or the theme benefits):
Place on the car (photo/logo/artwork) · Inspiration only · No images.
For images to place: ask for file paths; confirm they own them or have permission
(personal photos, their own artwork). Ask where the hero image should go: Hood · Both sides · Rear.

## Round 2b — design mode (mandatory on every new request)

**Q7. Design mode?** Code-drawn (default, offline) · AI image mode (image model paints the
artwork; prompt sent to a provider; may cost; results vary). Ask it every time, even if the
user chose AI mode before. See `ai-image-mode.md`.

## Defaults when the user says "just go" / "surprise me"

- Code-drawn mode ("just go" is not consent to AI image mode).
- 1 primary design + 1 alternate colourway.
- Palette and motifs from `design-playbook.md` theme recipes.
- Text only if the theme implies it (birthday → "HAPPY BIRTHDAY" + name if given).
- Filename: `<Theme>_<Model>` sanitised, e.g. `Galactic_Saga_M3.png`.
