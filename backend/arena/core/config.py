"""Application settings (pydantic-settings).

Single source of truth for runtime configuration. Values are read from the
process environment (and a local ``.env`` for development). Nothing here is
user-facing, so plain English field docs are fine.

Usage::

    from arena.core import settings
    settings.database_url

The cached :func:`get_settings` accessor is provided for FastAPI dependency
injection so tests can override it cleanly.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed runtime configuration loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Service identity -------------------------------------------------
    service_name: str = Field(
        default="arenarank-api",
        description="Logical service name surfaced in logs and traces.",
    )
    environment: str = Field(
        default="development",
        description="Deployment environment: development | staging | production.",
    )

    # --- Datastores -------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://arena:arena@localhost:5432/arena",
        description="Async SQLAlchemy DSN (asyncpg driver).",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL (cache, locks, arq queues, token bucket).",
    )
    db_pool_size: int = Field(
        default=20,
        description="SQLAlchemy async engine pool size. Should be >= a worker's "
        "max_jobs so concurrent matches don't serialize on connections.",
    )
    db_max_overflow: int = Field(
        default=10,
        description="Extra connections opened past db_pool_size under burst load.",
    )

    # --- Read-path replica observability (T3.1) ---------------------------
    replica_lag_check: bool = Field(
        default=False,
        description="When true (set on the EC2 read replica), /healthz reports "
        "the age of the last logical-replication apply (pg_stat_subscription) "
        "and /meta/last-update + leaderboard updatedAt reflect the real sync "
        "timestamp instead of now().",
    )

    # --- Read-path response cache (T0.3 — arena/api/cache.py) -------------
    # Whole-JSON-response TTLs per public GET route, seconds. 0 disables the
    # route's cache. These same values become the s-maxage of T1.1.
    cache_ttl_leaderboard_s: int = Field(
        default=60, description="Response-cache TTL for GET /leaderboard."
    )
    cache_ttl_champions_s: int = Field(
        default=300, description="Response-cache TTL for GET /champions*."
    )
    cache_ttl_meta_s: int = Field(
        default=300,
        description="Response-cache TTL for GET /meta/activity|records|last-update.",
    )
    cache_ttl_players_search_s: int = Field(
        default=30, description="Response-cache TTL for GET /players/search."
    )
    cache_ttl_match_s: int = Field(
        default=3600,
        description="Response-cache TTL for GET /match/{id} (finished matches are immutable).",
    )
    cache_ttl_player_s: int = Field(
        default=60, description="Response-cache TTL for GET /player/*."
    )
    cache_ttl_tournaments_s: int = Field(
        default=300, description="Response-cache TTL for GET /tournaments*."
    )

    # --- External integrations -------------------------------------------
    riot_api_key: str = Field(
        default="",
        description="Riot Games API key. Empty in dev; required for ingestion.",
    )
    # Riot rate-limit buckets (see arena/riot/rate_limit.py). The portal for
    # this key lists PER-METHOD limits only (match-v5: 2000/10s for matches/{id}
    # AND another 2000/10s for by-puuid/ids; account-v1: 1000/60s). The old
    # hardcoded app-wide 500/10s funnel was an assumption, not a Riot limit —
    # it capped the whole client at 50 rps. 0 = no app-wide bucket. If a future
    # key DOES show an app-wide limit in the portal, set these to match it;
    # 429 handling (Retry-After + circuit breaker) remains the backstop either way.
    riot_app_bucket_capacity: int = Field(
        default=0,
        description="App-wide Riot bucket capacity; 0 disables the app bucket "
        "(this key has per-method limits only).",
    )
    riot_app_bucket_refill_seconds: float = Field(
        default=10.0,
        description="Refill window (seconds) for the app-wide bucket, when enabled.",
    )
    riot_match_v5_bucket_capacity: int = Field(
        default=2000,
        description="Capacity of EACH match-v5 method bucket (ids list and match "
        "detail are separate Riot limits of 2000/10s each).",
    )
    riot_match_v5_bucket_refill_seconds: float = Field(
        default=10.0,
        description="Refill window (seconds) for each match-v5 method bucket.",
    )
    riot_match_cache_ttl_seconds: int = Field(
        default=24 * 60 * 60,
        description="TTL (segundos) do cache de payloads de match no Redis "
        "(riot:match:*). Payloads Arena são ~135KB cada; num box pequeno o cache "
        "24h estoura a memória do Redis. Reduza (ex.: 600 = 10min) em produção — "
        "o payload só é lido no intervalo fetch→rate, nunca depois. Default 24h "
        "preserva o comportamento de dev/backfill.",
    )

    # --- Match ingestion window ------------------------------------------
    match_min_started_at_ms: int = Field(
        default=0,
        description="Ignore matches whose Riot gameStartTimestamp (epoch ms) is "
        "strictly before this instant. 0 disables the cutoff. Enforced in the "
        "worker write-path funnel (match_pipeline) so every consumer — standard, "
        "priority, sweep/bulk — honors the same launch window. A match with an "
        "unknown start (started_at_ms == 0) is NOT dropped. "
        "Example: 1784365200000 = 2026-07-18T09:00:00Z (06:00 BRT).",
    )

    # --- Admin / operator auth -------------------------------------------
    admin_api_key: str = Field(
        default="",
        description="Shared key gating /admin/* + tournament-admin endpoints. "
        "Empty => admin access disabled (fail closed).",
    )

    # --- InfinitePay (tournament entry payments) -------------------------
    # Checkout Links API is handle-only (no client id/secret). The handle is a
    # semi-public InfiniteTag; the webhook token is the actual secret. See
    # docs/superpowers/specs/2026-07-21-infinitepay-inscricao-pix-design.md.
    infinitepay_handle: str = Field(
        default="",
        description="InfiniteTag (sem '$') usada na Checkout Links API. Empty => "
        "criação de cobrança desabilitada (fail closed).",
    )
    infinitepay_base_url: str = Field(
        default="https://api.checkout.infinitepay.io",
        description="Base URL da Checkout Links API (create link / payment_check).",
    )
    infinitepay_webhook_token: str = Field(
        default="",
        description="Segredo não-adivinhável embutido no PATH do webhook InfinitePay "
        "(/tournament/pay/webhook/<token>). Defesa em profundidade além do payment_check.",
    )
    tournament_entry_fee_cents: int = Field(
        default=500,
        description="Taxa de inscrição por jogador, em centavos (R$5,00 = 500).",
    )
    tournament_payment_ttl_s: int = Field(
        default=300,
        description="TTL (segundos) de um slot reservado não-pago antes de expirar (5 min).",
    )
    public_base_url: str = Field(
        default="https://arenarank.lol",
        description="Base URL pública do app (frontend), usada p/ montar o redirect_url "
        "das cobranças InfinitePay. https válido (InfinitePay valida o formato na criação).",
    )

    # --- Worker sweep + bulk-processor tuning ----------------------------
    sweep_interval_minutes: int = Field(
        default=5, description="Standard sweep tick interval (minutes). Must divide 60.")
    priority_sweep_interval_minutes: int = Field(
        default=5, description="Priority sweep tick interval (minutes). Must divide 60.")
    bulk_processor_interval_minutes: int = Field(
        default=2, description="Bulk processor tick interval (minutes). Must divide 60.")
    sweep_batch_size: int = Field(
        default=100, description="Tracked players fetched per standard sweep tick (DB page).")
    priority_sweep_batch_size: int = Field(
        default=200, description="Priority seeds processed per priority sweep tick.")
    sweep_matches_per_player: int = Field(
        default=10, description="Riot match ids fetched per player per sweep tick.")
    sweep_fetch_concurrency: int = Field(
        default=16,
        description="Concurrent Riot id-list calls inside one sweep tick (local "
        "semaphore). The client's Redis token bucket remains the hard rate "
        "ceiling; this only stops serial awaits from leaving the budget idle.")
    bulk_batch_size: int = Field(
        default=50, description="Max match ids drained+processed per bulk processor tick.")
    bulk_concurrency: int = Field(
        default=10, description="Semaphore width for parallel process_match in a bulk tick.")
    bulk_max_seconds_per_tick: int = Field(
        default=45,
        description="Wall-clock budget for draining the sweep pending lists in "
        "ONE tick invocation. Without this, bulk_process_tick ran exactly one "
        "bulk_batch_size batch per tick regardless of backlog size, capping "
        "real throughput at bulk_batch_size / bulk_processor_interval_minutes "
        "even though individual matches are I/O-bound and process far faster. "
        "Now it loops batches back-to-back until the pending lists are empty "
        "or this budget is spent. Keep comfortably under "
        "bulk_processor_interval_minutes * 60 so the tick lock is released "
        "before the next scheduled tick fires.",
    )
    sweep_pending_high_watermark: int = Field(
        default=50_000,
        description="Standard sweep holds when the combined sweep pending-list depth "
        "reaches this (the sweep pipeline's own backpressure; priority sweep is exempt).")
    priority_top_n: int = Field(
        default=1000,
        description="Top-N players (by CR) the priority sweep seeds from the DB each tick, "
        "independent of the Redis TOP_PLAYERS_SET cache.")
    priority_sweep_skip_dedup: bool = Field(
        default=False,
        description="Priority sweep bypasses the seen-matches dedup and re-enqueues "
        "recent ids even if already discovered. For catch-up runs where the Top-N's "
        "matches are buried in the standard pending backlog: reprocessing is safe "
        "(matches.processed idempotency makes repeats cheap no-ops). Keep False in "
        "normal operation — every tick re-enqueues the same recent ids while True.")

    # --- Live-queue sweep + session re-arm + rotation-detection sample ------
    arena_live_queue_ids: str = Field(
        default="1740,1750",
        description="CSV of Arena queue ids currently in rotation. The sweep "
        "polls ONLY these (one ids call per live queue per player) instead of "
        "every historical Arena queue id — 1700/1710 have zero post-cutoff "
        "matches, so polling them was pure waste. Rotation day: update this "
        "env and restart the sweep workers. Empty/unparsable => falls back to "
        "the full ARENA_QUEUE_IDS set.",
    )
    deep_sample_per_tick: int = Field(
        default=2,
        description="Players per standard sweep tick that ALSO get one "
        "UNFILTERED (no ?queue=) ids call bounded by deep_sample_window_seconds "
        "— the rotation-detection safety net. A brand-new Arena queue id "
        "surfaces here, flows through the CHERRY parser fallback and lands in "
        "matches.queue_id where operators can spot it. 0 disables.",
    )
    deep_sample_window_seconds: int = Field(
        default=26 * 60 * 60,
        description="startTime lookback for the unfiltered deep-sample call. "
        "Slightly over a day so the rotating sample never leaves a gap.",
    )
    rearm_enabled: bool = Field(
        default=True,
        description="Session re-arm: after a match is PROCESSED, its "
        "participants are scheduled for a quick re-poll (they are provably "
        "in an Arena session right now). Gives ~rearm_delays_seconds[0] "
        "discovery latency for follow-up matches of an active session.",
    )
    rearm_delays_seconds: str = Field(
        default="180,480,900",
        description="CSV re-poll backoff per consecutive miss. A hit resets "
        "to the first delay; rearm_max_misses consecutive empty polls end "
        "the session tracking.",
    )
    rearm_max_misses: int = Field(
        default=3,
        description="Consecutive empty re-polls before a player is dropped "
        "from the re-arm schedule (session considered over). With the default "
        "delays this tracks a player for ~26min after their last processed "
        "match — enough to cover one full Arena game in progress.",
    )
    rearm_batch_size: int = Field(
        default=500,
        description="Max due players drained from the re-arm schedule per "
        "rearm tick (1/min) — caps the burst at ~batch × live queues calls.",
    )
    rearm_recency_seconds: int = Field(
        default=7200,
        description="Only re-arm participants of matches that ENDED within "
        "this window. Keeps backlog catch-up (old matches processed late) "
        "from scheduling pointless re-polls of players long offline.",
    )

    # --- Outage reconciliation ---------------------------------------------
    # The steady-state sweep only ever asks Riot for a player's newest
    # sweep_matches_per_player ids, so a worker outage longer than that leaves
    # a silent gap. scheduler.heartbeat_tick detects the gap on restart
    # (last heartbeat vs now) and sweep.reconcile_tick performs one bounded,
    # start_time-windowed catch-up sweep to fill it — no operator action needed.
    reconcile_gap_threshold_seconds: int = Field(
        default=900,
        description="If the scheduler's heartbeat is older than this when a "
        "tick runs, the gap is treated as an outage and a reconciliation "
        "window is opened. Must comfortably exceed a normal deploy/restart.",
    )
    reconcile_max_gap_seconds: int = Field(
        default=7 * 24 * 60 * 60,
        description="Safety cap on how far back a reconciliation window looks "
        "even if the real outage was longer — bounds worst-case Riot API "
        "spend after a multi-day outage. Anything older needs a manual "
        "`scripts/backfill.py --mode refresh` run.",
    )
    reconcile_matches_per_player: int = Field(
        default=50,
        description="Riot match ids fetched per page per player per queue "
        "during a reconciliation pass (vs. sweep_matches_per_player's tail-only "
        "fetch, this is start_time-windowed so it actually covers the gap).",
    )
    reconcile_max_pages_per_player: int = Field(
        default=5,
        description="Pagination cap per player per queue during reconciliation. "
        "Hitting this cap is logged (reconcile.player_cap_hit) rather than "
        "silently truncated — an extremely active player mid-gap may still "
        "need a manual backfill for the remainder.",
    )
    reconcile_batch_size: int = Field(
        default=200,
        description="Tracked players fetched per DB page while scanning the "
        "full player set for a reconciliation pass (unlike the steady-state "
        "sweep, this is a one-shot full scan, not a persistent rotating cursor).",
    )

    @property
    def live_queue_ids(self) -> tuple[int, ...]:
        """Parsed arena_live_queue_ids; falls back to all known Arena queues."""
        try:
            ids = tuple(
                int(part) for part in self.arena_live_queue_ids.split(",") if part.strip()
            )
        except ValueError:
            ids = ()
        if ids:
            return ids
        from arena.riot.arena import ARENA_QUEUE_IDS

        return tuple(sorted(ARENA_QUEUE_IDS))

    @property
    def rearm_delays(self) -> tuple[int, ...]:
        """Parsed rearm_delays_seconds with a safe fallback."""
        try:
            delays = tuple(
                int(part) for part in self.rearm_delays_seconds.split(",") if part.strip()
            )
        except ValueError:
            delays = ()
        return delays or (180, 480, 900)

    @field_validator(
        "sweep_interval_minutes",
        "priority_sweep_interval_minutes",
        "bulk_processor_interval_minutes",
    )
    @classmethod
    def _interval_divides_60(cls, v: int) -> int:
        """Cron uses minute=range(0,60,X); a non-divisor leaves an irregular wrap gap."""
        if v <= 0 or 60 % v != 0:
            raise ValueError("worker interval minutes must be a positive divisor of 60")
        return v

    # --- HTTP / CORS ------------------------------------------------------
    # (T1.1: CORS fixo em "*" sem credenciais — necessário p/ o edge cache da
    # Cloudflare, que ignora Vary. A antiga allowlist CORS_ORIGINS morreu.)

    # --- Observability ----------------------------------------------------
    log_level: str = Field(
        default="INFO",
        description="Root log level: DEBUG | INFO | WARNING | ERROR | CRITICAL.",
    )
    otel_exporter_otlp_endpoint: str | None = Field(
        default=None,
        description="OTLP collector endpoint, e.g. http://localhost:4317. "
        "When unset, telemetry stays a no-op.",
    )
    otel_traces_enabled: bool = Field(
        default=False,
        description="Master switch for span export. Off by default for local runs.",
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton (cached)."""
    return Settings()


# Eagerly-constructed convenience handle for non-DI call sites.
settings: Settings = get_settings()
