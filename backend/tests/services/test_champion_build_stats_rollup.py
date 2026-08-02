"""``champion_build_stats`` — augment/item build stats materializadas (NATIVAS).

Substitui o agregado externo (``champion_build_ref``, ver ``build_ref_service.py``)
como fonte do painel "Build recomendada" e da aba "Augments em alta". Mesma
família dos outros rollups desta série (``champion_combo_stats``,
``champion_daily_stats``): um agregado por-request sobre ``match_participants``
seria o mesmo tipo de scan caro que motivou os anteriores.

Aceites:

* ``unnest()`` sobre as colunas ARRAY reproduz corretamente games/top1/top4/
  colocação — sem inflar via cartesian product (a preocupação óbvia de usar
  ``unnest`` lateral implícito do Postgres);
* um participante com o MESMO pick repetido (efeito que concede um augment
  extra — visto ao vivo: id 238 duas vezes) conta como UM jogo, não dois —
  bug real encontrado e corrigido nesta sessão: o ``unnest`` cru contava a
  linha duas vezes, inflando o games E pesando a colocação em dobro;
  o array vazio/NULL (participante pré-migração, sem captura) não derruba
  o agregado — ``unnest(NULL)`` não produz linha nenhuma, não erro;
* augment e item nunca se misturam (o mesmo pick_id numérico não é comparável
  entre os dois catálogos);
* elegibilidade é respeitada (mesmo predicado do resto do rollup);
* ``rebuild_champion_build_stats`` é idempotente e recompute a temporada
  INTEIRA (cumulativo);
* o piso de escrita nunca pode subir acima dos pisos de leitura
  (``BUILD_MIN_GAMES``/``TOP_MIN_GAMES`` em ``build_ref_service``).

DB-gated: os agregados são SQL de Postgres (unnest sobre coluna ARRAY,
tabela particionada). A invariante pura roda sempre.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.pool import NullPool

from arena.core.config import settings
from arena.services.build_ref_service import BUILD_MIN_GAMES, TOP_MIN_GAMES
from arena.services.stats_service import StatsService

# ---------------------------------------------------------------------------
# Invariante pura: a relação entre os pisos de escrita e leitura
# ---------------------------------------------------------------------------


def test_write_floor_stays_below_both_read_floors() -> None:
    """Piso de escrita >= piso de leitura => a leitura perde picks que deveria mostrar."""
    assert settings.champion_build_min_games < BUILD_MIN_GAMES
    assert settings.champion_build_min_games < TOP_MIN_GAMES
    assert settings.champion_build_min_games >= 1


# ---------------------------------------------------------------------------
# Daqui para baixo: Postgres real
# ---------------------------------------------------------------------------

_db = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="build stats rollup tests need a migrated Postgres (set DATABASE_URL)",
)

DAY0 = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)

_CHAMP = 9001
_AUG_COMMON = 63  # picked by every participant below
_AUG_RARE = 220  # picked by only a couple — for the write-floor test
_AUG_GRANTED_TWICE = 238  # the duplicate-in-one-array case
_AUG_SAME_PLACEMENT = 500  # two DIFFERENT participants sharing (champion, placement, pick)
_ITEM_A = 223008


class _Fixture:
    def __init__(self) -> None:
        self.season_id = uuid.uuid4()
        self.match_ids: list[uuid.UUID] = []
        self.player_ids: list[uuid.UUID] = []

    async def add_participant(
        self,
        session: Any,
        *,
        placement: int,
        augments: list[int] | None,
        items: list[int] | None = None,
        eligible: bool = True,
        champion_id: int = _CHAMP,
    ) -> None:
        """Uma partida com UM participante (o resto do lobby é irrelevante aqui)."""
        from sqlalchemy import text

        mid = uuid.uuid4()
        pid = uuid.uuid4()
        self.match_ids.append(mid)
        self.player_ids.append(pid)
        await session.execute(
            text(
                "INSERT INTO matches (id, riot_match_id, queue_id, mode, season_id, "
                "played_at, processed, integrity_flags, duration_seconds) "
                "VALUES (:id,:rid,1750,'TRIOS',:s,:p,true,'[]'::jsonb,600)"
            ),
            {"id": mid, "rid": f"BS_{mid.hex[:12]}", "s": self.season_id, "p": DAY0},
        )
        await session.execute(
            text("INSERT INTO players (id,puuid) VALUES (:i,:p)"),
            {"i": pid, "p": f"buildstats-test-{pid.hex}"},
        )
        await session.execute(
            text(
                "INSERT INTO match_participants (id,match_id,player_id,played_at,"
                "champion_id,team_id,placement,eligible,cr_before,cr_after,cr_delta,"
                "is_premade,modifiers,augments,items) "
                "VALUES (:i,:m,:pl,:p,:c,1,:pc,:e,1000,1000,0,false,'{}'::jsonb,:augs,:items)"
            ),
            {
                "i": uuid.uuid4(), "m": mid, "pl": pid, "p": DAY0,
                "c": champion_id, "pc": placement, "e": eligible,
                "augs": augments, "items": items,
            },
        )

    async def cleanup(self, session: Any) -> None:
        from sqlalchemy import text

        await session.execute(
            text("DELETE FROM champion_build_stats WHERE season_id=:s"), {"s": self.season_id}
        )
        for mid in self.match_ids:
            await session.execute(
                text("DELETE FROM match_participants WHERE match_id=:m"), {"m": mid}
            )
            await session.execute(text("DELETE FROM matches WHERE id=:m"), {"m": mid})
        for pid in self.player_ids:
            await session.execute(text("DELETE FROM players WHERE id=:p"), {"p": pid})
        await session.execute(text("DELETE FROM seasons WHERE id=:s"), {"s": self.season_id})
        await session.commit()


@asynccontextmanager
async def _seeded() -> AsyncIterator[tuple[Any, _Fixture]]:
    """Temporada descartável. Engine própria (mesmo padrão do combo rollup)."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    fx = _Fixture()
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        try:
            await session.execute(
                text(
                    "INSERT INTO seasons (id,name,queue_id,status,starts_at,ends_at,config) "
                    "VALUES (:id,:n,1750,'ENDED',:s,:e,'{}'::jsonb)"
                ),
                {
                    "id": fx.season_id, "n": f"buildstats-test-{fx.season_id.hex[:8]}",
                    "s": DAY0 - timedelta(days=30), "e": DAY0 + timedelta(days=30),
                },
            )
            # 4 eligible participants: AUG_COMMON on all four; AUG_RARE on just one
            # (below any real floor); AUG_GRANTED_TWICE duplicated in one array.
            await fx.add_participant(
                session, placement=1,
                augments=[_AUG_COMMON, _AUG_GRANTED_TWICE, _AUG_GRANTED_TWICE],
                items=[_ITEM_A],
            )
            await fx.add_participant(session, placement=2, augments=[_AUG_COMMON], items=[_ITEM_A])
            await fx.add_participant(session, placement=4, augments=[_AUG_COMMON], items=None)
            await fx.add_participant(
                session, placement=5, augments=[_AUG_COMMON, _AUG_RARE], items=[_ITEM_A]
            )
            # Two DIFFERENT participants, same champion, same placement, same pick —
            # must both count (2 games), not collapse into 1. The dedup key must be
            # scoped per-participant, not (season, champion, placement, pick) alone.
            await fx.add_participant(session, placement=2, augments=[_AUG_SAME_PLACEMENT])
            await fx.add_participant(session, placement=2, augments=[_AUG_SAME_PLACEMENT])
            # Ineligible: must never count toward anything.
            await fx.add_participant(
                session, placement=1, augments=[_AUG_COMMON], eligible=False
            )
            # Pre-migration-shaped row: NULL augments/items — must not crash unnest.
            await fx.add_participant(session, placement=3, augments=None, items=None)
            await session.commit()
            yield session, fx
        finally:
            await session.rollback()
            await fx.cleanup(session)


async def _rebuild(session: Any, fx: _Fixture, floor: int = 1) -> int:
    n = await StatsService().rebuild_champion_build_stats(
        session, season_id=str(fx.season_id), min_games=floor
    )
    await session.commit()
    return n


async def _row(session: Any, fx: _Fixture, kind: str, pick_id: int) -> Any:
    from sqlalchemy import text

    return (
        await session.execute(
            text(
                "SELECT * FROM champion_build_stats "
                "WHERE season_id=:s AND kind=:k AND champion_id=:c AND pick_id=:p"
            ),
            {"s": fx.season_id, "k": kind, "c": _CHAMP, "p": pick_id},
        )
    ).one_or_none()


# ---------------------------------------------------------------------------
# NULL arrays and the cartesian-product false alarm
# ---------------------------------------------------------------------------


@_db
async def test_null_augments_do_not_crash_or_count() -> None:
    """A row with no capture yet (NULL) must vanish from the aggregate, not error."""
    async with _seeded() as (session, fx):
        n = await _rebuild(session, fx)
        assert n > 0  # the rebuild completed and wrote real rows
        common = await _row(session, fx, "augment", _AUG_COMMON)
        assert common is not None
        assert common.games == 4  # the 4 eligible participants, NOT the NULL/ineligible ones


@_db
async def test_unnest_correlates_per_row_not_a_cartesian_blowup() -> None:
    """Regression guard for the SAWarning: games must match real participant counts,
    not multiply across unrelated rows (which a true unconstrained cartesian
    product between match_participants and the unnested array would produce)."""
    async with _seeded() as (session, fx):
        await _rebuild(session, fx)
        common = await _row(session, fx, "augment", _AUG_COMMON)
        rare = await _row(session, fx, "augment", _AUG_RARE)
        assert common is not None and common.games == 4
        assert rare is not None and rare.games == 1


# ---------------------------------------------------------------------------
# O bug real: pick repetido no MESMO array
# ---------------------------------------------------------------------------


@_db
async def test_a_pick_repeated_in_one_array_counts_as_one_game() -> None:
    """The regression: id 238 appears twice in one participant's augments (an
    augment-granting effect). Must count as 1 game for that pick, not 2 — and
    must not double-weight that participant's single placement into top1/top4/
    placement_sum.
    """
    async with _seeded() as (session, fx):
        await _rebuild(session, fx)
        granted = await _row(session, fx, "augment", _AUG_GRANTED_TWICE)
        assert granted is not None
        assert granted.games == 1  # NOT 2 — one participant, one game
        assert granted.top1 == 1  # that participant placed 1st
        assert granted.placement_sum == 1  # NOT 2 (1+1 from double-counting)


@_db
async def test_different_participants_sharing_placement_and_pick_both_count() -> None:
    """The inverse regression: TWO DIFFERENT participants (different matches/
    players) who happen to share (champion, placement, pick) must both count —
    the intra-array dedup must not accidentally collapse across participants.
    A prior version keyed DISTINCT on (season, champion, placement, pick) alone,
    which silently undercounted every pick sharing a placement with another
    game (caught via live data: a champion with thousands of games showed only
    a handful of counted picks).
    """
    async with _seeded() as (session, fx):
        await _rebuild(session, fx)
        row = await _row(session, fx, "augment", _AUG_SAME_PLACEMENT)
        assert row is not None
        assert row.games == 2  # NOT 1 — two distinct participants
        assert row.placement_sum == 4  # 2 + 2, not collapsed to 2


# ---------------------------------------------------------------------------
# Elegibilidade, separação augment/item, piso de escrita, idempotência
# ---------------------------------------------------------------------------


@_db
async def test_ineligible_participants_are_excluded() -> None:
    async with _seeded() as (session, fx):
        await _rebuild(session, fx)
        common = await _row(session, fx, "augment", _AUG_COMMON)
        assert common is not None
        assert common.games == 4  # the 5th (ineligible) participant did not count


@_db
async def test_augment_and_item_kinds_never_mix() -> None:
    """The same numeric id could plausibly collide between the two catalogs —
    ``kind`` must keep them in separate cells."""
    async with _seeded() as (session, fx):
        await _rebuild(session, fx)
        item_row = await _row(session, fx, "item", _ITEM_A)
        assert item_row is not None
        assert item_row.games == 3  # 3 of the 4 eligible participants carried it
        # No augment row exists for the SAME numeric id under "augment" unless a
        # fixture augment happens to share it — here it simply must not equal
        # the item's count by coincidence of a shared kind bucket.
        assert await _row(session, fx, "augment", _ITEM_A) is None


@_db
async def test_write_floor_drops_the_tail() -> None:
    async with _seeded() as (session, fx):
        await _rebuild(session, fx, floor=1)
        assert await _row(session, fx, "augment", _AUG_RARE) is not None  # 1 game, floor=1
        await _rebuild(session, fx, floor=2)
        assert await _row(session, fx, "augment", _AUG_RARE) is None  # 1 game < floor=2
        assert (await _row(session, fx, "augment", _AUG_COMMON)).games == 4  # unaffected


@_db
async def test_rebuild_is_idempotent() -> None:
    from sqlalchemy import text

    async with _seeded() as (session, fx):
        q = text(
            "SELECT kind,champion_id,pick_id,games,top1,top4,placement_sum "
            "FROM champion_build_stats WHERE season_id=:s ORDER BY kind,champion_id,pick_id"
        )
        first = await _rebuild(session, fx)
        snap1 = (await session.execute(q, {"s": fx.season_id})).all()
        second = await _rebuild(session, fx)
        snap2 = (await session.execute(q, {"s": fx.season_id})).all()
        assert first == second
        assert snap1 == snap2 and snap1
