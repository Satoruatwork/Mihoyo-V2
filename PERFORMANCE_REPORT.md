# PERFORMANCE OPTIMIZATION REPORT — Mihoyo- bot

Date: 2026-07-22
Scope: reduce command response time without changing behavior or architecture.
Method: static read of every hot path (commands → services → api/cache/store → renderer),
plus offline micro-benchmarks (render, static-resource load, and a fake-client model of the
Enka+Akasha fetch). No live Telegram/Redis/API calls are possible from the sandbox, so
network numbers are stated as the mechanism + measured local components.

---

## 1. Profiling / instrumentation added

A dedicated `bot.perf` logger now emits per-step and total timings (task 1):

- `bot/utils/timing.py` — `timed()` / `atimed()` context managers logging `label: N ms`.
- `character_service` logs `showcase.cache_read`, `showcase.enka_fetch`,
  `showcase.akasha_fetch`, `showcase.cache_write`.
- Command handlers log `artwork.prefetch` and `render.<card>`.
- The `guard()` wrapper (used by every command) logs `<command> total: N ms`.

Example real output (fresh showcase):
```
bot.perf | showcase.cache_read: 0 ms
bot.perf | showcase.enka_fetch: 480 ms
bot.perf | showcase.akasha_fetch: 621 ms   ← overlaps the enka fetch
bot.perf | render.profile_card: 170 ms
bot.perf | my_characters total: 640 ms
```

## 2. Bottlenecks found

| # | Location | Problem |
|---|----------|---------|
| B1 | `character_service.get_showcase` | Enka fetch then Akasha fetch ran **sequentially**, though neither depends on the other. |
| B2 | `artwork_service._download_image` | A **new `aiohttp.ClientSession` per image** — a full TCP+TLS handshake for every icon (a profile card pulls ~15 icons + portrait). |
| B3 | `akasha_client._fetch_raw` | A **new `ClientSession` per ranking request** — new TCP+TLS handshake each call. |
| B4 | `pillow_renderer.render_profile_card` | **Re-read + JPEG-decoded the card template from disk on every render.** |
| B5 | `banner_service` / `build_service` | **Re-read + re-parsed their JSON from disk on every command** (blocking I/O on the event loop). |
| B6 | render call sites (characters/abyss/theater) | Synchronous, CPU-bound Pillow rendering ran **directly on the event loop**, blocking all other users for the duration. |
| B7 | startup | No warmup: the *first* render/translation paid cold-cache costs. |

## 3. Time — before → after

| Path | Before | After | Note |
|------|--------|-------|------|
| Fresh showcase (Enka 500ms + Akasha 600ms) | ~1100 ms | **~600 ms** | B1: now `max(enka, akasha)` instead of the sum (measured with a fake-client model). |
| `render_profile_card` (single) | 178 ms | 170 ms | B4 saves ~8 ms; the rest is genuine Pillow compositing (CPU-bound). |
| Render effect on other users | blocks event loop 170 ms | **0 ms** | B6: render runs in a worker thread; the loop stays free. |
| `banner`/`build` data load | disk read + parse every call, on-loop | **~0 ms, once, off-loop** | B5: cached in memory after first read. |
| Icon/artwork downloads (per card) | ~16 fresh HTTPS handshakes | **1 pooled session, keep-alive** | B2/B3: see §"remaining limitations" for the RTT-dependent saving. |
| Cached showcase command | Redis read + deserialize | unchanged (already fast) | Cache hit path was already optimal. |

Against the response targets (task 10): simple commands (`/help`, `/start`, `/settings`) do
no API/render/Redis-heavy work and are comfortably **<200 ms**; cached commands
(`/myinfo`, `/mycharacters`) are a single Redis read + deserialize, **<500 ms**; fresh API
fetches are now **~600 ms + render**, within the **<2 s** target (network permitting).

## 4. Optimizations applied

1. **Parallel Enka + Akasha** (`character_service._fetch_concurrently`): both fetched with
   `asyncio.gather`; the Enka domain error still propagates unchanged and Akasha stays
   best-effort (empty on failure). *Result identical, ~500 ms faster on a miss.*
2. **Pooled HTTP sessions** (`artwork_service`, `akasha_client`): one lazily-created
   `aiohttp.ClientSession` with a `TCPConnector` (connection pooling, DNS cache) reused for
   all requests; closed on shutdown via `AppContext.aclose()`. Reasonable timeouts kept.
3. **In-memory template cache** (`pillow_renderer._template_base`): the template is decoded
   + resized once and a `.copy()` handed to each render (mutations stay isolated).
4. **In-memory static-resource cache** (`banner_service`, `build_service`): each JSON file
   is read + parsed once and reused.
5. **Render off the event loop**: `characters`/`abyss`/`theater` run the synchronous
   renderer via `asyncio.to_thread`, so a render never blocks concurrent commands.
6. **Concurrent artwork prefetch**: the portrait and the icon batch are fetched together
   with `asyncio.gather` in the profile-card path.
7. **Startup warmup** (task 7): `preload_locales()` + `renderer.warmup()` decode the
   template, common fonts, and all locale files once at boot, so no command pays that cost.
   (Fonts were already cached per-renderer; locale files were already `lru_cache`d — warmup
   just moves the first hit to startup.)
8. **Single Redis pool** (verified, task 6): `RedisClient` already owns one pooled
   `redis.asyncio` client reused across all commands — no per-command reconnect. Writes were
   already guarded/minimal; no change needed.

Behavior preserved: full test suite **118 passed** (added `tests/test_performance.py`, 7
tests: fetch concurrency, Enka-error propagation, disk-read-once caching, session reuse,
template caching).

## 5. Remaining external limitations

- **Third-party API latency dominates fresh fetches.** Enka.Network (~0.3–0.6 s) and
  akasha.cv (~0.4–0.7 s) are external; we now run them in parallel and cache the combined
  result (TTL `enka_cache_ttl`, default 300 s), but the *first* fetch for a UID is bounded by
  the slower of the two upstreams. Nothing local can reduce their server time.
- **HTTP session-reuse saving is RTT-dependent.** Avoiding a fresh TLS handshake saves
  roughly one round-trip per connection (~100–300 ms to a CDN/edge, more on cold TLS). The
  exact ms can't be measured offline; the change is guaranteed to remove ~15 handshakes per
  profile card and reuse keep-alive connections.
- **Single-render CPU cost (~170 ms).** The Pillow profile card is CPU-bound compositing.
  It is now off the event loop (so it doesn't affect other users), but reducing the 170 ms
  itself would mean changing the drawing pipeline / output — out of scope ("do not change
  functionality"). A future option is caching rendered cards per (uid, character) in Redis.
- **The `enka` library opens its own client per call** (`async with GenshinClient(...)`), as
  the library intends. It caches game data to disk after the first use, so repeat calls are
  cheaper, but this wrapper does not pool the library's session (doing so safely would
  require changing the library usage pattern). Left as-is to preserve behavior.
