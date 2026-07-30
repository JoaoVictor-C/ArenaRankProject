"""Queue names, Redis keys, eligibility filters, and pressure-mode knobs.

Single source of truth shared by ingestion, processor, and scheduler so the
producer and consumer never drift on queue names or dedup-set keys.

Two arq queues back the priority lanes from proposal section 13.1:

* ``arena:priority`` — any Top-1000 player is involved (sub-5-min SLA, §3.4).
* ``arena:standard`` — everything else.

A third logical lane, the **DLQ** (``arena:dlq``), is a Redis list the processor
pushes to after a job exhausts its retries (proposal section 6.3 / 14.1).

Match-eligibility filtering (proposal section 13.2 "Validate filters") is applied
twice on purpose: cheaply at ingestion from the lightweight match-id metadata we
already have, and authoritatively at processing time once the full match payload
is fetched. The constants live here so both stages agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from arena.riot.arena import ARENA_QUEUE_DUOS, ARENA_QUEUE_IDS

# ---------------------------------------------------------------------------
# arq queue names (priority lanes) + DLQ
# ---------------------------------------------------------------------------

#: Priority arq queue — a Top-1000 player participated (sub-5-min update SLA).
PRIORITY_QUEUE: Final[str] = "arena:priority"

#: Standard arq queue — the default lane for everyone else.
STANDARD_QUEUE: Final[str] = "arena:standard"

#: Dead-letter list. Jobs land here (as JSON) after exhausting retries.
DLQ_KEY: Final[str] = "arena:dlq"

#: The processor entrypoint name. Must match the registered function name so
#: ``enqueue_job`` on the ingestion side targets the right coroutine.
PROCESS_MATCH_TASK: Final[str] = "process_match"


# ---------------------------------------------------------------------------
# Redis keys (dedup set, processed flag, locks, pub/sub, ingestion cursor)
# ---------------------------------------------------------------------------

#: ZSET of Riot match ids already claimed for processing (ingestion dedup,
#: §13.1). Member = riot match id, score = epoch second it was claimed.
#:
#: This used to be a plain SET (``arena:seen_matches``) whose TTL was refreshed
#: with ``EXPIRE`` on the WHOLE key every time a tick found anything fresh. On a
#: live system that meant the key never actually expired, so the "a re-discovered
#: id is re-checked, not lost" guarantee below never fired and a claimed-then-
#: dropped id was invisible to discovery FOREVER. A sorted set gives real
#: per-member ageing (``ZREMRANGEBYSCORE``) and keeps the key bounded. New key
#: name because the type changed — reusing the old one would raise WRONGTYPE
#: against a live Redis.
SEEN_MATCHES_ZSET: Final[str] = "arena:seen_matches:z"

#: TTL (seconds) applied to dedup membership; 24h matches the Riot match cache
#: TTL (proposal section 9.3) so a re-discovered id is re-checked, not lost.
SEEN_MATCH_TTL_SECONDS: Final[int] = 24 * 60 * 60


def processed_flag_key(riot_match_id: str) -> str:
    """Per-match idempotency flag (proposal section 13.2, Redis atomic GET/SET).

    Set with ``SET NX`` at the start of processing so a duplicate dequeue exits
    immediately instead of re-running the rating pipeline.
    """
    return f"arena:processed:{riot_match_id}"


#: TTL on the processed flag. Long enough to cover retry storms / redeliveries
#: but not permanent — the durable source of truth is ``matches.processed``.
PROCESSED_FLAG_TTL_SECONDS: Final[int] = 7 * 24 * 60 * 60


def match_lock_key(riot_match_id: str) -> str:
    """Per-match write lock so two workers never write the same match at once."""
    return f"arena:lock:match:{riot_match_id}"


def player_lock_key(player_id: str) -> str:
    """Per-player write lock (sequential per-player rating write, §13.2)."""
    return f"arena:lock:player:{player_id}"


#: pub/sub channel the processor emits ``match.processed`` to (cache warmer,
#: webhook dispatcher — proposal section 13.2 final step).
MATCH_PROCESSED_CHANNEL: Final[str] = "arena:events:match_processed"

#: Sorted set of the current Top-1000 player ids (priority classification source,
#: §13.1). Maintained by the scheduler's leaderboard refresh; read by ingestion.
TOP_PLAYERS_SET: Final[str] = "arena:top_players"


#: Per-puuid ingestion cursor — the last Riot match id we saw for a player, so a
#: poll only fetches the new tail rather than re-scanning history.
def ingest_cursor_key(puuid: str) -> str:
    return f"arena:ingest_cursor:{puuid}"


#: Marca d'água por temporada: o MAIOR ``played_at`` (epoch ms) já avaliado. Uma
#: partida que chega abaixo dela foi avaliada FORA DE ORDEM, e o motor é
#: dependente de ordem — é o sinal que arma o ``replay_floor``.
#:
#: Vive no Redis, não no banco: é lido e escrito em toda partida do caminho de
#: escrita, e é puramente uma dica. Perdê-lo (flush/restart) só significa não
#: detectar atraso até a marca reconstruir; a auditoria de cobertura periódica é
#: a rede de segurança.
def ingest_hwm_key(season_id: str) -> str:
    return f"arena:ingest_hwm:{season_id}"


# ---------------------------------------------------------------------------
# Sweep pipeline keys (SweepWorker / PrioritySweepWorker)
# ---------------------------------------------------------------------------

#: Rotating KEYSET cursor for the standard sweep: the last ``players.puuid``
#: handed out by the previous tick. The next page is ``WHERE puuid > cursor``.
#:
#: Replaces the old integer-OFFSET cursor: players are registered continuously
#: and land at a random position in the puuid ordering, so every insert BEHIND
#: the live offset shifted the remaining pages by one and silently skipped a
#: tracked player for the rest of the rotation. Keyset paging is immune to
#: concurrent inserts. Empty/absent value = start of the rotation.
SWEEP_CURSOR_PUUID_KEY: Final[str] = "arena:sweep:cursor:puuid"

#: Rotating integer cursor for the priority sweep (offset into priority seeds).
PRIORITY_SWEEP_CURSOR_KEY: Final[str] = "arena:priority_sweep:cursor"

#: Session re-arm schedule: ZSET member = puuid, score = epoch seconds when the
#: player is due for a quick re-poll. Fed by the processor after a PROCESSED
#: match (all participants are provably mid-session); drained by rearm_tick.
REARM_ZSET: Final[str] = "arena:sweep:rearm"

#: Hash puuid -> consecutive empty re-polls (misses). A hit resets to 0; at
#: settings.rearm_max_misses the player leaves the schedule (session over).
REARM_MISSES_HASH: Final[str] = "arena:sweep:rearm:misses"

#: Rotating cursor (offset into the sweep page) for the unfiltered
#: rotation-detection sample rider on the standard sweep tick.
DEEP_SAMPLE_CURSOR_KEY: Final[str] = "arena:sweep:deep_sample:cursor"

#: Last-heartbeat timestamp (epoch seconds) written by scheduler.heartbeat_tick
#: every tick. Compared against "now" on the NEXT tick (including the
#: run-at-startup one right after a restart) to detect an outage.
SCHEDULER_HEARTBEAT_KEY: Final[str] = "arena:scheduler:heartbeat"

#: Set (via SET NX) by scheduler.heartbeat_tick when it detects the heartbeat
#: gap exceeds settings.reconcile_gap_threshold_seconds. Value is the epoch
#: second the reconciliation window should start from. Consumed (and deleted)
#: by sweep.reconcile_tick once it completes the catch-up pass.
RECONCILE_WINDOW_KEY: Final[str] = "arena:reconcile:window_since"

# ---------------------------------------------------------------------------
# New-player history backfill (BackfillWorker / backfill_tick)
# ---------------------------------------------------------------------------
#
# A player row is only ever born as a side effect of a lobby-mate's match being
# processed (``match_pipeline.register_players``). Nothing used to look at the
# history they already had: the sweep only ever asks Riot for the newest
# ``sweep_matches_per_player`` ids, and it only sees the player at all once
# ``player_seasons.matches_played > 0`` — which never happens if their first
# observed match was AFK/frozen. These keys back the one-shot catch-up that
# closes that hole.

#: List of puuids awaiting their one-shot history backfill. Producer:
#: ``match_pipeline`` (on genuine INSERT). Consumer: ``backfill_tick``.
BACKFILL_PENDING_LIST: Final[str] = "arena:backfill:pending"

#: Set of puuids whose backfill has been claimed (in flight or done). Guarantees
#: the one-shot stays one-shot across restarts and duplicate registrations.
BACKFILL_CLAIMED_SET: Final[str] = "arena:backfill:claimed"

#: Hash puuid -> attempt count, so a player whose Riot calls keep failing is
#: dropped instead of cycling through the pending list forever.
BACKFILL_ATTEMPTS_HASH: Final[str] = "arena:backfill:attempts"

#: Prefix for per-worker runtime enable flags (value "0" = paused; absent = enabled).
_WORKER_ENABLED_PREFIX: Final[str] = "arena:worker:enabled:"

#: Prefix for per-worker tick no-overlap locks.
_WORKER_TICK_LOCK_PREFIX: Final[str] = "arena:lock:worker:tick:"


#: Every worker that honors the enable/pause flag above (i.e. checks
#: ``worker_enabled_key(<name>)`` at the top of its tick and skips when "0").
#: Single source of truth for the admin pause/resume allow-list — a worker that
#: reads the flag but is missing here can never be paused from the console.
PAUSABLE_WORKERS: Final[frozenset[str]] = frozenset(
    {
        "sweep",
        "priority_sweep",
        "backfill",
        "rearm",
        "reconcile",
    }
)


def worker_enabled_key(name: str) -> str:
    """Redis key for the named worker's enable/pause flag."""
    return f"{_WORKER_ENABLED_PREFIX}{name}"


def worker_tick_lock_key(name: str) -> str:
    """Per-tick mutex preventing overlapping cron executions for the named worker."""
    return f"{_WORKER_TICK_LOCK_PREFIX}{name}"


# ---------------------------------------------------------------------------
# Pressure-mode backpressure (proposal section 11.4)
# ---------------------------------------------------------------------------

#: High-water mark: at/above this combined queue depth, ingestion stops fetching
#: new match ids and lets the processors drain the backlog.
PRESSURE_HIGH_WATERMARK: Final[int] = 100_000

#: Low-water mark: ingestion resumes normal fetching once depth falls below this.
#: A hysteresis gap (low < high) prevents thrashing around the threshold.
PRESSURE_LOW_WATERMARK: Final[int] = 60_000


# ---------------------------------------------------------------------------
# Match-eligibility filter (proposal section 13.2 "Validate filters")
# ---------------------------------------------------------------------------

#: Riot queue id for Arena (proposal section 1). Kept for back-compat; the
#: authoritative set is ``ARENA_QUEUE_IDS`` from :mod:`arena.riot.arena`.
ARENA_QUEUE_ID: Final[int] = ARENA_QUEUE_DUOS

#: Allowed queue ids — sourced from the parser so this filter can never again
#: drift behind a new Arena queue id (the 1710 bug) or drop 1750 trios.
ALLOWED_QUEUE_IDS: Final[frozenset[int]] = ARENA_QUEUE_IDS

#: Arena is either 8 teams × 2 (DUOS = 16) or 6 teams × 3 (TRIOS = 18). Accept
#: that range; anything outside is a malformed / wrong-mode lobby.
MIN_PARTICIPANTS: Final[int] = 16
MAX_PARTICIPANTS: Final[int] = 18

#: Reject suspiciously short matches (remakes / instant FFs) — a match shorter
#: than this never produced meaningful placements (proposal section 3.2 duration
#: outliers handles the statistical long tail; this is the hard floor).
MIN_DURATION_SECONDS: Final[int] = 120

#: Upper sanity bound; anything longer is almost certainly a data artifact.
MAX_DURATION_SECONDS: Final[int] = 60 * 60


@dataclass(frozen=True, slots=True)
class MatchMeta:
    """The lightweight match descriptor ingestion and the processor filter on.

    Populated from the Riot match-list metadata at ingestion (where some fields
    may be unknown -> ``None`` -> the filter defers that check to processing)
    and from the full payload at processing time.
    """

    riot_match_id: str
    queue_id: int | None = None
    participant_count: int | None = None
    duration_seconds: int | None = None
    #: Whether the match falls within an active, processable season window.
    in_active_season: bool | None = None


@dataclass(frozen=True, slots=True)
class FilterResult:
    """Outcome of :func:`evaluate_match_filters`."""

    eligible: bool
    #: Stable machine-readable reason when rejected (audit log + metrics label).
    reason: str | None = None


def evaluate_match_filters(meta: MatchMeta) -> FilterResult:
    """Apply the queue/participant/duration/season filters (proposal §13.2).

    ``None`` fields are treated as "not yet known" and pass at this stage — the
    check re-runs at processing time with the full payload. Known-bad values are
    rejected immediately. Returns a stable ``reason`` code on rejection so the
    caller can emit a consistent audit-log / metric label.
    """
    if meta.queue_id is not None and meta.queue_id not in ALLOWED_QUEUE_IDS:
        return FilterResult(False, "queue_id")

    if meta.participant_count is not None and not (
        MIN_PARTICIPANTS <= meta.participant_count <= MAX_PARTICIPANTS
    ):
        return FilterResult(False, "participant_count")

    if meta.duration_seconds is not None and not (
        MIN_DURATION_SECONDS <= meta.duration_seconds <= MAX_DURATION_SECONDS
    ):
        return FilterResult(False, "duration")

    if meta.in_active_season is False:
        return FilterResult(False, "season_range")

    return FilterResult(True, None)


__all__ = [
    "PRIORITY_QUEUE",
    "STANDARD_QUEUE",
    "DLQ_KEY",
    "PROCESS_MATCH_TASK",
    "SEEN_MATCHES_ZSET",
    "SEEN_MATCH_TTL_SECONDS",
    "PROCESSED_FLAG_TTL_SECONDS",
    "MATCH_PROCESSED_CHANNEL",
    "TOP_PLAYERS_SET",
    "SCHEDULER_HEARTBEAT_KEY",
    "RECONCILE_WINDOW_KEY",
    "PRESSURE_HIGH_WATERMARK",
    "PRESSURE_LOW_WATERMARK",
    "ARENA_QUEUE_ID",
    "ALLOWED_QUEUE_IDS",
    "MIN_PARTICIPANTS",
    "MAX_PARTICIPANTS",
    "MIN_DURATION_SECONDS",
    "MAX_DURATION_SECONDS",
    "MatchMeta",
    "FilterResult",
    "processed_flag_key",
    "match_lock_key",
    "player_lock_key",
    "ingest_cursor_key",
    "ingest_hwm_key",
    "SWEEP_CURSOR_PUUID_KEY",
    "PRIORITY_SWEEP_CURSOR_KEY",
    "BACKFILL_PENDING_LIST",
    "BACKFILL_CLAIMED_SET",
    "BACKFILL_ATTEMPTS_HASH",
    "REARM_ZSET",
    "REARM_MISSES_HASH",
    "DEEP_SAMPLE_CURSOR_KEY",
    "PAUSABLE_WORKERS",
    "worker_enabled_key",
    "worker_tick_lock_key",
    "evaluate_match_filters",
]
