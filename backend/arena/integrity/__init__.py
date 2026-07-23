"""Integrity / anti-abuse layer (proposal §3.2 + §13.2).

Pure-ish scoring that PRODUCES what the rating engine consumes:
``boosting_penalty_factor`` (0..1, via tiered RDS for duo boosting) and
``eligible_for_progression`` (AFK / ineligible protection), alongside structured
:class:`IntegrityFlag` audit objects. It never mutates match data and never
enforces — persistence (``integrity_events``) and enforcement are downstream.

Public API:
    evaluate(match, params) -> EvaluationResult            # pure (no I/O)
    evaluate_async(match, store, params) -> EvaluationResult  # + repeated-lobby
    lobby_fingerprint(match) -> str
    DEFAULT_INTEGRITY_PARAMS, IntegrityParams, validate_integrity_params
    + the dataclass contracts and individual evaluators

Pipeline position (proposal §13.2): runs after participant registration and
*before* RatingEngine.compute — its verdicts populate ``ParticipantInput``.
"""

from __future__ import annotations

from .evaluators import (
    build_repeated_lobby_flag,
    evaluate_dispersion,
    evaluate_duration,
    evaluate_eligibility,
    evaluate_rds,
    is_eligible,
)
from .fingerprint import (
    LobbyFingerprintStore,
    RedisLobbyFingerprintStore,
    lobby_fingerprint,
)
from .params import (
    DEFAULT_INTEGRITY_PARAMS,
    IntegrityParams,
    RdsTier,
    validate_integrity_params,
)
from .service import evaluate, evaluate_async
from .types import (
    EvaluationResult,
    FlagSeverity,
    FlagType,
    IntegrityFlag,
    MatchSnapshot,
    ParticipantSnapshot,
    ParticipantVerdict,
)

__all__ = [
    # entry points
    "evaluate",
    "evaluate_async",
    "lobby_fingerprint",
    # params
    "DEFAULT_INTEGRITY_PARAMS",
    "IntegrityParams",
    "RdsTier",
    "validate_integrity_params",
    # evaluators
    "evaluate_rds",
    "evaluate_eligibility",
    "evaluate_duration",
    "evaluate_dispersion",
    "build_repeated_lobby_flag",
    "is_eligible",
    # fingerprint store
    "LobbyFingerprintStore",
    "RedisLobbyFingerprintStore",
    # contracts
    "EvaluationResult",
    "FlagSeverity",
    "FlagType",
    "IntegrityFlag",
    "MatchSnapshot",
    "ParticipantSnapshot",
    "ParticipantVerdict",
]
