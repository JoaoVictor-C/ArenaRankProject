import { afterEach, expect, it } from "vitest";
import { isGsapOwned } from "./animEngine";

afterEach(() => {
  document.body.innerHTML = "";
});

it("treats every descendant of data-gsap-scope as GSAP-owned", () => {
  document.body.innerHTML = `
    <main data-gsap-scope>
      <section><div id="candidate" class="panel"></div></section>
    </main>`;

  expect(isGsapOwned(document.querySelector("#candidate") as Element)).toBe(true);
});

it("leaves unrelated route elements under the legacy engine", () => {
  document.body.innerHTML = `<main><div id="candidate" class="panel"></div></main>`;

  expect(isGsapOwned(document.querySelector("#candidate") as Element)).toBe(false);
});
