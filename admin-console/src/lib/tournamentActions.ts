/* Operator actions against the tournaments surface. Same conventions as
   actions.ts (apiGet/apiSend, Conn-first args). */
import { apiGet, apiSend, type Conn } from "./backend";
import type {
  SetMatchLinkBody,
  SubmitResultBody,
  TournamentCreateBody,
  TournamentDetail,
  TournamentListItem,
} from "./types";

export const fetchTournaments = (
  conn: Conn,
  signal?: AbortSignal,
): Promise<TournamentListItem[]> => apiGet<TournamentListItem[]>(conn, "/tournaments", signal);

/** Admin-gated detail (includes accessKey) — GET /tournament/{id} never sets it. */
export const fetchTournamentDetail = (
  conn: Conn,
  tournamentId: string,
  signal?: AbortSignal,
): Promise<TournamentDetail> =>
  apiGet<TournamentDetail>(
    conn,
    `/admin/tournament/${encodeURIComponent(tournamentId)}`,
    signal,
  );

export const createTournament = (
  conn: Conn,
  body: TournamentCreateBody,
): Promise<TournamentDetail> =>
  apiSend<TournamentDetail>(conn, "POST", "/admin/tournaments", body);

export const setMatchLink = (
  conn: Conn,
  tournamentId: string,
  n: number,
  body: SetMatchLinkBody,
): Promise<TournamentDetail> =>
  apiSend<TournamentDetail>(
    conn,
    "POST",
    `/admin/tournament/${encodeURIComponent(tournamentId)}/match/${n}/link`,
    body,
  );

export const submitMatchResult = (
  conn: Conn,
  tournamentId: string,
  n: number,
  body: SubmitResultBody,
): Promise<TournamentDetail> =>
  apiSend<TournamentDetail>(
    conn,
    "POST",
    `/admin/tournament/${encodeURIComponent(tournamentId)}/match/${n}/result`,
    body,
  );
