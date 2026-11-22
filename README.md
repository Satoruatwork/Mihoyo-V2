# Mihoyo- — Genshin Impact Telegram Bot

A premium, **Genshin Impact–only** Telegram bot. It links a player's Genshin UID and retrieves
public account information, showcased characters, builds, rankings, Spiral Abyss data,
Imaginarium Theater data, banner information, and build recommendations via public APIs
([Enka.Network](https://enka.network/) and [Akasha System](https://akasha.cv/)).

> This repository contains **Genshin Impact features only**. There is no Honkai: Star Rail
> or Zenless Zone Zero functionality.

This is the **backend foundation** phase — the architecture for account linking, data retrieval,
localization, caching, error handling, dynamic asset loading, and an image-rendering abstraction.
Premium UI / final image layouts are a later phase and can be added without refactoring.

## Features (this phase)

- **Account system** — link once with `/genshinlogin <UID>`, stored per Telegram user.
- **Character showcase** — `/mycharacters` (alias `/myc`) with inline character buttons,
  paging, callback navigation, and "back" without rerunning the command; `/inspect <UID>`
  for arbitrary profiles.
- **Full character details** — level, constellation, weapon (+ refinement & level), talents,
  artifacts + substats, and the complete stat block (HP, ATK, DEF, Crit Rate, Crit DMG,
  Energy Recharge, Elemental Mastery, and more). Akasha rank / top % / leaderboard position
  when available.
- **Spiral Abyss** — `/abyss`, `/preabyss`, `/abysscard`, `/preabysscard`.
- **Imaginarium Theater** — `/theater`, `/theatercard`.
- **Banners** — `/banner`.
- **Build guide** — `/build_guide`.
- **Localization** — `/language` (English, Spanish, Italian, Japanese, Chinese Simplified),
  English default, automatic per-key fallback.
- **Settings** — `/settings`.
- **Statistics** — `/stats` (registered users, groups, private chats, DB status, uptime).

## Persistence

The bot's persistence layer is **pluggable** — pick the database that fits your deployment.
All backends implement the same `UserStore`/`Cache`/`DatabaseClient` contracts, so switching
is a one-line env change with no code changes.

| `DATABASE_BACKEND` | Env URL | Provider | Notes |
|---|---|---|---|
| `redis` *(default)* | `REDIS_URL` | Redis / Upstash | Original, auto-upgrades `redis://` → `rediss://` for Upstash TLS |
| `mongodb` | `MONGODB_URL` | MongoDB / Atlas | Needs `MONGODB_DB` (default `mihoyo`) |
| `postgres` | `POSTGRES_URL` / `DATABASE_URL` / `SUPABASE_URL` | Postgres / Supabase / Neon | Any Postgres-compatible URI works |
| `memory` | — | Local file + in-memory cache | Dev/test only; data lives in `data/local_store.json` |

Set `DATABASE_BACKEND` and the matching URL in `.env`; the other URLs are ignored.
If `DATABASE_BACKEND` is omitted it is inferred from which URL is set (backwards compatible
with existing `REDIS_URL`-only deployments).

All operations degrade gracefully if the primary DB is briefly unavailable (the bot never
crashes). A local JSON fallback (`data/local_store.json`) keeps logins/settings working
until the remote DB recovers, and a circuit breaker avoids hammering a downed backend.

**Examples:**

```bash
# Redis (Upstash) — default
DATABASE_BACKEND=redis
REDIS_URL=rediss://default:<password>@<host>.upstash.io:6379

# MongoDB Atlas
DATABASE_BACKEND=mongodb
MONGODB_URL=mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB=mihoyo

# Postgres / Supabase — copy the Connection String → URI from Supabase Dashboard
DATABASE_BACKEND=postgres
POSTGRES_URL=postgresql://user:pass@db.supabase.co:5432/postgres
# DATABASE_URL and SUPABASE_URL are aliases — any one works

# Local dev without a remote DB
DATABASE_BACKEND=memory
```

To verify your database is reachable before deploying:

```bash
python scripts/check_db.py          # reads .env / env vars
# or explicitly:
REDIS_URL='rediss://...' python scripts/check_db.py
```

Legacy alias `scripts/check_redis.py` still works and delegates to `check_db.py`.

## Architecture

```
bot/
├── commands/     # thin Telegram handlers -> delegate to services
├── services/     # business logic (no Telegram, no rendering)
├── api/          # async wrappers over enka-api / akasha-py
├── database/     # pluggable stores (redis / mongo / postgres) + local fallback + factory
├── cache/        # pluggable caches (redis / mongo / postgres / memory) — JSON, TTL
├── renderer/     # Renderer abstraction + Pillow backend (placeholder layouts)
├── models/       # framework-agnostic domain dataclasses
├── assets/       # dynamic AssetLoader with placeholder fallback
├── translations/ # centralized JSON locales + i18n loader
└── utils/        # logging, domain errors, callback encoding
assets/           # artwork/icons/frames added manually later
```

Business logic is separated from rendering, all external requests are async, and API
responses are cached to respect rate limits. The bot never crashes on API failures,
private/hidden profiles, empty showcases, missing data, rate limits, or timeouts.

### Adding a new database backend

1. Implement `UserStore` + `DatabaseClient` in `bot/database/<my_backend>_store.py`
   (and `Cache` in `bot/cache/<my_backend>_cache.py` if the backend should also cache).
   See `bot/database/interfaces.py` / `bot/cache/interfaces.py` for the contracts,
   and `bot/database/store.py` (Redis) or `bot/database/mongo_store.py` as references.
2. Add a `_build_<my_backend>` helper in `bot/database/factory.py` and register the
   name in `SUPPORTED_BACKENDS` + `describe_backend` / `validate_backend_config`.
3. Add env vars in `bot/config.py` (with `AliasChoices` so common names all work)
   and document them in `.env.example` + this README.
4. Add tests in `tests/test_<my_backend>.py` (use `mongomock-motor` / `fakeredis`-style fakes).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # then fill in BOT_TOKEN and your DB URL
```

Edit `.env` and set `BOT_TOKEN` (from [@BotFather](https://t.me/BotFather)) and your
chosen database URL (see Persistence above). Only the driver for your chosen
`DATABASE_BACKEND` needs extra install — `redis` works out of the box, `motor` for
MongoDB, `asyncpg` for Postgres/Supabase are optional and listed in `requirements.txt`.

## Run

```bash
python -m bot.main
```

## Test

```bash
pytest
```

## Adding a language

Drop a new file in `bot/translations/locales/<code>.json` (copy `en.json` and translate).
Register its display name/flag in `bot/translations/i18n.py`. Missing keys fall back to English.

## Adding assets

Place files under the matching `assets/<category>/` directory. They are resolved dynamically by
key; a missing asset falls back to a placeholder instead of crashing.
