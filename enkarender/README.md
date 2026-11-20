# enkarender

A modular, original **Enka-to-image rendering engine** for Genshin Impact showcase data —
built as the long-term rendering foundation for the bot. It fetches a UID's public showcase
from Enka.Network, parses it into a clean domain model, and composes template-driven cards
(player profile, character build) into PNG bytes.

It is *inspired by* the layered architecture of the reference wrapper library
(`PaiGramTeam/EnkaNetwork.py`) — strict client/http/cache/model/assets separation, externally
downloaded + locally cached assets, hash-map name localization — but is an entirely original
codebase with its own structure, rendering engine, template system, and card layouts. No
source, templates, layouts, or image assets were copied.

## Why it is structured this way

Four independence rules drive the whole design:

| Rule | How it is enforced |
|------|--------------------|
| Rendering is independent of API calls | Card builders receive an already-parsed domain model; the `RenderContext` carries only data + preloaded images + fonts + theme — never a live client. |
| Data is independent of rendering | `models/` has no PIL/aiohttp imports; the parser turns raw payloads into plain dataclasses. |
| Templates are independent | A `Template` lists positioned `Component`s for a fixed canvas; it does no I/O and the engine renders any template without knowing its type. |
| Assets/fonts are centralized + cached | One `AssetManager`/`CacheManager`/`FontManager`; downloads are pooled and cached to disk, decoded images live in a bounded memory LRU, fonts are cached by `(family, size, weight)`. |

## Layers

```
api/        HttpTransport (pooled) + EnkaClient (raw payloads, UID validation, response cache)
models/     domain dataclasses + parser (raw -> domain; name localization injected)
assets/     CacheManager (memory LRU + disk + response TTL), Downloader, ResourceLoader, AssetManager
fonts/      FontManager (central registry, cached, graceful fallback)
render/     DrawingUtils + Theme, Canvas (composer), RenderEngine (card-agnostic)
templates/  Component/Template ABCs + RenderContext, reusable components, registry, ProfileCard/BuildCard
cards/      CardBuilder ABC + registry, ProfileCardBuilder, BuildCardBuilder
utils/      async + text helpers      config.py  enums.py  exceptions.py  logging.py
```

## Data flow

```
EnkaClient.fetch_showcase(uid)   → raw JSON        (api + cache)
parse_showcase(raw, resolvers)   → Showcase/Character   (models)
CardBuilder.build(model)         → resolves assets+fonts concurrently → RenderContext
RenderEngine.render(template,ctx)→ Canvas composites components → PNG bytes   (off the event loop)
```

## Usage

```python
import asyncio
from enkarender import EnkaRenderer

async def main():
    async with EnkaRenderer() as r:
        png = await r.render_build("800000000")      # first showcased character
        open("build.png", "wb").write(png)
        png = await r.render_profile("800000000")
        open("profile.png", "wb").write(png)

asyncio.run(main())
```

Run the fully offline demo (renders both cards from a bundled fixture, no network):

```bash
cd enkarender && pip install -r requirements.txt
PYTHONPATH=. python -m example.demo      # writes example/profile.png and example/build.png
```

## Extending

**Add a card style** — no engine change:
1. Add a `Template` subclass in `templates/` (layout only) and `registry.register(MyTemplate())`.
2. Add a `CardBuilder` subclass in `cards/` with `_view_model`, `_theme`, `_load_images`, and
   `registry.register(MyBuilder)`.

**Add a component** — drop a `Component` subclass in `templates/components.py`; reuse it from
any template. **Localized names / real art** — provide `text_map.json` / `characters.json` in
the asset dir and real icon URLs; the same code path then downloads + caches them.

## Testing

```bash
cd enkarender && python -m pytest -q      # cache, fonts, engine, cards, parser
```

## Layer-based renderer (JSON-driven, Photoshop-style)

`enkarender.layered` is a second rendering style built on the same foundation: a card is an
ordered **stack of independent layers**, each drawn by its own renderer and positioned
entirely from a **JSON layout** — no coordinates in code. A brand-new template is a new JSON
file + new asset folders, with **zero code changes**.

**Layer stack:** background → decorative overlays → panels → frames → character splash →
weapon → artifacts → talents → elements → stats → dynamic text → effects → footer → export.

**Per-layer renderers** (each draws only its own layer): `BackgroundRenderer`, `PanelRenderer`,
`CharacterRenderer`, `WeaponRenderer`, `ArtifactRenderer`, `TalentRenderer`, `StatRenderer`,
`TextRenderer`, `EffectRenderer`, `FooterRenderer` (+ a generic image renderer for
frames/elements/overlays). Types map to renderers via a registry, so new layer types drop in.

**Each layer in the JSON** configures `x, y, width, height, align, font, font_size, color,
rotation, scale, opacity, z-index` plus type-specific `props` (asset name / text template /
repeat config). Assets are auto-located from `backgrounds/ frames/ panels/ icons/ weapons/
artifacts/ elements/ effects/ characters/ fonts/` and cached in memory (decoded images +
fonts). Layouts **scale to any resolution** from one base size — pass `target_width` and every
coordinate/size/font is multiplied by a single factor.

```python
from enkarender.layered import LayeredAssetManager, LayeredRenderer, load_layout

assets = LayeredAssetManager("assets")            # your asset folders
engine = LayeredRenderer(assets)
layout = load_layout("enkarender/layered/layouts/profile.json")
png = engine.render_png(layout, data, target_width=1500)   # base 1000 -> rendered at 1500
```

Offline demo (renders the bundled layout with placeholder assets):
```bash
cd enkarender && PYTHONPATH=. python -m example.layered_demo   # writes example/layered_profile.png
```

## License

MIT. Original implementation; architecturally inspired by, but not derived from, the
referenced project.
