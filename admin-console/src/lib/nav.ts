/* ============================================================
   Sidebar nav structure (Operação / Moderação / Gestão) and the
   per-page title/description shown atop <main>. Static — no data
   dependency, so it lives next to the other `lib/` data shapes.
   ============================================================ */

export type View =
  | "visao"
  | "health"
  | "workers"
  | "queues"
  | "riot"
  | "daily"
  | "integrity"
  | "flags"
  | "dlq"
  | "audit"
  | "players"
  | "roles"
  | "season"
  | "refill"
  | "tournaments"
  | "activity";

export interface NavItem {
  id: View;
  label: string;
  icon: string;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Operação",
    items: [
      { id: "visao", label: "Visão geral", icon: "monitoring" },
      { id: "health", label: "Saúde do sistema", icon: "ecg_heart" },
      { id: "workers", label: "Workers", icon: "bolt" },
      { id: "queues", label: "Filas", icon: "layers" },
      { id: "riot", label: "Riot API", icon: "api" },
      { id: "daily", label: "Partidas diárias", icon: "bar_chart" },
    ],
  },
  {
    label: "Moderação",
    items: [
      { id: "integrity", label: "Fila de integridade", icon: "balance" },
      { id: "flags", label: "Flags de jogador", icon: "flag" },
      { id: "dlq", label: "Revisão de DLQ", icon: "report" },
      { id: "audit", label: "Registro de auditoria", icon: "history" },
    ],
  },
  {
    label: "Gestão",
    items: [
      { id: "players", label: "Busca de jogadores", icon: "person_search" },
      { id: "roles", label: "Papéis & permissões", icon: "admin_panel_settings" },
      { id: "season", label: "Temporada", icon: "calendar_month" },
      { id: "refill", label: "Refill da temporada", icon: "restart_alt" },
      { id: "tournaments", label: "Campeonatos", icon: "emoji_events" },
      { id: "activity", label: "Feed de atividade", icon: "timeline" },
    ],
  },
];

export const PAGE_META: Record<View, { title: string; desc: string }> = {
  visao: {
    title: "Visão geral",
    desc: "Métricas agregadas do backend em tempo real via telemetria.",
  },
  health: {
    title: "Saúde do sistema",
    desc: "Estado dos workers e da API da Riot, derivado de /admin/overview.",
  },
  workers: {
    title: "Workers",
    desc: "Pools de workers arq · pausar e retomar em tempo real.",
  },
  queues: {
    title: "Filas",
    desc: "Profundidade das filas Redis padrão e prioritária.",
  },
  riot: {
    title: "Riot API",
    desc: "Consumo do rate limit da Riot API por bucket.",
  },
  daily: {
    title: "Partidas diárias",
    desc: "Rollup diário de partidas processadas nos últimos dias.",
  },
  integrity: {
    title: "Fila de integridade",
    desc: "Partidas sinalizadas para revisão · o sistema não pune automaticamente.",
  },
  flags: {
    title: "Flags de jogador",
    desc: "Contas com flags de moderação (banidas, shadowban ou restritas).",
  },
  dlq: {
    title: "Revisão de DLQ",
    desc: "Partidas que falharam após esgotar as tentativas de reprocessamento.",
  },
  refill: {
    title: "Refill da temporada",
    desc:
      "Repovoar a janela da temporada e avaliar tudo em ordem cronológica.",
  },
  audit: {
    title: "Registro de auditoria",
    desc: "Toda ação privilegiada, com operador, alvo e origem.",
  },
  players: {
    title: "Busca de jogadores",
    desc: "Consulta por nome, tag ou PUUID · status de moderação.",
  },
  roles: {
    title: "Papéis & permissões",
    desc: "Matriz de RBAC aplicada no backend · chaves por operador.",
  },
  season: {
    title: "Temporada",
    desc: "Configuração e ciclo de vida da temporada ativa.",
  },
  tournaments: {
    title: "Campeonatos",
    desc: "Criação e gestão de campeonatos.",
  },
  activity: {
    title: "Feed de atividade",
    desc: "Linha do tempo unificada de ações administrativas.",
  },
};
