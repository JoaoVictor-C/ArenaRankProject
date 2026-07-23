"""Integrity orchestration (proposal §6.2 IntegrityService, §13.2 pipeline step).

``evaluate(match)`` is the pure entry point: it runs every flag evaluator that
needs no I/O (RDS, eligibility, duration, dispersion) and returns the flags plus
the per-participant verdicts the rating engine consumes. ``evaluate_async`` adds
the one I/O-bound signal (repeated-lobby, via a Redis fingerprint store) on top.

The layer never mutates the match snapshot and never enforces anything — it only
*produces* ``boosting_penalty_factor`` and ``eligible_for_progression``, leaving
persistence (``integrity_events``) and enforcement to the caller.
"""

from __future__ import annotations

from . import evaluators as E
from .fingerprint import (
    LobbyFingerprintStore,
    PartyCooccurrenceStore,
    lobby_fingerprint,
    subteam_pair_keys,
)
from .params import DEFAULT_INTEGRITY_PARAMS, IntegrityParams, validate_integrity_params
from .types import (
    EvaluationResult,
    IntegrityFlag,
    MatchSnapshot,
    ParticipantVerdict,
)


def _validate_match(match: MatchSnapshot) -> None:
    if not match.participants:
        raise ValueError("a match needs at least 1 participant")
    seen: set[str] = set()
    for part in match.participants:
        if part.player_id in seen:
            raise ValueError(f"duplicate participant: {part.player_id!r}")
        seen.add(part.player_id)


def _assemble(
    match: MatchSnapshot,
    boosting_factors: dict[str, float],
    eligibility: dict[str, bool],
    flags: list[IntegrityFlag],
    party_factors: dict[str, float] | None = None,
) -> EvaluationResult:
    party_factors = party_factors or {}
    verdicts: dict[str, ParticipantVerdict] = {
        part.player_id: ParticipantVerdict(
            player_id=part.player_id,
            boosting_penalty_factor=boosting_factors.get(part.player_id, 0.0),
            eligible_for_progression=eligibility.get(part.player_id, True),
            party_penalty_factor=party_factors.get(part.player_id, 0.0),
        )
        for part in match.participants
    }
    return EvaluationResult(match_id=match.match_id, flags=flags, verdicts=verdicts)


def evaluate(
    match: MatchSnapshot,
    params: IntegrityParams = DEFAULT_INTEGRITY_PARAMS,
) -> EvaluationResult:
    """Pure evaluation: RDS + eligibility + duration + dispersion.

    Excludes repeated-lobby (needs the Redis fingerprint window). Use
    :func:`evaluate_async` to include it. Same input ⇒ same output.
    """
    validate_integrity_params(params)
    _validate_match(match)

    boosting_factors, rds_flags = E.evaluate_rds(match, params)
    eligibility, afk_flags = E.evaluate_eligibility(match, params)
    duration_flags = E.evaluate_duration(match, params)
    dispersion_flags = E.evaluate_dispersion(match, params)

    flags = [*rds_flags, *afk_flags, *duration_flags, *dispersion_flags]
    return _assemble(match, boosting_factors, eligibility, flags)


async def evaluate_async(
    match: MatchSnapshot,
    lobby_store: LobbyFingerprintStore,
    party_store: PartyCooccurrenceStore,
    params: IntegrityParams = DEFAULT_INTEGRITY_PARAMS,
) -> EvaluationResult:
    """Full evaluation including the Redis-backed repeated-lobby + premade signals.

    Records this match's lobby fingerprint (24h window, repeated-lobby flag) and
    each subteam's co-occurrence pairs (premade dampener), folding the resulting
    per-player ``party_penalty_factor`` into the verdicts. The two stores are the
    only I/O dependencies; both are idempotent per ``match_id`` so redelivery is
    safe.
    """
    # Pure pass first (RDS / eligibility / duration / dispersion).
    pure = evaluate(match, params)

    # Premade co-occurrence: observe every intra-subteam pair, then score.
    subteams: dict[int, list[str]] = {}
    for part in match.participants:
        subteams.setdefault(part.team_id, []).append(part.player_id)
    all_pairs: list[str] = [pk for members in subteams.values() for pk in subteam_pair_keys(members)]
    pair_counts = (
        await party_store.observe(all_pairs, match.match_id, params.premade_window_seconds)
        if all_pairs
        else {}
    )
    party_factors = E.evaluate_premade(match, pair_counts, params)

    # Re-assemble verdicts with the party factor folded in (flags carry over).
    result = _assemble(
        match,
        {pid: v.boosting_penalty_factor for pid, v in pure.verdicts.items()},
        {pid: v.eligible_for_progression for pid, v in pure.verdicts.items()},
        pure.flags,
        party_factors,
    )

    fingerprint = lobby_fingerprint(match)
    count = await lobby_store.observe(
        fingerprint, match.match_id, params.repeated_lobby_window_seconds
    )
    lobby_flag = E.build_repeated_lobby_flag(match, fingerprint, count, params)
    if lobby_flag is not None:
        result.flags.append(lobby_flag)
    return result
