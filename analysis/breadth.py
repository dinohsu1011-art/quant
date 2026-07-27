"""Market breadth: how much of the market is participating, through time.

Every measure is a fraction of the names that HAD data on that date, not of the
universe's current size, so the series doesn't step whenever a name lists or the
membership snapshot changes.

One caveat the numbers cannot fix: `data/tickers.csv` is today's S&P membership,
so the historical breadth series is survivorship-biased — it reads the past
through the names that made it to today. Fine for "is the tape broad right now",
wrong for backtesting a breadth threshold.

    python -m analysis.breadth
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from analysis.universe import load_prices, sp500_members, us_calendar

MA_WINDOWS = (20, 50, 200)
HIGH_LOW_WINDOW = 252


def breadth_series(px, calendar, members=None):
    """DataFrame indexed by date: pct_above_20/50/200, new_highs, new_lows, n."""
    names = list(members) if members is not None else list(px)
    idx = calendar
    above = {w: pd.Series(0.0, index=idx) for w in MA_WINDOWS}
    cover = {w: pd.Series(0.0, index=idx) for w in MA_WINDOWS}
    hi = pd.Series(0.0, index=idx)
    lo = pd.Series(0.0, index=idx)
    cov = pd.Series(0.0, index=idx)

    for s in names:
        d = px.get(s)
        if d is None or len(d) < 30:
            continue
        c = d["close"].astype("float64")
        for w in MA_WINDOWS:
            ma = c.rolling(w, min_periods=w).mean()
            ok = (c > ma).reindex(idx)
            have = ma.notna().reindex(idx, fill_value=False)
            above[w] = above[w].add(ok.fillna(False).astype(float), fill_value=0)
            cover[w] = cover[w].add(have.astype(float), fill_value=0)
        rmax = c.rolling(HIGH_LOW_WINDOW, min_periods=HIGH_LOW_WINDOW).max()
        rmin = c.rolling(HIGH_LOW_WINDOW, min_periods=HIGH_LOW_WINDOW).min()
        hi = hi.add((c >= rmax).reindex(idx).fillna(False).astype(float), fill_value=0)
        lo = lo.add((c <= rmin).reindex(idx).fillna(False).astype(float), fill_value=0)
        cov = cov.add(rmax.notna().reindex(idx, fill_value=False).astype(float), fill_value=0)

    out = pd.DataFrame(index=idx)
    for w in MA_WINDOWS:
        out[f"pct_above_{w}"] = 100 * above[w] / cover[w].replace(0, np.nan)
    out["new_highs"] = hi
    out["new_lows"] = lo
    out["net_highs"] = hi - lo
    out["n"] = cov
    return out


def percentile_of_last(s, lookback=None):
    """Where the latest value sits in its own history, 0-100."""
    x = s.dropna()
    if lookback:
        x = x.iloc[-lookback:]
    if len(x) < 30:
        return None
    return float(100 * (x < x.iloc[-1]).mean())


def index_panel(conn_px, ids):
    """Per-index return/position table. `conn_px` is {stem: DataFrame}."""
    rows = []
    for sid, label in ids:
        d = conn_px.get(sid)
        if d is None or len(d) < 260:
            continue
        c = d["close"].astype("float64")
        ytd_base = c[c.index < f"{c.index[-1].year}-01-01"]
        rows.append({
            "id": sid, "label": label, "last": float(c.iloc[-1]),
            "r1w": float(c.iloc[-1] / c.iloc[-6] - 1),
            "r1m": float(c.iloc[-1] / c.iloc[-22] - 1),
            "r3m": float(c.iloc[-1] / c.iloc[-64] - 1),
            "ytd": float(c.iloc[-1] / ytd_base.iloc[-1] - 1) if len(ytd_base) else None,
            "off_high": float(c.iloc[-1] / c.iloc[-HIGH_LOW_WINDOW:].max() - 1),
            "vs_ma50": float(c.iloc[-1] / c.iloc[-50:].mean() - 1),
            "vs_ma200": float(c.iloc[-1] / c.iloc[-200:].mean() - 1),
        })
    return rows


def ratio_series(px, num, den, sessions=126):
    """A rebased ratio line plus its 1M/3M change — 'is it small caps or mega caps'."""
    a, b = px.get(num), px.get(den)
    if a is None or b is None:
        return None
    r = (a["close"] / b["close"]).dropna()
    if len(r) < 70:
        return None
    tail = r.iloc[-sessions:]
    return {
        "r1m": float(r.iloc[-1] / r.iloc[-22] - 1),
        "r3m": float(r.iloc[-1] / r.iloc[-64] - 1),
        "spark": [round(100 * v / tail.iloc[0], 2) for v in tail],
    }


def main():
    px = load_prices()
    cal, _ = us_calendar(px)
    b = breadth_series(px, cal, members=sp500_members())
    last = b.iloc[-1]
    print(f"breadth as of {b.index[-1].date()}  (n={int(last['n'])} S&P names)")
    for w in MA_WINDOWS:
        col = f"pct_above_{w}"
        print(f"  above {w:>3}dma: {last[col]:5.1f}%   "
              f"{percentile_of_last(b[col], 1260):.0f}th pct of the last 5y")
    print(f"  52w highs {int(last['new_highs'])}  lows {int(last['new_lows'])}  "
          f"net {int(last['net_highs']):+d}")


if __name__ == "__main__":
    main()
