/* Player search + moderation actions. Same conventions as operatorActions.ts. */
import { apiGet, apiSend, type Conn } from "./backend";
import type { PlayerModerationBody, PlayerModerationResult, PlayerSearchRow } from "./types";

export const searchPlayers = (
  conn: Conn,
  q: string,
  signal?: AbortSignal,
): Promise<PlayerSearchRow[]> =>
  apiGet<PlayerSearchRow[]>(conn, `/admin/players/search?q=${encodeURIComponent(q)}`, signal);

export const updatePlayerModeration = (
  conn: Conn,
  playerId: string,
  body: PlayerModerationBody,
): Promise<PlayerModerationResult> =>
  apiSend<PlayerModerationResult>(
    conn,
    "PATCH",
    `/admin/players/${encodeURIComponent(playerId)}/moderation`,
    body,
  );
