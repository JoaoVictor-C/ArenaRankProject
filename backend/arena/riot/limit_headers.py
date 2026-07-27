"""Riot's own rate-limit headers — the authoritative view of key consumption.

Our Redis token bucket (:mod:`arena.riot.rate_limit`) is a *model* of Riot's
limits: it is only as correct as the capacities configured in
``arena/core/config.py``. Riot, meanwhile, reports the truth on every response::

    X-App-Rate-Limit:        20:1,100:120     # limit:window_seconds pairs
    X-App-Rate-Limit-Count:  1:1,1:120        # current count in each window
    X-Method-Rate-Limit:     2000:10
    X-Method-Rate-Limit-Count: 5:10
    X-Rate-Limit-Type:       application|method|service   # 429 responses only

Capturing those turns the limit audit from a one-off portal check into a
continuous one: if Riot announces ``500:10`` while we configured ``2000:10``,
the key is being over-driven and :func:`detect_drift` says so before the 429
storm does.

Two halves, deliberately split:

- the **parser** (:func:`parse_rate_limit_headers`, :func:`detect_drift`) is
  pure and total — no I/O, no exceptions on malformed input, per the package's
  "pure modules stay pure" convention;
- the **store** (:func:`record_observed`, :func:`read_observed`) is best-effort
  Redis, mirroring :mod:`arena.core.metrics`: it must never break the call it
  observes.

Scope naming reuses the limiter's bucket names (``match-v5:match``,
``account-v1``, …) plus ``app`` for the app-wide window, so the admin console
can join observed data onto the configured buckets by key.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from arena.core.logging import get_logger

_log = get_logger("arena.riot.limit_headers")

#: Key prefix for the observed-limit snapshots.
PREFIX: Final[str] = "riot:observed"

#: How long a snapshot survives without a refresh. Long enough that an idle
#: ingestion pipeline still renders in the console, short enough that a rotated
#: key's stale limits age out on their own.
TTL_SECONDS: Final[int] = 6 * 60 * 60

#: Scope name for the app-wide window (the per-method scopes reuse bucket names).
APP_SCOPE: Final[str] = "app"


@dataclass(frozen=True, slots=True)
class LimitWindow:
    """One ``limit:seconds`` window Riot advertises, with its current count."""

    limit: int
    seconds: int
    count: int = 0

    @property
    def utilization(self) -> float:
        """``count / limit``, clamped to 0..1. Zero-limit windows read as 0."""
        if self.limit <= 0:
            return 0.0
        return max(0.0, min(1.0, self.count / self.limit))

    def as_dict(self) -> dict[str, Any]:
        return {"limit": self.limit, "seconds": self.seconds, "count": self.count}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> LimitWindow | None:
        """Rebuild from :meth:`as_dict`; ``None`` if the shape is unusable."""
        try:
            return cls(
                limit=int(raw["limit"]), seconds=int(raw["seconds"]), count=int(raw.get("count", 0))
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(frozen=True, slots=True)
class ObservedLimits:
    """What Riot reported about one response: app + method windows."""

    app: tuple[LimitWindow, ...] = ()
    method: tuple[LimitWindow, ...] = ()
    #: Which limit a 429 attributed the rejection to; ``None`` on non-429.
    limit_type: str | None = None
    #: Epoch seconds the snapshot was taken.
    observed_at: float = 0.0

    @property
    def is_empty(self) -> bool:
        """True when Riot sent no usable rate-limit headers at all."""
        return not self.app and not self.method

    def as_dict(self) -> dict[str, Any]:
        return {
            "app": [w.as_dict() for w in self.app],
            "method": [w.as_dict() for w in self.method],
            "limitType": self.limit_type,
            "observedAt": self.observed_at,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ObservedLimits:
        """Rebuild from :meth:`as_dict`; unusable entries are dropped."""
        return cls(
            app=_windows_from_list(raw.get("app")),
            method=_windows_from_list(raw.get("method")),
            limit_type=raw.get("limitType") if isinstance(raw.get("limitType"), str) else None,
            observed_at=_as_float(raw.get("observedAt")),
        )


def _windows_from_list(raw: object) -> tuple[LimitWindow, ...]:
    if not isinstance(raw, list):
        return ()
    out = []
    for entry in raw:
        if isinstance(entry, Mapping):
            window = LimitWindow.from_dict(entry)
            if window is not None:
                out.append(window)
    return tuple(out)


def _as_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


# --- parsing ---------------------------------------------------------------


def parse_limit_pairs(raw: str | None) -> tuple[tuple[int, int], ...]:
    """Parse ``"20:1,100:120"`` into ``((20, 1), (100, 120))``.

    Total by construction: malformed pairs are skipped rather than raising, so
    an unexpected header shape degrades to "no data" instead of breaking a
    Riot call. Pairs come back sorted by window length, which is the order the
    console renders them (tightest limit first).
    """
    if not raw:
        return ()
    pairs: list[tuple[int, int]] = []
    for chunk in raw.split(","):
        part = chunk.strip()
        if not part or ":" not in part:
            continue
        head, _, tail = part.partition(":")
        try:
            limit, seconds = int(head.strip()), int(tail.strip())
        except ValueError:
            continue
        if seconds <= 0:
            continue
        pairs.append((limit, seconds))
    return tuple(sorted(pairs, key=lambda p: p[1]))


def _merge(limits: str | None, counts: str | None) -> tuple[LimitWindow, ...]:
    """Zip a ``*-Rate-Limit`` header with its ``*-Rate-Limit-Count`` sibling.

    The two headers are matched on window length, not position: Riot lists them
    in the same order today, but joining on ``seconds`` is what actually makes
    the pairing meaningful. A window with no matching count reads as count 0.
    """
    by_seconds = {seconds: count for count, seconds in parse_limit_pairs(counts)}
    return tuple(
        LimitWindow(limit=limit, seconds=seconds, count=by_seconds.get(seconds, 0))
        for limit, seconds in parse_limit_pairs(limits)
    )


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive header lookup (httpx is case-insensitive; dicts aren't)."""
    value = headers.get(name)
    if value is not None:
        return value
    return headers.get(name.lower())


def parse_rate_limit_headers(headers: Mapping[str, str]) -> ObservedLimits:
    """Extract Riot's advertised limits + current counts from one response.

    Never raises: a response with no rate-limit headers yields an
    :attr:`~ObservedLimits.is_empty` snapshot.
    """
    limit_type = _header(headers, "X-Rate-Limit-Type")
    return ObservedLimits(
        app=_merge(_header(headers, "X-App-Rate-Limit"), _header(headers, "X-App-Rate-Limit-Count")),
        method=_merge(
            _header(headers, "X-Method-Rate-Limit"), _header(headers, "X-Method-Rate-Limit-Count")
        ),
        limit_type=limit_type.strip().lower() if isinstance(limit_type, str) else None,
        observed_at=time.time(),
    )


def detect_drift(
    windows: Sequence[LimitWindow], *, capacity: int, refill_seconds: float
) -> str | None:
    """Compare a configured bucket against what Riot actually advertises.

    Returns a PT-BR operator-facing message when the configuration would let us
    exceed Riot's real limit, else ``None``. Only *over*-configuration is
    reported: a bucket configured below Riot's ceiling is merely conservative,
    which is safe (and is what the headroom factor does on purpose).

    Matching is on window length; a configured window Riot never mentions is
    reported separately since it means the bucket is modelling a limit that
    does not exist (or exists under a different period).
    """
    if not windows:
        return None
    target = int(round(refill_seconds))
    match = next((w for w in windows if w.seconds == target), None)
    if match is None:
        advertised = ", ".join(f"{w.limit}/{w.seconds}s" for w in windows)
        return (
            f"Janela configurada de {target}s não existe na Riot "
            f"(a Riot anuncia: {advertised})."
        )
    if capacity > match.limit:
        return (
            f"Configurado {capacity}/{target}s, mas a Riot anuncia "
            f"{match.limit}/{match.seconds}s — a chave está sendo sobre-explorada."
        )
    return None


# --- best-effort Redis store ----------------------------------------------


def key(api_key_suffix: str, scope: str) -> str:
    """Redis key holding the latest snapshot for *scope* under this API key."""
    return f"{PREFIX}:{api_key_suffix}:{scope}"


async def record_observed(
    redis: Any, api_key_suffix: str, scope: str, observed: ObservedLimits
) -> None:
    """Persist the latest snapshot for *scope* (and the app window). Never raises.

    The app-wide window is written under its own scope rather than duplicated
    into every method scope, so the console reads one authoritative app entry
    no matter which endpoint last refreshed it.
    """
    if redis is None or observed.is_empty:
        return
    try:
        pipe = redis.pipeline(transaction=False)
        if observed.method:
            method_only = ObservedLimits(
                method=observed.method,
                limit_type=observed.limit_type,
                observed_at=observed.observed_at,
            )
            pipe.set(key(api_key_suffix, scope), json.dumps(method_only.as_dict()), ex=TTL_SECONDS)
        if observed.app:
            app_only = ObservedLimits(
                app=observed.app,
                limit_type=observed.limit_type,
                observed_at=observed.observed_at,
            )
            pipe.set(key(api_key_suffix, APP_SCOPE), json.dumps(app_only.as_dict()), ex=TTL_SECONDS)
        await pipe.execute()
    except Exception:  # noqa: BLE001 - observation must never break the caller
        _log.debug("riot.observed.record_failed", scope=scope, exc_info=True)


async def read_observed(
    redis: Any, api_key_suffix: str, scopes: Iterable[str]
) -> dict[str, ObservedLimits]:
    """Read snapshots for *scopes* in one round-trip. Missing scopes are absent.

    Returns an empty mapping (not an error) when Redis is unavailable, so the
    admin endpoint degrades to "configured values only" instead of 500-ing.
    """
    names = list(scopes)
    if redis is None or not names:
        return {}
    try:
        raw = await redis.mget([key(api_key_suffix, scope) for scope in names])
    except Exception:  # noqa: BLE001 - degrade to "no observed data"
        _log.debug("riot.observed.read_failed", exc_info=True)
        return {}

    out: dict[str, ObservedLimits] = {}
    for scope, blob in zip(names, raw, strict=False):
        if blob is None:
            continue
        if isinstance(blob, bytes | bytearray):
            blob = blob.decode("utf-8", "ignore")
        try:
            payload = json.loads(blob)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, Mapping):
            out[scope] = ObservedLimits.from_dict(payload)
    return out


__all__ = [
    "APP_SCOPE",
    "PREFIX",
    "TTL_SECONDS",
    "LimitWindow",
    "ObservedLimits",
    "detect_drift",
    "key",
    "parse_limit_pairs",
    "parse_rate_limit_headers",
    "read_observed",
    "record_observed",
]
