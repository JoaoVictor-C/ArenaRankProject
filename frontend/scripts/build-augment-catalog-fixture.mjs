import { writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const CATALOG_URL =
  "https://raw.communitydragon.org/latest/cdragon/arena/pt_br.json";
const VERSIONS_URL =
  "https://ddragon.leagueoflegends.com/api/versions.json";
const OUTPUT_URL = new URL(
  "../public/fixtures/augments-catalog.json",
  import.meta.url,
);

const rarityById = new Map([
  [2, "prismatic"],
  [1, "gold"],
  [0, "silver"],
  [4, "unique"],
]);
const rarityOrder = new Map([
  ["prismatic", 0],
  ["gold", 1],
  ["silver", 2],
  ["unique", 3],
]);
const tiers = ["S+", "S", "A", "B", "C", "D"];
const champions = [
  [1, "Annie"],
  [11, "Mestre Yi"],
  [14, "Sion"],
  [36, "Dr. Mundo"],
  [45, "Veigar"],
  [63, "Brand"],
  [68, "Rumble"],
  [69, "Cassiopeia"],
  [90, "Malzahar"],
  [103, "Ahri"],
  [113, "Sejuani"],
  [127, "Lissandra"],
  [134, "Syndra"],
  [143, "Zyra"],
  [163, "Taliyah"],
  [201, "Braum"],
  [516, "Ornn"],
  [526, "Rell"],
  [711, "Vex"],
  [876, "Lillia"],
];

function formatValue(value) {
  const rounded = Math.round(value * 100) / 100;
  return Number.isInteger(rounded)
    ? String(rounded)
    : String(rounded).replace(".", ",");
}

function cleanDescription(raw, dataValues) {
  const values = dataValues && typeof dataValues === "object"
    ? dataValues
    : {};
  let unresolved = false;
  const cleaned = String(raw ?? "")
    .replace(
      /@([A-Za-z0-9_.:]+)(?:\*([0-9.]+))?@/g,
      (_match, key, multiplier) => {
        const candidates = Array.isArray(values[key])
          ? values[key]
          : [values[key]];
        const numeric = [...candidates]
          .reverse()
          .find((candidate) => typeof candidate === "number");
        if (numeric === undefined) {
          unresolved = true;
          return "";
        }
        return formatValue(numeric * Number(multiplier ?? 1));
      },
    )
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/%i:[^%]+%/gi, "")
    .replace(/\{\{\s*Item_Keyword_OnHit\s*\}\}/gi, "ao contato")
    .replace(/\{\{[^}]+\}\}/g, "")
    .replace(/<[^>]+>/g, "")
    .replaceAll("&nbsp;", " ")
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'")
    .replace(/\s+/g, " ")
    .trim();
  return unresolved ? "" : cleaned;
}

function mockChampions(augmentId) {
  const selected = [];
  for (let index = 0; selected.length < 5; index += 1) {
    const candidate =
      champions[(augmentId * 7 + index * 11) % champions.length];
    if (!selected.some(([championId]) => championId === candidate[0])) {
      selected.push(candidate);
    }
  }
  return selected.map(([championId, name]) => ({ championId, name }));
}

const [catalogResponse, versionsResponse] = await Promise.all([
  fetch(CATALOG_URL),
  fetch(VERSIONS_URL),
]);
if (!catalogResponse.ok) {
  throw new Error(`CDragon catalog failed with ${catalogResponse.status}`);
}
if (!versionsResponse.ok) {
  throw new Error(`DDragon versions failed with ${versionsResponse.status}`);
}

const catalog = await catalogResponse.json();
const versions = await versionsResponse.json();
const augments = (catalog.augments ?? [])
  .map((augment) => {
    const rarity = rarityById.get(Number(augment.rarity));
    if (!rarity || !augment.id || !augment.name) return null;
    const iconPath = String(augment.iconSmall ?? "").trim().toLowerCase();
    return {
      id: Number(augment.id),
      name: String(augment.name).trim(),
      iconUrl: iconPath
        ? `https://raw.communitydragon.org/latest/game/${iconPath}`
        : null,
      rarity,
      description:
        cleanDescription(augment.desc, augment.dataValues) || null,
      tier:
        tiers[
          (Number(augment.id) * 31 + (rarityOrder.get(rarity) ?? 0) * 17) %
            tiers.length
        ],
      champions: mockChampions(Number(augment.id)),
    };
  })
  .filter(Boolean)
  .sort(
    (left, right) =>
      (rarityOrder.get(left.rarity) ?? 99) -
        (rarityOrder.get(right.rarity) ?? 99) ||
      left.name.localeCompare(right.name, "pt-BR"),
  );

const version = String(versions[0] ?? "");
const patch = version.split(".").slice(0, 2).join(".");
const fixture = {
  updatedAt: new Date().toISOString(),
  patch,
  mockedFields: ["tier", "champions"],
  augments,
};

await writeFile(
  fileURLToPath(OUTPUT_URL),
  `${JSON.stringify(fixture, null, 2)}\n`,
  "utf8",
);

console.log(`Wrote ${augments.length} augments to ${fileURLToPath(OUTPUT_URL)}`);
