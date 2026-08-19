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

Returns ship twice, on price (`r`) and total-return (`rt`) bases, so the site's
shared dividend toggle can switch them without a second fetch. Everything else
here — 52-week extremes, moving-average distance, volatility, liquidity — is a
statement about the share price and stays on price in both modes.

Everything is measured to the last close in the file. Names whose history is
shorter than a window get null for that window rather than a return off a
partial series — a stock that listed in March has no 1-year number, and showing
one computed from its first day would put it at the top of every ranking.

    python -m export.leaders [/some/dir]
"""
import json
import re
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
from ingestion.meta import load_meta
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
    "biotech": "Biotechnology",
    "elecind": "Electrical industrials", "epc": "EPC", "nuclear": "Nuclear",
    "solutil": "Solar utility", "solresi": "Solar residential",
    "utilities": "Utilities", "defense": "Defense", "space": "Space",
    "robotics": "Robotics", "miners": "Miners", "materials": "Materials",
    "gas": "Gas power", "japan": "Japan",
}


# Yahoo returns the full legal name; the screen has one column for it. Only the
# corporate-form tail is trimmed — nothing that distinguishes two companies.
_TAIL = re.compile(
    r"[\s,]*\b(?:the\s+)?(?:inc|inc\.|incorporated|corp|corp\.|corporation|co|co\.|"
    r"company|companies|ltd|ltd\.|limited|plc|llc|lp|nv|n\.v\.|sa|s\.a\.|ag|se|oyj|"
    r"abp|holding|holdings|group|kk|k\.k\.)\.?$", re.I)


def tidy(name: str) -> str:
    prev = None
    while name and name != prev:
        prev = name
        name = _TAIL.sub("", name).strip(" ,.")
    return name or prev or ""


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


def _sigma(c, k, current):
    """Magnitude of the current k-session move versus like-for-like history.

    Use every rolling k-session move ending before the latest close. This mirrors
    Theme Returns' move-context convention: sigma describes unusualness, while
    the return itself preserves direction.

    The comparison used to stop at the prior three years, on the argument that a
    stock's normal range drifts. It does, but 756 samples cannot resolve anything
    rarer than 1 in 756, so every move worth asking about came back "0 in 756".
    A long sample muddies the yardstick; a short one is silent on the tails.

    Returns (sigma, exceedances, n): how many of those n historical moves were
    at least this far from the mean, alongside the sigma itself. A sigma is only
    a probability if returns are normal, and they are not — the tails are the
    part that matters and the part the normal curve gets most wrong. So the
    count ships too, and the page can quote what actually happened next to what
    the bell curve claims.
    """
    if current is None or len(c) <= k + 4:
        return None, None, None
    end = np.arange(k, len(c) - 1)
    base = c[end - k]
    finish = c[end]
    sample = finish / base - 1
    sample = sample[np.isfinite(sample) & np.isfinite(base) & (base > 0)]
    if len(sample) < 4:
        return None, None, None
    sd = np.std(sample, ddof=1)
    if not np.isfinite(sd) or sd <= 0:
        return None, None, None
    mean = np.mean(sample)
    dev = abs((current / 100) - mean)
    hits = int(np.sum(np.abs(sample - mean) >= dev))
    return round(dev / sd, 2), hits, int(len(sample))


def _seasonality(dates, c):
    """Average calendar-month return, Jan..Dec, with the sample count per month.

    Month-end to month-end over the whole history, so the first partial month is
    dropped rather than counted as a short month. The count travels with the
    average because a 3-year listing gives three Marches, and three of anything
    is a story, not a tendency.

    Each month's sample is winsorized at the 10th/90th percentile before the mean
    is taken. Not for smoothing — for survival. Yahoo's split-adjusted history has
    genuine breaks in it (NVR shows +2600% in October 1993, a reorganisation the
    adjustment never applied), and one bar like that puts a name at the top of a
    36-year ranking on a number that never happened. Clipping the tails to their
    own 10/90 keeps every observation in the sample while denying any single one
    the power to set the answer.
    """
    s = pd.Series(c, index=dates)
    m = s.resample("ME").last().dropna()
    r = m.pct_change(fill_method=None).dropna()
    if len(r) < 12:
        return None
    out = []
    for mo in range(1, 13):
        x = r[r.index.month == mo].to_numpy(dtype=float)
        if not len(x):
            out.append(None)
            continue
        lo, hi = np.percentile(x, [10, 90])
        out.append([round(float(np.clip(x, lo, hi).mean()) * 100, 2), int(len(x))])
    return out


def _windows(c, dates):
    """Returns, sigmas and exceedance counts over every standard horizon."""
    r, z, zx = {}, {}, {}
    for label, k in WINDOWS:
        if k == "ytd":
            # first session of the current year *in this stock's own history*
            yr = dates[-1].year
            pos = np.searchsorted(dates.values, np.datetime64(f"{yr}-01-01"))
            # the session before the year's first is the base; a stock that
            # listed this year has no prior close and so no YTD number
            sessions = len(c) - pos
            r[label] = _ret(c, sessions) if 0 < pos < len(c) else None
            k = sessions
        else:
            r[label] = _ret(c, k)
        sg, hits, n = _sigma(c, k, r[label])
        z[label] = sg
        if sg is not None:
            zx[label] = [hits, n]
    return r, z, zx


def row(stem, df):
    c = df["close"].to_numpy(dtype=float)
    if len(c) < 30:
        return None
    dates = df.index
    r, z, zx = _windows(c, dates)

    # Returns get a second, dividend-reinvested copy so the site-wide basis
    # toggle has something to switch to. Only the return block is doubled: the
    # 52-week extremes, moving averages, volatility and liquidity below describe
    # where the *share price* is trading, and stay on price in both modes.
    # A name that never paid emits identical numbers, so ship nothing for it.
    rt = zt = zxt = None
    if "adj_close" in df:
        a = df["adj_close"].to_numpy(dtype=float)
        if len(a) == len(c) and np.isfinite(a).any() and not np.allclose(
            a / a[-1], c / c[-1], rtol=1e-9, atol=0, equal_nan=True
        ):
            rt, zt, zxt = _windows(a, dates)

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

    out = {
        "t": stem,
        "px": num(c[-1], 2),
        "r": r,
        "z": z,
        "zx": zx,
        "m": _seasonality(dates, c),
        "off52": num((c[-1] / hi52 - 1) * 100 if np.isfinite(hi52) else np.nan),
        "up52": num((c[-1] / lo52 - 1) * 100 if np.isfinite(lo52) else np.nan),
        "ma50": num((c[-1] / ma50 - 1) * 100 if np.isfinite(ma50) else np.nan),
        "ma200": num((c[-1] / ma200 - 1) * 100 if np.isfinite(ma200) else np.nan),
        "vol": num(vol),
        "adv": num(dollar),
        "rvol": num(rvol, 2),
    }
    if rt is not None:
        out["rt"], out["zt"], out["zxt"] = rt, zt, zxt
    return out


def build():
    stems = scan_universe()
    px = load_prices(stems, columns=("close", "adj_close", "volume"))
    # every tracked name gets a label, not just the index members — an unlabelled
    # stock still takes a slot in the cohort, so it has to be countable
    meta = load_meta()
    sp = {file_stem(t) for t in load_ticker_meta().index}
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
        r["n"] = tidy(m["name"] if m is not None else "") or stem
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
