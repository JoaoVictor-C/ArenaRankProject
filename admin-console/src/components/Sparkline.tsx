/* Tiny dependency-free SVG sparkline with an area fill and a head dot. */

interface Props {
  data: number[];
  color?: string;
  width?: number;
  height?: number;
  /** Force a fixed max; otherwise scales to the data (with a small headroom). */
  max?: number;
}

export function Sparkline({ data, color = "#4cc2ff", width = 160, height = 38, max }: Props) {
  const pad = 3;
  const w = width;
  const h = height;
  if (data.length === 0) {
    return <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" />;
  }
  const peak = max ?? Math.max(1, ...data) * 1.12;
  const n = data.length;
  const step = n > 1 ? (w - pad * 2) / (n - 1) : 0;
  const Y = (v: number) => h - pad - (Math.max(0, v) / peak) * (h - pad * 2);
  const X = (i: number) => pad + i * step;

  const line = data.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${X(n - 1).toFixed(1)} ${h - pad} L${X(0).toFixed(1)} ${h - pad} Z`;
  const hx = X(n - 1);
  const hy = Y(data[n - 1]);
  const id = `sg-${color.replace(/[^a-z0-9]/gi, "")}`;

  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={hx} cy={hy} r="2.1" fill={color} />
    </svg>
  );
}
