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
- **Statistics** — `/stats` (registered users, groups, private chats, Redis status, uptime).

## Persistence

[Redis](https://redis.io/) (Upstash-compatible) is the **primary datastore** and source of
truth for all persistent data: linked Genshin UIDs, language, per-user settings, registered
users/groups, cached API responses, and bot statistics. Account links persist across restarts;
users only re-link on `/genshinlogout` or if the data/DB is cleared. The connection is verified
at startup, auto-reconnects, and all operations degrade gracefully if Redis is briefly
unavailable (the bot never crashes).

## Architecture

```
bot/
├── commands/     # thin Telegram handlers -> delegate to services
├── services/     # business logic (no Telegram, no rendering)
├── api/          # async wrappers over enka-api / akasha-py
├── database/     # Redis client + store (primary persistent datastore)
├── cache/        # Redis-backed API response cache (JSON, TTL)
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

## Setup

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # then fill in BOT_TOKEN
```

Edit `.env` and set `BOT_TOKEN` (from [@BotFather](https://t.me/BotFather)) and
`REDIS_URL` (an Upstash Redis connection URL — `redis://` URLs are auto-upgraded to TLS).

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
