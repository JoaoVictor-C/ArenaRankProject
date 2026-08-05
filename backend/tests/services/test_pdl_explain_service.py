"""``PdlExplainService`` — integration smoke test against a real, already-migrated
Postgres (read-only; no fixtures created or cleaned up).

Every row in a real dev/prod DB predates this feature's ``explainVersion``/``cap``
JSONB keys until the season is rerated again, so this exercises the Tier-B legacy
reconstruction path specifically — the harder case, and the one the pure unit
tests in ``backend/tests/rating/test_explain_legacy.py`` already prove reconciles
in isolation. This test additionally proves the DB wiring (the real query, the
real ``state_before`` JSONB shape) agrees with that proof, and that nothing
mu/sigma-shaped leaks through the serialized DTO.
"""

from __future__ import annotations

import json
import os
import re

import pytest
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="pdl explain service tests need a migrated Postgres (set DATABASE_URL)",
)

_CAMEL_WORD = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z]|$|[0-9])")


def _camel_words(key: str) -> list[str]:
    """Split a camelCase/snake_case key into lowercase words -- so "multiplierPct"
    (contains "mu" only as a substring of "multiplier") is correctly NOT flagged,
    while "muBefore"/"sigmaAfter"/"lobbyMeanMu" (which really do carry mu/sigma as
    a distinct word) are."""
    return [w.lower() for w in _CAMEL_WORD.findall(key.replace("_", " "))]


def _is_forbidden_key(key: str) -> bool:
    words = _camel_words(key)
    if "mu" in words or "sigma" in words:
        return True
    return "lobby" in words and "mean" in words


async def _any_eligible_participant():
    """(match_id, riot_id) for some real, eligible participant row — whatever the
    connected DB happens to have. Skips (not fails) if the DB is reachable but
    genuinely empty (e.g. a fresh dev seed with no matches yet)."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from arena.db import models as m

    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        row = (
            await session.execute(
                select(m.MatchParticipant.match_id, m.Player.summoner_name, m.Player.tag_line)
                .join(m.Player, m.Player.id == m.MatchParticipant.player_id)
                .where(m.MatchParticipant.eligible.is_(True))
                .limit(1)
            )
        ).first()
    await engine.dispose()
    if row is None:
        pytest.skip("no eligible match_participants row found in the connected DB")
    return str(row.match_id), f"{row.summoner_name}#{row.tag_line}"


async def test_explain_participant_reconciles_against_real_data() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from arena.services.pdl_explain_service import PdlExplainService

    match_id, riot_id = await _any_eligible_participant()

    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        dto = await PdlExplainService().explain_participant(
            session, match_id=match_id, riot_id=riot_id
        )
    await engine.dispose()

    assert dto.fidelity in ("exato", "derivado", "parcial")
    assert dto.reconciles is True
    assert abs(dto.residual_pdl) < 1e-6
    assert sum(e.pdl for e in dto.entries) == dto.total_pdl


async def test_explain_participant_lobby_includes_every_participant_once() -> None:
    """The cross-team comparison this feature adds: PdlExplanation.lobby must
    list every participant of the SAME match exactly once, sorted by placement,
    with exactly one `is_you` entry matching the requested player's own placement
    and cr_delta — the direct "what did the other teams get" answer."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from arena.db import models as m
    from arena.services.pdl_explain_service import PdlExplainService

    match_id, riot_id = await _any_eligible_participant()

    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        dto = await PdlExplainService().explain_participant(
            session, match_id=match_id, riot_id=riot_id
        )
        expected_count = (
            await session.execute(
                select(m.MatchParticipant.player_id).where(
                    m.MatchParticipant.match_id == match_id
                )
            )
        ).all()
    await engine.dispose()

    assert len(dto.lobby) == len(expected_count)
    you = [e for e in dto.lobby if e.is_you]
    assert len(you) == 1
    assert you[0].placement == dto.placement
    assert you[0].cr_delta == dto.total_pdl
    assert [e.placement for e in dto.lobby] == sorted(e.placement for e in dto.lobby)


async def test_explain_participant_never_leaks_mu_sigma_or_lobby_mean() -> None:
    """Walk the serialized JSON keys/values -- nothing mu/sigma/lobby-mean-shaped
    may appear anywhere in the wire payload (ToS rule, see
    arena/schemas/common.py's module docstring)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from arena.services.pdl_explain_service import PdlExplainService

    match_id, riot_id = await _any_eligible_participant()

    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        dto = await PdlExplainService().explain_participant(
            session, match_id=match_id, riot_id=riot_id
        )
    await engine.dispose()

    raw = json.loads(dto.model_dump_json(by_alias=True))
    _walk_keys_assert_clean(raw)


def _walk_keys_assert_clean(node: object, path: str = "$") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            assert not _is_forbidden_key(key), (
                f"forbidden key {key!r} at {path}.{key} -- possible mu/sigma/lobby-mean leak"
            )
            _walk_keys_assert_clean(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _walk_keys_assert_clean(item, f"{path}[{i}]")
