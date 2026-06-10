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
  // ---------- offline occurrence engine ----------
  // Recomputes the per-event rows client-side from the compact daily series in
  // each shard (same close-to-close semantics as serve.py's event_study).
  function decodeSeries(raw) {
    const n = raw.dd.length + 1, days = new Array(n);
    days[0] = raw.d0;
    for (let i = 1; i < n; i++) days[i] = days[i - 1] + raw.dd[i - 1];
    return { days, close: raw.c.map(x => x / 100000),
             open: raw.o ? raw.o.map(x => x / 100000) : null };
  }
  const isodow = (day) => { const d = new Date(day * 86400000).getUTCDay(); return d === 0 ? 7 : d; };
  const dstr = (day) => new Date(day * 86400000).toISOString().slice(0, 10);
  function rollMA(arr, win) {           // min_periods=1, matches the cube build
    const out = new Array(arr.length); let sum = 0; const q = [];
    for (let i = 0; i < arr.length; i++) {
      q.push(arr[i]); sum += arr[i];
      if (q.length > win) sum -= q.shift();
      out[i] = sum / q.length;
    }
    return out;
  }
  function featureMaps(raw) {
    const s = decodeSeries(raw);
    const val = new Map(), prev = new Map(), ret = new Map(), rprev = new Map(), ma50 = new Map();
    const ma = rollMA(s.close, 50);
    for (let i = 0; i < s.days.length; i++) {
      const d = s.days[i];
      val.set(d, s.close[i]); ma50.set(d, ma[i]);
      if (i > 0) { prev.set(d, s.close[i - 1]); ret.set(d, s.close[i] / s.close[i - 1] - 1); }
      if (i > 1) rprev.set(d, s.close[i - 1] / s.close[i - 2] - 1);
    }
    return { val, prev, ret, rprev, ma50 };
  }
  let CONDM = null;
  function loadCondJs() {
    return new Promise((res, rej) => {
      if (L.cond) return res();
      const sc = document.createElement("script");
      sc.src = "cube/conditioners.js";
      sc.onload = () => res();
      sc.onerror = () => rej(new Error("conditioners.js not found"));
      document.body.appendChild(sc);
    });
  }
  function condMask(id, subj) {         // exact-date alignment; missing -> false
    const n = subj.days.length, m = new Array(n).fill(true);
    const F = (ser) => CONDM[ser];
    const apply = (fn) => { for (let i = 0; i < n; i++) m[i] = fn(subj.days[i], i) === true; };
    switch (id) {
      case "none": break;
      case "up":          apply((d, i) => subj.close[i] > subj.ma200[i]); break;
      case "down":        apply((d, i) => subj.close[i] < subj.ma200[i]); break;
      case "vix_hi":      apply((d) => F("vix").val.get(d) > 30); break;
      case "vix_lo":      apply((d) => F("vix").val.get(d) < 20); break;
      case "vixprev_hi":  apply((d) => F("vix").prev.get(d) >= 25); break;
      case "gold_up":     apply((d) => F("gold").ret.get(d) > 0); break;
      case "gold_dn":     apply((d) => F("gold").ret.get(d) < 0); break;
      case "cu_up":       apply((d) => F("copper").val.get(d) > F("copper").ma50.get(d)); break;
      case "cu_dn":       apply((d) => F("copper").val.get(d) < F("copper").ma50.get(d)); break;
      case "tnx_up":      apply((d) => F("tnx").val.get(d) > F("tnx").ma50.get(d)); break;
      case "tnx_dn":      apply((d) => F("tnx").val.get(d) < F("tnx").ma50.get(d)); break;
      case "credit_wide": apply((d) => F("hyg").val.get(d) < F("hyg").ma50.get(d)); break;
      case "usd_up":      apply((d) => F("uup").val.get(d) > F("uup").ma50.get(d)); break;
      case "vix_bw":      apply((d) => F("vix3m").val.get(d) < F("vix").val.get(d)); break;
      case "oil_up":      apply((d) => F("wti").val.get(d) > F("wti").ma50.get(d)); break;
      case "prev_dn":  apply((d, i) => i >= 2 && subj.ret[i - 1] < 0); break;
      case "prev_up":  apply((d, i) => i >= 2 && subj.ret[i - 1] > 0); break;
      case "prev_dn1": apply((d, i) => i >= 2 && subj.ret[i - 1] <= -0.01); break;
      case "prev_dn2": apply((d, i) => i >= 2 && subj.ret[i - 1] <= -0.02); break;
      case "prev_up1": apply((d, i) => i >= 2 && subj.ret[i - 1] >= 0.01); break;
      case "spy_prev_dn1": apply((d) => F("spy").rprev.get(d) <= -0.01); break;
      case "spy_prev_dn2": apply((d) => F("spy").rprev.get(d) <= -0.02); break;
      default: return null;
    }
    return m;
  }
  const SELF_CONTAINED = ["none", "up", "down", "prev_dn", "prev_up", "prev_dn1", "prev_dn2", "prev_up1"];
  async function computeRows(s, t, wd, c, h) {
    const raw = L.series && L.series[s];
    if (!raw) return null;
    if (!SELF_CONTAINED.includes(c)) {
      await loadCondJs();
      if (!CONDM) {
        CONDM = {};
        for (const k of Object.keys(L.cond)) CONDM[k] = featureMaps(L.cond[k]);
      }
    }
    const ser = decodeSeries(raw);
    const N = ser.days.length, ret = new Array(N).fill(NaN);
    for (let i = 1; i < N; i++) ret[i] = ser.close[i] / ser.close[i - 1] - 1;
    const subj = { days: ser.days, close: ser.close, ret,
                   ma200: (c === "up" || c === "down") ? rollMA(ser.close, 200) : null };
    const mask = condMask(c, subj);
    if (!mask) return null;
    const H = get(M.horizons, h).h, WD = get(M.weekdays, wd), T = get(M.triggers, t);
    let idx = [];
    if (T.streak != null) {
      // fire on the day the run count hits exactly N (matches the SQL engine)
      if (T.gap && !ser.open) return null;
      let run = 0;
      for (let i = 1; i < N; i++) {
        const dirOK = T.dir === "dn" ? ser.close[i] < ser.close[i - 1] : ser.close[i] > ser.close[i - 1];
        const gapOK = !T.gap ? true : (T.gap === "up" ? ser.open[i] > ser.close[i - 1]
                                                      : ser.open[i] < ser.close[i - 1]);
        run = (dirOK && gapOK) ? run + 1 : 0;
        if (run === T.streak && mask[i] && (WD.day == null || isodow(ser.days[i]) === WD.day)) idx.push(i);
      }
      idx.sort((x, y) => y - x);
    } else {
      for (let i = 1; i < N; i++) {
        if (!mask[i]) continue;
        if (WD.day != null && isodow(ser.days[i]) !== WD.day) continue;
        if (T.threshold != null) { if (ret[i] <= T.threshold) idx.push(i); }
        else idx.push(i);
      }
      if (T.worst_n != null) { idx.sort((x, y) => ret[x] - ret[y]); idx = idx.slice(0, T.worst_n); }
      else idx.sort((x, y) => y - x);   // trigger_date DESC, like the server
    }
    return idx.map(i => {
      const j = i + H, pend = j >= N;
      return { trigger_date: dstr(ser.days[i]), trigger_dow: isodow(ser.days[i]),
               trigger_ret: Math.round(ret[i] * 10000) / 100,
               outcome_date: pend ? null : dstr(ser.days[j]),
               outcome_dow: pend ? null : isodow(ser.days[j]),
               outcome_ret: pend ? null : Math.round((ser.close[j] / ser.close[i] - 1) * 10000) / 100 };
    });
  }
  window.__rows = computeRows;          // programmatic hook (tests/console)

  // analytic stats from locally-computed rows — covers combos the cube pruned
  // (n<3) or never enumerated, so nothing in the menus needs graying out
  const TCRIT = [12.71, 4.30, 3.18, 2.78, 2.57, 2.45, 2.36, 2.31, 2.26, 2.23, 2.20, 2.18, 2.16,
                 2.14, 2.13, 2.12, 2.11, 2.10, 2.09, 2.09, 2.08, 2.07, 2.07, 2.06, 2.06, 2.06,
                 2.05, 2.05, 2.05, 2.04];
  const tcrit = (df) => df <= 0 ? NaN : df <= 30 ? TCRIT[df - 1] : 1.96 + 2.4 / df;
  function statsFromRows(rows) {
    const v = rows.map(r => r.outcome_ret).filter(x => x != null);
    const E = M.bin_edges, counts = new Array(E.length - 1).fill(0);
    for (const x of v) for (let i = 0; i < counts.length; i++) if (x >= E[i] && x < E[i + 1]) { counts[i]++; break; }
    const n = v.length;
    if (!n) return { n: 0, up: null, mean: null, t: null, ci_lo: null, ci_hi: null, counts, rows: null };
    const mean = v.reduce((a, b) => a + b, 0) / n;
    const up = v.filter(x => x > 0).length / n * 100;
    const sd = n > 1 ? Math.sqrt(v.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1)) : 0;
    const se = sd / Math.sqrt(n), tc = tcrit(n - 1);
    const r3 = (x) => Math.round(x * 1000) / 1000;
    return { n, up: Math.round(up * 100) / 100, mean: r3(mean),
             t: sd > 0 ? Math.round(mean / se * 100) / 100 : null,
             ci_lo: sd > 0 ? r3(mean - tc * se) : r3(mean),
             ci_hi: sd > 0 ? r3(mean + tc * se) : r3(mean), counts, rows: null };
  }

  async function getResult(s, t, wd, c, h, thr) {
    if (SERVER === null) {
      if (t === "custom") return null;            // custom thresholds are live-only
      await loadShard(s);
      let base = norm((L.shards[s] || {})[`${t}|${wd}|${c}|${h}`]);
      let rows = null;
      try { rows = await computeRows(s, t, wd, c, h); } catch (e) {}
      if (!base && rows) base = statsFromRows(rows);   // cube-pruned combo: compute locally
      if (base) base.rows = rows;
      return base;
    }
    const T = t === "custom" ? null : get(M.triggers, t);
    const q = new URLSearchParams({ subject: s, horizon: get(M.horizons, h).h });
    if (t === "custom") q.set("threshold", (-thr / 100).toFixed(4));
    else if (T.threshold != null) q.set("threshold", T.threshold);
    else if (T.streak != null) {
      q.set("streak_n", T.streak);
      q.set("streak_dir", T.dir === "dn" ? "down" : "up");
      if (T.gap) q.set("streak_gap", T.gap);
    }
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

  function available(dim, id) {
    // every on-grid combo is computable now (cube hit, or local row engine for
    // pruned combos) — so nothing in the pickers needs graying out
    return true;
  }

  // ---------- sentence ----------
  function trigLabel() {
    if (state.t === "custom") return `falls ≥ ${state.thr.toFixed(1)}%`;
    const T = get(M.triggers, state.t);
    if (T.streak != null)
      return `closes ${T.dir === "dn" ? "red" : "green"} ${T.streak} days in a row` +
             (T.gap ? `, each gapping ${T.gap}` : "");
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
        } else if (d === "t") {
          const order = [], byG = {};
          for (const o of M.triggers) {
            const g = o.group || "Single-day moves";
            if (!byG[g]) { order.push(g); byG[g] = []; }
            byG[g].push(o);
          }
          items = [];
          for (const g of order) {
            items.push({ group: g });
            byG[g].forEach((o) => items.push({ id: o.id, label: o.label, sel: o.id === state.t }));
          }
          if (SERVER !== null) items.push({ id: "custom", label: "custom threshold (slider)", sel: state.t === "custom" });
        } else {
          const src = { wd: M.weekdays, c: M.conditions, h: M.horizons }[d];
          items = src.map((o) => ({ id: o.id, label: o.label, sel: o.id === state[d], dis: !available(d, o.id) }));
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
    if (!lastRows) {
      $("occsub").textContent = "";
      $("occ").innerHTML = `<div class="note">Event list unavailable for this combo.</div>`;
      return;
    }
    if (!lastRows.length) { $("occsub").textContent = ""; $("occ").innerHTML = `<div class="note">no events</div>`; return; }
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
    if (!lastRows) return;
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
