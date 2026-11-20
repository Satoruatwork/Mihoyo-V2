# DEPLOYMENT FIX REPORT — Redis switch broke the bot

Date: 2026-07-22
Scope: restore full functionality after switching Upstash Redis databases, without
rewriting unrelated code or changing the architecture.

---

## 1. Exact root cause

`redis.asyncio.from_url()` **raises `ValueError`** (not a `RedisError`) when given a URL
whose scheme is not `redis://` / `rediss://` / `unix://` — for example the Upstash
**REST** endpoint `https://<db>.upstash.io`.

That call happens **eagerly** during startup:

```
run_polling()  →  _post_init()  →  build_app_context()
                                     └─ store = RedisStore(redis.client)   # <-- from_url() here
```

`build_app_context()` accessed `redis.client`, which lazily calls `from_url()`. The
resulting `ValueError` was **not caught** by anything (`verify()` only caught `RedisError`,
and there was no try/except around the container build). The exception propagated out of
`_post_init`, so `run_polling()` **aborted before the updater started**. Result: the
process "deploys" (import + build succeed) but then crashes during initialization and
**never polls**, so it answers no commands — exactly the reported symptom.

Reproduced against the installed `redis==8.0.1`:

| REDIS_URL                                   | from_url() result |
|---------------------------------------------|-------------------|
| `rediss://default:pw@x.upstash.io:6379`     | OK (pool built)   |
| `redis://default:pw@x.upstash.io:6379`      | OK (auto-upgraded to TLS) |
| `https://x.upstash.io` (REST URL)           | **ValueError → startup crash** |
| `https://default:TOKEN@x.upstash.io` (REST) | **ValueError → startup crash** |
| `x.upstash.io:6379` (no scheme)             | **ValueError → startup crash** |

## 2. Why the previous Upstash database worked

The old `REDIS_URL` was a proper **Redis-protocol** URL
(`rediss://default:<password>@<host>:6379`, or a `redis://` Upstash URL that the code
auto-upgrades to TLS). `from_url()` parsed it, the pool built, and `verify()`'s `ping()`
succeeded, so `_post_init` finished and polling started.

## 3. Why the new Upstash database fails

When you create a new Upstash database, the console shows **two** connection options:

* **Redis** — `rediss://default:<password>@<host>:6379`  ← the one redis-py needs
* **REST API** — `UPSTASH_REDIS_REST_URL=https://<host>.upstash.io` + a REST token

If the new DB's `REDIS_URL` was set to the **REST URL** (an `https://` value) or to a bare
`host:port`, redis-py rejects it with `ValueError` and the bot crashes in `_post_init` as
described above. (A valid-but-unreachable Redis would *not* have caused this — that path
raises `RedisError`, which was already handled as "degraded mode".) The scheme mismatch is
the trigger.

## 4. Fixes applied

All changes preserve the existing architecture (thin handlers → services → stores; single
`AppContext`; graceful Redis degradation).

**`bot/database/redis_client.py`**
- `normalize_url()` now trims whitespace/quotes, auto-upgrades Upstash `redis://` → `rediss://`,
  and adds a scheme to a bare `host:port`.
- New `validate_redis_url()` — rejects empty values, the `https://` REST endpoint, and
  unsupported schemes **with an actionable message**, and does a final `from_url()` parse
  check so failures surface at validation time, not deep in the container build.
- New `mask_url()` — log-safe URL rendering (password removed).
- `verify()` now catches **any** exception (not just `RedisError`) and logs a full
  traceback, so it can never abort startup.
- New `self_test()` — exercises **PING → WRITE → READ → DELETE** on a throwaway key and
  logs each result (`PASS`/`FAIL`); never raises.
- Constructor logs the masked connection target.

**`bot/main.py`**
- `_validate_environment()` — fails fast with a **clear, actionable** `CRITICAL` log if
  `BOT_TOKEN` or `REDIS_URL` is missing/invalid (this is what now catches the REST-URL
  mistake, instead of a silent mid-startup crash).
- `_post_init()` rewritten to be resilient and fully instrumented:
  - Step 1 asset bootstrap (guarded — never crashes on download failure),
  - Step 2 build dependency container (logged; only a genuine build failure re-raises,
    after URL validation has already ruled out the common cause),
  - Step 3 `verify()` + `self_test()` (full CRUD),
  - Step 4 persistence round-trip storing/reading back **user id, linked UID, language,
    settings**, then cleaning up the diagnostic keys,
  - Step 5 publish command menu.
  - Every step logs; every exception includes a traceback; the `AppContext` is always
    installed so handlers never `KeyError`.
- `_post_init` ends by logging **"Bot started successfully"** — the last line before PTB's
  updater begins fetching updates.
- `main()` wraps `run_polling()` with fatal-error + shutdown logging; `_post_shutdown()`
  logs pool closure.
- Command/callback handlers are still registered in `build_application()` **before**
  `run_polling()`, independent of Redis — a Redis outage cannot unregister them.

**`Dockerfile`**
- Verified every runtime file is copied: `COPY bot ./bot` includes `commands/`, `services/`,
  `api/`, `database/`, `cache/`, `renderer/`, `models/`, `utils/`, `translations/locales/*.json`
  and `resources/*.json`; `COPY assets ./assets` includes the card template and images.
- Added `PYTHONDONTWRITEBYTECODE=1`, and `mkdir -p assets/fonts assets/characters` so the
  runtime-downloaded asset dirs always have a writable target. Comments document that
  `BOT_TOKEN`/`REDIS_URL` come from the platform env, never the image.

**Tests** — `tests/test_redis_client.py` (12 cases): normalization, validation (incl. REST
rejection), masking, and a full `self_test()` CRUD round-trip on fakeredis. Suite: **111 passed**.

## 5. Remaining configuration required on the deployment platform (Railway)

The code is fixed, but the deployment must be given the **correct** value:

1. **Set `REDIS_URL` to the Upstash _Redis_ URL, not the REST URL.**
   In the Upstash console → your database → **Connect** → copy the value under **"Redis"**:
   `rediss://default:<password>@<host>.upstash.io:6379`
   Do **not** use the "REST API" `UPSTASH_REDIS_REST_URL` (`https://…`) or REST token.
2. **Set `BOT_TOKEN`** to the current @BotFather token. (Note: the previously leaked token
   should already have been rotated — see AUDIT_REPORT C1.)
3. Redeploy. In the logs you should now see, in order:
   `Environment validated …` → `Redis client configured for rediss://default:***@…` →
   `Redis connection verified (PING -> PONG)` → `Redis self-test | RESULT -> PASS` →
   `store round-trip | … -> PASS` → **`Bot started successfully`**.
   If `REDIS_URL` is still wrong, the bot now exits immediately with a `CRITICAL` line that
   explains exactly what to paste — no more silent crash.
