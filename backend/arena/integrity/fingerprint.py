"""Lobby fingerprinting for repeated-lobby detection (proposal §3.2, §6.2).

A *fingerprint* is a stable hash of the lobby composition (the unordered set of
participating players, independent of teams/placement). The same five-or-six
players queueing together repeatedly is the match-fixing signal.

The fingerprint function is pure. The rolling 24h count lives in Redis behind a
small async protocol (:class:`LobbyFingerprintStore`) so the scoring core stays
pure and unit-testable, and so the integrity layer never imports a concrete
Redis client. A reference Redis implementation is provided for the worker.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .types import MatchSnapshot

if TYPE_CHECKING:  # pragma: no cover - typing only
    from redis.asyncio import Redis


def lobby_fingerprint(match: MatchSnapshot) -> str:
    """Stable SHA-256 hex of the lobby's player set (order/team independent).

    Pure: same player set ⇒ same fingerprint, regardless of teams or placement.
    Includes ``mode``+``team_size`` so a 2v2 and a 3v3 of overlapping players do
    not collide.
    """
    players = sorted({p.player_id for p in match.participants})
    payload = f"{match.mode}:{match.team_size}:" + ",".join(players)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def pair_key(a: str, b: str) -> str:
    """Stable order-independent hash of an unordered player pair.

    Used both as the Redis sorted-set key suffix (one set per pair) and as the
    lookup key into the ``pair_counts`` map ``evaluate_premade`` consumes.
    """
    lo, hi = (a, b) if a <= b else (b, a)
    return hashlib.sha256(f"{lo},{hi}".encode("utf-8")).hexdigest()


def subteam_pair_keys(member_ids: list[str]) -> list[str]:
    """All unordered intra-subteam pair keys (deduped). Empty for a 1-player team."""
    keys: list[str] = []
    members = sorted(set(member_ids))
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            keys.append(pair_key(members[i], members[j]))
    return keys


@runtime_checkable
class LobbyFingerprintStore(Protocol):
    """Rolling 24h occurrence counter for lobby fingerprints.

    ``observe`` records this match's fingerprint and returns the number of times
    the same composition has been seen inside the window (this match included).
    Implementations MUST be idempotent per ``match_id`` so a redelivered job does
    not double-count.
    """

    async def observe(self, fingerprint: str, match_id: str, window_seconds: int) -> int:
        """Record one occurrence; return the count within the window (>= 1)."""
        ...


class RedisLobbyFingerprintStore:
    """Redis-backed :class:`LobbyFingerprintStore` (worker dependency, not pure).

    Uses a per-fingerprint sorted set scored by event time. ``match_id`` is the
    member, giving free idempotency (re-adding the same member is a no-op for the
    count). A single pipeline trims the window, adds the member, counts, and
    refreshes the TTL.
    """

    __slots__ = ("_redis", "_prefix")

    def __init__(self, redis: Redis, key_prefix: str = "integrity:lobby:") -> None:
        self._redis = redis
        self._prefix = key_prefix

    async def observe(self, fingerprint: str, match_id: str, window_seconds: int) -> int:
        import time

        key = f"{self._prefix}{fingerprint}"
        now = int(time.time())
        cutoff = now - window_seconds
        pipe = self._redis.pipeline(transaction=True)
        pipe.zremrangebyscore(key, 0, cutoff)  # drop events outside the window
        pipe.zadd(key, {match_id: now})  # idempotent on match_id
        pipe.zcard(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()
        # zcard is the 3rd command (index 2).
        return int(results[2])


@runtime_checkable
class PartyCooccurrenceStore(Protocol):
    """Rolling co-occurrence counter for unordered player pairs (premade signal).

    ``observe`` records this match against every supplied pair key and returns the
    per-pair occurrence count inside the window (this match included). Like the
    lobby store, implementations MUST be idempotent per ``match_id`` so a
    redelivered job does not inflate counts.
    """

    async def observe(
        self, pair_keys: list[str], match_id: str, window_seconds: int
    ) -> dict[str, int]:
        """Record one occurrence per pair; return ``{pair_key: count}`` (each >= 1)."""
        ...


class RedisPartyCooccurrenceStore:
    """Redis-backed :class:`PartyCooccurrenceStore` (worker dependency, not pure).

    One sorted set per pair (``member = match_id``, score = event time), giving
    free per-``match_id`` idempotency. A single pipeline trims, adds, counts, and
    refreshes the TTL for every pair in the match.
    """

    __slots__ = ("_redis", "_prefix")

    def __init__(self, redis: Redis, key_prefix: str = "integrity:party:") -> None:
        self._redis = redis
        self._prefix = key_prefix

    async def observe(
        self, pair_keys: list[str], match_id: str, window_seconds: int
    ) -> dict[str, int]:
        import time

        if not pair_keys:
            return {}
        keys = list(dict.fromkeys(pair_keys))  # dedupe, preserve order
        now = int(time.time())
        cutoff = now - window_seconds
        pipe = self._redis.pipeline(transaction=True)
        for pk in keys:
            redis_key = f"{self._prefix}{pk}"
            pipe.zremrangebyscore(redis_key, 0, cutoff)
            pipe.zadd(redis_key, {match_id: now})
            pipe.zcard(redis_key)
            pipe.expire(redis_key, window_seconds)
        results = await pipe.execute()
        # zcard is the 3rd of each 4-command group (offset 2, stride 4).
        return {pk: int(results[i * 4 + 2]) for i, pk in enumerate(keys)}
