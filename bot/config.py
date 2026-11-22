"""Application configuration.

All settings are read from environment variables (or a local ``.env`` file) via
``pydantic-settings``. Nothing here is hardcoded so the same code runs in dev and prod.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root (two levels up from this file: bot/config.py -> repo root).
ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Typed application settings loaded from the environment / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Telegram
    bot_token: str = ""

    # Bot administrators (comma/space-separated Telegram user ids). Only these users may
    # run owner commands such as /broadcast. Empty = no admins (owner commands are dormant).
    admin_ids: str = ""

    # Optional single fallback HoYoLAB cookie. Per-user login (/hoyologin) is now the primary
    # path, so this is normally left empty. Kept for compatibility. Never commit a real value.
    hoyolab_cookie: str = ""

    # Optional dedicated encryption key for stored HoYoLAB sessions (/hoyologin). When empty,
    # the key is derived from BOT_TOKEN instead (see ``session_secret``), so per-user login
    # works out of the box. Set this only if you want session encryption independent of the
    # bot token. Never commit a real value — keep it in the environment only.
    hoyolab_secret: str = ""

    # --- Database backend selection ---------------------------------------
    # Which database driver to use for persistent storage. Supported values:
    #   redis      — Upstash-compatible Redis (default, for backwards compat)
    #   mongodb    — MongoDB / Atlas (requires MONGODB_URL)
    #   postgres   — any Postgres (Supabase, Neon, self-hosted; requires POSTGRES_URL / DATABASE_URL)
    #   supabase   — alias for postgres
    #   memory     — in-process/memory + local file fallback (useful for tests/dev)
    # If left empty, it is inferred from which URL is set (backwards compatible).
    database_backend: str = Field(default="", validation_alias=AliasChoices("DATABASE_BACKEND", "database_backend", "DB_BACKEND", "db_backend", "DATABASE_TYPE", "database_type"))

    # --- Redis — the primary persistent datastore (Upstash-compatible). ----
    # Upstash redis:// URLs are auto-upgraded to TLS (rediss://) by the Redis client.
    redis_url: str = Field(default="", validation_alias=AliasChoices("REDIS_URL", "redis_url", "UPSTASH_REDIS_URL", "upstash_redis_url"))

    # Redis fast-fail tuning. Kept low so that when Redis is unreachable a command fails
    # in a couple of seconds (with a clear message) instead of hanging on long timeouts.
    # Upstash round-trips are well under a second, so these are comfortably safe.
    redis_connect_timeout: float = 4.0
    redis_socket_timeout: float = 4.0
    redis_retries: int = 1
    # After a Redis failure, bypass it for this many seconds (circuit breaker) so commands
    # don't repeatedly wait on a dead connection — they use the local fallback instead.
    redis_breaker_cooldown: float = 30.0

    # --- MongoDB -----------------------------------------------------------
    mongodb_url: str = Field(default="", validation_alias=AliasChoices("MONGODB_URL", "mongodb_url", "MONGO_URL", "mongo_url", "MONGODB_URI", "mongodb_uri", "MONGO_URI", "mongo_uri"))
    mongodb_db: str = Field(default="mihoyo", validation_alias=AliasChoices("MONGODB_DB", "mongodb_db", "MONGO_DB", "mongo_db", "MONGODB_DATABASE", "mongodb_database"))

    # --- Postgres / Supabase / Neon ---------------------------------------
    # Accepts any of the common env names; all resolve to the same DSN.
    # Both upper-case (env var) and lower-case (python kwarg) variants are listed.
    postgres_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "POSTGRES_URL", "postgres_url",
            "POSTGRES_DSN", "postgres_dsn",
            "DATABASE_URL", "database_url",
            "DATABASE_URI", "database_uri",
            "SUPABASE_URL", "supabase_url",
            "SUPABASE_DB_URL", "supabase_db_url",
            "SUPABASE_DATABASE_URL", "supabase_database_url",
            "NEON_DATABASE_URL", "neon_database_url",
            "POSTGRESQL_URL", "postgresql_url",
        ),
    )

    # Local fallback store: keeps logins/settings working when primary DB is unreachable.
    # Relative paths resolve under the repo root. Point at a mounted volume for durability.
    local_store_path: str = "data/local_store.json"

    # Localization
    default_language: str = "en"

    # Caching (seconds)
    enka_cache_ttl: int = 300
    akasha_cache_ttl: int = 600

    # Game-metadata freshness. enka.py downloads its character/text metadata once and then
    # never refreshes it, which is what made newly released characters unresolvable. These
    # bound how long that metadata may go without an update, so a new character starts
    # working on its own once upstream publishes it — no redeploy, no code change.
    enka_assets_ttl: int = 21_600            # refresh enka.py's on-disk metadata every 6h
    enka_assets_force_cooldown: int = 900    # min gap between refreshes forced by an unknown id
    enka_metadata_ttl: int = 21_600          # lifetime of the upstream metadata used as fallback

    # Local snapshot of resolved character metadata (fallback when upstream is unreachable).
    # Relative paths resolve under the repo root.
    character_meta_path: str = "data/character_meta.json"

    # Assets
    assets_dir: str = "assets"

    # Logging
    log_level: str = "INFO"

    # ------------------------------------------------------------------
    @property
    def resolved_backend(self) -> str:
        """Canonical backend name inferred from ``DATABASE_BACKEND`` or populated URLs."""
        raw = (self.database_backend or "").strip().lower()
        # Normalise aliases
        aliases = {
            "redis": "redis",
            "mongodb": "mongodb", "mongo": "mongodb", "atlas": "mongodb",
            "postgres": "postgres", "postgresql": "postgres", "psql": "postgres",
            "supabase": "postgres", "neon": "postgres",
            "memory": "memory", "local": "memory", "file": "memory", "inmemory": "memory",
        }
        if raw in aliases:
            return aliases[raw]
        if raw:
            return raw  # unknown — let factory produce a helpful error
        # Not set — infer from which URL is present (backwards compat: redis wins)
        if self.postgres_url.strip():
            return "postgres"
        if self.mongodb_url.strip():
            return "mongodb"
        if self.redis_url.strip():
            return "redis"
        return "redis"  # default so existing deployments keep working

    @property
    def database_url(self) -> str:
        """The URL/DSN for the resolved backend (convenience for logging/factory)."""
        backend = self.resolved_backend
        if backend == "mongodb":
            return self.mongodb_url
        if backend == "postgres":
            return self.postgres_url
        if backend == "redis":
            return self.redis_url
        return ""

    @property
    def session_secret(self) -> str:
        """Key material for encrypting stored user sessions (/hoyologin).

        Uses ``HOYOLAB_SECRET`` when set; otherwise falls back to ``BOT_TOKEN`` — which is
        already a stable, required secret — so per-user login works without extra config.
        Trade-off: if you rotate the bot token, previously stored logins become unreadable and
        users simply re-run /hoyologin. Set a dedicated ``HOYOLAB_SECRET`` to avoid that.
        """
        return self.hoyolab_secret or self.bot_token

    @property
    def admin_id_set(self) -> set[int]:
        """Parsed set of admin Telegram user ids (tolerant of commas/spaces + junk)."""
        out: set[int] = set()
        for part in self.admin_ids.replace(",", " ").split():
            try:
                out.add(int(part))
            except ValueError:
                continue
        return out

    @property
    def assets_path(self) -> Path:
        """Absolute path to the assets root directory."""
        p = Path(self.assets_dir)
        return p if p.is_absolute() else (ROOT_DIR / p)

    @property
    def translations_path(self) -> Path:
        """Absolute path to the bundled locale files."""
        return ROOT_DIR / "bot" / "translations" / "locales"

    @property
    def local_store_file(self) -> Path:
        """Absolute path to the local fallback store file."""
        p = Path(self.local_store_path)
        return p if p.is_absolute() else (ROOT_DIR / p)

    @property
    def character_meta_file(self) -> Path:
        """Absolute path to the local character-metadata snapshot."""
        p = Path(self.character_meta_path)
        return p if p.is_absolute() else (ROOT_DIR / p)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton settings instance."""
    return Settings()
