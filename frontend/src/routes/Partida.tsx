import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import { StateBlock } from "../components";
import { useApi } from "../hooks/useApi";
import {
  isPartidaDemoEnabled,
  loadPartidaDossier,
} from "./partidaDossierModel";
import { PartidaDossierView } from "./PartidaDossier";

if (import.meta.env.DEV) {
  void import("./Partida.dev.css");
}

export function Partida() {
  const { matchId = "" } = useParams<{ matchId: string }>();
  const location = useLocation();
  const demo = isPartidaDemoEnabled(location.search);
  const { data, loading, error } = useApi(
    () => loadPartidaDossier(matchId, demo),
    [matchId, demo],
  );
  const [selectedTeamIndex, setSelectedTeamIndex] = useState(0);
  const [selectedPlayerRiotId, setSelectedPlayerRiotId] = useState("");
  const firstPlayerRiotId = data?.teams[0]?.players[0]?.riotId ?? "";
  const selectedTeam = data?.teams[selectedTeamIndex] ?? data?.teams[0];
  const effectiveSelectedPlayerRiotId =
    selectedPlayerRiotId || selectedTeam?.players[0]?.riotId || "";

  useEffect(() => {
    setSelectedTeamIndex(0);
    setSelectedPlayerRiotId(firstPlayerRiotId);
  }, [data?.detail.matchId, firstPlayerRiotId]);

  function selectTeam(index: number): void {
    const firstPlayer = data?.teams[index]?.players[0];
    setSelectedTeamIndex(index);
    setSelectedPlayerRiotId(firstPlayer?.riotId ?? "");
  }

  return (
    <div className="shell">
      <div className="breadcrumb">
        <Link to="/">Início</Link>
        <span className="sep">›</span>
        <span>Partida</span>
      </div>

      <StateBlock loading={loading} error={error} empty={!data && !loading && !error}>
        {data && (
          <PartidaDossierView
            dossier={data}
            selectedTeamIndex={selectedTeamIndex}
            selectedPlayerRiotId={effectiveSelectedPlayerRiotId}
            onSelectTeam={selectTeam}
            onSelectPlayer={setSelectedPlayerRiotId}
          />
        )}
      </StateBlock>
    </div>
  );
}
