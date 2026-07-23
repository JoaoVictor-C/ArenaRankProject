"""Pure builders for tournament provisioning + UI labels.

No DB, no Pydantic — plain helpers the service composes when provisioning a
tournament (``POST /admin/tournaments``) and when projecting persisted rows into
the contract DTOs. All user-facing strings are PT-BR.

ToS note: avatars are placeholder gradients (``{c1, c2}``) derived
deterministically from a seed — never real champion/player art.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime
from typing import TypedDict


class PrizeDict(TypedDict):
    """Prize row shape produced by :func:`build_prizes`."""

    place: int
    rp: int
    perPlayer: int
    medal: str


class AvatarDict(TypedDict):
    """Placeholder gradient shape."""

    c1: str
    c2: str


# Deterministic placeholder gradient palette (no real art — Riot ToS).
_PALETTE: list[tuple[str, str]] = [
    ("#6C63FF", "#FF6584"),
    ("#43BCCD", "#F7971E"),
    ("#2ECC71", "#E74C3C"),
    ("#3498DB", "#9B59B6"),
    ("#F39C12", "#1ABC9C"),
    ("#E91E63", "#00BCD4"),
    ("#FF5722", "#607D8B"),
    ("#795548", "#FF9800"),
]

_MEDALS: dict[int, str] = {1: "gold", 2: "silver", 3: "bronze"}

# Default prize split (percent by placement) when none is supplied.
_DEFAULT_PRIZE_SPLIT: list[dict[str, float]] = [
    {"place": 1, "pct": 60.0},
    {"place": 2, "pct": 30.0},
    {"place": 3, "pct": 10.0},
]

_DEFAULT_TIEBREAK = ["Total de vitórias", "Posição média", "Confronto direto"]


def avatar_from_seed(seed: str, offset: int = 0) -> AvatarDict:
    """Deterministic placeholder gradient ``{c1, c2}`` for *seed*."""
    digest = hashlib.sha256(f"{seed}{offset}".encode()).hexdigest()
    c1, c2 = _PALETTE[int(digest, 16) % len(_PALETTE)]
    return {"c1": c1, "c2": c2}


def team_size(fmt: str) -> int:
    """Players per team for a format. 3v3 → 3, anything else → 2."""
    return 3 if fmt == "3v3" else 2


def gen_access_key() -> str:
    """Generate an ``ARENA-XXXXXX`` access key (base32, 6 uppercase chars)."""
    raw = secrets.token_bytes(5)  # 5 bytes → 8 base32 chars; take 6
    b32 = base64.b32encode(raw).decode("ascii")[:6]
    return f"ARENA-{b32}"


def normalize_key(key: str) -> str:
    """Normalize an access key for comparison (strip + uppercase)."""
    return key.strip().upper()


def make_player_slot(riot_id: str) -> dict[str, object]:
    """Build a *filled* player slot ``{name, handle, riotId, avatar}`` from a Riot ID."""
    parts = riot_id.split("#", 1)
    name = parts[0]
    handle = f"#{parts[1]}" if len(parts) > 1 else "#???"
    return {
        "name": name,
        "handle": handle,
        "riotId": riot_id,
        "avatar": avatar_from_seed(riot_id),
    }


def empty_slots(count: int) -> list[dict[str, object]]:
    """A list of *count* empty slots ``[{empty: True}, ...]``."""
    return [{"empty": True} for _ in range(count)]


def count_real_players(players: list[dict[str, object]]) -> int:
    """Number of filled (non-empty) slots in a player list."""
    return sum(1 for p in players if not p.get("empty"))


def default_scoring(num_teams: int) -> list[dict[str, int]]:
    """Default scoring table: 1st = num_teams points … last = 1 point."""
    return [{"place": p, "points": num_teams - p + 1} for p in range(1, num_teams + 1)]


def scoring_to_dict(scoring: list[dict[str, int]]) -> dict[int, int]:
    """Convert a ``[{place, points}]`` list into a ``{place: points}`` map."""
    return {int(s["place"]): int(s["points"]) for s in scoring}


def fmt_money(amount: int, currency: str = "RP") -> str:
    """Format a prize amount (pt-BR thousands separator). BRL → 'R$ …', else '… RP'."""
    pretty = f"{amount:,}".replace(",", ".")
    return f"R$ {pretty}" if currency == "BRL" else f"{pretty} RP"


def when_label(starts_at: datetime | None) -> str:
    """Relative pt-BR label for a start time (e.g. 'em 3 dias', 'em andamento')."""
    if starts_at is None:
        return "a definir"
    now = datetime.now(tz=UTC)
    delta = (starts_at - now).total_seconds()
    if delta <= 0:
        return "em andamento"
    days = int(delta // 86400)
    if days >= 1:
        return f"em {days} dia{'s' if days > 1 else ''}"
    hours = int(delta // 3600)
    if hours >= 1:
        return f"em {hours} h"
    return f"em {max(1, int(delta // 60))} min"


def build_prizes(
    prize_rp: int, size: int, prize_split: list[dict[str, float]] | None
) -> list[PrizeDict]:
    """Split the prize pool by placement → ``[{place, rp, perPlayer, medal}]``."""
    if prize_rp <= 0:
        return []
    splits = prize_split or _DEFAULT_PRIZE_SPLIT
    out: list[PrizeDict] = []
    for s in splits:
        place = int(s["place"])
        rp = round(prize_rp * float(s["pct"]) / 100.0)
        out.append(
            {
                "place": place,
                "rp": rp,
                "perPlayer": rp // max(1, size),
                "medal": _MEDALS.get(place, "none"),
            }
        )
    return out


def format_lines(num_teams: int, num_matches: int, fmt: str) -> list[str]:
    """Human-readable pt-BR format bullets for the rules card."""
    size = team_size(fmt)
    return [
        f"{num_teams} equipes × {size} jogadores",
        f"Pontos corridos · {num_matches} partidas ({fmt})",
        "Classificação por pontos acumulados",
    ]


def default_tiebreak() -> list[str]:
    """Default pt-BR tiebreak description lines."""
    return list(_DEFAULT_TIEBREAK)


__all__ = [
    "avatar_from_seed",
    "team_size",
    "gen_access_key",
    "normalize_key",
    "make_player_slot",
    "empty_slots",
    "count_real_players",
    "default_scoring",
    "scoring_to_dict",
    "fmt_money",
    "when_label",
    "build_prizes",
    "format_lines",
    "default_tiebreak",
]
