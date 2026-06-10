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
from ingestion.baskets import BASKETS

# Short display names for basket constituents (market-lab-baskets.html).
MEMBER_NAMES = {
    "NVDA": "Nvidia", "AMD": "AMD", "TSM": "Taiwan Semi (ADR)", "INTC": "Intel",
    "AVGO": "Broadcom", "MRVL": "Marvell", "QCOM": "Qualcomm", "ARM": "Arm",
    "MU": "Micron", "WDC": "Western Digital", "STX": "Seagate", "SNDK": "SanDisk",
    "AMAT": "Applied Materials", "LRCX": "Lam Research", "KLAC": "KLA", "ASML": "ASML",
    "PENG": "Penguin Solutions",
    "ON": "onsemi", "MPWR": "Monolithic Power", "STM": "STMicroelectronics",
    "POWI": "Power Integrations", "ALGM": "Allegro Micro", "WOLF": "Wolfspeed",
    "NXPI": "NXP Semi", "DIOD": "Diodes", "AOSL": "Alpha & Omega", "VSH": "Vishay",
    "COHR": "Coherent", "LITE": "Lumentum", "FN": "Fabrinet", "AXTI": "AXT",
    "AAOI": "Applied Opto", "GLW": "Corning", "VIAV": "Viavi",
    "CRDO": "Credo", "ALAB": "Astera Labs", "CSCO": "Cisco",
    "SMCI": "Super Micro", "DELL": "Dell", "HPE": "HPE", "ANET": "Arista", "VRT": "Vertiv",
    "AAPL": "Apple", "IBM": "IBM",
    "MSFT": "Microsoft", "GOOGL": "Alphabet", "AMZN": "Amazon", "META": "Meta", "ORCL": "Oracle",
    "CRWV": "CoreWeave", "NBIS": "Nebius", "APLD": "Applied Digital", "IREN": "IREN",
    "DOCN": "DigitalOcean", "CIFR": "Cipher Mining",
    "NET": "Cloudflare", "AKAM": "Akamai", "FSLY": "Fastly",
    "DDOG": "Datadog", "SNOW": "Snowflake",
    "PANW": "Palo Alto", "CRWD": "CrowdStrike", "S": "SentinelOne", "OKTA": "Okta", "ZS": "Zscaler",
    "ETN": "Eaton", "GEV": "GE Vernova", "CAT": "Caterpillar", "CMI": "Cummins",
    "AME": "AMETEK", "HUBB": "Hubbell", "GNRC": "Generac", "MOD": "Modine",
    "ENS": "EnerSys", "POWL": "Powell Industries",
    "PWR": "Quanta", "EME": "EMCOR", "MTZ": "MasTec", "FIX": "Comfort Systems",
    "STRL": "Sterling Infra", "PRIM": "Primoris", "IESC": "IES Holdings", "MYRG": "MYR Group",
    "FLR": "Fluor", "J": "Jacobs", "ECG": "Everus Construction",
    "CCJ": "Cameco", "CEG": "Constellation", "BWXT": "BWX Technologies", "OKLO": "Oklo",
    "NXE": "NexGen", "LEU": "Centrus", "SMR": "NuScale", "UUUU": "Energy Fuels", "XE": "X-Energy",
    "FSLR": "First Solar", "NXT": "Nextracker", "ARRY": "Array Technologies",
    "SHLS": "Shoals", "FLNC": "Fluence", "EOSE": "Eos Energy", "CWEN": "Clearway",
    "BE": "Bloom Energy", "PLUG": "Plug Power", "FCEL": "FuelCell", "BEP": "Brookfield Renewable",
    "SOLS": "Solstice Adv Materials",
    "ENPH": "Enphase", "SEDG": "SolarEdge", "RUN": "Sunrun",
    "LMT": "Lockheed", "RTX": "RTX", "NOC": "Northrop", "GD": "General Dynamics",
    "LHX": "L3Harris", "HII": "Huntington Ingalls", "BA": "Boeing", "TXT": "Textron",
    "LDOS": "Leidos", "TDG": "TransDigm", "HEI": "HEICO", "CW": "Curtiss-Wright",
    "OSK": "Oshkosh", "KTOS": "Kratos", "MRCY": "Mercury Systems", "PLTR": "Palantir",
    "AVAV": "AeroVironment", "RCAT": "Red Cat", "UMAC": "Unusual Machines", "HWM": "Howmet",
    "IRDM": "Iridium", "RKLB": "Rocket Lab", "ASTS": "AST SpaceMobile", "LUNR": "Intuitive Machines",
    "RDW": "Redwire", "PL": "Planet Labs", "FLY": "Firefly Aerospace",
    "ROK": "Rockwell", "EMR": "Emerson", "PH": "Parker Hannifin", "APH": "Amphenol",
    "ZBRA": "Zebra", "CGNX": "Cognex", "NOVT": "Novanta", "LSCC": "Lattice", "AMBA": "Ambarella",
    "MBLY": "Mobileye", "SYM": "Symbotic", "AUR": "Aurora", "OUST": "Ouster", "AEVA": "Aeva",
    "INDI": "indie Semi", "KLIC": "Kulicke & Soffa", "TSLA": "Tesla", "XPEV": "XPeng (ADR)",
    "SERV": "Serve Robotics", "RR": "Richtech Robotics", "ARBE": "Arbe Robotics",
    "KITT": "Nauticus", "ALNT": "Allient", "VPG": "Vishay Precision", "ATOM": "Atomera",
    "MRAM": "Everspin", "BOT": "RoboStrategy", "AMBQ": "Ambiq Micro",
    "FCX": "Freeport", "SCCO": "Southern Copper", "NEM": "Newmont", "TECK": "Teck", "HBM": "Hudbay",
    "MP": "MP Materials", "ALB": "Albemarle", "NUE": "Nucor", "STLD": "Steel Dynamics",
    "CLF": "Cleveland-Cliffs", "FMC": "FMC", "USAR": "USA Rare Earth",
}

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
    # theme baskets (equal-weight, daily-rebalanced single-stock indices)
    {"id": "gpu", "label": "GPU (basket)"}, {"id": "cpuasic", "label": "CPU+ASIC (basket)"},
    {"id": "aiinference", "label": "AI Inference (basket)"},
    {"id": "memory", "label": "Memory (basket)"}, {"id": "semicap", "label": "Semicap (basket)"},
    {"id": "powersemi", "label": "Power Semis (basket)"}, {"id": "photonics", "label": "Photonics (basket)"},
    {"id": "connectivity", "label": "Connectivity (basket)"}, {"id": "networking", "label": "Networking (basket)"},
    {"id": "aiserver", "label": "AI Servers (basket)"}, {"id": "hyperscale", "label": "Hyperscalers (basket)"},
    {"id": "neocloud", "label": "Neocloud (basket)"}, {"id": "cdnedge", "label": "CDN/Edge (basket)"},
    {"id": "software", "label": "Software (basket)"}, {"id": "cyber", "label": "Cybersecurity (basket)"},
    {"id": "elecind", "label": "Electric Industrial (basket)"}, {"id": "epc", "label": "EPC (basket)"},
    {"id": "nuclear", "label": "Nuclear (basket)"},
    {"id": "solutil", "label": "Industrial Solar (basket)"}, {"id": "solresi", "label": "Residential Solar (basket)"},
    {"id": "defense", "label": "Defense & Aero (basket)"}, {"id": "space", "label": "Space (basket)"},
    {"id": "robotics", "label": "Robotics (basket)"},
    {"id": "miners", "label": "Metals—Miners (basket)"}, {"id": "materials", "label": "Materials (basket)"},
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
    # previous-session gates
    {"id": "prev_dn", "label": "Subject was down the previous day", "when": "{subj}_ret_prev<0"},
    {"id": "prev_up", "label": "Subject was up the previous day", "when": "{subj}_ret_prev>0"},
    {"id": "prev_dn1", "label": "Subject fell ≥1% the previous day", "when": "{subj}_ret_prev<=-0.01"},
    {"id": "prev_dn2", "label": "Subject fell ≥2% the previous day", "when": "{subj}_ret_prev<=-0.02"},
    {"id": "prev_up1", "label": "Subject rose ≥1% the previous day", "when": "{subj}_ret_prev>=0.01"},
    {"id": "spy_prev_dn1", "label": "SPY fell ≥1% the previous day", "when": "spy_ret_prev<=-0.01"},
    {"id": "spy_prev_dn2", "label": "SPY fell ≥2% the previous day", "when": "spy_ret_prev<=-0.02"},
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
    "Theme baskets": ["gpu", "cpuasic", "aiinference", "memory", "semicap", "powersemi",
                      "photonics", "connectivity", "networking", "aiserver", "hyperscale",
                      "neocloud", "cdnedge", "software", "cyber", "elecind", "epc", "nuclear",
                      "solutil", "solresi", "defense", "space", "robotics", "miners", "materials"],
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
               else c.pct_change() if k == "ret"
               else c.pct_change().shift(1) if k == "rprev"
               else c.rolling(int(k), min_periods=1).mean())
           for n, k in specs.items()}
    return pd.DataFrame(out)


def _pack_series(dates_idx, closes):
    """Compact daily series for client-side row computation: epoch-day deltas +
    closes ×10,000 as ints. Decoded in market-lab.js (decodeSeries).
    Unit-agnostic date math — DuckDB hands pandas datetime64[us], so raw asi8
    division by a nanosecond constant silently corrupts the day numbers."""
    days = ((dates_idx - pd.Timestamp("1970-01-01")) // pd.Timedelta("1D")).astype("int64").to_numpy()
    return {"d0": int(days[0]), "dd": [int(x) for x in np.diff(days)],
            "c": [int(round(v * 10000)) for v in closes]}


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
        _feats(conn, "spy",    {"spy_ret_prev": "rprev"}),
    ], axis=1, sort=False).sort_index()
    hz = {h["h"]: h["id"] for h in HORIZONS}

    results, series_by, kept, total = {}, {}, 0, 0
    for s in SUBJECTS:
        c = conn.execute(f'select date, close from "{s["id"]}" order by date').df()
        c["date"] = pd.to_datetime(c["date"])
        close = c.set_index("date")["close"]
        series_by[s["id"]] = _pack_series(close.index, close.to_numpy())
        ret = close.pct_change().to_numpy()
        retfin = np.isfinite(ret)
        isodow = np.asarray(close.index.dayofweek) + 1
        out_h = {h: (close.shift(-h) / close - 1).to_numpy() for h in hz}

        F = G.reindex(close.index)
        F["SUBJ"] = close.to_numpy()
        F["SUBJ_200dma"] = close.rolling(200, min_periods=1).mean().to_numpy()
        F["SUBJ_ret_prev"] = close.pct_change().shift(1).to_numpy()
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
    return results, series_by, kept, total


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    cube_dir = out_dir / "cube"
    cube_dir.mkdir(parents=True, exist_ok=True)
    conn = db.connect()
    as_of = conn.execute("select max(date) from spy").fetchone()[0]
    results, series_by, kept, total = build(conn)

    # Shard per subject: index.js carries meta+menus (~15KB, instant load); each
    # subject's results load on demand via <script> injection (works on file://).
    index = {
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
            "bin_labels": BIN_LABELS, "bin_edges": EDGES,
        },
    }
    (cube_dir / "index.js").write_text(
        "window.QUANT_LAB = " + json.dumps(index, separators=(",", ":"))
        + ";\nwindow.QUANT_LAB.shards = {};\nwindow.QUANT_LAB.series = {};\n")

    by_subj = {s["id"]: {} for s in SUBJECTS}
    for key, row in results.items():
        subj, rest = key.split("|", 1)
        by_subj[subj][rest] = row
    written = set()
    for subj, rows in by_subj.items():
        (cube_dir / f"{subj}.js").write_text(
            f"window.QUANT_LAB.shards[{json.dumps(subj)}] = "
            + json.dumps(rows, separators=(",", ":")) + ";\n"
            + f"window.QUANT_LAB.series[{json.dumps(subj)}] = "
            + json.dumps(series_by[subj], separators=(",", ":")) + ";\n")
        written.add(f"{subj}.js")

    # raw closes of the 8 conditioner source series — lets the page evaluate
    # when= gates client-side for the offline occurrence list
    cond = {}
    for v in ["vix", "vix3m", "gold", "copper", "tnx", "hyg", "uup", "wti", "spy"]:
        d = conn.execute(f'select date, close from "{v}" order by date').df()
        d["date"] = pd.to_datetime(d["date"])
        cs = d.set_index("date")["close"]
        cond[v] = _pack_series(cs.index, cs.to_numpy())
    (cube_dir / "conditioners.js").write_text(
        "window.QUANT_LAB.cond = " + json.dumps(cond, separators=(",", ":")) + ";\n")
    # prune shards for subjects that left the menu + the legacy monolith
    for f in cube_dir.glob("*.js"):
        if f.name not in written and f.name not in ("index.js", "baskets.js", "drawdowns.js", "conditioners.js"):
            f.unlink()
    legacy = out_dir / "trader-profile-cube.js"
    if legacy.exists():
        legacy.unlink()
        print(f"removed legacy {legacy.name}")

    # Basket composition data for market-lab-baskets.html — straight from the
    # parquets so it stays correct after every refresh / constituent change.
    label_of = {s["id"]: s["label"].replace(" (basket)", "") for s in SUBJECTS}
    bdata = []
    for bid, tickers in BASKETS.items():
        members = []
        for t in tickers:
            v = t.lower().replace("-", "_")
            r = conn.execute(f'''select min(date), last(close order by date),
                last(close order by date) / last(lag_c order by date) - 1
                from (select date, close, lag(close) over (order by date) lag_c from "{v}")''').fetchone()
            members.append({"t": t, "name": MEMBER_NAMES.get(t, t), "from": str(r[0]),
                            "last": round(float(r[1]), 2), "ret1": round(float(r[2]) * 100, 2)})
        members.sort(key=lambda m: m["from"])
        bdata.append({"id": bid, "label": label_of.get(bid, bid), "n": len(members),
                      "inception": members[0]["from"], "members": members})
    (cube_dir / "baskets.js").write_text(
        "window.QUANT_BASKETS = " + json.dumps({"as_of": str(as_of), "baskets": bdata},
                                               separators=(",", ":")) + ";\n")

    # Drawdown-from-ATH episodes + daily underwater series for market-lab-drawdowns.html.
    # Episode = decline from the running all-time high until a NEW high; depth = max
    # close-based drawdown within it. Episodes <3% deep are omitted.
    dd_idx = []
    for vid, lbl in [("gspc", "S&P 500"), ("ixic", "Nasdaq Composite"), ("ndx", "Nasdaq-100")]:
        d = conn.execute(f"select date, close from {vid} order by date").df()
        d["date"] = pd.to_datetime(d["date"])
        c = d.close.to_numpy()
        dt = d.date
        dd = c / np.maximum.accumulate(c) - 1
        eps = []
        i, N = 1, len(c)
        while i < N:
            if dd[i] < 0:
                j = i
                while j < N and dd[j] < 0:
                    j += 1
                k = i + int(np.argmin(dd[i:j]))
                depth = -float(dd[i:j].min()) * 100
                if depth >= 3:
                    eps.append({"depth": round(depth, 1), "peak": str(dt[i - 1].date()),
                                "trough": str(dt[k].date()), "p2t": int((dt[k] - dt[i - 1]).days),
                                "rec": int((dt[j] - dt[k]).days) if j < N else None})
                i = j
            else:
                i += 1
        dd_idx.append({"id": vid, "label": lbl,
                       "years": round((dt.iloc[-1] - dt.iloc[0]).days / 365.25, 1),
                       "start": str(dt.iloc[0].date()), "end": str(dt.iloc[-1].date()),
                       "episodes": eps,
                       "daily": {"dates": [str(x.date()) for x in dt],
                                 "dd": [round(float(v) * 100, 1) for v in dd]}})
    (cube_dir / "drawdowns.js").write_text(
        "window.QUANT_DRAWDOWNS = " + json.dumps({"as_of": str(as_of), "indexes": dd_idx},
                                                 separators=(",", ":")) + ";\n")
    total_bytes = sum(f.stat().st_size for f in cube_dir.glob("*.js"))
    print(f"\nWrote {cube_dir}/index.js + {len(written)} shards "
          f"({total_bytes:,} bytes total)  kept {kept}/{total} combos")


if __name__ == "__main__":
    main()
