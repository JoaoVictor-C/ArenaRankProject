---
target: a aba /perfil
total_score: 30
p0_count: 0
p1_count: 4
timestamp: 2026-07-20T02-21-32Z
slug: frontend-src-routes-perfil-tsx
---
Method: dual-agent (A: design review · B: detector + browser overlay) · target `/perfil` (rota `frontend/src/routes/Perfil.tsx`), inspecionado ao vivo em `Delegado Bafafa#PRESO` (Top-1 global).

## Design Health Score

| # | Heurística | Nota | Problema-chave |
|---|-----------|-------|-----------|
| 1 | Visibilidade do status | 3 | Skeletons + contagem "X de Y" fortes; Seguir/Compartilhar não dão feedback; load-more falha em silêncio (por design). |
| 2 | Match com o mundo real | 4 | PT-BR fluente em Arena: "PDL · Pontos de Liga", "Top metade", "Col. média", "há 1 d". |
| 3 | Controle e liberdade | 3 | Filtros com "Limpar", linhas expansíveis; sem voltar-ao-topo em listas longas. |
| 4 | Consistência e padrões | 3 | Tokens/cards coesos, mas `tabular-nums` morto (números pulam) e `.btn ghost` serve link real e botão morto. |
| 5 | Prevenção de erro | 3 | StateBlock cobre 404/erro; estados vazios graciosos; pouca superfície destrutiva. |
| 6 | Reconhecimento vs. memória | 3 | Ícones/badges/dots reconhecíveis; derrubado pelo filtro de campeão colapsado. |
| 7 | Flexibilidade e eficiência | 3 | Sort (Jogos/1º%/ΔPDL) + filtros duplos; sem atalhos de teclado; champ-filter quebrado. |
| 8 | Estético e minimalista | 3 | Genuinamente contido; KV do banner duplica o card Desempenho. |
| 9 | Recuperação de erro | 3 | StateBlock com cópia PT amigável; falha silenciosa do load-more é lacuna pequena. |
| 10 | Ajuda e documentação | 2 | Nada explica o que é PDL/CR/tier/"Provisório"; drill-down de modificadores é a única doc inline (e é boa). |
| **Total** | | **30/40** | **Good** (28–35) — base sólida, fixes pontuais. |

## Anti-Patterns Verdict

**Passa no cheiro de craft, falha no "isto está terminado?".** Um usuário fluente em op.gg/Mobalytics/Blitz/FACEIT confia no *visual* em segundos e bate em pontas inacabadas em ~20s de interação. O slop aqui **não é estético, é funcional**.

**LLM assessment:** Todos os DON'T visuais estão **empiricamente limpos** (consultados ao vivo): `box-shadow: none` em todo card em repouso; zero gradient-text por DOM query; zero glassmorphism; sem faixa lateral >1px; sem cinza-SaaS; Anton confinado ao wordmark. "Ouro Escasso" **sustenta** (~3–6 nós de texto dourado numa página densa). Direção majoritariamente Duplo-Sinal (deltas com `+`/`−`, form dots com o número). O que trai é: champ-filter invisível, botões mortos, e todo número sem alinhamento tabular.

**Deterministic scan (detect.mjs):** `Perfil.tsx` isolado = **exit 0, limpo**. Scan do diretório de rotas pegou 1 achado no /perfil: `layout-transition` em `Perfil.css:340` (`transition: height` na barra do histograma) — nit de perf menor. Overlay no navegador: **86 findings**, dos quais confirmam o design review:
- **`low-contrast` ×45** — 40× de `#5e6470 (text-faint) sobre #131419 = 3,1:1`. Confirmação forte e volumosa do P2 de contraste (conteúdo real em text-faint). Também `#fff sobre #2f9bd6 = 3,1:1` ×3.
- **`skipped-heading` ×1** — `<h2> "Histórico"` seguido de `<h4>` do footer sem h3. Confirma que os títulos dos cards da sidebar são `<span>`, não headings.
- **`all-caps-body` ×1**, `layout-transition` ×7 — menores.

**Falsos positivos confirmados** (não corrigir): `ai-color-palette` ×28 ("Cyan neon", "Purple/violet gradient bg", "Cyan gradient bg") = as cores **procedurais dos avatares** de jogador/campeão (c1/c2 gerados, ex. `#832786`) + o azul de marca `#2f9bd6`/`#4cb6ec` — arte, não slop de UI. `dark-glow` (`#d5a038`) e `gpt-thin-border-wide-shadow` = o **glow dourado da aba ativa do header global**, que o DESIGN.md sancionaexplicitamente como "a única assinatura luminosa tolerada" — não é o conteúdo do /perfil. `gradient-text` ×1 = provável gradiente do TierBadge dourado (fundo, texto quase-preto legível), não texto clipado; A mediu 0 clip-text por DOM.

**Visual overlays:** injeção bem-sucedida (live-server porta 8400, parado ao fim). 82 overlays desenhados; console reportou "82 anti-patterns" com seletores por elemento (`b.tnum`, `button.mt-btn`, `span.ch-icon.sm`…). A maioria dos rótulos são os falsos positivos de paleta acima; o sinal real é o bloco de low-contrast.

## Overall Impression

A página tem **disciplina de design-system genuína e verificada** — a marca "premium/legítima/não-slop" está de fato entregue, o que é raro. A transparência de modificadores por partida (expandir → grid "Colocação +7,9 · Sequência +23,3 · Penalidade de grupo −11,8") é a coisa mais diferenciadora da categoria: o op.gg nunca explica por que seu rating mudou; aqui você audita. Mas três defeitos funcionais a fazem ler como "protótipo, não produto" para um veterano: **filtro de campeão invisível, `tabular-nums` globalmente morto, e botões Seguir/Compartilhar mortos.** A maior oportunidade única: consertar essas três + o contraste do conteúdo (`text-faint` → `text-dim`) leva a página de "bonita mas inacabada" para "confiável".

## What's Working

1. **Transparência de modificadores por partida** (`HistRow` expand → `.mod-grid`). A tese de legitimidade ("mostramos nossa conta") virou literal e auditável, atrás de progressive disclosure, cada valor com número sinalizado. É o maior diferencial de categoria da tela.
2. **Disciplina de design-system real, não aspiracional.** Confirmado ao vivo: zero box-shadow em card em repouso, zero gradient-text, zero glass, elevação só tonal, ouro em ~3–6 nós de conquista.
3. **Linguagem colocação→cor coerente.** Form dots, badges de placement, tint de linha (`.hist-row.first/.top/.low`) e barras do histograma compartilham uma escala; cada elemento colorido carrega um número. Um modelo mental honesto, aprendido uma vez.

## Priority Issues

**[P1] Filtro de campeão renderiza como slivers invisíveis de 2px.**
- **Por quê importa:** filtrar por campeão é table-stakes (paridade op.gg); nasce morto e lê como "build quebrado".
- **Causa (confirmada):** `.ch-icon` em `base.css:193` não declara `display`; dentro do botão `.cf-icon` fica `inline` (mede 2×20px, botão 10×8px) e ignora `width/height:28px`. Só é dimensionado quando um pai grid/flex o blockifica (por isso `.champ-list` funciona e o filtro não).
- **Fix:** `.ch-icon { display: inline-block }` em base.css, ou `.cf-icon .ch-icon { display:block }`.
- **Comando:** `/impeccable harden` → `/impeccable polish`.

**[P1] Contraste: `--text-faint` (#5e6470, 3,1:1) em conteúdo real.**
- **Por quê importa:** metadados de partida "Arena 3v3 · 24 min 48 s" (11px), data (11px), handle `#PRESO` (14px), label da forma — todos **3,1:1**, falham WCAG AA (4,5:1). O detector confirmou **40 instâncias**. "Densidade com autoridade" exige que o dado seja legível.
- **Fix:** promover conteúdo para `--text-dim` (#9aa0aa, medido 6,99:1); reservar `--text-faint` a texto decorativo; subir texto de controles interativos para ≥4,5:1.
- **Comando:** `/impeccable colorize` (contraste) / `/impeccable audit`.

**[P1] `tabular-nums` globalmente derrotado; todo número treme.**
- **Por quê importa:** transições de CR (`730 → 770`), deltas, ranks e contadores renderizam com figuras proporcionais → dígitos não alinham, colunas tremem no load-more. Viola a "Regra do Número Tabular" do DESIGN.md — nos números que **são** o produto.
- **Causa (confirmada):** `.tnum` (`base.css:697`) seta tabular-nums, mas cada elemento usa o **shorthand `font:`**, que reseta `font-variant-numeric` para normal na mesma especificidade. A classe é aplicada religiosamente no TSX mas está morta (computa `normal`).
- **Fix:** adicionar `font-variant-numeric: tabular-nums` *depois* de cada `font:` shorthand, ou parar de usar shorthand nas regras numéricas.
- **Comando:** `/impeccable typeset`.

**[P1] Botões Seguir/Compartilhar mortos; sem estado de perfil-próprio.**
- **Por quê importa:** false affordances no topo da página quebram confiança nos primeiros 5s e minam o posicionamento "hub social" prometendo um grafo social inexistente. Todo perfil é idêntico, seja o seu ou não (sem "este é você"/editar).
- **Fix:** ligar os botões, OU marcá-los desabilitados/"em breve" (o header já faz isso honestamente com "Ache seu Duo"), OU escondê-los até existir. Adicionar branch de perfil-próprio.
- **Comando:** `/impeccable clarify` (estado honesto) / `/impeccable harden`.

**[P2] Alvos de toque sub-24px.**
- **Por quê importa:** mini-tabs segmentados (`.mt-btn`: Jogos/1º%/ΔPDL, Duplas/Rivais) medem **46×20px** (falham WCAG 2.5.8, 24px); alvos do champ-filter 10×8 (agravado pelo P1). Ruim no mobile BR (touch).
- **Fix:** `min-height: 28–32px` + área de hit com padding em `.mt-btn` e `.cf-icon`.
- **Comando:** `/impeccable layout` / `/impeccable polish`.

## Persona Red Flags

- **Alex (power user, ex-FACEIT/op.gg):** champ-filter morto — a primeira feature que ele busca; números não alinham em coluna (tabular-nums quebrado) — ele lê ΔPDL na vertical e nota na hora; "Seguir" não faz nada — tenta uma vez, nunca mais.
- **Sam (acessibilidade):** metadados/datas a **3,1:1** ilegíveis (baixa visão); mini-tabs de **20px** falham alvo motor; títulos de card são `<span>`, não headings (outline só H1→H2→H4 footer) → navegação por leitor de tela impossível; **dots de modificador colapsados** (`.hm-dot.up/.down`) codificam +/− só por **cor** — o valor sinalizado vive só no `title` → **violação de Duplo Sinal** para daltônico/touch; botões do champ-filter (10×8) impossíveis de acertar.
- **"Rodrigo" (BR mobile-first, Android médio, dados móveis):** a ≤720px a linha de partida **esconde `.hr-mods` e `.hr-when`** — ele perde os dots de modificador (o gancho de transparência central do produto) e o timestamp a menos que expanda cada linha; champ-filter quebrado é pior no touch; cada partida carrega imagem ddragon de 128px de CDN externo — perceptível em dados metrados.

## Minor Observations

- `TrendCard` diz **"PDL — 30 dias"** mas o `Delta` ao lado usa **`data.delta7d`** — card de 30 dias exibindo delta de 7 dias. Label/dado divergem.
- KV do banner **duplica** os três números do card Desempenho (1º lugar %, Top metade, Col. média) — candidato a `/impeccable distill` (banner = identidade/rank/trajetória; card = distribuição).
- `.hist-row.first` usa tint de fundo dourado a 5% — borda macia da "Ouro Escasso" (ouro como fundo de linha, não número de conquista), embora fraco o bastante para provavelmente passar.
- Stats de KV renderizam para amostras minúsculas sem ressalva "poucos jogos" → jogador de 3 partidas vê % potencialmente selvagens com autoridade total.
- `.perf-dist` usa `role="img"` com label genérico; contagens por barra vivem só em `title` → valores não expostos a leitor de tela.
- `signed()` usa o menos real U+2212 ("−64") — detalhe tipográfico bom, minado pelo tabular-nums quebrado.
- `layout-transition` ×7 (`.pd-bar` anima `height`) — nit de perf; preferir transform/scaleY.

## Questions to Consider

1. Se a tese de legitimidade é "mostramos nossa conta", por que o breakdown de modificadores fica atrás de um clique por linha *e* some inteiro no mobile? O maior modificador não deveria ser um chip sempre visível com seu valor sinalizado?
2. Botões Seguir/Compartilhar mortos danificam a alegação "hub social do Arena" *mais* do que simplesmente omiti-los até o grafo social existir?
3. Um perfil **Top-1** deveria ser mais cerimonial que o rank #4295? O tratamento do banner é idêntico independente da posição — falta um momento de reverência reservado ao topo da ladder?
4. O banner apresenta **7 números** antes do histórico que você chama de "a estrela". O KV grid está merecendo o lugar, ou é memória muscular de op.gg?
