# Brief de movimento — cluster de campeões (`/winrate` · `/campeao` · `/augments` · `/sinergias`)

**Modo:** Operate — o visitante vem cumprir uma tarefa (comparar campeões, escolher build, achar dupla).
**Decisão vigente (Clesio, 25/07/2026):** todo movimento de `/winrate`,
`/campeao/:id`, `/campeao/:id/otps`, `/augments` e `/sinergias` pertence ao
GSAP, inclusive animações CSS/legadas e as animações discutidas anteriormente.
Essa decisão substitui as limitações criativas deste brief quando houver
conflito.
**Data:** 24/07/2026 · **Status:** substituído, em migração.

> Contrato aprovado e atual:
> `docs/superpowers/specs/2026-07-25-gsap-cluster-motion-migration-design.md`.
> O restante deste arquivo preserva o histórico da primeira implementação e
> serve apenas como evidência técnica.

---

## 1. A régua

> **Nada se move sem justificar.** Em tela de Operate, movimento é explicação — mostra de onde um número veio, para onde uma linha foi, o que mudou depois do clique. Movimento que só enfeita rouba milissegundos de quem veio ler um dado.

Três testes que toda animação daqui precisa passar:

1. **Explica ou some.** Se remover a animação não tira informação nenhuma, ela era decoração. Corta.
2. **Não atrasa a tarefa.** Ninguém espera animação para ler um winrate. Entrada e transição terminam antes de a pessoa terminar de olhar — nunca o contrário.
3. **Sobrevive à repetição.** Este é um site de consulta recorrente. Uma animação encantadora na primeira visita e irritante na décima é uma animação errada.

O PRODUCT.md rejeita "cripto/neon" e "stats poluído". A tentação com GSAP na mão é justamente essa. **A ferramenta é potente; a régua é curta.**

---

## 2. Sistema de movimento (tokens)

Um vocabulário fechado. Fora dele, nada.

| Token | Duração | Easing | Uso |
|---|---|---|---|
| `--mo-micro` | 120 ms | `power2.out` | hover, foco, feedback de clique |
| `--mo-ui` | 220 ms | `power2.out` | troca de aba, chip, abertura de painel |
| `--mo-enter` | 420 ms | `power3.out` | entrada de bloco (reveal) |
| `--mo-data` | 700 ms | `power2.inOut` | contador, curva desenhando, barra |
| `--mo-flip` | 380 ms | `power2.inOut` | reordenação/filtro de lista (Flip) |

**Stagger padrão:** 60 ms entre irmãos, teto de 8 itens (o 9º em diante entra junto — escalonar 40 cards vira espera).
**Distância de entrada:** 16 px (o mock usava 28 px; em Operate isso lê como salto). Nunca escala/rotação na entrada.
**Só `transform` e `opacity`.** Qualquer animação de `width`/`height`/`top`/`filter` precisa de justificativa explícita — são as que fazem *layout/paint* e derrubam o frame no mobile.

---

## 3. Arquitetura: GSAP e o motor existente não podem coexistir no mesmo elemento

O `lib/animEngine.ts` já roda em todas as rotas e **ele mesmo** aplica `opacity: 0` + reveal por IntersectionObserver, além de count-up, draw de SVG, barras e tilt. Se o GSAP animar os mesmos nós, os dois disputam `opacity`/`transform` e o resultado é flicker ou elemento preso invisível.

**Regra de transição:**

- O GSAP assume **exclusivamente** as superfícies do cluster (`.wr-*`, `.cmp-*`, `.tl-*`).
- Essas superfícies saem da constante `REVEAL` do `animEngine` **no mesmo commit** que o GSAP entra nelas. Hoje elas foram adicionadas lá como ganho imediato — é ponte, não destino.
- O `animEngine` fica intocado nas rotas antigas (home, leaderboard, perfil, campeonatos). **Não migrar 8 rotas estáveis para ganhar consistência interna** — o custo de regressão não paga.
- Um único ponto de entrada novo (`lib/motion.ts`) registra plugins, lê `prefers-reduced-motion` e expõe os helpers. Nenhum componente importa `gsap` direto.

**Custo aceito:** ~40–70 KB gzip. Carregar GSAP **só nas rotas do cluster** (import dinâmico dentro de `motion.ts`, as rotas já são lazy) para a home e o leaderboard não pagarem por ele.

> Verificar a licença do GSAP antes de instalar. Os plugins mudaram de modelo de licenciamento recentemente e não confirmei os termos atuais aqui — é uma checagem de 2 minutos que evita uma dor jurídica.

---

## 4. O que anima, superfície por superfície

### 4.1 Entrada da página (todas)

- Blocos entram com `y: 16 → 0`, `opacity: 0 → 1`, `--mo-enter`, stagger 60 ms, disparo por ScrollTrigger (`start: "top 88%"`, `once: true`).
- **O primeiro viewport não espera scroll** — o que já está visível entra imediatamente no mount. (O motor atual acertou isso; manter.)
- **A tabela do `/winrate` e as bandas de tierlist entram como bloco único, não linha a linha.** 30 linhas escalonadas é uma tela que demora a assentar.

### 4.2 Dados que se desenham

- **Contadores** — hero do `/campeao` (4 KPIs), números do rail, `sampleSize` dos rodapés. `--mo-data`, respeitando o formato pt-BR (vírgula decimal, ponto de milhar). Dispara uma vez, ao entrar.
- **Curvas** (power spike, tendência, volume) — `stroke-dashoffset` do path de linha, e a área com `opacity` atrás dela. `--mo-data`. O **marcador de pico entra depois da curva terminar** — é o clímax do gráfico, não pode chegar junto.
- **Selos de tier** nas bandas: sem animação de entrada própria além do bloco. O tier é identidade, não evento.

### 4.3 Mudança de estado — onde o Flip se paga

Este é o único caso que CSS não resolve bem, e é o que mais falta hoje.

- **Ordenar a tabela do `/winrate`**: cada linha viaja da posição antiga para a nova (`--mo-flip`). O jogador *vê* seu campeão subir em vez de a tabela piscar. É o momento mais próximo de "assinatura" que este brief permite — e ele é funcional.
- **Filtrar chips de classe / busca**: itens que saem fazem fade+scale sutil; os que ficam deslizam para a nova posição.
- **Tierlists** (`/augments`, `/sinergias`): filtro reordena cards dentro das bandas com o mesmo Flip.
- **Abas Matchups ↔ Sinergia**: crossfade de 220 ms com altura travada durante a troca, para o conteúdo abaixo não pular.
- **Trio ↔ Dupla** em `/sinergias`: mesma regra.

### 4.4 Micro-interações

- Tiles de matchup e cards de comp: `y: -3` + borda clareando, `--mo-micro`.
- Faces de campeão e tiles de augment: `scale: 1.05` + brilho leve.
- Selo de tier no hover do card: **não pulsar.** Brilho pulsante é exatamente a assinatura "cripto/neon" que o produto rejeita.
- **Foco de teclado tem o mesmo tratamento visual do hover.** Hoje só o mouse ganha feedback.

---

## 5. Acessibilidade e performance (não negociável)

- **`prefers-reduced-motion: reduce`** → sem entrada, sem Flip, sem draw de curva. O conteúdo aparece no estado final, instantâneo. Contadores mostram o valor direto. O PRODUCT.md levanta isso explicitamente por causa do vídeo de fundo e dos reveals — vale aqui também.
- **Nada fica preso invisível.** Se o JS falhar ou o observer não disparar, o conteúdo precisa estar legível. O motor atual usa um timeout de segurança de 3 s; o novo sistema mantém a mesma garantia.
- **Sem animação durante a carga de dados.** Skeleton não pulsa em paralelo com reveal — escolhe um.
- Alvo: **60 fps no mobile**. Flip em lista longa é o risco real; limitar a reordenação animada aos itens visíveis.

---

## 6. Fora de escopo (decidido, não esquecido)

- Transição entre páginas (page transitions) — atrasa navegação em site de consulta.
- Parallax no hero do campeão e splash animada — foi a opção "assinatura marcante", descartada.
- ScrollSmooth / scroll sequestrado — hostil em tela de dados.
- SplitText em títulos — flourish de landing, errado em Operate.
- Migrar as rotas antigas para GSAP.

---

## 7. Fatias de implementação

| # | Fatia | Entrega | Depende de |
|---|---|---|---|
| 0 | ~~ponte~~ | revertida — as classes saíram do `REVEAL` quando o GSAP assumiu | — |
| 1 | ✅ `lib/motion.ts` | gsap 3.15.0 + ScrollTrigger + Flip, import dinâmico, guardas, tokens | — |
| 2 | ✅ Entrada + contadores | reveal e count-up nas 4 superfícies | 1 |
| 3 | ✅ Curvas desenhando | draw dos charts + área + marcador de pico depois da curva | 1 |
| 4 | ✅ Flip | ordenação da tabela do `/winrate`, filtro das tierlists | 1 |
| 5 | ✅ Micro-interações + foco | hover unificado, paridade de teclado e fallback para movimento reduzido | 1 |

**Custo medido:** o bundle principal **não cresceu** (235,34 kB vs 235,25 kB). O GSAP virou chunk próprio de 70,8 kB / **27,9 kB gzip**, carregado só nas rotas do cluster.

### Regra nova, descoberta na implementação: aba oculta

`document.visibilityState === "hidden"` pausa o `requestAnimationFrame`. Aplicar o estado inicial (`opacity: 0`) ali e nada avançar deixa a página **invisível** para quem abriu em segundo plano (ctrl+click, preload) — exatamente o modo de falha que a §5 proíbe. Foi observado na prática: 13 de 14 blocos ficaram em `opacity: 0`.

**`shouldSkipEntrance()` guarda as três entradas** (reveal, draw de curva, Flip): aba oculta entrega o estado final, sem animar. Ninguém está olhando de qualquer forma.

---

## 8. Como saber se deu certo

- A página não parece estática na primeira impressão **e** não atrasa a segunda visita.
- Ordenar a tabela fica legível: dá para seguir uma linha específica com os olhos.
- Com `reduced-motion` ligado, tudo continua utilizável e nada pisca.
- Nenhum bloco fica invisível se o JS falhar.
- O bundle da home e do leaderboard **não** cresce.
