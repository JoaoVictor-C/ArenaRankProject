/* Painel de ajustes flutuante (porta tweaks-panel.jsx / arena-tweaks.jsx).
   Controla: estilo de fundo (grid/gradient/plain — vocabulário do design) e animações (on/off).
   Persiste em localStorage e aplica em <body data-bg> / <html.ar-anim-off>. */
import { useEffect, useState } from "react";
import { Mi } from "./Mi";

type BgStyle = "grid" | "gradient" | "plain";

function load<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}

/* Default = "grid" (estado do design em Leaderboard/Perfil/Partida/Campeonatos).
   Migra valores legados ("dots" e quaisquer outros) para "grid". */
function loadBg(): BgStyle {
  const v = load<string>("ar-bg", "grid");
  return v === "gradient" || v === "plain" ? v : "grid";
}

export function TweaksPanel() {
  const [open, setOpen] = useState(false);
  const [bg, setBg] = useState<BgStyle>(loadBg);
  const [anim, setAnim] = useState<boolean>(() => load<boolean>("ar-anim-on", true));

  useEffect(() => {
    document.body.setAttribute("data-bg", bg);
    localStorage.setItem("ar-bg", JSON.stringify(bg));
  }, [bg]);

  useEffect(() => {
    document.documentElement.classList.toggle("ar-anim-off", !anim);
    localStorage.setItem("ar-anim-on", JSON.stringify(anim));
  }, [anim]);

  return (
    <div className="tweaks">
      <button
        className="tweaks-fab"
        type="button"
        aria-label="Ajustes de aparência"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <Mi name={open ? "close" : "tune"} />
      </button>
      {open && (
        <div className="tweaks-panel" role="dialog" aria-label="Ajustes">
          <div className="tweaks-title">Aparência</div>

          <div className="tweaks-group">
            <span className="tweaks-label">Fundo</span>
            <div className="tweaks-seg">
              {(["grid", "gradient", "plain"] as BgStyle[]).map((b) => (
                <button
                  key={b}
                  type="button"
                  data-active={bg === b}
                  onClick={() => setBg(b)}
                >
                  {b === "grid" ? "Grade" : b === "gradient" ? "Gradiente" : "Liso"}
                </button>
              ))}
            </div>
          </div>

          <div className="tweaks-group">
            <span className="tweaks-label">Animações</span>
            <div className="tweaks-seg">
              <button type="button" data-active={anim} onClick={() => setAnim(true)}>
                Ligadas
              </button>
              <button type="button" data-active={!anim} onClick={() => setAnim(false)}>
                Desligadas
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
