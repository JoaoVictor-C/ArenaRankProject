"""Worker write-path wiring: Riot payload -> RawMatch -> RatingService.

This module closes the Wave-2 seam the workers program against
(:class:`arena.workers.deps.RatingService`). The processor hands us a
``riot_match_id`` + the full match-v5 ``payload`` and expects a JSON-serializable
summary back; the real :class:`arena.services.rating_service.RatingService`
instead wants a normalized :class:`~arena.services.protocols.RawMatch`, a DB
session, and a per-player lock factory. :class:`WorkerRatingService` is the
adapter that bridges the two — it is what
:func:`arena.services.rating_service.get_rating_service` returns.

Normalization mirrors the proven offline path in
``scripts/e2e_process_fixture.py``: parse the Arena payload, register the players
(puuid -> internal id), resolve the active season, and build the ``RawMatch``.
Two deliberate improvements over that script:

* ``played_at`` uses the real ``gameStartTimestamp`` (``parsed.started_at_ms``)
  rather than the processing clock, so ``delta7d`` / chronological ordering stay
  correct (see ``arena/riot/arena.py`` and ``workaround.md`` §7).
* the internal ``matches.id`` is a deterministic UUIDv5 of the Riot match id, so
  re-ingesting the same match maps to the same row and the rating service's
  ``matches.processed`` idempotency guard actually fires across retries.

Integrity: this wiring honors the transport-level eligibility gate the Arena
parser already derives (AFK / early-surrender / too-short -> frozen), which is
the rating-affecting signal. The richer integrity scoring
(:func:`arena.integrity.evaluate_async` — RDS boosting, duration/dispersion,
repeated-lobby) needs a per-player CR snapshot that ``RawMatch`` does not carry;
it plugs in here later via the injectable ``integrity_factory`` seam without
touching the workers.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from arena.core.config import settings
from arena.core.logging import get_logger
from arena.db import models as m
from arena.db.session import get_sessionmaker
from arena.integrity.evaluators import evaluate_premade
from arena.integrity.fingerprint import (
    PartyCooccurrenceStore,
    RedisPartyCooccurrenceStore,
    subteam_pair_keys,
)
from arena.integrity.params import DEFAULT_INTEGRITY_PARAMS, IntegrityParams
from arena.integrity.types import MatchSnapshot, ParticipantSnapshot
from arena.riot.arena import NotAnArenaMatch, ParsedArenaMatch, parse_arena_match
from arena.rating import PlayerState
from arena.services.locks import RedisLockManager
from arena.services.protocols import (
    IntegrityEvaluator,
    IntegrityVerdict,
    RawMatch,
    RawParticipant,
)
from arena.services.rating_service import ProcessOutcome, RatingService
from arena.workers.backfill import enqueue_backfill

_log = get_logger("arena.services.match_pipeline")

# Stable namespace so uuid5(riot_match_id) is reproducible across processes.
_MATCH_NS = uuid.uuid5(uuid.NAMESPACE_URL, "arenarank:match")

#: A factory returning the async context manager that holds every per-player
#: lock for the rating critical section (see ``RedisLockManager.lock_players``).
LockPlayers = Callable[[Iterable[str]], AbstractAsyncContextManager[object]]


class NoActiveSeasonError(RuntimeError):
    """No ACTIVE (or any) season row exists — processing cannot proceed.

    Raised (not swallowed) so arq retries with backoff and finally dead-letters;
    an operator creates/activates a season and replays the DLQ.
    """


class EligibilityOnlyIntegrity:
    """Minimal :class:`~arena.services.protocols.IntegrityEvaluator`.

    Freezes the players the Arena parser already marked ineligible
    (AFK / early-surrender / game-too-short), applies no boosting penalty, and
    emits no flags. This is the rating-affecting subset of the integrity
    contract; the full evaluator is a drop-in replacement once a CR-bearing
    snapshot is assembled (see module docstring).
    """

    __slots__ = ("_ineligible",)

    def __init__(self, ineligible_player_ids: Iterable[str]) -> None:
        self._ineligible = set(ineligible_player_ids)

    async def evaluate(
        self, match: RawMatch, states: Mapping[str, PlayerState] | None = None
    ) -> IntegrityVerdict:
        return IntegrityVerdict(
            flags=[],
            boosting_factors={},
            ineligible_player_ids=set(self._ineligible),
        )


class PremadeIntegrity:
    """Eligibility + premade dampener (the live integrity path).

    Keeps the parser-derived eligibility (AFK / early-surrender / too-short) that
    :class:`EligibilityOnlyIntegrity` provides, and adds the co-occurrence-based
    premade dampener: it observes each subteam's player pairs in a rolling Redis
    window and scores a per-player ``party_penalty_factor`` from co-occurrence
    confidence x intra-party CR homogeneity (see ``integrity.evaluate_premade``).

    Degrades to eligibility-only when no co-occurrence store is available (e.g.
    ``redis=None`` in tests) or when pre-match ``states`` were not supplied. The
    richer RDS / duration / dispersion evaluators are intentionally NOT run here:
    ``RawParticipant`` carries no AFK/damage telemetry, so they would score on
    zeroed inputs.
    """

    __slots__ = ("_ineligible", "_party_store", "_params")

    def __init__(
        self,
        ineligible_player_ids: Iterable[str],
        party_store: PartyCooccurrenceStore | None,
        params: IntegrityParams = DEFAULT_INTEGRITY_PARAMS,
    ) -> None:
        self._ineligible = set(ineligible_player_ids)
        self._party_store = party_store
        self._params = params

    async def evaluate(
        self, match: RawMatch, states: Mapping[str, PlayerState] | None = None
    ) -> IntegrityVerdict:
        party_factors: dict[str, float] = {}
        if self._party_store is not None and states is not None:
            party_factors = await self._score_premade(match, states)
        return IntegrityVerdict(
            flags=[],
            boosting_factors={},
            ineligible_player_ids=set(self._ineligible),
            party_factors=party_factors,
        )

    async def _score_premade(
        self, match: RawMatch, states: Mapping[str, PlayerState]
    ) -> dict[str, float]:
        assert self._party_store is not None
        snap = MatchSnapshot(
            match_id=match.match_id,
            mode=match.mode,
            team_size=2 if match.mode == "DUOS" else 3,
            duration_seconds=match.duration_seconds or 0,
            participants=[
                ParticipantSnapshot(
                    player_id=p.player_id,
                    team_id=p.team_id,
                    champion_id=p.champion_id,
                    cr=states[p.player_id].cr if p.player_id in states else 0.0,
                )
                for p in match.participants
            ],
        )
        subteams: dict[int, list[str]] = {}
        for p in match.participants:
            subteams.setdefault(p.team_id, []).append(p.player_id)
        pairs = [pk for members in subteams.values() for pk in subteam_pair_keys(members)]
        counts = await self._party_store.observe(
            pairs, match.match_id, self._params.premade_window_seconds
        )
        return evaluate_premade(snap, counts, self._params)


def _default_integrity(ineligible: set[str], redis: Any) -> IntegrityEvaluator:
    """Build the live integrity evaluator: eligibility + (when Redis is present)
    the co-occurrence-based premade dampener. Falls back to eligibility-only when
    no Redis is wired (tests / single-worker dev)."""
    store = RedisPartyCooccurrenceStore(redis) if redis is not None else None
    return PremadeIntegrity(ineligible, store)


def deterministic_match_id(riot_match_id: str) -> str:
    """Stable internal ``matches.id`` for a Riot match id (idempotency anchor)."""
    return str(uuid.uuid5(_MATCH_NS, riot_match_id))


def played_at_iso(parsed: ParsedArenaMatch) -> str:
    """Real match start as ISO-8601, falling back to now if Riot omitted it."""
    if parsed.started_at_ms > 0:
        return datetime.fromtimestamp(parsed.started_at_ms / 1000, UTC).isoformat()
    return datetime.now(UTC).isoformat()


def before_cutoff(started_at_ms: int, cutoff_ms: int) -> bool:
    """True when the launch-window cutoff must drop this match.

    ``cutoff_ms == 0`` disables the window (always False). A match with an unknown
    start (``started_at_ms == 0``) is kept (False) so a rare payload missing
    ``gameStartTimestamp`` is not silently discarded. Pure/deterministic so the
    policy is unit-testable without a DB.
    """
    return bool(cutoff_ms) and 0 < started_at_ms < cutoff_ms


def build_raw_participants(
    parsed: ParsedArenaMatch,
    id_for_puuid: Callable[[str], str],
) -> tuple[list[RawParticipant], set[str]]:
    """Pure map: parsed subteams + a puuid->id resolver -> (participants, ineligible).

    Kept separate from DB registration so it is unit-testable without a database.
    ``team_id`` is Riot's ``playerSubteamId``; ``placement`` is the subteam's
    shared placement (1 = best).
    """
    participants: list[RawParticipant] = []
    ineligible: set[str] = set()
    for subteam in parsed.subteams:
        for p in subteam.participants:
            pid = id_for_puuid(p.puuid)
            if not p.eligible_for_progression:
                ineligible.add(pid)
            participants.append(
                RawParticipant(
                    player_id=pid,
                    champion_id=p.champion_id,
                    team_id=subteam.subteam_id,
                    placement=subteam.placement,
                )
            )
    return participants, ineligible


# Active season changes at most once per season boundary, yet was re-queried on
# every match (1-2 SELECTs/match). Cache the id process-wide behind a short TTL so
# a rollover is still picked up within seconds without a per-match round-trip.
_SEASON_CACHE_TTL_S = 30.0
_season_cache: dict[str, tuple[float, str]] = {}


async def resolve_active_season_id(session: AsyncSession) -> str:
    """Active season id; falls back to any season (dev) and otherwise raises.

    Cached for ``_SEASON_CACHE_TTL_S`` (monotonic) to drop the per-match query.
    """
    hit = _season_cache.get("active")
    now = time.monotonic()
    if hit is not None and hit[0] > now:
        return hit[1]

    season = (
        await session.execute(
            select(m.Season).where(m.Season.status == m.SeasonStatus.ACTIVE).limit(1)
        )
    ).scalar_one_or_none()
    if season is None:
        season = (await session.execute(select(m.Season).limit(1))).scalar_one_or_none()
    if season is None:
        raise NoActiveSeasonError("no season configured")
    season_id = str(season.id)
    _season_cache["active"] = (now + _SEASON_CACHE_TTL_S, season_id)
    return season_id


@dataclass(frozen=True, slots=True)
class RegisteredPlayers:
    """Outcome of :func:`register_players`.

    ``new_puuids`` are the rows this call genuinely INSERTed (as opposed to
    upserted onto an existing row). They are the trigger for the one-shot
    history backfill: a player is born here as a side effect of a lobby-mate's
    match, and nothing else in the online path ever looks at the history they
    already had.
    """

    id_map: dict[str, str]
    new_puuids: tuple[str, ...] = ()


def player_upsert_stmt(rows: list[dict[str, Any]]) -> Any:
    """The whole-lobby player upsert, returning ``(id, puuid, inserted)``.

    Split out from :func:`register_players` so the SQL shape — specifically the
    ``xmax`` discriminator, which only a live Postgres can execute — is pinned by
    a dialect-compile test rather than only by the integration test that skips
    without a database.

    Return type is ``Any`` because the mixed column/literal RETURNING makes the
    row type unresolvable for mypy --strict.
    """
    ins = pg_insert(m.Player).values(rows)
    return ins.on_conflict_do_update(
        index_elements=["puuid"],
        set_={
            "profile_icon_id": func.coalesce(ins.excluded.profile_icon_id, m.Player.profile_icon_id),
            "summoner_name": func.coalesce(ins.excluded.summoner_name, m.Player.summoner_name),
            "tag_line": func.coalesce(ins.excluded.tag_line, m.Player.tag_line),
        },
    ).returning(
        m.Player.id,
        m.Player.puuid,
        # Postgres idiom: on a row this statement INSERTed, xmax is 0; on one it
        # UPDATEd via ON CONFLICT, xmax carries the updating xid. This is the
        # only way to tell the two apart in a single round-trip — DO UPDATE
        # returns both kinds indistinguishably.
        literal_column("(xmax = 0)").label("inserted"),
    )


async def register_players(session: AsyncSession, parsed: ParsedArenaMatch) -> RegisteredPlayers:
    """Resolve every participant puuid to an internal ``players.id``, creating rows.

    One ``INSERT ... ON CONFLICT (puuid) DO UPDATE ... RETURNING`` for the whole
    lobby (mirrors ``arena.ingest.PlayerRegistry``) instead of up to 16 serial
    ``SELECT`` + ``flush`` round-trips. ``DO UPDATE`` (rather than ``DO NOTHING``)
    is required so Postgres returns a row for *every* puuid — existing and new —
    in a single trip; ``coalesce(excluded, current)`` refreshes the ddragon
    profile/name fields only when the payload carries a non-null value. The
    commit is still left to the rating service so players + match + participants
    persist atomically in one transaction.
    """
    roster: dict[str, dict[str, Any]] = {}
    for subteam in parsed.subteams:
        for p in subteam.participants:
            roster.setdefault(
                p.puuid,
                {
                    "puuid": p.puuid,
                    "summoner_name": p.riot_id_game_name or None,
                    "tag_line": p.riot_id_tagline or None,
                    "region": "br",
                    "profile_icon_id": p.profile_icon or None,
                },
            )
    if not roster:
        return RegisteredPlayers({})

    # Emit rows in a deterministic order (sorted by puuid). register_players runs
    # OUTSIDE the per-player rating lock, so two concurrent matches with an
    # overlapping roster would otherwise lock the conflicting player rows in
    # different VALUES orders and deadlock. Sorting gives every transaction the
    # same lock-acquisition order, which eliminates the deadlock.
    rows = [roster[pu] for pu in sorted(roster)]
    stmt = player_upsert_stmt(rows)

    id_map: dict[str, str] = {}
    new_puuids: list[str] = []
    for pid, pu, inserted in (await session.execute(stmt)).all():
        id_map[str(pu)] = str(pid)
        if inserted:
            new_puuids.append(str(pu))
    return RegisteredPlayers(id_map, tuple(new_puuids))


@asynccontextmanager
async def _noop_lock(player_ids: Iterable[str]) -> AsyncIterator[None]:
    """Lock factory used when no Redis is available (tests / single-worker dev)."""
    yield


def _lock_factory(redis: Any) -> LockPlayers:
    if redis is None:
        return _noop_lock
    return RedisLockManager(redis).lock_players


def _summary(riot_match_id: str, internal_match_id: str, outcome: ProcessOutcome) -> dict[str, Any]:
    """The JSON ``match.processed`` summary the processor publishes (camelCase)."""
    return {
        "matchId": riot_match_id,
        "internalMatchId": internal_match_id,
        "status": outcome.status,
        "voided": outcome.voided,
        "playersUpdated": outcome.players_updated,
        "flagsEmitted": outcome.flags_emitted,
        "affectedPlayers": outcome.affected_player_ids,
    }


class WorkerRatingService:
    """Adapter implementing the workers' ``RatingService`` protocol.

    Bridges ``process_match(riot_match_id, payload, *, redis) -> dict`` (what the
    arq processor calls) to the real
    :meth:`arena.services.rating_service.RatingService.process_match`
    (session + lock factory + ``RawMatch`` -> :class:`ProcessOutcome`).
    """

    __slots__ = ("_integrity_factory",)

    def __init__(
        self,
        integrity_factory: Callable[[set[str], Any], IntegrityEvaluator] | None = None,
    ) -> None:
        # Injectable so an alternative evaluator can replace the default without
        # changing the workers. The factory receives the parser-derived ineligible
        # set + the per-call redis handle (None in tests / single-worker dev).
        self._integrity_factory: Callable[[set[str], Any], IntegrityEvaluator] = (
            integrity_factory or _default_integrity
        )

    async def process_match(
        self,
        riot_match_id: str,
        payload: dict[str, Any],
        *,
        redis: Any,
    ) -> dict[str, Any]:
        try:
            parsed = parse_arena_match(payload)
        except NotAnArenaMatch as exc:
            # Belt-and-suspenders: the processor already queue-filtered, but a
            # non-Arena payload here is a terminal, non-error outcome.
            _log.info("pipeline.not_arena", matchId=riot_match_id, reason=str(exc))
            return {"matchId": riot_match_id, "status": "filtered", "reason": "not_arena"}

        # Launch-window cutoff (proposal §13.2): drop matches that started before
        # the configured instant so a fresh season only rates from go-live. This is
        # the single funnel every consumer (standard/priority/sweep/bulk) passes
        # through, so one check covers them all. started_at_ms == 0 means Riot
        # omitted the timestamp -> keep it (don't silently drop on missing data).
        cutoff_ms = settings.match_min_started_at_ms
        if before_cutoff(parsed.started_at_ms, cutoff_ms):
            _log.info(
                "pipeline.before_cutoff",
                matchId=riot_match_id,
                startedAtMs=parsed.started_at_ms,
                cutoffMs=cutoff_ms,
            )
            return {"matchId": riot_match_id, "status": "filtered", "reason": "before_cutoff"}

        # Structural sanity (rare Riot-side data anomaly): every participant is
        # occasionally stamped with playerSubteamId=0 (and placement 0), which
        # collapses parse_arena_match's grouping into one giant "subteam" instead
        # of several. Nothing upstream (queue id, participant count, duration)
        # catches this — it only surfaces as arena.rating.engine.rate() raising
        # "a match needs at least 2 teams", which used to retry 3x and
        # dead-letter a match that was never ratable to begin with. Mirrors the
        # engine's own guard exactly (>=2 teams) rather than requiring the
        # mode's full canonical shape (is_complete) — a smaller-than-canonical
        # lobby is still ratable and must not be filtered.
        if len(parsed.subteams) < 2:
            _log.info(
                "pipeline.incomplete_teams",
                matchId=riot_match_id,
                subteams=len(parsed.subteams),
            )
            return {"matchId": riot_match_id, "status": "filtered", "reason": "incomplete_teams"}

        factory = get_sessionmaker()
        async with factory() as session:
            season_id = await resolve_active_season_id(session)
            registered = await register_players(session, parsed)
            id_map = registered.id_map
            participants, ineligible = build_raw_participants(parsed, lambda pu: id_map[pu])
            raw = RawMatch(
                match_id=deterministic_match_id(parsed.match_id),
                riot_match_id=parsed.match_id,
                season_id=season_id,
                mode=parsed.mode.value,
                queue_id=parsed.queue_id,
                played_at=played_at_iso(parsed),
                participants=participants,
                duration_seconds=parsed.game_duration,
            )
            service = RatingService(self._integrity_factory(ineligible, redis))
            outcome = await service.process_match(session, _lock_factory(redis), raw)

        # Queue the one-shot history backfill for players this match introduced.
        # AFTER the transaction commits, so a rollback can't leave us backfilling
        # a player that does not exist; best-effort inside, so a Redis blip never
        # fails an already-persisted match.
        await enqueue_backfill(redis, registered.new_puuids)

        return _summary(riot_match_id, raw.match_id, outcome)


def get_rating_service() -> WorkerRatingService:
    """Factory the workers resolve via ``arena.services.rating_service``."""
    return WorkerRatingService()


__all__ = [
    "WorkerRatingService",
    "EligibilityOnlyIntegrity",
    "PremadeIntegrity",
    "NoActiveSeasonError",
    "build_raw_participants",
    "register_players",
    "RegisteredPlayers",
    "player_upsert_stmt",
    "resolve_active_season_id",
    "deterministic_match_id",
    "played_at_iso",
    "before_cutoff",
    "get_rating_service",
]
