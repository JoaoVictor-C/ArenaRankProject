import "./Sistema.css";
import { Link } from "react-router-dom";
import { Mi } from "../components";

/* ============================================================
   Sistema CR — "Como funciona o Casual Rating"
   Página de conteúdo estático. Rota: /sistema
   Seções: hero · como o CR funciona · modificadores ·
           integridade · pipeline · arquitetura · CTA
   ============================================================ */
export function Sistema() {
  return (
    <div className="shell">
      {/* ---- HERO ---- */}
      <section className="doc-hero">
        <div className="doc">
          <span className="eyebrow">ArenaRank · Transparência total</span>
          <h1>
            Como funciona o <span className="cr">Casual Rating</span>
          </h1>
          <p>
            Um sistema de rating competitivo, justo e à prova de abuso para os
            modos casuais de League of Legends — começando pelo Arena. Cada
            mudança no seu CR é explicável, rastreável e auditável.
          </p>
          <div className="hero-metrics">
            <div className="hmetric">
              <b className="tnum">250k+</b>
              <span>jogadores registrados (meta ano 1)</span>
            </div>
            <div className="hmetric">
              <b className="tnum">5M+</b>
              <span>partidas processadas</span>
            </div>
            <div className="hmetric">
              <b className="tnum">99,5%</b>
              <span>SLA de uptime da API</span>
            </div>
            <div className="hmetric">
              <b className="tnum">&lt; 5 min</b>
              <span>latência do Top 1000</span>
            </div>
          </div>
        </div>
      </section>

      {/* ---- COMO O CR FUNCIONA ---- */}
      <section className="doc-sec first">
        <div className="doc">
          <div className="sec-head">
            <span className="eyebrow">O cálculo</span>
            <h2>Como o seu CR é calculado</h2>
            <p>
              O CR (Casual Rating) mede a sua habilidade real no Arena — com
              base em como você se sai contra os outros, não em quantas partidas
              você joga.
            </p>
          </div>
          <div className="formula-grid">
            <div className="fcard">
              <h3>Habilidade, não volume</h3>
              <p>
                Seu CR sobe quando você supera o resultado esperado para o seu
                nível. Vencer partidas difíceis vale mais do que acumular jogos
                fáceis.
              </p>
              <div className="ffact">
                <b>Justo</b> recompensa desempenho real
              </div>
            </div>
            <div className="fcard">
              <h3>Reinício suave entre temporadas</h3>
              <p>
                No começo de cada temporada o seu CR se aproxima parcialmente do
                ponto médio — você recomeça com vantagem, sem zerar todo o
                progresso.
              </p>
              <div className="ffact">
                <b>Mantém</b> parte do seu histórico
              </div>
            </div>
            <div className="fcard">
              <h3>Partidas de colocação</h3>
              <p>
                Suas 10 primeiras partidas definem o seu ponto de partida e
                valem mais. Durante essa fase você exibe um selo provisório até
                o CR estabilizar.
              </p>
              <div className="ffact">
                <b>10</b> partidas iniciais
              </div>
            </div>
            <div className="fcard">
              <h3>Topo sem teto fixo</h3>
              <p>
                Quanto mais alto o seu CR, mais difícil fica ganhar cada ponto —
                recompensando consistência no topo, sem um limite rígido.
              </p>
              <div className="ffact">
                <b>∞</b> espaço para crescer
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---- MODIFICADORES ---- */}
      <section className="doc-sec">
        <div className="doc">
          <div className="sec-head">
            <span className="eyebrow">Por partida</span>
            <h2>Modificadores aplicados</h2>
            <p>
              Cada partida passa por uma cadeia determinística de modificadores.
              Todos eles aparecem no detalhamento da sua partida — nada é
              oculto.
            </p>
          </div>
          <div className="mod-cards">
            <div className="modc">
              <div className="ic">
                <Mi name="schedule" />
              </div>
              <h4>Colocação esperada</h4>
              <p>
                Modelo prevê sua colocação dado o CR de todas as equipes.
                Superar a expectativa rende mais CR.
              </p>
            </div>
            <div className="modc">
              <div className="ic">
                <Mi name="leaderboard" />
              </div>
              <h4>Peso por colocação</h4>
              <p>
                Multiplicadores específicos para Duos (8 equipes) e Trios (6
                equipes) no cálculo final.
              </p>
            </div>
            <div className="modc">
              <div className="ic">
                <Mi name="group" />
              </div>
              <h4>Bônus de dupla</h4>
              <p>
                Ajuste para duplas que jogam juntas, equilibrando a vantagem de
                coordenação.
              </p>
            </div>
            <div className="modc">
              <div className="ic">
                <Mi name="bolt" />
              </div>
              <h4>Amortecedor de sequência</h4>
              <p>
                Piso de proteção em derrotas (0,25×) e teto de bônus em
                vitórias (1,35×).
              </p>
            </div>
            <div className="modc">
              <div className="ic">
                <Mi name="shield" />
              </div>
              <h4>Proteção AFK</h4>
              <p>
                Jogadores inelegíveis (AFK) geram resultado nulo — sem
                movimento de rating para ninguém.
              </p>
            </div>
            <div className="modc">
              <div className="ic">
                <Mi name="equalizer" />
              </div>
              <h4>Controle de dispersão</h4>
              <p>
                Limita o ganho máximo por partida, evitando que um único jogador
                distorça o leaderboard.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ---- INTEGRIDADE ---- */}
      <section className="doc-sec">
        <div className="doc">
          <div className="sec-head">
            <span className="eyebrow">Anti-abuso multicamadas</span>
            <h2>Sistema de integridade</h2>
            <p>
              Cada partida é avaliada automaticamente contra padrões de abuso. O
              sistema nunca pune sozinho — casos sinalizados passam por revisão
              humana.
            </p>
          </div>
          <div className="integ-list">
            <div className="integ-item">
              <div className="ico">
                <Mi name="balance" />
              </div>
              <div>
                <h4>Detecção de boosting</h4>
                <p>
                  Identifica duplas em que a diferença de habilidade indica
                  carregamento, aplicando penalidades graduais.
                </p>
              </div>
              <span className="flag warn flag-col">
                <span className="dot" />
                WARN
              </span>
            </div>
            <div className="integ-item">
              <div className="ico">
                <Mi name="shield" />
              </div>
              <div>
                <h4>Proteção AFK / inelegível</h4>
                <p>
                  Jogadores inativos são marcados como inelegíveis — a partida
                  não afeta o rating de ninguém.
                </p>
              </div>
              <span className="flag info flag-col">
                <span className="dot" />
                INFO
              </span>
            </div>
            <div className="integ-item">
              <div className="ico">
                <Mi name="replay" />
              </div>
              <div>
                <h4>Repetição de lobby</h4>
                <p>
                  Mesma composição aparecendo 3+ vezes em 24h é sinalizada como
                  possível combinação de resultado (match-fixing).
                </p>
              </div>
              <span className="flag critical flag-col">
                <span className="dot" />
                CRITICAL
              </span>
            </div>
            <div className="integ-item">
              <div className="ico">
                <Mi name="timer" />
              </div>
              <div>
                <h4>Duração atípica</h4>
                <p>
                  Detecção de outliers estatísticos no tempo de partida,
                  identificando partidas anormalmente curtas ou longas.
                </p>
              </div>
              <span className="flag warn flag-col">
                <span className="dot" />
                WARN
              </span>
            </div>
            <div className="integ-item">
              <div className="ico">
                <Mi name="equalizer" />
              </div>
              <div>
                <h4>Controle de dispersão máxima</h4>
                <p>
                  Impede que um único jogador distorça o leaderboard limitando o
                  ganho de rating por partida.
                </p>
              </div>
              <span className="flag info flag-col">
                <span className="dot" />
                INFO
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* ---- PIPELINE ---- */}
      <section className="doc-sec">
        <div className="doc">
          <div className="sec-head">
            <span className="eyebrow">Bastidores</span>
            <h2>O caminho de cada partida</h2>
            <p>
              Da partida finalizada à atualização do ranking — tudo acontece
              automaticamente, em segundos, e sempre da mesma forma.
            </p>
          </div>
          <div className="pipe">
            <div className="pstep">
              <div className="num-wrap">
                <div className="num">1</div>
                <div className="line" />
              </div>
              <div className="body">
                <h4>Coleta</h4>
                <p>
                  Assim que uma partida de Arena termina, ela é captada
                  automaticamente — sem precisar de nenhuma ação sua.
                </p>
              </div>
            </div>
            <div className="pstep">
              <div className="num-wrap">
                <div className="num">2</div>
                <div className="line" />
              </div>
              <div className="body">
                <h4>Fila inteligente</h4>
                <p>
                  Partidas dos jogadores do Top 1000 entram numa fila
                  prioritária, garantindo atualização quase imediata no ranking.
                </p>
              </div>
            </div>
            <div className="pstep">
              <div className="num-wrap">
                <div className="num">3</div>
                <div className="line" />
              </div>
              <div className="body">
                <h4>Verificação</h4>
                <p>
                  A partida é checada contra abusos (boosting, AFK, lobbies
                  repetidos) antes de qualquer cálculo.
                </p>
              </div>
            </div>
            <div className="pstep">
              <div className="num-wrap">
                <div className="num">4</div>
                <div className="line" />
              </div>
              <div className="body">
                <h4>Cálculo do CR</h4>
                <p>
                  Comparamos o resultado de cada jogador ao esperado e ajustamos
                  para duplas e sequências — definindo quanto de CR cada um
                  ganha ou perde.
                </p>
              </div>
            </div>
            <div className="pstep">
              <div className="num-wrap">
                <div className="num">5</div>
                <div className="line" />
              </div>
              <div className="body">
                <h4>Registro</h4>
                <p>
                  O novo CR, o histórico da partida e as estatísticas de
                  campeão são salvos de forma segura e auditável.
                </p>
              </div>
            </div>
            <div className="pstep">
              <div className="num-wrap">
                <div className="num">6</div>
                <div className="line" />
              </div>
              <div className="body">
                <h4>Atualização</h4>
                <p>
                  Seu perfil e o leaderboard refletem o resultado em poucos
                  segundos.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---- ARQUITETURA ---- */}
      <section className="doc-sec">
        <div className="doc">
          <div className="sec-head">
            <span className="eyebrow">Engenharia</span>
            <h2>Arquitetura</h2>
            <p>
              Microsserviços em containers sobre Kubernetes gerenciado.
              Comunicação assíncrona via filas para processamento; REST para
              consultas e leaderboard.
            </p>
          </div>
          <div className="arch-layers">
            <div className="alayer">
              <div className="ln">Cliente</div>
              <div className="lc">
                <span className="tech">React + Vite · TypeScript</span>
                <span className="tech">PWA Mobile</span>
                <span className="tech">API REST Pública</span>
              </div>
            </div>
            <div className="alayer">
              <div className="ln">Gateway</div>
              <div className="lc">
                <span className="tech">Roteamento</span>
                <span className="tech">Autenticação · Rate limit</span>
                <span className="tech">TLS 1.3</span>
              </div>
            </div>
            <div className="alayer">
              <div className="ln">Serviços</div>
              <div className="lc">
                <span className="tech">Cálculo de CR</span>
                <span className="tech">Estatísticas</span>
                <span className="tech">Integridade</span>
                <span className="tech">Temporadas</span>
              </div>
            </div>
            <div className="alayer">
              <div className="ln">Processamento</div>
              <div className="lc">
                <span className="tech">Ingestão de partidas</span>
                <span className="tech">Processador de partidas</span>
                <span className="tech">Anti-boosting</span>
                <span className="tech">Aquecimento de cache</span>
              </div>
            </div>
            <div className="alayer">
              <div className="ln">Dados</div>
              <div className="lc">
                <span className="tech">PostgreSQL 16 + réplicas</span>
                <span className="tech">TimescaleDB</span>
                <span className="tech">Redis 7 · Streams + cache</span>
                <span className="tech">S3 / R2</span>
              </div>
            </div>
            <div className="alayer">
              <div className="ln">Infra</div>
              <div className="lc">
                <span className="tech">Docker + Kubernetes · EKS</span>
                <span className="tech">KEDA autoscaling</span>
                <span className="tech">GitHub Actions + ArgoCD</span>
                <span className="tech">Grafana · Prometheus · Loki</span>
                <span className="tech">Cloudflare CDN</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---- CTA ---- */}
      <section className="doc-sec" style={{ borderBottom: "none" }}>
        <div className="doc cta-band">
          <h2>Justo. Transparente. Auditável.</h2>
          <p>
            Busque seu Riot ID e veja seu Casual Rating, histórico e
            estatísticas — com cada modificador explicado.
          </p>
          <div className="cta-row">
            <Link to="/perfil" className="btn primary btn-lg">
              Ver meu perfil
            </Link>
            <Link to="/leaderboard" className="btn btn-lg">
              Explorar o leaderboard
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
