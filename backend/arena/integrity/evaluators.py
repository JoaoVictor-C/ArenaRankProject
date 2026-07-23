"""Pure flag evaluators + RDS / eligibility scoring (proposal §3.2).

Each function reads a read-only :class:`MatchSnapshot` (and params) and returns
zero or more :class:`IntegrityFlag` objects and/or per-participant verdict data.
None of them mutate their inputs or perform I/O. The only non-pure signal —
repeated-lobby — is split: the pure flag builder here, the Redis count upstream
in :mod:`arena.integrity.fingerprint`.
"""

from __future__ import annotations

from .fingerprint import pair_key
from .params import IntegrityParams
from .types import (
    FlagSeverity,
    FlagType,
    IntegrityFlag,
    MatchSnapshot,
    ParticipantSnapshot,
)


def _severity(value: str) -> FlagSeverity:
    return FlagSeverity(value)


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


# ---------------------------------------------------------------------------
# Eligibility / AFK protection (proposal §3.2: eligibleForProgression)
# ---------------------------------------------------------------------------


def is_eligible(part: ParticipantSnapshot, p: IntegrityParams) -> bool:
    """True when the participant earned a rating result this match.

    Ineligible (⇒ rating engine freezes them, no CR movement) when explicitly
    AFK, when they sat out most rounds, or when they dealt no damage in a real
    (non-trivial) match. Pure.
    """
    if part.afk:
        return False
    if part.rounds_total > 0:
        participation = part.rounds_played / part.rounds_total
        if participation < p.afk_min_participation:
            return False
    if part.rounds_played > 0 and part.damage_dealt < p.afk_min_damage:
        return False
    return True


def evaluate_eligibility(
    match: MatchSnapshot, p: IntegrityParams
) -> tuple[dict[str, bool], list[IntegrityFlag]]:
    """Per-player eligibility map + one INFO/WARN flag per ineligible player."""
    eligibility: dict[str, bool] = {}
    flags: list[IntegrityFlag] = []
    for part in match.participants:
        ok = is_eligible(part, p)
        eligibility[part.player_id] = ok
        if not ok:
            participation = part.rounds_played / part.rounds_total if part.rounds_total > 0 else 0.0
            flags.append(
                IntegrityFlag(
                    flag_type=FlagType.AFK_INELIGIBLE,
                    severity=FlagSeverity.WARN if part.afk else FlagSeverity.INFO,
                    player_id=part.player_id,
                    metadata={
                        "afk": part.afk,
                        "participation": round(participation, 4),
                        "rounds_played": part.rounds_played,
                        "rounds_total": part.rounds_total,
                        "damage_dealt": part.damage_dealt,
                    },
                )
            )
    return eligibility, flags


# ---------------------------------------------------------------------------
# RDS — Rating Disparity Score for duo boosting (tiered)
# ---------------------------------------------------------------------------


def _parties(match: MatchSnapshot) -> dict[str, list[ParticipantSnapshot]]:
    """Group participants by ``party_id`` (premades only; solo players excluded)."""
    parties: dict[str, list[ParticipantSnapshot]] = {}
    for part in match.participants:
        if part.party_id is None:
            continue
        parties.setdefault(part.party_id, []).append(part)
    return {pid: members for pid, members in parties.items() if len(members) >= 2}


def evaluate_rds(
    match: MatchSnapshot, p: IntegrityParams
) -> tuple[dict[str, float], list[IntegrityFlag]]:
    """Compute the duo-boosting penalty factor per participant + tiered flags.

    For each premade party, the CR gap between its strongest and weakest member
    is the Rating Disparity Score. The gap selects the highest qualifying tier;
    the *booster* (highest-CR member) receives that tier's ``penalty_factor`` as
    their ``boosting_penalty_factor`` (consumed by ``rating.boosting_penalty``).
    Carried members and solo players get 0.0. Pure.
    """
    factors: dict[str, float] = {part.player_id: 0.0 for part in match.participants}
    flags: list[IntegrityFlag] = []

    for party_id, members in _parties(match).items():
        strongest = max(members, key=lambda m: m.cr)
        weakest = min(members, key=lambda m: m.cr)
        gap = strongest.cr - weakest.cr
        if gap < p.rds_min_gap:
            continue

        tier = None
        for candidate in p.rds_tiers:
            if gap >= candidate.min_cr_gap:
                tier = candidate  # tiers ascending ⇒ last match is the highest
        if tier is None:
            continue

        factors[strongest.player_id] = _clamp(tier.penalty_factor, 0.0, 1.0)
        flags.append(
            IntegrityFlag(
                flag_type=FlagType.BOOSTING_RDS,
                severity=_severity(tier.severity),
                player_id=strongest.player_id,
                metadata={
                    "party_id": party_id,
                    "rds_cr_gap": round(gap, 2),
                    "tier": tier.label,
                    "penalty_factor": tier.penalty_factor,
                    "booster_id": strongest.player_id,
                    "carried_id": weakest.player_id,
                    "party_size": len(members),
                },
            )
        )
    return factors, flags


# ---------------------------------------------------------------------------
# Premade dampener — solo wins worth more than coordinated premade wins
# ---------------------------------------------------------------------------


def _confidence(count: int, p: IntegrityParams) -> float:
    """Co-occurrence count -> [0, 1]; 0 at count<=1, saturates at the threshold."""
    span = p.premade_repeat_threshold - 1
    return _clamp((count - 1) / span, 0.0, 1.0)


def evaluate_premade(
    match: MatchSnapshot,
    pair_counts: dict[str, int],
    p: IntegrityParams,
) -> dict[str, float]:
    """Per-player premade penalty factor (0..1) -> rating.party_dampener (gains-only).

    For each subteam: ``homogeneity`` falls from 1 (equal CR) to 0 as the subteam's
    internal CR spread reaches ``premade_homogeneity_gap`` (so carrying lower-elo
    mates backs off — RDS handles that case). Each player's ``confidence`` is the
    max over the co-occurrence counts of the pairs they share in the subteam.
    ``factor = premade_strength * confidence * homogeneity``. Pure.
    """
    factors: dict[str, float] = {part.player_id: 0.0 for part in match.participants}

    subteams: dict[int, list[ParticipantSnapshot]] = {}
    for part in match.participants:
        subteams.setdefault(part.team_id, []).append(part)

    for members in subteams.values():
        if len(members) < 2:
            continue  # a lone player cannot be a premade
        crs = [m.cr for m in members]
        spread = max(crs) - min(crs)
        homogeneity = _clamp(1.0 - spread / p.premade_homogeneity_gap, 0.0, 1.0)
        if homogeneity <= 0.0:
            continue
        for member in members:
            confidence = 0.0
            for other in members:
                if other.player_id == member.player_id:
                    continue
                count = pair_counts.get(pair_key(member.player_id, other.player_id), 0)
                confidence = max(confidence, _confidence(count, p))
            factors[member.player_id] = _clamp(
                p.premade_strength * confidence * homogeneity, 0.0, 1.0
            )
    return factors


# ---------------------------------------------------------------------------
# Unusual duration — statistical outlier on match length
# ---------------------------------------------------------------------------


def evaluate_duration(match: MatchSnapshot, p: IntegrityParams) -> list[IntegrityFlag]:
    """Flag matches whose length is a statistical outlier (z-score on duration)."""
    flags: list[IntegrityFlag] = []
    dur = match.duration_seconds

    z = (dur - p.duration_mean_seconds) / p.duration_std_seconds
    abs_z = abs(z)

    severity: FlagSeverity | None = None
    if dur < p.duration_min_seconds or abs_z >= p.duration_z_critical:
        severity = FlagSeverity.CRITICAL
    elif abs_z >= p.duration_z_warn:
        severity = FlagSeverity.WARN

    if severity is not None:
        flags.append(
            IntegrityFlag(
                flag_type=FlagType.UNUSUAL_DURATION,
                severity=severity,
                player_id=None,  # match-scoped
                metadata={
                    "duration_seconds": dur,
                    "z_score": round(z, 3),
                    "mean_seconds": p.duration_mean_seconds,
                    "std_seconds": p.duration_std_seconds,
                    "too_short": dur < p.duration_min_seconds,
                },
            )
        )
    return flags


# ---------------------------------------------------------------------------
# Rating dispersion — single-account leaderboard distortion (informational)
# ---------------------------------------------------------------------------


def evaluate_dispersion(match: MatchSnapshot, p: IntegrityParams) -> list[IntegrityFlag]:
    """Flag lobbies with an extreme in-lobby CR spread (dominant-account signal)."""
    if not match.participants:
        return []
    crs = [part.cr for part in match.participants]
    spread = max(crs) - min(crs)

    severity: FlagSeverity | None = None
    if spread >= p.dispersion_cr_critical:
        severity = FlagSeverity.CRITICAL
    elif spread >= p.dispersion_cr_warn:
        severity = FlagSeverity.WARN

    if severity is None:
        return []
    return [
        IntegrityFlag(
            flag_type=FlagType.RATING_DISPERSION,
            severity=severity,
            player_id=None,
            metadata={
                "cr_spread": round(spread, 2),
                "cr_max": round(max(crs), 2),
                "cr_min": round(min(crs), 2),
                "warn_threshold": p.dispersion_cr_warn,
                "critical_threshold": p.dispersion_cr_critical,
            },
        )
    ]


# ---------------------------------------------------------------------------
# Repeated lobby — pure flag builder (count comes from Redis upstream)
# ---------------------------------------------------------------------------


def build_repeated_lobby_flag(
    match: MatchSnapshot,
    fingerprint: str,
    occurrence_count: int,
    p: IntegrityParams,
) -> IntegrityFlag | None:
    """Build a repeated-lobby flag from a precomputed 24h occurrence count.

    Returns ``None`` below the threshold. WARN at ``repeated_lobby_threshold``,
    CRITICAL at ``repeated_lobby_critical``. Match-scoped. Pure.
    """
    if occurrence_count < p.repeated_lobby_threshold:
        return None
    severity = (
        FlagSeverity.CRITICAL
        if occurrence_count >= p.repeated_lobby_critical
        else FlagSeverity.WARN
    )
    return IntegrityFlag(
        flag_type=FlagType.REPEATED_LOBBY,
        severity=severity,
        player_id=None,
        metadata={
            "fingerprint": fingerprint,
            "occurrences_24h": occurrence_count,
            "threshold": p.repeated_lobby_threshold,
            "window_seconds": p.repeated_lobby_window_seconds,
            "player_count": len({part.player_id for part in match.participants}),
        },
    )
