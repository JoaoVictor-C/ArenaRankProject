import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, "..");

/**
 * Static schema verification (spec §7) — no live DB required.
 * Proves the schema is structurally valid via `prisma validate`.
 */
describe("prisma schema (static)", () => {
  it("passes `prisma validate`", () => {
    const out = execFileSync("npx", ["prisma", "validate"], {
      cwd: pkgRoot,
      encoding: "utf8",
      shell: process.platform === "win32",
    });
    expect(out).toMatch(/is valid/i);
  });
});
