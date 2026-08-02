---
name: ArenaRank
description: O hub social competitivo do modo Arena de LoL — ranking, campeonatos e perfis num salão dark de esports.
colors:
  primary: "#2f9bd6"
  primary-bright: "#4cb6ec"
  gold: "#d9b25f"
  gold-bright: "#ecc77a"
  up-green: "#46c084"
  down-red: "#e2574f"
  warn-amber: "#e0a83a"
  cta-entrar: "#ec3a34"
  bg: "#0b0c0f"
  bg-deep: "#08090b"
  surface: "#131419"
  surface-2: "#181a20"
  surface-3: "#1e2128"
  line: "#262a33"
  line-strong: "#333845"
  text: "#eef0f3"
  text-dim: "#9aa0aa"
  text-faint: "#878e9a"
typography:
  display:
    fontFamily: "Anton, sans-serif"
    fontSize: "58px"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "0"
  headline:
    fontFamily: "Plus Jakarta Sans, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.01em"
  title:
    fontFamily: "Plus Jakarta Sans, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0"
  body:
    fontFamily: "Plus Jakarta Sans, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "0"
  label:
    fontFamily: "Plus Jakarta Sans, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.08em"
  data:
    fontFamily: "ui-monospace, SF Mono, Menlo, monospace"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1
    letterSpacing: "0"
    fontFeature: "tabular-nums"
rounded:
  sm: "6px"
  md: "9px"
  lg: "12px"
  pill: "999px"
spacing:
  base: "8px"
  row: "12px"
  panel: "20px"
  shell: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "10px 16px"
  button-gold:
    backgroundColor: "{colors.gold}"
    textColor: "#2a2008"
    rounded: "{rounded.md}"
    padding: "10px 16px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "10px 16px"
  chip:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text-dim}"
    rounded: "{rounded.pill}"
    padding: "8px 13px"
  chip-active:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    rounded: "{rounded.pill}"
    padding: "8px 13px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
    padding: "{spacing.panel}"
  input-search:
    backgroundColor: "#141519"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    height: "44px"
---

# Design System: ArenaRank

## 1. Overview

**Creative North Star: "O Coliseu Escuro"**

ArenaRank é uma arena de gladiadores filmada por um broadcast de esports. O palco é pedra escura — um quase-preto azulado (`#0b0c0f`) sobre o qual tudo repousa — e a luz que importa é o ouro, reservada para o que foi conquistado: o topo do ranking, o CR, os medalhões, as molduras de campeão. Azul é a voz do sistema (links, foco, seleção, ação); ouro é o troféu. Nada aqui deve soar provisório ou de brincadeira: o rank precisa parecer uma conquista com valor real, porque essa legitimidade é o produto. A densidade é de esports — tabelas confiáveis, números tabulares, muita informação por tela — mas curada, nunca o caos de um site de stats coberto de anúncios.

O sistema é dark por convicção, não por moda: o jogador chega para se medir contra a cena, e o fundo escuro com ouro no topo é a linguagem da premiação. A profundidade nasce de camadas tonais (uma rampa de superfícies do `#0b0c0f` ao `#1e2128` separada por fios de borda), não de sombras empilhadas. Os componentes de ação têm peso e presença física — botões encorpados, hover que responde, gradientes dourados com brilho contido — enquanto os dados permanecem afiados e legíveis. A referência de mira é FACEIT somada ao acabamento de data-viz de Mobalytics/Blitz.

Este sistema rejeita explicitamente: o cinza-azulado de dashboard corporativo com cards idênticos e o template hero-metric; o site de stats poluído e ad-heavy; o cartoon infantil de cores primárias saturadas; e o neon-cripto de roxo com glow, glassmorphism e gradientes gritantes.

**Key Characteristics:**
- Palco quase-preto azulado, ouro reservado para conquista, azul para o sistema.
- Densidade de esports curada: tabelas nítidas, `tabular-nums`, informação sem ruído.
- Profundidade por camadas tonais + hairline, não por sombra.
- Ação tátil e encorpada; dado afiado e sóbrio.
- Legitimidade competitiva acima de decoração.

## 2. Colors

Uma paleta escura ancorada no logo: azul é marca e interação, ouro é rating e prêmio, verde/vermelho são direção (subiu/caiu), e uma rampa de neutros carrega todo o resto.

### Primary
- **Azul Arena** (`#2f9bd6`): a voz interativa do sistema. Links, botão primário, chip/aba ativos, borda de foco (`:focus-within` da busca), seleção atual. É a cor do "isto responde ao seu toque".
- **Azul Farol** (`#4cb6ec`): o realce do azul — hover do primário, placement 2º lugar, texto de destaque sobre superfícies escuras (contraste alto).

### Secondary
- **Ouro Conquista** (`#d9b25f`) e **Ouro Brilho** (`#ecc77a`): rating, tier, topo do ranking, badges de status (Top 1, PRO), moldura de perfil. Aparecem como gradiente `135deg` do brilho ao ouro sobre texto quase-preto (`#2a2008`) para máxima leitura. É a cor mais rara e mais valiosa da tela — seu poder vem da escassez.

### Tertiary
- **Verde Subida** (`#46c084`): delta positivo, streak de vitória, placement bom. Sempre acompanhado de seta/sinal — nunca só a cor.
- **Vermelho Queda** (`#e2574f`): delta negativo, streak de derrota, flag crítica de integridade.
- **Âmbar Alerta** (`#e0a83a`): flag de aviso, estados de atenção.
- **Vermelho Entrar** (`#ec3a34`): reservado ao CTA de login ("Entrar"). Distinto do vermelho semântico de queda; é ação destacada, não erro.

### Neutral
- **Pedra** (`#0b0c0f` bg / `#08090b` bg-deep): o palco. Fundo do corpo e do rodapé/header.
- **Rampa de Superfície** (`#131419` surface → `#181a20` surface-2 → `#1e2128` surface-3): camadas empilhadas que criam profundidade sem sombra. Painel, chip, input, hover de linha sobem um degrau nessa rampa.
- **Fios** (`#262a33` line / `#333845` line-strong): bordas hairline que separam superfícies e desenham tabelas.
- **Tinta** (`#eef0f3` text / `#9aa0aa` text-dim / `#878e9a` text-faint): corpo, secundário e terciário. Os três passam AA sobre toda a rampa de superfície (faint ≥5,3:1 desde a auditoria de 20/07); `text-faint` segue sendo a voz terciária — rótulos, metadados — nunca corpo longo.

### Named Rules
**A Regra do Ouro Escasso.** O ouro nunca é decoração. Ele marca conquista — rating, topo, tier, conquista de perfil — e some do resto da tela. Se aparecer em mais de um punhado de elementos por página, perdeu o significado.

**A Regra do Duplo Sinal.** Direção (subiu/caiu, vitória/derrota) nunca depende só de verde vs. vermelho. Sempre há um segundo sinal — seta, `+`/`−`, ícone — para quem não distingue as cores.

## 3. Typography

**Display Font:** Anton (com fallback sans-serif)
**Body Font:** Plus Jakarta Sans (com system-ui, sans-serif)
**Label/Data Font:** ui-monospace / SF Mono / Menlo para números técnicos

**Character:** Anton é um grotesco condensado pesado — só entra no wordmark/herói, em caixa-alta, como o letreiro do coliseu. Todo o resto do sistema é Plus Jakarta Sans, um sans humanista de eixo largo (200–800) que carrega headings, títulos, rótulos, corpo e dados com uma só voz. O par contrasta no eixo certo: display condensado dramático contra um workhorse aberto e neutro — nunca dois sans parecidos brigando.

### Hierarchy
- **Display** (Anton 400, 58px, lh 1, uppercase): wordmark do herói na Home. Peso de letreiro, `text-shadow` sutil para descolar do fundo. Só aqui.
- **Headline** (Plus Jakarta 700, 20px, lh 1): título de seção (`.section-head h2`). O maior tipo do corpo do produto.
- **Title** (Plus Jakarta 700, ~15px): nomes de jogador, títulos de card, cabeçalhos de bloco.
- **Body** (Plus Jakarta 400–500, 14px, lh 1.6): texto corrido e descrições. Prosa longa fica em 65–75ch; dados e UI compacta podem correr mais densos.
- **Label** (Plus Jakarta 700, 10–11px, tracking 0.06–0.18em, uppercase): eyebrows, cabeçalhos de tabela, badges, rótulos de rodapé. O tracking largo é o que os faz lerem como rótulo, não como corpo.
- **Data** (mono, `tabular-nums`): CR, deltas, percentuais, ids de partida. Números que alinham em coluna e não dançam ao atualizar.

### Named Rules
**A Regra do Número Tabular.** Todo dado numérico que aparece em coluna ou que muda (CR, winrate, delta, contadores) usa `tabular-nums`. Um placar competitivo cujos números pulam de largura não parece confiável.

**A Regra do Anton Único.** Anton só no wordmark. Nunca em rótulo, botão, header de tabela ou corpo — display font em label de UI é ruído.

## 4. Elevation

Profundidade é puramente tonal. Não há vocabulário de sombra: as superfícies se separam subindo degraus na rampa de neutros (`bg` → `surface` → `surface-2` → `surface-3`) e por fios de borda hairline (`--line`). Um painel é "mais alto" que o fundo porque é mais claro e tem contorno, não porque projeta sombra. Isso mantém o palco chapado e sério, coerente com o dark de broadcast, e evita o peso visual empilhado que puxaria a interface para o território de dashboard corporativo.

O token legado `--shadow` (`0 18px 50px rgba(0,0,0,0.45)`) e o `.panel.glow` que o usa devem ser aposentados. A única exceção tolerada é um elemento que genuinamente flutua sobre o conteúdo e precisa se descolar dele — um dropdown/popover em portal ou um toast — que pode receber uma sombra suave e difusa; nunca um card em repouso.

### Named Rules
**A Regra da Camada Tonal.** Elevação = um degrau mais claro na rampa de superfície + um fio de borda. Se você está alcançando `box-shadow` para separar um card do fundo, use tom e borda no lugar.

## 5. Components

Ação é tátil e encorpada — botões e CTAs têm presença física, hover que responde, ouro com brilho contido. Dado é afiado e sóbrio — tabelas, chips e badges ficam nítidos e discretos para a informação liderar.

### Buttons
- **Shape:** cantos discretos (9px, `--r-md`); variante `lg` com padding maior (13px 24px).
- **Primary:** fundo Azul Arena (`#2f9bd6`), texto branco, padding 10px 16px. Hover clareia (`brightness(1.08)`) — resposta física, sem trocar de cor.
- **Gold:** gradiente `135deg` de Ouro Brilho a Ouro sobre texto quase-preto (`#2a2008`), sem borda. Reservado à ação premium/conquista, não ao botão comum.
- **Ghost / Default:** default é `surface-2` com fio `--line`, texto branco; hover sobe para `surface-3` e borda `line-strong`. Ghost é transparente. Ambos para ação secundária.
- **CTA Entrar:** vermelho `#ec3a34`, branco, 800 weight, tracking 0.03em — o único lugar desse vermelho.

### Chips / Tabs
- **Chip:** pílula (`999px`), `surface-2` + fio, texto dim; hover clareia texto e borda. Ativo vira Azul Arena sólido com texto branco (variante `soft` = fundo `primary-dim` com texto `primary-bright`). Filtros de leaderboard/tierlist.
- **Tab:** texto dim sobre linha de base; ativo é branco com sublinhado inferior de 2px em Azul Arena. Sem preenchimento — navegação leve dentro de uma seção.

### Cards / Panels
- **Corner Style:** 12px (`--r-lg`).
- **Background:** `surface` (`#131419`), um degrau acima do palco.
- **Elevation Strategy:** tonal + fio `--line`; sem sombra em repouso (ver Elevação).
- **Border:** hairline `1px solid --line`.
- **Internal Padding:** 20px (`.panel-pad`).

### Inputs / Fields
- **Style:** busca do header — fundo `#141519`, fio `#23252d`, 9px de raio, 44px de altura, ícone Material Symbols em cinza.
- **Focus:** `:focus-within` troca a borda para Azul Arena (`#2f9bd6`). Sem glow.
- **Placeholder:** `var(--text-faint)` (#878e9a) — passa AA (4,5:1+), não o cinza-fantasma padrão.

### Navigation (Header 3 tiers)
- **Estrutura:** três faixas sobre `#0c0c0e` — (1) logo + abas de modo de jogo, (2) busca + ações (perfil dourado, troféu, Entrar), (3) mini-modos + navegação principal.
- **Links de nav:** Plus Jakarta 700, 11px, tracking 0.08em, texto dim; hover branco.
- **Ativo:** texto branco + barra inferior dourada (`#d5a038`) com glow contido (`box-shadow` dourado) — a única assinatura luminosa tolerada, marcando "você está aqui" com o ouro da conquista.

### Signature: Badges de Tier & Placement
O sistema de status é a peça distintiva. Badges de tier (Top1 gradiente ouro, Top10 ouro-dim, Top50 azul-dim, Top100 verde-dim, Top500 neutro), badges de placement 1–8 (p1 ouro, p2–p4 verde, p5+ vermelho), streaks (win verde-dim, loss vermelho-dim) e deltas (up/down/flat) formam um vocabulário consistente de reconhecimento competitivo. Todos: caixa-alta, `700–800` weight, cantos de 5–6px, cor de fundo semântica com texto de alto contraste.

## 6. Do's and Don'ts

### Do:
- **Do** reservar o ouro (`#d9b25f`/`#ecc77a`) para conquista — rating, topo, tier, perfil premiado — e mantê-lo escasso (a Regra do Ouro Escasso).
- **Do** usar `tabular-nums` em todo número que aparece em coluna ou que muda (CR, winrate, delta).
- **Do** criar profundidade com a rampa tonal (`surface` → `surface-2` → `surface-3`) + fio `--line`, não com sombra.
- **Do** reforçar direção com um segundo sinal (seta, `+`/`−`) além de verde/vermelho.
- **Do** dar peso tátil à ação (hover que clareia/responde) e manter os dados afiados e sóbrios.
- **Do** manter o corpo em `text` (`#eef0f3`) ou `text-dim` (`#9aa0aa`) sobre as superfícies escuras; deixar `text-faint` só para rótulos grandes.

### Don't:
- **Don't** deixar a interface parecer dashboard corporativo/SaaS genérico: cinza-azulado, cards idênticos repetidos, o template hero-metric, Inter sem alma.
- **Don't** cair no site de stats poluído e ad-heavy — densidade caótica de widgets brigando por atenção. Densidade sim, curada.
- **Don't** usar estética cartoon/infantil: cores primárias saturadas, bordas fofas, mascotes.
- **Don't** usar neon-cripto: roxo com glow, glassmorphism decorativo, gradientes gritantes, estética web3.
- **Don't** usar texto com gradiente (`background-clip: text`) — cor sólida sempre; ênfase por peso/tamanho.
- **Don't** usar faixa colorida de `border-left`/`border-right` > 1px como acento em card, item de lista ou alerta.
- **Don't** aplicar `box-shadow` em card em repouso; sombra suave só em overlay que genuinamente flutua (dropdown em portal, toast).
- **Don't** usar Anton fora do wordmark, nem depender só de cor para transmitir direção.
