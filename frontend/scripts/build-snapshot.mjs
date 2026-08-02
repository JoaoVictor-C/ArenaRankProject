/* ============================================================
   build-snapshot — congela as respostas GLOBAIS quentes no build.

   Motivo: o cache persistido (lib/queryPersist) só ajuda quem já visitou.
   O visitante de primeira viagem continuava encarando skeleton até a API
   responder. Estas respostas viram JSON dentro do bundle, servido pelo CDN
   da Amplify, então a primeira pintura não espera rede nenhuma.

   Regra dura: SÓ dado global. Nada de /player/* — a posição de um jogador
   não pode ser congelada no build e mostrada para outro.

   Nunca derruba o build: API fora do ar → mantém o placeholder e segue. O
   front trata `entries.X === null` como "sem semente" e mostra skeleton.

   Uso: node scripts/build-snapshot.mjs   (roda antes do `vite build`)
   ============================================================ */
import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = resolve(HERE, "../src/generated");
const TIMEOUT_MS = 15_000;

/** Um arquivo por chunk de rota, para o JSON cair no chunk lazy certo em vez
 *  de engordar o bundle de entrada que todo mundo baixa.
 *
 *  `trim` poda a resposta para o que a tela REALMENTE pinta. A semente existe
 *  para adiantar o primeiro pixel, não para embarcar a API inteira no bundle:
 *  a revalidação (que dispara na montagem) traz o payload completo logo em
 *  seguida. Sem podar, /champions sozinho custava 177 KB para exibir 6 linhas.
 */
const FILES = {
  "snapshot.home.json": {
    leaderboard: { path: "/leaderboard?format=3v3&limit=5" },
    champions: {
      path: "/champions?format=3v3&metric=first",
      // Home.tsx lê exatamente `champs.data?.table` cortado em 6 — nada mais.
      // `tiers` (a tierlist agrupada inteira) custava 88.8 KB sem pintar um
      // pixel na home; vai vazio e é preenchido pelo refetch da montagem.
      trim: (r) => ({
        ...r,
        tiers: [],
        table: Array.isArray(r.table) ? r.table.slice(0, 6) : r.table,
      }),
    },
  },
  "snapshot.leaderboard.json": {
    page1: { path: "/leaderboard?format=3v3&scope=global&season=3&limit=50&offset=0" },
    records: { path: "/meta/records" },
  },
};

async function resolveBaseUrl() {
  if (process.env.VITE_API_URL) return process.env.VITE_API_URL.replace(/\/$/, "");
  // Fallback: lê o .env.production commitado (é ele que manda no build da Amplify).
  try {
    const env = await readFile(resolve(HERE, "../.env.production"), "utf8");
    const m = env.match(/^\s*VITE_API_URL\s*=\s*(.+)$/m);
    if (m) return m[1].trim().replace(/\/$/, "");
  } catch {
    /* sem .env.production: cai no return abaixo */
  }
  return null;
}

async function fetchJson(url) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, { signal: ctrl.signal, headers: { accept: "application/json" } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function main() {
  const base = await resolveBaseUrl();
  if (!base) {
    console.warn("[snapshot] VITE_API_URL não resolvida — mantendo placeholders.");
    return;
  }

  for (const [file, endpoints] of Object.entries(FILES)) {
    const entries = {};
    let ok = 0;
    for (const [key, { path, trim }] of Object.entries(endpoints)) {
      const url = `${base}/api/v1${path}`;
      try {
        const raw = await fetchJson(url);
        entries[key] = trim ? trim(raw) : raw;
        ok += 1;
      } catch (err) {
        entries[key] = null;
        console.warn(`[snapshot] ${key} falhou (${url}): ${err.message}`);
      }
    }

    if (ok === 0) {
      console.warn(`[snapshot] ${file}: nada obtido — placeholder preservado.`);
      continue;
    }
    // generatedAt é a idade real da semente: o front usa como
    // initialDataUpdatedAt, então o badge diz "há 3h" em vez de "agora".
    const payload = { generatedAt: Date.now(), entries };
    await writeFile(resolve(OUT_DIR, file), JSON.stringify(payload), "utf8");
    console.log(`[snapshot] ${file}: ${ok}/${Object.keys(endpoints).length} endpoints`);
  }
}

main().catch((err) => {
  // Falha aqui NUNCA derruba o deploy: o site funciona sem semente.
  console.warn(`[snapshot] abortado sem gerar: ${err.message}`);
});
