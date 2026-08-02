/* ============================================================
   ArenaRank — motor de animação (portado de arena-anim.js + arena-fx.js)
   Framework-agnóstico: roda sobre o DOM. Chamado UMA vez no App (useEffect).
   - Revela blocos ao rolar (IntersectionObserver) com escalonamento
   - Lida com conteúdo injetado/re-renderizado (MutationObserver → cobre rotas)
   - Conta números, preenche barras, desenha sparklines, monta gráficos
   - Seguro: respeita prefers-reduced-motion; nunca esconde permanentemente
   ============================================================ */

let started = false;

const REVEAL = [
  ".breadcrumb", ".hero", ".metrics-band", ".sec", ".cta",
  ".lb-top", ".softlock", ".podium", ".lb-filters", ".lb-table", ".pager",
  ".rail-card", ".panel", ".tabs", ".section-head", ".tbl",
  ".doc-hero", ".doc-sec", ".mh", ".standings", ".grid2",
  ".title-block", ".metrics", ".panel-2col", ".admin-h",
  ".steps", ".features", ".tourn-grid", ".lbp", ".form-row", ".cards",
  // NÃO adicionar aqui as superfícies do mundo "handoff" (.wr- .cmp- .tl-):
  // elas são território do lib/motion.ts (GSAP). Os dois sistemas aplicam
  // opacity/transform no mesmo nó e brigam — resultado é flicker ou bloco
  // preso invisível. Ver frontend/.impeccable/motion-brief.md §3.
].join(",");

const COUNTUP = "[data-countup], .metric-x b, .priority-stat b";

type ArEl = HTMLElement & {
  __arIn?: boolean;
  __arSeen?: boolean;
  __arCount?: boolean;
  __arCountSeen?: boolean;
  __arFilled?: boolean;
  __pct?: number;
  __built?: boolean;
  __filled?: boolean;
  __obs?: boolean;
  __drawn?: boolean;
  __tiltLeave?: () => void;
};

/** Fronteira de propriedade: qualquer nó dentro das páginas migradas pertence
    somente ao GSAP, mesmo que também use uma classe genérica do motor legado. */
export function isGsapOwned(element: Element): boolean {
  return element.closest("[data-gsap-scope]") !== null;
}

export function initAnimEngine(): void {
  if (started) return;
  started = true;
  initReveal();
  initFx();
}

/* ============================================================
   1) REVEAL / COUNT-UP / BARRAS  (de arena-anim.js)
   ============================================================ */
function initReveal(): void {
  const reduce =
    !!window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const docEl = document.documentElement;
  if (!docEl.classList.contains("ar-anim")) docEl.classList.add("ar-anim");

  function isOutermost(el: Element): boolean {
    if (isGsapOwned(el)) return false;
    const p = el.parentElement;
    return !(p && p.closest(REVEAL));
  }

  function reveal(el: ArEl): void {
    if (el.__arIn || isGsapOwned(el)) return;
    el.__arIn = true;
    el.style.opacity = "1";
    el.style.transform = "none";
    el.style.filter = "none";
    const inner = el.querySelectorAll<ArEl>(REVEAL);
    for (let i = 0; i < inner.length; i++) {
      inner[i].style.opacity = "1";
      inner[i].style.transform = "none";
      inner[i].style.filter = "none";
      inner[i].__arIn = true;
    }
    fillBars(el);
  }

  function fillBars(scope: Element): void {
    if (isGsapOwned(scope)) return;
    const bars = scope.querySelectorAll<ArEl>(".pbar > span, .bar");
    for (let i = 0; i < bars.length; i++) {
      if (!isGsapOwned(bars[i])) animateBar(bars[i]);
    }
  }
  function animateBar(el: ArEl): void {
    if (el.__arFilled || isGsapOwned(el)) return;
    el.__arFilled = true;
    let target = el.style.width;
    if (!target) {
      const w = getComputedStyle(el).width;
      target = w && w !== "auto" ? w : "";
    }
    if (!target) return;
    if (reduce) {
      el.style.width = target;
      return;
    }
    el.style.width = "0px";
    void el.offsetWidth;
    requestAnimationFrame(() => {
      el.style.width = target;
    });
  }

  function countUp(el: ArEl): void {
    if (el.__arCount || isGsapOwned(el)) return;
    el.__arCount = true;
    const raw = (el.textContent || "").trim();
    const m = raw.match(/^([^\d-]*)(-?[\d.,]+)(.*)$/);
    if (!m) return;
    const pre = m[1];
    const numStr = m[2];
    const post = m[3];
    let decimals = 0;
    let value: number;
    try {
      if (numStr.indexOf(",") !== -1) {
        decimals = (numStr.split(",")[1] || "").length;
        value = parseFloat(numStr.replace(/\./g, "").replace(",", "."));
      } else if ((numStr.match(/\./g) || []).length === 1 && numStr.split(".")[1].length <= 2) {
        decimals = numStr.split(".")[1].length;
        value = parseFloat(numStr);
      } else {
        value = parseFloat(numStr.replace(/\./g, ""));
      }
    } catch {
      return;
    }
    if (!isFinite(value)) return;

    function fmt(n: number): string {
      let s = decimals > 0 ? n.toFixed(decimals) : String(Math.round(n));
      if (decimals > 0) s = s.replace(".", ",");
      const parts = s.split(",");
      parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".");
      return pre + parts.join(",") + post;
    }
    if (reduce) return;
    const dur = 1100;
    const t0 = performance.now();
    el.textContent = fmt(0);
    function step(t: number): void {
      const p = Math.min(1, (t - t0) / dur);
      const e = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(value * e);
      if (p < 1) requestAnimationFrame(step);
      else el.textContent = raw;
    }
    requestAnimationFrame(step);
  }

  if (reduce) {
    if ((window as any).__arFallback) clearTimeout((window as any).__arFallback);
    docEl.classList.remove("ar-anim");
    return;
  }

  const io = new IntersectionObserver(
    (entries) => {
      const hits: Element[] = [];
      for (let i = 0; i < entries.length; i++) {
        if (entries[i].isIntersecting) {
          hits.push(entries[i].target);
          io.unobserve(entries[i].target);
        }
      }
      if (!hits.length) return;
      hits.sort((a, b) => {
        const pos = a.compareDocumentPosition(b);
        return pos & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
      });
      hits.forEach((el, idx) => {
        const delay = Math.min(idx * 75, 320);
        setTimeout(() => reveal(el as ArEl), delay);
      });
    },
    { threshold: 0.08, rootMargin: "0px 0px -6% 0px" },
  );

  function register(root?: Document | Element): void {
    const els = (root || document).querySelectorAll<ArEl>(REVEAL);
    const vh = window.innerHeight || document.documentElement.clientHeight;
    for (let i = 0; i < els.length; i++) {
      const el = els[i];
      if (el.__arSeen || isGsapOwned(el)) continue;
      if (!isOutermost(el)) continue;
      el.__arSeen = true;
      // A SPA renders content asynchronously AFTER mount, so above-the-fold
      // blocks would stay hidden (opacity 0) until a scroll fired the observer.
      // Reveal anything already in the viewport immediately; only defer the
      // off-screen blocks to the IntersectionObserver (scroll reveal).
      const r = el.getBoundingClientRect();
      if (r.bottom > 0 && r.top < vh) {
        reveal(el);
      } else {
        io.observe(el);
      }
    }
  }

  const cio = new IntersectionObserver(
    (entries) => {
      for (let i = 0; i < entries.length; i++) {
        if (entries[i].isIntersecting) {
          countUp(entries[i].target as ArEl);
          cio.unobserve(entries[i].target);
        }
      }
    },
    { threshold: 0.6 },
  );

  function registerCounts(root?: Document | Element): void {
    const els = (root || document).querySelectorAll<ArEl>(COUNTUP);
    for (let i = 0; i < els.length; i++) {
      if (!els[i].__arCountSeen && !isGsapOwned(els[i])) {
        els[i].__arCountSeen = true;
        cio.observe(els[i]);
      }
    }
  }

  let pending = false;
  const mo = new MutationObserver((muts) => {
    let added = false;
    for (let i = 0; i < muts.length; i++) {
      if (muts[i].addedNodes && muts[i].addedNodes.length) {
        added = true;
        break;
      }
    }
    if (!added || pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      register(document);
      registerCounts(document);
      const inBlocks = document.querySelectorAll<ArEl>(".lb-table, .podium, .tbl, .metrics, .feed");
      for (let i = 0; i < inBlocks.length; i++) if (inBlocks[i].__arIn) fillBars(inBlocks[i]);
    });
  });

  // segurança ao trocar de aba (revela blocos antes ocultos)
  document.addEventListener(
    "click",
    (e) => {
      const trigger = (e.target as Element).closest(
        ".tab, [data-sec], [data-panel-trigger], .a-nav a, .a-nav button",
      );
      if (!trigger) return;
      setTimeout(() => {
        const els = document.querySelectorAll<ArEl>(REVEAL);
        for (let i = 0; i < els.length; i++) {
          const el = els[i];
          if (isGsapOwned(el)) continue;
          if (el.offsetParent === null) continue;
          if (isOutermost(el)) reveal(el);
        }
        const cs = document.querySelectorAll<ArEl>(COUNTUP);
        for (let j = 0; j < cs.length; j++) {
          if (!isGsapOwned(cs[j]) && cs[j].offsetParent !== null) countUp(cs[j]);
        }
      }, 80);
    },
    true,
  );

  function start(): void {
    register(document);
    registerCounts(document);
    mo.observe(document.body, { childList: true, subtree: true });
    if ((window as any).__arFallback) clearTimeout((window as any).__arFallback);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
}

/* ============================================================
   2) FX EXTRAVAGANTES (de arena-fx.js): tilt, sparkline, chart
   ============================================================ */
function initFx(): void {
  const reduce =
    !!window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const off = () => document.documentElement.classList.contains("ar-anim-off");

  function initTilt(): void {
    if (reduce) return;
    const sel = ".feat, .tcard, .step, .rank-card";
    document.addEventListener(
      "pointermove",
      (e) => {
        if (off()) return;
        const card = (e.target as Element).closest(sel) as ArEl | null;
        if (card && isGsapOwned(card)) return;
        if (card && card.__tiltLeave === undefined) {
          card.__tiltLeave = () => {
            card.style.transform = "none";
          };
          card.addEventListener("pointerleave", card.__tiltLeave);
        }
        if (!card) return;
        const r = card.getBoundingClientRect();
        const px = (e.clientX - r.left) / r.width - 0.5;
        const py = (e.clientY - r.top) / r.height - 0.5;
        const max = 7;
        card.style.transform =
          "perspective(820px) rotateY(" +
          (px * max).toFixed(2) +
          "deg) rotateX(" +
          (-py * max).toFixed(2) +
          "deg) translateY(-4px) scale(1.015)";
      },
      { passive: true },
    );
  }

  function drawSpark(svg: ArEl): void {
    if (svg.__drawn || isGsapOwned(svg)) return;
    svg.__drawn = true;
    const strokePaths = svg.querySelectorAll<SVGGeometryElement>("path[stroke], polyline[stroke]");
    const fills = svg.querySelectorAll<SVGElement>("path:not([stroke]), [fill^='url']");
    if (reduce || off()) return;
    strokePaths.forEach((p, i) => {
      let len: number;
      try {
        len = p.getTotalLength();
      } catch {
        return;
      }
      if (!len) return;
      p.style.strokeDasharray = String(len);
      p.style.strokeDashoffset = String(len);
      p.getBoundingClientRect();
      p.style.transition = "stroke-dashoffset 1.3s cubic-bezier(.16,.84,.44,1) " + i * 0.15 + "s";
      requestAnimationFrame(() => {
        p.style.strokeDashoffset = "0";
      });
    });
    fills.forEach((f) => {
      f.style.opacity = "0";
      f.style.transition = "opacity 1s ease .5s";
      requestAnimationFrame(() => {
        f.style.opacity = "";
      });
    });
  }

  function buildChart(el: ArEl): void {
    if (el.__built || isGsapOwned(el)) return;
    el.__built = true;
    const vals = (el.getAttribute("data-vals") || "")
      .split(",")
      .map((s) => parseFloat(s.trim()))
      .filter((n) => isFinite(n));
    if (!vals.length) return;
    const labels = (el.getAttribute("data-labels") || "").split(",").map((s) => s.trim());
    const max = Math.max.apply(null, vals);
    const hiIdx = el.hasAttribute("data-hi")
      ? parseInt(el.getAttribute("data-hi") as string, 10)
      : vals.indexOf(max);
    const fmt = el.getAttribute("data-suffix") || "";
    el.textContent = "";
    vals.forEach((v, i) => {
      const pct = max > 0 ? Math.max(4, Math.round((v / max) * 100)) : 0;
      const col = document.createElement("div") as ArEl;
      col.className = "ar-col" + (i === hiIdx ? " hi" : "");

      // Construído via DOM (textContent), não innerHTML: rótulos/sufixos vêm de
      // atributos e não devem ser interpretados como HTML (evita XSS e é robusto).
      const track = document.createElement("div");
      track.className = "ar-bar-track";
      const bar = document.createElement("div");
      bar.className = "ar-bar";
      const valEl = document.createElement("span");
      valEl.className = "ar-val";
      valEl.textContent = v.toLocaleString("pt-BR") + fmt;
      bar.appendChild(valEl);
      track.appendChild(bar);
      col.appendChild(track);
      if (labels[i]) {
        const xlbl = document.createElement("div");
        xlbl.className = "ar-xlbl";
        xlbl.textContent = labels[i];
        col.appendChild(xlbl);
      }

      el.appendChild(col);
      col.__pct = pct;
    });
  }
  function fillChart(el: ArEl): void {
    if (el.__filled || isGsapOwned(el)) return;
    el.__filled = true;
    const cols = el.querySelectorAll<ArEl>(".ar-col");
    for (let i = 0; i < cols.length; i++) {
      ((col: ArEl, idx: number) => {
        const bar = col.querySelector<HTMLElement>(".ar-bar");
        if (!bar) return;
        if (reduce || off()) {
          bar.style.height = col.__pct + "%";
          el.classList.add("ar-shown");
          return;
        }
        bar.style.transitionDelay = idx * 0.06 + "s";
        setTimeout(() => {
          bar.style.height = col.__pct + "%";
        }, 30);
      })(cols[i], i);
    }
    if (!(reduce || off())) setTimeout(() => el.classList.add("ar-shown"), 300);
  }

  const io =
    "IntersectionObserver" in window
      ? new IntersectionObserver(
          (entries) => {
            entries.forEach((en) => {
              if (!en.isIntersecting) return;
              const t = en.target as ArEl;
              io!.unobserve(t);
              if (t.matches(".ar-chart")) fillChart(t);
              else if (t.tagName.toLowerCase() === "svg") drawSpark(t);
            });
          },
          { threshold: 0.25 },
        )
      : null;

  function scan(): void {
    // [data-static]: charts renderizados/possuídos pelo React — o engine não
    // os reconstrói (buildChart faria textContent="" e apagaria o DOM do React).
    document.querySelectorAll<ArEl>(".ar-chart:not([data-static])").forEach((c) => {
      if (isGsapOwned(c)) return;
      buildChart(c);
      if (c.__obs) return;
      c.__obs = true;
      if (io) io.observe(c);
      else fillChart(c);
    });
    document.querySelectorAll<ArEl>(".rc-spark, svg.spark").forEach((s) => {
      if (isGsapOwned(s)) return;
      if (s.__obs) return;
      s.__obs = true;
      if (io) io.observe(s);
      else drawSpark(s);
    });
  }

  function start(): void {
    initTilt();
    scan();
    let pending = false;
    new MutationObserver(() => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(() => {
        pending = false;
        scan();
      });
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
}
