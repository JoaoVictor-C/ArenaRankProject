import "./Duo.css";

const ROOMS = [
  { nm: "Zaza", tag: "#1101", cr: 5018, c1: "#9b3fc7", c2: "#ff7af0", type: "open", slots: 2, filled: 1, msg: "Bora ranked 3v3, tenho mic" },
  { nm: "Luajhin", tag: "#BR1", cr: 4776, c1: "#8a1f1f", c2: "#ff6a3b", type: "approval", slots: 3, filled: 2, msg: "Duos chill, sem rage" },
  { nm: "wel", tag: "#kat", cr: 4402, c1: "#48bdff", c2: "#1846a0", type: "open", slots: 2, filled: 1, msg: "Procuro sup agressivo" },
  { nm: "muichiro", tag: "#isy", cr: 4295, c1: "#2a2a36", c2: "#7a7a8e", type: "open", slots: 3, filled: 1, msg: "Arena casual, qualquer rank" },
  { nm: "KatEvain", tag: "#BR1", cr: 3890, c1: "#ff32d9", c2: "#c084ff", type: "approval", slots: 2, filled: 1, msg: "Só players Gold+" },
  { nm: "NexusKing", tag: "#2077", cr: 3654, c1: "#5a8a3a", c2: "#a0d96b", type: "open", slots: 3, filled: 2, msg: "Treino de comp, voice obrigatório" },
];

export function Duo() {
  return (
    <div className="shell">
      <div className="duo-top">
        <div className="duo-title">
          <h1>Ache seu Duo</h1>
          <p className="sub">
            Encontre parceiros para Arena com base no seu rank, estilo de jogo e disponibilidade. Crie uma sala ou entre em uma existente.
          </p>
        </div>
        <div className="duo-online">
          <span className="pulse-dot" />
          <span><b>2.847</b> jogadores online</span>
        </div>
      </div>

      <div className="duo-layout">
        <div className="duo-main">
          <div className="duo-card glow">
            <div className="duo-hero">
              <div>
                <div className="dh-you">
                  <span className="pavatar" style={{ width: 58, height: 58, "--c1": "#23415f", "--c2": "#46b4ec" } as React.CSSProperties} />
                  <div className="dh-id">
                    <div className="nm">Frederic Boulos <span className="tag">#BR1</span></div>
                    <div className="row">
                      <span className="dh-cr">5.241 <span className="u">CR</span></span>
                      <span className="badge tier-top1">TOP 1</span>
                    </div>
                  </div>
                </div>
                <p className="dh-copy">Busque um parceiro compatível com seu nível ou crie uma sala e espere alguém entrar.</p>
                <div className="dh-actions">
                  <button className="btn primary lg" type="button">
                    <span className="mi">group_add</span> Buscar Duo
                  </button>
                  <button className="btn lg" type="button">
                    <span className="mi">add</span> Criar Sala
                  </button>
                </div>
              </div>
              <div className="dh-right">
                <div className="dh-stats">
                  <div className="dh-stat"><b>847</b><span>Duos formados</span></div>
                  <div className="dh-stat"><b>73%</b><span>Taxa de match</span></div>
                  <div className="dh-stat"><b>2m38s</b><span>Tempo médio</span></div>
                  <div className="dh-stat"><b>4.8★</b><span>Sua avaliação</span></div>
                </div>
              </div>
            </div>
          </div>

          <div className="duo-card">
            <div className="mr-head">
              <span className="mr-ttl">SUA SALA</span>
              <span className="mr-state"><span className="pulse-dot" /> Buscando</span>
              <span className="spacer" />
            </div>
            <div className="mr-body">
              <div className="slots">
                <div className="slot you host-slot">
                  <span className="sl-tag host">HOST</span>
                  <span className="pavatar" style={{ width: 50, height: 50, "--c1": "#23415f", "--c2": "#46b4ec" } as React.CSSProperties} />
                  <span className="sl-nm">Frederic Boulos</span>
                  <span className="sl-cr">5.241 CR</span>
                </div>
                <div className="slot empty">
                  <div className="ph"><span className="mi">person_add</span></div>
                  <span className="wlabel">Aguardando...</span>
                  <span className="wdots"><i /><i /><i /></span>
                </div>
                <div className="slot empty">
                  <div className="ph"><span className="mi">person_add</span></div>
                  <span className="wlabel">Aguardando...</span>
                  <span className="wdots"><i /><i /><i /></span>
                </div>
              </div>
              <div className="mr-meta">
                <span className="badge neutral">3v3</span>
                <span className="badge neutral">Qualquer rank</span>
                <span className="badge neutral">PT-BR</span>
              </div>
            </div>
          </div>

          <div className="duo-section-head">
            <h2>Salas disponíveis <span className="cnt">({ROOMS.length})</span></h2>
          </div>
          <div className="duo-rooms">
            {ROOMS.map((r, i) => (
              <div className="room-card" data-type={r.type} key={i}>
                <div className="rc-head">
                  <span className="pavatar" style={{ width: 42, height: 42, "--c1": r.c1, "--c2": r.c2 } as React.CSSProperties} />
                  <div className="rc-host">
                    <div className="nm">{r.nm}</div>
                    <div className="meta">
                      <span className="cr">{r.cr.toLocaleString("pt-BR")} CR</span>
                      <span>{r.tag}</span>
                    </div>
                  </div>
                  <span className="rc-type">
                    <span className={`badge ${r.type === "open" ? "room-open" : "room-appr"}`}>
                      {r.type === "open" ? "Aberta" : "Aprovação"}
                    </span>
                  </span>
                </div>
                <div className="rc-slots">
                  {Array.from({ length: r.filled }).map((_, j) => (
                    <span key={j} className="mini-slot pavatar" style={{ "--c1": "#3a3f4a", "--c2": "#5e6470" } as React.CSSProperties} />
                  ))}
                  {Array.from({ length: r.slots - r.filled }).map((_, j) => (
                    <span key={`e${j}`} className="mini-slot empty"><span className="mi">add</span></span>
                  ))}
                  <span className="rc-count">{r.filled}/{r.slots}</span>
                </div>
                <div className="mr-msg">{r.msg}</div>
              </div>
            ))}
          </div>
        </div>

        <aside className="duo-sidebar">
          <div className="panel panel-pad">
            <div className="eyebrow" style={{ marginBottom: 14 }}>FILTROS</div>
            <div className="duo-filters-group">
              <label className="tweaks-label">Faixa de CR</label>
              <div className="chips" style={{ marginTop: 8 }}>
                <span className="chip" data-active="true">Todos</span>
                <span className="chip">±500</span>
                <span className="chip">±1000</span>
              </div>
            </div>
            <div className="duo-filters-group" style={{ marginTop: 16 }}>
              <label className="tweaks-label">Idioma</label>
              <div className="chips" style={{ marginTop: 8 }}>
                <span className="chip" data-active="true">PT-BR</span>
                <span className="chip">EN</span>
                <span className="chip">ES</span>
              </div>
            </div>
            <div className="duo-filters-group" style={{ marginTop: 16 }}>
              <label className="tweaks-label">Tipo de sala</label>
              <div className="chips" style={{ marginTop: 8 }}>
                <span className="chip" data-active="true">Todas</span>
                <span className="chip">Aberta</span>
                <span className="chip">Aprovação</span>
              </div>
            </div>
          </div>
          <div className="panel panel-pad" style={{ marginTop: 16 }}>
            <div className="eyebrow" style={{ marginBottom: 14 }}>ATIVIDADE RECENTE</div>
            <div className="duo-activity">
              <div className="act-item"><span className="mi" style={{ color: "var(--green)" }}>group</span><span>Zaza encontrou duo (38s atrás)</span></div>
              <div className="act-item"><span className="mi" style={{ color: "var(--primary)" }}>add_circle</span><span>Nova sala de KatEvain</span></div>
              <div className="act-item"><span className="mi" style={{ color: "var(--gold)" }}>emoji_events</span><span>muichiro completou time</span></div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
