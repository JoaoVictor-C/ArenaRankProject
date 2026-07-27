# ArenaRank Frontend — briefing para agentes

Este é o app React do jogador (deployado), já com todas as páginas construídas
(`Home`, `Leaderboard`, `Perfil`, `Partida`, `Duo`, `Winrate`, `Sistema`,
`Campeonatos`/`Campeonatos2`, `Admin`). Ao editar ou adicionar uma página,
**use a fundação compartilhada — não reinvente.**

## Stack & comandos
- React 18 + Vite 5 + TS (strict). Router: `react-router-dom` v6 (rotas em `src/App.tsx`).
- Validar SEMPRE antes de terminar: `npm run build` (na pasta `frontend/`, relativa à raiz do repo) deve passar sem erros de tsc, e `npm run lint` + `npm run typecheck` devem passar.
- StrictMode está ON (effects rodam 2x em dev — escreva effects idempotentes).

## Fonte do design (contexto atual — leia antes de mudanças visuais)
- `PRODUCT.md` — registro do produto, plataforma, posicionamento e público.
- `DESIGN.md` — sistema visual vivo (tema dark, cores, tipografia).
- `.impeccable/live/config.json` — configuração do modo "live" do fluxo de design Impeccable.
- Essas três fontes descrevem o sistema de design **atual**; não existe mais um
  diretório de protótipos HTML para portar — as páginas já estão implementadas.

## Regras de ouro (NÃO QUEBRE)
1. **CSS compartilhado com cuidado:** `src/styles/*`, `src/lib/*`, `src/hooks/*`, `src/components/*` são usados por múltiplas páginas — mudanças ali afetam todo o app. Prefira **criar** um componente/CSS novo e co-localizado à página quando o comportamento for específico dela.
2. **Página = `src/routes/<Nome>.tsx`** + CSS co-localizado `src/routes/<Nome>.css` (importado no topo do `.tsx`). Todo CSS específico da página vai nesse arquivo.
3. **Preserve os nomes de classe CSS usados pelo motor de animação** (`src/lib/animEngine.ts` + `anim.css`) — ex.: `.hero`, `.podium`, `.pod`, `.lb-table`, `.tbl`, `.metrics`, `.feed`, `.sec`, `.pbar`/`.bar`. O engine revela/anima blocos por *querySelector* nesses seletores; renomear sem atualizar o engine quebra a animação silenciosamente.
4. **PT-BR** em todo texto visível e comentários de UI. Termos técnicos (nomes de função, tipos) no original.
5. **Arte de campeão/ícone = placeholder gradiente** (proibido usar arte da Riot). Use `<PlayerAvatar colors={...} />` e `<ChampIcon colors size? />`.
6. **ToS Riot:** NUNCA exiba winrate de augment/item de Arena (pick rate é OK). Nunca exponha μ/σ ou fórmulas cruas na UI — linguagem simples (CR / Pontos / PDL).

## Fundação disponível (importe daqui)
**Componentes** — `import { ... } from "../components";` (barrel em `src/components/index.ts`)
- `<Mi name="search" fill? />` — ícone Material Symbols.
- `<PlayerAvatar colors={{c1,c2}} size? className? />` · `<ChampIcon colors size?("sm"|"lg"|"xl") />` — placeholders (`Avatar.tsx`).
- `<TierBadge tier={TierKey} />` · `<Placement place={n} />` · `<Delta value={n} />` (sinal "−" real, sem seta) · `<Streak kind count />` · `<PlayerTagChip tag={PlayerTag} />` (`Badges.tsx`).
- `<Sparkline values={number[]} className stroke? fill? />` — SVG que o motor de animação "desenha".
- `<StateBlock loading? error? empty?>{children}</StateBlock>` — estados de carregamento/erro/vazio.
- `Header`, `Footer`, `Background`, `Layout`, `TweaksPanel` já estão no shell (`App.tsx`) — não os inclua de novo dentro de uma página.

**Lib** — `import { api } from "../lib/api"; import type { ... } from "../lib/types";`
- `api.leaderboard(opts)` · `api.player(riotId)` · `api.playerMatches(riotId, opts)` · `api.searchPlayers(opts)` · `api.match(matchId)` · `api.champions(opts)` · `api.tournaments()` / `api.tournament(id)` — veja `src/lib/api.ts` para a lista completa e assinaturas exatas (é o client tipado, espelha `src/lib/types.ts`).
- `setAdminKey` / `getAdminKey` / `clearAdminKey` (também em `api.ts`) — chave admin usada pela rota `/admin` (`AdminGate.tsx`).
- `import { nf, signed, pct, deltaClass, tierBadgeClass, tierLabel, winrateBand, timeAgo, fmtCountdown, splitRiotId } from "../lib/format";` — helpers pt-BR.

**Hooks** — `import { useApi } from "../hooks/useApi";` · `import { useIconColors } from "../hooks/useIconColors";`
- `const { data, loading, error } = useApi(() => api.leaderboard({format:"3v3"}), [format]);`
- Padrão: envolva o conteúdo em `<StateBlock loading={loading} error={error}>...usa data!...</StateBlock>`.

**Design tokens** (CSS vars globais, ver `DESIGN.md` para a definição viva): superfícies `--bg --surface --surface-2 --surface-3 --line`; texto `--text --text-dim --text-faint`; marca `--primary --primary-bright --primary-dim`; ouro `--gold --gold-bright --gold-dim`; semântico `--green --red --amber`; raios `--r-sm/md/lg`; `--maxw:1240px`; `--shadow`.
**Classes prontas** (em `base.css`): `.shell .sec .section-head .eyebrow .panel .panel-pad .badge .flag .place .streak .delta .tier .chip(s) .tabs .tab .btn(.primary/.gold/.lg/.ghost) .tbl .bar .pbar .ch-icon .pavatar .breadcrumb` etc.

## Dados
Consuma a API real (`api.*`). Se um campo não existir no tipo, prefira o tipo já definido em `types.ts`; só estenda se necessário e deixe claro por quê. O backend devolve dados reais onde há tabela — alguns widgets (feed "Atividade ao vivo", tierlist de campeão em certas visões) servem amostra determinística por design de contrato, não bug; confira `README.md`/`CLAUDE.md` na raiz antes de assumir regressão. Não hardcode dados no JSX (exceto rótulos/textos fixos da UI).

## Entregue (texto final = resultado)
1. Arquivos criados/modificados.
2. Confirmação de que `npm run build` (e `lint`/`typecheck`) passou (cole as últimas linhas).
3. Notas de fidelidade visual: o que ficou 1:1 com `DESIGN.md`/protótipo de referência, o que adaptou e por quê.
