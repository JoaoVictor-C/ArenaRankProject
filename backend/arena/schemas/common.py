"""Shared schema primitives + camelCase config for all API DTOs.

Mirrors ``F:/arenarank/spec/api_contract_v1.md`` and ``frontend/src/lib/types.ts``.
All response/request DTOs serialize with camelCase keys (contract requirement) via
:func:`arena_camel` + ``populate_by_name`` so Python code can still build models with
snake_case kwargs while the JSON wire format stays camelCase.

ToS note: never expose mu/sigma or augment/item winrate here — only CR/Pontos/PDL.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

# Fields whose camelCase form differs from what ``to_camel`` produces.
# ``to_camel`` uppercases the char following a digit, so "delta7d" -> "delta7D"
# and "h2h" -> "h2H"; the contract/frontend require the literal lowercase forms.
_ALIAS_OVERRIDES: dict[str, str] = {
    "delta7d": "delta7d",
    "h2h": "h2h",
    # "global" is a Python keyword → field is "global_"; wire key must be "global".
    "global_": "global",
}


def arena_camel(field_name: str) -> str:
    """camelCase alias generator honoring contract-specific overrides."""
    if field_name in _ALIAS_OVERRIDES:
        return _ALIAS_OVERRIDES[field_name]
    return to_camel(field_name)


class ArenaModel(BaseModel):
    """Base for every API DTO: camelCase aliases, populate-by-name, strict-ish."""

    model_config = ConfigDict(
        alias_generator=arena_camel,
        populate_by_name=True,
        from_attributes=True,
    )


# ---- shared value objects (contract "common" section) ----

TierKey = Literal["top1", "top10", "top50", "top100", "top500", "none"]
"""Display tier derived from global rank within format."""

Format = Literal["3v3", "2v2"]
"""Arena queue format. 3v3 = queue 1750, 2v2 = queue 1700."""

Severity = Literal["info", "warn", "critical"]


class AvatarColors(ArenaModel):
    """Placeholder gradient colors for an avatar/champion (no real art — ToS)."""

    c1: str
    c2: str


PlayerTagKind = Literal["hot", "otp", "champrank"]


class PlayerTag(ArenaModel):
    """Relevance-ordered badge shown on a player.

    Two families: a champion identity tag (``otp`` = "OTP {Champ}", ``champrank``
    = "TOP n {Champ}") and momentum (``hot`` = "Em alta"). ``icon`` is a Material
    Symbol name for momentum tags and empty for champion tags. ``champ_icon_url``,
    when set, is the ddragon icon of the tag's champion — the client extracts its
    dominant color to tint the chip (e.g. Vladimir → red gradient).
    """

    kind: PlayerTagKind
    label: str
    icon: str
    champ_icon_url: str | None = None


class Modifier(ArenaModel):
    """CR modifier breakdown entry (colocação/sequência/proteção/penalidade...).

    ``value`` may be positive or negative. This is the UI-safe mapping of the
    engine's AppliedModifiers — never carries mu/sigma.

    ``pdl_impact`` (Raio-X do resultado, v1.4) is the modifier's REAL additive
    PDL contribution — sourced from ``arena/rating/explain.py``'s reconciling
    ledger, not reverse-engineered client-side. ``None`` only in the (now
    unreachable outside tests) case a caller builds a ``Modifier`` without going
    through ``map_modifiers``. When every modifier on a match carries a finite
    ``pdl_impact``, the frontend's old multiplicative-inversion fallback
    (``profileRatingSignalModel.ts::resolveProfileRatingModifiers``) never
    engages — see that module's docstring.
    """

    kind: str
    label: str
    value: float
    icon: str
    pdl_impact: float | None = None
