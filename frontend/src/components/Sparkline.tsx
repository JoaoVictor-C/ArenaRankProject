/* Sparkline SVG a partir de number[]. Recebe a classe "spark" → o motor
   de FX (arena-fx) anima o "desenho" da linha ao entrar em viewport.
   Use className="rc-spark" para o cartão de rank da home. */
import { useMemo } from "react";

export function Sparkline({
  values,
  width = 320,
  height = 56,
  stroke = "var(--gold-bright)",
  fill = true,
  className = "spark",
  strokeWidth = 2,
}: {
  values: number[];
  width?: number;
  height?: number;
  stroke?: string;
  fill?: boolean;
  className?: string;
  strokeWidth?: number;
}) {
  const { line, area, gid } = useMemo(() => {
    const gid = `sl-${Math.abs(hashStr(values.join(",") + width + height))}`;
    if (values.length < 2) return { line: "", area: "", gid };
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const pad = 3;
    const stepX = (width - pad * 2) / (values.length - 1);
    const pts = values.map((v, i) => {
      const x = pad + i * stepX;
      const y = pad + (height - pad * 2) * (1 - (v - min) / span);
      return [x, y] as const;
    });
    const line = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
    const area = `${line} L${pts[pts.length - 1][0].toFixed(1)} ${height} L${pts[0][0].toFixed(1)} ${height} Z`;
    return { line, area, gid };
  }, [values, width, height]);

  return (
    <svg className={className} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      {fill && (
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity="0.22" />
            <stop offset="100%" stopColor={stroke} stopOpacity="0" />
          </linearGradient>
        </defs>
      )}
      {fill && area && <path d={area} fill={`url(#${gid})`} />}
      {line && (
        <path d={line} fill="none" stroke={stroke} strokeWidth={strokeWidth} strokeLinejoin="round" strokeLinecap="round" />
      )}
    </svg>
  );
}

function hashStr(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h << 5) - h + s.charCodeAt(i);
  return h | 0;
}
