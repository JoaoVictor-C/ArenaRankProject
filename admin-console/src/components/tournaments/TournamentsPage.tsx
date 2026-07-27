import { useCallback, useState } from "react";
import type { Conn } from "../../lib/backend";
import { useTournaments } from "../../lib/useTournaments";
import { TournamentList } from "./TournamentList";
import { TournamentDetail } from "./TournamentDetail";

export function TournamentsPage({ conn }: { conn: Conn }) {
  const list = useTournaments(conn);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const onCreated = useCallback(
    (id: string) => {
      list.refresh();
      setSelectedId(id);
    },
    [list],
  );

  if (selectedId) {
    return (
      <TournamentDetail
        conn={conn}
        tournamentId={selectedId}
        onBack={() => {
          setSelectedId(null);
          list.refresh();
        }}
      />
    );
  }

  return (
    <TournamentList
      conn={conn}
      tournaments={list.tournaments}
      loading={list.loading}
      error={list.error}
      onSelect={setSelectedId}
      onCreated={onCreated}
    />
  );
}
