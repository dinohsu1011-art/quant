/* Market Lab — sentence-driven event-study explorer.
   Data: cube/index.js (menus) + lazy cube/<subject>.js shards (offline), or the
   live serve.py API when reachable. No dependencies; works on file://. */
(() => {
  const L = window.QUANT_LAB;
  const $ = (id) => document.getElementById(id);
  if (!L) { $("mode").textContent = "cube/index.js missing — run: python -m export.cube"; return; }
  const M = L.menus;
  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const f2 = (x) => x == null ? "—" : (x >= 0 ? "+" : "") + Number(x).toFixed(2) + "%";
  const get = (arr, id) => arr.find((o) => o.id === id);
  const DOWN = { 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri" };

  // ---------- state ----------
  const state = { s: "spy", t: "d25", wd: "fri", c: "none", h: "h1", thr: null }; // thr = live custom %
  let SERVER = null, PIN = null, lastRows = null;
  const GRID = M.triggers.filter((t) => t.threshold != null)
                         .map((t) => ({ id: t.id, pct: -t.threshold * 100 }));

  // ---------- url hash ----------
  function readHash() {
    const p = location.hash.replace("#", "").split("|");
    if (p.length >= 5) {
      const [s, t, wd, c, h] = p;
      if (get(M.subjects, s)) state.s = s;
      if (t.startsWith("x")) { state.t = "custom"; state.thr = parseFloat(t.slice(1)) || 2.5; }
      else if (get(M.triggers, t)) { state.t = t; state.thr = null; }
      if (get(M.weekdays, wd)) state.wd = wd;
      if (get(M.conditions, c)) state.c = c;
      if (get(M.horizons, h)) state.h = h;
    }
  }
  function writeHash(push) {
    const t = state.t === "custom" ? "x" + state.thr : state.t;
    const h = `#${state.s}|${t}|${state.wd}|${state.c}|${state.h}`;
    if (h !== location.hash) (push ? history.pushState(null, "", h) : history.replaceState(null, "", h));
  }

  // ---------- data layer ----------
  function loadShard(subj) {
    return new Promise((res, rej) => {
      if (L.shards[subj]) return res();
      const sc = document.createElement("script");
      sc.src = `cube/${subj}.js`;
      sc.onload = () => res();
      sc.onerror = () => rej(new Error(`shard cube/${subj}.js not found`));
      document.body.appendChild(sc);
    });
  }
  function norm(arr, rows) {
    return arr ? { n: arr[0], up: arr[1], mean: arr[2], t: arr[3], ci_lo: arr[4], ci_hi: arr[5],
                   counts: arr.slice(6), rows: rows || null } : null;
  }
  async function getResult(s, t, wd, c, h, thr) {
    if (SERVER === null) {
      if (t === "custom") return null;            // custom thresholds are live-only
      await loadShard(s);
      return norm((L.shards[s] || {})[`${t}|${wd}|${c}|${h}`]);
    }
    const T = t === "custom" ? null : get(M.triggers, t);
    const q = new URLSearchParams({ subject: s, horizon: get(M.horizons, h).h });
    if (t === "custom") q.set("threshold", (-thr / 100).toFixed(4));
    else if (T.threshold != null) q.set("threshold", T.threshold);
    else q.set("worst_n", T.worst_n);
    const wdo = get(M.weekdays, wd);
    if (wdo.day != null) q.set("day", wd);
    const cnd = get(M.conditions, c);
    if (cnd.when) q.set("when", cnd.when.replace(/\{subj\}/g, s));
    const r = await fetch(SERVER + "/api/event?" + q);
    if (!r.ok) throw new Error("server " + r.status);
    const d = await r.json();
    const su = d.summary;
    return { n: su.n, up: su.up_pct, mean: su.mean_pct, t: su.t, ci_lo: su.ci_lo, ci_hi: su.ci_hi,
             counts: d.bins.counts, rows: d.rows };
  }

  // ---------- popover ----------
  const pop = $("pop");
  let popCloser = null;
  function openPop(anchor, items, onpick) {
    pop.innerHTML = items.map((it) => it.group !== undefined
      ? `<div class="g">${esc(it.group)}</div>`
      : `<div class="o${it.sel ? " sel" : ""}${it.dis ? " dis" : ""}" data-v="${esc(it.id)}">${esc(it.label)}</div>`
    ).join("");
    pop.style.display = "block";
    const r = anchor.getBoundingClientRect();
    pop.style.left = Math.min(r.left, innerWidth - pop.offsetWidth - 12) + "px";
    pop.style.top = Math.min(r.bottom + 6, innerHeight - pop.offsetHeight - 12) + "px";
    pop.onclick = (e) => {
      const v = e.target.dataset && e.target.dataset.v;
      if (v) { closePop(); onpick(v); }
    };
    popCloser = (e) => { if (!pop.contains(e.target) && e.target !== anchor) closePop(); };
    setTimeout(() => document.addEventListener("pointerdown", popCloser), 0);
  }
  function closePop() {
    pop.style.display = "none";
    if (popCloser) document.removeEventListener("pointerdown", popCloser);
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePop(); });

  function available(dim, id) {                    // offline graying within the loaded shard
    if (SERVER !== null || state.t === "custom") return true;
    const sh = L.shards[state.s];
    if (!sh) return true;
    const k = {
      t: `${id}|${state.wd}|${state.c}|${state.h}`,
      wd: `${state.t}|${id}|${state.c}|${state.h}`,
      c: `${state.t}|${state.wd}|${id}|${state.h}`,
      h: `${state.t}|${state.wd}|${state.c}|${id}`,
    }[dim];
    return !!sh[k];
  }

  // ---------- sentence ----------
  function trigLabel() {
    if (state.t === "custom") return `falls ≥ ${state.thr.toFixed(1)}%`;
    const T = get(M.triggers, state.t);
    return T.threshold != null ? `falls ≥ ${Math.abs(T.threshold * 100)}%` : `has one of its ${T.worst_n} worst days`;
  }
  function renderSentence() {
    const wdo = get(M.weekdays, state.wd), cnd = get(M.conditions, state.c);
    $("sentence").innerHTML =
      `<span class="quiet">After</span> <span class="tok" data-d="s">${esc(get(M.subjects, state.s).label)}</span> ` +
      `<span class="tok" data-d="t">${esc(trigLabel())}</span> ` +
      `<span class="quiet">on</span> <span class="tok" data-d="wd">${wdo.day == null ? "any weekday" : esc(wdo.label) + "s"}</span>` +
      `<span class="quiet">, when</span> <span class="tok" data-d="c">${state.c === "none" ? "(no condition)" : esc(cnd.label)}</span>` +
      `<span class="quiet">, what happens over the</span> <span class="tok" data-d="h">${esc(get(M.horizons, state.h).label.toLowerCase())}</span>` +
      `<span class="quiet">?</span>`;
    $("sentence").querySelectorAll(".tok").forEach((el) => {
      el.onclick = () => {
        const d = el.dataset.d;
        let items;
        if (d === "s") {
          const order = [], byG = {};
          for (const o of M.subjects) {
            const g = o.group || "Other";
            if (!byG[g]) { order.push(g); byG[g] = []; }
            byG[g].push(o);
          }
          items = [];
          for (const g of order) {
            items.push({ group: g });
            byG[g].forEach((o) => items.push({ id: o.id, label: o.label, sel: o.id === state.s }));
          }
        } else {
          const src = { t: M.triggers, wd: M.weekdays, c: M.conditions, h: M.horizons }[d];
          items = src.map((o) => ({ id: o.id, label: o.label, sel: o.id === state[d], dis: !available(d, o.id) }));
          if (d === "t" && SERVER !== null) items.push({ id: "custom", label: "custom threshold (slider)", sel: state.t === "custom" });
        }
        openPop(el, items, (v) => {
          if (d === "t" && v === "custom") { state.t = "custom"; state.thr = state.thr || 2.5; }
          else { state[d] = v; if (d === "t") state.thr = null; }
          update(true);
        });
      };
    });
  }

  // ---------- slider ----------
  function renderSlider() {
    const row = $("sliderrow"), inp = $("thr");
    const isWorst = state.t !== "custom" && get(M.triggers, state.t).threshold == null;
    row.style.visibility = isWorst ? "hidden" : "visible";
    if (isWorst) return;
    if (SERVER !== null) {
      inp.min = 0.5; inp.max = 8; inp.step = 0.1;
      inp.value = state.t === "custom" ? state.thr : -get(M.triggers, state.t).threshold * 100;
      $("thrhint").textContent = "live: any threshold";
    } else {
      inp.min = 0; inp.max = GRID.length - 1; inp.step = 1;
      inp.value = Math.max(0, GRID.findIndex((g) => g.id === state.t));
      $("thrhint").textContent = "snaps to cube grid · live server unlocks any value";
    }
    $("thrval").textContent = "−" + (state.t === "custom" ? state.thr.toFixed(1) : Math.abs(get(M.triggers, state.t).threshold * 100)) + "%";
  }
  let sliderTimer = null;
  $("thr").addEventListener("input", () => {
    const inp = $("thr");
    if (SERVER !== null) { state.t = "custom"; state.thr = parseFloat(inp.value); }
    else { state.t = GRID[parseInt(inp.value, 10)].id; state.thr = null; }
    $("thrval").textContent = "−" + (state.thr != null ? state.thr.toFixed(1) : Math.abs(get(M.triggers, state.t).threshold * 100)) + "%";
    clearTimeout(sliderTimer);
    sliderTimer = setTimeout(() => update(false), SERVER !== null ? 220 : 60);
  });

  // ---------- renderers ----------
  function renderStats(r) {
    const cells = r ? [
      ["next " + (get(M.horizons, state.h).h === 1 ? "session" : "5 sessions") + " up", r.up + "%", ""],
      ["mean", f2(r.mean), "t = " + (r.t == null ? "—" : r.t)],
      ["sample", "n = " + r.n, r.n < 15 ? "small — read with care" : ""],
      ["95% CI", `${f2(r.ci_lo)} · ${f2(r.ci_hi)}`,
        r.ci_lo != null && r.ci_lo <= 0 && r.ci_hi >= 0 ? "straddles zero" : "clears zero"],
    ] : [["no data", "—", "combo pruned (n<3) or live-only"], ["", "—", ""], ["", "—", ""], ["", "—", ""]];
    $("stats").innerHTML = cells.map(([l, v, s]) =>
      `<div class="stat"><div class="l">${esc(l)}&nbsp;</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}&nbsp;</div></div>`).join("");
    if (PIN && PIN.res && r) {
      const d = (r.up - PIN.res.up).toFixed(1);
      $("stats").children[0].querySelector(".s").textContent = `pinned ${PIN.res.up}% · Δ ${d >= 0 ? "+" : ""}${d}pp`;
    }
  }

  async function renderRegimes(cur) {
    const wrap = $("regimes");
    const outs = await Promise.all(M.conditions.map(async (c) => {
      try {
        const r = (c.id === state.c) ? cur : await getResult(state.s, state.t, state.wd, c.id, state.h, state.thr);
        return { id: c.id, label: c.label, r };
      } catch (e) { return { id: c.id, label: c.label, r: null }; }
    }));
    const rows = outs.filter((o) => o.r && o.r.n >= 3).sort((a, b) => b.r.up - a.r.up);
    wrap.innerHTML = rows.map((o) =>
      `<div class="regrow${o.id === state.c ? " cur" : ""}" data-c="${esc(o.id)}">
         <div class="rl" title="${esc(o.label)}">${esc(o.label.replace(/\s*\(.*\)\s*$/, ""))}</div>
         <div class="track"><div class="mark50" style="left:50%"></div>
           <div class="bar" style="width:0%"></div></div>
         <div class="rv">${o.r.up}% <span style="color:var(--platinum)">·</span> ${o.r.n}</div>
       </div>`).join("") || `<div class="note">no regime data for this combo</div>`;
    const els = wrap.querySelectorAll(".regrow");
    els.forEach((el) => { el.onclick = () => { state.c = el.dataset.c; update(true); }; });
    void wrap.offsetWidth;   // commit width:0 so the transition tweens (rAF-free: rAF stalls in background tabs)
    els.forEach((el, i) => { el.querySelector(".bar").style.width = Math.max(2, rows[i].r.up) + "%"; });
  }

  function renderHist(r) {
    const hist = $("hist"), labels = $("binlabels");
    const counts = r ? r.counts : new Array(M.bin_labels ? M.bin_labels.length : 14).fill(0);
    const bl = M.bin_labels;
    const maxC = Math.max(1, ...counts, ...(PIN && PIN.res ? PIN.res.counts : [0]));
    if (hist.children.length !== counts.length) {
      hist.innerHTML = counts.map((_, i) =>
        `<div class="bin${i <= 6 ? " neg" : ""}${i === 7 ? " zero" : ""}" data-i="${i}">
           <div class="ghost" style="height:0; display:none;"></div>
           <div class="fill" style="height:0"></div></div>`).join("");
      labels.innerHTML = bl.map((b, i) => `<span>${i % 2 ? "" : esc(b)}</span>`).join("");
    }
    [...hist.children].forEach((bin, i) => {
      bin.querySelector(".fill").style.height = (counts[i] / maxC * 100).toFixed(1) + "%";
      const g = bin.querySelector(".ghost");
      if (PIN && PIN.res) { g.style.display = "block"; g.style.height = (PIN.res.counts[i] / maxC * 100).toFixed(1) + "%"; }
      else g.style.display = "none";
      bin.dataset.tip = `${bl[i]}%: ${counts[i]} event${counts[i] === 1 ? "" : "s"}`;
      bin.onmouseenter = () => highlightRows(i);
      bin.onmouseleave = () => highlightRows(null);
    });
  }

  function renderOcc(r) {
    lastRows = r && r.rows;
    if (SERVER === null) {
      $("occsub").textContent = "· live mode only";
      $("occ").innerHTML = `<div class="note">The per-event list needs the live backend:&nbsp; <b>./.venv/bin/python serve.py</b> &nbsp;then open <b>localhost:8765/market-lab.html</b></div>`;
      return;
    }
    if (!lastRows || !lastRows.length) { $("occsub").textContent = ""; $("occ").innerHTML = `<div class="note">no events</div>`; return; }
    const rows = lastRows.filter((x) => x.outcome_ret != null);
    $("occsub").textContent = `· ${rows.length} events · hover a histogram bin to highlight`;
    $("occ").innerHTML = `<table><tr><th>trigger</th><th style="text-align:right">move</th><th>outcome session</th><th style="text-align:right">return</th><th></th></tr>` +
      rows.slice(0, 100).map((x) =>
        `<tr data-ret="${x.outcome_ret}"><td>${DOWN[x.trigger_dow] || ""} ${x.trigger_date}</td><td class="r">${f2(x.trigger_ret)}</td>` +
        `<td>${DOWN[x.outcome_dow] || ""} ${x.outcome_date || ""}</td><td class="r">${f2(x.outcome_ret)}</td>` +
        `<td class="${x.outcome_ret < 0 ? "dn" : "up"}">${x.outcome_ret < 0 ? "down" : "up"}</td></tr>`).join("") +
      `</table>` + (rows.length > 100 ? `<div class="note">showing 100 of ${rows.length}</div>` : "");
  }
  function highlightRows(binIdx) {
    if (SERVER === null || !lastRows) return;
    const E = M.bin_edges;
    document.querySelectorAll("#occ tr[data-ret]").forEach((tr) => {
      const v = parseFloat(tr.dataset.ret);
      tr.classList.toggle("hl", binIdx != null && v >= E[binIdx] && v < E[binIdx + 1]);
    });
  }

  // ---------- pin ----------
  $("pin").onclick = async () => {
    const r = await safeResult();
    if (!r) return;
    PIN = { label: `${get(M.subjects, state.s).label} · ${trigLabel()} · ${state.wd} · ${state.c}`, res: r };
    renderPinChip(); update(false);
  };
  function renderPinChip() {
    const c = $("pinchip");
    if (!PIN) { c.style.display = "none"; return; }
    c.style.display = "inline-flex";
    c.innerHTML = `pinned: <b>${esc(PIN.label)}</b> · up ${PIN.res.up}% · mean ${f2(PIN.res.mean)} <span class="x" id="unpin">✕</span>`;
    $("unpin").onclick = () => { PIN = null; renderPinChip(); update(false); };
  }

  // ---------- presets ----------
  const PRESETS = [
    ["NDX bad Fridays", { s: "ndx", t: "d4", wd: "fri", c: "none", h: "h1" }],
    ["crash Friday + VIX backwardated", { s: "spy", t: "d25", wd: "fri", c: "vix_bw", h: "h1" }],
    ["dip-buy in uptrend", { s: "spy", t: "d3", wd: "any", c: "up", h: "h1" }],
    ["semis worst 20 → next week", { s: "smh", t: "w20", wd: "any", c: "none", h: "h5" }],
    ["−2% day while yields rising", { s: "spy", t: "d2", wd: "any", c: "tnx_up", h: "h1" }],
  ];
  PRESETS.forEach(([label, st]) => {
    const b = document.createElement("button");
    b.textContent = label;
    b.onclick = () => { Object.assign(state, { thr: null }, st); update(true); };
    $("presets").appendChild(b);
  });

  // ---------- tooltip ----------
  const tip = $("tip");
  document.addEventListener("pointermove", (e) => {
    const t = e.target.closest && e.target.closest("[data-tip]");
    if (t) {
      tip.textContent = t.dataset.tip; tip.style.display = "block";
      tip.style.left = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 10) + "px";
      tip.style.top = (e.clientY + 14) + "px";
    } else tip.style.display = "none";
  });

  // ---------- main ----------
  async function safeResult() {
    try { return await getResult(state.s, state.t, state.wd, state.c, state.h, state.thr); }
    catch (e) {
      // live backend hiccup — fall back to the offline cube for on-grid combos
      if (SERVER !== null && state.t !== "custom") {
        try {
          await loadShard(state.s);
          const r = norm((L.shards[state.s] || {})[`${state.t}|${state.wd}|${state.c}|${state.h}`]);
          if (r) { $("mode").textContent = "Live (cube fallback: " + e.message + ")"; return r; }
        } catch (e2) {}
      }
      $("mode").textContent = "error: " + e.message;
      return null;
    }
  }
  let seq = 0;
  async function update(push) {
    const my = ++seq;
    renderSentence(); renderSlider(); writeHash(push);
    $("histsub").textContent = "· " + get(M.horizons, state.h).label.toLowerCase() + " return";
    const r = await safeResult();
    if (my !== seq) return;                       // stale async render
    renderStats(r); renderHist(r); renderOcc(r);
    renderRegimes(r);
    $("footnote").textContent = r && r.n < 15
      ? "Small sample — treat the split as descriptive history, not an edge. Pruned combos (n<3) are grayed out in the pickers."
      : "Close-to-close returns; outcome = next trading session(s), holiday-robust. Offline cube CI is a t-approximation.";
  }

  async function detect() {
    for (const base of ["", "http://localhost:8765", "http://localhost:8775"]) {
      try {
        const r = await fetch(base + "/api/health", { cache: "no-store" });
        if (r.ok) { const j = await r.json(); if (j.ok) { SERVER = base; $("mode").textContent = `Live · ${j.tickers} tickers`; return; } }
      } catch (e) {}
    }
    $("mode").textContent = "Offline · cube";
  }

  window.addEventListener("hashchange", () => { readHash(); update(false); });
  $("asof").textContent = "as of " + L.meta.as_of + " ";
  readHash();
  detect().then(() => update(false));
})();
