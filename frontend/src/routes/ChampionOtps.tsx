import { useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Mi } from "../components/Mi";
import { PlayerAvatar } from "../components/Avatar";
import { StateBlock } from "../components/StateBlock";
import { ParticleField } from "../components/ParticleField";
import { useApi } from "../hooks/useApi";
import { api } from "../lib/api";
import { nf } from "../lib/format";
import {
  STATE_SPINNER_LOOP,
  useFlipList,
  useGsapEntrance,
  useGsapInteractions,
  useGsapLoop,
  type EntranceStep,
  type InteractionMotion,
} from "../lib/motion";
import type { ChampTopPlayer } from "../lib/types";
import "./ChampionOtps.css";

const pct = (value: number) => `${Math.round(value)}%`;
const place = (value: number) => value.toFixed(2).replace(".", ",");
const INVALID_CHAMPION_ERROR = Object.assign(new Error("Campeão inválido"), { status: 404 });

const OTP_ENTRANCE: EntranceStep[] = [
  {
    selector: ".otp-crumb",
    from: { opacity: 0, y: -8 },
    duration: 0.28,
  },
  {
    selector: ".otp-hero",
    from: { opacity: 0, y: 18, clipPath: "inset(0 0 12% 0 round 14px)" },
    duration: 0.55,
    position: "-=0.06",
  },
  {
    selector: ".otp-board",
    from: { opacity: 0, y: 20, filter: "blur(4px)" },
    duration: 0.5,
    position: "-=0.24",
  },
  {
    selector: ".otp-row",
    from: { opacity: 0, x: 14 },
    duration: 0.36,
    stagger: 0.035,
    position: "-=0.28",
  },
  {
    selector: ".otp-method",
    from: { opacity: 0, y: 10 },
    duration: 0.32,
    position: "-=0.16",
  },
];

const OTP_INTERACTIONS: InteractionMotion[] = [
  { trigger: ".otp-row-link", to: { y: -2, x: 2 } },
  {
    trigger: ".otp-row-link",
    target: ".otp-open",
    to: { opacity: 1, x: 2 },
    rest: { opacity: 0, x: 0 },
  },
];

function PlayerRow({ player, rank }: { player: ChampTopPlayer; rank: number }) {
  const content = (
    <>
      <span className={`otp-rank${rank <= 3 ? ` top-${rank}` : ""}`}>{rank}</span>
      <span className="otp-player">
        <PlayerAvatar
          colors={player.avatar}
          url={player.profileIconUrl ?? undefined}
          alt={player.name}
          size={42}
        />
        <span className="otp-identity">
          <strong>{player.name}</strong>
          <small>{player.handle || "Riot ID indisponível"}</small>
        </span>
      </span>
      <span className="otp-cell otp-win">{pct(player.winrate)}</span>
      <span className="otp-cell">{nf(player.games)}</span>
      <span className="otp-cell">{place(player.avgPlace)}</span>
      <span className="otp-open" aria-hidden="true">
        <Mi name="arrow_outward" />
      </span>
    </>
  );

  if (!player.handle) return <div className="otp-row">{content}</div>;

  return (
    <Link
      className="otp-row otp-row-link"
      to={`/perfil/${encodeURIComponent(`${player.name}${player.handle}`)}`}
    >
      {content}
    </Link>
  );
}

export function ChampionOtps() {
  const { championId } = useParams();
  const id = Number(championId);
  const validId = Number.isInteger(id) && id > 0;
  const [search, setSearch] = useState("");
  const mains = useApi(
    () => (validId ? api.championOtps(id) : Promise.reject(INVALID_CHAMPION_ERROR)),
    [id, validId],
  );
  const champions = useApi(() => api.champions({ format: "3v3" }), []);
  const champion = champions.data?.table.find((entry) => entry.championId === id);

  const players = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("pt-BR");
    if (!query) return mains.data?.players ?? [];
    return (mains.data?.players ?? []).filter((player) =>
      `${player.name}${player.handle}`.toLocaleLowerCase("pt-BR").includes(query),
    );
  }, [mains.data?.players, search]);

  const name = mains.data?.name || champion?.name || "Campeão";
  const championIconUrl = mains.data?.championIconUrl || champion?.championIconUrl;
  const pageRef = useRef<HTMLElement>(null);
  const normalizedSearch = search.trim().toLocaleLowerCase("pt-BR");
  useGsapEntrance(pageRef, {
    steps: OTP_ENTRANCE,
    deps: [validId, Boolean(mains.data), Boolean(mains.error)],
  });
  useGsapLoop(pageRef, [STATE_SPINNER_LOOP]);
  const rowFlip = useFlipList(pageRef, ".otp-row", normalizedSearch);
  useGsapInteractions(pageRef, OTP_INTERACTIONS);

  return (
    <main className="otp-page" ref={pageRef} data-gsap-scope>
      <div className="otp-ambient" aria-hidden="true" />
      <ParticleField variant="route" />

      <div className="otp-shell">
        <nav className="otp-crumb" aria-label="Navegação estrutural">
          <Link to="/campeoes">Campeões</Link>
          <Mi name="chevron_right" />
          {validId ? <Link to={`/campeao/${id}`}>{name}</Link> : <span>Campeão inválido</span>}
          <Mi name="chevron_right" />
          <span>OTPs</span>
        </nav>

        <header className="otp-hero">
          <div className="otp-champion">
            {championIconUrl ? (
              <img src={championIconUrl} alt="" />
            ) : (
              <span aria-hidden="true">
                <Mi name="shield" />
              </span>
            )}
          </div>
          <div className="otp-heading">
            <span className="otp-eyebrow">Ladder BR · Arena 3v3</span>
            <h1>Top OTPs de {name}</h1>
            <p>
              Os jogadores com mais partidas registradas neste campeão. Winrate considera
              colocações na metade superior do lobby.
            </p>
          </div>
          <div
            className="otp-count"
            aria-label={mains.loading && validId ? "Total de jogadores carregando" : "Total de jogadores ranqueados"}
          >
            <strong>{mains.loading || !validId ? "—" : nf(mains.data?.players.length ?? 0)}</strong>
            <span>jogadores ranqueados</span>
          </div>
        </header>

        <section className="otp-board" aria-labelledby="otp-board-title">
          <div className="otp-toolbar">
            <div>
              <span className="otp-kicker">Especialistas do campeão</span>
              <h2 id="otp-board-title">Ranking Top {mains.data?.limit ?? 100}</h2>
            </div>
            <label className="otp-search">
              <Mi name="search" />
              <input
                value={search}
                onChange={(event) => {
                  rowFlip.capture();
                  setSearch(event.target.value);
                }}
                placeholder="Buscar jogador…"
                aria-label="Buscar jogador no ranking"
              />
            </label>
          </div>

          <StateBlock
            loading={validId && mains.loading}
            loadingLabel="Carregando ranking de OTPs…"
            error={!validId ? INVALID_CHAMPION_ERROR : mains.error}
            errorLabel={!validId ? "Campeão inválido." : undefined}
            onRetry={validId ? mains.retry : undefined}
            empty={validId && !mains.loading && !mains.error && mains.data?.players.length === 0}
          >
            <div className="otp-table" role="table" aria-label={`Top OTPs de ${name}`}>
              <div className="otp-table-head" role="row">
                <span>#</span>
                <span>Jogador</span>
                <span className="right">Winrate</span>
                <span className="right">Jogos</span>
                <span className="right">Col. média</span>
                <span />
              </div>
              <div role="rowgroup">
                {players.map((player, index) => (
                  <PlayerRow
                    key={`${player.name}${player.handle}`}
                    player={player}
                    rank={(mains.data?.players.indexOf(player) ?? index) + 1}
                  />
                ))}
              </div>
              {players.length === 0 && search && (
                <div className="otp-no-results">
                  <Mi name="person_search" />
                  Nenhum jogador encontrado para “{search}”.
                </div>
              )}
            </div>
          </StateBlock>
          {mains.data?.truncated && (
            <p className="otp-rollout">
              <Mi name="database" />
              Top 20 temporário — o Top 100 aparece assim que o novo contrato do backend entrar no ar.
            </p>
          )}
        </section>

        <p className="otp-method">
          <Mi name="verified" />
          Ranking ordenado por volume de partidas no campeão; desempate por colocações na
          metade superior. Dados reais da ladder ArenaRank.
        </p>
      </div>
    </main>
  );
}
