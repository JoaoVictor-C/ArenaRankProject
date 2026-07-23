/* Ícone Material Symbols. Uso: <Mi name="search" /> · <Mi name="bolt" fill /> */
import type { CSSProperties } from "react";

export function Mi({
  name,
  fill = false,
  className = "",
  style,
}: {
  name: string;
  fill?: boolean;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <span className={`mi${fill ? " fill" : ""}${className ? " " + className : ""}`} style={style} aria-hidden="true">
      {name}
    </span>
  );
}
