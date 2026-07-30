-- create_publication.sql — publicação lógica do read path (T2.4).
-- Roda UMA vez no PRIMÁRIO (notebook), depois do alembic upgrade head:
--
--   docker compose -f docker-compose.notebook.yml exec postgres \
--     psql -U arena -d arena -f /replication/create_publication.sql
--
-- Só as tabelas que o read path consome (validado contra arena/db/models.py):
--   players, seasons, player_seasons          identidade + rating corrente
--   matches, match_participants               partidas + histórico/gráfico do perfil
--   champion_stats                            tierlist/mains/OTP
--   tournaments, tournament_teams,
--   tournament_matches                        superfície /tournaments
--   champion_build_ref                        /champions/{id}/build + /champions/build/top
--   cr_snapshots_recent                       delta7d (espelho plano da T2.3)
--   champion_daily_stats                      tierlist /champions + trend + delta7d (B1/B2)
--   season_record_cache                       /meta/records materializado
--   champion_combo_stats                      /champions/synergy* materializado
--
-- FICAM FORA (deliberado):
--   cr_snapshots        hypertable/base histórica — não replica p/ vanilla; o
--                       read path usa cr_snapshots_recent
--   integrity_events    operacional/admin (write path)
--   player_achievements escrito na virada de temporada; nenhum router público lê
--
-- publish_via_partition_root = true: matches e match_participants são
-- PARTICIONADAS (p00–p15); publicar pela raiz desacopla a réplica do layout
-- exato de partições (o apply entra pela tabela-raiz).
--
-- Idempotência: DROP + CREATE (recriar a publicação não afeta subscriptions
-- existentes até o próximo REFRESH; num resync completo o init_replica.sh
-- recria a subscription de qualquer forma).

DROP PUBLICATION IF EXISTS arena_read;

CREATE PUBLICATION arena_read
    FOR TABLE
        players,
        seasons,
        player_seasons,
        matches,
        match_participants,
        champion_stats,
        tournaments,
        tournament_teams,
        tournament_matches,
        champion_build_ref,
        cr_snapshots_recent,
        champion_daily_stats,
        season_record_cache,
        champion_combo_stats
    WITH (publish_via_partition_root = true);

-- Conferência rápida:
SELECT pubname, puballtables, pubinsert, pubupdate, pubdelete
FROM pg_publication WHERE pubname = 'arena_read';
SELECT schemaname, tablename FROM pg_publication_tables
WHERE pubname = 'arena_read' ORDER BY tablename;
