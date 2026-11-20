# AUDIT REPORT — Mihoyo- (Genshin Impact Telegram Bot)

Date: 2026-07-22
Auditor: automated recovery/QA pass
Method: full dependency install in a clean venv, import smoke test, dependency-graph
build with `fakeredis`, full `pytest` run, and a fan-out static audit of every module
(handlers, services/API, renderer/models/utils) cross-checked against the *installed*
`enka==2.5.20` source.

Baseline before changes: `bot.main` imports cleanly; `91 passed` in the test suite; the
`AppContext` dependency graph builds without error. The codebase is defensive and well
structured — most common bug classes (un-awaited coroutines, mutable dataclass defaults,
missing None guards, callback-pattern/`callback_data` mismatches, i18n placeholder
mismatches) are already handled correctly.

---

## CRITICAL

### C1 — Live Telegram bot token committed to the repository
- **File:** `.env.example` (committed in `e1695c8 "Include bot token in .env.example for reference"`)
- **Issue:** A real, working `BOT_TOKEN=8852…` (redacted here) is committed in git history.
  A bot token grants full control of the bot. "Private repo" is not a safe control: the
  token lives in history, is copied to every clone, and is unrecoverable if the repo is
  ever made public or a collaborator/token is compromised.
- **Recommendation:** Revoke/rotate the token immediately via @BotFather, blank the value
  in `.env.example` (keep only the placeholder), and — ideally — purge it from history
  (`git filter-repo`) after rotation. **Not auto-fixed** (requires owner action in BotFather;
  history rewrite is destructive and must be the owner's decision).
- **Status:** OPEN — flagged for owner action.

---

## HIGH

### H1 — Weapon main/sub stats and weapon type never populate (FIXED)
- **File:** `bot/api/enka_client.py` → `_map_weapon()`
- **Root cause:** The mapper read `main_stat`, `sub_stat`, and `type`/`weapon_type`
  attributes from enka's `Weapon`. In `enka==2.5.20` the `Weapon` model has **no** such
  attributes — its fields are `item_id, refinement, level, ascension, icon, item_type,
  name, rarity, stats`, where `stats` is a `list[Stat]` (main = `FIGHT_PROP_BASE_ATTACK`,
  plus one secondary). `item_type` is always the constant `ITEM_WEAPON`, so it never
  contained the weapon class either.
- **Effect:** `weapon_type`, `main_stat_name/value`, `sub_stat_name/value` were **always
  `None`**. The renderer draws `weapon_type` on the character card
  (`pillow_renderer.py:323`), so the weapon type never appeared; the stat fields were dead,
  and were cached as `None` on every showcase fetch.
- **Fix:** Read the `stats` list; identify the main stat by
  `type.name == "FIGHT_PROP_BASE_ATTACK"` (order-independent), take the other stat as the
  sub stat, and derive the weapon class from the icon filename
  (`UI_EquipIcon_Sword_… / _Claymore_ / _Pole_ / _Bow_ / _Catalyst_`), which is stable and
  the only place the class is exposed in 2.5.20.
- **Evidence:** Reproduced (all `None` before) → fixed (Sword / Base ATK 674.0 / CRIT DMG
  44.1 after). 3 regression tests added; full suite `94 passed`; cache JSON round-trip
  preserves the populated fields. See `context.txt` → Testing History.
- **Status:** FIXED & VERIFIED.

---

## MEDIUM

### M1 — Asset resolver fails for names containing a dot in the stem (FIXED)
- **File:** `bot/assets/loader.py` → `resolve()`
- **Issue:** For a key like `char_1.2`, `Path.suffix` is `.2`, so the resolver stripped it
  and only probed `char_1.png/.webp/…`, never `char_1.2.png`. Such an asset could never be
  found and silently fell back to the placeholder.
- **Fix:** Only treat a trailing `.xxx` as an extension when it is in the known image
  extension set (`_EXTENSIONS`); otherwise the whole name is used as the stem so
  dotted keys resolve correctly.
- **Evidence:** New regression test `test_resolve_handles_dotted_stem` — resolves
  `char_1.2` and `char_1.2.png` to the real file.
- **Status:** FIXED & VERIFIED.

## LOW

- **L1 — `abyss_service.py` `max_floor` formatting (FIXED):** `f"{floor}-{chamber}" if floor
  and chamber` degraded a legitimate `chamber == 0` to floor-only. Rewritten to use explicit
  `is not None` checks. Regression test `test_max_floor_chamber_zero_is_preserved` added
  (`9-0` is now preserved). FIXED.
- **L2 — Loaded assets are force-`resize()`d to a square** (`loader.py`), distorting
  non-square art (no cover-fit). Visual only. OPEN (left intentionally — sized slots are
  called with explicit dimensions by design; cover-fit is a layout decision for later).
- **L3 — `pillow_renderer.py:286` `getpixel(...)[:3]`** assumes an indexable pixel; safe
  today because `base` is always converted to RGBA. Latent fragility only. OPEN.
- **L4 — Dead/misleading constant** `characters.py CALLBACK_PREFIX = "gsc"` (unused; the
  real handler pattern is `^(list|char|page|back|noop)\|`). Removed. FIXED.
- **L5 — `akasha-py` dependency is unused:** `akasha_client.py` calls `akasha.cv` via raw
  `aiohttp` (intentional — the pip client's UA gets 403). The declared dependency could be
  dropped. OPEN.

### New this session (same truthiness-vs-None anti-pattern as L1)

- **N1 — `akasha_client.py` `top_percent` (FIXED):** `(rank / total * 100.0) if (rank and
  total) else None` dropped a legitimate `rank == 0` (best possible rank) to `None` and
  relied on truthiness to avoid a divide-by-zero. Rewritten to `rank is not None and total
  is not None and total != 0`, which preserves `rank == 0` (→ `0.0`) and still guards the
  zero divisor. FIXED.
- **N2 — `commands/account.py` `/myinfo` abyss line (FIXED):** `if p.abyss_floor and
  p.abyss_chamber` hid the abyss line when either value was `0` (same pattern as L1).
  Changed to explicit `is not None` checks. FIXED.

---

## Verified correct (checked, no action needed)
- Callback routing: `callbacks.encode()` output matches the `CallbackQueryHandler` patterns;
  settings/language patterns ordered specific-first; ownership gate (group=-2) passes owners
  and owner-less callbacks through and blocks non-owners.
- Handler ordering in `main.py` (gate -2, tracking -1, commands/callbacks 0).
- enka/akasha async lifecycle (`async with` per call), argument parsing, awaits.
- Redis client/store/cache: graceful degradation on `RedisError`, correct key namespacing
  and TTL fallback, TLS auto-upgrade for Upstash URLs.
- Serialization round-trip for the full `Showcase` graph.
- i18n per-key fallback and `str.format` guarding; no mutable dataclass defaults.
