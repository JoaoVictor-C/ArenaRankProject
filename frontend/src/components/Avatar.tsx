/* PlayerAvatar = ícone do invocador · ChampIcon = ícone de campeão.

   Fonte das artes: Data Dragon (ddragon) — CDN estático OFICIAL da Riot,
   o mesmo que o cliente de LoL usa. É gratuito, sem chave e está em
   conformidade com os Termos de Serviço.

   Quando uma URL ddragon (`url`) é fornecida, renderizamos a arte real por
   cima do gradiente. O gradiente permanece como FALLBACK: fica visível até a
   imagem carregar e, se a imagem falhar (`onError`), escondemos o <img> e o
   gradiente reassume. As classes e tamanhos (.pavatar / .ch-icon) são mantidos
   intactos — a engine de animação depende deles. */
import { useState, type CSSProperties } from "react";
import type { AvatarColors } from "../lib/types";

// O perfil reutiliza estas propriedades no ancestral comum ao avatar e ao nick.
// eslint-disable-next-line react-refresh/only-export-components
export function avatarColorVars(c?: AvatarColors): CSSProperties {
  return { ["--c1" as string]: c?.c1 ?? "#2a4a6a", ["--c2" as string]: c?.c2 ?? "#46b4ec" };
}

/** Estilo da arte ddragon sobreposta: preenche o contêiner, herda o raio. */
const IMG_STYLE: CSSProperties = {
  position: "absolute",
  inset: 0,
  width: "100%",
  height: "100%",
  objectFit: "cover",
  borderRadius: "inherit",
};

/** <img> ddragon com fallback: ao falhar, esconde-se e o gradiente reaparece. */
function DDragonImg({ url, alt }: { url: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  return (
    <img
      src={url}
      alt={alt}
      loading="lazy"
      style={IMG_STYLE}
      onError={() => setFailed(true)}
      draggable={false}
    />
  );
}

export function PlayerAvatar({
  colors,
  url,
  alt = "",
  size,
  className = "",
  style,
}: {
  colors?: AvatarColors;
  /** URL ddragon do ícone de invocador. Ausente → só o gradiente. */
  url?: string;
  alt?: string;
  size?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const s: CSSProperties = { ...avatarColorVars(colors), ...style };
  if (size) {
    s.width = size;
    s.height = size;
  }
  return (
    <span className={`pavatar${className ? " " + className : ""}`} style={s}>
      {url ? <DDragonImg url={url} alt={alt} /> : null}
    </span>
  );
}

export function ChampIcon({
  colors,
  url,
  alt = "",
  size = "",
  className = "",
  style,
}: {
  colors?: AvatarColors;
  /** URL ddragon do ícone de campeão. Ausente → só o gradiente. */
  url?: string;
  alt?: string;
  size?: "sm" | "lg" | "xl" | "";
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <span
      className={`ch-icon${size ? " " + size : ""}${className ? " " + className : ""}`}
      style={{ ...avatarColorVars(colors), ...style }}
    >
      {url ? <DDragonImg url={url} alt={alt} /> : null}
    </span>
  );
}
