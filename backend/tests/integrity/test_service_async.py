"""Async integrity orchestration — folds the premade dampener into verdicts.

``evaluate_async`` records each subteam's co-occurrence pairs in the party store
and threads the resulting per-player ``party_penalty_factor`` into the verdicts the
rating engine consumes, alongside the existing repeated-lobby flag.
"""

from __future__ import annotations

import pytest

from arena.integrity.params import DEFAULT_INTEGRITY_PARAMS
from arena.integrity.service import evaluate_async
from arena.integrity.types import MatchSnapshot, ParticipantSnapshot


class _FakeLobbyStore:
    async def observe(self, fingerprint: str, match_id: str, window_seconds: int) -> int:
        return 1  # never trips the repeated-lobby threshold


class _FakePartyStore:
    """Returns a fixed count for every observed pair; records the observe call."""

    def __init__(self, count: int) -> None:
        self._count = count
        self.observed: list[str] = []

    async def observe(self, pair_keys, match_id, window_seconds):
        self.observed = list(pair_keys)
        return {pk: self._count for pk in pair_keys}


def _part(pid: str, team_id: int, cr: float) -> ParticipantSnapshot:
    return ParticipantSnapshot(player_id=pid, team_id=team_id, champion_id=0, cr=cr)


def _match(*parts: ParticipantSnapshot) -> MatchSnapshot:
    return MatchSnapshot(
        match_id="m", mode="DUOS", team_size=2, duration_seconds=600, participants=list(parts)
    )


@pytest.mark.asyncio
async def test_even_premade_gets_party_factor_in_verdict() -> None:
    match = _match(
        _part("a", 1, 1000.0), _part("b", 1, 1000.0),
        _part("c", 2, 1000.0), _part("d", 2, 1000.0),
    )
    party = _FakePartyStore(count=DEFAULT_INTEGRITY_PARAMS.premade_repeat_threshold)
    result = await evaluate_async(match, _FakeLobbyStore(), party, DEFAULT_INTEGRITY_PARAMS)
    v = result.verdict_for("a")
    assert v.party_penalty_factor == pytest.approx(DEFAULT_INTEGRITY_PARAMS.premade_strength)
    assert party.observed  # the party store was consulted


@pytest.mark.asyncio
async def test_solo_lobby_has_zero_party_factor() -> None:
    match = _match(
        _part("a", 1, 1000.0), _part("b", 1, 1000.0),
        _part("c", 2, 1000.0), _part("d", 2, 1000.0),
    )
    party = _FakePartyStore(count=1)  # no repeat history
    result = await evaluate_async(match, _FakeLobbyStore(), party, DEFAULT_INTEGRITY_PARAMS)
    assert result.verdict_for("a").party_penalty_factor == pytest.approx(0.0)
