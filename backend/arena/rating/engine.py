"""Match rating engine — gamified CRS pipeline over an OpenSkill Plackett-Luce base.

Ports slice-1 `rate()`: pure Plackett-Luce update (via the `openskill` lib, which the
formula spec also mandates) wrapped by the proposal's gamified modifier pipeline, the
conservative CR display, and the Trinity hardening (C1 sigma-scaled cap, C2 sigma-freeze
for flagged accounts, G2 param validation). Deterministic and side-effect free.

Pipeline per eligible player (proposal section 13.2):
    delta = delta_mu_base * placement_weight * placement_amp * streak_mult
            * soft_cap_factor * boosting_factor
    delta_final = dispersion_cap(delta, sigma_before)        # sigma-scaled, last
    mu_after = mu_before + delta_final
    sigma_after = pure PL  (or sigma-frozen when boosting flag f > 0 — DEC-A)
    cr_after = to_cr(mu_after, sigma_after)
"""

from __future__ import annotations

from openskill.models import PlackettLuce

from . import caps as C
from . import modifiers as M
from .params import validate_params
from .types import (
    AppliedModifiers,
    MatchInput,
    ParticipantInput,
    PlayerRatingResult,
    RatingResult,
)


def _frozen(part: ParticipantInput, is_win: bool) -> PlayerRatingResult:
    s = part.state
    return PlayerRatingResult(
        player_id=part.player_id,
        mu_before=s.mu,
        mu_after=s.mu,
        sigma_before=s.sigma,
        sigma_after=s.sigma,
        cr_before=s.cr,
        cr_after=s.cr,
        cr_delta=0.0,
        eligible=False,
        is_win=is_win,
        new_streak=s.current_streak,
        modifiers=AppliedModifiers(
            pl_base_delta_mu=0.0,
            placement_weight=1.0,
            placement_amp=1.0,
            streak_mult=1.0,
            soft_cap_factor=1.0,
            boosting_factor=1.0,
            party_factor=1.0,
            dispersion_clamped=False,
            final_delta_mu=0.0,
        ),
    )


def rate(match: MatchInput) -> RatingResult:
    p = match.params
    validate_params(p)  # Trinity G2: reject untrusted NaN/Infinity params before any math

    teams = match.teams
    if len(teams) < 2:
        raise ValueError("a match needs at least 2 teams")
    if any(len(t.participants) == 0 for t in teams):
        raise ValueError("every team needs at least 1 participant")

    team_count = len(teams)
    any_eligible = any(pt.eligible_for_progression for t in teams for pt in t.participants)

    # Deterministic order: teams by (placement, team_id), players by player_id (I2).
    ordered_teams = sorted(teams, key=lambda t: (t.placement, t.team_id))
    ordered_parts = [sorted(t.participants, key=lambda pt: pt.player_id) for t in ordered_teams]

    if not any_eligible:
        # All ineligible -> void (D3/I4). Everyone frozen.
        return RatingResult(
            match_id=match.match_id,
            voided=True,
            players=[
                _frozen(pt, t.placement <= team_count // 2)
                for t, parts in zip(ordered_teams, ordered_parts)
                for pt in parts
            ],
        )

    model = PlackettLuce(mu=p.mu0, sigma=p.sigma0, beta=p.beta, tau=p.tau, kappa=p.kappa)
    os_teams = [
        [model.rating(mu=pt.state.mu, sigma=pt.state.sigma, name=pt.player_id) for pt in parts]
        for parts in ordered_parts
    ]
    ranks = [float(t.placement) for t in ordered_teams]
    updated = model.rate(os_teams, ranks=ranks)

    # Lobby strength for the skill-mismatch override (CR cap layer): mean mu_before
    # across all participants, computed excluding self per player below.
    all_states = [pt.state for parts in ordered_parts for pt in parts]
    sum_mu_all = sum(st.mu for st in all_states)
    n_all = len(all_states)

    results: list[PlayerRatingResult] = []
    for t, parts, new_team in zip(ordered_teams, ordered_parts, updated):
        is_win = t.placement <= team_count // 2
        for pt, new_r in zip(parts, new_team):
            s = pt.state
            sigma_after_pl = new_r.sigma
            delta_mu_base = new_r.mu - s.mu

            if not pt.eligible_for_progression:
                results.append(_frozen(pt, is_win))
                continue

            sign = 1.0 if delta_mu_base > 0 else (-1.0 if delta_mu_base < 0 else 0.0)
            pw = M.placement_weight(t.placement, team_count, p)
            pa = M.placement_amp(s, p)
            sm = M.streak_multiplier(s.current_streak, sign, p)
            scf = M.soft_cap_factor(s.cr, delta_mu_base, p)
            bf = M.boosting_penalty(delta_mu_base, pt.boosting_penalty_factor)
            df = M.party_dampener(delta_mu_base, pt.party_penalty_factor)

            delta = delta_mu_base * pw * pa * sm * scf * bf * df
            delta_final, clamped = M.dispersion_cap(delta, s.sigma, p)

            mu_after = s.mu + delta_final

            # C2 / DEC-A: freeze sigma-shrink proportional to the boosting flag (flagged only).
            f = max(0.0, min(1.0, pt.boosting_penalty_factor))
            sigma_after = (
                s.sigma - (1.0 - f) * (s.sigma - sigma_after_pl) if f > 0 else sigma_after_pl
            )

            cr_after = M.to_cr(mu_after, sigma_after, p)

            # CR-space (PDL) cap layer — option B-pure: clamp the displayed cr_delta to
            # the placement-relative bound, then back-solve mu_after so the CR identity
            # cr = (mu - 3*sigma)*scale + offset still holds exactly. No ledger, no new
            # column (arenarank runs no matchmaking, so mu coherence is moot).
            if p.caps is not None:
                cp = p.caps
                lobby_mean = (sum_mu_all - s.mu) / (n_all - 1) if n_all > 1 else s.mu
                ovr = C.mismatch_override(
                    s.mu, lobby_mean, sigma=s.sigma, games=s.matches_played, cp=cp
                )
                scf = C.high_cr_scale(s.cr, cp)
                comp_win = C.composite_win_mult(ovr, scf, 1.0, cp)  # party R3 OFF
                capped_delta, clamped = C.apply_pdl_cap(
                    cr_after - s.cr,
                    t.placement,
                    team_count,
                    composite_win=comp_win,
                    composite_loss=1.0,
                    cp=cp,
                    # A flagged booster must not collect the minimum-gain floor.
                    gain_floor_mult=1.0 - max(0.0, min(1.0, pt.boosting_penalty_factor)),
                )
                if clamped:
                    cr_after = s.cr + capped_delta
                    mu_after = (cr_after - p.base_offset) / p.scale_factor + 3.0 * sigma_after

            # PDL floor: a player's displayed CR can never drop below 0. The cap
            # layer back-solves cr_after directly (bypassing to_cr), so re-assert
            # the floor here and keep the CR identity by re-deriving mu_after.
            if cr_after < 0.0:
                cr_after = 0.0
                mu_after = (cr_after - p.base_offset) / p.scale_factor + 3.0 * sigma_after

            results.append(
                PlayerRatingResult(
                    player_id=pt.player_id,
                    mu_before=s.mu,
                    mu_after=mu_after,
                    sigma_before=s.sigma,
                    sigma_after=sigma_after,
                    cr_before=s.cr,
                    cr_after=cr_after,
                    cr_delta=cr_after - s.cr,
                    eligible=True,
                    is_win=is_win,
                    new_streak=M.next_streak(s.current_streak, is_win),
                    modifiers=AppliedModifiers(
                        pl_base_delta_mu=delta_mu_base,
                        placement_weight=pw,
                        placement_amp=pa,
                        streak_mult=sm,
                        soft_cap_factor=scf,
                        boosting_factor=bf,
                        party_factor=df,
                        dispersion_clamped=clamped,
                        final_delta_mu=delta_final,
                    ),
                )
            )

    return RatingResult(match_id=match.match_id, voided=False, players=results)
