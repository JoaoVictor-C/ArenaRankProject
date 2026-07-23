"""Parity runner — Python runtime engine (arena.rating).

Reads the shared fixtures, runs each match through ``arena.rating.rate`` with the
neutralized shared params (PDL caps left OFF via ``caps=None``), and writes the
per-player results as JSON to stdout for ``compare.mjs`` to diff against the TS
oracle. Run:  ``python parity/run_py.py parity/fixtures.json``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from arena.rating import (
    MatchInput,
    ParticipantInput,
    PlayerState,
    RatingParams,
    TeamInput,
    rate,
)

# camelCase fixture key -> RatingParams snake_case field.
_PARAM_MAP = {
    "mu0": "mu0",
    "sigma0": "sigma0",
    "beta": "beta",
    "tau": "tau",
    "kappa": "kappa",
    "scaleFactor": "scale_factor",
    "baseOffset": "base_offset",
    "placementAmp": "placement_amp",
    "placementMatchCount": "placement_match_count",
    "streakLossFloor": "streak_loss_floor",
    "streakWinCeil": "streak_win_ceil",
    "streakThreshold": "streak_threshold",
    "softCapThreshold": "soft_cap_threshold",
    "softCapScale": "soft_cap_scale",
    "maxDeltaMu": "max_delta_mu",
    "dispersionSigmaRef": "dispersion_sigma_ref",
    "resetAnchor": "reset_anchor",
    "resetFactor": "reset_factor",
    "sigmaResetMult": "sigma_reset_mult",
    "sigmaResetCap": "sigma_reset_cap",
}


def _to_cr(mu: float, sigma: float, p: dict) -> float:
    return (mu - 3.0 * sigma) * p["scaleFactor"] + p["baseOffset"]


def _build_params(p: dict) -> RatingParams:
    kwargs = {field: p[key] for key, field in _PARAM_MAP.items()}
    kwargs["placement_weights"] = {
        int(k): list(v) for k, v in p["placementWeights"].items()
    }
    # caps defaults to None -> the Python-only PDL cap layer stays OFF for parity.
    return RatingParams(**kwargs)


def main() -> None:
    fixtures = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    p = fixtures["params"]
    params = _build_params(p)

    results = []
    for match in fixtures["matches"]:
        teams = []
        for team_index, team in enumerate(match["teams"]):
            participants = []
            for pl in team["players"]:
                cr = _to_cr(pl["mu"], pl["sigma"], p)
                state = PlayerState(
                    player_id=pl["id"],
                    mu=pl["mu"],
                    sigma=pl["sigma"],
                    cr=cr,
                    current_streak=pl.get("streak", 0),
                    matches_played=pl.get("matchesPlayed", 50),  # non-provisional
                    placement_matches_remaining=0,  # -> placement amp off
                    peak_cr=cr,
                )
                participants.append(
                    ParticipantInput(
                        player_id=pl["id"],
                        state=state,
                        champion_id=1,
                        eligible_for_progression=True,
                        is_premade=False,
                        party_id=None,
                        boosting_penalty_factor=0.0,
                    )
                )
            teams.append(
                TeamInput(
                    team_id=team_index,
                    placement=team["placement"],
                    participants=participants,
                )
            )

        result = rate(
            MatchInput(
                match_id=match["matchId"],
                mode=match["mode"],
                teams=teams,
                params=params,
            )
        )
        for pr in result.players:
            results.append(
                {
                    "matchId": match["matchId"],
                    "playerId": pr.player_id,
                    "crBefore": pr.cr_before,
                    "crAfter": pr.cr_after,
                    "crDelta": pr.cr_delta,
                    "muAfter": pr.mu_after,
                    "sigmaAfter": pr.sigma_after,
                }
            )

    json.dump({"engine": "py", "results": results}, sys.stdout)


if __name__ == "__main__":
    main()
