# ArenaRank Frontend — briefing para agentes de página

Você porta UMA página do protótipo de design para **React + Vite + TypeScript**, pixel-perfect e com animações, **wired na read-API real**. A fundação compartilhada já existe — **use-a, não reinvente**.

## Stack & comandos
- React 18 + Vite 5 + TS (strict). Router: `react-router-dom` v6.
- Validar SEMPRE antes de terminar: `npm run build` (na pasta `F:\arenarank\frontend`) deve passar **sem erros de tsc** e o Vite buildar. Rode também `npx tsc -b --noEmit` se quiser checagem rápida.
- StrictMode está ON (effects rodam 2x em dev — escreva effects idempotentes).

## Regras de ouro (NÃO QUEBRE)
1. **NÃO edite arquivos compartilhados:** `src/styles/*.css`, `src/lib/*`, `src/hooks/*`, `src/components/*` existentes. Você pode **CRIAR arquivos novos** (ex.: um componente só seu em `src/components/`, ou seu CSS de página). Isso evita conflito entre os agentes paralelos.
2. **Sua página = `src/routes/<NomeDela>.tsx`** (substitua o stub) + **um CSS co-localizado** `src/routes/<NomeDela>.css` importado no topo do .tsx (`import "./<NomeDela>.css";`). Todo CSS específico da página vai nesse arquivo.
3. **Preserve os nomes de classe CSS do design** (ex.: `.hero`, `.podium`, `.pod`, `.pod-fx`, `.pod-rank`, `.lb-table`, `.standings`, `.tbl`, `.metrics`, `.cards`, `.doc-sec`...). O motor de animação (`anim.css` + `animEngine.ts`) revela blocos por esses seletores e anima o pódio/sparklines/contadores automaticamente. Se renomear, perde a animação.
4. **PT-BR** em todo texto visível e comentários. Termos técnicos no original.
5. **Arte de campeão/ícone = placeholder gradiente** (proibido usar arte da Riot). Use `<PlayerAvatar colors={...} />` e `<ChampIcon colors={...} />`.
6. **ToS Riot:** NUNCA exiba winrate de augment/item de Arena (pick rate é OK).
7. **Sem μ/σ nem fórmulas cruas** na UI — linguagem simples (CR / Pontos / PDL).

## Fundação disponível (importe daqui)
**Componentes** — `import { ... } from "../components";`
- `<Mi name="search" fill? />` — ícone Material Symbols.
- `<PlayerAvatar colors={{c1,c2}} size? className? />` · `<ChampIcon colors size?("sm"|"lg"|"xl") />` — placeholders.
- `<TierBadge tier={TierKey} />` · `<Placement place={n} />` · `<Delta value={n} />` (sinal "−" real, sem seta) · `<Streak kind count />` · `<PlayerTagChip tag={PlayerTag} />`.
- `<Sparkline values={number[]} className="rc-spark"|"spark" stroke? fill? />` — SVG que o FX "desenha".
- `<StateBlock loading? error? empty?>{children}</StateBlock>` — estados de carregamento/erro/vazio.
- (Header, Footer, Background, Layout, TweaksPanel já estão no shell — NÃO os inclua na página.)

**Lib** — `import { api } from "../lib/api"; import type { ... } from "../lib/types";`
- `api.leaderboard({format,scope,season,limit,offset})` · `api.player(riotId)` · `api.match(matchId)` · `api.champions({format,metric,patch,region})` · `api.tournaments()` · `api.tournament(id)` · `api.adminOverview()` · `api.lastUpdate(rank?)`.
- Tipos em `src/lib/types.ts` (espelham `F:\arenarank\spec\api_contract_v1.md` — LEIA o contrato p/ os shapes).
- `import { nf, signed, pct, deltaClass, tierBadgeClass, tierLabel, winrateBand, timeAgo, fmtCountdown, splitRiotId } from "../lib/format";` — helpers pt-BR.

**Hooks** — `import { useApi } from "../hooks/useApi";`
- `const { data, loading, error } = useApi(() => api.leaderboard({format:"3v3"}), [format]);`
- Padrão: envolva o conteúdo em `<StateBlock loading={loading} error={error}>...usa data!...</StateBlock>`.

**Design tokens** (CSS vars já globais): superfícies `--bg --surface --surface-2 --surface-3 --line`; texto `--text --text-dim --text-faint`; marca `--primary --primary-bright --primary-dim`; ouro `--gold --gold-bright --gold-dim`; semântico `--green --red --amber`; raios `--r-sm/md/lg`; `--maxw:1240px`; `--shadow`.
**Classes prontas** (em base.css): `.shell .sec .section-head .eyebrow .panel .panel-pad .badge .flag .place .streak .delta .tier .chip(s) .tabs .tab .btn(.primary/.gold/.lg/.ghost) .tbl .bar .pbar .ch-icon .pavatar .breadcrumb` etc.

## Fonte do design (LEIA top-to-bottom antes de portar)
Os protótipos estão em `F:\arenarank\_design_staging\arenarank\project\`. Cada página tem um `.html` (com `<style>` page-specific + markup) e geralmente um `.js` (dados + render). **O `<style>` vira seu `<Page>.css`; o markup vira JSX; o `.js` (dados/render/interatividade) vira React + chamadas à `api`.** Screenshots de referência em `project/screenshots/`.

## Dados
Consuma a API real (`api.*`). Se um campo do design não existir no tipo, prefira o tipo do contrato; só estenda se necessário e deixe claro. O backend já devolve dados (reais onde há tabela; sample determinístico p/ subsistemas não modelados) — sua página deve renderizar a partir de `data`, com `<StateBlock>` para loading/erro. Não hardcode os dados no JSX (exceto rótulos/textos fixos da UI).

## Entregue (texto final = resultado)
1. Arquivos criados/modificados.
2. Confirmação de que `npm run build` passou (cole as últimas linhas).
3. Notas de fidelidade: o que ficou 1:1, o que adaptou e por quê.
