"""
Pre-compute an event-study CUBE for the Trader Profile's interactive panel.

For every combination of {subject × trigger × weekday × condition × horizon} on a
curated ~19-symbol universe, run event_study and store a compact result (sample
size, next-session up-rate, mean, t-stat, 95% CI, and a fixed-bin return
histogram). Combos with n<MIN_N are pruned. The whole thing ships as
`trader-profile-cube.js` (`window.QUANT_CUBE`) next to the HTML, so the panel
works on a plain double-click with zero backend.

The `menus` block is the single source of truth for the dropdowns AND for the
raw event_study params — the live server (serve.py) reuses the same ids.

    python -m export.cube              # default reports dir
    python -m export.cube /some/dir
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

sys.path.insert(0, str(Path(__file__).parent.parent))
import db
from analysis.events import event_study, summarize_event, MON, TUE, WED, THU, FRI

DEFAULT_OUT = Path.home() / "Desktop/Obsidian/trading-brain/reports"
MIN_N = 3  # prune combos with fewer events than this

# ---- menus (ids are stable; labels drive the dropdowns; params drive the calc)
SUBJECTS = [
    {"id": "spy", "label": "S&P 500 (SPY)"}, {"id": "qqq", "label": "Nasdaq-100 (QQQ)"},
    {"id": "ndx", "label": "Nasdaq-100 (NDX)"}, {"id": "ixic", "label": "Nasdaq Composite"},
    {"id": "xlk", "label": "Technology (XLK)"}, {"id": "xlf", "label": "Financials (XLF)"},
    {"id": "xlv", "label": "Health Care (XLV)"}, {"id": "xle", "label": "Energy (XLE)"},
    {"id": "xli", "label": "Industrials (XLI)"}, {"id": "xly", "label": "Cons. Disc. (XLY)"},
    {"id": "xlc", "label": "Comm. Svcs (XLC)"}, {"id": "xlp", "label": "Cons. Staples (XLP)"},
    {"id": "xlu", "label": "Utilities (XLU)"}, {"id": "xlre", "label": "Real Estate (XLRE)"},
    {"id": "xlb", "label": "Materials (XLB)"}, {"id": "vix", "label": "VIX"},
    {"id": "gold", "label": "Gold"}, {"id": "silver", "label": "Silver"},
    {"id": "copper", "label": "Copper"},
    # macro cross-asset
    {"id": "tlt", "label": "20Y Treasuries (TLT)"}, {"id": "ief", "label": "7-10Y Treasuries (IEF)"},
    {"id": "hyg", "label": "High Yield (HYG)"}, {"id": "lqd", "label": "IG Credit (LQD)"},
    {"id": "tnx", "label": "10Y Yield (TNX)"}, {"id": "vix3m", "label": "VIX 3-Month"},
    {"id": "uup", "label": "US Dollar (UUP)"}, {"id": "wti", "label": "WTI Crude"},
    # thematic sub-sectors
    {"id": "smh", "label": "Semis (SMH)"}, {"id": "xbi", "label": "Biotech (XBI)"},
    {"id": "kre", "label": "Regional Banks (KRE)"}, {"id": "xop", "label": "Oil E&P (XOP)"},
    {"id": "oih", "label": "Oil Services (OIH)"}, {"id": "gdx", "label": "Gold Miners (GDX)"},
    {"id": "tan", "label": "Solar (TAN)"}, {"id": "icln", "label": "Clean Energy (ICLN)"},
    {"id": "xhb", "label": "Homebuilders (XHB)"}, {"id": "xrt", "label": "Retail (XRT)"},
    {"id": "arkk", "label": "Innovation (ARKK)"}, {"id": "kweb", "label": "China Internet (KWEB)"},
    {"id": "jets", "label": "Airlines (JETS)"},
    # industry ETFs
    {"id": "ita", "label": "Defense & Aero (ITA)"}, {"id": "igv", "label": "Software (IGV)"},
    {"id": "cibr", "label": "Cybersecurity (CIBR)"}, {"id": "botz", "label": "Robotics (BOTZ)"},
    {"id": "ign", "label": "Networking (IGN)"}, {"id": "ura", "label": "Nuclear/Uranium (URA)"},
    {"id": "xme", "label": "Metals & Mining (XME)"}, {"id": "idrv", "label": "EV / Auto (IDRV)"},
    {"id": "ufo", "label": "Space (UFO)"}, {"id": "grid", "label": "Electrification (GRID)"},
    {"id": "ibit", "label": "Bitcoin (IBIT)"}, {"id": "pave", "label": "Infrastructure/EPC (PAVE)"},
    {"id": "fivg", "label": "Connectivity/5G (FIVG)"},
    # AI/chip value-chain baskets (equal-weight, daily-rebalanced single-stock indices)
    {"id": "gpu", "label": "GPU (basket)"}, {"id": "cpuasic", "label": "CPU+ASIC (basket)"},
    {"id": "memory", "label": "Memory (basket)"}, {"id": "semicap", "label": "Semicap (basket)"},
    {"id": "powersemi", "label": "Power Semis (basket)"}, {"id": "photonics", "label": "Photonics (basket)"},
    {"id": "aiserver", "label": "AI Servers (basket)"}, {"id": "hyperscale", "label": "Hyperscalers (basket)"},
    {"id": "neocloud", "label": "Neocloud (basket)"}, {"id": "cdnedge", "label": "CDN/Edge (basket)"},
    {"id": "solutil", "label": "Solar—Utility (basket)"}, {"id": "solresi", "label": "Solar—Resi (basket)"},
]
TRIGGERS = [
    {"id": "d1", "label": "Down ≥ 1%", "threshold": -0.01},
    {"id": "d2", "label": "Down ≥ 2%", "threshold": -0.02},
    {"id": "d25", "label": "Down ≥ 2.5%", "threshold": -0.025},
    {"id": "d3", "label": "Down ≥ 3%", "threshold": -0.03},
    {"id": "d4", "label": "Down ≥ 4%", "threshold": -0.04},
    {"id": "d5", "label": "Down ≥ 5%", "threshold": -0.05},
    {"id": "w20", "label": "Worst 20 days", "worst_n": 20},
    {"id": "w50", "label": "Worst 50 days", "worst_n": 50},
]
WEEKDAYS = [
    {"id": "any", "label": "Any day", "day": None},
    {"id": "mon", "label": "Monday", "day": MON},
    {"id": "tue", "label": "Tuesday", "day": TUE},
    {"id": "wed", "label": "Wednesday", "day": WED},
    {"id": "thu", "label": "Thursday", "day": THU},
    {"id": "fri", "label": "Friday", "day": FRI},
]
CONDITIONS = [
    {"id": "none", "label": "— none —", "when": None},
    {"id": "vix_hi", "label": "VIX > 30 (panic)", "when": "vix>30"},
    {"id": "vix_lo", "label": "VIX < 20 (calm)", "when": "vix<20"},
    {"id": "vixprev_hi", "label": "Entered stressed (VIX_prev ≥ 25)", "when": "vix_prev>=25"},
    {"id": "up", "label": "Subject in uptrend (>200DMA)", "when": "{subj}>{subj}_200dma"},
    {"id": "down", "label": "Subject in downtrend (<200DMA)", "when": "{subj}<{subj}_200dma"},
    {"id": "gold_up", "label": "Gold up that day", "when": "gold_up"},
    {"id": "gold_dn", "label": "Gold down that day", "when": "gold_down"},
    {"id": "cu_up", "label": "Copper > 50DMA (growth)", "when": "copper>copper_50dma"},
    {"id": "cu_dn", "label": "Copper < 50DMA (scare)", "when": "copper<copper_50dma"},
    # macro regime gates
    {"id": "tnx_up", "label": "Yields rising (10Y > 50DMA)", "when": "tnx>tnx_50dma"},
    {"id": "tnx_dn", "label": "Yields falling (10Y < 50DMA)", "when": "tnx<tnx_50dma"},
    {"id": "credit_wide", "label": "Credit widening (HYG < 50DMA)", "when": "hyg<hyg_50dma"},
    {"id": "usd_up", "label": "Dollar strong (UUP > 50DMA)", "when": "uup>uup_50dma"},
    {"id": "vix_bw", "label": "VIX backwardated (VIX3M < VIX)", "when": "vix3m<vix"},
    {"id": "oil_up", "label": "Oil rising (WTI > 50DMA)", "when": "wti>wti_50dma"},
]
HORIZONS = [
    {"id": "h1", "label": "Next session", "h": 1},
    {"id": "h5", "label": "Next 5 sessions", "h": 5},
]
# fixed histogram edges (% return); -inf/+inf tails capture extremes
EDGES = [-1e9, -6, -5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5, 6, 1e9]
BIN_LABELS = ["≤−6", "−6:−5", "−5:−4", "−4:−3", "−3:−2", "−2:−1", "−1:0",
              "0:1", "1:2", "2:3", "3:4", "4:5", "5:6", "≥6"]

# Subject dropdown groupings (for <optgroup> in the panel).
_GROUPS = {
    "Indices": ["spy", "qqq", "ndx", "ixic"],
    "Sectors": ["xlk", "xlf", "xlv", "xle", "xli", "xly", "xlc", "xlp", "xlu", "xlre", "xlb"],
    "Sub-sectors": ["smh", "xbi", "kre", "xop", "oih", "gdx", "tan", "icln",
                    "xhb", "xrt", "arkk", "kweb", "jets"],
    "Industry ETFs": ["ita", "igv", "cibr", "botz", "ign", "ura", "xme", "idrv",
                      "ufo", "grid", "ibit", "pave", "fivg"],
    "AI / chip baskets": ["gpu", "cpuasic", "memory", "semicap", "powersemi", "photonics",
                          "aiserver", "hyperscale", "neocloud", "cdnedge", "solutil", "solresi"],
    "Macro (rates/credit/FX/vol)": ["tlt", "ief", "hyg", "lqd", "tnx", "uup", "vix", "vix3m"],
    "Commodities": ["gold", "silver", "copper", "wti"],
}
_ID2GROUP = {i: g for g, ids in _GROUPS.items() for i in ids}


_FLAG = re.compile(r"([a-z0-9]+)_(up|down)\b")


def _feats(conn, view, specs):
    """Feature columns computed on a view's OWN series — matches event_study's per-series window."""
    c = conn.execute(f'select date, close from "{view}" order by date').df()
    c["date"] = pd.to_datetime(c["date"])
    c = c.set_index("date")["close"]
    out = {n: (c if k == "val" else c.shift(1) if k == "prev"
               else c.pct_change() if k == "ret" else c.rolling(int(k), min_periods=1).mean())
           for n, k in specs.items()}
    return pd.DataFrame(out)


def build(conn):
    """Vectorized: pull each subject once, evaluate every combo in numpy (no per-combo query).
    Conditioner features are computed on each series' OWN history, then aligned per subject —
    so results match event_study's SQL semantics. ~30s vs ~15 min for the per-combo version."""
    # conditioner features keyed by grammar-token name (each on its own series), joined by date
    G = pd.concat([
        _feats(conn, "vix",    {"vix": "val", "vix_prev": "prev"}),
        _feats(conn, "vix3m",  {"vix3m": "val"}),
        _feats(conn, "gold",   {"gold_ret": "ret"}),
        _feats(conn, "copper", {"copper": "val", "copper_50dma": "50"}),
        _feats(conn, "tnx",    {"tnx": "val", "tnx_50dma": "50"}),
        _feats(conn, "hyg",    {"hyg": "val", "hyg_50dma": "50"}),
        _feats(conn, "uup",    {"uup": "val", "uup_50dma": "50"}),
        _feats(conn, "wti",    {"wti": "val", "wti_50dma": "50"}),
    ], axis=1).sort_index()
    hz = {h["h"]: h["id"] for h in HORIZONS}

    results, kept, total = {}, 0, 0
    for s in SUBJECTS:
        c = conn.execute(f'select date, close from "{s["id"]}" order by date').df()
        c["date"] = pd.to_datetime(c["date"])
        close = c.set_index("date")["close"]
        ret = close.pct_change().to_numpy()
        retfin = np.isfinite(ret)
        isodow = np.asarray(close.index.dayofweek) + 1
        out_h = {h: (close.shift(-h) / close - 1).to_numpy() for h in hz}

        F = G.reindex(close.index)
        F["SUBJ"] = close.to_numpy()
        F["SUBJ_200dma"] = close.rolling(200, min_periods=1).mean().to_numpy()
        cmask = {}
        for cond in CONDITIONS:
            if cond["when"] is None:
                cmask[cond["id"]] = np.ones(len(F), bool)
            else:
                expr = _FLAG.sub(lambda m: f"({m.group(1)}_ret{'>' if m.group(2) == 'up' else '<'}0)",
                                 cond["when"].replace("{subj}", "SUBJ"))
                cmask[cond["id"]] = F.eval(expr).fillna(False).to_numpy(dtype=bool)

        for t in TRIGGERS:
            thr, wn = t.get("threshold"), t.get("worst_n")
            for wd in WEEKDAYS:
                wmask = retfin if wd["day"] is None else (retfin & (isodow == wd["day"]))
                for cond in CONDITIONS:
                    base = wmask & cmask[cond["id"]]
                    if thr is not None:
                        sel = np.where(base & (ret <= thr))[0]
                    else:
                        idx = np.where(base)[0]
                        sel = idx[np.argsort(ret[idx], kind="stable")][:wn]
                    for h, hid in hz.items():
                        total += 1
                        v = out_h[h][sel]
                        v = v[np.isfinite(v)] * 100.0
                        n = len(v)
                        if n < MIN_N:
                            continue
                        mean = float(v.mean())
                        up = float((v > 0).mean()) * 100.0
                        sd = float(v.std(ddof=1)) if n > 1 else 0.0
                        if sd > 0:
                            se = sd / np.sqrt(n)
                            tstat = round(mean / se, 2)
                            tc = float(sps.t.ppf(0.975, n - 1))
                            ci_lo, ci_hi = mean - tc * se, mean + tc * se
                        else:
                            tstat, ci_lo, ci_hi = None, mean, mean
                        counts = np.histogram(v, bins=EDGES)[0]
                        key = f'{s["id"]}|{t["id"]}|{wd["id"]}|{cond["id"]}|{hid}'
                        results[key] = [n, round(up, 1), round(mean, 3), tstat,
                                        round(ci_lo, 3), round(ci_hi, 3), *[int(x) for x in counts]]
                        kept += 1
        print(f"  {s['id']:6} done · kept {kept}")
    return results, kept, total


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = db.connect()
    as_of = conn.execute("select max(date) from spy").fetchone()[0]
    results, kept, total = build(conn)
    cube = {
        "meta": {
            "as_of": str(as_of), "kept": kept, "total": total,
            "schema": ["n", "up_pct", "mean_pct", "t", "ci_lo", "ci_hi", "...14 hist counts"],
            "note": "Pre-computed event studies. Combos with n<%d pruned. Use the live "
                    "server for arbitrary tickers/thresholds and the full event list." % MIN_N,
        },
        "menus": {
            "subjects": [{**s, "group": _ID2GROUP.get(s["id"], "Other")} for s in SUBJECTS],
            "triggers": TRIGGERS, "weekdays": WEEKDAYS,
            "conditions": CONDITIONS, "horizons": HORIZONS,
            "bin_labels": BIN_LABELS,
        },
        "results": results,
    }
    payload = "window.QUANT_CUBE = " + json.dumps(cube, separators=(",", ":")) + ";\n"
    out = out_dir / "trader-profile-cube.js"
    out.write_text(payload)
    print(f"\nWrote {out}  ({len(payload):,} bytes)  kept {kept}/{total} combos")


if __name__ == "__main__":
    main()
