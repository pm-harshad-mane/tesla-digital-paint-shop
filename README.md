# Tesla Digital Paint Shop

**`tesla-wrap-designer`** is a portable [Agent Skill](https://agentskills.io/specification)
that turns an idea like *"Star Wars theme"*, *"Simpsons cartoon theme"* or *"Happy birthday"*,
optionally with your own images, into a custom wrap for Tesla's
**Toybox → Paint Shop → Wraps** that follows Tesla's official spec
([teslamotors/custom-wraps](https://github.com/teslamotors/custom-wraps)).

- Asks the right questions first (model, year/generation, trim → the exact template)
- Renders layered original artwork: gradients, procedural patterns, SVG illustrations,
  text and your own photos/logos, placed panel-aware on the correct UV template
- Guarantees the spec: exact template size (1024×1024, Cybertruck 1024×768), ≤ 1 MB,
  **no transparent pixels** (they render black on the car), valid file name
- Validates every output, renders a seam-check image, and builds a self-contained HTML
  preview to inspect it before uploading

The skill is a single self-contained folder, `skills/tesla-wrap-designer/`. Nothing in it
depends on this repository, and it works in Claude, ChatGPT, OpenAI Codex and other tools that
support the `SKILL.md` format.

## Install

**Download the ready-made skill:
[`dist/tesla-wrap-designer.zip`](https://github.com/pm-harshad-mane/tesla-digital-paint-shop/raw/main/dist/tesla-wrap-designer.zip)**
(always built from the current `main`), or build it yourself; see [Building](#building).

| Platform | How |
|---|---|
| **Claude.ai / Claude desktop & mobile** (Pro, Max, Team, Enterprise; code execution on) | Customize → Skills → **+** → Upload a skill → `tesla-wrap-designer.zip` |
| **Claude Code** (plugin) | `/plugin install tesla-digital-paint-shop --marketplace pm-harshad-mane/tesla-digital-paint-shop` (Claude Code 2.1.275+), or `/plugin marketplace add pm-harshad-mane/tesla-digital-paint-shop` then `/plugin install tesla-digital-paint-shop@tesla-digital-paint-shop` |
| **Claude Code** (manual) | Unzip into `~/.claude/skills/` (all projects) or `<project>/.claude/skills/` |
| **Claude API** (`/v1/skills`) | Upload the zip with `POST /v1/skills`, then reference it in `container.skills` alongside the code execution tool ([Skills guide](https://platform.claude.com/docs/en/build-with-claude/skills-guide)) |
| **Claude Agent SDK** | Unzip into `.claude/skills/` (project) or `~/.claude/skills/`, with `setting_sources` including `project`/`user` |
| **ChatGPT** (web / desktop, plans with Skills) | Skills → Create → **Upload from your computer** → `tesla-wrap-designer.zip`. See [Using with ChatGPT](#using-with-chatgpt) |
| **OpenAI Codex** (CLI / IDE / app) | Unzip into `~/.agents/skills/` (all projects) or `<repo>/.agents/skills/`, then invoke with `$tesla-wrap-designer`. See [Using with ChatGPT](#using-with-chatgpt) |
| **Other Agent Skills-compatible tools** | Unzip into the tool's skills folder; the skill uses only `SKILL.md` + Python scripts |

Then ask: *"Make me a Happy Birthday wrap for my 2024 Model 3."*

**Runtime requirements:** Python 3.10+ with Pillow and numpy (preinstalled on Claude.ai and
the Claude API, and normally available in ChatGPT's Python sandbox). Nothing else: SVG
illustrations use a built-in pure-Python renderer (cairosvg or Chrome are used if present). No network access is needed: Tesla's templates for
every supported model are bundled in `assets/templates/`.

## Using with ChatGPT

OpenAI supports the same `SKILL.md` skill format in ChatGPT and Codex, so the zip from
[Install](#install) works unchanged. The skill runs its Python scripts in
ChatGPT's code sandbox; Tesla's templates are bundled, so no network access is needed.

### ChatGPT (web and desktop)

1. **Check availability.** Skills must be included in your ChatGPT plan. At the time of
   writing, third-party guides report Business, Enterprise, Edu and Healthcare workspaces, and
   a workspace admin may need to allow skill uploads. See OpenAI's
   [Skills in ChatGPT](https://help.openai.com/en/articles/20001066-skills-in-chatgpt) for
   the current list.
2. **Upload.** Open **Skills** (in the sidebar of the desktop app, or under Plugins on the
   web), choose **Create → Upload from your computer**, and select `tesla-wrap-designer.zip`.
   ChatGPT scans uploaded skills first. If the skill is marked **Needs Review**, review it
   and confirm before use.
3. **Check what was imported.** The name should be `tesla-wrap-designer`, and the
   description and instructions should match `SKILL.md`. Then install it.
4. **Use it.** In a chat, type `@` and pick **tesla-wrap-designer**, or just ask, e.g.
   *"Make a Happy Birthday wrap for my 2024 Model 3"*. ChatGPT also picks the skill
   automatically when a request matches its description.
5. **Download the results.** The skill writes the wrap PNG(s) and review files to
   `/mnt/data`, the sandbox folder ChatGPT offers for download. Download the PNG and the
   `*_preview.html` file, and open the preview in your browser to check the wrap before
   uploading it to the car.

**No Skills feature on your plan?** As a fallback, attach `tesla-wrap-designer.zip` to a chat
and ask: *"Unzip this, read tesla-wrap-designer/SKILL.md and follow it to make my wrap."* This
relies on ChatGPT's Python sandbox being able to open zip files, which has not always been
reliable, so the Skills route above is preferred.

### OpenAI Codex (CLI, IDE extension, app)

```bash
mkdir -p ~/.agents/skills
unzip tesla-wrap-designer.zip -d ~/.agents/skills/      # all projects
# or: unzip tesla-wrap-designer.zip -d <repo>/.agents/skills/   (one repository)
```

Older Codex versions read skills from `~/.codex/skills/` (or `$CODEX_HOME/skills/`) instead.
Codex detects new skills automatically; restart it if the skill doesn't appear. Invoke it
explicitly with `$tesla-wrap-designer` (or pick it from `/skills`), or simply describe the
wrap you want. Codex runs the scripts locally, so you need Python 3.10+ with Pillow and
numpy (`pip install -r ~/.agents/skills/tesla-wrap-designer/requirements.txt`).

## Building

```bash
python3 tools/build_skill.py        # dist/tesla-wrap-designer.zip (~4.7 MB)
python3 tools/update_templates.py   # maintainers: refresh bundled templates from Tesla's repo
```

The build checks SKILL.md (name format, ≤ 200-character description for Claude.ai,
< 500 lines) and the 30 MB size limit. The zip contains the skill folder at its root, which is
the layout every platform above accepts.

The zip is committed to the repo so users can download it directly. **Whenever you change
anything under `skills/tesla-wrap-designer/`, rebuild and commit the zip in the same commit.**
The build is deterministic, so the zip only changes when the skill does. GitHub Actions
(`.github/workflows/skill.yml`) runs `python3 tools/build_skill.py --check` and the self-test
on every push and pull request, and fails if the committed zip is out of date.

When Tesla adds or changes templates: bump `source_ref` (and add new models) in
`references/models.json`, run `tools/update_templates.py`, re-check
`references/panel-guide.md` against the regenerated `panels_overlay.png` files, then run
`scripts/selftest.py`.

## Use the scripts directly

```bash
S=skills/tesla-wrap-designer
python3 $S/scripts/env_check.py
python3 $S/scripts/fetch_templates.py --list
python3 $S/scripts/render_wrap.py $S/assets/examples/birthday_bash.json --model modely --preview
python3 $S/scripts/finalize_wrap.py my_art.png --model cybertruck --name "My Wrap"
python3 $S/scripts/validate_wrap.py wraps/*.png --model model3
python3 $S/scripts/selftest.py
```

`assets/viewer/wrap-viewer.html` also works on its own: open it in a browser, pick a model
and drop PNGs. It shows spec checks, template outlines, the car-surface mask, a
transparency/black risk map, Paint Shop tile previews and a tiltable flat-sheet view. Tesla
does not publish 3D meshes, so it is a UV-sheet view, not the real car.

## Supported vehicles

Model 3 (2017–23 · 2024+ Standard/Premium · 2024+ Performance) · Model Y (2020–24 · 2025+
Standard / Premium / Performance · Model Y L) · Model S (2021+ · 2025+ Plaid) · Model X (2021+) ·
Cybertruck. Tesla provides no templates for pre-2021 Model S/X.

## Upload to the car

- **USB:** format exFAT / FAT32 / MS-DOS FAT / ext3 / ext4 (not NTFS), create `Wraps/` at the
  root, copy up to 10 PNGs, and keep map/firmware update files off the drive.
- **Tesla app (v4.59.0+):** Creations → Wrap → Upload (up to 10).
- **In the car:** Toybox → Paint Shop → Wraps.

## Notes

- Franchise themes are rendered as original homage art, with no copyrighted characters or logos.
- Architecture and module contracts: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
