# Architecture — analysis & design

This document has two parts: (1) an analysis of the reference repository
`PaiGramTeam/EnkaNetwork.py`, and (2) the design of **enkarender**, the original
implementation this analysis informed. enkarender copies no source, templates, layouts, or
assets from the reference — only architectural *principles*.

---

## Part 1 — Analysis of the reference (`EnkaNetwork.py`)

### What it is
An async **API-wrapper library** for Enka.Network. It fetches a UID's public Genshin data and
returns typed response objects. It resolves game assets (characters, constellations, skills,
namecards) and localizes names via a text-map hash system. Notably, it is a **data library**:
it exposes icon *URLs/filenames*, not rendered images — card rendering lives in sibling
projects (e.g. enkacard). So the reference contributes the *data + asset + async* architecture;
the rendering architecture here is original, informed by how such ecosystems separate concerns.

### Module hierarchy (observed)
```
enkanetwork/
  assets/   model/   types/          # bundled data maps, response models, type defs
  client.py     EnkaNetworkAPI — public async client (fetch_user_by_uid, fetch_builds, …)
  http.py       transport — session, endpoints, request execution
  cache.py      response caching (TTL / stale control)
  assets.py     Assets — id→character/skill/namecard resolution + get_hash_map (localization)
  config.py     endpoints / base URLs
  enum.py       Language and other enums
  exception.py  typed errors (invalid UID, not found, HTTP errors, …)
  tools.py      helpers incl. asset updater      utils.py  misc utilities
```

### Responsibilities & data flow
1. **client** validates the UID and orchestrates a fetch.
2. **http** performs the request against endpoints from **config**, returning raw JSON.
3. **cache** short-circuits repeat requests within a TTL.
4. The client maps raw JSON into **model** objects (player, characters, equipment, stats).
5. **assets** resolves ids to resource descriptors and localizes `nameTextMapHash` → display
   strings via **get_hash_map**; assets are **downloaded from an external data repo** and
   updated via `update_assets()` rather than bundled binaries.
6. **enum/exception** give typed languages and typed failures throughout.

### Principles worth adopting
- Strict **layering**: client → http → cache → model → assets, each single-purpose.
- **Assets are external + cached + updatable**, not embedded — keeps the package small and
  lets new game content work without a code release.
- **Name-hash localization** decoupled from parsing (injectable).
- **Async** client with an explicit lifecycle (context manager).
- Centralized **config**, **enums**, and a **typed exception** hierarchy.
- Icon objects expose both a stable **key/filename** and a resolvable **URL**.

### What enkarender does differently (originality)
- Adds a first-class, **card-agnostic rendering engine** and a **drop-in template system**
  the reference does not have.
- Splits the asset concern into four explicit collaborators (cache / downloader / resource
  loader / manager) instead of one `assets.py`.
- Uses plain `@dataclass` domain models + an injectable-resolver parser rather than
  response-object wrappers, so the model layer has zero I/O or PIL dependency.
- Its own naming, structure, layouts, and drawing code.

---

## Part 2 — enkarender design

### Layer map & single responsibilities
| Layer | Module(s) | Responsibility |
|-------|-----------|----------------|
| Configuration | `config.py` | One immutable `Settings`: endpoints, dirs, TTLs, timeouts, concurrency. |
| Logging | `logging.py` | One `enkarender` logger namespace; one-call verbosity. |
| Enums / Errors | `enums.py`, `exceptions.py` | `Language`/`Element`/`Anchor`; a typed error tree under `EnkaRenderError`. |
| API | `api/http.py`, `api/client.py` | Pooled transport (retries/timeouts) + `EnkaClient` returning **raw** payloads; UID validation; optional response cache. |
| Models | `models/domain.py`, `models/parser.py` | Plain dataclasses + defensive raw→domain parser; name/character resolution **injected** as callables. |
| Cache | `assets/cache.py` | 3 tiers: image memory-LRU, disk-bytes (TTL), API-response (TTL). |
| Assets | `assets/downloader.py`, `assets/loader.py`, `assets/manager.py` | Fetch-or-cache bytes → decode+cache images → logical resolution (name-hash, icon key→URL). |
| Fonts | `fonts/manager.py` | Central registry; cache by `(family,size,weight)`; graceful fallback. |
| Render | `render/draw.py`, `render/canvas.py`, `render/engine.py` | Stateless drawing utils + `Theme`; a `Canvas` composer; a **card-agnostic** engine. |
| Templates | `templates/base.py`, `components.py`, `profile_card.py`, `build_card.py` | `Component`/`Template` ABCs + `RenderContext`; reusable components; a registry; two layouts. |
| Cards | `cards/base.py`, `profile.py`, `build.py` | `CardBuilder` ABC + registry; orchestrate model→context→render. |
| Utils | `utils/` | Concurrency (`gather_map`, `run_in_thread`) + text helpers. |

### End-to-end data flow
```
                 ┌── api/http (pooled, retries) ──┐
uid ─► EnkaClient┤                                 ├─► raw JSON ─► parse_showcase ─► Showcase
       (validate)└── cache (response TTL) ─────────┘   (resolvers injected)          / Character
                                                                                        │
                          ┌───────────── CardBuilder.build(model) ─────────────────────┘
                          │  _view_model(model)  → plain dict
                          │  _theme(model)        → element Theme
                          │  _load_images(model)  → assets.load_icon(...) ⇉ concurrent, cached
                          ▼
                    RenderContext(data, images, fonts, theme)   ← no client, no I/O
                          │
                    RenderEngine.render(template, ctx)   ← run_in_thread (off event loop)
                          │  Canvas(size, background)
                          │  for component in template.components(ctx): component.render(canvas, ctx)
                          ▼
                        PNG bytes
```

### Rendering engine
`RenderEngine.render(template, ctx)` is ~10 lines and knows nothing about card types: it
builds a `Canvas` at the template's size, applies the template background, and paints each
`Component` in order. Because a template is *only* a positioned list of components and reads
*only* from `RenderContext`, **new templates and card types require zero engine changes**.
`Canvas` centralizes the drawing vocabulary (panels, bars, gradients, cover-fit paste,
circular paste, anchored text); `DrawingUtils` holds the stateless pixel math; `Theme` +
`theme_for(element)` recolour a card from data without touching layout.

### Template system
- **Isolation**: every template is a self-contained class defining layout only.
- **Automatic binding**: a template maps view-model fields (`ctx.data[...]`) and image slots
  (`ctx.images[...]`) to component constructor args in one place — the single binding site.
- **Reusable components**: `Panel`, `Label`, `Icon`, `CircleImage`, `StatRow`, `ProgressBar`,
  `Divider`, `Gradient`, `TintOverlay` compose any card.
- **Drop-in**: templates self-register in a `TemplateRegistry` at import; the engine looks
  them up by key. A new template is a new file + one `register(...)` call.

### Adding a card type (no existing code touched)
1. `templates/foo_card.py`: subclass `Template` (set `key`, `size`, `components`), then
   `registry.register(FooTemplate())`.
2. `cards/foo.py`: subclass `CardBuilder` (`key`, `template_key`, `_view_model`, `_theme`,
   `_load_images`), then `registry.register(FooBuilder)`.
That is the entire extension surface.

### Performance & async
- **Pooled HTTP**: one `aiohttp` session + `TCPConnector` reused for API + every asset;
  retries with exponential backoff; per-op timeouts.
- **Minimal calls**: response TTL cache avoids repeat fetches; disk cache avoids re-downloads.
- **Low memory**: decoded images live in a *bounded* LRU (capacity from `Settings`); large
  originals are cover-fit before compositing.
- **Concurrency**: a builder resolves all portraits/icons in parallel (`gather_map`/`gather`);
  the CPU-bound Pillow render runs in a worker thread (`run_in_thread`) so the event loop and
  other renders stay responsive.
- **Warm caches**: fonts and decoded images are cached on first use and reused across cards.

### Separation of responsibilities (summary)
- API never imports models; models never import PIL or aiohttp; templates never do I/O;
  the engine never knows a card type; card builders are the *only* place the layers meet.
- Every cross-layer dependency is a constructor argument or an injected callable, so each
  layer is unit-testable in isolation (see `tests/`).
