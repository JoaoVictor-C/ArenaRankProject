"""Pins the SQL shape of the whole-lobby player upsert.

The statement carries an ``xmax = 0`` discriminator so ``register_players`` can
tell a genuine INSERT from an ON CONFLICT UPDATE in one round-trip — that is
what triggers the one-shot new-player history backfill. ``xmax`` is a Postgres
system column, so only a live Postgres can *execute* it, and the integration
test that does so skips without DATABASE_URL. These compile-level assertions
keep the clause from silently disappearing in the meantime.
"""

from __future__ import annotations

from sqlalchemy.dialects import postgresql

from arena.services.match_pipeline import player_upsert_stmt

_ROWS = [
    {
        "puuid": "pu-a",
        "summoner_name": "A",
        "tag_line": "BR1",
        "region": "br",
        "profile_icon_id": 1,
    },
    {
        "puuid": "pu-b",
        "summoner_name": "B",
        "tag_line": "BR1",
        "region": "br",
        "profile_icon_id": 2,
    },
]


def _compiled() -> str:
    return str(
        player_upsert_stmt(_ROWS).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_returns_the_insert_vs_update_discriminator() -> None:
    sql = _compiled()
    # Without this the backfill would fire for every player in every lobby.
    assert "(xmax = 0)" in sql
    assert "AS inserted" in sql


def test_is_an_upsert_on_puuid_that_returns_every_row() -> None:
    sql = _compiled()
    assert "ON CONFLICT (puuid) DO UPDATE" in sql
    # DO UPDATE (not DO NOTHING) is what makes RETURNING emit a row for existing
    # players too — register_players needs the id of the whole lobby.
    assert "DO NOTHING" not in sql
    assert "RETURNING" in sql
    assert "players.id" in sql and "players.puuid" in sql


def test_preserves_the_coalesce_and_row_order_contract() -> None:
    sql = _compiled()
    # Profile fields refresh only when the payload carries a non-null value.
    assert sql.count("coalesce") == 3
    # Rows are emitted in the caller's (puuid-sorted) order — the deadlock
    # avoidance documented in register_players.
    assert sql.index("pu-a") < sql.index("pu-b")
