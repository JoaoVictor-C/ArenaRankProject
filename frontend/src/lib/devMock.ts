/* ============================================================
   devMock — serve os endpoints da página do campeão que o backend
   ainda não tem, a partir de `public/api-fixtures/champion-page.json`.

   Por que existe: o fixture é o contrato que vai para a sessão de
   backend. Um contrato que nada consome é só um documento — plugando
   ele na UI real, qualquer campo errado aparece na tela na hora.

   NUNCA liga sozinho. Só com `?mock=1` na URL (persiste na aba via
   sessionStorage; `?mock=0` desliga) e só em dev — o build de produção
   não carrega este módulo, então a página continua degradando honesto
   para o usuário final.
   ============================================================ */
const FLAG = "arenarank.devMock";
/* Fora do prefixo /api de propósito: o proxy do Vite encaminha /api* para o
   backend real, então uma pasta "api-fixtures" nunca chegaria ao public/. */
const FIXTURE = "/fixtures/champion-page.json";
const POWER_SPIKE_FIXTURE = "/fixtures/champion-power-spike.json";

type Fixture = {
  trend: unknown;
  matchups: Record<string, unknown>;
  builds: unknown;
  /** Campos ADITIVOS sobre o /build que já existe (não substitui a resposta
      real: mescla por cima, para o painel novo funcionar com dado real ao lado). */
  buildPatch: Record<string, unknown>;
};

let cache: Promise<Fixture> | null = null;
let powerSpikeCache: Promise<unknown> | null = null;
const loadFixture = (): Promise<Fixture> => {
  cache ??= fetch(FIXTURE).then((r) => r.json() as Promise<Fixture>);
  return cache;
};
const loadPowerSpikeFixture = (): Promise<unknown> => {
  powerSpikeCache ??= fetch(POWER_SPIKE_FIXTURE).then(
    (response) => response.json() as Promise<unknown>,
  );
  return powerSpikeCache;
};

/** Endpoints pendentes → chave no fixture. Só estes são interceptados. */
function resolve(path: string): ((f: Fixture) => unknown) | null {
  if (/\/champions\/\d+\/trend/.test(path)) return (f) => f.trend;
  if (/\/champions\/\d+\/builds/.test(path)) return (f) => f.builds;
  // `/matchups` saiu daqui: o endpoint existe de verdade agora (agrega o
  // self-join de subteam sobre partidas já ingeridas, sem depender de dado
  // novo). Interceptá-lo esconderia a implementação real em desenvolvimento.
  return null;
}

/** `/build` existe: em vez de substituir, mescla só os campos que faltam
    (hoje `prismaticItems`), para o painel novo conviver com o dado real. */
function patchesBuild(path: string): boolean {
  return /\/champions\/\d+\/build(\?|$)/.test(path);
}

/** Reescreve o championId do fixture para o da rota, senão a página do
    campeão X exibiria o nome do campeão do fixture nos painéis. */
function retarget(payload: unknown, championId: number, name?: string): unknown {
  if (!payload || typeof payload !== "object") return payload;
  const clone = structuredClone(payload) as Record<string, unknown>;
  clone.championId = championId;
  if (name) clone.name = name;
  return clone;
}

export function isDevMockOn(): boolean {
  if (!import.meta.env.DEV) return false;
  const q = new URLSearchParams(window.location.search).get("mock");
  if (q === "1") sessionStorage.setItem(FLAG, "1");
  if (q === "0") sessionStorage.removeItem(FLAG);
  return sessionStorage.getItem(FLAG) === "1";
}

/** Devolve o payload do fixture para `path`, ou null se não for um dos
    endpoints pendentes (aí a chamada segue para a API de verdade). */
export async function devMockResponse(path: string): Promise<unknown | null> {
  if (!isDevMockOn()) return null;
  const championId = Number(/\/champions\/(\d+)\//.exec(path)?.[1] ?? 0);
  if (/\/champions\/\d+\/rounds/.test(path)) {
    const powerSpike = await loadPowerSpikeFixture();
    return retarget(powerSpike, championId);
  }
  const pick = resolve(path);
  if (!pick) return null;
  const fixture = await loadFixture();
  return retarget(pick(fixture), championId);
}

/** Mescla os campos ainda-não-servidos por cima de uma resposta REAL. */
export async function devMockPatch<T>(path: string, real: T): Promise<T> {
  if (!isDevMockOn() || !patchesBuild(path)) return real;
  const fixture = await loadFixture();
  return { ...real, ...fixture.buildPatch } as T;
}
