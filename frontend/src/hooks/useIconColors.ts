/* ============================================================
   useIconColors — extrai um par de cores análogas (deep + bright) a partir da
   cor dominante de uma imagem (ícone de invocador ddragon). Alimenta o efeito
   interno do card do pódio (--pc1/--pc2), para que o wash varie conforme o
   ícone do jogador. ddragon serve CORS `*`, então o canvas não fica "tainted".

   Degrada com elegância: retorna null até carregar e em qualquer falha
   (sem URL, erro de rede, canvas bloqueado) — o chamador usa o avatar como
   fallback. Resultados são cacheados por URL (módulo) — extrai uma vez só.
   ============================================================ */
import { useEffect, useState } from "react";

/** HSL (h 0..360, s/l 0..1) -> #RRGGBB. */
function hslHex(h: number, s: number, l: number): string {
  const a = s * Math.min(l, 1 - l);
  const ch = (n: number) => {
    const k = (n + h / 30) % 12;
    const c = l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return Math.round(255 * c)
      .toString(16)
      .padStart(2, "0");
  };
  return `#${ch(0)}${ch(8)}${ch(4)}`;
}

const cache = new Map<string, [string, string] | null>();

/**
 * Extrai `[c1, c2]` (par análogo deep+bright) da cor dominante mais vívida de
 * `url`. `null` enquanto carrega ou em falha (chamador faz fallback).
 */
export function useIconColors(url?: string | null): [string, string] | null {
  const [colors, setColors] = useState<[string, string] | null>(
    url && cache.has(url) ? cache.get(url)! : null,
  );

  useEffect(() => {
    if (!url) {
      setColors(null);
      return;
    }
    if (cache.has(url)) {
      setColors(cache.get(url)!);
      return;
    }
    let alive = true;
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      try {
        const n = 24;
        const cv = document.createElement("canvas");
        cv.width = n;
        cv.height = n;
        const ctx = cv.getContext("2d", { willReadFrequently: true });
        if (!ctx) throw new Error("no 2d context");
        ctx.drawImage(img, 0, 0, n, n);
        const data = ctx.getImageData(0, 0, n, n).data;
        // Histograma de HUE ponderado por croma (saturação*valor): pega o hue
        // DOMINANTE do ícone — robusto a pixels avulsos vívidos (um detalhe
        // magenta numa abóbora laranja não "rouba" a cor). Ignora cinza/preto.
        const BUCKETS = 36; // 10° por bucket
        const weight = new Float64Array(BUCKETS);
        for (let i = 0; i < data.length; i += 4) {
          const r = data[i] / 255;
          const g = data[i + 1] / 255;
          const b = data[i + 2] / 255;
          if (data[i + 3] / 255 < 0.5) continue;
          const mx = Math.max(r, g, b);
          const mn = Math.min(r, g, b);
          const v = mx;
          const s = mx === 0 ? 0 : (mx - mn) / mx;
          if (v < 0.2 || s < 0.2) continue; // descarta quase-preto e quase-cinza
          const d = mx - mn;
          let h = 0;
          if (mx === r) h = ((g - b) / d) % 6;
          else if (mx === g) h = (b - r) / d + 2;
          else h = (r - g) / d + 4;
          h *= 60;
          if (h < 0) h += 360;
          weight[Math.floor(h / 10) % BUCKETS] += s * v;
        }
        let bestB = -1;
        let bestW = 0;
        for (let k = 0; k < BUCKETS; k++) {
          if (weight[k] > bestW) {
            bestW = weight[k];
            bestB = k;
          }
        }
        if (bestB < 0) {
          // Ícone sem croma confiável (cinza/PB) — usa o fallback (avatar).
          cache.set(url, null);
          if (alive) setColors(null);
          return;
        }
        const hue = bestB * 10 + 5;
        const pair: [string, string] = [
          hslHex(hue, 0.55, 0.34),
          hslHex((hue + 26) % 360, 0.78, 0.62),
        ];
        cache.set(url, pair);
        if (alive) setColors(pair);
      } catch {
        cache.set(url, null);
        if (alive) setColors(null);
      }
    };
    img.onerror = () => {
      cache.set(url, null);
      if (alive) setColors(null);
    };
    img.src = url;
    return () => {
      alive = false;
    };
  }, [url]);

  return colors;
}
