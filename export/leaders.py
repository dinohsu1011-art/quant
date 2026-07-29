"""Ship one row per single stock — returns over every standard window, plus the
labels needed to ask which *groups* those returns belong to.

This is the screen behind "Datadog is the only software name in the top 10".
Answering that needs three things at once: a ranking of individual stocks, a
sector label on each, and the repo's own theme tags. The themes page has the
tags and the sector ETFs but charts composites; the weekend page measures
breadth but never names anybody. Neither can rank 500 stocks and then tell you
what the leaders have in common.

Windows are precomputed rather than shipped as full price history: 628 names of
daily closes is ~50 MB, the same thing as a fixed set of horizons is ~200 KB,
and a screen is read at standard horizons anyway.

Everything is measured to the last close in the file. Names whose history is
shorter than a window get null for that window rather than a return off a
partial series — a stock that listed in March has no 1-year number, and showing
one computed from its first day would put it at the top of every ranking.

    python -m export.leaders [/some/dir]
"""
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from analysis.universe import load_prices, scan_universe
from ingestion.baskets import BASKETS
from ingestion.recos import LEDGER, reco_tickers
from ingestion.tickers import load_ticker_meta
from config import file_stem

DEFAULT_OUT = Path.home() / "Desktop/Obsidian/trading-brain/reports"

# label -> sessions back. 'ytd' is resolved against the calendar.
WINDOWS = [("1D", 1), ("1W", 5), ("1M", 21), ("3M", 63), ("6M", 126),
           ("YTD", "ytd"), ("1Y", 252), ("3Y", 756), ("5Y", 1260)]

# Books, not themes. A reco book is a decision record; tagging its names as a
# "theme" would put them beside GPU and Software as if they described what a
# company does.
BOOK_TAGS = {f"{k}" for k in LEDGER} | {"mycoverage", "coverage1",
                                        "fredcoverage", "fredcoverage1"}
THEME_LABEL = {
    "gpu": "GPU", "cpuasic": "CPU/ASIC", "memory": "Memory", "semicap": "Semicap",
    "powersemi": "Power semis", "photonics": "Photonics",
    "connectivity": "Connectivity", "networking": "Networking",
    "aiserver": "AI servers", "hyperscale": "Hyperscalers", "neocloud": "Neocloud",
    "cdnedge": "CDN/Edge", "software": "Software", "cyber": "Cybersecurity",
    "elecind": "Electrical industrials", "epc": "EPC", "nuclear": "Nuclear",
    "solutil": "Solar utility", "solresi": "Solar residential",
    "utilities": "Utilities", "defense": "Defense", "space": "Space",
    "robotics": "Robotics", "miners": "Miners", "materials": "Materials",
    "gas": "Gas power", "japan": "Japan",
}


def theme_tags():
    """stem -> [theme id, ...]. A name can sit in several; DELL is an AI server
    and a memory-adjacent box, and the screen should show both."""
    out = {}
    for bid, members in BASKETS.items():
        if bid in BOOK_TAGS or bid not in THEME_LABEL:
            continue
        for t in members:
            out.setdefault(file_stem(t), []).append(bid)
    return out


def _ret(c, k):
    """Return over k sessions, or None when the series is too short."""
    if len(c) <= k:
        return None
    a, b = c[-1 - k], c[-1]
    if not np.isfinite(a) or not np.isfinite(b) or a <= 0:
        return None
    return round((b / a - 1) * 100, 2)


def row(stem, df):
    c = df["close"].to_numpy(dtype=float)
    if len(c) < 30:
        return None
    dates = df.index
    r = {}
    for label, k in WINDOWS:
        if k == "ytd":
            # first session of the current year *in this stock's own history*
            yr = dates[-1].year
            pos = np.searchsorted(dates.values, np.datetime64(f"{yr}-01-01"))
            # the session before the year's first is the base; a stock that
            # listed this year has no prior close and so no YTD number
            r[label] = _ret(c, len(c) - pos) if 0 < pos < len(c) else None
        else:
            r[label] = _ret(c, k)

    hi52 = np.nanmax(c[-252:]) if len(c) >= 60 else np.nan
    lo52 = np.nanmin(c[-252:]) if len(c) >= 60 else np.nan
    ma50 = np.nanmean(c[-50:]) if len(c) >= 50 else np.nan
    ma200 = np.nanmean(c[-200:]) if len(c) >= 200 else np.nan
    d = np.diff(np.log(np.where(c > 0, c, np.nan)))
    vol = np.nanstd(d[-126:]) * np.sqrt(252) * 100 if len(d) >= 60 else np.nan

    v = df["volume"].to_numpy(dtype=float) if "volume" in df else None
    dollar = np.nanmean((c[-63:] * v[-63:])) / 1e6 if v is not None and len(c) >= 63 else np.nan
    rvol = (v[-1] / np.nanmean(v[-50:])) if v is not None and len(v) >= 50 and np.nanmean(v[-50:]) > 0 else np.nan

    def num(x, nd=1):
        return None if x is None or not np.isfinite(x) else round(float(x), nd)

    return {
        "t": stem,
        "px": num(c[-1], 2),
        "r": r,
        "off52": num((c[-1] / hi52 - 1) * 100 if np.isfinite(hi52) else np.nan),
        "up52": num((c[-1] / lo52 - 1) * 100 if np.isfinite(lo52) else np.nan),
        "ma50": num((c[-1] / ma50 - 1) * 100 if np.isfinite(ma50) else np.nan),
        "ma200": num((c[-1] / ma200 - 1) * 100 if np.isfinite(ma200) else np.nan),
        "vol": num(vol),
        "adv": num(dollar),
        "rvol": num(rvol, 2),
    }


def build():
    stems = scan_universe()
    px = load_prices(stems, columns=("close", "volume"))
    meta = load_ticker_meta()
    # meta is keyed by the raw ticker (BRK-B); the price files by stem
    meta.index = [file_stem(t) for t in meta.index]
    sp = set(meta.index)
    tags = theme_tags()
    reco = {file_stem(t) for t in reco_tickers()}

    rows, as_of = [], None
    for stem in stems:
        df = px.get(stem)
        if df is None or not len(df):
            continue
        r = row(stem, df)
        if r is None:
            continue
        m = meta.loc[stem] if stem in meta.index else None
        r["n"] = (m["name"] if m is not None else "") or stem
        r["s"] = (m["sector"] if m is not None else "") or "—"
        r["i"] = (m["industry"] if m is not None else "") or ""
        r["sp"] = stem in sp
        r["rc"] = stem in reco
        r["th"] = tags.get(stem, [])
        r["last"] = df.index[-1].strftime("%Y-%m-%d")
        rows.append(r)

    # The most common last bar, not the newest: Tokyo names close a calendar day
    # ahead of New York, so the max would mark every US stock a day behind.
    as_of = Counter(r["last"] for r in rows).most_common(1)[0][0]
    cut = (pd.Timestamp(as_of) - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    # A name whose last bar is well behind the tape is a feed gap, not a flat
    # stock. Flagged rather than dropped so it can be seen and excluded.
    for r in rows:
        r["stale"] = r["last"] < cut

    return {
        "meta": {
            "as_of": as_of,
            "n": len(rows),
            "n_sp500": sum(r["sp"] for r in rows),
            "n_stale": sum(r["stale"] for r in rows),
            "windows": [w for w, _ in WINDOWS],
            "themes": THEME_LABEL,
            "sectors": sorted({r["s"] for r in rows if r["s"] != "—"}),
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
        "rows": rows,
    }


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    (out_dir / "cube").mkdir(parents=True, exist_ok=True)
    p = build()
    js = "window.QUANT_LEADERS = " + json.dumps(p, separators=(",", ":")) + ";\n"
    out = out_dir / "cube" / "leaders.js"
    out.write_text(js)
    m = p["meta"]
    print(f"wrote {out}  ({len(js)/1e6:.2f} MB)")
    print(f"  {m['n']} names ({m['n_sp500']} S&P 500), as of {m['as_of']}"
          + (f", {m['n_stale']} stale" if m["n_stale"] else ""))


if __name__ == "__main__":
    main()
