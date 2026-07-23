"""TournamentService — persisted tournaments over the normalized schema.

Source of truth for the tournaments subsystem (contract §5 + onboarding/admin).
Backed by three tables (``tournaments`` / ``tournament_teams`` /
``tournament_matches``); the scoring source of truth is the pure
:func:`arena.tournaments.scoring.compute_standings`.

Read paths fall back to the DTO sample (``t001``/``t002``) when the table is
empty or the requested id is a known sample id (contract §5).

Concurrency: every mutation that touches team/match state runs inside one
transaction and locks the tournament's rows with ``SELECT … FOR UPDATE`` so
concurrent onboarding (create/join) and result submission stay consistent.

Conventions honored here:
* User-facing error strings are PT-BR (raised as ``HTTPException``).
* CR/mu/sigma never appear — tournaments are points-based (``total``/``perMatch``).
* JSON wire keys are camelCase; that is applied by the Pydantic DTO layer, so the
  jsonb player slots persisted here already use camelCase keys (``riotId`` etc.)
  to match the ``PlayerSlot`` DTO 1:1.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arena.db import models as m
from arena.schemas.tournaments import (
    AccessResponse,
    AccessTeamSlot,
    PrizeRow,
    ScoringEntry,
    StandingRow,
    TeamRoster,
    TournamentCreate,
    TournamentDetail,
    TournamentListItem,
    TournamentMatch,
    TournamentMatchResult,
    TournamentMatchResultEntry,
    TournamentMatchResultRow,
    TournamentRules,
)
from arena.tournaments import provision as P
from arena.tournaments.scoring import MatchResult, compute_standings

HTTP_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", status.HTTP_422_UNPROCESSABLE_ENTITY)

_DEFAULT_CURRENCY = "RP"


def _parse_id(tournament_id: str) -> uuid.UUID | None:
    """Parse a path id into a UUID, or ``None`` when it is not a real DB id."""
    try:
        return uuid.UUID(tournament_id)
    except (ValueError, AttributeError):
        return None


def _to_iso(dt: datetime | None) -> str:
    return dt.isoformat() if dt is not None else datetime.now(tz=UTC).isoformat()


class TournamentService:
    """Application-layer use cases for the tournaments subsystem."""

    # -- reads -------------------------------------------------------------

    async def list_tournaments(self, session: AsyncSession) -> list[TournamentListItem]:
        """List provisioned tournaments (newest first).

        Returns an empty list when none exist — the UI renders an honest empty
        state. Tournaments are operator-created (``POST /admin/tournaments``); there
        is no DTO-sample fallback (they must never be presented as real events).
        """
        rows = (
            (await session.execute(select(m.Tournament).order_by(m.Tournament.created_at.desc())))
            .scalars()
            .all()
        )
        out: list[TournamentListItem] = []
        for t in rows:
            currency = _currency_of(t)
            out.append(
                TournamentListItem(
                    id=str(t.id),
                    title=t.title,
                    format=t.format,
                    starts_at=_to_iso(t.starts_at),
                    teams=t.num_teams,
                    prize_rp=t.prize_rp,
                    banner_tone=t.banner_tone,  # type: ignore[arg-type]
                    tag=t.tag or "ABERTO",
                    amount_label=P.fmt_money(t.prize_rp, currency),
                    when_label=P.when_label(t.starts_at),
                )
            )
        return out

    async def get_detail(
        self, session: AsyncSession, tournament_id: str, *, as_admin: bool = False
    ) -> TournamentDetail:
        """Full tournament detail. Raises 404 for an unknown id (no sample fallback)."""
        pk = _parse_id(tournament_id)
        if pk is not None:
            row = await self._load(session, pk)
            if row is not None:
                return self._project(*row, as_admin=as_admin)

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Torneio '{tournament_id}' não encontrado.",
        )

    # -- provisioning (admin) ---------------------------------------------

    async def create_tournament(
        self, session: AsyncSession, body: TournamentCreate
    ) -> TournamentDetail:
        """Provision a tournament: persist tournament + empty teams + upcoming matches.

        Returns the full TournamentDetail (status ``upcoming``, zeroed standings,
        empty player slots) including the generated ``accessKey``.
        """
        num_teams = body.num_teams
        num_matches = body.num_matches
        fmt = body.format
        size = P.team_size(fmt)
        currency = body.currency or _DEFAULT_CURRENCY
        access_key = body.access_key or P.gen_access_key()
        scoring = (
            [s.model_dump() for s in body.scoring] if body.scoring else P.default_scoring(num_teams)
        )
        starts_at = _parse_starts_at(body.starts_at)

        tournament = m.Tournament(
            title=body.title,
            format=fmt,
            status=m.TournamentStatus.upcoming,
            num_teams=num_teams,
            num_matches=num_matches,
            current_match=1,
            prize_rp=body.prize_rp,
            banner_tone=body.banner_tone or "b1",
            tag=body.tag or "ABERTO",
            starts_at=starts_at,
            scoring=_scoring_blob(scoring, body, currency),
            access_key=access_key,
        )
        session.add(tournament)
        await session.flush()  # assign tournament.id

        lobby_max = num_teams * size
        for j in range(1, num_teams + 1):
            session.add(
                m.TournamentTeam(
                    tournament_id=tournament.id,
                    seed=j,
                    team_name=f"Equipe {j}",
                    captain=None,
                    players=P.empty_slots(size),
                    per_match=[],
                    penalties=0,
                    bonus=0,
                    total=0,
                )
            )
        for n in range(1, num_matches + 1):
            session.add(
                m.TournamentMatch(
                    tournament_id=tournament.id,
                    n=n,
                    status=m.TournamentMatchStatus.upcoming,
                    winner_team_id=None,
                    starts_at=starts_at,
                    lobby_max=lobby_max,
                    lobby_count=0,
                    magnetic_link=f"arena://lobby/{tournament.id}/m{n}",
                    result=None,
                )
            )

        await session.commit()
        row = await self._load(session, tournament.id)
        assert row is not None
        return self._project(*row, as_admin=True)

    # -- onboarding (players) ---------------------------------------------

    async def validate_access(
        self, session: AsyncSession, tournament_id: str, key: str
    ) -> AccessResponse:
        """Validate an access key → list teams with open slots. 403 if invalid."""
        pk = _require_db_id(tournament_id)
        tournament = await session.get(m.Tournament, pk)
        if tournament is None or P.normalize_key(tournament.access_key) != P.normalize_key(key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Chave de acesso inválida."
            )

        size = P.team_size(tournament.format)
        teams = (
            (
                await session.execute(
                    select(m.TournamentTeam)
                    .where(m.TournamentTeam.tournament_id == pk)
                    .order_by(m.TournamentTeam.seed)
                )
            )
            .scalars()
            .all()
        )
        return AccessResponse(
            tournament_id=tournament_id,
            teams=[
                AccessTeamSlot(
                    team_id=str(t.id),
                    team_name=t.team_name,
                    open_slots=max(0, size - P.count_real_players(t.players)),
                )
                for t in teams
            ],
        )

    async def create_team(
        self, session: AsyncSession, tournament_id: str, key: str, team_name: str, riot_id: str
    ) -> str:
        """Claim the first free team, name it, register the captain. Returns teamId.

        403 invalid key · 409 no free team / duplicate riotId.
        """
        pk = _require_db_id(tournament_id)
        async with session.begin():
            tournament = await self._lock_tournament(session, pk, key)
            teams = await self._lock_teams(session, pk)
            self._reject_duplicate_riot_id(teams, riot_id)

            free = next((t for t in teams if P.count_real_players(t.players) == 0), None)
            if free is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Sem vagas de equipe disponíveis.",
                )

            size = P.team_size(tournament.format)
            captain = P.make_player_slot(riot_id)
            free.team_name = team_name
            free.captain = cast("str", captain["name"])
            free.players = [captain, *P.empty_slots(size - 1)]
            return str(free.id)

    async def join_team(
        self, session: AsyncSession, tournament_id: str, key: str, team_id: str, riot_id: str
    ) -> str:
        """Join an existing team in its first empty slot. Returns teamId.

        403 invalid key · 404 unknown team · 409 team full / duplicate riotId.
        """
        pk = _require_db_id(tournament_id)
        team_pk = _parse_id(team_id)
        async with session.begin():
            await self._lock_tournament(session, pk, key)
            teams = await self._lock_teams(session, pk)
            self._reject_duplicate_riot_id(teams, riot_id)

            team = next((t for t in teams if t.id == team_pk), None)
            if team is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Equipe '{team_id}' não encontrada.",
                )

            players = list(team.players)
            slot = next((i for i, p in enumerate(players) if p.get("empty")), None)
            if slot is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Equipe já está cheia."
                )
            players[slot] = P.make_player_slot(riot_id)
            team.players = players
            return str(team.id)

    # -- admin match mutations --------------------------------------------

    async def set_match_link(
        self,
        session: AsyncSession,
        tournament_id: str,
        n: int,
        magnetic_link: str,
        match_status: str,
    ) -> TournamentDetail:
        """Set a match's magnetic link + status; keep tournament status coherent.

        422 when ``n`` is out of range.
        """
        pk = _require_db_id(tournament_id)
        async with session.begin():
            tournament = await self._lock_tournament_only(session, pk)
            matches = await self._lock_matches(session, pk)
            match = self._match_or_422(matches, n, tournament.num_matches)

            match.magnetic_link = magnetic_link
            match.status = m.TournamentMatchStatus(match_status)

            if match_status == "live":
                if tournament.status == m.TournamentStatus.upcoming:
                    tournament.status = m.TournamentStatus.live
                tournament.current_match = n
            elif match_status == "ended" and n + 1 <= tournament.num_matches:
                tournament.current_match = n + 1

        row = await self._load(session, pk)
        assert row is not None
        return self._project(*row, as_admin=True)

    async def submit_result(
        self,
        session: AsyncSession,
        tournament_id: str,
        n: int,
        results: list[TournamentMatchResultEntry],
        penalties: dict[str, int] | None,
    ) -> TournamentDetail:
        """Submit a match result; recompute standings via ``compute_standings``.

        422 when ``n`` is out of range. ``perMatch`` reflects ended matches only.
        """
        pk = _require_db_id(tournament_id)
        async with session.begin():
            tournament = await self._lock_tournament_only(session, pk)
            matches = await self._lock_matches(session, pk)
            teams = await self._lock_teams(session, pk)
            match = self._match_or_422(matches, n, tournament.num_matches)

            match.result = [
                {"teamId": r.team_id, "placement": r.placement, "bravura": r.bravura}
                for r in results
            ]
            match.status = m.TournamentMatchStatus.ended
            match.winner_team_id = _winner_uuid(results)

            # Merge admin penalties into per-team running totals.
            if penalties:
                for t in teams:
                    add = penalties.get(str(t.id))
                    if add:
                        t.penalties += add

            # Recompute standings from all ended matches (scoring source of truth).
            scoring = P.scoring_to_dict(_scoring_list(tournament))
            team_ids = [str(t.id) for t in teams]
            match_results = _build_match_results(matches)
            pen_map = {str(t.id): t.penalties for t in teams}
            rows = compute_standings(team_ids, match_results, scoring, pen_map)

            by_id = {str(t.id): t for t in teams}
            for sr in rows:
                team = by_id[sr.team_id]
                team.per_match = list(sr.per_match)
                team.bonus = sr.bonus
                team.total = sr.total

            # Coherence: tournament becomes live, advance / close.
            if tournament.status == m.TournamentStatus.upcoming:
                tournament.status = m.TournamentStatus.live
            if n + 1 <= tournament.num_matches:
                tournament.current_match = n + 1
            elif all(mm.status == m.TournamentMatchStatus.ended for mm in matches):
                tournament.status = m.TournamentStatus.ended

        row = await self._load(session, pk)
        assert row is not None
        return self._project(*row, as_admin=True)

    # -- internals: loading / locking -------------------------------------

    async def _load(
        self, session: AsyncSession, pk: uuid.UUID
    ) -> tuple[m.Tournament, list[m.TournamentTeam], list[m.TournamentMatch]] | None:
        tournament = await session.get(m.Tournament, pk)
        if tournament is None:
            return None
        teams = (
            (
                await session.execute(
                    select(m.TournamentTeam)
                    .where(m.TournamentTeam.tournament_id == pk)
                    .order_by(m.TournamentTeam.seed)
                )
            )
            .scalars()
            .all()
        )
        matches = (
            (
                await session.execute(
                    select(m.TournamentMatch)
                    .where(m.TournamentMatch.tournament_id == pk)
                    .order_by(m.TournamentMatch.n)
                )
            )
            .scalars()
            .all()
        )
        return tournament, list(teams), list(matches)

    async def _lock_tournament(
        self, session: AsyncSession, pk: uuid.UUID, key: str
    ) -> m.Tournament:
        tournament = await self._lock_tournament_only(session, pk)
        if P.normalize_key(tournament.access_key) != P.normalize_key(key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Chave de acesso inválida."
            )
        return tournament

    async def _lock_tournament_only(self, session: AsyncSession, pk: uuid.UUID) -> m.Tournament:
        tournament = (
            await session.execute(
                select(m.Tournament).where(m.Tournament.id == pk).with_for_update()
            )
        ).scalar_one_or_none()
        if tournament is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Torneio não encontrado."
            )
        return tournament

    async def _lock_teams(self, session: AsyncSession, pk: uuid.UUID) -> list[m.TournamentTeam]:
        return list(
            (
                await session.execute(
                    select(m.TournamentTeam)
                    .where(m.TournamentTeam.tournament_id == pk)
                    .order_by(m.TournamentTeam.seed)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )

    async def _lock_matches(self, session: AsyncSession, pk: uuid.UUID) -> list[m.TournamentMatch]:
        return list(
            (
                await session.execute(
                    select(m.TournamentMatch)
                    .where(m.TournamentMatch.tournament_id == pk)
                    .order_by(m.TournamentMatch.n)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    def _reject_duplicate_riot_id(teams: list[m.TournamentTeam], riot_id: str) -> None:
        target = riot_id.strip().upper()
        for t in teams:
            for p in t.players:
                rid = p.get("riotId")
                if not p.get("empty") and rid and str(rid).strip().upper() == target:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Riot ID já inscrito neste torneio.",
                    )

    @staticmethod
    def _match_or_422(
        matches: list[m.TournamentMatch], n: int, num_matches: int
    ) -> m.TournamentMatch:
        if n < 1 or n > num_matches:
            raise HTTPException(status_code=HTTP_422, detail=f"Partida {n} fora do intervalo.")
        match = next((mm for mm in matches if mm.n == n), None)
        if match is None:
            raise HTTPException(
                status_code=HTTP_422, detail=f"Partida {n} não existe neste torneio."
            )
        return match

    # -- internals: projection (ORM rows → DTO) ---------------------------

    def _project(
        self,
        tournament: m.Tournament,
        teams: list[m.TournamentTeam],
        matches: list[m.TournamentMatch],
        *,
        as_admin: bool,
    ) -> TournamentDetail:
        currency = _currency_of(tournament)
        size = P.team_size(tournament.format)
        scoring_list = _scoring_list(tournament)
        prize_split = _prize_split(tournament)

        standings = sorted(
            (
                StandingRow(
                    team_id=str(t.id),
                    seed=t.seed,
                    team_name=t.team_name,
                    players=t.players,
                    per_match=list(t.per_match),
                    penalties=t.penalties,
                    bonus=t.bonus,
                    total=t.total,
                    is_you=None,
                )
                for t in teams
            ),
            key=lambda s: -s.total,
        )
        registrations = [
            TeamRoster(
                team_id=str(t.id),
                team_name=t.team_name,
                seed=t.seed,
                captain=t.captain or "",
                is_you=None,
                players=t.players,
            )
            for t in teams
        ]
        team_name_by_id = {str(t.id): t.team_name for t in teams}
        scoring_map = P.scoring_to_dict(scoring_list)

        match_dtos = [
            TournamentMatch(
                n=mm.n,
                status=mm.status.value,
                winner_team_id=str(mm.winner_team_id) if mm.winner_team_id else None,
                starts_at=_to_iso(mm.starts_at) if mm.starts_at else None,
                lobby_max=mm.lobby_max,
                lobby_count=mm.lobby_count,
                magnetic_link=mm.magnetic_link or "",
                result=[
                    TournamentMatchResultEntry(
                        team_id=str(r["teamId"]),
                        placement=int(r["placement"]),
                        bravura=int(r.get("bravura", 0)),
                    )
                    for r in (mm.result or [])
                ]
                or None,
            )
            for mm in matches
        ]

        history = [
            TournamentMatchResult(
                n=mm.n,
                status=mm.status.value,
                results=_history_rows(mm, team_name_by_id, scoring_map),
            )
            for mm in matches
        ]

        return TournamentDetail(
            id=str(tournament.id),
            title=tournament.title,
            format=tournament.format,
            prize_rp=tournament.prize_rp,
            prize_label=P.fmt_money(tournament.prize_rp, currency),
            currency=currency,
            status=tournament.status.value,
            current_match=tournament.current_match,
            matches=match_dtos,
            standings=standings,
            rules=TournamentRules(
                format=P.format_lines(
                    tournament.num_teams, tournament.num_matches, tournament.format
                ),
                scoring=[ScoringEntry(place=s["place"], points=s["points"]) for s in scoring_list],
                tiebreak=_tiebreak(tournament),
                currency=currency,
            ),
            prizes=[
                PrizeRow(
                    place=p["place"],
                    rp=p["rp"],
                    per_player=p["perPlayer"],
                    medal=p["medal"],  # type: ignore[arg-type]
                )
                for p in P.build_prizes(tournament.prize_rp, size, prize_split)
            ],
            registrations=registrations,
            history=history,
            access_key=tournament.access_key if as_admin else None,
        )


# ---------------------------------------------------------------------------
# Module-level helpers (pure)
# ---------------------------------------------------------------------------


def _require_db_id(tournament_id: str) -> uuid.UUID:
    pk = _parse_id(tournament_id)
    if pk is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Torneio '{tournament_id}' não encontrado.",
        )
    return pk


def _parse_starts_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _scoring_blob(
    scoring: list[dict[str, int]], body: TournamentCreate, currency: str
) -> dict[str, object]:
    """Bundle scoring + ancillary rules into the ``tournaments.scoring`` jsonb."""
    blob: dict[str, object] = {"scoring": scoring, "currency": currency}
    if body.tiebreak:
        blob["tiebreak"] = body.tiebreak
    if body.prize_split:
        blob["prizeSplit"] = [s.model_dump() for s in body.prize_split]
    return blob


def _scoring_blob_of(tournament: m.Tournament) -> dict[str, object]:
    raw = tournament.scoring
    return raw if isinstance(raw, dict) else {}


def _scoring_list(tournament: m.Tournament) -> list[dict[str, int]]:
    raw = tournament.scoring
    if isinstance(raw, list):  # legacy: bare scoring list
        return [{"place": int(s["place"]), "points": int(s["points"])} for s in raw]
    blob = _scoring_blob_of(tournament)
    scoring = blob.get("scoring")
    if isinstance(scoring, list) and scoring:
        return [{"place": int(s["place"]), "points": int(s["points"])} for s in scoring]
    return P.default_scoring(tournament.num_teams)


def _currency_of(tournament: m.Tournament) -> str:
    blob = _scoring_blob_of(tournament)
    cur = blob.get("currency")
    return cur if isinstance(cur, str) else _DEFAULT_CURRENCY


def _prize_split(tournament: m.Tournament) -> list[dict[str, float]] | None:
    blob = _scoring_blob_of(tournament)
    split = blob.get("prizeSplit")
    if isinstance(split, list) and split:
        return [{"place": int(s["place"]), "pct": float(s["pct"])} for s in split]
    return None


def _tiebreak(tournament: m.Tournament) -> list[str]:
    blob = _scoring_blob_of(tournament)
    tb = blob.get("tiebreak")
    if isinstance(tb, list) and tb:
        return [str(x) for x in tb]
    return P.default_tiebreak()


def _winner_uuid(results: list[TournamentMatchResultEntry]) -> uuid.UUID | None:
    for r in results:
        if r.placement == 1:
            try:
                return uuid.UUID(r.team_id)
            except (ValueError, AttributeError):
                return None
    return None


def _build_match_results(matches: list[m.TournamentMatch]) -> list[MatchResult | None]:
    """Project ended matches into pure ``MatchResult`` inputs for the scoring engine."""
    out: list[MatchResult | None] = []
    for mm in matches:
        if mm.status == m.TournamentMatchStatus.ended and mm.result:
            placements: dict[str, int] = {}
            bravura: dict[str, int] = {}
            for entry in mm.result:
                tid = str(entry["teamId"])
                placements[tid] = int(entry["placement"])
                b = int(entry.get("bravura", 0))
                if b:
                    bravura[tid] = b
            out.append(MatchResult(placements=placements, bravura=bravura))
        else:
            out.append(None)
    return out


def _history_rows(
    match: m.TournamentMatch,
    team_name_by_id: dict[str, str],
    scoring_map: dict[int, int],
) -> list[TournamentMatchResultRow]:
    if match.status != m.TournamentMatchStatus.ended or not match.result:
        return []
    rows = sorted(match.result, key=lambda r: int(r["placement"]))
    return [
        TournamentMatchResultRow(
            team_name=team_name_by_id.get(str(r["teamId"]), str(r["teamId"])),
            points=scoring_map.get(int(r["placement"]), 0),
            place=int(r["placement"]),
        )
        for r in rows
    ]


__all__ = ["TournamentService"]
