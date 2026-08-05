"""RatingService — orchestrates processing of one match end to end.

This is the heart of the write path (proposal §13.2). Given a normalized
:class:`~arena.services.protocols.RawMatch` it:

1. **Idempotency guard** — short-circuits if ``matches.processed`` is already
   true (the Redis ``processed`` flag is the worker's fast path; the DB flag is
   the durable source of truth checked here inside the lock).
2. **Integrity** — calls ``IntegrityEvaluator.evaluate(match)`` to obtain flags,
   per-player boosting factors, and AFK/ineligible players.
3. **Build engine input** — loads each player's current ``player_seasons`` state,
   maps it to the rating engine's ``MatchInput`` (wiring boosting factor +
   eligibility from the integrity verdict).
4. **Rate** — calls the pure ``arena.rating.rate()``.
5. **Persist in ONE transaction**, under a **per-player Redis lock**:
   ``player_seasons`` (CR/mu/sigma/streak/peak/placement) · ``match_participants``
   (CR-delta + modifiers snapshot) · ``champion_stats`` upsert · ``cr_snapshots``
   (Timescale) · ``integrity_events`` (one per flag) · ``matches.processed=true``.

The whole step is **idempotent on ``matches.processed``** and crash-safe: the
lock spans the read of current state through commit, so two workers handed the
same match cannot double-apply, and concurrent matches sharing a player serialize.

ToS / contract: this service persists ``mu``/``sigma`` (needed by the engine) but
emits nothing user-facing; the API layer projects CR/Pontos only. User-facing
log/exception strings are PT-BR.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import uuid

from sqlalchemy import or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from arena.db import models as m
from arena.rating import (
    DEFAULT_PARAMS,
    PARAMS_EPOCH,
    MatchInput,
    ParticipantInput,
    PlayerRatingResult,
    PlayerState,
    RatingParams,
    RatingResult,
    TeamInput,
    rate,
)
from arena.services.protocols import (
    IntegrityEvaluator,
    IntegrityVerdict,
    RawMatch,
    RawParticipant,
)

if TYPE_CHECKING:
    from arena.services.match_pipeline import WorkerRatingService

# A factory that, given the players touched by a match, returns an async context
# manager holding every per-player lock for the rating critical section. See
# :meth:`arena.services.locks.RedisLockManager.lock_players`.
LockPlayers = Callable[[Iterable[str]], AbstractAsyncContextManager[object]]


@dataclass(slots=True)
class ProcessOutcome:
    """Summary returned by :meth:`RatingService.process_match` (worker telemetry)."""

    match_id: str
    status: str  # "processed" | "already_processed" | "voided"
    voided: bool = False
    players_updated: int = 0
    flags_emitted: int = 0
    affected_player_ids: list[str] = field(default_factory=list)


class RatingService:
    """Stateless orchestrator; collaborators are injected (DI-friendly, testable).

    ``lock_players`` is any callable returning an async context manager that
    holds a lock for the given player ids (see
    :class:`arena.services.locks.RedisLockManager.lock_players`). It is injected
    rather than imported so the service stays decoupled from Redis for tests.
    """

    def __init__(
        self,
        integrity: IntegrityEvaluator,
        *,
        params: RatingParams = DEFAULT_PARAMS,
        snapshot_at_played: bool = False,
    ) -> None:
        self._integrity = integrity
        self._params = params
        # ``snapshot_at_played`` carimba ``cr_snapshots`` com o ``played_at`` da
        # partida em vez do relógio de processamento. Ligado SÓ pelo replay: ao
        # reprocessar meses de partidas numa rajada, o padrão (``now``) colapsa
        # todos os snapshots no instante do replay e o delta7d do site vira lixo
        # até acumular histórico novo. Na ingestão ao vivo os dois coincidem
        # (played_at ≈ agora), então o padrão fica como estava.
        self._snapshot_at_played = snapshot_at_played

    # -- public API --------------------------------------------------------

    async def process_match(
        self,
        session: AsyncSession,
        lock_players: LockPlayers,
        match: RawMatch,
    ) -> ProcessOutcome:
        """Idempotently process one match. See module docstring for the pipeline."""
        player_ids = sorted({p.player_id for p in match.participants})

        # Per-player Redis lock spans state-read .. commit (serializes shared players).
        async with lock_players(player_ids):
            if await self._already_processed(session, match.match_id, match.riot_match_id):
                return ProcessOutcome(match_id=match.match_id, status="already_processed")

            # Load pre-match state first so integrity signals that compare skill
            # (the premade dampener) get each player's CR. Both reads are inside
            # the same per-player lock, so the ordering swap changes no semantics.
            states = await self._load_states(session, match.season_id, player_ids)
            state_map = {pid: self._to_state(ps) for pid, ps in states.items()}
            verdict = await self._integrity.evaluate(match, state_map)

            match_input = self._build_match_input(match, verdict, states)

            result = rate(match_input)

            outcome = await self._persist(session, match, verdict, states, result)

        return outcome

    # -- pipeline steps ----------------------------------------------------

    async def _already_processed(
        self, session: AsyncSession, match_id: str, riot_match_id: str
    ) -> bool:
        # Também confere por riot_match_id: rows de eras anteriores (backfill)
        # podem ter um id interno diferente do UUIDv5 determinístico atual —
        # sem isso o guard não as via, o INSERT batia na unique
        # (riot_match_id, season_id, played_at) e a partida ciclava
        # retry → dead-letter apesar de já estar contabilizada.
        row = await session.execute(
            select(m.Match.processed)
            .where(
                or_(m.Match.id == match_id, m.Match.riot_match_id == riot_match_id)
            )
            .order_by(m.Match.processed.desc())
            .limit(1)
        )
        flag = row.scalar_one_or_none()
        return bool(flag)

    async def _load_states(
        self, session: AsyncSession, season_id: str, player_ids: list[str]
    ) -> dict[str, m.PlayerSeason]:
        """Load (or lazily create) the ``player_seasons`` row for each player.

        Players with no row yet (first match this season) get a fresh row at the
        engine defaults; it is added to the session and persisted in the same tx.
        """
        rows = await session.execute(
            select(m.PlayerSeason).where(
                m.PlayerSeason.season_id == season_id,
                m.PlayerSeason.player_id.in_(player_ids),
            )
        )
        by_player: dict[str, m.PlayerSeason] = {str(ps.player_id): ps for ps in rows.scalars()}
        for pid in player_ids:
            if pid not in by_player:
                ps = m.PlayerSeason(
                    player_id=pid,
                    season_id=season_id,
                    cr=self._params.base_offset
                    + (self._params.mu0 - 3.0 * self._params.sigma0) * self._params.scale_factor,
                    mu=self._params.mu0,
                    sigma=self._params.sigma0,
                    matches_played=0,
                    placement_matches_remaining=self._params.placement_match_count,
                    is_provisional=True,
                    peak_cr=self._params.base_offset
                    + (self._params.mu0 - 3.0 * self._params.sigma0) * self._params.scale_factor,
                    current_streak=0,
                )
                session.add(ps)
                by_player[pid] = ps
        return by_player

    def _build_match_input(
        self,
        match: RawMatch,
        verdict: IntegrityVerdict,
        states: dict[str, m.PlayerSeason],
    ) -> MatchInput:
        """Map persisted state + integrity verdict -> rating-engine ``MatchInput``."""
        teams_by_id: dict[int, list[RawParticipant]] = defaultdict(list)
        placement_by_team: dict[int, int] = {}
        for p in match.participants:
            teams_by_id[p.team_id].append(p)
            placement_by_team[p.team_id] = p.placement

        teams: list[TeamInput] = []
        for team_id, parts in teams_by_id.items():
            participants = [
                ParticipantInput(
                    player_id=p.player_id,
                    state=self._to_state(states[p.player_id]),
                    champion_id=p.champion_id,
                    eligible_for_progression=verdict.is_eligible(p.player_id),
                    is_premade=p.is_premade,
                    party_id=p.party_id,
                    boosting_penalty_factor=verdict.boosting_for(p.player_id),
                    party_penalty_factor=verdict.party_for(p.player_id),
                )
                for p in parts
            ]
            teams.append(
                TeamInput(
                    team_id=team_id,
                    placement=placement_by_team[team_id],
                    participants=participants,
                )
            )

        return MatchInput(
            match_id=match.match_id,
            mode=match.mode,
            teams=teams,
            params=self._params,
        )

    @staticmethod
    def _to_state(ps: m.PlayerSeason) -> PlayerState:
        return PlayerState(
            player_id=str(ps.player_id),
            mu=ps.mu,
            sigma=ps.sigma,
            cr=ps.cr,
            current_streak=ps.current_streak,
            matches_played=ps.matches_played,
            placement_matches_remaining=ps.placement_matches_remaining,
            peak_cr=ps.peak_cr,
        )

    # -- persistence (single transaction) ----------------------------------

    async def _persist(
        self,
        session: AsyncSession,
        match: RawMatch,
        verdict: IntegrityVerdict,
        states: dict[str, m.PlayerSeason],
        result: RatingResult,
    ) -> ProcessOutcome:
        """Apply the rating result + flags + processed marker in one transaction.

        Caller (``process_match``) holds the per-player locks; this method does
        not commit if the caller is inside an outer transaction — it flushes and
        lets the session's transactional scope (or the worker) commit. We
        ``commit()`` here so the unit of work is atomic and self-contained per
        the §13.2 "Begin/Commit transaction" boundary.
        """
        now = datetime.now(UTC)
        played_at = _parse_iso(match.played_at)
        snap_at = played_at if self._snapshot_at_played else now
        champion_by_player = {p.player_id: p.champion_id for p in match.participants}
        placement_by_player = {p.player_id: p.placement for p in match.participants}
        team_by_player = {p.player_id: p.team_id for p in match.participants}
        premade_by_player = {p.player_id: p.is_premade for p in match.participants}
        party_by_player = {p.player_id: p.party_id for p in match.participants}
        augments_by_player = {p.player_id: p.augments for p in match.participants}
        items_by_player = {p.player_id: p.items for p in match.participants}
        kills_by_player = {p.player_id: p.kills for p in match.participants}
        deaths_by_player = {p.player_id: p.deaths for p in match.participants}
        assists_by_player = {p.player_id: p.assists for p in match.participants}
        damage_to_champions_by_player = {
            p.player_id: p.damage_to_champions for p in match.participants
        }
        gold_earned_by_player = {p.player_id: p.gold_earned for p in match.participants}
        champion_level_by_player = {p.player_id: p.champion_level for p in match.participants}
        damage_taken_by_player = {p.player_id: p.damage_taken for p in match.participants}
        total_heal_by_player = {p.player_id: p.total_heal for p in match.participants}
        damage_self_mitigated_by_player = {
            p.player_id: p.damage_self_mitigated for p in match.participants
        }
        largest_multi_kill_by_player = {
            p.player_id: p.largest_multi_kill for p in match.participants
        }
        killing_sprees_by_player = {p.player_id: p.killing_sprees for p in match.participants}
        time_spent_dead_by_player = {
            p.player_id: p.time_spent_dead for p in match.participants
        }

        # RESTORE POINTS — capturados AQUI, antes do laço abaixo mutar cada
        # ``player_seasons`` in-place. Depois da primeira iteração ``states`` já
        # carrega o estado POSTERIOR, e o snapshot seria inútil (ou pior:
        # silenciosamente errado). Ver models.MatchParticipant.state_before.
        state_before_by_player = {
            pid: state_before_to_json(ps) for pid, ps in states.items()
        }

        # Pre-load every champion_stats row this match will touch in ONE query
        # (was one SELECT per eligible player). The read-modify-write below then
        # runs purely in memory; new rows are added to the map as they're created.
        champ_stats = await self._load_champion_stats(
            session, match.season_id, result, champion_by_player
        )

        updated = 0
        for pr in result.players:
            ps = states[pr.player_id]
            modifiers_json = _modifiers_to_json(pr)

            if pr.eligible and not result.voided:
                # 1) player_seasons read-modify-write
                ps.mu = pr.mu_after
                ps.sigma = pr.sigma_after
                ps.cr = pr.cr_after
                ps.current_streak = pr.new_streak
                ps.matches_played = ps.matches_played + 1
                if ps.placement_matches_remaining > 0:
                    ps.placement_matches_remaining -= 1
                ps.is_provisional = ps.placement_matches_remaining > 0
                if pr.cr_after > ps.peak_cr:
                    ps.peak_cr = pr.cr_after
                updated += 1

                # 4) cr_snapshots (Timescale) — only for movement.
                session.add(
                    m.CrSnapshot(
                        snapshot_at=snap_at,
                        player_id=pr.player_id,
                        season_id=match.season_id,
                        cr=ps.cr,
                        mu=ps.mu,
                        sigma=ps.sigma,
                        matches_played=ps.matches_played,
                    )
                )
                # 4b) dual-write no espelho plano replicável (T2.3): a réplica
                # de leitura serve o delta7d desta tabela; purge de temporadas
                # antigas fica no cron do scheduler.
                session.add(
                    m.CrSnapshotRecent(
                        snapshot_at=snap_at,
                        player_id=pr.player_id,
                        season_id=match.season_id,
                        cr=ps.cr,
                        mu=ps.mu,
                        sigma=ps.sigma,
                        matches_played=ps.matches_played,
                    )
                )

            # 2) match_participants snapshot (always, even frozen/voided — the
            #    record documents the match for everyone in the lobby).
            session.add(
                m.MatchParticipant(
                    match_id=match.match_id,
                    player_id=pr.player_id,
                    played_at=played_at,
                    champion_id=champion_by_player[pr.player_id],
                    team_id=team_by_player[pr.player_id],
                    placement=placement_by_player[pr.player_id],
                    eligible=pr.eligible,
                    cr_before=pr.cr_before,
                    cr_after=pr.cr_after,
                    cr_delta=pr.cr_delta,
                    is_premade=premade_by_player[pr.player_id],
                    party_id=party_by_player[pr.player_id],
                    modifiers=modifiers_json,
                    state_before=state_before_by_player.get(pr.player_id),
                    augments=augments_by_player[pr.player_id],
                    items=items_by_player[pr.player_id],
                    kills=kills_by_player[pr.player_id],
                    deaths=deaths_by_player[pr.player_id],
                    assists=assists_by_player[pr.player_id],
                    damage_to_champions=damage_to_champions_by_player[pr.player_id],
                    gold_earned=gold_earned_by_player[pr.player_id],
                    champion_level=champion_level_by_player[pr.player_id],
                    damage_taken=damage_taken_by_player[pr.player_id],
                    total_heal=total_heal_by_player[pr.player_id],
                    damage_self_mitigated=damage_self_mitigated_by_player[pr.player_id],
                    largest_multi_kill=largest_multi_kill_by_player[pr.player_id],
                    killing_sprees=killing_sprees_by_player[pr.player_id],
                    time_spent_dead=time_spent_dead_by_player[pr.player_id],
                )
            )

            # 3) champion_stats upsert (only when the result counted).
            if pr.eligible and not result.voided:
                self._apply_champion_stat(
                    session,
                    champ_stats,
                    player_id=pr.player_id,
                    season_id=match.season_id,
                    champion_id=champion_by_player[pr.player_id],
                    placement=placement_by_player[pr.player_id],
                    is_win=pr.is_win,
                    cr_delta=pr.cr_delta,
                )

        # 5) integrity_events (one row per emitted flag).
        for flag in verdict.flags:
            session.add(
                m.IntegrityEvent(
                    match_id=match.match_id,
                    player_id=flag.player_id,
                    flag_type=flag.flag_type,
                    severity=_to_severity(flag.severity),
                    metadata_=dict(flag.metadata) if flag.metadata else None,
                    created_at=now,
                    reviewed=False,
                )
            )

        # 6) mark match processed (idempotency anchor) + persist flags summary.
        await self._mark_processed(session, match, verdict, now)

        await session.commit()

        return ProcessOutcome(
            match_id=match.match_id,
            status="voided" if result.voided else "processed",
            voided=result.voided,
            players_updated=updated,
            flags_emitted=len(verdict.flags),
            affected_player_ids=[pr.player_id for pr in result.players],
        )

    async def _load_champion_stats(
        self,
        session: AsyncSession,
        season_id: str,
        result: RatingResult,
        champion_by_player: dict[str, int],
    ) -> dict[tuple[str, int], m.ChampionStat]:
        """Load all existing champion_stats rows this match touches in one query.

        Keyed by ``(player_id, champion_id)``. Empty when the match is voided or
        has no eligible players (nothing to upsert). A single composite-``IN``
        replaces the former per-player ``SELECT``.
        """
        keys = [
            (uuid.UUID(pr.player_id), champion_by_player[pr.player_id])
            for pr in result.players
            if pr.eligible
        ]
        if result.voided or not keys:
            return {}
        rows = await session.execute(
            select(m.ChampionStat).where(
                m.ChampionStat.season_id == season_id,
                tuple_(m.ChampionStat.player_id, m.ChampionStat.champion_id).in_(keys),
            )
        )
        return {(str(cs.player_id), cs.champion_id): cs for cs in rows.scalars()}

    def _apply_champion_stat(
        self,
        session: AsyncSession,
        champ_stats: dict[tuple[str, int], m.ChampionStat],
        *,
        player_id: str,
        season_id: str,
        champion_id: int,
        placement: int,
        is_win: bool,
        cr_delta: float,
    ) -> None:
        """In-memory read-modify-write of one champion_stats row (no DB round-trip).

        Operates on the pre-loaded ``champ_stats`` map; creates + registers the
        row (and caches it) on first sight of a ``(player, champion)`` pair.
        """
        cs = champ_stats.get((player_id, champion_id))
        if cs is None:
            cs = m.ChampionStat(
                player_id=player_id,
                season_id=season_id,
                champion_id=champion_id,
                matches_played=0,
                wins=0,
                top_half=0,
                total_placement_sum=0,
                cr_delta_sum=0.0,
                last10_placements=[],
            )
            session.add(cs)
            champ_stats[(player_id, champion_id)] = cs
        cs.matches_played += 1
        if is_win:
            cs.wins += 1
            cs.top_half += 1
        cs.total_placement_sum += placement
        cs.cr_delta_sum += cr_delta
        # keep a trailing window of the last 10 placements (most-recent last).
        window = list(cs.last10_placements or [])
        window.append(placement)
        cs.last10_placements = window[-10:]

    async def _mark_processed(
        self,
        session: AsyncSession,
        match: RawMatch,
        verdict: IntegrityVerdict,
        now: datetime,
    ) -> None:
        """Set ``processed=true`` on the match row, creating it if ingestion
        only staged it in Redis. The flag is the idempotency anchor."""
        row = await session.execute(select(m.Match).where(m.Match.id == match.match_id).limit(1))
        match_row = row.scalar_one_or_none()
        flags_summary = [{"flagType": f.flag_type, "severity": f.severity} for f in verdict.flags]
        if match_row is None:
            session.add(
                m.Match(
                    id=match.match_id,
                    riot_match_id=match.riot_match_id,
                    queue_id=match.queue_id,
                    mode=_to_mode(match.mode),
                    season_id=match.season_id,
                    played_at=_parse_iso(match.played_at),
                    processed_at=now,
                    processed=True,
                    integrity_flags=flags_summary,
                    duration_seconds=match.duration_seconds,
                )
            )
        else:
            match_row.processed = True
            match_row.processed_at = now
            match_row.integrity_flags = flags_summary


# ---------------------------------------------------------------------------
# helpers (module-level, pure)
# ---------------------------------------------------------------------------


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


#: Chaves de ``match_participants.state_before``. Espelham 1:1 os campos
#: INDEPENDENTES de :class:`arena.rating.types.PlayerState` — ``cr`` deriva de
#: (mu, sigma) e ``is_provisional`` de ``placement_matches_remaining``, então
#: guardá-los seria redundante e um convite a divergirem.
_STATE_BEFORE_KEYS = (
    "mu",
    "sigma",
    "current_streak",
    "matches_played",
    "placement_matches_remaining",
    "peak_cr",
)


def state_before_to_json(ps: m.PlayerSeason) -> dict[str, object]:
    """Snapshot do PlayerState de um jogador ANTES da partida corrente.

    Tem de ser chamado antes de ``_persist`` mutar a linha ``player_seasons``
    in-place. Ver o comentário em ``models.MatchParticipant.state_before`` para
    o porquê deste ponto de restauração existir.
    """
    return {
        "mu": ps.mu,
        "sigma": ps.sigma,
        "current_streak": ps.current_streak,
        "matches_played": ps.matches_played,
        "placement_matches_remaining": ps.placement_matches_remaining,
        "peak_cr": ps.peak_cr,
    }


def apply_state_before(
    ps: m.PlayerSeason, snapshot: dict[str, Any], *, params: RatingParams = DEFAULT_PARAMS
) -> None:
    """Restaura ``player_seasons`` a partir de um ``state_before`` — o inverso.

    ``cr`` e ``is_provisional`` são RECALCULADOS a partir dos campos
    independentes em vez de lidos, para a identidade
    ``cr = (mu - 3*sigma)*scale + offset`` não poder ser violada por um snapshot
    antigo. ``params`` tem de ser o MESMO do RatingService que vai reprocessar —
    escala/offset diferentes produziriam um cr inconsistente com o mu/sigma
    restaurado. Levanta ``KeyError`` se faltar chave: um snapshot truncado tem
    de falhar alto, não restaurar estado pela metade.
    """
    missing = [k for k in _STATE_BEFORE_KEYS if k not in snapshot]
    if missing:
        raise KeyError(f"state_before incompleto, faltam {missing}")
    ps.mu = float(snapshot["mu"])
    ps.sigma = float(snapshot["sigma"])
    ps.current_streak = int(snapshot["current_streak"])
    ps.matches_played = int(snapshot["matches_played"])
    ps.placement_matches_remaining = int(snapshot["placement_matches_remaining"])
    ps.peak_cr = float(snapshot["peak_cr"])
    ps.cr = params.base_offset + (ps.mu - 3.0 * ps.sigma) * params.scale_factor
    ps.is_provisional = ps.placement_matches_remaining > 0


def _finite_or_none(x: float) -> float | None:
    """``float('inf')``/``float('-inf')`` -> ``None`` (JSON has no Infinity
    token; Postgres's json/jsonb parser rejects it). Finite values pass through
    unchanged; NaN (should never occur here) also maps to ``None`` defensively."""
    from math import isfinite

    return x if isfinite(x) else None


def _modifiers_to_json(pr: PlayerRatingResult) -> dict[str, object]:
    """Serialize the engine's AppliedModifiers snapshot for the JSONB column.

    Internal analytics shape (mu-space deltas); the API layer remaps to the
    UI-safe ``Modifier`` DTO and never exposes raw mu values.

    The 11 original keys (through ``eligible``) are the pre-Raio-X contract and
    stay byte-identical for the ~1.5M already-persisted rows. Everything from
    ``explainVersion`` on is new, additive, CR-space-only input for
    ``arena/rating/explain.py`` — a row missing these keys (``explainVersion``
    absent/0) is handled by the read-time reconstruction path, not by a migration.
    """
    mods = pr.modifiers
    out: dict[str, object] = {
        "plBaseDeltaMu": mods.pl_base_delta_mu,
        "placementWeight": mods.placement_weight,
        "placementAmp": mods.placement_amp,
        "streakMult": mods.streak_mult,
        "softCapFactor": mods.soft_cap_factor,
        "boostingFactor": mods.boosting_factor,
        "partyFactor": mods.party_factor,
        "dispersionClamped": mods.dispersion_clamped,
        "finalDeltaMu": mods.final_delta_mu,
        "crDelta": pr.cr_delta,
        "eligible": pr.eligible,
        "explainVersion": 1,
        "paramsEpoch": PARAMS_EPOCH,
        "confidencePdl": pr.confidence_cr,
        "preCapCrDelta": pr.pre_cap_cr_delta,
        "teamCount": pr.team_count,
    }
    if pr.cap is not None:
        c = pr.cap
        out["cap"] = {
            "active": c.active,
            "bound": c.bound,
            # JSON has no Infinity token — Postgres's json/jsonb parser rejects
            # it outright ("invalid input syntax for type json"). cap_bounds()
            # legitimately returns +-inf as its "no curve configured for this
            # team_count" sentinel (e.g. a match shape caps.py has no curve
            # for); null is the correct JSON-safe spelling of "unbounded".
            "lo": _finite_or_none(c.lo),
            "hi": _finite_or_none(c.hi),
            "minGain": c.min_gain,
            "mismatchOverride": c.mismatch_override,
            "highCrScale": c.high_cr_scale,
            "compositeWin": c.composite_win,
            "compositeLoss": c.composite_loss,
            "gainFloorMult": c.gain_floor_mult,
            "teamCount": c.team_count,
            # lobby_mean_mu is intentionally NOT persisted here: it never needs to
            # leave the engine (the read path recomputes it from state_before when
            # reconstructing a legacy row), and mu-space values must not sit in a
            # JSONB column the API layer could someday serialize by accident.
        }
    return out


def _to_severity(value: str) -> m.Severity:
    return m.Severity[value.upper()]


def _to_mode(value: str) -> m.RatingMode:
    return m.RatingMode[value.upper()]


def get_rating_service() -> "WorkerRatingService":
    """Factory the arq workers resolve via ``arena.workers.deps.get_rating_service``.

    Returns the worker-facing adapter (Riot payload -> RawMatch -> this service).
    Imported lazily to avoid a circular import with
    :mod:`arena.services.match_pipeline` (which imports ``RatingService`` from here).
    """
    from arena.services.match_pipeline import get_rating_service as _factory

    return _factory()


__all__ = ["RatingService", "ProcessOutcome", "get_rating_service"]
