"""One-run audit: which players have Arena matches Riot knows about and we don't.

Walks EVERY row in ``players``, asks Riot for that account's match ids in the
window, and diffs them against what the database actually computed. Read-only by
default — it writes nothing and rates nothing.

It splits the gap into two kinds, because they have different causes and
different fixes:

``never_ingested``
    Riot lists the match, but there is no ``matches`` row for it at all. The
    discovery pipeline never saw it — a sweep rotation that outran
    ``sweep_matches_per_player``, an outage, a claimed-then-dropped id, or a
    player registered long after the fact (their history predates them being
    tracked). ``--enqueue`` feeds these back into the normal pending list.

``participant_gap``
    The ``matches`` row EXISTS but this player has no ``match_participants`` row
    in it. Discovery worked; the write path lost this player. That is a data
    integrity problem, not a coverage one, and enqueueing will NOT fix it —
    ``matches.processed`` is already true so the match is a no-op on re-ingest.
    These need ``scripts/rerate_matches.py`` or a targeted investigation.

Caveat worth reading before acting on the numbers: a match Riot lists can be
legitimately absent because the pipeline deliberately dropped it (shorter than
``MIN_DURATION_SECONDS``, remake, outside the launch window). The query is
already bounded to the live Arena queues and to the cutoff, which removes most
of that noise, but a small constant ``never_ingested`` count per player is
normal. Sustained double-digit counts are not.

Run (cwd backend; needs DATABASE_URL, REDIS_URL, RIOT_API_KEY):

    python -m scripts.audit_missing_matches
    python -m scripts.audit_missing_matches --since-days 30 --min-missing 10
    python -m scripts.audit_missing_matches --json /tmp/audit.json --enqueue

Or, containerised, without touching the running stack:

    docker compose run --rm audit-missing-matches
    docker compose run --rm audit-missing-matches --since-days 30 --enqueue
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arena.core.config import settings
from arena.db import models as m
from arena.db.session import get_sessionmaker
from arena.workers import queues as Q


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="audit-missing-matches",
        description="Report players whose Riot match history is ahead of the database.",
    )
    ap.add_argument(
        "--since-days",
        type=int,
        default=0,
        help="Lookback window in days. 0 (default) = back to the launch-window "
        "cutoff (MATCH_MIN_STARTED_AT_MS), i.e. everything the pipeline would "
        "ever have accepted.",
    )
    ap.add_argument(
        "--min-missing",
        type=int,
        default=5,
        help="Only LIST players missing at least this many matches (default 5). "
        "Totals in the summary always count everyone.",
    )
    ap.add_argument(
        "--limit-players",
        type=int,
        default=0,
        help="Stop after auditing N players (0 = all). Use for a quick sample.",
    )
    ap.add_argument("--page-size", type=int, default=100, help="Players per DB page / Riot batch.")
    ap.add_argument("--concurrency", type=int, default=8, help="Concurrent Riot id-list calls.")
    ap.add_argument("--matches-per-page", type=int, default=100, help="Riot page size (max 100).")
    ap.add_argument(
        "--max-pages-per-player",
        type=int,
        default=10,
        help="Pagination cap per player per queue. A player who hits it is "
        "reported as truncated — their real gap may be larger.",
    )
    ap.add_argument(
        "--max-api-calls",
        type=int,
        default=0,
        help="Global safety bound on Riot id-list calls (0 = unbounded). The run "
        "stops cleanly and reports what it covered.",
    )
    ap.add_argument("--top", type=int, default=50, help="Rows to print (default 50).")
    ap.add_argument("--json", default="", help="Also write the full report here.")
    ap.add_argument(
        "--enqueue",
        action="store_true",
        help="Push never_ingested ids onto the standard sweep pending list so "
        "the bulk processor picks them up. THE ONLY MODE THAT WRITES ANYTHING.",
    )
    return ap.parse_args(argv)


# ---------------------------------------------------------------------------
# Report shapes
# ---------------------------------------------------------------------------


@dataclass
class PlayerGap:
    puuid: str
    player_id: str
    name: str
    riot_total: int = 0
    computed: int = 0
    never_ingested: list[str] = field(default_factory=list)
    participant_gap: list[str] = field(default_factory=list)
    #: Riot pagination cap was hit — the true gap may be larger than reported.
    truncated: bool = False
    #: Riot errored for at least one queue; counts are a lower bound.
    partial: bool = False

    @property
    def missing(self) -> int:
        return len(self.never_ingested) + len(self.participant_gap)


# ---------------------------------------------------------------------------
# DB reads (all read-only)
# ---------------------------------------------------------------------------


async def _players_page(
    session: AsyncSession, after: str, limit: int
) -> list[tuple[str, str, str]]:
    """Keyset page of ``(player_id, puuid, display_name)`` ordered by puuid.

    Keyset rather than OFFSET so a registration landing mid-run cannot shift the
    pages and skip a player — the same reason the sweep pages this way.
    """
    stmt = (
        select(m.Player.id, m.Player.puuid, m.Player.summoner_name, m.Player.tag_line)
        .where(m.Player.puuid > after)
        .order_by(m.Player.puuid)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    out: list[tuple[str, str, str]] = []
    for pid, puuid, name, tag in rows:
        if not puuid:
            continue
        display = f"{name}#{tag}" if name and tag else (name or "?")
        out.append((str(pid), str(puuid), display))
    return out


async def _computed_by_player(session: AsyncSession, player_ids: list[str]) -> dict[str, set[str]]:
    """``player_id -> {riot_match_id}`` already computed, for a whole page.

    Joins through ``matches`` rather than recomputing ``deterministic_match_id``:
    rows written by the older offline replay path do not necessarily carry the
    UUIDv5-of-riot-id, and a mismatch there would fabricate a gap for every one
    of them.
    """
    if not player_ids:
        return {}
    stmt = (
        select(m.MatchParticipant.player_id, m.Match.riot_match_id)
        .join(m.Match, m.Match.id == m.MatchParticipant.match_id)
        .where(m.MatchParticipant.player_id.in_(player_ids))
    )
    have: dict[str, set[str]] = {pid: set() for pid in player_ids}
    for pid, riot_id in (await session.execute(stmt)).all():
        have.setdefault(str(pid), set()).add(str(riot_id))
    return have


async def _existing_matches(session: AsyncSession, riot_ids: list[str]) -> set[str]:
    """Which of *riot_ids* have a ``matches`` row at all (any player)."""
    if not riot_ids:
        return set()
    stmt = select(m.Match.riot_match_id).where(m.Match.riot_match_id.in_(riot_ids))
    return {str(r) for (r,) in (await session.execute(stmt)).all()}


# ---------------------------------------------------------------------------
# Riot read
# ---------------------------------------------------------------------------


class _Budget:
    """Shared, mutable Riot-call counter with an optional hard ceiling."""

    __slots__ = ("used", "limit")

    def __init__(self, limit: int) -> None:
        self.used = 0
        self.limit = limit

    def take(self) -> bool:
        if self.limit and self.used >= self.limit:
            return False
        self.used += 1
        return True

    @property
    def exhausted(self) -> bool:
        return bool(self.limit) and self.used >= self.limit


async def _riot_ids_for(
    client: Any, puuid: str, since: int, args: argparse.Namespace, budget: _Budget
) -> tuple[list[str], bool, bool]:
    """Return ``(ids, truncated, partial)`` for one account across live queues."""
    ids: list[str] = []
    truncated = False
    partial = False
    for queue_id in settings.live_queue_ids:
        start = 0
        for page in range(args.max_pages_per_player):
            if not budget.take():
                return ids, True, partial
            try:
                got = await client.list_match_ids(
                    puuid,
                    start=start,
                    count=args.matches_per_page,
                    queue=queue_id,
                    start_time=since,
                )
            except Exception as exc:  # noqa: BLE001 - one bad account never aborts the run
                print(f"  ! riot error puuid={puuid[:8]} queue={queue_id}: {exc}")
                partial = True
                break
            if not got:
                break
            ids.extend(got)
            if len(got) < args.matches_per_page:
                break
            start += args.matches_per_page
            if page == args.max_pages_per_player - 1:
                truncated = True
    # Dedup while preserving order; the same id can surface under two queues.
    return list(dict.fromkeys(ids)), truncated, partial


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def _since_epoch(args: argparse.Namespace) -> int:
    if args.since_days > 0:
        return int(time.time()) - args.since_days * 24 * 3600
    return settings.match_min_started_at_ms // 1000


def diff_page(
    page: list[tuple[str, str, str]],
    fetched: list[tuple[list[str], bool, bool]],
    computed_by_player: dict[str, set[str]],
) -> tuple[list[PlayerGap], list[str]]:
    """Pure diff: Riot ids vs computed ids -> per-player gaps + the ids to classify.

    Returned gaps carry every missing id in ``never_ingested``; the caller splits
    that into never-ingested vs participant-gap once it knows which of those ids
    have a ``matches`` row (:func:`split_missing`). Kept pure so the accounting
    is unit-testable without a database or a Riot key.
    """
    gaps: list[PlayerGap] = []
    unknown: list[str] = []
    for (pid, puuid, display), (riot_ids, truncated, partial) in zip(page, fetched):
        computed = computed_by_player.get(pid, set())
        missing = [rid for rid in riot_ids if rid not in computed]
        gaps.append(
            PlayerGap(
                puuid=puuid,
                player_id=pid,
                name=display,
                riot_total=len(riot_ids),
                computed=len(computed & set(riot_ids)),
                never_ingested=missing,
                truncated=truncated,
                partial=partial,
            )
        )
        unknown.extend(missing)
    return gaps, list(dict.fromkeys(unknown))


def split_missing(gaps: list[PlayerGap], known_matches: set[str]) -> None:
    """Split each gap's missing ids by whether a ``matches`` row exists.

    In place. An id with no match row was never discovered; one WITH a match row
    means discovery worked and the write path lost this player — a different
    failure that re-enqueueing cannot fix (``matches.processed`` is already true).
    """
    for gap in gaps:
        pending = gap.never_ingested
        gap.never_ingested = [rid for rid in pending if rid not in known_matches]
        gap.participant_gap = [rid for rid in pending if rid in known_matches]


async def _audit_page(
    session: AsyncSession,
    client: Any,
    page: list[tuple[str, str, str]],
    since: int,
    args: argparse.Namespace,
    budget: _Budget,
) -> list[PlayerGap]:
    """Riot fan-out for the page, then two batched DB reads for the whole page."""
    sem = asyncio.Semaphore(args.concurrency)

    async def _one(puuid: str) -> tuple[list[str], bool, bool]:
        async with sem:
            return await _riot_ids_for(client, puuid, since, args, budget)

    fetched = await asyncio.gather(*[_one(puuid) for _, puuid, _ in page])
    have = await _computed_by_player(session, [pid for pid, _, _ in page])

    gaps, unknown = diff_page(page, fetched, have)
    # One query decides, for every missing id on the page, whether the match was
    # never ingested or was ingested without this player.
    split_missing(gaps, await _existing_matches(session, unknown))
    return gaps


async def _enqueue_missing(redis: Any, gaps: list[PlayerGap]) -> int:
    """Enqueue never_ingested ids as process_match jobs, claim-first.

    Reuses the sweep's claim/enqueue helpers so this behaves exactly like a
    discovery: already-claimed ids are skipped, and a failed enqueue hands the
    claim back instead of stranding the id.
    """
    from arena.workers.ingestion import _dedup_new
    from arena.workers.sweep import _push_claimed

    ids: list[str] = []
    for gap in gaps:
        ids.extend(gap.never_ingested)
    ids = list(dict.fromkeys(ids))
    if not ids:
        return 0
    fresh = await _dedup_new(redis, ids)
    eligible = [
        rid for rid in fresh if Q.evaluate_match_filters(Q.MatchMeta(riot_match_id=rid)).eligible
    ]
    return await _push_claimed(redis, Q.STANDARD_QUEUE, eligible)


def _print_report(gaps: list[PlayerGap], args: argparse.Namespace, budget: _Budget) -> None:
    audited = len(gaps)
    with_gap = [g for g in gaps if g.missing > 0]
    listed = sorted(
        (g for g in gaps if g.missing >= args.min_missing),
        key=lambda g: g.missing,
        reverse=True,
    )
    total_never = sum(len(g.never_ingested) for g in gaps)
    total_partgap = sum(len(g.participant_gap) for g in gaps)
    riot_total = sum(g.riot_total for g in gaps)
    computed = sum(g.computed for g in gaps)

    print()
    print("=" * 78)
    print(f"players audited        {audited}")
    print(f"  with any gap         {len(with_gap)}")
    print(f"  listed (>= {args.min_missing} missing) {len(listed)}")
    print(f"riot matches seen      {riot_total}")
    print(f"  computed             {computed}")
    print(f"  never ingested       {total_never}")
    print(f"  participant gap      {total_partgap}")
    if riot_total:
        print(f"coverage               {100.0 * computed / riot_total:.2f}%")
    print(f"riot id-list calls     {budget.used}{' (BUDGET HIT)' if budget.exhausted else ''}")
    truncated = sum(1 for g in gaps if g.truncated)
    partial = sum(1 for g in gaps if g.partial)
    if truncated:
        print(f"! {truncated} player(s) hit the pagination cap — real gap may be larger")
    if partial:
        print(f"! {partial} player(s) had a Riot error — counts are a lower bound")
    print("=" * 78)

    if not listed:
        print(f"\nNo player is missing {args.min_missing}+ matches.")
        return

    print(f"\n{'player':<26} {'riot':>6} {'have':>6} {'miss':>6} {'never':>6} {'gap':>5}  flags")
    print("-" * 78)
    for g in listed[: args.top]:
        flags = "".join(("T" if g.truncated else "", "P" if g.partial else ""))
        name = (g.name[:22] + "..") if len(g.name) > 24 else g.name
        print(
            f"{name:<26} {g.riot_total:>6} {g.computed:>6} {g.missing:>6} "
            f"{len(g.never_ingested):>6} {len(g.participant_gap):>5}  {flags}"
        )
    if len(listed) > args.top:
        print(f"... and {len(listed) - args.top} more (raise --top or use --json)")
    print("\nflags: T = riot pagination cap hit, P = partial (riot error)")


async def run(args: argparse.Namespace) -> None:
    if not settings.riot_api_key:
        print("RIOT_API_KEY empty — nothing to compare against.")
        return

    from arena.riot import get_client

    client = get_client()
    since = _since_epoch(args)
    budget = _Budget(args.max_api_calls)
    factory = get_sessionmaker()

    print(f"auditing from {time.strftime('%Y-%m-%d %H:%M', time.gmtime(since))} UTC")
    print(f"queues={list(settings.live_queue_ids)} page={args.page_size} conc={args.concurrency}")
    if args.enqueue:
        print("--enqueue: never_ingested ids WILL be pushed to the pending list")

    gaps: list[PlayerGap] = []
    cursor = ""
    started = time.monotonic()
    async with factory() as session:
        while True:
            if args.limit_players and len(gaps) >= args.limit_players:
                break
            page = await _players_page(session, cursor, args.page_size)
            if not page:
                break
            if args.limit_players:
                page = page[: args.limit_players - len(gaps)]

            gaps.extend(await _audit_page(session, client, page, since, args, budget))
            cursor = page[-1][1]

            done = len(gaps)
            missing_so_far = sum(g.missing for g in gaps)
            print(
                f"  ...{done} players | {missing_so_far} missing | "
                f"{budget.used} riot calls | {time.monotonic() - started:.0f}s"
            )
            if budget.exhausted:
                print("! Riot call budget exhausted — stopping early.")
                break
            if len(page) < args.page_size:
                break

    _print_report(gaps, args, budget)

    if args.json:
        payload = {
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "since": since,
            "playersAudited": len(gaps),
            "riotCalls": budget.used,
            "players": [
                {**asdict(g), "missing": g.missing}
                for g in sorted(gaps, key=lambda g: g.missing, reverse=True)
                if g.missing > 0
            ],
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print(f"\nwrote {args.json}")

    if args.enqueue:
        from arena.workers.deps import create_redis_pool

        # An arq-capable pool, not a plain redis.asyncio.Redis — _push_claimed
        # now calls enqueue_job, which only ArqRedis exposes.
        redis = await create_redis_pool()
        try:
            pushed = await _enqueue_missing(redis, gaps)
            print(f"enqueued {pushed} match id(s) to {Q.STANDARD_QUEUE}")
        finally:
            await redis.aclose()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
